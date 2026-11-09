import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  test('owner transport sends one opaque package and preserves old link',
      () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 41));
    ZkActiveMvk.set(
      mvk: ownerMvk,
      vaultId: 'synthetic-owner',
      vaultHandle: 'synthetic-handle',
    );
    addTearDown(ZkActiveMvk.clear);
    setApiClientDeviceId('synthetic-device');
    final pair = await X25519().newKeyPair();
    final publicKey = await pair.extractPublicKey();
    final privateKey = SecretKey(await pair.extractPrivateKeyBytes());
    final fingerprint = await beneficiaryPublicKeyFingerprint(
      Uint8List.fromList(publicKey.bytes),
    );
    Map<String, dynamic>? stageBody;
    final writes = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        expect(request.headers['authorization'], 'Bearer synthetic-session');
        expect(request.headers['x-device-id'], 'synthetic-device');
        if (request.method != 'GET') writes.add(request);
        final path = request.url.path;
        if (path == '/inheritance/beneficiary/41/pubkey') {
          return http.Response(
            jsonEncode(<String, dynamic>{
              'beneficiary_link_id': 41,
              'crypto_version_hint': 1,
              'pk_vault_public_b64url': b64urlEncode(publicKey.bytes),
            }),
            200,
          );
        }
        if (path == '/inheritance/old-link-v2/stage') {
          expect(request.method, 'POST');
          expect(request.body, isNot(contains('"pin"')));
          expect(request.body, isNot(contains('"vault_name"')));
          expect(request.body, isNot(contains('synthetic-secret')));
          stageBody = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode(<String, dynamic>{
              'beneficiary_link_id': 41,
              'crypto_version': 2,
              'stage_revision': 1,
              'old_source_snapshot': 'A' * 43,
              'beneficiary_pk_sha256': fingerprint.replaceAll('-', ''),
              'state': 'staged',
              'legacy_link_unchanged': true,
            }),
            200,
          );
        }
        if (path == '/inheritance/old-link-v2/41/readback') {
          return http.Response(
            jsonEncode(<String, dynamic>{
              ...stageBody!,
              'stage_revision': 1,
              'old_source_snapshot': 'A' * 43,
              'beneficiary_pk_sha256': fingerprint.replaceAll('-', ''),
              'state': 'staged',
              'legacy_link_unchanged': true,
            }),
            200,
          );
        }
        fail('Unexpected route $path');
      }),
    );
    final staged = await client.stageLinkedOldInheritanceV2(
      authToken: 'synthetic-session',
      linkId: 41,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      confirmedBeneficiaryFingerprint: fingerprint,
      zkProofToken: 'synthetic-one-use-proof',
    );
    expect(staged.stageRevision, 1);
    expect(stageBody!['zk_proof_token'], 'synthetic-one-use-proof');
    expect(writes.map((request) => request.url.path),
        <String>['/inheritance/old-link-v2/stage']);
    final decoded = await decryptInheritanceMvk(
      expectedLinkId: 41,
      beneficiaryPrivateKey: privateKey,
      rawPackage: stageBody!,
    );
    expect(decoded.ownerVaultId, 'synthetic-owner');
    expect(
        await decoded.ownerMvk.extractBytes(), await ownerMvk.extractBytes());
  });
}
