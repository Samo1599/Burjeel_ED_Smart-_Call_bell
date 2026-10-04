"""Regression for the endpoint used by the charge reassignment dialog."""
import unittest
from unittest.mock import patch
from test_push import app
from fastapi.testclient import TestClient


class OperationalReassignmentTests(unittest.TestCase):
    def test_specific_reassign_route_updates_nurse_without_resetting_timer(self):
        with app.SessionLocal() as db:
            admin=db.query(app.User).filter_by(role='admin').first()
            nurses=db.query(app.User).filter_by(role='nurse',active=True).limit(2).all()
            room=db.query(app.Room).first()
            original_assignment=room.assigned_nurse_id
            created=app.now_utc()
            call=app.Call(room_id=room.id,assigned_nurse_id=nurses[0].id,status='new',reason='General assistance',created_at=created)
            db.add(call);db.commit();cid=call.id;room_id=room.id;target=nurses[1].id;uid=admin.id
            stamp=db.get(app.Call,cid).created_at
        try:
            with patch.object(app,'current_user',side_effect=lambda request,db:db.get(app.User,uid)),TestClient(app.app) as client:
                response=client.post(f'/api/call/{cid}/reassign',json={'nurse_id':target,'reason':'Workload balancing'})
                self.assertEqual(response.status_code,200,response.text)
            with app.SessionLocal() as db:
                call=db.get(app.Call,cid)
                self.assertEqual(call.assigned_nurse_id,target)
                self.assertEqual(app._utc_iso(call.created_at),app._utc_iso(stamp))
        finally:
            with app.SessionLocal() as db:
                db.query(app.Call).filter_by(id=cid).delete()
                db.get(app.Room,room_id).assigned_nurse_id=original_assignment
                db.commit()

class WallboardRecallPayloadTests(unittest.TestCase):
    def test_patient_recall_is_visible_to_live_screen_without_new_call_id(self):
        from datetime import timedelta
        with app.SessionLocal() as db:
            room=db.query(app.Room).first()
            call=app.Call(room_id=room.id,assigned_nurse_id=room.assigned_nurse_id,status='new',reason='General assistance',created_at=app.now_utc()-timedelta(seconds=125))
            db.add(call);db.commit();cid=call.id
            try:
                with patch.object(app,'enforce_escalations'),patch.object(app,'send_push_to_user'):
                    before=next(c for c in app.wallboard_payload(db)['calls'] if c['id']==cid)
                    self.assertEqual(before['recall_count'],0)
                    self.assertTrue(app._perform_patient_recall(db,call)['ok'])
                    after=next(c for c in app.wallboard_payload(db)['calls'] if c['id']==cid)
                    self.assertEqual(after['recall_count'],1)
                    self.assertEqual(after['created_at'],before['created_at'])
            finally:
                db.query(app.AuditLog).filter_by(call_id=cid).delete()
                db.delete(call);db.commit()
