/// Client-only preparation of a released file for the beneficiary's vault.
///
/// This produces encrypted upload material. It deliberately does not write,
/// publish, freeze, or retire either vault. The caller must use the V2 upload
/// route with exact readback and clear [sourceBytes] after that operation.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'file_v2_writer.dart';
import 'inheritance_mvk_v2.dart';
import 'inheritance_v2_file_reader.dart';
import 'vault_key_hierarchy.dart';

class PreparedInheritedV2File {
  final int linkId;
  final String ownerVaultId;
  final String sourceFileId;
  final PreparedNewFileV2 prepared;
  final Uint8List sourceBytes;

  const PreparedInheritedV2File({
    required this.linkId,
    required this.ownerVaultId,
    required this.sourceFileId,
    required this.prepared,
    required this.sourceBytes,
  });

  void clearSourceBytes() => sourceBytes.fillRange(0, sourceBytes.length, 0);
}

Future<String> inheritedTargetFileId({
  required int linkId,
  required String ownerVaultId,
  required String sourceFileId,
  required SecretKey beneficiaryMvk,
}) async {
  if (linkId <= 0 ||
      ownerVaultId.isEmpty ||
      !RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(sourceFileId)) {
    throw const FormatException('Invalid inherited file identity');
  }
  final context = utf8.encode(
    'vaultai.inheritance.file.v1\x00$linkId\x00$ownerVaultId\x00$sourceFileId',
  );
  final mac = await Hmac.sha256().calculateMac(
    context,
    secretKey: beneficiaryMvk,
  );
  return 'v2-${b64urlEncode(mac.bytes.sublist(0, 20))}';
}

Future<PreparedInheritedV2File> prepareInheritedV2File({
  required int linkId,
  required String sourceFileId,
  required SecretKey beneficiaryPrivateKey,
  required SecretKey beneficiaryMvk,
  required Map<String, dynamic> releasedPackage,
  required FetchInheritedFileCiphertext fetch,
  required bool Function() accessIsCurrent,
}) async {
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
  final download = await readReleasedV2File(
    linkId: linkId,
    fileId: sourceFileId,
    beneficiaryPrivateKey: beneficiaryPrivateKey,
    releasedPackage: releasedPackage,
    fetch: fetch,
    accessIsCurrent: accessIsCurrent,
  );
  try {
    checkAccess();
    final manifest = download.manifest;
    final fileName = manifest.fileName;
    if (fileName == null ||
        fileName.trim().isEmpty ||
        (manifest.assetType?.isNotEmpty ?? false) ||
        (manifest.detectedType?.isNotEmpty ?? false) ||
        (manifest.detectedService?.isNotEmpty ?? false) ||
        (manifest.extractedText?.isNotEmpty ?? false)) {
      throw const FormatException(
        'Inherited file metadata needs a private format update',
      );
    }
    final targetId = await inheritedTargetFileId(
      linkId: linkId,
      ownerVaultId: inherited.ownerVaultId,
      sourceFileId: sourceFileId,
      beneficiaryMvk: beneficiaryMvk,
    );
    checkAccess();
    final prepared = await FileV2Writer(beneficiaryMvk).prepare(
      fileId: targetId,
      fileName: fileName,
      savedName: manifest.savedName,
      contentType: manifest.contentType,
      relativePath: manifest.relativePath,
      bytes: download.bytes,
    );
    checkAccess();
    return PreparedInheritedV2File(
      linkId: linkId,
      ownerVaultId: inherited.ownerVaultId,
      sourceFileId: sourceFileId,
      prepared: prepared,
      sourceBytes: download.bytes,
    );
  } catch (_) {
    download.bytes.fillRange(0, download.bytes.length, 0);
    rethrow;
  }
}
