import 'session_termination.dart';

/// PIN-free saved-item list/detail availability from an authenticated OPAQUE
/// finalize response. Missing or older server responses leave it off.
final class ZkPinFreeItemReadSession {
  ZkPinFreeItemReadSession._();

  static final ZkPinFreeItemReadSession instance =
      ZkPinFreeItemReadSession._();

  SessionRequestScope? _scope;
  bool _active = false;
  bool _offered = false;
  bool _privateVaultSession = false;

  void bind({
    required String sessionToken,
    required bool offered,
    bool privateVaultSession = false,
  }) {
    final scope = SessionTermination.instance.captureRequest(sessionToken);
    if (!SessionTermination.instance.isCurrentRequest(scope)) {
      throw StateError('Vault item session changed.');
    }
    _scope = scope;
    _active = offered;
    _offered = offered;
    _privateVaultSession = privateVaultSession;
  }

  bool activeForToken(String token) =>
      _active && _sameSession(token);

  /// A lock disables reading, but must never reopen raw-PIN list/detail as
  /// a fallback within the same bearer, including late UI work.
  bool wasOfferedForToken(String token) =>
      _offered && _sameSession(token);

  /// An OPAQUE vault must not regain the legacy PIN route after its MVK is
  /// cleared or a server read offer is withheld. This marker is token-bound
  /// and survives lock until the session is cleared or replaced.
  bool privateVaultForToken(String token) =>
      _privateVaultSession && _sameSession(token);

  bool _sameSession(String token) {
    final scope = _scope;
    return scope != null &&
        SessionTermination.instance.isCurrentRequest(scope) &&
        SessionTermination.instance.isCurrentRequest(
          SessionTermination.instance.captureRequest(token),
        );
  }

  void lock() {
    _active = false;
  }

  void clear() {
    _scope = null;
    _active = false;
    _offered = false;
    _privateVaultSession = false;
  }
}
