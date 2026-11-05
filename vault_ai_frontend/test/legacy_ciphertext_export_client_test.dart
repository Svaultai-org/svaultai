import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';

const _grantExpiry = '2099-01-01T00:00:00Z';
const _grantBytes = LegacyCiphertextExportClient.grantMaxBytes;

void main() {
  test('staging rejects a source that changes between export chunks', () async {
    final firstSnapshot = List<String>.filled(43, 'A').join();
    final changedSnapshot = List<String>.filled(43, 'B').join();
    var grants = 0;
    var pages = 0;
    final client = LegacyCiphertextExportClient(
      proofProvider: () async => 'synthetic-proof',
      post: (path, body) async {
        if (path.endsWith('/start')) {
          grants++;
          return <String, dynamic>{
            'export_token': 'synthetic-grant-$grants',
            'next_sequence': 0,
            'pages_remaining': 16,
            'bytes_remaining': _grantBytes,
            'expires_at': _grantExpiry,
          };
        }
        pages++;
        if (body['mode'] == 'list_items') {
          return <String, dynamic>{
            'next_sequence': 1,
            'pages_remaining': 15,
            'bytes_remaining': _grantBytes - 1024,
            'records': <Map<String, dynamic>>[],
            'has_more': false,
          };
        }
        final offset = body['offset'] as int;
        return <String, dynamic>{
          'next_sequence': body['sequence'] + 1,
          'pages_remaining': 16 - (body['sequence'] as int) - 1,
          'bytes_remaining': _grantBytes -
              ((body['sequence'] as int) + 1) * 1024,
          'item_id': 11,
          'offset': offset,
          'ciphertext_chunk': offset == 0 ? 'abc' : 'def',
          'total_chars': 6,
          'next_offset': offset + 3,
          'done': offset == 3,
          'source_snapshot': offset == 0 ? firstSnapshot : changedSnapshot,
          'source_metadata': const <String, dynamic>{
            'item_type': 'note', 'service': 'synthetic',
            'item_type_ciphertext': null, 'service_ciphertext': null,
          },
        };
      },
    );
    await expectLater(
      client.readItemSource(itemId: 11, ciphertextChars: 6),
      throwsA(isA<FormatException>()),
    );
    expect(pages, 2);
    await client.listItems();
    expect(grants, 2);
  });

  test(
      'exports paged IDs and exact ciphertext with fresh proof on grant rollover',
      () async {
    var grantNumber = 0;
    var proofNumber = 0;
    final pageBodies = <Map<String, dynamic>>[];
    final client = LegacyCiphertextExportClient(
      proofProvider: () async => 'synthetic-proof-${++proofNumber}',
      post: (path, body) async {
        if (path.endsWith('/start')) {
          expect(body.keys, <String>['zk_proof_token']);
          expect(body['zk_proof_token'], 'synthetic-proof-${grantNumber + 1}');
          grantNumber++;
          return <String, dynamic>{
            'export_token': 'synthetic-grant-$grantNumber',
            'next_sequence': 0,
            'pages_remaining': 2,
            'bytes_remaining': _grantBytes,
            'expires_at': _grantExpiry,
          };
        }
        expect(path, '/vault/legacy-ciphertext/export/page');
        expect(body.containsKey('pin'), isFalse);
        pageBodies.add(Map<String, dynamic>.from(body));
        final sequence = body['sequence'] as int;
        final remaining = 1 - sequence;
        final common = <String, dynamic>{
          'next_sequence': sequence + 1,
          'pages_remaining': remaining,
          'bytes_remaining': _grantBytes - (sequence + 1) * 1024,
        };
        if (body['mode'] == 'list_items') {
          if (body['after_item_id'] == null) {
            return <String, dynamic>{
              ...common,
              'records': <Map<String, dynamic>>[
                <String, dynamic>{'item_id': 11, 'ciphertext_chars': 6},
              ],
              'has_more': true,
              'next_after_item_id': 11,
            };
          }
          return <String, dynamic>{
            ...common,
            'records': <Map<String, dynamic>>[
              <String, dynamic>{'item_id': 12, 'ciphertext_chars': 6},
            ],
            'has_more': false,
          };
        }
        expect(body['mode'], 'read_item');
        expect(body['item_id'], 11);
        final offset = body['offset'] as int;
        expect(body['max_chars'], LegacyCiphertextExportClient.maxReadChars);
        final chunk = offset == 0 ? 'abc' : 'def';
        return <String, dynamic>{
          ...common,
          'item_id': 11,
          'offset': offset,
          'ciphertext_chunk': chunk,
          'total_chars': 6,
          'next_offset': offset + chunk.length,
          'done': offset != 0,
        };
      },
    );

    final rows = await client.listItems();
    expect(rows.map((r) => r['item_id']), <int>[11, 12]);
    expect(await client.readItemCiphertext(itemId: 11, ciphertextChars: 6),
        'abcdef');
    expect(proofNumber, 2);
    expect(pageBodies.map((b) => b['sequence']), <int>[0, 1, 0, 1]);
    expect(pageBodies[1]['after_item_id'], 11);
    client.clearGrant();
  });

  test('refuses wrong read offset and never retries an uncertain sequence',
      () async {
    var starts = 0;
    var pages = 0;
    final client = LegacyCiphertextExportClient(
      proofProvider: () async => 'synthetic-proof',
      post: (path, body) async {
        if (path.endsWith('/start')) {
          starts++;
          return <String, dynamic>{
            'export_token': 'synthetic-grant-$starts',
            'next_sequence': 0,
            'pages_remaining': 16,
            'bytes_remaining': _grantBytes,
            'expires_at': _grantExpiry,
          };
        }
        pages++;
        if (pages == 1) {
          return <String, dynamic>{
            'next_sequence': 1,
            'pages_remaining': 15,
            'bytes_remaining': _grantBytes - 1024,
            'offset': 3,
            'ciphertext_chunk': 'abc',
            'total_chars': 3,
            'next_offset': 6,
            'done': true,
          };
        }
        return <String, dynamic>{
          'next_sequence': 1,
          'pages_remaining': 15,
          'bytes_remaining': _grantBytes - 1024,
          'records': <Map<String, dynamic>>[],
          'has_more': false,
        };
      },
    );
    await expectLater(
      client.readFileCiphertext(fileId: 'synthetic-file', ciphertextChars: 3),
      throwsA(isA<FormatException>()),
    );
    expect((await client.listFiles()), isEmpty);
    expect(starts, 2);
    expect(pages, 2);
  });

  test('rejects excessive ciphertext length before proof or network', () async {
    var called = false;
    final client = LegacyCiphertextExportClient(
      proofProvider: () async {
        called = true;
        return 'synthetic-proof';
      },
      post: (_, __) async => <String, dynamic>{},
    );
    await expectLater(
      client.readFileCiphertext(
        fileId: 'synthetic-file',
        ciphertextChars: LegacyCiphertextExportClient.maxTotalChars + 1,
      ),
      throwsA(isA<FormatException>()),
    );
    expect(called, isFalse);
  });

  test('large synthetic ciphertext renews byte-limited grant at exact offset',
      () async {
    const totalChars = 9 * LegacyCiphertextExportClient.maxReadChars;
    final syntheticChunk =
        'A' * LegacyCiphertextExportClient.maxReadChars;
    var grants = 0;
    var proofs = 0;
    var nextSequence = 0;
    var bytesLeft = 0;
    var expectedOffset = 0;
    final client = LegacyCiphertextExportClient(
      proofProvider: () async => 'synthetic-proof-${++proofs}',
      post: (path, body) async {
        expect(body.containsKey('pin'), isFalse);
        if (path.endsWith('/start')) {
          grants++;
          expect(body['zk_proof_token'], 'synthetic-proof-$grants');
          nextSequence = 0;
          bytesLeft = _grantBytes;
          return <String, dynamic>{
            'export_token': 'synthetic-grant-$grants',
            'next_sequence': 0,
            'pages_remaining': 16,
            'bytes_remaining': bytesLeft,
            'expires_at': _grantExpiry,
          };
        }
        expect(body['export_token'], 'synthetic-grant-$grants');
        expect(body['sequence'], nextSequence);
        expect(body['mode'], 'read_file');
        expect(body['offset'], expectedOffset);
        expect(body['max_chars'], LegacyCiphertextExportClient.maxReadChars);
        expect(bytesLeft,
            greaterThanOrEqualTo(LegacyCiphertextExportClient.maxPageCharge));
        final length = totalChars - expectedOffset < syntheticChunk.length
            ? totalChars - expectedOffset
            : syntheticChunk.length;
        expectedOffset += length;
        nextSequence++;
        bytesLeft -= length + 1024;
        return <String, dynamic>{
          'next_sequence': nextSequence,
          'pages_remaining': 16 - nextSequence,
          'bytes_remaining': bytesLeft,
          'file_id': 'synthetic-large-file',
          'offset': expectedOffset - length,
          'ciphertext_chunk': syntheticChunk.substring(0, length),
          'total_chars': totalChars,
          'next_offset': expectedOffset,
          'done': expectedOffset == totalChars,
          'source_snapshot': 'A' * 43,
          'source_metadata': const <String, dynamic>{
            'file_size': 1,
            'saved_name': 'synthetic file',
          },
        };
      },
    );
    final source = await client.readFileSource(
      fileId: 'synthetic-large-file', ciphertextChars: totalChars,
    );
    expect(source.ciphertext.length, totalChars);
    expect(source.ciphertext.startsWith('A' * 32), isTrue);
    expect(source.ciphertext.endsWith('A' * 32), isTrue);
    expect(expectedOffset, totalChars);
    expect(grants, 2);
    expect(proofs, 2);
    client.clearGrant();
  });
}
