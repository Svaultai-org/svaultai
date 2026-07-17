// 2026-07-17 (Round 15 — lazy OPAQUE): regression suite for the
// dynamic-import loader that keeps the ~450 KB @serenity-kit/opaque
// ESM + WASM bundle OFF the cold-start critical path.
//
// This suite asserts three behaviours the product brief calls out:
//
//   1. OPAQUE is NOT fetched during initial startup — index.html has
//      no eager <script type="module" src="…vaultai-opaque-init.js">
//      and no eager static import of the vendored ESM.
//   2. OPAQUE is fetched when the first authentication flow begins —
//      index.html defines `vaultaiEnsureOpaqueReady()` and calls
//      `import('./assets/opaque/vaultai-opaque-init.js')` inside it.
//      The Dart-side OpaqueClient.ready() invokes that function
//      (which is what every register / login / unlock / recovery flow
//      awaits before touching the OPAQUE API).
//   3. Subsequent authentication actions reuse the same loaded module
//      — the lazy loader caches the resolving Promise on
//      `loadingPromise`, and every subsequent call returns that same
//      Promise instead of re-importing.
//
// Every file the loader touches remains inside the same-origin
// deploy, so CSP `default-src 'self'` is preserved.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _read(String rel) {
  return File('${Directory.current.path}/$rel')
      .readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {
  late String html;
  late String initModule;
  late String opaqueClientDart;

  setUpAll(() {
    html = _read('web/index.html');
    initModule = _read('web/assets/opaque/vaultai-opaque-init.js');
    opaqueClientDart = _read('lib/services/opaque_client.dart');
  });


  group('Round 15 — OPAQUE is NOT fetched during initial startup', () {
    test('index.html has no eager <script type="module" ...vaultai-'
         'opaque-init.js> tag', () {
      final eagerModuleTag = RegExp(
        r'<script[^>]*type="module"[^>]*'
        r'assets/opaque/vaultai-opaque-init\.js[^>]*></script>',
      ).firstMatch(html);
      expect(eagerModuleTag, isNull,
          reason:
              'The eager module tag was the entire reason cold starts '
              'downloaded the 428 KB serenity-kit-opaque.esm.js + WASM. '
              'Round 15 must remove it.');
    });

    test('index.html has no eager <script src=".../serenity-kit-opaque'
         '.esm.js"> tag either', () {

      final eagerBundleTag = RegExp(
        r'<script[^>]*src="[^"]*serenity-kit-opaque\.esm\.js[^"]*"'
        r'[^>]*></script>',
      ).firstMatch(html);
      expect(eagerBundleTag, isNull,
          reason:
              'The vendored ESM must never be linked eagerly — the '
              'dynamic import inside vaultaiEnsureOpaqueReady is the '
              'sole entry.');
    });

    test('the vendored WASM/ESM bundle path is only referenced from '
         'inside the lazy-loader block (not from a bare <script>)', () {

      final bareTag = RegExp(
        r'<script[^>]*src="[^"]*assets/opaque/[^"]*"[^>]*></script>',
      ).firstMatch(html);
      expect(bareTag, isNull,
          reason:
              'No <script src="assets/opaque/…"> tag may exist in '
              'index.html after Round 15. All access must go through '
              'the dynamic import inside vaultaiEnsureOpaqueReady.');
    });

    test('the OPAQUE init module still exists at the expected path — '
         'the lazy loader depends on it being fetchable', () {
      final f = File(
        '${Directory.current.path}/web/assets/opaque/vaultai-opaque-init.js',
      );
      expect(f.existsSync(), isTrue,
          reason:
              'Lazy-loading only makes sense if the file the loader '
              'points at continues to ship in the /web bundle.');
    });
  });


  group('Round 15 — OPAQUE fetches when the first auth flow begins', () {
    test('globalThis.vaultaiEnsureOpaqueReady is defined in index.html',
        () {
      expect(
        RegExp(
          r'globalThis\.vaultaiEnsureOpaqueReady\s*=\s*function',
        ).hasMatch(html),
        isTrue,
        reason:
            'The lazy entry point must be defined on globalThis as a '
            'function — Dart calls it via JS interop.',
      );
    });

    test('vaultaiEnsureOpaqueReady uses a dynamic import() of the '
         'init module (not a static <script> tag)', () {

      expect(
        RegExp(
          r"import\(\s*['\x22]\.?/?assets/opaque/vaultai-opaque-init\.js['\x22]\s*\)",
        ).hasMatch(html),
        isTrue,
        reason:
            'The loader body must call `import(\'./assets/opaque/'
            'vaultai-opaque-init.js\')` — that is the moment the bundle '
            'is fetched.',
      );
    });

    test('after the dynamic import resolves, the loader awaits '
         'globalThis.vaultaiOpaqueReady (WASM instantiation)', () {
      expect(html.contains('globalThis.vaultaiOpaqueReady'), isTrue,
          reason:
              'The init module still sets globalThis.vaultaiOpaqueReady '
              'as a top-level side effect; the loader must forward '
              'that Promise so callers only resolve once WASM is up.');
    });

    test('the init module still exposes the same globalThis shape the '
         'Dart interop expects (client + ready + vendorVersion)', () {

      expect(initModule.contains('globalThis.vaultaiOpaqueReady'), isTrue,
          reason: 'init module must publish the ready Promise');
      expect(initModule.contains('globalThis.vaultaiOpaqueClient'), isTrue,
          reason: 'init module must publish the client namespace');
      expect(
        initModule.contains('globalThis.vaultaiOpaqueVendorVersion'),
        isTrue,
        reason: 'init module must publish the vendor-version marker',
      );
    });

    test('Dart OpaqueClient.ready() prefers vaultaiEnsureOpaqueReady() '
         'over the eager vaultaiOpaqueReady global', () {


      expect(
        opaqueClientDart.contains('_vaultaiEnsureOpaqueReadyFn'),
        isTrue,
        reason:
            'opaque_client.dart must reference the ensure-function '
            'external binding so it can trigger the lazy import.',
      );


      expect(
        RegExp(r"@JS\('vaultaiEnsureOpaqueReady'\)").hasMatch(opaqueClientDart),
        isTrue,
        reason:
            'opaque_client.dart must declare a @JS binding to the '
            'lazy entry point.',
      );
      expect(
        RegExp(r'ensure\.callAsFunction\(\)').hasMatch(opaqueClientDart),
        isTrue,
        reason:
            'opaque_client.dart must actually invoke ensure() so the '
            'dynamic import is triggered on first ready() call.',
      );
    });

    test('every OPAQUE flow in the app first awaits '
         'OpaqueClient.ready() (register / login / unlock / recovery)',
        () {
      final main = _read('lib/main.dart');
      final zk = _read('lib/services/zk_auth_service.dart');


      final mainCalls =
          RegExp(r'\bOpaqueClient\.ready\(\)').allMatches(main).length;
      expect(mainCalls, greaterThanOrEqualTo(2),
          reason:
              'main.dart wires OpaqueClient.ready() before every auth '
              'flow that touches OPAQUE — that is the trigger point '
              'for the lazy import.');


      final zkCalls =
          RegExp(r'\bOpaqueClient\.ready\(\)').allMatches(zk).length;
      expect(zkCalls, greaterThanOrEqualTo(3),
          reason:
              'zk_auth_service.dart wires OpaqueClient.ready() at the '
              'top of every OPAQUE flow (register / login / rekey).');
    });
  });


  group('Round 15 — subsequent auth actions reuse the same module', () {
    test('lazy loader keeps a module-scope `loadingPromise` cache', () {


      expect(
        RegExp(r'var\s+loadingPromise\s*=\s*null;').hasMatch(html),
        isTrue,
        reason:
            'The loader must declare a module-scope cache variable '
            'named loadingPromise so subsequent calls reuse the same '
            'Promise instead of re-importing.',
      );
    });

    test('lazy loader short-circuits when the cache is populated', () {


      expect(
        RegExp(
          r'if\s*\(\s*loadingPromise\s*\)\s*return\s+loadingPromise\s*;',
        ).hasMatch(html),
        isTrue,
        reason:
            'The very first branch of vaultaiEnsureOpaqueReady must '
            'return the cached Promise if it exists — that is what '
            'makes register + login + unlock + recovery share one '
            'fetch + parse + WASM instantiation.',
      );
    });

    test('lazy loader assigns loadingPromise BEFORE returning it — '
         'so a caller that awaits the first call and a caller that '
         'awaits mid-load both see the same Promise', () {


      final loaderRegion = html.substring(
        html.indexOf('vaultaiEnsureOpaqueReady'),
        html.indexOf('flutter_bootstrap.js'),
      );
      final assignBeforeReturn = RegExp(
        r'loadingPromise\s*=\s*import\('
        r'[^)]*\)\s*'
        r'\.then\(',
        dotAll: true,
      ).hasMatch(loaderRegion);
      expect(assignBeforeReturn, isTrue,
          reason:
              'The assignment `loadingPromise = import(...).then(...)` '
              'must happen before the function returns, so concurrent '
              'callers do not each trigger a separate import.');
    });

    test('on failure, cache is dropped so retries do not stick to a '
         'stale rejection forever', () {
      expect(
        html.contains('loadingPromise = null;'),
        isTrue,
        reason:
            'The .catch handler must reset loadingPromise = null so a '
            'subsequent auth attempt gets a fresh dynamic import '
            'chance. Without this, one transient network failure '
            'would permanently break login for the rest of the tab '
            'session.',
      );
    });
  });


  group('Round 15 — pre-existing contracts still hold', () {
    test('SW bootstrap tag remains synchronous + precedes the lazy '
         'loader block AND flutter_bootstrap.js', () {

      final swIdx = html.indexOf('vaultai-sw-bootstrap.js');
      final loaderIdx = html.indexOf('vaultaiEnsureOpaqueReady');
      final flutterIdx = html.indexOf('flutter_bootstrap.js');
      expect(swIdx, greaterThan(-1));
      expect(loaderIdx, greaterThan(-1));
      expect(flutterIdx, greaterThan(-1));
      expect(swIdx < loaderIdx, isTrue,
          reason:
              'SW registration must still attach before any lazy-load '
              'shim runs.');
      expect(loaderIdx < flutterIdx, isTrue,
          reason:
              'The lazy shim is defined before flutter_bootstrap.js '
              'so Dart can safely call it as soon as auth flows fire.');
    });

    test('lazy loader block is inline (no remote URL), preserving '
         'CSP default-src \'self\'', () {

      final start = html.indexOf('vaultaiEnsureOpaqueReady');
      final end = html.indexOf('</script>', start);
      expect(start, greaterThan(-1));
      expect(end, greaterThan(start));
      final loaderRegion = html.substring(start, end);
      final remoteUrls =
          RegExp(r'https?://').allMatches(loaderRegion).length;
      expect(remoteUrls, 0,
          reason:
              'The lazy loader must be entirely inline and reference '
              'no http(s) URL — same-origin discipline is the reason '
              'CSP can stay `default-src \'self\'`.');
    });
  });
}
