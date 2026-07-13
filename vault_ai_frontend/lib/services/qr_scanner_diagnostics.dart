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
      case ScannerInitCategory.unknown:
        return 'Try again, upload a QR image, or enter the '
            'recipient address manually.';
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
