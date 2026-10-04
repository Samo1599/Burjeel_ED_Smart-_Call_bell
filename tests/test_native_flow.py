import os, unittest, uuid
from unittest.mock import patch
from types import SimpleNamespace
import test_native_fcm as fcm_tests
from test_push import app

class NativeFlowTests(unittest.TestCase):
    setUp=fcm_tests.NativeFCMTests.setUp
    def test_three_transports_and_provider_failure(self):
        self.assertTrue(hasattr(app,'native_fcm'))
        from firebase_admin import messaging
        native=[]; web=[]
        import threading
        received=threading.Condition()
        def capture(message,**kwargs):
            with received:
                native.append(message);received.notify_all()
            return "accepted"
        with app.SessionLocal() as db:
            db.query(app.PushSubscription).delete()
            for mode in ('browser','pwa'):
                db.add(app.PushSubscription(user_id=9001,endpoint='https://example.test/'+mode,payload='{"endpoint":"https://example.test/'+mode+'","keys":{}}'))
            db.commit()
            with patch.dict(os.environ,{'NATIVE_FCM_ENABLED':'true'}),patch.object(app.native_fcm,'_firebase_app',return_value=None),patch.object(messaging,'send',side_effect=capture),patch.object(app,'VAPID_PRIVATE_KEY','test'),patch.object(app,'webpush',side_effect=lambda **kw: web.append(__import__('json').loads(kw['data'])) or SimpleNamespace(status_code=201)):
                for n in range(4):
                    result=app.send_push_to_user(db,9001,'Room 7','Call',extra={'kind':'recall' if n else 'call','skip_in_app':True})
                    self.assertEqual(result['sent'],2)
                    self.assertEqual(result['native']['queued'],1)
                with received: self.assertTrue(received.wait_for(lambda:len(native)==4,timeout=3))
                self.assertEqual({m.data['event_id'] for m in native},{web[n]['event_id'] for n in range(0,8,2)})
                with patch.object(app,'webpush',side_effect=RuntimeError('web provider down')):
                    self.assertEqual(app.send_push_to_user(db,9001,'Room 7','Call',extra={'skip_in_app':True})['native']['queued'],1)
                    with received: self.assertTrue(received.wait_for(lambda:len(native)==5,timeout=3))

    def test_delayed_native_provider_does_not_hold_web(self):
        import threading
        from firebase_admin import messaging
        entered=threading.Event(); release=threading.Event(); web_sent=threading.Event()
        def native(message,**kw):
            entered.set();release.wait(3);return 'accepted'
        def call():
            with app.SessionLocal() as db: app.send_push_to_user(db,9001,'Room','Call',extra={'skip_in_app':True})
        with app.SessionLocal() as db:
            db.query(app.PushSubscription).delete()
            db.add(app.PushSubscription(user_id=9001,endpoint='https://example.test/browser',payload='{"endpoint":"https://example.test/browser","keys":{}}'))
            db.commit()
        with patch.dict(os.environ,{'NATIVE_FCM_ENABLED':'true'}),patch.object(app.native_fcm,'_firebase_app',return_value=None),patch.object(messaging,'send',side_effect=native),patch.object(app,'VAPID_PRIVATE_KEY','test'),patch.object(app,'webpush',side_effect=lambda **kw: web_sent.set() or SimpleNamespace(status_code=201)):
            thread=threading.Thread(target=call);thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(web_sent.wait(.5),'Web Push is blocked by FCM')
            finally: release.set();thread.join(3)
