

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _readMain() {
  return File(
    Directory.current.path + '/lib/main.dart',
  ).readAsStringSync();
}

void main() {
  group('Logins page Delete wiring', () {
    test('onDelete routes through _startSecureItemDeleteConfirmation',
        () {
      final src = _readMain();
      
      
      expect(
        src,
        contains('_startSecureItemDeleteConfirmation(service, itemType)'),
        reason:
            'The Logins & Secure Items page Delete button must route '
            'through the chat-confirmation helper, not call the delete '
            'API directly.',
      );
    });

    test('chat secure-item card Delete also routes through confirmation',
        () {
      final src = _readMain();
      
      
      expect(
        src,
        contains('_startSecureItemDeleteConfirmation(title, itemType)'),
        reason:
            'The chat secure-item card Delete button must route through '
            'the chat-confirmation helper.',
      );
    });

    test('legacy direct delete handler is gone', () {
      final src = _readMain();
      expect(
        src,
        isNot(contains('Future<void> _confirmDeleteSecureItem(')),
        reason:
            'Operator brief: delete should route through chat '
            'confirmation. The legacy _confirmDeleteSecureItem direct '
            'API path must be removed.',
      );
    });
  });

  group('_startSecureItemDeleteConfirmation contract', () {
    test('helper is defined', () {
      expect(
        _readMain(),
        contains('Future<void> _startSecureItemDeleteConfirmation('),
        reason:
            'The chat-confirmation entry point must exist with the '
            'pinned name so the Logins page + chat card both call it.',
      );
    });

    test('switches the dashboard to the Chat section', () {
      final src = _readMain();
      
      final start =
          src.indexOf('Future<void> _startSecureItemDeleteConfirmation(');
      expect(start, greaterThan(-1));
      
      
      final body = src.substring(
        start,
        (start + 12000).clamp(0, src.length),
      );
      expect(
        body,
        contains('selectedSection = _DashboardSection.chat'),
        reason:
            'Clicking Delete must switch the dashboard to the Chat '
            'section so the user sees the confirmation prompt.',
      );
    });

    test('builds the closed-set sentinel and encrypts THAT, not the '
        'user-visible text', () {
      final src = _readMain();
      final start =
          src.indexOf('Future<void> _startSecureItemDeleteConfirmation(');
      final body = src.substring(
        start,
        (start + 12000).clamp(0, src.length),
      );
      
      expect(
        body,
        contains("'__delete_item:\$itemType:\$safeService'"),
        reason:
            'The wire payload must be the closed-set sentinel the '
            'backend recognises in vault_secure_item_delete_confirmation.',
      );
      
      // 2026-07-22 crypto-context refactor: the delete-sentinel is
      // now encrypted via `encryptWithContext(plaintext: sentinel,
      // context: ctxSnapshot)` instead of the legacy
      // `_VaultCrypto.encrypt(sentinel)`. The invariant remains
      // "the wire payload is the SENTINEL, not the visible bubble"
      // — the change is only which crypto helper is called.
      expect(
        body,
        contains('encryptWithContext('),
        reason:
            'The encrypted /chat payload MUST be produced via '
            'encryptWithContext so the key and its declared KDF '
            'metadata come from a single immutable snapshot.',
      );
      expect(
        body,
        contains('plaintext: sentinel'),
        reason:
            'The encrypted plaintext MUST be the sentinel — the '
            'visible bubble is shown to the user separately.',
      );
      expect(
        body,
        isNot(contains('plaintext: visibleBubble')),
        reason:
            'The visible bubble is for display only; it must not be '
            'sent on the wire.',
      );
    });

    test('user-visible bubble is natural language, not the sentinel', () {
      final src = _readMain();
      final start =
          src.indexOf('Future<void> _startSecureItemDeleteConfirmation(');
      final body = src.substring(
        start,
        (start + 12000).clamp(0, src.length),
      );
      
      
      expect(
        body,
        contains("'Delete \$safeService from my vault'"),
        reason:
            'Non-login bubble must read "Delete <title> from my vault".',
      );
      expect(
        body,
        contains("'Delete \$safeService login from my vault'"),
        reason:
            'Login bubble must read "Delete <title> login from my vault".',
      );
      
      expect(
        body,
        isNot(contains("msgs.add(_Msg('user', sentinel))")),
        reason:
            'The user-visible bubble must never be the raw sentinel.',
      );
    });

    test('refreshes Logins after the stream completes', () {
      final src = _readMain();
      final start =
          src.indexOf('Future<void> _startSecureItemDeleteConfirmation(');
      final body = src.substring(
        start,
        (start + 12000).clamp(0, src.length),
      );
      expect(
        body,
        contains('_loadVaultLogins()'),
        reason:
            'After the backend BAND_DELETED reply, the Logins page list '
            'must refresh so the deleted row disappears.',
      );
    });
  });

  group('Click does NOT call the delete API directly', () {
    test('Logins page onDelete body does not call deleteVaultSecureItem',
        () {
      final src = _readMain();
      
      final clueStart = src.indexOf('onDelete: (service, itemType) {');
      expect(
        clueStart,
        greaterThan(-1),
        reason: 'Logins page onDelete callback must exist.',
      );
      
      
      final clueEnd = src.indexOf('},', clueStart);
      final callbackBody = src.substring(clueStart, clueEnd);
      expect(
        callbackBody,
        isNot(contains('deleteVaultSecureItem')),
        reason:
            'The Logins page Delete callback must NOT call the delete '
            'API directly — it must route through chat confirmation.',
      );
    });

    test('chat secure-item card onSecureItemDelete body does not call '
        'deleteVaultSecureItem directly', () {
      final src = _readMain();
      final clueStart =
          src.indexOf('onSecureItemDelete: (title, itemType) {');
      expect(
        clueStart,
        greaterThan(-1),
        reason: 'Chat card onSecureItemDelete callback must exist.',
      );
      final clueEnd = src.indexOf('},', clueStart);
      final callbackBody = src.substring(clueStart, clueEnd);
      expect(
        callbackBody,
        isNot(contains('deleteVaultSecureItem')),
        reason:
            'The chat card Delete callback must NOT call the delete '
            'API directly — it must route through chat confirmation.',
      );
    });
  });
}
