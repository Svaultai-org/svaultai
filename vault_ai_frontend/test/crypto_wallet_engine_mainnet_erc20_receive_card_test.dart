

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


void main() {
  group('Mainnet ERC20 receive card — slice 10', () {
    test('N1: kCryptoWalletEngineMainnetErc20ReceiveEnabled defaults '
        'to false', () {
      expect(kCryptoWalletEngineMainnetErc20ReceiveEnabled, isFalse);
    });

    test('N2: mainnet token copy is compact and honest', () {


      final lower = kEvmNetworkMainnetTokenReceiveRealFundsHeadline
          .toLowerCase();
      expect(lower, contains('ethereum mainnet'));
      expect(lower, contains('only send'));
      expect(
        kEvmNetworkMainnetTokenReceiveRealFundsHeadline,
        contains('{token}'),
      );
      expect(kEvmNetworkMainnetTokenReceiveRealFundsHeadline.length,
        lessThan(90),
        reason: 'headline must stay compact for the dark card',
      );

      final blocker =
          kEvmNetworkMainnetTokenSendBlockedCopy.toLowerCase();
      expect(blocker, contains('sending is not enabled'));
      expect(blocker.length, lessThan(60),
        reason: 'send blocker copy must fit inside a compact pill',
      );
      expect(blocker.contains('security review'), isFalse,
        reason: 'no scary "security review" paragraph in user-facing copy',
      );


      expect(
        kEvmNetworkMainnetTokenSharedAddressNote.toLowerCase(),
        contains('ethereum wallet address'),
      );
      expect(
        kEvmNetworkMainnetTokenGasNote.toLowerCase(),
        contains('gas'),
      );
    });

    testWidgets('N3a: USDT coming-soon body renders when flag is off',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMainnetErc20ReceiveCard(
              asset: kMainnetErc20AssetUsdt,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMainnetErc20ReceiveCardKey)),
        findsOneWidget,
      );
      expect(
        find.text(kMainnetErc20ReceiveComingSoonBody),
        findsOneWidget,
      );
      
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_mainnet_erc20_receive_open_btn',
        )),
        findsNothing,
      );
      
      expect(
        find.byKey(const Key(kMainnetErc20ReceiveSendDisabledKey)),
        findsNothing,
      );
    });

    testWidgets('N3b: USDC coming-soon body renders when flag is off',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMainnetErc20ReceiveCard(
              asset: kMainnetErc20AssetUsdc,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMainnetErc20ReceiveCardKey)),
        findsOneWidget,
      );
      expect(
        find.text(kMainnetErc20ReceiveComingSoonBody),
        findsOneWidget,
      );
    });

    testWidgets('N4: card never renders a 0x mainnet address',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMainnetErc20ReceiveCard(
              asset: kMainnetErc20AssetUsdt,
            ),
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

    testWidgets('N5: card never renders a balance literal',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMainnetErc20ReceiveCard(
              asset: kMainnetErc20AssetUsdc,
            ),
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

    testWidgets('N6: with flag off, no shared-address / gas tiles',
        (tester) async {
      
      
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: CryptoWalletEngineMainnetErc20ReceiveCard(
              asset: kMainnetErc20AssetUsdt,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key(kMainnetErc20ReceiveSharedAddressKey)),
        findsNothing,
      );
      expect(
        find.byKey(const Key(kMainnetErc20ReceiveGasNoteKey)),
        findsNothing,
      );
      expect(
        find.byKey(const Key(kMainnetErc20ReceiveSendDisabledKey)),
        findsNothing,
      );
    });

    testWidgets(
        'N7: engine page suppresses the mainnet slot on testnet-only builds',
        (tester) async {
      
      
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: CryptoWalletEnginePage()),
        ),
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
      'N8: no "Receive-only" badge and no "Coming soon" clutter chip '
      'when flag is off (network chip still shows Ethereum Mainnet · ERC20)',
      (tester) async {
        await tester.pumpWidget(
          const MaterialApp(
            home: Scaffold(
              body: CryptoWalletEngineMainnetErc20ReceiveCard(
                asset: kMainnetErc20AssetUsdt,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Receive-only'), findsNothing);
        expect(find.text('Coming soon'), findsNothing);
        expect(find.text(kMainnetErc20ReceiveCardHeader), findsOneWidget);
      },
    );

    testWidgets('N9: 360 px mobile rendering survives',
        (tester) async {
      tester.view.physicalSize = const Size(360, 1200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: CryptoWalletEngineMainnetErc20ReceiveCard(
                asset: kMainnetErc20AssetUsdc,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    test('N10: source guard — no signing imports in mainnet token card',
        () {
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart',
      ).readAsStringSync();
      const banned = [
        'ethereum_wallet', 'ethereum_transaction',
        'ethereum_sepolia_proxy',
      ];
      for (final name in banned) {
        expect(
          src.contains("import '../services/$name"),
          isFalse,
          reason: 'Mainnet token card must not import $name',
        );
      }
    });

    test('N11: no "Lite" string in mainnet token card source', () {
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart',
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

    test('N12: source guard — no Send button references in card source',
        () {
      
      
      final src = File(
        'lib/ui/crypto_wallet_engine_mainnet_erc20_receive_card.dart',
      ).readAsStringSync();
      
      final scrubbed = src.split('\n').map((l) {
        final idx = l.indexOf('//');
        return idx >= 0 ? l.substring(0, idx) : l;
      }).join('\n');
      
      expect(
        scrubbed.contains('send/draft'),
        isFalse,
        reason: 'Mainnet token card must not call /send/draft',
      );
      expect(
        scrubbed.contains('send/broadcast'),
        isFalse,
        reason: 'Mainnet token card must not call /send/broadcast',
      );
    });
  });
}
