import 'dart:async';

/// Keeps the unlock PIN available only while a best-effort legacy migration
/// is actively running. The PIN is never persisted or sent in export requests.
class LegacyStagePinLease {
  static const maxLifetime = Duration(minutes: 5);

  String? _pin;
  late final DateTime _expiresAt;
  late final DateTime Function() _now;
  Timer? _timer;

  LegacyStagePinLease(
    String pin, {
    Duration lifetime = maxLifetime,
    DateTime Function()? now,
  }) {
    if (pin.isEmpty || lifetime <= Duration.zero || lifetime > maxLifetime) {
      throw ArgumentError('Invalid migration PIN lease');
    }
    _now = now ?? DateTime.now;
    _expiresAt = _now().add(lifetime);
    _pin = pin;
    _timer = Timer(lifetime, clear);
  }

  void requireActive() {
    if (_pin == null || !_now().isBefore(_expiresAt)) {
      clear();
      throw StateError('Legacy migration PIN lease expired');
    }
  }

  String requirePin() {
    requireActive();
    return _pin!;
  }

  void clear() {
    _pin = null;
    _timer?.cancel();
    _timer = null;
  }
}

/// Re-prompts the owner when another export grant needs a proof after the
/// current short PIN lease has expired. It never extends an existing lease:
/// every renewal requires a fresh owner entry and starts a new timer.
class RenewableLegacyStagePinLease {
  RenewableLegacyStagePinLease({
    required this.promptPin,
    DateTime Function()? now,
    this.lifetime = LegacyStagePinLease.maxLifetime,
  }) : _now = now;

  final Future<String?> Function() promptPin;
  final DateTime Function()? _now;
  final Duration lifetime;
  LegacyStagePinLease? _active;
  Future<String?>? _pendingPrompt;
  bool _closed = false;

  Future<String?> requireOrPrompt() async {
    if (_closed) throw StateError('Owner upgrade is closed');
    final active = _active;
    if (active != null) {
      try {
        return active.requirePin();
      } on StateError {
        active.clear();
        _active = null;
      }
    }
    final pending = _pendingPrompt;
    if (pending != null) return await pending;
    final nextPrompt = _promptAndLease();
    _pendingPrompt = nextPrompt;
    try {
      return await nextPrompt;
    } finally {
      if (identical(_pendingPrompt, nextPrompt)) _pendingPrompt = null;
    }
  }

  Future<String?> _promptAndLease() async {
    final pin = await promptPin();
    if (_closed) throw StateError('Owner upgrade is closed');
    if (pin != null) {
      _active = LegacyStagePinLease(pin, lifetime: lifetime, now: _now);
    }
    return pin;
  }

  void requireActive() {
    if (_closed) throw StateError('Owner upgrade is closed');
    final active = _active;
    if (active == null) throw StateError('Owner verification is unavailable');
    active.requireActive();
  }

  void clear() {
    _closed = true;
    _active?.clear();
    _active = null;
    _pendingPrompt = null;
  }
}

/// An active vault session can finish work authorized by an unexpired server
/// export grant after the local PIN lease has cleared. A new OPAQUE proof still
/// requires the PIN within its original five-minute lease. The server remains
/// responsible for enforcing each grant's page, byte, and expiry limits.
class LegacyStageSessionGuard {
  final LegacyStagePinLease pinLease;
  final void Function() requireSession;
  final void Function()? onPinLeaseExpired;

  const LegacyStageSessionGuard({
    required this.pinLease,
    required this.requireSession,
    this.onPinLeaseExpired,
  });

  /// Use before and after every export, V2 write, and readback request.
  void requireRequest() => requireSession();

  /// Use only when starting a fresh OPAQUE proof for a new export grant.
  String requirePinForProof() {
    requireSession();
    try {
      return pinLease.requirePin();
    } on StateError {
      onPinLeaseExpired?.call();
      rethrow;
    }
  }

  /// An OPAQUE exchange that finishes after the lease expires is discarded.
  void requireProofCompletion() {
    requireSession();
    try {
      pinLease.requireActive();
    } on StateError {
      onPinLeaseExpired?.call();
      rethrow;
    }
  }
}
