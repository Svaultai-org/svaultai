import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_saved_item_read_session.dart';

void main() {
  test('87 concurrent details serialize pages and reuse at most six proofs',
      () async {
    var proofs = 0;
    var listPages = 0;
    var readPages = 0;
    final nextSequence = <String, int>{};
    final export = LegacyCiphertextExportClient(
      proofProvider: () async {
        proofs++;
        return 'synthetic-proof-$proofs';
      },
      post: (path, body) async {
        if (path == '/vault/legacy-ciphertext/export/start') {
          final token = 'grant-$proofs';
          nextSequence[token] = 0;
          return <String, dynamic>{
            'export_token': token,
            'next_sequence': 0,
            'pages_remaining': 16,
            'bytes_remaining': LegacyCiphertextExportClient.grantMaxBytes,
            'expires_at': DateTime.now().toUtc()
                .add(const Duration(minutes: 5)).toIso8601String(),
          };
        }
        expect(path, '/vault/legacy-ciphertext/export/page');
        final token = body['export_token'];
        final sequence = body['sequence'];
        expect(sequence, nextSequence[token]);
        nextSequence[token] = (sequence as int) + 1;
        final remaining = 16 - nextSequence[token]!;
        final envelope = <String, dynamic>{
          'next_sequence': nextSequence[token],
          'pages_remaining': remaining,
          'bytes_remaining':
              LegacyCiphertextExportClient.grantMaxBytes -
                  nextSequence[token]! * 1024,
        };
        if (body['mode'] == 'list_items') {
          listPages++;
          final after = body['after_item_id'];
          final first = after == null;
          final start = first ? 1 : 51;
          final end = first ? 50 : 87;
          return <String, dynamic>{
            ...envelope,
            'records': <Map<String, dynamic>>[
              for (var id = start; id <= end; id++)
                <String, dynamic>{'item_id': id, 'ciphertext_chars': 1},
            ],
            'has_more': first,
            'next_after_item_id': end,
          };
        }
        expect(body['mode'], 'read_item');
        readPages++;
        return <String, dynamic>{
          ...envelope,
          'ciphertext_chunk': 'x',
          'total_chars': 1,
          'offset': 0,
          'next_offset': 1,
          'done': true,
        };
      },
    );
    final reader = LegacySavedItemReadSession(
      export: export, isCurrent: () => true,
    );
    final results = await Future.wait([
      for (var id = 1; id <= 87; id++) reader.readItem(id),
    ]);
    expect(results, hasLength(87));
    expect(results.last.record['item_id'], 87);
    expect(results.last.ciphertext, 'x');
    expect(listPages, 2);
    expect(readPages, 87);
    expect(proofs, 6);
    reader.close();
    await expectLater(reader.readItem(1), throwsStateError);
  });
}
