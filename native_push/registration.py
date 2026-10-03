"""Scoped native enrollment. Credentials are never staff session credentials."""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, update

Device = Challenge = Verification = User = None

def configure(base, user_model):
    global Device, Challenge, Verification, User
    User = user_model
    class NativePushDevice(base):
        __tablename__ = 'native_push_devices'
        id = Column(Integer, primary_key=True)
        installation_id = Column(String(36), unique=True, nullable=False)
        user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
        fcm_token = Column(Text, unique=True, nullable=False)
        credential_hash = Column(String(64), unique=True, nullable=False)
        active = Column(Boolean, default=True, nullable=False)
        updated_at = Column(DateTime(timezone=True), nullable=False)
    class NativeEnrollmentChallenge(base):
        __tablename__ = 'native_enrollment_challenges'
        digest = Column(String(64), primary_key=True)
        user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
        expires_at = Column(DateTime(timezone=True), nullable=False)
        used = Column(Boolean, default=False, nullable=False)
    class NativeDeviceVerification(base):
        __tablename__ = 'native_device_verifications'
        installation_id = Column(String(36), primary_key=True)
        user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
        confirmed_at = Column(DateTime(timezone=True), nullable=False)
    Verification = NativeDeviceVerification
    Device, Challenge = NativePushDevice, NativeEnrollmentChallenge
    return Device, Challenge

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def _active_user(db, user_id):
    user = db.get(User, user_id)
    if not user or not user.active:
        raise HTTPException(401, 'Account unavailable')
    return user

def issue_challenge(db, user_id: int) -> str:
    _active_user(db, user_id)
    value = secrets.token_urlsafe(32)
    db.add(Challenge(digest=digest(value), user_id=user_id, expires_at=datetime.now(timezone.utc)+timedelta(seconds=120)))
    db.commit()
    return value

def exchange_challenge(db, challenge: str, installation_id: str, fcm_token: str, previous_credential: str = "") -> dict:
    try:
        installation_id = str(uuid.UUID(installation_id))
    except (ValueError, AttributeError):
        raise HTTPException(400, 'Invalid installation')
    _validate_token(fcm_token)
    record = db.get(Challenge, digest(challenge))
    if not record:
        raise HTTPException(403, 'Invalid challenge')
    _active_user(db, record.user_id)
    claimed = db.execute(update(Challenge).where(Challenge.digest==record.digest, Challenge.used.is_(False), Challenge.expires_at>datetime.now(timezone.utc)).values(used=True).execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        db.rollback()
        raise HTTPException(403, 'Expired or used challenge')
    row = db.query(Device).filter_by(installation_id=installation_id).first()
    if row and row.user_id != record.user_id and (not previous_credential or not secrets.compare_digest(row.credential_hash,digest(previous_credential))):
        db.rollback()
        raise HTTPException(403, 'Installation ownership proof required')
    other = db.query(Device).filter_by(fcm_token=fcm_token).first()
    if other and other != row:
        db.rollback()
        raise HTTPException(409, 'Token belongs to another installation')
    credential = secrets.token_urlsafe(32)
    if not row:
        row = Device(installation_id=installation_id)
        db.add(row)
    if row.user_id is not None and row.user_id != record.user_id:
        db.query(Verification).filter_by(installation_id=installation_id).delete()
    row.user_id = record.user_id
    row.fcm_token = fcm_token
    row.credential_hash = digest(credential)
    row.active = True
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {'credential':credential, 'installation_id':installation_id, 'user_id':row.user_id}

def _validate_token(token):
    if not isinstance(token,str) or not 8 <= len(token) <= 4096 or token.strip()!=token:
        raise HTTPException(400, 'Invalid FCM token')

def authenticated_device(db, credential):
    row = db.query(Device).filter_by(credential_hash=digest(credential), active=True).first()
    if not row:
        raise HTTPException(401, 'Device credential unavailable')
    _active_user(db, row.user_id)
    return row

def refresh_device(db, credential: str, fcm_token: str) -> dict:
    row = authenticated_device(db, credential)
    _validate_token(fcm_token)
    other = db.query(Device).filter_by(fcm_token=fcm_token).first()
    if other and other.id != row.id:
        raise HTTPException(409, 'Token belongs to another installation')
    row.fcm_token=fcm_token
    row.updated_at=datetime.now(timezone.utc)
    db.commit()
    return {'ok':True}

def revoke_device(db, credential: str) -> None:
    row=authenticated_device(db,credential)
    row.active=False
    db.commit()
