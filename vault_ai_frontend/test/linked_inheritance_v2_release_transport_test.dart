import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/zk_active_sk_vault.dart';

const _enabled = bool.fromEnvironment(
  'VAULTAI_ENABLE_LINKED_INHERITANCE_RELEASE_READBACK',
  defaultValue: false,
);

void main() {
  test('released old-link transport is opt-in and sends no PIN', () async {
    final pair = await X25519().newKeyPair();
    final beneficiarySk = SecretKey(await pair.extractPrivateKeyBytes());
    final pk = await pair.extractPublicKey();
    final ownerMvk = SecretKey(List<int>.filled(32, 27));
    final envelope = await encryptInheritanceMvk(
      beneficiaryLinkId: 41,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(pk.bytes),
    );
    ZkActiveSkVault.set(
      skVault: beneficiarySk, vaultId: 'synthetic-beneficiary',
    );
    addTearDown(ZkActiveSkVault.clear);
    setApiClientDeviceId('synthetic-device');
    var requests = 0;
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests++;
        expect(request.method, 'POST');
        expect(request.url.path,
            '/inheritance/old-link-v2/41/released-package');
        expect(request.body, isEmpty);
        expect(request.url.query, isEmpty);
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-device');
        return http.Response(jsonEncode({
          ...envelope.toRequestBody(41),
          'owner_vault_id': 'synthetic-owner',
          'stage_revision': 1,
          'offer_commitment': 'A' * 43,
          'pairing_state': 'released',
          'released_at': DateTime.now().toUtc().toIso8601String(),
          'legacy_package_preserved': true,
          'package_decryption_verified': false,
        }), 200);
      }),
    );
    Future<void> check() async {
      final result = await client.readReleasedLinkedOldInheritanceV2(
        authToken: 'synthetic-session',
        linkId: 41,
        beneficiaryVaultId: 'synthetic-beneficiary',
        beneficiaryPrivateKey: beneficiarySk,
      );
      expect(await result.ownerMvk.extractBytes(),
          await ownerMvk.extractBytes());
    }
    if (_enabled) {
      await check();
      expect(requests, 1);
    } else {
      await expectLater(check(), throwsStateError);
      expect(requests, 0);
    }
  });
}
