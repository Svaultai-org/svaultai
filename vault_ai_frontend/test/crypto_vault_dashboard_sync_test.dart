


import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


CryptoWalletFeatures _features({
  bool mainnetReceiveEnabled = true,
  bool mainnetErc20ReceiveEnabled = true,
  bool solanaEnabled = false,
  bool tronEnabled = false,
  bool xmrEnabled = false,
}) {
  return CryptoWalletFeatures(
    walletEngineEnabled: true,
    sepoliaReceiveEnabled: true,
    sepoliaSendEnabled: false,
    mainnetReceiveEnabled: mainnetReceiveEnabled,
    mainnetErc20ReceiveEnabled: mainnetErc20ReceiveEnabled,
    mainnetSendEnabled: false,
    mainnetSendPaused: false,
    defaultNetwork: 'ethereum_mainnet',
    defaultNetworkConfigValid: true,
    solanaEnabled: solanaEnabled,
    solanaReceiveEnabled: solanaEnabled,
    solanaBalanceEnabled: solanaEnabled,
    solanaSendEnabled: false,
    solanaSendPaused: false,
    solanaActivityConnected: false,
    solanaStatusReady: false,
    solanaFeeReady: false,
    tronEnabled: tronEnabled,
    tronReceiveEnabled: tronEnabled,
    tronBalanceEnabled: tronEnabled,
    tronSendEnabled: false,
    tronSendPaused: false,
    tronActivityConnected: false,
    tronUsdtContractConfigured: tronEnabled,
    xmrEnabled: xmrEnabled,
    xmrReceiveEnabled: xmrEnabled,
    xmrBalanceEnabled: false,
    xmrSendEnabled: false,
    xmrActivityConnected: false,
    xmrScannerMode: 'none',
    xmrClientScannerSupported: false,
    xmrBackendScannerEnabled: false,
    supportedNetworks: const [],
    supportedAssetsByNetwork: const {},
  );
}


void main() {


  group('Part A — initial fan-out picks the right closed-set of live assets '
      'from CryptoWalletFeatures', () {

    test('mainnet + erc20 enabled → ETH + USDT_ERC20 + USDC_ERC20', () {
      final f = _features(
        mainnetReceiveEnabled: true, mainnetErc20ReceiveEnabled: true,
      );
      final assets = dashboardAssetsForInitialLiveRefresh(f);
      expect(assets, containsAll(['ETH', 'USDT_ERC20', 'USDC_ERC20']));
      expect(assets, isNot(contains('XMR')),
          reason: 'XMR is scanner-only, no receive+balance route.');
    });

    test('SOL live only when solanaEnabled', () {
      expect(
        dashboardAssetsForInitialLiveRefresh(_features(solanaEnabled: false)),
        isNot(contains('SOL')),
      );
      expect(
        dashboardAssetsForInitialLiveRefresh(_features(solanaEnabled: true)),
        contains('SOL'),
      );
    });

    test('USDT_TRC20 live only when tronEnabled', () {
      expect(
        dashboardAssetsForInitialLiveRefresh(_features(tronEnabled: false)),
        isNot(contains('USDT_TRC20')),
      );
      expect(
        dashboardAssetsForInitialLiveRefresh(_features(tronEnabled: true)),
        contains('USDT_TRC20'),
      );
    });

    test('mainnetReceiveEnabled=false drops ETH from fan-out', () {
      final assets = dashboardAssetsForInitialLiveRefresh(
        _features(mainnetReceiveEnabled: false),
      );
      expect(assets, isNot(contains('ETH')));
    });

    test('mainnetErc20ReceiveEnabled=false drops USDT_ERC20 + USDC_ERC20', () {
      final assets = dashboardAssetsForInitialLiveRefresh(
        _features(mainnetErc20ReceiveEnabled: false),
      );
      expect(assets, isNot(contains('USDT_ERC20')));
      expect(assets, isNot(contains('USDC_ERC20')));
    });
  });


  group('Part A — engine page wires the fan-out into _loadFeatures + '
      'per-asset refresh into detail-pop', () {

    test('_loadFeatures schedules _fanOutInitialLiveRefresh', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(
        src.contains('_fanOutInitialLiveRefresh()'),
        isTrue,
        reason: 'features load path must fan-out per-asset live '
            'refresh so dashboard cards match reality on open.',
      );
      expect(
        src.contains('dashboardAssetsForInitialLiveRefresh('),
        isTrue,
        reason: 'the fan-out helper must be the source of the '
            'per-asset list — no ad-hoc string literals in the '
            'engine page.',
      );
    });

    test('_openAssetDetail .then now also fires onAssetLiveRefreshRequested',
        () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf('void _openAssetDetail(BuildContext ctx');
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 3500);


      final thenIdx = scope.indexOf('.then((_) {');
      expect(thenIdx, greaterThan(0));
      final thenScope = scope.substring(thenIdx, thenIdx + 500);

      expect(
        thenScope.contains('onAssetLiveRefreshRequested?.call(asset)'),
        isTrue,
        reason: 'returning from detail page must refresh that '
            'asset\'s dashboard card so the two views agree.',
      );
      expect(
        thenScope.contains('onFeatureRefreshRequested?.call()'),
        isTrue,
        reason: 'features envelope refresh must still fire.',
      );
    });
  });


  group('Part C — shared receive+balance loader is the single source of '
      'truth for both dashboard and detail flows', () {

    test('loadWalletReceiveAndBalance returns closed-set '
        'DashboardAssetLiveState kinds', () {


      final f = loadWalletReceiveAndBalance;
      expect(f, isA<Function>());


      const noWallet = DashboardAssetLiveState.noWallet();
      const loading = DashboardAssetLiveState.loading();
      const avail = DashboardAssetLiveState.available(
        amount: '0', unit: 'ETH',
      );
      const reason = DashboardAssetLiveState.reason(reason: 'rpc_error');
      expect(noWallet.kind, DashboardAssetLiveStateKind.noWallet);
      expect(loading.kind, DashboardAssetLiveStateKind.loading);
      expect(avail.kind, DashboardAssetLiveStateKind.available);
      expect(reason.kind, DashboardAssetLiveStateKind.reason);
      expect(avail.hasAvailableBalance, isTrue);
      expect(reason.hasAvailableBalance, isFalse);
    });

    test('_refreshLiveAssetState delegates to the shared loader '
        '(loadAssetWalletState)',
        () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf(
        'Future<void> _refreshLiveAssetState(String asset) async',
      );
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 1600);



      expect(
        scope.contains('loadAssetWalletState('),
        isTrue,
        reason: 'engine page must NOT reimplement the receive+balance '
            'wire — it must delegate to the shared helper so dashboard '
            'and detail cannot disagree.',
      );
    });
  });


  group('Part B — Vault balance card rendering under different live states',
      () {

    test('Vault balance card render source has the three closed-set '
        'branches: hasAvailable, anyLoading, no-wallets fallback', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf('Widget _buildPortfolioSummary()');
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 6500);

      expect(
        scope.contains('if (hasAvailable) ...['),
        isTrue,
        reason: 'when any real balance is available, render per-asset '
            'rows — never keep the "Create wallets…" copy up.',
      );
      expect(
        scope.contains('else if (anyLoading) ...['),
        isTrue,
        reason: 'render skeleton rows while balances are still loading.',
      );
      expect(
        scope.contains(
          'crypto_wallet_engine_portfolio_no_wallets_body',
        ),
        isTrue,
        reason: 'the no-wallets copy must remain as the final fallback.',
      );
    });

    test('per-asset row + skeleton row builders live in the file', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(src.contains('_buildPortfolioBalanceRow('), isTrue);
      expect(src.contains('_buildPortfolioSkeletonRow('), isTrue);
      expect(src.contains('class _PortfolioBalanceRow'), isTrue);
    });

    test('mixed-state warning is now a COMPACT CHIP (polish pass) — '
        'the long sentence is gone', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');



      expect(
        src.contains('Some balances are temporarily unavailable.'),
        isFalse,
        reason: 'the polish pass replaces the long sentence with the '
            'compact "N balance(s) unavailable" chip.',
      );

      expect(src.contains('_buildPortfolioUnavailableChip('), isTrue,
          reason: 'compact chip builder must be wired');
      expect(
        src.contains("'crypto_wallet_engine_portfolio_unavailable_chip'"),
        isTrue,
        reason: 'chip must have a stable widget key for tests',
      );
    });

    test('no synthetic USD total is added in the has-available branch',
        () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf('Widget _buildPortfolioSummary()');
      final scope = src.substring(start, start + 6500);


      final ifIdx = scope.indexOf('if (hasAvailable) ...[');
      expect(ifIdx, greaterThan(0));
      final closeIdx = scope.indexOf('] else if (anyLoading)', ifIdx);
      expect(closeIdx, greaterThan(ifIdx));
      final availBranch = scope.substring(ifIdx, closeIdx);


      expect(
        availBranch.contains(r'$'),
        isFalse,
        reason: 'no dollar sign should appear in the available branch — '
            'no fake USD conversion.',
      );
      expect(
        availBranch.toLowerCase().contains('usd total'),
        isFalse,
        reason: 'no "USD total" label in the available branch.',
      );
      expect(
        availBranch.contains('kCryptoWalletEnginePortfolioHonestSubcopy'),
        isFalse,
        reason: 'the trailing honest subcopy was removed — per-asset '
            'rows tell the whole story on their own.',
      );
    });
  });
}
