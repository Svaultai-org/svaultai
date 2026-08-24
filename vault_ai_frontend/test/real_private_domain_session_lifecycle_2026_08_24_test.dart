import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/credential_v2.dart';
import 'package:vault_ai_frontend/services/credential_v2_api.dart';
import 'package:vault_ai_frontend/services/credential_v2_repository.dart';
import 'package:vault_ai_frontend/services/file_v2_repository.dart';
import 'package:vault_ai_frontend/services/memory_v2_repository.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

class _FixtureServer {
  final tokenVault = <String, String>{};
  final memories = <String, List<Map<String, dynamic>>>{};
  final credentials = <String, List<Map<String, dynamic>>>{};
  final delays = <String, Completer<void>>{};

  String _vault(http.Request request) {
    final token = request.headers['authorization']!.substring(7);
    return tokenVault[token]!;
  }

  MockClient client() => MockClient((request) async {
        final token = request.headers['authorization']?.substring(7) ?? '';
        final delay = delays[token];
        if (delay != null) await delay.future;
        final vault = _vault(request);
        if (request.url.path == '/vault/ciphertext/vault-ai-memory') {
          if (request.method == 'POST') {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            final rows = memories.putIfAbsent(vault, () => []);
            rows.removeWhere((row) => row['memory_id'] == body['memory_id']);
            rows.add(Map<String, dynamic>.from(body));
            return http.Response(
                jsonEncode({
                  'memory_id': body['memory_id'],
                  'duplicate': false,
                }),
                200);
          }
          return http.Response(jsonEncode(memories[vault] ?? const []), 200);
        }
        if (request.url.path == '/vault/v2/credentials') {
          return http.Response(jsonEncode(credentials[vault] ?? const []), 200);
        }
        if (request.url.path.startsWith('/vault/v2/credentials/') &&
            request.method == 'PUT') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          final rows = credentials.putIfAbsent(vault, () => []);
          rows.removeWhere((row) => row['record_id'] == body['record_id']);
          final stored = <String, dynamic>{
            ...body,
            'migration_state': 'v2_written',
            'verification_state': 'not_verified',
          };
          rows.add(stored);
          return http.Response(jsonEncode(stored), 200);
        }
        return http.Response('not found', 404);
      });
}

Future<void> _installSession({
  required AppState app,
  required String token,
  required String vaultId,
  required SecretKey mvk,
}) async {
  await app.setSession(
    token: token,
    vaultIdValue: vaultId,
    vaultNameValue: 'Test $vaultId',
    vaultHandleValue: 'VLT-$vaultId',
  );
  ZkActiveMvk.set(mvk: mvk, vaultId: vaultId, vaultHandle: 'VLT-$vaultId');
}

CredentialV2Repository _credentials(
  SecretKey mvk,
  String token,
  http.Client client,
) =>
    CredentialV2Repository(
      crypto: CredentialV2Crypto(
        VaultKeyHierarchy(mvk),
        randomForTest: Random(42),
      ),
      api: CredentialV2Api(
        baseUrl: 'https://fixture.invalid',
        sessionToken: token,
        client: client,
      ),
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late _FixtureServer server;
  late SecretKey keyA;
  late SecretKey keyB;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    ZkActiveMvk.clear();
    FileV2Repository.clear();
    server = _FixtureServer()
      ..tokenVault.addAll({
        'token-a1': 'vault-a',
        'token-a2': 'vault-a',
        'token-b': 'vault-b',
      });
    keyA = SecretKey(List<int>.generate(32, (i) => i + 1));
    keyB = SecretKey(List<int>.generate(32, (i) => 255 - i));
  });

  tearDown(() {
    ZkActiveMvk.clear();
    FileV2Repository.clear();
    NativeSecureStore.useSharedPreferencesForTesting = false;
  });

  test('real clearSession recreates encrypted domain repositories', () async {
    final app = AppState();
    await _installSession(
        app: app, token: 'token-a1', vaultId: 'vault-a', mvk: keyA);
    final fileA = FileV2Repository.current()!;
    final fileFixture = await fileA.encryptMetadata(
      fileId: 'file-a',
      filename: 'juli',
      label: 'juli',
    );
    final memoryA = MemoryV2Repository(
        baseUrl: 'https://fixture.invalid', authToken: 'token-a1');
    final credentialA = _credentials(keyA, 'token-a1', server.client());

    await http.runWithClient(
      () => memoryA.create(
        memoryId: 'memory-a',
        memoryType: 'family',
        plaintext: const MemoryV2Plaintext(
          value: 'lodato kendra',
          normalized: 'mother name',
        ),
      ),
      () => server.client(),
    );
    await credentialA.create(
      recordId: 'credential-a',
      credential: const CredentialV2Plaintext(
        service: 'Facebook',
        username: 'fixture@example.test',
        password: 'fixture-secret',
      ),
      serviceForLookup: 'Facebook',
    );

    await app.clearSession();
    expect(ZkActiveMvk.current(), isNull);
    expect(FileV2Repository.current(), isNull);

    await _installSession(
        app: app, token: 'token-a2', vaultId: 'vault-a', mvk: keyA);
    final fileA2 = FileV2Repository.current()!;
    expect(identical(fileA, fileA2), isFalse);
    expect(
        (await fileA2.decryptMetadata('file-a', fileFixture)).filename, 'juli');
    final memories = await http.runWithClient(
      () => MemoryV2Repository(
        baseUrl: 'https://fixture.invalid',
        authToken: 'token-a2',
      ).listDecrypted(),
      () => server.client(),
    );
    expect(memories.single['value'], 'lodato kendra');
    final credentials =
        await _credentials(keyA, 'token-a2', server.client()).listDecrypted();
    expect(credentials.single.plaintext.service, 'Facebook');
  });

  test('hard recreation and A-B-A keep persisted ciphertext isolated',
      () async {
    var app = AppState();
    await _installSession(
        app: app, token: 'token-a1', vaultId: 'vault-a', mvk: keyA);
    await http.runWithClient(
      () => MemoryV2Repository(
        baseUrl: 'https://fixture.invalid',
        authToken: 'token-a1',
      ).create(
        memoryId: 'memory-a',
        memoryType: 'family',
        plaintext: const MemoryV2Plaintext(
          value: 'lodato kendra',
          normalized: 'mother name',
        ),
      ),
      () => server.client(),
    );
    await _credentials(keyA, 'token-a1', server.client()).create(
      recordId: 'credential-a',
      credential: const CredentialV2Plaintext(
        service: 'Facebook',
        username: 'fixture@example.test',
        password: 'fixture-secret',
      ),
      serviceForLookup: 'Facebook',
    );
    final encryptedA = await FileV2Repository.current()!.encryptMetadata(
      fileId: 'file-a',
      filename: 'juli',
    );

    // Hard-process equivalent: all process-owned state is discarded, while
    // the sanitized authoritative ciphertext fixture remains.
    await app.clearSession();
    app.dispose();
    ZkActiveMvk.clear();
    FileV2Repository.clear();
    app = AppState();
    await _installSession(
        app: app, token: 'token-a2', vaultId: 'vault-a', mvk: keyA);
    expect(
      (await FileV2Repository.current()!.decryptMetadata('file-a', encryptedA))
          .filename,
      'juli',
    );
    expect(
      (await http.runWithClient(
        () => MemoryV2Repository(
          baseUrl: 'https://fixture.invalid',
          authToken: 'token-a2',
        ).listDecrypted(),
        () => server.client(),
      ))
          .single['value'],
      'lodato kendra',
    );
    expect(
      (await _credentials(keyA, 'token-a2', server.client()).listDecrypted())
          .single
          .plaintext
          .service,
      'Facebook',
    );

    await app.clearSession(keepLastVaultName: false);
    await _installSession(
        app: app, token: 'token-b', vaultId: 'vault-b', mvk: keyB);
    expect(
      await http.runWithClient(
        () => MemoryV2Repository(
          baseUrl: 'https://fixture.invalid',
          authToken: 'token-b',
        ).listDecrypted(),
        () => server.client(),
      ),
      isEmpty,
    );
    expect(
      await _credentials(keyB, 'token-b', server.client()).listDecrypted(),
      isEmpty,
    );
    final repoB = FileV2Repository.current()!;
    await expectLater(
      repoB.decryptMetadata('file-a', encryptedA),
      throwsA(anything),
    );

    await app.clearSession(keepLastVaultName: false);
    await _installSession(
        app: app, token: 'token-a2', vaultId: 'vault-a', mvk: keyA);
    expect(
      (await FileV2Repository.current()!.decryptMetadata('file-a', encryptedA))
          .filename,
      'juli',
    );
    expect(
      (await http.runWithClient(
        () => MemoryV2Repository(
          baseUrl: 'https://fixture.invalid',
          authToken: 'token-a2',
        ).listDecrypted(),
        () => server.client(),
      ))
          .single['value'],
      'lodato kendra',
    );
    expect(
      (await _credentials(keyA, 'token-a2', server.client()).listDecrypted())
          .single
          .plaintext
          .service,
      'Facebook',
    );
  });

  test('late completion from session A is rejected after session B login',
      () async {
    final app = AppState();
    await _installSession(
        app: app, token: 'token-a1', vaultId: 'vault-a', mvk: keyA);
    final epochA = app.sessionEpoch;
    final delayed = Completer<void>();
    server.delays['token-a1'] = delayed;
    final pending = http.runWithClient(
      () => MemoryV2Repository(
        baseUrl: 'https://fixture.invalid',
        authToken: 'token-a1',
      ).listDecrypted(),
      () => server.client(),
    );

    await app.clearSession(keepLastVaultName: false);
    await _installSession(
        app: app, token: 'token-b', vaultId: 'vault-b', mvk: keyB);
    delayed.complete();
    await pending;
    expect(
      app.ownsSessionLoad(
        epoch: epochA,
        vaultIdValue: 'vault-a',
        tokenValue: 'token-a1',
      ),
      isFalse,
    );
    expect(
      app.ownsSessionLoad(
        epoch: app.sessionEpoch,
        vaultIdValue: 'vault-b',
        tokenValue: 'token-b',
      ),
      isTrue,
    );
  });
}
