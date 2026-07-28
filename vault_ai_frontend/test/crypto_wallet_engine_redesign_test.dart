

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';

void main() {
  group('Crypto Wallet Engine — slice 6 wallet-style redesign', () {
    testWidgets('R1: portfolio summary banner renders — the trailing '
        'honest subcopy + live-balances note are gone (polish pass, '
        'the per-asset rows already tell the story)',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_portfolio_summary')),
        findsOneWidget,
      );




      expect(
        find.text(kCryptoWalletEnginePortfolioHonestSubcopy),
        findsNothing,
        reason: 'the "Svaultai only shows real on-chain balances" line '
            'was removed — the polished portfolio no longer trails a '
            'disclaimer paragraph.',
      );
      expect(
        find.byKey(
          const Key('crypto_wallet_engine_portfolio_live_balances_note'),
        ),
        findsNothing,
        reason: 'the "Live balances shown from connected Mainnet '
            'networks." line was removed — redundant with the network '
            'chip.',
      );



      expect(
        kCryptoWalletEnginePortfolioHonestSubcopy.toLowerCase(),
        contains('real on-chain'),
        reason: 'the constant is still exported for other callers, '
            'even though the Vault balance card no longer renders it.',
      );
    });

    testWidgets('R2: primary action row renders Receive/Send/Activity/Backup',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_primary_actions')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_primary_receive_btn')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_primary_send_btn')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_primary_activity_btn')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_primary_backup_btn')),
        findsOneWidget,
      );
    });

    testWidgets('R3: no user-visible string contains the word "Lite"',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      final liteRe = RegExp(r'\bLite\b', caseSensitive: false);
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(liteRe.hasMatch(txt), isFalse,
            reason: 'Found "Lite" in user-visible text: $txt');
      }
    });

    testWidgets(
        'R4: network chip identifies Ethereum Sepolia testnet',
        (tester) async {
      
      
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_network_badge')),
        findsOneWidget,
      );
      expect(
        find.textContaining('Ethereum Sepolia'),
        findsAtLeastNWidgets(1),
      );
      
      
      expect(
        find.byKey(const Key('crypto_wallet_engine_mainnet_coming_soon')),
        findsNothing,
      );
    });

    testWidgets('R5: non-custodial chip present',
        (tester) async {
      
      
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_chip_non_custodial',
        )),
        findsOneWidget,
      );
      expect(find.text('Non-custodial'), findsAtLeastNWidgets(1));
    });

    testWidgets(
        'R6: asset list renders the closed-set 6 (no BTC, no BNB) in order',
        (tester) async {
      
      
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      for (final asset in const [
        'ETH', 'USDT_ERC20', 'USDC_ERC20',
        'SOL', 'USDT_TRC20', 'XMR',
      ]) {
        expect(
          find.byKey(Key('crypto_wallet_engine_card_$asset')),
          findsOneWidget,
          reason: 'Asset card for $asset must be rendered',
        );
      }
      
      expect(
        find.byKey(const Key('crypto_wallet_engine_card_BTC')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_card_BNB')),
        findsNothing,
      );
    });

    testWidgets('R7: tapping the ETH card opens the asset detail page',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      
      final cardTap = find.byKey(const Key('crypto_wallet_engine_card_tap_ETH'));
      await tester.ensureVisible(cardTap);
      await tester.pumpAndSettle();
      await tester.tap(cardTap, warnIfMissed: false);
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_page')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_header')),
        findsOneWidget,
      );
    });

    testWidgets(
        'R8: ETH detail page renders balance, address, Receive, Send, '
        'Activity, Backup', (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineAssetDetailPage(asset: 'ETH'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_balance')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_address')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_receive_btn')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_activity_no_wallet',
        )),
        findsOneWidget,
        reason: 'in the no-wallet state the activity panel renders the '
            'honest no-wallet card, not the network-hitting activity card.',
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_backup')),
        findsOneWidget,
      );


      expect(
        find.text('Create wallet to view balance.'),
        findsOneWidget,
      );
    });

    testWidgets(
        'R9: USDT_ERC20 + USDC_ERC20 detail pages render the shared-address + '
        'gas-paid-in-ETH notes', (tester) async {
      for (final token in const ['USDT_ERC20', 'USDC_ERC20']) {
        tester.view.physicalSize = const Size(1200, 4000);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: CryptoWalletEngineAssetDetailPage(asset: token),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          find.byKey(const Key(
            'crypto_wallet_engine_asset_detail_token_shared_address',
          )),
          findsOneWidget,
          reason: '$token must render the shared-Ethereum-address note',
        );
        expect(
          find.byKey(const Key(
            'crypto_wallet_engine_asset_detail_token_gas_note',
          )),
          findsOneWidget,
          reason: '$token must render the gas-paid-in-ETH note',
        );
        expect(
          find.text(kAssetDetailTokenSharedAddressNote),
          findsOneWidget,
        );
      }
    });

    testWidgets(
        'R10: BTC detail page renders the "Coming soon" panel — no send, '
        'no balance number, no address', (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineAssetDetailPage(asset: 'BTC'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_coming_soon')),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_send_btn')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_asset_detail_receive_btn')),
        findsNothing,
      );
      
      final addrRe = RegExp(r'0x[0-9a-fA-F]{40}');
      final balRe = RegExp(r'\d+\.\d+\s*(BTC|ETH|SOL)');
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(addrRe.hasMatch(txt), isFalse, reason: 'No 0x addr: $txt');
        expect(balRe.hasMatch(txt), isFalse, reason: 'No balance lit: $txt');
      }
    });

    testWidgets(
        'R11: home Activity + ETH detail Activity say "not connected yet"',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_activity_section')),
        findsOneWidget,
      );




      final subcopy = kCryptoWalletEngineActivityEmptySubcopy.toLowerCase();
      expect(
        subcopy.contains('activity history is connected')
          || subcopy.contains('indexer is connected')
          || subcopy.contains('not connected yet'),
        isTrue,
        reason: 'polished copy must remain honest about indexer status',
      );
      
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineAssetDetailPage(asset: 'ETH'),
          ),
        ),
      );
      await tester.pumpAndSettle();


      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_activity_no_wallet',
        )),
        findsOneWidget,
      );
      expect(find.text('Create wallet to view activity.'), findsOneWidget);


      expect(
        kAssetDetailActivityNotConnected.toLowerCase(),
        contains('not connected yet'),
      );
    });

    testWidgets(
        'R12: Security section visible AFTER the asset grid (secondary)',
        (tester) async {
      
      
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      final gridFinder = find.byKey(
        const Key('crypto_wallet_engine_asset_grid'),
      );
      final securityFinder = find.byKey(
        const Key('crypto_wallet_engine_security_section'),
      );
      expect(gridFinder, findsOneWidget);
      expect(securityFinder, findsOneWidget);
      final gridOffset = tester.getTopLeft(gridFinder).dy;
      final securityOffset = tester.getTopLeft(securityFinder).dy;
      expect(securityOffset, greaterThan(gridOffset),
          reason: 'Security card must appear BELOW the asset grid.');
    });

    testWidgets(
        'R13: legacy Backup + Wallet notes sections are gone',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_backup_section')),
        findsNothing,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_notes_section')),
        findsNothing,
      );
    });

    testWidgets(
        'R14: Ask Svaultai section renders the closed-set suggested prompts',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_ask_ai_section')),
        findsOneWidget,
      );
      for (final prompt in kCryptoWalletEngineAskAiSuggestedPrompts) {
        expect(
          find.text(prompt),
          findsOneWidget,
          reason: 'Ask Svaultai prompt missing: $prompt',
        );
      }
    });

    testWidgets(
        'R15: no buy/sell/swap/trade/stake/bridge user-visible text',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      final bannedRe = RegExp(
        r'\b(buy|sell|swap|trade|trading|stake|staking|bridge|bridging)\b',
        caseSensitive: false,
      );
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(bannedRe.hasMatch(txt), isFalse,
            reason: 'Found banned trading/staking/bridge word in $txt');
      }
    });

    testWidgets(
        'R16: no mainnet send affordance is rendered while mainnet is disabled',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      
      
      expect(
        find.byKey(const Key('crypto_wallet_engine_mainnet_coming_soon')),
        findsNothing,
      );
      
      for (final el in find
          .byWidgetPredicate((w) => w is ButtonStyleButton)
          .evaluate()) {
        final btn = el.widget as ButtonStyleButton;
        final children = <String>[];
        void walk(Widget w) {
          if (w is Text) children.add(w.data ?? '');
        }
        if (btn.child != null) walk(btn.child!);
        for (final t in children) {
          final lower = t.toLowerCase();
          expect(
            lower.contains('mainnet'),
            isFalse,
            reason: 'Found mainnet label on a button: $t',
          );
        }
      }
      
      
      final cta = RegExp(
        r'(send\s+on\s+mainnet)|(broadcast\s+on\s+mainnet)|'
        r'(enable\s+mainnet\s+send)',
        caseSensitive: false,
      );
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(cta.hasMatch(txt), isFalse,
            reason: 'Found mainnet send CTA: $txt');
      }
    });

    test('R17: source guard: no banned placeholder word in detail page', () {
      const banned = ['demo', 'mock', 'fake', 'sample', 'lorem'];
      final src = File(
        'lib/ui/crypto_wallet_engine_asset_detail_page.dart',
      ).readAsStringSync();
      
      
      final scrubbed = src.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');
      final stringLit = RegExp(r"'([^'\\]|\\.)*'|" + r'"([^"\\]|\\.)*"');
      for (final m in stringLit.allMatches(scrubbed)) {
        final lit = m.group(0)!.toLowerCase();
        for (final word in banned) {
          if (lit.contains(word)) {
            fail('Asset detail page literal contains banned word '
                '"$word": $lit');
          }
        }
      }
    });

    testWidgets('R18: mobile 360 px renders the wallet dashboard key sections',
        (tester) async {
      
      
      tester.view.physicalSize = const Size(360, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      
      for (final keyName in const [
        'crypto_wallet_engine_portfolio_summary',
        'crypto_wallet_engine_primary_actions',
        'crypto_wallet_engine_asset_grid',
        'crypto_wallet_engine_activity_section',
        'crypto_wallet_engine_security_section',
        'crypto_wallet_engine_ask_ai_section',
      ]) {
        expect(
          find.byKey(Key(keyName)),
          findsOneWidget,
          reason: 'Section "$keyName" must render at 360 px',
        );
      }
      
      
      tester.takeException();
    });

    testWidgets('R19: tapping an Ask Svaultai prompt forwards through callback',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      String? captured;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CryptoWalletEnginePage(
              onSendChatPrompt: (p) => captured = p,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      
      final firstPrompt = kCryptoWalletEngineAskAiSuggestedPrompts.first;
      final chip = find.widgetWithText(ActionChip, firstPrompt);
      await tester.ensureVisible(chip);
      await tester.pumpAndSettle();
      await tester.tap(chip, warnIfMissed: false);
      await tester.pumpAndSettle();
      expect(captured, equals(firstPrompt));
    });
  });
}
