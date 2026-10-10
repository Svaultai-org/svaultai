import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/native_store_experience.dart';

/// Dialogs, signup, purchases and wallet routes are deliberately not safe
/// interruption points. Update and review UI wait for a settled main route.
class NativeStoreRouteObserver extends NavigatorObserver {
  final List<Route<dynamic>> _routes = [];
  final List<VoidCallback> _listeners = [];
  final Set<TransitionRoute<dynamic>> _departingRoutes = {};
  final _NativeStorePopEntry _popEntry = _NativeStorePopEntry();
  Route<dynamic>? _route;
  ModalRoute<dynamic>? _blockedRoute;
  Animation<double>? _routeAnimation;
  bool _updateBlocked = false;

  bool get _settled =>
      _departingRoutes.isEmpty &&
      _route is PageRoute &&
      _route!.isCurrent &&
      (_routeAnimation == null ||
          _routeAnimation!.status == AnimationStatus.completed);
  bool get updateAllowed =>
      _settled &&
      const {'/login', '/auth', '/unlock', '/chat'}
          .contains(_route?.settings.name);
  bool get reviewAllowed => _settled && _route?.settings.name == '/chat';

  void addListener(VoidCallback listener) => _listeners.add(listener);
  void removeListener(VoidCallback listener) => _listeners.remove(listener);

  void _notify() {
    for (final listener in [..._listeners]) {
      listener();
    }
  }

  void _animationChanged(AnimationStatus _) {
    _bindBackProtection();
    _notify();
  }

  void _selectRoute(Route<dynamic>? route) {
    _routeAnimation?.removeStatusListener(_animationChanged);
    _route = route;
    _routeAnimation = route is PageRoute ? route.animation : null;
    _routeAnimation?.addStatusListener(_animationChanged);
    _bindBackProtection();
    _notify();
  }

  /// MaterialApp.builder is above the Navigator, where a PopScope has no
  /// ModalRoute to protect. Register against the actual current route instead.
  void setUpdateBlocked(bool blocked) {
    _updateBlocked = blocked;
    _bindBackProtection();
  }

  void _bindBackProtection() {
    final next = _updateBlocked && updateAllowed && _route is ModalRoute
        ? _route as ModalRoute<dynamic>
        : null;
    if (identical(next, _blockedRoute)) return;
    _blockedRoute?.unregisterPopEntry(_popEntry);
    _blockedRoute = next;
    _popEntry.canPopNotifier.value = next == null;
    next?.registerPopEntry(_popEntry);
  }

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _routes.remove(route);
    _routes.add(route);
    _selectRoute(route);
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _routes.remove(route);
    if (route is TransitionRoute<dynamic>) {
      _departingRoutes.add(route);
      unawaited(route.completed.then((_) {
        _departingRoutes.remove(route);
        _bindBackProtection();
        _notify();
      }));
    }
    _selectRoute(previousRoute ?? (_routes.isEmpty ? null : _routes.last));
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    final index = oldRoute == null ? -1 : _routes.indexOf(oldRoute);
    if (index >= 0) {
      _routes.removeAt(index);
      if (newRoute != null) _routes.insert(index, newRoute);
    } else if (newRoute != null) {
      _routes.add(newRoute);
    }
    _selectRoute(_routes.isEmpty ? null : _routes.last);
  }

  @override
  void didRemove(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _routes.remove(route);
    _selectRoute(_routes.isEmpty ? null : _routes.last);
  }
}

class _NativeStorePopEntry implements PopEntry<Object?> {
  @override
  final ValueNotifier<bool> canPopNotifier = ValueNotifier(true);
  @override
  void onPopInvoked(bool didPop) {}
  @override
  void onPopInvokedWithResult(bool didPop, Object? result) {}
}

class NativeStoreExperience extends StatefulWidget {
  const NativeStoreExperience(
      {super.key,
      required this.child,
      required this.updateAllowed,
      required this.reviewAllowed,
      this.controller,
      this.reviewPolicy,
      this.enabled,
      this.routeObserver});
  final Widget child;
  final bool Function() updateAllowed;
  final bool Function() reviewAllowed;
  final NativeStoreController? controller;
  final OccasionalReviewPolicy? reviewPolicy;
  final bool? enabled;
  final NativeStoreRouteObserver? routeObserver;
  @override
  State<NativeStoreExperience> createState() => _NativeStoreExperienceState();
}

class _NativeStoreExperienceState extends State<NativeStoreExperience>
    with WidgetsBindingObserver {
  NativeStoreController? _controller;
  OccasionalReviewPolicy? _reviewPolicy;
  Timer? _timer;
  bool _foreground = true;
  bool _reviewAttemptedThisSession = false;
  bool _routeRebuildQueued = false;
  late final DateTime _started = DateTime.now();

  @override
  void initState() {
    super.initState();
    final enabled = widget.enabled ??
        (kReleaseMode &&
            !kIsWeb &&
            {TargetPlatform.iOS, TargetPlatform.android}
                .contains(defaultTargetPlatform));
    if (!enabled) return;
    _controller = widget.controller ??
        NativeStoreController(PlatformNativeStoreGateway());
    _controller!.addListener(_changed);
    widget.routeObserver?.addListener(_routeChanged);
    WidgetsBinding.instance.addObserver(this);
    unawaited(_controller!.check());
    unawaited(_prepareReview());
    _timer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (!_foreground) return;
      _changed();
      // Periodic store checks are bounded and single-flight.
      if (DateTime.now().difference(_started).inSeconds % 300 < 30) {
        unawaited(_controller!.check());
      }
      if (!_reviewAttemptedThisSession &&
          DateTime.now().difference(_started) >= const Duration(seconds: 90) &&
          _reviewAllowed() &&
          (_reviewPolicy?.eligible ?? false)) {
        _reviewAttemptedThisSession = true;
        unawaited(_reviewPolicy!
            .maybeRequest(_controller!.gateway, allowed: _reviewAllowed));
      }
    });
  }

  Future<void> _prepareReview() async {
    try {
      final preferences = await SharedPreferences.getInstance();
      if (!mounted) return;
      _reviewPolicy =
          widget.reviewPolicy ?? OccasionalReviewPolicy(preferences);
      await _reviewPolicy!.startSession();
    } catch (_) {}
  }

  bool _reviewAllowed() =>
      mounted &&
      _foreground &&
      !(_controller?.updateRequired ?? true) &&
      widget.reviewAllowed();

  void _changed() {
    if (mounted) setState(() {});
  }

  void _routeChanged() {
    // Navigator observers can fire while a route is being built. Rebuild only
    // after that frame, without replacing the child Navigator or its routes.
    if (_routeRebuildQueued) return;
    _routeRebuildQueued = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _routeRebuildQueued = false;
      _changed();
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  @override
  void didUpdateWidget(NativeStoreExperience oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.routeObserver != widget.routeObserver) {
      oldWidget.routeObserver?.removeListener(_routeChanged);
      oldWidget.routeObserver?.setUpdateBlocked(false);
      widget.routeObserver?.addListener(_routeChanged);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _changed();
    if (_foreground) {
      unawaited(_controller?.check());
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _controller?.removeListener(_changed);
    widget.routeObserver?.removeListener(_routeChanged);
    widget.routeObserver?.setUpdateBlocked(false);
    if (widget.controller == null) _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    if (controller == null) return widget.child;
    final blocked =
        _foreground && controller.updateRequired && widget.updateAllowed();
    widget.routeObserver?.setUpdateBlocked(blocked);
    // Keep the navigator and all underlying state alive. No logout, cache
    // clearing, key deletion, automatic store purchase or browser reload.
    return Stack(children: [
      ExcludeSemantics(
          excluding: blocked,
          child: IgnorePointer(ignoring: blocked, child: widget.child)),
      if (blocked) Positioned.fill(child: _updateNotice(context, controller)),
    ]);
  }

  Widget _updateNotice(BuildContext context, NativeStoreController controller) {
    final label = controller.update!.label;
    final version =
        label == 'the latest version' ? 'The latest version' : 'Version $label';
    return Scaffold(
      key: const Key('native_required_update'),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.system_update_alt, size: 56),
                  const SizedBox(height: 24),
                  Text('Update SVaultAI',
                      style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 12),
                  Text(
                      '$version is available from your store. '
                      'Update to continue. Your vault stays saved.',
                      textAlign: TextAlign.center),
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed:
                        controller.opening ? null : controller.openUpdate,
                    child: Text(
                        controller.opening ? 'Opening update…' : 'Update now'),
                  ),
                  TextButton(
                    onPressed: controller.opening ? null : controller.check,
                    child: const Text('Check again'),
                  ),
                  if (controller.error != null)
                    Text(controller.error!, textAlign: TextAlign.center),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
