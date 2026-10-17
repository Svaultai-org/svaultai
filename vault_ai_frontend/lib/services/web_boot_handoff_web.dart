import 'dart:js_interop';

@JS('svaultaiAppRendered')
external void _retireWebShell();

/// A render-only signal. It contains no identity, session or vault data and
/// never decides whether a route is public, authenticated or unlocked.
void notifyWebAppRendered() {
  try {
    _retireWebShell();
  } catch (_) {
    // Older HTML or an unavailable DOM hook must not stop the guarded app.
  }
}
