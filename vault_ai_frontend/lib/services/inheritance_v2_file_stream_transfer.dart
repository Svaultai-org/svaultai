/// Bounded, PIN-free transfer of a released V2 file into a beneficiary vault.
///
/// Every file byte is decrypted on the beneficiary device, encrypted under
/// its own MVK, then checked against a fresh source read before publication.
/// The existing V2 manifest/chunk/publish routes are used unchanged. A stable
/// target ID and the server's existing manifest allow an interrupted transfer
/// to resume without duplicating a published file.
library;

import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'file_v2_reader.dart';
import 'file_v2_writer.dart';
import 'inheritance_v2_file_reader.dart';
import 'inheritance_v2_file_stage.dart';
import 'vault_key_hierarchy.dart';
import 'zk_proof_token_guard.dart';

typedef InheritedV2TargetRequest = Future<Map<String, dynamic>?> Function(
  String method,
  String path,
  Map<String, Object>? body,
);

const int _gcmFramingBytes = 29;

void _checkMetadata(FileV2Manifest source) {
  if (source.fileName == null ||
      source.fileName!.trim().isEmpty ||
      (source.assetType?.isNotEmpty ?? false) ||
      (source.detectedType?.isNotEmpty ?? false) ||
      (source.detectedService?.isNotEmpty ?? false) ||
      (source.extractedText?.isNotEmpty ?? false)) {
    throw const FormatException(
      'Inherited file metadata needs a private format update',
    );
  }
}

void _checkTargetManifest(
  FileV2Manifest target,
  FileV2Manifest source,
  String targetId,
) {
  if (target.fileId != targetId ||
      target.totalBytes != source.totalBytes ||
      target.chunkSize != source.chunkSize ||
      target.chunkCount != source.chunkCount ||
      target.fileName != source.fileName ||
      target.savedName != source.savedName ||
      target.contentType != source.contentType ||
      target.relativePath != source.relativePath ||
      target.assetType != null ||
      target.detectedType != null ||
      target.detectedService != null ||
      target.extractedText != null ||
      target.nameVersion != 0) {
    throw const FormatException('Inherited target metadata differs');
  }
}

Future<FileV2Manifest> _decodeTargetManifest({
  required Map<String, dynamic> raw,
  required String manifestPath,
  required String targetId,
  required SecretKey beneficiaryMvk,
}) {
  return FileV2Reader(
    mvk: beneficiaryMvk,
    get: (path) async {
      if (path != manifestPath) {
        throw const FormatException('Invalid inherited target request');
      }
      return raw;
    },
  ).readManifest(targetId);
}

Future<void> _compareEncryptedTargetChunk({
  required Map<String, dynamic> response,
  required String fileId,
  required int index,
  required Uint8List sourceBytes,
  required SecretKey contentKey,
}) async {
  final encoded = response['ciphertext'];
  if (response['file_id'] != fileId ||
      response['chunk_index'] != index ||
      encoded is! String ||
      encoded.length > ((sourceBytes.length + _gcmFramingBytes) * 4 ~/ 3) + 8) {
    throw const FormatException('Inherited target chunk differs');
  }
  final ciphertext = b64urlDecode(encoded);
  if (ciphertext.length != sourceBytes.length + _gcmFramingBytes) {
    throw const FormatException('Inherited target chunk differs');
  }
  final targetBytes = await aesGcmUnwrap(contentKey, ciphertext);
  try {
    var difference = targetBytes.length ^ sourceBytes.length;
    if (targetBytes.length == sourceBytes.length) {
      for (var i = 0; i < sourceBytes.length; i++) {
        difference |= targetBytes[i] ^ sourceBytes[i];
      }
    }
    if (difference != 0) {
      throw const FormatException('Inherited target chunk differs');
    }
  } finally {
    targetBytes.fillRange(0, targetBytes.length, 0);
  }
}

Future<Map<String, dynamic>> transferReleasedV2FileStreamed({
  required int linkId,
  required String sourceFileId,
  required Future<String> Function() freshBeneficiaryProof,
  required SecretKey beneficiaryPrivateKey,
  required SecretKey beneficiaryMvk,
  required Map<String, dynamic> releasedPackage,
  required FetchInheritedFileCiphertext fetchSource,
  required InheritedV2TargetRequest requestTarget,
  required bool Function() accessIsCurrent,
  void Function(double progress)? onProgress,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
  }

  Future<Map<String, dynamic>?> request(
    String method,
    String path, [
    Map<String, Object>? body,
  ]) async {
    checkAccess();
    final result = await requestTarget(method, path, body);
    checkAccess();
    return result;
  }

  checkAccess();
  final source = await openReleasedV2FileStream(
    linkId: linkId,
    fileId: sourceFileId,
    beneficiaryPrivateKey: beneficiaryPrivateKey,
    releasedPackage: releasedPackage,
    fetch: fetchSource,
    accessIsCurrent: accessIsCurrent,
  );
  checkAccess();
  _checkMetadata(source.manifest);
  final targetId = await inheritedTargetFileId(
    linkId: linkId,
    ownerVaultId: source.ownerVaultId,
    sourceFileId: sourceFileId,
    beneficiaryMvk: beneficiaryMvk,
  );
  checkAccess();
  final manifestPath = '/vault/file-v2/$targetId/manifest';
  final existing = await request('GET', manifestPath);
  late final PreparedNewFileV2 prepared;
  if (existing == null) {
    prepared = await FileV2Writer(beneficiaryMvk).prepareStreamed(
      fileId: targetId,
      fileName: source.manifest.fileName!,
      savedName: source.manifest.savedName,
      contentType: source.manifest.contentType,
      relativePath: source.manifest.relativePath,
      totalBytes: source.manifest.totalBytes,
      chunkSize: source.manifest.chunkSize,
    );
    checkAccess();
    final staged = await request(
      'POST',
      '/vault/file-v2/manifest',
      prepared.toManifestBody(),
    );
    if (staged?['file_id'] != targetId ||
        staged?['crypto_version'] != 'client_mvk_v2') {
      throw const FormatException('Inherited target manifest not staged');
    }
  } else {
    if (existing['file_id'] != targetId ||
        existing['manifest_ciphertext'] is! String ||
        existing['migration_metadata_version'] != 1 ||
        existing['name_version'] != 0 ||
        !((existing['lifecycle_state'] == 'file_v2_written' &&
                existing['verification_state'] == 'not_verified') ||
            (existing['lifecycle_state'] == 'client_v2_ready' &&
                existing['verification_state'] == 'client_verified'))) {
      throw const FormatException('Inherited target manifest differs');
    }
    final target = await _decodeTargetManifest(
      raw: existing,
      manifestPath: manifestPath,
      targetId: targetId,
      beneficiaryMvk: beneficiaryMvk,
    );
    _checkTargetManifest(target, source.manifest, targetId);
    prepared = PreparedNewFileV2(
      fileId: targetId,
      totalBytes: target.totalBytes,
      chunkSize: target.chunkSize,
      chunkCount: target.chunkCount,
      manifestCiphertext: existing['manifest_ciphertext'] as String,
      chunkCiphertexts: const <String>[],
    );
  }

  final targetKey = await VaultKeyHierarchy(beneficiaryMvk).fileContentKey();
  checkAccess();
  final count = source.manifest.chunkCount;
  final chunkPath = '/vault/file-v2/$targetId/chunk/';
  for (var i = 0; i < count; i++) {
    final sourceBytes = await source.readChunk(i);
    try {
      checkAccess();
      final targetChunk = await request('GET', '$chunkPath$i');
      if (targetChunk == null) {
        final ciphertext = b64urlEncode(
          await aesGcmWrap(targetKey, sourceBytes),
        );
        checkAccess();
        final staged =
            await request('PUT', '/vault/file-v2/chunk', <String, Object>{
          'file_id': targetId,
          'chunk_index': i,
          'ciphertext': ciphertext,
        });
        if (staged?['file_id'] != targetId || staged?['chunk_index'] != i) {
          throw const FormatException('Inherited target chunk not staged');
        }
      } else {
        await _compareEncryptedTargetChunk(
          response: targetChunk,
          fileId: targetId,
          index: i,
          sourceBytes: sourceBytes,
          contentKey: targetKey,
        );
      }
    } finally {
      sourceBytes.fillRange(0, sourceBytes.length, 0);
    }
    onProgress?.call(count == 0 ? 0.8 : 0.8 * (i + 1) / count);
  }

  // Read every staged byte back from the server and compare it with a fresh
  // owner read. No unverified or partly staged file is made visible.
  final targetManifest = await request('GET', manifestPath);
  if (targetManifest == null ||
      targetManifest['manifest_ciphertext'] != prepared.manifestCiphertext) {
    throw const FormatException('Inherited target metadata changed');
  }
  _checkTargetManifest(
    await _decodeTargetManifest(
      raw: targetManifest,
      manifestPath: manifestPath,
      targetId: targetId,
      beneficiaryMvk: beneficiaryMvk,
    ),
    source.manifest,
    targetId,
  );
  for (var i = 0; i < count; i++) {
    final sourceBytes = await source.readChunk(i);
    try {
      final targetChunk = await request('GET', '$chunkPath$i');
      if (targetChunk == null) {
        throw const FormatException('Inherited target readback incomplete');
      }
      await _compareEncryptedTargetChunk(
        response: targetChunk,
        fileId: targetId,
        index: i,
        sourceBytes: sourceBytes,
        contentKey: targetKey,
      );
    } finally {
      sourceBytes.fillRange(0, sourceBytes.length, 0);
    }
    onProgress?.call(count == 0 ? 0.95 : 0.8 + 0.15 * (i + 1) / count);
  }
  await source.assertUnchanged();
  checkAccess();
  // A large transfer can outlive a short-lived proof. Obtain it only after
  // all ciphertext has been checked, immediately before publication.
  final beneficiaryProofToken =
      rejectPinShapedZkProof(await freshBeneficiaryProof());
  if (beneficiaryProofToken.isEmpty) {
    throw StateError('Beneficiary action proof required');
  }
  checkAccess();
  final published = await request(
    'POST',
    '/vault/file-v2/$targetId/publish-new',
    <String, Object>{
      'confirm': true,
      'inheritance_link_id': linkId,
      'inheritance_source_file_id': sourceFileId,
      'zk_proof_token': beneficiaryProofToken,
    },
  );
  if (published == null ||
      published['file_id'] != targetId ||
      !<String>{'published', 'already_published'}
          .contains(published['status'])) {
    throw const FormatException('Inherited target publish unconfirmed');
  }
  final ready = await request('GET', manifestPath);
  if (ready == null ||
      ready['file_id'] != targetId ||
      ready['lifecycle_state'] != 'client_v2_ready' ||
      ready['verification_state'] != 'client_verified' ||
      ready['manifest_ciphertext'] != prepared.manifestCiphertext) {
    throw const FormatException('Inherited target publish state unavailable');
  }
  onProgress?.call(1);
  return published;
}
