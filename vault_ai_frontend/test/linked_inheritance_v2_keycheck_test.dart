import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/linked_inheritance_v2_keycheck.dart';

const _pkHash =
    '1a92f23852dc908d97316a3b13578281196c1dd73d9ae5e313f3fb6b8954bf55';
const _commitment = 'ujXshrEqpVBexwliWpXJGy8tdZX2RiCFam0G-K409a8';
const _secret = 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8';

Map<String, dynamic> challenge() => {
      'beneficiary_link_id': 41,
      'stage_revision': 1,
      'offer_commitment': _commitment,
      'beneficiary_pk_sha256': _pkHash,
      'expires_at': DateTime.now().toUtc().add(const Duration(minutes: 5)).toIso8601String(),
      'challenge_ephemeral_pk': 'zo060cy2M-x7cMF4FKXHbs0CloUFDTRHRboFhw5YfVk',
      'challenge_nonce': 'AwMDAwMDAwMDAwMD',
      'challenge_ciphertext':
          '6PFiCC3TPX7zIQbD_hBPGVU8-pRrh4lsdfsoJa1n4vHK34ULf1YOGu9qIDyGZU7L',
    };

void main() {
  final beneficiaryPrivateKey = SecretKey(
    Uint8List.fromList(List<int>.filled(32, 1)),
  );

  test('decrypts Python X25519 challenge and submits no owner key or PIN',
      () async {
    Map<String, dynamic>? sent;
    final result = await verifyLinkedBeneficiaryKey(
      linkId: 41,
      beneficiaryPrivateKey: beneficiaryPrivateKey,
      zkProofToken: 'synthetic-proof',
      fetchChallenge: (id) async {
        expect(id, 41);
        return challenge();
      },
      submitResponse: (body) async {
        sent = body;
        return {
          'beneficiary_link_id': 41,
          'stage_revision': 1,
          'offer_commitment': _commitment,
          'beneficiary_key_possession_confirmed': true,
          'package_decryption_verified': false,
          'legacy_link_unchanged': true,
        };
      },
      accessIsCurrent: () => true,
    );
    expect(result.stageRevision, 1);
    expect(sent?['challenge_secret'], _secret);
    expect(sent?.keys, isNot(contains('pin')));
    expect(sent?.keys, isNot(contains('mvk')));
    expect(sent?.keys, isNot(contains('encrypted_payload')));
  });

  test('wrong beneficiary key and tampered stage never submit', () async {
    var submitCalls = 0;
    Future<Map<String, dynamic>> submit(Map<String, dynamic> _) async {
      submitCalls++;
      return {};
    }
    await expectLater(
      verifyLinkedBeneficiaryKey(
        linkId: 41,
        beneficiaryPrivateKey: SecretKey(List<int>.filled(32, 9)),
        zkProofToken: 'synthetic-proof',
        fetchChallenge: (_) async => challenge(),
        submitResponse: submit,
        accessIsCurrent: () => true,
      ),
      throwsStateError,
    );
    await expectLater(
      verifyLinkedBeneficiaryKey(
        linkId: 41,
        beneficiaryPrivateKey: beneficiaryPrivateKey,
        zkProofToken: 'synthetic-proof',
        fetchChallenge: (_) async => {
          ...challenge(),
          'offer_commitment': 'A' * 43,
        },
        submitResponse: submit,
        accessIsCurrent: () => true,
      ),
      throwsA(isA<Exception>()),
    );
    expect(submitCalls, 0);
  });

  test('expired or switched session never submits', () async {
    var submitCalls = 0;
    Future<Map<String, dynamic>> submit(Map<String, dynamic> _) async {
      submitCalls++;
      return {};
    }
    await expectLater(
      verifyLinkedBeneficiaryKey(
        linkId: 41,
        beneficiaryPrivateKey: beneficiaryPrivateKey,
        zkProofToken: 'synthetic-proof',
        fetchChallenge: (_) async => {
          ...challenge(),
          'expires_at': DateTime.now().toUtc().subtract(const Duration(seconds: 1)).toIso8601String(),
        },
        submitResponse: submit,
        accessIsCurrent: () => true,
      ),
      throwsStateError,
    );
    await expectLater(
      verifyLinkedBeneficiaryKey(
        linkId: 41,
        beneficiaryPrivateKey: beneficiaryPrivateKey,
        zkProofToken: 'synthetic-proof',
        fetchChallenge: (_) async => challenge(),
        submitResponse: submit,
        accessIsCurrent: () => false,
      ),
      throwsStateError,
    );
    expect(submitCalls, 0);
  });
}
