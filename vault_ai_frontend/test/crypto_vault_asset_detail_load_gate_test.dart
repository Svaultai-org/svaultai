


import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/evm_networks.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_asset_detail_page.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


Widget _wrap({required String asset, String? network}) {
  return MaterialApp(
    home: CryptoWalletEngineAssetDetailPage(
      asset: asset,
      network: network,
    ),
  );
}


void main() {

  group('Part A + D — receive fetch has a timeout, mounted-safe finally, '
      'and short-circuits into no-wallet state', () {

    test('_loadAddressAndBalance passes receive/balance timeouts through '
        'to the SHARED loader (loadAssetWalletState) — same timeout '
        'guarantees, in one place', () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');


      final start = src.indexOf('Future<void> _loadAddressAndBalance');
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 3500);



      expect(
        scope.contains('loadAssetWalletState('),
        isTrue,
        reason: 'detail page must call the shared loader — no more '
            'separate receive/balance parsing that can disagree with '
            'the dashboard.',
      );
      expect(
        scope.contains('receiveTimeout: kAssetDetailReceiveTimeout'),
        isTrue,
        reason: 'detail page must thread its receive timeout into the '
            'shared loader so wallet address card cannot spin forever.',
      );
      expect(
        scope.contains('balanceTimeout: kAssetDetailBalanceTimeout'),
        isTrue,
        reason: 'detail page must thread its balance timeout into the '
            'shared loader.',
      );



      expect(
        scope.contains("_balanceReason = 'no_wallet_yet'"),
        isTrue,
        reason: 'noWallet kind from the shared loader must map to '
            '_balanceReason=no_wallet_yet, not rpc_error.',
      );
    });

    test('_loadBalance wraps balance call in .timeout('
        'kAssetDetailBalanceTimeout) + finally', () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');

      final start = src.indexOf('Future<void> _loadBalance(String address)');
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 2500);

      expect(
        scope.contains('.timeout(kAssetDetailBalanceTimeout)'),
        isTrue,
      );
      expect(
        scope.contains('} finally {'),
        isTrue,
        reason: 'balance loading flag must reset in a finally block.',
      );
    });

    test('_loadAddressAndBalance only calls _loadBalance AFTER a '
        'non-empty address is confirmed', () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');
      final start = src.indexOf('Future<void> _loadAddressAndBalance');
      final scope = src.substring(start, start + 3500);



      final loadBalanceIdx = scope.indexOf('_loadBalance(addr);');
      expect(loadBalanceIdx, greaterThan(0));


      final guard = scope.substring(0, loadBalanceIdx);
      expect(
        guard.contains('addr != null && addr.isNotEmpty'),
        isTrue,
        reason: 'balance route must not be called before we know a '
            'non-empty address exists.',
      );
    });

    test('closed-set copy constants are defined and match spec', () {
      expect(kAssetDetailNoWalletAddressCopy, 'No wallet created yet.');
      expect(
        kAssetDetailNoWalletBalanceCopy,
        'Create wallet to view balance.',
      );
      expect(
        kAssetDetailNoWalletActivityCopy,
        'Create wallet to view activity.',
      );
      expect(kAssetDetailLoadingWalletCopy, 'Loading wallet…');
      expect(kAssetDetailLoadingBalanceCopy, 'Loading balance…');
      expect(kAssetDetailLoadingActivityCopy, 'Loading activity…');
      expect(
        kAssetDetailBalanceUnavailableCopy,
        'Balance temporarily unavailable.',
      );
    });

    test('timeout constants are set to reasonable seconds', () {
      expect(kAssetDetailReceiveTimeout.inSeconds, lessThanOrEqualTo(15));
      expect(kAssetDetailReceiveTimeout.inSeconds, greaterThanOrEqualTo(3));
      expect(kAssetDetailBalanceTimeout.inSeconds, lessThanOrEqualTo(15));
      expect(kAssetDetailBalanceTimeout.inSeconds, greaterThanOrEqualTo(3));
    });
  });


  group('Part B — no-wallet empty state renders the honest closed-set '
      'copy for each supported asset', () {

    testWidgets('ETH detail (no wiring) shows "No wallet created yet." + '
        '"Create wallet to view balance." + "Create wallet to view '
        'activity."', (tester) async {
      await tester.pumpWidget(_wrap(
        asset: 'ETH', network: kEvmNetworkEthereumMainnet,
      ));
      await tester.pumpAndSettle();


      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_address_no_wallet',
        )),
        findsOneWidget,
      );
      expect(find.text('No wallet created yet.'), findsOneWidget);


      expect(find.text('Create wallet to view balance.'), findsOneWidget);


      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_activity_no_wallet',
        )),
        findsOneWidget,
      );
      expect(find.text('Create wallet to view activity.'), findsOneWidget);


      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_address_loading',
        )),
        findsNothing,
      );
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_balance_loading',
        )),
        findsNothing,
      );
      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_activity_loading',
        )),
        findsNothing,
      );


      expect(
        find.text(kAssetDetailBalanceUnavailableCopy),
        findsNothing,
        reason: '"Balance temporarily unavailable." must NEVER show in '
            'the pre-wallet state — that copy is reserved for provider '
            'errors after a wallet has been created.',
      );
    });

    testWidgets('USDT_ERC20 no-wallet state shows the same honest copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        asset: 'USDT_ERC20', network: kEvmNetworkEthereumMainnet,
      ));
      await tester.pumpAndSettle();
      expect(find.text('No wallet created yet.'), findsOneWidget);
      expect(find.text('Create wallet to view balance.'), findsOneWidget);
      expect(find.text('Create wallet to view activity.'), findsOneWidget);
    });

    testWidgets('USDC_ERC20 no-wallet state shows the same honest copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        asset: 'USDC_ERC20', network: kEvmNetworkEthereumMainnet,
      ));
      await tester.pumpAndSettle();
      expect(find.text('No wallet created yet.'), findsOneWidget);
      expect(find.text('Create wallet to view balance.'), findsOneWidget);
      expect(find.text('Create wallet to view activity.'), findsOneWidget);
    });
  });


  group('Part C — activity panel does NOT mount the network-hitting '
      'activity card while the wallet address is unknown or absent', () {

    testWidgets('no-wallet ETH detail does not mount CryptoWalletActivityCard',
        (tester) async {
      await tester.pumpWidget(_wrap(
        asset: 'ETH', network: kEvmNetworkEthereumMainnet,
      ));
      await tester.pumpAndSettle();

      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_activity_card_ETH',
        )),
        findsNothing,
        reason: 'the activity card (which fetches transactions) must '
            'not mount before we know a wallet exists.',
      );

      expect(
        find.byKey(const Key(
          'crypto_wallet_engine_asset_detail_activity_no_wallet',
        )),
        findsOneWidget,
      );
    });

    test('_buildActivityPanel source has an explicit walletKnownAbsent '
        'gate BEFORE the Solana/Tron branches', () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');
      final start = src.indexOf('Widget _buildActivityPanel()');
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 3500);


      final gateIdx = scope.indexOf('walletKnownAbsent');
      final solanaIdx = scope.indexOf('CryptoWalletEngineSolanaActivityCard');
      final tronIdx = scope.indexOf('CryptoWalletEngineTronActivityCard');
      final defaultIdx = scope.indexOf('CryptoWalletActivityCard(');

      expect(gateIdx, greaterThan(0),
          reason: 'gate on walletKnownAbsent must exist.');


      final walletAbsentCardIdx =
          scope.indexOf('_buildActivityNoWalletCard()');
      expect(walletAbsentCardIdx, greaterThan(gateIdx));
      expect(walletAbsentCardIdx, lessThan(solanaIdx),
          reason: 'the no-wallet card must return BEFORE the SOL card.');
      expect(walletAbsentCardIdx, lessThan(tronIdx),
          reason: 'the no-wallet card must return BEFORE the TRON card.');
      expect(walletAbsentCardIdx, lessThan(defaultIdx),
          reason: 'the no-wallet card must return BEFORE the default '
              'CryptoWalletActivityCard.');
    });
  });


  group('Part D — load order: address first, only THEN balance/activity', () {

    test('the SHARED loader enforces receive-then-balance ordering — '
        'detail page delegates to it so we do not re-implement the '
        'ordering here', () {
      final loader = _readLib('services/crypto_wallet_dashboard_reason.dart');
      final start = loader.indexOf(
        'Future<DashboardAssetLiveState> loadAssetWalletState(',
      );
      expect(start, greaterThan(0));
      final scope = loader.substring(start);

      final receiveIdx = scope.indexOf('getCryptoWalletReceiveNetwork(');
      final balanceIdx = scope.indexOf('getCryptoWalletBalanceNetwork(');
      expect(receiveIdx, greaterThan(0),
          reason: 'shared loader must call receive first');
      expect(balanceIdx, greaterThan(receiveIdx),
          reason: 'shared loader must call balance AFTER receive.');



      final detail = _readLib(
        'ui/crypto_wallet_engine_asset_detail_page.dart',
      );
      final detailStart = detail.indexOf(
        'Future<void> _loadAddressAndBalance',
      );
      expect(detailStart, greaterThan(0));
      final detailScope = detail.substring(detailStart, detailStart + 3500);
      expect(detailScope.contains('loadAssetWalletState('), isTrue,
          reason: 'detail must delegate its load ordering to the shared '
              'loader.');
    });

    test('_loadBalance is never scheduled when addr is null/empty', () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');
      final start = src.indexOf('Future<void> _loadAddressAndBalance');
      final scope = src.substring(start, start + 3500);


      final guardIdx = scope.indexOf('if (addr != null && addr.isNotEmpty');
      final balanceCallIdx = scope.indexOf('_loadBalance(addr);');
      expect(guardIdx, greaterThan(0));
      expect(balanceCallIdx, greaterThan(guardIdx),
          reason: '_loadBalance must only be reachable through the '
              'addr != null && addr.isNotEmpty guard.');
    });
  });


  group('Part E — receive panel close still triggers the address '
      '+ balance reload on the detail page', () {

    test('_openReceivePanel .whenComplete calls _loadAddressAndBalance',
        () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');
      final openIdx = src.indexOf('void _openReceivePanel');
      expect(openIdx, greaterThan(0));
      final scope = src.substring(openIdx, openIdx + 5000);


      final whenCompleteIdx = scope.indexOf('.whenComplete(');
      final loadCallIdx = scope.indexOf('_loadAddressAndBalance()');
      expect(whenCompleteIdx, greaterThan(0));
      expect(loadCallIdx, greaterThan(whenCompleteIdx),
          reason: 'the receive-panel close callback must trigger a '
              'fresh address+balance load.');
    });
  });


  group('Part F — copy hygiene', () {

    test('no infinite "Loading…" copy in the detail page render paths', () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');


      final looseLoadingHits = RegExp(r"Text\('Loading…'").allMatches(src);
      expect(looseLoadingHits.length, 0,
          reason: 'the bare "Loading…" copy was replaced by scoped '
              '"Loading wallet…" / "Loading balance…" / "Loading '
              'activity…" copies.');
    });

    test('render paths do not carry "not connected" fallbacks', () {
      final src = _readLib('ui/crypto_wallet_engine_asset_detail_page.dart');
      expect(
        src.toLowerCase().contains('balance temporarily unavailable'),
        isTrue,
        reason: 'the closed-set "Balance temporarily unavailable." '
            'copy must remain — it is used for provider errors after '
            'wallet creation.',
      );

    });
  });


  group('Mobile layout — no overflow at 360 × 720 in the no-wallet '
      'empty state', () {

    testWidgets('ETH no-wallet renders without overflow at mobile size',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(_wrap(
        asset: 'ETH', network: kEvmNetworkEthereumMainnet,
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('SOL no-wallet renders without overflow at mobile size',
        (tester) async {
      tester.view.physicalSize = const Size(360, 720);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(_wrap(
        asset: 'SOL', network: 'solana_mainnet',
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });
}
