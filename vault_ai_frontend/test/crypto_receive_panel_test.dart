

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qr_flutter/qr_flutter.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/crypto_receive_panel.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_lite_page.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


const _usdtFull = 'TQx2P5kqY7Lr1Z9w8VnGdQfH3sM6Ev1RnY';
const _btcFull  = 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh';
const _xmrFull  =
    '8AaWDoNomZ5GtP6Wn34CpEh4i7p9oVUaeRkTr2VtcqK'
    'L5d9bF8U6Q4xz1vXmAZbWqYTKpcRfPjN3eGsHmDnLs';


Future<void> _pumpPanel(
  WidgetTester tester, {
  required String address,
  String title = 'USDT TRC20 wallet',
  String? network = 'USDT TRC20',
  void Function(String)? onCopy,
  VoidCallback? onClose,
}) async {
  await tester.binding.setSurfaceSize(const Size(720, 1024));
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: SingleChildScrollView(
          child: ReceivePanel(
            title:   title,
            address: address,
            network: network,
            onCopy:  onCopy,
            onClose: onClose,
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


List<Map<String, dynamic>> _seedRecords() => [
      {
        'item_id':        'r1',
        'type':           'crypto_wallet_address',
        'title':          'USDT TRC20 wallet',
        'category_label': 'Crypto wallet',
        'preview': {
          'wallet_address_mask': 'TQx2P5…1RnY',
          'network':              'USDT TRC20',
        },
      },
      {
        'item_id':        'r2',
        'type':           'crypto_seed_phrase',
        'title':          'Bitcoin seed phrase',
        'category_label': 'Seed phrase',
        'preview': {
          'seed_phrase_mask': '•••••• hidden',
        },
      },
      {
        'item_id':        'r3',
        'type':           'crypto_private_key',
        'title':          'ETH private key',
        'category_label': 'Private key',
        'preview': {
          'private_key_mask': '•••••• hidden',
        },
      },
      {
        'item_id':        'r4',
        'type':           'crypto_recovery_phrase',
        'title':          'Crypto recovery phrase',
        'category_label': 'Recovery phrase',
        'preview': {
          'recovery_phrase_mask': '•••••• hidden',
        },
      },
      {
        'item_id':        'r5',
        'type':           'crypto_note',
        'title':          'Avg buy notes',
        'category_label': 'Crypto note',
        'preview': {
          'crypto_note_mask': '•••••• hidden',
        },
      },
    ];


Future<void> _pumpPage(
  WidgetTester tester, {
  void Function(Map<String, dynamic>)? onShowQR,
}) async {
  
  
  await tester.binding.setSurfaceSize(const Size(900, 2400));
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        body: CryptoVaultLitePage(
          savedRecords: _seedRecords(),
          onShowQR: onShowQR,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('ReceivePanel — content rendering', () {
    testWidgets('renders title, network chip, masked preview, full address, '
        'QR, copy button, warning', (tester) async {
      await _pumpPanel(tester, address: _usdtFull);
      expect(
        find.byKey(const Key('crypto_receive_panel')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('crypto_receive_title')),
        findsOneWidget,
      );
      expect(find.text('USDT TRC20 wallet'), findsOneWidget);
      
      expect(
        find.byKey(const Key('crypto_receive_network_chip')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('crypto_receive_masked')),
        findsOneWidget,
      );
      final maskedWidget = tester.widget<Text>(
        find.byKey(const Key('crypto_receive_masked')),
      );
      expect(maskedWidget.data, 'TQx2P5…1RnY');
      
      expect(
        find.byKey(const Key('crypto_receive_full_address')),
        findsOneWidget,
      );
      final fullWidget = tester.widget<SelectableText>(
        find.byKey(const Key('crypto_receive_full_address')),
      );
      expect(fullWidget.data, _usdtFull);
      
      expect(
        find.byKey(const Key('crypto_receive_qr')),
        findsOneWidget,
      );
      expect(find.byType(QrImageView), findsOneWidget);
      
      expect(
        find.byKey(const Key('crypto_receive_warning')),
        findsOneWidget,
      );
      final warning = tester.widget<Text>(
        find.byKey(const Key('crypto_receive_warning')),
      );
      expect(warning.data, contains('Only send assets'));
      expect(warning.data, contains('permanently lose funds'));
      
      expect(
        find.byKey(const Key('crypto_receive_only_hint')),
        findsOneWidget,
      );
    });

    testWidgets('QR encodes the raw saved address verbatim',
        (tester) async {
      await _pumpPanel(tester, address: _btcFull, network: 'BTC');
      
      
      final fullWidget = tester.widget<SelectableText>(
        find.byKey(const Key('crypto_receive_full_address')),
      );
      expect(fullWidget.data, _btcFull);
      
      expect(find.byType(QrImageView), findsOneWidget);
    });

    test('panel source passes raw address to QrImageView.data', () {
      final src = File('lib/ui/crypto_receive_panel.dart')
          .readAsStringSync();
      
      
      expect(
        src,
        contains('data: address,'),
        reason:
            'panel must pass the raw saved address to '
            'QrImageView.data with no transformation',
      );
      
      expect(src.contains("'bitcoin:'"), isFalse);
      expect(src.contains("'ethereum:'"), isFalse);
      expect(src.contains("'solana:'"), isFalse);
      
      expect(src.contains("?amount="), isFalse);
      expect(src.contains("&amount="), isFalse);
    });

    testWidgets('Copy button fires onCopy with the exact saved address',
        (tester) async {
      String? captured;
      await _pumpPanel(
        tester,
        address: _btcFull,
        network: 'BTC',
        onCopy: (a) => captured = a,
      );
      await tester.tap(find.byKey(const Key('crypto_receive_copy_button')));
      await tester.pumpAndSettle();
      expect(captured, _btcFull);
    });

    testWidgets('Close button fires onClose', (tester) async {
      var closed = false;
      await _pumpPanel(
        tester,
        address: _btcFull,
        onClose: () => closed = true,
      );
      await tester.tap(find.byKey(const Key('crypto_receive_close')));
      await tester.pumpAndSettle();
      expect(closed, isTrue);
    });

    testWidgets('Mobile width renders without overflow', (tester) async {
      await tester.binding.setSurfaceSize(const Size(360, 740));
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: _testL10nDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: SingleChildScrollView(
              child: ReceivePanel(
                title:   'BTC wallet',
                address: _btcFull,
                network: 'BTC',
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('mask helper produces first6…last4', (tester) async {
      expect(maskWalletAddressForReceive(''), '');
      expect(maskWalletAddressForReceive('abc'), 'abc');  
      expect(
        maskWalletAddressForReceive(_btcFull),
        '${_btcFull.substring(0, 6)}…${_btcFull.substring(_btcFull.length - 4)}',
      );
      expect(
        maskWalletAddressForReceive(_xmrFull),
        '${_xmrFull.substring(0, 6)}…${_xmrFull.substring(_xmrFull.length - 4)}',
      );
    });
  });

  group('ReceivePanel — anti-claim guardrails', () {
    
    
    const forbiddenActiveClaims = <String>[
      
      'send crypto', 'send transaction', 'send funds',
      'sign transaction', 'broadcast transaction',
      'submit transaction',
      
      'create wallet', 'new wallet', 'generate wallet',
      
      'buy crypto', 'sell crypto', 'swap crypto',
      'trade crypto', 'exchange crypto',
      
      'guaranteed', 'profit', 'high return', 'investment return',
      'make money', 'to the moon',
    ];

    testWidgets('panel renders no forbidden ACTIVE claims',
        (tester) async {
      await _pumpPanel(tester, address: _btcFull, network: 'BTC');
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        final body = (t.data ?? '').toLowerCase();
        for (final needle in forbiddenActiveClaims) {
          expect(
            body.contains(needle), isFalse,
            reason:
                'Receive panel must NEVER claim "$needle"; '
                'found in: "$body"',
          );
        }
      }
    });

    test('module source carries no signing / wallet-gen / RPC libraries', () {
      final src = File('lib/ui/crypto_receive_panel.dart')
          .readAsStringSync();
      const forbidden = <String>[
        "import 'package:web3",
        "import 'package:bitcoin",
        "import 'package:eth_",
        "import 'package:solana",
        "import 'package:ethers",
        "import 'package:walletconnect",
        
        "'Send'", "'Sign'", "'Broadcast'", "'Submit'",
        "'Create wallet'", "'New wallet'",
        "'Buy'", "'Sell'", "'Swap'", "'Trade'", "'Exchange'",
      ];
      for (final needle in forbidden) {
        expect(
          src.contains(needle), isFalse,
          reason: 'crypto_receive_panel.dart must NEVER carry "$needle"',
        );
      }
    });
  });

  group('Show QR action on crypto cards', () {
    testWidgets('Show QR appears on crypto_wallet_address card only',
        (tester) async {
      await _pumpPage(tester, onShowQR: (_) {});
      
      expect(
        find.byKey(const Key('crypto_card_show_qr_r1')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('crypto_card_show_qr_r2')),
        findsNothing,
      );
      
      expect(
        find.byKey(const Key('crypto_card_show_qr_r3')),
        findsNothing,
      );
      
      expect(
        find.byKey(const Key('crypto_card_show_qr_r4')),
        findsNothing,
      );
      
      expect(
        find.byKey(const Key('crypto_card_show_qr_r5')),
        findsNothing,
      );
    });

    testWidgets('Show QR HIDDEN when callback not supplied',
        (tester) async {
      await _pumpPage(tester);
      
      
      expect(
        find.byKey(const Key('crypto_card_show_qr_r1')),
        findsNothing,
      );
    });

    testWidgets('Show QR tap fires onShowQR with the wallet record',
        (tester) async {
      Map<String, dynamic>? tapped;
      await _pumpPage(
        tester,
        onShowQR: (r) => tapped = r,
      );
      await tester.tap(find.byKey(const Key('crypto_card_show_qr_r1')));
      await tester.pumpAndSettle();
      expect(tapped, isNotNull);
      expect(tapped!['item_id'], 'r1');
      expect(tapped!['type'],    'crypto_wallet_address');
    });

    testWidgets('full wallet address NEVER renders in the list view',
        (tester) async {
      await _pumpPage(tester, onShowQR: (_) {});
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        final body = t.data ?? '';
        expect(
          body.contains(_usdtFull), isFalse,
          reason: 'List view must never render the full USDT address',
        );
        expect(
          body.contains(_btcFull), isFalse,
          reason: 'List view must never render the full BTC address',
        );
      }
    });
  });

  group('showReceivePanelDialog — modal flow', () {
    testWidgets('dialog opens and renders the panel', (tester) async {
      await tester.binding.setSurfaceSize(const Size(800, 1100));
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: _testL10nDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: Builder(
              builder: (ctx) => Center(
                child: ElevatedButton(
                  key: const Key('open_receive'),
                  onPressed: () => showReceivePanelDialog(
                    ctx,
                    title:   'BTC wallet',
                    address: _btcFull,
                    network: 'BTC',
                  ),
                  child: const Text('Open'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.byKey(const Key('open_receive')));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_receive_dialog')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_receive_panel')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_receive_qr')),
        findsOneWidget,
      );
    });
  });

  group('main.dart source guardrails', () {
    test('main.dart imports the crypto_receive_panel module', () {
      
      
      final src = File('lib/main.dart').readAsStringSync();
      expect(
        src,
        contains("import 'ui/crypto_receive_panel.dart'"),
        reason: 'main.dart must import the receive panel module',
      );
    });

    test('main.dart carries no send / wallet-gen UI strings', () {
      final src = File('lib/main.dart').readAsStringSync();
      
      
      const forbidden = <String>[
        "'Send crypto'", "'Sign transaction'", "'Broadcast'",
        "'Create wallet'", "'New wallet'", "'Generate wallet'",
        "'Buy'", "'Sell'", "'Swap'", "'Trade'", "'Exchange'",
      ];
      for (final needle in forbidden) {
        expect(
          src.contains(needle), isFalse,
          reason: 'main.dart must NEVER carry "$needle"',
        );
      }
    });
  });
}
