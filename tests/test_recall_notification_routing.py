import unittest
from datetime import timedelta
from unittest.mock import patch
from test_push import app


class RecallNotificationRoutingTests(unittest.TestCase):
    def test_every_recall_targets_current_room_nurse_after_assignment_changes(self):
        with app.SessionLocal() as db:
            nurses=db.query(app.User).filter_by(role='nurse',active=True).limit(2).all()
            room=app.Room(code='RECALL-ROUTING',zone='ED Main',qr_token='recall-routing',occupied=True,assigned_nurse_id=nurses[1].id)
            db.add(room);db.flush()
            call=app.Call(room_id=room.id,assigned_nurse_id=nurses[0].id,status='new',reason='General assistance',created_at=app.now_utc()-timedelta(seconds=125))
            db.add(call);db.commit();cid=call.id;rid=room.id
            try:
                with patch.object(app,'send_push_to_user',return_value={'sent':1,'errors':[]}) as send:
                    for count in (1,2,3):
                        for log in db.query(app.AuditLog).filter_by(call_id=cid,action='PATIENT_RECALL').all():log.created_at-=timedelta(seconds=125)
                        db.commit()
                        result=app._perform_patient_recall(db,call)
                        self.assertTrue(result['ok'])
                        recalls=[c for c in send.call_args_list if c.kwargs.get('extra',{}).get('kind')=='recall']
                        self.assertEqual(len(recalls),count)
                        self.assertEqual(recalls[-1].args[1],nurses[1].id)
                        self.assertEqual(recalls[-1].kwargs['extra']['recall_count'],count)
                        self.assertEqual(recalls[-1].kwargs['extra']['call_id'],cid)
            finally:
                db.query(app.AuditLog).filter_by(call_id=cid).delete()
                db.delete(call);db.delete(room);db.commit()
