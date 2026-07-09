

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';


Future<void> _pump(
  WidgetTester tester, {
  List<Map<String, dynamic>>? savedRecords,
  void Function(String prompt)? onSendChatPrompt,
}) async {
  await tester.pumpWidget(
    MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: CryptoVaultLitePage(
          savedRecords: savedRecords ?? const <Map<String, dynamic>>[],
          onSendChatPrompt: onSendChatPrompt,
        ),
      ),
    ),
  );
}

const _kForbiddenStrings = <String>[
  
  'you can send',
  'you can receive',
  'you can buy',
  'you can sell',
  'you can trade',
  'you can swap',
  'you can exchange',
  
  'guaranteed',
  'profit',
  'high return',
  'investment return',
  'make money',
  'to the moon',
  
  'we are an exchange',
  'vaultai is an exchange',
  'we sell crypto',
  'vaultai sells',
  'we trade',
  'vaultai is a broker',
];

void _assertNoForbiddenStrings(WidgetTester tester) {
  for (final t in tester.widgetList<Text>(find.byType(Text))) {
    final body = (t.data ?? '').toLowerCase();
    for (final needle in _kForbiddenStrings) {
      expect(
        body.contains(needle), isFalse,
        reason:
            'Crypto Vault Lite must NEVER contain "$needle"; '
            'found in: "$body"',
      );
    }
  }
}



const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {


  group('Heading + subtitle', () {
    testWidgets('heading reads Crypto Vault (no Lite in user copy)', (tester) async {
      
      
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_vault_lite_heading')),
        findsOneWidget,
      );
      final h = tester.widget<Text>(
        find.byKey(const Key('crypto_vault_lite_heading')),
      );
      expect(h.data, 'Crypto Vault');
    });

    testWidgets('subtitle names the storage roadmap', (tester) async {
      
      
      await _pump(tester);
      final s = tester.widget<Text>(
        find.byKey(const Key('crypto_vault_lite_subtitle')),
      );
      for (final fragment in [
        'wallet addresses',
        'crypto notes',
        'seed phrases',
        'private keys',
        'recovery phrases',
        'receive QR codes',
      ]) {
        expect(s.data, contains(fragment));
      }
      
      expect(s.data, isNot(contains('Coming soon')));
      expect(
        s.data,
        isNot(contains('Receive and send features will come later')),
      );
    });
  });


  group('Add buttons', () {
    testWidgets('renders all four add buttons', (tester) async {
      await _pump(tester);
      for (final key in const [
        'crypto_lite_add_wallet_button',
        'crypto_lite_add_seed_button',
        'crypto_lite_add_crypto_note_button',
        'crypto_lite_add_transaction_note_button',
      ]) {
        expect(find.byKey(Key(key)), findsOneWidget);
      }
      
      
      expect(find.text('Add wallet address'), findsAtLeastNWidgets(1));
      expect(
        find.text('Add seed phrase / private key'),
        findsAtLeastNWidgets(1),
      );
      expect(find.text('Add crypto note'), findsAtLeastNWidgets(1));
      
      expect(find.text('Add transaction note'), findsOneWidget);
    });

    testWidgets(
      'wallet button opens the structured Add Crypto Wallet dialog',
      (tester) async {
        
        
        final prompts = <String>[];
        await _pump(tester, onSendChatPrompt: prompts.add);
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('crypto_lite_add_wallet_dialog')),
          findsOneWidget,
        );
        
        
        expect(prompts, isEmpty);
      },
    );

    testWidgets('crypto-note button sends quick prompt', (tester) async {
      final prompts = <String>[];
      await _pump(tester, onSendChatPrompt: prompts.add);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_crypto_note_button'),
      ));
      await tester.pumpAndSettle();
      expect(prompts, [kCryptoPromptAddCryptoNote]);
    });

    testWidgets('transaction-note button sends quick prompt',
        (tester) async {
      final prompts = <String>[];
      await _pump(tester, onSendChatPrompt: prompts.add);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_transaction_note_button'),
      ));
      await tester.pumpAndSettle();
      expect(prompts, [kCryptoPromptAddTransactionNote]);
    });
  });


  group('Seed / private key warning', () {
    testWidgets(
      'tapping "Add seed phrase / private key" opens the strong-'
      'warning dialog',
      (tester) async {
        final prompts = <String>[];
        await _pump(tester, onSendChatPrompt: prompts.add);
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_seed_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(const Key('crypto_vault_strong_warning_dialog')),
          findsOneWidget,
        );
        
        final body = tester.widget<Text>(
          find.byKey(const Key('crypto_vault_strong_warning_body')),
        );
        for (final fragment in [
          'extremely sensitive',
          'Anyone with this phrase or key can control the wallet',
          'Store it only if you understand the risk',
        ]) {
          expect(body.data, contains(fragment));
        }
        
        expect(prompts, isEmpty);
      },
    );

    testWidgets('Cancel dismisses without sending a chat prompt',
        (tester) async {
      final prompts = <String>[];
      await _pump(tester, onSendChatPrompt: prompts.add);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_seed_button'),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(
        const Key('crypto_vault_strong_warning_cancel'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_vault_strong_warning_dialog')),
        findsNothing,
      );
      expect(prompts, isEmpty);
    });

    testWidgets(
      'Continue sends the seed-phrase prompt',
      (tester) async {
        final prompts = <String>[];
        await _pump(tester, onSendChatPrompt: prompts.add);
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_seed_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_vault_strong_warning_continue'),
        ));
        await tester.pumpAndSettle();
        expect(prompts, [kCryptoPromptAddSeed]);
      },
    );
  });


  group('Saved records', () {
    testWidgets('empty list renders the empty-state copy',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_lite_empty_title')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_lite_empty_body')),
        findsOneWidget,
      );
      final title = tester.widget<Text>(
        find.byKey(const Key('crypto_lite_empty_title')),
      );
      
      expect(title.data, 'Start by saving your first crypto record');
    });

    testWidgets(
      'populated list renders one card per record with masked '
      'preview + network chip + NO raw wallet address',
      (tester) async {
        const usdtFull = 'TQx2P5kqY7Lr1Z9w8VnGdQfH3sM6Ev1RnY';
        await _pump(tester, savedRecords: const [
          {
            'item_id': 'r1',
            'type':    'crypto_wallet_address',
            'title':   'USDT TRC20 wallet',
            'category_label': 'Crypto wallet',
            'icon': 'wallet',
            'preview': {
              'wallet_address_mask': 'TQx2P5…1RnY',
              'network':              'USDT TRC20',
            },
            'available_actions': ['open', 'reveal', 'edit', 'delete'],
          },
        ]);
        expect(
          find.byKey(const Key('crypto_lite_records_list')),
          findsOneWidget,
        );
        expect(find.text('USDT TRC20 wallet'), findsOneWidget);
        expect(find.text('Crypto wallet'),     findsOneWidget);
        
        
        expect(find.text('USDT TRC20'),        findsAtLeastNWidgets(1));
        expect(find.text('TQx2P5…1RnY'),       findsOneWidget);
        
        
        for (final t in tester.widgetList<Text>(find.byType(Text))) {
          expect(
            (t.data ?? '').contains(usdtFull), isFalse,
            reason: 'full wallet address must NEVER render',
          );
        }
      },
    );
  });


  group('Anti-claim guardrails', () {
    testWidgets('default page renders no forbidden claims',
        (tester) async {
      await _pump(tester);
      _assertNoForbiddenStrings(tester);
    });

    testWidgets('strong-warning dialog renders no forbidden claims',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_seed_button'),
      ));
      await tester.pumpAndSettle();
      _assertNoForbiddenStrings(tester);
    });
  });


  group('Source guardrails', () {
    test(
      'module source carries no send/receive/wallet/transaction UI',
      () async {
        final src = await File(
          'lib/ui/crypto_vault_lite_page.dart',
        ).readAsString();
        const forbidden = <String>[
          
          "'Send'",
          "'Receive'",
          "'Send crypto'",
          "'Receive crypto'",
          "'Create wallet'",
          "'New wallet'",
          "'Buy'",
          "'Sell'",
          "'Trade'",
          "'Swap'",
          "'Exchange'",
          
          'TransactionScreen',
          'SendCryptoScreen',
          'ReceiveCryptoScreen',
          'WalletScreen',
          'BroadcastScreen',
          
          "import 'package:web3",
          "import 'package:bitcoin",
          "import 'package:eth_",
          "import 'package:solana",
          "import 'package:ethers",
          "import 'package:walletconnect",
          "import 'package:flutter_web3",
        ];
        for (final needle in forbidden) {
          expect(
            src.contains(needle), isFalse,
            reason:
                'crypto_vault_lite_page.dart must NEVER carry '
                '"$needle"',
          );
        }
      },
    );

    test('strong-warning constant is operator-pinned verbatim', () {
      for (final fragment in const [
        'extremely sensitive',
        'Anyone with this phrase or key can control the wallet',
        'Store it only if you understand the risk',
      ]) {
        expect(kCryptoVaultStrongWarning, contains(fragment));
      }
    });

    test(
        'main.dart no longer mounts CryptoVaultLitePage on the live '
        'Crypto Wallet surface (2026-07-01 cleanup)',
        () async {
      
      
      final src = await File('lib/main.dart').readAsString();
      expect(
        src,
        isNot(contains('CryptoVaultLitePage(')),
        reason:
            'main.dart must NOT construct CryptoVaultLitePage on '
            'the live Crypto Wallet surface — the dashboard now '
            'mounts CryptoWalletEnginePage.',
      );
      
      
      expect(
        src,
        contains('billingBlockCount'),
        reason:
            'Crypto Vault section must still gate on billing tier '
            'so free / basic users never reach the wallet engine '
            'dashboard.',
      );
    });
  });
}
