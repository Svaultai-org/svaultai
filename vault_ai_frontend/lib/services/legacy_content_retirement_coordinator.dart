// Explicit, default-off completion after local exact readback. The server
// validates each source-bound receipt and consumes a fresh OPAQUE proof before
// removing one older ciphertext row. No PIN, plaintext or key is transmitted.

import 'dart:convert';

import 'package:cryptography/cryptography.dart' show SecretKey;

import 'file_v2_reader.dart';
import 'legacy_content_migration_stager.dart';
import 'vault_key_hierarchy.dart';
import 'zk_proof_token_guard.dart';

typedef FreshRetirementProof = Future<String> Function();

class LegacyRetirementResult {
  final int itemsRetired;
  final int filesRetired;
  final int receiptsExpired;

  const LegacyRetirementResult({
    required this.itemsRetired,
    required this.filesRetired,
    required this.receiptsExpired,
  });
}

class LegacyContentRetirementCoordinator {
  final bool enabled;
  final bool Function() accessIsCurrent;
  final SecretKey mvk;
  final MigrationRequest request;
  final FreshRetirementProof freshProof;
  final DateTime Function() now;

  const LegacyContentRetirementCoordinator({
    this.enabled = false,
    required this.accessIsCurrent,
    required this.mvk,
    required this.request,
    required this.freshProof,
    required this.now,
  });

  void _requireAccess() {
    if (!accessIsCurrent()) throw StateError('Vault session changed');
  }

  Future<MigrationReply> _request(
    String method, String path, [Map<String, dynamic>? body]
  ) async {
    _requireAccess();
    final reply = await request(method, path, body);
    _requireAccess();
    if (reply.statusCode != 200) {
      throw StateError('Older content completion was not accepted');
    }
    return reply;
  }

  Future<LegacyRetirementResult> complete(
    List<LegacyStageReadbackEvidence> evidence, {
    required bool ownerInitiated,
  }) async {
    if (!enabled || !ownerInitiated) {
      throw StateError('Owner-approved completion is unavailable');
    }
    _requireAccess();
    var items = 0;
    var files = 0;
    var expired = 0;
    for (final verified in evidence) {
      _requireAccess();
      if (!verified.receiptExpiresAt.isAfter(now().toUtc())) {
        expired++;
        continue;
      }
      if (!RegExp(r'^[A-Za-z0-9_-]{43}$')
              .hasMatch(verified.sourceSnapshot) ||
          verified.readbackReceipt.length > 256) {
        throw const FormatException('Invalid readback evidence');
      }
      final proof = rejectPinShapedZkProof(await freshProof());
      _requireAccess();
      if (proof.isEmpty || proof.length > 128) {
        throw StateError('Fresh vault verification is unavailable');
      }
      if (verified.isFile) {
        final id = verified.recordId;
        if (id.isEmpty || id.length > 128) {
          throw const FormatException('Invalid verified file ID');
        }
        final reply = await _request(
          'POST', '/vault/legacy-ciphertext/migrate/file-retire',
          <String, dynamic>{
            'file_id': id,
            'readback_receipt': verified.readbackReceipt,
            'zk_proof_token': proof,
            'client_verified_exact_bytes': true,
            'client_verified_extra_fields': verified.verifiedExtraFields,
            'source_snapshot': verified.sourceSnapshot,
          },
        );
        final body = reply.data;
        if (body is! Map || body['file_id'] != id ||
            body['retired'] != true) {
          throw const FormatException('Invalid file retirement response');
        }
        final reader = FileV2Reader(mvk: mvk, get: (path) async {
          final response = await _request('GET', path);
          final data = response.data;
          if (data is! Map<String, dynamic>) {
            throw const FormatException('Invalid private file readback');
          }
          return data;
        });
        await reader.download(id, requireRetired: true);
        _requireAccess();
        files++;
      } else {
        final id = int.tryParse(verified.recordId);
        if (id == null || id <= 0) {
          throw const FormatException('Invalid verified item ID');
        }
        final reply = await _request(
          'POST', '/vault/legacy-ciphertext/migrate/item-retire',
          <String, dynamic>{
            'item_id': id,
            'readback_receipt': verified.readbackReceipt,
            'zk_proof_token': proof,
            'source_snapshot': verified.sourceSnapshot,
          },
        );
        final body = reply.data;
        if (body is! Map || body['item_id'] != id ||
            body['retired'] != true) {
          throw const FormatException('Invalid item retirement response');
        }
        await _verifyRetiredItem(id);
        items++;
      }
    }
    return LegacyRetirementResult(
      itemsRetired: items, filesRetired: files, receiptsExpired: expired,
    );
  }

  Future<void> _verifyRetiredItem(int id) async {
    final reply = await _request('GET', '/vault/ciphertext/vault-items');
    final rows = reply.data;
    if (rows is! List) {
      throw const FormatException('Invalid private item inventory');
    }
    final matches = rows.whereType<Map>()
        .where((row) => row['item_id'] == id).toList();
    if (matches.length != 1) {
      throw const FormatException('Retired private item is unavailable');
    }
    final row = matches.single;
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> decrypt(String field) async {
      final encoded = row[field];
      if (encoded is! String || encoded.isEmpty) {
        throw const FormatException('Invalid retired item ciphertext');
      }
      final clear = await aesGcmUnwrap(key, b64urlDecode(encoded));
      _requireAccess();
      return utf8.decode(clear);
    }
    final type = await decrypt('item_type_ciphertext');
    final service = await decrypt('service_ciphertext');
    final payload = jsonDecode(await decrypt('payload_ciphertext'));
    if (type.isEmpty || service.isEmpty || payload is! Map ||
        payload['fields'] is! Map || payload['legacy_record'] is! Map) {
      throw const FormatException('Retired private item cannot be read');
    }
    _requireAccess();
  }
}
