// Bug 3 regression — transfer dialog wording must reflect the actual
// backend behavior. VaultAI does NOT send emails; the inheritance
// release flow notifies owners in-app via _create_notification, and
// the post-countdown behavior is NOT automatic release — the
// beneficiary must call /inheritance/access/claim followed by
// /inheritance/credentials/retrieve to move the escrow to
// ``released``.
//
// The two prior strings falsely claimed email notifications:
//   * main.dart:7133-7135 (beneficiary request-transfer dialog)
//   * main.dart:6971-6973 (owner cancel-transfer dialog)
//
// This test locks the corrected copy structurally so a future edit
// cannot silently re-introduce the wrong wording.

library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


/// Collapse both arbitrary whitespace AND the ``' '`` boundary that
/// dart2js concatenates away between adjacent string literals. This
/// lets a source assertion match the effective compiled string
/// without depending on the code's line-wrap style.
String _collapsedSourceText(String src) {
  final withoutStringBoundary = src.replaceAll(RegExp(r"'\s*'"), '');
  return withoutStringBoundary.replaceAll(RegExp(r'\s+'), ' ');
}


void main() {
  group('main.dart transfer dialog wording — no email claim', () {
    late String src;

    setUpAll(() {
      src = File('lib/main.dart').readAsStringSync();
    });

    test('no dialog text claims the vault owner will be emailed', () {
      // The exact prior strings that shipped in production.
      expect(
        src.contains('The vault owner will be emailed'),
        isFalse,
        reason: 'the request-transfer dialog must not claim email — '
            'VaultAI only notifies in-app',
      );
      expect(
        src.contains('The beneficiary will be emailed'),
        isFalse,
        reason: 'the cancel-transfer dialog must not claim email',
      );
    });

    test('beneficiary request-transfer dialog says "notified inside '
        'VaultAI" and describes claiming after the countdown', () {
      final collapsed = _collapsedSourceText(src);
      expect(
        collapsed.contains(
            'The vault owner will be notified inside VaultAI'),
        isTrue,
        reason: 'the request dialog must clearly state VaultAI '
            'notification (not email)',
      );
      expect(
        collapsed.contains('approve or reject'),
        isTrue,
        reason: 'the request dialog must mention the owner\'s '
            'approve/reject options during the countdown',
      );
      expect(
        collapsed.contains('claim the credentials'),
        isTrue,
        reason: 'the request dialog must describe the beneficiary '
            'CLAIMING (not passive automatic release) after the '
            'countdown ends — matches the actual backend state '
            'machine, see inheritance_release_routes.py::claim_access',
      );
    });

    test('owner cancel-transfer dialog says "notified inside '
        'VaultAI" instead of emailed', () {
      final collapsed = _collapsedSourceText(src);
      expect(
        collapsed.contains(
            'The beneficiary will be notified inside VaultAI'),
        isTrue,
        reason: 'the cancel dialog must clearly state in-app '
            'notification',
      );
    });
  });
}
