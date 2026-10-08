import unittest
from test_mvp import app
class ViewTests(unittest.TestCase):
 def test_customer_and_inspector_roundtrip(self):
  c=app.test_client();c.get('/')
  with c.session_transaction() as s: token=s['csrf']
  r=c.post('/case/1',data={'csrf':token,'action':'demo'});rid=r.location.rsplit('/',1)[1]
  c.post(f'/run/{rid}/request-review',data={'csrf':token,'requester':'고객','question':'증빙 확인'})
  a=c.get(f'/run/{rid}').get_data(as_text=True);b=c.get(f'/inspector/run/{rid}').get_data(as_text=True)
  self.assertNotIn('name="opinion"',a);self.assertNotIn('name="note"',a);self.assertNotIn('name="conclusion"',a)
  self.assertIn('name="opinion"',b);self.assertIn('name="note"',b);self.assertIn('name="conclusion"',b)
  c.post(f'/run/{rid}/review-opinion',data={'csrf':token,'reviewer':'검사자','opinion':'로그 추가 확인'})
  self.assertIn('로그 추가 확인',c.get(f'/run/{rid}').get_data(as_text=True))
  self.assertEqual(c.get('/inspector').status_code,200)
  other=app.test_client();self.assertEqual(other.get(f'/inspector/run/{rid}').status_code,404)

 def test_all_customer_cases_show_evidence_requests(self):
  from main import db
  import html
  c=app.test_client();c.get('/')
  with c.session_transaction() as sess: token=sess['csrf']
  for case in range(1,9):
   with self.subTest(case=case):
    reply=c.post(f'/case/{case}',data={'csrf':token,'action':'demo'})
    self.assertEqual(reply.status_code,302)
    rid=reply.location.rsplit('/',1)[1]
    text=c.get(reply.location).get_data(as_text=True)
    self.assertIn('항목별 결과와 필요한 증빙',text)
    self.assertIn('증빙 필요:',text)
    self.assertNotIn('name="note"',text)
    with db() as conn: rows=conn.execute('SELECT entity,reason,evidence_request FROM candidates WHERE run_id=?',(rid,)).fetchall()
    self.assertGreater(len(rows),0)
    for row in rows:
     self.assertTrue(row['evidence_request'].strip())
     self.assertIn(row['evidence_request'],html.unescape(text))
    self.assertLess(text.index('id="customer-findings"'),text.index('id="review-request"'))
