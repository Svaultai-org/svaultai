
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/help_center_content.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


Future<void> _pump(
  WidgetTester tester, {
  required HelpCenterMode mode,
  Size size = const Size(1400, 1200),
  void Function(String q)? onAskAssistant,
  VoidCallback?            onRequireSignIn,
  VoidCallback?            onClose,
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: HelpCenterPage(
          mode:            mode,
          onAskAssistant:  onAskAssistant,
          onRequireSignIn: onRequireSignIn,
          onClose:         onClose,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


const List<String> _kMustHaveIds = <String>[
  'what-is-vaultai',
  'what-can-i-save',
  'is-my-vault-encrypted',
  'if-i-forget-my-pin',
  'how-do-i-get-support',
  'what-is-crypto-vault',
  'is-crypto-custodial',
  'why-monero-different',
  'monero-balance-in-browser',
  'monero-send-disabled',
  'buy-sell-swap',
  'usdt-erc20-vs-trc20',
  'usdc-uses-eth-address',
  'what-plan-am-i-on',
  'storage-limits',
  'how-do-i-upgrade',
];

void main() {

  group('Help Center title + support note', () {
    testWidgets('title is "Help & FAQ"', (tester) async {
      await _pump(tester, mode: HelpCenterMode.public);
      expect(kHelpCenterTitle, 'Help & FAQ');
      expect(find.text('Help & FAQ'), findsOneWidget);
    });

    testWidgets('support note copy matches the operator brief',
        (tester) async {
      await _pump(tester, mode: HelpCenterMode.signedIn);
      expect(
        kHelpCenterSupportNote.toLowerCase(),
        contains('live customer support is not available'),
      );
      expect(
        find.byKey(const Key('help_center_support_note')),
        findsOneWidget,
      );
    });
  });


  group('Public mode', () {
    testWidgets(
      'renders with public key, banner, and sign-in button',
      (tester) async {
        var signedIn = false;
        await _pump(
          tester,
          mode: HelpCenterMode.public,
          onRequireSignIn: () => signedIn = true,
        );
        expect(
          find.byKey(const Key('help_center_page_public')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('help_center_public_banner')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('help_center_public_sign_in')),
          findsOneWidget,
        );

        await tester.tap(
          find.byKey(const Key('help_center_public_sign_in')),
        );
        await tester.pumpAndSettle();
        expect(signedIn, isTrue);
      },
    );

    testWidgets(
      'FAQ entries render but "Ask Svaultai" is REPLACED with '
      '"Sign in to ask Svaultai"',
      (tester) async {
        var signInPressed = false;
        await _pump(
          tester,
          mode: HelpCenterMode.public,
          onRequireSignIn: () => signInPressed = true,
        );


        expect(
          find.byKey(const Key(
              'help_entry_signin_what-is-vaultai')),
          findsOneWidget,
        );

        expect(
          find.byKey(const Key(
              'help_entry_ask_what-is-vaultai')),
          findsNothing,
        );


        await tester.tap(
          find.byKey(const Key(
              'help_entry_signin_what-is-vaultai')),
        );
        await tester.pumpAndSettle();
        expect(signInPressed, isTrue);
      },
    );

    testWidgets(
      'public mode does not render user-specific data patterns',
      (tester) async {
        await _pump(tester, mode: HelpCenterMode.public);


        expect(
          find.textContaining(RegExp(r'\d+(?:\.\d+)?\s*(?:GB|MB|TB)\s+used\s+of'),
              findRichText: true),
          findsNothing,
          reason: 'public FAQ leaked actual storage usage',
        );

        expect(
          find.textContaining(RegExp(r'plan:\s*\w'),
              findRichText: true),
          findsNothing,
          reason: 'public FAQ leaked plan value',
        );

        expect(
          find.textContaining(RegExp(r'balance:\s*\d'),
              findRichText: true),
          findsNothing,
          reason: 'public FAQ leaked balance value',
        );
      },
    );

    testWidgets(
      'onAskAssistant callback IS NOT invoked in public mode '
      'even if a caller wires it',
      (tester) async {
        var asked = false;
        await _pump(
          tester,
          mode: HelpCenterMode.public,
          onAskAssistant: (_) => asked = true,

          onRequireSignIn: () {},
        );

        expect(
          find.byKey(const Key(
              'help_entry_ask_what-is-vaultai')),
          findsNothing,
        );

        expect(asked, isFalse);
      },
    );

    testWidgets(
      'search still works in public mode',
      (tester) async {
        await _pump(tester, mode: HelpCenterMode.public);
        await tester.enterText(
          find.byKey(const Key('help_center_search_field')),
          'monero',
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
              'help_center_entry_why-monero-different')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(
              'help_center_entry_what-is-vaultai')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'category chip strip still works in public mode',
      (tester) async {
        await _pump(tester, mode: HelpCenterMode.public);
        for (final c in kFaqCategories) {
          expect(
            find.byKey(Key('help_center_chip_${c.id}')),
            findsOneWidget,
          );
        }
        await tester.tap(
          find.byKey(const Key('help_center_chip_crypto')),
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
              'help_center_entry_what-is-crypto-vault')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key(
              'help_center_entry_what-is-vaultai')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'mobile no overflow at 400×900',
      (tester) async {
        await _pump(
          tester, mode: HelpCenterMode.public,
          size: const Size(400, 900),
        );
        expect(tester.takeException(), isNull);
      },
    );
  });


  group('Signed-in mode', () {
    testWidgets(
      'renders with signed-in key and NO public banner',
      (tester) async {
        await _pump(tester, mode: HelpCenterMode.signedIn);
        expect(
          find.byKey(const Key('help_center_page')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('help_center_public_banner')),
          findsNothing,
        );
        expect(
          find.byKey(const Key('help_center_public_sign_in')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'shows "Ask Svaultai" button and fires callback with question',
      (tester) async {
        String? asked;
        await _pump(
          tester,
          size: const Size(1400, 12000),
          mode: HelpCenterMode.signedIn,
          onAskAssistant: (q) => asked = q,
        );


        expect(
          find.byKey(const Key(
              'help_entry_signin_what-is-vaultai')),
          findsNothing,
        );


        await tester.tap(
          find.byKey(const Key(
              'help_entry_ask_what-is-vaultai')),
        );
        await tester.pumpAndSettle();
        expect(asked, 'What is Svaultai?');
      },
    );
  });


  group('FAQ content is available for both modes', () {
    testWidgets(
      'public mode renders required brief-mandated FAQ ids',
      (tester) async {
        await _pump(tester, mode: HelpCenterMode.public);
        for (final id in _kMustHaveIds) {
          expect(
            find.byKey(Key('help_center_entry_$id')),
            findsOneWidget,
            reason: 'public FAQ missing required id $id',
          );
        }
      },
    );

    testWidgets(
      'signed-in mode renders required brief-mandated FAQ ids',
      (tester) async {
        await _pump(tester, mode: HelpCenterMode.signedIn);
        for (final id in _kMustHaveIds) {
          expect(
            find.byKey(Key('help_center_entry_$id')),
            findsOneWidget,
            reason: 'signed-in FAQ missing required id $id',
          );
        }
      },
    );
  });


  group('FAQ answers do not leak secrets', () {
    test('no answer contains raw secret placeholders', () {

      for (final e in kFaqEntries) {
        final lower = e.answer.toLowerCase();
        for (final leak in <String>[
          'here is your seed',
          'here is your private key',
          'here is your mnemonic',
          'paste your pin here',
          'reveal your password to',
          'send us your seed',
        ]) {
          expect(
            lower.contains(leak),
            isFalse,
            reason: 'FAQ ${e.id} leaks phrase "$leak"',
          );
        }
      }
    });
  });


  group('Close button', () {
    testWidgets(
      'close button appears only when onClose is wired',
      (tester) async {
        await _pump(tester, mode: HelpCenterMode.public);
        expect(
          find.byKey(const Key('help_center_close')),
          findsNothing,
        );

        var closed = false;
        await _pump(
          tester, mode: HelpCenterMode.public,
          onClose: () => closed = true,
        );
        expect(
          find.byKey(const Key('help_center_close')),
          findsOneWidget,
        );
        await tester.tap(
          find.byKey(const Key('help_center_close')),
        );
        await tester.pumpAndSettle();
        expect(closed, isTrue);
      },
    );
  });
}
