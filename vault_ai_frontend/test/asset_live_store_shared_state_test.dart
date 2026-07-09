


import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/asset_live_store.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {


  group('Part 1 — AssetLiveStore is a singleton both dashboard and detail '
      'reach', () {

    test('AssetLiveStore.instance is a stable singleton — same reference '
        'across every accessor', () {
      final a = AssetLiveStore.instance;
      final b = AssetLiveStore.instance;
      expect(identical(a, b), isTrue,
          reason: 'singleton must not spin up multiple instances — the '
              'point is one shared state between dashboard and detail.');
    });

    test('dashboard source imports asset_live_store.dart', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(
        src.contains("import '../services/asset_live_store.dart';"),
        isTrue,
        reason: 'dashboard must import the shared store',
      );
    });

    test('detail source imports asset_live_store.dart AND '
        'crypto_wallet_dashboard_reason.dart', () {
      final src = _readLib(
          'ui/crypto_wallet_engine_asset_detail_page.dart');
      expect(
        src.contains("import '../services/asset_live_store.dart';"),
        isTrue,
        reason: 'detail must import the shared store — the whole point of '
            'this refactor is that detail writes what dashboard reads.',
      );
      expect(
        src.contains(
          "import '../services/crypto_wallet_dashboard_reason.dart';",
        ),
        isTrue,
        reason: 'detail must use the SHARED loader (loadAssetWalletState) — '
            'no separate parsing logic that can disagree with dashboard.',
      );
    });
  });



  group('Part 2 — detail-successful available propagates to dashboard-'
      'observed state via the shared store', () {

    setUp(() {
      AssetLiveStore.instance.resetForTest();
    });

    test('detail applies available(0, ETH); dashboard reads exact same '
        'state from the store', () {
      final store = AssetLiveStore.instance;
      final detailSeq = store.claimSeq('ETH');
      store.applyState(
        source: 'detail',
        asset: 'ETH',
        seq: detailSeq,
        network: 'ethereum_mainnet',
        state: const DashboardAssetLiveState.available(
          amount: '0', unit: 'ETH', publicAddress: 'ADDR_MOCK',
        ),
      );




      final s = store.getState('ETH');
      expect(s, isNotNull);
      expect(s!.kind, DashboardAssetLiveStateKind.available);
      expect(s.balanceAmount, '0');
      expect(s.balanceUnit, 'ETH');
      expect(s.publicAddressPresent, isTrue);
    });

    test('detail available at seq=1; dashboard fanout seq=2 later returns '
        'rpc_error — since fanout is NEWER (seq=2 > seq=1) it IS applied '
        '— this is correct: a newer failure has authority',
        () {
      final store = AssetLiveStore.instance;

      final detailSeq = store.claimSeq('ETH');
      store.applyState(
        source: 'detail',
        asset: 'ETH',
        seq: detailSeq,
        state: const DashboardAssetLiveState.available(
          amount: '0', unit: 'ETH', publicAddress: 'ADDR_MOCK',
        ),
      );

      final fanoutSeq = store.claimSeq('ETH');
      expect(fanoutSeq, greaterThan(detailSeq));
      final applied = store.applyState(
        source: 'dashboard',
        asset: 'ETH',
        seq: fanoutSeq,
        state: const DashboardAssetLiveState.reason(reason: 'rpc_error'),
      );

      expect(applied, isTrue,
          reason: 'a NEWER refresh with fresh seq is authoritative — '
              'even if the outcome is worse.');
      expect(store.getState('ETH')!.kind,
          DashboardAssetLiveStateKind.reason);
    });

    test('the EXACT reported bug: dashboard seq=1 in-flight, detail seq=2 '
        'succeeds first, dashboard seq=1 late-lands with rpc_error — '
        'the late seq=1 error must be DROPPED so dashboard shows 0 ETH',
        () {
      final store = AssetLiveStore.instance;


      final dashSeq = store.claimSeq('ETH');
      expect(dashSeq, 1);
      store.applyState(
        source: 'dashboard',
        asset: 'ETH',
        seq: dashSeq,
        state: const DashboardAssetLiveState.loading(),
      );


      final detailSeq = store.claimSeq('ETH');
      expect(detailSeq, 2);
      store.applyState(
        source: 'detail',
        asset: 'ETH',
        seq: detailSeq,
        state: const DashboardAssetLiveState.available(
          amount: '0', unit: 'ETH', publicAddress: 'ADDR_MOCK',
        ),
      );


      final lateApplied = store.applyState(
        source: 'dashboard',
        asset: 'ETH',
        seq: dashSeq,
        state: const DashboardAssetLiveState.reason(reason: 'rpc_error'),
      );

      expect(lateApplied, isFalse,
          reason: 'the late seq=1 error MUST be dropped as stale — '
              'detail seq=2 available already won.');



      final s = store.getState('ETH')!;
      expect(s.kind, DashboardAssetLiveStateKind.available);
      expect(s.balanceAmount, '0');
      expect(s.balanceUnit, 'ETH');
    });

    test('publicAddressPresent flag surfaces from available/reason state '
        '(user spec: "available(amount, unit, publicAddressPresent=true)")',
        () {
      const withAddr = DashboardAssetLiveState.available(
        amount: '0', unit: 'ETH', publicAddress: 'ADDR_MOCK',
      );
      expect(withAddr.publicAddressPresent, isTrue);

      const withoutAddr = DashboardAssetLiveState.available(
        amount: '0', unit: 'ETH',
      );
      expect(withoutAddr.publicAddressPresent, isFalse);

      const reasonWithAddr = DashboardAssetLiveState.reason(
        reason: 'rpc_error', publicAddress: 'ADDR_MOCK',
      );
      expect(reasonWithAddr.publicAddressPresent, isTrue,
          reason: 'reason state can still carry publicAddress — the '
              'wallet exists, only balance is unreachable.');
    });

    test('no wallet does NOT show fake zero — the closed set forbids it',
        () {
      const noWallet = DashboardAssetLiveState.noWallet();
      expect(noWallet.balanceAmount, isNull,
          reason: 'noWallet state must never carry a fake balance');
      expect(noWallet.balanceUnit, isNull);
      expect(noWallet.hasAvailableBalance, isFalse);
    });
  });



  group('Part 3 — ChangeNotifier: writes trigger listeners so widgets '
      'rebuild', () {

    setUp(() {
      AssetLiveStore.instance.resetForTest();
    });

    test('applyState fires listener when state actually changes', () {
      final store = AssetLiveStore.instance;
      int notifyCount = 0;
      void listener() => notifyCount++;
      store.addListener(listener);
      try {
        final seq = store.claimSeq('ETH');
        store.applyState(
          source: 'detail',
          asset: 'ETH',
          seq: seq,
          state: const DashboardAssetLiveState.available(
            amount: '0', unit: 'ETH',
          ),
        );
        expect(notifyCount, 1);
      } finally {
        store.removeListener(listener);
      }
    });

    test('stale drop does NOT fire listener (no rebuild on no-op)', () {
      final store = AssetLiveStore.instance;


      final s1 = store.claimSeq('ETH');
      final s2 = store.claimSeq('ETH');
      store.applyState(
        source: 'detail', asset: 'ETH', seq: s2,
        state: const DashboardAssetLiveState.available(
          amount: '0', unit: 'ETH',
        ),
      );



      int notifyCount = 0;
      void listener() => notifyCount++;
      store.addListener(listener);
      try {
        final applied = store.applyState(
          source: 'dashboard', asset: 'ETH', seq: s1,
          state: const DashboardAssetLiveState.reason(reason: 'rpc_error'),
        );
        expect(applied, isFalse);
        expect(notifyCount, 0,
            reason: 'a dropped stale write must not trigger rebuilds');
      } finally {
        store.removeListener(listener);
      }
    });
  });



  group('Part 4 — parity dev logs: dashboard_asset_state + detail_asset_state '
      '(user spec Part 4)', () {

    test('AssetLiveStore emits <source>_asset_state and includes '
        'network=<name>, asset=<X>, kind=<kind>, amount_present=<bool>, '
        'unit=<X>', () {
      final src = _readLib('services/asset_live_store.dart');



      expect(src.contains(r"'${source}_asset_state"), isTrue,
          reason: 'log label must interpolate source (dashboard/detail) '
              'into <source>_asset_state.');



      expect(src.contains('asset=\$asset'), isTrue);
      expect(src.contains('network=\${network ?? ""}'), isTrue);
      expect(src.contains('kind=\${state.kind.name}'), isTrue);
      expect(src.contains('amount_present=\${state.balanceAmount != null}'),
          isTrue);
      expect(src.contains('unit=\${state.balanceUnit ?? ""}'), isTrue);
    });

    test('AssetLiveStore log NEVER carries publicAddress or any secret '
        'token', () {
      final src = _readLib('services/asset_live_store.dart');



      final logIdx = src.indexOf(r"'${source}_asset_state");
      expect(logIdx, greaterThan(0));
      final scope = src.substring(logIdx, logIdx + 400);


      expect(scope.contains(r'${state.publicAddress'), isFalse,
          reason: 'publicAddress must NEVER be logged.');
      expect(scope.contains(r'publicAddress:'), isFalse);



      const banned = ['publicaddress', 'public_address', 'wallet_address',
                      'wallet_addr', 'rpc_url', 'api_key', 'apikey',
                      'authorization', 'bearer', 'private_key', 'privatekey',
                      'seed_phrase', 'seedphrase', 'mnemonic',
                      'tx_hash', 'txhash', 'encrypted_secret',
                      'stripe', 'customer_id', 'subscription_id',
                      'email', 'card_number'];
      for (final b in banned) {
        expect(scope.toLowerCase().contains(b), isFalse,
            reason: 'log source must not literal-mention "$b"');
      }
    });

    test('AssetLiveStore log is guarded by kDebugMode', () {
      final src = _readLib('services/asset_live_store.dart');
      final logHelperStart = src.indexOf('void _log(');
      expect(logHelperStart, greaterThan(0));


      final end = (logHelperStart + 200 < src.length)
          ? logHelperStart + 200 : src.length;
      final scope = src.substring(logHelperStart, end);
      expect(scope.contains('if (!kDebugMode) return;'), isTrue,
          reason: 'all store logs must be kDebugMode-guarded — never '
              'reach release logs.');
    });
  });



  group('Part 5 — dashboard render reads from the shared store, and '
      'writes go only through it', () {

    test('_CryptoWalletEnginePageState listens to store and rebuilds on '
        'change', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      expect(src.contains('_liveStore.addListener('), isTrue,
          reason: 'dashboard must subscribe to store changes so it '
              'rebuilds when detail-page writes land.');
      expect(src.contains('_liveStore.removeListener('), isTrue,
          reason: 'listener must be cleaned up in dispose');
    });

    test('the widget-local _liveAssetState is now a VIEW over the store, '
        'not a separate map', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');



      expect(
        src.contains(
          'Map<String, DashboardAssetLiveState> get _liveAssetState =>',
        ),
        isTrue,
        reason: '_liveAssetState must be a getter that sources from '
            'the shared store — NOT a widget-local map that can '
            'diverge from what detail-page wrote.',
      );


      expect(
        src.contains(
          'final Map<String, DashboardAssetLiveState> _liveAssetState = {};',
        ),
        isFalse,
        reason: 'the old widget-local map must be gone — it was the '
            'root cause of dashboard/detail disagreement.',
      );
    });

    test('vault balance card renders per-asset row when '
        '_liveAssetState[asset] is available (this is the '
        '"Ethereum · 0 ETH" case)', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');




      final buildIdx = src.indexOf('Widget _buildPortfolioSummary(');
      expect(buildIdx, greaterThan(0));
      final scope = src.substring(buildIdx, buildIdx + 2500);



      expect(scope.contains('liveAssetState[asset]'), isTrue,
          reason: 'vault balance card must read from the passed '
              'liveAssetState map, which is now sourced from the store.');
      expect(scope.contains('DashboardAssetLiveStateKind.available'), isTrue,
          reason: 'card must react to available kind');
      expect(scope.contains('_PortfolioBalanceRow('), isTrue,
          reason: 'available kind must build a portfolio row like '
              '"Ethereum · 0 ETH".');
    });
  });



  group('Part 6 — detail page uses the shared loader, no separate parser',
      () {

    test('detail page calls loadAssetWalletState directly', () {
      final src = _readLib(
          'ui/crypto_wallet_engine_asset_detail_page.dart');
      expect(src.contains('loadAssetWalletState('), isTrue,
          reason: 'detail must call the SHARED loader — no more '
              'separate _loadAddressAndBalance parsing.');
    });

    test('detail page writes its result to the shared store', () {
      final src = _readLib(
          'ui/crypto_wallet_engine_asset_detail_page.dart');


      final applyCount = RegExp(r'AssetLiveStore\.instance\.applyState\(')
          .allMatches(src).length;
      expect(applyCount, greaterThanOrEqualTo(2),
          reason: 'detail must apply state at loading and at completion '
              'so dashboard sees both transitions.');


      expect(src.contains("source: 'detail'"), isTrue,
          reason: 'detail writes must be tagged so DevTools log stream '
              'distinguishes them from dashboard writes.');
    });

    test('detail page reads publicAddress from the shared state result — '
        'no redundant receive fetch', () {
      final src = _readLib(
          'ui/crypto_wallet_engine_asset_detail_page.dart');



      expect(
        src.contains('result.publicAddress'),
        isTrue,
        reason: 'detail must read the address off the shared loader '
            'result — a redundant fetch would reintroduce race risk.',
      );
    });
  });



  group('Part 7 — no fake balance is ever written into store', () {

    setUp(() {
      AssetLiveStore.instance.resetForTest();
    });

    test('a noWallet write does NOT carry an amount', () {
      final store = AssetLiveStore.instance;
      final seq = store.claimSeq('ETH');
      store.applyState(
        source: 'detail', asset: 'ETH', seq: seq,
        state: const DashboardAssetLiveState.noWallet(),
      );
      final s = store.getState('ETH')!;
      expect(s.balanceAmount, isNull);
      expect(s.balanceUnit, isNull);
    });

    test('a reason write does NOT carry an amount', () {
      final store = AssetLiveStore.instance;
      final seq = store.claimSeq('ETH');
      store.applyState(
        source: 'detail', asset: 'ETH', seq: seq,
        state: const DashboardAssetLiveState.reason(reason: 'rpc_error'),
      );
      final s = store.getState('ETH')!;
      expect(s.balanceAmount, isNull);
      expect(s.balanceUnit, isNull);
    });
  });
}
