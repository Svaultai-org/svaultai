import 'package:flutter/widgets.dart';

final RouteObserver<ModalRoute<void>> appRouteObserver =
    RouteObserver<ModalRoute<void>>();

String? resolveLandingRedirect({
  required bool authed,
  required bool unlocked,
  String lockedRoute = '/pin',
}) {
  if (!authed) return null;
  return unlocked ? '/chat' : lockedRoute;
}

/// Defer web startup to Flutter's browser route so both the marketing root and
/// explicit account links work. Native apps begin at authentication as before.
String? resolveInitialAppRoute({required bool isWeb}) =>
    isWeb ? null : '/login';
