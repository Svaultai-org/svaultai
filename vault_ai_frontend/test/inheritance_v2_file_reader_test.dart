import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_file_reader.dart';

void main() {
  test('released file decrypts only on beneficiary device', () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 11));
    final beneficiaryPair = await X25519().newKeyPair();
    final beneficiaryPublic = await beneficiaryPair.extractPublicKey();
    final beneficiaryPrivate =
        SecretKey(await beneficiaryPair.extractPrivateKeyBytes());
    final package = (await encryptInheritanceMvk(
      beneficiaryLinkId: 17,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(beneficiaryPublic.bytes),
    ))
        .toRequestBody(17);
    final fileId = FileV2Writer.newFileId();
    final plaintext = Uint8List.fromList('private synthetic file'.codeUnits);
    final prepared = await FileV2Writer(ownerMvk).prepare(
      fileId: fileId,
      fileName: 'example.txt',
      bytes: plaintext,
    );
    final requests = <String>[];
    Future<Map<String, dynamic>> fetch(String path) async {
      requests.add(path);
      if (path.endsWith('/manifest')) {
        return {
          'beneficiary_link_id': 17,
          'owner_vault_id': 'synthetic-owner',
          'file_id': fileId,
          'crypto_version': 'client_mvk_v2',
          'manifest_ciphertext': prepared.manifestCiphertext,
          'total_bytes': prepared.totalBytes,
          'chunk_size': prepared.chunkSize,
          'chunk_count': prepared.chunkCount,
          'lifecycle_state': 'client_v2_ready',
          'verification_state': 'client_verified',
          'name_version': 0,
          'migration_metadata_version': 1,
          'saved_name_override_ciphertext': null,
        };
      }
      if (path.endsWith('/chunk/0')) {
        return {
          'beneficiary_link_id': 17,
          'owner_vault_id': 'synthetic-owner',
          'file_id': fileId,
          'chunk_index': 0,
          'ciphertext': prepared.chunkCiphertexts.single,
        };
      }
      throw StateError('Unexpected inherited route');
    }

    final result = await readReleasedV2File(
      linkId: 17,
      fileId: fileId,
      beneficiaryPrivateKey: beneficiaryPrivate,
      releasedPackage: package,
      fetch: fetch,
      accessIsCurrent: () => true,
    );
    expect(result.manifest.fileName, 'example.txt');
    expect(result.bytes, plaintext);
    expect(requests, [
      '/inheritance/v2/17/files/$fileId/manifest',
      '/inheritance/v2/17/files/$fileId/chunk/0',
    ]);
    expect(requests.join(' '), isNot(contains('private synthetic file')));
  });

  test('wrong owner context fails before any chunk is fetched', () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 11));
    final beneficiaryPair = await X25519().newKeyPair();
    final beneficiaryPublic = await beneficiaryPair.extractPublicKey();
    final beneficiaryPrivate =
        SecretKey(await beneficiaryPair.extractPrivateKeyBytes());
    final package = (await encryptInheritanceMvk(
      beneficiaryLinkId: 17,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(beneficiaryPublic.bytes),
    ))
        .toRequestBody(17);
    var requests = 0;
    await expectLater(
      readReleasedV2File(
        linkId: 17,
        fileId: 'v2-synthetic',
        beneficiaryPrivateKey: beneficiaryPrivate,
        releasedPackage: package,
        fetch: (_) async {
          requests++;
          return {
            'beneficiary_link_id': 17,
            'owner_vault_id': 'another-owner',
          };
        },
        accessIsCurrent: () => true,
      ),
      throwsFormatException,
    );
    expect(requests, 1);
  });
}
