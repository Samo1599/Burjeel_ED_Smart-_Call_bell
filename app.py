import os, json, hashlib, secrets
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
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
app.mount('/static', StaticFiles(directory=os.path.join(BASE_DIR,'static')), name='static')
templates = Jinja2Templates(directory=os.path.join(BASE_DIR,'templates'))


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
    return RedirectResponse(role_home(u.role),303) if u else templates.TemplateResponse('login.html',ctx(request,db))
@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request,db:Session=Depends(get_db)): return templates.TemplateResponse('login.html',ctx(request,db))
@app.post('/login')
async def login(request:Request,db:Session=Depends(get_db)):
    form=await request.form(); email=str(form.get('email','')).strip().lower(); password=str(form.get('password',''))
    u=db.query(User).filter_by(email=email,active=True).first()
    if u and pwd_check(password,u.password_hash): request.session['user_id']=u.id; return RedirectResponse(role_home(u.role),303)
    return templates.TemplateResponse('login.html',ctx(request,db,error='Invalid credentials'),status_code=401)
@app.get('/logout')
def logout(request:Request): request.session.clear(); return RedirectResponse('/login',303)
@app.get('/room/{token}',response_class=HTMLResponse)
def patient_room(token:str,request:Request,db:Session=Depends(get_db)):
    enforce_escalations(db); room=db.query(Room).filter_by(qr_token=token).first()
    if not room: raise HTTPException(404)
    active=db.query(Call).filter_by(room_id=room.id).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).order_by(Call.created_at.desc()).first()
    return templates.TemplateResponse('patient.html',ctx(request,db,room=room,active_call=active))
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
    u=require_role(request,db,['nurse','charge']); enforce_escalations(db); rooms=db.query(Room).filter_by(assigned_nurse_id=u.id).order_by(Room.code).all(); calls=db.query(Call).filter_by(assigned_nurse_id=u.id).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).order_by(Call.created_at).all(); colleagues=db.query(User).filter(User.role=='nurse',User.id!=u.id).order_by(User.name).all(); pending=db.query(Handover).filter_by(to_nurse_id=u.id,status='pending').order_by(Handover.created_at.desc()).all(); return templates.TemplateResponse('nurse.html',ctx(request,db,rooms=rooms,calls=calls,colleagues=colleagues,pending_handovers=pending))
@app.get('/charge',response_class=HTMLResponse)
def charge_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['charge','manager','ed_manager','admin']); enforce_escalations(db); calls=db.query(Call).filter(Call.status.in_(['new','acknowledged','escalated','taken_over','arrived'])).order_by(Call.created_at).all(); rooms=db.query(Room).order_by(Room.code).all(); nurses=db.query(User).filter_by(role='nurse').all(); return templates.TemplateResponse('charge.html',ctx(request,db,calls=calls,rooms=rooms,nurses=nurses))
@app.get('/manager',response_class=HTMLResponse)
def manager_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['manager','ed_manager','admin']); enforce_escalations(db); calls=db.query(Call).order_by(Call.created_at.desc()).limit(200).all(); total=len(calls); escalated=sum(1 for c in calls if c.escalated_at); takeover=sum(1 for c in calls if c.taken_over_by_id); rt=[]
    for c in [x for x in calls if x.resolved_at]:
        s=c.created_at.replace(tzinfo=timezone.utc) if c.created_at.tzinfo is None else c.created_at; e=c.arrived_at or c.resolved_at; e=e.replace(tzinfo=timezone.utc) if e.tzinfo is None else e; rt.append((e-s).total_seconds())
    avg=int(sum(rt)/len(rt)) if rt else 0; return templates.TemplateResponse('manager.html',ctx(request,db,calls=calls,total=total,escalated=escalated,takeover=takeover,avg=avg))
@app.get('/admin',response_class=HTMLResponse)
def admin_page(request:Request,db:Session=Depends(get_db)):
    require_role(request,db,['admin']); return templates.TemplateResponse('admin.html',ctx(request,db,rooms=db.query(Room).order_by(Room.code).all(),users=db.query(User).order_by(User.role,User.name).all()))
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
def manifest(): return FileResponse(os.path.join(BASE_DIR,'static','manifest.webmanifest'),media_type='application/manifest+json')
@app.get('/sw.js')
def sw(): return FileResponse(os.path.join(BASE_DIR,'static','sw.js'),media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})

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
