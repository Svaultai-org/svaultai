/// Keep a file's displayed labels paired with the encrypted bytes opened.
/// An older device can rename a file between inventory and download.
void requireUnchangedLegacyFileMetadata(
  Map<String, dynamic> listed,
  Map<String, dynamic> source, {
  bool sourceIsExport = false,
}) {
  const encryptedLabels = <String>{
    'file_name_ciphertext',
    'saved_name_ciphertext',
    'content_type_ciphertext',
    'detected_type_ciphertext',
    'detected_service_ciphertext',
    'asset_type_ciphertext',
  };
  for (final field in encryptedLabels) {
    if (listed[field] != source[field]) {
      throw const FormatException('Older file labels changed');
    }
  }
  if (listed['file_size'] != source['file_size']) {
    throw const FormatException('Older file size changed');
  }
  if (sourceIsExport) {
    // Old clients can update readable columns without updating encrypted
    // labels. Do not pair those new names with a stale label from the list.
    for (final field in const <String>[
      'file_name',
      'saved_name',
      'content_type',
      'detected_type',
      'detected_service',
      'asset_type',
    ]) {
      final plain = source[field];
      if (plain is String && listed[field] != plain) {
        throw const FormatException('Older file labels changed');
      }
    }
  } else {
    for (final field in const <String>[
      'storage_mode',
      'chunk_size',
      'chunk_count',
      'name_version',
    ]) {
      if (listed[field] != source[field]) {
        throw const FormatException('Older file metadata changed');
      }
    }
  }
}
