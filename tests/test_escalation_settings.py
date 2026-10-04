import unittest,json,subprocess
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from test_push import app
from fastapi.testclient import TestClient

class EscalationFlowTests(unittest.TestCase):
    def setUp(self):
        self.clock=datetime(2026,10,4,4,tzinfo=timezone.utc)
        self.db=app.SessionLocal()
        self.db.query(app.EscalationSetting).delete();self.db.commit()
        self.room=self.db.query(app.Room).first()
        self.call=app.Call(room_id=self.room.id,status='acknowledged',created_at=self.clock,assigned_nurse_id=self.room.assigned_nurse_id)
        self.db.add(self.call);self.db.commit()
        self.addCleanup(self.cleanup)
    def cleanup(self):
        self.db.rollback()
        self.db.query(app.EscalationNotice).filter_by(call_id=self.call.id).delete()
        self.db.query(app.AuditLog).filter_by(call_id=self.call.id).delete()
        self.db.query(app.Call).filter_by(id=self.call.id).delete()
        self.db.query(app.EscalationSetting).delete();self.db.commit();self.db.close()
    def run_monitor(self,seconds):
        with patch.object(app,'now_utc',return_value=self.clock+timedelta(seconds=seconds)):
            app.enforce_escalations(self.db)
    def test_custom_intervals_order_once_and_ack_does_not_stop(self):
        settings={'nurse_supervisor':7,'manager':11,'ed_manager':13,'hod':17,'sound_repeat':19}
        self.db.add(app.EscalationSetting(key='timing',value=json.dumps(settings)));self.db.commit()
        roles=[]
        def notify(db,c,action,role,label,elapsed):
            roles.append(role);app.log_action(db,action,label,call=c);return 1,1
        with patch.object(app,'_notify_nursing_delay_level',side_effect=notify):
            for t in [6,7,7,17,18,18,30,31,31,47,48,100]:self.run_monitor(t)
        self.assertEqual(roles,['nurse_supervisor','manager','ed_manager','hod'])
        self.assertEqual(self.db.query(app.EscalationNotice).filter_by(call_id=self.call.id).count(),4)
    def test_arrival_cancels_remaining_stages(self):
        with patch.object(app,'_notify_nursing_delay_level') as sender:
            self.call.arrived_at=self.clock;self.db.commit();self.run_monitor(99999)
            sender.assert_not_called()
    def test_actual_push_targets_only_stage_role(self):
        people=[]
        for role in ['nurse_supervisor','manager','ed_manager','hod']:
            user=self.db.query(app.User).filter_by(role=role).first()
            if not user:
                user=app.User(name=role,email=role+'-escalation@test.local',password_hash='unused',role=role,active=True);self.db.add(user);self.db.flush();people.append(user.id)
        self.db.commit()
        try:
            with patch.object(app,'send_push_to_user',return_value={'sent':1}) as sender:
                self.run_monitor(120)
                for seconds,role in [(120,'nurse_supervisor'),(240,'manager'),(360,'ed_manager'),(480,'hod')]:
                    if seconds!=120:self.run_monitor(seconds)
                    ids=[c.args[1] for c in sender.call_args_list]
                    self.assertEqual(ids,[u.id for u in self.db.query(app.User).filter_by(role=role,active=True).all()])
                    sender.reset_mock()
        finally:
            for uid in people:self.db.query(app.User).filter_by(id=uid).delete()
            self.db.commit()
    def test_monitor_roles_forbidden_even_with_custom_admin_profile(self):
        admin=self.db.query(app.User).filter_by(role='admin').first()
        for role in ['manager','ed_manager','hod']:
            with patch.object(app,'get_user_access_profile',return_value=type('P',(),{'permissions_json':json.dumps([x[0] for x in app.PERMISSION_DEFS])})()),patch.object(app,'current_user',return_value=type('U',(),{'id':admin.id,'role':role,'name':'Monitor'})()),TestClient(app.app) as client:
                page=client.get('/charge');self.assertEqual(page.status_code,200)
                self.assertNotIn('onclick="openOpsReassign',page.text)
                self.assertNotIn('>Take Over</button>',page.text)
                for action in ['ack','arrive','resolve','takeover']:
                    self.assertEqual(client.post(f'/api/call/{self.call.id}/{action}').status_code,403)
                self.assertEqual(client.post('/api/handover',json={}).status_code,403)
                self.assertEqual(client.post('/admin/escalation-settings',data={}).status_code,403)
    def test_admin_settings_persist_arbitrary_duration_validation_and_ui(self):
        admin=self.db.query(app.User).filter_by(role='admin').first()
        form={}
        for key in app.ESCALATION_DEFAULTS:form[key+'_minutes']='7';form[key+'_seconds']='23'
        with patch.object(app,'current_user',side_effect=lambda request,db:db.get(app.User,admin.id)),TestClient(app.app) as client:
            self.assertEqual(client.post('/admin/escalation-settings',data=form,follow_redirects=False).status_code,303)
            self.db.expire_all();self.assertEqual(app.escalation_settings(self.db)['ed_manager'],443)
            page=client.get('/admin');self.assertEqual(page.status_code,200);self.assertIn('Save timing settings',page.text)
            form['hod_seconds']='60'
            self.assertEqual(client.post('/admin/escalation-settings',data=form).status_code,400)
            self.assertEqual(app.escalation_settings(self.db)['hod'],443)
            self.assertEqual(client.get('/api/wallboard').json()['sound_repeat_seconds'],443)

    def test_wallboard_repeat_behavior(self):
        subprocess.run(['node','tests/test_wallboard_repeat.js'],cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True)
