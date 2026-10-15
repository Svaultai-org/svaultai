import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;

const _tokenA = 'synthetic-session-A-never-a-real-bearer';
const _tokenB = 'synthetic-session-B-never-a-real-bearer';
const _coded401 = '{"detail":{"code":"session_superseded"}}';

final _service = st.SessionTermination.instance;

VaultAIClient _client(Future<http.Response> Function(http.Request) respond) =>
    VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient(respond),
    );

void main() {
  setUp(_service.resetForTests);
  tearDown(_service.resetForTests);

  group('session-bound termination core', () {
    test('old token and old epoch cannot terminate a new login', () async {
      _service.bindSession(_tokenA);
      final old = _service.captureRequest(_tokenA);
      _service.bindSession(_tokenB);
      expect(
          await _service.handle(st.SessionTerminationCode.superseded,
              request: old),
          isFalse);
      expect(_service.isTerminated, isFalse);
      expect(
          _service.isCurrentRequest(_service.captureRequest(_tokenB)), isTrue);
      _service.bindSession(_tokenA);
      expect(_service.canUseRequest(old), isFalse,
          reason: 'Rebinding the same bearer must not resurrect prior work.');
    });

    test('reset invalidates prior work and does not reset the epoch', () {
      _service.bindSession(_tokenA);
      final old = _service.captureRequest(_tokenA);
      final epoch = _service.sessionEpoch;
      _service.reset();
      expect(_service.sessionEpoch, greaterThan(epoch));
      expect(_service.canUseRequest(old), isFalse);
      expect(_service.canUseRequest(_service.captureRequest(_tokenA)), isFalse);
    });

    test('clear invalidates retired token but a new binding works', () {
      _service.bindSession(_tokenA);
      _service.clearSession();
      expect(_service.hasBoundSession, isFalse);
      expect(_service.canUseRequest(_service.captureRequest(_tokenA)), isFalse);
      _service.bindSession(_tokenB);
      expect(_service.canUseRequest(_service.captureRequest(_tokenB)), isTrue);
    });

    test('sequential and concurrent duplicate terminations run once', () async {
      _service.bindSession(_tokenA);
      var calls = 0;
      _service.setHandler((event) async {
        expect(_service.isCurrentTermination(event), isTrue);
        calls++;
        await Future<void>.delayed(Duration.zero);
        _service.clearSession();
      });
      final results = await Future.wait(List.generate(
          8, (_) => _service.handle(st.SessionTerminationCode.superseded)));
      expect(results.where((handled) => handled), hasLength(1));
      expect(await _service.handle(st.SessionTerminationCode.expired), isFalse);
      expect(calls, 1);
      expect(_service.isTerminated, isTrue);
      _service.bindSession(_tokenB);
      expect(_service.isTerminated, isFalse);
    });

    test('old async handler cannot unlock another session cleanup', () async {
      final first = Completer<void>();
      final second = Completer<void>();
      var calls = 0;
      _service.setHandler((event) async {
        calls++;
        await (calls == 1 ? first.future : second.future);
      });
      _service.bindSession(_tokenA);
      final oldScope = _service.captureRequest(_tokenA);
      final oldHandling =
          _service.handle(st.SessionTerminationCode.expired, request: oldScope);
      _service.bindSession(_tokenB);
      final newHandling = _service.handle(st.SessionTerminationCode.superseded,
          request: _service.captureRequest(_tokenB));
      first.complete();
      await oldHandling;
      expect(await _service.handle(st.SessionTerminationCode.invalid), isFalse);
      expect(calls, 2);
      second.complete();
      await newHandling;
      expect(_service.wasTerminatedRequest(oldScope), isFalse);
    });

    test('peer fingerprint accepts only the current exact session', () async {
      _service.bindSession(_tokenA);
      final oldFingerprint =
          _service.captureRequest(_tokenA).sessionFingerprint;
      _service.bindSession(_tokenB);
      final current = _service.captureRequest(_tokenB);
      expect(
          current.sessionFingerprint, matches(RegExp(r'^[A-Za-z0-9_-]{43}$')));
      expect(current.sessionFingerprint, isNot(contains(_tokenB)));
      expect(
          await _service.handlePeerTermination(
              oldFingerprint, st.SessionTerminationCode.superseded),
          isFalse);
      expect(
          await _service.handlePeerTermination(
              current.sessionFingerprint, st.SessionTerminationCode.superseded),
          isTrue);
      expect(
          await _service.handlePeerTermination(
              current.sessionFingerprint, st.SessionTerminationCode.superseded),
          isFalse);
    });

    test('old event guard fails immediately after replacement binding',
        () async {
      st.SessionTerminationEvent? captured;
      _service.bindSession(_tokenA);
      _service.setHandler((event) async {
        captured = event;
      });
      await _service.handle(st.SessionTerminationCode.expired,
          request: _service.captureRequest(_tokenA));
      expect(_service.isCurrentTermination(captured!), isTrue);
      _service.bindSession(_tokenB);
      expect(_service.isCurrentTermination(captured!), isFalse);
    });

    test('scope, event and exceptions never print bearer or fingerprint',
        () async {
      _service.bindSession(_tokenA);
      final scope = _service.captureRequest(_tokenA);
      st.SessionTerminationEvent? event;
      _service.setHandler((value) async {
        event = value;
      });
      await _service.handle(st.SessionTerminationCode.expired, request: scope);
      final repr =
          '$scope $event ${SessionTerminatedException(code: st.SessionTerminationCode.expired, message: _tokenA, requestScope: scope)} ${const StaleSessionResponseException()}';
      expect(repr, isNot(contains(_tokenA)));
      expect(repr, isNot(contains(scope.sessionFingerprint)));
    });
  });

  group('authenticated HTTP response fencing', () {
    test('current device 403 carries proof that becomes stale after re-login',
        () async {
      _service.bindSession(_tokenA);
      final client = _client((_) async => http.Response(
          '{"detail":{"code":"device_revoked","status":"revoked"}}', 403));
      DeviceNotTrustedException? captured;
      try {
        await client.authMe(authToken: _tokenA);
      } on DeviceNotTrustedException catch (error) {
        captured = error;
      }
      expect(captured, isNotNull);
      expect(_service.isCurrentRequest(captured!.requestScope!), isTrue);
      _service.bindSession(_tokenB);
      expect(_service.isCurrentRequest(captured.requestScope!), isFalse);
      expect(_service.isTerminated, isFalse);
    });
    for (final response in [
      http.Response(_coded401, 401),
      http.Response('{"vault_id":"old-vault"}', 200),
    ]) {
      test('delayed ${response.statusCode} cannot affect newer login',
          () async {
        _service.bindSession(_tokenA);
        final started = Completer<void>();
        final pending = Completer<http.Response>();
        var cleanup = 0;
        _service.setHandler((_) async {
          cleanup++;
        });
        final client = _client((request) {
          started.complete();
          return pending.future;
        });
        final old = client.authMe(authToken: _tokenA);
        final assertion =
            expectLater(old, throwsA(isA<StaleSessionResponseException>()));
        await started.future;
        _service.bindSession(_tokenB);
        pending.complete(response);
        await assertion;
        expect(cleanup, 0);
        expect(_service.isTerminated, isFalse);
      });
    }

    test('same client concurrently keeps independent request bindings',
        () async {
      _service.bindSession(_tokenA);
      final oldStarted = Completer<void>();
      final oldPending = Completer<http.Response>();
      final client = _client((request) {
        if (request.headers['authorization'] == 'Bearer $_tokenA') {
          oldStarted.complete();
          return oldPending.future;
        }
        return Future.value(http.Response('{"vault_id":"new-vault"}', 200));
      });
      final old = client.authMe(authToken: _tokenA);
      final assertion =
          expectLater(old, throwsA(isA<StaleSessionResponseException>()));
      await oldStarted.future;
      _service.bindSession(_tokenB);
      expect(
          await client.authMe(authToken: _tokenB), {'vault_id': 'new-vault'});
      oldPending.complete(http.Response(_coded401, 401));
      await assertion;
      expect(_service.isTerminated, isFalse);
    });

    test('old 401 cannot terminate a same-token rebind', () async {
      _service.bindSession(_tokenA);
      final pending = Completer<http.Response>();
      final started = Completer<void>();
      final client = _client((_) {
        started.complete();
        return pending.future;
      });
      final assertion = expectLater(client.authMe(authToken: _tokenA),
          throwsA(isA<StaleSessionResponseException>()));
      await started.future;
      _service.reset();
      _service.bindSession(_tokenA);
      pending.complete(http.Response(_coded401, 401));
      await assertion;
      expect(_service.isTerminated, isFalse);
    });

    test('current coded authMe 401 cleans up once and new sign-in is usable',
        () async {
      _service.bindSession(_tokenA);
      var calls = 0;
      var wires = 0;
      _service.setHandler((event) async {
        expect(_service.isCurrentTermination(event), isTrue);
        calls++;
        _service.clearSession();
      });
      final client = _client((_) async {
        wires++;
        return http.Response(_coded401, 401);
      });
      await expectLater(
          client.authMe(authToken: _tokenA),
          throwsA(isA<SessionTerminatedException>()
              .having((e) => e.handledBySessionCore, 'handled', isTrue)));
      await expectLater(client.authMe(authToken: _tokenA),
          throwsA(isA<SessionTerminatedException>()));
      expect(calls, 1);
      expect(wires, 1);
      _service.bindSession(_tokenB);
      final fresh =
          _client((_) async => http.Response('{"vault_id":"new"}', 200));
      expect(await fresh.authMe(authToken: _tokenB), {'vault_id': 'new'});
    });

    test('unbound standalone coded response cannot terminate global state',
        () async {
      final client = _client((_) async => http.Response(_coded401, 401));
      await expectLater(
          client.authMe(authToken: _tokenA),
          throwsA(isA<SessionTerminatedException>()
              .having((e) => e.handledBySessionCore, 'handled', isFalse)));
      expect(_service.isTerminated, isFalse);
    });

    test('bare 401 is authorization failure, not session expiry', () async {
      _service.bindSession(_tokenA);
      final client =
          _client((_) async => http.Response('{"detail":"Unauthorized"}', 401));
      await expectLater(client.authMe(authToken: _tokenA),
          throwsA(isA<ApiAuthorizationException>()));
      expect(_service.isTerminated, isFalse);
    });

    test('invalid PIN 401 and network failure do not terminate session',
        () async {
      _service.bindSession(_tokenA);
      final invalid = _client((_) async => http.Response(
          '{"detail":{"code":"invalid_pin","message":"Incorrect PIN"}}', 401));
      await expectLater(invalid.authMe(authToken: _tokenA),
          throwsA(isA<PinInvalidException>()));
      final offline =
          _client((_) async => throw http.ClientException('Offline'));
      expect(await offline.checkSessionValidity(authToken: _tokenA),
          SessionValidity.indeterminate);
      expect(_service.isTerminated, isFalse);
    });

    test('wire headers carry no local session epoch or fingerprint', () async {
      _service.bindSession(_tokenA);
      final fingerprint = _service.captureRequest(_tokenA).sessionFingerprint;
      final client = _client((request) async {
        expect(request.headers['authorization'], 'Bearer $_tokenA');
        expect(
            request.headers.keys
                .where((k) => k.contains('epoch') || k.contains('fingerprint')),
            isEmpty);
        expect(request.headers.values, isNot(contains(fingerprint)));
        return http.Response('{"vault_id":"current"}', 200);
      });
      await client.authMe(authToken: _tokenA);
    });

    test('HTTP logs redact bearer, digest and backend diagnostic body',
        () async {
      _service.bindSession(_tokenA);
      final fingerprint = _service.captureRequest(_tokenA).sessionFingerprint;
      final logs = <String>[];
      final client = _client((_) async => http.Response(
          jsonEncode({
            'detail': {
              'code': 'session_superseded',
              'token': _tokenA,
              'vault_id': 'sensitive-internal-vault',
              'fingerprint': fingerprint
            }
          }),
          401));
      await runZoned(() async {
        await expectLater(client.authMe(authToken: _tokenA),
            throwsA(isA<SessionTerminatedException>()));
      }, zoneSpecification: ZoneSpecification(print: (_, __, ___, text) {
        logs.add(text);
      }));
      expect(logs.join('\n'), isNot(contains(_tokenA)));
      expect(logs.join('\n'), isNot(contains(fingerprint)));
      expect(logs.join('\n'), isNot(contains('sensitive-internal-vault')));
    });

    test(
        'read-only validity uses existing authMe and has neutral offline result',
        () async {
      _service.bindSession(_tokenA);
      final valid = _client((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/auth/me');
        return http.Response('{"vault_id":"current"}', 200);
      });
      expect(await valid.checkSessionValidity(authToken: _tokenA),
          SessionValidity.valid);
      final serverError = _client((_) async => http.Response('{}', 503));
      expect(await serverError.checkSessionValidity(authToken: _tokenA),
          SessionValidity.indeterminate);
      final coded = _client((_) async => http.Response(_coded401, 401));
      _service.setHandler((_) async {
        _service.clearSession();
      });
      expect(await coded.checkSessionValidity(authToken: _tokenA),
          SessionValidity.terminated);
    });

    test('validity old response returns indeterminate after newer login',
        () async {
      _service.bindSession(_tokenA);
      final pending = Completer<http.Response>();
      final started = Completer<void>();
      final client = _client((_) {
        started.complete();
        return pending.future;
      });
      final result = client.checkSessionValidity(authToken: _tokenA);
      await started.future;
      _service.bindSession(_tokenB);
      pending.complete(http.Response(_coded401, 401));
      expect(await result, SessionValidity.indeterminate);
      expect(_service.isTerminated, isFalse);
    });

    test('Apple verification still uses identical endpoint and signed body',
        () async {
      _service.bindSession(_tokenA);
      final client = _client((request) async {
        expect(request.url.path, '/billing/apple/verify-transaction');
        expect(jsonDecode(request.body),
            {'signed_transaction': 'synthetic.signed.receipt'});
        return http.Response(
            '{"verified":true,"storage_limit_bytes":53687091200}', 200);
      });
      final result = await client.verifyAppleStoragePurchase(
          authToken: _tokenA, signedTransaction: 'synthetic.signed.receipt');
      expect(result['verified'], isTrue);
    });

    test('delayed multipart success is fenced after new binding', () async {
      _service.bindSession(_tokenA);
      final pending = Completer<http.Response>();
      final started = Completer<void>();
      final client = _client((request) {
        expect(request.url.path, '/upload-file/chunk');
        started.complete();
        return pending.future;
      });
      final assertion = expectLater(
          client.uploadChunk(
              authToken: _tokenA,
              fileId: 'synthetic-file',
              chunkIndex: 0,
              uploadToken: 'synthetic-upload',
              chunkFrameBytes: Uint8List.fromList([1, 2, 3])),
          throwsA(isA<StaleSessionResponseException>()));
      await started.future;
      _service.bindSession(_tokenB);
      pending.complete(http.Response('{"ok":true}', 200));
      await assertion;
    });

    test('delayed SSE response yields no old data after new binding', () async {
      _service.bindSession(_tokenA);
      final pending = Completer<http.Response>();
      final started = Completer<void>();
      final client = _client((request) {
        expect(request.url.path, '/chat');
        started.complete();
        return pending.future;
      });
      final result = client
          .chatStream(
              encryptedMessage: 'synthetic-ciphertext',
              vaultName: 'synthetic-label',
              pin: '000000',
              authToken: _tokenA)
          .toList();
      final assertion =
          expectLater(result, throwsA(isA<StaleSessionResponseException>()));
      await started.future;
      _service.bindSession(_tokenB);
      pending.complete(http.Response('data: old-data\n\n', 200,
          headers: {'content-type': 'text/event-stream'}));
      await assertion;
    });

    test('an already-open SSE stream stops at the next chunk after re-login',
        () async {
      _service.bindSession(_tokenA);
      final bytes = StreamController<List<int>>();
      final firstChunk = Completer<void>();
      final done = Completer<void>();
      final values = <String>[];
      Object? streamError;
      final client = VaultAIClient(
          baseUrl: 'https://example.invalid',
          httpClient: MockClient.streaming((_, body) async {
            await body.drain<void>();
            return http.StreamedResponse(bytes.stream, 200,
                headers: {'content-type': 'text/event-stream'});
          }));
      final subscription = client
          .chatStream(
              encryptedMessage: 'synthetic',
              vaultName: 'synthetic',
              pin: '000000',
              authToken: _tokenA)
          .listen((value) {
        values.add(value);
        if (!firstChunk.isCompleted) firstChunk.complete();
      }, onError: (Object error) {
        streamError = error;
      }, onDone: done.complete);
      bytes.add(utf8.encode('data: first\n'));
      await firstChunk.future;
      _service.bindSession(_tokenB);
      bytes.add(utf8.encode('data: obsolete-second\n'));
      await done.future;
      await bytes.close();
      await subscription.cancel();
      expect(values, ['first']);
      expect(streamError, isA<StaleSessionResponseException>());
    });
  });
}
