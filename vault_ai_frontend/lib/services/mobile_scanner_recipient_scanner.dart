// 2026-07-13: Production scanner adapter for the recipient-QR flow.
//
// Wraps `mobile_scanner ^7.x` behind the app's own
// `RecipientQrScanner` interface. The rest of the app never
// imports `mobile_scanner` directly; only this file does. That
// keeps the choice of scanner package swappable without ripping
// through the Send panels.
//
// Web behavior (the primary target — SVaultAI ships as a Flutter web
// app used from iPhone Safari):
//   * mobile_scanner uses `MediaDevices.getUserMedia({ video })`
//     on Chromium/WebKit browsers.
//   * Camera permission is requested when `start()` is called, NOT
//     when the sheet renders. The prompt is triggered by
//     `MobileScannerController.start()` inside the sheet.
//   * We prefer the rear camera (`CameraFacing.back`) so the user
//     can point the phone at a paper QR without flipping it.
//   * On decode we take the FIRST rawValue only, pause the
//     controller (so the same QR doesn't re-fire), and hand the
//     string to the caller via `results`.
//
// Non-web platforms are still supported by the same package; on
// iOS/Android the Info.plist / AndroidManifest camera permission
// entries are handled at build time by the package's plugin
// scaffolding.

import 'dart:async';

import 'package:mobile_scanner/mobile_scanner.dart';

import 'recipient_qr_scanner.dart';


class MobileScannerRecipientQrScanner implements RecipientQrScanner {
  final MobileScannerController _controller;
  final StreamController<String> _results =
      StreamController<String>.broadcast();
  StreamSubscription<BarcodeCapture>? _sub;
  bool _paused = false;
  bool _disposed = false;
  bool _cameraAvailable = true;

  MobileScannerRecipientQrScanner({MobileScannerController? controller})
      : _controller = controller ??
            MobileScannerController(
              // Only decode QRs (skip 1-D barcodes) so an EAN/UPC
              // sticker in the frame can't trip the flow.
              formats: const [BarcodeFormat.qrCode],
              cameraResolution: null,
              detectionSpeed: DetectionSpeed.normal,
              detectionTimeoutMs: 1000,
              facing: CameraFacing.back,
              torchEnabled: false,
            );

  /// Test-only accessor — exposes the underlying controller so a
  /// widget test can drive it if it uses this adapter directly.
  /// Regular callers should NOT reach past the interface.
  MobileScannerController get debugController => _controller;

  @override
  Stream<String> get results => _results.stream;

  @override
  bool get isCameraAvailable => _cameraAvailable;

  @override
  Future<void> start() async {
    if (_disposed) throw StateError('scanner disposed');
    _paused = false;
    try {
      await _controller.start();
    } catch (_) {
      _cameraAvailable = false;
      return;
    }
    _sub ??= _controller.barcodes.listen(
      _onBarcodeCapture,
      onError: (_) {},
    );
  }

  void _onBarcodeCapture(BarcodeCapture cap) {
    if (_paused || _disposed) return;
    for (final barcode in cap.barcodes) {
      final raw = barcode.rawValue;
      if (raw == null || raw.isEmpty) continue;
      // Pause immediately so a QR held under the camera does not
      // fire a second callback before the UI has decided what to
      // do with the first result.
      _paused = true;
      _results.add(raw);
      return;
    }
  }

  @override
  Future<void> pause() async {
    _paused = true;
    try {
      await _controller.stop();
    } catch (_) {}
  }

  @override
  Future<void> resume() async {
    if (_disposed) return;
    _paused = false;
    try {
      await _controller.start();
    } catch (_) {}
  }

  @override
  Future<void> stop() async {
    _paused = true;
    try {
      await _controller.stop();
    } catch (_) {}
  }

  @override
  Future<void> dispose() async {
    _disposed = true;
    await _sub?.cancel();
    _sub = null;
    try {
      await _controller.dispose();
    } catch (_) {}
    if (!_results.isClosed) {
      await _results.close();
    }
  }
}
