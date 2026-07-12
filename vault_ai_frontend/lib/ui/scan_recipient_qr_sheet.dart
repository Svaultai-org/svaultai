// 2026-07-13: Modal sheet that scans a recipient QR and returns a
// validated address (or null if the user cancelled).
//
// Contract:
//
//   final address = await showScanRecipientQrSheet(
//     context: ctx,
//     network: RecipientNetwork.ethereum,
//     expectedChainId: 1,
//     // Test-only: inject a fake scanner. Production omits this
//     // so the sheet uses the real mobile_scanner controller.
//     scanner: null,
//   );
//   if (address != null) destCtrl.text = address;
//
// Behavior:
//   * Camera permission is requested only when the sheet appears
//     and the scanner's `start()` is called — never at import time.
//   * The whole `Focus`/`Actions` scope of the sheet is dismissible
//     via the Escape key (desktop) and via the always-visible close
//     button in the header.
//   * On decode the scanner is paused before validation to prevent
//     duplicate result callbacks. On rejected decode the user sees
//     an inline error and the scanner resumes for another try.
//   * On valid decode the scanner is stopped + disposed and the
//     sheet closes with the extracted address.
//   * A "Paste address manually" fallback closes the sheet with a
//     null result. The caller keeps whatever was in the destination
//     field.
//   * On permission denial / no camera the sheet renders the same
//     fallback guidance instead of a broken camera preview.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../services/recipient_qr_parser.dart';
import '../services/recipient_qr_scanner.dart';
import 'crypto_wallet_engine_design.dart';


const String kScanRecipientQrSheetKey = 'scan_recipient_qr_sheet';
const String kScanRecipientQrCloseBtnKey =
    'scan_recipient_qr_close_btn';
const String kScanRecipientQrManualBtnKey =
    'scan_recipient_qr_manual_btn';
const String kScanRecipientQrErrorBannerKey =
    'scan_recipient_qr_error_banner';
const String kScanRecipientQrCameraUnavailableKey =
    'scan_recipient_qr_camera_unavailable';


/// Present the sheet. Returns the parsed recipient address, or null
/// if the user cancelled / chose manual entry.
Future<String?> showScanRecipientQrSheet({
  required BuildContext context,
  required RecipientNetwork network,
  int? expectedChainId,
  RecipientQrScanner? scanner,
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
    ),
  );
}


class _ScanRecipientQrSheet extends StatefulWidget {
  final RecipientNetwork network;
  final int? expectedChainId;
  final RecipientQrScanner? injectedScanner;

  const _ScanRecipientQrSheet({
    required this.network,
    required this.expectedChainId,
    this.injectedScanner,
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
  bool _cameraFailed = false;
  String? _errorMessage;

  bool get _useInjectedScanner => widget.injectedScanner != null;

  @override
  void initState() {
    super.initState();
    if (_useInjectedScanner) {
      _injectedScanner = widget.injectedScanner;
      _wireInjectedScanner();
    } else {
      _mobileScannerController = MobileScannerController(
        formats: const [BarcodeFormat.qrCode],
        detectionSpeed: DetectionSpeed.normal,
        detectionTimeoutMs: 1000,
        facing: CameraFacing.back,
        torchEnabled: false,
      );
      _wireMobileScanner();
    }
  }

  void _wireInjectedScanner() {
    final s = _injectedScanner!;
    _injectedSub = s.results.listen(_onDecode);
    scheduleMicrotask(() async {
      try {
        await s.start();
        if (!s.isCameraAvailable) {
          setState(() {
            _cameraFailed = true;
          });
        }
      } catch (_) {
        if (!mounted) return;
        setState(() {
          _cameraFailed = true;
        });
      }
    });
  }

  void _wireMobileScanner() {
    final ctrl = _mobileScannerController!;
    _mobileSub = ctrl.barcodes.listen((cap) {
      if (_busy || !mounted) return;
      for (final b in cap.barcodes) {
        final raw = b.rawValue;
        if (raw == null || raw.isEmpty) continue;
        _onDecode(raw);
        return;
      }
    });
    scheduleMicrotask(() async {
      try {
        await ctrl.start();
      } catch (_) {
        if (!mounted) return;
        setState(() {
          _cameraFailed = true;
        });
      }
    });
  }

  Future<void> _onDecode(String raw) async {
    if (_busy) return;
    // Prevent duplicate decode callbacks while we validate.
    _busy = true;
    try {
      if (_useInjectedScanner) {
        await _injectedScanner!.pause();
      } else {
        await _mobileScannerController!.stop();
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

    // Rejected — show the message and resume scanning so the user
    // can point at a different QR without closing the sheet.
    setState(() {
      _errorMessage = result.rejectMessage
          ?? 'Unsupported payment QR format.';
    });
    try {
      if (_useInjectedScanner) {
        await _injectedScanner!.resume();
      } else {
        await _mobileScannerController!.start();
      }
    } catch (_) {}
    _busy = false;
  }

  @override
  void dispose() {
    _injectedSub?.cancel();
    _mobileSub?.cancel();
    if (_useInjectedScanner) {
      _injectedScanner?.stop().then((_) => _injectedScanner?.dispose());
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
              _buildFooter(context),
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
    if (_cameraFailed) {
      return _buildCameraUnavailable();
    }
    return AspectRatio(
      aspectRatio: 1,
      child: Stack(
        fit: StackFit.expand,
        children: [
          _buildPreview(),
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

  Widget _buildPreview() {
    if (_useInjectedScanner) {
      // No real camera in widget tests; render a neutral surface so
      // layout tests still pass.
      return Container(color: Colors.black);
    }
    return MobileScanner(
      controller: _mobileScannerController!,
      errorBuilder: (ctx, error) {
        // Camera failed to initialise on the platform side.
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted) return;
          setState(() {
            _cameraFailed = true;
          });
        });
        return const SizedBox.shrink();
      },
      fit: BoxFit.cover,
    );
  }

  Widget _buildCameraUnavailable() {
    return Padding(
      key: const Key(kScanRecipientQrCameraUnavailableKey),
      padding: const EdgeInsets.fromLTRB(20, 24, 20, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(
            Icons.no_photography_outlined,
            color: kWalletTextSecondary,
            size: 36,
          ),
          const SizedBox(height: 12),
          const Text(
            'Camera unavailable',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Your browser blocked camera access, or no camera is '
            'connected. Close this sheet and paste the recipient '
            'address into the field instead.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: kWalletTextSecondary,
              fontSize: 12,
              height: 1.4,
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

  Widget _buildFooter(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 12, 18, 14),
        child: Row(
          children: [
            Expanded(
              child: OutlinedButton(
                key: const Key(kScanRecipientQrManualBtnKey),
                onPressed: () => Navigator.of(context).pop(null),
                style: OutlinedButton.styleFrom(
                  foregroundColor: kWalletTextPrimary,
                  side: const BorderSide(color: kWalletBorderStrong),
                  minimumSize: const Size.fromHeight(44),
                ),
                child: const Text('Enter address manually'),
              ),
            ),
          ],
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
      child: CustomPaint(
        painter: _AimingFramePainter(),
      ),
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
    final r = 18.0;
    final s = size.width;
    // Top-left
    canvas.drawLine(const Offset(0, 30), const Offset(0, 0), paint);
    canvas.drawLine(const Offset(0, 0), const Offset(30, 0), paint);
    // Top-right
    canvas.drawLine(Offset(s - 30, 0), Offset(s, 0), paint);
    canvas.drawLine(Offset(s, 0), Offset(s, 30), paint);
    // Bottom-left
    canvas.drawLine(Offset(0, s - 30), Offset(0, s), paint);
    canvas.drawLine(Offset(0, s), Offset(30, s), paint);
    // Bottom-right
    canvas.drawLine(Offset(s - 30, s), Offset(s, s), paint);
    canvas.drawLine(Offset(s, s), Offset(s, s - 30), paint);
    // Suppress unused-variable lint if any.
    // ignore: unused_local_variable
    final _ = r;
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
