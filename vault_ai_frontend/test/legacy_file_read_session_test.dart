import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_file_read_session.dart';

void main() {
  test('eleven concurrent older files reuse one proof and serialize pages',
      () async {
    final key = SecretKey(List<int>.filled(32, 7));
    final expected = List<int>.generate(16, (index) => index);
    final box = await AesGcm.with256bits().encrypt(
      expected,
      secretKey: key,
      nonce: List<int>.filled(12, 3),
    );
    final ciphertext = base64Encode(
      <int>[...box.nonce, ...box.cipherText, ...box.mac.bytes],
    );
    var proofCount = 0;
    var sequence = 0;
    var pageCount = 0;
    final export = LegacyCiphertextExportClient(
      proofProvider: () async {
        proofCount++;
        return 'synthetic-proof';
      },
      post: (path, body) async {
        expect(body.containsKey('pin'), isFalse);
        expect(body.containsKey('vault_name'), isFalse);
        if (path.endsWith('/start')) {
          return <String, dynamic>{
            'export_token': 'synthetic-grant',
            'next_sequence': 0,
            'pages_remaining': 16,
            'bytes_remaining': 32 * 1024 * 1024,
            'expires_at': DateTime.now()
                .toUtc()
                .add(const Duration(minutes: 5))
                .toIso8601String(),
          };
        }
        expect(path, endsWith('/page'));
        expect(body['sequence'], sequence);
        sequence++;
        pageCount++;
        final cursor = <String, dynamic>{
          'next_sequence': sequence,
          'pages_remaining': 16 - sequence,
          'bytes_remaining': 32 * 1024 * 1024 - sequence * 1024,
        };
        if (body['mode'] == 'list_files') {
          return <String, dynamic>{
            ...cursor,
            'records': <Map<String, dynamic>>[
              for (var i = 0; i < 11; i++)
                <String, dynamic>{
                  'file_id': 'file-$i',
                  'file_size': expected.length,
                  'ciphertext_chars': ciphertext.length,
                },
            ],
            'has_more': false,
          };
        }
        expect(body['mode'], 'read_file');
        return <String, dynamic>{
          ...cursor,
          'file_id': body['file_id'],
          'offset': 0,
          'ciphertext_chunk': ciphertext,
          'total_chars': ciphertext.length,
          'next_offset': ciphertext.length,
          'done': true,
          'source_snapshot': 'S' * 43,
          'source_metadata': <String, dynamic>{'file_size': expected.length},
        };
      },
    );
    final reader = LegacyFileReadSession(
      export: export,
      codec: LegacyCiphertextMigrationCodec(legacyKey: key, mvk: key),
      isCurrent: () => true,
    );
    final results = await Future.wait([
      for (var i = 0; i < 11; i++) reader.readFile('file-$i'),
    ]);
    expect(
        results
            .every((result) => result.bytes.toString() == expected.toString()),
        isTrue);
    expect(proofCount, 1);
    expect(pageCount, 12);
    Uint8List? rejectedBytes;
    await expectLater(
      reader.readFileWith('file-0', (opened) async {
        rejectedBytes = opened.bytes;
        throw const FormatException('Source metadata changed');
      }),
      throwsFormatException,
    );
    expect(rejectedBytes, isNotNull);
    expect(rejectedBytes, everyElement(0));
    reader.close();
    await expectLater(reader.readFile('file-0'), throwsStateError);
    expect(pageCount, 13);
  });

  test('bounded older text read stops before fetching oversized ciphertext',
      () async {
    var readPages = 0;
    final key = SecretKey(List<int>.filled(32, 7));
    final reader = LegacyFileReadSession(
      export: LegacyCiphertextExportClient(
        proofProvider: () async => 'synthetic-proof',
        post: (path, body) async {
          if (path.endsWith('/start')) {
            return <String, dynamic>{
              'export_token': 'synthetic-grant',
              'next_sequence': 0,
              'pages_remaining': 16,
              'bytes_remaining': 32 * 1024 * 1024,
              'expires_at': DateTime.now()
                  .toUtc()
                  .add(const Duration(minutes: 5))
                  .toIso8601String(),
            };
          }
          if (body['mode'] == 'list_files') {
            return <String, dynamic>{
              'next_sequence': 1,
              'pages_remaining': 15,
              'bytes_remaining': 32 * 1024 * 1024,
              'records': [
                {
                  'file_id': 'too-big',
                  'file_size': 130 * 1024,
                  'ciphertext_chars': 180 * 1024,
                },
              ],
              'has_more': false,
            };
          }
          readPages++;
          throw StateError('Oversized file must not be fetched');
        },
      ),
      codec: LegacyCiphertextMigrationCodec(legacyKey: key, mvk: key),
      isCurrent: () => true,
    );
    await expectLater(
      reader.readFileWith('too-big', (opened) async => opened,
          maxBytes: 128 * 1024),
      throwsFormatException,
    );
    expect(readPages, 0);
    reader.close();
  });
}
