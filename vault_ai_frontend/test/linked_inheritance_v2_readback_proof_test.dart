import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_readback_proof.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_release_readback.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_stage.dart';

const _owner = 'synthetic-owner';
const _beneficiary = 'synthetic-beneficiary';
const _commitment =
    'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _publicVector = 'L3zXtTlNHP2GsXNfzt7wKbEWHO-aeX_IRb5UkCx2VQk';

void main() {
  final ownerMvk = SecretKey(List<int>.filled(32, 27));
  final staged = StagedLinkedInheritanceV2(
    linkId: 41,
    stageRevision: 2,
    oldSourceSnapshot: _commitment,
    beneficiaryFingerprint: 'f' * 64,
  );
  final released = ReleasedLinkedInheritanceV2(
    linkId: 41,
    stageRevision: 2,
    offerCommitment: _commitment,
    ownerVaultId: _owner,
    ownerMvk: ownerMvk,
  );

  test('owner registers only stage-bound public key', () async {
    Map<String, dynamic>? request;
    final result = await registerLinkedReadbackVerifier(
      staged: staged,
      ownerVaultId: _owner,
      ownerMvk: ownerMvk,
      zkProofToken: 'synthetic-owner-proof',
      fetchReadback: (_) async => {
        'beneficiary_link_id': 41,
        'stage_revision': 2,
        'old_source_snapshot': _commitment,
        'owner_vault_id': _owner,
        'beneficiary_vault_id': _beneficiary,
        'offer_commitment': _commitment,
        'beneficiary_pk_sha256': 'f' * 64,
        'state': 'staged',
      },
      submitVerifier: (body) async {
        request = body;
        return {
          'beneficiary_link_id': 41,
          'stage_revision': 2,
          'offer_commitment': _commitment,
          'owner_readback_verifier_registered': true,
          'package_decryption_verified': false,
          'legacy_link_unchanged': true,
        };
      },
      accessIsCurrent: () => true,
    );
    expect(result.offerCommitment, _commitment);
    expect(request!['readback_public_key'], _publicVector);
    expect(request!.keys, isNot(contains('owner_mvk')));
    expect(jsonEncode(request), isNot(contains(base64Url.encode(
        List<int>.filled(32, 27)))));
  });

  test('beneficiary signs fresh challenge using decrypted owner key', () async {
    Map<String, dynamic>? request;
    final nonce = base64Url.encode(List<int>.generate(32, (i) => i))
        .replaceAll('=', '');
    final result = await proveLinkedReadback(
      released: released,
      beneficiaryVaultId: _beneficiary,
      zkProofToken: 'synthetic-beneficiary-proof',
      fetchChallenge: (_) async => {
        'beneficiary_link_id': 41,
        'stage_revision': 2,
        'offer_commitment': _commitment,
        'owner_vault_id': _owner,
        'beneficiary_vault_id': _beneficiary,
        'readback_public_key': _publicVector,
        'challenge_nonce': nonce,
        'expires_at': DateTime.now()
            .toUtc()
            .add(const Duration(minutes: 5))
            .toIso8601String(),
        'package_decryption_verified': false,
      },
      submitProof: (body) async {
        request = body;
        return {
          'beneficiary_link_id': 41,
          'stage_revision': 2,
          'offer_commitment': _commitment,
          'package_decryption_verified': true,
          'legacy_package_preserved': true,
          'readback_at': DateTime.now().toUtc().toIso8601String(),
        };
      },
      accessIsCurrent: () => true,
    );
    expect(result.stageRevision, 2);
    expect(request!.keys, isNot(contains('owner_mvk')));
    expect(request!.keys, isNot(contains('pin')));
    final signature = Signature(
      base64Url.decode(base64Url.normalize(request!['signature'] as String)),
      publicKey: SimplePublicKey(
        base64Url.decode(base64Url.normalize(_publicVector)),
        type: KeyPairType.ed25519,
      ),
    );
    final message = utf8.encode(
      'svaultai:linked-old-v2-readback:v1:'
      '41:2:$_commitment:$_owner:$_beneficiary:$nonce',
    );
    expect(await Ed25519().verify(message, signature: signature), isTrue);
  });

  test('wrong owner key, changed stage, and stale access fail before proof',
      () async {
    var submitted = 0;
    final nonce = base64Url.encode(List<int>.filled(32, 1))
        .replaceAll('=', '');
    Future<void> attempt({
      SecretKey? key,
      String commitment = _commitment,
      bool Function()? current,
    }) async {
      await proveLinkedReadback(
        released: ReleasedLinkedInheritanceV2(
          linkId: 41,
          stageRevision: 2,
          offerCommitment: commitment,
          ownerVaultId: _owner,
          ownerMvk: key ?? ownerMvk,
        ),
        beneficiaryVaultId: _beneficiary,
        zkProofToken: 'synthetic-proof',
        fetchChallenge: (_) async => {
          'beneficiary_link_id': 41,
          'stage_revision': 2,
          'offer_commitment': _commitment,
          'owner_vault_id': _owner,
          'beneficiary_vault_id': _beneficiary,
          'readback_public_key': _publicVector,
          'challenge_nonce': nonce,
          'expires_at': DateTime.now()
              .toUtc()
              .add(const Duration(minutes: 5))
              .toIso8601String(),
          'package_decryption_verified': false,
        },
        submitProof: (_) async {
          submitted++;
          return {};
        },
        accessIsCurrent: current ?? () => true,
      );
    }
    await expectLater(attempt(key: SecretKey(List<int>.filled(32, 1))),
        throwsStateError);
    await expectLater(attempt(commitment: 'B' * 43), throwsStateError);
    await expectLater(attempt(current: () => false), throwsStateError);
    expect(submitted, 0);
  });
}
