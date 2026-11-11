import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_private_conflict_tokens.dart';
import 'package:vault_ai_frontend/services/file_v2_reader.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_file_reader.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_file_stream_transfer.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

class SyntheticTransfer {
  final SecretKey ownerMvk = SecretKey(List<int>.filled(32, 61));
  final SecretKey beneficiaryMvk = SecretKey(List<int>.filled(32, 71));
  late final SecretKey beneficiaryPrivateKey;
  late final Map<String, dynamic> releasedPackage;
  late final PreparedNewFileV2 sourceManifest;
  late final SecretKey ownerContentKey;
  final String sourceFileId = FileV2Writer.newFileId();
  final int totalBytes;
  final int chunkSize;
  int maxPlainChunk = 0;
  int sourceChunkReads = 0;
  int targetManifestPosts = 0;
  int targetChunkPuts = 0;
  int publishCalls = 0;
  int proofCalls = 0;
  String proofToken = 'synthetic-opaque-proof';
  int? failPutAt;
  int? revokeAfterSourceReads;
  bool revokeOnFinalManifest = false;
  bool changeRevisionOnFinalManifest = false;
  bool renameTargetAfterPublish = false;
  int sourceManifestReads = 0;
  String? targetFileId;
  Map<String, Object>? publishBody;
  int targetNameVersion = 0;
  String? targetNameOverride;
  Map<String, Object>? targetManifestBody;
  final Map<int, String> targetChunks = {};
  bool published = false;
  bool losePublishAckOnce = false;
  final List<String> targetPaths = [];

  SyntheticTransfer({required this.totalBytes, required this.chunkSize});

  Future<void> initialize() async {
    final pair = await X25519().newKeyPair();
    final publicKey = await pair.extractPublicKey();
    beneficiaryPrivateKey = SecretKey(await pair.extractPrivateKeyBytes());
    releasedPackage = (await encryptInheritanceMvk(
      beneficiaryLinkId: 31,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(publicKey.bytes),
    ))
        .toRequestBody(31);
    sourceManifest = await FileV2Writer(ownerMvk).prepareStreamed(
      fileId: sourceFileId,
      fileName: 'private-synthetic.bin',
      savedName: 'Synthetic vault file',
      contentType: 'application/octet-stream',
      totalBytes: totalBytes,
      chunkSize: chunkSize,
    );
    ownerContentKey = await VaultKeyHierarchy(ownerMvk).fileContentKey();
  }

  Uint8List plainChunk(int index) {
    final start = index * chunkSize;
    final length = (totalBytes - start).clamp(0, chunkSize);
    if (length > maxPlainChunk) maxPlainChunk = length;
    return Uint8List.fromList(
      List<int>.generate(length, (offset) => (start + offset * 13) & 255),
    );
  }

  Future<Map<String, dynamic>> fetchSource(String path) async {
    if (path.endsWith('/manifest')) {
      sourceManifestReads++;
      if (revokeOnFinalManifest && sourceManifestReads > 1) {
        throw const FileV2ReadException(404);
      }
      return <String, dynamic>{
        'beneficiary_link_id': 31,
        'owner_vault_id': 'synthetic-owner',
        'source_revision':
            (changeRevisionOnFinalManifest && sourceManifestReads > 1)
                ? List.filled(64, 'b').join()
                : List.filled(64, 'a').join(),
        ...sourceManifest.toManifestBody(),
        'lifecycle_state': 'client_v2_ready',
        'verification_state': 'client_verified',
        'name_version': 0,
        'migration_metadata_version': 1,
        'saved_name_override_ciphertext': null,
      };
    }
    if (path.contains('/chunk/')) {
      if (revokeAfterSourceReads != null &&
          sourceChunkReads >= revokeAfterSourceReads!) {
        throw const FileV2ReadException(404);
      }
      final index = int.parse(path.split('/').last);
      sourceChunkReads++;
      final plain = plainChunk(index);
      try {
        return <String, dynamic>{
          'beneficiary_link_id': 31,
          'owner_vault_id': 'synthetic-owner',
          'file_id': sourceFileId,
          'chunk_index': index,
          'ciphertext': b64urlEncode(
            await aesGcmWrap(ownerContentKey, plain),
          ),
        };
      } finally {
        plain.fillRange(0, plain.length, 0);
      }
    }
    fail('Unexpected source path');
  }

  Map<String, dynamic> get targetManifestResponse => <String, dynamic>{
        ...targetManifestBody!,
        'lifecycle_state': published ? 'client_v2_ready' : 'file_v2_written',
        'verification_state': published ? 'client_verified' : 'not_verified',
        'name_version': targetNameVersion,
        'migration_metadata_version': 1,
        'saved_name_override_ciphertext': targetNameOverride,
      };

  Future<Map<String, dynamic>?> requestTarget(
    String method,
    String path,
    Map<String, Object>? body,
  ) async {
    targetPaths.add('$method $path ${jsonEncode(body)}');
    if (method == 'GET' && path.endsWith('/manifest')) {
      return targetManifestBody == null ? null : targetManifestResponse;
    }
    if (method == 'POST' && path == '/vault/file-v2/manifest') {
      targetManifestPosts++;
      if (targetManifestBody != null) fail('Duplicate manifest POST');
      targetManifestBody = body;
      targetFileId = body!['file_id'] as String;
      return <String, dynamic>{
        'file_id': targetFileId,
        'crypto_version': 'client_mvk_v2',
      };
    }
    if (method == 'GET' && path.contains('/chunk/')) {
      final index = int.parse(path.split('/').last);
      final ciphertext = targetChunks[index];
      if (ciphertext == null) return null;
      return <String, dynamic>{
        'file_id': targetFileId,
        'chunk_index': index,
        'ciphertext': ciphertext,
      };
    }
    if (method == 'PUT' && path == '/vault/file-v2/chunk') {
      final index = body!['chunk_index'] as int;
      if (failPutAt == index) {
        failPutAt = null;
        throw StateError('Synthetic interrupted upload');
      }
      targetChunkPuts++;
      targetChunks[index] = body['ciphertext'] as String;
      return <String, dynamic>{
        'file_id': targetFileId,
        'chunk_index': index,
      };
    }
    if (method == 'POST' && path.endsWith('/publish-new')) {
      publishCalls++;
      publishBody = body;
      expect(body?['zk_proof_token'], 'synthetic-opaque-proof');
      expect(body?['inheritance_source_revision'], List.filled(64, 'a').join());
      if (targetChunks.length != sourceManifest.chunkCount) {
        fail('Published incomplete synthetic file');
      }
      final prior = published;
      published = true;
      if (renameTargetAfterPublish) {
        targetNameVersion = 1;
        targetNameOverride = 'synthetic-beneficiary-rename';
      }
      if (losePublishAckOnce) {
        losePublishAckOnce = false;
        throw StateError('Synthetic lost publish response');
      }
      return <String, dynamic>{
        'file_id': targetFileId,
        'status': prior ? 'already_published' : 'published',
      };
    }
    fail('Unexpected target request');
  }

  Future<Map<String, dynamic>> transfer() => transferReleasedV2FileStreamed(
        linkId: 31,
        sourceFileId: sourceFileId,
        beneficiaryVaultId: 'synthetic-beneficiary',
        freshBeneficiaryProof: () async {
          proofCalls++;
          expect(sourceChunkReads,
              greaterThanOrEqualTo(sourceManifest.chunkCount * 2));
          return proofToken;
        },
        beneficiaryPrivateKey: beneficiaryPrivateKey,
        beneficiaryMvk: beneficiaryMvk,
        releasedPackage: releasedPackage,
        fetchSource: fetchSource,
        requestTarget: requestTarget,
        accessIsCurrent: () => true,
      );
}

void main() {
  test('inherited publish binds blind tags to streamed clear bytes', () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    await fixture.transfer();
    final wholeFile = Uint8List.fromList([
      for (var i = 0; i < fixture.sourceManifest.chunkCount; i++)
        ...fixture.plainChunk(i),
    ]);
    final expected = await FilePrivateConflictTokenMaker(
      mvk: fixture.beneficiaryMvk,
      vaultId: 'synthetic-beneficiary',
    ).make(
      wholeFileSha256: Uint8List.fromList(crypto.sha256.convert(wholeFile).bytes),
      fileSize: wholeFile.length,
      fileName: 'private-synthetic.bin',
      savedName: 'Synthetic vault file',
    );
    wholeFile.fillRange(0, wholeFile.length, 0);
    expect(fixture.publishBody?['content_token'],
        b64urlEncode(expected.contentToken));
    expect(fixture.publishBody?['name_tokens'],
        expected.nameTokens.map(b64urlEncode).toList());
    expect(fixture.publishBody?['duplicate_action'], 'keep_both');
    expect(jsonEncode(fixture.publishBody), isNot(contains('private-synthetic')));
  });

  test('streams a file above the in-memory cap and publishes after readback',
      () async {
    final fixture = SyntheticTransfer(
      totalBytes: maxInheritedFileInMemoryBytes + 1,
      chunkSize: 1024 * 1024,
    );
    await fixture.initialize();
    final result = await fixture.transfer();
    expect(result['status'], 'published');
    expect(fixture.published, isTrue);
    expect(fixture.maxPlainChunk, lessThanOrEqualTo(1024 * 1024));
    expect(fixture.targetManifestPosts, 1);
    expect(fixture.targetChunkPuts, fixture.sourceManifest.chunkCount);
    expect(fixture.sourceChunkReads, fixture.sourceManifest.chunkCount * 2);
    expect(fixture.proofCalls, 1);
    expect(fixture.targetPaths.join(' '), isNot(contains('private-synthetic')));
  });

  test('interrupted upload resumes with the same target and exact bytes',
      () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    fixture.failPutAt = 1;
    await expectLater(fixture.transfer(), throwsStateError);
    expect(fixture.targetManifestPosts, 1);
    expect(fixture.targetChunks.keys, contains(0));
    final result = await fixture.transfer();
    expect(result['status'], 'published');
    expect(fixture.targetManifestPosts, 1);
    expect(fixture.targetChunkPuts, fixture.sourceManifest.chunkCount);
    final again = await fixture.transfer();
    expect(again['status'], 'already_published');
    expect(fixture.targetChunkPuts, fixture.sourceManifest.chunkCount);
  });

  test('changed staged ciphertext fails before publication', () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    fixture.failPutAt = 1;
    await expectLater(fixture.transfer(), throwsStateError);
    fixture.targetChunks[0] = b64urlEncode(Uint8List(8 + 29));
    await expectLater(fixture.transfer(), throwsA(anything));
    expect(fixture.published, isFalse);
    expect(fixture.publishCalls, 0);
    expect(fixture.proofCalls, 0);
  });

  test('lost publish acknowledgement resumes without another file', () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    fixture.losePublishAckOnce = true;
    await expectLater(fixture.transfer(), throwsStateError);
    expect(fixture.published, isTrue);
    final resumed = await fixture.transfer();
    expect(resumed['status'], 'already_published');
    expect(fixture.targetManifestPosts, 1);
    expect(fixture.targetChunkPuts, fixture.sourceManifest.chunkCount);
    expect(fixture.publishCalls, 2);
  });

  test('revocation during readback leaves target unpublished', () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    fixture.revokeAfterSourceReads = fixture.sourceManifest.chunkCount;
    await expectLater(
      fixture.transfer(),
      throwsA(isA<FileV2ReadException>()),
    );
    expect(fixture.targetChunks.length, fixture.sourceManifest.chunkCount);
    expect(fixture.published, isFalse);
    expect(fixture.publishCalls, 0);
    expect(fixture.proofCalls, 0);
  });

  test('revocation at final release check blocks publish', () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    fixture.revokeOnFinalManifest = true;
    await expectLater(
      fixture.transfer(),
      throwsA(isA<FileV2ReadException>()),
    );
    expect(fixture.sourceManifestReads, 2);
    expect(fixture.publishCalls, 0);
    expect(fixture.published, isFalse);
  });

  test('source revision change before publication prevents visibility',
      () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    fixture.changeRevisionOnFinalManifest = true;
    await expectLater(fixture.transfer(), throwsStateError);
    expect(fixture.publishCalls, 0);
    expect(fixture.proofCalls, 0);
    expect(fixture.published, isFalse);
  });

  test('renamed published target requires review without duplicate upload',
      () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    await fixture.transfer();
    final targetKey = await VaultKeyHierarchy(fixture.beneficiaryMvk)
        .metadataKey();
    fixture.targetNameVersion = 1;
    fixture.targetNameOverride = b64urlEncode(
      await aesGcmWrap(targetKey, utf8.encode('Beneficiary chosen name')),
    );
    await expectLater(
      fixture.transfer(),
      throwsA(isA<InheritedV2FileNameReviewRequired>()),
    );
    expect(fixture.targetManifestPosts, 1);
    expect(fixture.publishCalls, 1);
    expect(fixture.proofCalls, 1);
  });

  test('target renamed just after publish needs review before success',
      () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    fixture.renameTargetAfterPublish = true;
    await expectLater(
      fixture.transfer(),
      throwsA(isA<InheritedV2FileNameReviewRequired>()),
    );
    expect(fixture.published, isTrue);
    expect(fixture.targetManifestPosts, 1);
    expect(fixture.publishCalls, 1);
    expect(fixture.proofCalls, 1);
  });

  test('PIN-shaped substitute is rejected after readback before publish',
      () async {
    final fixture = SyntheticTransfer(totalBytes: 29, chunkSize: 8);
    await fixture.initialize();
    fixture.proofToken = '123456';
    await expectLater(fixture.transfer(), throwsArgumentError);
    expect(fixture.proofCalls, 1);
    expect(fixture.publishCalls, 0);
    expect(fixture.published, isFalse);
  });
}
