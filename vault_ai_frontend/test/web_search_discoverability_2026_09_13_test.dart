import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('public web search discoverability', () {
    final pages = <String, String>{
      'web/features/index.html': 'https://app.svaultai.com/features/',
      'web/features/password-manager/index.html':
          'https://app.svaultai.com/features/password-manager/',
      'web/features/encrypted-file-storage/index.html':
          'https://app.svaultai.com/features/encrypted-file-storage/',
      'web/features/private-memory-vault/index.html':
          'https://app.svaultai.com/features/private-memory-vault/',
      'web/features/digital-inheritance/index.html':
          'https://app.svaultai.com/features/digital-inheritance/',
      'web/features/zero-knowledge-security/index.html':
          'https://app.svaultai.com/features/zero-knowledge-security/',
      'web/guides/index.html': 'https://app.svaultai.com/guides/',
      'web/guides/private-encrypted-vault/index.html':
          'https://app.svaultai.com/guides/private-encrypted-vault/',
      'web/guides/password-manager-vs-digital-vault/index.html':
          'https://app.svaultai.com/guides/password-manager-vs-digital-vault/',
      'web/guides/encrypted-file-storage-checklist/index.html':
          'https://app.svaultai.com/guides/encrypted-file-storage-checklist/',
      'web/guides/digital-inheritance-checklist/index.html':
          'https://app.svaultai.com/guides/digital-inheritance-checklist/',
    };

    test('every feature page is indexable, canonical, and descriptive', () {
      final titles = <String>{};
      final descriptions = <String>{};

      for (final entry in pages.entries) {
        final html = _read(entry.key);
        final title =
            RegExp(r'<title>([^<]+)</title>').firstMatch(html)?.group(1);
        final description = RegExp(
          r'<meta name="description" content="([^"]+)">',
        ).firstMatch(html)?.group(1);

        expect(title, isNotNull, reason: entry.key);
        expect(description, isNotNull, reason: entry.key);
        expect(title!.length, inInclusiveRange(25, 70), reason: entry.key);
        expect(description!.length, inInclusiveRange(90, 180),
            reason: entry.key);
        expect(titles.add(title), isTrue, reason: 'duplicate title: $title');
        expect(descriptions.add(description), isTrue,
            reason: 'duplicate description: $description');
        expect(html, contains('<meta name="robots" content="index, follow'));
        expect(html, contains('<link rel="canonical" href="${entry.value}">'));
        expect(html, contains('application/ld+json'));
        expect(html.toLowerCase(), isNot(contains('100% secure')));
      }
    });

    test('feature and guide hubs expose every focused public page', () {
      final hub = _read('web/features/index.html');
      final guideHub = _read('web/guides/index.html');
      for (final canonical in pages.values.where(
        (url) => url.contains('/features/') && url != pages.values.first,
      )) {
        final path = Uri.parse(canonical).path;
        expect(hub, contains('href="$path"'), reason: path);
      }
      for (final canonical in pages.values.where(
        (url) => url.contains('/guides/') && !url.endsWith('/guides/'),
      )) {
        final path = Uri.parse(canonical).path;
        expect(guideHub, contains('href="$path"'), reason: path);
      }
      expect(hub, contains('href="/guides/"'));
    });

    test('sitemap exposes every public feature URL', () {
      final sitemap = _read('web/sitemap.xml');
      for (final canonical in pages.values) {
        expect(sitemap, contains('<loc>$canonical</loc>'), reason: canonical);
      }
      expect(sitemap, contains('<lastmod>2026-09-13</lastmod>'));
    });

    test('robots and nginx allow feature guides but protect app routes', () {
      final robots = _read('web/robots.txt');
      final nginx = _read('../deploy/nginx/app.svaultai.com.conf');

      expect(robots, contains('Allow: /features/'));
      expect(robots, contains('Allow: /guides/'));
      expect(robots, contains('Disallow: /login'));
      expect(nginx, contains(r'~^/features(?:/.*)?$'));
      expect(nginx, contains(r'~^/guides(?:/.*)?$'));
      expect(
          nginx,
          contains(
              'default                     "noindex, nofollow, noarchive"'));
    });

    test('root structured data names both official mobile stores', () {
      final html = _read('web/index.html');
      expect(html,
          contains('https://apps.apple.com/us/app/svaultai/id6800601455'));
      expect(
          html,
          contains(
              'https://play.google.com/store/apps/details?id=com.svaultai.app'));
      expect(
          html, contains('Free download with optional in-app subscriptions'));
      expect(html, contains('href="/features/"'));
    });

    test('IndexNow ownership and submission wiring are valid', () {
      const key = 'd3e731074886067a0a003327df1cbed1';
      final keyFile = _read('web/$key.txt').trim();
      final submissionScript = _read('scripts/submit-indexnow.sh');

      expect(keyFile, key);
      expect(keyFile, matches(RegExp(r'^[a-f0-9]{32}$')));
      expect(submissionScript, contains('https://api.indexnow.org/indexnow'));
      expect(
        submissionScript,
        contains('https://app.svaultai.com/\${indexnow_key}.txt'),
      );
      expect(submissionScript, contains("'urlList': urls"));
    });
  });
}
