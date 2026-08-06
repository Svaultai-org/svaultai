
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/delete_vault_flow.dart';
import 'package:vault_ai_frontend/help_center_content.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


Future<void> _pumpDeleteFlow(
  WidgetTester tester, {
  Size size = const Size(720, 1000),
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  final client = const VaultAIClient(
    baseUrl: 'http://127.0.0.1:1',
  );
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: DeleteVaultFlow(
          client: client,
          authToken: 'test-token',
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


Future<void> _pumpHelpCenter(
  WidgetTester tester, {
  HelpCenterMode mode = HelpCenterMode.signedIn,
  Size size = const Size(1400, 12000),
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(body: HelpCenterPage(mode: mode)),
    ),
  );
  await tester.pumpAndSettle();
}


String _answerFor(String id) {
  final e = faqEntryById(id);
  expect(e, isNotNull, reason: 'FAQ $id must exist in kFaqEntries');
  return e!.answer;
}


void main() {


  group('Part 1 — Delete Vault destructive dialog renders', () {
    testWidgets('renders with destructive title', (tester) async {
      await _pumpDeleteFlow(tester);
      expect(
        find.textContaining('Delete vault permanently?'),
        findsOneWidget,
      );
    });

    testWidgets('shows the operator warning copy', (tester) async {
      await _pumpDeleteFlow(tester);
      expect(
        find.textContaining(
          'permanently deletes your SVaultAI vault data',
        ),
        findsOneWidget,
      );
      expect(
        find.textContaining('files, secure items, logins, ID'),
        findsOneWidget,
      );
      expect(
        find.textContaining(
          'Crypto Vault encrypted wallet records',
        ),
        findsOneWidget,
      );
    });

    testWidgets('crypto warning explicitly renders', (tester) async {
      await _pumpDeleteFlow(tester);
      expect(
        find.byKey(const Key('delete_vault_crypto_warning')),
        findsOneWidget,
      );
      expect(
        find.textContaining(
          'does not move or delete crypto assets on the blockchain',
        ),
        findsOneWidget,
      );
    });
  });


  group('Part 2 — Confirmation phrase gate', () {
    testWidgets(
      'delete button is disabled until phrase matches exactly',
      (tester) async {
        await _pumpDeleteFlow(tester);
        final ElevatedButton btn = tester.widget<ElevatedButton>(
          find.byKey(const Key('delete_vault_confirm_button')),
        );
        expect(btn.onPressed, isNull,
            reason: 'button must start disabled');

        await tester.enterText(
          find.byKey(const Key('delete_vault_phrase_field')),
          'DELETE MY VAULT',
        );
        await tester.pump();

        final ElevatedButton stillBtn =
            tester.widget<ElevatedButton>(
          find.byKey(const Key('delete_vault_confirm_button')),
        );
        expect(stillBtn.onPressed, isNull,
            reason: 'button must remain disabled without PIN');

        await tester.enterText(
          find.byKey(const Key('delete_vault_pin_field')),
          '123456',
        );
        await tester.pump();

        final ElevatedButton nowBtn =
            tester.widget<ElevatedButton>(
          find.byKey(const Key('delete_vault_confirm_button')),
        );
        expect(nowBtn.onPressed, isNotNull,
            reason:
                'button must enable only when BOTH the phrase and '
                'the PIN are entered correctly');
      },
    );

    testWidgets(
      'lowercase phrase does NOT enable the button',
      (tester) async {
        await _pumpDeleteFlow(tester);
        await tester.enterText(
          find.byKey(const Key('delete_vault_phrase_field')),
          'delete my vault',
        );
        await tester.enterText(
          find.byKey(const Key('delete_vault_pin_field')),
          '123456',
        );
        await tester.pump();
        final ElevatedButton btn = tester.widget<ElevatedButton>(
          find.byKey(const Key('delete_vault_confirm_button')),
        );
        expect(btn.onPressed, isNull,
            reason:
                'phrase must be exactly DELETE MY VAULT — case '
                'matters');
      },
    );

    testWidgets(
      'phrase field shows error when non-empty but not matching',
      (tester) async {
        await _pumpDeleteFlow(tester);
        await tester.enterText(
          find.byKey(const Key('delete_vault_phrase_field')),
          'DELETE',
        );
        await tester.pump();
        expect(
          find.textContaining('Phrase must match exactly.'),
          findsOneWidget,
        );
      },
    );
  });


  group('Part 3 — PIN gate', () {
    testWidgets('PIN field is obscured', (tester) async {
      await _pumpDeleteFlow(tester);
      final TextField pinField = tester.widget<TextField>(
        find.byKey(const Key('delete_vault_pin_field')),
      );
      expect(pinField.obscureText, isTrue);
    });

    testWidgets(
      'PIN field is present in the dialog',
      (tester) async {
        await _pumpDeleteFlow(tester);
        expect(
          find.byKey(const Key('delete_vault_pin_field')),
          findsOneWidget,
        );
      },
    );

    testWidgets('confirmation phrase constant is exactly the operator brief',
        (tester) async {
      expect(kDeleteVaultConfirmationPhrase, equals('DELETE MY VAULT'));
    });
  });


  group('Part 4 — Cancel path', () {
    testWidgets(
      'Cancel button dismisses without triggering delete',
      (tester) async {
        final navKey = GlobalKey<NavigatorState>();
        await tester.pumpWidget(
          MaterialApp(
            navigatorKey: navKey,
            localizationsDelegates: _testL10nDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: Scaffold(
              body: Builder(
                builder: (ctx) => Center(
                  child: ElevatedButton(
                    onPressed: () => showDeleteVaultDialog(
                      ctx,
                      client: const VaultAIClient(
                        baseUrl: 'http://127.0.0.1:1',
                      ),
                      authToken: 't',
                    ),
                    child: const Text('open'),
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.tap(find.text('open'));
        await tester.pumpAndSettle();

        expect(
          find.byKey(const Key('delete_vault_dialog')),
          findsOneWidget,
        );

        await tester.tap(
          find.byKey(const Key('delete_vault_cancel_button')),
        );
        await tester.pumpAndSettle();

        expect(
          find.byKey(const Key('delete_vault_dialog')),
          findsNothing,
        );
      },
    );
  });


  group('Part 5 — FAQ deletion entries are present', () {
    for (final id in const <String>[
      'delete-my-vault',
      'what-happens-when-i-delete-my-vault',
      'can-i-recover-deleted-vault',
      'crypto-when-vault-deleted',
      'why-inactive-unpaid-deleted',
      'how-to-prevent-auto-deletion',
    ]) {
      test('FAQ $id exists in kFaqEntries', () {
        expect(
          faqEntryById(id), isNotNull,
          reason: 'FAQ $id must be present',
        );
      });
    }

    test('automatic-deletion FAQ mentions the 6-month cutoff', () {
      final a = _answerFor('why-inactive-unpaid-deleted').toLowerCase();
      expect(a.contains('6 months'), isTrue);
      expect(a.contains('unpaid'), isTrue);
      expect(a.contains('permanently deleted'), isTrue);
    });

    test('prevent-auto-deletion FAQ explains keep-active path', () {
      final a = _answerFor('how-to-prevent-auto-deletion').toLowerCase();
      expect(a.contains('sign in'), isTrue);
      expect(a.contains('subscribe'), isTrue);
      expect(a.contains('6-month'), isTrue);
    });

    test('crypto-when-vault-deleted is explicit about no on-chain move',
        () {
      final a = _answerFor('crypto-when-vault-deleted').toLowerCase();
      expect(a.contains('does not move or delete'), isTrue);
      expect(a.contains('blockchain'), isTrue);
      expect(a.contains('never broadcasts'), isTrue);
    });

    test('can-i-recover-deleted-vault is honest that recovery is not '
        'possible', () {
      final a = _answerFor('can-i-recover-deleted-vault').toLowerCase();
      expect(a.contains('no.'), isTrue);
      expect(a.contains('permanently'), isTrue);
      expect(a.contains('no recovery flow'), isTrue);
    });
  });


  group('Part 6 — no pending-deletion / grace-period copy anywhere',
      () {
    const forbidden = <String>[
      'pending deletion',
      'pending-deletion',
      'grace period',
      'grace-period',
      '30-day grace',
      '30 day grace',
      'scheduled for deletion',
      'will be deleted in',
    ];

    const policyIds = <String>[
      'delete-my-vault',
      'what-happens-when-i-delete-my-vault',
      'can-i-recover-deleted-vault',
      'crypto-when-vault-deleted',
      'why-inactive-unpaid-deleted',
      'how-to-prevent-auto-deletion',
    ];

    test('policy copy never uses pending/grace language', () {
      final offenders = <String>[];
      for (final id in policyIds) {
        final a = _answerFor(id).toLowerCase();
        for (final f in forbidden) {
          if (a.contains(f)) offenders.add('$id → $f');
        }
      }
      expect(
        offenders, isEmpty,
        reason:
            'delete-policy copy must not mention pending deletion '
            'or grace periods: $offenders',
      );
    });
  });


  group('Part 7 — Help Center render integration', () {
    testWidgets(
      'signed-in Help Center renders the delete-my-vault answer',
      (tester) async {
        await _pumpHelpCenter(tester);
        expect(
          find.textContaining(
            'exact phrase',
            findRichText: true,
          ),
          findsWidgets,
        );
      },
    );

    testWidgets(
      'Help Center renders the automatic-deletion copy',
      (tester) async {
        await _pumpHelpCenter(tester);
        expect(
          find.textContaining(
            'not used for at least 6 months',
            findRichText: true,
          ),
          findsWidgets,
        );
      },
    );
  });


  group('Part 8 — No secrets or generic-Aisha copy anywhere', () {
    const banned = <String>[
      'aisha',
      'sample data',
      'lorem ipsum',
      'seed phrase',
      'mnemonic',
      'private key',
      'raw pin',
      'plaintext pin',
    ];

    const scannedIds = <String>[
      'delete-my-vault',
      'what-happens-when-i-delete-my-vault',
      'can-i-recover-deleted-vault',
      'crypto-when-vault-deleted',
      'why-inactive-unpaid-deleted',
      'how-to-prevent-auto-deletion',
    ];

    test('delete FAQs never surface seed/mnemonic/private-key text',
        () {
      final offenders = <String>[];
      for (final id in scannedIds) {
        final a = _answerFor(id).toLowerCase();
        for (final b in banned) {
          if (a.contains(b)) offenders.add('$id → $b');
        }
      }
      expect(offenders, isEmpty);
    });

    testWidgets(
      'delete dialog does not render Aisha or lorem-ipsum copy',
      (tester) async {
        await _pumpDeleteFlow(tester);
        for (final b in banned) {
          expect(
            find.textContaining(b, findRichText: true),
            findsNothing,
            reason: 'delete dialog must not contain "$b"',
          );
        }
      },
    );
  });


  group('Part 9 — Mobile layout has no overflow', () {
    testWidgets('delete dialog at 400x900', (tester) async {
      await _pumpDeleteFlow(tester,
          size: const Size(400, 900));
      expect(tester.takeException(), isNull);
    });

    testWidgets('delete dialog at 360x800', (tester) async {
      await _pumpDeleteFlow(tester,
          size: const Size(360, 800));
      expect(tester.takeException(), isNull);
    });

    testWidgets('Help Center at 360x800 renders new copy', (tester) async {
      await _pumpHelpCenter(tester, size: const Size(360, 800));
      expect(tester.takeException(), isNull);
    });
  });
}
