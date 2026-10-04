# Native Android pilot setup

This feature is disabled by default. Existing Web Push/VAPID remain separate.

## Firebase provisioning

1. In your Firebase project enable Cloud Messaging API and register Android package `com.burjeel.edcall`.
2. Download that Android app's `google-services.json` and place it at `android/app/google-services.json` (git-ignored). It is client configuration, not a server private key.
3. Provision server sending credentials for the **same project**. Upload a service-account JSON directly to the isolated Render service as a secret file; set `GOOGLE_APPLICATION_CREDENTIALS` to its absolute path and `NATIVE_FCM_ENABLED=true`. Do not paste this key in chat or commit it.
4. Use a feature-branch Render pilot service and test staff/rooms. Build app with `-PapiOrigin=https://YOUR-PILOT.onrender.com` so it targets the isolated service. The default build targets the existing `-dct3` origin; do not use default against production during pilot.

## Build

Requires JDK 17, Android SDK platform 35/build-tools 35.0.0 and network access to Google Maven/Maven Central. Dependencies and Gradle distribution checksum are pinned.

```bash
cd android
./gradlew testDebugUnitTest lintDebug assembleDebug assembleDebugAndroidTest -PapiOrigin=https://YOUR-PILOT.onrender.com
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`. This is debug-signed and for pilot only. Release signing keystore must be supplied outside git; never distribute a release represented as signed/verified until actually built and installed.

Without a Firebase project, `python scripts/android-fixture-config.py` generates an explicitly **build-only** config; its APK cannot receive live FCM. CI uses this fixture to check compilation, JVM tests and lint. CI artifacts are deliberately named NOT-LIVE-FCM.

## Phone enrollment

Install configured APK on a Google Play services Android phone. Log in using the existing staff account. On Android notification setup, tap Enable (permission), then Enable on the setup page to enroll. Tap Test, observe the native notification, and only then Confirm. Confirm requires the same authenticated session/device and a provider-accepted device test within five minutes. Provider acceptance alone never establishes physical delivery.

Browser and PWA registrations remain independent. After a successful native pilot, explicitly revoke the old PWA subscription on the same handset if duplicate alerts are unwanted. Do not delete all subscriptions for a staff account.

Logout disables local reception immediately and queues scoped server revocation if offline; the toolbar discloses pending confirmation. Token rotation is retried through WorkManager. Account transfer requires proof of the previous installation credential. A new installation UUID is needed if Android Keystore credentials are lost.

## Validation and rollback

Use `native-android-validation.md`. Observe `NATIVE_FCM_ACCEPTED`, `NATIVE_FCM_INVALID`, `NATIVE_FCM_ERROR` with event IDs and hashed installation identifiers. These are send outcomes, not display receipts. FCM data-only HIGH messages are displayed immediately by native code with no web request before display. Native fan-out runs in a bounded in-process executor so provider failures do not block Web Push or the call HTTP response. This queue is not durable across process termination/redeploy; full/expired work logs an explicit delivery failure.

Rollback first sets `NATIVE_FCM_ENABLED=false`; Web Push remains available. Return pilot users to their independently verified Browser/PWA subscriptions. Never merge before real locked-phone acceptance succeeds.
