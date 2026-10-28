from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from pathlib import Path
import sqlite3, json, os, hashlib, hmac, secrets, datetime

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get('NORTHUPPER_DB', ROOT / 'northupper_test.db'))
app = FastAPI(title='North Upper Egypt Branch Portal', version='0.1.0')
app.add_middleware(SessionMiddleware, secret_key=os.environ.get('NORTHUPPER_SESSION_SECRET', 'DEV-ONLY-change-this-secret-before-any-shared-deployment'), same_site='lax', https_only=False)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
app.mount('/assets', StaticFiles(directory=ROOT / 'assets'), name='assets')

MODULES = {
 'appointments': {'title':'طلبات المواعيد','roles':['branch_manager','planning','hr','finance','employee'],'sensitive':False},
 'drawings': {'title':'اللوحات الهندسية','roles':['branch_manager','planning','employee'],'sensitive':False},
 'tasks': {'title':'القرارات والتكليفات','roles':['branch_manager','planning','hr','warehouse','finance'],'sensitive':False},
 'projects': {'title':'المشروعات','roles':['branch_manager','planning','finance'],'sensitive':False},
 'warehouse': {'title':'المخازن','roles':['branch_manager','warehouse'],'sensitive':False},
 'assets': {'title':'الأصول والمركبات','roles':['branch_manager','warehouse','finance'],'sensitive':False},
 'workforce': {'title':'القوى العاملة','roles':['branch_manager','hr'],'sensitive':True},
 'medical': {'title':'المصروفات الطبية','roles':['hr','branch_manager'],'sensitive':True},
 'leave': {'title':'طلبات الإجازات','roles':['employee','direct_manager','hr','branch_manager'],'sensitive':False},
 'complaints': {'title':'الشكاوى والمقترحات','roles':['branch_manager','hr','planning'],'sensitive':False},
}
ROLE_LABELS={'branch_manager':'مدير الفرع','hr':'الموارد البشرية','it':'تقنية المعلومات','planning':'التخطيط والمتابعة','warehouse':'المخازن','finance':'الحسابات','direct_manager':'المدير المباشر','employee':'موظف'}
# Deliberately fake accounts for local testing only. Passwords are hashed with PBKDF2; no real employee data.
DEMO_USERS = [
 ('mgr.demo','مدير الفرع التجريبي','branch_manager','Demo-Mgr-2026'),
 ('hr.demo','مسؤول الموارد البشرية التجريبي','hr','Demo-HR-2026'),
 ('plan.demo','مسؤول التخطيط والمتابعة التجريبي','planning','Demo-Plan-2026'),
 ('store.demo','مسؤول المخازن التجريبي','warehouse','Demo-Store-2026'),
 ('fin.demo','مسؤول الحسابات التجريبي','finance','Demo-Fin-2026'),
 ('manager.demo','مدير مباشر تجريبي','direct_manager','Demo-Direct-2026'),
 ('employee.demo','موظف تجريبي','employee','Demo-Emp-2026'),
 ('it.demo','تقنية المعلومات التجريبية','it','Demo-IT-2026'),
]

def db():
 c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def pw_hash(password, salt=None):
 salt=salt or secrets.token_bytes(16)
 return salt.hex()+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt,220000).hex()
def pw_verify(password, stored):
 try:
  salt_hex,digest=stored.split(':',1); salt=bytes.fromhex(salt_hex); check=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,220000).hex(); return hmac.compare_digest(check,digest)
 except Exception: return False

def init_db():
 c=db(); c.executescript('''
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
 CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT NOT NULL, ref TEXT NOT NULL UNIQUE, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'جديد', owner TEXT DEFAULT '', due_date TEXT DEFAULT '', payload TEXT NOT NULL DEFAULT '{}', sensitivity TEXT NOT NULL DEFAULT 'normal', created_by TEXT NOT NULL, updated_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
 CREATE INDEX IF NOT EXISTS idx_records_module ON records(module,updated_at DESC);
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL, module TEXT NOT NULL, record_ref TEXT DEFAULT '', before_json TEXT DEFAULT '', after_json TEXT DEFAULT '', reason TEXT DEFAULT '', at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, read_at TEXT DEFAULT '', created_at TEXT NOT NULL);
 ''')
 for u in DEMO_USERS:
  c.execute('INSERT OR IGNORE INTO users(username,display_name,role,password_hash) VALUES(?,?,?,?)',(u[0],u[1],u[2],pw_hash(u[3])))
 if c.execute('SELECT COUNT(*) n FROM records').fetchone()['n']==0:
  now=dt(); samples=[
   ('appointments','APT-DEMO-001','طلب موعد مع التخطيط والمتابعة','قيد المراجعة','منسق المواعيد','2026-10-21',{'name':'أحمد محمود (وهمي)','phone':'01000000001','department':'التخطيط والمتابعة','proposed_date':'2026-10-21','note':'طلب استفسار عن موقف مشروع'},'normal'),
   ('appointments','APT-DEMO-002','طلب موعد مع مدير الفرع','مطلوب استيفاء','منسق المواعيد','2026-10-22',{'name':'منى إبراهيم (وهمي)','phone':'01000000002','department':'مدير الفرع','proposed_date':'2026-10-22','note':'يرجى استكمال سبب الاجتماع'},'normal'),
   ('drawings','DRW-TH-014','لوحة شبكة طهطا — خط طرد (تجريبي)','متأخرة','مهندس متابعة تجريبي','2026-10-18',{'project':'محطة مياه طهطا — مثال تجريبي','stage':'مرسلة للاستشاري','delay_cause':'انتظار رد جهة خارجية','impact':'يؤثر على نشاط','last_correspondence':'OUT-DEMO-014','next_action':'متابعة الرد وتحديث الأثر','governorate':'سوهاج'},'normal'),
   ('tasks','TASK-DEMO-001','مراجعة سبب تأخر لوحة تجريبية','قيد التنفيذ','مسؤول التخطيط التجريبي','2026-10-20',{'priority':'مرتفع','evidence_required':True,'evidence':'','decision_needed':'تحديد الإجراء التالي'},'normal'),
   ('projects','PRJ-DEMO-001','مشروع صرف صحي — مثال افتراضي','يحتاج تدخل','مسؤول المتابعة التجريبي','2026-10-25',{'governorate':'المنيا','progress':62,'budget_egp':12000000,'spent_egp':7900000,'source':'بيانات وهمية لا تستخدم رسميًا'},'normal'),
   ('warehouse','WH-DEMO-008','ماسورة HDPE — صنف تجريبي','رصيد منخفض','أمين مخزن تجريبي','2026-10-20',{'store':'مخزن تجريبي 1','balance':18,'reorder_level':25,'unit':'متر','last_movement':'MOV-DEMO-008'},'normal'),
   ('assets','AST-DEMO-003','سيارة مأمورية — مثال افتراضي','يحتاج مراجعة','مسؤول عهدة تجريبي','2026-10-23',{'type':'سيارة مؤجرة','odometer_start':12500,'odometer_end':12740,'expected_km':200,'deviation_km':40,'reason':'مطلوب مراجعة خط السير'},'normal'),
   ('workforce','WF-DEMO-001','ملخص قوى عاملة تجريبي','محدث','الموارد البشرية','2026-10-19',{'headcount':186,'monthly_payroll_egp':2840000,'source':'أرقام وهمية للاختبار فقط'},'salary'),
   ('medical','MED-DEMO-001','ملخص مصروفات علاجية تجريبي','قيد المراجعة','الموارد البشرية','2026-10-24',{'month':'2026-10','paid_egp':186400,'pending_cases':4,'diagnosis':None,'source':'أرقام وهمية للاختبار فقط'},'medical'),
   ('leave','LEV-DEMO-001','طلب إجازة اعتيادية — موظف تجريبي','بانتظار المدير المباشر','المدير المباشر التجريبي','2026-10-20',{'employee':'موظف تجريبي','leave_type':'اعتيادية','start_date':'2026-10-22','end_date':'2026-10-23','days':2,'manager_step':'pending','hr_step':'pending'},'normal'),
   ('complaints','CMP-DEMO-001','مقترح تحسين إجراء داخلي — تجريبي','جديد','مدير الفرع التجريبي','2026-10-26',{'category':'مقترح','details':'مثال اختبار فقط','source':'بيانات وهمية'},'normal')]
  for m,r,t,s,o,d,p,sens in samples:
   c.execute('INSERT INTO records(module,ref,title,status,owner,due_date,payload,sensitivity,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(m,r,t,s,o,d,json.dumps(p,ensure_ascii=False),sens,'system.demo','system.demo',now,now))
 c.commit(); c.close()
def dt(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
init_db()

def current_user(request: Request):
 username=request.session.get('username')
 if not username: return None
 c=db(); row=c.execute('SELECT username,display_name,role,active FROM users WHERE username=?',(username,)).fetchone(); c.close()
 return dict(row) if row and row['active'] else None

def require_user(request: Request):
 u=current_user(request)
 if not u: raise HTTPException(401,'يلزم تسجيل الدخول')
 return u

def can_access(user, module):
 if module not in MODULES: return False
 if user['role']=='it': return module == 'workforce' # IT may see the approved aggregate workforce/payroll summary only; no operational records or medical details
 if user['role'] in ('hr','branch_manager') and module=='medical': return True
 return user['role'] in MODULES[module]['roles']

def audit(c,user,action,module,ref='',before=None,after=None,reason=''):
 c.execute('INSERT INTO audit(actor,role,action,module,record_ref,before_json,after_json,reason,at) VALUES(?,?,?,?,?,?,?,?,?)',(user['username'],user['role'],action,module,ref,json.dumps(before,ensure_ascii=False) if before else '',json.dumps(after,ensure_ascii=False) if after else '',reason,dt()))

def record_dict(row):
 x=dict(row); x['payload']=json.loads(x['payload'] or '{}'); return x

@app.get('/', response_class=HTMLResponse)
def home(request: Request):
 u=current_user(request)
 if u: return RedirectResponse('/dashboard',status_code=303)
 return HTMLResponse((ROOT/'static'/'login.html').read_text(encoding='utf-8'))

@app.post('/login')
def login(request: Request, username: str=Form(...), password: str=Form(...)):
 c=db(); row=c.execute('SELECT * FROM users WHERE username=? AND active=1',(username.strip(),)).fetchone(); c.close()
 if not row or not pw_verify(password,row['password_hash']):
  return HTMLResponse((ROOT/'static'/'login.html').read_text(encoding='utf-8').replace('<!--ERROR-->','<div class="error">بيانات الدخول غير صحيحة.</div>'),status_code=401)
 request.session.clear(); request.session['username']=row['username']; request.session['issued_at']=dt()
 c=db(); audit(c,dict(username=row['username'],role=row['role']),'login','auth',reason='successful demo login'); c.commit(); c.close()
 return RedirectResponse('/dashboard',status_code=303)

@app.post('/logout')
def logout(request: Request):
 u=current_user(request)
 if u:
  c=db(); audit(c,u,'logout','auth'); c.commit(); c.close()
 request.session.clear(); return RedirectResponse('/',status_code=303)

@app.get('/dashboard',response_class=HTMLResponse)
def dashboard(request: Request):
 u=current_user(request)
 if not u: return RedirectResponse('/',status_code=303)
 return HTMLResponse((ROOT/'static'/'dashboard.html').read_text(encoding='utf-8').replace('__USER__',json.dumps(u,ensure_ascii=False)))

@app.get('/module/{module}',response_class=HTMLResponse)
def module_page(module: str, request: Request):
 u=current_user(request)
 if not u: return RedirectResponse('/',status_code=303)
 if module not in MODULES: raise HTTPException(404,'القسم غير موجود')
 if not can_access(u,module): return HTMLResponse('<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><body style="font-family:Arial;padding:40px"><h2>ليس لديك الصلاحية للدخول إلى هذه المنصة.</h2><a href="/dashboard">العودة إلى مركز القيادة</a></body></html>',status_code=403)
 return HTMLResponse((ROOT/'static'/'module.html').read_text(encoding='utf-8').replace('__MODULE__',module).replace('__TITLE__',MODULES[module]['title']).replace('__USER__',json.dumps(u,ensure_ascii=False)))

@app.get('/api/me')
def me(u=Depends(require_user)): return u

@app.get('/api/modules')
def list_modules(request: Request, u=Depends(require_user)):
 return [{'key':k,'title':v['title']} for k,v in MODULES.items() if can_access(u,k)]

@app.get('/api/records/{module}')
def list_records(module: str, request: Request, u=Depends(require_user)):
 if not can_access(u,module): raise HTTPException(403,'ليس لديك الصلاحية للدخول إلى هذه المنصة.')
 c=db(); rows=c.execute('SELECT * FROM records WHERE module=? ORDER BY updated_at DESC',(module,)).fetchall(); c.close()
 out=[]
 for row in rows:
  r=record_dict(row)
  if r['sensitivity']=='salary' and u['role'] not in ('branch_manager','hr','it'): continue
  if r['sensitivity']=='medical' and u['role']!='hr':
   # Branch manager receives aggregate-only summary, no individual medical detail.
   r['payload']={k:v for k,v in r['payload'].items() if k in ('month','paid_egp','pending_cases','source')}
  if module=='leave' and u['role']=='employee' and r['payload'].get('employee')!=u['display_name']: continue
  if module=='leave' and u['role']=='direct_manager' and r.get('owner') not in (u['display_name'],'المدير المباشر التجريبي'): continue
  out.append(r)
 return out

class RecordIn(BaseModel):
 ref: str = Field(min_length=3,max_length=80)
 title: str = Field(min_length=2,max_length=250)
 status: str = Field(default='جديد',max_length=80)
 owner: str = Field(default='',max_length=150)
 due_date: str = Field(default='',max_length=30)
 payload: dict = Field(default_factory=dict)
 reason: str = Field(default='',max_length=1000)

@app.post('/api/records/{module}')
def create_record(module: str, body: RecordIn, request: Request, u=Depends(require_user)):
 if not can_access(u,module): raise HTTPException(403,'ليس لديك الصلاحية للدخول إلى هذه المنصة.')
 if u['role']=='employee' and module!='leave': raise HTTPException(403,'ليس لديك الصلاحية لإنشاء هذا السجل.')
 if module=='medical' and u['role']!='hr': raise HTTPException(403,'تعديل التفاصيل الطبية مقصور على الموارد البشرية المخولة.')
 if module=='workforce' and u['role']!='hr': raise HTTPException(403,'تعديل بيانات القوى العاملة مقصور على الموارد البشرية المخولة.')
 now=dt(); c=db()
 try:
  sensitivity='normal'
  if module=='workforce': sensitivity='salary'
  if module=='medical': sensitivity='medical'
  c.execute('INSERT INTO records(module,ref,title,status,owner,due_date,payload,sensitivity,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(module,body.ref,body.title,body.status,body.owner,body.due_date,json.dumps(body.payload,ensure_ascii=False),sensitivity,u['username'],u['username'],now,now))
  audit(c,u,'create',module,body.ref,after=body.model_dump(),reason=body.reason); c.commit()
 except sqlite3.IntegrityError:
  c.close(); raise HTTPException(409,'الرقم المرجعي مستخدم بالفعل.')
 row=c.execute('SELECT * FROM records WHERE ref=?',(body.ref,)).fetchone(); c.close(); return record_dict(row)

@app.patch('/api/records/{module}/{ref}')
def update_record(module: str, ref: str, body: RecordIn, request: Request, u=Depends(require_user)):
 if not can_access(u,module): raise HTTPException(403,'ليس لديك الصلاحية للدخول إلى هذه المنصة.')
 if module=='medical' and u['role']!='hr': raise HTTPException(403,'تعديل التفاصيل الطبية مقصور على الموارد البشرية المخولة.')
 if module=='workforce' and u['role']!='hr': raise HTTPException(403,'تعديل بيانات القوى العاملة مقصور على الموارد البشرية المخولة.')
 c=db(); old=c.execute('SELECT * FROM records WHERE module=? AND ref=?',(module,ref)).fetchone()
 if not old: c.close(); raise HTTPException(404,'السجل غير موجود')
 before=record_dict(old)
 if old['sensitivity']=='salary' and u['role'] not in ('branch_manager','hr'): c.close(); raise HTTPException(403,'ليس لديك الصلاحية للبيانات المالية الحساسة.')
 if module=='tasks' and body.status in ('مكتمل','مغلق') and not (body.payload.get('evidence') or '').strip(): c.close(); raise HTTPException(422,'لا يمكن إغلاق التكليف دون مرجع إثبات.')
 if module=='leave' and body.status=='معتمد':
  if u['role'] not in ('hr','branch_manager'): c.close(); raise HTTPException(403,'اعتماد الإجازة النهائي للموارد البشرية أو مدير الفرع وفق الإجراء التجريبي.')
 now=dt(); c.execute('UPDATE records SET title=?,status=?,owner=?,due_date=?,payload=?,updated_by=?,updated_at=?,version=version+1 WHERE module=? AND ref=?',(body.title,body.status,body.owner,body.due_date,json.dumps(body.payload,ensure_ascii=False),u['username'],now,module,ref))
 after=dict(ref=ref,title=body.title,status=body.status,owner=body.owner,due_date=body.due_date,payload=body.payload,version=before['version']+1)
 audit(c,u,'update',module,ref,before=before,after=after,reason=body.reason); c.commit(); row=c.execute('SELECT * FROM records WHERE module=? AND ref=?',(module,ref)).fetchone(); c.close(); return record_dict(row)

@app.get('/api/audit')
def get_audit(request: Request, u=Depends(require_user)):
 if u['role'] not in ('branch_manager','it'): raise HTTPException(403,'ليس لديك الصلاحية لعرض سجل الحوكمة.')
 c=db(); rows=c.execute('SELECT actor,role,action,module,record_ref,reason,at FROM audit ORDER BY id DESC LIMIT 300').fetchall(); c.close(); return [dict(x) for x in rows]

@app.get('/api/health')
def health(): return {'ok':True,'database':'sqlite-local-test','environment':'DEMO ONLY','server_time':dt()}
