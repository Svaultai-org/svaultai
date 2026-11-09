import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_file_stage.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_file_reader.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

void main() {
  test('inherited file staging re-encrypts for beneficiary without writes',
      () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 11));
    final beneficiaryMvk = SecretKey(List<int>.filled(32, 22));
    final pair = await X25519().newKeyPair();
    final publicKey = await pair.extractPublicKey();
    final privateKey = SecretKey(await pair.extractPrivateKeyBytes());
    final package = (await encryptInheritanceMvk(
      beneficiaryLinkId: 17,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
    ))
        .toRequestBody(17);
    final sourceId = FileV2Writer.newFileId();
    final sourceBytes = Uint8List.fromList('synthetic private file'.codeUnits);
    final source = await FileV2Writer(ownerMvk).prepare(
      fileId: sourceId,
      fileName: 'example.txt',
      savedName: 'Private example',
      contentType: 'text/plain',
      relativePath: 'folder/example.txt',
      bytes: sourceBytes,
    );
    final requests = <String>[];
    Future<Map<String, dynamic>> fetch(String path) async {
      requests.add(path);
      if (path.endsWith('/manifest')) {
        return {
          'beneficiary_link_id': 17,
          'owner_vault_id': 'synthetic-owner',
          'file_id': sourceId,
          'crypto_version': 'client_mvk_v2',
          'manifest_ciphertext': source.manifestCiphertext,
          'total_bytes': source.totalBytes,
          'chunk_size': source.chunkSize,
          'chunk_count': source.chunkCount,
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
          'file_id': sourceId,
          'chunk_index': 0,
          'ciphertext': source.chunkCiphertexts.single,
        };
      }
      throw StateError('Unexpected ciphertext request');
    }

    Future<PreparedInheritedV2File> stage() => prepareInheritedV2File(
          linkId: 17,
          sourceFileId: sourceId,
          beneficiaryPrivateKey: privateKey,
          beneficiaryMvk: beneficiaryMvk,
          releasedPackage: package,
          fetch: fetch,
          accessIsCurrent: () => true,
        );
    final first = await stage();
    final second = await stage();
    expect(first.prepared.fileId, second.prepared.fileId);
    expect(first.prepared.fileId, isNot(sourceId));
    expect(first.prepared.totalBytes, sourceBytes.length);
    expect(
        requests.every((request) => request.startsWith(
              '/inheritance/v2/17/files/$sourceId/',
            )),
        isTrue);
    expect(requests.join(' '), isNot(contains('synthetic private file')));

    Future<Map<String, dynamic>> stagedGet(String path) async {
      if (path.endsWith('/manifest')) {
        return {
          'file_id': first.prepared.fileId,
          'crypto_version': 'client_mvk_v2',
          'manifest_ciphertext': first.prepared.manifestCiphertext,
          'total_bytes': first.prepared.totalBytes,
          'chunk_size': first.prepared.chunkSize,
          'chunk_count': first.prepared.chunkCount,
          'lifecycle_state': 'file_v2_written',
          'verification_state': 'not_verified',
          'name_version': 0,
          'migration_metadata_version': 1,
          'saved_name_override_ciphertext': null,
        };
      }
      return {
        'file_id': first.prepared.fileId,
        'chunk_index': 0,
        'ciphertext': first.prepared.chunkCiphertexts.single,
      };
    }

    final recipientReadback = await FileV2Reader(
      mvk: beneficiaryMvk,
      get: stagedGet,
    ).download(first.prepared.fileId);
    expect(recipientReadback.bytes, sourceBytes);
    expect(recipientReadback.manifest.fileName, 'example.txt');
    expect(recipientReadback.manifest.savedName, 'Private example');
    expect(recipientReadback.manifest.relativePath, 'folder/example.txt');
    await expectLater(
      FileV2Reader(mvk: ownerMvk, get: stagedGet)
          .download(first.prepared.fileId),
      throwsA(isA<SecretBoxAuthenticationError>()),
    );
    first.clearSourceBytes();
    second.clearSourceBytes();
    expect(first.sourceBytes.every((value) => value == 0), isTrue);
  });

  test('staging rejects an oversized file before requesting any chunk',
      () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 31));
    final beneficiaryMvk = SecretKey(List<int>.filled(32, 41));
    final pair = await X25519().newKeyPair();
    final publicKey = await pair.extractPublicKey();
    final privateKey = SecretKey(await pair.extractPrivateKeyBytes());
    final package = (await encryptInheritanceMvk(
      beneficiaryLinkId: 19,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
    ))
        .toRequestBody(19);
    const fileId = 'v2-synthetic-oversized';
    const total = maxInheritedFileInMemoryBytes + 1;
    const chunkSize = 256 * 1024;
    final chunkCount = (total + chunkSize - 1) ~/ chunkSize;
    final metadataKey = await VaultKeyHierarchy(ownerMvk).metadataKey();
    final encryptedManifest = b64urlEncode(await aesGcmWrap(
      metadataKey,
      utf8.encode(jsonEncode(<String, Object?>{
        'schema': 'vaultai.file.migrated.v1',
        'file_id': fileId,
        'file_size': total,
        'content_type': null,
        'chunk_size': chunkSize,
        'chunk_count': chunkCount,
        'encrypted_metadata': <String, String>{},
      })),
    ));
    final requests = <String>[];
    await expectLater(
      prepareInheritedV2File(
        linkId: 19,
        sourceFileId: fileId,
        beneficiaryPrivateKey: privateKey,
        beneficiaryMvk: beneficiaryMvk,
        releasedPackage: package,
        fetch: (path) async {
          requests.add(path);
          if (!path.endsWith('/manifest')) {
            fail('Oversized inheritance must not request chunks');
          }
          return <String, dynamic>{
            'beneficiary_link_id': 19,
            'owner_vault_id': 'synthetic-owner',
            'file_id': fileId,
            'crypto_version': 'client_mvk_v2',
            'manifest_ciphertext': encryptedManifest,
            'total_bytes': total,
            'chunk_size': chunkSize,
            'chunk_count': chunkCount,
            'lifecycle_state': 'client_v2_ready',
            'verification_state': 'client_verified',
            'name_version': 0,
            'migration_metadata_version': 1,
            'saved_name_override_ciphertext': null,
          };
        },
        accessIsCurrent: () => true,
      ),
      throwsA(isA<FileV2LocalSizeLimitException>()),
    );
    expect(requests, ['/inheritance/v2/19/files/$fileId/manifest']);
  });
}
