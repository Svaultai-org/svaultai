import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';
import 'package:vault_ai_frontend/ui/secure_item_detail.dart';

void main() {
  test('explicit View formats every stored login field', () {
    final text = secureItemViewTextFor('login', const <String, String>{
      'username': 'qa-user',
      'password': 'temporary-password',
      'url': 'https://example.com',
      'note': 'Encrypted retrieval regression test',
    });

    expect(text, contains('Username: qa-user'));
    expect(text, contains('Password: temporary-password'));
    expect(text, contains('Website or URL: https://example.com'));
    expect(text, contains('Note: Encrypted retrieval regression test'));
  });

  testWidgets('View preserves a title that itself ends in Login',
      (tester) async {
    String? viewedTitle;
    String? viewedType;
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: LoginsPage(
          isLoading: false,
          hasLoaded: true,
          logins: const <VaultLoginItem>[
            VaultLoginItem(service: 'QA Login', itemType: 'login'),
          ],
          onRefresh: () async {},
          vaultLabel: 'QA Review',
          onView: (title, type) {
            viewedTitle = title;
            viewedType = type;
          },
        ),
      ),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(OutlinedButton, 'View'));
    await tester.pump();

    expect(viewedTitle, 'QA Login');
    expect(viewedType, 'login');
  });

  test('dashboard View fetches the exact item instead of using chat parsing',
      () async {
    final source = await File('lib/main.dart').readAsString();
    final start = source.indexOf('Future<void> _openSecureItemView(');
    final end = source.indexOf(
      'Future<void> _showCreateMenu()',
      start,
    );
    expect(start, isNonNegative);
    expect(end, greaterThan(start));
    final body = source.substring(start, end);

    expect(body, contains('getVaultSecureItem('));
    expect(body, contains('showSecureItemDetailSheet('));
    expect(body, isNot(contains('_sendQuickPrompt(')));
  });

  test('PIN-only unlock restores ZK keys from the saved vault handle',
      () async {
    final source = await File('lib/main.dart').readAsString();
    final unlockStart = source.indexOf('class _UnlockPageState');
    final unlockEnd = source.indexOf('class PinGatePage', unlockStart);
    expect(unlockStart, isNonNegative);
    expect(unlockEnd, greaterThan(unlockStart));
    final unlockBody = source.substring(unlockStart, unlockEnd);

    expect(
      unlockBody,
      contains('selectInheritanceRevealLoginIdentifier('),
    );
    expect(unlockBody, contains('vaultHandle: app.vaultHandle'));
    expect(unlockBody, contains('vaultName: loginId.vaultName'));
    expect(unlockBody, contains('vaultHandle: loginId.vaultHandle'));
  });

  test('session PIN gate refuses to unlock without restored ZK keys', () async {
    final source = await File('lib/main.dart').readAsString();
    final verifyStart = source.indexOf('Future<bool> verifyPin(');
    final verifyEnd = source.indexOf(
      'Future<bool> applyFreshKdfMetadata(',
      verifyStart,
    );
    expect(verifyStart, isNonNegative);
    expect(verifyEnd, greaterThan(verifyStart));
    final verifyBody = source.substring(verifyStart, verifyEnd);
    expect(verifyBody, contains('if (zkRestore == null)'));
    expect(
      verifyBody,
      contains('Could not unlock encrypted vault data.'),
    );

    final pinGateStart = source.indexOf('class _PinGatePageState');
    final pinGateEnd = source.indexOf('class _ChatDashboardPageState');
    expect(pinGateStart, isNonNegative);
    expect(pinGateEnd, greaterThan(pinGateStart));
    final pinGateBody = source.substring(pinGateStart, pinGateEnd);
    expect(pinGateBody, contains('restoreZkSessionKeys: true'));
  });
}
