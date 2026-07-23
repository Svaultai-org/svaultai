// Bug 2 regression — beneficiary inheritance card shows the owner's
// vault_name when the plaintext passer_label is NULL (as it is for
// every ZK-created pairing), and falls back to 'Unknown' only when
// the backend genuinely has no usable identity for the owner.
//
// Prior to the 2026-07-23 fix the label render code was:
//   final label = (i['passer_label'] ?? 'Unknown').toString();
// which surfaced 'Unknown' for every ZK-created pairing because
// ``beneficiary_links.passer_label`` is NULL for those rows (the
// plaintext is stored in ``passer_label_ciphertext`` under the
// OWNER's metadataKey and the beneficiary cannot decrypt it).
//
// The fix adds ``owner_vault_name`` to the /beneficiary/list-inheritances
// response via a LEFT JOIN on vaults, and the render code becomes:
//   final label = (i['passer_label']
//                     ?? i['owner_vault_name']
//                     ?? 'Unknown').toString();
//
// This test locks the render precedence and the source contract.

library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


/// Pure precedence function extracted for testability. Mirrors the
/// inline expression at [main.dart:8673]; keep them in sync.
String _resolveOwnerLabel(Map<String, dynamic> i) {
  return (i['passer_label']
          ?? i['owner_vault_name']
          ?? 'Unknown')
      .toString();
}


void main() {
  group('inheritance card owner label — precedence order', () {

    test('legacy pairing with passer_label set prefers passer_label',
        () {
      final row = <String, dynamic>{
        'id': 1,
        'passer_label':     'Mom',
        'owner_vault_name': 'grandma_vault',
      };
      expect(_resolveOwnerLabel(row), equals('Mom'));
    });

    test('ZK pairing with passer_label NULL falls back to '
        'owner_vault_name', () {
      final row = <String, dynamic>{
        'id': 2,
        'passer_label':     null,
        'owner_vault_name': 'grandma_vault',
      };
      expect(_resolveOwnerLabel(row), equals('grandma_vault'));
    });

    test('both NULL falls back to the hardcoded Unknown', () {
      final row = <String, dynamic>{
        'id': 3,
        'passer_label':     null,
        'owner_vault_name': null,
      };
      expect(_resolveOwnerLabel(row), equals('Unknown'));
    });

    test('missing keys entirely falls back to the hardcoded Unknown',
        () {
      final row = <String, dynamic>{'id': 4};
      expect(_resolveOwnerLabel(row), equals('Unknown'));
    });

    test('empty-string passer_label is treated as PRESENT — do NOT '
        'fall through', () {
      // Note: this locks a subtle behavior — an empty-string value
      // is not the same as NULL. If the backend ever returns an
      // empty string, that IS what gets rendered (as an empty
      // Text). The fallback only fires on genuine NULL. Change
      // this behavior only with an explicit product decision.
      final row = <String, dynamic>{
        'id': 5,
        'passer_label':     '',
        'owner_vault_name': 'fallback_ok',
      };
      expect(_resolveOwnerLabel(row), equals(''));
    });
  });

  group('main.dart source contract — owner label render', () {
    late String src;

    setUpAll(() {
      src = File('lib/main.dart').readAsStringSync();
    });

    test('the inheritances-list render uses the three-level '
        'precedence (passer_label → owner_vault_name → Unknown)',
        () {
      final collapsed = src.replaceAll(RegExp(r'\s+'), ' ');
      expect(
        collapsed.contains(
            "i['passer_label'] ?? i['owner_vault_name'] ?? 'Unknown'"),
        isTrue,
        reason: 'the inheritances-list render must chain the three '
            'fallbacks — passer_label first, owner_vault_name '
            'second, hardcoded Unknown only as last resort',
      );
    });

    test('the old two-argument fallback is gone from the '
        'inheritances-list render', () {
      // Regression-lock the prior broken shape. If the source
      // reverts to the old expression this test fires.
      final collapsed = src.replaceAll(RegExp(r'\s+'), ' ');
      expect(
        collapsed.contains("(i['passer_label'] ?? 'Unknown')"),
        isFalse,
        reason: 'the two-argument fallback would surface "Unknown" '
            'for every ZK-created pairing — see 2026-07-23 Bug 2 '
            'fix',
      );
    });
  });
}
