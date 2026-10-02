# Re-call delivery diagnostics

Base: a3a0c7e612e13dac67c3c649e3d946ff7fda71d9.

Observed production logs for the reported test:
- First call accepted by the push provider at 2026-10-02 23:03:34 UTC.
- Re-call accepted at 23:06:19 UTC by the same three endpoint hashes.
- Both PWA-tagged subscriptions were accepted (HTTP 201).
- Re-call code already uses unique tags (`recall-{call_id}-{count}`) and high urgency.

These facts rule out a missing send for that test; they do not prove that Chrome received or displayed the event while locked. The user's screenshot was taken after opening the device/PWA and cannot establish the locked display time.

## Change

Every logical push send receives an event ID. Each endpoint gets a signed, expiring receipt token. The worker records its push-handler start time, displays the notification immediately, then posts a best-effort display receipt. There is no session/login dependency in the receipt endpoint. The network callback is bounded to 5 seconds and never precedes display. Verification reporting runs independently of this callback.

`WEBPUSH_ACCEPTED` includes event ID, kind and endpoint hash.
`WEBPUSH_DISPLAYED` includes the same identifiers plus client receive/display timestamps.
No patient text, full endpoint or credentials are included in receipt logs.

A display receipt means `showNotification` resolved; it does not prove a lock-screen popup, sound, user attention or that the phone was locked. Missing receipts are inconclusive if connectivity fails or the worker is old. Client timestamps depend on the phone clock.

## Validation

`python -m unittest discover -s tests -v` exercises independent mock Browser/PWA endpoints, initial call plus all three recalls without intervening registration requests, unique event IDs/tags, receipt signature validation, and worker display without page clients while receipt networking stalls. These are automated simulations, not a physical Android lock-screen test.

## Device test needed

Open the installed Chrome PWA once on the `-dct3` origin to update the worker. Close it, lock the phone, and create a new test call from a different device. After two minutes press Re-call. Record the press time and whether the locked phone alerts. If it does not, record the time the PWA is reopened. Compare the matching event IDs in Render logs. This diagnostic release does not claim to fix the unproven device-level delay.
