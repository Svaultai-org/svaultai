import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';







File _webFile(String relative) {
  return File('web/$relative');
}

void main() {
  group('web/index.html metadata', () {
    late String html;

    setUpAll(() async {
      final f = _webFile('index.html');
      expect(await f.exists(), isTrue,
          reason: 'vault_ai_frontend/web/index.html must exist');
      html = await f.readAsString();
    });

    test('title is VaultAI', () {

      expect(html, contains('<title>VaultAI</title>'));
    });

    test('meta description is the VaultAI copy', () {
      expect(
        html,
        contains(
          'VaultAI is a private digital vault for securely storing '
          'and managing passwords, documents, IDs, files, secure '
          'notes, and crypto wallet records.',
        ),
      );
    });

    test('canonical URL points at svaultai.com', () {
      expect(
        html,
        contains('<link rel="canonical" href="https://svaultai.com">'),
      );
    });

    test('theme-color is the VaultAI brand accent #10A37F', () {
      expect(
        html,
        contains('<meta name="theme-color" content="#10A37F">'),
      );
    });

    group('Open Graph tags', () {
      test('og:title = VaultAI', () {
        expect(html, contains('property="og:title" content="VaultAI"'));
      });

      test('og:description = tagline', () {
        expect(
          html,
          contains(
            'property="og:description" '
            'content="Your private AI-powered digital vault."',
          ),
        );
      });

      test('og:type = website', () {
        expect(html, contains('property="og:type" content="website"'));
      });

      test('og:url = https://svaultai.com', () {
        expect(
          html,
          contains('property="og:url" content="https://svaultai.com"'),
        );
      });

      test('og:image = https://svaultai.com/og-image.png', () {
        expect(
          html,
          contains(
            'property="og:image" '
            'content="https://svaultai.com/og-image.png"',
          ),
        );
      });

      test('og:image has width + height (1200x630)', () {
        expect(html, contains('property="og:image:width" content="1200"'));
        expect(html, contains('property="og:image:height" content="630"'));
      });

      test('og:site_name = VaultAI', () {
        expect(html, contains('property="og:site_name" content="VaultAI"'));
      });
    });

    group('Twitter tags', () {
      test('twitter:card = summary_large_image', () {
        expect(
          html,
          contains('name="twitter:card" content="summary_large_image"'),
        );
      });

      test('twitter:title = VaultAI', () {
        expect(html, contains('name="twitter:title" content="VaultAI"'));
      });

      test('twitter:description = tagline', () {
        expect(
          html,
          contains(
            'name="twitter:description" '
            'content="Your private AI-powered digital vault."',
          ),
        );
      });

      test('twitter:image = https://svaultai.com/og-image.png', () {
        expect(
          html,
          contains(
            'name="twitter:image" '
            'content="https://svaultai.com/og-image.png"',
          ),
        );
      });
    });

    group('Apple / PWA tags', () {
      test('apple-mobile-web-app-title = VaultAI', () {
        expect(
          html,
          contains(
            'name="apple-mobile-web-app-title" content="VaultAI"',
          ),
        );
      });

      test('application-name = VaultAI', () {
        expect(
          html,
          contains('name="application-name" content="VaultAI"'),
        );
      });

      test('apple-touch-icon points at the 192px PWA icon', () {
        expect(
          html,
          contains(
            'rel="apple-touch-icon" href="icons/Icon-192.png"',
          ),
        );
      });

      test('favicon.png is referenced (VaultAI-branded)', () {
        expect(html, contains('rel="icon" type="image/png" href="favicon.png"'));
      });

      test('manifest.json is linked', () {
        expect(html, contains('rel="manifest" href="manifest.json"'));
      });
    });

    test('no vault_ai_frontend or default Flutter branding in public HTML', () {
      expect(
        html.toLowerCase(),
        isNot(contains('vault_ai_frontend')),
        reason: 'The default Flutter project name must not be shipped',
      );
      expect(
        html.toLowerCase(),
        isNot(contains('a new flutter project')),
        reason: 'The default Flutter description must not be shipped',
      );
    });
  });

  group('web/manifest.json branding', () {
    late Map<String, dynamic> manifest;

    setUpAll(() async {
      final f = _webFile('manifest.json');
      expect(await f.exists(), isTrue,
          reason: 'vault_ai_frontend/web/manifest.json must exist');
      manifest = jsonDecode(await f.readAsString()) as Map<String, dynamic>;
    });

    test('name = VaultAI', () {
      expect(manifest['name'], 'VaultAI');
    });

    test('short_name = VaultAI', () {
      expect(manifest['short_name'], 'VaultAI');
    });

    test('description is the VaultAI copy', () {
      expect(manifest['description'], 'VaultAI private digital vault');
    });

    test('start_url = /', () {
      expect(manifest['start_url'], '/');
    });

    test('display = standalone', () {
      expect(manifest['display'], 'standalone');
    });

    test('theme_color matches the brand accent #10A37F', () {
      expect(manifest['theme_color'], '#10A37F');
    });

    test('background_color matches the brand canvas #0F1115', () {
      expect(manifest['background_color'], '#0F1115');
    });

    test('no vault_ai_frontend or default Flutter branding in manifest', () {
      final asJson = jsonEncode(manifest).toLowerCase();
      expect(asJson, isNot(contains('vault_ai_frontend')));
      expect(asJson, isNot(contains('a new flutter project')));
    });

    test('icons list includes both 192 and 512 and their maskable variants', () {
      final icons = manifest['icons'] as List;
      final sources = icons.map((e) => (e as Map)['src']).toSet();
      expect(sources, contains('icons/Icon-192.png'));
      expect(sources, contains('icons/Icon-512.png'));
      expect(sources, contains('icons/Icon-maskable-192.png'));
      expect(sources, contains('icons/Icon-maskable-512.png'));
    });
  });

  group('web asset files exist with the correct dimensions', () {
    test('web/favicon.png exists and is non-empty', () async {
      final f = _webFile('favicon.png');
      expect(await f.exists(), isTrue);
      final bytes = await f.readAsBytes();
      expect(bytes.isNotEmpty, isTrue);


      expect(bytes.length, greaterThan(120));
    });

    test('web/og-image.png exists and is 1200x630', () async {
      final f = _webFile('og-image.png');
      expect(await f.exists(), isTrue,
          reason:
              'og-image.png must exist so link unfurls show the VaultAI card '
              'on iMessage, WhatsApp, Slack, Discord, Facebook, LinkedIn, X.');
      final bytes = await f.readAsBytes();
      expect(bytes.length, greaterThan(2000),
          reason: 'og-image.png must be a real branded image, not a stub');



      final w = bytes[16] << 24 | bytes[17] << 16 | bytes[18] << 8 | bytes[19];
      final h = bytes[20] << 24 | bytes[21] << 16 | bytes[22] << 8 | bytes[23];
      expect(w, 1200, reason: 'og-image.png must be 1200 wide');
      expect(h, 630, reason: 'og-image.png must be 630 tall');
    });

    test('all PWA icons exist and are non-empty', () async {
      for (final name in [
        'icons/Icon-192.png',
        'icons/Icon-512.png',
        'icons/Icon-maskable-192.png',
        'icons/Icon-maskable-512.png',
      ]) {
        final f = _webFile(name);
        expect(await f.exists(), isTrue, reason: '$name must exist');
        final bytes = await f.readAsBytes();
        expect(bytes.length, greaterThan(500), reason: '$name must not be a stub');
      }
    });

    test('favicon and PWA icons are branded (heuristic size check)', () async {

      final favicon = await _webFile('favicon.png').readAsBytes();
      expect(favicon.length, greaterThan(200));


      final icon512 = await _webFile('icons/Icon-512.png').readAsBytes();
      expect(icon512.length, greaterThan(2000),
          reason: 'Icon-512.png should be a proper VaultAI mark, not a stub');
    });
  });
}
