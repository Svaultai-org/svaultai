

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_mainnet_receive_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


void main() {
  group('Mainnet receive card — slice 9', () {
    test('M1: kCryptoWalletEngineMainnetReceiveEnabled defaults to false', () {
      expect(kCryptoWalletEngineMainnetReceiveEnabled, isFalse);
    });

    test('M2: mainnet copy is compact and honest', () {


      final lower = kEvmNetworkMainnetReceiveRealFundsHeadline.toLowerCase();
      expect(lower, contains('ethereum mainnet'));
      expect(lower, contains('only send eth'));

      expect(kEvmNetworkMainnetReceiveRealFundsHeadline.length, lessThan(80),
        reason: 'headline must stay compact for the dark card',
      );

      final blocker = kEvmNetworkMainnetSendBlockedCopy.toLowerCase();
      expect(blocker, contains('sending is not enabled'));

      expect(blocker.length, lessThan(60),
        reason: 'send blocker copy must fit inside a compact pill',
      );

      expect(blocker.contains('security review'), isFalse,
        reason: 'no scary "security review" paragraph in user-facing copy',
      );
    });

    testWidgets('M3: coming-soon body renders when flag is off',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMainnetReceiveCard(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMainnetReceiveCardKey)),
        findsOneWidget,
      );
      
      expect(
        find.text(kMainnetReceiveComingSoonBody),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_mainnet_receive_open_btn',
        )),
        findsNothing,
      );
      
      
      expect(
        find.byKey(const Key(kMainnetReceiveSendDisabledKey)),
        findsNothing,
      );
    });

    testWidgets('M4: card never renders a 0x mainnet address',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMainnetReceiveCard(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final addrRe = RegExp(r'0x[0-9a-fA-F]{40}');
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(addrRe.hasMatch(txt), isFalse,
            reason: 'No 0x mainnet address shall appear: $txt');
      }
    });

    testWidgets('M5: card never renders a balance literal',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMainnetReceiveCard(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final balRe = RegExp(r'\d+\.\d+\s*(ETH|USDT|USDC)');
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(balRe.hasMatch(txt), isFalse,
            reason: 'No balance literal: $txt');
      }
    });

    testWidgets(
        'M8: testnet-only dashboard does not render the mainnet slot widget',
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
      expect(
        find.byKey(const Key('crypto_wallet_engine_mainnet_receive_slot')),
        findsNothing,
      );
    });

    testWidgets(
      'M9: no "Receive-only" badge and no "Coming soon" clutter chip '
      'when flag is off (network chip still shows Ethereum Mainnet)',
      (tester) async {
        await tester.pumpWidget(
          const MaterialApp(
            home: Scaffold(
              body: CryptoWalletEngineMainnetReceiveCard(),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Receive-only'), findsNothing);
        expect(find.text('Coming soon'), findsNothing);
        expect(find.text(kMainnetReceiveNetworkLabel), findsOneWidget);
      },
    );

    testWidgets('M10: 360 px mobile rendering survives',
        (tester) async {
      tester.view.physicalSize = const Size(360, 1200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: CryptoWalletEngineMainnetReceiveCard(),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    test('M11: source guard — no signing imports in mainnet card', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_receive_card.dart',
      ).readAsStringSync();
      const banned = [
        'ethereum_wallet', 'ethereum_transaction',
        'ethereum_sepolia_proxy',
      ];
      for (final name in banned) {
        expect(
          src.contains("import '../services/$name"),
          isFalse,
          reason: 'Mainnet card must not import $name',
        );
      }
    });

    test('M12: no "Lite" string in the mainnet card source', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_receive_card.dart',
      ).readAsStringSync();
      
      final scrubbed = src.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');
      final stringLit = RegExp(r"'([^'\\]|\\.)*'|" + r'"([^"\\]|\\.)*"');
      final liteRe = RegExp(r'\bLite\b', caseSensitive: false);
      for (final m in stringLit.allMatches(scrubbed)) {
        final lit = m.group(0)!;
        expect(
          liteRe.hasMatch(lit), isFalse,
          reason: 'No "Lite" string literal: $lit',
        );
      }
    });
  });
}
