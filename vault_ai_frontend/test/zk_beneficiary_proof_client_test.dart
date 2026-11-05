import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';


void main() {
  test('four safe beneficiary calls send only an OPAQUE proof', () async {
    final sent = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        sent.add(request);
        return http.Response('{}', 200);
      }),
    );
    await client.listBeneficiaries(
      vaultName: 'synthetic-vault',
      authToken: 'synthetic-bearer',
      zkProofToken: 'proof-one',
    );
    await client.listInheritances(
      vaultName: 'synthetic-vault',
      authToken: 'synthetic-bearer',
      zkProofToken: 'proof-two',
    );
    await client.requestTransfer(
      linkId: 7,
      vaultName: 'synthetic-vault',
      authToken: 'synthetic-bearer',
      zkProofToken: 'proof-three',
    );
    await client.cancelTransfer(
      linkId: 7,
      vaultName: 'synthetic-vault',
      authToken: 'synthetic-bearer',
      zkProofToken: 'proof-four',
    );
    expect(sent.map((request) => request.url.path).toList(), [
      '/beneficiary/list-mine',
      '/beneficiary/list-inheritances',
      '/beneficiary/request-transfer',
      '/beneficiary/cancel-transfer',
    ]);
    const proofs = ['proof-one', 'proof-two', 'proof-three', 'proof-four'];
    for (var index = 0; index < sent.length; index++) {
      final body = jsonDecode(sent[index].body) as Map<String, dynamic>;
      expect(body.containsKey('pin'), isFalse);
      expect(body.containsKey('vault_name'), isFalse);
      expect(body['zk_proof_token'], proofs[index]);
      if (index >= 2) expect(body['link_id'], 7);
    }
  });

  test('legacy beneficiary call keeps PIN shape', () async {
    http.Request? sent;
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        sent = request;
        return http.Response('{}', 200);
      }),
    );
    await client.listBeneficiaries(
      vaultName: 'synthetic-vault',
      authToken: 'synthetic-bearer',
      pin: 'synthetic-legacy-pin',
    );
    expect(jsonDecode(sent!.body), {'pin': 'synthetic-legacy-pin'});
  });
}
