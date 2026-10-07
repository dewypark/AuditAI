import io
import unittest
from pathlib import Path
import pandas as pd
from privileged_check import inspect_privileged_jml, read_case02, Case02InputError
from legacy_app import app

SAMPLE=Path(__file__).parent/'sample_data/Case02_Privileged_Access_JML.xlsx'
class Case02Tests(unittest.TestCase):
    def setUp(self):
        self.frames=read_case02(SAMPLE)
    def test_counts(self):
        r=inspect_privileged_jml(*self.frames)
        p=r['관리자권한 검사']
        self.assertEqual(len(p),16)
        self.assertEqual(p['부서 검사'].value_counts().to_dict(),{'부서 일치':13,'부서 불일치 검토':2,'소유자 확인 필요':1})
        self.assertEqual(p['승인 시점 검사'].value_counts().to_dict(),{'승인시점 충족':13,'승인 확인 필요':2,'사후 승인 검토':1})
        self.assertEqual(p['승인자 검사'].value_counts().to_dict(),{'승인자 일치':13,'승인 확인 필요':2,'승인자 불일치 검토':1})
        self.assertEqual(p['만료 검사'].value_counts().to_dict(),{'만료일 없음':14,'만료 후 권한 잔존 검토':1,'승인 기록 확인 필요':1})
        for k in ['퇴사자 권한 검토','입사전 권한부여','이동후 권한잔존']:
            self.assertEqual(len(r[k]),2)
        self.assertEqual(set(r['이동후 권한잔존'].user_id),{'U030'})
    def test_invalid_inputs(self):
        f=[x.copy() for x in self.frames]
        f[0]=pd.concat([f[0],f[0].iloc[[0]]])
        with self.assertRaises(Case02InputError):inspect_privileged_jml(*f)
        f=[x.copy() for x in self.frames];f[1].loc[0,'granted_at']='not a date'
        with self.assertRaises(Case02InputError):inspect_privileged_jml(*f)
        f=[x.copy() for x in self.frames];f[2]=f[2].drop(columns='is_privileged')
        with self.assertRaises(Case02InputError):inspect_privileged_jml(*f)
    def test_mover_boundary(self):
        f=[x.copy() for x in self.frames]
        f[1]['removed_at']=f[1]['removed_at'].astype('object')
        mask=f[1].employee_id.eq('E030')
        f[1].loc[mask,'removed_at']='2026-09-10 23:59:59'
        self.assertEqual(len(inspect_privileged_jml(*f)['이동후 권한잔존']),0)
        f[1].loc[mask,'removed_at']='2026-09-11 00:00:00'
        self.assertEqual(len(inspect_privileged_jml(*f)['이동후 권한잔존']),2)
    def test_web(self):
        c=app.test_client()
        self.assertEqual(c.get('/case01').status_code,200)
        self.assertEqual(c.get('/case02').status_code,200)
        self.assertEqual(c.post('/case02').status_code,400)
        for action in ['inspect','download']:
            response=c.post('/case02',data={'file':(io.BytesIO(SAMPLE.read_bytes()),'test.xlsx'),'action':action},content_type='multipart/form-data')
            self.assertEqual(response.status_code,200)
            if action=='inspect':self.assertIn('관리자 권한 16건',response.data.decode())
            else:
                book=pd.ExcelFile(io.BytesIO(response.data))
                self.assertEqual(len(book.sheet_names),7)
                self.assertEqual(len(pd.read_excel(book,'관리자권한 검사')),16)
        response=c.post('/case02',data={'file':(io.BytesIO(b'broken'),'test.xlsx')},content_type='multipart/form-data')
        self.assertEqual(response.status_code,400)
if __name__=='__main__':unittest.main()
