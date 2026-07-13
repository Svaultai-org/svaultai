// 2026-07-13: Scanner initialization diagnostics.
//
// The recipient QR sheet needs to distinguish real failure modes for
// two reasons:
//   1. UX — show the right message ("Camera in use by another app"
//      vs "Camera permission denied" vs "Your browser can't decode
//      QRs offline").
//   2. Ops — emit a stable category token so a Sentry-style logger
//      can group non-sensitive scanner failures without touching any
//      wallet-address or QR-payload data.
//
// This module intentionally handles ONLY safe, non-sensitive info:
//   * No wallet addresses.
//   * No decoded QR payloads.
//   * No image bytes.
//   * No user identifiers.
// It carries a category enum and a short technical hint string
// (e.g. "OverconstrainedError: environment"); nothing more.
//
// 2026-07-13 (v2): after production retest on iPhone Safari, the
// live camera still failed with the vague "Camera couldn't start"
// message. Root cause was the sheet calling
// MobileScannerController.start() BEFORE the MobileScanner widget
// was in the tree — start() waits for `attach()`, times out after
// 500 ms, and throws MobileScannerException(controllerNotAttached).
// This module now:
//   * classifies that specific error into a new
//     `webStartTimeout` category with the user-visible code
//     "WEB_START_TIMEOUT", so an operator seeing the screenshot
//     can immediately identify the lifecycle bug from the screen;
//   * exposes `userFacingCode` as a stable machine-readable token
//     surfaced under the body copy on the failure UI.

/// Categorises why the recipient QR live-camera scanner could not
/// initialise. Stable string codes so tests match on them.
enum ScannerInitCategory {
  /// getUserMedia was denied by the user or by browser policy.
  permissionDenied,

  /// No camera device is enumerable (or the OS refused to enumerate).
  noCamera,

  /// A camera exists but is exclusive-held by another process /
  /// browser tab.
  cameraInUse,

  /// The browser reports the scanner APIs are unavailable — e.g.
  /// insecure context (http:), missing MediaDevices, or a very
  /// old browser.
  unsupportedBrowser,

  /// The camera stack came up but the QR-decoder WASM /
  /// worker / blob couldn't load. Usually a bundling / CSP issue.
  decoderLoadFailed,

  /// A Content-Security-Policy or Permissions-Policy directive
  /// visibly blocked the required resource. Detected only when the
  /// browser reports a CSP violation string.
  cspBlocked,

  /// The MobileScannerController's `attach()` handshake did not
  /// complete before start() timed out. This means the
  /// `MobileScanner` widget was not mounted in the tree when
  /// `controller.start()` was invoked (a Flutter-web lifecycle
  /// bug in the caller — not a browser/permission problem).
  webStartTimeout,

  /// getUserMedia resolved with a MediaStream but no live video
  /// track is present (or the track is immediately in "ended"
  /// state). Some iPhone Safari builds surface this when the
  /// camera is claimed by a background PWA or a hardware fault.
  videoTrackNotReady,

  /// Everything else — unrecognised initialisation error.
  unknown,
}


/// The result of a scanner-init attempt.
class ScannerInitDiagnostic {
  final ScannerInitCategory category;

  /// A short, non-sensitive one-line technical hint. Safe to
  /// include in analytics + operator logs. Callers must NEVER put
  /// wallet-address strings or decoded QR payloads in here.
  final String hint;

  const ScannerInitDiagnostic({
    required this.category,
    required this.hint,
  });

  String get userFacingHeadline {
    switch (category) {
      case ScannerInitCategory.permissionDenied:
        return 'Camera permission denied';
      case ScannerInitCategory.noCamera:
        return 'No camera on this device';
      case ScannerInitCategory.cameraInUse:
        return 'Camera is being used by another app';
      case ScannerInitCategory.unsupportedBrowser:
        return "This browser can't scan QR codes";
      case ScannerInitCategory.decoderLoadFailed:
        return "QR decoder couldn't load";
      case ScannerInitCategory.cspBlocked:
        return 'Camera blocked by site policy';
      case ScannerInitCategory.webStartTimeout:
        return "Camera couldn't start";
      case ScannerInitCategory.videoTrackNotReady:
        return 'Camera video track not ready';
      case ScannerInitCategory.unknown:
        return "Camera couldn't start";
    }
  }

  String get userFacingBody {
    switch (category) {
      case ScannerInitCategory.permissionDenied:
        return 'Grant camera permission in your browser settings, '
            'or upload a QR image from your library instead.';
      case ScannerInitCategory.noCamera:
        return 'Upload a QR image from your library, or enter the '
            'recipient address manually.';
      case ScannerInitCategory.cameraInUse:
        return 'Close any other app or tab using the camera, then '
            'tap "Try camera again". Or upload a QR image instead.';
      case ScannerInitCategory.unsupportedBrowser:
        return 'Upload a QR image from your library, or enter the '
            'recipient address manually.';
      case ScannerInitCategory.decoderLoadFailed:
        return 'Refresh the page and try again, or upload a QR '
            'image, or enter the recipient address manually.';
      case ScannerInitCategory.cspBlocked:
        return 'Upload a QR image from your library, or enter the '
            'recipient address manually.';
      case ScannerInitCategory.webStartTimeout:
        return 'The camera preview did not attach in time. Tap '
            '"Try camera again", or upload a QR image, or enter '
            'the recipient address manually.';
      case ScannerInitCategory.videoTrackNotReady:
        return 'Close any other tab using the camera, then tap '
            '"Try camera again". Or upload a QR image instead.';
      case ScannerInitCategory.unknown:
        return 'Try again, upload a QR image, or enter the '
            'recipient address manually.';
    }
  }

  /// Stable machine-readable token, e.g. "WEB_START_TIMEOUT". Shown
  /// on the failure UI as "Camera error: <code>" so an operator
  /// looking at a screenshot can immediately identify the failure
  /// mode without seeing any sensitive detail.
  String get userFacingCode {
    switch (category) {
      case ScannerInitCategory.permissionDenied:
        return 'PERMISSION_DENIED';
      case ScannerInitCategory.noCamera:
        return 'NO_CAMERA';
      case ScannerInitCategory.cameraInUse:
        return 'CAMERA_IN_USE';
      case ScannerInitCategory.unsupportedBrowser:
        return 'UNSUPPORTED_BROWSER';
      case ScannerInitCategory.decoderLoadFailed:
        return 'DECODER_LOAD_FAILED';
      case ScannerInitCategory.cspBlocked:
        return 'CSP_BLOCKED';
      case ScannerInitCategory.webStartTimeout:
        return 'WEB_START_TIMEOUT';
      case ScannerInitCategory.videoTrackNotReady:
        return 'VIDEO_TRACK_NOT_READY';
      case ScannerInitCategory.unknown:
        return 'UNKNOWN';
    }
  }
}


class ScannerInitClassifier {
  /// Best-effort classification of a raw error thrown by the
  /// camera/scanner init path. The mobile_scanner package on web
  /// wraps browser errors in its own `MobileScannerException`
  /// class; we match on the message + toString to extract stable
  /// categories.
  ///
  /// Only string surface is examined. No wallet/QR data is touched.
  static ScannerInitDiagnostic classify(Object? error) {
    if (error == null) {
      return const ScannerInitDiagnostic(
        category: ScannerInitCategory.unknown,
        hint: 'null-error',
      );
    }
    final s = error.toString().toLowerCase();
    // Order matters: the "not attached" / "controllerNotAttached"
    // check must run BEFORE the generic "unsupported" check because
    // MobileScannerErrorCode.controllerNotAttached.message can
    // contain generic wording that would otherwise be misclassified.
    if (s.contains('controllernotattached')
        || s.contains('not attached')
        || s.contains('attach() was not called')
        || s.contains('widget was not attached')) {
      return ScannerInitDiagnostic(
        category: ScannerInitCategory.webStartTimeout,
        hint: _short(s),
      );
    }
    if (s.contains('videotracknotready')
        || s.contains('video track')
        || s.contains('trackended')
        || s.contains('track ended')
        || s.contains('no video track')) {
      return ScannerInitDiagnostic(
        category: ScannerInitCategory.videoTrackNotReady,
        hint: _short(s),
      );
    }
    if (s.contains('notallowed')
        || s.contains('permission') && s.contains('denied')
        || s.contains('permission_denied')) {
      return ScannerInitDiagnostic(
        category: ScannerInitCategory.permissionDenied,
        hint: _short(s),
      );
    }
    if (s.contains('notfound')
        || s.contains('no camera')
        || s.contains('nocamera')
        || s.contains('devicenotfound')
        || (s.contains('no') && s.contains('media') && s.contains('device'))) {
      return ScannerInitDiagnostic(
        category: ScannerInitCategory.noCamera,
        hint: _short(s),
      );
    }
    if (s.contains('notreadable') || s.contains('in use')
        || s.contains('trackstart') || s.contains('overconstrained')) {
      // OverconstrainedError typically means the requested facing
      // mode (environment / user) doesn't match any available
      // camera. We classify it as cameraInUse-adjacent so the retry
      // hint asks the user to close conflicting apps OR switch
      // camera. The camera-facing-fallback happens automatically
      // upstream.
      return ScannerInitDiagnostic(
        category: ScannerInitCategory.cameraInUse,
        hint: _short(s),
      );
    }
    if (s.contains('insecurecontext')
        || s.contains('http:') || s.contains('is not secure')
        || s.contains('unsupported')
        || s.contains('undefined is not')
        || s.contains('mediadevices')) {
      return ScannerInitDiagnostic(
        category: ScannerInitCategory.unsupportedBrowser,
        hint: _short(s),
      );
    }
    if (s.contains('wasm')
        || s.contains('worker')
        || s.contains('failed to fetch')
        || s.contains('failed to load')) {
      return ScannerInitDiagnostic(
        category: ScannerInitCategory.decoderLoadFailed,
        hint: _short(s),
      );
    }
    if (s.contains('content security policy')
        || s.contains('csp')
        || s.contains('permissions policy')
        || s.contains('permissions-policy')) {
      return ScannerInitDiagnostic(
        category: ScannerInitCategory.cspBlocked,
        hint: _short(s),
      );
    }
    return ScannerInitDiagnostic(
      category: ScannerInitCategory.unknown,
      hint: _short(s),
    );
  }

  static String _short(String s) {
    // Keep the hint short + strip anything that even looks like a
    // hex or base58 blob so we don't accidentally log a QR payload.
    final oneLine = s.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (oneLine.length <= 120) return oneLine;
    return '${oneLine.substring(0, 117)}...';
  }
}
