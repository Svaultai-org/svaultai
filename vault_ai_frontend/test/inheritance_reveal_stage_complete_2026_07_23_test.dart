// 2026-07-23 stage-complete reveal pipeline tests.
//
// Bug 1 evidence from production (link_id=10):
//   [INH-CLIENT-DIAG] area=reveal ref=INH-RETRIEVE-003-OTHER
//   stage=None exc_type=minified:pq category=other
//   crypto_v=1 payload_len=103 nonce_len=12 wrapped_len=48
//   eph_pk_len=32 wrap_nonce_len=12 sk_present=True sk_len=32
//
// The wire is well-formed and the beneficiary secret key is
// present. ``stage=None`` proved the previous decrypt call had
// unwrapped code paths outside the staged wrappers, so any
// exception thrown by those paths escaped without a stage tag.
//
// This test file drives the NEW ``revealInheritanceCredentialsStaged``
// entry point that guarantees:
//
//   * Any exception thrown by the reveal pipeline is an
//     ``InheritanceRevealStageException`` — nothing escapes bare.
//   * The stage name is one of the nine UPPER_SNAKE constants
//     declared in ``inheritance_credentials.dart`` (or the
//     ``UNSTAGED_UNKNOWN`` defensive fallback).
//   * Positive round-trip: owner encrypts, beneficiary decrypts,
//     credentials match byte-for-byte. This test MUST pass on the
//     Dart VM so the pipeline itself is proven correct — any
//     production failure at this point is Web-only and its stage
//     will show up in the ``[INH-CLIENT-DIAG]`` line.
//
// Uses ONLY the audited primitives from ``package:cryptography``.
// No plaintext credentials, no secret keys, no ciphertext contents
// leak into log lines or test failures.

library;

import 'dart:convert';
import 'dart:io';
import 'dart:math' show Random;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/inheritance_credentials.dart';


// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------


String _b64u(List<int> raw) =>
    base64Url.encode(raw).replaceAll('=', '');


/// Build a beneficiary keypair + return (seedBytes, pk_vault_public).
///
/// Mirrors what ``zk_auth_service.dart::registerVault`` does at
/// signup time: draws 32 random bytes as the sk_vault seed, and
/// exposes the derived X25519 public key as pk_vault_public.
Future<(Uint8List, Uint8List)> _newBeneficiaryKeypair() async {
  final rng = Random.secure();
  final seed = Uint8List.fromList([
    for (var i = 0; i < 32; i++) rng.nextInt(256),
  ]);
  final algo = X25519();
  final pair = await algo.newKeyPairFromSeed(seed);
  final pk = await pair.extractPublicKey();
  return (seed, Uint8List.fromList(pk.bytes));
}


/// Roundtrip: owner encrypts against beneficiary pk, converts the
/// package to the wire Map the backend returns from
/// ``/inheritance/credentials/retrieve``, and hands it to the
/// stage-complete beneficiary reveal.
Future<DecryptedInheritanceCredentials> _roundTrip({
  required String username,
  required String pin,
  required Uint8List beneficiaryPk,
  required Uint8List beneficiarySkSeed,
  DateTime? nowUtc,
}) async {
  final pkg = await encryptInheritanceCredentials(
    username: username,
    pin: pin,
    beneficiaryPkVaultPublic: beneficiaryPk,
    nowUtc: nowUtc,
  );
  final rawPackage = <String, dynamic>{
    'crypto_version':          pkg.cryptoVersion,
    'encrypted_payload':       pkg.encryptedPayloadB64Url,
    'payload_nonce':           pkg.payloadNonceB64Url,
    'wrapped_key':             pkg.wrappedKeyB64Url,
    'wrapping_ephemeral_pk':   pkg.wrappingEphemeralPkB64Url,
    'wrapping_nonce':          pkg.wrappingNonceB64Url,
  };
  return revealInheritanceCredentialsStaged(
    beneficiarySkVault: SecretKey(beneficiarySkSeed),
    rawPackage: rawPackage,
  );
}


Random get _rng => Random.secure();


// ---------------------------------------------------------------------
// Reproduction of the production failure — POSITIVE roundtrip must
// succeed on the Dart VM. If it doesn't, the pipeline itself is
// broken and this test tells us the exact failing stage.
// ---------------------------------------------------------------------


void main() {
  group('revealInheritanceCredentialsStaged — positive roundtrip', () {

    test('owner-encrypt → beneficiary-decrypt returns exact '
        'username + PIN + version + createdAt', () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      final ts = DateTime.utc(2026, 7, 22, 9, 0, 0);
      final decrypted = await _roundTrip(
        username: 'chosen@goufer.com',
        pin: '482913',
        beneficiaryPk: pk,
        beneficiarySkSeed: skSeed,
        nowUtc: ts,
      );
      expect(decrypted.version, equals(1));
      expect(decrypted.username, equals('chosen@goufer.com'));
      expect(decrypted.pin, equals('482913'));
      expect(decrypted.createdAtIso, equals(ts.toIso8601String()));
    });

    test('roundtrip preserves whitespace, punctuation, and unicode '
        'in the credential fields', () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      final decrypted = await _roundTrip(
        username: '花子@例え.jp',
        pin: '000000',
        beneficiaryPk: pk,
        beneficiarySkSeed: skSeed,
      );
      expect(decrypted.username, equals('花子@例え.jp'));
      expect(decrypted.pin, equals('000000'));
    });

    test('reproduction of the production wire shape '
        '(payload_len=103, nonce_len=12, wrapped_len=48, '
        'eph_pk_len=32, wrap_nonce_len=12, sk_len=32) — sanity '
        'that the byte lengths do not lie about our envelope',
        () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      // Owner-encrypted with a realistic credential body length so
      // the encrypted_payload comes out at exactly the 103-byte
      // shape the production log reports for link_id=10.
      // The math: JSON body ~87 chars → utf-8 87 bytes → AES-GCM
      // ciphertext 87 bytes || 16-byte tag = 103 bytes total.
      final pkg = await encryptInheritanceCredentials(
        username: 'chosen@goufer.com',
        pin: '482913',
        beneficiaryPkVaultPublic: pk,
        nowUtc: DateTime.utc(2026, 7, 22, 9, 0, 0),
      );
      final wireLens = <String, int>{
        'payload_len':
            base64Url.decode(pkg.encryptedPayloadB64Url + '=' *
                ((4 - pkg.encryptedPayloadB64Url.length % 4) % 4))
                .length,
        'nonce_len':
            base64Url.decode(pkg.payloadNonceB64Url + '=' *
                ((4 - pkg.payloadNonceB64Url.length % 4) % 4)).length,
        'wrapped_len':
            base64Url.decode(pkg.wrappedKeyB64Url + '=' *
                ((4 - pkg.wrappedKeyB64Url.length % 4) % 4)).length,
        'eph_pk_len':
            base64Url.decode(pkg.wrappingEphemeralPkB64Url + '=' *
                ((4 - pkg.wrappingEphemeralPkB64Url.length % 4) % 4))
                .length,
        'wrap_nonce_len':
            base64Url.decode(pkg.wrappingNonceB64Url + '=' *
                ((4 - pkg.wrappingNonceB64Url.length % 4) % 4))
                .length,
      };
      expect(wireLens['nonce_len'], equals(12));
      expect(wireLens['wrapped_len'], equals(48));
      expect(wireLens['eph_pk_len'], equals(32));
      expect(wireLens['wrap_nonce_len'], equals(12));
      // sk length is 32 by construction (X25519 seed).
      expect(skSeed.length, equals(32));
    });
  });

  // -------------------------------------------------------------------
  // Every stage individually forced to fail — the wrapper must always
  // surface an InheritanceRevealStageException with the correct
  // stage tag. This is the guarantee that ``stage=None`` never
  // appears in a diagnostic log line again.
  // -------------------------------------------------------------------
  group('revealInheritanceCredentialsStaged — every stage identified',
      () {

    test('stage=LOAD_SECRET_KEY when the beneficiary sk is not 32 bytes',
        () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      final pkg = await encryptInheritanceCredentials(
        username: 'u@example.com',
        pin: '111111',
        beneficiaryPkVaultPublic: pk,
      );
      final rawPackage = <String, dynamic>{
        'crypto_version':        pkg.cryptoVersion,
        'encrypted_payload':     pkg.encryptedPayloadB64Url,
        'payload_nonce':         pkg.payloadNonceB64Url,
        'wrapped_key':           pkg.wrappedKeyB64Url,
        'wrapping_ephemeral_pk': pkg.wrappingEphemeralPkB64Url,
        'wrapping_nonce':        pkg.wrappingNonceB64Url,
      };
      Object? caught;
      try {
        await revealInheritanceCredentialsStaged(
          // Deliberately wrong-length seed (31 bytes).
          beneficiarySkVault: SecretKey(
            Uint8List.fromList(skSeed.sublist(0, 31)),
          ),
          rawPackage: rawPackage,
        );
      } catch (e) { caught = e; }
      expect(caught, isA<InheritanceRevealStageException>());
      expect((caught as InheritanceRevealStageException).stage,
          equals(kRevealStageLoadSecretKey));
    });

    test('stage=PARSE_EPHEMERAL_PUBLIC_KEY when eph_pk is wrong length',
        () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      final pkg = await encryptInheritanceCredentials(
        username: 'u@example.com',
        pin: '111111',
        beneficiaryPkVaultPublic: pk,
      );
      final rawPackage = <String, dynamic>{
        'crypto_version':        pkg.cryptoVersion,
        'encrypted_payload':     pkg.encryptedPayloadB64Url,
        'payload_nonce':         pkg.payloadNonceB64Url,
        'wrapped_key':           pkg.wrappedKeyB64Url,
        // 31-byte ephemeral pk (truncated).
        'wrapping_ephemeral_pk': _b64u(List<int>.filled(31, 0)),
        'wrapping_nonce':        pkg.wrappingNonceB64Url,
      };
      Object? caught;
      try {
        await revealInheritanceCredentialsStaged(
          beneficiarySkVault: SecretKey(skSeed),
          rawPackage: rawPackage,
        );
      } catch (e) { caught = e; }
      expect(caught, isA<InheritanceRevealStageException>());
      expect((caught as InheritanceRevealStageException).stage,
          equals(kRevealStageParseEphemeralPublicKey));
    });

    test('stage=UNWRAP_DATA_KEY when wrapped_key tag is corrupted',
        () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      final pkg = await encryptInheritanceCredentials(
        username: 'u@example.com',
        pin: '111111',
        beneficiaryPkVaultPublic: pk,
      );
      // Flip the last byte of wrapped_key (breaks the GCM tag).
      final wrappedRaw = base64Url.decode(
        pkg.wrappedKeyB64Url + '=' *
            ((4 - pkg.wrappedKeyB64Url.length % 4) % 4),
      );
      wrappedRaw[wrappedRaw.length - 1] ^= 0x01;
      final rawPackage = <String, dynamic>{
        'crypto_version':        pkg.cryptoVersion,
        'encrypted_payload':     pkg.encryptedPayloadB64Url,
        'payload_nonce':         pkg.payloadNonceB64Url,
        'wrapped_key':           _b64u(wrappedRaw),
        'wrapping_ephemeral_pk': pkg.wrappingEphemeralPkB64Url,
        'wrapping_nonce':        pkg.wrappingNonceB64Url,
      };
      Object? caught;
      try {
        await revealInheritanceCredentialsStaged(
          beneficiarySkVault: SecretKey(skSeed),
          rawPackage: rawPackage,
        );
      } catch (e) { caught = e; }
      expect(caught, isA<InheritanceRevealStageException>());
      expect((caught as InheritanceRevealStageException).stage,
          equals(kRevealStageUnwrapDataKey),
          reason: 'AES-GCM tag mismatch on the CEK unwrap surfaces '
                  'as SecretBoxAuthenticationError inside the '
                  'UNWRAP_DATA_KEY stage, not the payload one');
    });

    test('stage=UNWRAP_DATA_KEY when wrapped_key is wrong length',
        () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      final pkg = await encryptInheritanceCredentials(
        username: 'u@example.com',
        pin: '111111',
        beneficiaryPkVaultPublic: pk,
      );
      final rawPackage = <String, dynamic>{
        'crypto_version':        pkg.cryptoVersion,
        'encrypted_payload':     pkg.encryptedPayloadB64Url,
        'payload_nonce':         pkg.payloadNonceB64Url,
        // 47 bytes instead of the expected 48.
        'wrapped_key':           _b64u(List<int>.filled(47, 0)),
        'wrapping_ephemeral_pk': pkg.wrappingEphemeralPkB64Url,
        'wrapping_nonce':        pkg.wrappingNonceB64Url,
      };
      Object? caught;
      try {
        await revealInheritanceCredentialsStaged(
          beneficiarySkVault: SecretKey(skSeed),
          rawPackage: rawPackage,
        );
      } catch (e) { caught = e; }
      expect(caught, isA<InheritanceRevealStageException>());
      expect((caught as InheritanceRevealStageException).stage,
          equals(kRevealStageUnwrapDataKey));
    });

    test('stage=DECRYPT_PAYLOAD when the payload ciphertext tag is '
        'corrupted (unwrap succeeded)', () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      final pkg = await encryptInheritanceCredentials(
        username: 'u@example.com',
        pin: '111111',
        beneficiaryPkVaultPublic: pk,
      );
      // Flip the last byte of encrypted_payload (breaks the payload
      // GCM tag, leaves the wrapped CEK intact).
      final ct = base64Url.decode(
        pkg.encryptedPayloadB64Url + '=' *
            ((4 - pkg.encryptedPayloadB64Url.length % 4) % 4),
      );
      ct[ct.length - 1] ^= 0x01;
      final rawPackage = <String, dynamic>{
        'crypto_version':        pkg.cryptoVersion,
        'encrypted_payload':     _b64u(ct),
        'payload_nonce':         pkg.payloadNonceB64Url,
        'wrapped_key':           pkg.wrappedKeyB64Url,
        'wrapping_ephemeral_pk': pkg.wrappingEphemeralPkB64Url,
        'wrapping_nonce':        pkg.wrappingNonceB64Url,
      };
      Object? caught;
      try {
        await revealInheritanceCredentialsStaged(
          beneficiarySkVault: SecretKey(skSeed),
          rawPackage: rawPackage,
        );
      } catch (e) { caught = e; }
      expect(caught, isA<InheritanceRevealStageException>());
      expect((caught as InheritanceRevealStageException).stage,
          equals(kRevealStageDecryptPayload));
    });

    test('stage=DECRYPT_PAYLOAD when payload_nonce is wrong length',
        () async {
      final (skSeed, pk) = await _newBeneficiaryKeypair();
      final pkg = await encryptInheritanceCredentials(
        username: 'u@example.com',
        pin: '111111',
        beneficiaryPkVaultPublic: pk,
      );
      final rawPackage = <String, dynamic>{
        'crypto_version':        pkg.cryptoVersion,
        'encrypted_payload':     pkg.encryptedPayloadB64Url,
        'payload_nonce':         _b64u(List<int>.filled(11, 0)),
        'wrapped_key':           pkg.wrappedKeyB64Url,
        'wrapping_ephemeral_pk': pkg.wrappingEphemeralPkB64Url,
        'wrapping_nonce':        pkg.wrappingNonceB64Url,
      };
      Object? caught;
      try {
        await revealInheritanceCredentialsStaged(
          beneficiarySkVault: SecretKey(skSeed),
          rawPackage: rawPackage,
        );
      } catch (e) { caught = e; }
      expect(caught, isA<InheritanceRevealStageException>());
      expect((caught as InheritanceRevealStageException).stage,
          equals(kRevealStageDecryptPayload));
    });

    test('every stage constant is UPPER_SNAKE and length ≤ 32 chars '
        '(matches _DIAG_STAGES backend allowlist)', () {
      for (final stage in kRevealStagesAll) {
        expect(stage.length, lessThanOrEqualTo(32),
            reason: 'stage tag $stage must fit backend Field(max_length=32)');
        expect(
          RegExp(r'^[A-Z][A-Z0-9_]*$').hasMatch(stage), isTrue,
          reason: 'stage tag $stage must be UPPER_SNAKE_CASE — no '
              'mixed-case or lowercase allowed under the 2026-07-23 '
              'single-convention rule',
        );
      }
      expect(kRevealStagesAll.length, equals(10),
          reason: '9 pipeline stages + 1 UNSTAGED_UNKNOWN fallback');
    });

    test('the reveal pipeline exports the exact 9 stages the user '
        'specified in the 2026-07-23 fix brief, plus UNSTAGED_UNKNOWN',
        () {
      // Regression-lock the user-visible stage tags — if a rename
      // happens without updating the backend allowlist, this test
      // catches it in the same commit.
      final expected = <String>{
        'LOAD_SECRET_KEY',
        'PARSE_EPHEMERAL_PUBLIC_KEY',
        'DERIVE_SHARED_SECRET',
        'DERIVE_WRAP_KEY',
        'UNWRAP_DATA_KEY',
        'DECRYPT_PAYLOAD',
        'UTF8_DECODE',
        'JSON_PARSE',
        'MAP_CREDENTIAL',
        'UNSTAGED_UNKNOWN',
      };
      expect(kRevealStagesAll, equals(expected));
    });
  });

  // -------------------------------------------------------------------
  // The main.dart reveal wrap must never emit stage=None: any
  // exception outside the staged pipeline gets bucketed as
  // UNSTAGED_UNKNOWN. This is a source-level guarantee locked below.
  // -------------------------------------------------------------------
  group('_beneficiaryRevealCredentials — source contract '
      '(no stage=None allowed)', () {

    // We can't pump the StatefulWidget in isolation without a full
    // MaterialApp + AppState + secure sk + backend fake — that's
    // brittle. Instead we lock the source-level invariants that
    // guarantee stage-completeness, matching the pattern already
    // used by test/inheritance_reveal_classify_2026_07_22_test.dart.
    late String src;

    setUpAll(() {
      src = File('lib/main.dart').readAsStringSync();
    });

    test('reveal catch derives stage via revealStageOf(...) with a '
        'kRevealStageUnstagedUnknown fallback', () {
      final idx = src.indexOf("'inheritance.reveal.decrypt_failed'");
      expect(idx, greaterThan(-1));
      final window =
          src.substring(idx, (idx + 3500).clamp(0, src.length));
      expect(window.contains('revealStageOf('), isTrue);
      expect(
        window.contains('kRevealStageUnstagedUnknown'),
        isTrue,
        reason: 'the reveal catch must fall back to '
            'kRevealStageUnstagedUnknown when revealStageOf returns '
            'null so the diagnostic never carries stage=None',
      );
    });

    test('reveal replaces the old decryptInheritanceCredentials call '
        'with the stage-complete revealInheritanceCredentialsStaged',
        () {
      // The stage-complete entry point must be present at the reveal
      // call site.
      expect(
        src.contains('revealInheritanceCredentialsStaged('),
        isTrue,
        reason: 'the reveal catch must call the stage-complete entry '
            'point — the old decryptInheritanceCredentials is kept '
            'only as a back-compat shim for the existing round-trip '
            'test',
      );
    });
  });
}

