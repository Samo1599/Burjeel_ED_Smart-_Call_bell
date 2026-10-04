"""Slow database/provider work must leave the ASGI event loop responsive."""
import asyncio
import threading
import time
import unittest
from unittest.mock import patch
from starlette.requests import Request
from starlette.responses import Response
from test_push import app


class EventLoopResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_escalation_scan_does_not_stop_heartbeat(self):
        release=threading.Event()
        def slow_scan(db):release.wait(.25)
        with patch.object(app,'enforce_escalations',side_effect=slow_scan):
            start=time.monotonic()
            task=asyncio.create_task(app.nursing_delay_monitor_loop())
            try:
                await asyncio.sleep(.02)
                self.assertLess(time.monotonic()-start,.15)
            finally:
                release.set();task.cancel()
                try:await task
                except asyncio.CancelledError:pass
                await asyncio.sleep(.02)

    async def test_diagnostic_database_write_does_not_stop_heartbeat(self):
        async def response(request):return Response(status_code=200)
        async def heartbeat():
            await asyncio.sleep(.02)
            return time.monotonic()
        with patch.object(app,'_mark_runtime_recovered',side_effect=lambda path:time.sleep(.25)):
            start=time.monotonic()
            beat=asyncio.create_task(heartbeat())
            await app.system_error_monitor(Request({'type':'http','path':'/test','headers':[]}),response)
            self.assertLess((await beat)-start,.15)
