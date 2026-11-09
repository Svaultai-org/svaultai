import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';

void main() {
  test('owner to beneficiary MVK envelope round trips without a PIN', () async {
    final beneficiary = await X25519().newKeyPair();
    final publicKey = await beneficiary.extractPublicKey();
    final privateKey = await beneficiary.extractPrivateKeyBytes();
    final ownerMvk = SecretKey(List<int>.generate(32, (i) => i + 1));
    final envelope = await encryptInheritanceMvk(
      beneficiaryLinkId: 17,
      ownerVaultId: 'synthetic-owner-vault',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
    );
    final body = envelope.toRequestBody(17);
    final serialized = jsonEncode(body);
    expect(body.containsKey('pin'), isFalse);
    expect(body.containsKey('username'), isFalse);
    expect(serialized.contains(base64Url.encode(await ownerMvk.extractBytes())),
        isFalse);
    final recovered = await decryptInheritanceMvk(
      expectedLinkId: 17,
      beneficiaryPrivateKey: SecretKey(privateKey),
      rawPackage: body,
    );
    expect(recovered.ownerVaultId, 'synthetic-owner-vault');
    expect(
        await recovered.ownerMvk.extractBytes(), await ownerMvk.extractBytes());
    expect(recovered.ownerLegacyKey, isNull);
  });

  test('old-link envelope carries a separate source key only inside ciphertext',
      () async {
    final beneficiary = await X25519().newKeyPair();
    final publicKey = await beneficiary.extractPublicKey();
    final ownerMvk = SecretKey(List<int>.filled(32, 27));
    final ownerLegacyKey = SecretKey([
      ...utf8.encode('123456'), ...List<int>.filled(26, 61),
    ]);
    final envelope = await encryptInheritanceMvk(
      beneficiaryLinkId: 93,
      ownerVaultId: 'synthetic-old-owner',
      ownerMvk: ownerMvk,
      ownerLegacyKey: ownerLegacyKey,
      beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
    );
    final body = envelope.toRequestBody(93);
    final wire = jsonEncode(body);
    expect(body.keys, isNot(contains('pin')));
    expect(body.keys, isNot(contains('owner_legacy_key')));
    expect(wire, isNot(contains('123456')));
    expect(wire, isNot(contains(base64Url.encode(
      await ownerLegacyKey.extractBytes(),
    ).replaceAll('=', ''))));
    final recovered = await decryptInheritanceMvk(
      expectedLinkId: 93,
      beneficiaryPrivateKey: SecretKey(
        await beneficiary.extractPrivateKeyBytes(),
      ),
      rawPackage: body,
    );
    expect(await recovered.ownerLegacyKey!.extractBytes(),
        await ownerLegacyKey.extractBytes());
    await expectLater(
      encryptInheritanceMvk(
        beneficiaryLinkId: 93,
        ownerVaultId: 'synthetic-old-owner',
        ownerMvk: ownerMvk,
        ownerLegacyKey: SecretKey([1, 2, 3]),
        beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
      ),
      throwsStateError,
    );
  });

  test('wrong beneficiary, changed link and tampered envelope fail closed',
      () async {
    final beneficiary = await X25519().newKeyPair();
    final publicKey = await beneficiary.extractPublicKey();
    final privateKey = await beneficiary.extractPrivateKeyBytes();
    final wrongKey = await X25519().newKeyPair();
    final envelope = await encryptInheritanceMvk(
      beneficiaryLinkId: 17,
      ownerVaultId: 'synthetic-owner-vault',
      ownerMvk: SecretKey(List<int>.filled(32, 7)),
      beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
    );
    final body = envelope.toRequestBody(17);
    await expectLater(
      decryptInheritanceMvk(
        expectedLinkId: 18,
        beneficiaryPrivateKey: SecretKey(privateKey),
        rawPackage: body,
      ),
      throwsFormatException,
    );
    await expectLater(
      decryptInheritanceMvk(
        expectedLinkId: 17,
        beneficiaryPrivateKey:
            SecretKey(await wrongKey.extractPrivateKeyBytes()),
        rawPackage: body,
      ),
      throwsA(isA<SecretBoxAuthenticationError>()),
    );
    final tampered = Map<String, dynamic>.from(body);
    tampered['encrypted_payload'] =
        '${(tampered['encrypted_payload'] as String).substring(0, 10)}A'
        '${(tampered['encrypted_payload'] as String).substring(11)}';
    await expectLater(
      decryptInheritanceMvk(
        expectedLinkId: 17,
        beneficiaryPrivateKey: SecretKey(privateKey),
        rawPackage: tampered,
      ),
      throwsA(anything),
    );
  });

  test('independent beneficiary key fingerprint matches only full local key',
      () async {
    final beneficiary = await X25519().newKeyPair();
    final publicKey = await beneficiary.extractPublicKey();
    final privateKey = SecretKey(await beneficiary.extractPrivateKeyBytes());
    final local = await beneficiaryPrivateKeyFingerprint(privateKey);
    final fetched = await beneficiaryPublicKeyFingerprint(
      Uint8List.fromList(publicKey.bytes),
    );
    expect(local, fetched);
    expect(local.replaceAll('-', '').length, 64);
    expect(beneficiaryFingerprintMatches(fetched, local), isTrue);
    expect(beneficiaryFingerprintMatches(fetched, local.substring(0, 20)),
        isFalse);
    final other = await X25519().newKeyPair();
    final otherFingerprint = await beneficiaryPublicKeyFingerprint(
      Uint8List.fromList((await other.extractPublicKey()).bytes),
    );
    expect(beneficiaryFingerprintMatches(fetched, otherFingerprint), isFalse);
  });
}
