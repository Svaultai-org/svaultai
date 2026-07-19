// Client-side crypto round-trip for the inheritance credential
// escrow. Encrypts a fixed username + PIN against a synthesized
// beneficiary X25519 keypair, uploads-shaped map is generated, then
// the beneficiary side unwraps to prove the wire format works.
//
// Also asserts the ciphertext never leaks either plaintext byte.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/inheritance_credentials.dart'
    as inh;

void main() {
  group('inheritance credential escrow — round trip', () {
    test('owner wraps → beneficiary unwraps to identical plaintext',
        () async {
      // Synthesized beneficiary keypair (deterministic seed for
      // repeatability — this is a test-only path).
      final algo = X25519();
      final seed = Uint8List.fromList(
        List<int>.generate(32, (i) => (i * 7 + 11) & 0xFF),
      );
      final kp = await algo.newKeyPairFromSeed(seed);
      final pk = await kp.extractPublicKey();

      final pkg = await inh.encryptInheritanceCredentials(
        username: 'Alexa',
        pin: '89262828',
        beneficiaryPkVaultPublic: Uint8List.fromList(pk.bytes),
      );

      final restored = await inh.decryptInheritanceCredentials(
        beneficiarySkVaultPrivate: seed,
        package: pkg,
      );

      expect(restored.version, inh.credentialsCryptoVersion);
      expect(restored.username, 'Alexa');
      expect(restored.pin, '89262828');
      expect(restored.createdAtIso, isNotEmpty);
    });

    test('ciphertext never contains the plaintext bytes', () async {
      final algo = X25519();
      final seed = Uint8List.fromList(
        List<int>.generate(32, (i) => (i * 5 + 3) & 0xFF),
      );
      final kp = await algo.newKeyPairFromSeed(seed);
      final pk = await kp.extractPublicKey();

      final pkg = await inh.encryptInheritanceCredentials(
        username: 'DistinctivePlaintextForTest',
        pin: '55511122333',
        beneficiaryPkVaultPublic: Uint8List.fromList(pk.bytes),
      );

      // b64url-decode every wire-visible byte string; the concatenated
      // bytes must not contain either the raw username or PIN as an
      // ASCII substring.
      Uint8List _dec(String s) {
        final padded = s + '=' * ((4 - s.length % 4) % 4);
        return base64Url.decode(padded);
      }
      final buffer = BytesBuilder()
        ..add(_dec(pkg.encryptedPayloadB64Url))
        ..add(_dec(pkg.payloadNonceB64Url))
        ..add(_dec(pkg.wrappedKeyB64Url))
        ..add(_dec(pkg.wrappingEphemeralPkB64Url))
        ..add(_dec(pkg.wrappingNonceB64Url));
      final wire = buffer.toBytes();
      final wireAscii = String.fromCharCodes(wire);

      expect(
        wireAscii.contains('DistinctivePlaintextForTest'),
        isFalse,
        reason:
            'the encrypted wire form must not contain the username '
            'as an ASCII substring',
      );
      expect(
        wireAscii.contains('55511122333'),
        isFalse,
        reason:
            'the encrypted wire form must not contain the PIN as an '
            'ASCII substring',
      );
    });

    test('wrong beneficiary sk cannot unwrap', () async {
      final algo = X25519();
      final legitSeed = Uint8List.fromList(
        List<int>.generate(32, (i) => (i + 1) & 0xFF),
      );
      final impostorSeed = Uint8List.fromList(
        List<int>.generate(32, (i) => (i + 2) & 0xFF),
      );
      final legit = await algo.newKeyPairFromSeed(legitSeed);
      final legitPk = await legit.extractPublicKey();

      final pkg = await inh.encryptInheritanceCredentials(
        username: 'Alexa',
        pin: '89262828',
        beneficiaryPkVaultPublic: Uint8List.fromList(legitPk.bytes),
      );

      expectLater(
        inh.decryptInheritanceCredentials(
          beneficiarySkVaultPrivate: impostorSeed,
          package: pkg,
        ),
        throwsA(anything),
      );
    });

    test('to-request body carries the six wire fields plus the link id',
        () async {
      final algo = X25519();
      final seed = Uint8List(32);
      final kp = await algo.newKeyPairFromSeed(seed);
      final pk = await kp.extractPublicKey();

      final pkg = await inh.encryptInheritanceCredentials(
        username: 'u',
        pin: '1111',
        beneficiaryPkVaultPublic: Uint8List.fromList(pk.bytes),
      );

      final body = pkg.toRequestBody(beneficiaryLinkId: 42);
      expect(body['beneficiary_link_id'], 42);
      expect(body['crypto_version'], 1);
      for (final k in const [
        'encrypted_payload',
        'payload_nonce',
        'wrapped_key',
        'wrapping_ephemeral_pk',
        'wrapping_nonce',
      ]) {
        expect(body[k], isA<String>());
        expect((body[k] as String).isNotEmpty, isTrue);
      }
    });
  });
}
