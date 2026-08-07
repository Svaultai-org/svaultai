import 'dart:convert';
import 'dart:math';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/services/credential_v2.dart';
import 'package:vault_ai_frontend/services/credential_v2_api.dart';
import 'package:vault_ai_frontend/services/credential_v2_migration.dart';
import 'package:vault_ai_frontend/services/credential_v2_repository.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

CredentialV2Plaintext fixture() => const CredentialV2Plaintext(
      service: 'Example',
      username: 'qa@example.test',
      password: 'synthetic-password',
      url: 'https://example.test/login',
      notes: 'synthetic notes',
      totpSecret: 'SYNTHETIC-TOTP',
      customFields: {'account': 'synthetic-42'},
    );

Map<String, dynamic> responseFor(CredentialV2Envelope envelope) => {
      ...envelope.toRequestBody(),
      'migration_state': 'v2_written',
      'verification_state': 'not_verified',
    };

CredentialV2Crypto crypto([int seed = 42, int mvkOffset = 1]) =>
    CredentialV2Crypto(
      VaultKeyHierarchy(
        SecretKey(List<int>.generate(32, (i) => (i + mvkOffset) & 0xff)),
      ),
      randomForTest: Random(seed),
    );

CredentialV2Envelope changed(
  CredentialV2Envelope source, {
  String? recordId,
  String? nonce,
  String? ciphertext,
  String? tag,
}) =>
    CredentialV2Envelope(
      recordId: recordId ?? source.recordId,
      nonce: nonce ?? source.nonce,
      ciphertext: ciphertext ?? source.ciphertext,
      authenticationTag: tag ?? source.authenticationTag,
      blindIndexes: source.blindIndexes,
    );

String flip(String encoded) {
  final bytes = b64urlDecode(encoded);
  bytes[0] ^= 1;
  return b64urlEncode(bytes);
}

void main() {
  test('full credential payload encrypts and decrypts locally', () async {
    final service = crypto();
    final envelope = await service.encrypt(
      recordId: 'credential-1',
      plaintext: fixture(),
      serviceForLookup: 'Example',
    );
    expect((await service.decrypt(envelope)).semanticallyEquals(fixture()),
        isTrue);
    final wire = jsonEncode(envelope.toRequestBody());
    for (final secret in [
      fixture().username,
      fixture().password,
      fixture().notes!,
      fixture().totpSecret!,
      fixture().customFields['account']!,
    ]) {
      expect(wire, isNot(contains(secret)));
    }
    final wireKeys = (jsonDecode(wire) as Map<String, dynamic>).keys;
    expect(wireKeys, isNot(contains('pin')));
    expect(wireKeys, isNot(contains('mvk')));
  });

  test('nonce is unique for repeated writes of the same record', () async {
    final service = crypto();
    final first =
        await service.encrypt(recordId: 'credential-1', plaintext: fixture());
    final second =
        await service.encrypt(recordId: 'credential-1', plaintext: fixture());
    expect(first.nonce, isNot(second.nonce));
    expect(first.ciphertext, isNot(second.ciphertext));
  });

  test('blind indexes are keyed deterministic and domain separated', () async {
    final service = crypto();
    final first = await service.blindIndex('username', '  QA@Example.Test ');
    final normalized = await service.blindIndex('username', 'qa@example.test');
    final differentField =
        await service.blindIndex('service', 'qa@example.test');
    expect(first, normalized);
    expect(first, isNot(differentField));
    expect(b64urlDecode(first), hasLength(32));
    expect(() => service.blindIndex('password', 'low entropy'),
        throwsArgumentError);
  });

  group('tamper rejection', () {
    test('ciphertext, nonce and authentication tag', () async {
      final service = crypto();
      final envelope =
          await service.encrypt(recordId: 'credential-1', plaintext: fixture());
      for (final tampered in [
        changed(envelope, ciphertext: flip(envelope.ciphertext)),
        changed(envelope, nonce: flip(envelope.nonce)),
        changed(envelope, tag: flip(envelope.authenticationTag)),
      ]) {
        await expectLater(service.decrypt(tampered), throwsA(anything));
      }
    });

    test('record substitution and wrong MVK', () async {
      final service = crypto();
      final envelope =
          await service.encrypt(recordId: 'credential-1', plaintext: fixture());
      await expectLater(
        service.decrypt(changed(envelope, recordId: 'credential-2')),
        throwsA(anything),
      );
      await expectLater(crypto(99, 77).decrypt(envelope), throwsA(anything));
    });

    test('wrong version, suite and key domain fail before decryption', () {
      final envelope = CredentialV2Envelope(
        recordId: 'credential-1',
        nonce: b64urlEncode(List.filled(12, 1)),
        ciphertext: b64urlEncode([1]),
        authenticationTag: b64urlEncode(List.filled(16, 2)),
        blindIndexes: const {},
      );
      for (final mutation in [
        {'crypto_version': 'legacy_v1'},
        {'cipher_suite': 'unknown'},
        {'key_domain': 'file'},
      ]) {
        expect(
          () => CredentialV2Envelope.fromResponse({
            ...responseFor(envelope),
            ...mutation,
          }),
          throwsFormatException,
        );
      }
    });
  });

  test('API body and headers contain no PIN, MVK or content key', () async {
    late http.Request captured;
    final envelope =
        await crypto().encrypt(recordId: 'credential-1', plaintext: fixture());
    final api = CredentialV2Api(
      baseUrl: 'https://unit.test',
      sessionToken: 'session-only',
      client: MockClient((request) async {
        captured = request;
        return http.Response(jsonEncode(responseFor(envelope)), 200);
      }),
    );
    await api.write(envelope);
    final body = jsonDecode(captured.body) as Map<String, dynamic>;
    expect(body.keys, isNot(contains('pin')));
    expect(body.keys, isNot(contains('mvk')));
    expect(body.keys, isNot(contains('content_key')));
    expect(captured.body.toLowerCase(),
        isNot(contains(fixture().password.toLowerCase())));
  });

  test('create list reveal edit lookup and delete preserve service parity',
      () async {
    final stored = <String, CredentialV2Envelope>{};
    var deleted = false;
    final client = MockClient((request) async {
      final segments = request.url.pathSegments;
      final id = segments.length >= 4 ? segments[3] : null;
      if (request.method == 'PUT') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final envelope = CredentialV2Envelope.fromResponse({
          ...body,
          'migration_state': 'v2_written',
          'verification_state': 'not_verified',
        });
        stored[id!] = envelope;
        return http.Response(jsonEncode(responseFor(envelope)), 200);
      }
      if (request.method == 'GET' && id != null) {
        final envelope = stored[id]!;
        return http.Response(jsonEncode(responseFor(envelope)), 200);
      }
      if (request.method == 'GET') {
        return http.Response(
          jsonEncode(stored.values.map(responseFor).toList()),
          200,
        );
      }
      if (request.method == 'DELETE') {
        deleted = true;
        return http.Response('{}', 200);
      }
      return http.Response('{}', 404);
    });
    final service = crypto();
    final repository = CredentialV2Repository(
      crypto: service,
      api: CredentialV2Api(
        baseUrl: 'https://unit.test',
        sessionToken: 'session',
        client: client,
      ),
    );
    await repository.create(
      recordId: 'credential-1',
      credential: fixture(),
      serviceForLookup: 'Example',
    );
    expect(await repository.listRecordIds(), ['credential-1']);
    expect(
        (await repository.reveal('credential-1')).password, fixture().password);
    final edited = CredentialV2Plaintext(
      service: 'Example',
      username: fixture().username,
      password: 'edited',
      customFields: const {'x': 'y'},
    );
    await repository.edit(recordId: 'credential-1', credential: edited);
    expect((await repository.reveal('credential-1')).password, 'edited');
    expect(
        await repository.exactLookup(
            field: 'username', value: fixture().username),
        hasLength(1));
    await repository.delete('credential-1');
    expect(deleted, isTrue);
  });

  test(
      'synthetic migration verifies round trip and wrong legacy PIN stops before API',
      () async {
    final stored = <String, dynamic>{};
    var requestCount = 0;
    var verified = false;
    final client = MockClient((request) async {
      requestCount++;
      if (request.method == 'PUT') {
        stored.addAll(jsonDecode(request.body) as Map<String, dynamic>);
        return http.Response(
            jsonEncode({
              ...stored,
              'migration_state': 'v2_written',
              'verification_state': 'not_verified'
            }),
            200);
      }
      if (request.method == 'GET') {
        return http.Response(
            jsonEncode({
              ...stored,
              'migration_state': 'v2_written',
              'verification_state': 'not_verified'
            }),
            200);
      }
      if (request.url.path.endsWith('/verify')) {
        verified = true;
        return http.Response('{}', 200);
      }
      return http.Response('{}', 404);
    });
    final migrator = CredentialV2Migrator(
      crypto: crypto(),
      api: CredentialV2Api(
        baseUrl: 'https://unit.test',
        sessionToken: 'session',
        client: client,
      ),
    );
    final result = await migrator.migrateOne(
      recordId: 'credential-1',
      operationId: '11111111-1111-4111-8111-111111111111',
      decryptLegacyLocally: () async => fixture(),
    );
    expect(result.plaintext.semanticallyEquals(fixture()), isTrue);
    expect(verified, isTrue);
    final before = requestCount;
    await expectLater(
      migrator.migrateOne(
        recordId: 'credential-2',
        operationId: '22222222-2222-4222-8222-222222222222',
        decryptLegacyLocally: () async =>
            throw StateError('wrong PIN or corrupt legacy data'),
      ),
      throwsStateError,
    );
    expect(requestCount, before);
  });

  test('corrupted legacy ciphertext stops before v2 upload', () async {
    var requests = 0;
    final migrator = CredentialV2Migrator(
      crypto: crypto(),
      api: CredentialV2Api(
        baseUrl: 'https://unit.test',
        sessionToken: 'session',
        client: MockClient((request) async {
          requests++;
          return http.Response('{}', 500);
        }),
      ),
    );
    await expectLater(
      migrator.migrateOne(
        recordId: 'credential-corrupt',
        operationId: '33333333-3333-4333-8333-333333333333',
        decryptLegacyLocally: () async =>
            throw const FormatException('corrupted legacy ciphertext'),
      ),
      throwsFormatException,
    );
    expect(requests, 0);
  });

  test('interrupted upload can retry with the same operation ID', () async {
    var putAttempts = 0;
    final stored = <String, dynamic>{};
    final client = MockClient((request) async {
      if (request.method == 'PUT') {
        putAttempts++;
        if (putAttempts == 1) return http.Response('{}', 503);
        stored.addAll(jsonDecode(request.body) as Map<String, dynamic>);
        return http.Response(
          jsonEncode({
            ...stored,
            'migration_state': 'v2_written',
            'verification_state': 'not_verified'
          }),
          200,
        );
      }
      if (request.method == 'GET') {
        return http.Response(
          jsonEncode({
            ...stored,
            'migration_state': 'v2_written',
            'verification_state': 'not_verified'
          }),
          200,
        );
      }
      if (request.url.path.endsWith('/verify')) return http.Response('{}', 200);
      return http.Response('{}', 404);
    });
    final migrator = CredentialV2Migrator(
      crypto: crypto(),
      api: CredentialV2Api(
        baseUrl: 'https://unit.test',
        sessionToken: 'session',
        client: client,
      ),
    );
    Future<CredentialV2MigrationResult> run() => migrator.migrateOne(
          recordId: 'credential-retry',
          operationId: '44444444-4444-4444-8444-444444444444',
          decryptLegacyLocally: () async => fixture(),
        );
    await expectLater(run(), throwsA(anything));
    expect((await run()).plaintext.semanticallyEquals(fixture()), isTrue);
    expect(putAttempts, 2);
  });

  test('compile-time credential gates are off by default', () {
    expect(zkV2CredentialReadEnabled, isFalse);
    expect(zkV2CredentialWriteEnabled, isFalse);
    expect(zkV2CredentialMigrationEnabled, isFalse);
  });
}
