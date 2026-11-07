import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  setUp(ZkActiveMvk.clear);
  tearDown(ZkActiveMvk.clear);

  test('private-only ZK refuses old create, link, request, claim before any PIN request',
      () async {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 51)),
      vaultId: 'synthetic-zk-vault',
      vaultHandle: 'synthetic-zk-handle',
    );
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{"ok":true}', 200);
      }),
    );
    final calls = <Future<Object?> Function()>[
      () => client.createBeneficiary(
            vaultName: '',
            pin: '123456',
            label: 'Synthetic heir',
            authToken: 'synthetic-session',
          ),
      () => client.linkBeneficiary(
            vaultName: '',
            pin: '123456',
            pairingCode: 'synthetic-code',
            authToken: 'synthetic-session',
          ),
      () => client.claimTransfer(
            linkId: 5,
            vaultName: '',
            pin: '123456',
            inheritedVaultName: 'Synthetic inherited vault',
            authToken: 'synthetic-session',
          ),
      () => client.requestTransfer(
            linkId: 5,
            vaultName: '',
            pin: '123456',
            authToken: 'synthetic-session',
          ),
    ];
    for (final call in calls) {
      await expectLater(call(), throwsStateError);
    }
    expect(requests, isEmpty);
  }, skip: !kEnableZkPrivateOnlyUnlock);

  test('legacy-only create, link, request, claim retain their request contracts',
      () async {
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{"ok":true}', 200);
      }),
    );
    await client.createBeneficiary(
      vaultName: 'Synthetic legacy vault',
      pin: '123456',
      label: 'Synthetic heir',
      authToken: 'synthetic-session',
    );
    await client.linkBeneficiary(
      vaultName: 'Synthetic legacy vault',
      pin: '123456',
      pairingCode: 'synthetic-code',
      authToken: 'synthetic-session',
    );
    await client.claimTransfer(
      linkId: 5,
      vaultName: 'Synthetic legacy vault',
      pin: '123456',
      inheritedVaultName: 'Synthetic inherited vault',
      authToken: 'synthetic-session',
    );
    await client.requestTransfer(
      linkId: 5,
      vaultName: 'Synthetic legacy vault',
      pin: '123456',
      authToken: 'synthetic-session',
    );
    expect(requests.map((request) => request.url.path), <String>[
      '/beneficiary/create',
      '/beneficiary/link',
      '/beneficiary/claim-transfer',
      '/beneficiary/request-transfer',
    ]);
    for (final request in requests) {
      expect(request.method, 'POST');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body['pin'], '123456');
      expect(body['vault_name'], anyOf(isNull, ''));
    }
  }, skip: kEnableZkPrivateOnlyUnlock);

  test('private-only build blocks an old countdown even without an active key',
      () async {
    ZkActiveMvk.clear();
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{"ok":true}', 200);
      }),
    );
    await expectLater(
      client.requestTransfer(
        linkId: 5,
        vaultName: '',
        zkProofToken: 'synthetic-proof',
        authToken: 'synthetic-session',
      ),
      throwsStateError,
    );
    expect(requests, isEmpty);
  }, skip: !kEnableZkPrivateOnlyUnlock);

  test('private handle still blocks before PIN lookup when MVK is unavailable',
      () {
    ZkActiveMvk.clear();
    if (kEnableZkPrivateOnlyUnlock) {
      expect(
          () => requireLegacyBeneficiaryPinActionAllowed(
              vaultHandle: 'synthetic-zk-handle'),
          throwsStateError);
    } else {
      requireLegacyBeneficiaryPinActionAllowed(
          vaultHandle: 'synthetic-zk-handle');
    }
    requireLegacyBeneficiaryPinActionAllowed(vaultHandle: null);
  });
}
