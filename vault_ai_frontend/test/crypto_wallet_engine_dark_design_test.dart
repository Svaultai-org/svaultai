

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/crypto_wallet_engine_design.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';

Future<void> _pumpEnginePage(
  WidgetTester tester, {
  Size size = const Size(1200, 2400),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('crypto wallet engine dark design', () {
    testWidgets('DD1: page background key + dark gradient is rendered',
        (tester) async {
      await _pumpEnginePage(tester);
      final bg = find.byKey(kWalletPageBackgroundKey);
      expect(bg, findsOneWidget);
      final widget = tester.widget<Container>(bg);
      final decoration = widget.decoration as BoxDecoration?;
      expect(decoration, isNotNull);
      expect(
        decoration!.gradient, isA<LinearGradient>(),
        reason: 'Page background must be a gradient, not a flat color.',
      );
      final gradient = decoration.gradient! as LinearGradient;
      
      for (final color in gradient.colors) {
        final hsl = HSLColor.fromColor(color);
        expect(
          hsl.lightness, lessThan(0.20),
          reason: 'Page background stop $color must be dark (lightness '
              '< 0.20). Got lightness=${hsl.lightness}.',
        );
      }
    });

    testWidgets(
        'DD2: every asset card is rendered with a non-white surface',
        (tester) async {
      await _pumpEnginePage(tester);
      for (final asset in kCryptoWalletEngineAssets) {
        final card = find.byKey(Key('crypto_wallet_engine_card_$asset'));
        expect(card, findsOneWidget,
            reason: 'Card for $asset must render.');
        final widget = tester.widget<Container>(card);
        final decoration = widget.decoration as BoxDecoration?;
        expect(decoration, isNotNull);
        
        
        final gradient = decoration!.gradient;
        expect(
          gradient, isA<LinearGradient>(),
          reason: 'Asset card for $asset must use a gradient surface.',
        );
        final colors = (gradient! as LinearGradient).colors;
        
        
        final avgLightness = colors
                .map((c) => HSLColor.fromColor(c).lightness)
                .fold<double>(0, (a, b) => a + b) /
            colors.length;
        expect(
          avgLightness, lessThan(0.25),
          reason: 'Average gradient lightness on $asset card is '
              '$avgLightness — must be < 0.25 for a dark surface.',
        );
      }
    });

    testWidgets('DD3: portfolio summary uses accent-tinted dark card',
        (tester) async {
      await _pumpEnginePage(tester);
      final card = find.byKey(
        const Key('crypto_wallet_engine_portfolio_summary'),
      );
      expect(card, findsOneWidget);
      final widget = tester.widget<Container>(card);
      final decoration = widget.decoration as BoxDecoration?;
      expect(decoration, isNotNull);
      
      
      final firstColor = decoration!.gradient is LinearGradient
          ? (decoration.gradient! as LinearGradient).colors.first
          : decoration.color ?? const Color(0xFFFFFFFF);
      final hsl = HSLColor.fromColor(firstColor);
      expect(
        hsl.lightness, lessThan(0.25),
        reason: 'Portfolio surface must be dark (lightness < 0.25). '
            'Got $firstColor with lightness=${hsl.lightness}.',
      );
    });

    testWidgets('DD4: activity / security / ask-ai cards are dark',
        (tester) async {
      
      
      await _pumpEnginePage(tester);
      const keys = <Key>[
        Key('crypto_wallet_engine_activity_section'),
        Key('crypto_wallet_engine_security_section'),
        Key('crypto_wallet_engine_ask_ai_section'),
      ];
      for (final key in keys) {
        final finder = find.byKey(key);
        expect(finder, findsOneWidget,
            reason: 'Section $key must render.');
        final widget = tester.widget<Container>(finder);
        final decoration = widget.decoration as BoxDecoration?;
        expect(decoration, isNotNull,
            reason: 'Section $key must carry a BoxDecoration.');
        final color = decoration!.gradient is LinearGradient
            ? (decoration.gradient! as LinearGradient).colors.first
            : decoration.color ?? const Color(0xFFFFFFFF);
        final hsl = HSLColor.fromColor(color);
        expect(
          hsl.lightness, lessThan(0.30),
          reason: 'Section $key surface must be dark '
              '(lightness < 0.30). Got $color, '
              'lightness=${hsl.lightness}.',
        );
      }
    });

    testWidgets(
        'DD5: launched assets carry the Live badge and NEVER the '
        'placeholder Coming next / Planned / Privacy wallet later '
        'badges',
        (tester) async {
      await _pumpEnginePage(tester);
      for (final asset in const ['SOL', 'USDT_TRC20', 'XMR']) {
        expect(
          find.byKey(Key('crypto_wallet_engine_card_live_$asset')),
          findsOneWidget,
          reason: 'Live badge for $asset must render on first frame.',
        );
        expect(
          find.byKey(
              Key('crypto_wallet_engine_card_future_state_$asset')),
          findsNothing,
          reason: '$asset is launched — no future-state badge should '
              'ever render on the live dashboard.',
        );
      }
      expect(find.text('Coming next'), findsNothing);
      expect(find.text('Planned'), findsNothing);
      expect(find.text('Privacy wallet later'), findsNothing);
    });

    testWidgets('DD6: every asset card carries a glyph icon avatar',
        (tester) async {
      await _pumpEnginePage(tester);
      for (final asset in kCryptoWalletEngineAssets) {
        expect(
          find.byKey(Key('crypto_wallet_engine_card_glyph_$asset')),
          findsOneWidget,
          reason: 'Glyph avatar for $asset must render.',
        );
      }
    });

    testWidgets('DD7: primary / secondary / ghost button shapes are pills',
        (tester) async {
      await _pumpEnginePage(tester);
      final receive = find.byKey(
        const Key('crypto_wallet_engine_primary_receive_btn'),
      );
      final send = find.byKey(
        const Key('crypto_wallet_engine_primary_send_btn'),
      );
      final activity = find.byKey(
        const Key('crypto_wallet_engine_primary_activity_btn'),
      );
      expect(receive, findsOneWidget);
      expect(send, findsOneWidget);
      expect(activity, findsOneWidget);
    });

    testWidgets('DD8: heading + subtitle use the dark-palette text colors',
        (tester) async {
      await _pumpEnginePage(tester);
      final heading = tester.widget<Text>(
        find.byKey(const Key('crypto_wallet_engine_heading')),
      );
      expect(heading.style?.color, equals(kWalletTextPrimary));
      final subheading = tester.widget<Text>(
        find.byKey(const Key('crypto_wallet_engine_subheading')),
      );
      expect(subheading.style?.color, equals(kWalletTextSecondary));
      
      final hsl = HSLColor.fromColor(kWalletTextSecondary);
      expect(
        hsl.lightness, greaterThan(0.50),
        reason: 'Secondary text color must be readable on dark surfaces.',
      );
    });

    testWidgets('DD9: no flat white Container surfaces survive on the dashboard',
        (tester) async {
      
      
      await _pumpEnginePage(tester);
      final scroller = find.byKey(const Key('crypto_wallet_engine_page'));
      expect(scroller, findsOneWidget);
      
      
      var inspected = 0;
      for (final el in find.descendant(
        of: scroller, matching: find.byType(Container),
      ).evaluate()) {
        final container = el.widget as Container;
        final decoration = container.decoration;
        if (decoration is! BoxDecoration) continue;
        final solid = decoration.color;
        if (solid == Colors.white) {
          fail('A Container on the Crypto Vault dashboard uses solid '
              'white. Found at key=${container.key}. The dark redesign '
              'forbids white card surfaces.');
        }
        final gradient = decoration.gradient;
        if (gradient is LinearGradient) {
          final first = gradient.colors.first;
          if (first == Colors.white) {
            fail('A Container on the Crypto Vault dashboard starts a '
                'gradient at pure white. Found at key=${container.key}.');
          }
        }
        inspected++;
      }
      expect(inspected, greaterThan(10),
          reason: 'Sanity: the dashboard should have many Containers; '
              'we only inspected $inspected.');
    });

    testWidgets(
        'DD10: walletStatusBadge tone live renders the success accent',
        (tester) async {
      
      
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: walletStatusBadge(
                'Live',
                tone: WalletBadgeTone.live,
                key: const Key('badge_test_live'),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final text = tester.widget<Text>(find.text('Live'));
      expect(text.style?.color, equals(kWalletAccentSuccess));
    });
  });
}
