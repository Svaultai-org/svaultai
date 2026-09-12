import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show
        isClientSecureItemDeleteCancellationPhrase,
        isClientSecureItemDeleteConfirmationPhrase;

String _readMain() {
  return File(
    Directory.current.path + '/lib/main.dart',
  ).readAsStringSync();
}

void main() {
  group('client ciphertext delete confirmation phrases', () {
    test('accepts an explicit confirmation', () {
      expect(isClientSecureItemDeleteConfirmationPhrase('yes'), isTrue);
      expect(
        isClientSecureItemDeleteConfirmationPhrase('confirm delete'),
        isTrue,
      );
      expect(isClientSecureItemDeleteConfirmationPhrase('show it'), isFalse);
    });

    test('accepts cancellation without deleting', () {
      expect(isClientSecureItemDeleteCancellationPhrase('no'), isTrue);
      expect(
        isClientSecureItemDeleteCancellationPhrase("don't delete it"),
        isTrue,
      );
      expect(isClientSecureItemDeleteCancellationPhrase('yes'), isFalse);
    });
  });

  group('Logins page Delete wiring', () {
    test('onDelete routes through _startSecureItemDeleteConfirmation', () {
      final src = _readMain();

      expect(
        src,
        contains('_startSecureItemDeleteConfirmation(service, itemType)'),
        reason: 'The Logins & Secure Items page Delete button must route '
            'through the chat-confirmation helper, not call the delete '
            'API directly.',
      );
    });

    test('chat secure-item card Delete also routes through confirmation', () {
      final src = _readMain();

      expect(
        src,
        contains('_startSecureItemDeleteConfirmation(title, itemType)'),
        reason: 'The chat secure-item card Delete button must route through '
            'the chat-confirmation helper.',
      );
    });

    test('legacy direct delete handler is gone', () {
      final src = _readMain();
      expect(
        src,
        isNot(contains('Future<void> _confirmDeleteSecureItem(')),
        reason: 'Operator brief: delete should route through chat '
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
        reason: 'The chat-confirmation entry point must exist with the '
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
        reason: 'Clicking Delete must switch the dashboard to the Chat '
            'section so the user sees the confirmation prompt.',
      );
    });

    test('client-owned ciphertext delete is confirmed locally first', () {
      final src = _readMain();
      final start =
          src.indexOf('Future<void> _startSecureItemDeleteConfirmation(');
      final body = src.substring(
        start,
        (start + 12000).clamp(0, src.length),
      );

      expect(
        body,
        contains('_pendingClientSecureItemDeleteService = safeService'),
        reason: 'The dashboard must keep the selected client-encrypted item '
            'until the user confirms the destructive action.',
      );
      expect(
        body,
        contains("msgs.add(_Msg('assistant', question))"),
        reason: 'The user must see an explicit confirmation question before '
            'the ciphertext row is deleted.',
      );
    });

    test('confirmed action uses ciphertext-aware delete and refreshes', () {
      final src = _readMain();
      final start = src.indexOf(
        'Future<bool> _tryResolveClientSecureItemDelete(',
      );
      expect(start, greaterThan(-1));
      final body = src.substring(
        start,
        (start + 6000).clamp(0, src.length),
      );

      expect(
        body,
        contains('await client.deleteVaultSecureItem('),
        reason: 'Confirmed dashboard deletion must use the existing method '
            'that resolves and deletes client-encrypted vault items.',
      );
      expect(
        body,
        contains('await _reloadVaultLoginsAfterMutation()'),
        reason: 'The visible dashboard must refresh after a confirmed delete.',
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
        reason: 'Non-login bubble must read "Delete <title> from my vault".',
      );
      expect(
        body,
        contains("'Delete \$safeService login from my vault'"),
        reason: 'Login bubble must read "Delete <title> login from my vault".',
      );

      expect(
        body,
        isNot(contains("msgs.add(_Msg('user', sentinel))")),
        reason: 'The user-visible bubble must never be the raw sentinel.',
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
        contains('_reloadVaultLoginsAfterMutation()'),
        reason: 'After the backend BAND_DELETED reply, the Logins page list '
            'must refresh so the deleted row disappears.',
      );
    });
  });

  group('Click does NOT call the delete API directly', () {
    test('Logins page onDelete body does not call deleteVaultSecureItem', () {
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
        reason: 'The Logins page Delete callback must NOT call the delete '
            'API directly — it must route through chat confirmation.',
      );
    });

    test(
        'chat secure-item card onSecureItemDelete body does not call '
        'deleteVaultSecureItem directly', () {
      final src = _readMain();
      final clueStart = src.indexOf('onSecureItemDelete: (title, itemType) {');
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
        reason: 'The chat card Delete callback must NOT call the delete '
            'API directly — it must route through chat confirmation.',
      );
    });
  });
}
