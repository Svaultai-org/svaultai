// 2026-07-17 (Round 14 — branded startup loader): regression suite
// for the inline HTML/CSS loader that renders while main.dart.js
// downloads. The loader MUST:
//
//   1. Exist in web/index.html.
//   2. Carry VaultAI branding (wordmark + brand canvas colour + accent).
//   3. Ship the visible caption "Loading VaultAI…".
//   4. Expose accessibility hooks (role="status", aria-live="polite",
//      aria-label, aria-hidden on decorative subtrees, prefers-reduced-
//      motion honoured).
//   5. Be removed after Flutter's first frame:
//        - Primary: `flutter-first-frame` window event listener.
//        - Fallback A: MutationObserver watches for `flutter-view` /
//          `flt-glass-pane` / `flt-scene-host`.
//        - Fallback B: polling safety net so a missed event never
//          leaves the loader on top of a working app.
//   6. Be pure inline HTML/CSS + inline SVG — no remote assets, no
//      external fonts, no CDN scripts (CSP `default-src 'self'`).
//   7. Preserve every existing pre-loader contract:
//        - Round-12 SW bootstrap (`vaultai-sw-bootstrap.js`) still
//          loads SYNCHRONOUSLY BEFORE the async `flutter_bootstrap.js`.
//        - The OG title/tags block is untouched.
//        - The CSP / same-origin discipline is intact.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _html() {
  return File('${Directory.current.path}/web/index.html')
      .readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {
  late String html;

  setUpAll(() {
    final f = File('${Directory.current.path}/web/index.html');
    expect(f.existsSync(), isTrue,
        reason: 'vault_ai_frontend/web/index.html must exist');
    html = _html();
  });


  group('Round 14 — branded startup loader present', () {
    test('loader root div id is present with expected tag shape', () {
      expect(
        RegExp(
          r'<div\s+id="vaultai-startup-loader"',
          multiLine: true,
        ).hasMatch(html),
        isTrue,
        reason:
            'The startup loader root <div id="vaultai-startup-loader"> '
            'must be rendered directly in index.html so the first paint '
            'is never a blank tab.',
      );
    });

    test('renders BEFORE flutter_bootstrap.js in body order', () {
      final loaderIdx = html.indexOf('id="vaultai-startup-loader"');
      final flutterIdx = html.indexOf('flutter_bootstrap.js');
      expect(loaderIdx, greaterThan(-1));
      expect(flutterIdx, greaterThan(-1));
      expect(loaderIdx < flutterIdx, isTrue,
          reason:
              'The loader element must appear in the DOM before the '
              'async flutter_bootstrap.js tag — otherwise the tab is '
              'blank while main.dart.js is fetched.');
    });
  });


  group('Round 14 — VaultAI branding', () {
    test('brand canvas #0F1115 is the loader background', () {
      expect(
        RegExp(r'#vaultai-startup-loader\s*\{[^}]*background:\s*#0F1115',
            caseSensitive: false,
            multiLine: true,
            dotAll: true).hasMatch(html),
        isTrue,
        reason: 'Loader background must match the VaultAI canvas #0F1115 '
                '(same as web manifest background_color and mobile splash).',
      );
    });

    test('brand accent #10A37F is used for spinner + icon stroke', () {

      final accentMatches =
          RegExp(r'#10A37F', caseSensitive: false).allMatches(html).length;
      expect(accentMatches, greaterThanOrEqualTo(2),
          reason:
              'Brand accent #10A37F must be used somewhere inside the '
              'loader styles (spinner + icon).');
    });

    test('VaultAI wordmark text renders literally in the loader', () {
      final wordmarkRegion = RegExp(
        r'<div\s+class="vaultai-loader-wordmark"[^>]*>.*?</div>',
        dotAll: true,
      ).firstMatch(html);
      expect(wordmarkRegion, isNotNull,
          reason: 'wordmark region must exist');
      expect(wordmarkRegion!.group(0)!, contains('VaultAI'),
          reason: 'The literal "VaultAI" wordmark text must render.');
    });

    test(
        'inline SVG vault icon is present (no remote image references)',
        () {

      final loaderSection = html.substring(
        html.indexOf('id="vaultai-startup-loader"'),
        html.indexOf('vaultai-sw-bootstrap.js'),
      );
      expect(loaderSection.contains('<svg'), isTrue,
          reason: 'Loader must use an inline SVG icon.');
      expect(loaderSection.contains('vaultai-loader-icon'), isTrue,
          reason: 'Icon must carry the vaultai-loader-icon class '
                  'for styling.');


      expect(loaderSection.contains('<img'), isFalse,
          reason:
              'Loader must NOT reference an <img> — that would trigger a '
              'network fetch and defeat the point of an inline loader.');
    });

    test('caption reads "Loading VaultAI…"', () {

      expect(
        html.contains('Loading VaultAI&hellip;') ||
            html.contains('Loading VaultAI…'),
        isTrue,
        reason: 'Visible caption must read "Loading VaultAI…" '
                '(literal ellipsis or &hellip; entity).',
      );
    });
  });


  group('Round 14 — accessibility', () {
    test('role="status" on the loader root', () {
      final rootMatch = RegExp(
        r'<div\s+id="vaultai-startup-loader"[^>]*>',
      ).firstMatch(html);
      expect(rootMatch, isNotNull);
      final tag = rootMatch!.group(0)!;
      expect(tag, contains('role="status"'),
          reason:
              'The loader root must carry role="status" so screen '
              'readers announce it as a live status region.');
    });

    test('aria-live="polite" on the loader root', () {
      final rootMatch = RegExp(
        r'<div\s+id="vaultai-startup-loader"[^>]*>',
      ).firstMatch(html);
      expect(rootMatch, isNotNull);
      final tag = rootMatch!.group(0)!;
      expect(tag, contains('aria-live="polite"'),
          reason:
              'The loader root must be a polite aria-live region so '
              'assistive tech announces the loading state without '
              'interrupting.');
    });

    test('aria-label is set on the root so SR users know what it is', () {
      final rootMatch = RegExp(
        r'<div\s+id="vaultai-startup-loader"[^>]*>',
      ).firstMatch(html);
      expect(rootMatch, isNotNull);
      expect(rootMatch!.group(0)!, contains('aria-label='),
          reason: 'aria-label must be present so screen readers get an '
                  'explicit description.');
    });

    test('decorative subtrees are aria-hidden', () {

      final wordmarkMatch = RegExp(
        r'<div\s+class="vaultai-loader-wordmark"[^>]*>',
      ).firstMatch(html);
      final spinnerMatch = RegExp(
        r'<div\s+class="vaultai-loader-spinner"[^>]*>',
      ).firstMatch(html);
      expect(wordmarkMatch, isNotNull);
      expect(spinnerMatch, isNotNull);
      expect(wordmarkMatch!.group(0)!, contains('aria-hidden="true"'));
      expect(spinnerMatch!.group(0)!, contains('aria-hidden="true"'));
    });

    test('prefers-reduced-motion disables the spinner animation', () {
      expect(
        RegExp(r'@media\s*\(prefers-reduced-motion:\s*reduce\)',
            caseSensitive: false).hasMatch(html),
        isTrue,
        reason:
            'The reduced-motion media query is required so users who '
            'set OS-level reduced motion do not see the spinner spin.',
      );
    });
  });


  group('Round 14 — self-removal on first frame', () {
    test('listens for the flutter-first-frame window event', () {

      final normalized = html
          .replaceAll(RegExp(r"\s+"), ' ');
      expect(
        normalized.contains("'flutter-first-frame'") ||
            normalized.contains('"flutter-first-frame"'),
        isTrue,
        reason:
            'The primary teardown signal MUST be the '
            "`flutter-first-frame` event Flutter dispatches on window.",
      );
      expect(normalized.contains('addEventListener'), isTrue,
          reason: 'Loader teardown script must wire addEventListener.');
    });

    test('MutationObserver fallback watches for the Flutter root '
         'element to appear', () {
      expect(html.contains('MutationObserver'), isTrue,
          reason:
              'A MutationObserver fallback is required so the loader '
              'is torn down as soon as the Flutter root mounts, even '
              'if the first-frame event is missed.');

      expect(html, contains('flutter-view'));
      expect(html.contains('flt-glass-pane') ||
             html.contains('flt-scene-host'),
          isTrue,
          reason:
              'Must probe at least one legacy Flutter-web root name '
              '(flt-glass-pane / flt-scene-host) for older engines.');
    });

    test('polling safety net is present so a missed event NEVER '
         'leaves the loader covering the app', () {

      expect(html.contains('setInterval'), isTrue,
          reason:
              'A setInterval-based fallback is required so a missed '
              'first-frame + MutationObserver failure combo never '
              'leaves the loader covering a working app.');
    });

    test('teardown uses opacity fade + DOM removal (not just hide)', () {

      expect(html.contains('vaultai-loader-hidden'), isTrue,
          reason: 'A hidden-state CSS class must exist so the fade '
                  'transition can play before removal.');
      expect(html.contains('removeChild'), isTrue,
          reason: 'The loader must be REMOVED from the DOM after fade — '
                  'not just hidden — so it never re-appears.');
    });

    test('no arbitrarily long fixed setTimeout is used as the primary '
         'trigger', () {

      final bigDelays = RegExp(r'setTimeout\([^,]+,\s*(\d{4,})\s*\)')
          .allMatches(html);
      for (final m in bigDelays) {

        final ms = int.parse(m.group(1)!);
        expect(ms, lessThan(10000),
            reason:
                'setTimeout ${ms}ms found — the loader must NOT use a '
                'multi-second fixed delay as its trigger. Only short '
                'fade-out delays are acceptable.');
      }
    });
  });


  group('Round 14 — self-contained (no remote assets)', () {
    test('loader block references no external URLs', () {

      final loaderBlock = html.substring(
        html.indexOf('#vaultai-startup-loader'),
        html.indexOf('vaultai-sw-bootstrap.js'),
      );


      final remoteUrls = RegExp(r'https?://')
          .allMatches(loaderBlock)
          .length;
      expect(remoteUrls, 0,
          reason:
              'The startup loader must not reference any http(s) URL. '
              'Everything must be inline so it can paint before any '
              'network fetch beyond index.html itself.');


      expect(loaderBlock.contains('@font-face'), isFalse,
          reason:
              'No @font-face is allowed in the loader block — that '
              'would require a network fetch. Use system fonts.');
    });
  });


  group('Round 14 — pre-existing contracts survive', () {
    test('title is still <title>VaultAI</title>', () {
      expect(html, contains('<title>VaultAI</title>'));
    });

    test('canonical + theme-color + OG tags all still present', () {
      expect(html,
          contains('<link rel="canonical" href="https://svaultai.com">'));
      expect(html,
          contains('<meta name="theme-color" content="#10A37F">'));
      expect(html,
          contains('property="og:title" content="VaultAI"'));
      expect(html,
          contains('property="og:image" '
                   'content="https://svaultai.com/og-image.png"'));
    });

    test('SW bootstrap tag is still SYNCHRONOUS + before Flutter '
         '(Round 12 contract preserved)', () {
      final swIdx = html.indexOf('vaultai-sw-bootstrap.js');
      final flutterIdx = html.indexOf('flutter_bootstrap.js');
      expect(swIdx, greaterThan(-1));
      expect(flutterIdx, greaterThan(-1));
      expect(swIdx < flutterIdx, isTrue,
          reason: 'SW bootstrap must load BEFORE flutter_bootstrap.js '
                  '— Round-12 lock-in.');
      final swTag = RegExp(
              r'<script[^>]*vaultai-sw-bootstrap\.js[^>]*></script>')
          .firstMatch(html);
      expect(swTag, isNotNull);
      final tagText = swTag!.group(0)!;
      expect(tagText.contains(' async'), isFalse);
      expect(tagText.contains(' defer'), isFalse);
    });

    test('OPAQUE lazy loader is wired (Round 15 — eager <script type='
         '"module"> tag replaced by vaultaiEnsureOpaqueReady)', () {


      final eagerTag = RegExp(
        r'<script[^>]*type="module"[^>]*'
        r'assets/opaque/vaultai-opaque-init\.js[^>]*></script>',
      ).firstMatch(html);
      expect(eagerTag, isNull,
          reason:
              'Round 15: the eager <script type="module" '
              'src="assets/opaque/vaultai-opaque-init.js"> tag must be '
              'GONE — OPAQUE is now loaded lazily so the ~450 KB '
              'bundle + WASM stays off the cold-start critical path.');


      expect(
        html.contains('vaultaiEnsureOpaqueReady'),
        isTrue,
        reason:
            'The lazy OPAQUE shim `vaultaiEnsureOpaqueReady` must be '
            'defined in index.html so Dart can trigger the dynamic '
            'import of the vendored ESM the moment an auth flow starts.',
      );
    });

    test('flutter_bootstrap.js tag is still async (does not block '
         'first paint)', () {
      final tag = RegExp(
        r'<script[^>]*src="flutter_bootstrap\.js"[^>]*></script>',
      ).firstMatch(html);
      expect(tag, isNotNull);
      expect(tag!.group(0)!, contains(' async'));
    });
  });
}
