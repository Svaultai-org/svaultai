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
