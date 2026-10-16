import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/route_guard.dart';

void main() {
  test('web defers to the URL and native keeps its login startup', () {
    expect(resolveInitialAppRoute(isWeb: true), isNull);
    expect(resolveInitialAppRoute(isWeb: false), '/login');
    final source = File('lib/main.dart').readAsStringSync();
    expect(source,
        contains('initialRoute: resolveInitialAppRoute(isWeb: kIsWeb)'));
  });

  for (final route in ['/', '/login', '/signup', '/recover']) {
    testWidgets('web URL $route opens the requested public or account screen',
        (tester) async {
      tester.platformDispatcher.defaultRouteNameTestValue = route;
      addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
      await tester.pumpWidget(MaterialApp(
        initialRoute: resolveInitialAppRoute(isWeb: true),
        routes: {
          '/': (_) => const Scaffold(body: Text('Public homepage')),
          '/login': (_) => const Scaffold(body: Text('Existing login')),
          '/signup': (_) => const Scaffold(body: Text('Existing signup')),
          '/recover': (_) => const Scaffold(body: Text('Existing recovery')),
        },
      ));
      await tester.pumpAndSettle();
      expect(
        find.text(switch (route) {
          '/login' => 'Existing login',
          '/signup' => 'Existing signup',
          '/recover' => 'Existing recovery',
          _ => 'Public homepage',
        }),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('native default startup still opens login rather than marketing',
      (tester) async {
    tester.platformDispatcher.defaultRouteNameTestValue = '/';
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    await tester.pumpWidget(MaterialApp(
      initialRoute: resolveInitialAppRoute(isWeb: false),
      routes: {
        '/': (_) => const Scaffold(body: Text('Public homepage')),
        '/login': (_) => const Scaffold(body: Text('Existing login')),
      },
    ));
    await tester.pumpAndSettle();
    expect(find.text('Existing login'), findsOneWidget);
    expect(find.text('Public homepage'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
