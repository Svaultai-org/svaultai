


import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/billing_me_diagnostic.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


Widget _wrapDetail({
  required String asset,
  required String? network,
}) {
  return MaterialApp(
    home: CryptoWalletEngineAssetDetailPage(
      asset: asset,
      network: network,
    ),
  );
}


void main() {


  group('Part A — detail page network label follows widget.network', () {

    for (final asset in const ['ETH', 'USDT_ERC20', 'USDC_ERC20']) {
      test('assetDetailNetworkLabel($asset, mainnet) === expected mainnet '
          'label', () {
        final label = assetDetailNetworkLabel(
          asset: asset, network: kEvmNetworkEthereumMainnet,
        );
        if (asset == 'ETH') {
          expect(label, kAssetDetailEthereumMainnetLabel);
          expect(label, 'Ethereum Mainnet');
        } else {
          expect(label, kAssetDetailEthereumMainnetErc20Label);
          expect(label, 'Ethereum Mainnet · ERC20');
        }
        expect(label.toLowerCase().contains('sepolia'), isFalse);
        expect(label.toLowerCase().contains('testnet'), isFalse);
      });

      test('assetDetailNetworkLabel($asset, sepolia) === Sepolia Testnet',
          () {
        expect(
          assetDetailNetworkLabel(
            asset: asset, network: kEvmNetworkEthereumSepolia,
          ),
          kAssetDetailEthereumSepoliaLabel,
        );
      });
    }

    test('non-ethereum assets fall through to per-asset network label '
        'unchanged', () {
      expect(
        assetDetailNetworkLabel(asset: 'SOL', network: 'solana_mainnet'),
        contains('Solana'),
      );
      expect(
        assetDetailNetworkLabel(asset: 'USDT_TRC20', network: 'tron_mainnet'),
        contains('Tron'),
      );
      expect(
        assetDetailNetworkLabel(asset: 'XMR', network: 'monero_mainnet'),
        contains('Monero'),
      );
    });

    test('assetDetailIsSepolia flips only on Ethereum-family + Sepolia '
        'network', () {
      expect(
        assetDetailIsSepolia(
          asset: 'ETH', network: kEvmNetworkEthereumSepolia,
        ),
        isTrue,
      );
      expect(
        assetDetailIsSepolia(
          asset: 'ETH', network: kEvmNetworkEthereumMainnet,
        ),
        isFalse,
      );
      expect(
        assetDetailIsSepolia(
          asset: 'SOL', network: 'solana_mainnet',
        ),
        isFalse,
      );
    });

    test('detail page hardcoded "Ethereum Sepolia testnet" string is gone',
        () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');


      expect(src.contains("'Ethereum Sepolia testnet'"), isFalse);


      expect(
        src.contains("isEthSepolia =\n"
            "        widget.asset == 'ETH' ||"),
        isFalse,
        reason: 'the old always-true isEthSepolia flag must be gone.',
      );


      expect(
        src.contains('assetDetailNetworkLabel('),
        isTrue,
        reason: 'the network-aware helper must drive the header label.',
      );
    });

    test('Sepolia-specific token gas note is gone (was: "Sepolia ETH")',
        () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');
      expect(
        src.contains('Sepolia ETH'),
        isFalse,
        reason: 'Gas note copy must not mention Sepolia — it applies to '
            'any Ethereum network.',
      );
    });

    testWidgets('ETH detail page (network=mainnet) renders '
        '"Ethereum Mainnet" — never "Sepolia"', (tester) async {
      await tester.pumpWidget(_wrapDetail(
        asset: 'ETH', network: kEvmNetworkEthereumMainnet,
      ));
      await tester.pumpAndSettle();
      expect(
        find.byKey(
          const Key('crypto_wallet_engine_asset_detail_network_label'),
        ),
        findsOneWidget,
      );
      expect(find.text('Ethereum Mainnet'), findsOneWidget);
      expect(find.textContaining('Sepolia'), findsNothing);
      expect(find.textContaining('testnet'), findsNothing);
    });

    testWidgets('USDT ERC20 detail page (network=mainnet) renders '
        '"Ethereum Mainnet · ERC20"', (tester) async {
      await tester.pumpWidget(_wrapDetail(
        asset: 'USDT_ERC20', network: kEvmNetworkEthereumMainnet,
      ));
      await tester.pumpAndSettle();
      expect(find.text('Ethereum Mainnet · ERC20'), findsOneWidget);
      expect(find.textContaining('Sepolia'), findsNothing);
    });

    testWidgets('USDC ERC20 detail page (network=mainnet) renders '
        '"Ethereum Mainnet · ERC20"', (tester) async {
      await tester.pumpWidget(_wrapDetail(
        asset: 'USDC_ERC20', network: kEvmNetworkEthereumMainnet,
      ));
      await tester.pumpAndSettle();
      expect(find.text('Ethereum Mainnet · ERC20'), findsOneWidget);
      expect(find.textContaining('Sepolia'), findsNothing);
    });

    testWidgets('ETH detail page (network=sepolia) still shows Sepolia '
        'Testnet — testnet mode is honest, not hidden',
        (tester) async {
      await tester.pumpWidget(_wrapDetail(
        asset: 'ETH', network: kEvmNetworkEthereumSepolia,
      ));
      await tester.pumpAndSettle();
      expect(find.text('Ethereum Sepolia Testnet'), findsOneWidget);
    });
  });


  group('Part B — network-aware Vault balance card copy', () {

    test('portfolio "Live balances" copy has separate Mainnet / Sepolia '
        'strings', () {
      expect(
        kCryptoWalletEnginePortfolioLiveBalancesNoteMainnet,
        'Live balances shown from connected Mainnet networks.',
      );
      expect(
        kCryptoWalletEnginePortfolioLiveBalancesNoteSepolia,
        'Testnet balances shown from connected test networks.',
      );
    });

    test('no-wallets subtitle uses "Vault balance" language, not '
        '"Portfolio"', () {
      expect(
        kCryptoWalletEnginePortfolioNoWalletsBody
            .toLowerCase().contains('portfolio'),
        isFalse,
      );
      expect(
        kCryptoWalletEnginePortfolioNoWalletsBody
            .toLowerCase().contains('vault balance'),
        isTrue,
      );
    });

    test('no synthetic USD total claim is preserved in the honest '
        'subcopy', () {
      expect(
        kCryptoWalletEnginePortfolioHonestSubcopy
            .toLowerCase().contains('real on-chain'),
        isTrue,
      );
      expect(
        kCryptoWalletEnginePortfolioHonestSubcopy
            .toLowerCase().contains('synthetic totals'),
        isTrue,
      );
    });

    test('the old testnet-only default copy string is gone', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');


      expect(
        src.contains(
          'Live balances shown for connected test networks. SVaultAI never',
        ),
        isFalse,
        reason: 'the network-neutral hard-coded test-networks copy '
            'must be replaced by a network-aware pair.',
      );
      expect(
        src.contains(
          'kCryptoWalletEnginePortfolioLiveBalancesNoteMainnet',
        ),
        isTrue,
      );
      expect(
        src.contains(
          'kCryptoWalletEnginePortfolioLiveBalancesNoteSepolia',
        ),
        isTrue,
      );
    });
  });


  group('Part C — billing_me diagnostic classifier + closed-set copy', () {

    test('classifyBillingMeError maps TimeoutException → timeout', () {
      final r = classifyBillingMeError(
        TimeoutException('billing check timed out after 5s'),
      );
      expect(r.errorCode, kBillingMeCodeTimeout);
      expect(r.statusLabel, 'timeout');
    });

    test('classifyBillingMeError maps AuthExpiredException → '
        'auth_expired / 401', () {
      final r = classifyBillingMeError(
        const AuthExpiredException(),
      );
      expect(r.errorCode, kBillingMeCodeAuthExpired);
      expect(r.statusLabel, '401');
    });

    test('classifyBillingMeError maps DeviceNotTrustedException → '
        'device_untrusted / 403', () {
      final r = classifyBillingMeError(
        const DeviceNotTrustedException(message: 'pending approval'),
      );
      expect(r.errorCode, kBillingMeCodeDeviceUntrusted);
      expect(r.statusLabel, '403');
    });

    test('classifyBillingMeError extracts 500 status from error text', () {
      final r = classifyBillingMeError(
        Exception('Billing state failed status=500 body=...'),
      );
      expect(r.errorCode, kBillingMeCodeServerError);
      expect(r.statusLabel, '500');
    });

    test('classifyBillingMeError extracts 502 status from error text '
        '(no keyword)', () {
      final r = classifyBillingMeError(
        Exception('Billing state failed with status 502 upstream'),
      );
      expect(r.errorCode, kBillingMeCodeServerError);
      expect(r.statusLabel, '502');
    });

    test('classifyBillingMeError detects "network is unreachable" as '
        'not_reachable', () {
      final r = classifyBillingMeError(
        Exception('SocketException: network is unreachable'),
      );
      expect(r.errorCode, kBillingMeCodeNotReachable);
      expect(r.statusLabel, 'network');
    });

    test('classifyBillingMeError unknown error → unknown_error', () {
      final r = classifyBillingMeError(
        Exception('some mysterious failure with no obvious signal'),
      );
      expect(r.errorCode, kBillingMeCodeUnknownError);
      expect(r.statusLabel, 'unknown');
    });

    test('billingBannerCopyForCode maps every closed-set code to a '
        'non-scary line', () {
      final banned = <String>[
        'stripe', 'customer_id', 'subscription_id',
      ];
      for (final code in kAllBillingMeCodes) {
        final copy = billingBannerCopyForCode(code);
        if (code == kBillingMeCodeOk) {
          expect(copy, '',
              reason: 'ok has no banner copy');
          continue;
        }
        expect(copy.length, greaterThan(0),
            reason: 'code $code must map to a copy string');
        expect(copy.length, lessThan(120),
            reason: 'banner copy must stay compact for code $code');
        for (final b in banned) {
          expect(copy.toLowerCase().contains(b), isFalse,
              reason: 'copy for $code must never leak "$b"');
        }
      }
    });

    test('server_error / timeout / unknown all map to the calm compact '
        'copy — never a scary "backend crashed" line', () {
      expect(
        billingBannerCopyForCode(kBillingMeCodeServerError),
        'Subscription status is temporarily unavailable.',
      );
      expect(
        billingBannerCopyForCode(kBillingMeCodeTimeout),
        'Subscription status is temporarily unavailable.',
      );
      expect(
        billingBannerCopyForCode(kBillingMeCodeUnknownError),
        'Subscription status is temporarily unavailable.',
      );
    });

    test('billingDevLogLineIsSafe rejects lines with banned tokens', () {
      expect(
        billingDevLogLineIsSafe('billing_me_status=200 billing_me_ms=42'),
        isTrue,
      );
      expect(
        billingDevLogLineIsSafe('billing_me_status=200 stripe=sk_test'),
        isFalse,
      );
      expect(
        billingDevLogLineIsSafe(
          'billing_me_status=200 email=user@example.com',
        ),
        isFalse,
      );
      expect(
        billingDevLogLineIsSafe(
          'billing_me_status=200 customer_id=cus_abc',
        ),
        isFalse,
      );
    });

    test('main.dart wires the new billing diagnostic classifier + '
        'safe dev log helper', () {
      final src = _readLib('main.dart');
      expect(src.contains('classifyBillingMeError('), isTrue);
      expect(src.contains('billingBannerCopyForCode('), isTrue);
      expect(src.contains('_logDevBillingMe('), isTrue);
      expect(
        src.contains('billing_me_status='),
        isTrue,
        reason: 'the dev log line must carry billing_me_status.',
      );
      expect(
        src.contains('billing_me_error_code='),
        isTrue,
        reason: 'the dev log line must carry billing_me_error_code.',
      );
      expect(
        src.contains('billing_me_ms='),
        isTrue,
        reason: 'the dev log line must carry billing_me_ms.',
      );
    });

    test('main.dart no longer stores raw e.toString() as billingLoadError', () {
      final src = _readLib('main.dart');


      expect(
        src.contains('billingLoadError = safeCopy'),
        isTrue,
        reason: 'billingLoadError must hold a closed-set safe copy line, '
            'never the raw exception message.',
      );
    });
  });


  group('Part D — dashboard live-asset state kinds', () {

    test('DashboardAssetLiveState kinds are the closed set', () {
      final kinds = DashboardAssetLiveStateKind.values.toSet();
      expect(kinds, equals({
        DashboardAssetLiveStateKind.loading,
        DashboardAssetLiveStateKind.noWallet,
        DashboardAssetLiveStateKind.available,
        DashboardAssetLiveStateKind.reason,
      }));
    });

    test('available state exposes amount + unit; reason state exposes '
        'backendReason', () {
      const avail = DashboardAssetLiveState.available(
        amount: '0.00', unit: 'ETH',
      );
      expect(avail.hasAvailableBalance, isTrue);
      expect(avail.balanceAmount, '0.00');
      expect(avail.balanceUnit, 'ETH');

      const reason = DashboardAssetLiveState.reason(
        reason: 'rpc_not_configured',
      );
      expect(reason.hasAvailableBalance, isFalse);
      expect(reason.backendReason, 'rpc_not_configured');
    });

    test('main crypto engine page wires _refreshLiveAssetState and passes '
        'liveAssetState down', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(src.contains('_refreshLiveAssetState('), isTrue);
      expect(src.contains('onAssetLiveRefreshRequested?.call('), isTrue);
      expect(src.contains('liveAssetState: '), isTrue);
      expect(src.contains('liveState: live'), isTrue);
    });

    test('receive panel close now also triggers per-asset live refresh',
        () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');


      final receiveIdx = src.indexOf('_openReceivePanel(BuildContext');
      expect(receiveIdx, greaterThan(0),
          reason: '_openReceivePanel method must still exist');

      final scope = src.substring(receiveIdx, receiveIdx + 4500);
      expect(
        scope.contains('onAssetLiveRefreshRequested?.call(assetForPanel)'),
        isTrue,
        reason: 'closing the receive panel must fire per-asset live '
            'refresh so the dashboard card can show the fresh wallet.',
      );
      expect(
        scope.contains('onFeatureRefreshRequested?.call()'),
        isTrue,
        reason: 'the feature envelope refresh path must remain intact.',
      );
    });
  });
}
