// A user-confirmed legacy saved-item deletion. The server receives an exact
// source snapshot and a fresh OPAQUE proof, never the PIN or vault title.

import 'zk_proof_token_guard.dart';

enum SavedItemDeleteStorage { legacy, ciphertext }

SavedItemDeleteStorage savedItemDeleteStorage(Map<String, dynamic> row) {
  // A staged copy still has an active legacy source. The V2-only DELETE
  // refuses that source, so route the owner's confirmed deletion through the
  // proof-bound legacy endpoint which removes the entire row atomically.
  if (row['is_legacy'] == true) return SavedItemDeleteStorage.legacy;
  if (row['has_v2_payload'] == true) return SavedItemDeleteStorage.ciphertext;
  throw StateError('Saved item is unavailable');
}

void requireStagedLegacyDeleteIdentity({
  required Map<String, dynamic> source,
  required Map<String, dynamic> listing,
  required String itemType,
  required String service,
}) {
  final sourceTypeCipher = source['item_type_ciphertext'];
  final listedTypeCipher = listing['item_type_ciphertext'];
  final sourceStaged =
      sourceTypeCipher is String && sourceTypeCipher.isNotEmpty;
  final listedStaged =
      listedTypeCipher is String && listedTypeCipher.isNotEmpty;
  if (sourceStaged != listedStaged) {
    throw const FormatException('Saved-item staged identity changed');
  }
  if (sourceStaged &&
      (source['item_type'] != itemType ||
          source['service'] != service ||
          listing['item_type'] != itemType ||
          listing['service'] != service)) {
    throw const FormatException('Saved-item staged identity changed');
  }
}

class LegacySavedItemDeleteSource {
  final int itemId;
  final String itemType;
  final String service;
  final String sourceSnapshot;
  final String deleteSnapshot;

  const LegacySavedItemDeleteSource({
    required this.itemId,
    required this.itemType,
    required this.service,
    required this.sourceSnapshot,
    required this.deleteSnapshot,
  });
}

class LegacySavedItemDeletion {
  final Future<LegacySavedItemDeleteSource> Function(int) sourceReader;
  final Future<String> Function() proofProvider;
  final Future<Map<String, dynamic>> Function(String, Map<String, dynamic>)
  post;
  final void Function() requireCurrentSession;

  const LegacySavedItemDeletion({
    required this.sourceReader,
    required this.proofProvider,
    required this.post,
    required this.requireCurrentSession,
  });

  Future<void> delete({
    required int itemId,
    required String itemType,
    required String service,
    required bool userConfirmed,
  }) async {
    if (!userConfirmed ||
        itemId <= 0 ||
        itemType.trim().isEmpty ||
        service.trim().isEmpty) {
      throw const FormatException('Saved-item deletion is not confirmed');
    }
    requireCurrentSession();
    final source = await sourceReader(itemId);
    requireCurrentSession();
    if (source.itemId != itemId ||
        source.itemType != itemType ||
        source.service != service ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(source.sourceSnapshot) ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(source.deleteSnapshot)) {
      throw const FormatException('Saved-item identity changed');
    }
    final proof = rejectPinShapedZkProof(await proofProvider());
    requireCurrentSession();
    final response = await post(
      '/vault/items/legacy-ciphertext/$itemId/delete',
      <String, dynamic>{
        'source_snapshot': source.sourceSnapshot,
        'delete_snapshot': source.deleteSnapshot,
        'zk_proof_token': proof,
        'confirm': true,
      },
    );
    requireCurrentSession();
    if (response['status'] != 'deleted' || response['item_id'] != itemId) {
      throw const FormatException('Saved-item deletion response is invalid');
    }
  }
}
