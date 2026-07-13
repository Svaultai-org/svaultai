/// 2026-07-14 (Round 11 — real controller wiring): `InheritedWidget`
/// that owns the `AppReleaseController` for the lifetime of the
/// running app, keeps it responsive to lifecycle + browser
/// visibility events, and makes it reachable from any descendant
/// (Send panels, Settings, banners) via `.of(context)`.
///
/// Wiring points (all wired in `main.dart`):
///
///   * created inside `AppReleaseControllerScope` state, kept alive
///     as long as the widget is mounted (which is the app's
///     lifetime — `AppReleaseControllerScope` wraps every route);
///   * lifecycle: `WidgetsBindingObserver.didChangeAppLifecycleState`
///     triggers a check on `AppLifecycleState.resumed`;
///   * web tab visibility: the web side-effect module attaches a
///     `visibilitychange` listener that fires the same
///     `checkForUpdate` when the tab becomes visible again;
///   * periodic 5-min timer runs inside `AppReleaseController.start`.
///
/// Consumer helpers:
///
///   * `AppReleaseControllerScope.of(context)` returns the
///     controller. Use `.sendShouldBeBlocked()` before starting a
///     Send flow.
///   * `.updateAvailableNotifier` drives the update banner.
///   * `.applyUpdateAndReload(reloadAllowed: () => !broadcastInFlight)`
///     is the exact call the banner's "Update now" button makes.

library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';

import 'app_release_controller.dart';
// Web-only: attach `document.addEventListener('visibilitychange', …)`
// so the controller checks for a new release whenever the tab
// becomes visible again after being backgrounded.
import 'app_release_controller_scope_web_stub.dart'
    if (dart.library.html) 'app_release_controller_scope_web.dart'
    as web;


class AppReleaseControllerScope extends StatefulWidget {
  const AppReleaseControllerScope({
    super.key,
    required this.baseUrl,
    required this.child,
    this.controllerOverride,
  });

  final String baseUrl;
  final Widget child;

  /// Optional injection for widget tests — bypasses the real
  /// controller construction so tests can drive the pending-update
  /// state directly.
  final AppReleaseController? controllerOverride;

  static AppReleaseController? maybeOf(BuildContext context) {
    final scope = context
        .dependOnInheritedWidgetOfExactType<_AppReleaseControllerInherited>();
    return scope?.controller;
  }

  static AppReleaseController of(BuildContext context) {
    final ctl = maybeOf(context);
    assert(ctl != null,
        'AppReleaseControllerScope not found in widget tree.');
    return ctl!;
  }

  @override
  State<AppReleaseControllerScope> createState() =>
      _AppReleaseControllerScopeState();
}


class _AppReleaseControllerScopeState
    extends State<AppReleaseControllerScope>
    with WidgetsBindingObserver {
  late final AppReleaseController _controller;
  bool _ownsController = false;
  VoidCallback? _detachWebVisibility;

  @override
  void initState() {
    super.initState();
    _controller = widget.controllerOverride ??
        AppReleaseController(baseUrl: widget.baseUrl);
    _ownsController = widget.controllerOverride == null;
    WidgetsBinding.instance.addObserver(this);
    if (_ownsController) {
      _controller.start();
    }
    _detachWebVisibility = web.attachVisibilityChange(() {
      _controller.checkForUpdate();
    });
  }

  @override
  void dispose() {
    _detachWebVisibility?.call();
    WidgetsBinding.instance.removeObserver(this);
    if (_ownsController) {
      _controller.dispose();
    }
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _controller.checkForUpdate();
    }
  }

  @override
  Widget build(BuildContext context) {
    return _AppReleaseControllerInherited(
      controller: _controller,
      child: widget.child,
    );
  }
}


class _AppReleaseControllerInherited extends InheritedWidget {
  const _AppReleaseControllerInherited({
    required this.controller,
    required super.child,
  });

  final AppReleaseController controller;

  @override
  bool updateShouldNotify(_AppReleaseControllerInherited old) =>
      !identical(old.controller, controller);
}
