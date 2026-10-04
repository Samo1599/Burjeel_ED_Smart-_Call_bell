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
