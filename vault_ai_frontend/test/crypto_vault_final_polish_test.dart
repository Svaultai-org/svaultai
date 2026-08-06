


import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


CryptoWalletFeatures _features({
  bool mainnetReceive = true,
  bool mainnetErc20 = true,
  bool mainnetSendEnabled = false,
  bool mainnetSendPaused = false,
  bool solanaEnabled = true,
  bool solanaSendEnabled = false,
  bool solanaSendPaused = false,
  bool solanaActivityConnected = false,
  bool tronEnabled = true,
  bool tronBalanceEnabled = true,
  bool tronSendEnabled = false,
  bool tronSendPaused = false,
  bool tronActivityConnected = false,
  bool tronUsdtContractConfigured = true,
  bool xmrEnabled = true,
}) {
  return CryptoWalletFeatures.fromBackend(<String, dynamic>{
    'mainnetReceiveEnabled':      mainnetReceive,
    'mainnetErc20ReceiveEnabled': mainnetErc20,
    'mainnetSendEnabled':         mainnetSendEnabled,
    'mainnetSendPaused':          mainnetSendPaused,
    'solanaEnabled':              solanaEnabled,
    'solanaSendEnabled':          solanaSendEnabled,
    'solanaSendPaused':           solanaSendPaused,
    'solanaActivityConnected':    solanaActivityConnected,
    'tronEnabled':                tronEnabled,
    'tronBalanceEnabled':         tronBalanceEnabled,
    'tronSendEnabled':            tronSendEnabled,
    'tronSendPaused':             tronSendPaused,
    'tronActivityConnected':      tronActivityConnected,
    'tronUsdtContractConfigured': tronUsdtContractConfigured,
    'xmrEnabled':                 xmrEnabled,
    'defaultNetwork':             'ethereum_mainnet',
    'defaultNetworkConfigValid':  true,
  });
}


void main() {


  group('Part B — Vault balance card compact row layout', () {

    test('portfolioRowAssetName maps every asset to the polished name', () {
      expect(portfolioRowAssetName('ETH'),        'Ethereum');
      expect(portfolioRowAssetName('USDT_ERC20'), 'USDT');
      expect(portfolioRowAssetName('USDC_ERC20'), 'USDC');
      expect(portfolioRowAssetName('SOL'),        'Solana');
      expect(portfolioRowAssetName('USDT_TRC20'), 'USDT');
      expect(portfolioRowAssetName('XMR'),        'Monero');
    });

    test('portfolioRowNetworkTag surfaces distinguishing tag ONLY where '
        'the asset lives on a specific chain sub-network', () {
      expect(portfolioRowNetworkTag('ETH'),        'Mainnet');
      expect(portfolioRowNetworkTag('USDT_ERC20'), 'ERC20');
      expect(portfolioRowNetworkTag('USDC_ERC20'), 'ERC20');
      expect(portfolioRowNetworkTag('USDT_TRC20'), 'TRC20');


      expect(portfolioRowNetworkTag('SOL'), isNull,
          reason: 'Solana is its own network — no sub-network tag');
    });

    test('portfolioUnavailableChipLabel is compact and singular/plural '
        'aware', () {
      expect(portfolioUnavailableChipLabel(1), '1 balance unavailable');
      expect(portfolioUnavailableChipLabel(2), '2 balances unavailable');
      expect(portfolioUnavailableChipLabel(0), '');
    });

    test('vault balance card render source uses the compact chip helper — '
        'NOT the old long sentence', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');

      expect(
        src.contains(
          "'Some balances are temporarily unavailable.'",
        ),
        isFalse,
        reason: 'the long sentence must be gone — replaced by a compact '
            'chip so the card feels finished.',
      );
      expect(
        src.contains('_buildPortfolioUnavailableChip('),
        isTrue,
        reason: 'the vault balance card must call the compact chip '
            'builder for the unavailable-count indicator.',
      );



      final buildIdx = src.indexOf('Widget _buildPortfolioSummary(BuildContext context)');
      expect(buildIdx, greaterThan(0));
      final scope = src.substring(buildIdx, buildIdx + 2500);
      expect(
        scope.contains('erroredCount'),
        isTrue,
        reason: 'the summary must count errored assets so the chip can '
            'say "1" vs "N".',
      );
    });

    test('per-row layout renders assetName and network tag from the '
        'shared helpers, not a hardcoded label', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final buildIdx = src.indexOf(
        'Widget _buildPortfolioBalanceRow(_PortfolioBalanceRow row)',
      );
      expect(buildIdx, greaterThan(0));
      final scope = src.substring(buildIdx, buildIdx + 2500);

      expect(scope.contains('portfolioRowAssetName(row.asset)'), isTrue);
      expect(scope.contains('portfolioRowNetworkTag(row.asset)'), isTrue);
    });

    test('no synthetic USD total leaks into the polished summary '
        'source', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final buildIdx = src.indexOf('Widget _buildPortfolioSummary(BuildContext context)');
      final scope = src.substring(buildIdx, buildIdx + 3500);

      expect(scope.contains(r'$USD'), isFalse);
      expect(scope.contains('total_usd'), isFalse);
      expect(scope.contains('synthetic'), isFalse);




      expect(
        scope.contains('kCryptoWalletEnginePortfolioHonestSubcopy'),
        isFalse,
        reason: 'the extra "SVaultAI only shows real on-chain balances" '
            'line is redundant — per-asset rows already tell the story.',
      );
      expect(
        scope.contains('kCryptoWalletEnginePortfolioLiveBalancesNoteMainnet'),
        isFalse,
        reason: 'the extra "Live balances shown from connected Mainnet '
            'networks." line was removed — the portfolio is enough.',
      );
    });
  });



  group('Part C — Activity copy is compact + honest', () {

    test('vault activity section polished copy is now the friendly '
        '"No activity yet." primary + subcopy pair (was the long '
        '"Vault activity will show real transactions" sentence)', () {

      expect(
        kCryptoWalletEngineActivityEmptyPrimary,
        'No activity yet.',
      );
      expect(
        kCryptoWalletEngineActivityEmptySubcopy,
        'Real transactions will appear here when activity history is '
        'connected.',
      );
      expect(
        kCryptoWalletEngineActivityHonestSubcopy,
        'SVaultAI never invents transaction history.',
      );



      expect(kCryptoWalletEngineActivityEmptyPrimary.length, lessThan(40));
      expect(kCryptoWalletEngineActivityEmptySubcopy.length, lessThan(160));
      expect(kCryptoWalletEngineActivityHonestSubcopy.length, lessThan(120));
    });

    test('activity section source renders three-line pair under stable '
        'keys (primary + subcopy + honesty)', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final buildIdx = src.indexOf('Widget _buildActivitySection()');
      expect(buildIdx, greaterThan(0));
      final scope = src.substring(buildIdx, buildIdx + 1800);



      expect(
        scope.contains(
          "Key('crypto_wallet_engine_activity_empty_primary')",
        ),
        isTrue,
      );
      expect(
        scope.contains(
          "Key('crypto_wallet_engine_activity_empty_subcopy')",
        ),
        isTrue,
      );
      expect(
        scope.contains(
          "Key('crypto_wallet_engine_activity_honest_subcopy')",
        ),
        isTrue,
      );


      expect(scope.contains('Transaction history not connected yet.'),
          isFalse);
      expect(
        scope.contains(
          'Vault activity will show real transactions once an indexer',
        ),
        isFalse,
      );
    });

    test('asset card activity chip has a closed set of 4 kinds — the '
        'default is the friendly "No activity yet"', () {

      expect(
        dashboardCardActivityChipCopy(DashboardCardActivityKind.empty),
        'No activity yet',
      );



      expect(
        kCryptoWalletEngineAssetCardActivityUnavailableCompact,
        'Activity history not connected',
        reason: 'the deprecated symbol now aliases the '
            'indexer-missing label — the old "Activity unavailable" '
            'string is retired.',
      );
    });

    test('asset card render uses the kind-driven chip helper — not the '
        'flat old const', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final chipRegex = RegExp(
        r'crypto_wallet_engine_card_activity_chip_\$asset',
      );
      expect(chipRegex.hasMatch(src), isTrue,
          reason: 'chip render must be wired under the new stable key');



      final chipStart = src.indexOf(
        'crypto_wallet_engine_card_activity_chip_\$asset',
      );
      expect(chipStart, greaterThan(0));


      final scopeStart = (chipStart - 500).clamp(0, src.length).toInt();
      final scopeEnd = (chipStart + 1000 < src.length)
          ? chipStart + 1000 : src.length;
      final scope = src.substring(scopeStart, scopeEnd);
      expect(
        scope.contains('dashboardCardActivityChipCopy('),
        isTrue,
        reason: 'the render must consult the closed-set helper.',
      );
      expect(
        scope.contains('dashboardCardActivityKind('),
        isTrue,
        reason: 'the render must consult the closed-set kind resolver.',
      );
      expect(
        scope.contains('capability.transactionsUnavailableReason!'),
        isFalse,
        reason: 'the card must not inline the long unavailable-reason '
            'text — that reason is only used in the semantic capability '
            'model, not in the compact chip rendered on the card.',
      );
    });
  });



  group('Part D — Send button reflects real send readiness', () {

    test('ETH send hidden unless mainnetSendEnabled AND not paused', () {
      final off = dashboardAssetActionCapability(
        asset: 'ETH', features: _features(mainnetSendEnabled: false),
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(off.send, isFalse);
      expect(off.sendUnavailableReason,
          kAssetSendUnavailableMainnetDisabled);

      final paused = dashboardAssetActionCapability(
        asset: 'ETH',
        features: _features(
          mainnetSendEnabled: true, mainnetSendPaused: true,
        ),
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(paused.send, isFalse);
      expect(paused.sendUnavailableReason,
          kAssetSendUnavailableMainnetPaused);

      final on = dashboardAssetActionCapability(
        asset: 'ETH',
        features: _features(mainnetSendEnabled: true),
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(on.send, isTrue);
      expect(on.sendUnavailableReason, isNull);
    });

    test('SOL send hidden unless solanaSendEnabled AND not paused', () {
      final off = dashboardAssetActionCapability(
        asset: 'SOL', features: _features(solanaSendEnabled: false),
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(off.send, isFalse);

      final on = dashboardAssetActionCapability(
        asset: 'SOL',
        features: _features(solanaSendEnabled: true),
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(on.send, isTrue);
    });

    test('USDT_TRC20 send REQUIRES provider readiness (TRON balance '
        'enabled + contract configured) — not just send flag',
        () {

      final providerHalfConfigured = dashboardAssetActionCapability(
        asset: 'USDT_TRC20',
        features: _features(
          tronSendEnabled: true,
          tronBalanceEnabled: false,
        ),
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(providerHalfConfigured.send, isFalse,
          reason: 'send must NOT appear active if TRON balance provider '
              'is not ready — the send flow would immediately fail on '
              'draft/preflight.');
      expect(
        providerHalfConfigured.sendUnavailableReason,
        kAssetSendUnavailableTronProviderNotReady,
      );



      final noContract = dashboardAssetActionCapability(
        asset: 'USDT_TRC20',
        features: _features(
          tronSendEnabled: true,
          tronUsdtContractConfigured: false,
        ),
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(noContract.send, isFalse);
      expect(
        noContract.sendUnavailableReason,
        kAssetSendUnavailableTronProviderNotReady,
      );



      final ok = dashboardAssetActionCapability(
        asset: 'USDT_TRC20',
        features: _features(tronSendEnabled: true),
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(ok.send, isTrue);
      expect(ok.sendUnavailableReason, isNull);
    });

    test('XMR never has an active Send button — Monero send is not '
        'enabled yet', () {
      final f = _features(xmrEnabled: true);
      final cap = dashboardAssetActionCapability(
        asset: 'XMR', features: f,
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(cap.send, isFalse,
          reason: 'Monero sending is not enabled yet — hard rule');
      expect(cap.sendUnavailableReason, kAssetSendUnavailableMonero);
    });

    test('"Send not ready" copy is short — must fit in a small chip', () {
      expect(
        kAssetSendUnavailableTronProviderNotReady.length,
        lessThan(30),
        reason: 'the not-ready fallback must be short enough to render '
            'in a compact chip, not a full sentence.',
      );
    });
  });



  group('Part E — no exchange/trading words leaked into any new copy', () {

    test('polished portfolio, activity, and send copy never mention '
        'buy/sell/swap/trade/stake/bridge/exchange', () {
      const banned = ['buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
                      'exchange', 'convert'];
      final strings = <String>[
        portfolioUnavailableChipLabel(1),
        portfolioUnavailableChipLabel(2),
        kCryptoWalletEngineActivityHonestEmpty,
        kCryptoWalletEngineActivityHonestSubcopy,
        kCryptoWalletEngineAssetCardActivityUnavailableCompact,
        kAssetSendUnavailableTronProviderNotReady,
      ];
      for (final s in strings) {
        final low = s.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'copy "$s" leaks "$b"');
        }
      }
    });
  });
}
