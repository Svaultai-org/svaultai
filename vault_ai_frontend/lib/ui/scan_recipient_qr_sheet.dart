// 2026-07-13: Modal sheet that scans OR uploads a recipient QR and
// returns a validated address (or null if the user cancelled).
//
// Production incident recap (fixed here):
//
//   * The previous version wired `MobileScanner.errorBuilder` to
//     immediately flip the sheet into a dead-end "Camera unavailable"
//     state. `errorBuilder` fires whenever the controller's transient
//     state carries any error object — including states that clear
//     themselves as soon as `start()` resolves. On iPhone Safari the
//     result was: the browser granted the camera (indicator went
//     live) but VaultAI painted the failure fallback before the
//     preview had a chance to render. The user was blocked with only
//     "Enter address manually" as an escape.
//
//   * The failure fallback also had no way to retry or to upload an
//     image, both of which the product requires.
//
// This rewrite delivers three input methods, always reachable:
//
//   1. Live camera preview at the top (started when the sheet
//      opens; retry-able via the "Try camera again" action).
//   2. Upload / capture QR image from the device (via
//      `QrImagePicker` -> local `QrImageDecoder`).
//   3. Cancel + enter address manually (returns null from the
//      sheet; the send panel keeps whatever was already in the
//      destination field).
//
// Behavior:
//   * `errorBuilder` no longer triggers a false-positive failure. A
//     dedicated `_liveState` machine tracks initialising / running /
//     failed states based on the controller's actual value stream.
//   * Rear-camera-first: if the first `start()` fails, the sheet
//     retries with an unconstrained facing. Only after BOTH attempts
//     fail does the failure state show — with the actual diagnostic
//     category and both fallback actions.
//   * Live decode + image decode both go through the same
//     `RecipientQrParser` so network-mismatch, wrong-chain, seed-
//     phrase, and private-key rejections are identical between
//     paths.
//   * The sheet NEVER uploads image bytes. Nothing crosses the
//     network from this sheet.

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../services/qr_image_decoder.dart';
import '../services/qr_image_picker.dart';
import '../services/qr_scanner_diagnostics.dart';
import '../services/recipient_qr_parser.dart';
import '../services/recipient_qr_scanner.dart';
import 'crypto_wallet_engine_design.dart';


const String kScanRecipientQrSheetKey = 'scan_recipient_qr_sheet';
const String kScanRecipientQrCloseBtnKey =
    'scan_recipient_qr_close_btn';
const String kScanRecipientQrManualBtnKey =
    'scan_recipient_qr_manual_btn';
const String kScanRecipientQrUploadBtnKey =
    'scan_recipient_qr_upload_btn';
const String kScanRecipientQrRetryBtnKey =
    'scan_recipient_qr_retry_btn';
const String kScanRecipientQrErrorBannerKey =
    'scan_recipient_qr_error_banner';
const String kScanRecipientQrCameraFailedKey =
    'scan_recipient_qr_camera_failed';
const String kScanRecipientQrCameraLoadingKey =
    'scan_recipient_qr_camera_loading';


enum _LiveState { initializing, running, failed }


/// Present the sheet. Returns the parsed recipient address, or null
/// if the user cancelled / chose manual entry.
///
/// Injection points for widget tests (all optional; production
/// omits them and gets the real mobile_scanner + file_picker):
///   * [scanner]      — the abstract live-camera scanner.
///   * [imagePicker]  — pickable image source.
///   * [imageDecoder] — pure-Dart image → QR text decoder.
Future<String?> showScanRecipientQrSheet({
  required BuildContext context,
  required RecipientNetwork network,
  int? expectedChainId,
  RecipientQrScanner? scanner,
  QrImagePicker? imagePicker,
  QrImageDecoder? imageDecoder,
}) {
  return showModalBottomSheet<String?>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    barrierColor: Colors.black.withOpacity(0.75),
    isDismissible: true,
    enableDrag: true,
    useSafeArea: true,
    builder: (sheetCtx) => _ScanRecipientQrSheet(
      network: network,
      expectedChainId: expectedChainId,
      injectedScanner: scanner,
      imagePicker: imagePicker,
      imageDecoder: imageDecoder,
    ),
  );
}


class _ScanRecipientQrSheet extends StatefulWidget {
  final RecipientNetwork network;
  final int? expectedChainId;
  final RecipientQrScanner? injectedScanner;
  final QrImagePicker? imagePicker;
  final QrImageDecoder? imageDecoder;

  const _ScanRecipientQrSheet({
    required this.network,
    required this.expectedChainId,
    this.injectedScanner,
    this.imagePicker,
    this.imageDecoder,
  });

  @override
  State<_ScanRecipientQrSheet> createState() =>
      _ScanRecipientQrSheetState();
}


class _ScanRecipientQrSheetState extends State<_ScanRecipientQrSheet> {
  RecipientQrScanner? _injectedScanner;
  MobileScannerController? _mobileScannerController;
  StreamSubscription<String>? _injectedSub;
  StreamSubscription<BarcodeCapture>? _mobileSub;
  bool _busy = false;
  bool _uploadInFlight = false;
  bool _cameraFacingFallbackTried = false;
  _LiveState _liveState = _LiveState.initializing;
  ScannerInitDiagnostic? _lastInitError;
  String? _errorMessage;

  bool get _useInjectedScanner => widget.injectedScanner != null;

  late final QrImagePicker _picker =
      widget.imagePicker ?? const FilePickerQrImagePicker();
  late final QrImageDecoder _decoder =
      widget.imageDecoder ?? const ZxingQrImageDecoder();

  @override
  void initState() {
    super.initState();
    if (_useInjectedScanner) {
      _injectedScanner = widget.injectedScanner;
      _wireInjectedScanner();
    } else {
      _initMobileScanner(preferRearCamera: true);
    }
  }

  void _wireInjectedScanner() {
    final s = _injectedScanner!;
    _injectedSub = s.results.listen(_onDecode);
    scheduleMicrotask(() async {
      try {
        await s.start();
        if (!mounted) return;
        if (!s.isCameraAvailable) {
          setState(() {
            _liveState = _LiveState.failed;
            _lastInitError = const ScannerInitDiagnostic(
              category: ScannerInitCategory.noCamera,
              hint: 'fake-camera-unavailable',
            );
          });
        } else {
          setState(() {
            _liveState = _LiveState.running;
          });
        }
      } catch (e) {
        if (!mounted) return;
        setState(() {
          _liveState = _LiveState.failed;
          _lastInitError = ScannerInitClassifier.classify(e);
        });
      }
    });
  }

  Future<void> _initMobileScanner({required bool preferRearCamera}) async {
    // Dispose any prior controller before creating a fresh one.
    await _teardownMobileController();
    final ctrl = MobileScannerController(
      formats: const [BarcodeFormat.qrCode],
      detectionSpeed: DetectionSpeed.normal,
      detectionTimeoutMs: 1000,
      facing: preferRearCamera
          ? CameraFacing.back
          : CameraFacing.unknown,
      torchEnabled: false,
    );
    _mobileScannerController = ctrl;
    _mobileSub = ctrl.barcodes.listen((cap) {
      if (_busy || !mounted) return;
      for (final b in cap.barcodes) {
        final raw = b.rawValue;
        if (raw == null || raw.isEmpty) continue;
        _onDecode(raw);
        return;
      }
    });
    if (mounted) {
      setState(() {
        _liveState = _LiveState.initializing;
        _lastInitError = null;
      });
    }
    try {
      await ctrl.start();
      if (!mounted) return;
      setState(() {
        _liveState = _LiveState.running;
      });
    } catch (e) {
      // Facing-fallback: if the rear camera failed once, retry with
      // no facing constraint before showing a failure. This handles
      // devices where `environment` doesn't map to anything (iPad
      // without rear camera, external webcam on desktop Safari, ...).
      if (preferRearCamera && !_cameraFacingFallbackTried) {
        _cameraFacingFallbackTried = true;
        await _initMobileScanner(preferRearCamera: false);
        return;
      }
      if (!mounted) return;
      setState(() {
        _liveState = _LiveState.failed;
        _lastInitError = ScannerInitClassifier.classify(e);
      });
    }
  }

  Future<void> _teardownMobileController() async {
    try {
      await _mobileSub?.cancel();
    } catch (_) {}
    _mobileSub = null;
    try {
      await _mobileScannerController?.dispose();
    } catch (_) {}
    _mobileScannerController = null;
  }

  Future<void> _onDecode(String raw) async {
    if (_busy) return;
    _busy = true;
    try {
      if (_useInjectedScanner) {
        await _injectedScanner!.pause();
      } else {
        await _mobileScannerController?.stop();
      }
    } catch (_) {}

    final result = RecipientQrParser.parse(
      raw: raw,
      network: widget.network,
      expectedChainId: widget.expectedChainId,
    );
    if (!mounted) return;

    if (result.ok) {
      Navigator.of(context).pop(result.address);
      return;
    }

    setState(() {
      _errorMessage =
          result.rejectMessage ?? 'Unsupported payment QR format.';
    });
    // Resume so the user can point at a different QR without closing.
    try {
      if (_useInjectedScanner) {
        await _injectedScanner!.resume();
      } else {
        await _mobileScannerController?.start();
      }
    } catch (_) {}
    _busy = false;
  }

  Future<void> _handleRetry() async {
    if (_useInjectedScanner) {
      // In test mode we can't "reinitialise" a real scanner. Reset
      // the state so the fake can be re-driven.
      setState(() {
        _liveState = _LiveState.initializing;
        _lastInitError = null;
        _errorMessage = null;
      });
      try {
        await _injectedScanner!.stop();
      } catch (_) {}
      try {
        await _injectedScanner!.start();
        if (!mounted) return;
        setState(() {
          _liveState = _injectedScanner!.isCameraAvailable
              ? _LiveState.running
              : _LiveState.failed;
        });
      } catch (e) {
        if (!mounted) return;
        setState(() {
          _liveState = _LiveState.failed;
          _lastInitError = ScannerInitClassifier.classify(e);
        });
      }
      return;
    }
    _cameraFacingFallbackTried = false;
    await _initMobileScanner(preferRearCamera: true);
  }

  Future<void> _handleUploadImage() async {
    if (_uploadInFlight) return;
    _uploadInFlight = true;
    setState(() {
      _errorMessage = null;
    });
    // Pause live camera during the picker so the browser doesn't
    // fight for the video track.
    try {
      if (_useInjectedScanner) {
        await _injectedScanner?.pause();
      } else {
        await _mobileScannerController?.stop();
      }
    } catch (_) {}
    Uint8List? bytes;
    try {
      bytes = await _picker.pickImageBytes();
    } catch (_) {
      bytes = null;
    }
    if (!mounted) return;
    if (bytes == null) {
      // Cancellation — resume live camera cleanly.
      try {
        if (_useInjectedScanner) {
          await _injectedScanner?.resume();
        } else {
          await _mobileScannerController?.start();
        }
      } catch (_) {}
      _uploadInFlight = false;
      return;
    }
    final decoded = await _decoder.decode(bytes);
    // Drop the bytes reference so GC can reclaim them promptly.
    bytes = null;
    if (!mounted) return;

    switch (decoded.category) {
      case QrImageDecodeCategory.ok:
        final result = RecipientQrParser.parse(
          raw: decoded.text!,
          network: widget.network,
          expectedChainId: widget.expectedChainId,
        );
        if (result.ok) {
          Navigator.of(context).pop(result.address);
          return;
        }
        setState(() {
          _errorMessage = result.rejectMessage
              ?? 'Unsupported payment QR format.';
        });
        break;
      case QrImageDecodeCategory.noQrFound:
        setState(() {
          _errorMessage = 'No QR code was found in this image.';
        });
        break;
      case QrImageDecodeCategory.multipleQrFound:
        setState(() {
          _errorMessage =
              'Multiple QR codes were found. Choose a clearer image.';
        });
        break;
      case QrImageDecodeCategory.decodeError:
        setState(() {
          _errorMessage = "Couldn't read this image. Try a clearer "
              'photo of the QR code.';
        });
        break;
    }
    // Resume live camera so the user can try again.
    try {
      if (_useInjectedScanner) {
        await _injectedScanner?.resume();
      } else {
        await _mobileScannerController?.start();
      }
    } catch (_) {}
    _uploadInFlight = false;
  }

  @override
  void dispose() {
    _injectedSub?.cancel();
    _mobileSub?.cancel();
    if (_useInjectedScanner) {
      _injectedScanner
          ?.stop()
          .then((_) => _injectedScanner?.dispose());
    } else {
      _mobileScannerController?.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    final maxHeight = (mq.size.height - mq.viewInsets.bottom)
        .clamp(0.0, mq.size.height) * 0.92;
    return Focus(
      autofocus: true,
      canRequestFocus: true,
      onKeyEvent: (node, event) {
        if (event is KeyDownEvent
            && event.logicalKey == LogicalKeyboardKey.escape) {
          Navigator.of(context).pop(null);
          return KeyEventResult.handled;
        }
        return KeyEventResult.ignored;
      },
      child: AnimatedPadding(
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
        padding: EdgeInsets.only(bottom: mq.viewInsets.bottom),
        child: Container(
          key: const Key(kScanRecipientQrSheetKey),
          constraints: BoxConstraints(maxHeight: maxHeight),
          decoration: const BoxDecoration(
            color: kWalletBgBase,
            borderRadius: BorderRadius.vertical(
              top: Radius.circular(18),
            ),
            border: Border(
              top: BorderSide(color: kWalletBorder, width: 1),
              left: BorderSide(color: kWalletBorder, width: 1),
              right: BorderSide(color: kWalletBorder, width: 1),
            ),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _buildHeader(context),
              Flexible(child: _buildBody(context)),
              _buildActionRow(context),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 6, 4, 4),
      child: Row(
        children: [
          const SizedBox(width: 44),
          const Expanded(
            child: Text(
              'Scan recipient QR',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: kWalletTextPrimary,
                fontSize: 15,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.2,
              ),
            ),
          ),
          IconButton(
            key: const Key(kScanRecipientQrCloseBtnKey),
            icon: const Icon(Icons.close, color: kWalletTextPrimary),
            tooltip: 'Close',
            onPressed: () => Navigator.of(context).pop(null),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    // 2026-07-13: bounded preview height. Previously the preview
    // used AspectRatio(1) which — at wider viewports — made the
    // sheet too tall to fit the always-visible action row within
    // the screen. Cap the preview at ~44% of the viewport height
    // (with a 240dp floor) so the retry/upload/manual actions
    // always render on-screen even at compact mobile heights.
    final mq = MediaQuery.of(context);
    final availableHeight =
        (mq.size.height - mq.viewInsets.bottom).clamp(0.0, mq.size.height);
    final previewHeight = (availableHeight * 0.44).clamp(240.0, 380.0);
    return SizedBox(
      height: previewHeight,
      child: Stack(
        fit: StackFit.expand,
        children: [
          _buildPreviewOrStateSurface(),
          const Center(child: _AimingFrame()),
          if (_errorMessage != null)
            Positioned(
              left: 12, right: 12, bottom: 12,
              child: _errorBanner(_errorMessage!),
            ),
        ],
      ),
    );
  }

  Widget _buildPreviewOrStateSurface() {
    switch (_liveState) {
      case _LiveState.initializing:
        return Container(
          key: const Key(kScanRecipientQrCameraLoadingKey),
          color: Colors.black,
          child: const Center(
            child: SizedBox(
              width: 22, height: 22,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor:
                    AlwaysStoppedAnimation<Color>(Colors.white70),
              ),
            ),
          ),
        );
      case _LiveState.failed:
        return _buildCameraFailedSurface();
      case _LiveState.running:
        return _buildLivePreview();
    }
  }

  Widget _buildLivePreview() {
    if (_useInjectedScanner) {
      return Container(color: Colors.black);
    }
    return MobileScanner(
      controller: _mobileScannerController!,
      // 2026-07-13 fix: `errorBuilder` receives transient errors
      // that would otherwise take the sheet into the dead-end fail
      // state on the very first render. We just render a black
      // surface for the fault-frame; the actual failure decision is
      // driven by `start()` throwing, which we handle in
      // `_initMobileScanner`.
      errorBuilder: (ctx, error) => Container(color: Colors.black),
      fit: BoxFit.cover,
    );
  }

  Widget _buildCameraFailedSurface() {
    final diag = _lastInitError
        ?? const ScannerInitDiagnostic(
          category: ScannerInitCategory.unknown,
          hint: 'no-diag',
        );
    return Container(
      key: const Key(kScanRecipientQrCameraFailedKey),
      color: kWalletBgTint,
      padding: const EdgeInsets.fromLTRB(20, 24, 20, 20),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(
            Icons.no_photography_outlined,
            color: kWalletTextSecondary,
            size: 36,
          ),
          const SizedBox(height: 12),
          Text(
            diag.userFacingHeadline,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: kWalletTextPrimary,
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            diag.userFacingBody,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: kWalletTextSecondary,
              fontSize: 12,
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }

  Widget _errorBanner(String text) {
    return Container(
      key: const Key(kScanRecipientQrErrorBannerKey),
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.65),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: kWalletAccentDanger.withOpacity(0.65),
          width: 1,
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline_rounded,
              size: 15, color: kWalletAccentDanger),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 12,
                height: 1.35,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildActionRow(BuildContext context) {
    // The action row shows THREE actions.
    //   1. "Try camera again" — visible only if the camera failed.
    //   2. "Upload QR image"  — visible ALWAYS.
    //   3. "Enter address manually" — visible ALWAYS (returns null).
    final showRetry = _liveState == _LiveState.failed;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 12, 18, 14),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (showRetry) ...[
              _primaryAction(
                key: const Key(kScanRecipientQrRetryBtnKey),
                label: 'Try camera again',
                icon: Icons.refresh_rounded,
                onPressed: _handleRetry,
              ),
              const SizedBox(height: 8),
            ],
            _primaryAction(
              key: const Key(kScanRecipientQrUploadBtnKey),
              label: _uploadInFlight
                  ? 'Reading image…'
                  : 'Upload QR image',
              icon: Icons.photo_library_outlined,
              onPressed: _uploadInFlight ? null : _handleUploadImage,
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              key: const Key(kScanRecipientQrManualBtnKey),
              onPressed: () => Navigator.of(context).pop(null),
              icon: const Icon(Icons.keyboard_alt_outlined),
              label: const Text('Enter address manually'),
              style: OutlinedButton.styleFrom(
                foregroundColor: kWalletTextPrimary,
                side: const BorderSide(color: kWalletBorderStrong),
                minimumSize: const Size.fromHeight(44),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _primaryAction({
    required Key key,
    required String label,
    required IconData icon,
    required VoidCallback? onPressed,
  }) {
    return FilledButton.icon(
      key: key,
      onPressed: onPressed,
      icon: Icon(icon, size: 18),
      label: Text(label),
      style: FilledButton.styleFrom(
        backgroundColor: kWalletBgTint,
        foregroundColor: kWalletTextPrimary,
        minimumSize: const Size.fromHeight(46),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: const BorderSide(color: kWalletBorderStrong),
        ),
      ),
    );
  }
}


class _AimingFrame extends StatelessWidget {
  const _AimingFrame();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 220, height: 220,
      child: CustomPaint(painter: _AimingFramePainter()),
    );
  }
}


class _AimingFramePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white.withOpacity(0.9)
      ..strokeWidth = 3
      ..style = PaintingStyle.stroke;
    final s = size.width;
    canvas.drawLine(const Offset(0, 30), const Offset(0, 0), paint);
    canvas.drawLine(const Offset(0, 0), const Offset(30, 0), paint);
    canvas.drawLine(Offset(s - 30, 0), Offset(s, 0), paint);
    canvas.drawLine(Offset(s, 0), Offset(s, 30), paint);
    canvas.drawLine(Offset(0, s - 30), Offset(0, s), paint);
    canvas.drawLine(Offset(0, s), Offset(30, s), paint);
    canvas.drawLine(Offset(s - 30, s), Offset(s, s), paint);
    canvas.drawLine(Offset(s, s), Offset(s, s - 30), paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
