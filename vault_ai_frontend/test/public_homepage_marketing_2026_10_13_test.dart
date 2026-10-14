import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/public_download_badges.dart';
import 'package:vault_ai_frontend/public_homepage_marketing.dart';

String _html() => File('web/index.html').readAsStringSync();

Map<String, dynamic> _softwareApplication() {
  final payload = RegExp(
    r'<script type="application/ld\+json">([\s\S]*?)</script>',
  ).firstMatch(_html())!.group(1)!;
  final graph = (jsonDecode(payload) as Map<String, dynamic>)['@graph'] as List;
  return Map<String, dynamic>.from(
    graph.singleWhere((node) => node['@type'] == 'SoftwareApplication') as Map,
  );
}

String _sha(String text) => sha256.convert(utf8.encode(text)).toString();

Widget _wrap(Widget child, {required double width, double scale = 1}) {
  return MaterialApp(
    routes: {
      '/signup': (_) => const Scaffold(body: Text('Existing signup route')),
      '/privacy': (_) => const Scaffold(body: Text('Existing privacy route')),
      '/help-and-faq-public': (_) =>
          const Scaffold(body: Text('Existing help route')),
    },
    home: MediaQuery(
      data: MediaQueryData(
        size: Size(width, 900),
        textScaler: TextScaler.linear(scale),
      ),
      child: Scaffold(
        body: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: child,
          ),
        ),
      ),
    ),
  );
}

void main() {
  group('approved public homepage marketing copy', () {
    test('visible headline and opening use the approved accurate wording', () {
      expect(
        kPublicHomepageHeadline,
        'SVaultAI — The Vault Your Family Can Actually Open',
      );
      expect(
        _sha(kPublicHomepageOpening),
        '04d52e00aae073d4f3dbd8113aca0500c39649d1efb645d3c96e26eeef236ca1',
      );
      expect(
        _sha(kPublicHomepageInheritance),
        '6320e1c0c7a8bc0d202cbae140f8d8e6f363b645db32c38087f46f2e287da460',
      );
    });

    test('static headline and social titles agree with the visible hero', () {
      final html = _html();
      expect(html, contains('<title>$kPublicHomepageHeadline</title>'));
      expect(
        html,
        contains('property="og:title" content="$kPublicHomepageHeadline"'),
      );
      expect(
        html,
        contains('name="twitter:title" content="$kPublicHomepageHeadline"'),
      );
      expect(html, contains('<h1>$kPublicHomepageHeadline</h1>'));
      expect(RegExp(r'<h1>').allMatches(html), hasLength(1));
      final summary = '${kPublicHomepageOpening.split('. Pair').first}.';
      expect(
        html,
        contains('name="description" content="$summary"'),
      );
      expect(
        html,
        contains('property="og:description" content="$summary"'),
      );
      expect(
        html,
        contains('name="twitter:description" content="$summary"'),
      );
    });

    test('inheritance immediately follows opening and keeps the legal warning',
        () {
      final html = _html();
      final opening = html.indexOf('<p>$kPublicHomepageOpening</p>');
      final inheritance =
          html.indexOf('<h2>$kPublicHomepageInheritanceHeading</h2>');
      expect(opening, greaterThan(-1));
      expect(inheritance, greaterThan(opening));
      expect(
        html.substring(opening, inheritance),
        '<p>$kPublicHomepageOpening</p>\n    ',
      );
      expect(html, contains('<p>$kPublicHomepageInheritance</p>'));
      expect(
        kPublicHomepageInheritance,
        contains(
            'A beneficiary must request access before the waiting period starts.'),
      );
      expect(
        kPublicHomepageInheritance,
        contains('decline to stop that pending release.'),
      );
      expect(
        kPublicHomepageInheritance,
        contains('not a legal will or a substitute for estate advice.'),
      );
    });

    test('approved chat and asset copy retain Concierge and availability', () {
      final html = _html();
      expect(
          html,
          contains(
              "Ask the AI chat to find, save, retrieve and manage content you authorize inside your vault — \"where's my passport scan?\" — in everyday language. Client-side encryption keeps protected vault content under your control."));
      expect(
          html,
          contains(
              "Assets brings supported non-custodial cryptocurrency, PAXG Digital Gold and Ethereum KAG Digital Silver together. Inheritance access planning can help a paired beneficiary access the vault using the credentials you prepare; it does not transfer legal ownership of assets."));
      expect(
        html,
        contains(
            "Concierge offers optional free checks for known password exposure, weakness and reuse. Other tokenized categories are coming soon; email and background exposure monitoring are not enabled, and private-file or comprehensive dark-web scanning is not supported."),
      );
      expect(
        html,
        contains(
            'Cryptocurrency wallet features require an eligible paid storage plan.'),
      );
      expect(
        _softwareApplication()['description'],
        "An encrypted digital vault for files, photos, documents, logins and memories, with a built-in chat assistant and optional inheritance access planning. Prepare encrypted credentials for a paired beneficiary, then approve or decline their access request. Requests can become claimable after their waiting period if you do not respond. Free base vault; optional paid storage plans. Availability depends on the asset, network and issuer.",
      );
    });

    test('software price, subscription offer and existing store links remain',
        () {
      final software = _softwareApplication();
      expect(software['offers'], {
        '@type': 'Offer',
        'price': '0',
        'priceCurrency': 'USD',
        'description': 'Free download with optional in-app subscriptions',
      });
      expect(software['downloadUrl'], [
        'https://apps.apple.com/us/app/svaultai/id6800601455',
        'https://play.google.com/store/apps/details?id=com.svaultai.app',
      ]);
      final seo = RegExp(
        r'<main id="seo-content"[\s\S]*?</main>',
      ).firstMatch(_html())!.group(0)!;
      final destinations = RegExp(
        r'<a href="([^"]+)">',
      ).allMatches(seo).map((match) => match.group(1)).toList();
      expect(destinations, [
        '/privacy/',
        '/help-and-faq-public',
        '/features/',
        '/guides/',
        'https://apps.apple.com/us/app/svaultai/id6800601455',
        'https://play.google.com/store/apps/details?id=com.svaultai.app',
        '/signup',
      ]);
    });

    test('only requested CTA is appended and no unsupported promises remain',
        () {
      final html = _html();
      expect(
        html,
        contains('<h2>$kPublicHomepageCtaHeading</h2>\n'
            '    <a href="/signup">$kPublicHomepageCtaButton</a>\n'
            '    <p>$kPublicHomepageCtaCaption</p>'),
      );
      expect(html.indexOf('<h2>$kPublicHomepageCtaHeading</h2>'),
          greaterThan(html.indexOf('</nav>')));
      for (final unsupported in [
        'end-to-end-encrypted vault for your entire digital life',
        "it only opens if you're gone",
        'automatically after 30 days of silence',
        'It takes 30 seconds.',
        'Your PIN never leaves your device',
      ]) {
        expect(html, isNot(contains(unsupported)));
      }
    });

    test('hidden SEO, boot shell and private-route controls stay in place', () {
      final html = _html();
      expect(html, contains('#seo-content { display: none !important; }'));
      expect(
          html, contains("document.getElementById('seo-content')?.remove()"));
      expect(html, contains("path === '/' || path === '/help-and-faq-public'"));
      expect(html, contains("'content', 'noindex, nofollow, noarchive'"));
      expect(
          html, contains('id="svaultai-boot-logo" src="icons/Icon-512.png"'));
      expect(html, contains('window.location.reload()'));
    });

    test('existing public sections, hero controls and routes remain intact',
        () {
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, contains("title: 'Svaultai'"));
      expect(source, contains('child: const PublicMobileAppsSection()'));
      expect(source, contains('child: const PublicLandingFooter()'));
      expect(source, contains('child: const PublicHomepageFinalCta()'));
      final start = source.indexOf('class _HeroText');
      final hero =
          source.substring(start, source.indexOf('class _HeroCard', start));
      expect(hero, contains('kPublicHomepageHeadline'));
      expect(hero, contains('kPublicHomepageOpening'));
      expect(hero, contains('const PublicHomepageInheritance()'));
      expect(hero, contains("Navigator.pushNamed(context, '/signup')"));
      expect(hero, contains("Navigator.pushNamed(context, '/login')"));
      expect(hero, contains('AppLocalizations.of(context).commonSignUp'));
      expect(hero, contains('AppLocalizations.of(context).commonSignIn'));
      expect(hero, contains('const PlatformDownloadBadges(compact: true)'));
      expect(
        source.indexOf('child: const PublicHomepageFinalCta()'),
        greaterThan(source.indexOf('child: const PublicLandingFooter()')),
      );
    });
  });

  for (final width in <double>[390, 768, 1440]) {
    for (final scale in <double>[1, 1.3]) {
      testWidgets('new marketing copy fits width $width at text scale $scale',
          (tester) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = Size(width, 900);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(_wrap(
          const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(kPublicHomepageHeadline),
              Text(kPublicHomepageOpening),
              PublicHomepageInheritance(),
              PublicHomepageFinalCta(),
            ],
          ),
          width: width,
          scale: scale,
        ));
        await tester.pump();
        expect(find.text(kPublicHomepageInheritanceHeading), findsOneWidget);
        expect(find.text(kPublicHomepageInheritance), findsOneWidget);
        expect(find.text(kPublicHomepageCtaHeading), findsOneWidget);
        expect(find.text(kPublicHomepageCtaButton), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }

  for (final width in <double>[390, 768, 1440]) {
    testWidgets('unchanged public sections and additions fit width $width',
        (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = Size(width, 900);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(_wrap(
        const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            PublicHomepageInheritance(),
            PublicMobileAppsSection(),
            PublicLandingFooter(),
            PublicHomepageFinalCta(),
          ],
        ),
        width: width,
      ));
      await tester.pump();
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('new CTA opens only the existing signup route', (tester) async {
    await tester.pumpWidget(_wrap(const PublicHomepageFinalCta(), width: 390));
    await tester
        .tap(find.byKey(const Key('public_homepage_create_vault_button')));
    await tester.pumpAndSettle();
    expect(find.text('Existing signup route'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
