// 2026-07-14 (Round 12): regression suite for the explicit
// service-worker retirement bootstrap.
//
// Round 11 shipped a migration SW body but the production build
// (`--pwa-strategy=none`) never registered it — Flutter's own
// bootstrap issues no `.register()` in that mode. Existing users
// stuck on the pre-Round-11 offline-first SW therefore never
// received the migration. This suite locks in:
//
//   1. `web/index.html` loads `vaultai-sw-bootstrap.js`
//      SYNCHRONOUSLY (no `async`) BEFORE the async
//      `flutter_bootstrap.js`.
//   2. The bootstrap template registers
//      `/flutter_service_worker.js?v=<full-sha>` at scope `/`.
//   3. `controllerchange` reload has a per-session, per-release
//      loop guard via `sessionStorage['vaultai_sw_migration_reloaded']`.
//   4. The migration SW body remains pass-through (no `fetch`
//      handler; still calls `skipWaiting`, `clients.claim`,
//      `flutter*` cache drain, `client.navigate`).
//   5. Neither build script silently uses a 'dev' SHA — both
//      require `RELEASE_SHA` or an explicit `--allow-dev-release`
//      opt-in.
//   6. `.gitattributes` enforces LF endings on `.sh` files.
//   7. The Nginx cache contract from Round 11 is unchanged for
//      shell files, `release.json`, and the SW file.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _read(String rel) {
  return File('${Directory.current.path}/$rel')
      .readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {
  group('Round 12 — index.html loads SW bootstrap before Flutter', () {
    test('vaultai-sw-bootstrap.js precedes flutter_bootstrap.js '
         'and is SYNCHRONOUS (no async)', () {
      final html = _read('web/index.html');
      final swIdx = html.indexOf('vaultai-sw-bootstrap.js');
      final flutterIdx = html.indexOf('flutter_bootstrap.js');
      expect(swIdx, greaterThan(-1),
          reason: 'index.html must reference vaultai-sw-bootstrap.js.');
      expect(flutterIdx, greaterThan(-1));
      expect(swIdx < flutterIdx, isTrue,
          reason:
              'SW bootstrap must load BEFORE flutter_bootstrap.js.');
      final swTag = RegExp(
              r'<script[^>]*vaultai-sw-bootstrap\.js[^>]*></script>')
          .firstMatch(html);
      expect(swTag, isNotNull,
          reason: 'SW bootstrap must be a <script> tag.');
      // Synchronous: no `async` or `defer` attribute on the SW
      // bootstrap tag (Flutter's own tag is async — that's fine).
      final tagText = swTag!.group(0)!;
      expect(tagText.contains(' async'), isFalse,
          reason:
              'SW bootstrap must be SYNCHRONOUS so registration '
              'is attached before Flutter runs.');
      expect(tagText.contains(' defer'), isFalse);
    });

    test('source fallback exists so the referenced bootstrap URL is '
         'a 200 even after an accidental plain Flutter build', () {
      final fallback = File(
        '${Directory.current.path}/web/vaultai-sw-bootstrap.js',
      );
      expect(fallback.existsSync(), isTrue,
          reason:
              'index.html references /vaultai-sw-bootstrap.js; the '
              'source web/ asset must exist so plain build/web output '
              'does not deploy a 404 for that URL.');
      final js = fallback.readAsStringSync().replaceAll('\r\n', '\n');
      expect(js.contains('__VAULTAI_APP_RELEASE__'), isTrue);
      expect(
        js.contains(
          "if (RELEASE.charAt(0) === '_' && RELEASE.charAt(1) === '_')",
        ),
        isTrue,
        reason:
            'The source fallback must no-op until the release build '
            'substitutes a concrete SHA.',
      );
    });
  });

  group('Round 12 — bootstrap template contract', () {
    late String tpl;
    setUp(() {
      tpl = _read('web/vaultai-sw-bootstrap.template.js');
    });

    test('registers the exact SW script URL with query and '
         'scope="/"', () {
      expect(
        tpl.contains("'/flutter_service_worker.js?v=' + RELEASE"),
        true,
        reason:
            'SW must be registered at /flutter_service_worker.js '
            'with a `?v=<release>` query so every deploy is a '
            'distinct URL.',
      );
      expect(tpl.contains("scope: SW_SCOPE"), true);
      expect(tpl.contains("var SW_SCOPE = '/'"), true,
          reason: 'Scope must be exactly "/".');
    });

    test('short-circuits if the token was not substituted', () {
      // Extract the guard block:
      expect(
        tpl.contains(
          "if (RELEASE.charAt(0) === '_' && RELEASE.charAt(1) === '_')",
        ),
        true,
        reason:
            'Raw template (with __VAULTAI_APP_RELEASE__ literal) '
            'must never call .register(); guard clause required.',
      );
    });

    test('uses sessionStorage loop guard keyed on RELOAD_KEY = '
         '"vaultai_sw_migration_reloaded" and dedupes per '
         'RELEASE', () {
      expect(
        tpl.contains("var RELOAD_KEY = 'vaultai_sw_migration_reloaded'"),
        true,
      );
      expect(tpl.contains('sessionStorage.getItem(RELOAD_KEY)'), true);
      expect(tpl.contains('sessionStorage.setItem(RELOAD_KEY'), true);
      // The reload must be idempotent per RELEASE. Round-13 SW-loop
      // fix split the check across lines to add diag logging, so we
      // now assert the SEMANTIC (target === RELEASE guard exists)
      // instead of pinning the exact one-liner text.
      final semanticCheck = RegExp(
        r'target\s*===\s*RELEASE|readReloadedTarget\(\)\s*===\s*RELEASE',
      );
      expect(semanticCheck.hasMatch(tpl), true,
          reason: 'safeReload must compare the persisted release '
                  'target to the current RELEASE constant');
    });

    test('controllerchange handler + in-scope reloaded flag; '
         'safeReload guarded by both', () {
      // The listener may be on one or multiple lines (Round-13 added
      // diag logging inside the callback). Assert the addEventListener
      // + safeReload call are both present and wired together.
      expect(
        RegExp(r"navigator\.serviceWorker\.addEventListener\(\s*"
               r"'controllerchange'").hasMatch(tpl),
        true,
        reason: 'bootstrap must attach a controllerchange listener',
      );
      expect(tpl.contains('safeReload();'), true,
          reason: 'the controllerchange callback must call safeReload');
      expect(tpl.contains('var reloaded = false;'), true);
      // Round-13 wraps the runtime-flag check in a block so it can
      // emit a diag log; assert the guard pattern via regex.
      expect(
        RegExp(r'if\s*\(reloaded\)\s*[{\n]').hasMatch(tpl),
        true,
        reason: 'safeReload must short-circuit when `reloaded` is set',
      );
    });

    test('never touches localStorage / IndexedDB / cookies / '
         'wallet ciphertext', () {
      final commentless = tpl.split('\n')
          .where((l) => !l.trimLeft().startsWith('//'))
          .join('\n');
      expect(commentless.contains('localStorage.'), false);
      expect(commentless.contains('indexedDB.'), false);
      expect(commentless.contains('document.cookie'), false);
    });

    test('does not attempt registration when serviceWorker is '
         'not supported', () {
      expect(tpl.contains("if (!('serviceWorker' in navigator))"), true);
    });
  });

  group('Round 12 — migration SW body invariants', () {
    late String sw;
    setUp(() {
      sw = _read('scripts/migration-service-worker.js');
    });

    test('skipWaiting + clients.claim + flutter* cache drain + '
         'client.navigate remain in place', () {
      expect(sw.contains('self.skipWaiting()'), true);
      expect(sw.contains('self.clients.claim()'), true);
      expect(sw.contains("names[i].indexOf('flutter') === 0"), true);
      expect(sw.contains('.navigate('), true);
    });

    test('has NO fetch handler (pass-through)', () {
      // Look for the exact substring the SW spec matches on: a
      // `self.addEventListener('fetch', ...)` handler.
      expect(sw.contains("addEventListener('fetch'"), false,
          reason:
              'Migration SW MUST NOT install a fetch handler — '
              'pass-through only, so Nginx `no-store` shell rules '
              'take effect on every request.');
    });

    test('never touches auth / wallet / user prefs storage', () {
      final commentless = sw.split('\n')
          .where((l) => !l.trimLeft().startsWith('//'))
          .join('\n');
      expect(commentless.contains('localStorage.'), false);
      expect(commentless.contains('indexedDB.'), false);
      expect(commentless.contains('document.cookie'), false);
    });
  });

  group('Round 12 — build scripts fail-closed on dev', () {
    test('.sh script requires RELEASE_SHA or --allow-dev-release; '
         'never silently emits APP_RELEASE=dev in production', () {
      final sh = _read('scripts/build-web-release.sh');
      expect(sh.contains(r'RELEASE_SHA'), true,
          reason: 'Must accept RELEASE_SHA env var for archive '
                  'hosts.');
      expect(sh.contains('--allow-dev-release'), true,
          reason: 'Must accept explicit local-dev opt-in.');
      expect(sh.contains('cannot resolve a real 40-char commit SHA'),
          true,
          reason: 'Must fail closed with a clear diagnostic.');
      expect(sh.contains('exit 2'), true,
          reason: 'Must exit non-zero on the fail-closed path.');
      // The regex validator for the SHA:
      expect(sh.contains(r"'^[a-f0-9]{40}$'"), true,
          reason: 'Must validate the SHA as 40 hex chars.');
      // The old silent-dev fallback MUST NOT remain:
      expect(sh.contains('echo dev'), false,
          reason: 'The silent `|| echo dev` fallback that shipped '
                  'in Round 11 must not survive.');
    });

    test('.ps1 script requires RELEASE_SHA or --allow-dev-release',
        () {
      final ps1 = _read('scripts/build-web-release.ps1');
      expect(ps1.contains(r'$env:RELEASE_SHA'), true);
      expect(ps1.contains('--allow-dev-release'), true);
      expect(ps1.contains(r"'^[a-f0-9]{40}$'"), true);
      expect(ps1.contains('cannot resolve a real 40-char commit SHA'),
          true);
      expect(ps1.contains('exit 2'), true);
      // The old Round-11 silent-fallback pattern used
      //   $shaFull = 'dev'
      // reassigned via a `try/catch` around git rev-parse. Round 12
      // must not resurrect it. The `dev` sentinel string may only
      // appear inside the `--allow-dev-release` opt-in branch.
      final devIdx = ps1.indexOf("'dev");
      if (devIdx >= 0) {
        // The only allowed occurrence of a 'dev...' literal is
        // guarded by an explicit `if (allowDev)` block above it.
        final scope = ps1.substring(0, devIdx);
        expect(scope.contains(r'if ($allowDev)'), true,
            reason:
                'Any "dev" literal in build-web-release.ps1 must '
                r'be reachable only via `if ($allowDev)`. Direct '
                'silent fallback is forbidden.');
      }
    });

    test('both scripts overwrite build/web/flutter_service_worker.js '
         'with migration-service-worker.js', () {
      final sh = _read('scripts/build-web-release.sh');
      final ps1 = _read('scripts/build-web-release.ps1');
      for (final src in [sh, ps1]) {
        expect(src.contains('migration-service-worker.js'), true);
        expect(src.contains('build/web/flutter_service_worker.js'),
            true);
      }
    });

    test('both scripts substitute __VAULTAI_APP_RELEASE__ in the '
         'bootstrap template', () {
      final sh = _read('scripts/build-web-release.sh');
      final ps1 = _read('scripts/build-web-release.ps1');
      expect(sh.contains('__VAULTAI_APP_RELEASE__'), true);
      expect(ps1.contains('__VAULTAI_APP_RELEASE__'), true);
      expect(sh.contains('vaultai-sw-bootstrap.template.js'), true);
      expect(ps1.contains('vaultai-sw-bootstrap.template.js'), true);
      expect(sh.contains('build/web/vaultai-sw-bootstrap.js'), true);
      expect(ps1.contains('build/web/vaultai-sw-bootstrap.js'), true);
    });
  });

  group('Round 12 — .gitattributes LF enforcement', () {
    test('build-web-release.sh and other .sh files pinned to LF', () {
      final ga = _read('../.gitattributes');
      expect(ga.contains('*.sh'), true);
      expect(RegExp(r'\*\.sh\s+text\s+eol=lf').hasMatch(ga), true,
          reason:
              '.gitattributes MUST pin .sh files to LF so Linux '
              'shebang parsing does not break with CRLF.');
      // .ps1 stays CRLF (Windows-native):
      expect(RegExp(r'\*\.ps1\s+text\s+eol=crlf').hasMatch(ga), true);
    });

    test('build-web-release.sh on disk is already LF-encoded', () {
      final bytes = File(
        '${Directory.current.path}/scripts/build-web-release.sh',
      ).readAsBytesSync();
      final firstEol = bytes.indexOf(0x0A); // \n
      expect(firstEol, greaterThan(-1));
      // The byte immediately before the first \n must NOT be \r.
      expect(bytes[firstEol - 1], isNot(equals(0x0D)),
          reason:
              'The first line of build-web-release.sh has CRLF — '
              'production reported /usr/bin/env: bash\\r on this '
              'exact symptom. It must be LF.');
    });
  });

  group('Round 12 — Nginx cache contract unchanged', () {
    test('shell files no-store; /assets no-cache,must-revalidate; '
         'no immutable directive anywhere', () {
      final conf = _read('../deploy/nginx/app.svaultai.com.conf');
      // Every explicit Cache-Control directive:
      final headers = RegExp(
              r'add_header\s+Cache-Control\s+"([^"]+)"',
              multiLine: true)
          .allMatches(conf)
          .map((m) => m.group(1)!)
          .toList();
      expect(headers, isNotEmpty);
      for (final h in headers) {
        expect(h.contains('immutable'), false,
            reason:
                'Immutable would reintroduce the stale-cache bug. '
                'Offending: $h');
      }
      // Contains a no-store directive AND a no-cache/must-revalidate:
      expect(headers.any((h) => h.contains('no-store')), true);
      expect(
        headers.any((h) =>
            h.contains('no-cache') && h.contains('must-revalidate')),
        true,
      );
    });
  });
}
