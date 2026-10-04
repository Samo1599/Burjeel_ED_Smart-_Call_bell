import unittest, uuid, os
from unittest.mock import patch
from datetime import datetime, timezone
from test_push import app

class NativeFCMTests(unittest.TestCase):
    def setUp(self):
        with app.SessionLocal() as db:
            db.query(app.NativePushDevice).delete()
            if not db.get(app.User,9001): db.add(app.User(id=9001,name='Test',email='native9001@example.test',password_hash='unused',role='nurse',active=True))
            db.add(app.NativePushDevice(installation_id=str(uuid.uuid4()),user_id=9001,fcm_token='native-test-token',credential_hash=uuid.uuid4().hex,active=True,updated_at=datetime.now(timezone.utc)))
            db.commit()

    def test_high_priority_unique_recall_events(self):
        self.assertTrue(hasattr(app,'native_fcm'),'FCM transport missing')
        from firebase_admin import messaging
        captured=[]
        with patch.dict(os.environ,{'NATIVE_FCM_ENABLED':'true'}),patch.object(app.native_fcm,'_firebase_app',return_value=None),patch.object(messaging,'send',side_effect=lambda message,**kw: captured.append(message) or 'accepted'),patch.object(app,'VAPID_PRIVATE_KEY',''):
            with app.SessionLocal() as db:
                for n in range(4):
                    result=app.native_fcm.send_native_to_user(db,9001,{'event_id':uuid.uuid4().hex,'sent_at_ms':1,'title':'Room 7','body':'Sensitive reason','kind':'recall' if n else 'call'})
                    self.assertEqual(result['sent'],1)
        self.assertEqual(len({m.data['event_id'] for m in captured}),4)
        self.assertEqual(len({m.data['event_id'] for m in captured}),4)
        for message in captured:
            self.assertEqual(message.android.priority,'high')
            self.assertEqual(message.android.ttl.total_seconds(),900)
            self.assertIsNone(message.android.collapse_key)
            self.assertIsNone(message.notification)
            self.assertNotIn('Sensitive',message.data['body'])
            self.assertIsNone(message.android.notification)

    def test_provider_failure_does_not_escape(self):
        self.assertTrue(hasattr(app,'native_fcm'),'FCM transport missing')
        from firebase_admin import messaging
        with patch.dict(os.environ,{'NATIVE_FCM_ENABLED':'true'}),patch.object(app.native_fcm,'_firebase_app',return_value=None),patch.object(messaging,'send',side_effect=RuntimeError('network failure')),patch.object(app,'VAPID_PRIVATE_KEY',''):
            with app.SessionLocal() as db:
                result=app.native_fcm.send_native_to_user(db,9001,{'event_id':uuid.uuid4().hex,'title':'Room 7'})
                self.assertEqual(result['failed'],1)

    def test_invalid_token_deactivates_one_device(self):
        self.assertTrue(hasattr(app,'native_fcm'),'FCM transport missing')
        from firebase_admin import messaging
        with patch.dict(os.environ,{'NATIVE_FCM_ENABLED':'true'}),patch.object(app.native_fcm,'_firebase_app',return_value=None),patch.object(messaging,'send',side_effect=messaging.UnregisteredError('gone')):
            with app.SessionLocal() as db:
                result=app.native_fcm.send_native_to_user(db,9001,{'event_id':'test','sent_at_ms':1,'title':'Room 7','url':'/nurse'})
                self.assertEqual(result['disabled'],1)
                self.assertFalse(db.query(app.NativePushDevice).first().active)

    def test_old_token_error_does_not_disable_rotated_registration(self):
        from firebase_admin import messaging
        def rotate_then_fail(message,**kwargs):
            with app.SessionLocal() as other:
                row=other.query(app.NativePushDevice).first()
                row.fcm_token='fresh-token'; row.credential_hash='fresh-generation'
                other.commit()
            raise messaging.UnregisteredError('old token expired')
        with patch.dict(os.environ,{'NATIVE_FCM_ENABLED':'true'}),patch.object(app.native_fcm,'_firebase_app',return_value=None),patch.object(messaging,'send',side_effect=rotate_then_fail):
            with app.SessionLocal() as db:
                app.native_fcm.send_native_to_user(db,9001,{'event_id':'race','sent_at_ms':1})
            with app.SessionLocal() as db:
                self.assertTrue(db.query(app.NativePushDevice).first().active)
