/// Read a released owner's V2 file on the beneficiary's device only.
///
/// The server supplies ciphertext after checking the released link. Its
/// response is scoped to the same owner/link as the MVK envelope before any
/// encrypted manifest or chunk is accepted. This does not import the file.
library;

import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'file_v2_reader.dart';
import 'inheritance_mvk_v2.dart';

typedef FetchInheritedFileCiphertext = Future<Map<String, dynamic>> Function(
  String path,
);

// The inheritance path currently stages a whole file in memory. Keep it well
// below the regular reader's 512 MiB ceiling until a streaming import exists.
const int maxInheritedFileInMemoryBytes = 16 * 1024 * 1024;

class ReleasedV2FileStream {
  final String ownerVaultId;
  final String sourceRevision;
  final FileV2Manifest manifest;
  final FileV2Reader _reader;
  final bool Function() _accessIsCurrent;

  const ReleasedV2FileStream({
    required this.ownerVaultId,
    required this.sourceRevision,
    required this.manifest,
    required FileV2Reader reader,
    required bool Function() accessIsCurrent,
  })  : _reader = reader,
        _accessIsCurrent = accessIsCurrent;

  void _checkAccess() {
    if (!_accessIsCurrent()) throw StateError('Vault access changed');
  }

  Future<Uint8List> readChunk(int index) async {
    _checkAccess();
    final bytes = await _reader.readChunk(manifest, index);
    try {
      _checkAccess();
      return bytes;
    } catch (_) {
      bytes.fillRange(0, bytes.length, 0);
      rethrow;
    }
  }

  /// Recheck release permission and the source metadata before publication.
  Future<void> assertUnchanged() async {
    _checkAccess();
    final current = await _reader.readManifest(
      manifest.fileId,
      requireReady: true,
    );
    _checkAccess();
    if (current.totalBytes != manifest.totalBytes ||
        current.chunkSize != manifest.chunkSize ||
        current.chunkCount != manifest.chunkCount ||
        current.fileName != manifest.fileName ||
        current.savedName != manifest.savedName ||
        current.contentType != manifest.contentType ||
        current.relativePath != manifest.relativePath ||
        current.assetType != manifest.assetType ||
        current.detectedType != manifest.detectedType ||
        current.detectedService != manifest.detectedService ||
        current.extractedText != manifest.extractedText ||
        current.nameVersion != manifest.nameVersion) {
      throw StateError('Inherited source changed during transfer');
    }
  }
}

Future<({String ownerVaultId, FileV2Reader reader,
    String? Function() sourceRevision})> _scopedReader({
  required int linkId,
  required String fileId,
  required SecretKey beneficiaryPrivateKey,
  required Map<String, dynamic> releasedPackage,
  required FetchInheritedFileCiphertext fetch,
  required bool Function() accessIsCurrent,
  bool requireSourceRevision = false,
}) async {
  if (!RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(fileId)) {
    throw const FormatException('Invalid inherited file identity');
  }
  void checkAccess() {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
  }

  checkAccess();
  final inherited = await decryptInheritanceMvk(
    expectedLinkId: linkId,
    beneficiaryPrivateKey: beneficiaryPrivateKey,
    rawPackage: releasedPackage,
  );
  checkAccess();

  final expectedPrefix = '/vault/file-v2/$fileId/';
  String? sourceRevision;
  final reader = FileV2Reader(
    mvk: inherited.ownerMvk,
    get: (path) async {
      checkAccess();
      if (!path.startsWith(expectedPrefix)) {
        throw const FormatException('Invalid inherited file path');
      }
      final suffix = path.substring(expectedPrefix.length);
      if (suffix != 'manifest' &&
          !RegExp(r'^chunk/(0|[1-9][0-9]*)$').hasMatch(suffix)) {
        throw const FormatException('Invalid inherited file request');
      }
      final response = await fetch(
        '/inheritance/v2/$linkId/files/$fileId/$suffix',
      );
      checkAccess();
      if (response['beneficiary_link_id'] != linkId ||
          response['owner_vault_id'] != inherited.ownerVaultId) {
        throw const FormatException('Inherited file context mismatch');
      }
      if (suffix == 'manifest') {
        final revision = response['source_revision'];
        if (requireSourceRevision &&
            (revision is! String ||
                !RegExp(r'^[0-9a-f]{64}$').hasMatch(revision))) {
          throw const FormatException('Inherited source revision unavailable');
        }
        if (revision is String) {
          if (sourceRevision != null && sourceRevision != revision) {
            throw StateError('Inherited source changed during transfer');
          }
          sourceRevision = revision;
        }
      }
      return response;
    },
  );
  return (ownerVaultId: inherited.ownerVaultId, reader: reader,
      sourceRevision: () => sourceRevision);
}

Future<ReleasedV2FileStream> openReleasedV2FileStream({
  required int linkId,
  required String fileId,
  required SecretKey beneficiaryPrivateKey,
  required Map<String, dynamic> releasedPackage,
  required FetchInheritedFileCiphertext fetch,
  required bool Function() accessIsCurrent,
}) async {
  final scoped = await _scopedReader(
    linkId: linkId,
    fileId: fileId,
    beneficiaryPrivateKey: beneficiaryPrivateKey,
    releasedPackage: releasedPackage,
    fetch: fetch,
    accessIsCurrent: accessIsCurrent,
    requireSourceRevision: true,
  );
  final manifest = await scoped.reader.readManifest(fileId, requireReady: true);
  if (!accessIsCurrent()) throw StateError('Vault access changed');
  final revision = scoped.sourceRevision();
  if (revision == null) {
    throw const FormatException('Inherited source revision unavailable');
  }
  return ReleasedV2FileStream(
    ownerVaultId: scoped.ownerVaultId,
    sourceRevision: revision,
    manifest: manifest,
    reader: scoped.reader,
    accessIsCurrent: accessIsCurrent,
  );
}

Future<FileV2Download> readReleasedV2File({
  required int linkId,
  required String fileId,
  required SecretKey beneficiaryPrivateKey,
  required Map<String, dynamic> releasedPackage,
  required FetchInheritedFileCiphertext fetch,
  required bool Function() accessIsCurrent,
}) async {
  final scoped = await _scopedReader(
    linkId: linkId,
    fileId: fileId,
    beneficiaryPrivateKey: beneficiaryPrivateKey,
    releasedPackage: releasedPackage,
    fetch: fetch,
    accessIsCurrent: accessIsCurrent,
  );
  final result = await scoped.reader.download(
    fileId,
    requireReady: true,
    maxBytes: maxInheritedFileInMemoryBytes,
  );
  try {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    return result;
  } catch (_) {
    result.bytes.fillRange(0, result.bytes.length, 0);
    rethrow;
  }
}
