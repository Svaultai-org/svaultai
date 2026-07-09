


import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_balance_reason.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';


CryptoWalletFeatures _features({
  bool walletEngineEnabled = true,
  bool mainnetReceiveEnabled = true,
  bool mainnetErc20ReceiveEnabled = true,
  bool mainnetSendEnabled = false,
  bool mainnetSendPaused = false,
  bool solanaEnabled = false,
  bool solanaBalanceEnabled = false,
  bool solanaSendEnabled = false,
  bool solanaSendPaused = false,
  bool solanaActivityConnected = false,
  bool solanaStatusReady = false,
  bool solanaFeeReady = false,
  bool tronEnabled = false,
  bool tronBalanceEnabled = false,
  bool tronSendEnabled = false,
  bool tronSendPaused = false,
  bool tronActivityConnected = false,
  bool tronUsdtContractConfigured = false,
  bool xmrEnabled = false,
  bool xmrActivityConnected = false,
}) {
  return CryptoWalletFeatures(
    walletEngineEnabled: walletEngineEnabled,
    sepoliaReceiveEnabled: true,
    sepoliaSendEnabled: false,
    mainnetReceiveEnabled: mainnetReceiveEnabled,
    mainnetErc20ReceiveEnabled: mainnetErc20ReceiveEnabled,
    mainnetSendEnabled: mainnetSendEnabled,
    mainnetSendPaused: mainnetSendPaused,
    defaultNetwork: 'ethereum_mainnet',
    defaultNetworkConfigValid: true,
    solanaEnabled: solanaEnabled,
    solanaReceiveEnabled: solanaEnabled,
    solanaBalanceEnabled: solanaBalanceEnabled,
    solanaSendEnabled: solanaSendEnabled,
    solanaSendPaused: solanaSendPaused,
    solanaActivityConnected: solanaActivityConnected,
    solanaStatusReady: solanaStatusReady,
    solanaFeeReady: solanaFeeReady,
    tronEnabled: tronEnabled,
    tronReceiveEnabled: tronEnabled,
    tronBalanceEnabled: tronBalanceEnabled,
    tronSendEnabled: tronSendEnabled,
    tronSendPaused: tronSendPaused,
    tronActivityConnected: tronActivityConnected,
    tronUsdtContractConfigured: tronUsdtContractConfigured,
    xmrEnabled: xmrEnabled,
    xmrReceiveEnabled: xmrEnabled,
    xmrBalanceEnabled: false,
    xmrSendEnabled: false,
    xmrActivityConnected: xmrActivityConnected,
    xmrScannerMode: 'none',
    xmrClientScannerSupported: false,
    xmrBackendScannerEnabled: false,
    supportedNetworks: const [],
    supportedAssetsByNetwork: const {},
  );
}


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


String _mapReason(String asset, String? reason) {
  final kind = walletNetworkKindFor(asset: asset, network: null);
  return walletBalanceReasonRender(
    reason: reason, asset: asset, networkKind: kind,
  ).message;
}


void main() {


  group('Part A — no vague "Balance not yet connected" left anywhere '
      'on live Crypto Vault surfaces', () {

    test('lib/ui/crypto_wallet_engine_page.dart does not contain the '
        'vague placeholder', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(
        src.contains('Balance not yet connected'),
        isFalse,
        reason: 'the vague dashboard placeholder must be gone — the '
            'closed-set reason mapper (crypto_wallet_balance_reason) '
            'is the single source of truth for balance copy.',
      );
      expect(
        src.contains('kCryptoWalletEngineBalanceNotConnectedLabel'),
        isFalse,
        reason: 'the constant itself must be removed.',
      );
    });

    test('lib/main.dart never renders "Balance not yet connected"', () {
      final src = _readLib('main.dart');
      expect(src.contains('Balance not yet connected'), isFalse);
    });
  });


  group('Part A — dashboard reason resolver maps per-asset feature '
      'state to the exact closed-set copy', () {

    test('ETH: no wallet yet copy when RPC receive enabled', () {
      final f = _features(mainnetReceiveEnabled: true);
      final reason = dashboardAssetBalanceReason(asset: 'ETH', features: f);
      expect(reason, 'no_wallet_yet');
      expect(_mapReason('ETH', reason), 'Create wallet to view balance.');
    });

    test('ETH: feature disabled when mainnet receive off', () {
      final f = _features(mainnetReceiveEnabled: false);
      expect(
        dashboardAssetBalanceReason(asset: 'ETH', features: f),
        'feature_disabled',
      );
    });

    test('SOL: rpc_not_configured when solanaEnabled but no '
        'solanaBalanceEnabled', () {
      final f = _features(
        solanaEnabled: true, solanaBalanceEnabled: false,
      );
      final reason = dashboardAssetBalanceReason(asset: 'SOL', features: f);
      expect(reason, 'rpc_not_configured');
      expect(_mapReason('SOL', reason), 'Solana RPC is not configured.');
    });

    test('USDT_TRC20: rpc_not_configured when tronEnabled but no '
        'tronBalanceEnabled', () {
      final f = _features(
        tronEnabled: true, tronBalanceEnabled: false,
      );
      final reason = dashboardAssetBalanceReason(
        asset: 'USDT_TRC20', features: f,
      );
      expect(reason, 'rpc_not_configured');
      expect(_mapReason('USDT_TRC20', reason),
          'TRON API is not configured.');
    });

    test('USDT_TRC20: token_contract_not_configured when RPC on but '
        'contract missing', () {
      final f = _features(
        tronEnabled: true,
        tronBalanceEnabled: true,
        tronUsdtContractConfigured: false,
      );
      expect(
        dashboardAssetBalanceReason(asset: 'USDT_TRC20', features: f),
        'token_contract_not_configured',
      );
    });

    test('XMR: scanner-required copy when xmrEnabled but scanner off is '
        'the compact "Scanner not enabled" chip (was the long paragraph)',
        () {
      final f = _features(xmrEnabled: true);
      final reason = dashboardAssetBalanceReason(asset: 'XMR', features: f);
      expect(reason, 'xmr_scanner_not_enabled');




      expect(_mapReason('XMR', reason), 'Scanner not enabled');
    });

    test('features unknown → null reason (dashboard should show '
        'skeleton)', () {
      expect(
        dashboardAssetBalanceReason(asset: 'ETH', features: null),
        isNull,
      );
    });
  });


  group('Part C — per-asset action capability follows real capability', () {

    test('XMR: send is always false, transactions false — never live', () {
      final f = _features(xmrEnabled: true);
      final cap = dashboardAssetActionCapability(
        asset: 'XMR', features: f,
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(cap.receive, isTrue);
      expect(cap.send, isFalse);
      expect(cap.transactions, isFalse);
      expect(cap.sendUnavailableReason, kAssetSendUnavailableMonero);
      expect(cap.transactionsUnavailableReason,
          kAssetActivityUnavailableMonero);
    });

    test('USDT_TRC20: send hidden until tronSendEnabled=true', () {
      final f = _features(
        tronEnabled: true, tronBalanceEnabled: true,
        tronUsdtContractConfigured: true,
        tronSendEnabled: false,
      );
      final cap = dashboardAssetActionCapability(
        asset: 'USDT_TRC20', features: f,
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(cap.receive, isTrue);
      expect(cap.send, isFalse,
          reason: 'TRON send must not appear as active while backend '
              'flag is off');
      expect(cap.sendUnavailableReason,
          kAssetSendUnavailableTronDisabled);
    });

    test('USDT_TRC20: transactions hidden while activity feed not '
        'connected', () {
      final f = _features(
        tronEnabled: true, tronBalanceEnabled: true,
        tronUsdtContractConfigured: true,
        tronActivityConnected: false,
      );
      final cap = dashboardAssetActionCapability(
        asset: 'USDT_TRC20', features: f,
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(cap.transactions, isFalse,
          reason: 'TRON activity must not appear live if backend '
              'activity feed is not implemented');
      expect(cap.transactionsUnavailableReason,
          kAssetActivityUnavailableTron);
    });

    test('SOL: send hidden until solanaSendEnabled=true', () {
      final f = _features(
        solanaEnabled: true, solanaBalanceEnabled: true,
        solanaSendEnabled: false,
      );
      final cap = dashboardAssetActionCapability(
        asset: 'SOL', features: f,
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(cap.send, isFalse);
      expect(cap.sendUnavailableReason,
          kAssetSendUnavailableSolanaDisabled);
    });

    test('ETH: send hidden until mainnet send flag on', () {
      final f = _features(
        mainnetReceiveEnabled: true,
        mainnetSendEnabled: false,
      );
      final cap = dashboardAssetActionCapability(
        asset: 'ETH', features: f,
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(cap.receive, isTrue);
      expect(cap.send, isFalse);
      expect(cap.sendUnavailableReason,
          kAssetSendUnavailableMainnetDisabled);
    });

    test('ETH: send is enabled when mainnet send flag on and not '
        'paused', () {
      final f = _features(
        mainnetReceiveEnabled: true,
        mainnetSendEnabled: true,
        mainnetSendPaused: false,
      );
      final cap = dashboardAssetActionCapability(
        asset: 'ETH', features: f,
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(cap.send, isTrue);
      expect(cap.sendUnavailableReason, isNull);
    });

    test('no wiring → nothing is live', () {
      final f = _features(
        mainnetReceiveEnabled: true, mainnetSendEnabled: true,
      );
      final cap = dashboardAssetActionCapability(
        asset: 'ETH', features: f,
        hasReceiveWiring: false, hasSendWiring: false,
      );
      expect(cap.receive, isFalse);
      expect(cap.send, isFalse);
    });

    test('features null → nothing is live', () {
      final cap = dashboardAssetActionCapability(
        asset: 'ETH', features: null,
        hasReceiveWiring: true, hasSendWiring: true,
      );
      expect(cap.receive, isFalse);
      expect(cap.send, isFalse);
      expect(cap.transactions, isFalse);
    });
  });


  group('Part C — action unavailable copy is honest and never mentions '
      'exchange verbs', () {

    test('all send-unavailable strings are one-line and honest', () {
      final strings = [
        kAssetSendUnavailableMonero,
        kAssetSendUnavailableTronDisabled,
        kAssetSendUnavailableTronPaused,
        kAssetSendUnavailableSolanaDisabled,
        kAssetSendUnavailableSolanaPaused,
        kAssetSendUnavailableMainnetDisabled,
        kAssetSendUnavailableMainnetPaused,
      ];
      for (final s in strings) {
        expect(s.length, lessThan(80),
            reason: 'must be a short in-card note: "$s"');
        for (final banned in const [
          ' buy ', ' sell ', ' swap ', ' trade ', ' stake ',
          ' bridge ', ' exchange ',
        ]) {
          expect(' $s '.toLowerCase().contains(banned), isFalse,
              reason: '"$s" must not mention "$banned"');
        }
      }
    });

    test('all activity-unavailable strings are honest', () {
      final strings = [
        kAssetActivityUnavailableMonero,
        kAssetActivityUnavailableTron,
        kAssetActivityUnavailableSolana,
        kAssetActivityUnavailableEthereum,
      ];
      for (final s in strings) {
        expect(s.length, lessThan(80));
        expect(
          s.toLowerCase().contains('coming soon'),
          isFalse,
          reason: '"$s" must not promise "coming soon" — it must be '
              'a plain not-yet-connected note.',
        );
      }
    });
  });


  group('Part D — engine dashboard no longer mounts the giant mainnet '
      'receive cards on default render', () {

    test('crypto_wallet_engine_page.dart does not construct '
        'CryptoWalletEngineMainnetReceiveCard on the default page', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(
        src.contains('CryptoWalletEngineMainnetReceiveCard('),
        isFalse,
        reason: 'the giant ETH receive card must not appear on the '
            'default dashboard render — it opens only via the Receive '
            'flow.',
      );
      expect(
        src.contains('CryptoWalletEngineMainnetErc20ReceiveCard('),
        isFalse,
        reason: 'the giant USDT/USDC ERC20 receive cards must not '
            'appear on the default dashboard render.',
      );
      expect(
        src.contains('_buildMainnetSlot'),
        isFalse,
        reason: 'the mainnet-slot helper must be removed — the '
            'giant receive cards are gated behind the Receive flow.',
      );
    });

    test('imports for the removed mainnet card widgets are dropped', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(
        src.contains("import 'crypto_wallet_engine_mainnet_receive_card.dart'"),
        isFalse,
      );
      expect(
        src.contains(
          "import 'crypto_wallet_engine_mainnet_erc20_receive_card.dart'",
        ),
        isFalse,
      );
    });
  });


  group('Part E — subscription banner is compact + dismissible', () {

    test('main.dart routes the banner through a Stack overlay + a '
        'dismiss field', () {
      final src = _readLib('main.dart');
      expect(
        src.contains('_cryptoBillingBannerDismissed'),
        isTrue,
        reason: 'the dismiss state field must exist so the banner can '
            'be closed.',
      );
      expect(
        src.contains('Positioned.fill(child: content)'),
        isTrue,
        reason: 'banner must render as an overlay that never pushes '
            'the dashboard down.',
      );
      expect(
        src.contains('crypto_vault_billing_banner_dismiss_button'),
        isTrue,
        reason: 'the compact banner must expose a dismiss button so '
            'the user can close it.',
      );
    });

    test('banner label is the compact, single-line form (no "Storage/" '
        'prefix, no "cannot be refreshed")', () {
      final src = _readLib('main.dart');
      expect(
        src.contains('Storage/subscription status'),
        isFalse,
        reason: 'the "Storage/subscription" long-form banner label '
            'must be replaced by the compact one-liner.',
      );
      expect(
        src.contains('Subscription status is temporarily unavailable.'),
        isTrue,
        reason: 'compact one-line banner label must be present.',
      );
    });
  });
}
