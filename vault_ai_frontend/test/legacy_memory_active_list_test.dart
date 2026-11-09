import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart'
    as sessions;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart'
    as crypto;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  const token = 'synthetic-active-memory-token';
  setUp(() {
    sessions.SessionTermination.instance.resetForTests();
    sessions.SessionTermination.instance.bindSession(token);
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 47)),
      vaultId: 'synthetic-active-memory-vault',
      vaultHandle: 'synthetic-active-memory-handle',
    );
  });
  tearDown(() {
    sessions.SessionTermination.instance.resetForTests();
    ZkActiveMvk.clear();
  });

  test('active reader merges bounded pages and retains missing count',
      () async {
    final key = await crypto.VaultKeyHierarchy(ZkActiveMvk.current()!)
        .memoryKey();
    Future<String> envelope(String title) async => crypto.b64urlEncode(
      await crypto.aesGcmWrap(key, utf8.encode(jsonEncode({
        'title': title, 'value': 'Synthetic only', 'memory_type': 'note',
      }))),
    );
    final native = await envelope('Native memory');
    final first = await envelope('Prepared first');
    final second = await envelope('Prepared second');
    final requested = <String>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requested.add(request.url.toString());
        expect(request.method, 'GET');
        if (request.url.path == '/vault/ciphertext/vault-ai-memory') {
          expect(request.headers['X-SVaultAI-Memory-Active-Copy'], '1');
          return http.Response(jsonEncode([{
            'memory_id': 'native-1', 'memory_type': 'note',
            'payload_ciphertext': native,
          }]), 200);
        }
        expect(request.url.path, '/vault/memory/legacy-copy/list');
        expect(request.url.queryParameters['limit'], '20');
        if (request.url.queryParameters['after_memory_id'] == '0') {
          return http.Response(jsonEncode({
            'copies': [{
              'legacy_memory_id': 42,
              'memory_record_id': 'memory-migrated-42',
              'source_snapshot': List<String>.filled(43, 'S').join(),
              'memory_type': 'note',
              'payload_ciphertext': first,
            }],
            'unavailable_count': 19,
            'has_more': true,
            'next_after_memory_id': 61,
          }), 200);
        }
        expect(request.url.queryParameters['after_memory_id'], '61');
        return http.Response(jsonEncode({
          'copies': [{
            'legacy_memory_id': 62,
            'memory_record_id': 'memory-migrated-62',
            'source_snapshot': List<String>.filled(43, 'T').join(),
            'memory_type': 'note',
            'payload_ciphertext': second,
          }],
          'unavailable_count': 0,
          'has_more': false,
          'next_after_memory_id': 62,
        }), 200);
      }),
    );
    final inventory = await client.listZkMemories(
      authToken: token, limit: 0,
    );
    expect(requested, hasLength(3));
    expect(inventory['unavailable_count'], 19);
    expect((inventory['items'] as List).map((row) => row['id']).toList(), [
      'native-1', 'memory-migrated-42', 'memory-migrated-62',
    ]);
    expect((inventory['items'] as List)[1]['legacy_memory_id'], 42);
    expect((inventory['items'] as List)[2]['source_snapshot'],
        List<String>.filled(43, 'T').join());
  }, skip: !kEnableLegacyMemoryV2ActiveRead);

  test('active reader refuses a page that cannot advance', () async {
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        if (request.url.path == '/vault/ciphertext/vault-ai-memory') {
          return http.Response('[]', 200);
        }
        return http.Response(jsonEncode({
          'copies': [], 'unavailable_count': 20,
          'has_more': true, 'next_after_memory_id': 0,
        }), 200);
      }),
    );
    await expectLater(
      client.listZkMemories(authToken: token, limit: 0),
      throwsFormatException,
    );
  }, skip: !kEnableLegacyMemoryV2ActiveRead);
}
