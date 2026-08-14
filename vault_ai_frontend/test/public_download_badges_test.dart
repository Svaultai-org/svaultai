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
  testWidgets('Google Play is linked and Apple badge has no dead link',
      (tester) async {
    await tester.pumpWidget(_wrap(const PlatformDownloadBadges()));
    expect(find.byKey(const Key('google_play_download_badge')), findsOneWidget);
    expect(find.byKey(const Key('apple_app_store_badge')), findsOneWidget);
    expect(
        find.byKey(const Key('apple_app_store_download_link')), findsNothing);
    expect(find.textContaining('Coming soon'), findsNothing);
    expect(kGooglePlayListingUrl,
        'https://play.google.com/store/apps/details?id=com.svaultai.app');
    expect(kConfiguredAppStoreUrl, isEmpty);
    expect(kConfiguredMacAppStoreUrl, isEmpty);
  });

  testWidgets('configured App Store URL makes the standard badge clickable',
      (tester) async {
    await tester.pumpWidget(_wrap(const PlatformDownloadBadges(
      appStoreUrl: 'https://example.test/apple-listing',
    )));
    expect(find.byKey(const Key('apple_app_store_badge')), findsOneWidget);
    expect(
        find.byKey(const Key('apple_app_store_download_link')), findsOneWidget);
    expect(find.textContaining('Coming soon'), findsNothing);
  });

  testWidgets('Mac reuses Apple listing and supports a distinct future URL',
      (tester) async {
    await tester.pumpWidget(_wrap(const PlatformDownloadBadges(
      appStoreUrl: 'https://example.test/apple-listing',
      macAppStoreUrl: 'https://example.test/apple-listing',
    )));
    expect(
        find.byKey(const Key('mac_app_store_download_action')), findsNothing);

    await tester.pumpWidget(_wrap(const PlatformDownloadBadges(
      appStoreUrl: 'https://example.test/apple-listing',
      macAppStoreUrl: 'https://example.test/mac-listing',
    )));
    expect(
        find.byKey(const Key('mac_app_store_download_action')), findsOneWidget);
  });

  for (final width in <double>[390, 768, 1440]) {
    testWidgets('download section is overflow-free at width $width',
        (tester) async {
      await tester.pumpWidget(_wrap(
        const Column(
          children: [
            PublicMobileAppsSection(),
            PublicLandingFooter(),
          ],
        ),
        width: width,
      ));
      expect(
          find.byKey(const Key('public_mobile_apps_section')), findsOneWidget);
      expect(find.byKey(const Key('public_landing_footer')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
