import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_saved_item_read_session.dart';

void main() {
  final snapshot = List<String>.filled(43, 'A').join();
  final labels = <String, dynamic>{
    'item_type': null,
    'service': null,
    'item_type_ciphertext': null,
    'service_ciphertext': null,
  };

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
            'expires_at': DateTime.now()
                .toUtc()
                .add(const Duration(minutes: 5))
                .toIso8601String(),
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
          'bytes_remaining': LegacyCiphertextExportClient.grantMaxBytes -
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
          'item_id': body['item_id'],
          'ciphertext_chunk': 'x',
          'total_chars': 1,
          'offset': 0,
          'next_offset': 1,
          'done': true,
          'source_snapshot': snapshot,
          'source_metadata': labels,
        };
      },
    );
    final reader = LegacySavedItemReadSession(
      export: export,
      isCurrent: () => true,
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

  test('decode failure invalidates grant before the next queued read',
      () async {
    var proofs = 0;
    var pages = 0;
    final nextSequence = <String, int>{};
    final export = LegacyCiphertextExportClient(
      proofProvider: () async => 'proof-${++proofs}',
      post: (path, body) async {
        if (path == '/vault/legacy-ciphertext/export/start') {
          final token = 'grant-$proofs';
          nextSequence[token] = 0;
          return <String, dynamic>{
            'export_token': token,
            'next_sequence': 0,
            'pages_remaining': 16,
            'bytes_remaining': LegacyCiphertextExportClient.grantMaxBytes,
            'expires_at': DateTime.now()
                .toUtc()
                .add(const Duration(minutes: 5))
                .toIso8601String(),
          };
        }
        pages++;
        final token = body['export_token'];
        final sequence = body['sequence'];
        expect(sequence, nextSequence[token]);
        nextSequence[token] = (sequence as int) + 1;
        final envelope = <String, dynamic>{
          'next_sequence': nextSequence[token],
          'pages_remaining': 16 - nextSequence[token]!,
          'bytes_remaining': LegacyCiphertextExportClient.grantMaxBytes -
              nextSequence[token]! * 1024,
        };
        if (body['mode'] == 'list_items') {
          return <String, dynamic>{
            ...envelope,
            'records': <Map<String, dynamic>>[
              for (var id = 1; id <= 2; id++)
                <String, dynamic>{'item_id': id, 'ciphertext_chars': 1},
            ],
            'has_more': false,
          };
        }
        return <String, dynamic>{
          ...envelope,
          'item_id': body['item_id'],
          'ciphertext_chunk': 'x',
          'total_chars': 1,
          'offset': 0,
          'next_offset': 1,
          'done': true,
          'source_snapshot': snapshot,
          'source_metadata': labels,
        };
      },
    );
    final reader = LegacySavedItemReadSession(
      export: export,
      isCurrent: () => true,
    );
    final enteredDecode = Completer<void>();
    final finishDecode = Completer<void>();
    final first = reader.readItemWith<void>(1, (_, __) async {
      enteredDecode.complete();
      await finishDecode.future;
      throw const FormatException('synthetic local decode failure');
    });
    final firstFailure = expectLater(first, throwsFormatException);
    await enteredDecode.future;
    final second = reader.readItem(2);
    await Future<void>.delayed(Duration.zero);
    expect(pages, 2); // The second export waits for local decode.
    finishDecode.complete();
    await firstFailure;
    final result = await second;
    expect(result.record['item_id'], 2);
    expect(pages, 4);
    expect(proofs, 2); // The failed grant is replaced, never reused mid-page.
    reader.close();
  });

  test('a changed title cannot be paired with cached list metadata', () async {
    var proofs = 0;
    var lists = 0;
    var pages = 0;
    var currentTitle = 'old title';
    final nextSequence = <String, int>{};
    final export = LegacyCiphertextExportClient(
      proofProvider: () async => 'proof-${++proofs}',
      post: (path, body) async {
        if (path == '/vault/legacy-ciphertext/export/start') {
          final token = 'grant-$proofs';
          nextSequence[token] = 0;
          return <String, dynamic>{
            'export_token': token,
            'next_sequence': 0,
            'pages_remaining': 16,
            'bytes_remaining': LegacyCiphertextExportClient.grantMaxBytes,
            'expires_at': DateTime.now()
                .toUtc()
                .add(const Duration(minutes: 5))
                .toIso8601String(),
          };
        }
        pages++;
        final token = body['export_token'];
        expect(body['sequence'], nextSequence[token]);
        nextSequence[token] = nextSequence[token]! + 1;
        final envelope = <String, dynamic>{
          'next_sequence': nextSequence[token],
          'pages_remaining': 16 - nextSequence[token]!,
          'bytes_remaining': LegacyCiphertextExportClient.grantMaxBytes -
              nextSequence[token]! * 1024,
        };
        if (body['mode'] == 'list_items') {
          lists++;
          return <String, dynamic>{
            ...envelope,
            'records': <Map<String, dynamic>>[
              <String, dynamic>{
                'item_id': 42,
                'ciphertext_chars': 1,
                'item_type': 'login',
                'service': currentTitle,
              },
            ],
            'has_more': false,
          };
        }
        return <String, dynamic>{
          ...envelope,
          'item_id': body['item_id'],
          'ciphertext_chunk': 'x',
          'total_chars': 1,
          'offset': 0,
          'next_offset': 1,
          'done': true,
          'source_snapshot': snapshot,
          'source_metadata': <String, dynamic>{
            'item_type': 'login',
            'service': currentTitle,
            'item_type_ciphertext': null,
            'service_ciphertext': null,
          },
        };
      },
    );
    final reader = LegacySavedItemReadSession(
      export: export,
      isCurrent: () => true,
    );
    final first = await reader.readItem(42);
    expect(first.record['service'], 'old title');
    currentTitle = 'new title';
    await expectLater(reader.readItem(42), throwsStateError);
    final refreshed = await reader.readItem(42);
    expect(refreshed.record['service'], 'new title');
    expect(lists, 2);
    expect(pages, 5);
    expect(proofs, 2);
    reader.close();
  });
}
