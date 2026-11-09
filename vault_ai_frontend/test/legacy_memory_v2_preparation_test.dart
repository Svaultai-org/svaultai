import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_memory_v2_preparation.dart';

void main() {
  final legacyKey = SecretKey(List<int>.filled(32, 7));
  final mvk = SecretKey(List<int>.filled(32, 8));
  final codec = LegacyCiphertextMigrationCodec(legacyKey: legacyKey, mvk: mvk);
  final snapshot = List<String>.filled(43, 'S').join();

  Future<({LegacyMemoryV2Preparation preparation, List<String> calls})> setup(
      {bool corruptReadback = false}) async {
    final legacyJson = jsonEncode(<String, dynamic>{
      'schema': 'vault_personal_memory_v1',
      'status': 'active',
      'memory_type': 'note',
      'title': 'Synthetic title',
      'value': 'Synthetic private memory',
    });
    final legacyCiphertext = await codec
        .encodeLegacyItem(jsonDecode(legacyJson) as Map<String, dynamic>);
    final calls = <String>[];
    var page = 0;
    var proof = 0;
    String? stagedCiphertext;
    final export = LegacyCiphertextExportClient(
      proofProvider: () async => 'synthetic-export-proof-${++proof}',
      post: (path, body) async {
        calls.add(path);
        expect(jsonEncode(body), isNot(contains('Synthetic private memory')));
        expect(body.containsKey('pin'), false);
        if (path.endsWith('/start')) {
          return <String, dynamic>{
            'export_token': 'synthetic-grant',
            'expires_at': '2099-01-01T00:00:00Z',
            'next_sequence': 0,
            'pages_remaining': 16,
            'bytes_remaining': 32 * 1024 * 1024,
          };
        }
        final mode = body['mode'];
        final sequence = page++;
        final common = <String, dynamic>{
          'next_sequence': sequence + 1,
          'pages_remaining': 15 - sequence,
          'bytes_remaining': 32 * 1024 * 1024 - (sequence + 1) * 1024,
        };
        if (mode == 'list_memories') {
          return <String, dynamic>{
            ...common,
            'records': <Map<String, dynamic>>[
              <String, dynamic>{
                'memory_id': 42,
                'memory_type': 'note',
                'ciphertext_chars': legacyCiphertext.length,
              },
            ],
            'has_more': false,
          };
        }
        expect(mode, 'read_memory');
        expect(body['memory_id'], 42);
        return <String, dynamic>{
          ...common,
          'memory_id': 42,
          'offset': 0,
          'ciphertext_chunk': legacyCiphertext,
          'total_chars': legacyCiphertext.length,
          'next_offset': legacyCiphertext.length,
          'done': true,
          'source_snapshot': snapshot,
          'source_metadata': <String, dynamic>{'memory_type': 'note'},
        };
      },
    );
    final preparation = LegacyMemoryV2Preparation(
      export: export,
      codec: codec,
      mvk: mvk,
      proofProvider: () async => 'synthetic-stage-proof-${++proof}',
      accessIsCurrent: () => true,
      post: (path, body) async {
        calls.add(path);
        expect(path, '/vault/memory/legacy-copy/42/stage');
        final wire = jsonEncode(body);
        expect(wire, isNot(contains('Synthetic private memory')));
        expect(wire, isNot(contains('Synthetic title')));
        expect(body.containsKey('pin'), false);
        expect(body['source_snapshot'], snapshot);
        expect(body['client_verified_source'], true);
        expect(body['zk_proof_token'], 'synthetic-stage-proof-2');
        stagedCiphertext = body['payload_ciphertext'] as String;
        return <String, dynamic>{
          'memory_id': 42,
          'prepared': true,
          'active_legacy_unchanged': true,
        };
      },
      get: (path) async {
        calls.add(path);
        expect(path, '/vault/memory/legacy-copy/42/readback');
        return <String, dynamic>{
          'memory_id': 42,
          'source_snapshot': snapshot,
          'memory_record_id': 'memory-migrated-42',
          'memory_type': 'note',
          'payload_ciphertext': corruptReadback ? 'A' * 80 : stagedCiphertext,
        };
      },
    );
    return (preparation: preparation, calls: calls);
  }

  test('prepares exact owner-side Memory copy without changing old source',
      () async {
    final action = await setup();
    expect(await action.preparation.prepare(), 1);
    expect(action.calls, <String>[
      '/vault/legacy-ciphertext/export/start',
      '/vault/legacy-ciphertext/export/page',
      '/vault/legacy-ciphertext/export/page',
      '/vault/memory/legacy-copy/42/stage',
      '/vault/memory/legacy-copy/42/readback',
    ]);
  });

  test('mismatched Memory copy readback refuses success', () async {
    final action = await setup(corruptReadback: true);
    await expectLater(action.preparation.prepare(), throwsFormatException);
  });
}
