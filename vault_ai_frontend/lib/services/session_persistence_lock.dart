/// Native session storage is isolated per application. The AppState queue
/// provides ordering within this process; no cross-tab lock is necessary.
Future<T> withSessionPersistenceLock<T>(
    Future<T> Function(bool exclusive) action) => action(true);
