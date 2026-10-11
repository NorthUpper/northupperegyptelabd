-- North Upper Egypt Branch Portal — V17 backend foundation
-- Apply in a NEW Supabase project after reviewing with the responsible IT/security team.
-- This is a starting migration, not a claim that a live backend is connected.

create extension if not exists pgcrypto;

create table if not exists public.employees (
  id uuid primary key references auth.users(id) on delete cascade,
  employee_code text not null unique,
  full_name text not null,
  job_title text,
  department text,
  role text not null default 'employee'
    check (role in ('employee','direct_manager','hr','branch_manager','it')),
  manager_id uuid references public.employees(id) on delete set null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.leave_balances (
  id uuid primary key default gen_random_uuid(),
  employee_id uuid not null references public.employees(id) on delete cascade,
  leave_type text not null,
  entitled_days numeric(7,2) not null default 0 check (entitled_days >= 0),
  used_days numeric(7,2) not null default 0 check (used_days >= 0),
  updated_at timestamptz not null default now(),
  unique(employee_id, leave_type),
  check (used_days <= entitled_days)
);

create table if not exists public.leave_requests (
  id uuid primary key default gen_random_uuid(),
  request_no bigint generated always as identity unique,
  employee_id uuid not null references public.employees(id) on delete restrict,
  leave_type text not null check (leave_type in ('الإجازة الاعتيادية','الإجازة العارضة','الإجازة المرضية','إجازة الوضع','إجازات أخرى')),
  start_date date not null,
  end_date date not null,
  requested_calendar_days integer generated always as ((end_date - start_date) + 1) stored,
  notes text,
  status text not null default 'manager_pending'
    check (status in ('manager_pending','hr_pending','approved','rejected')),
  submitted_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  final_decision_at timestamptz,
  final_decision_by uuid references public.employees(id),
  check (end_date >= start_date),
  check (notes is null or length(notes) <= 2000)
);

create table if not exists public.leave_request_events (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.leave_requests(id) on delete cascade,
  actor_id uuid not null references public.employees(id) on delete restrict,
  action text not null check (action in ('submitted','manager_approved','hr_approved','rejected')),
  note text,
  created_at timestamptz not null default now()
);

create index if not exists idx_employees_manager_id on public.employees(manager_id);
create index if not exists idx_leave_requests_employee_submitted on public.leave_requests(employee_id, submitted_at desc);
create index if not exists idx_leave_requests_status on public.leave_requests(status);
create index if not exists idx_leave_events_request on public.leave_request_events(request_id, created_at);

create or replace function public.portal_role()
returns text
language sql stable security definer
set search_path = public, pg_temp
as $$
  select e.role from public.employees e
  where e.id = auth.uid() and e.is_active = true
  limit 1;
$$;

create or replace function public.is_direct_manager_of(target_employee uuid)
returns boolean
language sql stable security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.employees e
    where e.id = target_employee and e.manager_id = auth.uid() and e.is_active = true
  );
$$;

alter table public.employees enable row level security;
alter table public.leave_balances enable row level security;
alter table public.leave_requests enable row level security;
alter table public.leave_request_events enable row level security;

-- Employee profile: self, HR/branch manager, or direct manager of the employee.
drop policy if exists employees_select_scoped on public.employees;
create policy employees_select_scoped on public.employees
for select to authenticated
using (
  id = auth.uid()
  or public.portal_role() in ('hr','branch_manager')
  or manager_id = auth.uid()
);

-- Employee/role provisioning and edits are intentionally not granted to browser sessions in this first migration.
-- Add narrowly scoped server-side workflows after the branch approves who may change which fields.

-- Balances are private to the employee and HR; managers do not automatically see balances.
drop policy if exists leave_balances_select_self_hr on public.leave_balances;
create policy leave_balances_select_self_hr on public.leave_balances
for select to authenticated
using (employee_id = auth.uid() or public.portal_role() = 'hr');

-- Request visibility: employee, assigned direct manager for the pending stage, or HR.
drop policy if exists leave_requests_select_scoped on public.leave_requests;
create policy leave_requests_select_scoped on public.leave_requests
for select to authenticated
using (
  employee_id = auth.uid()
  or public.portal_role() = 'hr'
  or (status = 'manager_pending' and public.is_direct_manager_of(employee_id))
  or (status = 'hr_pending' and public.portal_role() = 'branch_manager')
);

-- Employees may submit requests only for themselves and only into the initial state.
drop policy if exists leave_requests_insert_self on public.leave_requests;
create policy leave_requests_insert_self on public.leave_requests
for insert to authenticated
with check (
  employee_id = auth.uid()
  and status = 'manager_pending'
  and end_date >= start_date
);

-- Explicit minimum grants for browser sessions; RLS still applies to every row.
grant select on public.employees, public.leave_balances, public.leave_requests, public.leave_request_events to authenticated;
grant insert on public.leave_requests to authenticated;
revoke insert, update, delete on public.employees from authenticated;
revoke update, delete on public.leave_requests from authenticated;
revoke insert, update, delete on public.leave_request_events from authenticated;
revoke insert, update, delete on public.leave_balances from authenticated;

drop policy if exists leave_events_select_scoped on public.leave_request_events;
create policy leave_events_select_scoped on public.leave_request_events
for select to authenticated
using (
  exists (
    select 1 from public.leave_requests r
    where r.id = request_id and (
      r.employee_id = auth.uid()
      or public.portal_role() = 'hr'
      or (r.status = 'manager_pending' and public.is_direct_manager_of(r.employee_id))
      or (r.status = 'hr_pending' and public.portal_role() = 'branch_manager')
    )
  )
);

create or replace function public.log_leave_submission()
returns trigger
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.leave_request_events(request_id, actor_id, action, note)
  values (new.id, auth.uid(), 'submitted', nullif(trim(coalesce(new.notes,'')),''));
  return new;
end;
$$;

drop trigger if exists trg_log_leave_submission on public.leave_requests;
create trigger trg_log_leave_submission
after insert on public.leave_requests
for each row execute function public.log_leave_submission();

create or replace function public.decide_leave_request(
  p_request_id uuid,
  p_decision text,
  p_note text default null
)
returns public.leave_requests
language plpgsql security definer
set search_path = public, pg_temp
as $$
declare
  r public.leave_requests;
  actor_role text;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  if p_decision not in ('approve','reject') then raise exception 'Invalid decision'; end if;
  if p_decision = 'reject' and coalesce(trim(p_note),'') = '' then
    raise exception 'A rejection reason is required';
  end if;
  if length(coalesce(p_note,'')) > 2000 then raise exception 'Note is too long'; end if;

  actor_role := public.portal_role();
  select * into r from public.leave_requests where id = p_request_id for update;
  if not found then raise exception 'Request not found'; end if;

  if r.status = 'manager_pending' then
    if actor_role <> 'direct_manager' or not public.is_direct_manager_of(r.employee_id) then
      raise exception 'Not authorized for manager review';
    end if;
    if p_decision = 'reject' then
      update public.leave_requests set status='rejected', updated_at=now(), final_decision_at=now(), final_decision_by=auth.uid()
      where id=p_request_id returning * into r;
      insert into public.leave_request_events(request_id,actor_id,action,note)
      values(p_request_id,auth.uid(),'rejected',trim(p_note));
    else
      update public.leave_requests set status='hr_pending', updated_at=now()
      where id=p_request_id returning * into r;
      insert into public.leave_request_events(request_id,actor_id,action,note)
      values(p_request_id,auth.uid(),'manager_approved',nullif(trim(coalesce(p_note,'')),''));
    end if;
  elsif r.status = 'hr_pending' then
    if actor_role <> 'hr' then raise exception 'Not authorized for HR review'; end if;
    if p_decision = 'reject' then
      update public.leave_requests set status='rejected', updated_at=now(), final_decision_at=now(), final_decision_by=auth.uid()
      where id=p_request_id returning * into r;
      insert into public.leave_request_events(request_id,actor_id,action,note)
      values(p_request_id,auth.uid(),'rejected',trim(p_note));
    else
      -- Do not deduct balances here until the branch's official day-counting and leave rules are approved.
      update public.leave_requests set status='approved', updated_at=now(), final_decision_at=now(), final_decision_by=auth.uid()
      where id=p_request_id returning * into r;
      insert into public.leave_request_events(request_id,actor_id,action,note)
      values(p_request_id,auth.uid(),'hr_approved',nullif(trim(coalesce(p_note,'')),''));
    end if;
  else
    raise exception 'Request is not awaiting this approval stage';
  end if;
  return r;
end;
$$;

revoke all on function public.portal_role() from public;
revoke all on function public.is_direct_manager_of(uuid) from public;
revoke all on function public.log_leave_submission() from public;
revoke all on function public.decide_leave_request(uuid,text,text) from public;
grant execute on function public.portal_role() to authenticated;
grant execute on function public.is_direct_manager_of(uuid) to authenticated;
grant execute on function public.decide_leave_request(uuid,text,text) to authenticated;

-- IMPORTANT: create Auth users and matching employees rows through a trusted admin process.
-- Do not insert real employee passwords into this database or frontend code.
