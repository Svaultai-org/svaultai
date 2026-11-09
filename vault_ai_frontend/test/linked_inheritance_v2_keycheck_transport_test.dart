import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_active_sk_vault.dart';

const _enabled = bool.fromEnvironment(
  'VAULTAI_ENABLE_LINKED_INHERITANCE_KEYCHECK', defaultValue: false,
);

void main() {
  test('keycheck transport is opt-in and never sends PIN or owner MVK',
      () async {
    final privateKey = SecretKey(List<int>.filled(32, 1));
    ZkActiveSkVault.set(skVault: privateKey, vaultId: 'synthetic-beneficiary');
    addTearDown(ZkActiveSkVault.clear);
    setApiClientDeviceId('synthetic-device');
    final calls = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        calls.add(request);
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-device');
        expect(request.method, 'POST');
        expect(request.body, isNot(contains('"pin"')));
        expect(request.body, isNot(contains('"mvk"')));
        if (request.url.path ==
            '/inheritance/old-link-v2/41/beneficiary-challenge') {
          return http.Response(jsonEncode({
            'beneficiary_link_id': 41,
            'stage_revision': 1,
            'offer_commitment': 'ujXshrEqpVBexwliWpXJGy8tdZX2RiCFam0G-K409a8',
            'beneficiary_pk_sha256':
                '1a92f23852dc908d97316a3b13578281196c1dd73d9ae5e313f3fb6b8954bf55',
            'expires_at': DateTime.now()
                .toUtc().add(const Duration(minutes: 5)).toIso8601String(),
            'challenge_ephemeral_pk':
                'zo060cy2M-x7cMF4FKXHbs0CloUFDTRHRboFhw5YfVk',
            'challenge_nonce': 'AwMDAwMDAwMDAwMD',
            'challenge_ciphertext':
                '6PFiCC3TPX7zIQbD_hBPGVU8-pRrh4lsdfsoJa1n4vHK34ULf1YOGu9qIDyGZU7L',
          }), 200);
        }
        if (request.url.path ==
            '/inheritance/old-link-v2/beneficiary-keycheck') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['challenge_secret'],
              'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8');
          expect(body['zk_proof_token'], 'synthetic-proof');
          return http.Response(jsonEncode({
            'beneficiary_link_id': 41,
            'stage_revision': 1,
            'offer_commitment': 'ujXshrEqpVBexwliWpXJGy8tdZX2RiCFam0G-K409a8',
            'beneficiary_key_possession_confirmed': true,
            'package_decryption_verified': false,
            'legacy_link_unchanged': true,
          }), 200);
        }
        fail('Unexpected route ${request.url.path}');
      }),
    );
    Future<void> check() async {
      final result = await client.verifyLinkedOldInheritanceBeneficiaryKey(
        authToken: 'synthetic-session',
        linkId: 41,
        beneficiaryVaultId: 'synthetic-beneficiary',
        beneficiaryPrivateKey: privateKey,
        zkProofToken: 'synthetic-proof',
      );
      expect(result.stageRevision, 1);
    }
    if (_enabled) {
      await check();
      expect(calls.length, 2);
    } else {
      await expectLater(check(), throwsStateError);
      expect(calls, isEmpty);
    }
  });
}
