import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

const _base = 'https://synthetic.invalid';
const _token = 'synthetic-memory-session';
const _secretMarker = 'synthetic-private-memory-value';

void _bindPrivateVault() {
  st.SessionTermination.instance.bindSession(_token);
  PrivateZkPinTransportSession.bind(_token);
  ZkActiveMvk.set(
    mvk: SecretKey(List<int>.generate(32, (index) => index + 1)),
    vaultId: 'synthetic-vault',
    vaultHandle: 'synthetic-handle',
  );
}

void main() {
  setUp(() {
    st.SessionTermination.instance.reset();
    PrivateZkPinTransportSession.clear();
    ZkActiveMvk.clear();
    setApiClientDeviceId('synthetic-memory-device');
  });
  tearDown(() {
    st.SessionTermination.instance.reset();
    PrivateZkPinTransportSession.clear();
    ZkActiveMvk.clear();
    setApiClientDeviceId('');
  });

  test('private save uses ciphertext POST and decrypts filtered readback',
      () async {
    _bindPrivateVault();
    final methods = <String>[];
    Map<String, dynamic>? stored;
    final client = VaultAIClient(
      baseUrl: _base,
      httpClient: MockClient((request) async {
        methods.add(request.method);
        expect(request.headers['authorization'], 'Bearer $_token');
        expect(request.headers['x-device-id'], 'synthetic-memory-device');
        expect(request.url.path, '/vault/ciphertext/vault-ai-memory');
        if (request.method == 'POST') {
          expect(request.body, isNot(contains(_secretMarker)));
          expect(request.body.toLowerCase(), isNot(contains('"pin"')));
          stored = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response('{"memory_id":"1","duplicate":false}', 200);
        }
        if (request.url.queryParameters.containsKey('memory_lookup_hash')) {
          expect(request.url.queryParameters['memory_lookup_hash'],
              stored?['memory_lookup_hash']);
        }
        return http.Response(jsonEncode([
          if (stored != null) stored,
        ]), 200);
      }),
    );
    await client.upsertZkMemory(
      authToken: _token,
      data: const <String, dynamic>{
        'title': 'Synthetic memory',
        'memory_type': 'note',
        'value': _secretMarker,
      },
    );
    expect(methods, ['GET', 'POST', 'GET']);
    expect(stored?['payload_ciphertext'], isA<String>());
    expect(stored, isNot(contains('pin')));
  }, skip: !kEnableZkPrivateOnlyUnlock);

  test('private save with missing readback fails and same-record retry succeeds',
      () async {
    _bindPrivateVault();
    Map<String, dynamic>? stored;
    var filteredReads = 0;
    var writes = 0;
    final client = VaultAIClient(
      baseUrl: _base,
      httpClient: MockClient((request) async {
        if (request.method == 'POST') {
          writes++;
          stored ??= jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response('{"memory_id":"1","duplicate":true}', 200);
        }
        if (request.url.queryParameters.containsKey('memory_lookup_hash')) {
          filteredReads++;
          return http.Response(
            filteredReads == 1 ? '[]' : jsonEncode([stored]), 200,
          );
        }
        return http.Response(jsonEncode([
          if (stored != null) stored,
        ]), 200);
      }),
    );
    const data = <String, dynamic>{
      'title': 'Synthetic retry memory',
      'memory_type': 'note',
      'value': _secretMarker,
    };
    await expectLater(
      client.upsertZkMemory(authToken: _token, data: data),
      throwsA(isA<MemorySaveReadbackException>()),
    );
    await client.upsertZkMemory(authToken: _token, data: data);
    expect(writes, 2);
    expect(filteredReads, 2);
  }, skip: !kEnableZkPrivateOnlyUnlock);

  test('private proposal finalize includes device and verifies readback',
      () async {
    _bindPrivateVault();
    final methods = <String>[];
    Map<String, dynamic>? stored;
    final client = VaultAIClient(
      baseUrl: _base,
      httpClient: MockClient((request) async {
        methods.add(request.method);
        expect(request.headers['x-device-id'], 'synthetic-memory-device');
        expect(request.headers['authorization'], 'Bearer $_token');
        if (request.method == 'POST') {
          expect(request.body, isNot(contains(_secretMarker)));
          expect(request.body.toLowerCase(), isNot(contains('"pin"')));
          stored = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response('{"memory_id":"1","duplicate":false}', 200);
        }
        return http.Response(jsonEncode([
          if (stored != null) stored,
        ]), 200);
      }),
    );
    expect(await client.tryZkFinalizeMemoryProposal(
      baseUrl: _base,
      authToken: _token,
      memoryType: 'note',
      memoryKey: 'Synthetic proposal',
      memoryValue: _secretMarker,
    ), isTrue);
    expect(methods, ['GET', 'POST', 'GET']);
  }, skip: !kEnableZkPrivateOnlyUnlock);

  test('ordinary save keeps its existing GET then POST flow', () async {
    st.SessionTermination.instance.bindSession(_token);
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 7)),
      vaultId: 'synthetic-ordinary-vault',
      vaultHandle: 'synthetic-ordinary-handle',
    );
    final methods = <String>[];
    final client = VaultAIClient(
      baseUrl: _base,
      httpClient: MockClient((request) async {
        methods.add(request.method);
        if (request.method == 'GET') return http.Response('[]', 200);
        return http.Response('{"memory_id":"1"}', 200);
      }),
    );
    await client.upsertZkMemory(
      authToken: _token,
      data: const <String, dynamic>{
        'title': 'Ordinary synthetic memory',
        'memory_type': 'note',
        'value': _secretMarker,
      },
    );
    expect(methods, ['GET', 'POST']);
  });
}
