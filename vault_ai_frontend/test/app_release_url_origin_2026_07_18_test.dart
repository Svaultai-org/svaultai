// 2026-07-18 (release-URL fix): the AppReleaseController used to
// build its `/release.json` URL against `backendBaseUrl`, which on
// the deployed VaultAI web app resolves to https://api.svaultai.com
// — the FastAPI backend host. That host does NOT serve
// `/release.json`; the manifest is emitted into `build/web/` by the
// canonical release-build script and served from the frontend origin
// https://app.svaultai.com by nginx.
//
// The Round-15 wiring change in main.dart now passes
//   `baseUrl: kIsWeb ? Uri.base.origin : backendBaseUrl`
// so:
//   * on web    → releases resolve against the current app origin,
//                 e.g. https://app.svaultai.com/release.json
//   * on mobile → releases resolve against the API host, because
//                 mobile does not have an app-origin concept and the
//                 backend team can proxy /release.json later without
//                 changing this file.
//
// This suite proves the behavioural + source-level contracts of that
// fix, plus a regression pin that the controller never issues a
// request to the API host on web ever again.

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:vault_ai_frontend/services/app_release_controller.dart';

String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel')
      .readAsStringSync()
      .replaceAll('\r\n', '\n');
}

class _Recorder {
  final List<Uri> requestedUris = <Uri>[];
}

AppReleaseController _controller({
  required String baseUrl,
  required String serverCommit,
  required _Recorder rec,
  String runningRelease = 'aaaaaaaa11111111aaaaaaaa11111111aaaaaaaa',
}) {
  final mock = MockClient((req) async {
    rec.requestedUris.add(req.url);
    return http.Response(
      jsonEncode({'commit': serverCommit, 'builtAt': 'x'}),
      200,
    );
  });
  return AppReleaseController(
    baseUrl: baseUrl,
    runningRelease: runningRelease,
    httpClient: mock,
    unregisterServiceWorker: () async {},
    clearAppCodeCacheEntries: () async {},
    reloadPage: () {},
    readLastAttemptedTarget: () => null,
    writeLastAttemptedTarget: (_) {},
  );
}

void main() {
  group('release-URL fix — behavioural', () {
    test(
        'web: given baseUrl = Uri.base.origin (app.svaultai.com), '
        'the controller GETs https://app.svaultai.com/release.json '
        '— NOT https://api.svaultai.com/release.json', () async {
      final rec = _Recorder();
      final ctl = _controller(
        baseUrl: 'https://app.svaultai.com',
        serverCommit: 'bbbbbbbb22222222bbbbbbbb22222222bbbbbbbb',
        rec: rec,
      );
      await ctl.checkForUpdate();

      expect(rec.requestedUris, hasLength(1),
          reason: 'exactly one release.json fetch per checkForUpdate');
      final uri = rec.requestedUris.single;

      expect(uri.scheme, 'https');
      expect(uri.host, 'app.svaultai.com',
          reason: 'On web, the release manifest must be resolved against '
              'the frontend origin (app.svaultai.com). Talking to the '
              'API host would 404 forever and keep '
              '`updateAvailable=false` even after a real deploy.');
      expect(uri.path, '/release.json');

      expect(uri.host, isNot(equals('api.svaultai.com')),
          reason: 'REGRESSION GUARD: the pre-fix code sent this request to '
              'api.svaultai.com, which does not host /release.json.');
    });

    test(
        'non-web: given baseUrl = backendBaseUrl (the FastAPI '
        'host), the controller keeps using that host — the mobile '
        'path is unchanged', () async {
      final rec = _Recorder();
      final ctl = _controller(
        baseUrl: 'https://api.svaultai.com',
        serverCommit: 'cccccccc33333333cccccccc33333333cccccccc',
        rec: rec,
      );
      await ctl.checkForUpdate();

      expect(rec.requestedUris, hasLength(1));
      final uri = rec.requestedUris.single;
      expect(uri.host, 'api.svaultai.com',
          reason: 'Mobile / desktop must keep talking to backendBaseUrl. '
              'Uri.base.origin is meaningless off-web, so main.dart '
              'gates the switch on kIsWeb.');
      expect(uri.path, '/release.json');
    });

    test(
        'web: same-origin resolution works on any dev host, not just '
        'the production app origin', () async {
      for (final origin in [
        'http://localhost:8080',
        'https://staging.svaultai.com',
        'https://preview-123.pages.dev',
      ]) {
        final rec = _Recorder();
        final ctl = _controller(
          baseUrl: origin,
          serverCommit: 'dddddddd44444444dddddddd44444444dddddddd',
          rec: rec,
        );
        await ctl.checkForUpdate();

        expect(rec.requestedUris, hasLength(1),
            reason: 'origin=$origin should have issued exactly '
                'one fetch');
        final uri = rec.requestedUris.single;
        expect(uri.origin, origin,
            reason: 'origin=$origin — release.json must be served '
                'from the same origin as the app itself');
        expect(uri.path, '/release.json');
      }
    });

    test(
        'web: the controller keeps its cache-busting query + no-'
        'cache request headers after the origin change', () async {
      final rec = _Recorder();
      final ctl = _controller(
        baseUrl: 'https://app.svaultai.com',
        serverCommit: 'eeeeeeee55555555eeeeeeee55555555eeeeeeee',
        rec: rec,
      );
      await ctl.checkForUpdate();

      final uri = rec.requestedUris.single;

      expect(uri.queryParameters.containsKey('ts'), isTrue,
          reason: 'The Round-10 cache-busting `?ts=<microseconds>` query '
              'must survive the origin refactor.');
      expect(int.tryParse(uri.queryParameters['ts']!), isNotNull,
          reason: 'ts must be a numeric timestamp.');
    });
  });

  group('release-URL fix — source-level pins', () {
    test(
        'main.dart wires the scope with kIsWeb ? Uri.base.origin '
        ': backendBaseUrl', () {
      final src = _readLib('main.dart');
      expect(
        RegExp(r'baseUrl:\s*kIsWeb\s*\?\s*Uri\.base\.origin\s*'
                r':\s*backendBaseUrl')
            .hasMatch(src),
        isTrue,
        reason: 'The release scope must be wired to prefer the frontend '
            'origin on web. Any regression to `baseUrl: backendBaseUrl` '
            'reintroduces the api.svaultai.com/release.json 404 bug.',
      );
    });

    test(
        'main.dart no longer wires the release scope with the '
        'raw backendBaseUrl (regression guard)', () {
      final src = _readLib('main.dart');


      final startIdx = src.indexOf('AppReleaseControllerScope(');
      final endIdx = src.indexOf('child: VaultaiApp', startIdx);
      expect(startIdx, greaterThan(-1),
          reason: 'expected AppReleaseControllerScope( in main.dart');
      expect(endIdx, greaterThan(startIdx),
          reason: 'expected child: VaultaiApp AFTER the scope opens');
      final block = src.substring(startIdx, endIdx);


      expect(
        RegExp(r'baseUrl:\s*backendBaseUrl\s*,').hasMatch(block),
        isFalse,
        reason: 'REGRESSION GUARD: the release scope must never revert '
            'to `baseUrl: backendBaseUrl` — that resolves to '
            'https://api.svaultai.com on web and the FastAPI host '
            'does not serve /release.json.',
      );
    });

    test(
        'the controller URL construction remains `<baseUrl>/'
        'release.json?ts=…` — a change here would silently redirect '
        'the fix', () {
      final ctl = _readLib('services/app_release_controller.dart');
      expect(
        ctl.contains(r"Uri.parse('$baseUrl/release.json?ts=$ts')"),
        isTrue,
        reason: 'AppReleaseController.checkForUpdate() must build the '
            'URL exactly as `<baseUrl>/release.json?ts=<ts>` so the '
            'origin fix in main.dart takes effect verbatim.',
      );
    });
  });
}
