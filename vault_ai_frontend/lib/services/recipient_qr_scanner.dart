// 2026-07-13: Injectable QR-scanner adapter for the Send flow.
//
// A single interface hides the underlying scanner package from the
// UI. Widget tests inject a `FakeRecipientQrScanner` that pushes
// synthetic decode results into the stream; production code uses
// the mobile_scanner-backed platform implementation.
//
// Lifecycle contract (matches what mobile_scanner exposes on web):
//
//   * `start()`  — begin camera preview + decoding. Idempotent.
//   * `pause()`  — pause DECODING while keeping the camera up. Used
//                  when we've just decoded a candidate and are
//                  validating it (prevents the "duplicate result
//                  callback for the same physical QR" bug).
//   * `resume()` — resume decoding after `pause()` if the caller
//                  chose to keep scanning after a rejected decode.
//   * `stop()`   — stop the camera + release the surface.
//   * `dispose()` — release the controller entirely. After
//                  `dispose()` the instance MUST NOT be reused.
//
// After `stop()` OR `dispose()` the results stream is closed; the
// UI must not expect further events.

import 'dart:async';

abstract class RecipientQrScanner {
  /// One decode event per physical QR read. Rate-limited by the
  /// implementation so a QR held under the camera does not fire
  /// repeatedly.
  Stream<String> get results;

  Future<void> start();
  Future<void> pause();
  Future<void> resume();
  Future<void> stop();
  Future<void> dispose();

  /// Whether the underlying platform actually has a camera / has
  /// been granted permission. Used by the UI to show a fallback
  /// message ("Camera unavailable — paste the address manually").
  bool get isCameraAvailable;
}


/// In-memory scanner used exclusively in widget tests. The test
/// drives the flow by calling [pushResult].
class FakeRecipientQrScanner implements RecipientQrScanner {
  final StreamController<String> _controller =
      StreamController<String>.broadcast();

  bool _started = false;
  bool _paused = false;
  bool _stopped = false;
  bool _disposed = false;
  bool _cameraAvailable;

  int startCalls = 0;
  int pauseCalls = 0;
  int resumeCalls = 0;
  int stopCalls = 0;
  int disposeCalls = 0;

  FakeRecipientQrScanner({bool cameraAvailable = true})
      : _cameraAvailable = cameraAvailable;

  @override
  Stream<String> get results => _controller.stream;

  @override
  bool get isCameraAvailable => _cameraAvailable;

  /// Test-only: mimic a QR being read from the camera. Duplicate
  /// pushes while paused are suppressed to match the production
  /// contract (mobile_scanner's `useBarcode` deduping).
  void pushResult(String value) {
    if (!_started || _paused || _stopped || _disposed) return;
    _controller.add(value);
  }

  /// Test-only: simulate the platform reporting camera unavailable
  /// (permission denied, no hardware, HTTPS missing on web).
  void setCameraUnavailable() {
    _cameraAvailable = false;
  }

  @override
  Future<void> start() async {
    startCalls++;
    if (_disposed) throw StateError('scanner disposed');
    _started = true;
    _paused = false;
    _stopped = false;
  }

  @override
  Future<void> pause() async {
    pauseCalls++;
    _paused = true;
  }

  @override
  Future<void> resume() async {
    resumeCalls++;
    _paused = false;
  }

  @override
  Future<void> stop() async {
    stopCalls++;
    _stopped = true;
    _started = false;
  }

  @override
  Future<void> dispose() async {
    disposeCalls++;
    _disposed = true;
    _stopped = true;
    _started = false;
    await _controller.close();
  }
}
