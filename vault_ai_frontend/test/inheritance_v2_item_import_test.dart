import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_item_import.dart';
import 'package:vault_ai_frontend/services/inheritance_mvk_v2.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

void main() {
  test('released owner item is decrypted then re-encrypted for beneficiary',
      () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 11));
    final beneficiaryMvk = SecretKey(List<int>.filled(32, 22));
    final ownerKey = await VaultKeyHierarchy(ownerMvk).metadataKey();
    Future<String> encrypt(String clear) async =>
        b64urlEncode(await aesGcmWrap(ownerKey, utf8.encode(clear)));
    final encryptedRow = <String, dynamic>{
      'item_id': 7,
      'item_type_ciphertext': await encrypt('login'),
      'service_ciphertext': await encrypt('Example'),
      'payload_ciphertext': await encrypt(jsonEncode({
        'fields': {
          'username': 'synthetic-user',
          'password': 'synthetic-secret'
        },
        'notes': 'synthetic-note',
      })),
    };
    final inherited = await decodeInheritedVaultItem(
      ownerMvk: ownerMvk,
      encryptedRow: encryptedRow,
    );
    expect(inherited.service, 'Example');
    final importedPayload = inheritedItemPayload(
      inherited,
      linkId: 17,
      ownerVaultId: 'synthetic-owner',
    );
    final recipientKey = await VaultKeyHierarchy(beneficiaryMvk).metadataKey();
    final recipientCiphertext = await aesGcmWrap(
      recipientKey,
      utf8.encode(jsonEncode(importedPayload)),
    );
    final verified = jsonDecode(utf8.decode(
      await aesGcmUnwrap(recipientKey, recipientCiphertext),
    )) as Map<String, dynamic>;
    expect(verified['fields']['password'], 'synthetic-secret');
    expect(verified['_svaultai_inheritance_source_v2'], {
      'link_id': 17,
      'owner_vault_id': 'synthetic-owner',
      'item_id': 7,
    });
    await expectLater(
      aesGcmUnwrap(ownerKey, recipientCiphertext),
      throwsA(isA<SecretBoxAuthenticationError>()),
    );
    expect(inheritedItemTitle(inherited, 17), 'Example (inherited 17-7)');
  });

  test('owner to beneficiary import pipeline is PIN-free and retry-safe',
      () async {
    final ownerMvk = SecretKey(List<int>.filled(32, 11));
    final beneficiaryMvk = SecretKey(List<int>.filled(32, 22));
    final beneficiaryPair = await X25519().newKeyPair();
    final beneficiaryPublic = await beneficiaryPair.extractPublicKey();
    final beneficiaryPrivate =
        SecretKey(await beneficiaryPair.extractPrivateKeyBytes());
    final package = (await encryptInheritanceMvk(
      beneficiaryLinkId: 17,
      ownerVaultId: 'synthetic-owner',
      ownerMvk: ownerMvk,
      beneficiaryPublicKey: Uint8List.fromList(beneficiaryPublic.bytes),
    ))
        .toRequestBody(17);
    expect(package.containsKey('pin'), isFalse);
    final ownerKey = await VaultKeyHierarchy(ownerMvk).metadataKey();
    Future<String> encryptOwner(String clear) async =>
        b64urlEncode(await aesGcmWrap(ownerKey, utf8.encode(clear)));
    final export = <String, dynamic>{
      'beneficiary_link_id': 17,
      'owner_vault_id': 'synthetic-owner',
      'items': [
        {
          'item_id': 7,
          'item_type_ciphertext': await encryptOwner('login'),
          'service_ciphertext': await encryptOwner('Example'),
          'payload_ciphertext': await encryptOwner(jsonEncode({
            'fields': {'username': 'synthetic-user'},
          })),
        },
      ],
    };
    final saved = <Map<String, dynamic>>[];
    var writes = 0;
    Future<int> run() => importReleasedV2SavedItems(
          linkId: 17,
          beneficiaryPrivateKey: beneficiaryPrivate,
          releasedPackage: package,
          fetchExport: (_) async => export,
          listBeneficiaryItems: () async => {'items': saved},
          writeBeneficiaryItem: (item, title, payload) async {
            writes++;
            final key = await VaultKeyHierarchy(beneficiaryMvk).metadataKey();
            final ciphertext = await aesGcmWrap(
              key,
              utf8.encode(jsonEncode(payload)),
            );
            final clear = jsonDecode(utf8.decode(
              await aesGcmUnwrap(key, ciphertext),
            )) as Map<String, dynamic>;
            expect(title, 'Example (inherited 17-7)');
            expect(clear['fields']['username'], 'synthetic-user');
            saved.add({'zk_payload': clear});
            return {'item_id': 99};
          },
          accessIsCurrent: () => true,
        );
    expect(await run(), 1);
    expect(await run(), 0);
    expect(writes, 1);
  });
}
