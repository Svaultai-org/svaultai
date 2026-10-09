import 'dart:async';

import 'package:flutter/material.dart';

import '../../services/concierge_exposure.dart';

/// A feature-owned private dialog. A stale unlock/session lease blanks the
/// contents and dismisses this exact route without popping unrelated routes.
Future<T?> showConciergeLeaseDialog<T>({
  required BuildContext context,
  required Listenable sessionChanges,
  required ConciergeAccessLease access,
  required WidgetBuilder builder,
  void Function(Route<T> route)? onRouteCreated,
}) async {
  access.assertCurrent();
  final navigator = Navigator.of(context, rootNavigator: true);
  final route = DialogRoute<T>(
      context: context,
      builder: (ctx) => ListenableBuilder(
          listenable: sessionChanges,
          builder: (ctx, _) =>
              access.isCurrent ? builder(ctx) : const SizedBox.shrink()));
  var removing = false;
  void checkAccess() {
    if (access.isCurrent || removing) return;
    removing = true;
    scheduleMicrotask(() {
      if (route.navigator != null && route.isActive) {
        navigator.removeRoute(route);
      }
    });
  }

  sessionChanges.addListener(checkAccess);
  onRouteCreated?.call(route);
  try {
    access.assertCurrent();
    return await navigator.push<T>(route);
  } finally {
    sessionChanges.removeListener(checkAccess);
  }
}
