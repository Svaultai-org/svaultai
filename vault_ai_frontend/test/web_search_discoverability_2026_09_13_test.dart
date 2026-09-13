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

    test('feature hub links to every focused guide', () {
      final hub = _read('web/features/index.html');
      for (final canonical in pages.values.skip(1)) {
        final path = Uri.parse(canonical).path;
        expect(hub, contains('href="$path"'), reason: path);
      }
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
      expect(robots, contains('Disallow: /login'));
      expect(nginx, contains(r'~^/features(?:/.*)?$'));
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
  });
}
