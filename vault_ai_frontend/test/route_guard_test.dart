import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/route_guard.dart';

String _readLib(String relative) {
  final file = File('lib/$relative');
  expect(file.existsSync(), isTrue,
      reason: 'expected file does not exist: ${file.path}');
  return file.readAsStringSync();
}

void main() {
  group('resolveLandingRedirect', () {
    test('authenticated + unlocked redirects to /chat', () {
      expect(
        resolveLandingRedirect(authed: true, unlocked: true),
        '/chat',
      );
    });

    test('authenticated + locked redirects to /pin', () {
      expect(
        resolveLandingRedirect(authed: true, unlocked: false),
        '/pin',
      );
    });

    test('unauthenticated visitor renders public landing (returns null)', () {
      expect(
        resolveLandingRedirect(authed: false, unlocked: false),
        isNull,
      );
    });

    test('unauthenticated + (unreachable) unlocked still renders landing', () {
      expect(
        resolveLandingRedirect(authed: false, unlocked: true),
        isNull,
      );
    });
  });

  group('appRouteObserver', () {
    test('is a RouteObserver<ModalRoute<void>>', () {
      expect(appRouteObserver, isA<RouteObserver<ModalRoute<void>>>());
    });
  });

  group('LandingPage guard wiring', () {
    test('LandingPage is a StatefulWidget that runs the guard in initState',
        () {
      final src = _readLib('main.dart');
      expect(
        src,
        contains('class LandingPage extends StatefulWidget'),
        reason: 'LandingPage must be a StatefulWidget so initState '
            'can run the auth guard',
      );
      expect(
        src,
        contains('class _LandingPageState extends State<LandingPage>'),
      );
    });

    test('_LandingPageState mixes in RouteAware', () {
      final src = _readLib('main.dart');
      expect(
        src,
        contains('class _LandingPageState extends State<LandingPage> '
            'with RouteAware'),
        reason: 'LandingPage must mix in RouteAware so its guard '
            're-runs when the user pops back to it',
      );
    });

    test(
        '_LandingPageState overrides didPopNext + subscribes to '
        'appRouteObserver', () {
      final src = _readLib('main.dart');
      final stateIdx = src.indexOf('class _LandingPageState');
      expect(stateIdx, greaterThan(-1));
      final window = src.substring(
        stateIdx,
        (stateIdx + 5000).clamp(0, src.length),
      );
      expect(window, contains('void didPopNext()'));
      expect(window, contains('appRouteObserver.subscribe(this'));
      expect(window, contains('appRouteObserver.unsubscribe(this)'));
    });

    test(
        '_LandingPageState guard reads AppState.hydrated and skips '
        'when not hydrated', () {
      final src = _readLib('main.dart');
      final stateIdx = src.indexOf('class _LandingPageState');
      final window = src.substring(
        stateIdx,
        (stateIdx + 5000).clamp(0, src.length),
      );
      expect(window, contains('app.hydrated'));
    });

    test(
        '_LandingPageState guard runs via addPostFrameCallback + calls '
        'resolveLandingRedirect + pushReplacementNamed', () {
      final src = _readLib('main.dart');
      final stateIdx = src.indexOf('class _LandingPageState');
      final window = src.substring(
        stateIdx,
        (stateIdx + 5000).clamp(0, src.length),
      );
      expect(window, contains('addPostFrameCallback'));
      expect(window, contains('resolveLandingRedirect'));
      expect(window, contains('pushReplacementNamed'));
    });
  });

  group('main.dart route table', () {
    test('"/" routes to LandingPage and "/login" to LoginPage', () {
      final src = _readLib('main.dart');
      expect(src, contains("'/': (_) => const LandingPage()"));
      expect(src, contains("'/login': (_) => const LoginPage()"));
      expect(src, contains("'/signup': (_) => const SignupPage()"));
      expect(src, contains("'/unlock': (_) => const UnlockPage()"));
      expect(src, contains("'/pin': (_) => const PinGatePage()"));
      expect(src, contains("'/storage': (_) => const StoragePage()"));
    });

    test('"/auth" is kept as a back-compat alias of LoginPage', () {
      final src = _readLib('main.dart');
      expect(src, contains("'/auth': (_) => const LoginPage()"));
    });

    test('MaterialApp wires appRouteObserver into navigatorObservers', () {
      final src = _readLib('main.dart');
      expect(
        src,
        contains('navigatorObservers: [appRouteObserver]'),
        reason: 'appRouteObserver must be wired into MaterialApp '
            'or didPopNext never fires',
      );
    });
  });

  group('AppState.hydrated', () {
    test('AppState exposes a hydrated getter that starts false', () {
      final src = _readLib('main.dart');
      expect(src, contains('bool _hydrated = false;'));
      expect(src, contains('bool get hydrated => _hydrated;'));
    });

    test('hydrate() sets _hydrated=true before notifyListeners', () {
      final src = _readLib('main.dart');
      final hIdx = src.indexOf('Future<void> hydrate() async');
      expect(hIdx, greaterThan(-1));

      final window = src.substring(
        hIdx,
        (hIdx + 12000).clamp(0, src.length),
      );
      final flipIdx = window.indexOf('_hydrated = true');
      final notifyIdx = window.indexOf('notifyListeners()');
      expect(flipIdx, greaterThan(-1));
      expect(notifyIdx, greaterThan(-1));
      expect(
        flipIdx,
        lessThan(notifyIdx),
        reason: '_hydrated = true must precede notifyListeners() so '
            'the first listener-driven rebuild sees hydrated=true',
      );
    });
  });

  group('StoragePage no-session redirect', () {
    test('no-session branch redirects via pushReplacementNamed', () {
      final src = _readLib('storage_page.dart');
      final refreshIdx = src.indexOf('Future<void> _refresh');
      expect(refreshIdx, greaterThan(-1));
      final window = src.substring(
        refreshIdx,
        (refreshIdx + 1500).clamp(0, src.length),
      );

      expect(
        window,
        contains('sessionToken'),
        reason: '_refresh must consult AppState.sessionToken to decide '
            'whether the user is signed in',
      );
      expect(
        window,
        contains('pushReplacementNamed'),
        reason: 'no-session branch must redirect to the auth surface',
      );
    });

    test('inline "You need to sign in" error is gone', () {
      final src = _readLib('storage_page.dart');
      expect(
        src,
        isNot(contains('You need to sign in')),
        reason: 'inline no-session error was replaced by a redirect',
      );
    });
  });
}
