import os, json, hashlib, secrets, base64, io
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware
from jinja2 import Environment, DictLoader, select_autoescape
import qrcode
import qrcode.image.svg
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

try:
    from pywebpush import webpush, WebPushException
except Exception:
    webpush = None
    WebPushException = Exception

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_URL = os.getenv('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR,'callbell.db')}")
if DB_URL.startswith('postgres://'): DB_URL = DB_URL.replace('postgres://','postgresql+psycopg://',1)
if DB_URL.startswith('postgresql://'): DB_URL = DB_URL.replace('postgresql://','postgresql+psycopg://',1)
if DB_URL.startswith('postgresql+psycopg://'):
    engine = create_engine(DB_URL, connect_args={"options":"-csearch_path=burjeel_ed_call"}, future=True)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS burjeel_ed_call"))
else:
    engine = create_engine(DB_URL, connect_args={'check_same_thread':False} if DB_URL.startswith('sqlite') else {}, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()
SLA_SECONDS = int(os.getenv('SLA_SECONDS','120'))
VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY','')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY','')
VAPID_SUBJECT = os.getenv('VAPID_SUBJECT','mailto:it@example.com')

app = FastAPI(title='Burjeel ED Smart Call')
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SECRET_KEY','dev-secret-change-me'))

TEMPLATES = {
    "base.html": "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\"><title>{% block title %}Burjeel ED Call{% endblock %}</title><link rel=\"manifest\" href=\"/manifest.webmanifest\"><meta name=\"theme-color\" content=\"#004f9e\"><link rel=\"apple-touch-icon\" href=\"/static/icons/icon-192.png\"><link rel=\"stylesheet\" href=\"/static/app.css\"></head><body><header class=\"topbar\"><div class=\"brand\"><img src=\"/static/icons/icon-192.png\" alt=\"logo\"><div><b>Burjeel ED Call</b><span>Smart Call Bell</span></div></div>{% if current_user %}<div class=\"userbox\"><span>{{ current_user.name }}</span><small>{{ current_user.role.replace('_',' ')|title }}</small><a href=\"/logout\">Logout</a></div>{% endif %}</header>{% if current_user %}<nav class=\"nav\">{% if current_user.role in ['nurse','charge'] %}<a href=\"/nurse\">My Rooms</a>{% endif %}{% if current_user.role in ['charge','manager','ed_manager','admin'] %}<a href=\"/charge\">Live Board</a>{% endif %}<a href=\"/wallboard\">📺 Call Bell Screen</a>{% if current_user.role in ['manager','ed_manager','admin'] %}<a href=\"/manager\">Management</a>{% endif %}{% if current_user.role == 'admin' %}<a href=\"/admin\">Admin</a>{% endif %}</nav>{% endif %}<main class=\"container\">{% block content %}{% endblock %}</main><script>window.VAPID_PUBLIC_KEY='{{ vapid_public_key|default('') }}';</script><script src=\"/static/app.js\"></script>{% block scripts %}{% endblock %}</body></html>",
    "login.html": "{% extends 'base.html' %}{% block title %}Sign in - Burjeel ED Call{% endblock %}{% block content %}<section class=\"login-shell\"><div class=\"login-card\"><img class=\"hero-logo\" src=\"/static/icons/icon-512.png\"><h1>ED Smart Call Bell</h1><p>Secure staff access</p>{% if error %}<div class=\"alert danger\">{{ error }}</div>{% endif %}<form method=\"post\" action=\"/login\"><label>Email<input name=\"email\" type=\"email\" required placeholder=\"sara@demo.local\"></label><label>Password<input name=\"password\" type=\"password\" required placeholder=\"••••••••\"></label><button class=\"btn primary wide\">Sign in</button></form><div class=\"demo\"><b>Demo</b><span>sara@demo.local / Demo123!</span><span>charge@demo.local / Demo123!</span><span>manager@demo.local / Demo123!</span></div></div></section>{% endblock %}",
    "nurse.html": "{% extends 'base.html' %}{% block title %}My Rooms - Burjeel ED Call{% endblock %}{% block content %}<div class=\"page-head\"><div><div class=\"eyebrow\">Nurse workspace</div><h1>My Rooms</h1><p>Assigned rooms and live patient calls.</p></div><button class=\"btn secondary\" onclick=\"enablePush()\">Enable notifications</button></div><div class=\"stats\"><div class=\"stat\"><b>{{ rooms|length }}</b><span>Assigned rooms</span></div><div class=\"stat red\"><b>{{ calls|length }}</b><span>Active calls</span></div><div class=\"stat amber\"><b>{{ pending_handovers|length }}</b><span>Pending handovers</span></div></div>{% if pending_handovers %}<section class=\"panel\"><h2>Handover requests</h2>{% for h in pending_handovers %}<div class=\"list-row\"><b>{{h.room.code}}</b><span>From {{h.from_nurse.name}}</span><button class=\"btn primary\" onclick=\"acceptHandover({{h.id}})\">Accept</button></div>{% endfor %}</section><br>{% endif %}<section class=\"grid rooms\">{% for room in rooms %}<article class=\"room-card {% if calls|selectattr('room_id','equalto',room.id)|list %}hot{% endif %}\"><div class=\"room-top\"><b>{{ room.code }}</b><span>{{ room.zone }}</span></div>{% set rcalls = calls|selectattr('room_id','equalto',room.id)|list %}{% if rcalls %}{% set c=rcalls[0] %}<div class=\"call-status {{ c.status }}\">{{ c.status.replace('_',' ')|upper }}</div><div class=\"timer\" data-created=\"{{ c.created_at.isoformat() }}\" data-call-id=\"{{ c.id }}\">00:00</div><p>{{ c.reason }}</p><div class=\"actions\">{% if c.status in ['new','escalated'] %}<button class=\"btn primary\" onclick=\"callAction({{c.id}},'ack')\">Acknowledge</button>{% endif %}{% if c.status in ['acknowledged','taken_over','escalated'] %}<button class=\"btn success\" onclick=\"callAction({{c.id}},'arrive')\">Arrived</button>{% endif %}{% if c.status=='arrived' %}<button class=\"btn success\" onclick=\"callAction({{c.id}},'resolve')\">Resolve</button>{% endif %}</div>{% else %}<div class=\"ready\">● Ready</div><p class=\"muted\">No active patient call</p>{% endif %}{% if colleagues %}<div class=\"handover-box\"><select id=\"handover-{{room.id}}\"><option value=\"\">Hand over to…</option>{% for n in colleagues %}<option value=\"{{n.id}}\">{{n.name}}</option>{% endfor %}</select><button class=\"btn secondary\" onclick=\"handoverRoom({{room.id}})\">Handover</button></div>{% endif %}</article>{% endfor %}</section>{% endblock %}",
    "charge.html": "{% extends 'base.html' %}{% block title %}Charge Nurse Live Board{% endblock %}{% block content %}\n<div class=\"page-head\"><div><div class=\"eyebrow\">Charge Nurse Command</div><h1>ED Live Call Board</h1><p>All active calls, escalations, ownership and room assignment.</p></div><button class=\"btn secondary\" onclick=\"enablePush()\">Enable notifications</button></div>\n<div class=\"stats\"><div class=\"stat\"><b>{{ rooms|length }}</b><span>Rooms</span></div><div class=\"stat red\"><b>{{ calls|length }}</b><span>Open calls</span></div><div class=\"stat amber\"><b>{{ calls|selectattr('status','equalto','escalated')|list|length }}</b><span>Escalated</span></div></div>\n<section class=\"grid rooms\">\n{% for room in rooms %}{% set rcalls=calls|selectattr('room_id','equalto',room.id)|list %}\n<article class=\"room-card {% if rcalls %}hot{% endif %}\">\n  <div class=\"room-top\"><b>{{room.code}}</b><span>{{room.zone}}</span></div>\n  <div class=\"assignment\">Assigned: <b>{{ room.assigned_nurse.name if room.assigned_nurse else 'Unassigned' }}</b></div>\n  {% if rcalls %}{% set c=rcalls[0] %}\n    <div class=\"call-status {{c.status}}\">{{c.status.replace('_',' ')|upper}}</div>\n    <div class=\"timer\" data-created=\"{{ c.created_at.isoformat() }}\" data-call-id=\"{{c.id}}\">00:00</div>\n    <p>{{c.reason}}</p>\n    {% if c.escalation_reason %}<div class=\"alert danger small\">{{c.escalation_reason}}</div>{% endif %}\n    <div class=\"actions\">\n      {% if c.status in ['new','escalated'] %}<button class=\"btn danger\" onclick=\"callAction({{c.id}},'takeover')\">Take Over</button>{% endif %}\n      {% if c.status in ['taken_over','acknowledged','escalated'] %}<button class=\"btn success\" onclick=\"callAction({{c.id}},'arrive')\">Arrived</button>{% endif %}\n      {% if c.status=='arrived' %}<button class=\"btn success\" onclick=\"callAction({{c.id}},'resolve')\">Resolve</button>{% endif %}\n    </div>\n    {% if c.status in ['new','acknowledged','escalated','taken_over'] %}\n    <div class=\"reassign-box\">\n      <div class=\"reassign-title\"><b>Reassign Nurse</b><span>Original call timer continues</span></div>\n      <select id=\"reassign-nurse-{{c.id}}\">\n        <option value=\"\">Select active nurse…</option>\n        {% for n in nurses %}<option value=\"{{n.id}}\" {% if c.assigned_nurse_id==n.id %}disabled{% endif %}>{{n.name}}{% if c.assigned_nurse_id==n.id %} (Current){% endif %}</option>{% endfor %}\n      </select>\n      <select id=\"reassign-reason-{{c.id}}\">\n        <option value=\"\">Reason…</option>\n        <option>Workload balancing</option><option>Break</option><option>Shift change</option><option>No response</option><option>Clinical priority</option><option>Other</option>\n      </select>\n      <button class=\"btn secondary\" onclick=\"reassignCall({{c.id}})\">Reassign</button>\n    </div>\n    {% endif %}\n  {% else %}\n    <div class=\"ready\">● Ready</div>\n    <select onchange=\"assignRoom({{room.id}},this.value)\"><option value=\"\">Reassign nurse…</option>{% for n in nurses %}<option value=\"{{n.id}}\">{{n.name}}</option>{% endfor %}</select>\n  {% endif %}\n</article>{% endfor %}\n</section>{% endblock %}",
    "manager.html": "{% extends 'base.html' %}{% block title %}KPI Management{% endblock %}\n{% block content %}\n<div class=\"page-head\">\n  <div><div class=\"eyebrow\">Operational oversight & analytics</div><h1>KPI Management</h1><p>Call-bell performance, SLA compliance, nurse workload, room performance and downloadable reports.</p></div>\n  <div class=\"manager-export-actions\"><a class=\"btn primary\" href=\"/manager/export.xlsx?{{filter_qs}}\">Export Excel</a><a class=\"btn secondary\" href=\"/manager/export.pdf?{{filter_qs}}\">Export PDF</a></div>\n</div>\n\n<form class=\"manager-filter panel\" method=\"get\" action=\"/manager\">\n  <div class=\"period-buttons\">\n    <button name=\"period\" value=\"today\" class=\"filter-chip {{'active' if period=='today' else ''}}\">Today</button>\n    <button name=\"period\" value=\"week\" class=\"filter-chip {{'active' if period=='week' else ''}}\">Weekly</button>\n    <button name=\"period\" value=\"month\" class=\"filter-chip {{'active' if period=='month' else ''}}\">Monthly</button>\n    <button type=\"button\" class=\"filter-chip {{'active' if period=='custom' else ''}}\" onclick=\"document.getElementById('customDates').classList.toggle('show')\">Custom Date</button>\n  </div>\n  <div id=\"customDates\" class=\"custom-dates {{'show' if period=='custom' else ''}}\">\n    <label>From <input type=\"date\" name=\"from\" value=\"{{from_date}}\"></label>\n    <label>To <input type=\"date\" name=\"to\" value=\"{{to_date}}\"></label>\n    <button class=\"btn primary\" name=\"period\" value=\"custom\">Apply</button>\n  </div>\n</form>\n\n<div class=\"stats kpi-stats\">\n  <div class=\"stat\"><b>{{kpi.total}}</b><span>Total calls</span></div>\n  <div class=\"stat\"><b>{{kpi.avg_response}}</b><span>Avg response</span></div>\n  <div class=\"stat\"><b>{{kpi.median_response}}</b><span>Median response</span></div>\n  <div class=\"stat amber\"><b>{{kpi.over_2m}}</b><span>Calls over 2 min</span></div>\n  <div class=\"stat red\"><b>{{kpi.over_5m}}</b><span>Calls over 5 min</span></div>\n  <div class=\"stat\"><b>{{kpi.escalations}}</b><span>Escalations</span></div>\n  <div class=\"stat\"><b>{{kpi.takeovers}}</b><span>Charge takeovers</span></div>\n  <div class=\"stat\"><b>{{kpi.sla_rate}}</b><span>SLA compliance</span></div>\n</div>\n\n<div class=\"manager-grid\">\n<section class=\"panel\">\n  <div class=\"section-head\"><div><h2>Nurse Performance</h2><p class=\"muted\">Call volume, average response and escalation exposure.</p></div></div>\n  <div class=\"table-wrap\"><table><thead><tr><th>Nurse</th><th>Calls</th><th>Avg response</th><th>Over SLA</th><th>Escalated</th></tr></thead><tbody>\n  {% for n in nurse_perf %}<tr><td><b>{{n.name}}</b></td><td>{{n.calls}}</td><td>{{n.avg_response}}</td><td>{{n.over_sla}}</td><td>{{n.escalated}}</td></tr>{% endfor %}\n  {% if not nurse_perf %}<tr><td colspan=\"5\" class=\"muted\">No calls in this period.</td></tr>{% endif %}\n  </tbody></table></div>\n</section>\n\n<section class=\"panel\">\n  <div class=\"section-head\"><div><h2>Room Performance</h2><p class=\"muted\">Demand and response by room.</p></div></div>\n  <div class=\"table-wrap\"><table><thead><tr><th>Room</th><th>Zone</th><th>Calls</th><th>Avg response</th><th>SLA breaches</th></tr></thead><tbody>\n  {% for r in room_perf %}<tr><td><b>{{r.room}}</b></td><td>{{r.zone}}</td><td>{{r.calls}}</td><td>{{r.avg_response}}</td><td>{{r.over_sla}}</td></tr>{% endfor %}\n  {% if not room_perf %}<tr><td colspan=\"5\" class=\"muted\">No calls in this period.</td></tr>{% endif %}\n  </tbody></table></div>\n</section>\n</div>\n\n<section class=\"panel management-call-table\">\n  <div class=\"section-head\"><div><h2>Call Lifecycle</h2><p class=\"muted\">{{range_label}} · Created → Acknowledged → Arrived → Resolved</p></div></div>\n  <div class=\"table-wrap\"><table><thead><tr><th>Room</th><th>Created</th><th>Primary nurse</th><th>Status</th><th>Response</th><th>Total duration</th><th>Escalated</th><th>Takeover</th><th>Reason</th></tr></thead><tbody>\n  {% for c in call_rows %}<tr><td><b>{{c.room}}</b><br><small>{{c.zone}}</small></td><td>{{c.created}}</td><td>{{c.nurse}}</td><td><span class=\"badge {{c.status}}\">{{c.status_label}}</span></td><td>{{c.response}}</td><td>{{c.duration}}</td><td>{{c.escalated}}</td><td>{{c.takeover}}</td><td>{{c.reason}}</td></tr>{% endfor %}\n  {% if not call_rows %}<tr><td colspan=\"9\" class=\"muted\">No calls in this period.</td></tr>{% endif %}\n  </tbody></table></div>\n</section>\n{% endblock %}",
    "admin.html": "{% extends 'base.html' %}{% block title %}Admin Control Panel{% endblock %}\n{% block content %}\n<div class=\"page-head\"><div><div class=\"eyebrow\">System administration</div><h1>Control Panel</h1><p>Staff, rooms, assignments, QR codes, notifications and audit visibility.</p></div><div class=\"status-pill {{ 'ok' if vapid_ready else 'warn' }}\">{{ 'Push configured' if vapid_ready else 'Push not configured' }}</div></div>\n<div class=\"stats four\"><div class=\"stat\"><b>{{ users|length }}</b><span>Staff accounts</span></div><div class=\"stat\"><b>{{ rooms|length }}</b><span>Rooms</span></div><div class=\"stat red\"><b>{{ active_calls }}</b><span>Active calls</span></div><div class=\"stat amber\"><b>{{ push_count }}</b><span>Push devices</span></div></div>\n<div class=\"admin-tabs\"><a href=\"#staff\">Staff</a><a href=\"#rooms\">Rooms & QR</a><a href=\"#audit\">Audit log</a><a href=\"#system\">System</a></div>\n\n<section id=\"staff\" class=\"panel admin-section\"><div class=\"section-head\"><div><h2>Staff & Roles</h2><p class=\"muted\">Create staff accounts, enable/disable access and reset passwords.</p></div></div>\n<form class=\"admin-form grid-form\" method=\"post\" action=\"/admin/users\"><input name=\"name\" placeholder=\"Full name\" required><input name=\"email\" type=\"email\" placeholder=\"Email\" required><select name=\"role\" required><option value=\"nurse\">Nurse</option><option value=\"charge\">Nurse In Charge</option><option value=\"manager\">Nurse Manager</option><option value=\"ed_manager\">ED Manager</option><option value=\"admin\">System Admin</option></select><input name=\"password\" type=\"password\" placeholder=\"Temporary password (8+ chars)\" minlength=\"8\" required><button class=\"btn primary\">Add staff</button></form>\n<div class=\"table-wrap\"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead><tbody>{% for u in users %}<tr><td><b>{{u.name}}</b></td><td>{{u.email}}</td><td>{{u.role.replace('_',' ')|title}}</td><td><span class=\"badge {{'resolved' if u.active else 'new'}}\">{{'Active' if u.active else 'Disabled'}}</span></td><td><div class=\"row-actions\"><form method=\"post\" action=\"/admin/users/{{u.id}}/toggle\"><button class=\"btn secondary\" {% if u.id==current_user.id %}disabled title=\"You cannot disable your own account\"{% endif %}>{{'Disable' if u.active else 'Enable'}}</button></form><form method=\"post\" action=\"/admin/users/{{u.id}}/reset\"><input name=\"password\" type=\"password\" placeholder=\"New password\" minlength=\"8\" required><button class=\"btn secondary\">Reset</button></form></div></td></tr>{% endfor %}</tbody></table></div></section>\n\n<section id=\"rooms\" class=\"panel admin-section\"><div class=\"section-head\"><div><h2>Rooms, Assignments & QR</h2><p class=\"muted\">Patient links stay hidden behind simple QR controls. Open View QR to display or print the room poster.</p></div></div>\n<form class=\"admin-form grid-form\" method=\"post\" action=\"/admin/rooms\"><input name=\"code\" placeholder=\"Room code e.g. ED-09\" required><input name=\"zone\" placeholder=\"Zone e.g. ED Main\" required><select name=\"nurse_id\"><option value=\"\">Unassigned</option>{% for n in nurses %}<option value=\"{{n.id}}\">{{n.name}}</option>{% endfor %}</select><button class=\"btn primary\">Add room</button></form>\n{% if room_msg %}<div class=\"admin-room-msg {{'error' if room_msg_type=='error' else 'success'}}\">{{room_msg}}</div>{% endif %}\n<div class=\"table-wrap\"><table><thead><tr><th>Room / Zone</th><th>Nurse</th><th>Status</th><th>QR Code</th><th>Actions</th></tr></thead><tbody>\n{% for r in rooms %}<tr>\n<td>\n  <form class=\"room-edit-form\" method=\"post\" action=\"/admin/rooms/{{r.id}}/edit\">\n    <input name=\"code\" value=\"{{r.code}}\" maxlength=\"40\" aria-label=\"Room name\" required>\n    <input name=\"zone\" value=\"{{r.zone}}\" maxlength=\"80\" aria-label=\"Zone\" required>\n    <button class=\"btn secondary\">Save name</button>\n  </form>\n</td>\n<td><form class=\"inline-form\" method=\"post\" action=\"/admin/rooms/{{r.id}}/assign\"><select name=\"nurse_id\"><option value=\"\">Unassigned</option>{% for n in nurses %}<option value=\"{{n.id}}\" {% if r.assigned_nurse_id==n.id %}selected{% endif %}>{{n.name}}</option>{% endfor %}</select><button class=\"btn secondary\">Save</button></form></td>\n<td><span class=\"badge {{'resolved' if r.occupied else 'new'}}\">{{'Active' if r.occupied else 'Closed'}}</span></td>\n<td><div class=\"row-actions\"><a class=\"btn primary qr-action\" href=\"/admin/rooms/{{r.id}}/qr\" target=\"_blank\">View QR</a><a class=\"btn secondary qr-action\" href=\"/admin/rooms/{{r.id}}/qr?print=1\" target=\"_blank\">Print QR</a></div></td>\n<td><div class=\"row-actions\"><form method=\"post\" action=\"/admin/rooms/{{r.id}}/toggle\"><button class=\"btn secondary\">{{'Close' if r.occupied else 'Open'}}</button></form><form method=\"post\" action=\"/admin/rooms/{{r.id}}/token\"><button class=\"btn secondary\">Regenerate QR</button></form><form method=\"post\" action=\"/admin/rooms/{{r.id}}/delete\" onsubmit=\"return confirm('Delete room {{r.code}}? This is only allowed when the room has no call or handover history.');\"><button class=\"btn danger room-delete-btn\">Delete</button></form></div></td>\n</tr>{% endfor %}\n</tbody></table></div></section>\n\n<section id=\"audit\" class=\"panel admin-section\"><div class=\"section-head\"><div><h2>Audit Log</h2><p class=\"muted\">Latest 100 recorded workflow and administration actions.</p></div></div><div class=\"table-wrap\"><table><thead><tr><th>Time</th><th>Action</th><th>User</th><th>Room</th><th>Detail</th></tr></thead><tbody>{% for a in audit_logs %}<tr><td>{{a.created_at.strftime('%Y-%m-%d %H:%M:%S')}}</td><td><b>{{a.action}}</b></td><td>{{a.user.name if a.user else '-'}}</td><td>{{a.room_id or '-'}}</td><td>{{a.detail or '-'}}</td></tr>{% endfor %}</tbody></table></div></section>\n<section id=\"system\" class=\"panel admin-section\"><h2>System Status</h2><div class=\"system-grid\"><div><span>Database</span><b>Connected</b></div><div><span>SLA</span><b>{{sla_seconds}} sec</b></div><div><span>Web Push</span><b>{{'Configured' if vapid_ready else 'Not configured'}}</b></div><div><span>App mode</span><b>Single-file app.py</b></div></div></section>\n{% endblock %}",
    "qr.html": "{% extends 'base.html' %}{% block title %}{{room.code}} QR Code{% endblock %}{% block content %}\n<section class=\"qr-shell\"><div class=\"qr-poster\"><img class=\"qr-logo\" src=\"/static/icons/icon-512.png\"><div class=\"eyebrow\">{{room.zone}}</div><h1>{{room.code}}</h1><h2>Scan to call your nurse</h2><p class=\"qr-ar\" dir=\"rtl\">امسح الكود لاستدعاء الممرضة</p><img class=\"qr-image\" src=\"data:image/svg+xml;base64,{{qr_data}}\" alt=\"QR code for {{room.code}}\"><p class=\"muted\">Point your phone camera at the QR code.</p><p class=\"qr-ar muted\" dir=\"rtl\">وجّه كاميرا الهاتف إلى رمز QR.</p><div class=\"qr-print-actions\"><button class=\"btn primary\" onclick=\"window.print()\">Print QR</button><a class=\"btn secondary\" href=\"/admin#rooms\">Back</a></div></div></section>\n{% if auto_print %}<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),300));</script>{% endif %}\n{% endblock %}",
    "patient.html": "{% extends 'base.html' %}{% block title %}{{ room.code }} - {{ t.page_title }}{% endblock %}\n{% block content %}\n<section class=\"patient-shell patient-lang\" dir=\"{{ 'rtl' if lang=='ar' else 'ltr' }}\"><div class=\"patient-card\">\n<div class=\"patient-lang-switch\" dir=\"ltr\"><button class=\"lang-chip {{'active' if lang=='en' else ''}}\" onclick=\"setPatientLang('en')\">EN</button><span>•</span><button class=\"lang-chip {{'active' if lang=='ar' else ''}}\" onclick=\"setPatientLang('ar')\">ع</button></div>\n<img class=\"hero-logo\" src=\"/static/icons/icon-512.png\"><div class=\"eyebrow\">{{ room.zone }}</div><h1>{{ room.code }}</h1>\n<h2 class=\"patient-question\">{{ t.help_title }}</h2><p class=\"muted patient-note\">{{ t.help_note }}</p>\n<div id=\"patient-state\">{% if active_call %}\n<div class=\"call-active\"><div class=\"pulse\"></div><h2>{{ t.call_active }}</h2><div class=\"timer\" data-created=\"{{ active_call.created_at.isoformat() }}\" data-call-id=\"{{ active_call.id }}\">00:00</div><p id=\"patientStatus\">{{ status_label }}</p><p class=\"muted\">{{ t.wait_note }}</p></div>\n{% else %}\n<div class=\"reason-grid\"><button class=\"reason selected\" data-reason=\"General assistance\"><span class=\"reason-icon\">🤝</span><span>{{t.general}}</span></button><button class=\"reason\" data-reason=\"Pain\"><span class=\"reason-icon\">❤️‍🩹</span><span>{{t.pain}}</span></button><button class=\"reason\" data-reason=\"Toilet assistance\"><span class=\"reason-icon\">🚻</span><span>{{t.toilet}}</span></button><button class=\"reason\" data-reason=\"IV / Medication\"><span class=\"reason-icon\">💧</span><span>{{t.medication}}</span></button></div>\n<button id=\"callBtn\" class=\"call-btn\" aria-label=\"{{t.call_nurse}}\">🔔<span>{{ t.call_nurse }}</span></button><p id=\"callMessage\" class=\"muted\"></p>\n{% endif %}</div>\n<div class=\"physical-note\">⚠️ {{ t.physical_note }}</div></div></section>\n{% endblock %}\n{% block scripts %}<script>\nconst patientLang='{{lang}}'; const qs=new URLSearchParams(location.search); const stored=localStorage.getItem('edcall-lang');\nif(!qs.has('lang')&&stored&&stored!==patientLang){const u=new URL(location.href);u.searchParams.set('lang',stored);location.replace(u.toString());}\nfunction setPatientLang(l){localStorage.setItem('edcall-lang',l);const u=new URL(location.href);u.searchParams.set('lang',l);location.href=u.toString();}\nlet reason='General assistance';document.querySelectorAll('.reason').forEach(b=>b.onclick=()=>{document.querySelectorAll('.reason').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');reason=b.dataset.reason;});\nconst btn=document.getElementById('callBtn');if(btn)btn.onclick=async()=>{btn.disabled=true;const r=await fetch('/api/room/{{room.qr_token}}/call',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});const d=await r.json();if(d.ok){location.reload()}else{document.getElementById('callMessage').textContent='{{t.error}}';btn.disabled=false;}};\n</script>{% endblock %}",
"wallboard.html": "{% extends 'base.html' %}{% block title %}Call Bell Screen{% endblock %}\n{% block content %}\n<section class=\"wallboard-shell\" data-lang=\"{{lang}}\">\n  <div class=\"wallboard-head\">\n    <div><div class=\"eyebrow\">{{ t.kicker }}</div><h1>{{ t.title }}</h1><p>{{ t.subtitle }}</p></div>\n    <div class=\"wallboard-tools\">\n      <div class=\"wall-clock\" id=\"wallClock\">--:--:--</div>\n      <div class=\"view-switch\" title=\"Display mode\">\n        <button class=\"view-btn\" data-view=\"compact\" onclick=\"setWallView('compact',this)\">▦ {{t.compact}}</button>\n        <button class=\"view-btn\" data-view=\"cards\" onclick=\"setWallView('cards',this)\">▤ {{t.cards}}</button>\n        <button class=\"view-btn\" data-view=\"list\" onclick=\"setWallView('list',this)\">☷ {{t.list}}</button>\n        <button class=\"view-btn\" data-view=\"zones\" onclick=\"setWallView('zones',this)\">▥ {{t.zones}}</button>\n      </div>\n      <div class=\"lang-mini\" dir=\"ltr\"><a class=\"{{'active' if lang=='en' else ''}}\" href=\"/wallboard?lang=en\">EN</a><span>•</span><a class=\"{{'active' if lang=='ar' else ''}}\" href=\"/wallboard?lang=ar\">ع</a></div>\n      <button id=\"soundBtn\" class=\"btn primary\" onclick=\"enableWallboardSound()\">🔊 {{t.enable_sound}}</button>\n      <button class=\"btn secondary\" onclick=\"toggleWallFullscreen()\">⛶ {{t.fullscreen}}</button>\n    </div>\n  </div>\n\n  <div class=\"wall-stats\">\n    <div class=\"wall-stat\"><span>{{t.total_rooms}}</span><b id=\"statRooms\">{{stats.total_rooms}}</b></div>\n    <div class=\"wall-stat\"><span>{{t.active_calls}}</span><b id=\"statActive\">{{stats.active}}</b></div>\n    <div class=\"wall-stat danger\"><span>{{t.escalated}}</span><b id=\"statEscalated\">{{stats.escalated}}</b></div>\n    <div class=\"wall-stat overdue\"><span>{{t.over_sla}}</span><b id=\"statOverSla\">{{stats.over_sla}}</b></div>\n    <div class=\"wall-stat\"><span>{{t.avg_response}}</span><b id=\"statAvg\">{{stats.avg_response}}</b></div>\n    <div class=\"wall-stat\"><span>{{t.unassigned}}</span><b id=\"statUnassigned\">{{stats.unassigned}}</b></div>\n  </div>\n\n  <div class=\"wall-filters\">\n    <button class=\"filter-chip active\" onclick=\"setWallFilter('all',this)\">{{t.all}}</button>\n    {% for z in zones %}<button class=\"filter-chip\" onclick=\"setWallFilter('{{z}}',this)\">{{z}}</button>{% endfor %}\n    <label class=\"show-idle\"><input id=\"idleToggle\" type=\"checkbox\" checked onchange=\"toggleIdle(this.checked)\"> {{t.show_idle}}</label>\n    <span class=\"wall-live\">● LIVE</span><span id=\"wallConnection\" class=\"wall-connection\">{{t.connected}}</span>\n  </div>\n\n  <div id=\"wallRooms\" class=\"wall-room-grid view-compact\">\n    {% for r in rooms_view %}\n    <article class=\"wall-room-card status-{{r.status}} {% if r.over_sla %}sla-breach{% endif %}\" data-zone=\"{{r.zone}}\" data-status=\"{{r.status}}\" data-room=\"{{r.room}}\">\n      <div class=\"wall-room-top\"><div><b>{{r.room}}</b><span>{{r.zone}}</span></div><span class=\"wall-badge\">{{r.status_label}}</span></div>\n      <div class=\"wall-room-body\">\n        <div class=\"room-reason\">{{r.reason_label}}</div>\n        <div class=\"room-meta\"><span>{{t.assigned_nurse}}</span><b>{{r.nurse}}</b></div>\n        <div class=\"room-meta room-elapsed\"><span>{{t.elapsed}}</span><b>{{r.elapsed_label}}</b></div>\n      </div>\n      {% if r.takeover %}<div class=\"wall-takeover\">{{t.charge_takeover}}: {{r.takeover}}</div>{% endif %}\n    </article>\n    {% endfor %}\n  </div>\n\n  <div class=\"wall-bottom\">\n    <section class=\"wall-panel\"><h2>{{t.nurse_workload}}</h2><div id=\"wallWorkload\">{% for n in workload %}<div class=\"workload-row\"><b>{{n.name}}</b><span>{{n.rooms}} {{t.rooms}}</span><span>{{n.active}} {{t.calls}}</span></div>{% endfor %}</div></section>\n    <section class=\"wall-panel\"><h2>{{t.pending_handover}}</h2><div id=\"wallHandovers\">{% if not handovers %}<div class=\"muted\">{{t.none}}</div>{% endif %}{% for h in handovers %}<div class=\"handover-row\"><b>{{h.room}}</b><span>{{h.from_nurse}} → {{h.to_nurse}}</span></div>{% endfor %}</div></section>\n    <section class=\"wall-panel\"><h2>{{t.recent_resolved}}</h2><div id=\"wallRecent\">{% if not recent %}<div class=\"muted\">{{t.none}}</div>{% endif %}{% for r in recent %}<div class=\"recent-row\"><b>{{r.room}}</b><span>{{r.response}}</span><span>{{r.nurse}}</span></div>{% endfor %}</div></section>\n  </div>\n</section>\n{% endblock %}\n{% block scripts %}\n<script>\nwindow.WALLBOARD_LANG='{{lang}}';\nwindow.WALLBOARD_I18N={{ wall_i18n_json|safe }};\nvar wallFilter='all', wallSound=false, showIdle=true, wallView=localStorage.getItem('wallboard-view')||'compact', seenCalls=new Set({{ call_ids_json|safe }}), seenStages={{ call_stages_json|safe }};\n\nfunction setWallView(v,el){wallView=v;localStorage.setItem('wallboard-view',v);var box=document.getElementById('wallRooms');box.className='wall-room-grid view-'+v;document.querySelectorAll('.view-btn').forEach(function(x){x.classList.toggle('active',x.dataset.view===v)});renderZoneHeaders();applyWallFilter()}\nfunction renderZoneHeaders(){document.querySelectorAll('.zone-divider').forEach(function(x){x.remove()});if(wallView!=='zones')return;var box=document.getElementById('wallRooms'),cards=[...box.querySelectorAll('.wall-room-card')],seen={};cards.forEach(function(c){var z=c.dataset.zone||'Other';if(!seen[z]){var d=document.createElement('div');d.className='zone-divider';d.dataset.zone=z;d.innerHTML='<span>'+z+'</span>';box.insertBefore(d,c);seen[z]=true}})}\nfunction setWallFilter(v,el){wallFilter=v;document.querySelectorAll('.filter-chip').forEach(function(x){x.classList.remove('active')});el.classList.add('active');applyWallFilter()}\nfunction toggleIdle(v){showIdle=v;applyWallFilter()}\nfunction applyWallFilter(){document.querySelectorAll('.wall-room-card').forEach(function(c){var zoneOk=(wallFilter==='all'||c.dataset.zone===wallFilter),idleOk=(showIdle||c.dataset.status!=='ready');c.style.display=(zoneOk&&idleOk)?'':'none'});document.querySelectorAll('.zone-divider').forEach(function(d){var any=[...document.querySelectorAll('.wall-room-card[data-zone=\"'+d.dataset.zone+'\"]')].some(function(c){return c.style.display!=='none'});d.style.display=any?'':'none'})}\nfunction fmtSec(s){s=Math.max(0,Math.round(s||0));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}\nfunction wallStatusLabel(s){return (window.WALLBOARD_I18N.status||{})[s]||s.replaceAll('_',' ')}\nfunction wallReasonLabel(s){return (window.WALLBOARD_I18N.reason||{})[s]||s}\nfunction beep(freq,dur,repeats){freq=freq||880;dur=dur||.18;repeats=repeats||2;try{var AC=window.AudioContext||window.webkitAudioContext;var ctx=window._wallAC||(window._wallAC=new AC());var t=ctx.currentTime;for(var i=0;i<repeats;i++){var o=ctx.createOscillator(),g=ctx.createGain();o.frequency.value=freq;o.connect(g);g.connect(ctx.destination);g.gain.setValueAtTime(.12,t);g.gain.exponentialRampToValueAtTime(.001,t+dur);o.start(t);o.stop(t+dur);t+=dur+.08}}catch(e){}}\nfunction speakCall(c,escalated){if(!wallSound||!('speechSynthesis'in window))return;var msg=window.WALLBOARD_LANG==='ar'?(escalated?('تم تصعيد النداء للغرفة '+c.room):('نداء جديد من الغرفة '+c.room)):(escalated?('Escalated call, room '+c.room):('New nurse call, room '+c.room));speechSynthesis.cancel();var u=new SpeechSynthesisUtterance(msg);u.lang=window.WALLBOARD_LANG==='ar'?'ar-AE':'en-US';u.rate=.9;speechSynthesis.speak(u)}\nfunction enableWallboardSound(){wallSound=true;localStorage.setItem('wallboard-sound','1');beep(880,.12,1);document.getElementById('soundBtn').textContent='🔊 '+window.WALLBOARD_I18N.sound_on}\nfunction toggleWallFullscreen(){if(!document.fullscreenElement){if(document.documentElement.requestFullscreen)document.documentElement.requestFullscreen()}else if(document.exitFullscreen)document.exitFullscreen()}\nfunction renderRooms(d){var box=document.getElementById('wallRooms'),h='';d.rooms_view.forEach(function(r){h+='<article class=\"wall-room-card status-'+r.status+' '+(r.over_sla?'sla-breach':'')+'\" data-zone=\"'+r.zone+'\" data-status=\"'+r.status+'\" data-room=\"'+r.room+'\"><div class=\"wall-room-top\"><div><b>'+r.room+'</b><span>'+r.zone+'</span></div><span class=\"wall-badge\">'+wallStatusLabel(r.status)+'</span></div><div class=\"wall-room-body\"><div class=\"room-reason\">'+wallReasonLabel(r.reason)+'</div><div class=\"room-meta\"><span>'+window.WALLBOARD_I18N.assigned_nurse+'</span><b>'+r.nurse+'</b></div><div class=\"room-meta room-elapsed\"><span>'+window.WALLBOARD_I18N.elapsed+'</span><b>'+r.elapsed_label+'</b></div></div>'+(r.takeover?'<div class=\"wall-takeover\">'+window.WALLBOARD_I18N.charge_takeover+': '+r.takeover+'</div>':'')+'</article>'});box.innerHTML=h;box.className='wall-room-grid view-'+wallView;renderZoneHeaders();applyWallFilter()}\nfunction renderWorkload(items){var h='';items.forEach(function(n){h+='<div class=\"workload-row\"><b>'+n.name+'</b><span>'+n.rooms+' '+window.WALLBOARD_I18N.rooms+'</span><span>'+n.active+' '+window.WALLBOARD_I18N.calls+'</span></div>'});document.getElementById('wallWorkload').innerHTML=h||'<div class=\"muted\">'+window.WALLBOARD_I18N.none+'</div>'}\nfunction renderHandovers(items){var h='';items.forEach(function(x){h+='<div class=\"handover-row\"><b>'+x.room+'</b><span>'+x.from_nurse+' → '+x.to_nurse+'</span></div>'});document.getElementById('wallHandovers').innerHTML=h||'<div class=\"muted\">'+window.WALLBOARD_I18N.none+'</div>'}\nfunction renderRecent(items){var h='';items.forEach(function(x){h+='<div class=\"recent-row\"><b>'+x.room+'</b><span>'+x.response+'</span><span>'+x.nurse+'</span></div>'});document.getElementById('wallRecent').innerHTML=h||'<div class=\"muted\">'+window.WALLBOARD_I18N.none+'</div>'}\nasync function refreshWallboard(){try{var r=await fetch('/api/wallboard');if(!r.ok)throw new Error('offline');var d=await r.json(),c=document.getElementById('wallConnection');c.textContent=window.WALLBOARD_I18N.connected;c.classList.remove('bad');document.getElementById('statRooms').textContent=d.stats.total_rooms;document.getElementById('statActive').textContent=d.stats.active;document.getElementById('statEscalated').textContent=d.stats.escalated;document.getElementById('statOverSla').textContent=d.stats.over_sla;document.getElementById('statAvg').textContent=d.stats.avg_response;document.getElementById('statUnassigned').textContent=d.stats.unassigned;d.calls.forEach(function(x){if(!seenCalls.has(x.id)){seenCalls.add(x.id);beep(x.status==='escalated'?520:880,.18,x.status==='escalated'?3:2);speakCall(x,x.status==='escalated')}stageAlert(x)});renderRooms(d);renderWorkload(d.workload);renderHandovers(d.handovers);renderRecent(d.recent)}catch(e){var el=document.getElementById('wallConnection');el.textContent=window.WALLBOARD_I18N.disconnected;el.classList.add('bad')}}\nsetInterval(refreshWallboard,3000);setInterval(function(){document.getElementById('wallClock').textContent=new Date().toLocaleTimeString([], {hour12:false})},1000);\ndocument.getElementById('idleToggle').checked=true;setWallView(wallView,document.querySelector('.view-btn[data-view=\"'+wallView+'\"]'));if(localStorage.getItem('wallboard-sound')==='1'){document.getElementById('soundBtn').textContent='🔊 '+window.WALLBOARD_I18N.tap_sound}\n</script>\n{% endblock %}"
}
APP_CSS = ":root{--blue:#0059ad;--deep:#023d7b;--ink:#172033;--muted:#667085;--bg:#f3f6fa;--red:#d92d20;--amber:#f79009;--green:#039855;--line:#dfe5ec}*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink)}.topbar{height:76px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:10px 28px;position:sticky;top:0;z-index:10}.brand{display:flex;align-items:center;gap:12px}.brand img{width:46px;height:46px}.brand b,.brand span{display:block}.brand span{font-size:12px;color:var(--muted)}.userbox{text-align:right}.userbox span,.userbox small{display:block}.userbox a{font-size:12px;color:var(--blue)}.nav{background:#fff;padding:10px 28px;display:flex;gap:18px;border-bottom:1px solid var(--line)}.nav a{text-decoration:none;color:var(--deep);font-weight:650}.container{max-width:1280px;margin:0 auto;padding:28px}.page-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}.page-head h1{margin:4px 0 6px;font-size:32px}.page-head p,.muted{color:var(--muted)}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:800;color:var(--blue)}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0 26px}.stats.four{grid-template-columns:repeat(4,1fr)}.stat{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px}.stat b{font-size:30px;display:block}.stat span{color:var(--muted)}.stat.red{border-left:5px solid var(--red)}.stat.amber{border-left:5px solid var(--amber)}.grid.rooms{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}.room-card{background:#fff;border:1px solid var(--line);border-radius:20px;padding:18px;min-height:220px;box-shadow:0 8px 24px rgba(16,24,40,.04)}.room-card.hot{border:2px solid #f1a9a5}.room-top{display:flex;justify-content:space-between;align-items:center}.room-top b{font-size:25px}.room-top span,.assignment{font-size:13px;color:var(--muted)}.assignment{margin:8px 0 16px}.call-status{display:inline-block;margin-top:18px;padding:7px 10px;border-radius:999px;background:#eef2f6;font-weight:800;font-size:12px}.call-status.new,.badge.new{background:#fee4e2;color:#b42318}.call-status.escalated,.badge.escalated{background:#fef0c7;color:#b54708}.call-status.acknowledged,.badge.acknowledged{background:#e0f2fe;color:#026aa2}.call-status.taken_over,.badge.taken_over{background:#f3e8ff;color:#7f56d9}.call-status.arrived,.badge.arrived,.badge.resolved{background:#dcfae6;color:#067647}.timer{font-size:36px;font-variant-numeric:tabular-nums;font-weight:800;margin:9px 0}.ready{margin-top:34px;color:var(--green);font-weight:800}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.btn{border:0;border-radius:12px;padding:11px 15px;font-weight:750;cursor:pointer}.btn.primary{background:var(--blue);color:#fff}.btn.secondary{background:#eaf2fb;color:var(--deep)}.btn.success{background:var(--green);color:#fff}.btn.danger{background:var(--red);color:#fff}.btn.wide{width:100%;font-size:16px}.alert{padding:12px;border-radius:12px;margin:12px 0}.alert.danger{background:#fee4e2;color:#b42318}.alert.small{font-size:12px}.login-shell,.patient-shell{display:grid;place-items:center;min-height:calc(100vh - 150px)}.login-card,.patient-card{width:min(480px,100%);background:#fff;border:1px solid var(--line);border-radius:28px;padding:32px;text-align:center;box-shadow:0 18px 50px rgba(16,24,40,.08)}.hero-logo{width:104px;height:104px;object-fit:contain}.login-card label{text-align:left;display:block;font-weight:700;margin:15px 0}.login-card input,.room-card select{width:100%;margin-top:7px;border:1px solid #cfd7e2;border-radius:12px;padding:12px;font-size:15px}.demo{margin-top:22px;padding:14px;background:#f7f9fc;border-radius:14px;font-size:12px}.demo span{display:block;color:var(--muted);margin-top:4px}.patient-card h1{font-size:44px;margin:5px}.reason-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:22px 0}.reason{padding:12px;border:1px solid var(--line);border-radius:12px;background:#fff;cursor:pointer}.reason.selected{border:2px solid var(--blue);background:#eef6ff}.call-btn{width:220px;height:220px;border-radius:50%;border:10px solid #d7e8fb;background:var(--blue);color:#fff;font-size:46px;box-shadow:0 15px 30px rgba(0,89,173,.25);cursor:pointer}.call-btn span{font-size:20px;display:block;margin-top:8px}.call-active{padding:28px}.pulse{width:20px;height:20px;background:var(--red);border-radius:50%;margin:0 auto;box-shadow:0 0 0 0 rgba(217,45,32,.5);animation:pulse 1.5s infinite}@keyframes pulse{70%{box-shadow:0 0 0 20px rgba(217,45,32,0)}}.table-wrap{background:#fff;border:1px solid var(--line);border-radius:18px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:14px;border-bottom:1px solid #edf0f4;font-size:14px}th{background:#f8fafc}.badge{padding:6px 9px;border-radius:999px;font-size:12px}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}.panel{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px}.list-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;padding:12px 0;border-bottom:1px solid #edf0f4;font-size:14px}@media(max-width:700px){.container{padding:16px}.topbar{padding:8px 14px}.brand b{font-size:14px}.nav{padding:8px 14px;overflow:auto}.stats,.stats.four,.two-col{grid-template-columns:1fr 1fr}.page-head{align-items:flex-start;gap:12px}.page-head h1{font-size:26px}.call-btn{width:190px;height:190px}.userbox span{display:none}}.handover-box{display:flex;gap:8px;margin-top:18px;border-top:1px solid #edf0f4;padding-top:14px}.handover-box select{flex:1;border:1px solid #cfd7e2;border-radius:10px;padding:9px;background:#fff}\n.admin-tabs{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 18px}.admin-tabs a{background:#fff;border:1px solid var(--line);padding:9px 13px;border-radius:999px;text-decoration:none;color:var(--deep);font-weight:750}.admin-section{margin-bottom:18px;scroll-margin-top:110px}.section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.admin-form{margin:12px 0 18px}.grid-form{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.admin-form input,.admin-form select,.inline-form select,.row-actions input{border:1px solid #cfd7e2;border-radius:10px;padding:10px;background:#fff;min-width:0}.row-actions,.inline-form{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.row-actions form{display:flex;gap:6px}.row-actions input{width:145px}.status-pill{padding:9px 12px;border-radius:999px;font-weight:800;font-size:12px}.status-pill.ok{background:#dcfae6;color:#067647}.status-pill.warn{background:#fef0c7;color:#b54708}.system-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.system-grid>div{background:#f8fafc;border:1px solid var(--line);border-radius:14px;padding:14px}.system-grid span,.system-grid b{display:block}.system-grid span{color:var(--muted);font-size:12px;margin-bottom:5px}.mono-link{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:var(--blue);word-break:break-all}.btn:disabled{opacity:.45;cursor:not-allowed}@media(max-width:900px){.grid-form{grid-template-columns:1fr 1fr}.system-grid{grid-template-columns:1fr 1fr}}@media(max-width:600px){.grid-form,.system-grid{grid-template-columns:1fr}.row-actions input{width:120px}}\n"
APP_CSS += "\n/* QR + bilingual patient journey */\n.qr-action{text-decoration:none;display:inline-block}.qr-shell{display:grid;place-items:center;min-height:calc(100vh - 150px)}.qr-poster{width:min(520px,100%);background:#fff;border:1px solid var(--line);border-radius:28px;padding:28px;text-align:center;box-shadow:0 18px 50px rgba(16,24,40,.08)}.qr-logo{width:86px;height:86px;object-fit:contain}.qr-poster h1{font-size:42px;margin:6px 0}.qr-poster h2{margin:8px 0}.qr-ar{font-family:Tahoma,Arial,sans-serif}.qr-image{width:min(330px,85vw);height:auto;margin:16px auto;display:block}.qr-print-actions{display:flex;gap:10px;justify-content:center;margin-top:18px}.patient-lang-switch{display:flex;align-items:center;justify-content:flex-end;gap:6px;margin-bottom:8px}.lang-chip{border:1px solid #d0d7e2;background:#fff;border-radius:999px;padding:5px 9px;font-size:12px;font-weight:800;color:var(--deep);cursor:pointer}.lang-chip.active{background:#eaf2fb;border-color:#8eb8e5}.patient-question{font-size:22px;margin:14px 0 4px}.patient-note{margin-top:0}.reason{display:flex;align-items:center;justify-content:center;gap:7px;min-height:58px}.reason-icon{font-size:20px}.physical-note{margin-top:24px;padding:12px 14px;background:#fff7e8;border:1px solid #f4d49b;border-radius:14px;font-size:13px;line-height:1.5}.patient-lang[dir=\"rtl\"] .patient-card{text-align:right}.patient-lang[dir=\"rtl\"] .eyebrow,.patient-lang[dir=\"rtl\"] h1,.patient-lang[dir=\"rtl\"] .patient-question,.patient-lang[dir=\"rtl\"] .patient-note,.patient-lang[dir=\"rtl\"] .call-active{text-align:center}.patient-lang[dir=\"rtl\"] .reason{font-family:Tahoma,Arial,sans-serif}.patient-lang[dir=\"rtl\"] .call-btn span{font-family:Tahoma,Arial,sans-serif}@media print{.topbar,.nav,.qr-print-actions{display:none!important}.container{padding:0}.qr-shell{min-height:auto}.qr-poster{box-shadow:none;border:none;width:100%;padding:10mm}.qr-image{width:95mm}.qr-logo{width:25mm;height:25mm}}"
APP_CSS += ".wallboard-shell{max-width:1600px;margin:0 auto}.wallboard-head{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:18px}.wallboard-head h1{font-size:38px;margin:2px 0 4px}.wallboard-head p{margin:0;color:var(--muted)}.wallboard-tools{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}.wall-clock{font-size:28px;font-weight:850;font-variant-numeric:tabular-nums;background:#fff;border:1px solid var(--line);padding:8px 13px;border-radius:14px}.lang-mini{display:flex;gap:5px;align-items:center}.lang-mini a{padding:5px 8px;border-radius:999px;text-decoration:none;color:var(--deep);font-weight:800;font-size:12px;border:1px solid var(--line);background:#fff}.lang-mini a.active{background:#eaf2fb}.wall-stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:16px}.wall-stat{background:#fff;border:1px solid var(--line);border-radius:16px;padding:14px 16px}.wall-stat span{display:block;color:var(--muted);font-size:12px}.wall-stat b{font-size:28px}.wall-stat.danger{border-left:5px solid var(--red)}.wall-stat.overdue{border-left:5px solid var(--amber)}.wall-filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px}.filter-chip{border:1px solid var(--line);background:#fff;padding:7px 11px;border-radius:999px;font-weight:750;color:var(--deep);cursor:pointer}.filter-chip.active{background:var(--deep);color:#fff}.wall-live{margin-left:auto;color:var(--green);font-weight:900}.wall-connection{font-size:12px;color:var(--green);font-weight:800}.wall-connection.bad{color:var(--red)}.wall-call-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;min-height:250px}.wall-call-card{background:#fff;border:2px solid var(--line);border-radius:20px;padding:17px;box-shadow:0 8px 20px rgba(16,24,40,.04)}.wall-call-card.status-new{border-color:#f0a6a1}.wall-call-card.status-escalated,.wall-call-card.status-taken_over{border-color:#f79009}.wall-call-card.status-arrived{border-color:#66c98b}.wall-call-card.sla-breach{animation:wallPulse 1.1s infinite;background:#fff7f6}@keyframes wallPulse{0%,100%{box-shadow:0 0 0 0 rgba(217,45,32,.12)}50%{box-shadow:0 0 0 8px rgba(217,45,32,.13)}}.wall-call-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.wall-call-top b{font-size:30px;display:block}.wall-call-top span{font-size:12px;color:var(--muted)}.wall-badge{background:#eef2f6!important;color:var(--deep)!important;padding:6px 9px;border-radius:999px;font-weight:850}.status-escalated .wall-badge{background:#fef0c7!important;color:#b54708!important}.status-new .wall-badge{background:#fee4e2!important;color:#b42318!important}.status-arrived .wall-badge{background:#dcfae6!important;color:#067647!important}.wall-reason{font-size:21px;font-weight:850;margin:18px 0}.wall-call-mid{display:grid;grid-template-columns:1fr auto;gap:18px}.wall-call-mid span{display:block;font-size:11px;color:var(--muted)}.wall-call-mid b{font-size:18px}.wall-takeover{margin-top:12px;padding:9px;background:#f3e8ff;border-radius:10px;font-size:13px;color:#6941c6}.wall-empty{grid-column:1/-1;display:grid;place-items:center;background:#fff;border:1px dashed var(--line);border-radius:20px;min-height:220px;color:var(--muted);font-size:20px}.wall-bottom{display:grid;grid-template-columns:1.15fr 1fr 1fr;gap:14px;margin-top:16px}.wall-panel{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px}.wall-panel h2{font-size:17px;margin:0 0 10px}.workload-row,.handover-row,.recent-row{display:grid;grid-template-columns:1.2fr .8fr .8fr;gap:8px;padding:9px 0;border-bottom:1px solid #edf0f4;font-size:13px}.handover-row{grid-template-columns:.5fr 1.5fr}.recent-row{grid-template-columns:.5fr .7fr 1fr}.wallboard-shell[data-lang=\"ar\"]{direction:rtl}.wallboard-shell[data-lang=\"ar\"] .wall-live{margin-left:0;margin-right:auto}@media(max-width:1000px){.wall-stats{grid-template-columns:repeat(3,1fr)}.wall-bottom{grid-template-columns:1fr}.wallboard-head{flex-direction:column}.wallboard-tools{justify-content:flex-start}}@media(max-width:650px){.wall-stats{grid-template-columns:1fr 1fr}.wall-call-grid{grid-template-columns:1fr}.wall-call-top b{font-size:26px}}"
APP_CSS += ".view-switch{display:flex;gap:4px;background:#eef3f8;padding:4px;border-radius:12px}.view-btn{border:0;background:transparent;padding:7px 9px;border-radius:9px;font-size:12px;font-weight:800;color:var(--deep);cursor:pointer}.view-btn.active{background:#fff;box-shadow:0 1px 4px rgba(16,24,40,.12)}.show-idle{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);font-weight:700}.wall-stats{grid-template-columns:repeat(6,1fr)}.wall-room-grid{display:grid;gap:10px;align-items:stretch}.wall-room-grid.view-compact{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}.wall-room-grid.view-cards{grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}.wall-room-grid.view-list{grid-template-columns:1fr;gap:6px}.wall-room-grid.view-zones{grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}.wall-room-card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px;min-height:126px;box-shadow:0 4px 14px rgba(16,24,40,.035);position:relative;overflow:hidden}.wall-room-card.status-ready{border-color:#dce6df;background:#fbfefc}.wall-room-card.status-new{border-color:#f0a6a1}.wall-room-card.status-escalated,.wall-room-card.status-taken_over{border-color:#f79009}.wall-room-card.status-arrived{border-color:#66c98b}.wall-room-card.sla-breach{animation:wallPulse 1.1s infinite;background:#fff7f6}.wall-room-top{display:flex;justify-content:space-between;gap:8px}.wall-room-top b{font-size:23px;display:block;line-height:1}.wall-room-top span{font-size:10px;color:var(--muted)}.wall-room-body{margin-top:9px}.room-reason{font-size:14px;font-weight:850;min-height:20px}.room-meta{margin-top:8px}.room-meta span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.04em}.room-meta b{font-size:13px}.room-elapsed{position:absolute;right:12px;bottom:10px;text-align:right}.wallboard-shell[data-lang=\"ar\"] .room-elapsed{right:auto;left:12px;text-align:left}.wall-room-card.status-ready .room-reason{color:var(--green)}.view-compact .wall-room-card{padding:10px;min-height:108px}.view-compact .wall-room-top b{font-size:20px}.view-compact .room-meta{margin-top:5px}.view-compact .room-meta span{display:none}.view-compact .room-meta b{font-size:12px}.view-compact .room-elapsed{bottom:8px}.view-cards .wall-room-card{min-height:170px;padding:16px}.view-cards .wall-room-top b{font-size:30px}.view-cards .room-reason{font-size:19px;margin-top:15px}.view-cards .room-meta b{font-size:16px}.view-list .wall-room-card{display:grid;grid-template-columns:130px 1fr 180px 110px;align-items:center;min-height:58px;padding:8px 12px}.view-list .wall-room-top{display:block}.view-list .wall-room-top b{font-size:20px}.view-list .wall-room-body{display:contents}.view-list .room-reason{font-size:14px;min-height:0}.view-list .room-meta{margin:0}.view-list .room-elapsed{position:static;text-align:right}.view-list .wall-takeover{grid-column:1/-1;margin-top:4px}.zone-divider{grid-column:1/-1;font-size:13px;font-weight:900;color:var(--deep);padding:8px 2px 3px;border-bottom:2px solid #dbe6f1;letter-spacing:.04em}.wall-badge{padding:5px 7px;border-radius:999px;font-weight:850;font-size:9px!important}.status-ready .wall-badge{background:#dcfae6!important;color:#067647!important}.wall-bottom{margin-top:12px}.wall-panel{padding:12px}.wall-panel h2{font-size:14px}.workload-row,.handover-row,.recent-row{padding:6px 0;font-size:11px}@media(max-width:1200px){.wall-stats{grid-template-columns:repeat(3,1fr)}.wall-room-grid.view-compact{grid-template-columns:repeat(auto-fill,minmax(165px,1fr))}}@media(max-width:700px){.view-switch{width:100%;overflow:auto}.wall-stats{grid-template-columns:repeat(2,1fr)}.wall-room-grid.view-compact,.wall-room-grid.view-cards,.wall-room-grid.view-zones{grid-template-columns:repeat(2,minmax(0,1fr))}.view-list .wall-room-card{grid-template-columns:100px 1fr}.view-list .room-meta,.view-list .room-elapsed{display:none}}"
APP_CSS += ".alert-legend{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:-4px 0 12px;font-size:11px;font-weight:800;color:#475467}.legend-item{display:flex;align-items:center;gap:6px}.legend-item i{width:11px;height:11px;border-radius:50%;display:inline-block}.legend-green i{background:#12b76a;box-shadow:0 0 0 4px rgba(18,183,106,.12)}.legend-amber i{background:#f79009;box-shadow:0 0 0 4px rgba(247,144,9,.12)}.legend-red i{background:#d92d20;box-shadow:0 0 0 4px rgba(217,45,32,.12)}.legend-blue i{background:#2970ff;box-shadow:0 0 0 4px rgba(41,112,255,.12)}.wall-room-card.alert-fresh{border:2px solid #12b76a;animation:fullCardGreen 1.25s ease-in-out infinite}.wall-room-card.alert-warning{border:3px solid #f79009;animation:fullCardAmber .95s ease-in-out infinite}.wall-room-card.alert-critical{border:3px solid #d92d20;animation:fullCardRed .72s ease-in-out infinite}.wall-room-card.alert-takeover{border:3px solid #2970ff;animation:fullCardBlue .95s ease-in-out infinite}.wall-room-card.alert-arrived{border:2px solid #12b76a;background:#ecfdf3;animation:none}.wall-room-card.alert-idle{animation:none}.wall-room-card.alert-fresh .wall-badge{background:#d1fadf!important;color:#05603a!important}.wall-room-card.alert-warning .wall-badge{background:#fef0c7!important;color:#b54708!important}.wall-room-card.alert-critical .wall-badge{background:#fee4e2!important;color:#b42318!important}.wall-room-card.alert-takeover .wall-badge{background:#dbe9ff!important;color:#1849a9!important}@keyframes fullCardGreen{0%,100%{background:#f6fef9;box-shadow:0 0 0 0 rgba(18,183,106,.18),0 6px 16px rgba(18,183,106,.06)}50%{background:#d1fadf;box-shadow:0 0 0 7px rgba(18,183,106,.22),0 10px 30px rgba(18,183,106,.28)}}@keyframes fullCardAmber{0%,100%{background:#fffcf5;box-shadow:0 0 0 0 rgba(247,144,9,.18),0 6px 18px rgba(247,144,9,.08)}50%{background:#fef0c7;box-shadow:0 0 0 9px rgba(247,144,9,.25),0 12px 34px rgba(247,144,9,.32)}}@keyframes fullCardRed{0%,100%{background:#fff7f6;box-shadow:0 0 0 0 rgba(217,45,32,.22),0 8px 20px rgba(217,45,32,.10)}50%{background:#fecaca;box-shadow:0 0 0 11px rgba(217,45,32,.30),0 14px 40px rgba(217,45,32,.38)}}@keyframes fullCardBlue{0%,100%{background:#f5f8ff;box-shadow:0 0 0 0 rgba(41,112,255,.16),0 6px 18px rgba(41,112,255,.08)}50%{background:#dbe9ff;box-shadow:0 0 0 8px rgba(41,112,255,.22),0 12px 32px rgba(41,112,255,.30)}}@media (prefers-reduced-motion:reduce){.wall-room-card.alert-fresh,.wall-room-card.alert-warning,.wall-room-card.alert-critical,.wall-room-card.alert-takeover{animation-duration:2.4s}}"
APP_CSS += ".reassign-box{margin-top:14px;padding:12px;background:#f8fafc;border:1px solid #d9e2ec;border-radius:12px;display:grid;grid-template-columns:1fr 1fr auto;gap:8px}.reassign-title{grid-column:1/-1;display:flex;justify-content:space-between;gap:10px;align-items:center}.reassign-title b{font-size:13px}.reassign-title span{font-size:10px;color:var(--muted)}.reassign-box select{min-width:0;width:100%;border:1px solid #cfd7e2;border-radius:9px;padding:9px;background:#fff;color:var(--deep)}@media(max-width:700px){.reassign-box{grid-template-columns:1fr}.reassign-title{grid-column:auto;display:block}.reassign-title span{display:block;margin-top:3px}}"
APP_CSS += ".room-edit-form{display:grid;grid-template-columns:minmax(85px,110px) minmax(100px,150px) auto;gap:6px;align-items:center}.room-edit-form input{border:1px solid #cfd7e2;border-radius:9px;padding:9px;min-width:0;background:#fff}.admin-room-msg{margin:0 0 12px;padding:11px 13px;border-radius:10px;font-weight:750;font-size:13px}.admin-room-msg.success{background:#dcfae6;color:#067647;border:1px solid #abefc6}.admin-room-msg.error{background:#fee4e2;color:#b42318;border:1px solid #fecdca}.room-delete-btn{background:#d92d20!important;color:#fff!important;border-color:#d92d20!important}@media(max-width:900px){.room-edit-form{grid-template-columns:1fr}.room-edit-form .btn{width:100%}}"
APP_CSS += ".manager-export-actions{display:flex;gap:8px;flex-wrap:wrap}.manager-export-actions a{text-decoration:none}.manager-filter{margin-bottom:14px;padding:12px 14px}.period-buttons{display:flex;gap:7px;flex-wrap:wrap}.custom-dates{display:none;gap:10px;align-items:end;flex-wrap:wrap;margin-top:12px}.custom-dates.show{display:flex}.custom-dates label{display:grid;gap:4px;font-size:12px;font-weight:700;color:var(--muted)}.custom-dates input{border:1px solid #cfd7e2;border-radius:9px;padding:9px;background:#fff}.kpi-stats{grid-template-columns:repeat(8,minmax(110px,1fr))}.manager-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:14px 0}.management-call-table{margin-top:14px}.management-call-table small{color:var(--muted)}@media(max-width:1200px){.kpi-stats{grid-template-columns:repeat(4,1fr)}}@media(max-width:900px){.manager-grid{grid-template-columns:1fr}}@media(max-width:650px){.kpi-stats{grid-template-columns:repeat(2,1fr)}}"
APP_JS = "function pad(v){return String(v).padStart(2,'0')}\nfunction updateTimers(){document.querySelectorAll('.timer[data-created]').forEach(el=>{const s=new Date(el.dataset.created);const sec=Math.max(0,Math.floor((Date.now()-s.getTime())/1000));el.textContent=`${pad(Math.floor(sec/60))}:${pad(sec%60)}`})}\nsetInterval(updateTimers,1000);updateTimers();\nasync function callAction(id,action){const r=await fetch(`/api/call/${id}/${action}`,{method:'POST'});if(r.ok) location.reload();else alert('Action could not be completed.');}\nasync function assignRoom(id,nurseId){if(!nurseId)return;const r=await fetch(`/api/room/${id}/assign`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nurse_id:nurseId})});if(r.ok)location.reload();}\nasync function reassignCall(id){const n=document.getElementById(`reassign-nurse-${id}`),rs=document.getElementById(`reassign-reason-${id}`);if(!n||!n.value){alert('Select a nurse.');return}if(!rs||!rs.value){alert('Select a reason.');return}const r=await fetch(`/api/call/${id}/reassign`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nurse_id:n.value,reason:rs.value})});const d=await r.json().catch(()=>({}));if(r.ok){alert('Call reassigned. Original timer preserved.');location.reload()}else alert(d.error||'Reassignment could not be completed.');}\nfunction urlBase64ToUint8Array(base64String){const padding='='.repeat((4-base64String.length%4)%4);const base64=(base64String+padding).replace(/-/g,'+').replace(/_/g,'/');const raw=atob(base64);return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)))}\nasync function enablePush(){if(!('serviceWorker'in navigator)||!('PushManager'in window)){alert('Push notifications are not supported on this device.');return}const reg=await navigator.serviceWorker.register('/sw.js');const permission=await Notification.requestPermission();if(permission!=='granted'){alert('Notification permission was not granted.');return}const key=''+(window.VAPID_PUBLIC_KEY||'');if(!key){alert('Notifications are ready in-app. Configure VAPID keys on the server to activate background Web Push.');return}const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array(key)});await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub)});alert('Notifications enabled.');}\nif('serviceWorker'in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{})}\nasync function handoverRoom(roomId){const el=document.getElementById(`handover-${roomId}`);if(!el||!el.value)return;const r=await fetch('/api/handover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room_id:roomId,to_nurse_id:el.value})});if(r.ok){alert('Handover request sent.');location.reload()}else alert('Handover could not be created.');}\nasync function acceptHandover(id){const r=await fetch(`/api/handover/${id}/accept`,{method:'POST'});if(r.ok)location.reload();else alert('Could not accept handover.');}"
MANIFEST_JSON = "{\"name\":\"Burjeel ED Smart Call\",\"short_name\":\"ED Call\",\"start_url\":\"/\",\"display\":\"standalone\",\"background_color\":\"#f3f6fa\",\"theme_color\":\"#0059ad\",\"icons\":[{\"src\":\"/static/icons/icon-192.png\",\"sizes\":\"192x192\",\"type\":\"image/png\"},{\"src\":\"/static/icons/icon-512.png\",\"sizes\":\"512x512\",\"type\":\"image/png\"}]}"
SERVICE_WORKER_JS = "self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('push',event=>{let data={title:'Burjeel ED Call',body:'New call',url:'/nurse'};try{data={...data,...event.data.json()}}catch(e){}event.waitUntil(self.registration.showNotification(data.title,{body:data.body,icon:'/static/icons/icon-192.png',badge:'/static/icons/icon-192.png',vibrate:[300,120,300,120,500],requireInteraction:true,data:{url:data.url}}))});self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(clients.openWindow(event.notification.data.url||'/nurse'))});"
LOGO_PNG_B64 = "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"
template_env = Environment(loader=DictLoader(TEMPLATES), autoescape=select_autoescape(['html','xml']))

def render_template(name, context, status_code=200):
    return HTMLResponse(template_env.get_template(name).render(**context), status_code=status_code)

@app.get('/static/app.css')
def inline_css(): return Response(APP_CSS, media_type='text/css')
@app.get('/static/app.js')
def inline_js(): return Response(APP_JS, media_type='application/javascript')
@app.get('/static/icons/icon-192.png')
@app.get('/static/icons/icon-512.png')
@app.get('/favicon.ico')
def inline_logo(): return Response(base64.b64decode(LOGO_PNG_B64), media_type='image/png')


def now_utc(): return datetime.now(timezone.utc)
def pwd_hash(p):
    salt=secrets.token_hex(16); dk=hashlib.pbkdf2_hmac('sha256',p.encode(),salt.encode(),120000)
    return salt+'$'+dk.hex()
def pwd_check(p,h):
    salt,digest=h.split('$',1); dk=hashlib.pbkdf2_hmac('sha256',p.encode(),salt.encode(),120000)
    return secrets.compare_digest(dk.hex(),digest)

class User(Base):
    __tablename__='users'; id=Column(Integer,primary_key=True); name=Column(String(120),nullable=False); email=Column(String(180),unique=True,nullable=False); password_hash=Column(String(255),nullable=False); role=Column(String(40),nullable=False); active=Column(Boolean,default=True)
class Room(Base):
    __tablename__='rooms'; id=Column(Integer,primary_key=True); code=Column(String(40),unique=True,nullable=False); zone=Column(String(80),default='ED Main'); qr_token=Column(String(120),unique=True,nullable=False); occupied=Column(Boolean,default=True); assigned_nurse_id=Column(Integer,ForeignKey('users.id')); assigned_nurse=relationship('User',foreign_keys=[assigned_nurse_id])
class Call(Base):
    __tablename__='calls'; id=Column(Integer,primary_key=True); room_id=Column(Integer,ForeignKey('rooms.id'),nullable=False); status=Column(String(40),default='new'); reason=Column(String(80),default='General assistance'); created_at=Column(DateTime(timezone=True),default=now_utc,nullable=False); acknowledged_at=Column(DateTime(timezone=True)); arrived_at=Column(DateTime(timezone=True)); resolved_at=Column(DateTime(timezone=True)); escalated_at=Column(DateTime(timezone=True)); assigned_nurse_id=Column(Integer,ForeignKey('users.id')); taken_over_by_id=Column(Integer,ForeignKey('users.id')); escalation_reason=Column(String(255)); room=relationship('Room'); assigned_nurse=relationship('User',foreign_keys=[assigned_nurse_id]); taken_over_by=relationship('User',foreign_keys=[taken_over_by_id])
class AuditLog(Base):
    __tablename__='audit_logs'; id=Column(Integer,primary_key=True); call_id=Column(Integer,ForeignKey('calls.id')); room_id=Column(Integer,ForeignKey('rooms.id')); user_id=Column(Integer,ForeignKey('users.id')); action=Column(String(80),nullable=False); detail=Column(String(500)); created_at=Column(DateTime(timezone=True),default=now_utc,nullable=False); user=relationship('User')
class Handover(Base):
    __tablename__='handovers'; id=Column(Integer,primary_key=True); room_id=Column(Integer,ForeignKey('rooms.id'),nullable=False); from_nurse_id=Column(Integer,ForeignKey('users.id'),nullable=False); to_nurse_id=Column(Integer,ForeignKey('users.id'),nullable=False); status=Column(String(30),default='pending'); created_at=Column(DateTime(timezone=True),default=now_utc); accepted_at=Column(DateTime(timezone=True)); room=relationship('Room'); from_nurse=relationship('User',foreign_keys=[from_nurse_id]); to_nurse=relationship('User',foreign_keys=[to_nurse_id])
class PushSubscription(Base):
    __tablename__='push_subscriptions'; id=Column(Integer,primary_key=True); user_id=Column(Integer,ForeignKey('users.id'),nullable=False); endpoint=Column(Text,unique=True,nullable=False); payload=Column(Text,nullable=False); created_at=Column(DateTime(timezone=True),default=now_utc)

Base.metadata.create_all(engine)

def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

def current_user(request:Request,db:Session):
    uid=request.session.get('user_id'); return db.get(User,uid) if uid else None

def require_role(request,db,roles):
    user=current_user(request,db)
    if not user: raise HTTPException(401)
    if roles and user.role not in roles: raise HTTPException(403)
    return user

def ctx(request,db,**kwargs): return {'request':request,'current_user':current_user(request,db),'sla_seconds':SLA_SECONDS,'vapid_public_key':VAPID_PUBLIC_KEY,**kwargs}
def log_action(db,action,detail='',call=None,room=None,user=None): db.add(AuditLog(action=action,detail=detail,call_id=call.id if call else None,room_id=(room.id if room else (call.room_id if call else None)),user_id=user.id if user else None))
def send_push_to_user(db,user_id,title,body,url='/nurse'):
    if not(webpush and VAPID_PRIVATE_KEY): return {'sent':0,'mode':'in-app-fallback'}
    sent=0
    for sub in db.query(PushSubscription).filter_by(user_id=user_id).all():
        try:
            webpush(subscription_info=json.loads(sub.payload),data=json.dumps({'title':title,'body':body,'url':url}),vapid_private_key=VAPID_PRIVATE_KEY,vapid_claims={'sub':VAPID_SUBJECT}); sent+=1
        except WebPushException: pass
    return {'sent':sent,'mode':'webpush'}
def enforce_escalations(db):
    changed=False
    for c in db.query(Call).filter(Call.status.in_(['new','acknowledged'])).all():
        created=c.created_at.replace(tzinfo=timezone.utc) if c.created_at and c.created_at.tzinfo is None else c.created_at
        if c.status=='new' and created and (now_utc()-created).total_seconds()>=SLA_SECONDS:
            c.status='escalated'; c.escalated_at=now_utc(); c.escalation_reason='Primary nurse did not acknowledge within SLA'; log_action(db,'CALL_ESCALATED',c.escalation_reason,call=c)
            for charge in db.query(User).filter_by(role='charge').all(): send_push_to_user(db,charge.id,f'Escalated call - {c.room.code}','Primary nurse did not acknowledge within SLA','/charge')
            changed=True
    if changed: db.commit()
def serialize_call(c):
    end=c.resolved_at or now_utc(); start=c.created_at
    if start.tzinfo is None:start=start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:end=end.replace(tzinfo=timezone.utc)
    return {'id':c.id,'room':c.room.code,'status':c.status,'reason':c.reason,'created_at':c.created_at.isoformat(),'elapsed_seconds':int((end-start).total_seconds()),'assigned_nurse':c.assigned_nurse.name if c.assigned_nurse else None,'taken_over_by':c.taken_over_by.name if c.taken_over_by else None,'escalation_reason':c.escalation_reason}
def role_home(role): return {'nurse':'/nurse','charge':'/charge','manager':'/manager','ed_manager':'/manager','admin':'/admin'}.get(role,'/nurse')

@app.get('/healthz')
def healthz(): return {'status':'ok'}
@app.get('/',response_class=HTMLResponse)
def index(request:Request,db:Session=Depends(get_db)):
    u=current_user(request,db)
    return RedirectResponse(role_home(u.role),303) if u else render_template('login.html',ctx(request,db))
@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request,db:Session=Depends(get_db)): return render_template('login.html',ctx(request,db))
@app.post('/login')
async def login(request:Request,db:Session=Depends(get_db)):
    form=await request.form(); email=str(form.get('email','')).strip().lower(); password=str(form.get('password',''))
    u=db.query(User).filter_by(email=email,active=True).first()
    if u and pwd_check(password,u.password_hash): request.session['user_id']=u.id; return RedirectResponse(role_home(u.role),303)
    return render_template('login.html',ctx(request,db,error='Invalid credentials'),status_code=401)
@app.get('/logout')
def logout(request:Request): request.session.clear(); return RedirectResponse('/login',303)
@app.get('/room/{token}',response_class=HTMLResponse)
def patient_room(token:str,request:Request,db:Session=Depends(get_db)):
    enforce_escalations(db); room=db.query(Room).filter_by(qr_token=token).first()
    if not room: raise HTTPException(404)
    active=db.query(Call).filter_by(room_id=room.id).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).order_by(Call.created_at.desc()).first()
    lang=request.query_params.get('lang','en').lower()
    if lang not in ['en','ar']: lang='en'
    translations={
      'en':{'page_title':'Call Nurse','help_title':'How can we help?','help_note':'Choose a reason, then tap the call button.','general':'General assistance','pain':'Pain','toilet':'Toilet assistance','medication':'IV / Medication','call_nurse':'CALL NURSE','call_active':'Call sent','wait_note':'Your nurse has been notified.','physical_note':'For urgent or life-threatening needs, use the physical emergency call bell immediately.','error':'Unable to send the call. Please use the physical call bell.'},
      'ar':{'page_title':'استدعاء الممرضة','help_title':'كيف يمكننا مساعدتك؟','help_note':'اختر سبب النداء ثم اضغط زر استدعاء الممرضة.','general':'مساعدة عامة','pain':'ألم','toilet':'مساعدة للحمام','medication':'المحلول / الدواء','call_nurse':'استدعاء الممرضة','call_active':'تم إرسال النداء','wait_note':'تم إشعار الممرضة المسؤولة عن الغرفة.','physical_note':'للحالات العاجلة أو المهددة للحياة استخدم زر النداء الفعلي فورًا.','error':'تعذر إرسال النداء. يرجى استخدام زر النداء الفعلي.'}
    }
    status_en={'new':'Waiting for nurse','acknowledged':'Nurse acknowledged','escalated':'Escalated to nurse in charge','taken_over':'Nurse in charge responding','arrived':'Nurse arrived','resolved':'Resolved'}
    status_ar={'new':'بانتظار استجابة الممرضة','acknowledged':'تم تأكيد النداء','escalated':'تم التصعيد إلى الممرضة المسؤولة','taken_over':'الممرضة المسؤولة تتولى النداء','arrived':'حضرت الممرضة','resolved':'تم إغلاق النداء'}
    status=(status_ar if lang=='ar' else status_en).get(active.status if active else '',translations[lang]['call_active'])
    return render_template('patient.html',ctx(request,db,room=room,active_call=active,lang=lang,t=translations[lang],status_label=status))
@app.post('/api/room/{token}/call')
async def patient_call(token:str,request:Request,db:Session=Depends(get_db)):
    room=db.query(Room).filter_by(qr_token=token).first();
    if not room: raise HTTPException(404)
    if not room.occupied or not room.assigned_nurse_id: return JSONResponse({'ok':False,'error':'Room is not ready for digital call. Please use the physical call bell.'},409)
    active=db.query(Call).filter_by(room_id=room.id).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).first()
    if active:return {'ok':True,'call_id':active.id,'status':active.status,'duplicate':True}
    data=await request.json(); c=Call(room_id=room.id,assigned_nurse_id=room.assigned_nurse_id,reason=data.get('reason','General assistance')); db.add(c); db.flush(); log_action(db,'CALL_CREATED',f'Patient call: {c.reason}',call=c); db.commit(); send_push_to_user(db,room.assigned_nurse_id,f'Call Bell - {room.code}',f'Patient requests {c.reason}','/nurse'); return {'ok':True,'call_id':c.id,'status':c.status}
@app.get('/api/call/{call_id}/status')
def call_status(call_id:int,db:Session=Depends(get_db)):
    enforce_escalations(db); c=db.get(Call,call_id)
    if not c: raise HTTPException(404)
    return serialize_call(c)
@app.get('/nurse',response_class=HTMLResponse)
def nurse_page(request:Request,db:Session=Depends(get_db)):
    u=require_role(request,db,['nurse','charge']); enforce_escalations(db); rooms=db.query(Room).filter_by(assigned_nurse_id=u.id).order_by(Room.code).all(); calls=db.query(Call).filter_by(assigned_nurse_id=u.id).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).order_by(Call.created_at).all(); colleagues=db.query(User).filter(User.role=='nurse',User.id!=u.id).order_by(User.name).all(); pending=db.query(Handover).filter_by(to_nurse_id=u.id,status='pending').order_by(Handover.created_at.desc()).all(); return render_template('nurse.html',ctx(request,db,rooms=rooms,calls=calls,colleagues=colleagues,pending_handovers=pending))
@app.get('/charge',response_class=HTMLResponse)
def charge_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['charge','manager','ed_manager','admin']); enforce_escalations(db); calls=db.query(Call).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).order_by(Call.created_at).all(); rooms=db.query(Room).order_by(Room.code).all(); nurses=db.query(User).filter_by(role='nurse',active=True).order_by(User.name).all(); return render_template('charge.html',ctx(request,db,calls=calls,rooms=rooms,nurses=nurses))
def _aware(dt):
    if not dt: return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _fmt_seconds(sec):
    if sec is None: return '-'
    sec=max(0,int(sec)); return f'{sec//60:02d}:{sec%60:02d}'

def _management_range(request):
    period=request.query_params.get('period','today')
    now=now_utc()
    if period=='week':
        start=(now-timedelta(days=6)).replace(hour=0,minute=0,second=0,microsecond=0); end=now
    elif period=='month':
        start=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0); end=now
    elif period=='custom':
        try:
            start=datetime.strptime(request.query_params.get('from',''),'%Y-%m-%d').replace(tzinfo=timezone.utc)
            end=datetime.strptime(request.query_params.get('to',''),'%Y-%m-%d').replace(tzinfo=timezone.utc)+timedelta(days=1)-timedelta(microseconds=1)
        except Exception:
            period='today'; start=now.replace(hour=0,minute=0,second=0,microsecond=0); end=now
    else:
        period='today'; start=now.replace(hour=0,minute=0,second=0,microsecond=0); end=now
    return period,start,end

def _management_data(request,db):
    period,start,end=_management_range(request)
    calls=db.query(Call).filter(Call.created_at>=start,Call.created_at<=end).order_by(Call.created_at.desc()).all()
    call_rows=[]; response_secs=[]; completed_secs=[]
    nurse_map={}; room_map={}
    for c in calls:
        created=_aware(c.created_at); ack=_aware(c.acknowledged_at); arrived=_aware(c.arrived_at); resolved=_aware(c.resolved_at)
        response_end=arrived or resolved
        response=(response_end-created).total_seconds() if response_end and created else None
        duration=(resolved-created).total_seconds() if resolved and created else None
        if response is not None: response_secs.append(response)
        if duration is not None: completed_secs.append(duration)
        nurse_name=c.assigned_nurse.name if c.assigned_nurse else 'Unassigned'
        room_code=c.room.code if c.room else '-'; zone=c.room.zone if c.room else '-'
        call_rows.append({'id':c.id,'room':room_code,'zone':zone,'created':created.strftime('%Y-%m-%d %H:%M:%S') if created else '-','nurse':nurse_name,'status':c.status,'status_label':c.status.replace('_',' ').title(),'response':_fmt_seconds(response),'response_seconds':response,'duration':_fmt_seconds(duration),'duration_seconds':duration,'escalated':'Yes' if c.escalated_at else 'No','takeover':c.taken_over_by.name if c.taken_over_by else '-','reason':c.reason,'acknowledged':ack.strftime('%Y-%m-%d %H:%M:%S') if ack else '-','arrived':arrived.strftime('%Y-%m-%d %H:%M:%S') if arrived else '-','resolved':resolved.strftime('%Y-%m-%d %H:%M:%S') if resolved else '-'})
        nm=nurse_map.setdefault(nurse_name,{'name':nurse_name,'calls':0,'responses':[],'over_sla':0,'escalated':0})
        nm['calls']+=1
        if response is not None: nm['responses'].append(response)
        if response is not None and response>SLA_SECONDS: nm['over_sla']+=1
        if c.escalated_at: nm['escalated']+=1
        rm=room_map.setdefault(room_code,{'room':room_code,'zone':zone,'calls':0,'responses':[],'over_sla':0})
        rm['calls']+=1
        if response is not None: rm['responses'].append(response)
        if response is not None and response>SLA_SECONDS: rm['over_sla']+=1
    nurse_perf=[]
    for n in nurse_map.values():
        avg=sum(n['responses'])/len(n['responses']) if n['responses'] else None
        nurse_perf.append({'name':n['name'],'calls':n['calls'],'avg_response':_fmt_seconds(avg),'avg_seconds':avg,'over_sla':n['over_sla'],'escalated':n['escalated']})
    nurse_perf.sort(key=lambda x:(-x['calls'],x['name']))
    room_perf=[]
    for r in room_map.values():
        avg=sum(r['responses'])/len(r['responses']) if r['responses'] else None
        room_perf.append({'room':r['room'],'zone':r['zone'],'calls':r['calls'],'avg_response':_fmt_seconds(avg),'avg_seconds':avg,'over_sla':r['over_sla']})
    room_perf.sort(key=lambda x:(-x['calls'],x['room']))
    avg=sum(response_secs)/len(response_secs) if response_secs else None
    median=None
    if response_secs:
        vals=sorted(response_secs); mid=len(vals)//2
        median=vals[mid] if len(vals)%2 else (vals[mid-1]+vals[mid])/2
    over2=sum(1 for x in response_secs if x>120); over5=sum(1 for x in response_secs if x>300)
    sla_ok=sum(1 for x in response_secs if x<=SLA_SECONDS)
    sla_rate=f'{(sla_ok/len(response_secs)*100):.1f}%' if response_secs else '-'
    kpi={'total':len(calls),'avg_response':_fmt_seconds(avg),'median_response':_fmt_seconds(median),'over_2m':over2,'over_5m':over5,'escalations':sum(1 for c in calls if c.escalated_at),'takeovers':sum(1 for c in calls if c.taken_over_by_id),'sla_rate':sla_rate}
    handovers=db.query(Handover).filter(Handover.created_at>=start,Handover.created_at<=end).order_by(Handover.created_at.desc()).all()
    audits=db.query(AuditLog).filter(AuditLog.created_at>=start,AuditLog.created_at<=end).order_by(AuditLog.created_at.desc()).all()
    filter_qs=f'period={period}'
    from_date=request.query_params.get('from',''); to_date=request.query_params.get('to','')
    if period=='custom' and from_date and to_date: filter_qs+=f'&from={from_date}&to={to_date}'
    range_label=f'{start.strftime("%Y-%m-%d")} to {end.strftime("%Y-%m-%d")}'
    return {'period':period,'start':start,'end':end,'calls':calls,'call_rows':call_rows,'nurse_perf':nurse_perf,'room_perf':room_perf,'kpi':kpi,'handovers':handovers,'audits':audits,'filter_qs':filter_qs,'from_date':from_date,'to_date':to_date,'range_label':range_label}

@app.get('/manager',response_class=HTMLResponse)
def manager_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['manager','ed_manager','admin']); enforce_escalations(db)
    d=_management_data(request,db)
    return render_template('manager.html',ctx(request,db,**d))

@app.get('/manager/export.xlsx')
def manager_export_excel(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['manager','ed_manager','admin']); d=_management_data(request,db)
    wb=Workbook(); ws=wb.active; ws.title='Executive Dashboard'
    navy='0B2A4A'; blue='0B67C2'; light='EAF2FB'; green='D1FADF'; amber='FEF0C7'; red='FEE4E2'; white='FFFFFF'
    thin=Side(style='thin',color='D0D5DD')
    ws['A1']='Burjeel ED Smart Call Bell - Executive KPI Dashboard'; ws['A1'].font=Font(size=16,bold=True,color=white); ws['A1'].fill=PatternFill('solid',fgColor=navy); ws.merge_cells('A1:F1')
    ws['A2']='Reporting period'; ws['B2']=d['range_label']; ws['A3']='Generated UTC'; ws['B3']=now_utc().strftime('%Y-%m-%d %H:%M:%S')
    metrics=[('Total Calls',d['kpi']['total']),('Average Response',d['kpi']['avg_response']),('Median Response',d['kpi']['median_response']),('Calls >2 min',d['kpi']['over_2m']),('Calls >5 min',d['kpi']['over_5m']),('Escalations',d['kpi']['escalations']),('Charge Takeovers',d['kpi']['takeovers']),('SLA Compliance',d['kpi']['sla_rate'])]
    row=5
    for label,value in metrics:
        ws.cell(row=row,column=1,value=label).font=Font(bold=True); ws.cell(row=row,column=2,value=value); row+=1
    ws['D5']='Calls by Room'; ws['D5'].font=Font(bold=True,color=white); ws['D5'].fill=PatternFill('solid',fgColor=blue); ws['E5']='Calls'; ws['E5'].font=Font(bold=True,color=white); ws['E5'].fill=PatternFill('solid',fgColor=blue)
    for i,r in enumerate(d['room_perf'][:12],start=6): ws.cell(i,4,r['room']); ws.cell(i,5,r['calls'])
    if d['room_perf']:
        chart=BarChart(); chart.title='Call Volume by Room'; chart.y_axis.title='Calls'; chart.x_axis.title='Room'
        chart.add_data(Reference(ws,min_col=5,min_row=5,max_row=5+min(12,len(d['room_perf']))),titles_from_data=True)
        chart.set_categories(Reference(ws,min_col=4,min_row=6,max_row=5+min(12,len(d['room_perf'])))); chart.height=7; chart.width=12; ws.add_chart(chart,'G5')
    for col in range(1,6): ws.column_dimensions[get_column_letter(col)].width=22

    ws2=wb.create_sheet('Call Details')
    headers=['Call ID','Room','Zone','Reason','Primary Nurse','Status','Created','Acknowledged','Arrived','Resolved','Response Time','Response Seconds','Total Duration','Duration Seconds','Escalated','Charge Takeover','SLA Status','Reassignment History']
    ws2.append(headers)
    for cell in ws2[1]: cell.font=Font(bold=True,color=white); cell.fill=PatternFill('solid',fgColor=navy); cell.alignment=Alignment(horizontal='center')
    audit_by_call={}
    for a in d['audits']:
        if a.call_id: audit_by_call.setdefault(a.call_id,[]).append(f'{a.action}: {a.detail or ""}')
    for c in d['call_rows']:
        sla='Within SLA' if c['response_seconds'] is not None and c['response_seconds']<=SLA_SECONDS else ('Over SLA' if c['response_seconds'] is not None else 'Open/No arrival')
        ws2.append([c['id'],c['room'],c['zone'],c['reason'],c['nurse'],c['status_label'],c['created'],c['acknowledged'],c['arrived'],c['resolved'],c['response'],c['response_seconds'],c['duration'],c['duration_seconds'],c['escalated'],c['takeover'],sla,' | '.join(audit_by_call.get(c['id'],[]))])
    ws2.freeze_panes='A2'; ws2.auto_filter.ref=ws2.dimensions

    ws3=wb.create_sheet('Nurse Performance'); ws3.append(['Nurse','Calls','Average Response','Average Seconds','Over SLA','Escalated'])
    for n in d['nurse_perf']: ws3.append([n['name'],n['calls'],n['avg_response'],n['avg_seconds'],n['over_sla'],n['escalated']])
    ws4=wb.create_sheet('Room Performance'); ws4.append(['Room','Zone','Calls','Average Response','Average Seconds','SLA Breaches'])
    for r in d['room_perf']: ws4.append([r['room'],r['zone'],r['calls'],r['avg_response'],r['avg_seconds'],r['over_sla']])
    ws5=wb.create_sheet('SLA & Escalation'); ws5.append(['Call ID','Room','Created','Response','Response Seconds','Escalated','Takeover','SLA Status'])
    for c in d['call_rows']:
        sla='Within SLA' if c['response_seconds'] is not None and c['response_seconds']<=SLA_SECONDS else ('Over SLA' if c['response_seconds'] is not None else 'Open/No arrival')
        ws5.append([c['id'],c['room'],c['created'],c['response'],c['response_seconds'],c['escalated'],c['takeover'],sla])
    ws6=wb.create_sheet('Handover'); ws6.append(['Room','From Nurse','To Nurse','Status','Created','Accepted'])
    for h in d['handovers']: ws6.append([h.room.code,h.from_nurse.name,h.to_nurse.name,h.status,_aware(h.created_at).strftime('%Y-%m-%d %H:%M:%S') if h.created_at else '-',_aware(h.accepted_at).strftime('%Y-%m-%d %H:%M:%S') if h.accepted_at else '-'])
    ws7=wb.create_sheet('Audit Summary'); ws7.append(['Time','Action','User','Room ID','Call ID','Detail'])
    for a in d['audits']: ws7.append([_aware(a.created_at).strftime('%Y-%m-%d %H:%M:%S') if a.created_at else '-',a.action,a.user.name if a.user else '-',a.room_id,a.call_id,a.detail or ''])
    for sheet in [ws3,ws4,ws5,ws6,ws7]:
        for cell in sheet[1]: cell.font=Font(bold=True,color=white); cell.fill=PatternFill('solid',fgColor=navy)
        sheet.freeze_panes='A2'; sheet.auto_filter.ref=sheet.dimensions
    for sheet in wb.worksheets:
        for row_cells in sheet.iter_rows():
            for cell in row_cells:
                cell.border=Border(bottom=thin); cell.alignment=Alignment(vertical='top')
        for column in range(1,min(sheet.max_column,18)+1):
            max_len=max([len(str(sheet.cell(r,column).value or '')) for r in range(1,min(sheet.max_row,200)+1)] or [10]); sheet.column_dimensions[get_column_letter(column)].width=min(max(max_len+2,11),36)
    out=io.BytesIO(); wb.save(out); out.seek(0)
    filename=f'Burjeel_ED_Call_Bell_KPI_{d["period"]}_{now_utc().strftime("%Y%m%d_%H%M")}.xlsx'
    return Response(out.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="{filename}"'})

@app.get('/manager/export.pdf')
def manager_export_pdf(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['manager','ed_manager','admin']); d=_management_data(request,db)
    out=io.BytesIO(); doc=SimpleDocTemplate(out,pagesize=landscape(A4),rightMargin=24,leftMargin=24,topMargin=24,bottomMargin=24); styles=getSampleStyleSheet(); story=[]
    story.append(Paragraph('Burjeel ED Smart Call Bell - KPI Management Report',styles['Title'])); story.append(Paragraph(d['range_label'],styles['Normal'])); story.append(Spacer(1,10))
    k=d['kpi']; kdata=[['KPI','Value'],['Total Calls',k['total']],['Average Response',k['avg_response']],['Median Response',k['median_response']],['Calls >2 min',k['over_2m']],['Calls >5 min',k['over_5m']],['Escalations',k['escalations']],['Charge Takeovers',k['takeovers']],['SLA Compliance',k['sla_rate']]]
    kt=Table(kdata,colWidths=[180,100]); kt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0B2A4A')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),.25,colors.HexColor('#D0D5DD')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8FAFC')]),('PADDING',(0,0),(-1,-1),5)])); story.append(kt); story.append(Spacer(1,12))
    story.append(Paragraph('Nurse Performance',styles['Heading2']))
    ndata=[['Nurse','Calls','Avg Response','Over SLA','Escalated']]+[[n['name'],n['calls'],n['avg_response'],n['over_sla'],n['escalated']] for n in d['nurse_perf']]
    nt=Table(ndata,repeatRows=1); nt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0B67C2')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.HexColor('#D0D5DD')),('PADDING',(0,0),(-1,-1),4)])); story.append(nt); story.append(Spacer(1,12))
    story.append(Paragraph('Recent Call Lifecycle',styles['Heading2']))
    cdata=[['Room','Created','Nurse','Status','Response','Escalated','Takeover','Reason']]+[[c['room'],c['created'],c['nurse'],c['status_label'],c['response'],c['escalated'],c['takeover'],c['reason']] for c in d['call_rows'][:60]]
    ct=Table(cdata,repeatRows=1,colWidths=[50,100,80,70,55,55,75,110]); ct.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0B2A4A')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.HexColor('#D0D5DD')),('FONTSIZE',(0,0),(-1,-1),7),('PADDING',(0,0),(-1,-1),3)])); story.append(ct)
    doc.build(story); out.seek(0)
    filename=f'Burjeel_ED_Call_Bell_KPI_{d["period"]}_{now_utc().strftime("%Y%m%d_%H%M")}.pdf'
    return Response(out.getvalue(),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{filename}"'})

def wallboard_payload(db:Session):
    enforce_escalations(db)
    active_status=['new','acknowledged','escalated','taken_over','arrived']
    calls=db.query(Call).filter(Call.status.in_(active_status)).order_by(Call.created_at).all()
    now=now_utc(); call_out=[]; call_by_room={}
    for c in calls:
        created=c.created_at.replace(tzinfo=timezone.utc) if c.created_at and c.created_at.tzinfo is None else c.created_at
        elapsed=max(0,int((now-created).total_seconds())) if created else 0
        if c.status=='taken_over': alert_stage='takeover'
        elif c.status=='arrived': alert_stage='arrived'
        elif c.status=='escalated': alert_stage='critical'
        elif elapsed<=SLA_SECONDS: alert_stage='fresh'
        elif elapsed<=SLA_SECONDS*2: alert_stage='warning'
        else: alert_stage='critical'
        item={'id':c.id,'room':c.room.code,'room_id':c.room_id,'zone':c.room.zone,'status':c.status,'reason':c.reason,'nurse':c.assigned_nurse.name if c.assigned_nurse else 'Unassigned','takeover':c.taken_over_by.name if c.taken_over_by else None,'elapsed_seconds':elapsed,'elapsed_label':f'{elapsed//60:02d}:{elapsed%60:02d}','created_at':created.isoformat() if created else '','over_sla':c.status in ['new','acknowledged','escalated'] and elapsed>SLA_SECONDS,'alert_stage':alert_stage}
        call_out.append(item); call_by_room[c.room_id]=item
    rooms=db.query(Room).order_by(Room.zone,Room.code).all(); rooms_view=[]
    for r in rooms:
        c=call_by_room.get(r.id)
        if c: rooms_view.append(dict(c))
        else: rooms_view.append({'id':None,'room':r.code,'room_id':r.id,'zone':r.zone,'status':'ready' if r.occupied else 'closed','reason':'Ready' if r.occupied else 'Closed','nurse':r.assigned_nurse.name if r.assigned_nurse else 'Unassigned','takeover':None,'elapsed_seconds':0,'elapsed_label':'--:--','created_at':'','over_sla':False,'alert_stage':'idle'})
    recent_calls=db.query(Call).filter(Call.resolved_at.isnot(None)).order_by(Call.resolved_at.desc()).limit(6).all()
    recent=[]
    for c in recent_calls:
        s=c.created_at.replace(tzinfo=timezone.utc) if c.created_at and c.created_at.tzinfo is None else c.created_at
        e=c.arrived_at or c.resolved_at; e=e.replace(tzinfo=timezone.utc) if e and e.tzinfo is None else e
        sec=max(0,int((e-s).total_seconds())) if s and e else 0
        recent.append({'room':c.room.code,'response':f'{sec//60:02d}:{sec%60:02d}','nurse':(c.taken_over_by.name if c.taken_over_by else (c.assigned_nurse.name if c.assigned_nurse else 'Unassigned'))})
    nurses=db.query(User).filter_by(role='nurse',active=True).order_by(User.name).all(); workload=[]
    for n in nurses:
        workload.append({'name':n.name,'rooms':db.query(Room).filter_by(assigned_nurse_id=n.id,occupied=True).count(),'active':sum(1 for c in calls if c.assigned_nurse_id==n.id)})
    hs=db.query(Handover).filter_by(status='pending').order_by(Handover.created_at.desc()).limit(8).all()
    handovers=[{'room':h.room.code,'from_nurse':h.from_nurse.name,'to_nurse':h.to_nurse.name} for h in hs]
    rt=[]
    for c in recent_calls:
        if c.created_at and (c.arrived_at or c.resolved_at):
            s=c.created_at.replace(tzinfo=timezone.utc) if c.created_at.tzinfo is None else c.created_at; e=c.arrived_at or c.resolved_at; e=e.replace(tzinfo=timezone.utc) if e.tzinfo is None else e; rt.append((e-s).total_seconds())
    avg=int(sum(rt)/len(rt)) if rt else 0
    stats={'total_rooms':len(rooms),'active':len(calls),'escalated':sum(1 for c in calls if c.status=='escalated'),'over_sla':sum(1 for c in call_out if c['over_sla']),'avg_response':f'{avg//60:02d}:{avg%60:02d}','unassigned':db.query(Room).filter(Room.occupied==True,Room.assigned_nurse_id.is_(None)).count()}
    return {'calls':call_out,'rooms_view':rooms_view,'recent':recent,'workload':workload,'handovers':handovers,'stats':stats,'zones':[z[0] for z in db.query(Room.zone).distinct().order_by(Room.zone).all()]}

@app.get('/wallboard',response_class=HTMLResponse)
def wallboard_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['nurse','charge','manager','ed_manager','admin'])
    lang=request.query_params.get('lang','en').lower()
    if lang not in ['en','ar']: lang='en'
    p=wallboard_payload(db)
    i18n={
      'en':{'kicker':'Nurse Station Wallboard','title':'ED Live Call Board','subtitle':'Room calls, SLA escalation, nurse workload and handover status.','enable_sound':'Enable sound','sound_on':'Sound on','tap_sound':'Tap for sound','fullscreen':'Full screen','total_rooms':'Rooms','active_calls':'Active calls','escalated':'Escalated','over_sla':'Over SLA','avg_response':'Avg response','unassigned':'Unassigned rooms','all':'All','connected':'Connected','disconnected':'Offline','no_calls':'No active call bell requests','assigned_nurse':'Assigned nurse','elapsed':'Elapsed','charge_takeover':'Charge takeover','nurse_workload':'Nurse workload','pending_handover':'Pending handover','recent_resolved':'Recent resolved','rooms':'rooms','calls':'calls','none':'None','compact':'Compact','cards':'Cards','list':'List','zones':'Zones','show_idle':'Show ready rooms','legend_green':'0–2 min','legend_amber':'2–4 min','legend_red':'4+ min / escalated','legend_blue':'Charge takeover','status':{'new':'NEW CALL','acknowledged':'ACKNOWLEDGED','escalated':'ESCALATED','taken_over':'CHARGE TAKEOVER','arrived':'ARRIVED','ready':'READY','closed':'CLOSED'},'reason':{'General assistance':'General assistance','Pain':'Pain','Toilet assistance':'Toilet assistance','IV / Medication':'IV / Medication','Ready':'Ready','Closed':'Closed'}},
      'ar':{'kicker':'شاشة محطة التمريض','title':'لوحة نداءات الطوارئ المباشرة','subtitle':'نداءات الغرف والتصعيد وعبء التمريض وحالات التسليم.','enable_sound':'تفعيل الصوت','sound_on':'الصوت مفعل','tap_sound':'اضغط لتفعيل الصوت','fullscreen':'ملء الشاشة','total_rooms':'الغرف','active_calls':'النداءات النشطة','escalated':'تم التصعيد','over_sla':'تجاوز الوقت','avg_response':'متوسط الاستجابة','unassigned':'غرف بدون ممرضة','all':'الكل','connected':'متصل','disconnected':'غير متصل','no_calls':'لا توجد نداءات نشطة','assigned_nurse':'الممرضة المسؤولة','elapsed':'الوقت','charge_takeover':'استلام مسؤول التمريض','nurse_workload':'عبء التمريض','pending_handover':'تسليمات معلقة','recent_resolved':'آخر النداءات المغلقة','rooms':'غرف','calls':'نداءات','none':'لا يوجد','compact':'مضغوط','cards':'بطاقات','list':'قائمة','zones':'مناطق','show_idle':'إظهار الغرف الجاهزة','legend_green':'0–2 دقيقة','legend_amber':'2–4 دقائق','legend_red':'4+ دقائق / تصعيد','legend_blue':'استلام مسؤول التمريض','status':{'new':'نداء جديد','acknowledged':'تم التأكيد','escalated':'تم التصعيد','taken_over':'استلام المسؤول','arrived':'تم الوصول','ready':'جاهزة','closed':'مغلقة'},'reason':{'General assistance':'مساعدة عامة','Pain':'ألم','Toilet assistance':'مساعدة للحمام','IV / Medication':'المحلول / الدواء','Ready':'جاهزة','Closed':'مغلقة'}}
    }
    t=i18n[lang]; calls=[]; rooms_view=[]
    for c in p['calls']:
        x=dict(c); x['status_label']=t['status'].get(c['status'],c['status']); x['reason_label']=t['reason'].get(c['reason'],c['reason']); calls.append(x)
    for r in p['rooms_view']:
        x=dict(r); x['status_label']=t['status'].get(r['status'],r['status']); x['reason_label']=t['reason'].get(r['reason'],r['reason']); rooms_view.append(x)
    return render_template('wallboard.html',ctx(request,db,lang=lang,t=t,calls=calls,rooms_view=rooms_view,recent=p['recent'],workload=p['workload'],handovers=p['handovers'],stats=p['stats'],zones=p['zones'],wall_i18n_json=json.dumps(t,ensure_ascii=False),call_ids_json=json.dumps([c['id'] for c in p['calls']]),call_stages_json=json.dumps({str(c['id']):c['alert_stage'] for c in p['calls']})))

@app.get('/api/wallboard')
def wallboard_api(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['nurse','charge','manager','ed_manager','admin']); return wallboard_payload(db)

@app.get('/admin',response_class=HTMLResponse)
def admin_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['admin'])
    users=db.query(User).order_by(User.role,User.name).all()
    rooms=db.query(Room).order_by(Room.code).all()
    nurses=db.query(User).filter_by(role='nurse',active=True).order_by(User.name).all()
    audit_logs=db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    active_calls=db.query(Call).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).count()
    push_count=db.query(PushSubscription).count()
    return render_template('admin.html',ctx(request,db,rooms=rooms,users=users,nurses=nurses,audit_logs=audit_logs,active_calls=active_calls,push_count=push_count,vapid_ready=bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY),room_msg=request.query_params.get('room_msg',''),room_msg_type=request.query_params.get('room_msg_type','success')))

@app.post('/admin/users')
async def admin_create_user(request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); form=await request.form()
    name=str(form.get('name','')).strip(); email=str(form.get('email','')).strip().lower(); role=str(form.get('role','')).strip(); password=str(form.get('password',''))
    if role not in ['nurse','charge','manager','ed_manager','admin'] or not name or not email or len(password)<8: raise HTTPException(400)
    if db.query(User).filter_by(email=email).first(): return RedirectResponse('/admin#staff',303)
    u=User(name=name,email=email,role=role,password_hash=pwd_hash(password),active=True); db.add(u); db.flush(); log_action(db,'ADMIN_USER_CREATED',f'{email} role={role}',user=admin); db.commit()
    return RedirectResponse('/admin#staff',303)

@app.post('/admin/users/{uid}/toggle')
def admin_toggle_user(uid:int,request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); u=db.get(User,uid)
    if not u: raise HTTPException(404)
    if u.id==admin.id: return RedirectResponse('/admin#staff',303)
    u.active=not u.active; log_action(db,'ADMIN_USER_TOGGLED',f'{u.email} active={u.active}',user=admin); db.commit()
    return RedirectResponse('/admin#staff',303)

@app.post('/admin/users/{uid}/reset')
async def admin_reset_password(uid:int,request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); u=db.get(User,uid)
    if not u: raise HTTPException(404)
    form=await request.form(); password=str(form.get('password',''))
    if len(password)<8: raise HTTPException(400)
    u.password_hash=pwd_hash(password); log_action(db,'ADMIN_PASSWORD_RESET',u.email,user=admin); db.commit()
    return RedirectResponse('/admin#staff',303)

@app.post('/admin/rooms')
async def admin_create_room(request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); form=await request.form()
    code=str(form.get('code','')).strip().upper(); zone=str(form.get('zone','')).strip() or 'ED Main'; nurse_id=str(form.get('nurse_id','')).strip()
    if not code or db.query(Room).filter_by(code=code).first(): return RedirectResponse('/admin#rooms',303)
    nurse=db.get(User,int(nurse_id)) if nurse_id else None
    if nurse and nurse.role!='nurse': nurse=None
    room=Room(code=code,zone=zone,qr_token=secrets.token_urlsafe(18),occupied=True,assigned_nurse_id=nurse.id if nurse else None); db.add(room); db.flush(); log_action(db,'ADMIN_ROOM_CREATED',f'{code} zone={zone}',room=room,user=admin); db.commit()
    return RedirectResponse('/admin#rooms',303)

@app.post('/admin/rooms/{room_id}/edit')
async def admin_edit_room(room_id:int,request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); room=db.get(Room,room_id)
    if not room: raise HTTPException(404)
    form=await request.form()
    code=str(form.get('code','')).strip().upper()
    zone=str(form.get('zone','')).strip()
    if not code or not zone:
        return RedirectResponse('/admin?room_msg=Room+name+and+zone+are+required&room_msg_type=error#rooms',303)
    duplicate=db.query(Room).filter(Room.code==code,Room.id!=room.id).first()
    if duplicate:
        return RedirectResponse('/admin?room_msg=Room+name+already+exists&room_msg_type=error#rooms',303)
    old_code,old_zone=room.code,room.zone
    room.code=code; room.zone=zone
    log_action(db,'ADMIN_ROOM_EDITED',f'{old_code}/{old_zone} -> {code}/{zone}',room=room,user=admin)
    db.commit()
    return RedirectResponse('/admin?room_msg=Room+updated+successfully#rooms',303)

@app.post('/admin/rooms/{room_id}/delete')
def admin_delete_room(room_id:int,request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); room=db.get(Room,room_id)
    if not room: raise HTTPException(404)
    active=db.query(Call).filter_by(room_id=room.id).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).first()
    if active:
        return RedirectResponse('/admin?room_msg=Cannot+delete+a+room+with+an+active+call&room_msg_type=error#rooms',303)
    if db.query(Call).filter_by(room_id=room.id).first() or db.query(Handover).filter_by(room_id=room.id).first():
        return RedirectResponse('/admin?room_msg=Room+has+call+or+handover+history.+Close+it+instead+to+preserve+audit+records&room_msg_type=error#rooms',303)
    code,zone=room.code,room.zone
    db.query(AuditLog).filter_by(room_id=room.id).update({AuditLog.room_id:None},synchronize_session=False)
    db.delete(room)
    db.add(AuditLog(action='ADMIN_ROOM_DELETED',detail=f'{code} zone={zone}',user_id=admin.id))
    db.commit()
    return RedirectResponse('/admin?room_msg=Room+deleted+successfully#rooms',303)

@app.get('/admin/rooms/{room_id}/qr',response_class=HTMLResponse)
def admin_room_qr(room_id:int,request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['admin']); room=db.get(Room,room_id)
    if not room: raise HTTPException(404)
    patient_url=str(request.base_url).rstrip('/')+f'/room/{room.qr_token}'
    image=qrcode.make(patient_url,image_factory=qrcode.image.svg.SvgPathImage)
    buf=io.BytesIO(); image.save(buf); qr_data=base64.b64encode(buf.getvalue()).decode('ascii')
    auto_print=request.query_params.get('print')=='1'
    return render_template('qr.html',ctx(request,db,room=room,qr_data=qr_data,patient_url=patient_url,auto_print=auto_print))

@app.post('/admin/rooms/{room_id}/toggle')
def admin_toggle_room(room_id:int,request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); room=db.get(Room,room_id)
    if not room: raise HTTPException(404)
    room.occupied=not room.occupied; log_action(db,'ADMIN_ROOM_TOGGLED',f'{room.code} occupied={room.occupied}',room=room,user=admin); db.commit()
    return RedirectResponse('/admin#rooms',303)

@app.post('/admin/rooms/{room_id}/assign')
async def admin_assign_room(room_id:int,request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); room=db.get(Room,room_id)
    if not room: raise HTTPException(404)
    form=await request.form(); nurse_id=str(form.get('nurse_id','')).strip(); nurse=db.get(User,int(nurse_id)) if nurse_id else None
    if nurse and nurse.role!='nurse': raise HTTPException(400)
    old=room.assigned_nurse.name if room.assigned_nurse else 'Unassigned'; room.assigned_nurse_id=nurse.id if nurse else None
    log_action(db,'ADMIN_ROOM_ASSIGNED',f'{room.code}: {old} -> {nurse.name if nurse else "Unassigned"}',room=room,user=admin); db.commit()
    return RedirectResponse('/admin#rooms',303)

@app.post('/admin/rooms/{room_id}/token')
def admin_regenerate_room_token(room_id:int,request:Request,db:Session=Depends(get_db)):
    admin=require_role(request,db,['admin']); room=db.get(Room,room_id)
    if not room: raise HTTPException(404)
    room.qr_token=secrets.token_urlsafe(18); log_action(db,'ADMIN_ROOM_TOKEN_REGENERATED',room.code,room=room,user=admin); db.commit()
    return RedirectResponse('/admin#rooms',303)
@app.post('/api/call/{call_id}/{action}')
def call_action(call_id:int,action:str,request:Request,db:Session=Depends(get_db)):
    u=require_role(request,db,['nurse','charge','manager','ed_manager','admin']); c=db.get(Call,call_id)
    if not c: raise HTTPException(404)
    if action=='ack':
        if u.role=='nurse' and c.assigned_nurse_id!=u.id: raise HTTPException(403)
        c.status='acknowledged'; c.acknowledged_at=now_utc(); log_action(db,'CALL_ACKNOWLEDGED',f'By {u.name}',call=c,user=u)
    elif action=='takeover':
        if u.role not in ['charge','manager','ed_manager','admin']: raise HTTPException(403)
        c.status='taken_over'; c.taken_over_by_id=u.id
        if not c.escalated_at:c.escalated_at=now_utc();c.escalation_reason='Charge nurse manual takeover'
        log_action(db,'CALL_TAKEN_OVER',f'By {u.name}; primary={c.assigned_nurse.name if c.assigned_nurse else "Unassigned"}',call=c,user=u)
    elif action=='arrive':
        if not(u.id in [c.assigned_nurse_id,c.taken_over_by_id] or u.role in ['charge','manager','ed_manager','admin']): raise HTTPException(403)
        c.status='arrived'; c.arrived_at=now_utc(); log_action(db,'NURSE_ARRIVED',f'By {u.name}',call=c,user=u)
    elif action=='resolve':
        if not(u.id in [c.assigned_nurse_id,c.taken_over_by_id] or u.role in ['charge','manager','ed_manager','admin']): raise HTTPException(403)
        c.status='resolved'; c.resolved_at=now_utc(); log_action(db,'CALL_RESOLVED',f'By {u.name}',call=c,user=u)
    else: raise HTTPException(400)
    db.commit(); return {'ok':True,'call':serialize_call(c)}
@app.post('/api/call/{call_id}/reassign')
async def reassign_active_call(call_id:int,request:Request,db:Session=Depends(get_db)):
    supervisor=require_role(request,db,['charge','manager','ed_manager','admin'])
    c=db.get(Call,call_id)
    if not c: raise HTTPException(404)
    if c.status not in ['new','acknowledged','escalated','taken_over']:
        return JSONResponse({'ok':False,'error':'Only an open call that has not reached Arrived can be reassigned.'},409)
    data=await request.json()
    try: nurse_id=int(data.get('nurse_id'))
    except: return JSONResponse({'ok':False,'error':'Select a nurse.'},400)
    reason=str(data.get('reason','')).strip()
    if reason not in ['Workload balancing','Break','Shift change','No response','Clinical priority','Other']:
        return JSONResponse({'ok':False,'error':'Select a valid reassignment reason.'},400)
    nurse=db.get(User,nurse_id)
    if not nurse or nurse.role!='nurse' or not nurse.active:
        return JSONResponse({'ok':False,'error':'Selected nurse is not active.'},400)
    if c.assigned_nurse_id==nurse.id:
        return JSONResponse({'ok':False,'error':'This nurse is already assigned.'},409)
    old_nurse=c.assigned_nurse
    old_name=old_nurse.name if old_nurse else 'Unassigned'
    old_id=c.assigned_nurse_id
    c.assigned_nurse_id=nurse.id
    c.room.assigned_nurse_id=nurse.id
    if c.status in ['new','acknowledged']:
        c.status='new'; c.acknowledged_at=None
    elif c.status in ['escalated','taken_over']:
        c.status='escalated'; c.taken_over_by_id=None
    detail=f'{c.room.code}: {old_name} -> {nurse.name}; reason={reason}; by={supervisor.name}; original_call_time={c.created_at.isoformat()}'
    log_action(db,'CALL_REASSIGNED',detail,room=c.room,call=c,user=supervisor)
    db.commit()
    send_push_to_user(db,nurse.id,f'Reassigned Call - {c.room.code}',f'{reason}. Patient call requires your response.','/nurse')
    if old_id:
        send_push_to_user(db,old_id,f'Call Reassigned - {c.room.code}',f'Call moved to {nurse.name} by {supervisor.name}.','/nurse')
    return {'ok':True,'call':serialize_call(c),'from_nurse':old_name,'to_nurse':nurse.name,'reason':reason,'timer_preserved':True}

@app.post('/api/room/{room_id}/assign')
async def assign_room(room_id:int,request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['charge','manager','ed_manager','admin']); data=await request.json(); room=db.get(Room,room_id); nurse=db.get(User,int(data['nurse_id']))
    if not room or not nurse: raise HTTPException(404)
    if nurse.role!='nurse': return JSONResponse({'ok':False,'error':'Only nurse users can be assigned'},400)
    old=room.assigned_nurse; room.assigned_nurse_id=nurse.id; log_action(db,'ROOM_ASSIGNED',f'{room.code}: {old.name if old else "Unassigned"} -> {nurse.name}',room=room); db.commit(); return {'ok':True}

@app.post('/api/handover')
async def create_handover(request:Request,db:Session=Depends(get_db)):
    u=require_role(request,db,['nurse','charge','manager','ed_manager','admin']); data=await request.json(); room=db.get(Room,int(data['room_id'])); to_nurse=db.get(User,int(data['to_nurse_id']))
    if not room or not to_nurse: raise HTTPException(404)
    if to_nurse.role!='nurse': return JSONResponse({'ok':False,'error':'Target must be a nurse'},400)
    if u.role=='nurse' and room.assigned_nurse_id!=u.id: raise HTTPException(403)
    existing=db.query(Handover).filter_by(room_id=room.id,status='pending').first()
    if existing: return {'ok':True,'handover_id':existing.id,'duplicate':True}
    h=Handover(room_id=room.id,from_nurse_id=room.assigned_nurse_id or u.id,to_nurse_id=to_nurse.id,status='pending'); db.add(h); db.flush(); log_action(db,'HANDOVER_CREATED',f'{room.code} -> {to_nurse.name}',room=room,user=u); db.commit(); send_push_to_user(db,to_nurse.id,f'Handover request - {room.code}',f'{u.name} requested room handover','/nurse'); return {'ok':True,'handover_id':h.id}

@app.post('/api/handover/{hid}/accept')
def accept_handover(hid:int,request:Request,db:Session=Depends(get_db)):
    u=require_role(request,db,['nurse','charge','manager','ed_manager','admin']); h=db.get(Handover,hid)
    if not h: raise HTTPException(404)
    if u.role=='nurse' and h.to_nurse_id!=u.id: raise HTTPException(403)
    h.status='accepted'; h.accepted_at=now_utc(); h.room.assigned_nurse_id=h.to_nurse_id; log_action(db,'HANDOVER_ACCEPTED',f'{h.room.code}: {h.from_nurse.name} -> {h.to_nurse.name}',room=h.room,user=u); db.commit(); return {'ok':True}

@app.post('/api/push/subscribe')
async def push_subscribe(request:Request,db:Session=Depends(get_db)):
    u=require_role(request,db,['nurse','charge','manager','ed_manager','admin']); payload=await request.json(); endpoint=payload.get('endpoint')
    if not endpoint:return JSONResponse({'ok':False},400)
    rec=db.query(PushSubscription).filter_by(endpoint=endpoint).first()
    if rec:rec.user_id=u.id;rec.payload=json.dumps(payload)
    else:db.add(PushSubscription(user_id=u.id,endpoint=endpoint,payload=json.dumps(payload)))
    db.commit(); return {'ok':True}
@app.get('/api/live')
def live(request:Request,db:Session=Depends(get_db)):
    u=require_role(request,db,['nurse','charge','manager','ed_manager','admin']); enforce_escalations(db); q=db.query(Call).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])); q=q.filter_by(assigned_nurse_id=u.id) if u.role=='nurse' else q; return [serialize_call(c) for c in q.order_by(Call.created_at).all()]
@app.get('/manifest.webmanifest')
def manifest(): return Response(MANIFEST_JSON,media_type='application/manifest+json')
@app.get('/sw.js')
def sw(): return Response(SERVICE_WORKER_JS,media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})

def seed_demo():
    db=SessionLocal()
    try:
        if db.query(User).first():return
        created={}
        for name,email,role in [('Nurse Sara','sara@demo.local','nurse'),('Nurse Mona','mona@demo.local','nurse'),('Charge Nurse Fatima','charge@demo.local','charge'),('Nurse Manager','manager@demo.local','manager'),('ED Department Manager','edmanager@demo.local','ed_manager'),('System Admin','admin@demo.local','admin')]:
            u=User(name=name,email=email,role=role,password_hash=pwd_hash('Demo123!'));db.add(u);db.flush();created[email]=u
        for i in range(1,9):db.add(Room(code=f'ED-{i:02d}',zone='ED Main' if i<=4 else 'Fast Track',qr_token=f'room-{i:02d}-secure-token',occupied=True,assigned_nurse_id=created['sara@demo.local'].id if i<=4 else created['mona@demo.local'].id))
        db.commit()
    finally:db.close()
seed_demo()
