import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/services/concierge_exposure.dart';
import 'package:vault_ai_frontend/services/pwned_password_check.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

class FixturePasswords implements PasswordExposureChecker {
  int calls = 0;
  int count = 0;
  bool fail = false;
  Completer<PasswordExposureResult>? delayed;
  @override
  Future<PasswordExposureResult> check(String password) async {
    calls++;
    if (fail) throw const PasswordExposureUnavailable();
    return delayed == null ? PasswordExposureResult(count) : delayed!.future;
  }
}

class FixtureProvider implements ConciergeExposureProvider {
  ConciergeProviderCapabilities caps = const ConciergeProviderCapabilities(
      emailRange: true, emailMonitoring: true);
  int emails = 0;
  int creates = 0;
  bool failEmail = false;
  bool failDelete = false;
  bool failList = false;
  final List<bool> stealerSelections = [];
  List<Map<String, dynamic>> rows = [];
  List<String> deleted = [];
  @override
  Future<ConciergeProviderCapabilities> capabilities(
          ConciergeAccessLease access) async =>
      caps;
  @override
  Future<ConciergeEmailExposure> checkEmail(
      String email, ConciergeAccessLease access) async {
    emails++;
    if (failEmail) throw const ConciergeUnavailable();
    return const ConciergeEmailExposure(breaches: [
      {'name': 'Example', 'title': 'Example breach'}
    ]);
  }

  @override
  Future<Map<String, dynamic>> createMonitor(String email, String sourceId,
      {required bool stealerLogs, required ConciergeAccessLease access}) async {
    creates++;
    stealerSelections.add(stealerLogs);
    final monitor = {
      'id': 'monitor_$creates',
      'source_item_id': sourceId,
      'status': 'not_checked',
      'stealer_domains': <String>[]
    };
    rows.add(monitor);
    return {'monitor': monitor};
  }

  @override
  Future<List<Map<String, dynamic>>> monitors(
      ConciergeAccessLease access) async {
    if (failList) throw const ConciergeUnavailable();
    return List.of(rows);
  }

  @override
  Future<void> deleteMonitor(String id, ConciergeAccessLease access) async {
    if (failDelete) throw const ConciergeUnavailable();
    deleted.add(id);
    rows.removeWhere((e) => e['id'] == id);
  }
}

class Harness {
  bool unlocked = true;
  int epoch = 1;
  int writes = 0;
  Map<String, dynamic>? state;
  List<ConciergeLoginRecord> records = const [
    ConciergeLoginRecord(
        id: '1',
        title: 'Example',
        password: 'unique-fixture-password!',
        email: 'owner@example.test')
  ];
  int unreadable = 0;
  final passwords = FixturePasswords();
  final provider = FixtureProvider();
  ConciergeExposureBindings get bindings => ConciergeExposureBindings(
      captureAccess: () {
        final captured = epoch;
        return ConciergeAccessLease(
            isCurrent: () => unlocked && epoch == captured);
      },
      loadLogins: (_) async =>
          ConciergeInventory(records, unreadableRecords: unreadable),
      readEncryptedState: (_) async => state,
      writeEncryptedState: (data, _) async {
        writes++;
        state = jsonDecode(jsonEncode(data));
      },
      provider: provider,
      passwordChecker: passwords);
}

void main() {
  tearDown(ZkActiveMvk.clear);

  test(
      'password request sends only five-hex prefix with padding, no token/password/full hash',
      () async {
    const secret = 'fixture-secret-never-real';
    final digest = sha1.convert(utf8.encode(secret)).toString().toUpperCase();
    final checker = PwnedPasswordChecker(client: MockClient((request) async {
      expect(request.url.toString(),
          'https://api.pwnedpasswords.com/range/${digest.substring(0, 5)}');
      expect(request.headers['Add-Padding'], 'true');
      expect(request.headers.keys.map((e) => e.toLowerCase()),
          isNot(contains('authorization')));
      expect(request.body, isEmpty);
      expect(request.url.toString(), isNot(contains(secret)));
      expect(request.url.toString(), isNot(contains(digest.substring(5))));
      return http.Response(
          '${digest.substring(5)}:42\r\n${'A' * 35}:0\r\n', 200);
    }));
    expect((await checker.check(secret)).occurrences, 42);
  });

  test('padding zero and valid missing suffix are not findings', () async {
    final checker = PwnedPasswordChecker(
        client: MockClient((_) async => http.Response('${'B' * 35}:0', 200)));
    expect((await checker.check('not-real-fixture')).found, false);
  });
  for (final response in [
    http.Response('', 200),
    http.Response('<html>not data</html>', 200),
    http.Response('short:1', 200),
    http.Response('not-found', 404),
    http.Response('limited', 429)
  ]) {
    test(
        'invalid/unavailable password response fails closed ${response.statusCode}/${response.body.length}',
        () async {
      final checker =
          PwnedPasswordChecker(client: MockClient((_) async => response));
      await expectLater(checker.check('private-fixture'),
          throwsA(isA<PasswordExposureUnavailable>()));
    });
  }

  test(
      'email proxy sends six-hex prefix only, matches/discards unrelated results locally',
      () async {
    const email = 'owner@example.test';
    final digest = sha1.convert(utf8.encode(email)).toString().toUpperCase();
    final called = <String>[];
    final provider = ConciergeBackendProvider(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture-token',
        deviceId: 'fixture-device',
        client: MockClient((request) async {
          expect(request.headers['X-Device-Id'], 'fixture-device');
          called.add(request.url.path);
          if (request.url.path.endsWith('email-range')) {
            final body = jsonDecode(request.body);
            expect(body['prefix'], digest.substring(0, 6));
            expect(request.body, isNot(contains(email)));
            expect(request.body, isNot(contains(digest.substring(6))));
            return http.Response(
                jsonEncode({
                  'status': 'checked',
                  'rows': [
                    {
                      'hashSuffix': 'F' * 34,
                      'websites': ['Unrelated']
                    },
                    {
                      'hashSuffix': digest.substring(6),
                      'websites': ['Example']
                    },
                  ]
                }),
                200);
          }
          return http.Response(
              jsonEncode({
                'status': 'checked',
                'breach': {'name': 'Example', 'title': 'Example breach'}
              }),
              200);
        }));
    final result = await provider.checkEmail(
        email, ConciergeAccessLease(isCurrent: () => true));
    expect(result.breaches.single['title'], 'Example breach');
    expect(called, ['/concierge/email-range', '/concierge/breaches/Example']);
    expect(jsonEncode(result.breaches), isNot(contains(digest)));
  });

  test('no password/email calls without global consent', () async {
    final h = Harness();
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.checkNow();
    expect(h.passwords.calls, 0);
    expect(h.provider.emails, 0);
    expect(h.writes, 0);
  });
  test(
      'only selected authorized email queried; password result linked to affected login and encrypted state is secret-free',
      () async {
    final h = Harness();
    h.passwords.count = 7;
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(
        enabled: true, approvedEmails: {'owner@example.test'}));
    await c.checkNow();
    expect(h.provider.emails, 1);
    expect(
        c.findings.map((e) => e.kind), containsAll(['pwned', 'email_breach']));
    expect(c.findings.every((e) => e.title == 'Example'), true);
    expect(jsonEncode(h.state), isNot(contains(h.records.single.password!)));
    expect(
        jsonEncode(h.state),
        isNot(contains(
            sha1.convert(utf8.encode(h.records.single.password!)).toString())));
    expect(c.lastPasswordCheckAt, isNotNull);
  });
  test(
      'local reused and short/common checks, external request deduplicated, no private-key eligibility',
      () async {
    final h = Harness();
    h.records = const [
      ConciergeLoginRecord(id: '1', title: 'One', password: '123456'),
      ConciergeLoginRecord(id: '2', title: 'Two', password: '123456')
    ];
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(enabled: true));
    await c.checkNow();
    expect(h.passwords.calls, 1);
    expect(c.findings.where((e) => e.kind == 'reused'), hasLength(2));
    expect(c.findings.where((e) => e.kind == 'weak'), hasLength(2));
  });
  test(
      'unconfigured email provider never creates a clean email check or sends emails',
      () async {
    final h = Harness();
    h.provider.caps = const ConciergeProviderCapabilities();
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(
        enabled: true, approvedEmails: {'owner@example.test'}));
    await c.checkNow();
    expect(c.emailStatus, 'provider_not_configured');
    expect(c.lastEmailCheckAt, null);
    expect(h.provider.emails, 0);
  });
  test(
      'provider outage retains prior alert and successful timestamp, not a clean result',
      () async {
    final h = Harness();
    h.passwords.count = 3;
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(enabled: true));
    await c.checkNow();
    final last = c.lastPasswordCheckAt;
    final findingTime =
        c.findings.singleWhere((e) => e.kind == 'pwned').checkedAt;
    h.passwords.fail = true;
    await c.checkNow();
    expect(c.passwordStatus, 'partial');
    expect(c.lastPasswordCheckAt, last);
    expect(c.findings.where((e) => e.kind == 'pwned'), hasLength(1));
    expect(c.findings.singleWhere((e) => e.kind == 'pwned').stale, true);
    expect(c.findings.singleWhere((e) => e.kind == 'pwned').checkedAt,
        findingTime);
  });
  test('unreadable ciphertext prevents full-clear coverage', () async {
    final h = Harness()..unreadable = 1;
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(enabled: true));
    await c.checkNow();
    expect(c.passwordStatus, 'partial');
    expect(c.lastPasswordCheckAt, null);
    expect(c.unreadableRecords, 1);
  });
  test('lock during password request cannot publish or persist result',
      () async {
    final h = Harness();
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(enabled: true));
    h.passwords.delayed = Completer();
    final before = h.writes;
    final pending = c.checkNow();
    await Future<void>.delayed(Duration.zero);
    h.unlocked = false;
    h.epoch++;
    h.passwords.delayed!.complete(const PasswordExposureResult(123));
    await pending;
    expect(c.findings, isEmpty);
    expect(c.passwordStatus, 'locked');
    expect(h.writes, before);
  });
  test('duplicate Check taps start only one run', () async {
    final h = Harness();
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(enabled: true));
    h.passwords.delayed = Completer();
    final one = c.checkNow();
    final two = c.checkNow();
    await Future<void>.delayed(Duration.zero);
    expect(h.passwords.calls, 1);
    h.passwords.delayed!.complete(const PasswordExposureResult(0));
    await Future.wait([one, two]);
  });
  test(
      'background full-email disclosure requires distinct opt-in and can be withdrawn',
      () async {
    final h = Harness();
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(
        enabled: true, approvedEmails: {'owner@example.test'}));
    expect(h.provider.creates, 0);
    await c.configure(const ConciergeConsent(
        enabled: true,
        approvedEmails: {'owner@example.test'},
        backgroundEmails: true));
    expect(h.provider.creates, 1);
    await c.configure(const ConciergeConsent());
    expect(h.provider.deleted, ['monitor_1']);
    expect(c.revocationPending, false);
  });
  test(
      'withdrawal finds orphaned monitor; failure stays pending and retry removes it',
      () async {
    final h = Harness();
    h.provider.rows = [
      {'id': 'orphan', 'source_item_id': '1'}
    ];
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    h.provider.failDelete = true;
    await c.configure(const ConciergeConsent());
    expect(c.revocationPending, true);
    expect(c.issue, contains('pending'));
    h.provider.failDelete = false;
    await c.retryRevocation();
    expect(c.revocationPending, false);
    expect(h.provider.deleted, ['orphan']);
  });

  test(
      'repository decrypts only eligible opaque logins; corrupt/private-key records are not scanned',
      () async {
    final mvk = SecretKey(List.generate(32, (i) => i));
    ZkActiveMvk.set(mvk: mvk, vaultId: 'fixture-vault', vaultHandle: 'fixture');
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> encrypted(Object value) async =>
        b64urlEncode(await aesGcmWrap(
            key, utf8.encode(value is String ? value : jsonEncode(value))));
    final rows = [
      for (final type in ['login', 'crypto_private_key'])
        {
          'item_id': type == 'login' ? 1 : 2,
          'item_type_ciphertext': await encrypted(type),
          'service_ciphertext': await encrypted('Example'),
          'payload_ciphertext': await encrypted({
            'fields': {
              'username': 'Owner@Example.test',
              'password': 'fixture-only'
            }
          }),
        },
      {'item_id': 3, 'item_type_ciphertext': 'bad'}
    ];
    final repo = ConciergeVaultRepository(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        vaultId: 'fixture-vault',
        deviceId: 'fixture-device',
        client: MockClient((request) async {
          expect(request.headers['X-Device-Id'], 'fixture-device');
          expect(request.url.path, '/vault/ciphertext/vault-items');
          expect(request.body, isEmpty);
          return http.Response(jsonEncode(rows), 200);
        }));
    final inventory =
        await repo.loadLogins(ConciergeAccessLease(isCurrent: () => true));
    expect(inventory.logins, hasLength(1));
    expect(inventory.logins.single.email, 'owner@example.test');
    expect(inventory.unreadableRecords, 1);
  });
  test(
      'dedicated state uses client ciphertext only, authenticated namespace and CAS revision',
      () async {
    final mvk = SecretKey(List.filled(32, 7));
    ZkActiveMvk.set(mvk: mvk, vaultId: 'fixture-vault', vaultHandle: 'fixture');
    Map<String, dynamic>? written;
    final repo = ConciergeVaultRepository(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        vaultId: 'fixture-vault',
        deviceId: 'fixture-device',
        client: MockClient((request) async {
          expect(request.headers['X-Device-Id'], 'fixture-device');
          expect(request.url.path, '/concierge/state');
          if (request.method == 'GET') {
            return http.Response('{"ciphertext":null,"revision":0}', 200);
          }
          written = jsonDecode(request.body);
          expect(
              written!.keys,
              containsAll(
                  ['ciphertext', 'envelope_version', 'expected_revision']));
          expect(written!['expected_revision'], 0);
          expect(request.body, isNot(contains('owner@example.test')));
          return http.Response('{"revision":1}', 200);
        }));
    final access = ConciergeAccessLease(isCurrent: () => true);
    await repo.readEncryptedState(access);
    await repo.writeEncryptedState({
      'approved_emails': ['owner@example.test']
    }, access);
    final payload = jsonDecode(utf8.decode(await aesGcmUnwrap(
        await VaultKeyHierarchy(mvk).metadataKey(),
        b64urlDecode(written!['ciphertext']))));
    expect(payload['purpose'], 'vaultai.concierge.state.v1');
    expect(payload['vault_id'], 'fixture-vault');
    expect(payload['data']['approved_emails'], ['owner@example.test']);
  });

  test('empty device ID fails closed before any authenticated request',
      () async {
    final mvk = SecretKey(List.filled(32, 1));
    ZkActiveMvk.set(mvk: mvk, vaultId: 'fixture-vault', vaultHandle: 'fixture');
    var requests = 0;
    final client = MockClient((_) async {
      requests++;
      return http.Response('{}', 200);
    });
    final access = ConciergeAccessLease(isCurrent: () => true);
    final repo = ConciergeVaultRepository(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        vaultId: 'fixture-vault',
        deviceId: '',
        client: client);
    final provider = ConciergeBackendProvider(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        deviceId: '',
        client: client);
    await expectLater(
        repo.loadLogins(access), throwsA(isA<ConciergeUnavailable>()));
    await expectLater(
        provider.capabilities(access), throwsA(isA<ConciergeUnavailable>()));
    expect(requests, 0);
  });

  test('state conflict never retries or silently overwrites a newer revision',
      () async {
    ZkActiveMvk.set(
        mvk: SecretKey(List.filled(32, 2)),
        vaultId: 'fixture-vault',
        vaultHandle: 'fixture');
    var puts = 0;
    final repo = ConciergeVaultRepository(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        vaultId: 'fixture-vault',
        deviceId: 'fixture-device',
        client: MockClient((request) async {
          if (request.method == 'GET') {
            return http.Response('{"ciphertext":null,"revision":4}', 200);
          }
          puts++;
          expect(jsonDecode(request.body)['expected_revision'], 4);
          return http.Response(
              '{"detail":{"code":"concierge_state_conflict"}}', 409);
        }));
    final access = ConciergeAccessLease(isCurrent: () => true);
    await repo.readEncryptedState(access);
    await expectLater(
        repo.writeEncryptedState({'consent': 'fixture'}, access),
        throwsA(isA<ConciergeUnavailable>()
            .having((e) => e.code, 'code', 'state_conflict')));
    expect(puts, 1);
  });

  test('state ciphertext from another vault cannot be read or overwritten',
      () async {
    final mvk = SecretKey(List.filled(32, 3));
    ZkActiveMvk.set(mvk: mvk, vaultId: 'fixture-vault', vaultHandle: 'fixture');
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    final ciphertext = b64urlEncode(await aesGcmWrap(
        key,
        utf8.encode(jsonEncode({
          'purpose': 'vaultai.concierge.state.v1',
          'vault_id': 'another-vault',
          'data': {'consent': 'private-fixture'}
        }))));
    var calls = 0;
    final repo = ConciergeVaultRepository(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        vaultId: 'fixture-vault',
        deviceId: 'fixture-device',
        client: MockClient((_) async {
          calls++;
          return http.Response(
              jsonEncode({'ciphertext': ciphertext, 'revision': 1}), 200);
        }));
    final access = ConciergeAccessLease(isCurrent: () => true);
    await expectLater(
        repo.readEncryptedState(access), throwsA(isA<ConciergeUnavailable>()));
    await expectLater(repo.writeEncryptedState({}, access),
        throwsA(isA<ConciergeUnavailable>()));
    expect(calls, 1);
  });

  test(
      'key replacement during ciphertext read drops result even with a permissive caller lease',
      () async {
    final old = SecretKey(List.filled(32, 4));
    ZkActiveMvk.set(mvk: old, vaultId: 'fixture-vault', vaultHandle: 'fixture');
    final pending = Completer<http.Response>();
    final repo = ConciergeVaultRepository(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        vaultId: 'fixture-vault',
        deviceId: 'fixture-device',
        client: MockClient((_) => pending.future));
    final result = repo.loadLogins(ConciergeAccessLease(isCurrent: () => true));
    ZkActiveMvk.set(
        mvk: SecretKey(List.filled(32, 5)),
        vaultId: 'fixture-vault',
        vaultHandle: 'fixture');
    pending.complete(http.Response('[]', 200));
    await expectLater(result, throwsA(isA<ConciergeAccessExpired>()));
  });

  test('unreadable saved state cannot enable or run checks', () async {
    final h = Harness();
    final original = h.bindings;
    final bindings = ConciergeExposureBindings(
        captureAccess: original.captureAccess,
        loadLogins: original.loadLogins,
        readEncryptedState: (_) async =>
            throw const ConciergeUnavailable('state_unreadable'),
        writeEncryptedState: original.writeEncryptedState,
        provider: h.provider,
        passwordChecker: h.passwords);
    final c = ConciergeExposureController(bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(enabled: true));
    await c.checkNow();
    expect(c.stateReady, false);
    expect(h.passwords.calls, 0);
    expect(h.provider.emails, 0);
    expect(h.writes, 0);
  });

  test('disposing a check invalidates pending completion and persistence',
      () async {
    final h = Harness();
    final c = ConciergeExposureController(h.bindings);
    await c.hydrate();
    await c.configure(const ConciergeConsent(enabled: true));
    h.passwords.delayed = Completer();
    final before = h.writes;
    final pending = c.checkNow();
    await Future<void>.delayed(Duration.zero);
    c.dispose();
    h.passwords.delayed!.complete(const PasswordExposureResult(20));
    await pending;
    expect(h.writes, before);
    expect(c.findings, isEmpty);
  });

  test('stealer opt-in queries only provider-verified domains', () async {
    final h = Harness();
    h.provider.caps = const ConciergeProviderCapabilities(
        emailRange: true,
        emailMonitoring: true,
        stealerLogs: true,
        verifiedEmailDomains: {'supported.test'});
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    await c.configure(const ConciergeConsent(
        enabled: true,
        approvedEmails: {'owner@example.test'},
        backgroundEmails: true,
        stealerLogs: true));
    expect(h.provider.stealerSelections, [false]);
  });

  test(
      'opening Concierge shows authorized background breaches with provider check time without scanning passwords',
      () async {
    final h = Harness();
    final time = DateTime.utc(2026, 10, 8);
    h.records = [
      ...h.records,
      const ConciergeLoginRecord(
          id: '2',
          title: 'Second service',
          password: 'other-fixture-secret',
          email: 'owner@example.test')
    ];
    h.state = {
      'schema': 1,
      'consent': const ConciergeConsent(
              enabled: true,
              approvedEmails: {'owner@example.test'},
              backgroundEmails: true)
          .toJson(),
      'monitor_ids': {'owner@example.test': 'monitor_1'}
    };
    h.provider.rows = [
      {
        'id': 'monitor_1',
        'source_item_id': '1',
        'status': 'found',
        'successful_at': time.toIso8601String(),
        'breaches': [
          {'title': 'Background example'}
        ],
        'stealer_domains': ['example.test']
      }
    ];
    final c = ConciergeExposureController(h.bindings);
    addTearDown(c.dispose);
    await c.hydrate();
    expect(c.findings.map((f) => f.kind),
        containsAll(['email_monitor_breach', 'stealer_domain']));
    expect(c.findings.every((f) => f.checkedAt == time && !f.stale), true);
    expect(
        c.findings
            .where((f) => f.kind == 'email_monitor_breach')
            .map((f) => f.loginId)
            .toSet(),
        {'1', '2'});
    expect(
        c.findings
            .where((f) => f.kind == 'stealer_domain')
            .map((f) => f.loginId)
            .toSet(),
        {'1', '2'});
    expect(h.passwords.calls, 0);
    expect(h.provider.emails, 0);
    h.provider.failList = true;
    await c.checkNow();
    expect(
        c.findings
            .where((f) => f.kind == 'email_monitor_breach')
            .every((f) => f.stale),
        true);
    expect(
        c.findings
            .where((f) => f.kind == 'email_monitor_breach')
            .every((f) => f.checkedAt == time),
        true);
  });

  test(
      'exact backend capability contract enables conditional stealer domains and distinguishes outages',
      () async {
    final provider = ConciergeBackendProvider(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        deviceId: 'fixture-device',
        client: MockClient((request) async {
          expect(request.headers['X-Device-Id'], 'fixture-device');
          return http.Response(
              jsonEncode({
                'enabled': true,
                'email_range': {'status': 'unavailable'},
                'email_monitoring': {'status': 'available'},
                'stealer_logs': {
                  'status': 'conditional',
                  'verified_email_domains': ['Example.Test']
                }
              }),
              200);
        }));
    final caps = await provider
        .capabilities(ConciergeAccessLease(isCurrent: () => true));
    expect(caps.emailRange, false);
    expect(caps.emailRangeStatus, 'unavailable');
    expect(caps.emailMonitoring, true);
    expect(caps.stealerLogs, true);
    expect(caps.verifiedEmailDomains, {'example.test'});
  });

  test(
      'monitor create/list/delete all carry current device and only explicit full-email disclosure',
      () async {
    final calls = <String>[];
    const monitorId = 'e9e49a89-5d44-45fd-9f4c-967a5cc436a4';
    final monitor = {
      'id': monitorId,
      'source_item_id': '1',
      'background': true,
      'stealer_logs': false,
      'status': 'found',
      'error_code': null,
      'attempted_at': '2026-10-09T00:00:00Z',
      'successful_at': '2026-10-09T00:00:01Z',
      'retry_after_seconds': null,
      'breaches': [
        {
          'name': 'Example',
          'title': 'Example breach',
          'domain': 'example.test',
          'breach_date': '2026-01-01',
          'data_classes': ['Email addresses'],
          'is_verified': true,
          'is_spam_list': false,
          'is_stealer_log': false
        }
      ],
      'stealer_domains': <String>[],
      'provider': 'hibp',
      'coverage': 'known data'
    };
    final provider = ConciergeBackendProvider(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        deviceId: 'fixture-device',
        client: MockClient((request) async {
          expect(request.headers['X-Device-Id'], 'fixture-device');
          calls.add(request.method);
          if (request.method == 'POST') {
            final body = jsonDecode(request.body);
            expect(body['email'], 'owner@example.test');
            expect(body['email_disclosure_consent'], true);
            expect(body['stealer_disclosure_consent'], false);
            return http.Response(jsonEncode(monitor), 201);
          }
          if (request.method == 'DELETE') {
            return http.Response(
                jsonEncode({'status': 'withdrawn', 'id': monitorId}), 200);
          }
          return http.Response(
              jsonEncode({
                'monitors': [monitor],
                'capabilities': {'enabled': true}
              }),
              200);
        }));
    final access = ConciergeAccessLease(isCurrent: () => true);
    final created = await provider.createMonitor('owner@example.test', '1',
        stealerLogs: false, access: access);
    expect(created['id'], monitorId);
    final rows = await provider.monitors(access);
    expect(rows.single['successful_at'], '2026-10-09T00:00:01Z');
    expect(rows.single['breaches'].single['title'], 'Example breach');
    await provider.deleteMonitor(monitorId, access);
    expect(calls, ['POST', 'GET', 'DELETE']);
  });

  test(
      'exact-ID edit preserves notes and unknown fields and never edits a duplicate title',
      () async {
    final mvk = SecretKey(List.filled(32, 10));
    ZkActiveMvk.set(mvk: mvk, vaultId: 'fixture-vault', vaultHandle: 'fixture');
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> encrypted(Object value) async =>
        b64urlEncode(await aesGcmWrap(
            key, utf8.encode(value is String ? value : jsonEncode(value))));
    final rows = [
      for (final id in [1, 2])
        {
          'item_id': id,
          'item_type_ciphertext': await encrypted('login'),
          'service_ciphertext': await encrypted('Duplicate'),
          'payload_ciphertext': await encrypted({
            'fields': {
              'password': 'old-$id',
              'notes': 'note-$id',
              'unknown': 'retain'
            },
            'source': 'fixture',
            'unknown_payload': {'retain': true}
          })
        }
    ];
    var reads = 0;
    var writes = 0;
    final repo = ConciergeVaultRepository(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        vaultId: 'fixture-vault',
        deviceId: 'fixture-device',
        client: MockClient((request) async {
          expect(request.headers['X-Device-Id'], 'fixture-device');
          if (request.method == 'GET') {
            reads++;
            return http.Response(jsonEncode(rows), 200);
          }
          writes++;
          final body = jsonDecode(request.body);
          expect(body['item_id'], 2);
          expect(body.keys, hasLength(4));
          expect(request.body, isNot(contains('new-fixture-password')));
          final payload = jsonDecode(utf8.decode(await aesGcmUnwrap(
              key, b64urlDecode(body['payload_ciphertext']))));
          expect(payload['fields'], {
            'password': 'new-fixture-password',
            'notes': 'note-2',
            'unknown': 'retain'
          });
          expect(payload['unknown_payload']['retain'], true);
          expect(payload['source'], 'fixture');
          return http.Response('{"item_id":2,"created":false}', 200);
        }));
    final access = ConciergeAccessLease(isCurrent: () => true);
    final original = await repo.loadLoginForEdit('2', access);
    expect(original.fields['password'], 'old-2');
    expect(original.toString(), isNot(contains('old-2')));
    await repo.updateLoginById(
        '2', original.title, {'password': 'new-fixture-password'}, access,
        expectedItemType: 'login');
    expect(reads, 2);
    expect(writes, 1);
  });

  test(
      'edit re-read rejects deleted IDs without recreating or posting anything',
      () async {
    ZkActiveMvk.set(
        mvk: SecretKey(List.filled(32, 11)),
        vaultId: 'fixture-vault',
        vaultHandle: 'fixture');
    var posts = 0;
    final repo = ConciergeVaultRepository(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        vaultId: 'fixture-vault',
        deviceId: 'fixture-device',
        client: MockClient((request) async {
          if (request.method == 'POST') posts++;
          return http.Response('[]', 200);
        }));
    await expectLater(
        repo.updateLoginById('2', 'Deleted', {'password': 'fixture'},
            ConciergeAccessLease(isCurrent: () => true),
            expectedItemType: 'login'),
        throwsA(isA<ConciergeUnavailable>()
            .having((e) => e.code, 'code', 'login_not_found')));
    expect(posts, 0);
  });

  test(
      'raw unsupported-domain capability is preserved, not called missing configuration',
      () async {
    final provider = ConciergeBackendProvider(
        baseUrl: 'https://example.invalid',
        authToken: 'fixture',
        deviceId: 'fixture-device',
        client: MockClient((_) async => http.Response(
            jsonEncode({
              'enabled': true,
              'email_range': {'status': 'available'},
              'email_monitoring': {'status': 'available'},
              'stealer_logs': {
                'status': 'unsupported_domain',
                'verified_email_domains': []
              }
            }),
            200)));
    final caps = await provider
        .capabilities(ConciergeAccessLease(isCurrent: () => true));
    expect(caps.stealerLogs, false);
    expect(caps.stealerStatus, 'unsupported_domain');
    expect(caps.verifiedEmailDomains, isEmpty);
  });

  test(
      'lost withdrawal response can safely retry already absent monitor, but other failures stay unavailable',
      () async {
    final access = ConciergeAccessLease(isCurrent: () => true);
    for (final code in ['monitor_not_found', 'other_error']) {
      final provider = ConciergeBackendProvider(
          baseUrl: 'https://example.invalid',
          authToken: 'fixture',
          deviceId: 'fixture-device',
          client: MockClient((_) async => http.Response(
              jsonEncode({
                'detail': {'code': code}
              }),
              404)));
      if (code == 'monitor_not_found') {
        await provider.deleteMonitor(
            'e9e49a89-5d44-45fd-9f4c-967a5cc436a4', access);
      } else {
        await expectLater(
            provider.deleteMonitor(
                'e9e49a89-5d44-45fd-9f4c-967a5cc436a4', access),
            throwsA(isA<ConciergeUnavailable>()));
      }
    }
  });
}
