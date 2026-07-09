

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';

Future<void> _pump(WidgetTester tester, {Size size = const Size(1200, 2400)}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('crypto wallet engine visible-page fix', () {
    testWidgets('VP1: main page is VaultAI Crypto Wallet, tagline pinned',
        (tester) async {
      await _pump(tester);
      expect(find.text('VaultAI Crypto Wallet'), findsOneWidget);
      expect(
        find.text(
          'Your keys. Your crypto. VaultAI cannot move funds without your '
          'approval.',
        ),
        findsOneWidget,
      );
    });

    testWidgets('VP2: old Lite saved-record tagline is not rendered',
        (tester) async {
      await _pump(tester);
      expect(
        find.textContaining('Store wallet addresses, seed phrases'),
        findsNothing,
      );
      expect(
        find.textContaining('private keys, recovery phrases'),
        findsNothing,
      );
    });

    testWidgets(
        'VP3: old "Add ..." Lite primary actions are not on the main page',
        (tester) async {
      await _pump(tester);
      for (final label in const [
        'Add wallet address',
        'Add seed phrase / private key',
        'Add crypto note',
        'Add transaction note',
      ]) {
        expect(
          find.text(label),
          findsNothing,
          reason: 'Old Lite primary action "$label" must not appear on '
              'the main Crypto Vault page.',
        );
      }
    });

    testWidgets('VP4: Trust Wallet dropdown copy is not rendered',
        (tester) async {
      await _pump(tester);
      expect(find.textContaining('Trust Wallet'), findsNothing);
    });

    testWidgets('VP5: Bitcoin and BNB Smart Chain are not on the main page',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_wallet_engine_card_BTC')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_card_BNB')),
        findsNothing,
      );
      expect(find.text('Bitcoin'), findsNothing);
      expect(find.text('BNB Smart Chain'), findsNothing);
    });

    testWidgets(
        'VP6: old Lite warning / counter / "not enabled yet" copy gone',
        (tester) async {
      await _pump(tester);
      const banned = <String>[
        'Send features are not enabled yet',
        'Receive QR only shows saved addresses',
        'Saved wallets: 0',
        'Balance lookup not connected',
        'No wallet saved',
        'Add wallet',
      ];
      for (final phrase in banned) {
        expect(
          find.textContaining(phrase),
          findsNothing,
          reason: 'Old Lite copy "$phrase" must not appear on the main '
              'Crypto Vault page.',
        );
      }
    });

    testWidgets(
        'VP7: ETH / USDT_ERC20 / USDC_ERC20 live cards render — under the '
        '2026-07-05 dashboard cleanup, action buttons are HIDDEN until '
        'features are loaded so we never show a misleading button',
        (tester) async {
      await _pump(tester);
      for (final asset in const ['ETH', 'USDT_ERC20', 'USDC_ERC20']) {
        expect(
          find.byKey(Key('crypto_wallet_engine_card_$asset')),
          findsOneWidget,
          reason: 'Live asset card $asset is required on the main page.',
        );
        expect(
          find.byKey(Key('crypto_wallet_engine_card_live_$asset')),
          findsOneWidget,
          reason: 'Live badge required on $asset card.',
        );


        expect(
          find.byKey(Key('crypto_wallet_engine_card_balance_skeleton_$asset')),
          findsOneWidget,
          reason: 'Balance skeleton must be visible while features load.',
        );


        expect(
          find.byKey(Key('crypto_wallet_engine_card_receive_btn_$asset')),
          findsNothing,
          reason: 'Receive button must be hidden until backend features '
              'confirm the flow is wired.',
        );
        expect(
          find.byKey(Key('crypto_wallet_engine_card_send_btn_$asset')),
          findsNothing,
          reason: 'Send button must be hidden until backend features '
              'confirm mainnet send is enabled + not paused.',
        );
      }


      expect(find.text('Ethereum'), findsWidgets);
      expect(find.text('USDT'), findsWidgets);
      expect(find.text('USDC'), findsWidgets);
      expect(find.text('Ethereum ERC20'), findsWidgets);
    });

    testWidgets(
        'VP8: SOL renders the Live badge and NEVER the "Coming next" '
        'placeholder — all six assets are launched now',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_wallet_engine_card_SOL')),
        findsOneWidget,
      );

      expect(find.text('Coming next'), findsNothing);
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_card_future_state_SOL',
        )),
        findsNothing,
      );

      expect(
        find.byKey(const Key('crypto_wallet_engine_card_live_SOL')),
        findsOneWidget,
      );
    });

    testWidgets(
        'VP9: USDT_TRC20 renders the Live badge and NEVER the '
        '"Planned" placeholder',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_wallet_engine_card_USDT_TRC20')),
        findsOneWidget,
      );

      expect(find.text('Planned'), findsNothing);
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_card_future_state_USDT_TRC20',
        )),
        findsNothing,
      );

      expect(
        find.byKey(const Key('crypto_wallet_engine_card_live_USDT_TRC20')),
        findsOneWidget,
      );
    });

    testWidgets(
        'VP10: XMR renders the Live badge and NEVER the "Privacy '
        'wallet later" placeholder',
        (tester) async {
      await _pump(tester);
      expect(
        find.byKey(const Key('crypto_wallet_engine_card_XMR')),
        findsOneWidget,
      );

      expect(find.text('Privacy wallet later'), findsNothing);
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_card_future_state_XMR',
        )),
        findsNothing,
      );

      expect(
        find.byKey(const Key('crypto_wallet_engine_card_live_XMR')),
        findsOneWidget,
      );

      expect(
        find.byKey(const Key('crypto_wallet_engine_card_send_btn_XMR')),
        findsNothing,
        reason: 'Send stays hidden for XMR until send wiring exists',
      );
    });

    testWidgets('VP11: tapping a LIVE asset card opens the detail page',
        (tester) async {
      await _pump(tester);
      final ethCardTap = find.byKey(
        const Key('crypto_wallet_engine_card_tap_ETH'),
      );
      expect(ethCardTap, findsOneWidget);
      await tester.ensureVisible(ethCardTap);
      await tester.pumpAndSettle();
      await tester.tap(ethCardTap, warnIfMissed: false);
      await tester.pumpAndSettle();
      expect(
        find.byType(CryptoWalletEngineAssetDetailPage),
        findsOneWidget,
        reason: 'Tapping the ETH card must push the real wallet-engine '
            'asset detail page.',
      );
    });

    testWidgets(
        'VP12: Security button opens the new dark security page (not Lite)',
        (tester) async {
      
      
      var litePushes = 0;
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletEnginePage(
              onOpenLite: () => litePushes++,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final securityBtn = find.byKey(
        const Key('crypto_wallet_engine_security_open_btn'),
      );
      await tester.ensureVisible(securityBtn);
      await tester.pumpAndSettle();
      await tester.tap(securityBtn);
      await tester.pumpAndSettle();
      expect(
        litePushes, equals(0),
        reason: 'Security button must NEVER invoke onOpenLite — the '
            'legacy Lite page is no longer reachable from the live '
            'wallet product.',
      );
      
      expect(
        find.byKey(const Key('crypto_wallet_engine_security_page')),
        findsOneWidget,
      );
    });

    testWidgets('VP13: mobile layout renders + scrolls at 412x900',
        (tester) async {
      
      
      await _pump(tester, size: const Size(412, 900));
      final scroller = find.byKey(const Key('crypto_wallet_engine_page'));
      expect(scroller, findsOneWidget);
      await tester.drag(scroller, const Offset(0, -2000));
      await tester.pumpAndSettle();
      expect(
        tester.takeException(), isNull,
        reason: 'Crypto Vault page must lay out at 412x900 without '
            'throwing a layout exception.',
      );
    });

    testWidgets(
        'VP14: activity taglines are visible; the redundant portfolio '
        'live-balances note is now gone (per-asset rows are enough)',
        (tester) async {
      await _pump(tester);


      expect(
        find.byKey(
          const Key('crypto_wallet_engine_portfolio_live_balances_note'),
        ),
        findsNothing,
        reason: 'the trailing live-balances note was removed from the '
            'Vault balance card — the per-asset rows are enough.',
      );




      expect(
        find.byKey(
          const Key('crypto_wallet_engine_activity_empty_primary'),
        ),
        findsOneWidget,
      );
      expect(
        find.byKey(
          const Key('crypto_wallet_engine_activity_empty_subcopy'),
        ),
        findsOneWidget,
      );
      expect(
        find.byKey(
          const Key('crypto_wallet_engine_activity_honest_subcopy'),
        ),
        findsOneWidget,
      );
      expect(
        find.text('VaultAI never invents transaction history.'),
        findsOneWidget,
      );
    });
  });
}
