
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/crypto_chat_live_cache.dart';
import 'package:vault_ai_frontend/services/crypto_vault_chat_control.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_chat_cards.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


Widget _wrap(Widget child, {Size size = const Size(1200, 2400)}) {
  return MaterialApp(
    localizationsDelegates: _testL10nDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: SizedBox(
        width: size.width,
        height: size.height,
        child: SingleChildScrollView(child: child),
      ),
    ),
  );
}


CryptoVaultChatCard _card(Map<String, dynamic> raw) {
  return CryptoVaultChatCard.fromJson(raw);
}


class _MockClock {
  DateTime _now;
  _MockClock(this._now);
  DateTime call() => _now;
  void advance(Duration d) { _now = _now.add(d); }
}


class _CallCounter {
  int calls = 0;
  final Map<String, dynamic> response;
  final bool throwException;
  _CallCounter({required this.response, this.throwException = false});

  CryptoBalanceFetcher get fetcher =>
      ({required String asset, required String address}) async {
        calls++;
        if (throwException) {
          throw Exception('mock provider failure');
        }
        return response;
      };
}


void main() {


  group('CryptoChatLiveCache — unit', () {

    test('empty cache is idle', () {
      final cache = CryptoChatLiveCache();
      expect(cache.cacheSize,    0);
      expect(cache.inFlightSize, 0);
    });

    test('fetch returns run() and caches result', () async {
      final cache = CryptoChatLiveCache();
      final res = await cache.fetch(
        type: kCryptoChatCacheRequestBalance,
        asset: 'ETH', address: '0xabc',
        run: () async => {
          'balanceStatus':   'available',
          'availableAmount': '0',
          'unit':            'ETH',
        },
      );
      expect(res['availableAmount'], '0');
      expect(cache.cacheSize, 1);
      expect(cache.hasFresh(
        type: kCryptoChatCacheRequestBalance,
        asset: 'ETH', address: '0xabc'), isTrue);
    });

    test('second identical fetch returns cached value, no new run()',
        () async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      Future<Map<String, dynamic>> run() async {
        runs++;
        return {'balanceStatus': 'available', 'availableAmount': '1'};
      }
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      expect(runs, 1);
    });

    test('two concurrent identical fetches share the same future',
        () async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      Future<Map<String, dynamic>> run() async {
        runs++;
        await Future<void>.delayed(const Duration(milliseconds: 5));
        return {'balanceStatus': 'available', 'availableAmount': '0.5'};
      }
      final f1 = cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      final f2 = cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      expect(cache.inFlightSize, 1);
      final r1 = await f1;
      final r2 = await f2;
      expect(runs, 1);
      expect(r1, r2);
    });

    test('different assets do NOT dedupe', () async {
      final cache = CryptoChatLiveCache();
      var ethRuns = 0, solRuns = 0;
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1',
        run: () async { ethRuns++;
          return {'balanceStatus': 'available'}; },
      );
      await cache.fetch(
        type: 'balance', asset: 'SOL', address: 'sol1',
        run: () async { solRuns++;
          return {'balanceStatus': 'available'}; },
      );
      expect(ethRuns, 1);
      expect(solRuns, 1);
      expect(cache.cacheSize, 2);
    });

    test('different types (balance vs activity) do NOT dedupe',
        () async {
      final cache = CryptoChatLiveCache();
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1',
        run: () async => {'balanceStatus': 'available'},
      );
      await cache.fetch(
        type: 'activity', asset: 'ETH', address: '0x1',
        run: () async => {'activityStatus': 'available'},
      );
      expect(cache.cacheSize, 2);
    });

    test('TTL expiry allows refetch', () async {
      final clock = _MockClock(DateTime(2026, 7, 8, 12, 0));
      final cache = CryptoChatLiveCache(
        ttl: const Duration(seconds: 45),
        clock: clock.call,
      );
      var runs = 0;
      Future<Map<String, dynamic>> run() async {
        runs++;
        return {'balanceStatus': 'available', 'availableAmount': '$runs'};
      }
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      expect(runs, 1);

      clock.advance(const Duration(seconds: 44));
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      expect(runs, 1);

      clock.advance(const Duration(seconds: 2));
      final res = await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      expect(runs, 2);
      expect(res['availableAmount'], '2');
    });

    test('invalidate removes the entry', () async {
      final cache = CryptoChatLiveCache();
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1',
        run: () async => {'balanceStatus': 'available'},
      );
      cache.invalidate(
        type: 'balance', asset: 'ETH', address: '0x1',
      );
      expect(cache.hasFresh(
        type: 'balance', asset: 'ETH', address: '0x1'), isFalse);
    });

    test('clear() empties everything', () async {
      final cache = CryptoChatLiveCache();
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1',
        run: () async => {'balanceStatus': 'available'},
      );
      await cache.fetch(
        type: 'activity', asset: 'ETH', address: '0x1',
        run: () async => {'activityStatus': 'available'},
      );
      expect(cache.cacheSize, 2);
      cache.clear();
      expect(cache.cacheSize, 0);
    });

    test('XMR never gets cached — always bypasses', () async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      Future<Map<String, dynamic>> run() async {
        runs++;
        return {'balanceStatus': 'scanner_gated'};
      }
      await cache.fetch(
        type: 'balance', asset: 'XMR', address: 'xmr-addr', run: run,
      );
      await cache.fetch(
        type: 'balance', asset: 'XMR', address: 'xmr-addr', run: run,
      );

      expect(runs, 2);
      expect(cache.hasFresh(
        type: 'balance', asset: 'XMR', address: 'xmr-addr'), isFalse);
    });

    test('unavailable results are NOT cached — allows retry', () async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      final firstRes = {
        'balanceStatus': 'unavailable', 'reason': 'network_error',
      };
      final secondRes = {
        'balanceStatus': 'available', 'availableAmount': '0',
      };
      Future<Map<String, dynamic>> run() async {
        runs++;
        return runs == 1 ? firstRes : secondRes;
      }
      final r1 = await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      expect(r1['balanceStatus'], 'unavailable');


      final r2 = await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1', run: run,
      );
      expect(runs, 2);
      expect(r2['balanceStatus'], 'available');
    });

    test('empty asset or address bypasses cache — passthrough',
        () async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      Future<Map<String, dynamic>> run() async {
        runs++;
        return {'balanceStatus': 'available'};
      }
      await cache.fetch(
        type: 'balance', asset: '', address: '0x1', run: run,
      );
      await cache.fetch(
        type: 'balance', asset: '', address: '0x1', run: run,
      );
      expect(runs, 2);
      expect(cache.cacheSize, 0);
    });

    test('exception from run bubbles up and does not cache',
        () async {
      final cache = CryptoChatLiveCache();
      try {
        await cache.fetch(
          type: 'balance', asset: 'ETH', address: '0x1',
          run: () async => throw Exception('mock'),
        );
        fail('expected throw');
      } catch (_) {

      }
      expect(cache.cacheSize, 0);
      expect(cache.inFlightSize, 0);
    });

    test('forbidden keys are stripped before caching', () async {
      final cache = CryptoChatLiveCache();
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1',
        run: () async => {
          'balanceStatus':   'available',
          'availableAmount': '0.5',
          'privateKey':      'leak',
          'seed_phrase':     'leak',
          'signedTxHex':     '0xdead',
        },
      );

      final cached = await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0x1',
        run: () async => {'balanceStatus': 'available'},
      );
      expect(cached.containsKey('privateKey'), isFalse);
      expect(cached.containsKey('seed_phrase'), isFalse);
      expect(cached.containsKey('signedTxHex'), isFalse);
      expect(cached['availableAmount'], '0.5');
    });
  });



  group('Widget rebuild does not refetch — balance card', () {

    testWidgets(
        'ChatBubble rebuild reuses cached balance (no refetch)',
        (tester) async {
      final cache = CryptoChatLiveCache();
      final counter = _CallCounter(response: {
        'balanceStatus':   'available',
        'availableAmount': '0',
        'unit':            'ETH',
      });
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabc',
        },
      });


      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: counter.fetcher,
          cache: cache,
        ),
      ));
      await tester.pumpAndSettle();
      expect(counter.calls, 1);
      expect(find.text('0 ETH'), findsOneWidget);


      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: counter.fetcher,
          cache: cache,
        ),
      ));
      await tester.pumpAndSettle();


      expect(counter.calls, 1);
    });

    testWidgets(
        'two cards for same ETH+address share ONE in-flight request',
        (tester) async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      final fetcher = ({
        required String asset, required String address,
      }) async {
        runs++;
        await Future<void>.delayed(const Duration(milliseconds: 10));
        return {
          'balanceStatus':   'available',
          'availableAmount': '0',
          'unit':            'ETH',
        };
      };
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabc',
        },
      });


      await tester.pumpWidget(_wrap(
        Column(
          children: [
            CryptoVaultChatCardView(card: c,
                onFetchBalance: fetcher, cache: cache),
            CryptoVaultChatCardView(card: c,
                onFetchBalance: fetcher, cache: cache),
          ],
        ),
      ));
      await tester.pumpAndSettle();


      expect(runs, 1);
      expect(find.text('0 ETH'), findsNWidgets(2));
    });
  });



  group('Retry button', () {

    testWidgets(
        'balance card shows retry when live status is unavailable',
        (tester) async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      final fetcher = ({
        required String asset, required String address,
      }) async {
        runs++;
        if (runs == 1) {
          return {
            'balanceStatus': 'unavailable',
            'reason':        'rpc_not_configured',
          };
        }
        return {
          'balanceStatus':   'available',
          'availableAmount': '0',
          'unit':            'ETH',
        };
      };
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabc',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c, onFetchBalance: fetcher, cache: cache,
        ),
      ));
      await tester.pumpAndSettle();

      expect(runs, 1);
      expect(find.byKey(
          const Key('crypto_vault_chat_balance_retry')),
          findsOneWidget);


      await tester.tap(find.byKey(
          const Key('crypto_vault_chat_balance_retry')));
      await tester.pumpAndSettle();


      expect(runs, 2);
      expect(find.text('0 ETH'), findsOneWidget);
    });

    testWidgets(
        'activity card shows retry when provider fails',
        (tester) async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      final fetcher = ({
        required String asset,
        required String address,
        int limit = 10,
      }) async {
        runs++;
        if (runs == 1) {
          throw Exception('mock indexer down');
        }
        return {'transactions': const <dynamic>[]};
      };
      final c = _card({
        'cardType': 'crypto_vault_activity_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_activity_data_v1',
          'available':      true,
          'asset':          'ETH',
          'activityStatus': 'pending_live_fetch',
          'entries':        const <dynamic>[],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c, onFetchActivity: fetcher, cache: cache,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(
          const Key('crypto_vault_chat_activity_retry')),
          findsOneWidget);


      await tester.tap(find.byKey(
          const Key('crypto_vault_chat_activity_retry')));
      await tester.pumpAndSettle();
      expect(runs, 2);
      expect(find.byKey(
          const Key('crypto_vault_chat_activity_empty')),
          findsOneWidget);
    });
  });



  group('XMR never fetches even with cache', () {

    testWidgets('XMR balance card does not invoke fetcher',
        (tester) async {
      final cache = CryptoChatLiveCache();
      final counter = _CallCounter(response: {
        'balanceStatus': 'available', 'availableAmount': '0',
      });
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'XMR',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'XMR',
          'label':          'XMR',
          'balanceStatus':  'scanner_gated',
          'reason':         'scanner_requires_desktop',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c, onFetchBalance: counter.fetcher, cache: cache,
        ),
      ));
      await tester.pumpAndSettle();
      expect(counter.calls, 0);
      expect(cache.cacheSize, 0);
    });
  });



  group('Cache scoping (overview shares cache with balance)', () {

    testWidgets(
        'overview populates row, subsequent balance card uses cached '
        'value without refetch',
        (tester) async {
      final cache = CryptoChatLiveCache();
      var runs = 0;
      final fetcher = ({
        required String asset, required String address,
      }) async {
        runs++;
        return {
          'balanceStatus':   'available',
          'availableAmount': '2.5',
          'unit':            'ETH',
        };
      };


      final overviewCard = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            {
              'asset': 'ETH', 'label': 'ETH', 'network': 'ethereum',
              'balanceStatus': 'pending_live_fetch',
              'receiveReady':  true, 'sendEnabled':  true,
              'publicAddress': '0xabc',
            },
          ],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: overviewCard,
          onFetchBalance: fetcher,
          cache: cache,
        ),
      ));
      await tester.pumpAndSettle();
      expect(runs, 1);


      final balanceCard = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabc',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: balanceCard,
          onFetchBalance: fetcher,
          cache: cache,
        ),
      ));
      await tester.pumpAndSettle();


      expect(runs, 1);
      expect(find.text('2.5 ETH'), findsOneWidget);
    });
  });



  group('No secrets visible', () {

    testWidgets(
        'fetcher response with forbidden keys — nothing leaks '
        'through cache into widget tree',
        (tester) async {
      final cache = CryptoChatLiveCache();
      final fetcher = ({
        required String asset, required String address,
      }) async => {
        'balanceStatus':   'available',
        'availableAmount': '1',
        'unit':            'ETH',

        'privateKey':      'super-secret-privatekey-abc',
        'seed_phrase':     'correct horse battery staple',
        'signedTxHex':     '0xdeadbeef01234567',
        'authToken':       'sk_live_leaked_token',
      };
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabc',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c, onFetchBalance: fetcher, cache: cache,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('1 ETH'), findsOneWidget);


      expect(find.textContaining('super-secret'),  findsNothing);
      expect(find.textContaining('correct horse'), findsNothing);
      expect(find.textContaining('0xdeadbeef'),    findsNothing);
      expect(find.textContaining('sk_live'),       findsNothing);


      final cached = await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0xabc',
        run: () async => {'balanceStatus': 'available'},
      );
      for (final k in [
        'privateKey', 'seed_phrase', 'signedTxHex', 'authToken',
      ]) {
        expect(cached.containsKey(k), isFalse,
            reason: 'forbidden key $k leaked into cached envelope');
      }
    });
  });



  group('Mobile overflow safety with retry buttons', () {

    testWidgets('balance card with retry button fits 400x900',
        (tester) async {
      final cache = CryptoChatLiveCache();
      final fetcher = ({
        required String asset, required String address,
      }) async => {
        'balanceStatus': 'unavailable',
        'reason':        'rpc_not_configured_super_long_reason_slug',
      };
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabc',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c, onFetchBalance: fetcher, cache: cache,
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.byKey(
          const Key('crypto_vault_chat_balance_retry')),
          findsOneWidget);
    });

    testWidgets('activity card with retry button fits 400x900',
        (tester) async {
      final cache = CryptoChatLiveCache();
      final fetcher = ({
        required String asset, required String address,
        int limit = 10,
      }) async => throw Exception('boom');
      final c = _card({
        'cardType': 'crypto_vault_activity_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_activity_data_v1',
          'available':      true,
          'asset':          'ETH',
          'activityStatus': 'pending_live_fetch',
          'entries':        const <dynamic>[],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c, onFetchActivity: fetcher, cache: cache,
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.byKey(
          const Key('crypto_vault_chat_activity_retry')),
          findsOneWidget);
    });

    testWidgets('overview retry button appears when a row fails, '
                'fits at 400x900',
        (tester) async {
      final cache = CryptoChatLiveCache();
      final fetcher = ({
        required String asset, required String address,
      }) async {
        if (asset == 'ETH') {
          throw Exception('provider failure');
        }
        return {
          'balanceStatus':   'available',
          'availableAmount': '2',
          'unit':            'SOL',
        };
      };
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            {
              'asset': 'ETH', 'label': 'ETH', 'network': 'ethereum',
              'balanceStatus': 'pending_live_fetch',
              'receiveReady':  true, 'sendEnabled':  true,
              'publicAddress': '0xabc',
            },
            {
              'asset': 'SOL', 'label': 'SOL', 'network': 'solana',
              'balanceStatus': 'pending_live_fetch',
              'receiveReady':  true, 'sendEnabled':  true,
              'publicAddress': 'sol1',
            },
          ],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c, onFetchBalance: fetcher, cache: cache,
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);


      expect(find.byKey(
          const Key('crypto_vault_chat_show_vault_retry_failed')),
          findsOneWidget);
    });
  });
}
