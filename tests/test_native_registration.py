import unittest, uuid
from unittest.mock import patch
from types import SimpleNamespace
from test_push import app
from fastapi.testclient import TestClient

class NativeRegistrationTests(unittest.TestCase):
    def setUp(self):
        with app.SessionLocal() as db:
            db.query(app.NativePushDevice).delete()
            db.query(app.NativeEnrollmentChallenge).delete()
            for uid in (9001,9002):
                user=db.get(app.User,uid)
                if not user:
                    db.add(app.User(id=uid,name='Test',email=f'native{uid}@example.test',password_hash='unused',role='nurse',active=True))
                else: user.active=True
            db.commit()
        self.client=TestClient(app.app)
        self.user=SimpleNamespace(id=9001,active=True,role='nurse')
        self.auth=patch.object(app,'current_user',return_value=self.user)
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.addCleanup(self.client.close)
        self.origin={'Origin':'http://testserver'}

    def challenge(self):
        response=self.client.get('/api/mobile/status')
        self.assertEqual(response.status_code,200)
        headers={**self.origin,'X-CSRF-Token':response.json()['csrf_token']}
        response=self.client.post('/api/mobile/challenge',headers=headers)
        self.assertEqual(response.status_code,200)
        return response.json()['challenge']

    def enroll(self,challenge,installation=None,credential=None):
        return self.client.post('/api/mobile/enroll',headers={'Authorization':'Bearer '+credential} if credential else {},json={'challenge':challenge,'installation_id':installation or str(uuid.uuid4()),'fcm_token':'test-token-'+str(uuid.uuid4()),'user_id':123})

    def test_verified_installation_resumes_without_another_test(self):
        first=self.enroll(self.challenge()).json()
        headers={'Authorization':'Bearer '+first['credential']}
        with patch.object(app.native_fcm,'enabled',return_value=True),patch.object(app.native_fcm,'send_native_to_user',return_value={'sent':1}) as sender:
            self.assertEqual(self.client.post('/api/mobile/resume',headers=headers).status_code,409)
            status=self.client.get('/api/mobile/status').json()
            self.client.post('/api/mobile/test',headers={**self.origin,'X-CSRF-Token':status['csrf_token']},json={'installation_id':first['installation_id']})
            self.assertEqual(self.client.post('/api/mobile/ready',headers=headers).status_code,200)
            second=self.enroll(self.challenge(),first['installation_id'],first['credential']).json()
            headers={'Authorization':'Bearer '+second['credential']}
            self.assertEqual(self.client.post('/api/mobile/resume',headers=headers).status_code,200)
            self.assertEqual(sender.call_count,1)
            self.user.id=9002
            third=self.enroll(self.challenge(),first['installation_id'],second['credential']).json()
            self.assertEqual(self.client.post('/api/mobile/resume',headers={'Authorization':'Bearer '+third['credential']}).status_code,409)

    def test_challenge_ownership_and_replay(self):
        with patch.object(app,'current_user',return_value=None):
            self.assertEqual(self.client.post('/api/mobile/challenge',headers=self.origin).status_code,401)
        self.assertEqual(self.client.post('/api/mobile/challenge',headers={'Origin':'https://evil.example'}).status_code,403)
        challenge=self.challenge()
        enrolled=self.enroll(challenge)
        self.assertEqual(enrolled.status_code,200)
        self.assertEqual(enrolled.json()['user_id'],9001)
        self.assertEqual(self.enroll(challenge).status_code,403)

    def test_rotation_revocation_and_disabled_account(self):
        installation=str(uuid.uuid4())
        first=self.enroll(self.challenge(),installation).json()
        headers={'Authorization':'Bearer '+first['credential']}
        self.assertEqual(self.client.post('/api/mobile/token',headers=headers,json={'fcm_token':'rotated-'+installation}).status_code,200)
        self.assertEqual(self.client.post('/api/mobile/revoke',headers=headers).status_code,200)
        self.assertEqual(self.client.post('/api/mobile/token',headers=headers,json={'fcm_token':'ignored'}).status_code,401)
        self.user.active=False
        self.assertEqual(self.client.post('/api/mobile/challenge',headers=self.origin).status_code,401)

    def test_account_switch_invalidates_previous_credential(self):
        installation=str(uuid.uuid4())
        first=self.enroll(self.challenge(),installation).json()
        self.user.id=9002
        self.assertEqual(self.enroll(self.challenge(),installation).status_code,403)
        second=self.enroll(self.challenge(),installation,first['credential'])
        self.assertEqual(second.status_code,200)
        self.assertEqual(self.client.post('/api/mobile/token',headers={'Authorization':'Bearer '+first['credential']},json={'fcm_token':'stale'}).status_code,401)

    def test_native_ready_requires_credential_and_bound_session(self):
        enrollment=self.enroll(self.challenge()).json()
        self.assertEqual(self.client.post('/api/mobile/ready').status_code,401)
        headers={'Authorization':'Bearer '+enrollment['credential']}
        self.assertEqual(self.client.post('/api/mobile/ready',headers=headers).status_code,503)
        with patch.object(app.native_fcm,'enabled',return_value=True):
            self.assertEqual(self.client.post('/api/mobile/ready',headers=headers).status_code,409)
        status=self.client.get('/api/mobile/status').json()
        with patch.object(app.native_fcm,'send_native_to_user',return_value={'sent':1}),patch.object(app.native_fcm,'enabled',return_value=True):
            self.client.post('/api/mobile/test',headers={**self.origin,'X-CSRF-Token':status['csrf_token']},json={'installation_id':enrollment['installation_id']})
            response=self.client.post('/api/mobile/ready',headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['url'],'/nurse')

    def test_expired_challenge_is_denied(self):
        from datetime import datetime, timedelta, timezone
        from native_push.registration import digest
        challenge=self.challenge()
        with app.SessionLocal() as db:
            db.get(app.NativeEnrollmentChallenge,digest(challenge)).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.enroll(challenge).status_code,403)

    def test_malformed_enrollment_is_rejected(self):
        client=TestClient(app.app,raise_server_exceptions=False)
        with client:
            self.assertEqual(client.post('/api/mobile/enroll',json=[]).status_code,400)
            self.assertEqual(client.post('/api/mobile/enroll',content='not-json',headers={'Content-Type':'application/json'}).status_code,400)

    def test_targeted_native_test_excludes_other_installations(self):
        first=self.enroll(self.challenge()).json()
        second=self.enroll(self.challenge()).json()
        status=self.client.get('/api/mobile/status').json()
        headers={**self.origin,'X-CSRF-Token':status['csrf_token']}
        with patch.object(app.native_fcm,'send_native_to_user',return_value={'sent':1}) as sender:
            response=self.client.post('/api/mobile/test',headers=headers,json={'installation_id':first['installation_id']})
            self.assertEqual(response.status_code,200)
            self.assertEqual(sender.call_args.args[3],first['installation_id'])
            self.assertEqual(self.client.post('/api/mobile/test',headers=headers,json={'installation_id':str(uuid.uuid4())}).status_code,404)
        self.user.id=9002
        self.assertEqual(self.client.post('/api/mobile/test',headers=headers,json={'installation_id':second['installation_id']}).status_code,404)

    def test_automatic_ready_requires_receipt_secret_from_push(self):
        first=self.enroll(self.challenge()).json()
        headers={'Authorization':'Bearer '+first['credential']}
        status=self.client.get('/api/mobile/status').json()
        with patch.object(app.native_fcm,'enabled',return_value=True),patch.object(app.native_fcm,'send_native_to_user',return_value={'sent':1}) as sender:
            response=self.client.post('/api/mobile/test',headers={**self.origin,'X-CSRF-Token':status['csrf_token']},json={'installation_id':first['installation_id']})
            self.assertNotIn('receipt_token',response.json())
            receipt=sender.call_args.args[2]['receipt_token']
            self.assertEqual(self.client.post('/api/mobile/ready-received',headers=headers,json={'receipt_token':'wrong'}).status_code,409)
            self.assertEqual(self.client.post('/api/mobile/ready-received',headers=headers,json={'receipt_token':receipt}).status_code,200)
            self.assertEqual(self.client.post('/api/mobile/ready-received',headers=headers,json={'receipt_token':receipt}).status_code,409)

    def test_native_login_progress_bootstraps_on_root_and_login(self):
        with patch.object(app,'current_user',return_value=None):
            for path in ('/','/login'):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200)
                self.assertIn('if(window.BurjeelNative)',response.text)
                self.assertIn('/static/native-login.js',response.text)

    def test_device_receipt_survives_session_cookie_overwrite(self):
        first=self.enroll(self.challenge()).json()
        headers={'Authorization':'Bearer '+first['credential']}
        status=self.client.get('/api/mobile/status').json()
        with patch.object(app.native_fcm,'enabled',return_value=True),patch.object(app.native_fcm,'send_native_to_user',return_value={'sent':1}) as sender:
            self.client.post('/api/mobile/test',headers={**self.origin,'X-CSRF-Token':status['csrf_token']},json={'installation_id':first['installation_id']})
            receipt=sender.call_args.args[2]['receipt_token']
            def cookie_overwritten(request,db):
                request.session.pop('native_test',None)
                return self.user
            with patch.object(app,'_mobile_user',side_effect=cookie_overwritten):
                self.assertEqual(self.client.post('/api/mobile/ready-received',headers=headers,json={'receipt_token':receipt}).status_code,200)

    def test_invalid_device_receipt_is_visible_in_error_monitor(self):
        first=self.enroll(self.challenge()).json()
        headers={'Authorization':'Bearer '+first['credential']}
        before=app.SessionLocal()
        try:before.query(app.RuntimeErrorEvent).delete();before.commit()
        finally:before.close()
        self.client.post('/api/mobile/ready-received',headers=headers,json={'receipt_token':'wrong'})
        with app.SessionLocal() as db:
            self.assertIsNotNone(db.query(app.RuntimeErrorEvent).filter_by(source='native-notifications').first())

    def test_provider_rejection_leaves_open_monitor_event(self):
        first=self.enroll(self.challenge()).json()
        status=self.client.get('/api/mobile/status').json()
        with patch.object(app.native_fcm,'send_native_to_user',return_value={'sent':0,'failed':1}):
            response=self.client.post('/api/mobile/test',headers={**self.origin,'X-CSRF-Token':status['csrf_token']},json={'installation_id':first['installation_id']})
        self.assertEqual(response.status_code,503)
        with app.SessionLocal() as db:
            self.assertIsNotNone(db.query(app.RuntimeErrorEvent).filter_by(source='native-notifications',exception_type='NativeTestSendFailed',status='open').first())
