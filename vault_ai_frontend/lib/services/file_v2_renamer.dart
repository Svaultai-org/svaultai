// Rename a ready V2 file with an MVK-encrypted saved name. The server receives
// only an opaque ciphertext, a version, and a one-time OPAQUE proof.

import 'dart:convert';

import 'package:cryptography/cryptography.dart';

import 'file_v2_reader.dart';
import 'saved_file_rename.dart';
import 'vault_key_hierarchy.dart';

typedef FileV2RenamePost = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> body,
);

class FileV2Renamer {
  final SecretKey mvk;
  final FileV2Get get;
  final FileV2RenamePost post;

  const FileV2Renamer({
    required this.mvk,
    required this.get,
    required this.post,
  });

  Future<FileV2Manifest> rename({
    required String fileId,
    required String savedName,
    required String zkProofToken,
  }) async {
    final error = savedFileNameValidationError(savedName);
    if (fileId.isEmpty || zkProofToken.isEmpty || error != null) {
      throw const FormatException('Invalid private file rename');
    }
    final normalized = normalizeSavedFileName(savedName);
    final path = '/vault/file-v2/${Uri.encodeComponent(fileId)}/manifest';
    final before = await FileV2Reader(mvk: mvk, get: get).readManifest(
      fileId,
      requireReady: true,
    );
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    final ciphertext = b64urlEncode(
      await aesGcmWrap(key, utf8.encode(normalized)),
    );
    final expectedVersion = before.nameVersion + 1;

    Future<FileV2Manifest?> verifiedReadback() async {
      final raw = await get(path);
      if (raw['name_version'] != expectedVersion ||
          raw['saved_name_override_ciphertext'] != ciphertext) {
        return null;
      }
      final after = await FileV2Reader(mvk: mvk, get: get).readManifest(
        fileId,
        requireReady: true,
      );
      return after.nameVersion == expectedVersion &&
              after.savedName == normalized
          ? after
          : null;
    }

    try {
      final response = await post(
        '/vault/file-v2/${Uri.encodeComponent(fileId)}/rename',
        <String, dynamic>{
          'zk_proof_token': zkProofToken,
          'expected_name_version': before.nameVersion,
          'saved_name_ciphertext': ciphertext,
        },
      );
      if (response['file_id'] != fileId ||
          response['name_version'] != expectedVersion ||
          response['renamed'] != true) {
        throw const FormatException('Invalid private file rename response');
      }
    } catch (_) {
      // The response can be lost after the server committed and consumed the
      // one-time proof. Exact ciphertext readback distinguishes that case.
      try {
        final recovered = await verifiedReadback();
        if (recovered != null) return recovered;
      } catch (_) {}
      rethrow;
    }
    final verified = await verifiedReadback();
    if (verified == null) {
      throw const FormatException('Private file rename readback mismatch');
    }
    return verified;
  }
}
