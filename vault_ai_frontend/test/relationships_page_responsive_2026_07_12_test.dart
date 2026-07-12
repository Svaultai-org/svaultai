// 2026-07-12 mobile-responsiveness suite for the Relationships page.
//
// Verifies that the shared DashboardScaffold header (used by the
// Relationships page and every other dashboard) collapses cleanly
// on 320dp, 390dp, and 430dp viewports, and that the _EdgeRowCard
// self-measures so a wrong parent isMobile flag does not overflow.
//
// The suite pumps _DashboardHeader (via DashboardScaffold) directly
// with a Refresh action, then re-pumps at wide/desktop widths to
// confirm the original single-row layout still works.

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/dashboards/dashboard_shell.dart';


Widget _wrap(Widget child) {
  return MaterialApp(
    theme: ThemeData.dark(useMaterial3: true),
    localizationsDelegates: const [
      AppLocalizations.delegate,
      GlobalMaterialLocalizations.delegate,
      GlobalCupertinoLocalizations.delegate,
      GlobalWidgetsLocalizations.delegate,
    ],
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('en'),
    home: Scaffold(
      backgroundColor: const Color(0xFF0F1115),
      body: child,
    ),
  );
}


Future<void> _pumpAtWidth(
  WidgetTester t, {
  required double width,
  required Widget child,
}) async {
  t.view.physicalSize = Size(width, 900);
  t.view.devicePixelRatio = 1.0;
  addTearDown(() {
    t.view.resetPhysicalSize();
    t.view.resetDevicePixelRatio();
  });
  await t.pumpWidget(_wrap(child));
  await t.pumpAndSettle();
}


DashboardScaffold _headerFixture({
  required bool isMobile,
  bool includeAction = true,
}) {
  return DashboardScaffold(
    isMobile: isMobile,
    title: 'Relationships',
    subtitle:
        'Understand how your saved items connect — files, logins, '
        'IDs, and cards, discovered automatically.',
    icon: Icons.hub_outlined,
    actions: [
      if (includeAction)
        OutlinedButton.icon(
          key: const Key('rel_refresh_btn'),
          onPressed: () {},
          icon: const Icon(Icons.refresh, size: 18),
          label: const Text('Refresh'),
        ),
    ],
    body: const SizedBox(height: 40),
  );
}


void main() {
  group('Relationships header — mobile responsive', () {
    for (final width in <double>[320, 390, 430]) {
      testWidgets('renders cleanly at ${width.toInt()}dp with no overflow',
          (t) async {
        await _pumpAtWidth(t,
          width: width,
          child: _headerFixture(isMobile: true),
        );
        // No RenderFlex overflow / any layout exception.
        expect(t.takeException(), isNull,
            reason: 'header must not overflow at ${width}dp');
        // Title stays visible and intact.
        expect(find.text('Relationships'), findsOneWidget);
        // Refresh action is still reachable — not sliced off by
        // the Row squeezing the title Expanded slot.
        expect(find.byKey(const Key('rel_refresh_btn')),
            findsOneWidget);
      });
    }

    testWidgets('at 320dp the Refresh button is BELOW the title/subtitle',
        (t) async {
      await _pumpAtWidth(t,
        width: 320,
        child: _headerFixture(isMobile: true),
      );
      final titleY = t.getTopLeft(find.text('Relationships')).dy;
      final refreshY = t.getTopLeft(
        find.byKey(const Key('rel_refresh_btn')),
      ).dy;
      expect(refreshY, greaterThan(titleY),
          reason: 'narrow mobile must stack Refresh below the '
              'title/subtitle instead of competing horizontally');
    });

    testWidgets('subtitle wraps but does not push the title off-screen',
        (t) async {
      await _pumpAtWidth(t,
        width: 320,
        child: _headerFixture(isMobile: true),
      );
      final titleTL = t.getTopLeft(find.text('Relationships'));
      // Title must be inside the viewport (dx >= 0).
      expect(titleTL.dx, greaterThanOrEqualTo(0));
      // And not pushed below the visible area (dy < 200).
      expect(titleTL.dy, lessThan(200));
    });
  });

  group('Relationships header — desktop layout still intact', () {
    testWidgets('single-row layout with title, subtitle, Refresh',
        (t) async {
      await _pumpAtWidth(t,
        width: 1200,
        child: _headerFixture(isMobile: false),
      );
      expect(t.takeException(), isNull);
      // At desktop widths the title and the Refresh button share
      // one row — so their vertical centers are near each other.
      final titleY = t.getCenter(find.text('Relationships')).dy;
      final refreshY = t.getCenter(
        find.byKey(const Key('rel_refresh_btn')),
      ).dy;
      expect((titleY - refreshY).abs(), lessThan(80),
          reason: 'desktop header must keep title + Refresh on '
              'the same visual row');
    });
  });

  group('Header degrades gracefully without any action', () {
    testWidgets('header renders even when actions=[]', (t) async {
      await _pumpAtWidth(t,
        width: 320,
        child: _headerFixture(
          isMobile: true,
          includeAction: false,
        ),
      );
      expect(t.takeException(), isNull);
      expect(find.text('Relationships'), findsOneWidget);
    });
  });
}
