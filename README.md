# Burjeel ED Smart Call

Digital call-bell workflow for Emergency Department rooms.

## Core flow
Patient QR -> Call -> Assigned Nurse -> Acknowledge -> Arrive -> Resolve -> Escalation/Charge Takeover.

## Roles
- Nurse: own rooms/calls
- Charge Nurse: all live calls, room assignment, takeover/escalation
- Nurse Manager: monitoring and operational reports
- ED Department Manager: executive workflow and performance monitoring
- Admin: users/rooms/system configuration

## Demo users
All demo accounts use password `Demo123!`.
- sara@demo.local
- mona@demo.local
- charge@demo.local
- manager@demo.local
- edmanager@demo.local
- admin@demo.local

Patient demo URL: `/room/room-01-secure-token`

## Local run
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

## Production
Use PostgreSQL on Render. Configure VAPID keys for Web Push.

> The digital system is designed as an additional workflow channel. A physical/emergency call mechanism should remain available according to the facility's approved clinical and engineering policy.
