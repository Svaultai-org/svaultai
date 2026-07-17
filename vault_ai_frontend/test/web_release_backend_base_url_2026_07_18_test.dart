// 2026-07-18 (production black-screen fix): regression suite for the
// startup crash reproduced on commits 0875667..dc781d3..698c4b8.
//
// SYMPTOM
//   The web release built by `flutter build web --release` with no
//   `--dart-define=BACKEND_BASE_URL=...` override crashed at startup
//   with an uncaught StateError before `runApp` was called. Browser
//   console showed a bare minified stack:
//
//     Object.d (main.dart.js:3875:20)         ← Dart throwException
//     main.dart.js:35957:15                    ← the actual throw
//     bpt.a (main.dart.js:5247:63)             ← zone-guard trampoline
//     bpt.$2 (main.dart.js:54894:14)
//
//   Line 35957 minified to the compiled form of the release-HTTPS
//   guard at main.dart:648-654:
//
//     if (kReleaseMode && !backendBaseUrl.startsWith('https://')) {
//       throw StateError('BACKEND_BASE_URL must use https:// ...');
//     }
//
// ROOT CAUSE
//   The `backendBaseUrl` getter (main.dart:125-129) branched on
//   `kReleaseMode && !kIsWeb` to return the production API host,
//   leaving web release with `String.fromEnvironment('BACKEND_BASE_URL',
//   defaultValue: 'http://localhost:8000')` — which fails the HTTPS
//   guard, which throws, which is uncaught (the guard runs BEFORE
//   `runZonedGuarded`), which yields the black screen.
//
// FIX
//   Drop the `&& !kIsWeb` gate: web release ALSO uses the production
//   API host by default. Both platforms hit the same FastAPI service
//   today. If they ever need to diverge, introduce a separate
//   `_kWebProductionBaseUrl` constant — do NOT reintroduce a
//   `!kIsWeb` gate that leaves web release resolving to localhost.
//
// This suite pins the fix at the source level. It cannot exercise the
// getter directly under the VM (there `kReleaseMode == false` and
// `kIsWeb == false`, so the fallback branch always runs), so it uses
// source-level assertions that are compile-time-equivalent to the
// runtime behaviour.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _readMain() {
  return File('${Directory.current.path}/lib/main.dart')
      .readAsStringSync()
      .replaceAll('\r\n', '\n');
}

/// Extracts the body of the `String get backendBaseUrl { ... }` block
/// so the regression assertions can look at the getter in isolation
/// without matching similarly-named strings elsewhere in main.dart.
String _getterBody(String src) {
  final anchor = 'String get backendBaseUrl';
  final start = src.indexOf(anchor);
  expect(start, greaterThan(-1),
      reason:
          'main.dart must expose a top-level `String get backendBaseUrl`. '
          'If the shape changed, update this test to match the new API.');
  final openBrace = src.indexOf('{', start);
  expect(openBrace, greaterThan(start));

  var depth = 0;
  var i = openBrace;
  for (; i < src.length; i++) {
    final ch = src[i];
    if (ch == '{') depth++;
    if (ch == '}') {
      depth--;
      if (depth == 0) {
        i++;
        break;
      }
    }
  }
  return src.substring(start, i);
}

void main() {
  group('backendBaseUrl web-release regression (2026-07-18)', () {
    late String src;
    late String getterBody;

    setUpAll(() {
      src = _readMain();
      getterBody = _getterBody(src);
    });

    test('release-mode branch does NOT gate on `!kIsWeb` — that gate '
         'is exactly the bug that caused the production black screen', () {
      final withoutComments = getterBody
          .split('\n')
          .where((l) => !l.trimLeft().startsWith('//'))
          .join('\n');
      expect(
        withoutComments.contains('kReleaseMode && !kIsWeb'),
        isFalse,
        reason:
            'The `kReleaseMode && !kIsWeb` guard in backendBaseUrl was the '
            'root cause of the app.svaultai.com startup crash: on web '
            'release with no --dart-define=BACKEND_BASE_URL override, it '
            'fell through to the localhost dev fallback, which failed '
            'the release-HTTPS guard in main() and threw an uncaught '
            'StateError before runApp. Do NOT reintroduce this gate.',
      );
    });

    test('release-mode branch returns the production API host', () {
      final withoutComments = getterBody
          .split('\n')
          .where((l) => !l.trimLeft().startsWith('//'))
          .join('\n');
      expect(
        RegExp(r'if\s*\(\s*kReleaseMode\s*\)\s*return\s+_k[A-Za-z]+;')
            .hasMatch(withoutComments),
        isTrue,
        reason:
            'The release-mode branch must return a production constant '
            'unconditionally so both `flutter build web --release` and '
            '`flutter build appbundle --release` end up talking to '
            'https://api.svaultai.com by default.',
      );
    });

    test('production API host constant is `https://api.svaultai.com`', () {
      expect(
        RegExp(r"_kProductionApiBaseUrl\s*=\s*'https://api\.svaultai\.com'")
            .hasMatch(src),
        isTrue,
        reason:
            'The production API host constant used by both platforms '
            'must remain https://api.svaultai.com.',
      );
    });

    test('the compile-time override branch still wins (staging / CI can '
         'still redirect BACKEND_BASE_URL)', () {

      expect(
        getterBody.contains('_kHasBackendBaseUrlOverride'),
        isTrue,
        reason:
            'The `--dart-define=BACKEND_BASE_URL=...` escape hatch is '
            'still needed for staging + preview builds. It must be '
            'checked BEFORE the release-mode default.',
      );
      final overrideIdx =
          getterBody.indexOf('_kHasBackendBaseUrlOverride');
      final releaseIdx = getterBody.indexOf('kReleaseMode');
      expect(overrideIdx, lessThan(releaseIdx),
          reason:
              'The override check must come first — otherwise a '
              'BACKEND_BASE_URL=https://staging.example.com override '
              'would be silently ignored on release builds.');
    });

    test('dev fallback still lands on http://localhost:8000 so '
         '`flutter run` on VM/debug keeps working without --dart-define',
        () {
      expect(
        src.contains("defaultValue: 'http://localhost:8000'"),
        isTrue,
        reason:
            'Dev builds must still resolve to http://localhost:8000 '
            'so contributors do not have to pass --dart-define '
            'locally.',
      );
    });
  });

  group('regression source-pin: the release-HTTPS guard at the top of '
        'main() cannot become unreachable', () {
    late String src;
    setUpAll(() {
      src = _readMain();
    });

    test('main.dart still has the guard `if (kReleaseMode && '
         '!backendBaseUrl.startsWith(...))`', () {
      expect(
        src.contains("!backendBaseUrl.startsWith('https://')"),
        isTrue,
        reason:
            'The startup-time HTTPS guard is what prevents an '
            'accidentally-misconfigured release from shipping auth '
            'tokens in plaintext. Keep it.',
      );
    });

    test('the guard runs BEFORE `runZonedGuarded(...)` so an override '
         'error surfaces as a clear StateError, not a silent '
         'network failure', () {
      final guardIdx =
          src.indexOf("!backendBaseUrl.startsWith('https://')");
      final zoneIdx = src.indexOf('runZonedGuarded');
      expect(guardIdx, greaterThan(-1));
      expect(zoneIdx, greaterThan(-1));
      expect(guardIdx, lessThan(zoneIdx),
          reason:
              'The HTTPS guard must run before the zoned-guard so an '
              'accidental misconfiguration is caught with a clear '
              'diagnostic instead of an anonymous minified exception.');
    });
  });
}
