import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_stage.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_active_sk_vault.dart';

const _enabled = bool.fromEnvironment(
  'VAULTAI_ENABLE_LINKED_INHERITANCE_READBACK_PROOF',
  defaultValue: false,
);

void main() {
  test('readback proof transport is opt-in and sends no key or PIN', () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 27));
    final beneficiaryPair = await X25519().newKeyPair();
    final beneficiarySk =
        SecretKey(await beneficiaryPair.extractPrivateKeyBytes());
    final beneficiaryPk = await beneficiaryPair.extractPublicKey();
    final envelope = await encryptInheritanceMvk(
      beneficiaryLinkId: 41,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(beneficiaryPk.bytes),
    );
    const commitment =
        'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
    final staged = StagedLinkedInheritanceV2(
      linkId: 41,
      stageRevision: 2,
      oldSourceSnapshot: commitment,
      beneficiaryFingerprint: 'f' * 64,
    );
    final nonce = base64Url.encode(List<int>.generate(32, (i) => i))
        .replaceAll('=', '');
    final paths = <String>[];
    String? publicVerifier;
    setApiClientDeviceId('synthetic-device');
    addTearDown(() {
      ZkActiveMvk.clear();
      ZkActiveSkVault.clear();
    });
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        paths.add(request.url.path);
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-device');
        expect(request.body, isNot(contains('"pin"')));
        expect(request.body, isNot(contains('"owner_mvk"')));
        expect(request.body, isNot(contains('"vault_name"')));
        if (request.url.path == '/inheritance/old-link-v2/41/readback') {
          expect(request.method, 'GET');
          return http.Response(jsonEncode({
            'beneficiary_link_id': 41,
            'stage_revision': 2,
            'old_source_snapshot': commitment,
            'owner_vault_id': 'synthetic-owner',
            'beneficiary_vault_id': 'synthetic-beneficiary',
            'offer_commitment': commitment,
            'beneficiary_pk_sha256': 'f' * 64,
            'state': 'staged',
          }), 200);
        }
        if (request.url.path ==
            '/inheritance/old-link-v2/readback-verifier') {
          expect(request.method, 'POST');
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          publicVerifier = body['readback_public_key'] as String;
          expect(publicVerifier,
              'L3zXtTlNHP2GsXNfzt7wKbEWHO-aeX_IRb5UkCx2VQk');
          return http.Response(jsonEncode({
            'beneficiary_link_id': 41,
            'stage_revision': 2,
            'offer_commitment': commitment,
            'owner_readback_verifier_registered': true,
            'package_decryption_verified': false,
            'legacy_link_unchanged': true,
          }), 200);
        }
        if (request.url.path ==
            '/inheritance/old-link-v2/41/released-package') {
          expect(request.method, 'POST');
          expect(request.body, isEmpty);
          return http.Response(jsonEncode({
            ...envelope.toRequestBody(41),
            'owner_vault_id': 'synthetic-owner',
            'stage_revision': 2,
            'offer_commitment': commitment,
            'pairing_state': 'released',
            'released_at': DateTime.now().toUtc().toIso8601String(),
            'legacy_package_preserved': true,
            'package_decryption_verified': false,
          }), 200);
        }
        if (request.url.path ==
            '/inheritance/old-link-v2/41/readback-challenge') {
          expect(request.method, 'POST');
          expect(request.body, '{}');
          return http.Response(jsonEncode({
            'beneficiary_link_id': 41,
            'stage_revision': 2,
            'offer_commitment': commitment,
            'owner_vault_id': 'synthetic-owner',
            'beneficiary_vault_id': 'synthetic-beneficiary',
            'readback_public_key': publicVerifier,
            'challenge_nonce': nonce,
            'expires_at': DateTime.now()
                .toUtc()
                .add(const Duration(minutes: 5))
                .toIso8601String(),
            'package_decryption_verified': false,
          }), 200);
        }
        if (request.url.path == '/inheritance/old-link-v2/readback-proof') {
          expect(request.method, 'POST');
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body.keys, contains('signature'));
          expect(body.keys, isNot(contains('owner_mvk')));
          return http.Response(jsonEncode({
            'beneficiary_link_id': 41,
            'stage_revision': 2,
            'offer_commitment': commitment,
            'package_decryption_verified': true,
            'legacy_package_preserved': true,
            'readback_at': DateTime.now().toUtc().toIso8601String(),
          }), 200);
        }
        fail('Unexpected ${request.method} ${request.url.path}');
      }),
    );
    ZkActiveMvk.set(
      mvk: ownerMvk,
      vaultId: 'synthetic-owner',
      vaultHandle: 'synthetic-handle',
    );
    Future<void> register() async {
      await client.registerLinkedOldInheritanceReadbackVerifier(
        authToken: 'synthetic-session',
        staged: staged,
        ownerVaultId: 'synthetic-owner',
        ownerMvk: ownerMvk,
        zkProofToken: 'synthetic-owner-proof',
      );
    }
    if (!_enabled) {
      await expectLater(register(), throwsStateError);
      expect(paths, isEmpty);
      return;
    }
    await register();
    ZkActiveMvk.clear();
    ZkActiveSkVault.set(
      skVault: beneficiarySk,
      vaultId: 'synthetic-beneficiary',
    );
    final receipt = await client.proveReleasedLinkedOldInheritanceReadback(
      authToken: 'synthetic-session',
      linkId: 41,
      beneficiaryVaultId: 'synthetic-beneficiary',
      beneficiaryPrivateKey: beneficiarySk,
      zkProofToken: 'synthetic-beneficiary-proof',
    );
    expect(receipt.stageRevision, 2);
    expect(paths, [
      '/inheritance/old-link-v2/41/readback',
      '/inheritance/old-link-v2/readback-verifier',
      '/inheritance/old-link-v2/41/released-package',
      '/inheritance/old-link-v2/41/readback-challenge',
      '/inheritance/old-link-v2/readback-proof',
    ]);
  });
}
