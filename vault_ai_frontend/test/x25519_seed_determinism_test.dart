// Verifies that the cryptography package's X25519.newKeyPairFromSeed
// is deterministic for a given seed. This is load-bearing for
// zk_auth_service's inheritance flow, where the wrapped sk_vault
// private key MUST decode into the same X25519 public key across
// unlocks. If the library ever changed to derive-and-throw-away
// semantics, our public keys would drift and inheritance would break.

import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('X25519.newKeyPairFromSeed is deterministic per seed', () async {
    final algo = X25519();
    final seed = Uint8List.fromList(List<int>.generate(32, (i) => i));

    final pair1 = await algo.newKeyPairFromSeed(seed);
    final pk1 = await pair1.extractPublicKey();
    final priv1 = await pair1.extractPrivateKeyBytes();

    final pair2 = await algo.newKeyPairFromSeed(seed);
    final pk2 = await pair2.extractPublicKey();
    final priv2 = await pair2.extractPrivateKeyBytes();

    expect(pk1.bytes, equals(pk2.bytes),
        reason: 'X25519 public key must be deterministic for a given seed');
    expect(priv1, equals(priv2),
        reason: 'X25519 private key must be deterministic for a given seed');
    expect(pk1.bytes.length, 32);
  });

  test('X25519.newKeyPairFromSeed produces different keys for different seeds',
      () async {
    final algo = X25519();
    final s1 = Uint8List.fromList(List<int>.generate(32, (i) => i));
    final s2 = Uint8List.fromList(List<int>.generate(32, (i) => i + 1));
    final p1 = await (await algo.newKeyPairFromSeed(s1)).extractPublicKey();
    final p2 = await (await algo.newKeyPairFromSeed(s2)).extractPublicKey();
    expect(p1.bytes, isNot(equals(p2.bytes)));
  });

  test('AES-GCM round-trip with cryptography package', () async {
    final aead = AesGcm.with256bits();
    final key = await aead.newSecretKey();
    final nonce = aead.newNonce();
    final plaintext = Uint8List.fromList([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    final box = await aead.encrypt(plaintext, secretKey: key, nonce: nonce);
    final decrypted = await aead.decrypt(box, secretKey: key);
    expect(decrypted, equals(plaintext));
  });

  test('HKDF-SHA-256 with disjoint info strings produces disjoint keys',
      () async {
    final hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
    final key = SecretKey(Uint8List.fromList(List<int>.generate(32, (i) => i)));
    final k1 = await hkdf.deriveKey(
      secretKey: key,
      nonce: const [],
      info: [0x76, 0x31], // "v1"
    );
    final k2 = await hkdf.deriveKey(
      secretKey: key,
      nonce: const [],
      info: [0x76, 0x32], // "v2"
    );
    final b1 = await k1.extractBytes();
    final b2 = await k2.extractBytes();
    expect(b1, isNot(equals(b2)));
    expect(b1.length, 32);
  });
}
