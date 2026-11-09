import 'session_termination.dart';

/// PIN-free saved-item list/detail availability from an authenticated OPAQUE
/// finalize response. Missing or older server responses leave it off.
final class ZkPinFreeItemReadSession {
  ZkPinFreeItemReadSession._();

  static final ZkPinFreeItemReadSession instance = ZkPinFreeItemReadSession._();

  SessionRequestScope? _scope;
  bool _active = false;
  bool _offered = false;
  bool _privateVaultSession = false;
  bool _privateVaultConfirmed = false;
  String? _privateVaultId;
  String? _privateVaultHandle;

  void bind({
    required String sessionToken,
    required bool offered,
    bool privateVaultSession = false,
    String? privateVaultId,
    String? privateVaultHandle,
  }) {
    final scope = SessionTermination.instance.captureRequest(sessionToken);
    if (!SessionTermination.instance.isCurrentRequest(scope)) {
      throw StateError('Vault item session changed.');
    }
    _scope = scope;
    _active = offered;
    _offered = offered;
    _privateVaultSession = privateVaultSession;
    _privateVaultConfirmed = privateVaultSession &&
        privateVaultId?.isNotEmpty == true &&
        privateVaultHandle?.isNotEmpty == true;
    _privateVaultId = privateVaultSession ? privateVaultId : null;
    _privateVaultHandle = privateVaultSession ? privateVaultHandle : null;
  }

  bool activeForToken(String token) => _active && _sameSession(token);

  /// A lock disables reading, but must never reopen raw-PIN list/detail as
  /// a fallback within the same bearer, including late UI work.
  bool wasOfferedForToken(String token) => _offered && _sameSession(token);

  /// An OPAQUE vault must not regain the legacy PIN route after its MVK is
  /// cleared or a server read offer is withheld. This marker is token-bound
  /// and survives lock until the session is cleared or replaced.
  bool privateVaultForToken(String token) =>
      _privateVaultSession && _sameSession(token);

  /// Hydration may know only a persisted handle. A validated response or an
  /// in-session adoption supplies the authoritative identity without changing
  /// a signed offer's active/locked state.
  void updatePrivateVaultForToken({
    required String sessionToken,
    required String vaultId,
    String? vaultHandle,
  }) {
    if (!_sameSession(sessionToken) || vaultId.isEmpty) {
      throw StateError('Vault item session changed.');
    }
    _privateVaultSession = true;
    _privateVaultConfirmed = true;
    _privateVaultId = vaultId;
    _privateVaultHandle = vaultHandle?.isNotEmpty == true ? vaultHandle : null;
  }

  /// A server-confirmed legacy-only identity can discard a stale persisted
  /// handle marker without changing an unrelated replacement session.
  bool clearPrivateVaultForToken(String sessionToken) {
    if (!_sameSession(sessionToken) || _privateVaultConfirmed) return false;
    _privateVaultSession = false;
    _privateVaultConfirmed = false;
    _privateVaultId = null;
    _privateVaultHandle = null;
    return true;
  }

  bool privateVaultKeyMatchesForToken(
    String token, {
    required String? vaultId,
    required String? vaultHandle,
  }) =>
      privateVaultForToken(token) &&
      _privateVaultId != null &&
      _privateVaultHandle != null &&
      _privateVaultId == vaultId &&
      _privateVaultHandle == vaultHandle;

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
    _privateVaultConfirmed = false;
    _privateVaultId = null;
    _privateVaultHandle = null;
  }
}
