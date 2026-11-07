import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/metadata_migration_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart'
    as sessions;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart'
    as hierarchy;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

// No actual legacy/user rows or backend writes. These values model exactly the
// separate fields produced by the metadata next-batch contract.
const _title = 'Synthetic archive renewal';
const _value = 'SYNTHETIC-MIGRATION-CONTENT-CANARY-2819';

class _MigrationStore {
  _MigrationStore(List<Map<String, dynamic>> plaintext,
      {this.batchSize = 1, this.table = 'vault_ai_memory'})
      : pending = [
          for (var i = 0; i < plaintext.length; i++)
            {'row_id': 'owned-${i + 1}', 'plaintext': plaintext[i]}
        ],
        preservedSources = List<Map<String, dynamic>>.from(
            plaintext.map((row) => Map<String, dynamic>.from(row)));

  final List<Map<String, dynamic>> pending;
  final List<Map<String, dynamic>> preservedSources;
  final int batchSize;
  final String table;
  final ciphertext = <String, Map<String, dynamic>>{};
  final attempts = <Map<String, dynamic>>[];
  bool failBeforeCommit = false;
  bool failAfterCommit = false;
  bool corruptReadback = false;
  bool safeCapabilityAvailable = true;

  Future<Map<String, dynamic>> get(String path, {String? bearerToken}) async {
    if (path.endsWith('/memory-capabilities')) {
      if (!safeCapabilityAvailable) return {};
      return {
        'memory_payload_format': memoryMigrationPayloadFormat,
        'preserves_legacy_source': true,
        'opaque_readback': true,
      };
    }
    if (path.contains('/memory-readback/')) {
      final rowId = Uri.decodeComponent(path.split('/').last);
      return {
        'row_id': rowId,
        'payload_ciphertext': corruptReadback
            ? 'AA'
            : ciphertext[rowId]?['payload_ciphertext'],
      };
    }
    if (path.endsWith('/status')) {
      return {'completed_at': pending.isEmpty ? 'synthetic-completion' : null};
    }
    return {
      'table': pending.isEmpty ? '' : table,
      'rows': pending.take(batchSize).toList(),
      'remaining_estimate': pending.length
    };
  }

  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body,
      {String? bearerToken}) async {
    attempts
        .add(Map<String, dynamic>.from(jsonDecode(jsonEncode(body)) as Map));
    if (table == 'vault_ai_memory') {
      expect(body['memory_payload_format'], memoryMigrationPayloadFormat);
    }
    if (failBeforeCommit) {
      failBeforeCommit = false;
      throw StateError('synthetic failure before persistence');
    }
    var applied = 0;
    for (final row in body['rows'] as List) {
      final id = row['row_id'] as String;
      if (!ciphertext.containsKey(id)) {
        ciphertext[id] = Map<String, dynamic>.from(row['ciphertext'] as Map);
        pending.removeWhere((source) => source['row_id'] == id);
        applied++;
      }
    }
    if (failAfterCommit) {
      failAfterCommit = false;
      throw StateError('synthetic lost acknowledgement');
    }
    return {
      'applied': applied,
      'skipped': (body['rows'] as List).length - applied
    };
  }

  MetadataMigrationClient client({int maxBatches = 20}) =>
      MetadataMigrationClient(
          mvk: ZkActiveMvk.current()!,
          sessionToken: 'synthetic-migration-token',
          get: get,
          post: post,
          maxBatchesPerRun: maxBatches);
}

Future<Map<String, dynamic>> _openMemory(String ciphertext) async {
  final key =
      await hierarchy.VaultKeyHierarchy(ZkActiveMvk.current()!).memoryKey();
  return Map<String, dynamic>.from(jsonDecode(utf8.decode(await hierarchy
      .aesGcmUnwrap(key, hierarchy.b64urlDecode(ciphertext)))) as Map);
}

void main() {
  setUp(() {
    sessions.SessionTermination.instance.resetForTests();
    sessions.SessionTermination.instance
        .bindSession('synthetic-migration-token');
    ZkActiveMvk.set(
        mvk: SecretKey(List.filled(32, 42)),
        vaultId: 'synthetic-migration-vault',
        vaultHandle: 'synthetic-migration-handle');
  });
  tearDown(() {
    sessions.SessionTermination.instance.resetForTests();
    ZkActiveMvk.clear();
  });

  test('split batches resume without rewriting the first persisted envelope',
      () async {
    final rows = [
      {
        'memory_key': _title,
        'memory_value': _value,
        'memory_normalized_key': _title.toLowerCase()
      },
      {'memory_key': 'Title only'},
      {'memory_value': 'Value only', 'memory_normalized_key': null},
    ];
    final store = _MigrationStore(rows, batchSize: 1);
    final first = await store.client(maxBatches: 1).runOnce();
    expect(first.rowsApplied, 1);
    expect(first.completed, isFalse);
    final firstEnvelope = store.ciphertext['owned-1']!['payload_ciphertext'];
    final resumed = await store.client().runOnce();
    expect(resumed.completed, isTrue);
    expect(resumed.rowsApplied, 2);
    expect(store.ciphertext, hasLength(3));
    expect(store.ciphertext['owned-1']!['payload_ciphertext'], firstEnvelope);
    expect(store.preservedSources, rows);
    for (var i = 0; i < rows.length; i++) {
      expect(
          await _openMemory(store
              .ciphertext['owned-${i + 1}']!['payload_ciphertext'] as String),
          rows[i]);
    }
  });

  test('null, missing and unknown JSON fields are preserved together',
      () async {
    final row = <String, dynamic>{
      'memory_key': _title,
      'memory_value': null,
      'future_fields': {
        'tags': ['owned', 'synthetic'],
        'number': 7,
        'flag': false
      }
    };
    final store = _MigrationStore([row]);
    expect((await store.client().runOnce()).completed, isTrue);
    expect(
        await _openMemory(
            store.ciphertext.values.single['payload_ciphertext'] as String),
        row);
    expect(jsonEncode(store.attempts), isNot(contains(_title)));
    expect(jsonEncode(store.attempts), isNot(contains('future_fields')));
  });

  test(
      'failed apply retains source fields and a retry preserves the whole memory',
      () async {
    final row = <String, dynamic>{'memory_key': _title, 'memory_value': _value};
    final store = _MigrationStore([row])..failBeforeCommit = true;
    final failed = await store.client().runOnce();
    expect(failed.error, isNotNull);
    expect(store.pending.single['plaintext'], row);
    expect(store.ciphertext, isEmpty);
    expect((await store.client().runOnce()).completed, isTrue);
    expect(
        await _openMemory(
            store.ciphertext.values.single['payload_ciphertext'] as String),
        row);
    expect(store.attempts, hasLength(2));
    expect(store.preservedSources.single, row);
  });

  test('lost acknowledgement resumes without replacing the durable envelope',
      () async {
    final row = <String, dynamic>{'memory_key': _title, 'memory_value': _value};
    final store = _MigrationStore([row])..failAfterCommit = true;
    expect((await store.client().runOnce()).error, isNotNull);
    final durable =
        store.ciphertext.values.single['payload_ciphertext'] as String;
    expect((await store.client().runOnce()).completed, isTrue);
    expect(store.attempts, hasLength(1));
    expect(store.ciphertext.values.single['payload_ciphertext'], durable);
    expect(await _openMemory(durable), row);
    expect(store.preservedSources.single, row);
  });

  test('old server capability blocks memory write before transmission', () async {
    final row = <String, dynamic>{'memory_key': _title, 'memory_value': _value};
    final store = _MigrationStore([row])..safeCapabilityAvailable = false;
    final result = await store.client().runOnce();
    expect(result.error, isNotNull);
    expect(store.attempts, isEmpty);
    expect(store.ciphertext, isEmpty);
    expect(store.preservedSources.single, row);
  });

  test('mismatched readback reports failure while source stays intact', () async {
    final row = <String, dynamic>{'memory_key': _title, 'memory_value': _value};
    final store = _MigrationStore([row])..corruptReadback = true;
    final result = await store.client().runOnce();
    expect(result.error, isNotNull);
    expect(store.ciphertext, hasLength(1));
    expect(store.preservedSources.single, row);
  });

  test('preexisting malformed copy is never replaced by a new nonce', () async {
    final row = <String, dynamic>{'memory_key': _title, 'memory_value': _value};
    final store = _MigrationStore([row]);
    store.ciphertext['owned-1'] = {'payload_ciphertext': 'AA'};
    final result = await store.client().runOnce();
    expect(result.error, isNotNull);
    expect(store.ciphertext['owned-1']!['payload_ciphertext'], 'AA');
    expect(store.preservedSources.single, row);
  });

  test(
      'non-memory metadata retains its separate ciphertext columns and contract',
      () async {
    final store = _MigrationStore([
      {'file_name': 'owned.pdf', 'saved_name': 'Owned archive'}
    ], table: 'uploaded_files');
    expect((await store.client().runOnce()).completed, isTrue);
    expect(store.attempts.single.containsKey('memory_payload_format'), isFalse);
    final columns = store.ciphertext.values.single;
    expect(columns.keys.toSet(),
        {'file_name_ciphertext', 'saved_name_ciphertext'});
    final key =
        await hierarchy.VaultKeyHierarchy(ZkActiveMvk.current()!).metadataKey();
    expect(
        utf8.decode(await hierarchy.aesGcmUnwrap(
            key,
            hierarchy
                .b64urlDecode(columns['saved_name_ciphertext'] as String))),
        'Owned archive');
  });

  test(
      'legacy memory migration preserves every field in a readable aggregate envelope',
      () async {
    Map<String, dynamic>? applied;
    final migration = MetadataMigrationClient(
        mvk: ZkActiveMvk.current()!,
        sessionToken: 'synthetic-migration-token',
        maxBatchesPerRun: 1,
        get: (path, {bearerToken}) async {
          if (path.endsWith('/memory-capabilities')) {
            return {
              'memory_payload_format': memoryMigrationPayloadFormat,
              'preserves_legacy_source': true,
              'opaque_readback': true,
            };
          }
          if (path.contains('/memory-readback/')) {
            return {
              'payload_ciphertext':
                  ((applied!['rows'] as List).single['ciphertext']
                      as Map)['payload_ciphertext'],
            };
          }
          return {
            'table': 'vault_ai_memory',
            'rows': [
              {
                'row_id': 'owned-memory-1',
                'plaintext': {
                  'memory_key': _title,
                  'memory_value': _value,
                  'memory_normalized_key': _title.toLowerCase(),
                }
              }
            ],
          };
        },
        post: (path, body, {bearerToken}) async {
          expect(path, '/vault/metadata-migration/apply-batch');
          expect(body['memory_payload_format'], memoryMigrationPayloadFormat);
          applied = Map<String, dynamic>.from(body);
          return {'applied': 1, 'skipped': 0};
        });
    await migration.runOnce();
    final ciphertext = ((applied!['rows'] as List).single['ciphertext']
        as Map)['payload_ciphertext'] as String;
    final key =
        await hierarchy.VaultKeyHierarchy(ZkActiveMvk.current()!).memoryKey();
    final plaintext =
        await hierarchy.aesGcmUnwrap(key, hierarchy.b64urlDecode(ciphertext));
    Object? payload;
    try {
      payload = jsonDecode(utf8.decode(plaintext));
    } on FormatException {
      payload = null;
    }
    expect(payload, isA<Map>(),
        reason:
            'The ordinary memory reader requires an aggregate JSON object, not the last migrated scalar.');
    expect((payload as Map)['memory_key'], _title);
    expect(payload['memory_value'], _value);
    expect(payload['memory_normalized_key'], _title.toLowerCase());

    final client = VaultAIClient(
        baseUrl: 'http://127.0.0.1:1',
        httpClient: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/vault/ciphertext/vault-ai-memory');
          return http.Response(
              jsonEncode([
                {
                  'memory_id': 'owned-memory-1',
                  'memory_type': 'note',
                  'payload_ciphertext': ciphertext
                }
              ]),
              200);
        }));
    final inventory =
        await client.listZkMemories(authToken: 'synthetic-migration-token');
    expect(inventory['unavailable_count'], 0);
    expect((inventory['items'] as List).single['memory_value'], _value);
  });
}
