

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/main.dart' show kCryptoWalletEngineEnabled;
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';

void main() {
  group('crypto_wallet_engine slice 1', () {
    test('FW1: feature flag defaults to true', () {
      expect(
        kCryptoWalletEngineEnabled,
        isTrue,
        reason:
            'kCryptoWalletEngineEnabled must default to true so the '
            'visible Crypto Vault landing page is the real non-'
            'custodial wallet engine — not the old saved-record '
            'dashboard.',
      );
    });

    test('FW2: asset catalog is the closed-set 6 (no BTC, no BNB)', () {
      expect(
        kCryptoWalletEngineAssets,
        equals(<String>[
          'ETH', 'USDT_ERC20', 'USDC_ERC20',
          'SOL', 'USDT_TRC20', 'XMR',
        ]),
      );
      expect(
        kCryptoWalletEngineAssets.contains('BTC'), isFalse,
        reason: 'Bitcoin must not appear on the main Crypto Vault page.',
      );
      expect(
        kCryptoWalletEngineAssets.contains('BNB'), isFalse,
        reason: 'BNB must not appear on the main Crypto Vault page.',
      );
      expect(kCryptoWalletEngineAssetLabels.length,
          equals(kCryptoWalletEngineAssets.length));
      expect(kCryptoWalletEngineNetworkLabels.length,
          equals(kCryptoWalletEngineAssets.length));
    });

    test('FW2b: all six assets are launched — future-state maps are '
        'empty (SOL/USDT_TRC20/XMR no longer render Coming next / '
        'Planned / Privacy wallet later)', () {
      expect(
        kCryptoWalletEngineLaunchedAssets,
        equals(<String>{
          'ETH', 'USDT_ERC20', 'USDC_ERC20',
          'SOL', 'USDT_TRC20', 'XMR',
        }),
      );

      expect(kCryptoWalletEngineFutureStateLabel, isEmpty,
          reason: 'no launched asset may sit in the future-state map');
      expect(kCryptoWalletEngineFutureStateBodyByAsset, isEmpty);


      expect(
        kCryptoWalletEngineLaunchedAssets,
        equals(kCryptoWalletEngineAssets.toSet()),
      );
    });

    testWidgets(
        'FW3: features-unknown LIVE asset cards render the "Checking…" '
        'skeleton and NEVER the removed "Balance not yet connected" '
        'placeholder',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();


      expect(find.text('Balance not yet connected'), findsNothing);


      for (final asset in kCryptoWalletEngineMainPageLiveAssets) {
        expect(
          find.byKey(
            Key('crypto_wallet_engine_card_balance_skeleton_$asset'),
          ),
          findsOneWidget,
          reason: 'live card $asset must show the "Checking…" '
              'skeleton while features are not yet loaded.',
        );
      }


      expect(find.text('Checking…'),
          findsAtLeastNWidgets(kCryptoWalletEngineMainPageLiveAssets.length));
    });

    testWidgets('FW3b: no numeric balance / amount string appears anywhere',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      
      
      final regex = RegExp(
        r'(\d+\.\d+\s*(ETH|BTC|SOL|BNB|USDT|USDC|XMR))|'
        r'(\$\s*\d+(\.\d+)?)',
      );
      final aiPromptsFinder = find.byKey(
        const Key('crypto_wallet_engine_ask_ai_prompts'),
      );
      final excludedElements = <Element>{};
      if (aiPromptsFinder.evaluate().isNotEmpty) {
        excludedElements.addAll(
          find
              .descendant(
                of: aiPromptsFinder, matching: find.byType(Text),
              )
              .evaluate(),
        );
      }
      final textWidgets = find.byType(Text);
      for (var i = 0; i < textWidgets.evaluate().length; i++) {
        final el = textWidgets.evaluate().elementAt(i);
        if (excludedElements.contains(el)) continue;
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(
          regex.hasMatch(txt), isFalse,
          reason: 'Found numeric-balance-shaped text in card: $txt',
        );
      }
    });

    testWidgets(
        'FW4: primary Send button (no wiring) shows operator-pinned '
        'not-ready banner',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();

      final btn = find.byKey(
        const Key('crypto_wallet_engine_primary_send_btn'),
      );
      await tester.ensureVisible(btn);
      await tester.pumpAndSettle();
      expect(btn, findsOneWidget);
      await tester.tap(btn, warnIfMissed: false);
      await tester.pump();
      expect(
        find.text(kCryptoWalletEngineSendNotReadyBanner),
        findsOneWidget,
        reason:
            'Tapping Send must show the operator-pinned not-ready '
            'banner, not a confirm dialog or broadcast call.',
      );
      expect(
        kCryptoWalletEngineSendNotReadyBanner.contains('PIN'),
        isTrue,
      );
      expect(
        kCryptoWalletEngineSendNotReadyBanner.contains('locally'),
        isTrue,
      );
      expect(
        kCryptoWalletEngineSendNotReadyBanner.contains('will never broadcast'),
        isTrue,
      );


      expect(
        find.byKey(const Key('crypto_wallet_engine_card_send_btn_ETH')),
        findsNothing,
        reason: 'dashboard per-asset Send button must not render when '
            'features are unknown / send is not enabled — it would '
            'mislead the user.',
      );
    });

    testWidgets(
        'FW5: primary Receive button (no wiring) shows not-ready banner',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();

      final btn = find.byKey(
        const Key('crypto_wallet_engine_primary_receive_btn'),
      );
      await tester.ensureVisible(btn);
      await tester.pumpAndSettle();
      expect(btn, findsOneWidget);
      await tester.tap(btn, warnIfMissed: false);
      await tester.pump();
      expect(
        find.text(kCryptoWalletEngineReceiveNotReadyBanner),
        findsOneWidget,
      );
      expect(
        kCryptoWalletEngineReceiveNotReadyBanner.contains('not ready'),
        isTrue,
      );


      expect(
        find.byKey(const Key('crypto_wallet_engine_card_receive_btn_ETH')),
        findsNothing,
        reason: 'dashboard per-asset Receive button must not render '
            'when features are unknown — it would falsely imply the '
            'flow is wired.',
      );
    });

    testWidgets(
        'FW6: XMR card is Live + scanner-gated (never "Privacy wallet '
        'later"); Send hidden until send wiring is present',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();


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
        reason: 'XMR must render the Live badge from the first frame',
      );


      expect(
        find.byKey(const Key('crypto_wallet_engine_card_send_btn_XMR')),
        findsNothing,
        reason: 'Send is not enabled for XMR — never render the button',
      );
    });

    testWidgets('FW7: non-custodial chip is rendered',
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

    test('FW8: no demo/mock/fake/sample/lorem placeholder string is exposed',
        () {
      const banned = ['demo', 'mock', 'fake', 'sample', 'lorem'];
      final pageSrc =
          File('lib/ui/crypto_wallet_engine_page.dart').readAsStringSync();
      var src = pageSrc.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');
      final stringLit = RegExp(r"'([^'\\]|\\.)*'|" + r'"([^"\\]|\\.)*"');
      for (final m in stringLit.allMatches(src)) {
        final lit = m.group(0)!.toLowerCase();
        for (final word in banned) {
          if (lit.contains(word)) {
            fail(
              'crypto_wallet_engine_page.dart contains banned '
              'placeholder word "$word" in string literal: $lit',
            );
          }
        }
      }
    });

    test('FW9: main.dart routing constructs CryptoWalletEnginePage', () {
      
      
      final mainSrc = File('lib/main.dart').readAsStringSync();
      expect(
        mainSrc.contains('kCryptoWalletEngineEnabled'), isTrue,
        reason: 'main.dart must reference kCryptoWalletEngineEnabled.',
      );
      expect(
        mainSrc.contains('CryptoWalletEnginePage('), isTrue,
        reason: 'main.dart must construct CryptoWalletEnginePage.',
      );
    });
  });
}
