# Burjeel ED Smart Call - Test Report

## Automated tests
- Patient creates call -> assigned nurse acknowledges -> arrives -> resolves: PASS
- SLA breach -> Charge Nurse escalation -> takeover -> arrival -> resolve: PASS
- Role access control (nurse blocked from management dashboard): PASS
- Nurse-to-nurse room handover -> recipient accepts -> ownership changes: PASS

Result: **4 passed**.

## Visual journey captures
1. Patient call page ready
2. Patient call active
3. Nurse receives new call
4. Nurse acknowledges
5. Nurse marks arrival
6. Charge Nurse sees SLA escalation
7. Charge Nurse takes over
8. Nurse Manager dashboard
9. Nurse room handover controls
10. Receiving nurse sees pending handover

## Notification implementation
- PWA manifest + service worker are included.
- Push-subscription endpoint is implemented.
- Background Web Push activates when VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are configured on Render.
- In-app workflow remains available when Web Push is unavailable.

## Production note
Keep the approved physical/emergency call-bell path available during pilot and production validation. The digital workflow should not be the sole emergency-call mechanism until hospital clinical/engineering governance approves it.
