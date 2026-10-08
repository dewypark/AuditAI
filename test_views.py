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
