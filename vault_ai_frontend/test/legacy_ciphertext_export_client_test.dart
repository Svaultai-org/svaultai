import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';

void main() {
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
          };
        }
        pages++;
        if (pages == 1) {
          return <String, dynamic>{
            'next_sequence': 1,
            'pages_remaining': 15,
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
}
