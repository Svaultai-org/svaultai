import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_file_metadata_consistency.dart';

void main() {
  final listed = <String, dynamic>{
    'file_size': 3,
    'storage_mode': 'inline',
    'file_name': 'photo.jpg',
    'saved_name': 'Beach photo',
    'file_name_ciphertext': 'encrypted-original-name',
    'saved_name_ciphertext': 'encrypted-display-name',
  };

  test('accepts the same exported name and size snapshot', () {
    requireUnchangedLegacyFileMetadata(
        listed,
        <String, dynamic>{
          'file_size': 3,
          'file_name': null,
          'saved_name': null,
          'file_name_ciphertext': 'encrypted-original-name',
          'saved_name_ciphertext': 'encrypted-display-name',
        },
        sourceIsExport: true);
  });

  test('rejects a concurrent encrypted rename before returning file', () {
    expect(
      () => requireUnchangedLegacyFileMetadata(
          listed,
          <String, dynamic>{
            'file_size': 3,
            'file_name_ciphertext': 'encrypted-original-name',
            'saved_name_ciphertext': 'new-encrypted-name',
          },
          sourceIsExport: true),
      throwsFormatException,
    );
  });

  test('rejects an older-client plaintext rename with stale ciphertext', () {
    expect(
      () => requireUnchangedLegacyFileMetadata(
          listed,
          <String, dynamic>{
            'file_size': 3,
            'file_name_ciphertext': 'encrypted-original-name',
            'saved_name_ciphertext': 'encrypted-display-name',
            'saved_name': 'Changed on another device',
          },
          sourceIsExport: true),
      throwsFormatException,
    );
  });

  test('rejects a chunked metadata change during download', () {
    final before = <String, dynamic>{
      ...listed,
      'storage_mode': 'chunked',
      'chunk_size': 3,
      'chunk_count': 1,
    };
    final after = <String, dynamic>{...before, 'chunk_count': 2};
    expect(
      () => requireUnchangedLegacyFileMetadata(before, after),
      throwsFormatException,
    );
  });
}
