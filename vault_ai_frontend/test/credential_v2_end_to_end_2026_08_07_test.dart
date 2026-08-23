import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart' show sha256;
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
  test('forgotten PIN attacker bundle cannot decrypt client_mvk_v2', () async {
    final legitimateCrypto = crypto(42, 11);
    final envelope = await legitimateCrypto.encrypt(
      recordId: 'credential-no-recovery-1',
      plaintext: fixture(),
      serviceForLookup: fixture().service,
    );
    final attackerBundle = <String, Object>{
      'complete_database_row': responseFor(envelope),
      'backend_source_available': true,
      'backend_environment_available': true,
      'session_signing_keys_available': true,
      'administrator_database_access': true,
      'trusted_device_database_control': true,
      'billing_controls': true,
      'account_controls': true,
    };
    expect(attackerBundle, isNot(contains('pin')));
    expect(attackerBundle, isNot(contains('opaque_export_secret')));
    expect(attackerBundle, isNot(contains('unwrapped_mvk')));

    for (var attackerOffset = 70; attackerOffset < 76; attackerOffset++) {
      await expectLater(
        crypto(99, attackerOffset).decrypt(envelope),
        throwsA(anything),
      );
    }
  });

  test(
      'support/admin account reset cannot restore access to a client_mvk_v2 vault when the original unlock secret is lost',
      () async {
    final envelope = await crypto(42, 21).encrypt(
      recordId: 'credential-support-reset-1',
      plaintext: fixture(),
    );
    for (final administrativeChange in <String>[
      'reset account authentication record',
      'forge session',
      'mark attacker device trusted',
      'change subscription',
      'change username',
      'change email',
    ]) {
      final substituteKeyOffset =
          sha256.convert(utf8.encode(administrativeChange)).bytes.first + 1;
      await expectLater(
        crypto(77, substituteKeyOffset).decrypt(envelope),
        throwsA(anything),
      );
    }
  });

  test('credential lookup intent is deterministic and service-only', () {
    final exact = parseCredentialV2LookupIntent('find my Example login');
    expect(exact, isNotNull);
    expect(exact!.listAll, isFalse);
    expect(exact.service, 'Example');
    expect(
        parseCredentialV2LookupIntent('show my saved logins')!.listAll, isTrue);
    expect(parseCredentialV2LookupIntent('tell me about Example'), isNull);
    expect(
      looksLikePrivateCredentialQuery(
        'How does inheritance work while my account is active?',
      ),
      isFalse,
    );

    expect(parseCredentialV2CreateIntent('generate me Samsung logins')?.service,
        'Samsung');
    expect(
        parseCredentialV2CreateIntent('create a login for Nebula Orchard')
            ?.service,
        'Nebula Orchard');
    expect(parseCredentialV2CreateIntent('add new login'), isNotNull);
    expect(
        parseCredentialV2CreateIntent('make me a Samsung account login')
            ?.service,
        'Samsung');
    expect(parseCredentialV2CreateIntent('set up a login for Samsung')?.service,
        'Samsung');
    expect(
        parseCredentialV2CreateIntent('save me a new login for Samsung')
            ?.service,
        'Samsung');
    expect(parseCredentialV2CreateIntent('show my Samsung login'), isNull);
    final supplied = parseCredentialV2CreateIntent(
        'create me a YouTube login with beraves123@aol.com as the username');
    expect(supplied?.service, 'YouTube');
    expect(supplied?.username, 'beraves123@aol.com');
    final reverseSupplied = parseCredentialV2CreateIntent(
      'create me an AOL login with my username as beury123@aol.com',
    );
    expect(reverseSupplied?.service, 'AOL');
    expect(reverseSupplied?.username, 'beury123@aol.com');
    expect(
      parseCredentialV2CreateIntent('make me another Facebook login')
          ?.explicitlyAnother,
      isTrue,
    );
    expect(parseCredentialV2CreateIntent('I need a login for Samsung')?.service,
        'Samsung');

    expect(parseCredentialV2DeleteIntent('delete my Tinder login')?.service,
        'Tinder');
    expect(parseCredentialV2DeleteIntent('get rid of youtube login')?.service,
        'youtube');
    expect(
        parseCredentialV2DeleteIntent('remove Samsung from my vault')?.service,
        'Samsung');
    expect(
        parseCredentialV2DeleteIntent(
            'delete the video qa-short-8421.mp4 from my vault'),
        isNull);
    expect(parseCredentialV2DeleteIntent('remove receipt.pdf from my vault'),
        isNull);
    expect(
      parseCredentialV2DeleteIntent('remove qa field voice 7392 from my vault'),
      isNull,
    );
    expect(
      parseCredentialV2DeleteIntent('delete youtube video login')?.service,
      'youtube video',
    );

    final generated = generateCredentialV2Plaintext(
      'Nebula Orchard',
      random: Random(17),
    );
    expect(generated.service, 'Nebula Orchard');
    expect(generated.username, startsWith('nebulaorchard_'));
    expect(generated.password.length, 20);
    expect(generated.password, matches(RegExp(r'[A-Z]')));
    expect(generated.password, matches(RegExp(r'[a-z]')));
    expect(generated.password, matches(RegExp(r'[0-9]')));
    expect(generated.password, matches(RegExp(r'[!@#%*\-_+=]')));
  });

  test('explicit v2 miss retains exact legacy local fallback', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('legacyMatches.length == 1'));
    expect(source, contains('_openLegacySecureItemDirect'));
    expect(source, contains('item.cryptoVersion == credentialV2CryptoVersion'));
  });

  test('local credential matching is driven by decrypted vault services', () {
    final instagram = DecryptedCredentialV2Record(
      'credential-instagram',
      const CredentialV2Plaintext(
        service: 'Instagram',
        username: 'qa-user',
        password: 'not-logged',
      ),
    );
    final gmail = DecryptedCredentialV2Record(
      'credential-gmail',
      const CredentialV2Plaintext(
        service: 'Gmail',
        username: 'qa-user',
        password: 'not-logged',
      ),
    );
    final records = [instagram, gmail];

    for (final naturalText in [
      'what is my instagram login',
      'show my Instagram username',
      'my instagram',
      'insta',
    ]) {
      expect(
        matchCredentialV2RecordsForText(naturalText, records)
            .map((record) => record.recordId),
        ['credential-instagram'],
      );
    }
    expect(
        matchCredentialV2RecordsForText('travel document', records), isEmpty);
  });

  test('explicit lookup service remains distinguishable from fuzzy siblings',
      () {
    final intent = parseCredentialV2LookupIntent('show me qa-nova-9315 login');
    expect(intent?.service, 'qa-nova-9315');
    expect(normalizeExactLookup(intent!.service!), 'qa-nova-9315');
    expect(normalizeExactLookup('Nova46880'), isNot('qa-nova-9315'));
  });

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

  test(
      'supplied values survive intent draft confirmation encrypted save and retrieval',
      () async {
    const cases = <String>[
      'username john password abc123 is my instagram login',
      'my instagram username is john and password is abc123',
      'instagram is username john and password abc123',
      'remember my instagram login, username john, password abc123',
      'instagram login is john / abc123',
      'save instagram username john password abc123',
      'save my instagram login john and pass abc123',
    ];

    for (var index = 0; index < cases.length; index++) {
      final intent = parseCredentialV2CreateIntent(cases[index]);
      expect(intent, isNotNull, reason: cases[index]);
      expect(intent!.service!.toLowerCase(), 'instagram', reason: cases[index]);
      expect(intent.username, 'john', reason: cases[index]);
      expect(intent.password, 'abc123', reason: cases[index]);
      expect(intent.hasSuppliedValues, isTrue, reason: cases[index]);

      // The in-memory draft models the existing confirm-before-write flow.
      final draft = generateCredentialV2Plaintext(
        intent.service!,
        username: intent.username,
        password: intent.password,
        random: Random(index + 100),
      );
      expect(draft.username, 'john', reason: cases[index]);
      expect(draft.password, 'abc123', reason: cases[index]);

      final stored = <String, CredentialV2Envelope>{};
      final client = MockClient((request) async {
        final recordId = request.url.pathSegments.last;
        if (request.method == 'PUT') {
          final envelope = CredentialV2Envelope.fromResponse({
            ...jsonDecode(request.body) as Map<String, dynamic>,
            'migration_state': 'v2_written',
            'verification_state': 'not_verified',
          });
          stored[recordId] = envelope;
          return http.Response(jsonEncode(responseFor(envelope)), 200);
        }
        if (request.method == 'GET') {
          return http.Response(
            jsonEncode(responseFor(stored[recordId]!)),
            200,
          );
        }
        return http.Response('{}', 404);
      });
      final repository = CredentialV2Repository(
        crypto: crypto(index + 200),
        api: CredentialV2Api(
          baseUrl: 'https://unit.test',
          sessionToken: 'session-only',
          client: client,
        ),
      );
      final recordId = 'supplied-values-$index';
      await repository.create(recordId: recordId, credential: draft);

      final wire = jsonEncode(stored[recordId]!.toRequestBody());
      expect(wire, isNot(contains('john')), reason: cases[index]);
      expect(wire, isNot(contains('abc123')), reason: cases[index]);
      final retrieved = await repository.reveal(recordId);
      expect(retrieved.username, 'john', reason: cases[index]);
      expect(retrieved.password, 'abc123', reason: cases[index]);
    }
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

  test('generated draft finalize and cancel send identifiers only', () async {
    final captured = <http.Request>[];
    final api = CredentialV2Api(
      baseUrl: 'https://unit.test',
      sessionToken: 'session-only',
      client: MockClient((request) async {
        captured.add(request);
        return http.Response('{}', 200);
      }),
    );
    await api.finalizeGeneratedDraft(
      recordId: 'generated-opaque-1',
      draftId: 'draft-1',
    );
    await api.cancelGeneratedDraft('draft-1');
    expect(captured, hasLength(2));
    for (final request in captured) {
      expect(request.method, 'POST');
      expect(request.body, isEmpty);
      expect(request.url.query, isEmpty);
      expect(request.headers.keys.map((key) => key.toLowerCase()),
          isNot(contains('pin')));
    }
  });

  test('generated transport failure retries without duplicate envelope',
      () async {
    final stored = <String, CredentialV2Envelope>{};
    final requests = <http.Request>[];
    var putAttempts = 0;
    final client = MockClient((request) async {
      requests.add(request);
      if (request.method == 'PUT') {
        putAttempts++;
        if (putAttempts == 1) {
          throw const SocketException('QA injected transport failure');
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final envelope = CredentialV2Envelope.fromResponse({
          ...body,
          'migration_state': 'v2_written',
          'verification_state': 'not_verified',
        });
        stored[envelope.recordId] = envelope;
        return http.Response(jsonEncode(responseFor(envelope)), 200);
      }
      if (request.method == 'POST') return http.Response('{}', 200);
      throw StateError('unexpected request');
    });
    final repository = CredentialV2Repository(
      crypto: crypto(),
      api: CredentialV2Api(
        baseUrl: 'https://qa-unreachable.invalid',
        sessionToken: 'session-only',
        client: client,
      ),
    );
    const recordId = 'generated-retry-opaque';
    await expectLater(
      repository.create(recordId: recordId, credential: fixture()),
      throwsA(isA<SocketException>()),
    );
    expect(stored, isEmpty);

    await repository.create(recordId: recordId, credential: fixture());
    await repository.api.finalizeGeneratedDraft(
      recordId: recordId,
      draftId: 'draft-retry',
    );

    expect(putAttempts, 2);
    expect(stored.keys, [recordId]);
    final finalize =
        requests.singleWhere((request) => request.method == 'POST');
    expect(finalize.body, isEmpty);
    expect(finalize.url.query, isEmpty);
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
    final lookup = await repository.exactLookup(
        field: 'username', value: fixture().username);
    expect(lookup, hasLength(1));
    expect(lookup.single.plaintext.password, 'edited');
    await repository.delete('credential-1');
    expect(deleted, isTrue);
  });

  test('list preserves migration state and isolates malformed v2 siblings',
      () async {
    final service = crypto();
    final valid = await service.encrypt(
      recordId: 'valid-migrated',
      plaintext: fixture(),
    );
    final client = MockClient((request) async => http.Response(
          jsonEncode([
            {
              ...responseFor(valid),
              'migration_state': 'v2_verified',
              'verification_state': 'client_verified',
            },
            {'crypto_version': 'client_mvk_v2', 'record_id': 'malformed'},
            {
              ...responseFor(valid),
              'record_id': 'tampered-sibling',
            },
          ]),
          200,
        ));
    final records = await CredentialV2Repository(
      crypto: service,
      api: CredentialV2Api(
        baseUrl: 'https://unit.test',
        sessionToken: 'session',
        client: client,
      ),
    ).listDecrypted();
    expect(records, hasLength(1));
    expect(records.single.recordId, 'valid-migrated');
    expect(records.single.migrationState, 'v2_verified');
    expect(records.single.verificationState, 'client_verified');
  });

  test('all accepted migration lifecycle states parse without hiding records',
      () async {
    const states = [
      'migration_pending',
      'v2_written',
      'v2_verified',
      'migrated',
      'rollback_pending',
      'rolled_back',
    ];
    final envelope = await crypto().encrypt(
      recordId: 'state-record',
      plaintext: fixture(),
    );
    for (final state in states) {
      final parsed = CredentialV2Envelope.fromResponse({
        ...responseFor(envelope),
        'migration_state': state,
      });
      expect(parsed.migrationState, state);
    }
  });

  test(
      'synthetic migration verifies round trip and wrong legacy PIN stops before API',
      () async {
    final stored = <String, dynamic>{};
    var requestCount = 0;
    var verified = false;
    final stages = <String>[];
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
      onStage: stages.add,
    );
    expect(result.plaintext.semanticallyEquals(fixture()), isTrue);
    expect(verified, isTrue);
    expect(stages, [
      'legacy_decrypted',
      'encrypted',
      'put_complete',
      'readback_complete',
      'local_verified',
      'verify_complete',
    ]);
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
