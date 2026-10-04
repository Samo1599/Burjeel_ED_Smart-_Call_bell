"""Real patient page and API, with browser/server clocks advanced together."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
from test_push import app


class PatientRecallBrowserTests(unittest.TestCase):
    def test_recall_reactivates_after_each_two_minute_cooldown(self):
        for lang in ('en', 'ar'):
            with self.subTest(lang=lang):
                self.check_journey(lang)

    def check_journey(self, lang):
        clock={'now':datetime(2026,10,4,12,0,tzinfo=timezone.utc)}
        with app.SessionLocal() as db:
            room=app.Room(code='RECALL-TEST',zone='ED Main',qr_token='recall-browser-test',occupied=True)
            db.add(room);db.flush();rid=room.id
            call=app.Call(room_id=rid,status='new',reason='General assistance',created_at=clock['now'])
            db.add(call);db.commit();cid=call.id
        try:
            # SQLAlchemy's timestamp default captured the original function at import.
            # Keep real audit records, stamping them with the simulated server clock.
            original_log=app.log_action
            def log_at_clock(db,*args,**kwargs):
                original_log(db,*args,**kwargs)
                for record in db.new:
                    if isinstance(record,app.AuditLog):record.created_at=clock['now']
            with patch.object(app,'now_utc',side_effect=lambda:clock['now']),patch.object(app,'log_action',side_effect=log_at_clock),patch.object(app,'enforce_escalations'),patch.object(app,'send_push_to_user'),TestClient(app.app) as client,sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('WALLBOARD_TEST_CHROME'),args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':390,'height':844})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                def route(r):
                    u=urlsplit(r.request.url)
                    response=client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data,headers={'content-type':r.request.headers.get('content-type','text/plain')})
                    r.fulfill(status=response.status_code,headers={'content-type':response.headers.get('content-type','text/plain')},body=response.content)
                page.route('http://patient.test/**',route)
                page.clock.install(time=clock['now'])
                page.goto('http://patient.test/room/recall-browser-test?lang='+lang)
                self.assertEqual(errors,[], 'Patient JavaScript must initialize before the cooldown can run')
                self.assertEqual(page.evaluate('typeof updateRecallAvailability'),'function')
                def advance(seconds):
                    clock['now']+=timedelta(seconds=seconds)
                    page.clock.fast_forward(seconds*1000)
                    page.evaluate('async()=>{await syncPatientCallState();await silentRefreshNow("#patient-live-root",window.rebindPatientControls)}')
                for count in (1,2,3):
                    self.assertFalse(page.locator('#recallPanel').is_visible())
                    advance(119)
                    self.assertFalse(page.locator('#recallPanel').is_visible())
                    advance(1)
                    self.assertTrue(page.locator('#recallBtn').is_enabled())
                    self.assertTrue(page.locator('#recallPanel').is_visible(),page.evaluate('({now:Date.now(),panel:document.querySelector("#recallPanel").outerHTML})'))
                    page.locator('#recallBtn').click()
                    page.wait_for_function('(count)=>Number(document.querySelector("#recallPanel").dataset.recallCount)===count',arg=count)
                    self.assertFalse(page.locator('#recallPanel').is_visible())
                    with app.SessionLocal() as db:
                        self.assertEqual(app._recall_state(db,db.get(app.Call,cid))['recall_count'],count)
                    # Reopening must keep the remaining cooldown and recall count.
                    page.reload()
                    self.assertFalse(page.locator('#recallPanel').is_visible())
                advance(120)
                self.assertFalse(page.locator('#recallPanel').is_visible())
                with app.SessionLocal() as db:
                    call=db.get(app.Call,cid);call.status='arrived';call.arrived_at=clock['now'];db.commit()
                page.reload()
                self.assertEqual(page.locator('#recallPanel').count(),0)
                self.assertEqual(errors,[])
                browser.close()
        finally:
            with app.SessionLocal() as db:
                db.query(app.AuditLog).filter_by(call_id=cid).delete()
                db.query(app.Call).filter_by(id=cid).delete()
                db.query(app.Room).filter_by(id=rid).delete();db.commit()
