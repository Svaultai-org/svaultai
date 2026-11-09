import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_stage.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

void main() {
  test('owner stages exact MVK package without changing the old link',
      () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 29));
    final beneficiaryPair = await X25519().newKeyPair();
    final beneficiaryPublic = await beneficiaryPair.extractPublicKey();
    final beneficiaryPrivate =
        SecretKey(await beneficiaryPair.extractPrivateKeyBytes());
    final fingerprint = await beneficiaryPublicKeyFingerprint(
      Uint8List.fromList(beneficiaryPublic.bytes),
    );
    Map<String, dynamic>? stagedBody;
    var pubkeyReads = 0;
    var stageWrites = 0;
    final staged = await stageLinkedOldInheritanceV2(
      linkId: 57,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      confirmedBeneficiaryFingerprint: fingerprint,
      zkProofToken: 'synthetic-one-use-proof',
      fetchPubkey: (_) async {
        pubkeyReads++;
        return <String, dynamic>{
          'beneficiary_link_id': 57,
          'crypto_version_hint': 1,
          'pk_vault_public_b64url': b64urlEncode(beneficiaryPublic.bytes),
        };
      },
      stage: (body) async {
        stageWrites++;
        stagedBody = body;
        return <String, dynamic>{
          'beneficiary_link_id': 57,
          'crypto_version': 2,
          'stage_revision': 1,
          'old_source_snapshot': 'A' * 43,
          'beneficiary_pk_sha256': fingerprint.replaceAll('-', ''),
          'state': 'staged',
          'legacy_link_unchanged': true,
        };
      },
      readback: (_) async => <String, dynamic>{
        ...stagedBody!,
        'stage_revision': 1,
        'old_source_snapshot': 'A' * 43,
        'beneficiary_pk_sha256': fingerprint.replaceAll('-', ''),
        'state': 'staged',
        'legacy_link_unchanged': true,
      },
      accessIsCurrent: () => true,
    );
    expect(staged.linkId, 57);
    expect(staged.stageRevision, 1);
    expect(pubkeyReads, 1);
    expect(stageWrites, 1);
    expect(stagedBody!['zk_proof_token'], 'synthetic-one-use-proof');
    expect(stagedBody, isNot(containsPair('pin', anything)));
    expect(stagedBody, isNot(containsPair('vault_name', anything)));
    final decrypted = await decryptInheritanceMvk(
      expectedLinkId: 57,
      beneficiaryPrivateKey: beneficiaryPrivate,
      rawPackage: stagedBody!,
    );
    expect(decrypted.ownerVaultId, 'synthetic-owner');
    expect(
        await decrypted.ownerMvk.extractBytes(), await ownerMvk.extractBytes());
  });

  test('wrong fingerprint aborts before any staging request', () async {
    final pair = await X25519().newKeyPair();
    final publicKey = await pair.extractPublicKey();
    var stages = 0;
    await expectLater(
      stageLinkedOldInheritanceV2(
        linkId: 57,
        ownerVaultId: 'synthetic-owner',
        ownerMvk: SecretKey(List<int>.filled(32, 29)),
        confirmedBeneficiaryFingerprint: '0' * 64,
        zkProofToken: 'synthetic-proof',
        fetchPubkey: (_) async => <String, dynamic>{
          'beneficiary_link_id': 57,
          'crypto_version_hint': 1,
          'pk_vault_public_b64url': b64urlEncode(publicKey.bytes),
        },
        stage: (_) async {
          stages++;
          return <String, dynamic>{};
        },
        readback: (_) async => <String, dynamic>{},
        accessIsCurrent: () => true,
      ),
      throwsFormatException,
    );
    expect(stages, 0);
  });

  test('changed server readback fails closed', () async {
    final pair = await X25519().newKeyPair();
    final publicKey = await pair.extractPublicKey();
    final fingerprint = await beneficiaryPublicKeyFingerprint(
      Uint8List.fromList(publicKey.bytes),
    );
    var stageWrites = 0;
    await expectLater(
      stageLinkedOldInheritanceV2(
        linkId: 57,
        ownerVaultId: 'synthetic-owner',
        ownerMvk: SecretKey(List<int>.filled(32, 29)),
        confirmedBeneficiaryFingerprint: fingerprint,
        zkProofToken: 'synthetic-proof',
        fetchPubkey: (_) async => <String, dynamic>{
          'beneficiary_link_id': 57,
          'crypto_version_hint': 1,
          'pk_vault_public_b64url': b64urlEncode(publicKey.bytes),
        },
        stage: (_) async {
          stageWrites++;
          return <String, dynamic>{
            'beneficiary_link_id': 57,
            'crypto_version': 2,
            'stage_revision': 1,
            'old_source_snapshot': 'A' * 43,
            'beneficiary_pk_sha256': fingerprint.replaceAll('-', ''),
            'state': 'staged',
            'legacy_link_unchanged': true,
          };
        },
        readback: (_) async => <String, dynamic>{
          'beneficiary_link_id': 57,
          'crypto_version': 2,
          'stage_revision': 1,
          'old_source_snapshot': 'A' * 43,
          'beneficiary_pk_sha256': fingerprint.replaceAll('-', ''),
          'state': 'staged',
          'legacy_link_unchanged': true,
          'encrypted_payload': b64urlEncode(Uint8List(48)),
        },
        accessIsCurrent: () => true,
      ),
      throwsStateError,
    );
    expect(stageWrites, 1);
  });
}
