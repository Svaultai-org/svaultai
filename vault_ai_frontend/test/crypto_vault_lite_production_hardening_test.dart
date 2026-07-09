

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';


import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';
import 'dart:io';


String _readPageSource() {
  return File(
    '${Directory.current.path}/lib/ui/crypto_vault_lite_page.dart',
  ).readAsStringSync().replaceAll('\r\n', '\n');
}


const List<String> _PROHIBITED_LITERALS = [
  "'Send crypto'",
  "'Send BTC'",
  "'Send ETH'",
  "'Sign transaction'",
  "'Broadcast transaction'",
  "'Buy crypto'",
  "'Sell crypto'",
  "'Swap crypto'",
  "'Trade crypto'",
  "'Stake crypto'",
  "'Bridge crypto'",
  "'Create wallet'",
  "'Create a wallet'",
  "'Generate wallet'",
  "'Connect MetaMask'",
  "'Verify transaction'",
  "'Import transaction history'",
  
  "\"Send crypto\"",
  "\"Sign transaction\"",
  "\"Broadcast transaction\"",
  "\"Buy crypto\"",
  "\"Sell crypto\"",
  "\"Swap crypto\"",
  "\"Trade crypto\"",
  "\"Stake crypto\"",
  "\"Create wallet\"",
  "\"Generate wallet\"",
  "\"Connect MetaMask\"",
];


void _h1OperatorPinnedCopy() {
  group('H1 — Operator-pinned copy strings', () {
    test('heading + status', () {
      
      
      expect(kCryptoVaultLiteHeading, 'Crypto Vault');
      expect(kCryptoVaultLiteStatus,  'Active');
    });

    test('balance status copy', () {
      expect(kCryptoBalanceUnavailable, 'Balance unavailable');
      expect(
        kCryptoBalanceUnavailableMonero,
        'Balance unavailable for Monero privacy addresses.',
      );
      expect(
        kCryptoBalanceLookupNotConnected,
        'Balance lookup not connected',
      );
      expect(kCryptoNoWalletSaved, 'No wallet saved');
    });

    test('transaction-note safety copy', () {
      expect(
        kCryptoTxNoteManualSafetyCopy,
        'This is a manual note. VaultAI is not sending or '
        'verifying a blockchain transaction.',
      );
    });

    test('sensitive backup warning copy', () {
      expect(
        kCryptoVaultStrongWarning,
        contains('Anyone with this phrase or key can control the '
            'wallet.'),
      );
      expect(
        kCryptoRevealWarningBodyA,
        'Anyone with this phrase or key can control the wallet.',
      );
    });

    test('add-wallet dialog title pinned', () {
      expect(kCryptoAddWalletDialogTitle, 'Add crypto wallet');
    });

    test('reveal panel CTA pinned', () {
      expect(
        kCryptoBackupRevealPanelTitle, 'Encrypted backup saved',
      );
    });

    test('copy-secret toast does not echo secret', () {
      expect(
        kCryptoCopySecretDoneToast, 'Secret copied to clipboard',
      );
    });

    test('copy-address toast does not echo address', () {
      expect(
        kCryptoCopyAddressDoneToast,
        'Address copied to clipboard',
      );
    });
  });
}


void _h2SourceLevelAntiClaim() {
  group('H2 — Source-level anti-claim guard', () {
    test('no prohibited string literal appears in page source',
        () {
      final src = _readPageSource();
      for (final literal in _PROHIBITED_LITERALS) {
        expect(
          src.contains(literal), isFalse,
          reason: 'crypto_vault_lite_page.dart contains the '
              'prohibited literal $literal',
        );
      }
    });
  });
}


void _h3AssetWalletCatalogs() {
  group('H3 — Asset + wallet-label catalogs', () {
    test('asset ids match backend canonical order', () {
      expect(
        kCryptoAssets.map((a) => a.id).toList(),
        const ['btc', 'eth',
               'usdt_trc20', 'usdt_erc20', 'usdc_erc20',
               'sol', 'bnb', 'xmr'],
      );
    });

    test('asset display names match backend network labels', () {
      
      const expected = {
        'btc':        'Bitcoin',
        'eth':        'Ethereum',
        'usdt_trc20': 'Tron TRC20',
        'usdt_erc20': 'Ethereum ERC20',
        'usdc_erc20': 'Ethereum ERC20',
        'sol':        'Solana',
        'bnb':        'BNB Smart Chain',
        'xmr':        'Monero',
      };
      for (final a in kCryptoAssets) {
        expect(a.networkLabel, expected[a.id],
            reason: 'asset ${a.id} network label mismatch with '
                'backend NETWORK_LABEL_FOR_ASSET');
      }
    });

    test('XMR is the only privacy chain', () {
      expect(
        kCryptoAssets.where((a) => a.isPrivacyChain).length, 1,
      );
      expect(
        kCryptoAssets.firstWhere((a) => a.isPrivacyChain).id,
        'xmr',
      );
    });

    test('wallet labels match backend canonical order', () {
      expect(
        kCryptoWalletLabels.map((l) => l.id).toList(),
        const ['metamask', 'trust_wallet', 'ledger', 'trezor',
               'binance', 'coinbase', 'custom'],
      );
    });
  });
}


void _h4NetworkAliasTolerance() {
  group('H4 — Network alias tolerance', () {
    test('canonical mappings', () {
      const cases = {
        
        'BTC':              'btc',
        'btc':              'btc',
        'ETH':              'eth',
        'SOL':              'sol',
        'BNB':              'bnb',
        'XMR':              'xmr',
        
        'Bitcoin':          'btc',
        'bitcoin':          'btc',
        'Ethereum':         'eth',
        'ethereum':         'eth',
        'Tron TRC20':       'usdt_trc20',
        'USDT TRC20':       'usdt_trc20',
        'usdt trc20':       'usdt_trc20',
        'USDT ERC20':       'usdt_erc20',
        'usdt erc20':       'usdt_erc20',
        'usdc erc20':       'usdc_erc20',
        'Solana':           'sol',
        'solana':           'sol',
        'BNB Smart Chain':  'bnb',
        'bnb smart chain':  'bnb',
        
        'bsc':              'bnb',
        'Monero':           'xmr',
        'monero':           'xmr',
      };
      cases.forEach((input, expectedId) {
        expect(
          cryptoAssetFromNetwork(input)?.id, expectedId,
          reason: 'cryptoAssetFromNetwork($input) should '
              'resolve to $expectedId',
        );
      });
    });

    test('rejects unknown inputs', () {
      expect(cryptoAssetFromNetwork(null), isNull);
      expect(cryptoAssetFromNetwork(''),   isNull);
      expect(cryptoAssetFromNetwork('garbage-network'), isNull);
    });
  });
}


void _h5AddressValidator() {
  group('H5 — Address validator', () {
    test('ETH well-formed accepted; mismatched rejected', () {
      expect(
        cryptoAddressMatchesAsset(
          kCryptoAssetETH,
          '0x' + '0' * 39 + '1',
        ),
        isTrue,
      );
      expect(
        cryptoAddressMatchesAsset(kCryptoAssetETH, '0xabc'),
        isFalse,
      );
    });

    test('TRC20 well-formed accepted; ETH-shape rejected', () {
      expect(
        cryptoAddressMatchesAsset(
          kCryptoAssetUsdtTrc20,
          'TPL66VK2gCXNCD7EJg9pgJRfqcRazjhUZY',
        ),
        isTrue,
      );
      expect(
        cryptoAddressMatchesAsset(
          kCryptoAssetUsdtTrc20, '0x' + '0' * 40),
        isFalse,
      );
    });

    test('empty address is never matched', () {
      for (final a in kCryptoAssets) {
        expect(
          cryptoAddressMatchesAsset(a, ''), isFalse,
          reason: 'empty address must NEVER match ${a.id}',
        );
      }
    });
  });
}


Future<void> _pumpMobile(WidgetTester tester, {
  List<Map<String, dynamic>> savedRecords = const [],
  Future<Map<String, dynamic>> Function(
    Map<String, dynamic> record,
  )? onLoadDetail,
  Future<Map<String, dynamic>> Function(
    Map<String, dynamic> record, String pin,
  )? onReveal,
}) async {
  await tester.binding.setSurfaceSize(const Size(360, 800));
  await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: CryptoVaultLitePage(
        savedRecords: savedRecords,
        onDirectSaveWalletProfile:     (_) async {},
        onDirectSaveSensitiveBackup:   (_) async {},
        onDirectSaveCryptoNote:        (_) async {},
        onLoadCryptoRecordDetail:      onLoadDetail,
        onUpdateCryptoWalletProfile:   (rec, edits) async {},
        onUpdateCryptoBackupMetadata:  (rec, edits) async {},
        onDeleteCryptoRecord:          (rec) async {},
        onRevealCryptoSensitiveBackup: onReveal,
      ),
    ),
  ));
  await tester.pumpAndSettle();
}


Map<String, dynamic> _walletRecord() => {
  'item_id':        'w1',
  'type':           'crypto_wallet_address',
  'title':          'MetaMask ETH wallet',
  'category_label': 'Crypto wallet',
  'preview': {
    'wallet_address_mask': '0x0000…0001',
    'network':             'Ethereum',
  },
};


Map<String, dynamic> _walletDetail() => {
  'service':   'MetaMask ETH wallet',
  'item_type': 'crypto_wallet_address',
  'fields': {
    'wallet_address': '0x0000000000000000000000000000000000000001',
    'network':        'Ethereum',
    'wallet_label':   'MetaMask',
    'asset':          'ETH',
    'balance_status': 'lookup_not_connected',
  },
};


Map<String, dynamic> _backupRecord() => {
  'item_id':        's1',
  'type':           'crypto_recovery_phrase',
  'title':          'Ledger BTC recovery',
  'category_label': 'Recovery phrase',
  'preview': {
    'recovery_phrase_mask': '•••••• hidden',
    'network':              'Bitcoin',
  },
};


Map<String, dynamic> _backupDetail() => {
  'service':   'Ledger BTC recovery',
  'item_type': 'crypto_recovery_phrase',
  'fields': {
    'recovery_phrase': 'abandon ' * 11 + 'about',
    'network':         'Bitcoin',
    'wallet_label':    'Ledger',
    'asset':           'BTC',
    'secret_type':     'recovery_phrase',
  },
};


void _h7MobileSweep() {
  group('H7 — Mobile 360 px sweep', () {
    testWidgets('dashboard renders without overflow at 360 px',
        (tester) async {
      await _pumpMobile(tester);
      expect(
        find.byKey(const Key('crypto_lite_asset_dashboard')),
        findsOneWidget,
      );
    });

    testWidgets('Add wallet dialog opens at 360 px', (tester) async {
      await _pumpMobile(tester);
      await tester.ensureVisible(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_lite_add_wallet_dialog')),
        findsOneWidget,
      );
    });

    testWidgets('Add general note dialog opens at 360 px',
        (tester) async {
      await _pumpMobile(tester);
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

    testWidgets('Add transaction note dialog opens at 360 px',
        (tester) async {
      await _pumpMobile(tester);
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

    testWidgets('Wallet detail dialog at 360 px', (tester) async {
      await _pumpMobile(
        tester,
        savedRecords: [_walletRecord()],
        onLoadDetail: (rec) async => _walletDetail(),
      );
      await tester.ensureVisible(
        find.byKey(const Key('crypto_card_view_w1')),
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_w1')));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_detail_dialog')),
        findsOneWidget,
      );
    });

    testWidgets('Delete wallet confirm at 360 px', (tester) async {
      await _pumpMobile(
        tester,
        savedRecords: [_walletRecord()],
        onLoadDetail: (rec) async => _walletDetail(),
      );
      await tester.ensureVisible(
        find.byKey(const Key('crypto_card_view_w1')),
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_w1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(
        const Key('crypto_wallet_detail_delete_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
          const Key('crypto_delete_wallet_confirm_dialog')),
        findsOneWidget,
      );
    });

    testWidgets('Sensitive backup detail at 360 px', (tester) async {
      await _pumpMobile(
        tester,
        savedRecords: [_backupRecord()],
        onLoadDetail: (rec) async => _backupDetail(),
        onReveal: (rec, pin) async => {
          'secretType':  'recovery_phrase',
          'secretValue': 'abandon ' * 11 + 'about',
        },
      );
      await tester.ensureVisible(
        find.byKey(const Key('crypto_card_view_s1')),
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_backup_detail_dialog')),
        findsOneWidget,
      );
    });

    testWidgets('Reveal warning at 360 px', (tester) async {
      await _pumpMobile(
        tester,
        savedRecords: [_backupRecord()],
        onLoadDetail: (rec) async => _backupDetail(),
        onReveal: (rec, pin) async => {
          'secretType':  'recovery_phrase',
          'secretValue': 'x',
        },
      );
      await tester.ensureVisible(
        find.byKey(const Key('crypto_card_view_s1')),
      );
      await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(
        const Key('crypto_backup_detail_reveal_button'),
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(
          'crypto_backup_reveal_warning_dialog')),
        findsOneWidget,
      );
    });
  });
}


void _h8ReceiveQRGate() {
  group('H8 — Receive-QR page-side gate', () {
    testWidgets(
      'wallet-address card shows Show QR; sensitive-backup card '
      'does NOT',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(900, 1200));
        await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoVaultLitePage(
              savedRecords: [_walletRecord(), _backupRecord()],
              onShowQR: (_) {},
            ),
          ),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('crypto_card_show_qr_w1')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('crypto_card_show_qr_s1')),
          findsNothing,
        );
      },
    );

    testWidgets(
      'transaction-note card does NOT show Show QR',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(900, 1200));
        await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoVaultLitePage(
              savedRecords: const [
                {
                  'item_id': 'n1',
                  'type':    'crypto_transaction_note',
                  'title':   'ETH withdrawal',
                  'category_label': 'Transaction note',
                  'preview': {
                    'transaction_note_mask': 'manual note',
                    'network':               'Ethereum',
                  },
                },
              ],
              onShowQR: (_) {},
            ),
          ),
        ));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key('crypto_card_show_qr_n1')),
          findsNothing,
        );
      },
    );
  });
}


void _h9DialogTreeAntiClaim() {
  group('H9 — Dialog-tree anti-claim guard', () {
    const _prohibitedNeedles = [
      'send crypto',
      'sign transaction',
      'broadcast transaction',
      'buy crypto',
      'sell crypto',
      'swap crypto',
      'trade crypto',
      'stake crypto',
      'create wallet',
      'create a wallet',
      'wallet generation',
      'generate wallet',
      'connect metamask',
      'verify transaction',
      'import transaction history',
      'bridge crypto',
      'withdraw crypto',
    ];

    Future<void> _scan(
      WidgetTester tester, {
      required Key dialogKey,
    }) async {
      for (final tw in tester.widgetList<Text>(
        find.descendant(
          of: find.byKey(dialogKey),
          matching: find.byType(Text),
        ),
      )) {
        final body = (tw.data ?? '').toLowerCase();
        for (final needle in _prohibitedNeedles) {
          expect(body.contains(needle), isFalse,
              reason: 'dialog $dialogKey must NOT contain '
                  '"$needle"; found in "$body"');
        }
      }
    }

    testWidgets('add wallet dialog tree is clean', (tester) async {
      await _pumpMobile(tester);
      await tester.ensureVisible(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_wallet_button'),
      ));
      await tester.pumpAndSettle();
      await _scan(tester,
          dialogKey: const Key('crypto_lite_add_wallet_dialog'));
    });

    testWidgets('add general note dialog tree is clean',
        (tester) async {
      await _pumpMobile(tester);
      await tester.ensureVisible(find.byKey(
        const Key('crypto_lite_add_crypto_note_button'),
      ));
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_crypto_note_button'),
      ));
      await tester.pumpAndSettle();
      await _scan(tester,
          dialogKey: const Key(
              'crypto_lite_add_general_note_dialog'));
    });

    testWidgets('add transaction note dialog tree is clean',
        (tester) async {
      await _pumpMobile(tester);
      await tester.ensureVisible(find.byKey(
        const Key('crypto_lite_add_transaction_note_button'),
      ));
      await tester.tap(find.byKey(
        const Key('crypto_lite_add_transaction_note_button'),
      ));
      await tester.pumpAndSettle();
      await _scan(tester,
          dialogKey: const Key('crypto_lite_add_tx_note_dialog'));
    });
  });
}


void _h10ErrorEnvelopesSafe() {
  group('H10 — Error envelopes never echo user values', () {
    testWidgets(
      'Add wallet save error inline panel does NOT echo address',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(900, 2400));
        const eth = '0x0000000000000000000000000000000000000001';
        await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoVaultLitePage(
              savedRecords: const [],
              onDirectSaveWalletProfile: (_) async {
                throw Exception(
                    'Save crypto wallet failed: 500');
              },
            ),
          ),
        ));
        await tester.pumpAndSettle();
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
          find.byKey(const Key(
            'crypto_lite_add_wallet_address_field')),
          eth,
        );
        await tester.tap(find.byKey(
          const Key('crypto_lite_add_wallet_save_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(
            const Key('crypto_lite_add_wallet_save_error')),
          findsOneWidget,
        );
        
        
        for (final tw in tester.widgetList<Text>(
          find.descendant(
            of: find.byKey(
              const Key('crypto_lite_add_wallet_save_error')),
            matching: find.byType(Text),
          ),
        )) {
          expect((tw.data ?? '').contains(eth), isFalse,
              reason: 'save-error panel must NEVER echo the '
                  'address');
        }
      },
    );

    testWidgets(
      'Reveal wrong-PIN inline error does NOT echo PIN or secret',
      (tester) async {
        const _RECOVERY = 'abandon abandon abandon abandon abandon '
            'abandon abandon abandon abandon abandon abandon about';
        await tester.binding.setSurfaceSize(const Size(900, 2400));
        await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoVaultLitePage(
              savedRecords: [_backupRecord()],
              onLoadCryptoRecordDetail: (rec) async =>
                  _backupDetail(),
              onRevealCryptoSensitiveBackup: (rec, pin) async {
                throw Exception(
                  'Reveal sensitive backup failed: 401',
                );
              },
            ),
          ),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('crypto_card_view_s1')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_backup_detail_reveal_button'),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(
          const Key('crypto_backup_reveal_warning_continue'),
        ));
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(
            const Key('crypto_backup_reveal_pin_field')),
          '4242',
        );
        await tester.tap(find.byKey(
          const Key('crypto_backup_reveal_pin_submit_button'),
        ));
        await tester.pumpAndSettle();
        
        expect(
          find.byKey(
            const Key('crypto_backup_reveal_pin_error_text')),
          findsOneWidget,
        );
        
        for (final tw in tester.widgetList<Text>(
          find.descendant(
            of: find.byKey(
              const Key(
                'crypto_backup_reveal_pin_error_text')),
            matching: find.byType(Text),
          ),
        )) {
          final body = tw.data ?? '';
          expect(body.contains('4242'), isFalse,
              reason: 'PIN error must NEVER echo the typed PIN');
          expect(body.contains(_RECOVERY), isFalse,
              reason: 'PIN error must NEVER expose the secret');
        }
      },
    );
  });
}


void _h11AssetBalanceCopyHonest() {
  group('H11 — Asset balance copy honest', () {
    testWidgets(
      'every asset card pins the honest balance copy + XMR pins '
      'privacy message',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(900, 2400));
        await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: CryptoVaultLitePage(
              savedRecords: const [],
              onDirectSaveWalletProfile: (_) async {},
            ),
          ),
        ));
        await tester.pumpAndSettle();
        
        final xmrBalanceText = tester.widget<Text>(find.byKey(
          const Key('crypto_lite_asset_card_xmr_balance'),
        ));
        expect(
          xmrBalanceText.data, kCryptoBalanceUnavailableMonero,
        );
        
        for (final id in const [
          'btc', 'eth', 'usdt_trc20', 'usdt_erc20', 'usdc_erc20',
          'sol', 'bnb',
        ]) {
          final t = tester.widget<Text>(find.byKey(
            Key('crypto_lite_asset_card_${id}_balance'),
          ));
          expect(
            t.data, kCryptoBalanceUnavailable,
            reason: '$id card must pin "Balance unavailable"',
          );
        }
      },
    );
  });
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  _h1OperatorPinnedCopy();
  _h2SourceLevelAntiClaim();
  _h3AssetWalletCatalogs();
  _h4NetworkAliasTolerance();
  _h5AddressValidator();
  _h7MobileSweep();
  _h8ReceiveQRGate();
  _h9DialogTreeAntiClaim();
  _h10ErrorEnvelopesSafe();
  _h11AssetBalanceCopyHonest();
}
