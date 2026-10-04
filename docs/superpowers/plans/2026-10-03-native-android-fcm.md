# Native Android FCM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a nurse Android companion receiving first calls and all three recalls independently of the PWA, with physical locked-phone validation before merge.

**Architecture:** Keep the existing FastAPI site and Web Push transport. Add scoped native device enrollment and Firebase Admin transport, plus a Kotlin app with restricted WebView and native notification handling. Integrate both transports at the existing logical send point.

**Tech Stack:** FastAPI, SQLAlchemy, Firebase Admin Python SDK, Kotlin, Android Firebase Messaging, WorkManager, Gradle.

**Spec:** `docs/superpowers/specs/2026-10-03-native-android-fcm-design.md` (approved 2026-10-03).

## Global Constraints

- Base existing main; independent branch/worktree; preserve existing call routing and three-recall limit.
- Package `com.burjeel.edcall`; minimum Android 8 (API 26).
- Production origin `https://burjeel-ed-smart-call-bell-dct3.onrender.com`; HTTPS only.
- Android priority HIGH; TTL 15 minutes; unique event and display tag per logical send.
- Lock-screen content: room and general alert only, no patient names or detailed reason.
- Browser, PWA, and native registrations remain independent; no inferred cross-device deletion.
- Firebase server credentials and release signing key never enter git or APK.
- No merge or lock-screen success claim before actual physical-phone tests pass.

## Review Focus

1. Token rotates while offline: queued scoped refresh must resume without another login (Tasks 1, 4).
2. Logout offline: UI must disclose pending server revocation rather than claim success (Task 4).
3. An external page or forged origin requests enrollment: deny access to bridge and account mapping (Tasks 1, 3).
4. Android notification permission/channel disabled after enrollment: readiness must become blocked (Tasks 3, 4).
5. Duplicate/reordered FCM events: duplicate event stays one notification; distinct recalls stay distinct (Tasks 2, 3).

## File map

- `app.py`: new SQLAlchemy native tables, authenticated route wiring, login/logout hooks, send integration; no unrelated template rewrite.
- `native_push/registration.py`: challenge exchange, scoped credentials and device lifecycle.
- `native_push/fcm.py`: lazy Firebase initialization, payload mapping, isolated send results.
- `tests/test_native_registration.py`, `tests/test_native_fcm.py`, `tests/test_native_flow.py`: server regression suite using mocked provider, real DB and request boundaries.
- `android/`: pinned Gradle wrapper/configuration and Kotlin app; namespace `com.burjeel.edcall`.
- `android/app/src/main/java/com/burjeel/edcall/`: `MainActivity.kt`, `NativeBridge.kt`, `DeviceStore.kt`, `EnrollmentClient.kt`, `TokenRefreshWorker.kt`, `CallMessagingService.kt`, `CallNotifications.kt`.
- `android/app/src/test/`: JVM tests; `android/app/src/androidTest/`: origin, notification and enrollment instrumentation.
- `.github/workflows/native-push.yml`: reproducible backend checks, Android checks/build using supplied Firebase client configuration.
- `docs/native-android-setup.md`, `docs/native-android-validation.md`: provisioning, pilot, evidence and rollback.

### Task 1: Native registration and scoped ownership

**Files:** app.py, native_push/registration.py, tests/test_native_registration.py.

**Interfaces:** `issue_challenge(db, user_id: int) -> str`; `exchange_challenge(db, challenge: str, installation_id: str, fcm_token: str) -> dict`; `refresh_device(db, credential: str, fcm_token: str) -> dict`; `revoke_device(db, credential: str) -> None`.

Routes: session+CSRF protected `POST /api/mobile/challenge`; single-use `POST /api/mobile/enroll`; scoped bearer `POST /api/mobile/token`, `POST /api/mobile/revoke`; session-owned `GET /api/mobile/status`. Challenge expires after 120 seconds. Credential is random 256-bit, hashed server-side; never returned outside enrollment. Installation ID is random UUID, not hardware identity.

- [ ] Write test `test_challenge_ownership_and_replay`: unauthenticated issuance=401, forged Origin/CSRF=403, supplied user_id cannot override owner, replay/expiry denied; token rotation revokes old credentials on account change.
- [ ] Run `python -m unittest discover -s tests -p 'test_native_registration.py' -v`; confirm failure on missing routes/functions.
- [ ] Implement additive native device/challenge tables and interfaces. Active account required on every enrollment/refresh/send; token uniqueness and transfer are transactional. Logout deactivates the installation linked to the session.
- [ ] Add `test_rotation_revocation_and_disabled_account`: new token replaces old; revoked credential rejected; disabled user gets no device refresh; other installations remain active.
- [ ] Run registration suite; require all assertions pass, then commit this task.

### Task 2: FCM payload and logical-event integration

**Files:** native_push/fcm.py, app.py send_push_to_user, requirements.txt, tests/test_native_fcm.py, tests/test_native_flow.py.

**Interfaces:** `send_native_to_user(db, user_id: int, event: dict, installation_id: str | None = None) -> dict` returns sent/failed/disabled counts. Event includes event_id, sent_at_ms, kind, tag, url and minimal room alert. Keep existing Web Push return fields backward compatible.

- [ ] Write `test_high_priority_unique_recall_events`: initial+three recalls have four unique event IDs/tags, HIGH priority, TTL=900 seconds, no common collapse_key; data values are strings and lock-screen notification excludes detailed reason.
- [ ] Run `python -m unittest discover -s tests -p 'test_native_fcm.py' -v`; verify failing tests before implementation.
- [ ] Implement lazy Firebase Admin transport behind `NATIVE_FCM_ENABLED`; pin verified SDK release at execution. Credential path supplied via GOOGLE_APPLICATION_CREDENTIALS. Send timeout is bounded; invalid/unregistered token deactivates only that row; transient failures log redacted status and never raise into call action.
- [ ] Wire native fan-out outside existing VAPID/empty-web-subscription early returns. Create event identity once, reuse it across transports. Native-targeted test route `POST /api/mobile/test` requires own authenticated session and registered installation.
- [ ] Add `test_three_transports_and_provider_failure`: Browser/PWA/native each receive all four logical events; native-only user works; Web Push failure does not block native and vice versa; targeted native test excludes all other installations. Duplicate event mapping preserves same tag; reorder preserves distinct events.
- [ ] Run `python -m unittest discover -s tests -v` and `node tests/push_worker.cjs`; require old and new tests pass, then commit.

### Task 3: Android shell and immediate native display

**Files:** android Gradle files, manifest, MainActivity.kt, NativeBridge.kt, CallMessagingService.kt, CallNotifications.kt and their tests.

**Interfaces:** `CallNotifications.show(context: Context, event: CallEvent)`; `CallEvent(eventId: String, title: String, body: String, path: String)`; `NativeBridge` exposes only enrollment/status commands to the allowed HTTPS origin. Use WebView origin-aware messaging, not a globally available unrestricted JavaScript interface.

- [ ] Write tests `distinctEventsRemainVisible`, `duplicateEventUsesSameNotification`, `externalNavigationCannotEnroll`, `disabledPermissionBlocksReadiness`. Assert foreign URLs and crafted notification routes cannot open privileged pages or obtain bridge access.
- [ ] Verify tests fail before component implementation. Select current compatible stable Android/Gradle/Kotlin/Firebase versions from official documentation, pin versions and wrapper checksum; install build dependencies only at this execution stage.
- [ ] Implement minSdk=26 shell, allowed-origin WebView, channel HIGH with sound/vibration, Android runtime permission, PendingIntent immutable and restricted internal navigation. Foreground service callback shows immediately without network; background notification+data payload uses Android system display. No permanent foreground service.
- [ ] Disable Web Push creation only in authenticated native session and verify native readiness through server association. Existing browser login still requires its own Web Push setup.
- [ ] Run `cd android && ./gradlew testDebugUnitTest lintDebug`; require passing checks. Run instrumentation on available emulator for bridge and channel behavior; label emulator results separately from phone tests. Commit.

### Task 4: Native enrollment, token refresh and logout

**Files:** DeviceStore.kt, EnrollmentClient.kt, TokenRefreshWorker.kt, MainActivity.kt and lifecycle tests; app.py session binding.

**Interfaces:** `EnrollmentClient.enroll(challenge: String, installationId: String, token: String): EnrollmentResult`; `refresh(token: String): RefreshResult`; `revoke(): RevocationResult`. DeviceStore keeps installation UUID and Keystore-protected scoped credential. Worker retries transient network failures, stops on revoked/unauthorized credentials.

- [ ] Write tests `offlineTokenRotationRetries`, `offlineLogoutShowsPendingRevocation`, `accountSwitchInvalidatesPreviousCredential`, `channelDisabledAfterEnrollmentBlocksReady`.
- [ ] Run Android unit tests and relevant server ownership tests; verify intended failures.
- [ ] Implement challenge exchange through authenticated same-origin flow, encrypted storage, WorkManager refresh/revocation, explicit registration status and own-device test with user confirmation. Logout clears local login immediately and only reports server revocation confirmed after successful revoke. Reinstall creates a new installation.
- [ ] Run Android tests/lint and server suite; require success. Perform emulator account-switch walkthrough without claiming locked-phone delivery. Commit.

### Task 5: Reproducible build and isolated Render pilot

**Files:** CI workflow, setup/validation docs, Android config templates and gitignore.

**Interfaces:** CI consumes Firebase client config from repository secret; Render consumes enable flag and service-account secret file. Signing is supplied externally. No production key is required for mocked unit tests.

- [ ] Add CI jobs running backend tests/Node suite, Android tests/lint and APK build. Use an explicitly labeled build-only fixture config for tests if actual Firebase client config is unavailable; never represent such APK as configured for live delivery.
- [ ] Document Firebase package registration, client config injection, secure Render credential provisioning, external signing and exact repeatable build commands. Confirm absence of keys/tokens in git diff and artifacts intended for sharing.
- [ ] Run the CI-equivalent commands locally and produce APK only if actual build succeeds. Record whether it is test-configured or live-configured.
- [ ] Deploy feature branch to an isolated Render pilot service/account set; do not merge merely to deploy. Verify /healthz, enrollment, targeted test, initial/recall provider acceptance and existing Web Push tests. Monitor Render logs with event/device hashes, no full tokens.
- [ ] Record setup blockers accurately (missing Firebase project/config/signing/phone), preserve working branch, and commit docs/evidence. Feature remains disabled on main.

### Task 6: Physical phone acceptance and merge gate

**Files:** docs/native-android-validation.md; branch fixes discovered during validation.

**Interfaces:** evidence rows contain handset/Android/app version, network, background state, event_id, provider accepted time, visually observed notification time and result. Background FCM acceptance is not a display receipt.

- [ ] With a real phone, install configured APK and enroll test nurse. Test initial+three recalls with app backgrounded and screen locked, without opening it between events; repeat Wi-Fi, mobile data, 20-minute background and forced Doze via adb where available.
- [ ] Require all observed events within 10 seconds in measured scenarios. Separately document force-stop behavior, channel/permission disable, logout and account-switch checks. User-assisted physical observations are labeled as such.
- [ ] Fix failures with regression tests and rerun affected checks. If physical access unavailable, record NOT TESTED and stop before merge; emulator or Render acceptance cannot replace this gate.
- [ ] Run full backend suite, Node worker suite, Android tests/lint/build and whole-branch review. Open/update PR with actual results and limitations.
- [ ] Only after all required tests including phone pass, merge under user authorization, then monitor both main Render services for health and logical send flow. Rollback disables NATIVE_FCM_ENABLED first while preserving existing Web Push and device data.

## Self-review

Registration/security, background display, token lifecycle, coexistence, isolated provisioning, and physical acceptance each have an owning task. Review-focus failures are assigned tests. Server and Android interfaces agree on scoped challenge exchange and session linkage. No step treats provider acceptance, mock tests, or emulator results as physical lock-screen proof.
