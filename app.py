import os, json, hashlib, secrets, base64, io
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware
from jinja2 import Environment, DictLoader, select_autoescape
import qrcode
import qrcode.image.svg
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
    "base.html": "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\"><title>{% block title %}Burjeel ED Call{% endblock %}</title><link rel=\"manifest\" href=\"/manifest.webmanifest\"><meta name=\"theme-color\" content=\"#004f9e\"><link rel=\"apple-touch-icon\" href=\"/static/icons/icon-192.png\"><link rel=\"stylesheet\" href=\"/static/app.css\"></head><body><header class=\"topbar\"><div class=\"brand\"><img src=\"/static/icons/icon-192.png\" alt=\"logo\"><div><b>Burjeel ED Call</b><span>Smart Call Bell</span></div></div>{% if current_user %}<div class=\"userbox\"><span>{{ current_user.name }}</span><small>{{ current_user.role.replace('_',' ')|title }}</small><a href=\"/logout\">Logout</a></div>{% endif %}</header>{% if current_user %}<nav class=\"nav\">{% if current_user.role in ['nurse','charge'] %}<a href=\"/nurse\">My Rooms</a>{% endif %}{% if current_user.role in ['charge','manager','ed_manager','admin'] %}<a href=\"/charge\">Live Board</a>{% endif %}{% if current_user.role in ['manager','ed_manager','admin'] %}<a href=\"/manager\">Management</a>{% endif %}{% if current_user.role == 'admin' %}<a href=\"/admin\">Admin</a>{% endif %}</nav>{% endif %}<main class=\"container\">{% block content %}{% endblock %}</main><script>window.VAPID_PUBLIC_KEY='{{ vapid_public_key|default('') }}';</script><script src=\"/static/app.js\"></script>{% block scripts %}{% endblock %}</body></html>",
    "login.html": "{% extends 'base.html' %}{% block title %}Sign in - Burjeel ED Call{% endblock %}{% block content %}<section class=\"login-shell\"><div class=\"login-card\"><img class=\"hero-logo\" src=\"/static/icons/icon-512.png\"><h1>ED Smart Call Bell</h1><p>Secure staff access</p>{% if error %}<div class=\"alert danger\">{{ error }}</div>{% endif %}<form method=\"post\" action=\"/login\"><label>Email<input name=\"email\" type=\"email\" required placeholder=\"sara@demo.local\"></label><label>Password<input name=\"password\" type=\"password\" required placeholder=\"••••••••\"></label><button class=\"btn primary wide\">Sign in</button></form><div class=\"demo\"><b>Demo</b><span>sara@demo.local / Demo123!</span><span>charge@demo.local / Demo123!</span><span>manager@demo.local / Demo123!</span></div></div></section>{% endblock %}",
    "nurse.html": "{% extends 'base.html' %}{% block title %}My Rooms - Burjeel ED Call{% endblock %}{% block content %}<div class=\"page-head\"><div><div class=\"eyebrow\">Nurse workspace</div><h1>My Rooms</h1><p>Assigned rooms and live patient calls.</p></div><button class=\"btn secondary\" onclick=\"enablePush()\">Enable notifications</button></div><div class=\"stats\"><div class=\"stat\"><b>{{ rooms|length }}</b><span>Assigned rooms</span></div><div class=\"stat red\"><b>{{ calls|length }}</b><span>Active calls</span></div><div class=\"stat amber\"><b>{{ pending_handovers|length }}</b><span>Pending handovers</span></div></div>{% if pending_handovers %}<section class=\"panel\"><h2>Handover requests</h2>{% for h in pending_handovers %}<div class=\"list-row\"><b>{{h.room.code}}</b><span>From {{h.from_nurse.name}}</span><button class=\"btn primary\" onclick=\"acceptHandover({{h.id}})\">Accept</button></div>{% endfor %}</section><br>{% endif %}<section class=\"grid rooms\">{% for room in rooms %}<article class=\"room-card {% if calls|selectattr('room_id','equalto',room.id)|list %}hot{% endif %}\"><div class=\"room-top\"><b>{{ room.code }}</b><span>{{ room.zone }}</span></div>{% set rcalls = calls|selectattr('room_id','equalto',room.id)|list %}{% if rcalls %}{% set c=rcalls[0] %}<div class=\"call-status {{ c.status }}\">{{ c.status.replace('_',' ')|upper }}</div><div class=\"timer\" data-created=\"{{ c.created_at.isoformat() }}\" data-call-id=\"{{ c.id }}\">00:00</div><p>{{ c.reason }}</p><div class=\"actions\">{% if c.status in ['new','escalated'] %}<button class=\"btn primary\" onclick=\"callAction({{c.id}},'ack')\">Acknowledge</button>{% endif %}{% if c.status in ['acknowledged','taken_over','escalated'] %}<button class=\"btn success\" onclick=\"callAction({{c.id}},'arrive')\">Arrived</button>{% endif %}{% if c.status=='arrived' %}<button class=\"btn success\" onclick=\"callAction({{c.id}},'resolve')\">Resolve</button>{% endif %}</div>{% else %}<div class=\"ready\">● Ready</div><p class=\"muted\">No active patient call</p>{% endif %}{% if colleagues %}<div class=\"handover-box\"><select id=\"handover-{{room.id}}\"><option value=\"\">Hand over to…</option>{% for n in colleagues %}<option value=\"{{n.id}}\">{{n.name}}</option>{% endfor %}</select><button class=\"btn secondary\" onclick=\"handoverRoom({{room.id}})\">Handover</button></div>{% endif %}</article>{% endfor %}</section>{% endblock %}",
    "charge.html": "{% extends 'base.html' %}{% block title %}Charge Nurse Live Board{% endblock %}{% block content %}<div class=\"page-head\"><div><div class=\"eyebrow\">Charge Nurse Command</div><h1>ED Live Call Board</h1><p>All active calls, escalations, ownership and room assignment.</p></div><button class=\"btn secondary\" onclick=\"enablePush()\">Enable notifications</button></div><div class=\"stats\"><div class=\"stat\"><b>{{ rooms|length }}</b><span>Rooms</span></div><div class=\"stat red\"><b>{{ calls|length }}</b><span>Open calls</span></div><div class=\"stat amber\"><b>{{ calls|selectattr('status','equalto','escalated')|list|length }}</b><span>Escalated</span></div></div><section class=\"grid rooms\">{% for room in rooms %}{% set rcalls=calls|selectattr('room_id','equalto',room.id)|list %}<article class=\"room-card {% if rcalls %}hot{% endif %}\"><div class=\"room-top\"><b>{{room.code}}</b><span>{{room.zone}}</span></div><div class=\"assignment\">Assigned: <b>{{ room.assigned_nurse.name if room.assigned_nurse else 'Unassigned' }}</b></div>{% if rcalls %}{% set c=rcalls[0] %}<div class=\"call-status {{c.status}}\">{{c.status.replace('_',' ')|upper}}</div><div class=\"timer\" data-created=\"{{ c.created_at.isoformat() }}\" data-call-id=\"{{c.id}}\">00:00</div><p>{{c.reason}}</p>{% if c.escalation_reason %}<div class=\"alert danger small\">{{c.escalation_reason}}</div>{% endif %}<div class=\"actions\">{% if c.status in ['new','escalated'] %}<button class=\"btn danger\" onclick=\"callAction({{c.id}},'takeover')\">Take Over</button>{% endif %}{% if c.status in ['taken_over','acknowledged','escalated'] %}<button class=\"btn success\" onclick=\"callAction({{c.id}},'arrive')\">Arrived</button>{% endif %}{% if c.status=='arrived' %}<button class=\"btn success\" onclick=\"callAction({{c.id}},'resolve')\">Resolve</button>{% endif %}</div>{% else %}<div class=\"ready\">● Ready</div><select onchange=\"assignRoom({{room.id}},this.value)\"><option value=\"\">Reassign nurse…</option>{% for n in nurses %}<option value=\"{{n.id}}\">{{n.name}}</option>{% endfor %}</select>{% endif %}</article>{% endfor %}</section>{% endblock %}",
    "manager.html": "{% extends 'base.html' %}{% block title %}Management Dashboard{% endblock %}{% block content %}<div class=\"page-head\"><div><div class=\"eyebrow\">Operational oversight</div><h1>ED Call Bell Performance</h1><p>Live workflow and recent operational history.</p></div></div><div class=\"stats four\"><div class=\"stat\"><b>{{total}}</b><span>Recent calls</span></div><div class=\"stat red\"><b>{{escalated}}</b><span>Escalations</span></div><div class=\"stat amber\"><b>{{takeover}}</b><span>Charge takeovers</span></div><div class=\"stat\"><b>{{'%02d:%02d'|format(avg//60,avg%60)}}</b><span>Avg arrival response</span></div></div><div class=\"table-wrap\"><table><thead><tr><th>Room</th><th>Call</th><th>Primary nurse</th><th>Status</th><th>Takeover</th><th>Reason</th></tr></thead><tbody>{% for c in calls %}<tr><td><b>{{c.room.code}}</b></td><td>{{c.created_at.strftime('%H:%M:%S')}}</td><td>{{c.assigned_nurse.name if c.assigned_nurse else '-'}}</td><td><span class=\"badge {{c.status}}\">{{c.status.replace('_',' ')}}</span></td><td>{{c.taken_over_by.name if c.taken_over_by else '-'}}</td><td>{{c.reason}}</td></tr>{% endfor %}</tbody></table></div>{% endblock %}",
    "admin.html": "{% extends 'base.html' %}{% block title %}Admin Control Panel{% endblock %}\n{% block content %}\n<div class=\"page-head\"><div><div class=\"eyebrow\">System administration</div><h1>Control Panel</h1><p>Staff, rooms, assignments, QR codes, notifications and audit visibility.</p></div><div class=\"status-pill {{ 'ok' if vapid_ready else 'warn' }}\">{{ 'Push configured' if vapid_ready else 'Push not configured' }}</div></div>\n<div class=\"stats four\"><div class=\"stat\"><b>{{ users|length }}</b><span>Staff accounts</span></div><div class=\"stat\"><b>{{ rooms|length }}</b><span>Rooms</span></div><div class=\"stat red\"><b>{{ active_calls }}</b><span>Active calls</span></div><div class=\"stat amber\"><b>{{ push_count }}</b><span>Push devices</span></div></div>\n<div class=\"admin-tabs\"><a href=\"#staff\">Staff</a><a href=\"#rooms\">Rooms & QR</a><a href=\"#audit\">Audit log</a><a href=\"#system\">System</a></div>\n\n<section id=\"staff\" class=\"panel admin-section\"><div class=\"section-head\"><div><h2>Staff & Roles</h2><p class=\"muted\">Create staff accounts, enable/disable access and reset passwords.</p></div></div>\n<form class=\"admin-form grid-form\" method=\"post\" action=\"/admin/users\"><input name=\"name\" placeholder=\"Full name\" required><input name=\"email\" type=\"email\" placeholder=\"Email\" required><select name=\"role\" required><option value=\"nurse\">Nurse</option><option value=\"charge\">Nurse In Charge</option><option value=\"manager\">Nurse Manager</option><option value=\"ed_manager\">ED Manager</option><option value=\"admin\">System Admin</option></select><input name=\"password\" type=\"password\" placeholder=\"Temporary password (8+ chars)\" minlength=\"8\" required><button class=\"btn primary\">Add staff</button></form>\n<div class=\"table-wrap\"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead><tbody>{% for u in users %}<tr><td><b>{{u.name}}</b></td><td>{{u.email}}</td><td>{{u.role.replace('_',' ')|title}}</td><td><span class=\"badge {{'resolved' if u.active else 'new'}}\">{{'Active' if u.active else 'Disabled'}}</span></td><td><div class=\"row-actions\"><form method=\"post\" action=\"/admin/users/{{u.id}}/toggle\"><button class=\"btn secondary\" {% if u.id==current_user.id %}disabled title=\"You cannot disable your own account\"{% endif %}>{{'Disable' if u.active else 'Enable'}}</button></form><form method=\"post\" action=\"/admin/users/{{u.id}}/reset\"><input name=\"password\" type=\"password\" placeholder=\"New password\" minlength=\"8\" required><button class=\"btn secondary\">Reset</button></form></div></td></tr>{% endfor %}</tbody></table></div></section>\n\n<section id=\"rooms\" class=\"panel admin-section\"><div class=\"section-head\"><div><h2>Rooms, Assignments & QR</h2><p class=\"muted\">Patient links stay hidden behind simple QR controls. Open View QR to display or print the room poster.</p></div></div>\n<form class=\"admin-form grid-form\" method=\"post\" action=\"/admin/rooms\"><input name=\"code\" placeholder=\"Room code e.g. ED-09\" required><input name=\"zone\" placeholder=\"Zone e.g. ED Main\" required><select name=\"nurse_id\"><option value=\"\">Unassigned</option>{% for n in nurses %}<option value=\"{{n.id}}\">{{n.name}}</option>{% endfor %}</select><button class=\"btn primary\">Add room</button></form>\n<div class=\"table-wrap\"><table><thead><tr><th>Room</th><th>Zone</th><th>Nurse</th><th>Status</th><th>QR Code</th><th>Actions</th></tr></thead><tbody>\n{% for r in rooms %}<tr><td><b>{{r.code}}</b></td><td>{{r.zone}}</td><td><form class=\"inline-form\" method=\"post\" action=\"/admin/rooms/{{r.id}}/assign\"><select name=\"nurse_id\"><option value=\"\">Unassigned</option>{% for n in nurses %}<option value=\"{{n.id}}\" {% if r.assigned_nurse_id==n.id %}selected{% endif %}>{{n.name}}</option>{% endfor %}</select><button class=\"btn secondary\">Save</button></form></td><td><span class=\"badge {{'resolved' if r.occupied else 'new'}}\">{{'Active' if r.occupied else 'Closed'}}</span></td>\n<td><div class=\"row-actions\"><a class=\"btn primary qr-action\" href=\"/admin/rooms/{{r.id}}/qr\" target=\"_blank\">View QR</a><a class=\"btn secondary qr-action\" href=\"/admin/rooms/{{r.id}}/qr?print=1\" target=\"_blank\">Print QR</a></div></td>\n<td><div class=\"row-actions\"><form method=\"post\" action=\"/admin/rooms/{{r.id}}/toggle\"><button class=\"btn secondary\">{{'Close' if r.occupied else 'Open'}}</button></form><form method=\"post\" action=\"/admin/rooms/{{r.id}}/token\"><button class=\"btn secondary\">Regenerate QR</button></form></div></td></tr>{% endfor %}\n</tbody></table></div></section>\n\n<section id=\"audit\" class=\"panel admin-section\"><div class=\"section-head\"><div><h2>Audit Log</h2><p class=\"muted\">Latest 100 recorded workflow and administration actions.</p></div></div><div class=\"table-wrap\"><table><thead><tr><th>Time</th><th>Action</th><th>User</th><th>Room</th><th>Detail</th></tr></thead><tbody>{% for a in audit_logs %}<tr><td>{{a.created_at.strftime('%Y-%m-%d %H:%M:%S')}}</td><td><b>{{a.action}}</b></td><td>{{a.user.name if a.user else '-'}}</td><td>{{a.room_id or '-'}}</td><td>{{a.detail or '-'}}</td></tr>{% endfor %}</tbody></table></div></section>\n<section id=\"system\" class=\"panel admin-section\"><h2>System Status</h2><div class=\"system-grid\"><div><span>Database</span><b>Connected</b></div><div><span>SLA</span><b>{{sla_seconds}} sec</b></div><div><span>Web Push</span><b>{{'Configured' if vapid_ready else 'Not configured'}}</b></div><div><span>App mode</span><b>Single-file app.py</b></div></div></section>\n{% endblock %}",
    "qr.html": "{% extends 'base.html' %}{% block title %}{{room.code}} QR Code{% endblock %}{% block content %}\n<section class=\"qr-shell\"><div class=\"qr-poster\"><img class=\"qr-logo\" src=\"/static/icons/icon-512.png\"><div class=\"eyebrow\">{{room.zone}}</div><h1>{{room.code}}</h1><h2>Scan to call your nurse</h2><p class=\"qr-ar\" dir=\"rtl\">امسح الكود لاستدعاء الممرضة</p><img class=\"qr-image\" src=\"data:image/svg+xml;base64,{{qr_data}}\" alt=\"QR code for {{room.code}}\"><p class=\"muted\">Point your phone camera at the QR code.</p><p class=\"qr-ar muted\" dir=\"rtl\">وجّه كاميرا الهاتف إلى رمز QR.</p><div class=\"qr-print-actions\"><button class=\"btn primary\" onclick=\"window.print()\">Print QR</button><a class=\"btn secondary\" href=\"/admin#rooms\">Back</a></div></div></section>\n{% if auto_print %}<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),300));</script>{% endif %}\n{% endblock %}",
    "patient.html": "{% extends 'base.html' %}{% block title %}{{ room.code }} - {{ t.page_title }}{% endblock %}\n{% block content %}\n<section class=\"patient-shell patient-lang\" dir=\"{{ 'rtl' if lang=='ar' else 'ltr' }}\"><div class=\"patient-card\">\n<div class=\"patient-lang-switch\" dir=\"ltr\"><button class=\"lang-chip {{'active' if lang=='en' else ''}}\" onclick=\"setPatientLang('en')\">EN</button><span>•</span><button class=\"lang-chip {{'active' if lang=='ar' else ''}}\" onclick=\"setPatientLang('ar')\">ع</button></div>\n<img class=\"hero-logo\" src=\"/static/icons/icon-512.png\"><div class=\"eyebrow\">{{ room.zone }}</div><h1>{{ room.code }}</h1>\n<h2 class=\"patient-question\">{{ t.help_title }}</h2><p class=\"muted patient-note\">{{ t.help_note }}</p>\n<div id=\"patient-state\">{% if active_call %}\n<div class=\"call-active\"><div class=\"pulse\"></div><h2>{{ t.call_active }}</h2><div class=\"timer\" data-created=\"{{ active_call.created_at.isoformat() }}\" data-call-id=\"{{ active_call.id }}\">00:00</div><p id=\"patientStatus\">{{ status_label }}</p><p class=\"muted\">{{ t.wait_note }}</p></div>\n{% else %}\n<div class=\"reason-grid\"><button class=\"reason selected\" data-reason=\"General assistance\"><span class=\"reason-icon\">🤝</span><span>{{t.general}}</span></button><button class=\"reason\" data-reason=\"Pain\"><span class=\"reason-icon\">❤️‍🩹</span><span>{{t.pain}}</span></button><button class=\"reason\" data-reason=\"Toilet assistance\"><span class=\"reason-icon\">🚻</span><span>{{t.toilet}}</span></button><button class=\"reason\" data-reason=\"IV / Medication\"><span class=\"reason-icon\">💧</span><span>{{t.medication}}</span></button></div>\n<button id=\"callBtn\" class=\"call-btn\" aria-label=\"{{t.call_nurse}}\">🔔<span>{{ t.call_nurse }}</span></button><p id=\"callMessage\" class=\"muted\"></p>\n{% endif %}</div>\n<div class=\"physical-note\">⚠️ {{ t.physical_note }}</div></div></section>\n{% endblock %}\n{% block scripts %}<script>\nconst patientLang='{{lang}}'; const qs=new URLSearchParams(location.search); const stored=localStorage.getItem('edcall-lang');\nif(!qs.has('lang')&&stored&&stored!==patientLang){const u=new URL(location.href);u.searchParams.set('lang',stored);location.replace(u.toString());}\nfunction setPatientLang(l){localStorage.setItem('edcall-lang',l);const u=new URL(location.href);u.searchParams.set('lang',l);location.href=u.toString();}\nlet reason='General assistance';document.querySelectorAll('.reason').forEach(b=>b.onclick=()=>{document.querySelectorAll('.reason').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');reason=b.dataset.reason;});\nconst btn=document.getElementById('callBtn');if(btn)btn.onclick=async()=>{btn.disabled=true;const r=await fetch('/api/room/{{room.qr_token}}/call',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});const d=await r.json();if(d.ok){location.reload()}else{document.getElementById('callMessage').textContent='{{t.error}}';btn.disabled=false;}};\n</script>{% endblock %}"
}
APP_CSS = ":root{--blue:#0059ad;--deep:#023d7b;--ink:#172033;--muted:#667085;--bg:#f3f6fa;--red:#d92d20;--amber:#f79009;--green:#039855;--line:#dfe5ec}*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink)}.topbar{height:76px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:10px 28px;position:sticky;top:0;z-index:10}.brand{display:flex;align-items:center;gap:12px}.brand img{width:46px;height:46px}.brand b,.brand span{display:block}.brand span{font-size:12px;color:var(--muted)}.userbox{text-align:right}.userbox span,.userbox small{display:block}.userbox a{font-size:12px;color:var(--blue)}.nav{background:#fff;padding:10px 28px;display:flex;gap:18px;border-bottom:1px solid var(--line)}.nav a{text-decoration:none;color:var(--deep);font-weight:650}.container{max-width:1280px;margin:0 auto;padding:28px}.page-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}.page-head h1{margin:4px 0 6px;font-size:32px}.page-head p,.muted{color:var(--muted)}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:800;color:var(--blue)}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0 26px}.stats.four{grid-template-columns:repeat(4,1fr)}.stat{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px}.stat b{font-size:30px;display:block}.stat span{color:var(--muted)}.stat.red{border-left:5px solid var(--red)}.stat.amber{border-left:5px solid var(--amber)}.grid.rooms{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}.room-card{background:#fff;border:1px solid var(--line);border-radius:20px;padding:18px;min-height:220px;box-shadow:0 8px 24px rgba(16,24,40,.04)}.room-card.hot{border:2px solid #f1a9a5}.room-top{display:flex;justify-content:space-between;align-items:center}.room-top b{font-size:25px}.room-top span,.assignment{font-size:13px;color:var(--muted)}.assignment{margin:8px 0 16px}.call-status{display:inline-block;margin-top:18px;padding:7px 10px;border-radius:999px;background:#eef2f6;font-weight:800;font-size:12px}.call-status.new,.badge.new{background:#fee4e2;color:#b42318}.call-status.escalated,.badge.escalated{background:#fef0c7;color:#b54708}.call-status.acknowledged,.badge.acknowledged{background:#e0f2fe;color:#026aa2}.call-status.taken_over,.badge.taken_over{background:#f3e8ff;color:#7f56d9}.call-status.arrived,.badge.arrived,.badge.resolved{background:#dcfae6;color:#067647}.timer{font-size:36px;font-variant-numeric:tabular-nums;font-weight:800;margin:9px 0}.ready{margin-top:34px;color:var(--green);font-weight:800}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.btn{border:0;border-radius:12px;padding:11px 15px;font-weight:750;cursor:pointer}.btn.primary{background:var(--blue);color:#fff}.btn.secondary{background:#eaf2fb;color:var(--deep)}.btn.success{background:var(--green);color:#fff}.btn.danger{background:var(--red);color:#fff}.btn.wide{width:100%;font-size:16px}.alert{padding:12px;border-radius:12px;margin:12px 0}.alert.danger{background:#fee4e2;color:#b42318}.alert.small{font-size:12px}.login-shell,.patient-shell{display:grid;place-items:center;min-height:calc(100vh - 150px)}.login-card,.patient-card{width:min(480px,100%);background:#fff;border:1px solid var(--line);border-radius:28px;padding:32px;text-align:center;box-shadow:0 18px 50px rgba(16,24,40,.08)}.hero-logo{width:104px;height:104px;object-fit:contain}.login-card label{text-align:left;display:block;font-weight:700;margin:15px 0}.login-card input,.room-card select{width:100%;margin-top:7px;border:1px solid #cfd7e2;border-radius:12px;padding:12px;font-size:15px}.demo{margin-top:22px;padding:14px;background:#f7f9fc;border-radius:14px;font-size:12px}.demo span{display:block;color:var(--muted);margin-top:4px}.patient-card h1{font-size:44px;margin:5px}.reason-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:22px 0}.reason{padding:12px;border:1px solid var(--line);border-radius:12px;background:#fff;cursor:pointer}.reason.selected{border:2px solid var(--blue);background:#eef6ff}.call-btn{width:220px;height:220px;border-radius:50%;border:10px solid #d7e8fb;background:var(--blue);color:#fff;font-size:46px;box-shadow:0 15px 30px rgba(0,89,173,.25);cursor:pointer}.call-btn span{font-size:20px;display:block;margin-top:8px}.call-active{padding:28px}.pulse{width:20px;height:20px;background:var(--red);border-radius:50%;margin:0 auto;box-shadow:0 0 0 0 rgba(217,45,32,.5);animation:pulse 1.5s infinite}@keyframes pulse{70%{box-shadow:0 0 0 20px rgba(217,45,32,0)}}.table-wrap{background:#fff;border:1px solid var(--line);border-radius:18px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:14px;border-bottom:1px solid #edf0f4;font-size:14px}th{background:#f8fafc}.badge{padding:6px 9px;border-radius:999px;font-size:12px}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}.panel{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px}.list-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;padding:12px 0;border-bottom:1px solid #edf0f4;font-size:14px}@media(max-width:700px){.container{padding:16px}.topbar{padding:8px 14px}.brand b{font-size:14px}.nav{padding:8px 14px;overflow:auto}.stats,.stats.four,.two-col{grid-template-columns:1fr 1fr}.page-head{align-items:flex-start;gap:12px}.page-head h1{font-size:26px}.call-btn{width:190px;height:190px}.userbox span{display:none}}.handover-box{display:flex;gap:8px;margin-top:18px;border-top:1px solid #edf0f4;padding-top:14px}.handover-box select{flex:1;border:1px solid #cfd7e2;border-radius:10px;padding:9px;background:#fff}\n.admin-tabs{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 18px}.admin-tabs a{background:#fff;border:1px solid var(--line);padding:9px 13px;border-radius:999px;text-decoration:none;color:var(--deep);font-weight:750}.admin-section{margin-bottom:18px;scroll-margin-top:110px}.section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.admin-form{margin:12px 0 18px}.grid-form{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px}.admin-form input,.admin-form select,.inline-form select,.row-actions input{border:1px solid #cfd7e2;border-radius:10px;padding:10px;background:#fff;min-width:0}.row-actions,.inline-form{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.row-actions form{display:flex;gap:6px}.row-actions input{width:145px}.status-pill{padding:9px 12px;border-radius:999px;font-weight:800;font-size:12px}.status-pill.ok{background:#dcfae6;color:#067647}.status-pill.warn{background:#fef0c7;color:#b54708}.system-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.system-grid>div{background:#f8fafc;border:1px solid var(--line);border-radius:14px;padding:14px}.system-grid span,.system-grid b{display:block}.system-grid span{color:var(--muted);font-size:12px;margin-bottom:5px}.mono-link{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:var(--blue);word-break:break-all}.btn:disabled{opacity:.45;cursor:not-allowed}@media(max-width:900px){.grid-form{grid-template-columns:1fr 1fr}.system-grid{grid-template-columns:1fr 1fr}}@media(max-width:600px){.grid-form,.system-grid{grid-template-columns:1fr}.row-actions input{width:120px}}\n"
APP_CSS += "\n/* QR + bilingual patient journey */\n.qr-action{text-decoration:none;display:inline-block}.qr-shell{display:grid;place-items:center;min-height:calc(100vh - 150px)}.qr-poster{width:min(520px,100%);background:#fff;border:1px solid var(--line);border-radius:28px;padding:28px;text-align:center;box-shadow:0 18px 50px rgba(16,24,40,.08)}.qr-logo{width:86px;height:86px;object-fit:contain}.qr-poster h1{font-size:42px;margin:6px 0}.qr-poster h2{margin:8px 0}.qr-ar{font-family:Tahoma,Arial,sans-serif}.qr-image{width:min(330px,85vw);height:auto;margin:16px auto;display:block}.qr-print-actions{display:flex;gap:10px;justify-content:center;margin-top:18px}.patient-lang-switch{display:flex;align-items:center;justify-content:flex-end;gap:6px;margin-bottom:8px}.lang-chip{border:1px solid #d0d7e2;background:#fff;border-radius:999px;padding:5px 9px;font-size:12px;font-weight:800;color:var(--deep);cursor:pointer}.lang-chip.active{background:#eaf2fb;border-color:#8eb8e5}.patient-question{font-size:22px;margin:14px 0 4px}.patient-note{margin-top:0}.reason{display:flex;align-items:center;justify-content:center;gap:7px;min-height:58px}.reason-icon{font-size:20px}.physical-note{margin-top:24px;padding:12px 14px;background:#fff7e8;border:1px solid #f4d49b;border-radius:14px;font-size:13px;line-height:1.5}.patient-lang[dir=\"rtl\"] .patient-card{text-align:right}.patient-lang[dir=\"rtl\"] .eyebrow,.patient-lang[dir=\"rtl\"] h1,.patient-lang[dir=\"rtl\"] .patient-question,.patient-lang[dir=\"rtl\"] .patient-note,.patient-lang[dir=\"rtl\"] .call-active{text-align:center}.patient-lang[dir=\"rtl\"] .reason{font-family:Tahoma,Arial,sans-serif}.patient-lang[dir=\"rtl\"] .call-btn span{font-family:Tahoma,Arial,sans-serif}@media print{.topbar,.nav,.qr-print-actions{display:none!important}.container{padding:0}.qr-shell{min-height:auto}.qr-poster{box-shadow:none;border:none;width:100%;padding:10mm}.qr-image{width:95mm}.qr-logo{width:25mm;height:25mm}}"
APP_JS = "function pad(v){return String(v).padStart(2,'0')}function updateTimers(){document.querySelectorAll('.timer[data-created]').forEach(el=>{const s=new Date(el.dataset.created);const sec=Math.max(0,Math.floor((Date.now()-s.getTime())/1000));el.textContent=`${pad(Math.floor(sec/60))}:${pad(sec%60)}`})}setInterval(updateTimers,1000);updateTimers();\nasync function callAction(id,action){const r=await fetch(`/api/call/${id}/${action}`,{method:'POST'});if(r.ok) location.reload();else alert('Action could not be completed.');}\nasync function assignRoom(id,nurseId){if(!nurseId)return;const r=await fetch(`/api/room/${id}/assign`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nurse_id:nurseId})});if(r.ok)location.reload();}\nfunction urlBase64ToUint8Array(base64String){const padding='='.repeat((4-base64String.length%4)%4);const base64=(base64String+padding).replace(/-/g,'+').replace(/_/g,'/');const raw=atob(base64);return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)))}\nasync function enablePush(){if(!('serviceWorker'in navigator)||!('PushManager'in window)){alert('Push notifications are not supported on this device.');return}const reg=await navigator.serviceWorker.register('/sw.js');const permission=await Notification.requestPermission();if(permission!=='granted'){alert('Notification permission was not granted.');return}const key=''+(window.VAPID_PUBLIC_KEY||'');if(!key){alert('Notifications are ready in-app. Configure VAPID keys on the server to activate background Web Push.');return}const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array(key)});await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub)});alert('Notifications enabled.');}\nif('serviceWorker'in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{})}\nasync function handoverRoom(roomId){const el=document.getElementById(`handover-${roomId}`);if(!el||!el.value)return;const r=await fetch('/api/handover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room_id:roomId,to_nurse_id:el.value})});if(r.ok){alert('Handover request sent.');location.reload()}else alert('Handover could not be created.');}\nasync function acceptHandover(id){const r=await fetch(`/api/handover/${id}/accept`,{method:'POST'});if(r.ok)location.reload();else alert('Could not accept handover.');}"
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
    require_role(request,db,['charge','manager','ed_manager','admin']); enforce_escalations(db); calls=db.query(Call).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).order_by(Call.created_at).all(); rooms=db.query(Room).order_by(Room.code).all(); nurses=db.query(User).filter_by(role='nurse').all(); return render_template('charge.html',ctx(request,db,calls=calls,rooms=rooms,nurses=nurses))
@app.get('/manager',response_class=HTMLResponse)
def manager_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['manager','ed_manager','admin']); enforce_escalations(db); calls=db.query(Call).order_by(Call.created_at.desc()).limit(200).all(); total=len(calls); escalated=sum(1 for c in calls if c.escalated_at); takeover=sum(1 for c in calls if c.taken_over_by_id); rt=[]
    for c in [x for x in calls if x.resolved_at]:
        s=c.created_at.replace(tzinfo=timezone.utc) if c.created_at.tzinfo is None else c.created_at; e=c.arrived_at or c.resolved_at; e=e.replace(tzinfo=timezone.utc) if e.tzinfo is None else e; rt.append((e-s).total_seconds())
    avg=int(sum(rt)/len(rt)) if rt else 0; return render_template('manager.html',ctx(request,db,calls=calls,total=total,escalated=escalated,takeover=takeover,avg=avg))
@app.get('/admin',response_class=HTMLResponse)
def admin_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['admin'])
    users=db.query(User).order_by(User.role,User.name).all()
    rooms=db.query(Room).order_by(Room.code).all()
    nurses=db.query(User).filter_by(role='nurse',active=True).order_by(User.name).all()
    audit_logs=db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    active_calls=db.query(Call).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).count()
    push_count=db.query(PushSubscription).count()
    return render_template('admin.html',ctx(request,db,rooms=rooms,users=users,nurses=nurses,audit_logs=audit_logs,active_calls=active_calls,push_count=push_count,vapid_ready=bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)))

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
