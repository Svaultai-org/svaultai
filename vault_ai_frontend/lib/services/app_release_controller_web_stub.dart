/// Non-web stub for AppReleaseController. On mobile/desktop the
/// service worker + Cache Storage APIs do not apply; every hook is
/// a no-op.

Future<void> unregisterFlutterServiceWorker() async {}

Future<void> clearAppCodeCacheEntries() async {}

void reloadPage() {}

String? readLastAttemptedTargetRelease() => null;

void writeLastAttemptedTargetRelease(String target) {}
