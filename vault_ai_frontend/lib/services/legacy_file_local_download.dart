// Read an older inline file through the proof-bound ciphertext export and
// decrypt it only on the owner device. This does not migrate or retire it.

import 'dart:typed_data';

import 'legacy_ciphertext_export_client.dart';
import 'legacy_ciphertext_migration_codec.dart';

class LegacyFileLocalDownload {
  final LegacyCiphertextExportClient export;
  final LegacyCiphertextMigrationCodec codec;
  final bool Function() accessIsCurrent;

  const LegacyFileLocalDownload({
    required this.export,
    required this.codec,
    required this.accessIsCurrent,
  });

  Future<Uint8List> read(String fileId) async {
    if (fileId.isEmpty || fileId.length > 128) {
      throw const FormatException('Invalid file identity');
    }
    void checkAccess() {
      if (!accessIsCurrent()) {
        throw StateError('Vault access changed during file download');
      }
    }

    try {
      checkAccess();
      final matches = (await export.listFiles())
          .where((row) => row['file_id'] == fileId)
          .toList();
      checkAccess();
      if (matches.length != 1) {
        throw const FormatException('Older file is unavailable');
      }
      final listed = matches.single;
      final chars = listed['ciphertext_chars'];
      final declaredSize = listed['file_size'];
      if (chars is! int || chars <= 0 ||
          chars > LegacyCiphertextExportClient.maxTotalChars ||
          declaredSize is! int || declaredSize < 0 ||
          declaredSize > LegacyCiphertextExportClient.maxTotalChars) {
        throw const FormatException('Older file needs another download path');
      }
      final source = await export.readFileSource(
        fileId: fileId,
        ciphertextChars: chars,
      );
      checkAccess();
      if (!RegExp(r'^[A-Za-z0-9_-]{43}$')
              .hasMatch(source.sourceSnapshot) ||
          source.ciphertext.length != chars ||
          source.sourceMetadata['file_size'] != declaredSize) {
        throw const FormatException('Older file changed during download');
      }
      final bytes = await codec.decodeLegacyFileBytes(source.ciphertext);
      checkAccess();
      if (bytes.length != declaredSize) {
        throw const FormatException('Older file size did not match');
      }
      return bytes;
    } finally {
      export.clearGrant();
    }
  }
}
