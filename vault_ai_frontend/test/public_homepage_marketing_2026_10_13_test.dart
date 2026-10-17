import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/public_download_badges.dart';
import 'package:vault_ai_frontend/public_homepage_marketing.dart';

Widget _wrap(Widget child, {required double width, double scale = 1}) {
  return MaterialApp(
    routes: {
      '/signup': (_) => const Scaffold(body: Text('Existing signup route')),
      '/login': (_) => const Scaffold(body: Text('Existing login route')),
    },
    home: MediaQuery(
      data: MediaQueryData(
        size: Size(width, 900),
        textScaler: TextScaler.linear(scale),
      ),
      child: Scaffold(
        body: SingleChildScrollView(
          child: Padding(padding: const EdgeInsets.all(18), child: child),
        ),
      ),
    ),
  );
}

void main() {
  test(
    'public marketing keeps truthful free, wallet, AI and beneficiary limits',
    () {
      final source = File(
        'lib/public_homepage_marketing.dart',
      ).readAsStringSync();
      expect(kPublicHomepageCtaCaption, contains('1 GB included'));
      expect(kPublicHomepageCtaCaption, contains('No email or phone number'));
      expect(source, contains('Digital Assets & Crypto'));
      expect(source, contains('require an eligible paid storage plan'));
      expect(source, contains('on servers and with service providers'));
      expect(
        kPublicHomepageInheritance,
        contains('Approval releases the prepared credentials immediately'),
      );
      expect(
        kPublicHomepageInheritance,
        contains('Declining clears the request and returns the arrangement to normal'),
      );
      expect(
        source,
        contains('this is not a permission to share only selected files'),
      );
      expect(source, contains('transfer legal ownership'));
      expect(source, isNot(contains('asset records')));
      expect(source, isNot(contains('Your PIN never leaves your device')));
    },
  );

  test('real demo image is bundled and existing auth entry points remain', () {
    expect(
      File('assets/branding/public-vault-demo.jpg').lengthSync(),
      greaterThan(10000),
    );
    final main = File('lib/main.dart').readAsStringSync();
    expect(main, contains("'/': (_) => const LandingPage()"));
    expect(main, contains("'/login': (_) => privateRoute(const LoginPage())"));
    expect(
      main,
      contains("'/signup': (_) => privateRoute(const SignupPage())"),
    );
    expect(main, contains('child: const PublicHomepageDetails()'));
    expect(main, contains('const PublicHomepageDemo()'));
  });

  for (final width in <double>[320, 390, 768, 1440]) {
    for (final scale in <double>[1, 1.3]) {
      testWidgets('public homepage lays out at width $width and scale $scale', (
        tester,
      ) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = Size(width, 900);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          _wrap(
            const Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                PublicHomepageHero(),
                SizedBox(height: 24),
                PublicHomepageDemo(),
                SizedBox(height: 24),
                PublicHomepageDetails(),
                PublicHomepageFinalCta(),
                PublicLandingFooter(),
              ],
            ),
            width: width,
            scale: scale,
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text(kPublicHomepageHeadline), findsOneWidget);
        expect(
          find.byKey(const Key('public_homepage_primary_cta')),
          findsOneWidget,
        );
        expect(find.byKey(const Key('public_homepage_demo')), findsOneWidget);
        expect(
          find.byKey(const Key('public_homepage_plan_details')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('public_homepage_security_details')),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      });
    }
  }

  for (final entry in [
    (
      'public_homepage_primary_cta',
      const PublicHomepageHero(),
      'Existing signup route',
    ),
    (
      'public_homepage_sign_in',
      const PublicHomepageHero(),
      'Existing login route',
    ),
    (
      'public_homepage_create_vault_button',
      const PublicHomepageFinalCta(),
      'Existing signup route',
    ),
  ]) {
    testWidgets('${entry.$1} opens the existing account route', (tester) async {
      await tester.pumpWidget(_wrap(entry.$2, width: 390));
      final button = find.byKey(Key(entry.$1));
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(find.text(entry.$3), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('footer Help Center invokes the supported public-help callback',
      (tester) async {
    var opened = false;
    await tester.pumpWidget(_wrap(
      PublicLandingFooter(onHelpCenter: () => opened = true),
      width: 390,
    ));
    await tester.tap(find.byKey(const Key('public_footer_help_center')));
    await tester.pump();
    expect(opened, isTrue);
    expect(tester.takeException(), isNull);
    final main = File('lib/main.dart').readAsStringSync();
    expect(main, contains('onHelpCenter: () => openHelpCenter('));
  });
}
