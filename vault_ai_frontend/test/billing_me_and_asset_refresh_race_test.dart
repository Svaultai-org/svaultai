


import 'dart:io';

import 'package:flutter_test/flutter_test.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


String _extractRefreshBilling(String src) {
  final start = src.indexOf('Future<void> refreshBilling(');
  expect(start, greaterThan(0),
      reason: 'refreshBilling method must exist in main.dart');
  final end = src.indexOf('Future<void> retryBilling(', start);
  expect(end, greaterThan(start));
  return src.substring(start, end);
}

String _extractRefreshLiveAsset(String src) {
  final start = src.indexOf('Future<void> _refreshLiveAssetState(');
  expect(start, greaterThan(0));




  final scope = src.substring(start);
  final closeIdx = scope.indexOf('\n  String get _effectiveNetwork');
  expect(closeIdx, greaterThan(0),
      reason: '_refreshLiveAssetState scope end marker must be present');
  return scope.substring(0, closeIdx);
}


void main() {


  group('Part A — refreshBilling has sequence protection (older failure '
      'cannot overwrite newer success)', () {

    test('AppState declares _billingRefreshSeq and '
        '_billingRefreshLatestApplied fields', () {
      final src = _readLib('main.dart');
      expect(src.contains('int _billingRefreshSeq = 0;'), isTrue,
          reason: 'refresh sequence counter must be an AppState field');
      expect(src.contains('int _billingRefreshLatestApplied = 0;'), isTrue,
          reason: 'latest-applied marker must be an AppState field so '
              'older refreshes can be dropped');
    });

    test('refreshBilling increments seq before the network call', () {
      final scope = _extractRefreshBilling(_readLib('main.dart'));


      final incIdx = scope.indexOf('final seq = ++_billingRefreshSeq;');
      final callIdx = scope.indexOf('.getBillingMe(');
      expect(incIdx, greaterThan(0),
          reason: 'refreshBilling must claim a sequence number before the '
              'network call.');
      expect(callIdx, greaterThan(incIdx),
          reason: 'seq++ must happen BEFORE the network call so we know '
              'which call is newer.');
    });

    test('refreshBilling drops stale SUCCESS if a newer call already applied '
        'a result', () {
      final scope = _extractRefreshBilling(_readLib('main.dart'));


      expect(
        scope.contains('if (seq < _billingRefreshLatestApplied)'),
        isTrue,
        reason: 'a stale-success guard must exist so a slow success cannot '
            'clobber the newer response.',
      );

      expect(
        scope.contains('errorCode: \'ok_stale\''),
        isTrue,
        reason: 'stale-success must be logged with a distinguishable code.',
      );

      expect(
        scope.contains('stateAfter: \'unchanged_stale_win\''),
        isTrue,
        reason: 'stale-success must not mutate billingLoadState.',
      );
    });

    test('refreshBilling drops stale FAILURE when a newer 200 already '
        'landed (the exact bug: /billing/me 200 but banner still on)', () {
      final scope = _extractRefreshBilling(_readLib('main.dart'));


      final catchIdx = scope.indexOf('} catch (e) {');
      expect(catchIdx, greaterThan(0));
      final catchScope = scope.substring(catchIdx);


      expect(
        catchScope.contains('if (seq < _billingRefreshLatestApplied)'),
        isTrue,
        reason: 'the error path must guard against overwriting a newer '
            'success — this is the CORE FIX for "/billing/me 200 but '
            'banner still shows".',
      );

      expect(
        catchScope.contains('_stale'),
        isTrue,
        reason: 'stale-error path must be logged with a distinguishable '
            'code so we can diagnose it in DevTools.',
      );

      expect(
        catchScope.contains('unchanged_success_holds'),
        isTrue,
        reason: 'the stale-failure path must NOT mutate '
            'billingLoadState/billingLoadError — the earlier success '
            'holds.',
      );



      final classifyIdx = catchScope.indexOf('classifyBillingMeError(e)');
      final guardIdx = catchScope.indexOf(
          'if (seq < _billingRefreshLatestApplied)');
      final loadStateWriteIdx = catchScope.indexOf(
          'billingLoadState = BillingLoadState.error');
      expect(classifyIdx, greaterThan(0));
      expect(guardIdx, greaterThan(classifyIdx),
          reason: 'guard must be evaluated before we write error state');
      expect(loadStateWriteIdx, greaterThan(guardIdx),
          reason: 'error-state write must be gated behind the sequence '
              'guard.');
    });

    test('refreshBilling logs billing_me_state_after_success on success '
        'path (visible confirmation for the user)', () {
      final scope = _extractRefreshBilling(_readLib('main.dart'));


      final logIdx = scope.indexOf('_logDevBillingMeStateAfterSuccess()');
      final notifyIdx = scope.indexOf('notifyListeners();', logIdx);
      expect(logIdx, greaterThan(0),
          reason: 'refreshBilling must emit the state-after-success log '
              'so the user can verify loaded=true, error=false in '
              'DevTools.');
      expect(notifyIdx, greaterThan(logIdx),
          reason: 'log must fire AFTER state assignment (loaded=true) '
              'and BEFORE notifyListeners so the log reflects the state '
              'the UI is about to see.');
    });

    test('billing_me_state_after_success log line names the exact fields', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('void _logDevBillingMeStateAfterSuccess(');
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 600);

      expect(scope.contains('if (!kDebugMode) return;'), isTrue);
      expect(scope.contains('billing_me_state_after_success'), isTrue);
      expect(scope.contains('loaded='), isTrue);
      expect(scope.contains('error='), isTrue);
      expect(scope.contains('banner_should_show='), isTrue);
    });
  });



  group('Part B — per-asset live refresh routes ALL writes through the '
      'shared store (single-source-of-truth)', () {

    test('_CryptoWalletEnginePageState delegates seq bookkeeping to the '
        'shared AssetLiveStore singleton — no more widget-local seq maps',
        () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');



      expect(src.contains('_liveAssetRefreshSeq'), isFalse,
          reason: 'per-asset seq map must live in AssetLiveStore, not '
              'the widget — otherwise detail-page and dashboard '
              'refreshes cannot see each other.');
      expect(src.contains('_liveAssetRefreshLatestApplied'), isFalse,
          reason: 'latest-applied bookkeeping must live in '
              'AssetLiveStore, not the widget.');



      expect(src.contains('AssetLiveStore.instance'), isTrue,
          reason: 'dashboard must reference the shared singleton store');
      expect(src.contains('_liveStore = AssetLiveStore.instance'), isTrue,
          reason: 'a stable field must hold the store instance');
    });

    test('_refreshLiveAssetState claims seq via _liveStore.claimSeq BEFORE '
        'the network call', () {
      final scope = _extractRefreshLiveAsset(
          _readLib('ui/crypto_wallet_engine_page.dart'));

      final claimIdx = scope.indexOf('_liveStore.claimSeq(asset)');
      final callIdx = scope.indexOf('loadAssetWalletState(');

      expect(claimIdx, greaterThan(0),
          reason: 'seq must be claimed via the shared store');
      expect(callIdx, greaterThan(claimIdx),
          reason: 'seq claim must come BEFORE the network call');
    });

    test('_refreshLiveAssetState routes ALL state writes through '
        '_liveStore.applyState (loading + result)', () {
      final scope = _extractRefreshLiveAsset(
          _readLib('ui/crypto_wallet_engine_page.dart'));



      final applyCount = RegExp(r'_liveStore\.applyState\(')
          .allMatches(scope).length;
      expect(applyCount, greaterThanOrEqualTo(2),
          reason: '_refreshLiveAssetState must call applyState twice: '
              'once for loading, once for the result — both go through '
              'the store\'s seq guard.');



      expect(scope.contains('_liveAssetState[asset] = '), isFalse,
          reason: 'no direct writes to a widget-local map are allowed — '
              'ALL writes must go through the shared store.');
    });

    test('AssetLiveStore.applyState enforces the stale-drop invariant '
        '(older failure cannot overwrite newer success)', () {
      final src = _readLib('services/asset_live_store.dart');

      expect(src.contains('if (seq < latest)'), isTrue,
          reason: 'stale drop guard required — this is what stops an older '
              'refresh from downgrading a newer success.');
      expect(src.contains('asset_live_store_drop_stale'), isTrue,
          reason: 'stale-drop must log distinguishably');
    });

    test('_refreshLiveAssetState log labels carry seq for debuggability', () {
      final scope = _extractRefreshLiveAsset(
          _readLib('ui/crypto_wallet_engine_page.dart'));


      expect(scope.contains('refresh_started asset='), isTrue);
      expect(scope.contains('refresh_done asset='), isTrue);
      expect(scope.contains('seq=\$seq'), isTrue,
          reason: 'log labels must include the seq token so we can '
              'correlate races in DevTools.');
    });
  });



  group('Part C — safe response-shape logs', () {

    test('main.dart wires _logDevBillingMeShape into refreshBilling '
        'success path', () {
      final scope = _extractRefreshBilling(_readLib('main.dart'));

      final shapeIdx = scope.indexOf('_logDevBillingMeShape(ent, seq: seq)');
      expect(shapeIdx, greaterThan(0),
          reason: 'refreshBilling must log the response shape after decode.');



      final applyIdx = scope.indexOf('billingEffectiveLimitBytes =');
      expect(applyIdx, greaterThan(shapeIdx),
          reason: 'shape log must fire BEFORE we apply fields — so the '
              'log reflects what the backend actually returned, not our '
              'defaulted state.');
    });

    test('_logDevBillingMeShape emits only top-level key names + '
        'field-present flags (no wallet/customer/subscription/token '
        'values)', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('void _logDevBillingMeShape(');
      expect(start, greaterThan(0));


      final scope = src.substring(start, start + 1400);

      expect(scope.contains('if (!kDebugMode) return;'), isTrue);



      expect(scope.contains('body_top_keys='), isTrue);
      expect(scope.contains('billing_state='), isTrue);
      expect(scope.contains('status='), isTrue);
      expect(scope.contains('included_bytes_present='), isTrue);
      expect(scope.contains('effective_limit_bytes_present='), isTrue);
      expect(scope.contains('has_active_subscription_present='), isTrue);



      const banned = ['stripe', 'customer_id', 'subscription_id',
                      'email', 'payment', 'card_number',
                      'authorization', 'bearer', 'account_id',
                      'sk_test', 'sk_live', 'pk_test', 'pk_live'];
      for (final b in banned) {
        expect(scope.toLowerCase().contains(b), isFalse,
            reason: 'shape log source must not literal-mention "$b"');
      }
    });

    test('shared balance loader emits balance_shape with '
        'balanceStatus/availableAmount_present/unit/reason', () {
      final src = _readLib('services/crypto_wallet_dashboard_reason.dart');
      final start = src.indexOf('Future<DashboardAssetLiveState> '
          'loadWalletReceiveAndBalance(');
      expect(start, greaterThan(0));


      final scope = src.substring(start);



      expect(scope.contains('balance_shape asset='), isTrue);
      expect(scope.contains('body_top_keys='), isTrue);
      expect(scope.contains('balanceStatus='), isTrue);
      expect(scope.contains('availableAmount_present='), isTrue);
      expect(scope.contains('unit='), isTrue);
      expect(scope.contains('reason='), isTrue);
    });

    test('shared balance loader shape log never logs address, token, '
        'API key, RPC URL, private key, encrypted secret, tx hash', () {
      final src = _readLib('services/crypto_wallet_dashboard_reason.dart');
      final start = src.indexOf('balance_shape asset=');
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 500);



      const banned = ['publicaddress', 'public_address', 'wallet_address',
                      'wallet_addr', 'rpc_url', 'api_key', 'apikey',
                      'authorization', 'bearer', 'private_key', 'privatekey',
                      'seed_phrase', 'seedphrase', 'mnemonic',
                      'tx_hash', 'txhash', 'encrypted_secret'];
      for (final b in banned) {
        expect(scope.toLowerCase().contains(b), isFalse,
            reason: 'balance_shape log must not literal-mention "$b"');
      }
    });
  });



  group('Part D — no secret leak across every new log label', () {

    test('every developer.log label added by this slice never carries '
        'address/token/rpc/api-key/private-key strings', () {
      final targets = [
        _readLib('main.dart'),
        _readLib('ui/crypto_wallet_engine_page.dart'),
        _readLib('services/crypto_wallet_dashboard_reason.dart'),
      ];



      const newLabels = [
        'billing_me_shape',
        'billing_me_state_after_success',
        'refresh_dropped_stale',
        'balance_shape',
        'ok_stale',
        'unchanged_stale_win',
        'unchanged_success_holds',
      ];

      for (final src in targets) {
        for (final label in newLabels) {
          if (!src.contains(label)) continue;
          final idx = src.indexOf(label);
          final chunk = src.substring(
            idx,
            (idx + 400 < src.length) ? idx + 400 : src.length,
          );
          const banned = ['stripe', 'customer_id', 'subscription_id',
                          'email', 'payment', 'card_number',
                          'sk_test', 'sk_live', 'pk_test', 'pk_live',
                          'authorization: bearer',
                          'private_key', 'privatekey', 'seed_phrase',
                          'seedphrase', 'mnemonic',
                          'tx_hash', 'txhash', 'encrypted_secret',
                          'rpc_url', 'api_key', 'apikey',
                          'wallet_address', 'wallet_addr'];
          for (final b in banned) {
            expect(chunk.toLowerCase().contains(b), isFalse,
                reason: 'log block for "$label" must not literal-mention '
                    '"$b"');
          }
        }
      }
    });
  });
}
