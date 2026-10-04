"""Nurse timer starts at zero and retains server elapsed time across renders."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from test_push import app
from starlette.requests import Request

class NurseTimerTests(unittest.TestCase):
    def render_call(self, age=0, stopped=False):
        now=datetime(2026,10,4,3,0,tzinfo=timezone.utc)
        # SQLite timestamps may be naive UTC; the nurse page must normalize them.
        created=(now-timedelta(seconds=age)).replace(tzinfo=None)
        c=SimpleNamespace(id=999,room_id=1,created_at=created,status='arrived' if stopped else 'new',reason='General assistance',arrived_at=created+timedelta(seconds=12) if stopped else None,resolved_at=None)
        room=SimpleNamespace(id=1,code='ED-01',zone='ED Main')
        req=Request({'type':'http','method':'GET','path':'/nurse','headers':[],'session':{},'query_string':b''})
        context=dict(request=req,current_user=SimpleNamespace(name='Test Nurse',role='nurse'),current_permissions=['my_rooms'],role_labels=app.ROLE_LABELS,rooms=[room],calls=[c],colleagues=[],pending_handovers=[],refresh_key='test',utc_iso=app._utc_iso,elapsed_for_call=app._elapsed_seconds)
        with patch.object(app,'now_utc',return_value=now):
            return app.render_template('nurse.html',context).body.decode()
    def test_new_call_starts_at_zero_with_explicit_utc(self):
        html=self.render_call()
        self.assertIn('data-created="2026-10-04T03:00:00Z" data-elapsed="0"',html)
        self.assertIn('data-call-id="999">00:00</time>',html)
    def test_reload_retains_elapsed_and_arrival_freezes_timer(self):
        html=self.render_call(65)
        self.assertIn('data-elapsed="65"',html)
        self.assertIn('data-call-id="999">01:05</time>',html)
        html=self.render_call(65,True)
        self.assertIn('data-elapsed="12"',html)
        self.assertIn('data-stop="2026-10-04T02:59:07Z"',html)
        self.assertIn('data-call-id="999">00:12</time>',html)
