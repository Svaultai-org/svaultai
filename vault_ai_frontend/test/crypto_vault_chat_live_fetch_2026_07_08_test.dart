
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
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


CryptoBalanceFetcher _fixedBalanceFetcher(
  Map<String, dynamic> response, {
  Duration delay = Duration.zero,
  List<String>? callsSink,
}) {
  return ({required String asset, required String address}) async {
    callsSink?.add('$asset|$address');
    if (delay > Duration.zero) {
      await Future<void>.delayed(delay);
    }
    return response;
  };
}


CryptoBalanceFetcher _perAssetBalanceFetcher(
  Map<String, Map<String, dynamic>> byAsset,
) {
  return ({required String asset, required String address}) async {
    return byAsset[asset] ?? {
      'balanceStatus': 'unavailable',
      'reason':        'not_configured',
    };
  };
}


CryptoBalanceFetcher _throwingBalanceFetcher() {
  return ({required String asset, required String address}) async {
    throw Exception('mock network failure');
  };
}


CryptoActivityFetcher _fixedActivityFetcher(
  Map<String, dynamic> response,
) {
  return ({
    required String asset,
    required String address,
    int limit = 10,
  }) async {
    return response;
  };
}


void main() {


  group('Balance card live fetch', () {

    testWidgets('ETH real zero renders "0 ETH" from provider result',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabcdef',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'schema':          'crypto_wallet_balance_v1',
            'balanceStatus':   'available',
            'availableAmount': '0',
            'unit':            'ETH',
          }),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(
          const Key('crypto_vault_chat_balance_display_value')),
          findsOneWidget);
      expect(find.text('0 ETH'), findsOneWidget);
    });

    testWidgets('USDT ERC20 real zero renders "0 USDT"',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'USDT_ERC20',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'USDT_ERC20',
          'label':          'USDT (ERC20)',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabcdef',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'available',
            'availableAmount': '0',
            'unit':            'USDT',
          }),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('0 USDT'), findsOneWidget);
    });

    testWidgets('USDC real zero renders "0 USDC"', (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'USDC_ERC20',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'USDC_ERC20',
          'label':          'USDC (ERC20)',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabcdef',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'available',
            'availableAmount': '0',
            'unit':            'USDC',
          }),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('0 USDC'), findsOneWidget);
    });

    testWidgets('SOL real zero renders "0 SOL"', (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'SOL',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'SOL',
          'label':          'SOL',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  'SoLLLLLL',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'available',
            'availableAmount': '0',
            'unit':            'SOL',
          }),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('0 SOL'), findsOneWidget);
    });

    testWidgets('USDT TRC20 real zero renders "0 USDT"',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'USDT_TRC20',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'USDT_TRC20',
          'label':          'USDT (TRC20)',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  'TXTronAddr',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'available',
            'availableAmount': '0',
            'unit':            'USDT',
          }),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('0 USDT'), findsOneWidget);
    });

    testWidgets('provider unavailable → shows reason, no fake zero',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabcdef',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'unavailable',
            'availableAmount': null,
            'reason':          'rpc_not_configured',
          }),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('0 ETH'), findsNothing);

      expect(find.byKey(
          const Key('crypto_vault_chat_balance_display_value')),
          findsNothing);
    });

    testWidgets('provider throws → widget shows unavailable, no crash',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabcdef',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _throwingBalanceFetcher(),
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('0 ETH'), findsNothing);
    });

    testWidgets(
        'XMR balance card is scanner-gated and never shows 0 XMR '
        'even if provider is called',
        (tester) async {
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
      final calls = <String>[];
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'available',
            'availableAmount': '0',
            'unit':            'XMR',
          }, callsSink: calls),
        ),
      ));
      await tester.pumpAndSettle();

      expect(calls.isEmpty, isTrue,
          reason: 'XMR scanner-gated must not trigger a provider call');

      expect(find.text('0 XMR'), findsNothing);
      expect(find.byKey(
          const Key('crypto_vault_chat_balance_gated')),
          findsOneWidget);
    });

    testWidgets(
        'fetcher never called if backend status is not pending_live_fetch',
        (tester) async {
      final calls = <String>[];
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'available',
          'displayBalance': '1 ETH',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher(
            {'balanceStatus': 'available', 'availableAmount': '999'},
            callsSink: calls,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(calls.isEmpty, isTrue);
      expect(find.text('1 ETH'), findsOneWidget);
      expect(find.text('999 ETH'), findsNothing);
    });

    testWidgets('fetcher NOT called if publicAddress missing',
        (tester) async {
      final calls = <String>[];
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',


        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher(
            {'balanceStatus': 'available', 'availableAmount': '0'},
            callsSink: calls,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(calls.isEmpty, isTrue);
    });
  });



  group('Crypto overview live fetch — per-asset', () {

    testWidgets('each row fetched independently; success rows show '
                'balance, failed rows show reason',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            {
              'asset': 'ETH', 'label': 'ETH', 'network': 'ethereum',
              'balanceStatus': 'pending_live_fetch',
              'receiveReady':  true, 'sendEnabled': true,
              'publicAddress': '0xETH',
            },
            {
              'asset': 'USDT_ERC20', 'label': 'USDT (ERC20)',
              'network': 'ethereum',
              'balanceStatus': 'pending_live_fetch',
              'receiveReady':  true, 'sendEnabled': true,
              'publicAddress': '0xETH',
            },
            {
              'asset': 'XMR', 'label': 'XMR', 'network': 'monero',
              'balanceStatus': 'scanner_gated',
              'reason':        'scanner_requires_desktop',
              'receiveReady':  false, 'sendEnabled': false,
            },
          ],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _perAssetBalanceFetcher({

            'ETH': {
              'balanceStatus':   'available',
              'availableAmount': '0.5',
              'unit':            'ETH',
            },


            'USDT_ERC20': {
              'balanceStatus':   'unavailable',
              'reason':          'rpc_not_configured',
            },
          }),
        ),
      ));
      await tester.pumpAndSettle();


      expect(find.textContaining('0.5 ETH'), findsAtLeastNWidgets(1));


      expect(find.textContaining('999'), findsNothing);


      expect(find.byKey(
          const Key('crypto_vault_chat_show_vault_row_XMR')),
          findsOneWidget);
    });

    testWidgets(
        'one failed provider does not break other rows',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            {
              'asset': 'ETH', 'label': 'ETH', 'network': 'ethereum',
              'balanceStatus': 'pending_live_fetch',
              'receiveReady':  true, 'sendEnabled': true,
              'publicAddress': '0xETH',
            },
            {
              'asset': 'SOL', 'label': 'SOL', 'network': 'solana',
              'balanceStatus': 'pending_live_fetch',
              'receiveReady':  true, 'sendEnabled': true,
              'publicAddress': 'SoL',
            },
          ],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: ({
            required String asset,
            required String address,
          }) async {
            if (asset == 'ETH') {
              throw Exception('provider failed');
            }
            return {
              'balanceStatus':   'available',
              'availableAmount': '2',
              'unit':            'SOL',
            };
          },
        ),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);

      expect(find.textContaining('2 SOL'), findsAtLeastNWidgets(1));
    });

    testWidgets(
        'overview never renders a numeric balance for XMR row',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            {
              'asset': 'XMR', 'label': 'XMR', 'network': 'monero',
              'balanceStatus': 'scanner_gated',
              'reason':        'scanner_requires_desktop',
              'receiveReady':  false, 'sendEnabled': false,
            },
          ],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'available',
            'availableAmount': '0',
            'unit':            'XMR',
          }),
        ),
      ));
      await tester.pumpAndSettle();

      expect(
        find.byWidgetPredicate((w) =>
            w is Text
            && RegExp(r'^\s*0(\.\d+)?\s*XMR\s*$').hasMatch(w.data ?? '')),
        findsNothing,
      );
    });
  });



  group('Activity card live fetch', () {

    testWidgets(
        'ready empty response renders "No activity yet"',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_activity_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_activity_data_v1',
          'available':      true,
          'asset':          'ETH',
          'activityStatus': 'pending_live_fetch',
          'entries':        [],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchActivity: _fixedActivityFetcher({
            'schema':       'crypto_wallet_transactions_v1',
            'transactions': [],
          }),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(
          const Key('crypto_vault_chat_activity_empty')),
          findsOneWidget);
    });

    testWidgets('real entries render safe txn rows',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_activity_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_activity_data_v1',
          'available':      true,
          'asset':          'ETH',
          'activityStatus': 'pending_live_fetch',
          'entries':        [],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchActivity: _fixedActivityFetcher({
            'transactions': [
              {
                'direction': 'in',
                'status':    'confirmed',
                'hash':      '0xdeadbeef01234567',
              },
              {
                'direction': 'out',
                'status':    'pending',
                'hash':      '0xdeadbeef89abcdef',
              },
            ],
          }),
        ),
      ));
      await tester.pumpAndSettle();


      expect(find.textContaining('in ·'),
          findsAtLeastNWidgets(1));
      expect(find.textContaining('out ·'),
          findsAtLeastNWidgets(1));


      expect(find.byKey(
          const Key('crypto_vault_chat_activity_empty')),
          findsNothing);
    });

    testWidgets(
        'XMR activity stays scanner_gated — fetcher never called',
        (tester) async {
      var fetcherCalls = 0;
      final c = _card({
        'cardType': 'crypto_vault_activity_card',
        'asset':    'XMR',
        'data': {
          'schema':         'crypto_activity_data_v1',
          'available':      true,
          'asset':          'XMR',
          'activityStatus': 'scanner_gated',
          'reason':         'scanner_requires_desktop',
          'entries':        [],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchActivity: ({
            required String asset,
            required String address,
            int limit = 10,
          }) async {
            fetcherCalls++;
            return {'transactions': []};
          },
        ),
      ));
      await tester.pumpAndSettle();

      expect(fetcherCalls, 0);
      expect(find.byKey(
          const Key('crypto_vault_chat_activity_scanner_gated')),
          findsOneWidget);
    });

    testWidgets('provider unavailable renders unavailable copy',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_activity_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_activity_data_v1',
          'available':      true,
          'asset':          'ETH',
          'activityStatus': 'pending_live_fetch',
          'entries':        [],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchActivity: ({
            required String asset,
            required String address,
            int limit = 10,
          }) async {
            throw Exception('mock indexer down');
          },
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(
          const Key('crypto_vault_chat_activity_unavailable')),
          findsOneWidget);
    });
  });



  group('Send draft never broadcasts even with live fetch wired', () {

    testWidgets('send draft carries canBroadcast=false always',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_send_draft_card',
        'asset':     'ETH',
        'amount':    '5',
        'recipient': '0xabc',

        'canBroadcast': true,
        'data': {
          'schema':       'crypto_send_draft_data_v1',
          'available':    true,
          'asset':        'ETH',
          'network':      'ethereum',
          'canBroadcast': false,
          'requiresPinUnlock':            true,
          'requiresTrustedDevice':        true,
          'requiresLocalSigning':         true,
          'requiresExplicitConfirmation': true,
        },
      });
      expect(c.canBroadcast, isFalse);
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(card: c),
      ));
      await tester.pump();
      expect(find.byKey(
          const Key('crypto_vault_chat_send_never_broadcasts')),
          findsOneWidget);
    });
  });



  group('Mobile overflow safety with live fetch', () {

    testWidgets('balance card live-fetched fits at 400x900',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabcdef0123456789abcdef',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'available',
            'availableAmount': '1234567.89012345',
            'unit':            'ETH',
          }),
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('overview with 6 assets + live fetch fits at 400x900',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_show_vault_card',
        'data': {
          'schema':    'crypto_vault_overview_data_v1',
          'available': true,
          'assets': [
            for (final a in ['ETH', 'USDT_ERC20', 'USDC_ERC20',
                             'SOL', 'USDT_TRC20', 'XMR'])
              {
                'asset':         a,
                'label':         a,
                'network':       'x',
                'balanceStatus': a == 'XMR' ? 'scanner_gated'
                                            : 'pending_live_fetch',
                'receiveReady':  a != 'XMR',
                'sendEnabled':   a != 'XMR',
                'publicAddress': a == 'XMR' ? null : '0x$a',
              },
          ],
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({
            'balanceStatus':   'available',
            'availableAmount': '0',
            'unit':            'ETH',
          }),
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });



  group('No secrets visible in widget tree', () {

    testWidgets(
        'fetcher response containing forbidden keys does not leak',
        (tester) async {
      final c = _card({
        'cardType': 'crypto_vault_balance_card',
        'asset':    'ETH',
        'data': {
          'schema':         'crypto_balance_data_v1',
          'available':      true,
          'asset':          'ETH',
          'label':          'ETH',
          'balanceStatus':  'pending_live_fetch',
          'publicAddress':  '0xabcdef',
        },
      });
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: c,
          onFetchBalance: _fixedBalanceFetcher({

            'balanceStatus':   'available',
            'availableAmount': '0.5',
            'unit':            'ETH',

            'privateKey':      'leaked-private-key',
            'seed_phrase':     'correct horse battery staple',
            'signedTxHex':     '0xdeadbeef',
            'authToken':       'sk-abc',
          }),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('0.5 ETH'), findsOneWidget);

      expect(find.textContaining('leaked-private-key'), findsNothing);
      expect(find.textContaining('correct horse battery'), findsNothing);
      expect(find.textContaining('signedTxHex'), findsNothing);
      expect(find.textContaining('sk-abc'), findsNothing);
    });
  });
}
