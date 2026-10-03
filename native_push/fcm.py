"""Native transport. Provider acceptance never implies lock-screen display."""
import os
import hashlib
import logging
from threading import Lock, BoundedSemaphore
from concurrent.futures import ThreadPoolExecutor
import time
from sqlalchemy import update
from datetime import timedelta
from . import registration

_log=logging.getLogger(__name__)
_lock=Lock()
_executor=ThreadPoolExecutor(max_workers=4,thread_name_prefix="native-fcm")
_slots=BoundedSemaphore(64)

def enabled():
    return os.getenv('NATIVE_FCM_ENABLED','false').lower()=='true'

def _firebase_app():
    import firebase_admin
    with _lock:
        try: return firebase_admin.get_app('burjeel-native')
        except ValueError:
            if not os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
                raise RuntimeError('Firebase credentials not configured')
            return firebase_admin.initialize_app(options={'httpTimeout':10},name='burjeel-native')

def build_message(token, event):
    from firebase_admin import messaging
    path=event.get('url','/nurse')
    if path not in ('/nurse','/charge','/manager','/alerts'): path='/nurse'
    kind=str(event.get('kind','call'))
    title=str(event.get('title','Burjeel ED Call'))[:120]
    # Detailed call reason stays in authenticated web board, never on lock screen.
    body='Repeated call — open the app' if kind=='recall' else 'New alert — open the app'
    data={key:str(event.get(key,'')) for key in ('event_id','sent_at_ms','kind','call_id','recall_count')}
    if kind=='test': data['receipt_token']=str(event.get('receipt_token',''))
    data['url']=path
    data.update(title=title,body=body,registration_hash=str(event.get('registration_hash','')))
    return messaging.Message(token=token,data=data,android=messaging.AndroidConfig(priority='high',ttl=timedelta(minutes=15)))

def send_native_to_user(db,user_id: int,event: dict,installation_id: str | None=None) -> dict:
    result={'sent':0,'failed':0,'disabled':0,'configured':enabled()}
    if not enabled(): return result
    user=db.get(registration.User,user_id)
    if not user or not user.active: return result
    q=db.query(registration.Device).filter_by(user_id=user_id,active=True)
    if installation_id: q=q.filter_by(installation_id=installation_id)
    devices=q.all()
    if not devices: return result
    try:
        from firebase_admin import messaging
        provider=_firebase_app()
    except Exception:
        _log.warning('NATIVE_FCM_UNAVAILABLE event=%s',event.get('event_id'))
        result['configured']=False; result['failed']=len(devices)
        return result
    deadline=time.monotonic()+15
    for device in devices:
        if time.monotonic()>deadline:
            result['failed']+=1
            _log.warning('NATIVE_FCM_DEADLINE event=%s',event.get('event_id'))
            continue
        token_snapshot=device.fcm_token
        generation_snapshot=device.credential_hash
        device_hash=hashlib.sha256(device.installation_id.encode()).hexdigest()[:12]
        try:
            messaging.send(build_message(token_snapshot,{**event,"registration_hash":generation_snapshot}),app=provider)
            result['sent']+=1
            _log.warning('NATIVE_FCM_ACCEPTED event=%s device_hash=%s sent_at_ms=%s',event.get('event_id'),device_hash,event.get('sent_at_ms'))
        except (messaging.UnregisteredError,messaging.SenderIdMismatchError):
            changed=db.execute(update(registration.Device).where(registration.Device.id==device.id,registration.Device.fcm_token==token_snapshot,registration.Device.credential_hash==generation_snapshot).values(active=False).execution_options(synchronize_session=False)).rowcount
            db.commit()
            db.expire(device)
            result['disabled']+=changed; result['failed']+=1
            _log.warning('NATIVE_FCM_INVALID event=%s device_hash=%s',event.get('event_id'),device_hash)
        except Exception as exc:
            result['failed']+=1
            _log.warning('NATIVE_FCM_ERROR event=%s device_hash=%s type=%s',event.get('event_id'),device_hash,type(exc).__name__)
    if result['disabled']: db.commit()
    return result

def dispatch_native(session_factory,user_id: int,event: dict) -> dict:
    """Bounded in-process delivery; survives neither process termination nor redeploy."""
    if not enabled(): return {'queued':0,'configured':False}
    if not _slots.acquire(blocking=False):
        _log.error('NATIVE_FCM_QUEUE_FULL event=%s',event.get('event_id'))
        return {'queued':0,'failed':1}
    queued_at=time.monotonic()
    def deliver():
        try:
            if time.monotonic()-queued_at>15:
                _log.error('NATIVE_FCM_QUEUE_EXPIRED event=%s',event.get('event_id'))
                return
            with session_factory() as db: send_native_to_user(db,user_id,event)
        except Exception as exc:
            _log.error('NATIVE_FCM_JOB_FAILED event=%s type=%s',event.get('event_id'),type(exc).__name__)
        finally: _slots.release()
    try: _executor.submit(deliver)
    except Exception:
        _slots.release()
        return {'queued':0,'failed':1}
    return {'queued':1,'configured':True}
