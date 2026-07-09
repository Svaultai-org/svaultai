
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/crypto_vault_chat_control.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_chat_cards.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


Widget _wrap(Widget child, {Size size = const Size(1200, 2400)}) {
  return MaterialApp(
    localizationsDelegates: _testL10nDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: SizedBox(
        width: size.width,
        height: size.height,
        child: SingleChildScrollView(child: child),
      ),
    ),
  );
}


CryptoVaultChatCard _card(Map<String, dynamic> raw) {
  return CryptoVaultChatCard.fromJson(raw);
}


void main() {


  group('CryptoVaultChatCard.data + defensive parsing', () {

    test('data field is preserved by fromJson', () {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [{'asset': 'ETH', 'label': 'ETH'}],
        },
      });
      expect(c.data, isNotNull);
      expect(c.data!['available'], isTrue);
    });

    test('forbidden top-level keys stripped from data', () {
      final c = _card({
        'cardType': 'crypto_vault_send_draft_card',
        'data': {
          'privateKey':    'leak',
          'private_key':   'leak',
          'seedPhrase':    'leak',
          'signed_tx_hex': 'leak',
          'authToken':     'leak',
          'asset':         'safe',
        },
      });
      expect(c.data!['asset'], 'safe');
      for (final k in [
        'privateKey', 'private_key', 'seedPhrase',
        'signed_tx_hex', 'authToken',
      ]) {
        expect(c.data!.containsKey(k), isFalse,
            reason: 'forbidden key $k leaked');
      }
    });

    test('forbidden nested keys stripped', () {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'assets': [
            {'asset': 'XMR', 'polyseed': 'leak',
             'private_view_key': 'leak'},
          ],
        },
      });
      final assets = c.data!['assets'] as List;
      final xmr = (assets.first as Map).cast<String, dynamic>();
      expect(xmr['asset'], 'XMR');
      expect(xmr.containsKey('polyseed'), isFalse);
      expect(xmr.containsKey('private_view_key'), isFalse);
    });

    test('canBroadcast is always false at parser layer', () {
      final c = _card({
        'cardType': 'crypto_vault_send_draft_card',

        'canBroadcast': true,
      });

      expect(c.canBroadcast, isFalse);
    });
  });



  group('Crypto Vault overview (show_vault) card', () {

    testWidgets('populated show_vault renders asset rows',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            {
              'asset': 'ETH', 'label': 'ETH', 'network': 'ethereum',
              'balanceStatus': 'pending_live_fetch',
              'receiveReady': true, 'sendEnabled': true,
            },
            {
              'asset': 'XMR', 'label': 'XMR', 'network': 'monero',
              'balanceStatus': 'scanner_gated',
              'reason': 'scanner_requires_desktop',
              'receiveReady': false, 'sendEnabled': false,
            },
          ],
          'unavailableCount': 1,
          'xmrScannerStatus': 'disabled',
          'xmrReason':        'scanner_not_enabled',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_show_vault_row_ETH')),
          findsOneWidget);
      expect(find.byKey(
          const Key('crypto_vault_chat_show_vault_row_XMR')),
          findsOneWidget);


      expect(find.byKey(
          const Key('crypto_vault_chat_show_vault_xmr_scanner')),
          findsOneWidget);
    });

    testWidgets('unpopulated show_vault falls back to summary copy',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.textContaining('Non-custodial'),
          findsOneWidget);
    });
  });



  group('Balance card', () {

    testWidgets('ETH real zero renders "0 ETH" only when '
                'balanceStatus=available',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'available',
          'displayBalance': '0 ETH',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_balance_display_value')),
          findsOneWidget);
      expect(find.text('0 ETH'), findsOneWidget);
    });

    for (final status in [
      'pending_live_fetch',
      'scanner_gated',
      'requires_desktop',
      'unavailable',
    ]) {
      testWidgets(
          '$status status does NOT render a balance number',
          (tester) async {
        final c = _card({
          'cardType': 'crypto_vault_balance_card',
          'asset':    'ETH',
          'data': {
            'schema':        'crypto_balance_data_v1',
            'available':     true,
            'asset':         'ETH',
            'label':         'ETH',
            'balanceStatus': status,
          },
        });
        await tester.pumpWidget(_wrap(
          CryptoVaultChatCardView(card: c),
        ));
        await tester.pump();
        expect(find.byKey(
            const Key('crypto_vault_chat_balance_display_value')),
            findsNothing);
      });
    }

    testWidgets('XMR balance card shows scanner_gated copy',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'XMR',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'XMR',
          'label':          'XMR',
          'balanceStatus':  'scanner_gated',
          'reason':         'scanner_requires_desktop',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();


      expect(find.text('0 XMR'), findsNothing);
      expect(find.byKey(
          const Key('crypto_vault_chat_balance_gated')),
          findsOneWidget);
    });

    testWidgets(
        'balance card ignores displayBalance when status != available',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',

          'displayBalance': '999.9999 ETH',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.text('999.9999 ETH'), findsNothing);
    });
  });



  group('Receive card', () {

    testWidgets('receive card renders public address',
        (tester) async {
      const addr = '0xabcdef0123456789abcdef0123456789abcdef01';
      final c = _card({
        'cardType': 'crypto_vault_receive_card',
        'asset':    'ETH',
        'data': {
          'schema':        'crypto_receive_data_v1',
          'available':     true,
          'asset':         'ETH',
          'label':         'ETH',
          'network':       'ethereum',
          'receiveReady':  true,
          'publicAddress': addr,
          'walletLabel':   'main',
          'warning':       'Only send ETH on ethereum to this address.',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_receive_public_address')),
          findsOneWidget);
      expect(find.byKey(
          const Key('crypto_vault_chat_receive_warning')),
          findsOneWidget);
      expect(find.textContaining('0xabcdef01234567'),
          findsOneWidget);
    });

    testWidgets('receive card without wallet shows no-wallet copy',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_receive_card',
        'asset':    'ETH',
        'data': {
          'schema':        'crypto_receive_data_v1',
          'available':     true,
          'asset':         'ETH',
          'label':         'ETH',
          'receiveReady':  false,
          'reason':        'create_wallet_first',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_receive_no_wallet')),
          findsOneWidget);
    });

    testWidgets('receive QR card shows public address + QR ready',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_receive_qr_card',
        'asset':    'ETH',
        'data': {
          'schema':        'crypto_receive_data_v1',
          'available':     true,
          'asset':         'ETH',
          'label':         'ETH',
          'receiveReady':  true,
          'publicAddress': '0xdeadbeef00',
          'qrPayload':     '0xdeadbeef00',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_qr_payload')),
          findsOneWidget);
      expect(find.byKey(
          const Key('crypto_vault_chat_qr_public_address')),
          findsOneWidget);
    });
  });



  group('Scanner status card', () {

    testWidgets('scanner requires_desktop reason renders desktop copy',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_scanner_status_card',
        'data': {
          'schema':          'crypto_scanner_status_data_v1',
          'available':       true,
          'asset':           'XMR',
          'scannerStatus':   'requires_desktop',
          'reason':          'scanner_requires_desktop',
          'canShowBalance':  false,
          'canShowActivity': false,
          'canSend':         false,
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_scanner_headline')),
          findsOneWidget);
      expect(find.textContaining('desktop'),
          findsAtLeastNWidgets(1));


      expect(find.byKey(
          const Key('crypto_vault_chat_scanner_no_send_pill')),
          findsOneWidget);
    });

    testWidgets('scanner not_enabled renders scanner-not-enabled copy',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_scanner_status_card',
        'data': {
          'schema':          'crypto_scanner_status_data_v1',
          'available':       true,
          'asset':           'XMR',
          'scannerStatus':   'not_enabled',
          'reason':          'scanner_not_enabled',
          'canShowBalance':  false,
          'canShowActivity': false,
          'canSend':         false,
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_scanner_headline')),
          findsOneWidget);
      expect(find.textContaining('Scanner not enabled'),
          findsAtLeastNWidgets(1));
    });
  });



  group('Activity card', () {

    testWidgets('activity xmr scanner_gated renders gated copy',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_activity_card',
        'asset':    'XMR',
        'data': {
          'schema':         'crypto_activity_data_v1',
          'available':      true,
          'asset':          'XMR',
          'activityStatus': 'scanner_gated',
          'reason':         'scanner_requires_desktop',
          'entries':        [],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_activity_scanner_gated')),
          findsOneWidget);
    });

    testWidgets('activity pending_live_fetch renders loading',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_activity_card',
        'data': {
          'schema':         'crypto_activity_data_v1',
          'available':      true,
          'activityStatus': 'pending_live_fetch',
          'entries':        [],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_activity_loading')),
          findsOneWidget);
    });
  });



  group('Send draft card', () {

    testWidgets('send draft renders safety pills',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_send_draft_card',
        'asset':     'ETH',
        'amount':    '1.0',
        'recipient': '0xabc',
        'data': {
          'schema':        'crypto_send_draft_data_v1',
          'available':     true,
          'asset':         'ETH',
          'network':       'ethereum',
          'amount':        '1.0',
          'toAddressPublic': '0xabc',
          'feePreviewStatus': 'pending_live_fetch',
          'canBroadcast':                 false,
          'requiresTrustedDevice':        true,
          'requiresPinUnlock':            true,
          'requiresLocalSigning':         true,
          'requiresExplicitConfirmation': true,
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();


      expect(find.text('Trusted device'), findsOneWidget);
      expect(find.text('PIN unlock'), findsOneWidget);
      expect(find.text('Local signing'), findsOneWidget);
      expect(find.text('Explicit confirmation'), findsOneWidget);


      expect(find.byKey(
          const Key('crypto_vault_chat_send_never_broadcasts')),
          findsOneWidget);
    });

    testWidgets('XMR send draft renders disabled banner',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_send_draft_card',
        'asset':     'XMR',
        'amount':    '0.5',
        'recipient': '43abc...',
        'data': {
          'schema':        'crypto_send_draft_data_v1',
          'available':     true,
          'asset':         'XMR',
          'network':       'monero',
          'amount':        '0.5',
          'toAddressPublic': '43abc...',
          'canBroadcast':                 false,
          'sendDisabledReason':           'xmr_send_not_supported',
          'requiresTrustedDevice':        true,
          'requiresPinUnlock':            true,
          'requiresLocalSigning':         true,
          'requiresExplicitConfirmation': true,
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_send_xmr_disabled')),
          findsOneWidget);
      expect(find.textContaining('Monero send is disabled'),
          findsOneWidget);
    });
  });



  group('USDT ambiguity is preserved', () {


    testWidgets('USDT ambiguous clarify card shows both options',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_clarify_card',
        'message':  'USDT can mean ERC20 or TRC20.',
        'options':  ['USDT_ERC20', 'USDT_TRC20'],
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_clarify_option_USDT_ERC20')),
          findsOneWidget);
      expect(find.byKey(
          const Key('crypto_vault_chat_clarify_option_USDT_TRC20')),
          findsOneWidget);
    });
  });



  group('Regression: no fake balance/activity', () {

    testWidgets('overview does not render a numeric balance for any asset',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            {'asset': 'ETH', 'label': 'ETH', 'network': 'ethereum',
             'balanceStatus': 'pending_live_fetch',
             'receiveReady': true, 'sendEnabled': true},
            {'asset': 'XMR', 'label': 'XMR', 'network': 'monero',
             'balanceStatus': 'scanner_gated',
             'reason': 'scanner_requires_desktop',
             'receiveReady': false, 'sendEnabled': false},
          ],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();


      final matcher = RegExp(r'^\s*\d+(\.\d+)?\s*(ETH|USDT|USDC|SOL|XMR)\s*$');
      expect(
        find.byWidgetPredicate((w) =>
            w is Text &&
            (w.data ?? '').isNotEmpty &&
            matcher.hasMatch(w.data!)),
        findsNothing,
        reason: 'overview must not render a numeric balance for '
                'any asset when balanceStatus is not "available"',
      );
    });
  });



  group('Mobile overflow safety with populated crypto data', () {

    Future<void> _pumpNoOverflow(
      WidgetTester tester,
      String cardType, Map<String, dynamic> data,
      {String? asset}
    ) async {
      final c = _card({
        'cardType': cardType,
        if (asset != null) 'asset': asset,
        'data':     data,
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
        size: const Size(400, 900),
      ));
      await tester.pump();
      expect(tester.takeException(), isNull,
          reason: 'populated $cardType overflows at 400x900');
    }

    testWidgets('populated show_vault fits at 400x900',
        (tester) async {
      await _pumpNoOverflow(tester,
        'crypto_vault_show_vault_card',
        {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            for (final a in ['ETH', 'USDT_ERC20', 'USDC_ERC20',
                             'SOL', 'USDT_TRC20', 'XMR'])
              {
                'asset': a,
                'label': a,
                'network': 'x',
                'balanceStatus': 'pending_live_fetch',
                'receiveReady': false,
                'sendEnabled':  a != 'XMR',
              },
          ],
          'xmrScannerStatus': 'requires_desktop',
          'xmrReason':        'scanner_requires_desktop',
        },
      );
    });

    testWidgets('populated balance card fits at 400x900',
        (tester) async {
      await _pumpNoOverflow(tester,
        'crypto_vault_balance_card',
        {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
        },
        asset: 'ETH',
      );
    });

    testWidgets('populated receive card fits at 400x900',
        (tester) async {
      await _pumpNoOverflow(tester,
        'crypto_vault_receive_card',
        {
          'schema':        'crypto_receive_data_v1',
          'available':     true,
          'asset':         'XMR',
          'label':         'XMR',
          'receiveReady':  true,
          'publicAddress': '43veryLongMoneroAddressThatDefinitelyOverflows'
                           '0000000000000000000000000000000000000000000000',
          'network':       'monero',
          'warning':       'Only send XMR on monero to this address.',
        },
        asset: 'XMR',
      );
    });

    testWidgets('populated scanner card fits at 400x900',
        (tester) async {
      await _pumpNoOverflow(tester,
        'crypto_vault_scanner_status_card',
        {
          'schema':          'crypto_scanner_status_data_v1',
          'available':       true,
          'asset':           'XMR',
          'scannerStatus':   'requires_desktop',
          'reason':          'scanner_requires_desktop',
          'canShowBalance':  false,
          'canShowActivity': false,
          'canSend':         false,
        },
      );
    });

    testWidgets('populated send-draft card fits at 400x900',
        (tester) async {
      await _pumpNoOverflow(tester,
        'crypto_vault_send_draft_card',
        {
          'schema':        'crypto_send_draft_data_v1',
          'available':     true,
          'asset':         'ETH',
          'network':       'ethereum',
          'amount':        '5.0',
          'toAddressPublic': '0xabcdef0123456789abcdef0123456789abcdef01',
        },
        asset: 'ETH',
      );
    });
  });
}
