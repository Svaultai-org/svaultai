import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_content_migration_stager.dart';
import 'package:vault_ai_frontend/services/legacy_content_retirement_coordinator.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

final _mvk = SecretKey(List<int>.filled(32, 17));
final _source = List<String>.filled(43, 'A').join();
final _expires = DateTime.utc(2030, 1, 1);

LegacyStageReadbackEvidence _evidence({required bool file}) =>
    LegacyStageReadbackEvidence(
      isFile: file,
      recordId: file ? 'synthetic-file' : '7',
      sourceSnapshot: _source,
      readbackReceipt: file ? 'fr1.synthetic-receipt' : 'ir1.synthetic-receipt',
      receiptExpiresAt: _expires,
      verifiedExtraFields: false,
    );

Future<String> _encrypt(SecretKey key, String text) async =>
    b64urlEncode(await aesGcmWrap(key, utf8.encode(text)));

void main() {
  test('default-off and missing owner action stop before proof or network',
      () async {
    var calls = 0;
    final coordinator = LegacyContentRetirementCoordinator(
      accessIsCurrent: () => true,
      mvk: _mvk,
      now: () => DateTime.utc(2029, 1, 1),
      freshProof: () async { calls++; return 'proof'; },
      request: (_, __, [___]) async {
        calls++;
        return const MigrationReply(200, {});
      },
    );
    await expectLater(coordinator.complete([_evidence(file: false)],
        ownerInitiated: true), throwsStateError);
    final enabled = LegacyContentRetirementCoordinator(
      enabled: true,
      accessIsCurrent: () => true,
      mvk: _mvk,
      now: () => DateTime.utc(2029, 1, 1),
      freshProof: coordinator.freshProof,
      request: coordinator.request,
    );
    await expectLater(enabled.complete([_evidence(file: false)],
        ownerInitiated: false), throwsStateError);
    expect(calls, 0);
  });

  test('item exact readback receipt retires with one proof, then V2 opens',
      () async {
    final sent = <(String, String, Map<String, dynamic>?)>[];
    final key = await VaultKeyHierarchy(_mvk).metadataKey();
    final row = <String, dynamic>{
      'item_id': 7,
      'item_type_ciphertext': await _encrypt(key, 'login'),
      'service_ciphertext': await _encrypt(key, 'synthetic.example'),
      'payload_ciphertext': await _encrypt(key, jsonEncode({
        'fields': {'username': 'synthetic'},
        'legacy_record': {'username': 'synthetic'},
      })),
    };
    final coordinator = LegacyContentRetirementCoordinator(
      enabled: true, accessIsCurrent: () => true, mvk: _mvk,
      now: () => DateTime.utc(2029, 1, 1),
      freshProof: () async => 'one-use-opaque-proof',
      request: (method, path, [body]) async {
        sent.add((method, path, body));
        if (path.endsWith('/item-retire')) {
          return const MigrationReply(200, {
            'item_id': 7, 'retired': true, 'already_retired': false,
          });
        }
        expect(path, '/vault/ciphertext/vault-items');
        return MigrationReply(200, [row]);
      },
    );
    final result = await coordinator.complete([_evidence(file: false)],
        ownerInitiated: true);
    expect(result.itemsRetired, 1);
    expect(result.filesRetired, 0);
    expect(sent.map((r) => r.$2), [
      '/vault/legacy-ciphertext/migrate/item-retire',
      '/vault/ciphertext/vault-items',
    ]);
    expect(sent.first.$3!.keys.toSet(), {
      'item_id', 'readback_receipt', 'zk_proof_token', 'source_snapshot',
    });
    expect(jsonEncode(sent.first.$3), isNot(contains('synthetic.example')));
    expect(jsonEncode(sent.first.$3), isNot(contains('pin')));
  });

  test('file receipt retires with one proof and downloads V2 after retire',
      () async {
    final key = await VaultKeyHierarchy(_mvk).metadataKey();
    final manifest = await _encrypt(key, jsonEncode({
      'schema': 'vaultai.file.migrated.v1',
      'file_id': 'synthetic-file',
      'file_size': 0,
      'content_type': 'application/octet-stream',
      'chunk_size': 256 * 1024,
      'chunk_count': 0,
      'encrypted_metadata': <String, dynamic>{
        'file_name_ciphertext': await _encrypt(key, 'synthetic-file.txt'),
      },
    }));
    final sent = <(String, String, Map<String, dynamic>?)>[];
    final coordinator = LegacyContentRetirementCoordinator(
      enabled: true, accessIsCurrent: () => true, mvk: _mvk,
      now: () => DateTime.utc(2029, 1, 1),
      freshProof: () async => 'one-use-opaque-proof',
      request: (method, path, [body]) async {
        sent.add((method, path, body));
        if (path.endsWith('/file-retire')) {
          return const MigrationReply(200, {
            'file_id': 'synthetic-file', 'retired': true,
          });
        }
        expect(path, '/vault/file-v2/synthetic-file/manifest');
        return MigrationReply(200, {
          'file_id': 'synthetic-file',
          'crypto_version': 'client_mvk_v2',
          'manifest_ciphertext': manifest,
          'total_bytes': 0,
          'chunk_size': 256 * 1024,
          'chunk_count': 0,
          'lifecycle_state': 'legacy_migration_retired',
          'verification_state': 'client_verified',
          'migration_metadata_version': 1,
          'name_version': 0,
        });
      },
    );
    final result = await coordinator.complete([_evidence(file: true)],
        ownerInitiated: true);
    expect(result.filesRetired, 1);
    expect(sent.map((r) => r.$2), [
      '/vault/legacy-ciphertext/migrate/file-retire',
      '/vault/file-v2/synthetic-file/manifest',
    ]);
    expect(sent.first.$3!.keys.toSet(), {
      'file_id', 'readback_receipt', 'zk_proof_token',
      'client_verified_exact_bytes', 'client_verified_extra_fields',
      'source_snapshot',
    });
    expect(sent.first.$3!['client_verified_exact_bytes'], isTrue);
  });

  test('expired receipt is deferred and unreadable post-retire V2 fails',
      () async {
    var requests = 0;
    final expired = LegacyContentRetirementCoordinator(
      enabled: true, accessIsCurrent: () => true, mvk: _mvk,
      now: () => DateTime.utc(2030, 1, 2),
      freshProof: () async { requests++; return 'proof'; },
      request: (_, __, [___]) async {
        requests++; return const MigrationReply(200, {});
      },
    );
    final result = await expired.complete([_evidence(file: false)],
        ownerInitiated: true);
    expect(result.receiptsExpired, 1);
    expect(requests, 0);

    final broken = LegacyContentRetirementCoordinator(
      enabled: true, accessIsCurrent: () => true, mvk: _mvk,
      now: () => DateTime.utc(2029, 1, 1),
      freshProof: () async => 'proof',
      request: (_, path, [___]) async => path.endsWith('/item-retire')
          ? const MigrationReply(200, {'item_id': 7, 'retired': true})
          : const MigrationReply(200, <Object>[]),
    );
    await expectLater(broken.complete([_evidence(file: false)],
        ownerInitiated: true), throwsFormatException);
  });

  test('PIN-shaped proof and changed session stop before retirement',
      () async {
    var current = true;
    var requests = 0;
    final unsafeProof = LegacyContentRetirementCoordinator(
      enabled: true, accessIsCurrent: () => current, mvk: _mvk,
      now: () => DateTime.utc(2029, 1, 1),
      freshProof: () async => '123456',
      request: (_, __, [___]) async {
        requests++; return const MigrationReply(200, {});
      },
    );
    await expectLater(unsafeProof.complete([_evidence(file: false)],
        ownerInitiated: true), throwsArgumentError);
    expect(requests, 0);

    final changedSession = LegacyContentRetirementCoordinator(
      enabled: true, accessIsCurrent: () => current, mvk: _mvk,
      now: () => DateTime.utc(2029, 1, 1),
      freshProof: () async {
        current = false;
        return 'one-use-proof';
      },
      request: (_, __, [___]) async {
        requests++; return const MigrationReply(200, {});
      },
    );
    await expectLater(changedSession.complete([_evidence(file: false)],
        ownerInitiated: true), throwsStateError);
    expect(requests, 0);
  });
}
