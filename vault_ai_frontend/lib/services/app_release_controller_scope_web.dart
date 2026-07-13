/// Web attachment for `AppReleaseControllerScope`: hook into the
/// browser's `document.visibilitychange` so the controller runs
/// `checkForUpdate` whenever the user returns to the tab.

// ignore_for_file: deprecated_member_use
// dart:html — see comment in app_release_controller_web.dart.

import 'dart:html' as html;


typedef _CheckForUpdate = void Function();


/// Returns a detach callback the scope will invoke on `dispose()`.
/// Returns `null` if the browser does not expose `document`.
void Function()? attachVisibilityChange(_CheckForUpdate cb) {
  try {
    void listener(html.Event _) {
      try {
        // Only trigger on VISIBLE — hidden transitions are noise.
        if (html.document.visibilityState == 'visible') {
          cb();
        }
      } catch (_) {}
    }
    html.document.addEventListener('visibilitychange', listener);
    return () {
      try {
        html.document.removeEventListener('visibilitychange', listener);
      } catch (_) {}
    };
  } catch (_) {
    return null;
  }
}
