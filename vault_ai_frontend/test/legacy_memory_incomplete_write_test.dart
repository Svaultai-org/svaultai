import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/memory_title_identity.dart';
import 'package:vault_ai_frontend/services/session_termination.dart'
    as sessions;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  const token = 'synthetic-memory-token';
  setUp(() {
    sessions.SessionTermination.instance.resetForTests();
    sessions.SessionTermination.instance.bindSession(token);
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 47)),
      vaultId: 'synthetic-memory-vault',
      vaultHandle: 'synthetic-memory-handle',
    );
  });
  tearDown(() {
    sessions.SessionTermination.instance.resetForTests();
    ZkActiveMvk.clear();
  });

  test('missing older copy blocks native and chat memory writes', () async {
    final paths = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        paths.add('${request.method} ${request.url.path}');
        expect(request.method, 'GET');
        if (request.url.path == '/vault/ciphertext/vault-ai-memory') {
          return http.Response('[]', 200);
        }
        expect(request.url.path, '/vault/memory/legacy-copy/list');
        return http.Response(
            jsonEncode({
              'copies': [],
              'unavailable_count': 1,
              'has_more': false,
              'next_after_memory_id': 7,
            }),
            200);
      }),
    );

    await expectLater(
      client.upsertZkMemory(
        authToken: token,
        data: {'title': 'Could be an older title', 'value': 'Synthetic only'},
      ),
      throwsA(isA<MemoryInventoryIncompleteException>()),
    );
    await expectLater(
      client.tryZkFinalizeMemoryProposal(
        baseUrl: 'https://synthetic.invalid',
        authToken: token,
        memoryType: 'note',
        memoryKey: 'Could be an older title',
        memoryValue: 'Synthetic only',
      ),
      throwsA(isA<MemoryInventoryIncompleteException>()),
    );
    expect(paths, [
      'GET /vault/ciphertext/vault-ai-memory',
      'GET /vault/memory/legacy-copy/list',
      'GET /vault/ciphertext/vault-ai-memory',
      'GET /vault/memory/legacy-copy/list',
    ]);
  }, skip: !kEnableLegacyMemoryV2ActiveRead);

  test('complete older inventory still permits a native memory write',
      () async {
    final methods = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        methods.add(request.method);
        if (request.method == 'POST') {
          expect(request.url.path, '/vault/ciphertext/vault-ai-memory');
          return http.Response('{"memory_id":"synthetic"}', 200);
        }
        if (request.url.path == '/vault/ciphertext/vault-ai-memory') {
          return http.Response('[]', 200);
        }
        expect(request.url.path, '/vault/memory/legacy-copy/list');
        return http.Response(
            jsonEncode({
              'copies': [],
              'unavailable_count': 0,
              'has_more': false,
              'next_after_memory_id': 0,
            }),
            200);
      }),
    );

    await client.upsertZkMemory(
      authToken: token,
      data: {'title': 'New synthetic memory', 'value': 'Synthetic only'},
    );
    expect(methods, ['GET', 'GET', 'POST']);
  }, skip: !kEnableLegacyMemoryV2ActiveRead);
}
