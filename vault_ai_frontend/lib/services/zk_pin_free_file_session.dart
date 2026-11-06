import 'session_termination.dart';

/// File-route offers from the exact authenticated OPAQUE session. A failed
/// PIN-free request never retries through a PIN-bearing route in that bearer.
final class ZkPinFreeFileSession {
  ZkPinFreeFileSession._();

  static final ZkPinFreeFileSession instance = ZkPinFreeFileSession._();

  SessionRequestScope? _scope;
  bool _listOffered = false;
  bool _downloadOffered = false;

  void bind({
    required String sessionToken,
    required bool listOffered,
    required bool downloadOffered,
  }) {
    final scope = SessionTermination.instance.captureRequest(sessionToken);
    if (!SessionTermination.instance.isCurrentRequest(scope)) {
      throw StateError('Vault file session changed.');
    }
    _scope = scope;
    _listOffered = listOffered;
    _downloadOffered = downloadOffered;
  }

  bool listOfferedForToken(String token) => _listOffered && _sameSession(token);

  bool downloadOfferedForToken(String token) =>
      _downloadOffered && _sameSession(token);

  bool _sameSession(String token) {
    final scope = _scope;
    return scope != null &&
        SessionTermination.instance.isCurrentRequest(scope) &&
        SessionTermination.instance.isCurrentRequest(
          SessionTermination.instance.captureRequest(token),
        );
  }

  void clear() {
    _scope = null;
    _listOffered = false;
    _downloadOffered = false;
  }
}
