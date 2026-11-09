import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_release_readback.dart';

void main() {
  late SecretKey ownerMvk;
  late SecretKey ownerLegacyKey;
  late SecretKey beneficiarySk;
  late Map<String, dynamic> released;

  setUp(() async {
    ownerMvk = SecretKey(List<int>.filled(32, 27));
    ownerLegacyKey = SecretKey(List<int>.filled(32, 53));
    final pair = await X25519().newKeyPair();
    beneficiarySk = SecretKey(await pair.extractPrivateKeyBytes());
    final pk = await pair.extractPublicKey();
    final envelope = await encryptInheritanceMvk(
      beneficiaryLinkId: 41,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      ownerLegacyKey: ownerLegacyKey,
      beneficiaryPublicKey: Uint8List.fromList(pk.bytes),
    );
    released = {
      ...envelope.toRequestBody(41),
      'owner_vault_id': 'synthetic-owner',
      'stage_revision': 2,
      'offer_commitment': 'A' * 43,
      'pairing_state': 'released',
      'released_at': DateTime.now().toUtc().toIso8601String(),
      'legacy_package_preserved': true,
      'package_decryption_verified': false,
    };
  });

  test('beneficiary decrypts after release, old package stays preserved',
      () async {
    final result = await readReleasedLinkedInheritanceV2(
      linkId: 41,
      beneficiaryPrivateKey: beneficiarySk,
      fetchReleased: (id) async {
        expect(id, 41);
        return released;
      },
      accessIsCurrent: () => true,
    );
    expect(result.ownerVaultId, 'synthetic-owner');
    expect(result.stageRevision, 2);
    expect(await result.ownerMvk.extractBytes(),
        await ownerMvk.extractBytes());
    expect(await result.ownerLegacyKey!.extractBytes(),
        await ownerLegacyKey.extractBytes());
  });

  test('unreleased or mismatched owner package fails closed', () async {
    Future<void> check(Map<String, dynamic> body) async {
      await readReleasedLinkedInheritanceV2(
        linkId: 41,
        beneficiaryPrivateKey: beneficiarySk,
        fetchReleased: (_) async => body,
        accessIsCurrent: () => true,
      );
    }
    await expectLater(check({...released, 'pairing_state': 'claimable'}),
        throwsFormatException);
    await expectLater(check({...released, 'owner_vault_id': 'other-owner'}),
        throwsStateError);
    await expectLater(check({...released, 'wrapped_key': 'A' * 64}),
        throwsA(isA<SecretBoxAuthenticationError>()));
  });

  test('session change before or after fetch prevents local key result',
      () async {
    var current = false;
    var fetches = 0;
    Future<void> check() async {
      await readReleasedLinkedInheritanceV2(
        linkId: 41,
        beneficiaryPrivateKey: beneficiarySk,
        fetchReleased: (_) async {
          fetches++;
          current = false;
          return released;
        },
        accessIsCurrent: () => current,
      );
    }
    await expectLater(check(), throwsStateError);
    expect(fetches, 0);
    current = true;
    await expectLater(check(), throwsStateError);
    expect(fetches, 1);
  });
}
