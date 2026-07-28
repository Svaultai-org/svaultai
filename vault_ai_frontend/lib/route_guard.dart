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
