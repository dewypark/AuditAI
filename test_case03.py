import io
import unittest
from pathlib import Path
import pandas as pd
from sod_check import inspect_sod,read_case03,SoDInputError
from legacy_app import app
SAMPLE=Path(__file__).parent/'sample_data/Case03_SoD_Practice.xlsx'
class SoDTests(unittest.TestCase):
 def setUp(self):self.f=read_case03(SAMPLE)
 def test_expected(self):
  r=inspect_sod(*self.f);c=r['SoD 검토 후보']
  self.assertEqual(set(zip(c.user_id,c.rule_id)),{('U002','SOD01'),('U006','SOD02'),('U010','SOD03'),('U020','SOD01'),('U020','SOD02'),('U050','SOD01'),('U050','SOD02'),('U050','SOD03')})
  self.assertEqual(c.user_id.nunique(),5)
  self.assertTrue(c[c.user_id.eq('U002')]['완화 통제 검토'].iloc[0].startswith('유효 승인'))
  self.assertIn('U099',set(r['자료 확인'].user_id))
 def test_boundary(self):
  f=[x.copy() for x in self.f];f[1]['removed_at']=f[1]['removed_at'].astype('object')
  mask=f[1].user_id.eq('U002')&f[1].role_id.eq('R_PAYMENT')
  f[1].loc[mask,'removed_at']=pd.Timestamp('2026-09-30 18:00:00')
  c=inspect_sod(*f)['SoD 검토 후보'];self.assertNotIn('U002',set(c.user_id))
  f[1].loc[mask,'removed_at']=pd.Timestamp('2026-09-30 18:00:01')
  self.assertIn('U002',set(inspect_sod(*f)['SoD 검토 후보'].user_id))
 def test_duplicates(self):
  f=[x.copy() for x in self.f];f[0]=pd.concat([f[0],f[0].iloc[[0]]])
  with self.assertRaises(SoDInputError):inspect_sod(*f)
  f=[x.copy() for x in self.f];extra=f[1].iloc[[1]].copy();extra.assignment_id='A999';f[1]=pd.concat([f[1],extra])
  self.assertEqual(len(inspect_sod(*f)['SoD 검토 후보']),8)
 def test_empty(self):
  f=[x.copy() for x in self.f];f[0]['account_status']='Disabled'
  self.assertEqual(len(inspect_sod(*f)['SoD 검토 후보']),0)
 def test_web(self):
  c=app.test_client();self.assertEqual(c.get('/case03').status_code,200)
  self.assertEqual(c.post('/case03').status_code,400)
  for action in ['inspect','download']:
   r=c.post('/case03',data={'file':(io.BytesIO(SAMPLE.read_bytes()),'sample.xlsx'),'action':action},content_type='multipart/form-data');self.assertEqual(r.status_code,200)
   if action=='inspect':self.assertIn('충돌 계정·규칙 8건',r.data.decode())
   else:self.assertEqual(len(pd.read_excel(io.BytesIO(r.data),sheet_name='SoD 검토 후보')),8)
if __name__=='__main__':unittest.main()
