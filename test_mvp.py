import unittest,json,io,os,tempfile,sys,subprocess
from pathlib import Path
import pandas as pd
os.environ['AUDITAI_DATA_DIR']=tempfile.mkdtemp(prefix='auditai-tests-')
from main import app,db,DB
from engine import execute
from finance_checks import inspect_finance
ROOT=Path(__file__).parent
CFG=dict(snapshot='2026-09-30 18:00',emergency_hours=48,tolerance=.01,high_amount=1000000,contamination=.05)
def sample(n):return {k:pd.DataFrame(v) for k,v in json.loads((ROOT/'sample_data'/f'case{n:02}.json').read_text()).items()}
class MVPTests(unittest.TestCase):
 def test_reconciliation_groundtruth_and_tolerance(self):
  t=sample(5);r,c,p=execute(5,t,CFG)
  self.assertEqual({(x['entity_id'],x['rule_id']) for x in c},{('T002','REC01'),('T999','REC01'),('T006','REC03'),('T010','REC02')})
  t={'Source':pd.DataFrame([dict(transaction_id='A',amount=10,currency='KRW')]),'Target':pd.DataFrame([dict(transaction_id='A',amount=10.01,currency='KRW')])}
  self.assertEqual(len(execute(5,t,CFG)[1]),0)
  t['Target'].loc[0,'amount']=10.011
  self.assertEqual(len(execute(5,t,CFG)[1]),1)
 def test_journal_groundtruth(self):
  _,cs,p=execute(6,sample(6),CFG)
  self.assertEqual({(x['entity_id'],x['rule_id']) for x in cs},{('J001:KRW','JE01'),('J003:KRW','JE01'),('L002D','JE02'),('L003D','JE03'),('L004D','JE04'),('L005D','JE05')})
 def test_payments_and_void_scope(self):
  _,cs,p=execute(7,sample(7),CFG)
  self.assertEqual(p,99)
  self.assertEqual({x['entity_id'] for x in cs if x['rule_id']=='AP01'},{'P001','P002'})
  self.assertEqual({x['entity_id'] for x in cs if x['rule_id']=='VEN01'},{'V005','V006'})
  t=sample(7);t['Payments'].loc[1,'status']='Void'
  self.assertFalse(any(x['rule_id']=='AP01' for x in execute(7,t,CFG)[1]))
 def test_model_determinism_and_small_currency(self):
  a=execute(8,sample(8),CFG);b=execute(8,sample(8),CFG)
  self.assertEqual(a[1],b[1]);f=a[0]['위험 점수']
  self.assertFalse(f.loc[f.currency.eq('USD'),'ml_flag'].any())
  self.assertEqual(f.loc[f.transaction_id.eq('T001'),'rule_score'].iloc[0],80)
 def test_bad_input(self):
  for n in range(5,9):
   t=sample(n);k=next(iter(t));t[k]=pd.concat([t[k],t[k].iloc[:1]])
   with self.assertRaises(ValueError):execute(n,t,CFG)
  t=sample(6);t['Journal'].loc[0,'posted_at']='broken'
  with self.assertRaises(ValueError):execute(6,t,CFG)
  t=sample(5);t['Source'].loc[0,'amount']=float('inf')
  with self.assertRaises(ValueError):execute(5,t,CFG)
 def test_all_cases_upload_download_review_history_and_restart(self):
  client=app.test_client();client.get('/')
  with client.session_transaction() as s:csrf=s['csrf']
  ids=[]
  for n in range(1,9):
   self.assertEqual(client.get(f'/case/{n}').status_code,200)
   r=client.post(f'/case/{n}',data=dict(csrf=csrf,action='demo'))
   self.assertEqual(r.status_code,302,r.data[:300]);rid=r.location.rsplit('/',1)[1];ids.append(rid)
   self.assertEqual(client.get(r.location).status_code,200)
   x=client.get(f'/run/{rid}/export');self.assertEqual(x.status_code,200)
   book=pd.ExcelFile(io.BytesIO(x.data));self.assertIn('검토 기록',book.sheet_names)
  rid=ids[4]
  self.assertEqual(client.post(f'/run/{rid}/conclusion',data=dict(csrf=csrf,reviewer='tester',conclusion='premature')).status_code,400)
  with db() as c:cs=c.execute('SELECT id FROM candidates WHERE run_id=?',(rid,)).fetchall()
  for row in cs:
   cid=row['id'];path=f'/run/{rid}/review/{cid}'
   self.assertEqual(client.post(path,data=dict(csrf=csrf,status='검토 완료·설명 가능',reviewer='tester',note='확인')).status_code,400)
   self.assertEqual(client.post(path,data=dict(csrf=csrf,status='검토 완료·설명 가능',reviewer='tester',note='합성 증빙 참조 기록 시연',evidence_ref='SYNTHETIC-DEMO-ONLY')).status_code,302)
  self.assertEqual(client.post(f'/run/{rid}/conclusion',data=dict(csrf=csrf,reviewer='tester',conclusion='합성 시연: 실제 운영 효과성 결론 아님')).status_code,302)
  with db() as c:self.assertEqual(c.execute('SELECT count(*) FROM history WHERE run_id=?',(rid,)).fetchone()[0],5)
  other=app.test_client();self.assertEqual(other.get(f'/run/{rid}').status_code,404)
  self.assertEqual(client.post('/case/5',data=dict(action='demo')).status_code,400)
  # Separate process imports the app and reads committed records after restart.
  result=subprocess.check_output([sys.executable,'-c','from main import db;\nwith db() as c: print(c.execute("SELECT count(*) FROM runs").fetchone()[0])'],cwd=ROOT,env=os.environ,text=True)
  self.assertGreaterEqual(int(result.strip()),8)
  self.assertEqual(client.get(f'/run/{rid}/workpaper').status_code,200)
 def test_mapping_upload_and_formula_safe_export(self):
  client=app.test_client();client.get('/')
  with client.session_transaction() as s:csrf=s['csrf']
  data=json.loads((ROOT/'sample_data'/'case05.json').read_text());data['Source'][0]['transaction_id']='=1+1';data['Target'][0]['transaction_id']='=1+1'
  for row in data['Source']:row['거래번호']=row.pop('transaction_id')
  mapping=json.dumps({'Source':{'거래번호':'transaction_id'}},ensure_ascii=False)
  r=client.post('/case/5',data={'csrf':csrf,'mapping':mapping,'action':'upload','file':(io.BytesIO(json.dumps(data,ensure_ascii=False).encode()),'custom.json')})
  self.assertEqual(r.status_code,302,r.data[:200])
  from openpyxl import load_workbook
  book=load_workbook(io.BytesIO(client.get(r.location+'/export').data))
  self.assertFalse(any(cell.data_type=='f' for sheet in book for row in sheet for cell in row))
if __name__=='__main__':unittest.main()
