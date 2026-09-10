import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/public_download_badges.dart';

Widget _wrap(Widget child, {double width = 390}) => MaterialApp(
      routes: {
        '/privacy': (_) => const SizedBox(),
        '/help-and-faq-public': (_) => const SizedBox(),
      },
      home: MediaQuery(
        data: MediaQueryData(size: Size(width, 900)),
        child: Scaffold(body: SingleChildScrollView(child: child)),
      ),
    );

void main() {
  testWidgets('both mobile store badges are live links', (tester) async {
    await tester.pumpWidget(_wrap(const PlatformDownloadBadges()));
    expect(find.byKey(const Key('google_play_download_badge')), findsOneWidget);
    expect(find.byKey(const Key('app_store_download_badge')), findsOneWidget);
    expect(kAppStoreListingUrl,
        'https://apps.apple.com/us/app/svaultai/id6800601455');
  });

  for (final width in <double>[390, 768, 1440]) {
    testWidgets('download section is overflow-free at width $width',
        (tester) async {
      await tester.pumpWidget(_wrap(
        const Column(children: [
          PublicMobileAppsSection(),
          PublicLandingFooter(),
        ]),
        width: width,
      ));
      expect(tester.takeException(), isNull);
    });
  }
}
