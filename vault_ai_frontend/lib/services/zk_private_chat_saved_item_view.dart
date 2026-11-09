/// Exact, local saved-item reveal for a selected private-chat result.
///
/// The caller supplies only the MVK V2 reader or the owner-proof legacy
/// ciphertext reader. This class has no legacy PIN-bearing HTTP fallback and
/// never adds decrypted values to chat history or general AI context.
library;

import 'zk_private_chat.dart';

typedef ZkSelectedV2ItemRead = Future<Map<String, dynamic>> Function(
  int itemId,
  String title,
  String itemType,
);
typedef ZkSelectedLegacyItemRead = Future<Map<String, dynamic>> Function(
    int itemId);

final class ZkSelectedSavedItemView {
  const ZkSelectedSavedItemView({
    required this.id,
    required this.title,
    required this.itemType,
    required this.fields,
  });

  final int id;
  final String title;
  final String itemType;
  final Map<String, String> fields;
}

final class ZkPrivateChatSavedItemView {
  static bool shouldOpen(ZkLocalChatResult result, {required bool enabled}) =>
      enabled &&
      result.disposition == ZkLocalChatDisposition.found &&
      result.selection?.kind == ZkLocalChatKind.savedItem &&
      (result.action == ZkLocalChatAction.open ||
          result.action == ZkLocalChatAction.readText);

  static Future<ZkSelectedSavedItemView> read({
    required ZkLocalChatRecord selection,
    required bool legacyProofOffered,
    required bool Function() accessIsCurrent,
    required ZkSelectedV2ItemRead readV2,
    required ZkSelectedLegacyItemRead readLegacy,
  }) async {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    final id = int.tryParse(selection.id);
    final title = selection.title.trim();
    final type = selection.itemType?.trim();
    if (selection.kind != ZkLocalChatKind.savedItem ||
        id == null ||
        id <= 0 ||
        title.isEmpty ||
        type == null ||
        type.isEmpty) {
      throw StateError('Saved-item selection is unavailable');
    }
    if (selection.legacyProofRequired && !legacyProofOffered) {
      throw StateError('Private saved-item proof is unavailable');
    }
    final detail = selection.legacyProofRequired
        ? await readLegacy(id)
        : await readV2(id, title, type);
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    if (detail['id'] != id ||
        detail['service'] is! String ||
        (detail['service'] as String).trim() != title ||
        detail['item_type'] is! String ||
        (detail['item_type'] as String).trim() != type ||
        detail['storage_engine'] !=
            (selection.legacyProofRequired
                ? 'legacy_compatibility'
                : 'ciphertext')) {
      throw const FormatException('Saved-item identity changed');
    }
    final rawFields = detail['fields'];
    if (rawFields is! Map) {
      throw const FormatException('Saved-item fields are unavailable');
    }
    final fields = <String, String>{};
    for (final entry in rawFields.entries) {
      if (entry.key is! String || entry.value is! String) {
        throw const FormatException('Invalid saved-item field');
      }
      fields[entry.key as String] = entry.value as String;
    }
    final notes = detail['notes'];
    if (notes is String &&
        notes.isNotEmpty &&
        !fields.containsKey('note') &&
        !fields.containsKey('notes')) {
      fields['notes'] = notes;
    }
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    return ZkSelectedSavedItemView(
      id: id,
      title: title,
      itemType: type,
      fields: fields,
    );
  }
}
