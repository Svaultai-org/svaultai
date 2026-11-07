/// Client-only decode of a released owner's encrypted saved item.
library;

import 'dart:convert';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';
import 'inheritance_mvk_v2.dart';

class InheritedVaultItem {
  final int sourceItemId;
  final String itemType;
  final String service;
  final Map<String, dynamic> payload;

  const InheritedVaultItem({
    required this.sourceItemId,
    required this.itemType,
    required this.service,
    required this.payload,
  });
}

Future<InheritedVaultItem> decodeInheritedVaultItem({
  required SecretKey ownerMvk,
  required Map<String, dynamic> encryptedRow,
}) async {
  final id = encryptedRow['item_id'];
  if (id is! int || id <= 0) {
    throw const FormatException('Invalid inherited item identity');
  }
  final key = await VaultKeyHierarchy(ownerMvk).metadataKey();
  Future<String> field(String name) async {
    final encoded = encryptedRow[name];
    if (encoded is! String || encoded.isEmpty) {
      throw const FormatException('Missing inherited item ciphertext');
    }
    return utf8.decode(await aesGcmUnwrap(key, b64urlDecode(encoded)));
  }

  final type = (await field('item_type_ciphertext')).trim();
  final service = (await field('service_ciphertext')).trim();
  final decodedPayload = jsonDecode(await field('payload_ciphertext'));
  if (type.isEmpty ||
      service.isEmpty ||
      decodedPayload is! Map ||
      decodedPayload.containsKey('_svaultai_inheritance_source_v2')) {
    throw const FormatException('Invalid inherited item payload');
  }
  return InheritedVaultItem(
    sourceItemId: id,
    itemType: type,
    service: service,
    payload: Map<String, dynamic>.from(decodedPayload),
  );
}

String inheritedItemTitle(InheritedVaultItem item, int linkId) =>
    '${item.service} (inherited $linkId-${item.sourceItemId})';

Map<String, dynamic> inheritedItemPayload(
  InheritedVaultItem item, {
  required int linkId,
  required String ownerVaultId,
}) =>
    {
      ...item.payload,
      '_svaultai_inheritance_source_v2': {
        'link_id': linkId,
        'owner_vault_id': ownerVaultId,
        'item_id': item.sourceItemId,
      },
    };

typedef FetchInheritedExport = Future<Map<String, dynamic>> Function(
    int linkId);
typedef ListBeneficiaryItems = Future<Map<String, dynamic>> Function();
typedef WriteBeneficiaryItem = Future<Map<String, dynamic>?> Function(
  InheritedVaultItem item,
  String title,
  Map<String, dynamic> payload,
);

Future<int> importReleasedV2SavedItems({
  required int linkId,
  required SecretKey beneficiaryPrivateKey,
  required Map<String, dynamic> releasedPackage,
  required FetchInheritedExport fetchExport,
  required ListBeneficiaryItems listBeneficiaryItems,
  required WriteBeneficiaryItem writeBeneficiaryItem,
  required bool Function() accessIsCurrent,
}) async {
  void checkAccess() {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
  }

  checkAccess();
  final inherited = await decryptInheritanceMvk(
    expectedLinkId: linkId,
    beneficiaryPrivateKey: beneficiaryPrivateKey,
    rawPackage: releasedPackage,
  );
  checkAccess();
  final exported = await fetchExport(linkId);
  checkAccess();
  if (exported['beneficiary_link_id'] != linkId ||
      exported['owner_vault_id'] != inherited.ownerVaultId ||
      exported['items'] is! List ||
      (exported['items'] as List).length > 500) {
    throw const FormatException('Invalid inherited vault export');
  }

  Set<int> importedIds(Map<String, dynamic> listed) {
    final found = <int>{};
    for (final row in (listed['items'] as List? ?? const [])) {
      if (row is! Map) continue;
      final payload = row['zk_payload'];
      if (payload is! Map) continue;
      final origin = payload['_svaultai_inheritance_source_v2'];
      if (origin is Map &&
          origin['link_id'] == linkId &&
          origin['owner_vault_id'] == inherited.ownerVaultId &&
          origin['item_id'] is int) {
        found.add(origin['item_id'] as int);
      }
    }
    return found;
  }

  final existing = await listBeneficiaryItems();
  checkAccess();
  final imported = importedIds(existing);
  final sourceIds = <int>{};
  var newItems = 0;
  for (final raw in exported['items'] as List) {
    checkAccess();
    if (raw is! Map) throw const FormatException('Invalid inherited item');
    final item = await decodeInheritedVaultItem(
      ownerMvk: inherited.ownerMvk,
      encryptedRow: Map<String, dynamic>.from(raw),
    );
    checkAccess();
    if (!sourceIds.add(item.sourceItemId)) {
      throw const FormatException('Duplicate inherited item');
    }
    if (imported.contains(item.sourceItemId)) continue;
    final result = await writeBeneficiaryItem(
      item,
      inheritedItemTitle(item, linkId),
      inheritedItemPayload(
        item,
        linkId: linkId,
        ownerVaultId: inherited.ownerVaultId,
      ),
    );
    checkAccess();
    if (result == null || result['item_id'] is! int) {
      throw StateError('Inherited item import was not confirmed');
    }
    imported.add(item.sourceItemId);
    newItems++;
  }
  final verified = await listBeneficiaryItems();
  checkAccess();
  if (!importedIds(verified).containsAll(sourceIds)) {
    throw StateError('Inherited item import was not verified');
  }
  return newItems;
}
