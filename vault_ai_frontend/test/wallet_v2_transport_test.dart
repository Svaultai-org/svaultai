import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;

void main() {
  test('wallet V2 stage/read/retire transport excludes PIN and wallet secret',
      () async {
    const token = 'synthetic-wallet-session';
    st.SessionTermination.instance.bindSession(token);
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{}', 200);
      }),
    );
    final stage = <String, dynamic>{
      'legacy_item_id': 42,
      'source_snapshot': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
      'wallet_record_id': 'synthetic-wallet-record-1',
      'chain': 'evm',
      'network': 'ethereum-mainnet',
      'asset': 'ETH',
      'public_address': '0x0000000000000000000000000000000000000001',
      'wallet_label': 'Synthetic wallet',
      'payload_ciphertext': 'AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0=',
      'envelope_version': 'v2',
    };
    await client.walletV2MigrationPost(
      authToken: token,
      path: '/vault/wallet-v2/migrate/stage',
      body: stage,
    );
    await client.walletV2Read(
      authToken: token,
      path: '/vault/wallet-v2/synthetic-wallet-record-1',
    );
    await client.walletV2MigrationPost(
      authToken: token,
      path: '/vault/wallet-v2/migrate/retire',
      body: {
        'legacy_item_id': 42,
        'wallet_record_id': 'synthetic-wallet-record-1',
        'source_snapshot': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
        'readback_receipt': 'synthetic-receipt',
        'zk_proof_token': 'synthetic-opaque-proof',
        'client_verified_exact_bytes': true,
      },
    );
    expect(requests.map((r) => r.url.path), [
      '/vault/wallet-v2/migrate/stage',
      '/vault/wallet-v2/synthetic-wallet-record-1',
      '/vault/wallet-v2/migrate/retire',
    ]);
    for (final request in requests) {
      expect(request.body, isNot(contains('"pin"')));
      expect(request.body, isNot(contains('synthetic-private-key')));
    }
    final before = requests.length;
    await expectLater(
      client.walletV2MigrationPost(
        authToken: token,
        path: '/vault/wallet-v2/migrate/stage',
        body: {...stage, 'pin': '123456'},
      ),
      throwsStateError,
    );
    expect(requests, hasLength(before));
    expect(jsonDecode(requests.first.body)['payload_ciphertext'],
        stage['payload_ciphertext']);
  });

  test('new-wallet V2 transport only stages ciphertext and a readback receipt',
      () async {
    const token = 'synthetic-wallet-new-session';
    st.SessionTermination.instance.bindSession(token);
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.invalid',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{}', 200);
      }),
    );
    final stage = <String, dynamic>{
      'wallet_record_id': 'synthetic-new-wallet-record-1',
      'chain': 'evm', 'network': 'ethereum_mainnet', 'asset': 'ETH',
      'public_address': '0x0000000000000000000000000000000000000001',
      'wallet_label': 'Synthetic wallet',
      'payload_ciphertext': 'AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0',
      'envelope_version': 'v2', 'migration_state': 'migration_pending',
    };
    await client.walletV2NewPost(
      authToken: token, path: '/vault/wallet-v2', body: stage,
    );
    await client.walletV2Read(
      authToken: token, path: '/vault/wallet-v2/synthetic-new-wallet-record-1',
    );
    await client.walletV2NewPost(
      authToken: token,
      path: '/vault/wallet-v2/synthetic-new-wallet-record-1/publish-new',
      body: {
        'readback_receipt': 'synthetic-receipt',
        'client_verified_exact_bytes': true,
      },
    );
    await client.walletV2List(authToken: token);
    expect(requests.map((request) => request.url.path), [
      '/vault/wallet-v2', '/vault/wallet-v2/synthetic-new-wallet-record-1',
      '/vault/wallet-v2/synthetic-new-wallet-record-1/publish-new',
      '/vault/wallet-v2',
    ]);
    for (final request in requests) {
      expect(request.body, isNot(contains('"pin"')));
      expect(request.body, isNot(contains('private_key')));
      expect(request.body, isNot(contains('wallet-secret')));
    }
    final before = requests.length;
    await expectLater(
      client.walletV2NewPost(
        authToken: token, path: '/vault/wallet-v2',
        body: {...stage, 'secret': 'wallet-secret'},
      ),
      throwsStateError,
    );
    await expectLater(
      client.walletV2NewPost(
        authToken: token, path: '/vault/wallet-v2',
        body: {...stage, 'migration_state': 'v2_verified'},
      ),
      throwsStateError,
    );
    expect(requests, hasLength(before));
  });
}
