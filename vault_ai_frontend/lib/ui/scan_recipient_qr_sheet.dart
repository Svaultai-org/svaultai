// 2026-07-13: Modal sheet that scans OR uploads a recipient QR and
// returns a validated address (or null if the user cancelled).
//
// Production incident recap:
//
//   * ROUND 1 fix (this file, earlier revision) removed the false-
//     positive "Camera unavailable" that `MobileScanner.errorBuilder`
//     used to trigger on transient controller state.
//
//   * ROUND 2 fix (2026-07-13 iPhone Safari retest): the live camera
//     still failed with "Camera couldn't start".
//     Root cause: `_initMobileScanner()` was called synchronously
//     from `initState()` and immediately awaited
//     `MobileScannerController.start()`. At that moment the
//     `MobileScanner` widget was NOT yet in the tree — the body
//     rendered a plain loading placeholder while `_liveState ==
//     initializing`. `start()` waits for `_MobileScannerState.
//     initState()` to call `controller.attach()`; when that never
//     happens (widget never mounted), the internal
//     `_isAttachedCompleter.future.timeout(500ms)` fires and
//     `start()` throws `MobileScannerException(controllerNotAttached)`.
//     The user saw a vague "Camera couldn't start" (unknown
//     category) with no reproduction guidance.
//
//     Fix, per iOS-Safari verified strategy B ("manual startup
//     after mount"):
//       1. `autoStart: false` on the controller so the widget's
//          own `_initializeController()` does NOT call start() —
//          only we do. There is exactly one start per attempt.
//       2. The MobileScanner widget is ALWAYS present in the
//          body while `_liveState != failed` — during
//          `initializing` we overlay a spinner ON TOP of the
//          widget rather than replacing it. This guarantees
//          `attach()` runs before we call `start()`.
//       3. Start is scheduled via
//          `WidgetsBinding.instance.addPostFrameCallback` after
//          the mounting frame renders. This defers start to a
//          moment where `_isAttachedCompleter` has completed.
//       4. Facing fallback (rear -> front) rebuilds the controller
//          under a fresh `ValueKey`, forcing the `MobileScanner`
//          widget to remount so `attach()` runs on the NEW
//          controller. The old sheet's "unknown" facing was a
//          no-op — `mobile_scanner_web`'s delegate maps both
//          `CameraFacing.back` and `CameraFacing.unknown` to
//          `'environment'`.
//       5. Diagnostic code (WEB_START_TIMEOUT, VIDEO_TRACK_NOT_
//          READY, ...) is now surfaced in the failure UI. This
//          lets an operator triage a screenshot without exposing
//          any wallet or QR data.
//
// Behavior:
//   * `MobileScanner.errorBuilder` renders a plain black container
//     so transient controller-value errors during the first frame
//     never blip the sheet into the failure state.
//   * A dedicated `_liveState` machine tracks initialising /
//     running / failed states driven by:
//       (a) `start()` throwing / resolving, OR
//       (b) the controller's ValueNotifier reporting `error != null`.
//   * Live decode + image decode both go through the same
//     `RecipientQrParser` so network-mismatch, wrong-chain, seed-
//     phrase, and private-key rejections are identical between
//     paths.
//   * The sheet NEVER uploads image bytes. Nothing crosses the
//     network from this sheet.

import 'dart:async';

import 'package:flutter/foundation.dart';
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
const String kScanRecipientQrDiagnosticCodeKey =
    'scan_recipient_qr_diagnostic_code';
const String kScanRecipientQrMobileScannerHostKey =
    'scan_recipient_qr_mobile_scanner_host';


enum _LiveState { initializing, running, failed }


/// Testable factory for the exact `MobileScannerController` config
/// used by the recipient QR sheet in production. Unit tests use this
/// to lock in the invariants that made iPhone Safari fail before:
///   * `autoStart: false` — the widget must NEVER call start() on
///     its own; only the sheet's post-frame path calls start(),
///     and only once per generation.
///   * `facing` is either `CameraFacing.back` (initial) or
///     `CameraFacing.front` (facing fallback). It is NEVER
///     `CameraFacing.unknown` (which the web delegate maps to the
///     same `'environment'` string as `back`, making the fallback
///     a no-op).
@visibleForTesting
MobileScannerController buildScanSheetMobileScannerController({
  required CameraFacing facing,
}) {
  assert(
    facing != CameraFacing.unknown,
    'unknown is not a valid facing constraint (mobile_scanner_web '
    'maps it to environment, same as back — makes fallback a no-op)',
  );
  return MobileScannerController(
    formats: const [BarcodeFormat.qrCode],
    detectionSpeed: DetectionSpeed.normal,
    detectionTimeoutMs: 1000,
    facing: facing,
    torchEnabled: false,
    autoStart: false,
  );
}


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
  int _mobileScannerGeneration = 0;
  bool _mobileStartRequested = false;
  bool _mobileStartInFlight = false;
  CameraFacing _currentFacing = CameraFacing.back;
  bool _rearFallbackTried = false;
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
      // Production path: build the controller synchronously so
      // build() can immediately render the MobileScanner widget
      // during the `initializing` state. `start()` is scheduled to
      // run AFTER the mount frame via `addPostFrameCallback` —
      // that guarantees the widget's `attach()` handshake has
      // completed before start() checks `_isAttachedCompleter`.
      _buildMobileController(preferRearCamera: true);
      _scheduleMobileStart();
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

  void _buildMobileController({required bool preferRearCamera}) {
    _currentFacing = preferRearCamera
        ? CameraFacing.back
        : CameraFacing.front;
    _mobileScannerGeneration += 1;
    // CRITICAL: `buildScanSheetMobileScannerController` locks
    // `autoStart: false`. That prevents the double-start race that
    // was producing MobileScannerException(controllerNotAttached)
    // on iPhone Safari — only THIS file calls start(), and only
    // once per generation, only after the widget's attach() has
    // completed via the post-frame callback.
    final ctrl = buildScanSheetMobileScannerController(
      facing: _currentFacing,
    );
    ctrl.addListener(_onControllerValueChanged);
    _mobileSub = ctrl.barcodes.listen((cap) {
      if (_busy || !mounted) return;
      for (final b in cap.barcodes) {
        final raw = b.rawValue;
        if (raw == null || raw.isEmpty) continue;
        _onDecode(raw);
        return;
      }
    });
    _mobileScannerController = ctrl;
    _mobileStartRequested = false;
    _mobileStartInFlight = false;
    if (mounted) {
      _liveState = _LiveState.initializing;
      _lastInitError = null;
    }
  }

  void _scheduleMobileStart() {
    // Defer the actual `start()` to the first post-frame callback
    // after the current build. By then the `MobileScanner` widget
    // that owns this controller has been inserted into the tree
    // and its `initState()` has called `controller.attach()`,
    // completing the `_isAttachedCompleter` guarded by `start()`.
    //
    // This is Strategy B from the production retest runbook:
    //   autoStart: false
    //   mount widget first
    //   start() from a post-frame callback
    //   never call start twice
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _startMobileScanner();
    });
  }

  Future<void> _startMobileScanner() async {
    if (!mounted) return;
    final ctrl = _mobileScannerController;
    if (ctrl == null) return;
    if (_mobileStartRequested || _mobileStartInFlight) return;
    _mobileStartRequested = true;
    _mobileStartInFlight = true;
    try {
      await ctrl.start();
      // The controller listener updates `_liveState` when
      // value.isRunning flips true. Nothing else to do here.
    } catch (e) {
      if (!mounted) {
        _mobileStartInFlight = false;
        return;
      }
      await _handleMobileStartFailure(e);
    } finally {
      _mobileStartInFlight = false;
    }
  }

  void _onControllerValueChanged() {
    final ctrl = _mobileScannerController;
    if (ctrl == null || !mounted) return;
    final v = ctrl.value;
    if (v.error != null && _liveState != _LiveState.failed) {
      // Async surface — schedule a microtask so we do not call
      // setState from inside a ValueNotifier notify cycle.
      final err = v.error!;
      scheduleMicrotask(() {
        if (!mounted) return;
        _handleMobileStartFailure(err);
      });
      return;
    }
    if (v.isRunning && _liveState != _LiveState.running) {
      setState(() {
        _liveState = _LiveState.running;
      });
    }
  }

  Future<void> _handleMobileStartFailure(Object error) async {
    // Facing fallback: if the rear camera failed once, retry with
    // the front camera before showing failure. The previous
    // implementation swapped to `CameraFacing.unknown` which
    // `mobile_scanner_web` maps to `'environment'` — the same
    // constraint as `CameraFacing.back`, so the fallback was a
    // no-op. Front camera is a genuinely different constraint.
    if (!_rearFallbackTried
        && _currentFacing == CameraFacing.back) {
      _rearFallbackTried = true;
      await _teardownMobileController();
      if (!mounted) return;
      setState(() {
        _buildMobileController(preferRearCamera: false);
      });
      _scheduleMobileStart();
      return;
    }
    if (!mounted) return;
    setState(() {
      _liveState = _LiveState.failed;
      _lastInitError = ScannerInitClassifier.classify(error);
    });
  }

  Future<void> _teardownMobileController() async {
    try {
      await _mobileSub?.cancel();
    } catch (_) {}
    _mobileSub = null;
    final ctrl = _mobileScannerController;
    if (ctrl != null) {
      try {
        ctrl.removeListener(_onControllerValueChanged);
      } catch (_) {}
      try {
        await ctrl.dispose();
      } catch (_) {}
    }
    _mobileScannerController = null;
    _mobileStartRequested = false;
    _mobileStartInFlight = false;
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
    // Production path: rebuild a fresh controller from scratch —
    // resets the rear-facing fallback flag so the user gets a full
    // rear → front sequence again.
    _rearFallbackTried = false;
    await _teardownMobileController();
    if (!mounted) return;
    setState(() {
      _buildMobileController(preferRearCamera: true);
    });
    _scheduleMobileStart();
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
      final ctrl = _mobileScannerController;
      if (ctrl != null) {
        try {
          ctrl.removeListener(_onControllerValueChanged);
        } catch (_) {}
        ctrl.dispose();
      }
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
    // 2026-07-13 (v2): the failed surface fully replaces the
    // camera area; the initializing surface OVERLAYS a spinner
    // on top of the still-mounted MobileScanner widget so
    // `attach()` fires before we call `start()`.
    if (_liveState == _LiveState.failed) {
      return _buildCameraFailedSurface();
    }
    return Stack(
      fit: StackFit.expand,
      children: [
        _buildLivePreview(),
        if (_liveState == _LiveState.initializing)
          Container(
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
          ),
      ],
    );
  }

  Widget _buildLivePreview() {
    if (_useInjectedScanner) {
      return Container(color: Colors.black);
    }
    final ctrl = _mobileScannerController;
    if (ctrl == null) return Container(color: Colors.black);
    return MobileScanner(
      // 2026-07-13 (v2): the generation-scoped Key forces a
      // widget REMOUNT when we swap controllers during facing
      // fallback. Without the key, the state's `late final
      // controller` still references the OLD controller and
      // `attach()` never runs on the NEW one.
      key: ValueKey(
        '$kScanRecipientQrMobileScannerHostKey-$_mobileScannerGeneration',
      ),
      controller: ctrl,
      // errorBuilder receives transient errors that could
      // otherwise take the sheet into the dead-end fail state on
      // the very first render. We just render a black surface for
      // the fault-frame; the actual failure decision is driven by
      // start() throwing OR by the controller's value.error
      // changing (see `_onControllerValueChanged`).
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
          const SizedBox(height: 10),
          Text(
            key: const Key(kScanRecipientQrDiagnosticCodeKey),
            'Camera error: ${diag.userFacingCode}',
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: kWalletTextSecondary,
              fontSize: 11,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.4,
              fontFeatures: [FontFeature.tabularFigures()],
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
