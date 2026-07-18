import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart' show zkNotificationFallback;

String _readMain() =>
    File('lib/main.dart').readAsStringSync();

void main() {
  group('ZK notification fallback — kind→label mapping', () {
    test('every known kind returns a non-empty title and body', () {
      const kinds = <String>[
        'transfer_requested',
        'transfer_cancelled',
        'transfer_completed',
        'device_approved',
        'device_revoked',
        'device_approval_pending',
        'device_self_approval_cancelled',
        'credential_files',
        'upload',
      ];
      for (final k in kinds) {
        final f = zkNotificationFallback(k);
        expect(f['title'], isNotNull);
        expect(f['title']!.trim(), isNotEmpty,
            reason: 'fallback title for "$k" must be non-empty');
        expect(f['body'], isNotNull);
        expect(f['body']!.trim(), isNotEmpty,
            reason: 'fallback body for "$k" must be non-empty');
      }
    });

    test('null / empty kind still yields a neutral "Vault activity" '
        'fallback (never a blank row)', () {
      for (final k in <String?>[null, '', '   ']) {
        final f = zkNotificationFallback(k);
        expect(f['title']!.trim(), isNotEmpty);
        expect(f['body']!.trim(), isNotEmpty);
      }
    });

    test('unknown / future kinds do NOT return blank — the kind '
        'slug is normalized into a Title Case label', () {
      final f = zkNotificationFallback('vault_migration_scheduled');
      expect(f['title'], 'Vault Migration Scheduled');
      expect(f['body']!.trim(), isNotEmpty);
    });

    test('fallback text NEVER contains user-supplied identifiers '
        'like vault_name / device_name / label / filename — the '
        'privacy contract forbids reconstructing user text', () {
      // A defensive check: iterate the known kinds and confirm none
      // of them string-interpolates a placeholder that could reveal
      // a user identifier. Fallbacks must be generic.
      const forbiddenTokens = <String>[
        r'$', // no interpolation at all
        'vault_name',
        'device_label',
        'beneficiary_label',
        'file_name',
      ];
      const kinds = <String>[
        'transfer_requested',
        'transfer_cancelled',
        'transfer_completed',
        'device_approved',
        'device_revoked',
        'device_approval_pending',
        'device_self_approval_cancelled',
        'credential_files',
        'upload',
        '',
      ];
      for (final k in kinds) {
        final f = zkNotificationFallback(k);
        for (final t in forbiddenTokens) {
          expect(f['title'], isNot(contains(t)),
              reason: 'kind "$k" title must not contain "$t"');
          expect(f['body'], isNot(contains(t)),
              reason: 'kind "$k" body must not contain "$t"');
        }
      }
    });
  });

  group('_NotificationBell renders the fallback for NULL title/body',
      () {
    test('main.dart notification-list itemBuilder consults '
        'zkNotificationFallback when title and body are both empty',
        () {
      final src = _readMain();
      // Find the notification list item builder block and confirm
      // it references zkNotificationFallback and does NOT unwrap
      // (n[title] ?? "").toString() directly into the Text widget
      // without a fallback path.
      final builderIdx = src.indexOf(
        "itemBuilder: (_, i) {\r\n"
        "                      final n = a.notifications[i];",
      );
      // On non-Windows checkouts the file may have LF endings.
      final builderIdxAlt = src.indexOf(
        "itemBuilder: (_, i) {\n"
        "                      final n = a.notifications[i];",
      );
      final resolved = builderIdx >= 0 ? builderIdx : builderIdxAlt;
      expect(resolved, greaterThan(-1),
          reason: 'the notification-list itemBuilder must exist');
      // Look for the fallback call within a reasonable window after
      // the builder.
      final window = src.substring(
        resolved, (resolved + 4000).clamp(0, src.length),
      );
      expect(
        window,
        contains('zkNotificationFallback('),
        reason: '_NotificationBell must dispatch to '
                'zkNotificationFallback when title/body are NULL',
      );
      expect(
        window,
        contains('displayTitle'),
        reason: 'the row Text widget must read from the resolved '
                'displayTitle (fallback or verbatim), never the raw '
                '(n[title] ?? "") value',
      );
      expect(
        window,
        contains('displayBody'),
        reason: 'the row Text widget must read from the resolved '
                'displayBody (fallback or verbatim)',
      );
    });
  });
}
