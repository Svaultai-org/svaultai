import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart' as crypto;
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

    test('title uses canonical SVaultAI branding', () {
      expect(
        html,
        contains('<title>SVaultAI — Private AI-Powered Digital Vault</title>'),
      );
    });

    test('meta description carries the complete positioning', () {
      expect(
        html,
        contains(
          'SVaultAI is a private, AI-powered digital vault designed to protect '
          'and manage credentials, documents, memories, media, identity '
          'records, inheritance, and non-custodial digital assets with '
          'zero-knowledge, user-controlled access.',
        ),
      );
    });

    test('canonical URL points at the served production host', () {
      expect(
        html,
        contains('<link rel="canonical" href="https://app.svaultai.com/">'),
      );
    });

    test('theme-color uses the canonical dark icon canvas', () {
      expect(
        html,
        contains('<meta name="theme-color" content="#0F1115">'),
      );
    });

    group('Open Graph tags', () {
      test('og:title uses canonical branding', () {
        expect(
            html,
            contains(
                'property="og:title" content="SVaultAI — Private AI-Powered Digital Vault"'));
      });

      test('og:description = tagline', () {
        expect(
          html,
          contains(
            'property="og:description" '
            'content="Protect and manage credentials, documents, memories',
          ),
        );
      });

      test('og:type = website', () {
        expect(html, contains('property="og:type" content="website"'));
      });

      test('og:url = https://app.svaultai.com', () {
        expect(
          html,
          contains('property="og:url" content="https://app.svaultai.com/"'),
        );
      });

      test('og:image = https://app.svaultai.com/og-image.png', () {
        expect(
          html,
          contains(
            'property="og:image" '
            'content="https://app.svaultai.com/og-image.png"',
          ),
        );
      });

      test('og:image has width + height (1200x630)', () {
        expect(html, contains('property="og:image:width" content="1200"'));
        expect(html, contains('property="og:image:height" content="630"'));
      });

      test('og:site_name = SVaultAI', () {
        expect(html, contains('property="og:site_name" content="SVaultAI"'));
      });
    });

    group('Twitter tags', () {
      test('twitter:card = summary_large_image', () {
        expect(
          html,
          contains('name="twitter:card" content="summary_large_image"'),
        );
      });

      test('twitter:title uses canonical branding', () {
        expect(
            html,
            contains(
                'name="twitter:title" content="SVaultAI — Private AI-Powered Digital Vault"'));
      });

      test('twitter:description = tagline', () {
        expect(
          html,
          contains(
            'name="twitter:description" '
            'content="A private, AI-powered digital vault',
          ),
        );
      });

      test('twitter:image = https://app.svaultai.com/og-image.png', () {
        expect(
          html,
          contains(
            'name="twitter:image" '
            'content="https://app.svaultai.com/og-image.png"',
          ),
        );
      });
    });

    group('Apple / PWA tags', () {
      test('apple-mobile-web-app-title = SVaultAI', () {
        expect(
          html,
          contains(
            'name="apple-mobile-web-app-title" content="SVaultAI"',
          ),
        );
      });

      test('application-name = SVaultAI', () {
        expect(
          html,
          contains('name="application-name" content="SVaultAI"'),
        );
      });

      test('apple-touch-icon points at the canonical 180px asset', () {
        expect(
          html,
          contains(
            'rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png"',
          ),
        );
      });

      test('ICO and sized canonical PNG favicons are referenced', () {
        expect(html, contains('rel="icon" href="favicon.ico" sizes="any"'));
        expect(html, contains('href="favicon-32x32.png"'));
        expect(html, contains('href="favicon-16x16.png"'));
      });

      test('manifest.json is linked', () {
        expect(html, contains('rel="manifest" href="manifest.json"'));
      });
    });

    test('JSON-LD defines WebSite, Organization and SoftwareApplication', () {
      expect(html, contains('type="application/ld+json"'));
      expect(html, contains('"@type": "WebSite"'));
      expect(html, contains('"@type": "Organization"'));
      expect(html, contains('"@type": "SoftwareApplication"'));
      expect(html, contains('"name": "SVaultAI"'));
      expect(html,
          contains('"logo": "https://app.svaultai.com/icons/Icon-512.png"'));
      expect(
        html,
        contains(
            'https://play.google.com/store/apps/details?id=com.svaultai.app'),
      );
      expect(html, isNot(contains('apps.apple.com')));
    });

    test('crawlable pre-boot content carries the product positioning', () {
      expect(html,
          contains('<h1>SVaultAI — Private AI-Powered Digital Vault</h1>'));
      expect(html, contains('AI-powered conversational access'));
      expect(html, contains('non-custodial digital assets'));
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

    test('name uses full SVaultAI title', () {
      expect(manifest['name'], 'SVaultAI — Private AI-Powered Digital Vault');
    });

    test('short_name = SVaultAI', () {
      expect(manifest['short_name'], 'SVaultAI');
    });

    test('description carries the broad vault positioning', () {
      expect(manifest['description'],
          contains('private, AI-powered digital vault'));
      expect(manifest['description'], contains('non-custodial digital assets'));
    });

    test('start_url = /', () {
      expect(manifest['start_url'], '/');
    });

    test('display = standalone', () {
      expect(manifest['display'], 'standalone');
    });

    test('theme_color matches the canonical dark icon canvas', () {
      expect(manifest['theme_color'], '#0F1115');
    });

    test('background_color matches the brand canvas #0F1115', () {
      expect(manifest['background_color'], '#0F1115');
    });

    test('no vault_ai_frontend or default Flutter branding in manifest', () {
      final asJson = jsonEncode(manifest).toLowerCase();
      expect(asJson, isNot(contains('vault_ai_frontend')));
      expect(asJson, isNot(contains('a new flutter project')));
    });

    test('icons list includes both 192 and 512 and their maskable variants',
        () {
      final icons = manifest['icons'] as List;
      final sources = icons.map((e) => (e as Map)['src']).toSet();
      expect(sources, contains('icons/Icon-192.png'));
      expect(sources, contains('icons/Icon-512.png'));
      expect(sources, contains('icons/Icon-maskable-192.png'));
      expect(sources, contains('icons/Icon-maskable-512.png'));
    });
  });

  group('crawler control files', () {
    test('robots allows public crawling and points to canonical sitemap',
        () async {
      final robots = await _webFile('robots.txt').readAsString();
      expect(robots, contains('User-agent: *'));
      expect(robots, contains('Allow: /'));
      expect(robots, contains('Allow: /help-and-faq-public'));
      expect(robots, contains('Disallow: /login'));
      expect(robots, contains('Disallow: /chat'));
      expect(robots, contains('Disallow: /storage'));
      expect(robots, contains('Sitemap: https://app.svaultai.com/sitemap.xml'));
    });

    test('sitemap contains only canonical public URLs', () async {
      final sitemap = await _webFile('sitemap.xml').readAsString();
      expect(sitemap, contains('<loc>https://app.svaultai.com/</loc>'));
      expect(sitemap, contains('<loc>https://app.svaultai.com/privacy/</loc>'));
      expect(
        sitemap,
        contains('<loc>https://app.svaultai.com/help-and-faq-public</loc>'),
      );
      expect(sitemap, isNot(contains('<loc>https://svaultai.com/')));
    });
  });

  group('web asset files exist with the correct dimensions', () {
    test('all browser and Apple icon variants exist', () async {
      for (final name in [
        'favicon.ico',
        'favicon-16x16.png',
        'favicon-32x32.png',
        'favicon.png',
        'apple-touch-icon.png',
      ]) {
        final f = _webFile(name);
        expect(await f.exists(), isTrue, reason: '$name must exist');
        expect((await f.readAsBytes()).length, greaterThan(120));
      }
    });

    test('web/og-image.png exists and is 1200x630', () async {
      final f = _webFile('og-image.png');
      expect(await f.exists(), isTrue,
          reason:
              'og-image.png must exist so link unfurls show the SVaultAI card '
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
        expect(bytes.length, greaterThan(500),
            reason: '$name must not be a stub');
      }
    });

    test('favicon and PWA icons are branded (heuristic size check)', () async {
      final favicon = await _webFile('favicon.png').readAsBytes();
      expect(favicon.length, greaterThan(200));

      final icon512 = await _webFile('icons/Icon-512.png').readAsBytes();
      expect(icon512.length, greaterThan(2000),
          reason: 'Icon-512.png should be a proper SVaultAI mark, not a stub');
    });

    test('canonical source and generated web assets have approved hashes',
        () async {
      const expected = {
        'assets/branding/vaultai-icon-1024.png':
            'f6e35c09f709f20da6db0951676306ff7da14d7622d749902844fdb6e4a7c3e4',
        'web/favicon.ico':
            '45c4b23431abef7442709acbd8d92387b183b44e7b6b2f6829e34098da33e244',
        'web/favicon-16x16.png':
            'd0582bb93eefe7b4f6e46544e1106c145503494d18f0932f20ae358c046feac2',
        'web/favicon-32x32.png':
            'd87ca40f8b1af1ada40350b4ef75dc9c7be79d462c4a11f231b7403545ecbf34',
        'web/apple-touch-icon.png':
            '56875ee9d786758f39aca66cb11fd63296fb927bb1ce411ac41ccc0f61b352a4',
        'web/icons/Icon-192.png':
            '0a3f796d488d3ed2b2a38180e5a3a87d18b4b785be949955564e207b334a75f7',
        'web/icons/Icon-512.png':
            '927bf6a8dcc3fd3a226d9b5f9dae861596d466eaadbf352e33fee35acea04e52',
        'web/icons/Icon-maskable-192.png':
            'ab664bc734c6695ee62acc8a4fbea2a77a9a32f00e5fc57ac25cdb7e966c6bd9',
        'web/icons/Icon-maskable-512.png':
            'a816c77570197cf4a510ea6245228f375316ff7fc2ed9b4e1c77a40df230d99a',
        'web/og-image.png':
            'c67d7701f93faa8d8a3fd2067eaacca7e8b4bb273ab045b8b8338e23bc4cfe15',
      };

      for (final entry in expected.entries) {
        final file = File(entry.key);
        expect(await file.exists(), isTrue, reason: '${entry.key} must exist');
        final digest =
            crypto.sha256.convert(await file.readAsBytes()).toString();
        expect(digest, entry.value, reason: '${entry.key} must be canonical');
      }
    });
  });
}
