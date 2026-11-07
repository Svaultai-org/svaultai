import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';

void main() {
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
}
