


import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_features.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


CryptoWalletFeatures _allEnabledFeatures() {
  return CryptoWalletFeatures.fromBackend(<String, dynamic>{
    'mainnetReceiveEnabled':      true,
    'mainnetErc20ReceiveEnabled': true,
    'solanaEnabled':              true,
    'tronEnabled':                true,
    'xmrEnabled':                 true,
    'defaultNetwork':             'ethereum_mainnet',
    'defaultNetworkConfigValid':  true,
  });
}


void main() {


  group('Part 1 — networkForAssetRoute maps per-asset like detail-page did',
      () {

    test('ETH / USDT_ERC20 / USDC_ERC20 stay on the effective mainnet '
        'network (ethereum_mainnet)', () {
      final f = _allEnabledFeatures();
      for (final a in const ['ETH', 'USDT_ERC20', 'USDC_ERC20']) {
        expect(
          networkForAssetRoute(
            asset: a, features: f,
            effectiveMainnetNetwork: 'ethereum_mainnet',
          ),
          'ethereum_mainnet',
          reason: '$a must route to ethereum_mainnet on Mainnet mode',
        );
      }
    });

    test('SOL routes to solana_mainnet — never to ethereum_mainnet '
        '(the exact bug: dashboard fan-out was sending SOL to '
        'ethereum_mainnet)', () {
      final f = _allEnabledFeatures();
      expect(
        networkForAssetRoute(
          asset: 'SOL', features: f,
          effectiveMainnetNetwork: 'ethereum_mainnet',
        ),
        'solana_mainnet',
      );
    });

    test('USDT_TRC20 routes to tron_mainnet', () {
      final f = _allEnabledFeatures();
      expect(
        networkForAssetRoute(
          asset: 'USDT_TRC20', features: f,
          effectiveMainnetNetwork: 'ethereum_mainnet',
        ),
        'tron_mainnet',
      );
    });

    test('XMR routes to monero_mainnet', () {
      final f = _allEnabledFeatures();
      expect(
        networkForAssetRoute(
          asset: 'XMR', features: f,
          effectiveMainnetNetwork: 'ethereum_mainnet',
        ),
        'monero_mainnet',
      );
    });

    test('when a chain feature is DISABLED, the asset falls back to the '
        'effective mainnet — no bogus network is emitted', () {
      final disabledSol = CryptoWalletFeatures.fromBackend(
        <String, dynamic>{
          'mainnetReceiveEnabled':     true,
          'solanaEnabled':             false,
          'defaultNetwork':            'ethereum_mainnet',
          'defaultNetworkConfigValid': true,
        },
      );
      expect(
        networkForAssetRoute(
          asset: 'SOL', features: disabledSol,
          effectiveMainnetNetwork: 'ethereum_mainnet',
        ),
        'ethereum_mainnet',
        reason: 'if solana is disabled the fallback must be the '
            'effective mainnet — never an invented network.',
      );
    });

    test('null features falls back to effective mainnet', () {
      expect(
        networkForAssetRoute(
          asset: 'SOL', features: null,
          effectiveMainnetNetwork: 'ethereum_mainnet',
        ),
        'ethereum_mainnet',
      );
    });
  });



  group('Part 2 — dashboard fan-out uses per-asset network (matches detail)',
      () {

    test('_refreshLiveAssetState computes routeNetwork via '
        'networkForAssetRoute — NOT _effectiveNetwork directly', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf(
        'Future<void> _refreshLiveAssetState(String asset) async',
      );
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 3000);


      expect(
        scope.contains('networkForAssetRoute('),
        isTrue,
        reason: 'dashboard refresh must consult the shared per-asset '
            'network helper — sending SOL to ethereum_mainnet is the '
            'root cause bug we are fixing.',
      );
      expect(
        scope.contains('asset: asset'),
        isTrue,
      );




      final helperIdx = scope.indexOf('networkForAssetRoute(');
      final loaderIdx = scope.indexOf('loadAssetWalletState(');
      expect(loaderIdx, greaterThan(helperIdx),
          reason: 'per-asset network must be computed BEFORE the loader '
              'call');



      final loaderScope = scope.substring(loaderIdx);
      expect(
        loaderScope.contains('network: routeNetwork'),
        isTrue,
        reason: 'the computed routeNetwork must be threaded into the '
            'shared loader.',
      );
    });

    test('_refreshLiveAssetState no longer inlines '
        'network: _effectiveNetwork in the loader call — that is the '
        'exact broken line', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf(
        'Future<void> _refreshLiveAssetState(String asset) async',
      );
      final scope = src.substring(start, start + 3000);

      final loaderIdx = scope.indexOf('loadAssetWalletState(');
      expect(loaderIdx, greaterThan(0));
      final loaderScope = scope.substring(loaderIdx, loaderIdx + 400);


      expect(
        loaderScope.contains('network: _effectiveNetwork'),
        isFalse,
        reason: 'the loader must NOT receive _effectiveNetwork directly — '
            'that was the SOL→ethereum_mainnet bug. It must receive the '
            'routeNetwork computed via networkForAssetRoute.',
      );
    });
  });



  group('Part 3 — _openAssetDetail uses the exact SAME helper for '
      'dashboard/detail parity', () {

    test('_openAssetDetail consults networkForAssetRoute — no more '
        'inline ternaries that could drift', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf(
        'void _openAssetDetail(BuildContext ctx, String asset)',
      );
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 900);

      expect(scope.contains('networkForAssetRoute('), isTrue,
          reason: 'detail navigation must use the shared helper — same '
              'code path as dashboard fan-out.');



      expect(scope.contains("'solana_mainnet'"), isFalse,
          reason: 'inline solana_mainnet ternary must be gone.');
      expect(scope.contains("'tron_mainnet'"), isFalse,
          reason: 'inline tron_mainnet ternary must be gone.');
      expect(scope.contains("'monero_mainnet'"), isFalse,
          reason: 'inline monero_mainnet ternary must be gone.');
    });
  });



  group('Part 4 — fan-out is SEQUENTIAL, not parallel (backend cold-start '
      'safety)', () {

    test('_fanOutInitialLiveRefresh is Future<void> and awaits each '
        'refresh — parallel fire-and-forget is gone', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf('_fanOutInitialLiveRefresh(');
      expect(start, greaterThan(0));


      final scope = src.substring(start, start + 900);

      expect(
        scope.contains('Future<void> _fanOutInitialLiveRefresh()'),
        isTrue,
        reason: 'fan-out must be async so we can await per-asset — '
            'firing 4 receive calls in parallel slams a cold backend '
            'with concurrent PBKDF vault-unlocks and times some out.',
      );
      expect(
        scope.contains('await _refreshLiveAssetState(asset)'),
        isTrue,
        reason: 'each refresh must be awaited before the next — one '
            'asset at a time.',
      );
    });

    test('_fanOutInitialLiveRefresh emits a fanout_done log so we can '
        'confirm every asset ran to completion', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(src.contains('fanout_done assets='), isTrue,
          reason: 'end-of-fan-out log is a diagnostic anchor — if we '
              'see fanout_start but never fanout_done, we know the '
              'sequential loop was interrupted.');
    });
  });
}
