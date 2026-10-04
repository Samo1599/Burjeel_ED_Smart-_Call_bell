# Native push validation evidence

Status as of 2026-10-03: **Not ready for merge or live-delivery claim.**

- Backend suite: 20 tests passed locally, including existing Web Push/Node worker harness, native ownership/replay/expiry, targeted sends and initial+three recall fan-out with mocked FCM.
- Android JVM suite: 11 tests passed (notification/navigation/readiness, receiver existence, and four lifecycle race regressions).
- Android lint: passed with zero errors; text/localization warnings exist in the first pilot UI.
- Debug APK: built successfully using a build-only Firebase fixture. This proves compilation, not live FCM configuration or delivery.
- Android instrumentation: written, not executed; no emulator/physical device available. Instrumentation compilation is checked separately.
- Firebase production project/client config/server credentials: not supplied.
- Isolated Render FCM deployment/send monitoring: not performed; needs Firebase configuration and pilot setup.
- Physical lock screen, 20-minute background, Wi-Fi/mobile and Doze tests: **NOT TESTED**.
- Merge: prohibited until required physical tests pass.

## Physical test sheet

Use only test staff/rooms. Record APK commit/version, handset, Android version, Firebase project and network. Send initial and three recalls without opening the app between them. Repeat with Wi-Fi, mobile data, at least 20 minutes background and forced Doze where adb is available. Target each observed event within 10 seconds; any miss or delay fails that scenario.

| Scenario | Event ID | Provider accepted time | Visually observed time | Delay | Result |
|---|---|---|---|---|---|
| Locked / first | Not run | — | — | — | NOT TESTED |
| Locked / recall 1 | Not run | — | — | — | NOT TESTED |
| Locked / recall 2 | Not run | — | — | — | NOT TESTED |
| Locked / recall 3 | Not run | — | — | — | NOT TESTED |
| 20-minute background | Not run | — | — | — | NOT TESTED |
| Doze | Not run | — | — | — | NOT TESTED |

Also verify permission/channel disabled state, token rotation, offline logout with subsequent server confirmation, account switch with no old-generation notification, and force-stop separately (FCM may require reopening after force-stop). Provider logs and mock results are not substitutes for this sheet.

## Implementation rulings

- Native sends use a bounded in-process executor with separate DB sessions, queue capacity 64, four workers and a 15-second queue admission age. These are not durable across process termination/deployment; expired/full jobs are logged. This prevents FCM outages from blocking the call HTTP action and Web Push.
- FCM notification messages are always collapsible and ignore collapse_key. The approved notification+data approach was corrected to noncollapsible data-only HIGH without collapse_key, then immediate native display. This preserves independent recalls; wake timing remains subject to physical verification.
- Installation transfer requires the previous scoped credential, not UUID alone. Lost Keystore recovery creates a new installation identity.
- Node worker test runs through the Python suite with required JSON input; standalone invocation without input fails.
- Implementation uses a sibling git worktree to preserve the existing checkout.

## Independent review and fixes

One independent whole-branch review found five Critical/Important defects. Regression tests reproduced then fixed: enrollment completion after logout (including stale session cookies), stale refresh rejection clearing newer credentials, token rotation during enrollment, stale invalid-token failure disabling a refreshed registration, and synchronous FCM blocking Web Push. Native state transitions use lifecycle revisions; deferred session cookies apply on the UI thread only to a current attempt. FCM invalidation compares the sent token and credential generation.

Deferred minor: initial/recall call_id and recall_count payload fields are currently empty at some existing call sites; event_id still uniquely correlates each logical send. The initial pilot UI also has localization lint warnings. Physical, live Firebase, Render pilot and actual instrumentation validation remain pending.
