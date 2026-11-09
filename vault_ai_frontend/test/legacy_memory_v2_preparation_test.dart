import 'dart:convert';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_memory_v2_preparation.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

void main() {
  final legacyKey = SecretKey(List<int>.filled(32, 7));
  final mvk = SecretKey(List<int>.filled(32, 8));
  final codec = LegacyCiphertextMigrationCodec(legacyKey: legacyKey, mvk: mvk);
  final snapshot = List<String>.filled(43, 'S').join();

  Future<({LegacyMemoryV2Preparation preparation, List<String> calls})> setup(
      {bool corruptReadback = false,
      bool invalidateAfterStage = false,
      bool confirmAfterReadback = false,
      bool reuseProtectedCopy = false,
      void Function(int)? onProgress}) async {
    final legacyJson = jsonEncode(<String, dynamic>{
      'schema': 'vault_personal_memory_v1',
      'status': 'active',
      'memory_type': 'note',
      'title': 'Synthetic title',
      'value': 'Synthetic private memory',
    });
    final legacyCiphertext = await codec
        .encodeLegacyItem(jsonDecode(legacyJson) as Map<String, dynamic>);
    final existingCopy = b64urlEncode(await aesGcmWrap(
      await VaultKeyHierarchy(mvk).memoryKey(),
      utf8.encode(legacyJson),
    ));
    final calls = <String>[];
    var page = 0;
    var proof = 0;
    var current = true;
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
      accessIsCurrent: () => current,
      onProgress: onProgress,
      confirmAfterReadback: confirmAfterReadback,
      post: (path, body) async {
        calls.add(path);
        final wire = jsonEncode(body);
        expect(wire, isNot(contains('Synthetic private memory')));
        expect(wire, isNot(contains('Synthetic title')));
        expect(body.containsKey('pin'), false);
        expect(body['source_snapshot'], snapshot);
        if (path.endsWith('/confirm')) {
          expect(confirmAfterReadback, true);
          expect(body['client_verified_readback'], true);
          expect(body['zk_proof_token'], 'synthetic-stage-proof-3');
          final readbackCiphertext =
              reuseProtectedCopy ? existingCopy : stagedCiphertext!;
          expect(
              body['payload_sha256'],
              b64urlEncode(crypto.sha256
                  .convert(
                    b64urlDecode(readbackCiphertext),
                  )
                  .bytes));
          return <String, dynamic>{
            'memory_id': 42,
            'source_snapshot': snapshot,
            'payload_sha256': body['payload_sha256'],
            'confirmed': true,
            'older_client_writes_blocked': true,
          };
        }
        expect(path, '/vault/memory/legacy-copy/42/stage');
        expect(body['client_verified_source'], true);
        expect(body['zk_proof_token'], 'synthetic-stage-proof-2');
        stagedCiphertext = body['payload_ciphertext'] as String;
        if (invalidateAfterStage) current = false;
        return <String, dynamic>{
          'memory_id': 42,
          'prepared': true,
          'active_legacy_unchanged': true,
          if (reuseProtectedCopy) 'reused_verified_copy': true,
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
          'payload_ciphertext': corruptReadback
              ? 'A' * 80
              : reuseProtectedCopy
                  ? existingCopy
                  : stagedCiphertext,
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
    final verified = <int>[];
    final action = await setup(
      corruptReadback: true,
      onProgress: verified.add,
    );
    await expectLater(action.preparation.prepare(), throwsFormatException);
    expect(verified, isEmpty);
  });

  test('explicit confirmation binds decrypted readback without plaintext',
      () async {
    final action = await setup(
      confirmAfterReadback: true,
      reuseProtectedCopy: true,
    );
    expect(await action.preparation.prepare(), 1);
    expect(action.calls.where((path) => path.endsWith('/confirm')).length, 1);
    expect(action.calls.last, '/vault/memory/legacy-copy/42/confirm');
  });

  test('confirmation never follows a changed readback', () async {
    final action = await setup(
      confirmAfterReadback: true,
      corruptReadback: true,
    );
    await expectLater(action.preparation.prepare(), throwsFormatException);
    expect(action.calls.where((path) => path.endsWith('/confirm')), isEmpty);
  });

  test('progress follows verified readback and stops after session change',
      () async {
    final verified = <int>[];
    final success = await setup(onProgress: verified.add);
    expect(await success.preparation.prepare(), 1);
    expect(verified, <int>[1]);

    verified.clear();
    final changed = await setup(
      invalidateAfterStage: true,
      onProgress: verified.add,
    );
    await expectLater(changed.preparation.prepare(), throwsStateError);
    expect(changed.calls.last, '/vault/memory/legacy-copy/42/stage');
    expect(verified, isEmpty);
  });

  test('owner edit keeps both ciphertext readers current, delete keeps source',
      () async {
    final old = <String, dynamic>{
      'schema': 'vault_personal_memory_v1',
      'status': 'active',
      'memory_type': 'note',
      'title': 'Synthetic title',
      'value': 'Synthetic private memory',
    };
    var legacyCiphertext = await codec.encodeLegacyItem(old);
    final memoryKey = await VaultKeyHierarchy(mvk).memoryKey();
    var copyCiphertext = b64urlEncode(
      await aesGcmWrap(memoryKey, utf8.encode(jsonEncode(old))),
    );
    var currentSnapshot = snapshot;
    final nextSnapshot = List<String>.filled(43, 'E').join();
    var deleted = false;
    var sequence = 0;
    final export = LegacyCiphertextExportClient(
      proofProvider: () async => 'synthetic-export-proof',
      post: (path, body) async {
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
        final common = <String, dynamic>{
          'next_sequence': ++sequence,
          'pages_remaining': 16 - sequence,
          'bytes_remaining': 32 * 1024 * 1024 - sequence * 1024,
        };
        if (body['mode'] == 'list_memories') {
          return <String, dynamic>{
            ...common,
            'records': [
              {
                'memory_id': 42,
                'memory_type': 'note',
                'ciphertext_chars': legacyCiphertext.length
              },
            ],
            'has_more': false
          };
        }
        expect(body['mode'], 'read_memory');
        return <String, dynamic>{
          ...common,
          'memory_id': 42,
          'offset': 0,
          'ciphertext_chunk': legacyCiphertext,
          'total_chars': legacyCiphertext.length,
          'next_offset': legacyCiphertext.length,
          'done': true,
          'source_snapshot': currentSnapshot,
          'source_metadata': {'memory_type': 'note'},
        };
      },
    );
    final action = LegacyMemoryV2Preparation(
      export: export,
      codec: codec,
      mvk: mvk,
      proofProvider: () async => 'synthetic-action-proof',
      accessIsCurrent: () => true,
      post: (path, body) async {
        final wire = jsonEncode(body);
        expect(wire, isNot(contains('Synthetic private memory')));
        expect(wire, isNot(contains('Synthetic edited memory')));
        expect(body.containsKey('pin'), false);
        if (path.endsWith('/edit')) {
          expect(body['source_snapshot'], snapshot);
          expect(body['expected_memory_generation'], '42');
          expect(body['zk_proof_token'], 'synthetic-action-proof');
          legacyCiphertext = body['legacy_payload_ciphertext'] as String;
          copyCiphertext = body['payload_ciphertext'] as String;
          final reopenedOld = await codec.decodeLegacyString(legacyCiphertext);
          final reopenedNew = utf8.decode(await aesGcmUnwrap(
            memoryKey,
            b64urlDecode(copyCiphertext),
          ));
          expect(reopenedOld, reopenedNew);
          expect(jsonDecode(reopenedNew)['value'], 'Synthetic edited memory');
          currentSnapshot = nextSnapshot;
          return <String, dynamic>{
            'memory_id': 42,
            'source_snapshot': nextSnapshot,
            'active_legacy_updated': true,
            'prepared_copy_updated': true,
          };
        }
        expect(path, '/vault/memory/legacy-copy/42/delete');
        expect(body['source_snapshot'], nextSnapshot);
        expect(body['client_confirmed_delete'], true);
        deleted = true;
        return <String, dynamic>{
          'memory_id': 42,
          'hidden_from_old_clients': true,
          'original_ciphertext_preserved': true,
        };
      },
      get: (path) async {
        expect(path, '/vault/memory/legacy-copy/42/readback');
        return <String, dynamic>{
          'memory_id': 42,
          'source_snapshot': currentSnapshot,
          'memory_record_id': 'memory-migrated-42',
          'memory_type': 'note',
          'payload_ciphertext': copyCiphertext,
        };
      },
    );
    await action.edit(current: {
      'legacy_memory_id': 42,
      'source_snapshot': snapshot,
    }, updated: {
      'value': 'Synthetic edited memory'
    }, expectedMemoryGeneration: '42');
    expect(deleted, false);
    await action.delete({
      'legacy_memory_id': 42,
      'source_snapshot': nextSnapshot,
    });
    expect(deleted, true);
    expect((await codec.decodeLegacyString(legacyCiphertext)),
        contains('Synthetic edited memory'));
  });
}
