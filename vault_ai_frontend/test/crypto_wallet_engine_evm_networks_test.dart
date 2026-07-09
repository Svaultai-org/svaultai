

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';

void main() {
  group('EVM network registry — closed-set catalog', () {
    test('E1: closed-set is exactly Sepolia + Mainnet', () {
      expect(
        kAllEvmNetworks,
        equals(['ethereum_sepolia', 'ethereum_mainnet']),
      );
    });

    test('E2: per-network metadata matches the backend', () {
      expect(
        kEvmNetworkDisplayName[kEvmNetworkEthereumSepolia],
        equals('Ethereum Sepolia'),
      );
      expect(
        kEvmNetworkDisplayName[kEvmNetworkEthereumMainnet],
        equals('Ethereum Mainnet'),
      );
      expect(kEvmNetworkChainId[kEvmNetworkEthereumSepolia], equals(11155111));
      expect(kEvmNetworkChainId[kEvmNetworkEthereumMainnet], equals(1));
      expect(kEvmNetworkIsTestnet[kEvmNetworkEthereumSepolia], isTrue);
      expect(kEvmNetworkIsTestnet[kEvmNetworkEthereumMainnet], isFalse);
    });

    test('E3: default network is ethereum_sepolia', () {
      expect(kEvmNetworkDefault, equals(kEvmNetworkEthereumSepolia));
    });

    test('E8: evmNetworkIsTestnet helper', () {
      expect(evmNetworkIsTestnet(kEvmNetworkEthereumSepolia), isTrue);
      expect(evmNetworkIsTestnet(kEvmNetworkEthereumMainnet), isFalse);
      expect(evmNetworkIsTestnet(null), isFalse);
      expect(evmNetworkIsTestnet('garbage'), isFalse);
    });

    test('E9: isKnownEvmNetwork is strict + case-sensitive', () {
      expect(isKnownEvmNetwork('ethereum_sepolia'), isTrue);
      expect(isKnownEvmNetwork('ethereum_mainnet'), isTrue);
      expect(isKnownEvmNetwork('ETHEREUM_SEPOLIA'), isFalse,
          reason: 'Network ids are case-sensitive — uppercase '
              'must NOT match a lowercase id.');
      expect(isKnownEvmNetwork(''), isFalse);
      expect(isKnownEvmNetwork(null), isFalse);
      expect(isKnownEvmNetwork('polkadot'), isFalse);
    });

    test('E6: operator-pinned Sepolia testnet warning mentions Sepolia', () {
      expect(
        kEvmNetworkTestnetWarning.toLowerCase(),
        contains('sepolia'),
      );
      expect(
        kEvmNetworkTestnetWarning.toLowerCase(),
        contains('testnet'),
      );
      expect(
        kEvmNetworkTestnetWarning.toLowerCase(),
        contains('mainnet'),
        reason: 'Testnet warning must explicitly tell the user '
            'not to send mainnet funds.',
      );
    });

    test('E7: operator-pinned mainnet warning mentions real funds', () {
      expect(
        kEvmNetworkMainnetWarning.toLowerCase(),
        contains('real'),
      );
      expect(
        kEvmNetworkMainnetWarning.toLowerCase(),
        contains('mainnet'),
      );
    });
  });

  group('Engine page renders the slice 5 banners', () {
    testWidgets('E4: Testnet chip identifies Sepolia', (tester) async {
      
      
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('crypto_wallet_engine_network_badge')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('crypto_wallet_engine_testnet_warning')),
        findsNothing,
        reason: 'The giant testnet warning panel is retired in favour '
            'of the compact chip.',
      );
      expect(
        find.textContaining('Testnet'),
        findsAtLeastNWidgets(1),
      );
    });

    testWidgets(
        'E5: mainnet "coming soon" placeholder is NOT rendered on the '
        'testnet dashboard',
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
        find.byKey(const Key('crypto_wallet_engine_mainnet_coming_soon')),
        findsNothing,
      );
      expect(
        find.text(kEvmNetworkMainnetComingSoon),
        findsNothing,
      );
    });

    testWidgets(
        'E10: engine page renders no mainnet receive address or balance',
        (tester) async {
      
      
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: CryptoWalletEnginePage())),
      );
      await tester.pumpAndSettle();
      
      
      final addrRe = RegExp(r'0x[0-9a-fA-F]{40}');
      final balRe = RegExp(r'\d+\.\d+\s*ETH\s*\(mainnet\)');
      for (final el in find.byType(Text).evaluate()) {
        final w = el.widget as Text;
        final txt = w.data ?? '';
        expect(addrRe.hasMatch(txt), isFalse,
            reason: 'No 0x-address may appear on the engine page: $txt');
        expect(balRe.hasMatch(txt), isFalse,
            reason: 'No mainnet balance literal may appear: $txt');
      }
    });
  });
}
