
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/services/vault_chat_router.dart';
import 'package:vault_ai_frontend/ui/chat/chat_bubble.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';



ChatMessage _vaultCardMsg({
  required String intent,
  required Map<String, dynamic> card,
}) {
  return ChatMessage(
    'assistant',
    (card['message'] ?? '').toString(),
    kind: ChatMessage.kVaultChatCard,
    payload: <String, dynamic>{
      'intent': intent,
      'card':   card,
    },
  );
}

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






const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {


  group('ChatMessage.kVaultChatCard wiring', () {

    test('kVaultChatCard constant is defined', () {
      expect(ChatMessage.kVaultChatCard, 'vault_chat_card');
    });

    test('kVaultChatCard messages are cards', () {
      final msg = _vaultCardMsg(
        intent: 'vault_overview',
        card: {'cardType': 'vault_overview_card', 'message': 'ok'},
      );
      expect(msg.isCard, isTrue,
          reason: 'vault_chat_card must be treated as a structured '
                  'card so it renders through _CardBubble');
    });

    test('kVaultChatCard payload keeps intent + card', () {
      final msg = _vaultCardMsg(
        intent: 'vault_login_list',
        card: {'cardType': 'vault_login_card', 'view': 'list'},
      );
      expect(msg.payload!['intent'], 'vault_login_list');
      final card = msg.payload!['card'] as Map<String, dynamic>;
      expect(card['cardType'], 'vault_login_card');
      expect(card['view'], 'list');
    });
  });



  group('ChatBubble routes kVaultChatCard through VaultChatCardView', () {

    testWidgets('overview card renders overview widget',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_overview',
          card: {
            'cardType':          'vault_overview_card',
            'liveFetchRequired': true,
            'maskedByDefault':   true,
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(find.byKey(const Key('vault_chat_card_overview')),
            findsOneWidget);
      });

    testWidgets('login list card renders login widget',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_login_list',
          card: {
            'cardType':        'vault_login_card',
            'view':            'list',
            'maskedByDefault': true,
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(find.byKey(const Key('vault_chat_card_login')),
            findsOneWidget);
      });

    testWidgets('id document card renders id widget',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_id_document_list',
          card: {
            'cardType':        'vault_id_document_card',
            'view':            'list',
            'maskedByDefault': true,
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(find.byKey(const Key('vault_chat_card_id_document')),
            findsOneWidget);
      });

    testWidgets('storage card renders storage widget',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_storage_usage',
          card: {
            'cardType':          'vault_storage_usage_card',
            'liveFetchRequired': true,
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(find.byKey(const Key('vault_chat_card_storage_usage')),
            findsOneWidget);
      });

    testWidgets('billing card renders billing widget',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_billing_status',
          card: {
            'cardType':          'vault_billing_status_card',
            'liveFetchRequired': true,
            'view':              'status',
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(
            find.byKey(const Key('vault_chat_card_billing_status')),
            findsOneWidget);
      });

    testWidgets('refusal card renders refusal widget',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_refusal_secret_material',
          card: {
            'cardType':      'vault_refusal_card',
            'refusalReason': 'secret_material_request',
            'message':       'VaultAI never surfaces your seed.',
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(find.byKey(const Key('vault_chat_card_refusal')),
            findsOneWidget);
      });

    testWidgets('confirmation-required card renders confirmation '
                'widget with safety pills',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_login_reveal',
          card: {
            'cardType': 'vault_confirmation_required_card',
            'action':   'reveal_login_password',
            'message':  'Revealing a password requires trusted '
                        'device, PIN unlock, and explicit '
                        'confirmation.',
            'requiresPinUnlock':            true,
            'requiresTrustedDevice':        true,
            'requiresExplicitConfirmation': true,
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(
            find.byKey(
              const Key('vault_chat_card_confirmation_required'),
            ),
            findsOneWidget);
      });

    testWidgets('empty payload renders no card (SizedBox.shrink)',
      (tester) async {

        final msg = ChatMessage(
          'assistant', '',
          kind: ChatMessage.kVaultChatCard,
          payload: null,
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();


        expect(find.byKey(const Key('vault_chat_card_refusal')),
            findsNothing);
      });
  });



  group('Crypto delegation through kVaultChatCard', () {

    testWidgets('delegated crypto card renders CryptoVaultChatCardView',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_crypto_delegated',
          card: {
            'cardType':    'vault_crypto_delegated_card',
            'innerIntent': 'show_wallet',
            'innerCard': {
              'schema':   'crypto_vault_chat_control_v1',
              'cardType': 'crypto_show_wallet_card',
              'message':  'Opening your Crypto Vault.',
              'openTarget': 'crypto_vault_home',
            },
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();


        expect(find.text('Opening your Crypto Vault.'),
            findsOneWidget);
      });
  });



  group('Sensitive-data invariants at the ChatBubble layer', () {

    testWidgets('login card never renders a password string',
      (tester) async {

        final msg = _vaultCardMsg(
          intent: 'vault_login_list',
          card: {
            'cardType':        'vault_login_card',
            'view':            'list',
            'maskedByDefault': true,


            'password': 'hunter2',
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();

        expect(find.text('hunter2'), findsNothing);
      });

    testWidgets('id document card never renders a raw id number',
      (tester) async {
        final msg = _vaultCardMsg(
          intent: 'vault_id_document_list',
          card: {
            'cardType':        'vault_id_document_card',
            'view':            'list',
            'maskedByDefault': true,
            'idNumber': '123-45-6789',
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(find.text('123-45-6789'), findsNothing);
      });

    testWidgets(
      'crypto delegated card never renders a fake balance number',
      (tester) async {

        final msg = _vaultCardMsg(
          intent: 'vault_crypto_delegated',
          card: {
            'cardType':    'vault_crypto_delegated_card',
            'innerIntent': 'show_balance',
            'innerCard': {
              'schema':   'crypto_vault_chat_control_v1',
              'cardType': 'crypto_balance_card',
              'asset':    'ETH',
              'network':  'ethereum_sepolia',
              'liveFetchRequired': true,
              'balance':  '999.9999',
              'balanceAmount': 999.9999,
            },
          },
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();


        expect(
          find.byWidgetPredicate((w) =>
              w is Text && (w.data ?? '').contains('999.9999')),
          findsNothing,
        );
      });
  });



  group('Full ChatMessageList round-trip', () {

    testWidgets('assistant vault_chat_card message renders through '
                'the list, existing text messages continue to render',
      (tester) async {
        final msgs = <ChatMessage>[
          ChatMessage('user', 'Show my logins'),
          _vaultCardMsg(
            intent: 'vault_login_list',
            card: {
              'cardType':        'vault_login_card',
              'view':            'list',
              'maskedByDefault': true,
            },
          ),
          ChatMessage('user', 'Tell me a joke'),
          ChatMessage('assistant', 'Why did the vault cross the road?'),
        ];

        await tester.pumpWidget(MaterialApp(
      localizationsDelegates: _testL10nDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: ChatMessageList(
              messages: msgs,
              thinking: false,
              streaming: false,
              isMobile: false,
            ),
          ),
        ));
        await tester.pump();


        expect(find.byKey(const Key('vault_chat_card_login')),
            findsOneWidget);


        expect(find.text('Tell me a joke'), findsOneWidget);
        expect(find.text('Why did the vault cross the road?'),
            findsOneWidget);
      });
  });



  group('Mobile overflow safety at 400x900 (small phones)', () {


    Future<void> _pumpNoOverflow(
      WidgetTester tester,
      String cardType,
      Map<String, dynamic> extra,
    ) async {
      final msg = _vaultCardMsg(
        intent: cardType.replaceFirst('_card', ''),
        card: {'cardType': cardType, ...extra},
      );
      await tester.pumpWidget(_wrap(
        ChatBubble(msg: msg, isMobile: true),
        size: const Size(400, 900),
      ));
      await tester.pump();

      expect(tester.takeException(), isNull,
          reason: 'no overflow for $cardType at 400x900');
    }

    testWidgets('login card fits at 400x900',
      (tester) async {
        await _pumpNoOverflow(tester, 'vault_login_card', {
          'view':            'list',
          'maskedByDefault': true,
        });
      });

    testWidgets('id document card fits at 400x900',
      (tester) async {
        await _pumpNoOverflow(tester, 'vault_id_document_card', {
          'view':            'list',
          'maskedByDefault': true,
        });
      });

    testWidgets('confirmation card fits at 400x900',
      (tester) async {
        await _pumpNoOverflow(
          tester, 'vault_confirmation_required_card', {
          'action': 'reveal_login_password',
          'message': 'Revealing a password requires trusted device, '
                     'PIN unlock, and explicit confirmation.',
          'requiresPinUnlock':            true,
          'requiresTrustedDevice':        true,
          'requiresExplicitConfirmation': true,
        });
      });

    testWidgets('refusal card fits at 400x900',
      (tester) async {
        await _pumpNoOverflow(tester, 'vault_refusal_card', {
          'refusalReason': 'secret_material_request',
          'message': 'VaultAI never surfaces your seed, mnemonic, '
                     'private keys, encrypted wallet secret, auth '
                     'token, or API key through chat. Use the '
                     'gated Security page instead.',
        });
      });
  });



  group('Existing chat card kinds continue to render', () {


    testWidgets('text-kind message still renders as text bubble',
      (tester) async {
        final msg = ChatMessage(
          'assistant', 'Hello, this is plain text.',
        );
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(find.text('Hello, this is plain text.'),
            findsOneWidget);
      });

    testWidgets('user text message still renders',
      (tester) async {
        final msg = ChatMessage('user', 'What is my USDT balance?');
        await tester.pumpWidget(_wrap(
          ChatBubble(msg: msg, isMobile: false),
        ));
        await tester.pump();
        expect(find.text('What is my USDT balance?'),
            findsOneWidget);
      });
  });



  group('Regression: kAllowedVcrIntents/cards untouched', () {


    test('intents still 32, cards still 16', () {


      expect(kAllowedVcrIntents, hasLength(32));
      expect(kAllowedVcrCards,   hasLength(16));
    });
  });
}
