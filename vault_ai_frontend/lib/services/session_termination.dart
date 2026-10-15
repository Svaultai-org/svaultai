library;

/// Session-termination service (Step B.4).
///
/// One idempotent local logout flow driven by the backend's coded 401
/// responses. Every coded 401 the API layer classifies
/// (session_superseded / session_expired / session_revoked /
/// invalid_session) funnels into [SessionTermination.instance.handle],
/// which:
///
///   * marks the process as "terminated" so later authenticated
///     requests short-circuit with the same exception rather than
///     hitting the wire again;
///   * bumps a monotonic [generation] counter so late responses from
///     the pre-termination generation can be discarded by callers who
///     care;
///   * invokes the application-provided [_handler] exactly once per
///     termination generation, even if many concurrent 401 responses
///     arrive at once;
///   * broadcasts a matching event to other open tabs (web only, via
///     conditional import), so a second tab already displaying the
///     vault also drops to the login screen;
///   * ignores peer-tab events for other session fingerprints, and deduplicates
///     termination within the current binding (local generations are not
///     cross-process identities).
///
/// A successful re-login calls [bindSession] before issuing authenticated
/// requests. Binding, reset, and clear all invalidate prior request epochs. The
/// generation counter never decreases — it only advances — so
/// generation-comparing callers can tell "still the same session" vs
/// "session was ended and possibly restarted" without a live handle
/// to the service.

import 'dart:async';
import 'dart:collection';
import 'dart:convert';

import 'package:crypto/crypto.dart' show sha256;

import 'session_termination_channel.dart'
    if (dart.library.html) 'session_termination_channel_web.dart' as channel;

/// The four backend codes the API layer recognises. Kept as an enum
/// (rather than raw strings inside call-sites) so the compiler helps
/// exhaustiveness at every branch.
enum SessionTerminationCode {
  /// Another device signed into this Vault; this device is displaced.
  superseded,

  /// The session's TTL elapsed.
  expired,

  /// Some non-supersede revoke (logout on another device, admin
  /// revoke, vault delete).
  revoked,

  /// Token no longer decodes / has no matching row / token_id_hash
  /// mismatches / any other "we cannot trust this token" bucket.
  invalid,
}

/// Turn a backend `detail.code` string into an enum, or `null` if the
/// string is not one of the four session codes. Case-sensitive by
/// design: the backend emits exact lowercase snake_case.
SessionTerminationCode? parseSessionTerminationCode(String? raw) {
  switch (raw) {
    case 'session_superseded':
      return SessionTerminationCode.superseded;
    case 'session_expired':
      return SessionTerminationCode.expired;
    case 'session_revoked':
      return SessionTerminationCode.revoked;
    case 'invalid_session':
      return SessionTerminationCode.invalid;
    default:
      return null;
  }
}

/// User-facing message per code. Fixed strings so translations and
/// tests can pin them.
String userMessageFor(SessionTerminationCode code) {
  switch (code) {
    case SessionTerminationCode.superseded:
      return 'You were signed out because this Vault was opened on another device.';
    case SessionTerminationCode.expired:
      return 'Your session expired. Sign in again.';
    case SessionTerminationCode.revoked:
      return 'Your session was revoked. Sign in again.';
    case SessionTerminationCode.invalid:
      return 'Your session is no longer valid. Sign in again.';
  }
}

/// Event delivered to the application's registered handler.
///
/// [reason] distinguishes a direct 401 from a peer-tab broadcast so
/// the receiving tab can suppress the "another device" message for a
/// peer-driven logout that isn't literally another device.
class SessionTerminationEvent {
  final SessionTerminationCode code;
  final String userMessage;
  final int generation;
  final SessionTerminationReason reason;

  /// Epoch captured before termination, never a raw bearer token.
  final int sessionEpoch;
  final String? sessionFingerprint;

  const SessionTerminationEvent({
    required this.code,
    required this.userMessage,
    required this.generation,
    required this.reason,
    this.sessionEpoch = 0,
    this.sessionFingerprint,
  });

  @override
  String toString() => 'SessionTerminationEvent(code: $code, [redacted])';
}

/// Sensitive, in-memory request fence. Never serialize or log this handle.
/// Only the one-way, non-authorizing fingerprint may reach the peer channel.
final class SessionRequestScope {
  const SessionRequestScope._(this._token, this.sessionEpoch, this._wasBound);

  final String _token;
  final int sessionEpoch;
  final bool _wasBound;
  String get sessionFingerprint => _fingerprint(_token);

  @override
  String toString() => 'SessionRequestScope([redacted])';
}

String _fingerprint(String token) => base64Url
    .encode(sha256
        .convert(utf8.encode('svaultai.session-termination.v2|$token'))
        .bytes)
    .replaceAll('=', '');

enum SessionTerminationReason {
  /// A backend response carried a coded 401.
  server,

  /// Another open tab broadcast that it has terminated.
  peerTab,
}

typedef SessionTerminationHandler = Future<void> Function(
    SessionTerminationEvent event);

/// Process-wide singleton. Not injected via DI — the API layer needs
/// synchronous access from inside static-ish HTTP helpers, and the
/// app's auth state also needs the same instance.
class SessionTermination {
  SessionTermination._();
  static final SessionTermination instance = SessionTermination._();

  int _generation = 0;
  bool _terminated = false;
  bool _handling = false;
  String? _sessionToken;
  int? _terminatedRequestEpoch;
  String? _terminatedSessionFingerprint;
  final LinkedHashSet<String> _retiredFingerprints = LinkedHashSet<String>();
  SessionTerminationHandler? _handler;
  channel.SessionTerminationChannel? _channel;

  /// Monotonic generation counter. Callers that captured a value at
  /// request-issue time can check `SessionTermination.instance
  /// .generation == captured` before applying results, discarding
  /// late responses that belong to a session that has since ended.
  int get generation => _generation;
  int get sessionEpoch => _generation;
  bool get hasBoundSession => _sessionToken != null;

  /// Bind synchronously before hydration validation or persisting a new login.
  /// Even rebinding the same token invalidates previously captured work.
  void bindSession(String token) {
    if (token.isEmpty) throw ArgumentError('A session token is required.');
    _retireCurrentToken();
    _retiredFingerprints.remove(_fingerprint(token));
    _generation += 1;
    _sessionToken = token;
    _terminated = false;
    _handling = false;
    _terminatedRequestEpoch = null;
    _terminatedSessionFingerprint = null;
  }

  SessionRequestScope captureRequest(String token) =>
      SessionRequestScope._(token, _generation, _sessionToken != null);

  bool isCurrentRequest(SessionRequestScope scope) =>
      !_terminated &&
      scope.sessionEpoch == _generation &&
      _sessionToken != null &&
      scope._token == _sessionToken;

  /// Standalone clients may work before app binding, but their responses cannot
  /// terminate an unbound process. Binding/reset always invalidates them.
  bool canUseRequest(SessionRequestScope scope) =>
      !_terminated &&
      scope.sessionEpoch == _generation &&
      (_sessionToken == null
          ? !scope._wasBound &&
              !_retiredFingerprints.contains(scope.sessionFingerprint)
          : scope._token == _sessionToken);

  bool isCurrentTermination(SessionTerminationEvent event) =>
      _terminated &&
      event.generation == _generation &&
      event.sessionFingerprint ==
          (_sessionToken == null ? null : _fingerprint(_sessionToken!));

  /// A probe may finish after its cleanup cleared the binding. The captured
  /// epoch must still identify that exact termination, not a subsequent login.
  bool wasTerminatedRequest(SessionRequestScope scope) =>
      _terminated &&
      scope.sessionEpoch == _terminatedRequestEpoch &&
      scope.sessionFingerprint == _terminatedSessionFingerprint;

  /// `true` between a termination and the next [reset]. While true,
  /// [assertNotTerminated] throws so authenticated requests do not
  /// hit the wire.
  bool get isTerminated => _terminated;

  /// Install the application handler exactly once. Later calls
  /// overwrite the previous handler (useful for hot-restart in
  /// tests).
  void setHandler(SessionTerminationHandler handler) {
    _handler = handler;
  }

  /// Attach the platform peer-tab channel. Safe on non-web (no-op).
  /// Safe to call more than once — the second call closes the prior
  /// channel and replaces it.
  void enablePeerTabListener() {
    _channel?.close();
    final ch = channel.SessionTerminationChannel();
    ch.listen(_onPeerBroadcast);
    _channel = ch;
  }

  /// Detach the peer-tab channel. Called on shutdown/hot-restart.
  void disposePeerTabListener() {
    _channel?.close();
    _channel = null;
  }

  /// Called by the api layer whenever a coded 401 is received.
  /// Idempotent: only the first call per termination generation
  /// invokes the handler; subsequent concurrent calls short-circuit
  /// as no-ops. Reset is required before a new login can start
  /// fresh.
  Future<bool> handle(
    SessionTerminationCode code, {
    SessionTerminationReason reason = SessionTerminationReason.server,
    SessionRequestScope? request,
  }) async {
    if (request != null && !isCurrentRequest(request)) return false;
    if (_handling || _terminated) {
      // A prior 401 already started termination; the redundant one
      // is safe to drop — the handler will run exactly once.
      return false;
    }
    final capturedEpoch = _generation;
    final fingerprint =
        _sessionToken == null ? null : _fingerprint(_sessionToken!);
    _handling = true;
    _terminated = true;
    _terminatedRequestEpoch = capturedEpoch;
    _terminatedSessionFingerprint = fingerprint;
    _generation += 1;
    final event = SessionTerminationEvent(
      code: code,
      userMessage: userMessageFor(code),
      generation: _generation,
      reason: reason,
      sessionEpoch: capturedEpoch,
      sessionFingerprint: fingerprint,
    );
    final handlingGeneration = _generation;
    try {
      // Broadcast BEFORE calling the app handler so peer tabs can
      // start their own cleanup in parallel with ours. Peer-tab
      // triggered terminations do not re-broadcast (avoid loops).
      if (reason == SessionTerminationReason.server) {
        try {
          if (fingerprint != null) _channel?.broadcast(fingerprint, code);
        } catch (_) {
          // Broadcast failures are best-effort; local cleanup still
          // proceeds.
        }
      }
      final handler = _handler;
      if (handler != null) {
        await handler(event);
      }
    } finally {
      // A completed old handler must not unlock another session's termination.
      if (_generation == handlingGeneration) _handling = false;
    }
    return true;
  }

  /// Clear/reset invalidates all prior request work. A successful login must
  /// subsequently [bindSession] with the actual token, not merely reset a flag.
  void reset() {
    _retireCurrentToken();
    _generation += 1;
    _sessionToken = null;
    _terminated = false;
    _handling = false;
    _terminatedRequestEpoch = null;
    _terminatedSessionFingerprint = null;
  }

  /// Clear binding after cleanup without reopening a terminated session.
  /// Anonymous sign-in remains possible; [bindSession] releases the latch.
  void clearSession() {
    _retireCurrentToken();
    _generation += 1;
    _sessionToken = null;
    _handling = false;
  }

  void _retireCurrentToken() {
    final token = _sessionToken;
    if (token == null) return;
    _retiredFingerprints.add(_fingerprint(token));
    if (_retiredFingerprints.length > 100) {
      _retiredFingerprints.remove(_retiredFingerprints.first);
    }
  }

  /// Convenience for the api-client header path. Throws a
  /// [StateError] with a stable message the api layer catches and
  /// converts to a `SessionTerminatedException`; the api layer
  /// cannot import this file's exception type without a cycle, so
  /// we use a sentinel.
  void assertNotTerminated() {
    if (_terminated) {
      throw const _TerminatedSentinel();
    }
  }

  /// TEST-ONLY hook. Full reset of state including generation.
  void resetForTests() {
    _handling = false;
    _terminated = false;
    _generation = 0;
    _sessionToken = null;
    _terminatedRequestEpoch = null;
    _terminatedSessionFingerprint = null;
    _retiredFingerprints.clear();
    _handler = null;
    _channel?.close();
    _channel = null;
  }

  Future<bool> handlePeerTermination(
      String sessionFingerprint, SessionTerminationCode code) async {
    final token = _sessionToken;
    if (token == null || sessionFingerprint != _fingerprint(token)) {
      return false;
    }
    return handle(code,
        reason: SessionTerminationReason.peerTab,
        request: captureRequest(token));
  }

  void _onPeerBroadcast(String fingerprint, SessionTerminationCode code) {
    // ignore: discarded_futures
    handlePeerTermination(fingerprint, code);
  }
}

/// Sentinel exception the api layer catches from
/// [SessionTermination.assertNotTerminated]. Not user-facing.
class _TerminatedSentinel implements Exception {
  const _TerminatedSentinel();
}

/// Re-exported so the api layer can catch the sentinel by type
/// without importing a private symbol.
bool isSessionTerminationSentinel(Object e) => e is _TerminatedSentinel;
