import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  late String mainSource;

  setUpAll(() async {
    mainSource = await File('lib/main.dart').readAsString();
  });

  test('shared header uses the approved mobile master and not legacy shield',
      () {
    expect(
      mainSource,
      contains("const String kCanonicalBrandLogoAsset = "
          "'assets/branding/vaultai-icon-1024.png';"),
    );
    final start = mainSource.indexOf('class TopNavBar');
    final end = mainSource.indexOf(
      'class ZkSemanticSearchUnavailableBanner',
      start,
    );
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final topNav = mainSource.substring(start, end);
    expect(topNav, contains("Key('top_nav_canonical_logo')"));
    expect(topNav, isNot(contains('Icons.shield_rounded')));
  });

  test('login and signup inherit the canonical shared header', () {
    final login = mainSource.substring(
      mainSource.indexOf('class LoginPage'),
      mainSource.indexOf('class SignupPage'),
    );
    final signup = mainSource.substring(
      mainSource.indexOf('class SignupPage'),
      mainSource.indexOf('class UnlockPage'),
    );
    expect(login, contains('appBar: TopNavBar'));
    expect(signup, contains('appBar: TopNavBar'));
    expect(mainSource, contains("initialRoute: kIsWeb ? null : '/login'"));
  });

  test('Help, privacy, and not-found public surfaces reference canonical logo',
      () async {
    expect(mainSource, contains("Key('help_center_canonical_logo')"));
    expect(mainSource, contains("Key('not_found_canonical_logo')"));

    final privacy = await File('web/privacy/index.html').readAsString();
    expect(privacy, contains('src="/icons/Icon-192.png"'));
    expect(privacy, isNot(contains('Icons.shield_rounded')));
  });

  test('private route indexing guard is present in HTML and Nginx source',
      () async {
    final index = await File('web/index.html').readAsString();
    final nginx =
        await File('../deploy/nginx/app.svaultai.com.conf').readAsString();
    expect(index, contains('noindex, nofollow, noarchive'));
    expect(index, contains("path === '/help-and-faq-public'"));
    expect(nginx, contains('add_header X-Robots-Tag'));
    expect(nginx, contains(r'map $request_uri $vaultai_robots_header'));
    expect(
      nginx,
      matches(RegExp(
        r'location = /index\.html\s*\{[^}]*add_header X-Robots-Tag',
        dotAll: true,
      )),
    );
    expect(nginx,
        contains('default                     "noindex, nofollow, noarchive"'));
    for (final publicAsset in <String>[
      '/robots.txt',
      '/sitemap.xml',
      '/favicon.ico',
      '/favicon.png',
      '/favicon-16x16.png',
      '/favicon-32x32.png',
      '/apple-touch-icon.png',
      '/og-image.png',
    ]) {
      expect(
        nginx,
        matches(RegExp('${RegExp.escape(publicAsset)}\\s+"";')),
      );
    }
  });
}
