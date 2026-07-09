

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';


Future<void> _pump(
  WidgetTester tester, {
  void Function(String prompt)? onSendChatPrompt,
  Future<void> Function(CryptoAddNoteDraft draft)? onDirectSaveCryptoNote,
}) async {
  await tester.binding.setSurfaceSize(const Size(900, 2400));
  await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: CryptoVaultLitePage(
        savedRecords: const [],
        onSendChatPrompt: onSendChatPrompt,
        onDirectSaveCryptoNote: onDirectSaveCryptoNote,
        
        onDirectSaveWalletProfile: (_) async {},
      ),
    ),
  ));
  await tester.pumpAndSettle();
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  
  
  group('N1 — Add crypto note opens general dialog', () {
    testWidgets('action-row Add crypto note opens general dialog',
        (tester) async {
      await _pump(
        tester,
        onDirectSaveCryptoNote: (_) async {},
      );
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_crypto_note_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
          const Key('crypto_lite_add_general_note_dialog')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('crypto_lite_add_tx_note_dialog')),
        findsNothing,
      );
      
      
      expect(
        find.byKey(
          const Key('crypto_lite_add_general_note_dialog_title')),
        findsOneWidget,
      );
      final titleText = tester.widget<Text>(find.byKey(
        const Key('crypto_lite_add_general_note_dialog_title'),
      ));
      expect(titleText.data, kCryptoAddNoteGeneralTitle);
    });
  });

  
  group('N2 — Add transaction note opens tx dialog', () {
    testWidgets('action-row Add transaction note opens tx dialog',
        (tester) async {
      await _pump(
        tester,
        onDirectSaveCryptoNote: (_) async {},
      );
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_transaction_note_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_add_tx_note_dialog')),
        findsOneWidget,
      );
      final titleText = tester.widget<Text>(find.byKey(
        const Key('crypto_lite_add_tx_note_dialog_title'),
      ));
      expect(titleText.data, kCryptoAddNoteTxTitle);
    });
  });

  
  group('N3 — General note dialog fields', () {
    testWidgets('exposes asset / title / body', (tester) async {
      await _pump(
        tester,
        onDirectSaveCryptoNote: (_) async {},
      );
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_crypto_note_button'),
      ));
      await tester.pumpAndSettle();
      for (final key in const [
        'crypto_lite_add_note_asset_dropdown',
        'crypto_lite_add_note_title_field',
        'crypto_lite_add_note_body_field',
        'crypto_lite_add_note_save_button',
        'crypto_lite_add_note_cancel_button',
      ]) {
        expect(find.byKey(Key(key)), findsOneWidget,
            reason: 'general note dialog MUST expose $key');
      }
      
      expect(
        find.byKey(
          const Key('crypto_lite_add_tx_note_wallet_dropdown')),
        findsNothing,
      );
      expect(
        find.byKey(
          const Key('crypto_lite_add_tx_note_tx_hash_field')),
        findsNothing,
      );
      expect(
        find.byKey(
          const Key('crypto_lite_add_tx_note_amount_field')),
        findsNothing,
      );
      expect(
        find.byKey(
          const Key('crypto_lite_add_tx_note_date_field')),
        findsNothing,
      );
      
      expect(
        find.byKey(
          const Key('crypto_lite_add_tx_note_safety_copy')),
        findsNothing,
      );
    });
  });

  
  group('N4 — Transaction note dialog fields', () {
    testWidgets(
      'exposes asset / wallet / tx hash / amount / date / title / body',
      (tester) async {
        await _pump(
          tester,
          onDirectSaveCryptoNote: (_) async {},
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_transaction_note_button'),
        ));
        await tester.pumpAndSettle();
        for (final key in const [
          'crypto_lite_add_note_asset_dropdown',
          'crypto_lite_add_note_title_field',
          'crypto_lite_add_note_body_field',
          'crypto_lite_add_tx_note_wallet_dropdown',
          'crypto_lite_add_tx_note_tx_hash_field',
          'crypto_lite_add_tx_note_amount_field',
          'crypto_lite_add_tx_note_date_field',
          'crypto_lite_add_note_save_button',
          'crypto_lite_add_note_cancel_button',
        ]) {
          expect(find.byKey(Key(key)), findsOneWidget,
              reason: 'tx note dialog MUST expose $key');
        }
      },
    );
  });

  
  group('N5 — Manual-note safety copy', () {
    testWidgets(
      'transaction note dialog renders safety copy verbatim',
      (tester) async {
        await _pump(
          tester,
          onDirectSaveCryptoNote: (_) async {},
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_transaction_note_button'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(
            const Key('crypto_lite_add_tx_note_safety_copy')),
          findsOneWidget,
        );
        expect(
          find.text(kCryptoTxNoteManualSafetyCopy),
          findsOneWidget,
        );
        
        expect(kCryptoTxNoteManualSafetyCopy,
            contains('manual note'));
        expect(kCryptoTxNoteManualSafetyCopy,
            contains('not sending or verifying'));
      },
    );
  });

  
  group('N6 — Validation refusals', () {
    testWidgets(
      'empty title or body refuses to fire onDirectSaveCryptoNote',
      (tester) async {
        final captured = <CryptoAddNoteDraft>[];
        await _pump(
          tester,
          onDirectSaveCryptoNote: (d) async => captured.add(d),
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_crypto_note_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_note_save_button'),
        ));
        await tester.pumpAndSettle();
        expect(captured, isEmpty);
        
        expect(
          find.byKey(
            const Key('crypto_lite_add_general_note_dialog')),
          findsOneWidget,
        );
      },
    );
  });

  
  group('N7 — General note save', () {
    testWidgets(
      'general note save yields draft with noteType=general',
      (tester) async {
        CryptoAddNoteDraft? captured;
        await _pump(
          tester,
          onDirectSaveCryptoNote: (d) async => captured = d,
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_crypto_note_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.enterText(
          find.byKey(const Key('crypto_lite_add_note_title_field')),
          'Cold-wallet rotation',
        );
        await tester.enterText(
          find.byKey(const Key('crypto_lite_add_note_body_field')),
          'Rotate Ledger BTC cold wallet on Q3.',
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_note_save_button'),
        ));
        await tester.pumpAndSettle();
        expect(captured, isNotNull);
        expect(captured!.noteType, 'general');
        expect(captured!.title, 'Cold-wallet rotation');
        expect(captured!.note,
            'Rotate Ledger BTC cold wallet on Q3.');
        expect(captured!.txHash, '');
        expect(captured!.amountText, '');
        expect(captured!.dateText, '');
      },
    );
  });

  
  group('N8 — Transaction note save', () {
    testWidgets(
      'tx note save yields draft with noteType=transaction_note + '
      'every optional field',
      (tester) async {
        CryptoAddNoteDraft? captured;
        await _pump(
          tester,
          onDirectSaveCryptoNote: (d) async => captured = d,
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_transaction_note_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_note_asset_dropdown'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Ethereum').last);
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_tx_note_wallet_dropdown'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Trezor').last);
        await tester.pumpAndSettle();
        
        await tester.enterText(
          find.byKey(const Key('crypto_lite_add_note_title_field')),
          'ETH withdrawal',
        );
        await tester.enterText(
          find.byKey(const Key('crypto_lite_add_note_body_field')),
          'Moved funds off exchange.',
        );
        
        await tester.enterText(
          find.byKey(
            const Key('crypto_lite_add_tx_note_tx_hash_field')),
          '0xabc123',
        );
        await tester.enterText(
          find.byKey(
            const Key('crypto_lite_add_tx_note_amount_field')),
          '0.5 ETH',
        );
        await tester.enterText(
          find.byKey(
            const Key('crypto_lite_add_tx_note_date_field')),
          '2026-06-29',
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_note_save_button'),
        ));
        await tester.pumpAndSettle();
        expect(captured, isNotNull);
        expect(captured!.noteType, 'transaction_note');
        expect(captured!.title, 'ETH withdrawal');
        expect(captured!.note, 'Moved funds off exchange.');
        expect(captured!.asset?.id, 'eth');
        expect(captured!.walletLabel?.id, 'trezor');
        expect(captured!.txHash, '0xabc123');
        expect(captured!.amountText, '0.5 ETH');
        expect(captured!.dateText, '2026-06-29');
      },
    );
  });

  
  group('N9 — Save error UI', () {
    testWidgets(
      'save error keeps dialog open and shows inline error',
      (tester) async {
        await _pump(
          tester,
          onDirectSaveCryptoNote: (_) async {
            throw Exception('Save crypto note failed: 500');
          },
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_crypto_note_button'),
        ));
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(const Key('crypto_lite_add_note_title_field')),
          'A title',
        );
        await tester.enterText(
          find.byKey(const Key('crypto_lite_add_note_body_field')),
          'A body',
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_note_save_button'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(
            const Key('crypto_lite_add_general_note_dialog')),
          findsOneWidget,
        );
        expect(
          find.byKey(
            const Key('crypto_lite_add_note_save_error')),
          findsOneWidget,
        );
      },
    );
  });

  
  group('N10 — Cancel does not save', () {
    testWidgets('Cancel dismisses dialog without firing onSave',
        (tester) async {
      final captured = <CryptoAddNoteDraft>[];
      await _pump(
        tester,
        onDirectSaveCryptoNote: (d) async => captured.add(d),
      );
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_crypto_note_button'),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_note_cancel_button'),
      ));
      await tester.pumpAndSettle();
      expect(captured, isEmpty);
      expect(
        find.byKey(
          const Key('crypto_lite_add_general_note_dialog')),
        findsNothing,
      );
    });
  });

  
  group('N11 — Anti-claim guard', () {
    testWidgets(
      'general + tx note dialogs contain no prohibited copy',
      (tester) async {
        await _pump(
          tester,
          onDirectSaveCryptoNote: (_) async {},
        );
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_crypto_note_button'),
        ));
        await tester.pumpAndSettle();
        _assertNoProhibitedCopy(
          tester,
          dialogKey: 'crypto_lite_add_general_note_dialog',
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_note_cancel_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_transaction_note_button'),
        ));
        await tester.pumpAndSettle();
        _assertNoProhibitedCopy(
          tester,
          dialogKey: 'crypto_lite_add_tx_note_dialog',
        );
      },
    );
  });

  
  group('N12 — Mobile layout', () {
    testWidgets('general dialog renders at 360 px', (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 800));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoVaultLitePage(
            savedRecords: const [],
            onDirectSaveCryptoNote: (_) async {},
            onDirectSaveWalletProfile: (_) async {},
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(
        const Key('crypto_lite_add_crypto_note_button'),
      ));
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_crypto_note_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
          const Key('crypto_lite_add_general_note_dialog')),
        findsOneWidget,
      );
    });

    testWidgets('tx dialog renders at 360 px', (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 800));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoVaultLitePage(
            savedRecords: const [],
            onDirectSaveCryptoNote: (_) async {},
            onDirectSaveWalletProfile: (_) async {},
          ),
        ),
      ));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(
        const Key('crypto_lite_add_transaction_note_button'),
      ));
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_transaction_note_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_add_tx_note_dialog')),
        findsOneWidget,
      );
    });
  });

  
  group('N13 — Backward compat', () {
    testWidgets(
      'no direct callback → general button fires legacy '
      'kCryptoPromptAddCryptoNote',
      (tester) async {
        final prompts = <String>[];
        await _pump(
          tester,
          onSendChatPrompt: prompts.add,
          
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_crypto_note_button'),
        ));
        await tester.pumpAndSettle();
        expect(prompts, [kCryptoPromptAddCryptoNote]);
        
        expect(
          find.byKey(
            const Key('crypto_lite_add_general_note_dialog')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'no direct callback → tx button fires legacy '
      'kCryptoPromptAddTransactionNote',
      (tester) async {
        final prompts = <String>[];
        await _pump(
          tester,
          onSendChatPrompt: prompts.add,
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_transaction_note_button'),
        ));
        await tester.pumpAndSettle();
        expect(prompts, [kCryptoPromptAddTransactionNote]);
      },
    );
  });
}


void _assertNoProhibitedCopy(
  WidgetTester tester, {
  required String dialogKey,
}) {
  for (final t in tester.widgetList<Text>(
    find.descendant(
      of: find.byKey(Key(dialogKey)),
      matching: find.byType(Text),
    ),
  )) {
    final body = (t.data ?? '').toLowerCase();
    for (final needle in const [
      'send crypto', 'send btc', 'send eth',
      'sign transaction', 'broadcast transaction',
      'buy crypto', 'sell crypto', 'swap crypto',
      'trade crypto', 'create wallet', 'create a wallet',
      'connect metamask',
      'verify transaction', 'import transaction history',
    ]) {
      expect(body.contains(needle), isFalse,
          reason: '$dialogKey must NOT contain "$needle"; '
              'found in "$body"');
    }
  }
}
