import 'dart:async';
import 'dart:js_interop';

@JS('navigator')
external _Navigator get _navigator;

extension type _Navigator(JSObject _) implements JSObject {
  external _LockManager? get locks;
}

extension type _LockManager(JSObject _) implements JSObject {
  external JSPromise<JSAny?> request(JSString name, JSFunction callback);
}

/// Cooperating tabs serialize login writes and token-owned cleanup under one
/// same-origin Web Lock. A read/compare/delete alone is not cross-tab atomic.
/// Without Web Locks, callers can still persist an intentional new login but
/// must decline destructive cleanup whose ownership cannot be guaranteed.
Future<T> withSessionPersistenceLock<T>(
    Future<T> Function(bool exclusive) action) async {
  final locks = _navigator.locks;
  if (locks == null) return action(false);
  final ownerZone = Zone.current;
  late T result;
  Object? actionError;
  StackTrace? actionStack;
  final callback = ((JSAny? _) => ownerZone.run(() {
    return Future<void>.sync(() async {
      try {
        result = await action(true);
      } catch (error, stack) {
        actionError = error;
        actionStack = stack;
      }
    }).toJS;
  })).toJS;
  // Permission/lock errors do not silently fall back to an unguarded delete.
  await locks.request('svaultai:session-persistence:v1'.toJS, callback).toDart;
  if (actionError != null) {
    Error.throwWithStackTrace(actionError!, actionStack!);
  }
  return result;
}
