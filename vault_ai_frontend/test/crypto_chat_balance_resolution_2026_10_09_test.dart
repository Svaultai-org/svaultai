import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart' show resolveCryptoChatBalance;
import 'package:vault_ai_frontend/services/crypto_chat_live_cache.dart';
import 'package:vault_ai_frontend/services/crypto_vault_chat_control.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/ui/crypto_vault_chat_cards.dart';

const _baseUrl = 'http://127.0.0.1:9';
const _address = '0x2222222222222222222222222222222222222222';
Map<String, dynamic> _available(String amount) => {
      'balanceStatus': 'available',
      'availableAmount': amount,
      'unit': 'ETH',
    };
http.Response _json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

Future<Map<String, dynamic>> _resolve({
  String asset = 'ETH',
  String network = 'ethereum_mainnet',
  String address = '',
  bool Function()? current,
  Duration timeout = const Duration(seconds: 1),
}) =>
    resolveCryptoChatBalance(
      baseUrl: _baseUrl,
      network: network,
      asset: asset,
      address: address,
      authToken: 'balance-synthetic-session',
      accessIsCurrent: current ?? () => true,
      timeout: timeout,
    );

CryptoVaultChatCard _card({String address = '', String asset = 'ETH'}) =>
    CryptoVaultChatCard.fromJson({
      'cardType': 'crypto_vault_balance_card',
      'asset': asset,
      'data': {
        'schema': 'crypto_balance_data_v1',
        'available': true,
        'asset': asset,
        'label': asset,
        'balanceStatus': 'pending_live_fetch',
        'publicAddress': address,
      },
    });

Widget _view(CryptoVaultChatCard card, CryptoBalanceFetcher fetch,
        {CryptoChatLiveCache? cache}) =>
    MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Scaffold(
          body: SingleChildScrollView(
              child: CryptoVaultChatCardView(
        key: const Key('balance-under-test'),
        card: card,
        onFetchBalance: fetch,
        cache: cache,
      ))),
    );

void main() {
  setUp(() {
    SessionTermination.instance.reset();
    setApiClientDeviceId('balance-synthetic-device');
  });
  tearDown(() {
    SessionTermination.instance.reset();
    setApiClientDeviceId('');
  });

  for (final entry in {
    'ETH': 'ethereum_mainnet',
    'USDT_ERC20': 'ethereum_mainnet',
    'USDC_ERC20': 'ethereum_mainnet',
    'SOL': 'solana_mainnet',
    'USDT_TRC20': 'tron_mainnet',
  }.entries) {
    test(
        '${entry.key} missing address resolves existing receive then balance once',
        () async {
      final paths = <String>[];
      await http.runWithClient(() async {
        final result = await _resolve(asset: entry.key, network: entry.value);
        expect(result['availableAmount'], '1.25');
        expect(paths, [
          '/crypto/wallet/network/${entry.value}/${entry.key}/receive',
          '/crypto/wallet/network/${entry.value}/${entry.key}/balance',
        ]);
      },
          () => MockClient((request) async {
                expect(request.method, 'GET');
                expect(request.url.origin, _baseUrl);
                expect(request.headers['Authorization'],
                    'Bearer balance-synthetic-session');
                expect(
                    request.headers['X-Device-Id'], 'balance-synthetic-device');
                paths.add(request.url.path);
                if (request.url.path.endsWith('/receive')) {
                  return _json({
                    'wallet_engine': 'receive_ready',
                    'publicAddress': _address
                  });
                }
                expect(request.url.queryParameters['address'], _address);
                return _json(_available('1.25'));
              }));
    });
  }

  test('existing nonempty address skips receive without changing balance',
      () async {
    final paths = <String>[];
    await http.runWithClient(() async {
      expect((await _resolve(address: _address))['availableAmount'], '0');
      expect(paths, ['/crypto/wallet/network/ethereum_mainnet/ETH/balance']);
    },
        () => MockClient((request) async {
              paths.add(request.url.path);
              return _json(_available('0'));
            }));
  });

  for (final receive in [
    {'wallet_engine': 'no_account'},
    {'wallet_engine': 'receive_ready', 'publicAddress': ''},
    {'wallet_engine': 'unavailable', 'publicAddress': _address},
  ]) {
    test(
        'receive refusal ${receive['wallet_engine']} is terminal without a fake zero',
        () async {
      var calls = 0;
      await http.runWithClient(() async {
        final result = await _resolve();
        expect(result['balanceStatus'], 'unavailable');
        expect(result['availableAmount'], isNull);
        expect(calls, 1);
      },
          () => MockClient((request) async {
                calls++;
                expect(request.url.path, endsWith('/receive'));
                return _json(receive);
              }));
    });
  }

  test('total timeout prevents late receive from starting balance', () async {
    final receive = Completer<http.Response>();
    var calls = 0;
    await http.runWithClient(() async {
      final result = await _resolve(timeout: const Duration(milliseconds: 10));
      expect(result['reason'], 'request_timed_out');
      receive.complete(
          _json({'wallet_engine': 'receive_ready', 'publicAddress': _address}));
      await Future<void>.delayed(Duration.zero);
      expect(calls, 1);
    },
        () => MockClient((_) {
              calls++;
              return receive.future;
            }));
  });

  test(
      'access invalidated during receive cannot start balance or terminate a new session',
      () async {
    final receive = Completer<http.Response>();
    var current = true;
    var calls = 0;
    await http.runWithClient(() async {
      final pending = _resolve(current: () => current);
      final assertion = expectLater(pending, throwsA(isA<StateError>()));
      await Future<void>.delayed(Duration.zero);
      current = false;
      receive.complete(_json({
        'detail': {'code': 'session_superseded'}
      }, 401));
      await assertion;
      expect(calls, 1);
      expect(SessionTermination.instance.isTerminated, isFalse);
    },
        () => MockClient((_) {
              calls++;
              return receive.future;
            }));
  });

  test('late balance after access loss throws and cannot repopulate cache',
      () async {
    final balance = Completer<http.Response>();
    final cache = CryptoChatLiveCache();
    var current = true;
    await http.runWithClient(() async {
      final pending = cache.fetch(
        type: kCryptoChatCacheRequestBalance,
        asset: 'ETH',
        address: _address,
        run: () => _resolve(address: _address, current: () => current),
      );
      final assertion = expectLater(pending, throwsA(isA<StateError>()));
      await Future<void>.delayed(Duration.zero);
      current = false;
      cache.clear();
      balance.complete(_json(_available('500')));
      await assertion;
      expect(cache.cacheSize, 0);
      expect(cache.inFlightSize, 0);
    }, () => MockClient((_) => balance.future));
  });

  testWidgets(
      'empty-address card bypasses shared cache and repeated rebuild does not duplicate fetch',
      (tester) async {
    final response = Completer<Map<String, dynamic>>();
    final cache = CryptoChatLiveCache();
    var calls = 0;
    Future<Map<String, dynamic>> fetch(
        {required String asset, required String address}) {
      expect(address, isEmpty);
      calls++;
      return response.future;
    }

    await tester.pumpWidget(_view(_card(), fetch, cache: cache));
    await tester.pumpWidget(_view(_card(), fetch, cache: cache));
    expect(calls, 1);
    expect(cache.inFlightSize, 0);
    response.complete(_available('2.5'));
    await tester.pumpAndSettle();
    expect(find.text('2.5 ETH'), findsOneWidget);
    expect(find.byKey(const Key('crypto_vault_chat_balance_loading')),
        findsNothing);
    expect(cache.cacheSize, 0);
  });

  testWidgets(
      'timed-out cached fetch releases in-flight and Retry is single-flight',
      (tester) async {
    final blocked = Completer<Map<String, dynamic>>();
    final retry = Completer<Map<String, dynamic>>();
    final cache = CryptoChatLiveCache();
    var calls = 0;
    Future<Map<String, dynamic>> fetch(
            {required String asset, required String address}) =>
        ++calls == 1 ? blocked.future : retry.future;
    await tester
        .pumpWidget(_view(_card(address: _address), fetch, cache: cache));
    await tester
        .pump(kCryptoChatBalanceFetchTimeout + const Duration(milliseconds: 1));
    await tester.pump();
    expect(cache.inFlightSize, 0);
    expect(find.byKey(const Key('crypto_vault_chat_balance_loading')),
        findsNothing);
    final retryButton =
        find.byKey(const Key('crypto_vault_chat_balance_retry'));
    expect(retryButton, findsOneWidget);
    await tester.tap(retryButton);
    await tester.tap(retryButton);
    expect(calls, 2);
    retry.complete(_available('3'));
    await tester.pumpAndSettle();
    blocked.complete(_available('999'));
    await tester.pumpAndSettle();
    expect(find.text('3 ETH'), findsOneWidget);
    expect(find.text('999 ETH'), findsNothing);
    expect(
        cache.peek(
            type: kCryptoChatCacheRequestBalance,
            asset: 'ETH',
            address: _address)?['availableAmount'],
        '3');
  });

  testWidgets('no-wallet response stops loading and allows a safe retry',
      (tester) async {
    var calls = 0;
    Future<Map<String, dynamic>> fetch(
        {required String asset, required String address}) async {
      calls++;
      return {
        'balanceStatus': 'unavailable',
        'reason': 'no_wallet',
        'availableAmount': null,
      };
    }

    await tester.pumpWidget(_view(_card(), fetch));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('crypto_vault_chat_balance_loading')),
        findsNothing);
    expect(find.byKey(const Key('crypto_vault_chat_balance_display_value')),
        findsNothing);
    final retry = find.byKey(const Key('crypto_vault_chat_balance_retry'));
    expect(retry, findsOneWidget);
    await tester.tap(retry);
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.byKey(const Key('crypto_vault_chat_balance_display_value')),
        findsNothing);
  });

  testWidgets(
      'same-asset changed address drops an old result and old finalizer',
      (tester) async {
    final old = Completer<Map<String, dynamic>>();
    final next = Completer<Map<String, dynamic>>();
    final addresses = <String>[];
    Future<Map<String, dynamic>> fetch(
        {required String asset, required String address}) {
      addresses.add(address);
      return address == 'old' ? old.future : next.future;
    }

    await tester.pumpWidget(_view(_card(address: 'old'), fetch));
    await tester.pumpWidget(_view(_card(address: 'next'), fetch));
    expect(addresses, ['old', 'next']);
    old.complete(_available('999'));
    await tester.pump();
    expect(find.text('999 ETH'), findsNothing);
    next.complete(_available('4'));
    await tester.pumpAndSettle();
    expect(find.text('4 ETH'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('XMR remains scanner-gated with no live lookup', (tester) async {
    var calls = 0;
    await tester.pumpWidget(
        _view(_card(asset: 'XMR'), ({required asset, required address}) async {
      calls++;
      return _available('0');
    }));
    await tester.pump();
    expect(calls, 0);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
