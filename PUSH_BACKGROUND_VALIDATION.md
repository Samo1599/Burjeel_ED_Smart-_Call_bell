# PWA Push background repair

Base: 812766a828d5e10efc072f2a172e56730144ec67.

## Evidence and changes

Both Render services for this repository ran the base commit. Recent user traffic was on
https://burjeel-ed-smart-call-bell-dct3.onrender.com; the other origin is
https://burjeel-ed-smart-call-bell.onrender.com. A subscription at one origin does not register it at the other.

No WEBPUSH_ERROR or PUSH_TEST_ERROR appeared in the queried post-deploy logs. Existing logs lacked per-endpoint success diagnostics. This does not prove delivery or identify the phone's background failure.

- Show notifications before attempting verification callbacks, and bound callbacks to 5 seconds. Previously a delayed server/network response blocked test notifications.
- Serialize self-healing checks and re-register an existing subscription when its server row is missing, rather than unsubscribing the live OS endpoint.
- Keep concurrent verification records for separate Browser/PWA endpoints.
- Compare the current subscription's VAPID public key before accepting an earlier verification; use the active ready registration in setup.
- Explicit manifest identity and root scope, preserving the prior start URL; no-cache worker delivery.
- Log push-service acceptance using endpoint hashes and context labels, with a 10-second sender timeout. Acceptance is not receipt.
- Label registration as registration, not confirmed delivery.

## Automated validation

Run `python -m pip install -r requirements.txt httpx` and
`python -m unittest discover -s tests -v` with Node available.

5 tests passed. Backend tests use separate mock Browser/PWA endpoints and a mocked sender;
Node executes the worker and client code against API stubs. No native mobile PWA, real push
provider, real VAPID pair, or phone lock screen was exercised by these tests.

## Remaining physical-device check

Use the same production origin in the Browser and installed PWA. Verify each context once,
record their endpoint hashes (they may share an endpoint on some platforms), close the PWA,
lock the phone, trigger a test call from another device, and record send/display times.
Compare WEBPUSH_ACCEPTED / WEBPUSH_ERROR and the targeted verification callback with the
actual visible notification. Do not label a provider acceptance or a foreground callback
as a successful lock-screen test.

Lock-screen symptom remains unconfirmed until that test is performed. The repairs address
reproduced code defects, not a proven OS-level root cause.
