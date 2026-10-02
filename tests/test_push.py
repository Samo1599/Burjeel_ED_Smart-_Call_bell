"""Deterministic Push flow tests; these do not test a phone's lock screen."""
import os, tempfile, unittest, json
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_tmp=tempfile.TemporaryDirectory()
os.environ['DATABASE_URL']='sqlite:///'+_tmp.name+'/test.db'
import app
from fastapi.testclient import TestClient

class PushTests(unittest.TestCase):
    def setUp(self):
        with app.SessionLocal() as db:
            for model in (app.PushVerification,app.PushDevice,app.PushSubscription): db.query(model).delete()
            db.commit()
        self.client=TestClient(app.app)
        self.auth=patch.object(app,'require_role',return_value=SimpleNamespace(id=1,name='Test Nurse',role='nurse'))
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.addCleanup(self.client.close)
    def register(self,mode,endpoint):
        return self.client.post('/api/push/subscribe',json={'subscription':{'endpoint':endpoint,'keys':{'p256dh':'test','auth':'test'}},'device':{'display_mode':mode,'platform':'test'}})
    def test_distinct_endpoints_fan_out_and_targeted_tests(self):
        endpoints=['https://push.example/browser','https://push.example/pwa']
        for mode,ep in zip(['browser','pwa'],endpoints): self.assertEqual(self.register(mode,ep).status_code,200)
        with patch.object(app,'VAPID_PRIVATE_KEY','test'),patch.object(app,'webpush',return_value=SimpleNamespace(status_code=201)) as sender, app.SessionLocal() as db:
            self.assertEqual(app.send_push_to_user(db,1,'Call','Room')['sent'],2)
            self.assertEqual({c.kwargs['subscription_info']['endpoint'] for c in sender.call_args_list},set(endpoints))
            sender.reset_mock()
            self.assertEqual(app.send_push_to_user(db,1,'Test','PWA',endpoint=endpoints[1])['sent'],1)
            self.assertEqual(sender.call_args.kwargs['subscription_info']['endpoint'],endpoints[1])
            self.assertEqual(sender.call_args.kwargs['headers']['Urgency'],'high')
    def test_simultaneous_verifications_are_independent(self):
        for mode in ['browser','pwa']: self.register(mode,'https://push.example/'+mode)
        tokens=[]
        with patch.object(app,'VAPID_PRIVATE_KEY','test'),patch.object(app,'VAPID_PUBLIC_KEY','test'),patch.object(app,'webpush',return_value=SimpleNamespace(status_code=201)):
            for mode in ['browser','pwa']:
                r=self.client.post('/api/push/test',json={'endpoint':'https://push.example/'+mode,'device':{'display_mode':mode,'platform':'test'}})
                self.assertEqual(r.status_code,200);tokens.append(r.json()['verification_token'])
        for token,mode in zip(tokens,['browser','pwa']):
            self.assertEqual(self.client.post('/api/push/verify/'+token).status_code,200)
            self.assertTrue(self.client.get('/api/push/verification/'+token+'?mode='+mode+'&platform=test').json()['verified'])
    def test_missing_server_row_requires_registration_not_unsubscribe(self):
        r=self.client.post('/api/push/health',json={'endpoint':'https://push.example/pwa','device':{'display_mode':'pwa'}})
        self.assertFalse(r.json()['force_resubscribe']);self.assertTrue(r.json()['needs_registration'])
        self.register('pwa','https://push.example/pwa')
        self.assertTrue(self.client.post('/api/push/health',json={'endpoint':'https://push.example/pwa'}).json()['healthy'])
    def test_browser_verification_does_not_verify_pwa(self):
        ep='https://push.example/shared'
        self.register('browser',ep);self.register('pwa',ep)
        with app.SessionLocal() as db:
            app._upsert_push_device(db,1,ep,{'display_mode':'browser','platform':'test'},verified=True);db.commit()
        for mode,expected in [('browser',True),('pwa',False)]:
            r=self.client.post('/api/push/device-status',json={'endpoint':ep,'device':{'display_mode':mode,'platform':'test'}})
            self.assertEqual(r.json()['verified'],expected)
    def test_call_then_recalls_reach_each_endpoint_without_opening_pwa(self):
        from datetime import timedelta
        for mode in ['browser','pwa']:self.register(mode,'https://push.example/'+mode)
        with app.SessionLocal() as db:
            room=app.Room(code='RECALL-TEST',qr_token='recall-test-token',occupied=True,assigned_nurse_id=1)
            db.add(room);db.commit()
        clock=app.now_utc()
        with patch.object(app,'now_utc',return_value=clock) as now,patch.object(app,'VAPID_PRIVATE_KEY','test'),patch.object(app,'webpush',return_value=SimpleNamespace(status_code=201)) as sender:
            first=self.client.post('/api/room/recall-test-token/call',json={'reason':'General assistance'})
            self.assertEqual(first.status_code,200);call_id=first.json()['call_id']
            self.assertEqual(sender.call_count,2)
            # There are no health/subscribe requests between the original call and recalls.
            for number in [1,2,3]:
                now.return_value=clock+timedelta(seconds=121*number)
                r=self.client.post('/api/call/'+str(call_id)+'/recall')
                self.assertEqual(r.status_code,200);self.assertEqual(r.json()['recall_count'],number)
            messages=[json.loads(c.kwargs['data']) for c in sender.call_args_list if c.kwargs['subscription_info']['endpoint']=='https://push.example/pwa']
            self.assertEqual(len(messages),4)
            self.assertEqual(len({m['event_id'] for m in messages}),4)
            self.assertEqual([m.get('tag') for m in messages[1:]],[f'recall-{call_id}-{i}' for i in [1,2,3]])
            for m in messages:
                signed=app.push_receipt_signer.loads(m['receipt_token'])
                self.assertEqual(signed['event_id'],m['event_id'])
                self.assertEqual(signed['endpoint_hash'],app.hashlib.sha256(b'https://push.example/pwa').hexdigest()[:12])
            self.assertEqual(self.client.post('/api/call/'+str(call_id)+'/recall').status_code,409)
    def test_signed_display_receipts_work_without_auth(self):
        token=app.push_receipt_signer.dumps({'event_id':'event-test','user_id':1,'endpoint_hash':'hash-test','kind':'recall','sent_at_ms':1000})
        with patch('builtins.print') as logs:
            r=self.client.post('/api/push/receipt',json={'token':token,'received_at_ms':2000,'displayed_at_ms':2001})
            self.assertEqual(r.status_code,204)
            self.assertIn('WEBPUSH_DISPLAYED event=event-test kind=recall',logs.call_args.args[0])
        self.assertEqual(self.client.post('/api/push/receipt',json={'token':token+'tampered','received_at_ms':2000,'displayed_at_ms':2001}).status_code,403)
        self.assertEqual(self.client.post('/api/push/receipt',json={'token':token,'received_at_ms':2000,'displayed_at_ms':1999}).status_code,400)

    def test_assets_and_js_harness(self):
        self.assertEqual(self.client.get('/sw.js').headers['cache-control'],'no-cache')
        manifest=self.client.get('/manifest.webmanifest').json()
        self.assertEqual(manifest['id'],'/');self.assertEqual(manifest['scope'],'/')
        import subprocess
        subprocess.run(['node','tests/push_worker.cjs'],input=json.dumps({'sw':app.SERVICE_WORKER_JS,'js':app.APP_JS}),text=True,check=True)

if __name__=='__main__':unittest.main()
