


import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_activity_card.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}




class _FakeVaultAIClient extends VaultAIClient {
  final Map<String, dynamic> Function()? receiveResponseBuilder;
  final Object Function()? receiveErrorBuilder;
  final Map<String, dynamic> Function()? balanceResponseBuilder;
  final Object Function()? balanceErrorBuilder;
  final Duration receiveDelay;
  final Duration balanceDelay;

  int receiveCallCount = 0;
  int balanceCallCount = 0;
  String? lastBalanceAddress;

  _FakeVaultAIClient({
    this.receiveResponseBuilder,
    this.receiveErrorBuilder,
    this.balanceResponseBuilder,
    this.balanceErrorBuilder,
    this.receiveDelay = Duration.zero,
    this.balanceDelay = Duration.zero,
  }) : super(baseUrl: 'https://test.invalid');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    receiveCallCount++;
    if (receiveDelay > Duration.zero) {
      await Future<void>.delayed(receiveDelay);
    }
    if (receiveErrorBuilder != null) throw receiveErrorBuilder!();
    return receiveResponseBuilder!.call();
  }

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) async {
    balanceCallCount++;
    lastBalanceAddress = address;
    if (balanceDelay > Duration.zero) {
      await Future<void>.delayed(balanceDelay);
    }
    if (balanceErrorBuilder != null) throw balanceErrorBuilder!();
    return balanceResponseBuilder!.call();
  }
}


void main() {


  group('Shared loader — receive route response shape parsing', () {

    test('receive_ready + publicAddress → available balance', () async {
      final client = _FakeVaultAIClient(
        receiveResponseBuilder: () => {
          'wallet_engine': 'receive_ready',
          'publicAddress': '0xABCDEF0123456789',
          'asset': 'ETH',
          'network': 'Ethereum Mainnet',
        },
        balanceResponseBuilder: () => {
          'balanceStatus': 'available',
          'availableAmount': '0',
          'unit': 'ETH',
        },
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'valid-token',
        network: 'ethereum_mainnet',
        asset: 'ETH',
      );

      expect(result.kind, DashboardAssetLiveStateKind.available);
      expect(result.balanceAmount, '0');
      expect(result.balanceUnit, 'ETH');
      expect(result.hasAvailableBalance, isTrue);
      expect(client.receiveCallCount, 1);
      expect(client.balanceCallCount, 1);
      expect(client.lastBalanceAddress, '0xABCDEF0123456789');
    });

    test('backend returns no_account → noWallet (never call balance)',
        () async {
      final client = _FakeVaultAIClient(
        receiveResponseBuilder: () => {
          'wallet_engine': 'no_account',
          'asset': 'ETH',
        },
        balanceResponseBuilder: () => throw StateError(
          'balance should not be called when wallet does not exist',
        ),
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'valid-token',
        network: 'ethereum_mainnet',
        asset: 'ETH',
      );

      expect(result.kind, DashboardAssetLiveStateKind.noWallet);
      expect(client.receiveCallCount, 1);
      expect(client.balanceCallCount, 0,
          reason: 'balance MUST NOT be called when wallet does not '
              'exist yet.');
    });

    test('backend returns create_eth_mainnet_wallet_first for ERC20 → '
        'noWallet', () async {
      final client = _FakeVaultAIClient(
        receiveResponseBuilder: () => {
          'wallet_engine': 'create_eth_mainnet_wallet_first',
          'asset': 'USDT_ERC20',
        },
        balanceResponseBuilder: () => throw StateError('do not call'),
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'valid-token',
        network: 'ethereum_mainnet',
        asset: 'USDT_ERC20',
      );

      expect(result.kind, DashboardAssetLiveStateKind.noWallet);
      expect(client.balanceCallCount, 0);
    });

    test('receive_ready but empty publicAddress → noWallet', () async {
      final client = _FakeVaultAIClient(
        receiveResponseBuilder: () => {
          'wallet_engine': 'receive_ready',
          'publicAddress': '',
        },
        balanceResponseBuilder: () => throw StateError('do not call'),
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'valid-token',
        network: 'ethereum_mainnet',
        asset: 'ETH',
      );

      expect(result.kind, DashboardAssetLiveStateKind.noWallet);
    });
  });


  group('Shared loader — SEMANTIC BUG FIX — receive exception must not '
      'be confused with noWallet', () {

    test('receive throws generic Exception → reason(rpc_error), NEVER '
        'noWallet', () async {
      final client = _FakeVaultAIClient(
        receiveErrorBuilder: () => Exception(
          'Backend unreachable — status 500',
        ),
        balanceResponseBuilder: () => throw StateError('do not call'),
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'valid-token',
        network: 'ethereum_mainnet',
        asset: 'ETH',
      );

      expect(result.kind, DashboardAssetLiveStateKind.reason,
          reason: 'exception on the receive call must be surfaced as '
              'a diagnostic reason, NEVER as noWallet — masking the '
              'exception as noWallet was the root cause of the dashboard '
              'saying "Create wallet to view balance." when the wallet '
              'actually existed.');
      expect(result.backendReason, 'rpc_error');
      expect(client.balanceCallCount, 0,
          reason: 'balance MUST NOT be called when receive failed.');
    });

    test('receive throws TimeoutException → reason(receive_timeout), '
        'NEVER noWallet — distinguishable from generic rpc_error so '
        'the user knows it was a timeout, not a masked auth error',
        () async {
      final client = _FakeVaultAIClient(
        receiveDelay: const Duration(seconds: 30),
        receiveResponseBuilder: () => {'wallet_engine': 'receive_ready'},
        balanceResponseBuilder: () => throw StateError('do not call'),
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'valid-token',
        network: 'ethereum_mainnet',
        asset: 'ETH',
        receiveTimeout: const Duration(milliseconds: 50),
      );

      expect(result.kind, DashboardAssetLiveStateKind.reason);


      expect(result.backendReason, 'receive_timeout');
      expect(result.backendReason, isNot('rpc_error'),
          reason: 'a timeout must be distinguishable from a masked '
              'auth failure — user Rule 4.');
      expect(client.balanceCallCount, 0);
    });
  });


  group('Shared loader — balance route response shape parsing', () {

    test('available + availableAmount + unit → available', () async {
      final client = _FakeVaultAIClient(
        receiveResponseBuilder: () => {
          'wallet_engine': 'receive_ready',
          'publicAddress': '0xAAAA',
        },
        balanceResponseBuilder: () => {
          'balanceStatus': 'available',
          'availableAmount': '1.234',
          'unit': 'ETH',
        },
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'v',
        network: 'ethereum_mainnet',
        asset: 'ETH',
      );

      expect(result.kind, DashboardAssetLiveStateKind.available);
      expect(result.balanceAmount, '1.234');
      expect(result.balanceUnit, 'ETH');
    });

    test('backend uses fallback balance key → still available', () async {
      final client = _FakeVaultAIClient(
        receiveResponseBuilder: () => {
          'wallet_engine': 'receive_ready',
          'publicAddress': '0xAAAA',
        },
        balanceResponseBuilder: () => {
          'balanceStatus': 'available',

          'balance': '99',
          'unit': 'ETH',
        },
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'v',
        network: 'ethereum_mainnet',
        asset: 'ETH',
      );

      expect(result.kind, DashboardAssetLiveStateKind.available);
      expect(result.balanceAmount, '99');
    });

    test('unavailable + reason preserves the closed-set reason', () async {
      final client = _FakeVaultAIClient(
        receiveResponseBuilder: () => {
          'wallet_engine': 'receive_ready',
          'publicAddress': '0xAAAA',
        },
        balanceResponseBuilder: () => {
          'balanceStatus': 'unavailable',
          'reason': 'rpc_not_configured',
        },
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'v',
        network: 'ethereum_mainnet',
        asset: 'ETH',
      );

      expect(result.kind, DashboardAssetLiveStateKind.reason);
      expect(result.backendReason, 'rpc_not_configured');
    });

    test('balance throws → reason(rpc_error), noWallet is NOT returned',
        () async {
      final client = _FakeVaultAIClient(
        receiveResponseBuilder: () => {
          'wallet_engine': 'receive_ready',
          'publicAddress': '0xAAAA',
        },
        balanceErrorBuilder: () => Exception('server 500'),
      );

      final result = await loadWalletReceiveAndBalance(
        apiClient: client,
        authToken: 'v',
        network: 'ethereum_mainnet',
        asset: 'ETH',
      );

      expect(result.kind, DashboardAssetLiveStateKind.reason);
      expect(result.backendReason, 'rpc_error');
    });
  });


  group('Diagnostic dev logs are wired (kDebugMode-guarded, no secrets)',
      () {

    test('shared loader source has kDebugMode-guarded log emitter', () {
      final src = _readLib('services/crypto_wallet_dashboard_reason.dart');
      expect(src.contains("if (!kDebugMode) return"), isTrue);
      expect(src.contains("developer.log("), isTrue);
      expect(src.contains("name: 'CryptoVault'"), isTrue);
    });

    test('shared loader emits stable labels at every step of the flow',
        () {
      final src = _readLib('services/crypto_wallet_dashboard_reason.dart');
      for (final label in const [
        'live_refresh_started',
        'receive_response',
        'receive_call_failed',
        'live_refresh_result',
        'balance_available',
        'balance_unavailable',
        'balance_call_failed',
      ]) {
        expect(src.contains(label), isTrue,
            reason: 'missing diagnostic label: $label');
      }
    });

    test('engine page source has a _cvLog helper + logs the four gate '
        'points asked for by the operator', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(src.contains('void _cvLog('), isTrue);
      for (final label in const [
        'features_loaded',
        'features_failed',
        'fanout_start',
        'refresh_started',
        'refresh_done',
        'default_network=',
        'mainnet_receive=',
        'effective_network=',
      ]) {
        expect(src.contains(label), isTrue,
            reason: 'missing engine-page dev log fragment: $label');
      }
    });

    test('dev-log labels NEVER carry banned secret tokens', () {
      final srcs = [
        _readLib('services/crypto_wallet_dashboard_reason.dart'),
        _readLib('ui/crypto_wallet_engine_page.dart'),
      ];


      final labelRe = RegExp(
        r"(?:_walletBalanceDevLog|_cvLog|developer\.log)"
        r"\(\s*\n?\s*'([^']+)",
      );
      final labels = <String>[];
      for (final src in srcs) {
        for (final m in labelRe.allMatches(src)) {
          labels.add(m.group(1)!);
        }
      }
      expect(labels, isNotEmpty,
          reason: 'dev-log call sites must be present so the diagnostic '
              'logs surface at runtime.');


      for (final banned in const [
        'publicaddress', 'public_address', 'wallet_address',
        'wallet_addr', 'rpc_url', 'api_key', 'apikey',
        'authorization', 'bearer', 'private_key', 'privatekey',
        'seed_phrase', 'seedphrase', 'mnemonic', 'tx_hash', 'txhash',
        'encrypted_secret', 'stripe',
      ]) {
        for (final label in labels) {
          expect(label.toLowerCase().contains(banned), isFalse,
              reason: 'dev log label "$label" leaks "$banned"');
        }
      }
    });
  });


  group('Part D — activity empty/no-wallet copy is network-aware', () {

    test('Mainnet mode: empty copy is the polished "No activity yet." + '
        'Ethereum indexer subcopy — never leaks Sepolia',
        () {
      final empty = activityCopyEmptyForNetwork('ethereum_mainnet');



      expect(empty, contains('No activity yet'));
      expect(empty, contains('Ethereum'));
      expect(empty.toLowerCase(), isNot(contains('sepolia')));
      expect(empty.toLowerCase(), isNot(contains('testnet')));



      expect(
        activityCopyNoWalletYetForNetwork('ethereum_mainnet'),
        contains('Ethereum Mainnet'),
      );
      expect(
        activityCopyNoWalletYetForNetwork('ethereum_mainnet').toLowerCase(),
        isNot(contains('sepolia')),
      );
    });

    test('Sepolia mode still says Sepolia Testnet', () {
      expect(
        activityCopyEmptyForNetwork('ethereum_sepolia'),
        contains('Ethereum Sepolia Testnet'),
      );
      expect(
        activityCopyNoWalletYetForNetwork('ethereum_sepolia'),
        contains('Ethereum Sepolia Testnet'),
      );
    });

    test('unknown network → chain-agnostic default (no Sepolia leak)',
        () {
      expect(
        activityCopyEmptyForNetwork(null).toLowerCase(),
        isNot(contains('sepolia')),
      );
      expect(
        activityCopyEmptyForNetwork(null).toLowerCase(),
        isNot(contains('mainnet')),
      );
      expect(
        activityCopyNoWalletYetForNetwork(null).toLowerCase(),
        isNot(contains('sepolia')),
      );
    });

    test('activity card source no longer has the hardcoded '
        '"Ethereum Sepolia" leak', () {
      final src = _readLib('ui/crypto_wallet_engine_activity_card.dart');


      final renderScope = src.substring(src.indexOf('String _unavailableCopy'));
      expect(
        renderScope.contains("return kActivityCopyNoWalletYet;"),
        isFalse,
        reason: 'the render site must call '
            'activityCopyNoWalletYetForNetwork(widget.network), never '
            'the chain-agnostic const directly.',
      );
      expect(
        renderScope.contains('activityCopyNoWalletYetForNetwork'),
        isTrue,
      );
      expect(
        renderScope.contains('activityCopyEmptyForNetwork'),
        isTrue,
      );
    });
  });
}
