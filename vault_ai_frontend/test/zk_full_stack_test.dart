// End-to-end sanity tests for the ZK stack:
//   * inheritance rewrap → beneficiary unwrap
//   * metadata migration client picks the correct ciphertext column
//     names for each table
//   * vault_key_hierarchy: domain-separated subkeys are disjoint
//
// These tests exercise the whole cryptographic composition end-to-
// end without needing a live server or WASM (they use pure Dart
// primitives from the `cryptography` package).

import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/inheritance_rewrap.dart';
import 'package:vault_ai_frontend/services/metadata_migration_client.dart';
import 'package:vault_ai_frontend/services/vault_handle.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

void main() {
  group('inheritance rewrap', () {
    test('passer wrap → beneficiary unwrap yields the same MVK',
        () async {
      final passerMvkBytes = Uint8List.fromList(
        List<int>.generate(32, (i) => (i * 13 + 1) & 0xFF),
      );
      final mvk = SecretKey(passerMvkBytes);

      final algo = X25519();
      final beneficiarySkBytes = Uint8List.fromList(
        List<int>.generate(32, (i) => (i * 17 + 9) & 0xFF),
      );
      final beneficiaryPair =
          await algo.newKeyPairFromSeed(beneficiarySkBytes);
      final beneficiaryPk = await beneficiaryPair.extractPublicKey();

      final envelope = await wrapMvkForBeneficiary(
        mvk: mvk,
        beneficiaryPkVaultPublic: Uint8List.fromList(beneficiaryPk.bytes),
      );

      final restored = await unwrapMvkAsBeneficiary(
        beneficiarySkVaultPrivate: SecretKey(beneficiarySkBytes),
        envelope: envelope,
      );
      expect(await restored.extractBytes(), equals(passerMvkBytes));
    });

    test('beneficiary with different sk cannot unwrap', () async {
      final mvk = SecretKey(Uint8List(32));
      final algo = X25519();
      final legitSk = Uint8List.fromList(
        List<int>.generate(32, (i) => (i * 3 + 1) & 0xFF),
      );
      final impostorSk = Uint8List.fromList(
        List<int>.generate(32, (i) => (i * 3 + 2) & 0xFF),
      );
      final legitPk =
          await (await algo.newKeyPairFromSeed(legitSk)).extractPublicKey();
      final envelope = await wrapMvkForBeneficiary(
        mvk: mvk,
        beneficiaryPkVaultPublic: Uint8List.fromList(legitPk.bytes),
      );
      expectLater(
        unwrapMvkAsBeneficiary(
          beneficiarySkVaultPrivate: SecretKey(impostorSk),
          envelope: envelope,
        ),
        throwsA(isA<Exception>()),
      );
    });
  });

  group('metadata_migration_client', () {
    test('runOnce completes when server returns empty batch', () async {
      Future<Map<String, dynamic>> fakeGet(String path,
          {String? bearerToken}) async {
        if (path.contains('next-batch')) {
          return {'table': '', 'rows': [], 'remaining_estimate': 0};
        }
        if (path.contains('status')) {
          return {
            'completed_tables': ['uploaded_files', 'vault_items',
              'notifications', 'vault_ai_memory'],
            'pending_tables': [],
            'completed_at': '2026-07-14T12:00:00Z',
          };
        }
        return {};
      }

      Future<Map<String, dynamic>> fakePost(
        String path,
        Map<String, dynamic> body, {
        String? bearerToken,
      }) async => {'applied': 0, 'skipped': 0};

      final client = MetadataMigrationClient(
        mvk: SecretKey(Uint8List(32)),
        sessionToken: 'unused',
        post: fakePost,
        get: fakeGet,
      );
      final result = await client.runOnce();
      expect(result.completed, isTrue);
      expect(result.batchesApplied, 0);
    });

    test('runOnce encrypts rows and posts ciphertext', () async {
      final calls = <Map<String, dynamic>>[];
      int getCount = 0;

      Future<Map<String, dynamic>> fakeGet(String path,
          {String? bearerToken}) async {
        getCount++;
        if (path.contains('next-batch')) {
          if (getCount == 1) {
            return {
              'table': 'uploaded_files',
              'rows': [
                {
                  'row_id': 'abc123',
                  'plaintext': {
                    'file_name': 'passport.pdf',
                    'saved_name': 'My Passport',
                  }
                }
              ],
              'remaining_estimate': 1,
            };
          }
          return {'table': '', 'rows': [], 'remaining_estimate': 0};
        }
        return {
          'completed_tables': [],
          'pending_tables': ['uploaded_files'],
          'completed_at': null,
        };
      }

      Future<Map<String, dynamic>> fakePost(
        String path,
        Map<String, dynamic> body, {
        String? bearerToken,
      }) async {
        calls.add(body);
        return {'applied': 1, 'skipped': 0};
      }

      final client = MetadataMigrationClient(
        mvk: SecretKey(Uint8List.fromList(
          List<int>.generate(32, (i) => (i * 5) & 0xFF),
        )),
        sessionToken: 'unused',
        post: fakePost,
        get: fakeGet,
      );
      final result = await client.runOnce();
      expect(result.batchesApplied, 1);
      expect(result.rowsApplied, 1);
      expect(calls.length, 1);

      final body = calls.first;
      expect(body['table'], 'uploaded_files');
      final rows = body['rows'] as List;
      expect(rows.length, 1);
      final row = rows.first as Map;
      expect(row['row_id'], 'abc123');
      final ct = row['ciphertext'] as Map;
      expect(ct.containsKey('file_name_ciphertext'), isTrue);
      expect(ct.containsKey('saved_name_ciphertext'), isTrue);
      // Ciphertext value MUST NOT equal the plaintext.
      expect(ct['file_name_ciphertext'], isNot(equals('passport.pdf')));
    });
  });

  group('vault_key_hierarchy domain separation', () {
    test('metadata / memory / display keys are pairwise disjoint',
        () async {
      final mvk = SecretKey(
        Uint8List.fromList(List<int>.generate(32, (i) => (i * 3 + 7) & 0xFF)),
      );
      final h = VaultKeyHierarchy(mvk);
      final k1 = await h.metadataKey();
      final k2 = await h.memoryKey();
      final k3 = await h.displayNameKey();
      final k4 = await h.semanticLookupKey();
      final b1 = await k1.extractBytes();
      final b2 = await k2.extractBytes();
      final b3 = await k3.extractBytes();
      final b4 = await k4.extractBytes();
      expect(b1, isNot(equals(b2)));
      expect(b1, isNot(equals(b3)));
      expect(b2, isNot(equals(b3)));
      expect(b1, isNot(equals(b4)));
    });
  });

  group('vault_handle interop with legacy adoption keying', () {
    test('handle round-trips via display and via credential id', () {
      final raw = generateVaultHandle();
      final disp = vaultHandleToDisplay(raw);
      expect(vaultHandleFromDisplay(disp), equals(raw));
      final credentialId = vaultHandleCredentialId(raw);
      // credential id must be base64url of the handle bytes — the
      // same value the backend derives.
      expect(credentialId, equals(vaultHandleB64Url(raw)));
    });
  });
}
