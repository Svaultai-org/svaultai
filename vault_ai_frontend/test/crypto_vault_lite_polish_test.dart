

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';


Future<void> _pump(
  WidgetTester tester, {
  List<Map<String, dynamic>>? savedRecords,
  void Function(String prompt)? onSendChatPrompt,
  void Function(Map<String, dynamic>)? onShowQR,
  Size viewport = const Size(900, 2000),
}) async {
  await tester.binding.setSurfaceSize(viewport);
  await tester.pumpWidget(
    MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: CryptoVaultLitePage(
          savedRecords: savedRecords ?? const <Map<String, dynamic>>[],
          onSendChatPrompt: onSendChatPrompt,
          onShowQR: onShowQR,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  
  
  group('Hero card', () {
    testWidgets('hero card renders with operator-pinned content',
        (tester) async {
      await _pump(tester);
      expect(find.byKey(const Key('crypto_lite_hero_card')),
          findsOneWidget);
      
      
      expect(find.text('Crypto Vault'), findsOneWidget);
      
      expect(find.byKey(const Key('crypto_lite_active_chip')),
          findsOneWidget);
      expect(find.text('Active'), findsAtLeastNWidgets(1));
      
      expect(
        find.text(
          'Store wallet addresses, seed phrases, private keys, '
          'recovery phrases, crypto notes, and receive QR codes '
          'securely.',
        ),
        findsOneWidget,
      );
      
      expect(
        find.text(
          'Send features are not enabled yet. Receive QR only '
          'shows saved addresses.',
        ),
        findsOneWidget,
      );
    });

    testWidgets('hero is anti-claim safe', (tester) async {
      await _pump(tester);
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        final body = (t.data ?? '').toLowerCase();
        for (final needle in const [
          'you can send',
          'you can buy',
          'you can sell',
          'you can trade',
          'you can swap',
          'create wallet',
          'create a wallet',
          'wallet generation',
          'broadcast transaction',
        ]) {
          expect(
            body.contains(needle), isFalse,
            reason: 'hero / page must NOT contain "$needle"; '
                'found in "$body"',
          );
        }
      }
    });
  });

  
  group('Counter row', () {
    testWidgets('counters render with zero values in empty state',
        (tester) async {
      await _pump(tester);
      expect(find.byKey(const Key('crypto_lite_counters')),
          findsOneWidget);
      for (final spec in kCryptoCounters) {
        expect(find.byKey(Key(spec.key)), findsOneWidget);
        
        final value = tester.widget<Text>(
          find.byKey(Key('${spec.key}_value')),
        );
        expect(value.data, '0',
            reason: '${spec.key} must read 0 in the empty state');
        
        expect(find.text('${spec.label}: '), findsOneWidget);
      }
    });

    testWidgets('counters reflect saved record types', (tester) async {
      await _pump(tester, savedRecords: const [
        {'item_id': 'w1', 'type': 'crypto_wallet_address',  'title': 'BTC'},
        {'item_id': 'w2', 'type': 'crypto_wallet_address',  'title': 'ETH'},
        {'item_id': 's1', 'type': 'crypto_seed_phrase',     'title': 'Seed'},
        {'item_id': 's2', 'type': 'crypto_private_key',     'title': 'PK'},
        {'item_id': 'r1', 'type': 'crypto_recovery_phrase', 'title': 'Rec'},
        {'item_id': 'n1', 'type': 'crypto_note',            'title': 'Note'},
        {'item_id': 'n2', 'type': 'crypto_exchange_note',   'title': 'Bin'},
        {'item_id': 't1', 'type': 'crypto_transaction_note','title': 'Tx 1'},
        {'item_id': 't2', 'type': 'crypto_transaction_note','title': 'Tx 2'},
        {'item_id': 't3', 'type': 'crypto_transaction_note','title': 'Tx 3'},
      ]);
      
      final wallets = tester.widget<Text>(find.byKey(
        const Key('crypto_lite_counter_wallets_value')));
      final sensitive = tester.widget<Text>(find.byKey(
        const Key('crypto_lite_counter_sensitive_keys_value')));
      final notes = tester.widget<Text>(find.byKey(
        const Key('crypto_lite_counter_notes_value')));
      final tx = tester.widget<Text>(find.byKey(
        const Key('crypto_lite_counter_transactions_value')));
      expect(wallets.data,  '2');
      expect(sensitive.data, '3');
      expect(notes.data,    '2');
      expect(tx.data,       '3');
    });
  });

  
  group('Feature tiles', () {
    testWidgets('four operator-pinned tiles render', (tester) async {
      await _pump(tester);
      expect(find.byKey(const Key('crypto_lite_feature_tiles')),
          findsOneWidget);
      
      for (final t in kCryptoFeatureTiles) {
        expect(find.byKey(Key(t.key)), findsOneWidget);
        expect(find.text(t.title), findsAtLeastNWidgets(1));
      }
      
      expect(
        find.text('Save addresses and show receive QR codes.'),
        findsOneWidget,
      );
      expect(
        find.text('Encrypted storage for sensitive recovery data.'),
        findsOneWidget,
      );
      expect(
        find.text(
            'Keep exchange, hardware wallet, and transaction notes.'),
        findsOneWidget,
      );
      expect(
        find.text('Show QR codes for saved wallet addresses.'),
        findsOneWidget,
      );
    });

    testWidgets('tiles render even when records exist', (tester) async {
      await _pump(tester, savedRecords: const [
        {'item_id': 'w1', 'type': 'crypto_wallet_address', 'title': 'BTC'},
      ]);
      expect(find.byKey(const Key('crypto_lite_feature_tiles')),
          findsOneWidget);
    });
  });

  
  group('Improved empty state', () {
    testWidgets('empty state card replaces the legacy plain frame',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_lite_empty_state_card')),
        findsOneWidget,
      );
      
      expect(
        find.text('Start by saving your first crypto record'),
        findsOneWidget,
      );
      
      expect(
        find.text(
          'Add a wallet address, seed phrase, private key, '
          'crypto note, or transaction note. Everything is '
          'encrypted inside your vault.',
        ),
        findsOneWidget,
      );
      
      
      expect(
        find.byKey(const Key('crypto_lite_empty_primary_button')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(
            const Key('crypto_lite_empty_secondary_seed_button')),
        findsOneWidget,
      );
      expect(
        find.byKey(
            const Key('crypto_lite_empty_secondary_note_button')),
        findsOneWidget,
      );
    });

    testWidgets(
      'empty primary button opens the Add Crypto Wallet dialog',
      (tester) async {
        
        
        final prompts = <String>[];
        await _pump(tester, onSendChatPrompt: prompts.add);
        await tester.tap(
          find.byKey(const Key('crypto_lite_empty_primary_button')),
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('crypto_lite_add_wallet_dialog')),
          findsOneWidget,
        );
        expect(prompts, isEmpty);
      },
    );

    testWidgets('empty state DOES NOT render when records exist',
        (tester) async {
      await _pump(tester, savedRecords: const [
        {'item_id': 'w1', 'type': 'crypto_wallet_address', 'title': 'BTC'},
      ]);
      expect(
        find.byKey(const Key('crypto_lite_empty_state_card')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_lite_empty_primary_button')),
        findsNothing,
      );
    });
  });

  
  group('Chat suggestions', () {
    testWidgets('renders in the empty state with closed-set prompts',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_lite_chat_suggestions_card')),
        findsOneWidget,
      );
      expect(find.text('Try asking VaultAI:'), findsOneWidget);
      for (final s in kCryptoChatSuggestions) {
        expect(find.byKey(Key(s.key)), findsOneWidget);
        expect(find.text(s.label), findsOneWidget);
      }
    });

    testWidgets('tap routes prompt through onSendChatPrompt',
        (tester) async {
      final prompts = <String>[];
      await _pump(tester, onSendChatPrompt: prompts.add);
      await tester.tap(find.byKey(
        const Key('crypto_lite_suggest_show_btc_qr'),
      ));
      await tester.pumpAndSettle();
      expect(prompts, ['show my BTC receive QR']);
    });

    testWidgets('chat suggestions DO NOT render when records exist',
        (tester) async {
      await _pump(tester, savedRecords: const [
        {'item_id': 'w1', 'type': 'crypto_wallet_address', 'title': 'BTC'},
      ]);
      expect(
        find.byKey(const Key('crypto_lite_chat_suggestions_card')),
        findsNothing,
      );
    });
  });

  
  group('Records mode regression', () {
    testWidgets('wallet card still surfaces Show QR', (tester) async {
      Map<String, dynamic>? qrFor;
      await _pump(
        tester,
        savedRecords: const [
          {
            'item_id':        'w1',
            'type':           'crypto_wallet_address',
            'title':          'BTC wallet',
            'category_label': 'Crypto wallet',
            'preview': {
              'wallet_address_mask': '1A1z…eEYx',
              'network':              'BTC',
            },
          },
        ],
        onShowQR: (r) => qrFor = r,
      );
      
      final showQrFinder = find.byKey(const Key('crypto_card_show_qr_w1'));
      expect(showQrFinder, findsOneWidget);
      await tester.ensureVisible(showQrFinder);
      await tester.tap(showQrFinder);
      await tester.pumpAndSettle();
      expect(qrFor, isNotNull);
      expect(qrFor!['item_id'], 'w1');
    });

    testWidgets('seed phrase card hides Show QR', (tester) async {
      await _pump(tester, savedRecords: const [
        {
          'item_id':        's1',
          'type':           'crypto_seed_phrase',
          'title':          'BTC seed',
          'category_label': 'Seed phrase',
          'preview': {'seed_phrase_mask': '•••••• hidden'},
        },
      ]);
      expect(find.byKey(const Key('crypto_card_show_qr_s1')), findsNothing);
    });
  });

  
  group('Mobile layout', () {
    testWidgets('renders without overflow at 360 px', (tester) async {
      
      
      await _pump(tester, viewport: const Size(360, 2400));
      
      
      expect(find.byKey(const Key('crypto_lite_hero_card')),
          findsOneWidget);
      expect(find.byKey(const Key('crypto_lite_counters')),
          findsOneWidget);
      expect(find.byKey(const Key('crypto_lite_feature_tiles')),
          findsOneWidget);
      expect(
        find.byKey(const Key('crypto_lite_empty_state_card')),
        findsOneWidget,
      );
    });
  });
}
