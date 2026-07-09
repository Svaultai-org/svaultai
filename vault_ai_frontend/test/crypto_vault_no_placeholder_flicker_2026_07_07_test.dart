import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/services/monero_scanner_status.dart';


Future<void> _pumpFreshEngine(WidgetTester tester,
    {Size size = const Size(1200, 2400)}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
  );
}


void main() {
  group('Crypto Vault first-frame render never shows obsolete '
      'placeholder copy for launched assets', () {


    const _forbiddenPlaceholderStrings = <String>[
      'Coming next',
      'Planned',
      'Privacy wallet later',
      'Solana wallet support is coming next',
      'USDT TRC20 support is planned',
      'Monero requires a special',
      'no Send, no Receive, no QR',
      'No Send, no Receive, no QR',
    ];


    testWidgets(
        'first frame — before any pump — contains no obsolete '
        'placeholder text',
        (tester) async {
      await _pumpFreshEngine(tester);



      for (final banned in _forbiddenPlaceholderStrings) {
        expect(
          find.text(banned),
          findsNothing,
          reason: 'first frame contains obsolete placeholder text: '
              '$banned',
        );
      }
    });


    testWidgets(
        'after pumpAndSettle — no obsolete placeholder text either',
        (tester) async {
      await _pumpFreshEngine(tester);
      await tester.pumpAndSettle();

      for (final banned in _forbiddenPlaceholderStrings) {
        expect(
          find.text(banned),
          findsNothing,
          reason: 'after settle contains obsolete placeholder text: '
              '$banned',
        );
      }
    });


    testWidgets(
        'no future-state badge key renders for ANY launched asset',
        (tester) async {
      await _pumpFreshEngine(tester);
      await tester.pumpAndSettle();
      for (final asset in kCryptoWalletEngineLaunchedAssets) {
        expect(
          find.byKey(
              Key('crypto_wallet_engine_card_future_state_$asset')),
          findsNothing,
          reason: '$asset must never carry the future-state badge',
        );
        expect(
          find.byKey(
              Key('crypto_wallet_engine_card_future_body_$asset')),
          findsNothing,
          reason: '$asset must never render the future-state body',
        );
      }
    });
  });


  group('Every launched asset renders Live from first frame', () {

    testWidgets('SOL renders Live badge, not "Coming next"',
        (tester) async {
      await _pumpFreshEngine(tester);

      expect(
        find.byKey(const Key('crypto_wallet_engine_card_live_SOL')),
        findsOneWidget,
      );

      expect(find.text('Coming next'), findsNothing);
    });

    testWidgets('USDT_TRC20 renders Live badge, not "Planned"',
        (tester) async {
      await _pumpFreshEngine(tester);

      expect(
        find.byKey(
            const Key('crypto_wallet_engine_card_live_USDT_TRC20')),
        findsOneWidget,
      );
      expect(find.text('Planned'), findsNothing);
    });

    testWidgets('XMR renders Live badge, not "Privacy wallet later"',
        (tester) async {
      await _pumpFreshEngine(tester);

      expect(
        find.byKey(const Key('crypto_wallet_engine_card_live_XMR')),
        findsOneWidget,
      );
      expect(find.text('Privacy wallet later'), findsNothing);
    });

    testWidgets('ETH / USDT_ERC20 / USDC_ERC20 also render Live '
        'badge from the first frame', (tester) async {
      await _pumpFreshEngine(tester);
      for (final asset in const ['ETH', 'USDT_ERC20', 'USDC_ERC20']) {
        expect(
          find.byKey(Key('crypto_wallet_engine_card_live_$asset')),
          findsOneWidget,
          reason: '$asset must show the Live badge on first frame',
        );
      }
    });
  });


  group('Constants — the sole source of truth for the launched set',
      () {

    test('kCryptoWalletEngineLaunchedAssets covers every dashboard '
        'asset', () {
      expect(
        kCryptoWalletEngineLaunchedAssets,
        equals(kCryptoWalletEngineAssets.toSet()),
        reason: 'every asset shown on the dashboard must be launched '
            '— otherwise it would render the deprecated future-state '
            'placeholder copy.',
      );
    });

    test('future-state label map is empty — nothing may render '
        'obsolete placeholder text on the dashboard', () {
      expect(kCryptoWalletEngineFutureStateLabel, isEmpty);
    });

    test('future-state body map is empty', () {
      expect(kCryptoWalletEngineFutureStateBodyByAsset, isEmpty);
    });


    test('the fallback future-state body string is not rendered '
        'anywhere by the dashboard because isLive is true for all '
        'launched assets — but it is still available for a '
        'genuinely-future asset', () {


      expect(kCryptoWalletEngineFutureStateBody, isNotEmpty);
    });
  });


  group('XMR-specific first-frame contract', () {

    testWidgets(
        'XMR dashboard card first frame shows the safe scanner-gated '
        'copy, not the obsolete "no Send, no Receive, no QR" copy',
        (tester) async {
      await _pumpFreshEngine(tester);
      await tester.pumpAndSettle();


      expect(find.text('no Send, no Receive, no QR'), findsNothing);
      expect(find.text('No Send, no Receive, no QR'), findsNothing);


      expect(
        find.byKey(
          const Key('crypto_wallet_engine_card_xmr_scanner_note'),
        ),
        findsOneWidget,
        reason: 'XMR card carries the scanner-gated note — replaces '
            'the obsolete privacy-wallet-later banner.',
      );

      expect(
        find.text(kMoneroDashboardScannerNoteCopyDefault),
        findsOneWidget,
      );
    });


    testWidgets('Send button is not visible on the XMR dashboard '
        'card (Send is not enabled for XMR in this slice)',
        (tester) async {
      await _pumpFreshEngine(tester);
      await tester.pumpAndSettle();

      expect(
        find.byKey(
          const Key('crypto_wallet_engine_card_send_btn_XMR'),
        ),
        findsNothing,
      );
    });
  });


  group('No fake XMR balance and no exchange language', () {

    testWidgets(
        'first frame never shows a hard-coded "0 XMR" — Monero '
        'balance is scanner-gated, not zeroed',
        (tester) async {
      await _pumpFreshEngine(tester);
      await tester.pumpAndSettle();

      expect(find.text('0 XMR'),   findsNothing);
      expect(find.text('0.0 XMR'), findsNothing);
      expect(find.text('0.00 XMR'), findsNothing);
    });


    test('the launched-asset label and note constants contain no '
        'exchange language', () {
      const banned = <String>[
        'buy', 'sell', 'swap', 'trade', 'stake',
        'bridge', 'exchange', 'convert', 'coming soon',
      ];
      final strings = <String>[
        kMoneroDashboardBalanceCopyDefault,
        kMoneroDashboardScannerNoteCopyDefault,
        kMoneroDashboardActivityChipCopyDefault,
      ];
      for (final s in strings) {
        final low = s.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'copy "$s" leaks "$b"');
        }
      }
    });
  });


  group('Mobile — no overflow at 400 px width', () {

    testWidgets(
        'first frame at 400x900 does not overflow in any asset card',
        (tester) async {
      await _pumpFreshEngine(tester, size: const Size(400, 900));
      await tester.pumpAndSettle();


      for (final asset in kCryptoWalletEngineLaunchedAssets) {
        expect(
          find.byKey(Key('crypto_wallet_engine_card_$asset')),
          findsOneWidget,
        );
      }
      expect(tester.takeException(), isNull);
    });
  });
}
