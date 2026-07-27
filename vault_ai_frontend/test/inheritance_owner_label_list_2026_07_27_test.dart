import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show resolveOwnerBeneficiaryLabelForDisplay;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart'
    as vk_hier;

SecretKey _mvk() {
  return SecretKey(Uint8List.fromList(List<int>.generate(32, (i) => i + 1)));
}

Future<String> _encryptedLabel(String label, SecretKey mvk) async {
  final hierarchy = vk_hier.VaultKeyHierarchy(mvk);
  final metaKey = await hierarchy.metadataKey();
  final envelope = await vk_hier.aesGcmWrap(metaKey, utf8.encode(label));
  return vk_hier.b64urlEncode(envelope);
}

void main() {
  group('owner beneficiary label list mapping', () {
    test('decrypts owner-only ZK label ciphertext for display', () async {
      final mvk = _mvk();
      final row = await resolveOwnerBeneficiaryLabelForDisplay(
        {
          'id': 7,
          'label': null,
          'passer_label_ciphertext':
              await _encryptedLabel('Son - John', mvk),
        },
        mvk: mvk,
      );

      expect(row['label'], 'Son - John');
    });

    test('preserves plaintext legacy label without ciphertext', () async {
      final row = await resolveOwnerBeneficiaryLabelForDisplay(
        {
          'id': 8,
          'label': 'Aunt Mary',
          'passer_label_ciphertext': null,
        },
        mvk: _mvk(),
      );

      expect(row['label'], 'Aunt Mary');
    });

    test('falls back only when no stored label can be read', () async {
      final row = await resolveOwnerBeneficiaryLabelForDisplay(
        {
          'id': 9,
          'label': null,
          'passer_label_ciphertext': 'not-valid-ciphertext',
        },
        mvk: _mvk(),
      );

      expect(row['label'], isNull);
      expect(row['has_stored_label'], isTrue);
    });
  });
}
