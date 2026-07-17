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
///   * ignores duplicate peer-tab events for the same generation to
///     avoid logout loops.
///
/// A successful re-login calls [reset] which clears the "terminated"
/// flag so new authenticated requests are allowed again. The
/// generation counter never decreases — it only advances — so
/// generation-comparing callers can tell "still the same session" vs
/// "session was ended and possibly restarted" without a live handle
/// to the service.

import 'dart:async';

import 'session_termination_channel.dart'
    if (dart.library.html) 'session_termination_channel_web.dart'
    as channel;

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

  const SessionTerminationEvent({
    required this.code,
    required this.userMessage,
    required this.generation,
    required this.reason,
  });
}

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
  SessionTerminationHandler? _handler;
  channel.SessionTerminationChannel? _channel;

  /// Monotonic generation counter. Callers that captured a value at
  /// request-issue time can check `SessionTermination.instance
  /// .generation == captured` before applying results, discarding
  /// late responses that belong to a session that has since ended.
  int get generation => _generation;

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
  Future<void> handle(
    SessionTerminationCode code, {
    SessionTerminationReason reason = SessionTerminationReason.server,
  }) async {
    if (_handling) {
      // A prior 401 already started termination; the redundant one
      // is safe to drop — the handler will run exactly once.
      return;
    }
    if (_terminated && reason == SessionTerminationReason.peerTab) {
      // Peer broadcast arrived after we already terminated locally.
      // Nothing to do; ignore to avoid logout loops.
      return;
    }
    _handling = true;
    _terminated = true;
    _generation += 1;
    final event = SessionTerminationEvent(
      code: code,
      userMessage: userMessageFor(code),
      generation: _generation,
      reason: reason,
    );
    try {
      // Broadcast BEFORE calling the app handler so peer tabs can
      // start their own cleanup in parallel with ours. Peer-tab
      // triggered terminations do not re-broadcast (avoid loops).
      if (reason == SessionTerminationReason.server) {
        try {
          _channel?.broadcast(_generation, code);
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
      _handling = false;
    }
  }

  /// Called by successful login/re-login flows before persisting the
  /// new session. Clears the terminated flag; generation is NOT
  /// rewound so late responses from the prior generation continue to
  /// be recognised as stale.
  void reset() {
    _terminated = false;
    _handling = false;
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
    _handler = null;
    _channel?.close();
    _channel = null;
  }

  void _onPeerBroadcast(int peerGeneration, SessionTerminationCode code) {
    // Ignore self-broadcasts (we already advanced our own generation
    // to `peerGeneration - N` for some small N when we broadcast).
    if (peerGeneration <= _generation) return;
    // Only run once per peer generation.
    // ignore: discarded_futures
    handle(code, reason: SessionTerminationReason.peerTab);
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
