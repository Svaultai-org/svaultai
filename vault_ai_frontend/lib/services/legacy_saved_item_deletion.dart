// A user-confirmed legacy saved-item deletion. The server receives an exact
// source snapshot and a fresh OPAQUE proof, never the PIN or vault title.

import 'zk_proof_token_guard.dart';

class LegacySavedItemDeleteSource {
  final int itemId;
  final String itemType;
  final String service;
  final String sourceSnapshot;

  const LegacySavedItemDeleteSource({
    required this.itemId,
    required this.itemType,
    required this.service,
    required this.sourceSnapshot,
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
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(source.sourceSnapshot)) {
      throw const FormatException('Saved-item identity changed');
    }
    final proof = rejectPinShapedZkProof(await proofProvider());
    requireCurrentSession();
    final response = await post(
      '/vault/items/legacy-ciphertext/$itemId/delete',
      <String, dynamic>{
        'source_snapshot': source.sourceSnapshot,
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
