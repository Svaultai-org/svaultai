import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart' as app_main;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  tearDown(ZkActiveMvk.clear);

  test('V2 pairing create and link never put a PIN or vault name on the wire',
      () async {
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await client.createZkBeneficiary(
      passerLabelCiphertext: 'synthetic-ciphertext',
      zkProofToken: 'owner-proof',
      authToken: 'synthetic-session',
    );
    await client.linkZkBeneficiary(
      pairingCode: 'synthetic-code',
      zkProofToken: 'beneficiary-proof',
      authToken: 'synthetic-session',
    );
    expect(sent.map((r) => r.url.path), [
      '/beneficiary/zk-create',
      '/beneficiary/zk-link',
    ]);
    final create = jsonDecode(sent[0].body) as Map<String, dynamic>;
    final link = jsonDecode(sent[1].body) as Map<String, dynamic>;
    expect(create, {
      'passer_label_ciphertext': 'synthetic-ciphertext',
      'zk_proof_token': 'owner-proof',
    });
    expect(link, {
      'pairing_code': 'synthetic-code',
      'zk_proof_token': 'beneficiary-proof',
    });
    expect(sent.every((r) => !r.body.contains('123456')), isTrue);
  });

  test('V2 escrow removal sends one-time proof and legacy removal does not',
      () async {
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await client.deleteInheritanceCredentials(
      linkId: 17,
      authToken: 'synthetic-session',
      zkProofToken: 'synthetic-proof',
    );
    await client.deleteInheritanceCredentials(
      linkId: 18,
      authToken: 'synthetic-session',
    );
    expect(jsonDecode(sent[0].body), {
      'beneficiary_link_id': 17,
      'zk_proof_token': 'synthetic-proof',
    });
    expect(jsonDecode(sent[1].body), {'beneficiary_link_id': 18});
    expect(sent.every((request) => !request.body.contains('123456')), isTrue);
  });

  test('V2 pairing checks the action lease before wire and after response',
      () async {
    var current = false;
    var calls = 0;
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        calls++;
        current = false;
        return http.Response('{}', 200);
      }),
    );
    void guard() {
      if (!current) throw StateError('Vault changed');
    }
    await expectLater(
      client.createZkBeneficiary(
        passerLabelCiphertext: 'synthetic-ciphertext',
        zkProofToken: 'synthetic-proof',
        authToken: 'synthetic-session',
        accessGuard: guard,
      ),
      throwsStateError,
    );
    expect(calls, 0);
    current = true;
    await expectLater(
      client.linkZkBeneficiary(
        pairingCode: 'synthetic-code',
        zkProofToken: 'synthetic-proof',
        authToken: 'synthetic-session',
        accessGuard: guard,
      ),
      throwsStateError,
    );
    expect(calls, 1);
  });

  test('private label encryption refuses a changed vault key', () async {
    final first = SecretKey(List<int>.filled(32, 3));
    ZkActiveMvk.set(
      mvk: first, vaultId: 'synthetic-one', vaultHandle: 'VLT-one',
    );
    final ciphertext = await app_main.encryptZkBeneficiaryLabelCiphertext(
      'Synthetic beneficiary',
      expectedMvk: first,
      expectedVaultId: 'synthetic-one',
    );
    expect(ciphertext, isNotEmpty);
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 4)),
      vaultId: 'synthetic-two',
      vaultHandle: 'VLT-two',
    );
    await expectLater(
      app_main.encryptZkBeneficiaryLabelCiphertext(
        'Synthetic beneficiary',
        expectedMvk: first,
        expectedVaultId: 'synthetic-one',
      ),
      throwsStateError,
    );
  });

  test('mixed pairing protocol lookup sends only the code and checks lease',
      () async {
    var current = true;
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        current = false;
        return http.Response('{"protocol":"private"}', 200);
      }),
    );
    void guard() {
      if (!current) throw StateError('Vault changed');
    }
    await expectLater(
      client.beneficiaryPairingProtocol(
        pairingCode: 'synthetic-code',
        authToken: 'synthetic-session',
        accessGuard: guard,
      ),
      throwsStateError,
    );
    expect(sent, hasLength(1));
    expect(sent.single.url.path, '/beneficiary/pairing-protocol');
    expect(jsonDecode(sent.single.body), {'pairing_code': 'synthetic-code'});
    current = false;
    await expectLater(
      client.beneficiaryPairingProtocol(
        pairingCode: 'synthetic-code',
        authToken: 'synthetic-session',
        accessGuard: guard,
      ),
      throwsStateError,
    );
    expect(sent, hasLength(1));
    final stableClient = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient(
        (_) async => http.Response('{"protocol":"legacy"}', 200),
      ),
    );
    current = true;
    expect(
      await stableClient.beneficiaryPairingProtocol(
        pairingCode: 'synthetic-old-code',
        authToken: 'synthetic-session',
        accessGuard: guard,
      ),
      'legacy',
    );
  });
}
