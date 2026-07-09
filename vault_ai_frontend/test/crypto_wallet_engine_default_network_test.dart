

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_receive_panel.dart';

void main() {
  group('CRYPTO_WALLET_DEFAULT_NETWORK — compile-time resolver', () {
    test('unset dart-define resolves to Sepolia by default', () {
      expect(
        resolveCompileTimeDefaultNetwork(),
        equals(kEvmNetworkEthereumSepolia),
      );
    });

    test('unset dart-define is valid (dev default)', () {
      expect(compileTimeDefaultNetworkConfigValid(), isTrue);
    });

    test('compile-time resolved constant matches resolver', () {
      expect(
        kCompileTimeDefaultNetworkResolved,
        anyOf(
          equals(kEvmNetworkEthereumSepolia),
          equals(kEvmNetworkEthereumMainnet),
        ),
      );
    });

    test('compile-time chip label matches default network', () {
      final label = compileTimeDashboardChipLabel();
      expect(
        label,
        anyOf(
          equals(kEvmNetworkMainnetDashboardChipLabel),
          equals(kEvmNetworkSepoliaDashboardChipLabel),
        ),
      );
    });
  });

  group('resolveEffectiveDefaultNetwork — prefers backend when valid', () {
    test('mainnet backend + config-valid → mainnet', () {
      expect(
        resolveEffectiveDefaultNetwork(
          backendDefaultNetwork: kEvmNetworkEthereumMainnet,
          backendDefaultNetworkConfigValid: true,
        ),
        equals(kEvmNetworkEthereumMainnet),
      );
    });

    test('sepolia backend + config-valid → sepolia', () {
      expect(
        resolveEffectiveDefaultNetwork(
          backendDefaultNetwork: kEvmNetworkEthereumSepolia,
          backendDefaultNetworkConfigValid: true,
        ),
        equals(kEvmNetworkEthereumSepolia),
      );
    });

    test('invalid backend + config-invalid → falls back safely', () {
      final resolved = resolveEffectiveDefaultNetwork(
        backendDefaultNetwork: '',
        backendDefaultNetworkConfigValid: false,
      );
      expect(
        resolved,
        anyOf(
          equals(kEvmNetworkEthereumSepolia),
          equals(kEvmNetworkEthereumMainnet),
        ),
      );
    });

    test('unknown backend network never returns an off-catalog id', () {
      final resolved = resolveEffectiveDefaultNetwork(
        backendDefaultNetwork: 'solana_mainnet',
        backendDefaultNetworkConfigValid: true,
      );
      expect(
        resolved,
        anyOf(
          equals(kEvmNetworkEthereumSepolia),
          equals(kEvmNetworkEthereumMainnet),
        ),
      );
    });

    test('bitcoin/solana/tron/bnb backends never leak into the result', () {
      for (final banned in [
        'bitcoin_mainnet',
        'solana_mainnet',
        'tron_mainnet',
        'usdt_trc20',
        'bnb_smart_chain',
        'monero_mainnet',
      ]) {
        final resolved = resolveEffectiveDefaultNetwork(
          backendDefaultNetwork: banned,
          backendDefaultNetworkConfigValid: true,
        );
        expect(resolved, isNot(equals(banned)),
            reason: 'Resolver must reject $banned');
      }
    });
  });

  group('CryptoWalletFeatures — includes defaultNetwork', () {
    test('fromBackend parses defaultNetwork string field', () {
      final f = CryptoWalletFeatures.fromBackend({
        'walletEngineEnabled': true,
        'defaultNetwork': 'ethereum_mainnet',
        'defaultNetworkConfigValid': true,
      });
      expect(f.defaultNetwork, equals(kEvmNetworkEthereumMainnet));
      expect(f.defaultNetworkConfigValid, isTrue);
    });

    test('unknown() has empty defaultNetwork', () {
      const f = CryptoWalletFeatures.unknown();
      expect(f.defaultNetwork, isEmpty);
      expect(f.defaultNetworkConfigValid, isFalse);
    });

    test('effectiveDefaultNetwork prefers valid backend value', () {
      final f = CryptoWalletFeatures.fromBackend({
        'defaultNetwork': 'ethereum_mainnet',
        'defaultNetworkConfigValid': true,
      });
      expect(f.effectiveDefaultNetwork,
          equals(kEvmNetworkEthereumMainnet));
      expect(f.isMainnetDefault, isTrue);
    });

    test('effectiveDefaultNetwork rejects invalid backend value', () {
      final f = CryptoWalletFeatures.fromBackend({
        'defaultNetwork': 'solana_mainnet',
        'defaultNetworkConfigValid': true,
      });
      expect(
        f.effectiveDefaultNetwork,
        anyOf(
          equals(kEvmNetworkEthereumSepolia),
          equals(kEvmNetworkEthereumMainnet),
        ),
      );
    });

    test('mainnetActive gates on compile-time receive flag', () {
      final f = CryptoWalletFeatures.fromBackend({
        'defaultNetwork': 'ethereum_mainnet',
        'defaultNetworkConfigValid': true,
        'mainnetReceiveEnabled': true,
        'mainnetErc20ReceiveEnabled': true,
      });
      final compileTimeOn = kCryptoWalletEngineMainnetReceiveEnabled
          && kCryptoWalletEngineMainnetErc20ReceiveEnabled;
      expect(f.mainnetActive, equals(compileTimeOn && f.isMainnetDefault));
    });
  });

  group('receive panel copy — network-aware', () {
    test('Mainnet ETH warning says Ethereum Mainnet, no Sepolia', () {
      final warn = receivePanelAssetWarningFor(
        kEvmNetworkEthereumMainnet, 'ETH',
      );
      expect(warn, contains('Ethereum Mainnet'));
      expect(warn.toLowerCase(), isNot(contains('sepolia')));
      expect(warn.toLowerCase(), isNot(contains('testnet')));
    });

    test('Mainnet USDT/USDC warning says ERC20 on Ethereum Mainnet', () {
      for (final asset in ['USDT_ERC20', 'USDC_ERC20']) {
        final warn = receivePanelAssetWarningFor(
          kEvmNetworkEthereumMainnet, asset,
        );
        expect(warn, contains('ERC20'));
        expect(warn, contains('Ethereum Mainnet'));
        expect(warn.toLowerCase(), isNot(contains('sepolia')));
      }
    });

    test('Sepolia warning still mentions Sepolia + testnet', () {
      final warn = receivePanelAssetWarningFor(
        kEvmNetworkEthereumSepolia, 'ETH',
      );
      expect(warn.toLowerCase(), contains('sepolia'));
      expect(warn.toLowerCase(), contains('testnet'));
    });

    test('Mainnet token shared address banner mentions mainnet', () {
      final banner = receivePanelTokenSharedBannerFor(
        kEvmNetworkEthereumMainnet,
      );
      expect(banner, contains('Ethereum Mainnet'));
      expect(banner.toLowerCase(), isNot(contains('sepolia')));
    });

    test('Sepolia token shared address banner mentions sepolia', () {
      final banner = receivePanelTokenSharedBannerFor(
        kEvmNetworkEthereumSepolia,
      );
      expect(banner.toLowerCase(), contains('sepolia'));
    });

    test('Mainnet gas note mentions ETH for gas', () {
      expect(
        kTokenReceiveGasNoteMainnet.toLowerCase(),
        contains('gas'),
      );
      expect(
        kTokenReceiveGasNoteMainnet.toLowerCase(),
        contains('eth'),
      );
    });

    test('Mainnet network label reads "Ethereum Mainnet"', () {
      expect(
        receivePanelNetworkLabelFor(kEvmNetworkEthereumMainnet),
        equals('Ethereum Mainnet'),
      );
    });

    test('Mainnet badge does NOT include "Do not send mainnet ETH" language',
        () {
      final badge = receivePanelNetworkBadgeFor(kEvmNetworkEthereumMainnet);
      expect(badge.toLowerCase(),
          isNot(contains('do not send mainnet')));
    });
  });

  group('non-exchange surface guarantees', () {
    test('Copy strings never contain buy/sell/swap/trade/stake/bridge', () {
      final blobs = [
        kEthReceiveAssetWarningMainnet,
        kTokenReceiveAssetWarningMainnetTemplate,
        kTokenReceiveSharedAddressBannerMainnet,
        kTokenReceiveGasNoteMainnet,
        kEvmNetworkMainnetDashboardChipLabel,
        kEvmNetworkSepoliaDashboardChipLabel,
      ];
      for (final b in blobs) {
        final lower = b.toLowerCase();
        for (final banned in ['swap', 'stake', 'bridge',
                              'trade', 'buy ', 'sell ']) {
          expect(lower, isNot(contains(banned)),
              reason: 'Copy leaked banned language: $b');
        }
      }
    });
  });
}
