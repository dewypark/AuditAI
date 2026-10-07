import unittest,io
import pandas as pd
from test_mvp import app,db
class ReviewRequestTests(unittest.TestCase):
 def test_request_opinion_scope_and_exports(self):
  client=app.test_client();client.get('/')
  with client.session_transaction() as s:csrf=s['csrf']
  result=client.post('/case/1',data=dict(csrf=csrf,action='demo'));rid=result.location.rsplit('/',1)[1]
  path=f'/run/{rid}/request-review';reply=f'/run/{rid}/review-opinion'
  self.assertEqual(client.post(reply,data=dict(csrf=csrf,reviewer='검토자',opinion='미리 작성')).status_code,400)
  self.assertEqual(client.post(path,data=dict(requester='신청자',question='검토')).status_code,400)
  self.assertEqual(client.post(path,data=dict(csrf=csrf,requester='신청자',question='')).status_code,400)
  for who in ['신청자','중복']:
   self.assertEqual(client.post(path,data=dict(csrf=csrf,requester=who,question='회수 지연과 증빙 검토')).status_code,302)
  with db() as c:
   req=c.execute('SELECT * FROM review_requests WHERE run_id=?',(rid,)).fetchone()
   self.assertEqual(req['status'],'검토 대기');self.assertEqual(req['requester'],'신청자')
   self.assertEqual(c.execute('SELECT count(*) FROM review_requests WHERE run_id=?',(rid,)).fetchone()[0],1)
  other=app.test_client();other.get('/')
  with other.session_transaction() as s:token=s['csrf']
  self.assertEqual(other.post(reply,data=dict(csrf=token,reviewer='다른 사용자',opinion='접근')).status_code,404)
  self.assertEqual(client.post(reply,data=dict(csrf=csrf,reviewer='검토자',opinion='<script>demo</script>')).status_code,302)
  html=client.get(result.location).get_data(as_text=True)
  self.assertIn('의견 작성 완료',html);self.assertIn('&lt;script&gt;demo&lt;/script&gt;',html)
  with db() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM history WHERE run_id=?',(rid,)).fetchone()[0],2)
   self.assertEqual(c.execute('SELECT conclusion FROM runs WHERE id=?',(rid,)).fetchone()[0],'')
   self.assertEqual(c.execute("SELECT count(*) FROM candidates WHERE run_id=? AND status!='미검토'",(rid,)).fetchone()[0],0)
  book=pd.ExcelFile(io.BytesIO(client.get(f'/run/{rid}/export').data))
  self.assertIn('검토 신청·의견',book.sheet_names)
  self.assertIn('검토 신청·의견',client.get(f'/run/{rid}/workpaper').get_data(as_text=True))
