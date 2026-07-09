

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';


Future<void> _pump(
  WidgetTester tester, {
  void Function(String prompt)? onSendChatPrompt,
  void Function(Map<String, dynamic> record)? onShowQR,
  List<Map<String, dynamic>> savedRecords = const [],
}) async {
  await tester.binding.setSurfaceSize(const Size(900, 2400));
  await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: CryptoVaultLitePage(
        savedRecords: savedRecords,
        onSendChatPrompt: onSendChatPrompt ?? (_) {},
        onShowQR: onShowQR,
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
  
  
  group('D1 — Asset dashboard renders eight closed-set cards', () {
    testWidgets('all eight asset cards are present', (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_lite_asset_dashboard')),
        findsOneWidget,
      );
      for (final id in const [
        'btc',
        'eth',
        'usdt_trc20',
        'usdt_erc20',
        'usdc_erc20',
        'sol',
        'bnb',
        'xmr',
      ]) {
        expect(
          find.byKey(Key('crypto_lite_asset_card_$id')),
          findsOneWidget,
          reason: 'asset card $id MUST render',
        );
      }
    });

    testWidgets('asset cards pin operator display names', (tester) async {
      await _pump(tester);
      for (final pair in const [
        ['btc',        'Bitcoin'],
        ['eth',        'Ethereum'],
        ['usdt_trc20', 'USDT TRC20'],
        ['usdt_erc20', 'USDT ERC20'],
        ['usdc_erc20', 'USDC ERC20'],
        ['sol',        'Solana'],
        ['bnb',        'BNB Smart Chain'],
        ['xmr',        'Monero'],
      ]) {
        final id   = pair[0];
        final name = pair[1];
        expect(
          tester.widget<Text>(
            find.byKey(Key('crypto_lite_asset_card_${id}_name')),
          ).data,
          name,
          reason: '$id display name must read "$name"',
        );
      }
    });
  });

  
  group('D2 — Empty asset card pins "No wallet saved"', () {
    testWidgets('all cards show kCryptoNoWalletSaved when no records',
        (tester) async {
      await _pump(tester);
      for (final id in const [
        'btc', 'eth', 'usdt_trc20', 'usdt_erc20',
        'usdc_erc20', 'sol', 'bnb', 'xmr',
      ]) {
        expect(
          tester.widget<Text>(
            find.byKey(Key('crypto_lite_asset_card_${id}_count')),
          ).data,
          kCryptoNoWalletSaved,
          reason: '$id MUST show "No wallet saved" when no records',
        );
      }
      expect(kCryptoNoWalletSaved, 'No wallet saved');
    });

    testWidgets('saved BTC + ETH wallets update only their cards',
        (tester) async {
      await _pump(tester, savedRecords: const [
        {
          'item_id':        'w_btc',
          'type':           'crypto_wallet_address',
          'title':          'Ledger BTC wallet',
          'category_label': 'Wallet address',
          'preview':        {'network': 'Bitcoin'},
        },
        {
          'item_id':        'w_eth_a',
          'type':           'crypto_wallet_address',
          'title':          'MetaMask ETH wallet',
          'category_label': 'Wallet address',
          'preview':        {'network': 'Ethereum'},
        },
        {
          'item_id':        'w_eth_b',
          'type':           'crypto_wallet_address',
          'title':          'Trezor ETH wallet',
          'category_label': 'Wallet address',
          'preview':        {'network': 'Ethereum'},
        },
      ]);
      expect(
        tester.widget<Text>(find.byKey(
          const Key('crypto_lite_asset_card_btc_count'),
        )).data,
        '1 saved',
      );
      expect(
        tester.widget<Text>(find.byKey(
          const Key('crypto_lite_asset_card_eth_count'),
        )).data,
        '2 saved',
      );
      expect(
        tester.widget<Text>(find.byKey(
          const Key('crypto_lite_asset_card_sol_count'),
        )).data,
        kCryptoNoWalletSaved,
      );
    });
  });

  
  group('D3 — Add wallet button opens dialog', () {
    testWidgets('action-row Add wallet address opens the dialog',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_dialog')),
        findsOneWidget,
      );
      expect(
        tester.widget<Text>(find.byKey(
          const Key('crypto_lite_add_wallet_dialog_title'),
        )).data,
        kCryptoAddWalletDialogTitle,
      );
      expect(kCryptoAddWalletDialogTitle, 'Add crypto wallet');
    });

    testWidgets('asset card Add wallet button opens the dialog',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_asset_card_btc_add_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_dialog')),
        findsOneWidget,
      );
    });
  });

  
  group('D4 — Dialog fields render', () {
    testWidgets('dialog has asset/label/address/note fields',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      for (final key in const [
        'crypto_lite_add_wallet_asset_dropdown',
        'crypto_lite_add_wallet_label_dropdown',
        'crypto_lite_add_wallet_address_field',
        'crypto_lite_add_wallet_note_field',
        'crypto_lite_add_wallet_save_button',
        'crypto_lite_add_wallet_cancel_button',
      ]) {
        expect(
          find.byKey(Key(key)),
          findsOneWidget,
          reason: 'dialog MUST expose $key',
        );
      }
    });

    testWidgets('Save button label is "Save wallet"', (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Save wallet'), findsOneWidget);
      expect(find.text('Cancel'), findsOneWidget);
    });

    testWidgets('Cancel button dismisses dialog without prompt',
        (tester) async {
      final prompts = <String>[];
      await _pump(tester, onSendChatPrompt: prompts.add);
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_cancel_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_dialog')),
        findsNothing,
      );
      expect(prompts, isEmpty);
    });
  });

  
  group('D5/D6 — Save routes structured prompt to chat', () {
    testWidgets(
      'MetaMask + ETH + 0x... → "Save my MetaMask Ethereum wallet '
      'at address 0x..."',
      (tester) async {
        final prompts = <String>[];
        await _pump(tester, onSendChatPrompt: prompts.add);
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_asset_dropdown'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Ethereum').last);
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_label_dropdown'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('MetaMask').last);
        await tester.pumpAndSettle();
        
        await tester.enterText(
          find.byKey(
              const Key('crypto_lite_add_wallet_address_field')),
          '0x' + '0' * 39 + '1',
        );
        
        await tester.enterText(
          find.byKey(
              const Key('crypto_lite_add_wallet_note_field')),
          'Daily driver',
        );
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(prompts.length, 1);
        final p = prompts.single;
        expect(p, contains('MetaMask'));
        expect(p, contains('Ethereum'));
        expect(p, contains('0x' + '0' * 39 + '1'));
        expect(p, contains('Daily driver'));
        
        expect(
          find.byKey(const Key('crypto_lite_add_wallet_dialog')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'Trust Wallet + USDT TRC20 + T-address → structured prompt',
      (tester) async {
        final prompts = <String>[];
        await _pump(tester, onSendChatPrompt: prompts.add);
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_button'),
        ));
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_asset_dropdown'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('USDT TRC20').last);
        await tester.pumpAndSettle();
        
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_label_dropdown'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Trust Wallet').last);
        await tester.pumpAndSettle();
        
        const tron = 'TPL66VK2gCXNCD7EJg9pgJRfqcRazjhUZY';
        await tester.enterText(
          find.byKey(
              const Key('crypto_lite_add_wallet_address_field')),
          tron,
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        expect(prompts.length, 1);
        final p = prompts.single;
        expect(p, contains('Trust Wallet'));
        expect(p, contains('Tron TRC20'));
        expect(p, contains(tron));
      },
    );
  });

  
  group('D7 — Asset-card Add wallet opens dialog', () {
    testWidgets('XMR asset card opens dialog', (tester) async {
      await _pump(tester);
      await tester.tap(find.byKey(
        const Key('crypto_lite_asset_card_xmr_add_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_dialog')),
        findsOneWidget,
      );
    });
  });

  
  group('D8 — Show QR receive-only contract', () {
    testWidgets('wallet card shows Show QR', (tester) async {
      await _pump(
        tester,
        onShowQR: (_) {},
        savedRecords: const [
          {
            'item_id':        'w1',
            'type':           'crypto_wallet_address',
            'title':          'BTC main',
            'category_label': 'Wallet address',
            'preview':        {'network': 'Bitcoin'},
          },
        ],
      );
      expect(
        find.byKey(const Key('crypto_card_show_qr_w1')),
        findsOneWidget,
      );
    });

    testWidgets('seed phrase card hides Show QR', (tester) async {
      await _pump(
        tester,
        onShowQR: (_) {},
        savedRecords: const [
          {
            'item_id':        's1',
            'type':           'crypto_seed_phrase',
            'title':          'Ledger BTC recovery',
            'category_label': 'Seed phrase',
            'preview':        {'network': 'Bitcoin'},
          },
        ],
      );
      expect(
        find.byKey(const Key('crypto_card_show_qr_s1')),
        findsNothing,
      );
    });
  });

  
  group('D9 — Monero balance copy', () {
    testWidgets('XMR balance pins kCryptoBalanceUnavailableMonero',
        (tester) async {
      await _pump(tester);
      expect(
        tester.widget<Text>(find.byKey(
          const Key('crypto_lite_asset_card_xmr_balance'),
        )).data,
        kCryptoBalanceUnavailableMonero,
      );
      expect(
        kCryptoBalanceUnavailableMonero,
        'Balance unavailable for Monero privacy addresses.',
      );
    });

    testWidgets('non-Monero cards pin kCryptoBalanceUnavailable',
        (tester) async {
      await _pump(tester);
      for (final id in const [
        'btc', 'eth', 'usdt_trc20', 'usdt_erc20',
        'usdc_erc20', 'sol', 'bnb',
      ]) {
        expect(
          tester.widget<Text>(find.byKey(
            Key('crypto_lite_asset_card_${id}_balance'),
          )).data,
          kCryptoBalanceUnavailable,
          reason: '$id card MUST show "$kCryptoBalanceUnavailable"',
        );
      }
    });
  });

  
  group('D10 — No fake balance number', () {
    testWidgets('no synthetic balance number renders on any card',
        (tester) async {
      await _pump(tester);
      
      
      final synthetic = RegExp(
        r'(\$\s*\d|\d+\.?\d*\s*(usd|btc|eth|sol|bnb|xmr|usdt|usdc)\b)',
        caseSensitive: false,
      );
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        final body = t.data ?? '';
        expect(
          synthetic.hasMatch(body), isFalse,
          reason: 'page MUST NOT render a synthetic balance number; '
              'found in "$body"',
        );
      }
    });
  });

  
  group('D11 — Anti-claim copy guard', () {
    testWidgets('page renders no send/buy/sell/swap/create-wallet copy',
        (tester) async {
      await _pump(tester);
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        final body = (t.data ?? '').toLowerCase();
        for (final needle in const [
          'send crypto',
          'send btc',
          'send eth',
          'buy crypto',
          'sell crypto',
          'swap crypto',
          'trade crypto',
          'create wallet',
          'create a wallet',
          'wallet generation',
          'generate wallet',
          'broadcast transaction',
          'sign transaction',
        ]) {
          expect(
            body.contains(needle), isFalse,
            reason: 'page MUST NOT contain "$needle"; found in "$body"',
          );
        }
      }
    });
  });

  
  group('D12 — Hero totals row', () {
    testWidgets('hero shows "0" when no records', (tester) async {
      await _pump(tester);
      expect(
        tester.widget<Text>(find.byKey(
          const Key('crypto_lite_hero_total_wallets_value'),
        )).data,
        '0',
      );
      expect(
        tester.widget<Text>(find.byKey(
          const Key('crypto_lite_hero_total_balance_value'),
        )).data,
        kCryptoBalanceLookupNotConnected,
      );
    });

    testWidgets('hero counts wallet records only', (tester) async {
      await _pump(tester, savedRecords: const [
        {
          'item_id': 'w1', 'type': 'crypto_wallet_address',
          'title':   'BTC',
          'preview': {'network': 'Bitcoin'},
        },
        {
          'item_id': 'w2', 'type': 'crypto_wallet_address',
          'title':   'ETH',
          'preview': {'network': 'Ethereum'},
        },
        
        {
          'item_id': 's1', 'type': 'crypto_seed_phrase',
          'title':   'BTC recovery',
        },
      ]);
      expect(
        tester.widget<Text>(find.byKey(
          const Key('crypto_lite_hero_total_wallets_value'),
        )).data,
        '2',
      );
    });
  });

  
  group('D13 — Mobile layout', () {
    testWidgets('renders without overflow at 360 px', (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 2400));
      await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: Scaffold(
          body: CryptoVaultLitePage(
            savedRecords: const [],
            onSendChatPrompt: (_) {},
          ),
        ),
      ));
      await tester.pumpAndSettle();
      
      expect(
        find.byKey(const Key('crypto_lite_asset_dashboard')),
        findsOneWidget,
      );
      for (final id in const [
        'btc', 'eth', 'usdt_trc20', 'xmr',
      ]) {
        expect(
          find.byKey(Key('crypto_lite_asset_card_$id')),
          findsOneWidget,
        );
      }
    });
  });

  
  group('D14 — Closed-set catalogs', () {
    test('kCryptoAssets has exactly eight entries in canonical order',
        () {
      expect(kCryptoAssets.length, 8);
      expect(kCryptoAssets[0].id, 'btc');
      expect(kCryptoAssets[1].id, 'eth');
      expect(kCryptoAssets[2].id, 'usdt_trc20');
      expect(kCryptoAssets[3].id, 'usdt_erc20');
      expect(kCryptoAssets[4].id, 'usdc_erc20');
      expect(kCryptoAssets[5].id, 'sol');
      expect(kCryptoAssets[6].id, 'bnb');
      expect(kCryptoAssets[7].id, 'xmr');
      
      expect(
        kCryptoAssets.where((a) => a.isPrivacyChain).length,
        1,
      );
      expect(
        kCryptoAssets.firstWhere((a) => a.isPrivacyChain).id,
        'xmr',
      );
    });

    test('kCryptoWalletLabels lists the seven operator-pinned labels',
        () {
      expect(
        kCryptoWalletLabels.map((l) => l.id).toList(),
        const ['metamask', 'trust_wallet', 'ledger', 'trezor',
               'binance', 'coinbase', 'custom'],
      );
    });

    test('cryptoAssetFromNetwork tolerates ticker/name/label variants',
        () {
      expect(cryptoAssetFromNetwork('BTC')?.id,            'btc');
      expect(cryptoAssetFromNetwork('Bitcoin')?.id,        'btc');
      expect(cryptoAssetFromNetwork('Ethereum')?.id,       'eth');
      expect(cryptoAssetFromNetwork('Tron TRC20')?.id,
          'usdt_trc20');
      expect(cryptoAssetFromNetwork('USDT TRC20')?.id,
          'usdt_trc20');
      expect(cryptoAssetFromNetwork('Solana')?.id,         'sol');
      expect(cryptoAssetFromNetwork('BNB Smart Chain')?.id, 'bnb');
      expect(cryptoAssetFromNetwork('Monero')?.id,         'xmr');
      expect(cryptoAssetFromNetwork('XMR')?.id,            'xmr');
      expect(cryptoAssetFromNetwork('unknown'),            isNull);
      expect(cryptoAssetFromNetwork(''),                   isNull);
      expect(cryptoAssetFromNetwork(null),                 isNull);
    });

    test('cryptoAddressMatchesAsset basic format checks', () {
      
      expect(
        cryptoAddressMatchesAsset(
          kCryptoAssetETH, '0x' + '0' * 39 + '1'),
        isTrue,
      );
      expect(
        cryptoAddressMatchesAsset(kCryptoAssetETH, '0xabc'),
        isFalse,
      );
      
      expect(
        cryptoAddressMatchesAsset(
          kCryptoAssetBNB, '0x' + '0' * 39 + '2'),
        isTrue,
      );
      
      expect(
        cryptoAddressMatchesAsset(
          kCryptoAssetUsdtTrc20,
          'TPL66VK2gCXNCD7EJg9pgJRfqcRazjhUZY'),
        isTrue,
      );
      
      expect(
        cryptoAddressMatchesAsset(
          kCryptoAssetETH, 'TPL66VK2gCXNCD7EJg9pgJRfqcRazjhUZY'),
        isFalse,
      );
    });
  });
}
