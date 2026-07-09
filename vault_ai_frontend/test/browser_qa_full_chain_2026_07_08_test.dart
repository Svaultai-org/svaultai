


import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/crypto_chat_live_cache.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];




ChatMessage _vaultCardMsg({
  required String intent,
  required Map<String, dynamic> card,
}) => ChatMessage(
      'assistant', (card['message'] ?? '').toString(),
      kind: ChatMessage.kVaultChatCard,
      payload: <String, dynamic>{
        'intent': intent, 'card': card,
      },
    );


ChatMessage _cryptoDelegatedMsg({
  required String innerIntent,
  required Map<String, dynamic> innerCard,
}) => _vaultCardMsg(
      intent: 'vault_crypto_delegated',
      card: {
        'cardType':    'vault_crypto_delegated_card',
        'innerIntent': innerIntent,
        'innerCard':   innerCard,
      },
    );


Widget _wrap(Widget child, {Size size = const Size(1200, 2400)}) {
  return MaterialApp(
    localizationsDelegates: _testL10nDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      body: SizedBox(
        width: size.width,
        height: size.height,
        child: child,
      ),
    ),
  );
}


void main() {


  group('Cache is actually reachable through ChatMessageList chain', () {

    testWidgets(
        'balance card inside ChatMessageList uses the injected cache',
        (tester) async {
      final cache = CryptoChatLiveCache();
      var calls = 0;
      final fetcher = ({
        required String asset, required String address,
      }) async {
        calls++;
        return {
          'balanceStatus':   'available',
          'availableAmount': '0',
          'unit':            'ETH',
        };
      };

      final msg = _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_balance',
        innerCard: {
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
        },
      );


      await tester.pumpWidget(_wrap(ChatMessageList(
        messages:  [msg],
        thinking:  false,
        streaming: false,
        isMobile:  false,
        onFetchCryptoBalance: fetcher,
        cryptoCache:          cache,
      )));
      await tester.pumpAndSettle();
      expect(calls, 1);
      expect(find.text('0 ETH'), findsOneWidget);


      await tester.pumpWidget(_wrap(ChatMessageList(
        messages:  [msg],
        thinking:  false,
        streaming: false,
        isMobile:  false,
        onFetchCryptoBalance: fetcher,
        cryptoCache:          cache,
      )));
      await tester.pumpAndSettle();
      expect(calls, 1);
    });

    testWidgets(
        'two balance messages in same list dedupe through the chain',
        (tester) async {
      final cache = CryptoChatLiveCache();
      var calls = 0;
      final fetcher = ({
        required String asset, required String address,
      }) async {
        calls++;
        await Future<void>.delayed(const Duration(milliseconds: 5));
        return {
          'balanceStatus':   'available',
          'availableAmount': '1.25',
          'unit':            'ETH',
        };
      };
      final msg = _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_balance',
        innerCard: {
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
        },
      );
      await tester.pumpWidget(_wrap(ChatMessageList(
        messages:  [msg, msg],
        thinking:  false,
        streaming: false,
        isMobile:  false,
        onFetchCryptoBalance: fetcher,
        cryptoCache:          cache,
      )));
      await tester.pumpAndSettle();


      expect(calls, 1);
      expect(find.text('1.25 ETH'), findsNWidgets(2));
    });
  });



  group('Prime-from-cache avoids the loading flash on remount', () {

    testWidgets(
        'remounted balance card renders cached value in first frame',
        (tester) async {
      final cache = CryptoChatLiveCache();


      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0xabc',
        run: () async => {
          'balanceStatus':   'available',
          'availableAmount': '0',
          'unit':            'ETH',
        },
      );

      final msg = _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_balance',
        innerCard: {
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
        },
      );

      await tester.pumpWidget(_wrap(ChatMessageList(
        messages:  [msg],
        thinking:  false,
        streaming: false,
        isMobile:  false,
        onFetchCryptoBalance: ({
          required String asset, required String address,
        }) async => {

          'balanceStatus':   'available',
          'availableAmount': '999',
          'unit':            'ETH',
        },
        cryptoCache: cache,
      )));


      await tester.pump();

      expect(find.text('0 ETH'), findsOneWidget);
      expect(find.text('Loading live balance…'), findsNothing);
    });

    testWidgets(
        'remounted overview primes each row from cache',
        (tester) async {
      final cache = CryptoChatLiveCache();
      await cache.fetch(
        type: 'balance', asset: 'ETH', address: '0xETH',
        run: () async => {
          'balanceStatus':   'available',
          'availableAmount': '0',
          'unit':            'ETH',
        },
      );
      await cache.fetch(
        type: 'balance', asset: 'SOL', address: 'sol1',
        run: () async => {
          'balanceStatus':   'available',
          'availableAmount': '2',
          'unit':            'SOL',
        },
      );
      final msg = _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_show_vault',
        innerCard: {
          'cardType': 'crypto_vault_show_vault_card',
          'data': {
            'schema':    'crypto_vault_overview_data_v1',
            'available': true,
            'assets': [
              {
                'asset': 'ETH', 'label': 'ETH', 'network': 'ethereum',
                'balanceStatus': 'pending_live_fetch',
                'receiveReady':  true, 'sendEnabled':  true,
                'publicAddress': '0xETH',
              },
              {
                'asset': 'SOL', 'label': 'SOL', 'network': 'solana',
                'balanceStatus': 'pending_live_fetch',
                'receiveReady':  true, 'sendEnabled':  true,
                'publicAddress': 'sol1',
              },
            ],
          },
        },
      );
      await tester.pumpWidget(_wrap(ChatMessageList(
        messages:  [msg],
        thinking:  false,
        streaming: false,
        isMobile:  false,
        onFetchCryptoBalance: ({
          required String asset, required String address,
        }) async => {'balanceStatus': 'unavailable'},
        cryptoCache: cache,
      )));

      await tester.pump();
      expect(find.textContaining('0 ETH'), findsAtLeastNWidgets(1));
      expect(find.textContaining('2 SOL'), findsAtLeastNWidgets(1));
    });
  });



  group('Full acceptance walkthrough end-to-end', () {


    Widget _forMessage(ChatMessage msg, CryptoChatLiveCache cache) {
      return _wrap(ChatMessageList(
        messages:  [msg],
        thinking:  false,
        streaming: false,
        isMobile:  false,
        onFetchCryptoBalance: ({
          required String asset, required String address,
        }) async => {
          'balanceStatus':   'available',
          'availableAmount': '0',
          'unit':            asset.replaceAll('_ERC20', '')
                                  .replaceAll('_TRC20', ''),
        },
        onFetchCryptoActivity: ({
          required String asset,
          required String address,
          int limit = 10,
        }) async => {'transactions': const <dynamic>[]},
        cryptoCache: cache,
      ), size: const Size(400, 900));
    }


    Future<void> _pumpNoOverflow(
      WidgetTester tester, ChatMessage msg,
    ) async {
      final cache = CryptoChatLiveCache();
      await tester.pumpWidget(_forMessage(msg, cache));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull,
          reason: 'overflow or exception during message render');
    }

    testWidgets('vault overview', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_overview',
        card: {
          'cardType': 'vault_overview_card',
          'data': {
            'schema':    'vault_overview_data_v1',
            'available': true,
            'counts': {
              'files': 12, 'documents': 3, 'logins': 7,
              'secure_items': 4, 'id_documents': 2,
              'generated_logins': 1,
            },
            'storage': {
              'used_bytes': 1048576, 'quota_bytes': 10485760,
              'percent_used': 10.0,
            },
          },
        },
      ));
    });

    testWidgets('logins list', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_login_list',
        card: {
          'cardType': 'vault_login_card',
          'view':     'list',
          'data': {
            'schema':    'vault_login_data_v1',
            'available': true,
            'logins': [
              {
                'title': 'Gmail',
                'username_masked': 'u***@example.com',
                'domain': 'example.com',
              },
            ],
            'count': 1,
          },
        },
      ));
    });

    testWidgets('gmail login search', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_login_search',
        card: {
          'cardType': 'vault_login_card',
          'view':     'search',
          'query':    'Gmail',
          'data': {
            'schema':    'vault_login_data_v1',
            'available': true,
            'logins':    const <dynamic>[],
            'count':     0,
          },
        },
      ));
    });

    testWidgets('secure items', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_secure_item_list',
        card: {
          'cardType': 'vault_secure_item_card',
          'view':     'list',
          'data': {
            'schema':    'vault_secure_item_data_v1',
            'available': true,
            'items':     const <dynamic>[],
            'count':     0,
          },
        },
      ));
    });

    testWidgets('id documents', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_id_document_list',
        card: {
          'cardType': 'vault_id_document_card',
          'view':     'list',
          'data': {
            'schema':    'vault_id_document_data_v1',
            'available': true,
            'documents': const <dynamic>[],
            'count':     0,
          },
        },
      ));
    });

    testWidgets('storage', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_storage_usage',
        card: {
          'cardType': 'vault_storage_usage_card',
          'data': {
            'schema':      'vault_storage_data_v1',
            'available':   true,
            'used_bytes':  1048576,
            'quota_bytes': 10485760,
            'percent_used': 10.0,
            'file_count':   3,
            'document_count': 1,
          },
        },
      ));
    });

    testWidgets('billing', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_billing_status',
        card: {
          'cardType': 'vault_billing_status_card',
          'data': {
            'schema':    'vault_billing_data_v1',
            'available': true,
            'plan':      'free',
            'status':    'no_account',
            'included_bytes': 10485760,
            'has_active_subscription': false,
          },
        },
      ));
    });

    testWidgets('activity recent', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_activity_recent',
        card: {
          'cardType': 'vault_activity_card',
          'data': {
            'schema':    'vault_activity_data_v1',
            'available': true,
            'events':    const <dynamic>[],
            'count':     0,
          },
        },
      ));
    });

    testWidgets('search Chase', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_cross_vault_search',
        card: {
          'cardType': 'vault_cross_vault_search_card',
          'query':    'Chase',
          'data': {
            'schema':    'vault_search_data_v1',
            'available': true,
            'query':     'Chase',
            'groups':    const <dynamic>[],
            'group_count': 0,
          },
        },
      ));
    });

    testWidgets('crypto vault overview', (tester) async {
      await _pumpNoOverflow(tester, _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_show_vault',
        innerCard: {
          'cardType': 'crypto_vault_show_vault_card',
          'data': {
            'schema':    'crypto_vault_overview_data_v1',
            'available': true,
            'assets': [
              for (final a in ['ETH', 'USDT_ERC20', 'USDC_ERC20',
                               'SOL', 'USDT_TRC20', 'XMR'])
                {
                  'asset': a, 'label': a, 'network': 'x',
                  'balanceStatus': a == 'XMR' ? 'scanner_gated'
                                              : 'pending_live_fetch',
                  'receiveReady':  a != 'XMR',
                  'sendEnabled':   a != 'XMR',
                  'publicAddress': a == 'XMR' ? null : '0x$a',
                },
            ],
            'xmrScannerStatus': 'requires_desktop',
            'xmrReason':        'scanner_requires_desktop',
          },
        },
      ));
    });

    testWidgets('ETH balance', (tester) async {
      await _pumpNoOverflow(tester, _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_balance',
        innerCard: {
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
        },
      ));
    });

    testWidgets('USDT TRC20 balance', (tester) async {
      await _pumpNoOverflow(tester, _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_balance',
        innerCard: {
          'cardType': 'crypto_vault_balance_card',
          'asset':    'USDT_TRC20',
          'data': {
            'schema':         'crypto_balance_data_v1',
            'available':      true,
            'asset':          'USDT_TRC20',
            'label':          'USDT (TRC20)',
            'balanceStatus':  'pending_live_fetch',
            'publicAddress':  'TXABCDEF',
          },
        },
      ));
    });

    testWidgets('crypto activity', (tester) async {
      await _pumpNoOverflow(tester, _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_activity',
        innerCard: {
          'cardType': 'crypto_vault_activity_card',
          'asset':    'ETH',
          'data': {
            'schema':         'crypto_activity_data_v1',
            'available':      true,
            'asset':          'ETH',
            'activityStatus': 'pending_live_fetch',
            'entries':        const <dynamic>[],
          },
        },
      ));
    });

    testWidgets('Monero scanner status', (tester) async {
      await _pumpNoOverflow(tester, _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_scanner_status',
        innerCard: {
          'cardType': 'crypto_vault_scanner_status_card',
          'asset':    'XMR',
          'data': {
            'schema':          'crypto_scanner_status_data_v1',
            'available':       true,
            'asset':           'XMR',
            'scannerStatus':   'requires_desktop',
            'reason':          'scanner_requires_desktop',
            'canShowBalance':  false,
            'canShowActivity': false,
            'canSend':         false,
          },
        },
      ));
    });

    testWidgets('send draft 5 USDC to 0x0', (tester) async {
      await _pumpNoOverflow(tester, _cryptoDelegatedMsg(
        innerIntent: 'crypto_vault_send_draft',
        innerCard: {
          'cardType':  'crypto_vault_send_draft_card',
          'asset':     'USDC_ERC20',
          'amount':    '5',
          'recipient': '0x0000000000000000000000000000000000000000',
          'data': {
            'schema':          'crypto_send_draft_data_v1',
            'available':       true,
            'asset':           'USDC_ERC20',
            'network':         'ethereum',
            'canBroadcast':    false,
            'requiresTrustedDevice':        true,
            'requiresPinUnlock':            true,
            'requiresLocalSigning':         true,
            'requiresExplicitConfirmation': true,
          },
        },
      ));
    });

    testWidgets('refusal — seed phrase', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_refusal_secret_material',
        card: {
          'cardType': 'vault_refusal_card',
          'refusalReason': 'secret_material_request',
          'message': 'VaultAI never surfaces your seed.',
        },
      ));
    });

    testWidgets('refusal — bypass PIN', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_refusal_bypass_pin',
        card: {
          'cardType': 'vault_refusal_card',
          'refusalReason': 'bypass_pin_request',
          'message': 'VaultAI does not bypass PIN unlock.',
        },
      ));
    });

    testWidgets('refusal — auto-send', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_refusal_auto_send',
        card: {
          'cardType': 'vault_refusal_card',
          'refusalReason': 'auto_send_without_confirmation',
          'message': 'VaultAI cannot auto-send crypto.',
        },
      ));
    });

    testWidgets('refusal — swap', (tester) async {
      await _pumpNoOverflow(tester, _vaultCardMsg(
        intent: 'vault_refusal_exchange_action',
        card: {
          'cardType': 'vault_refusal_card',
          'refusalReason': 'exchange_action_request',
          'message': 'VaultAI is non-custodial. No swap/trade/etc.',
        },
      ));
    });
  });



  group('Non-vault chat still renders normal text bubbles', () {

    testWidgets('plain-text assistant message renders text bubble',
        (tester) async {
      final cache = CryptoChatLiveCache();
      await tester.pumpWidget(_wrap(ChatMessageList(
        messages: [
          ChatMessage('user', 'Tell me a joke'),
          ChatMessage('assistant',
              'Why did the vault cross the road?'),
        ],
        thinking:  false,
        streaming: false,
        isMobile:  false,
        cryptoCache: cache,
      )));
      await tester.pumpAndSettle();
      expect(find.text('Tell me a joke'), findsOneWidget);
      expect(find.text('Why did the vault cross the road?'),
          findsOneWidget);


      expect(cache.cacheSize, 0);
    });
  });
}
