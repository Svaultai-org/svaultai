// Owns a local scanner attempt so a vault lock or page close stops it even
// when startScan is still pending or fails after starting native work.

import 'monero_scanner.dart';

class MoneroScanSession {
  final MoneroScannerAdapter adapter;
  bool _closed = false;
  bool _starting = false;
  bool _started = false;

  MoneroScanSession(this.adapter);

  bool get isClosed => _closed;
  bool get isActiveOrStarting => _started || _starting;

  Future<void> start(
    MoneroScannerInput input, {
    required bool Function() accessIsCurrent,
  }) async {
    if (_closed || !accessIsCurrent()) {
      input.wipe();
      throw StateError('Vault access changed');
    }
    if (_starting || _started) {
      input.wipe();
      throw StateError('Monero scanner already started');
    }
    _starting = true;
    try {
      await adapter.startScan(input);
      input.wipe();
      _starting = false;
      _started = true;
      if (_closed || !accessIsCurrent()) {
        throw StateError('Vault access changed');
      }
    } catch (_) {
      input.wipe();
      // An adapter may start native work before its Future rejects. Always
      // stop after a failed attempt, including an access change during start.
      _starting = false;
      await _stopQuietly(force: true);
      rethrow;
    } finally {
      input.wipe();
    }
  }

  Future<void> stop() => _stopQuietly();

  Future<void> close() async {
    _closed = true;
    await _stopQuietly();
  }

  Future<void> _stopQuietly({bool force = false}) async {
    if (!force && !_starting && !_started) return;
    try {
      await adapter.stopScan();
      _started = false;
    } catch (_) {
      // Keep the attempted state so a subsequent close/start completion can
      // retry cleanup. The adapter remains responsible for idempotent stop.
      _started = true;
    }
  }
}
