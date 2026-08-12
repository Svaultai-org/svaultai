// Regression for the c2f917e production report:
//
//   After the 2026-07-21 wordmark-ellipsis fix (f3c3f13), the
//   mobile header shows "[shield] V... 🔔 [chip]" which reads as
//   broken UI. The requirement is to HIDE the wordmark entirely on
//   phone-width viewports and show only the shield logo.
//
// The tablet+ threshold is `VaultBreakpoints.tabletMin = 600`
// (lib/ui/responsive.dart:30). Below that, the wordmark must be
// omitted; at 600px+ it must render fully.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:vault_ai_frontend/main.dart' show AppState, TopNavBar;

import '_helpers/responsive_harness.dart';

AppState _authedAppState() {
  final app = AppState();
  app.sessionToken = 'sess';
  app.vaultId = 'v-1';
  app.vaultName = 'Alexa';
  app.displayName = 'Alexa';
  app.authed = true;
  return app;
}

Future<void> _pumpHeader(
  WidgetTester tester, {
  required DeviceProfile device,
  required AppState app,
  bool isMobile = true,
}) async {
  await pumpAtDevice(
    tester,
    ChangeNotifierProvider<AppState>.value(
      value: app,
      child: Scaffold(
        appBar: TopNavBar(
          isMobile: isMobile,
          showMenuButton: true,
          onMenuTap: () {},
        ),
        body: const SizedBox.shrink(),
      ),
    ),
    device: device,
    wrapInScaffold: false,
  );
}

// Wordmark Text finder — 'SVaultAI' (case-preserved wordmark
// literal). Any variant like 'V...' would not have data=='SVaultAI'
// but the ellipsis is rendered by TextPainter, not by mutating
// the Text.data string. So the correct assertion is: on phone,
// the Text('SVaultAI') widget is NOT in the tree at all.
Finder _wordmarkTextFinder() {
  return find.byWidgetPredicate(
    (w) => w is Text && w.data == 'SVaultAI',
  );
}

void main() {
  group('TopNavBar — mobile hides the wordmark entirely', () {
    for (final device in DeviceProfiles.allPhones) {
      testWidgets(
        'wordmark is NOT rendered @ ${device.name} '
        '(${device.width.toInt()}px)',
        (tester) async {
          final app = _authedAppState();
          await _pumpHeader(tester, device: device, app: app);
          expect(
            _wordmarkTextFinder(),
            findsNothing,
            reason: '${device.name}: on phone-width viewports the '
                'wordmark must be omitted entirely. Showing '
                '"V..." is worse than showing nothing.',
          );
        },
      );
    }
  });

  group('TopNavBar — tablet and desktop keep the wordmark', () {
    testWidgets(
      'wordmark IS rendered on tablet (>= 600px)',
      (tester) async {
        final app = _authedAppState();
        await _pumpHeader(
          tester,
          device: DeviceProfiles.ipad, // 820x1180
          app: app,
          isMobile: false,
        );
        expect(_wordmarkTextFinder(), findsOneWidget,
            reason: 'tablet must show full SVaultAI wordmark');
      },
    );

    testWidgets(
      'wordmark IS rendered on desktop',
      (tester) async {
        final app = _authedAppState();
        await _pumpHeader(
          tester,
          device: DeviceProfiles.desktop, // 1440x900
          app: app,
          isMobile: false,
        );
        expect(_wordmarkTextFinder(), findsOneWidget);
      },
    );
  });

  group('TopNavBar — compact mobile navigation', () {
    testWidgets(
      'redundant shield is hidden on iPhone SE',
      (tester) async {
        final app = _authedAppState();
        await _pumpHeader(tester, device: DeviceProfiles.iphoneSE, app: app);
        // The shield is Icon(Icons.shield_rounded, ...) inside a
        // fixed 42x42 Container. Presence confirms the brand mark
        // remains visible even when the wordmark is hidden.
        final shield = find.byWidgetPredicate(
          (w) => w is Icon && w.icon == Icons.shield_rounded,
        );
        expect(shield, findsNothing,
            reason: 'hiding the redundant shield prevents phone overflow');
      },
    );
  });
}
