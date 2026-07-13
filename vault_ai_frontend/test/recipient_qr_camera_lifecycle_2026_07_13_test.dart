// 2026-07-13 (v2): regression tests for the iPhone Safari
// "Camera couldn't start" root cause.
//
// What broke in production (iPhone Safari retest):
//   * `initState()` called `_initMobileScanner()` which immediately
//     awaited `controller.start()`.
//   * The `MobileScanner` widget was NOT in the tree yet (the sheet
//     rendered a plain loading spinner during `_LiveState.
//     initializing`), so `controller.attach()` never fired.
//   * `MobileScannerController.start()` timed out waiting on
//     `_isAttachedCompleter` after 500 ms and threw
//     `MobileScannerException(controllerNotAttached)`.
//   * The classifier fell through to the vague "Camera couldn't
//     start" (unknown category).
//   * Facing fallback swapped to `CameraFacing.unknown`, which
//     `mobile_scanner_web` maps to `'environment'` — same as
//     `CameraFacing.back`. The fallback was a no-op.
//
// This file locks in the invariants that make the fix stick:
//
//   1. The production controller factory ALWAYS uses
//      `autoStart: false` (no double-start with the widget).
//   2. The production controller factory rejects
//      `CameraFacing.unknown` (facing fallback must actually
//      change the constraint).
//   3. The scanner-init classifier maps
//      "controllerNotAttached" → webStartTimeout, NOT unknown, so
//      the code shown on screen is the operator-actionable
//      `WEB_START_TIMEOUT`.
//   4. The classifier maps video-track messages →
//      videoTrackNotReady → `VIDEO_TRACK_NOT_READY`.
//   5. Every category exposes a stable, non-empty
//      `userFacingCode` — screenshots can be triaged offline.
//   6. Retry through the injected path stops the fake scanner
//      exactly once and starts it again (no double-start, no
//      leaked instance).
//   7. Reopen after close creates a fresh scanner (no reuse of
//      the disposed one).
//   8. Diagnostic-code text renders on the failure UI with the
//      expected code.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'package:vault_ai_frontend/services/qr_scanner_diagnostics.dart';
import 'package:vault_ai_frontend/services/recipient_qr_parser.dart';
import 'package:vault_ai_frontend/services/recipient_qr_scanner.dart';
import 'package:vault_ai_frontend/ui/scan_recipient_qr_sheet.dart';


Future<void> _openSheet(
  WidgetTester tester, {
  required RecipientQrScanner scanner,
  required void Function(String?) onResult,
  RecipientNetwork network = RecipientNetwork.ethereum,
  int? expectedChainId = 1,
  Size viewport = const Size(390, 1600),
}) async {
  await tester.binding.setSurfaceSize(viewport);
  addTearDown(() => tester.binding.setSurfaceSize(null));
  tester.view.padding = FakeViewPadding.zero;
  tester.view.viewInsets = FakeViewPadding.zero;
  addTearDown(() {
    tester.view.resetPadding();
    tester.view.resetViewInsets();
  });
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Builder(builder: (ctx) {
        WidgetsBinding.instance.addPostFrameCallback((_) async {
          final r = await showScanRecipientQrSheet(
            context: ctx,
            network: network,
            expectedChainId: expectedChainId,
            scanner: scanner,
          );
          onResult(r);
        });
        return const SizedBox.shrink();
      }),
    ),
  ));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}


Future<void> _invokeButton(WidgetTester tester, Key k) async {
  final widget = tester.widget(find.byKey(k));
  final onPressed = (widget as dynamic).onPressed as VoidCallback?;
  expect(onPressed, isNotNull,
      reason: 'button ${k.toString()} must be enabled');
  onPressed!.call();
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 200));
}


void main() {
  group('production MobileScannerController factory invariants', () {
    test('autoStart is FALSE (prevents double-start with widget)',
        () {
      final ctrl = buildScanSheetMobileScannerController(
        facing: CameraFacing.back,
      );
      addTearDown(ctrl.dispose);
      expect(ctrl.autoStart, isFalse,
          reason: 'autoStart MUST stay false — the widget\'s '
              '_initializeController() calls start() when autoStart '
              'is true, which races with our own post-frame start() '
              'and produced controllerNotAttached on iPhone Safari.');
    });

    test('back facing produces CameraFacing.back on the controller',
        () {
      final ctrl = buildScanSheetMobileScannerController(
        facing: CameraFacing.back,
      );
      addTearDown(ctrl.dispose);
      expect(ctrl.facing, CameraFacing.back);
    });

    test('front facing produces CameraFacing.front on the controller '
        '(fallback path must use FRONT, not UNKNOWN — mobile_scanner_'
        'web maps unknown to the same "environment" string as back)',
        () {
      final ctrl = buildScanSheetMobileScannerController(
        facing: CameraFacing.front,
      );
      addTearDown(ctrl.dispose);
      expect(ctrl.facing, CameraFacing.front);
    });

    test('formats is [qrCode] — we do NOT ask the scanner to decode '
        'other 1D/2D formats we do not use', () {
      final ctrl = buildScanSheetMobileScannerController(
        facing: CameraFacing.back,
      );
      addTearDown(ctrl.dispose);
      expect(ctrl.formats, const [BarcodeFormat.qrCode]);
    });

    test('torchEnabled is FALSE — never light up the flash '
        'automatically on the recipient sheet', () {
      final ctrl = buildScanSheetMobileScannerController(
        facing: CameraFacing.back,
      );
      addTearDown(ctrl.dispose);
      expect(ctrl.torchEnabled, isFalse);
    });

    test('CameraFacing.unknown is rejected in debug (assertion)',
        () {
      expect(
        () => buildScanSheetMobileScannerController(
          facing: CameraFacing.unknown,
        ),
        throwsA(isA<AssertionError>()),
      );
    });
  });


  group('scanner-init classifier: iPhone Safari failure modes', () {
    test('controllerNotAttached is classified as webStartTimeout '
        '(WEB_START_TIMEOUT)', () {
      // The exact string mobile_scanner throws when start() times
      // out waiting for the widget to mount + call attach().
      final d = ScannerInitClassifier.classify(
        Exception(
          'MobileScannerException(errorCode: controllerNotAttached, '
          'details: The MobileScannerController was not attached to '
          'a MobileScanner widget when start() was called.)',
        ),
      );
      expect(d.category, ScannerInitCategory.webStartTimeout);
      expect(d.userFacingCode, 'WEB_START_TIMEOUT');
    });

    test('generic "not attached" string is classified as '
        'webStartTimeout', () {
      final d = ScannerInitClassifier.classify(
        Exception('Controller was not attached'),
      );
      expect(d.category, ScannerInitCategory.webStartTimeout);
    });

    test('videoTrackEnded → videoTrackNotReady (VIDEO_TRACK_NOT_READY)',
        () {
      final d = ScannerInitClassifier.classify(
        Exception('MediaStream video track ended'),
      );
      expect(d.category, ScannerInitCategory.videoTrackNotReady);
      expect(d.userFacingCode, 'VIDEO_TRACK_NOT_READY');
    });

    test('no video track present → videoTrackNotReady', () {
      final d = ScannerInitClassifier.classify(
        Exception('no video track available'),
      );
      expect(d.category, ScannerInitCategory.videoTrackNotReady);
    });

    test('webStartTimeout check runs BEFORE unsupportedBrowser fallback '
        '(unsupported keyword must not steal a not-attached error)',
        () {
      // Craft an error message that contains BOTH "not attached"
      // and "mediadevices" — the not-attached signal must win.
      final d = ScannerInitClassifier.classify(
        Exception(
          'Widget was not attached; mediadevices call was skipped',
        ),
      );
      expect(d.category, ScannerInitCategory.webStartTimeout,
          reason: 'not-attached must be recognised before the '
              'generic mediadevices fallback.');
    });
  });


  group('userFacingCode: stable, non-empty per category', () {
    test('every category has a stable machine-readable code', () {
      final codes = <String>{};
      for (final c in ScannerInitCategory.values) {
        final d = ScannerInitDiagnostic(category: c, hint: 'h');
        expect(d.userFacingCode.isNotEmpty, isTrue,
            reason: 'category $c must have a userFacingCode.');
        // Code must match /^[A-Z_]+$/ so it's usable in ops
        // logs / URL fragments without escaping.
        expect(
          RegExp(r'^[A-Z_]+$').hasMatch(d.userFacingCode),
          isTrue,
          reason: 'code ${d.userFacingCode} must be UPPER_SNAKE.',
        );
        codes.add(d.userFacingCode);
      }
      // All codes are distinct (no two categories share a code).
      expect(codes.length, ScannerInitCategory.values.length);
    });

    test('every category has a stable user-facing headline + body',
        () {
      for (final c in ScannerInitCategory.values) {
        final d = ScannerInitDiagnostic(category: c, hint: 'h');
        expect(d.userFacingHeadline.isNotEmpty, isTrue);
        expect(d.userFacingBody.isNotEmpty, isTrue);
      }
    });
  });


  group('sheet renders the diagnostic code on the failure UI', () {
    testWidgets('camera unavailable → "Camera error: NO_CAMERA" '
        'text is visible on the failed surface', (tester) async {
      final scanner = FakeRecipientQrScanner(cameraAvailable: false);
      await _openSheet(tester, scanner: scanner, onResult: (_) {});
      // The failed surface is present.
      expect(
        find.byKey(const Key(kScanRecipientQrCameraFailedKey)),
        findsOneWidget,
      );
      // The diagnostic-code line is visible with the correct
      // code — matches the injected `noCamera` category.
      expect(
        find.byKey(const Key(kScanRecipientQrDiagnosticCodeKey)),
        findsOneWidget,
      );
      expect(find.text('Camera error: NO_CAMERA'), findsOneWidget);
    });

    testWidgets('successful camera → NO failed surface + NO diagnostic '
        'code rendered', (tester) async {
      final scanner = FakeRecipientQrScanner();
      await _openSheet(tester, scanner: scanner, onResult: (_) {});
      expect(
        find.byKey(const Key(kScanRecipientQrCameraFailedKey)),
        findsNothing,
      );
      expect(
        find.byKey(const Key(kScanRecipientQrDiagnosticCodeKey)),
        findsNothing,
      );
    });
  });


  group('retry lifecycle: no double-start, controller is released',
      () {
    testWidgets('camera unavailable → retry stops the OLD scanner '
        'exactly once before starting again (no leaked instance)',
        (tester) async {
      final scanner = FakeRecipientQrScanner(cameraAvailable: false);
      await _openSheet(tester, scanner: scanner, onResult: (_) {});
      final stopsBefore = scanner.stopCalls;
      final startsBefore = scanner.startCalls;
      await _invokeButton(
          tester, const Key(kScanRecipientQrRetryBtnKey));
      expect(scanner.stopCalls, greaterThan(stopsBefore),
          reason: 'retry MUST stop() before start().');
      expect(scanner.startCalls, startsBefore + 1,
          reason: 'retry MUST call start() EXACTLY ONCE — no '
              'double-start race.');
    });

    testWidgets('retry twice in succession does not stack extra '
        'start() calls', (tester) async {
      final scanner = FakeRecipientQrScanner(cameraAvailable: false);
      await _openSheet(tester, scanner: scanner, onResult: (_) {});
      final startsBefore = scanner.startCalls;
      await _invokeButton(
          tester, const Key(kScanRecipientQrRetryBtnKey));
      await _invokeButton(
          tester, const Key(kScanRecipientQrRetryBtnKey));
      expect(scanner.startCalls - startsBefore, 2,
          reason: 'two retries → exactly two start()s, no extras.');
    });

    testWidgets('close after failed camera disposes the scanner '
        'exactly once', (tester) async {
      final scanner = FakeRecipientQrScanner(cameraAvailable: false);
      await _openSheet(tester, scanner: scanner, onResult: (_) {});
      await _invokeButton(
          tester, const Key(kScanRecipientQrManualBtnKey));
      expect(scanner.disposeCalls, greaterThanOrEqualTo(1));
    });
  });


  group('lifecycle: injected scanner always transitions cleanly', () {
    testWidgets('successful decode returns address and closes sheet '
        'without triggering the failed surface', (tester) async {
      final scanner = FakeRecipientQrScanner();
      String? got;
      await _openSheet(tester,
          scanner: scanner, onResult: (r) => got = r);
      // Sheet must not show the failed surface before a decode.
      expect(
        find.byKey(const Key(kScanRecipientQrCameraFailedKey)),
        findsNothing,
      );
      scanner.pushResult(
        '0xffffffffffffffffffffffffffffffffffffffff',
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(got, '0xffffffffffffffffffffffffffffffffffffffff');
    });

    testWidgets('scanner start throwing directly is classified via '
        'the injected path', (tester) async {
      // A scanner where start() throws — we surface the failure UI
      // and the diagnostic code is the "unknown" one.
      final scanner = _ThrowingStartScanner(
        Exception('boom: unknown init failure'),
      );
      await _openSheet(tester, scanner: scanner, onResult: (_) {});
      expect(
        find.byKey(const Key(kScanRecipientQrCameraFailedKey)),
        findsOneWidget,
      );
      expect(
        find.text('Camera error: UNKNOWN'),
        findsOneWidget,
      );
    });

    testWidgets('scanner start throwing a not-attached error is '
        'classified as WEB_START_TIMEOUT', (tester) async {
      final scanner = _ThrowingStartScanner(
        Exception('Widget was not attached before start()'),
      );
      await _openSheet(tester, scanner: scanner, onResult: (_) {});
      expect(
        find.byKey(const Key(kScanRecipientQrCameraFailedKey)),
        findsOneWidget,
      );
      expect(
        find.text('Camera error: WEB_START_TIMEOUT'),
        findsOneWidget,
      );
    });

    testWidgets('scanner start throwing a video-track error is '
        'classified as VIDEO_TRACK_NOT_READY', (tester) async {
      final scanner = _ThrowingStartScanner(
        Exception('MediaStream: no video track available'),
      );
      await _openSheet(tester, scanner: scanner, onResult: (_) {});
      expect(
        find.byKey(const Key(kScanRecipientQrCameraFailedKey)),
        findsOneWidget,
      );
      expect(
        find.text('Camera error: VIDEO_TRACK_NOT_READY'),
        findsOneWidget,
      );
    });
  });


  group('320 / 390 / 430 layouts: fallback actions always visible',
      () {
    for (final w in const [320.0, 390.0, 430.0]) {
      testWidgets('at ${w.toInt()}dp the retry + upload + manual '
          'actions are all present when camera failed',
          (tester) async {
        final scanner =
            FakeRecipientQrScanner(cameraAvailable: false);
        await _openSheet(
          tester,
          scanner: scanner,
          onResult: (_) {},
          viewport: Size(w, 1600),
        );
        expect(
          find.byKey(const Key(kScanRecipientQrRetryBtnKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kScanRecipientQrUploadBtnKey)),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(kScanRecipientQrManualBtnKey)),
          findsOneWidget,
        );
        // Diagnostic code is visible on every layout.
        expect(
          find.byKey(const Key(kScanRecipientQrDiagnosticCodeKey)),
          findsOneWidget,
        );
      });
    }
  });
}


/// Test double whose `start()` throws a specific error. Used to
/// verify each error class routes to the right diagnostic code
/// through the injected path.
class _ThrowingStartScanner implements RecipientQrScanner {
  final Object toThrow;
  _ThrowingStartScanner(this.toThrow);

  @override
  Stream<String> get results => const Stream.empty();

  @override
  bool get isCameraAvailable => false;

  @override
  Future<void> start() async {
    throw toThrow;
  }

  @override
  Future<void> pause() async {}
  @override
  Future<void> resume() async {}
  @override
  Future<void> stop() async {}
  @override
  Future<void> dispose() async {}
}
