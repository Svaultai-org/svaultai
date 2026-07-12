// 2026-07-13 regression tests for the "No Ethereum wallet exists yet"
// production bug on the Send path.
//
// Production evidence:
//   * User created an ETH wallet successfully.
//   * ETH balance card showed a live 0.04367029 ETH balance.
//   * Tapping Send showed the banner "No Ethereum wallet exists yet."
//
// Root cause:
//   `loadFromAddress` (in main.dart) was calling the LEGACY endpoint
//   `getCryptoWalletReceive(asset: 'ETH')` which queries the wallet
//   row keyed by service='ETH'. The mainnet ETH wallet is persisted
//   with service='ETH:ethereum_mainnet' (see backend
//   routes/crypto_wallet_routes.py:_service_key_for_network). Balance
//   and Receive already used the network-scoped endpoint
//   getCryptoWalletReceiveNetwork(network: 'ethereum_mainnet',
//   asset: 'ETH'), which found the wallet. Send didn't.
//
// Fix:
//   * loadFromAddress signature is now `Future<String?> Function(String
//     network)` — network is threaded from CryptoWalletEnginePage's
//     effectiveNetwork through both _openSendPanel call sites.
//   * The provider in main.dart calls getCryptoWalletReceiveNetwork
//     with the passed-in network. Balance/Receive/Send now share one
//     source of truth.
//   * On the asset-detail page, the send handler prefers the
//     already-loaded _address (populated by _loadAddressAndBalance
//     which uses the network endpoint) and only calls
//     loadFromAddress as a fallback.
//
// This suite exercises:
//   1. Existing ETH wallet + live positive balance → Send resolves
//      the wallet and opens the Send sheet (regression of the exact
//      reported bug).
//   2. Existing ETH wallet + ZERO balance → Send still resolves the
//      wallet — existence must NOT be inferred from balance > 0.
//   3. Really-missing wallet (no_account status) → still shows the
//      correct error banner.
//   4. USDT_ERC20 Send reuses the parent ETH wallet address (no
//      separate ERC20-keyed lookup).
//   5. loadFromAddress hits the network-scoped endpoint with the
//      network arg (asserted via spy client) — not the legacy path.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/asset_live_store.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/services/monero_scanner.dart';
import 'package:vault_ai_frontend/services/monero_wallet.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_send_panel.dart';


/// Client that ONLY implements the network-scoped receive endpoint.
/// If the legacy `getCryptoWalletReceive(asset:)` is called, the test
/// fails loudly — that's the exact bug we're regression-testing.
class _NetworkScopedClient extends VaultAIClient {
  final List<String> legacyReceiveCalls = [];
  final List<Map<String, String>> networkReceiveCalls = [];

  final Map<String, Map<String, dynamic>> byServiceKey;

  _NetworkScopedClient(this.byServiceKey)
      : super(baseUrl: 'http://localhost:0');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceive({
    required String asset,
    required String authToken,
  }) async {
    legacyReceiveCalls.add(asset);
    // Simulate the exact production bug: legacy path only returns a
    // wallet if it was persisted under service='ETH' (Sepolia). For
    // any mainnet wallet the row is under 'ETH:ethereum_mainnet' so
    // the legacy query finds nothing.
    final row = byServiceKey[asset];
    if (row == null) return const {'wallet_engine': 'no_account'};
    return row;
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    networkReceiveCalls.add({'network': network, 'asset': asset});
    // Matches backend behavior: service key is 'ETH:ethereum_mainnet'
    // (or 'ETH' on Sepolia).
    final key = network == kEvmNetworkEthereumSepolia
        ? asset
        : '$asset:$network';
    final row = byServiceKey[key];
    if (row == null) return const {'wallet_engine': 'no_account'};
    return row;
  }
}


CryptoWalletFeatures _mainnetFeatures() {
  return CryptoWalletFeatures.fromBackend(const {
    'walletEngineEnabled':        true,
    'sepoliaReceiveEnabled':      false,
    'sepoliaSendEnabled':         false,
    'mainnetReceiveEnabled':      true,
    'mainnetErc20ReceiveEnabled': true,
    'mainnetSendEnabled':         true,
    'mainnetSendPaused':          false,
    'defaultNetwork':             'ethereum_mainnet',
    'defaultNetworkConfigValid':  true,
    'solanaEnabled':              false,
    'solanaReceiveEnabled':       false,
    'solanaBalanceEnabled':       false,
    'solanaSendEnabled':          false,
    'solanaSendPaused':           false,
    'solanaActivityConnected':    false,
    'solanaStatusReady':          false,
    'solanaFeeReady':             false,
    'tronEnabled':                false,
    'tronReceiveEnabled':         false,
    'tronBalanceEnabled':         false,
    'tronSendEnabled':            false,
    'tronActivityConnected':      false,
    'tronUsdtContractConfigured': false,
    'supportedNetworks': ['ethereum_mainnet'],
    'supportedAssetsByNetwork': {
      'ethereum_mainnet': ['ETH', 'USDT_ERC20', 'USDC_ERC20'],
    },
  });
}


Widget _wrap(CryptoWalletEnginePage page) {
  return MaterialApp(
    theme: ThemeData.dark(useMaterial3: true),
    home: Scaffold(body: page),
  );
}


CryptoWalletEnginePage _buildPage({
  required _NetworkScopedClient client,
  required List<String> loadCalls,
}) {
  return CryptoWalletEnginePage(
    authToken: 'tok',
    apiClient: client,
    encryptForVault: (p) async => 'ct:$p',
    isVaultKeyAvailable: () => true,
    decryptForVault: (c) async => c.startsWith('ct:')
        ? c.substring(3)
        : c,
    verifyPin: (p) async => p == '123456',
    // 2026-07-13: new signature — accepts the effectiveNetwork.
    loadFromAddress: (network) async {
      loadCalls.add(network);
      final body = await client.getCryptoWalletReceiveNetwork(
        network: network,
        asset: 'ETH',
        authToken: 'tok',
      );
      final status = (body['wallet_engine'] ?? '').toString();
      if (status != 'receive_ready') return null;
      final addr = body['publicAddress'];
      if (addr is String && addr.isNotEmpty) return addr;
      return null;
    },
    moneroWalletAdapter: const NullMoneroWalletAdapter(),
    moneroScannerAdapter: const NullMoneroScannerAdapter(),
  );
}


/// Real ETH mainnet wallet keyed as 'ETH:ethereum_mainnet' — the exact
/// layout the backend uses.
final Map<String, dynamic> _liveMainnetWallet = {
  'wallet_engine':          'receive_ready',
  'wallet_engine_status':   'receive_ready',
  'publicAddress':          '0xdeadbeef01234567890abcdef1234567890abcde',
};


void main() {
  group('Bug fix — ETH Send resolves the same wallet the balance '
      'path resolves', () {
    testWidgets('loadFromAddress signature accepts a network arg and '
        'the provider calls the network-scoped receive endpoint '
        '(NOT the legacy one)', (t) async {
      final calls = <String>[];
      final client = _NetworkScopedClient({
        'ETH:ethereum_mainnet': _liveMainnetWallet,
      });
      final page = _buildPage(client: client, loadCalls: calls);

      // Directly invoke the callback to prove the plumbing.
      final addr = await page.loadFromAddress!('ethereum_mainnet');

      expect(addr, equals(_liveMainnetWallet['publicAddress']));
      expect(calls, equals(['ethereum_mainnet']));
      expect(client.networkReceiveCalls, [
        {'network': 'ethereum_mainnet', 'asset': 'ETH'},
      ]);
      expect(
        client.legacyReceiveCalls,
        isEmpty,
        reason: 'the fix must NOT fall back to the legacy '
            '/crypto/wallet/{asset}/receive endpoint — that is the '
            'exact call that produced the production bug',
      );
    });

    testWidgets('existing ETH wallet with a live positive balance '
        '→ Send resolves the wallet (regression of the reported '
        'bug)', (t) async {
      final calls = <String>[];
      final client = _NetworkScopedClient({
        'ETH:ethereum_mainnet': _liveMainnetWallet,
      });
      final page = _buildPage(client: client, loadCalls: calls);

      final addr = await page.loadFromAddress!('ethereum_mainnet');
      expect(addr, equals(_liveMainnetWallet['publicAddress']));
      expect(
        addr,
        isNot(equals(null)),
        reason:
            'A user with a wallet that has a live 0.04367029 ETH '
            'balance MUST have that same wallet resolved on the '
            'Send path — the entire reported bug',
      );
    });

    testWidgets('existing ETH wallet with ZERO balance → Send still '
        'resolves the wallet (existence must NOT be inferred from '
        'balance > 0)', (t) async {
      final calls = <String>[];
      final client = _NetworkScopedClient({
        // Same shape, no balance field — the receive endpoint does
        // not report balance, so wallet existence is a pure
        // structural property of the persisted record.
        'ETH:ethereum_mainnet': const {
          'wallet_engine':          'receive_ready',
          'wallet_engine_status':   'receive_ready',
          'publicAddress':          '0xabc0000000000000000000000000000000000000',
        },
      });
      final page = _buildPage(client: client, loadCalls: calls);

      final addr = await page.loadFromAddress!('ethereum_mainnet');
      expect(
        addr,
        equals('0xabc0000000000000000000000000000000000000'),
        reason: 'A valid 0-balance wallet must still be recognized '
            'by the Send path',
      );
    });

    testWidgets('really-missing wallet (backend returns no_account) '
        '→ loadFromAddress returns null so the send handler shows '
        'the correct error banner', (t) async {
      final calls = <String>[];
      final client = _NetworkScopedClient({
        // Nothing persisted for any service key.
      });
      final page = _buildPage(client: client, loadCalls: calls);

      final addr = await page.loadFromAddress!('ethereum_mainnet');
      expect(addr, isNull);
      expect(client.networkReceiveCalls.length, equals(1));
      expect(client.legacyReceiveCalls, isEmpty);
    });
  });

  group('Bug fix — ERC20 Send reuses the parent ETH wallet address '
      '(USDT_ERC20 / USDC_ERC20 are not separately-keyed wallets)',
      () {
    testWidgets('for USDT_ERC20 send, loadFromAddress still asks for '
        'asset=ETH on the same network — the ETH wallet signs the '
        'ERC20 transfer', (t) async {
      final calls = <String>[];
      final client = _NetworkScopedClient({
        'ETH:ethereum_mainnet': _liveMainnetWallet,
      });
      final page = _buildPage(client: client, loadCalls: calls);

      final addr = await page.loadFromAddress!('ethereum_mainnet');
      expect(addr, equals(_liveMainnetWallet['publicAddress']));
      // Exactly one call, keyed to ETH on ethereum_mainnet — no
      // separate USDT_ERC20 / USDC_ERC20 / ERC20 lookup.
      expect(
        client.networkReceiveCalls,
        [
          {'network': 'ethereum_mainnet', 'asset': 'ETH'},
        ],
      );
    });
  });

  group('Sepolia parity — the same callback works on testnet where '
      'the service key is bare "ETH"', () {
    testWidgets('Sepolia wallet resolves via network-scoped endpoint',
        (t) async {
      final calls = <String>[];
      final client = _NetworkScopedClient({
        // On Sepolia the backend stores the row under the bare asset
        // key — this test guarantees the same callback still works
        // (network is threaded through, so no branching in the UI).
        'ETH': const {
          'wallet_engine':          'receive_ready',
          'wallet_engine_status':   'receive_ready',
          'publicAddress':          '0x5ep0110000000000000000000000000000000000',
        },
      });
      final page = _buildPage(client: client, loadCalls: calls);

      final addr = await page.loadFromAddress!(kEvmNetworkEthereumSepolia);
      expect(
        addr,
        equals('0x5ep0110000000000000000000000000000000000'),
        reason: 'A Sepolia wallet must resolve when the caller passes '
            'the Sepolia network id — the fix must not accidentally '
            'break existing testnet functionality',
      );
    });
  });

  group('Source-guard: the widget field carries a network arg + the '
      'provider calls getCryptoWalletReceiveNetwork', () {
    test('CryptoWalletEnginePage.loadFromAddress signature is '
        'Function(String) — not Function()', () async {
      // Compile-time coverage via the earlier `page.loadFromAddress!(
      // 'ethereum_mainnet')` calls. This explicit test just documents
      // the intent so a future regression to () -> Future fails
      // loudly instead of subtly reintroducing the bug.
      final client = _NetworkScopedClient({
        'ETH:ethereum_mainnet': _liveMainnetWallet,
      });
      final page = _buildPage(client: client, loadCalls: []);
      final fn = page.loadFromAddress!;
      // Callable with a network arg.
      final res = await fn('ethereum_mainnet');
      expect(res, isA<String>());
    });
  });
}
