

import 'package:flutter/widgets.dart';


final RouteObserver<ModalRoute<void>> appRouteObserver =
    RouteObserver<ModalRoute<void>>();


String? resolveLandingRedirect({
  required bool authed,
  required bool unlocked,
}) {
  if (!authed) return null;
  return unlocked ? '/chat' : '/pin';
}
