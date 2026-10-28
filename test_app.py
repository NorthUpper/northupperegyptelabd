import os, tempfile
from fastapi.testclient import TestClient
from backend import app as mod

fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
mod.DB_PATH = __import__('pathlib').Path(path)
mod.init_db()
client = TestClient(mod.app)

def login(username,password):
 return client.post('/login',data={'username':username,'password':password},follow_redirects=False)

def test_demo_login_and_dashboard():
 r=login('mgr.demo','Demo-Mgr-2026'); assert r.status_code==303
 assert client.get('/dashboard').status_code==200
 assert client.get('/api/health').json()['ok'] is True

def test_employee_cannot_read_workforce():
 client.post('/logout'); login('employee.demo','Demo-Emp-2026')
 assert client.get('/api/records/workforce').status_code==403

def test_hr_can_read_medical_but_manager_only_aggregate():
 client.post('/logout'); login('hr.demo','Demo-HR-2026')
 hr=client.get('/api/records/medical').json()[0]
 assert 'paid_egp' in hr['payload']
 client.post('/logout'); login('mgr.demo','Demo-Mgr-2026')
 manager=client.get('/api/records/medical').json()[0]
 assert 'paid_egp' in manager['payload'] and 'diagnosis' not in manager['payload']

def test_duplicate_reference_rejected():
 client.post('/logout'); login('mgr.demo','Demo-Mgr-2026')
 body={'ref':'APT-DEMO-001','title':'تكرار','status':'جديد','owner':'','due_date':'','payload':{}}
 assert client.post('/api/records/appointments',json=body).status_code==409

def test_task_cannot_close_without_evidence():
 client.post('/logout'); login('mgr.demo','Demo-Mgr-2026')
 body={'ref':'TASK-DEMO-001','title':'مراجعة سبب تأخر لوحة تجريبية','status':'مكتمل','owner':'مسؤول التخطيط التجريبي','due_date':'2026-10-20','payload':{'priority':'مرتفع','evidence':''}}
 assert client.patch('/api/records/tasks/TASK-DEMO-001',json=body).status_code==422

def test_it_cannot_access_medical():
 client.post('/logout'); login('it.demo','Demo-IT-2026')
 assert client.get('/api/records/medical').status_code==403
 assert client.get('/api/records/drawings').status_code==403
 assert client.get('/api/records/workforce').status_code==200


def test_manager_cannot_edit_medical_details():
 client.post('/logout'); login('mgr.demo','Demo-Mgr-2026')
 body={'ref':'MED-DEMO-001','title':'ملخص مصروفات علاجية تجريبي','status':'قيد المراجعة','owner':'الموارد البشرية','due_date':'2026-10-24','payload':{'paid_egp':0}}
 assert client.patch('/api/records/medical/MED-DEMO-001',json=body).status_code==403

def test_it_can_only_read_aggregate_workforce_not_edit():
 client.post('/logout'); login('it.demo','Demo-IT-2026')
 assert client.get('/api/records/workforce').status_code==200
 body={'ref':'WF-DEMO-001','title':'ملخص قوى عاملة تجريبي','status':'محدث','owner':'الموارد البشرية','due_date':'2026-10-19','payload':{'monthly_payroll_egp':0}}
 assert client.patch('/api/records/workforce/WF-DEMO-001',json=body).status_code==403
