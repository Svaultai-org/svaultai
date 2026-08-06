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


CryptoVaultChatResponse _parse(Map<String, dynamic> raw) =>
    CryptoVaultChatResponse.fromJson(raw);


Map<String, dynamic> _envelope({
  required String intent,
  required Map<String, dynamic> card,
}) => {
  'schema': 'crypto_vault_chat_control_v1',
  'intent': intent,
  'card':   card,
};


void main() {


  group('Closed-set intents + cards', () {

    test('intent set is exactly the 11 documented intents', () {
      expect(kAllowedCvcIntents, hasLength(11));
      expect(kAllowedCvcIntents, contains('crypto_vault_balance'));
      expect(kAllowedCvcIntents,
          contains('crypto_vault_refusal_secret_material'));
      expect(kAllowedCvcIntents,
          contains('crypto_vault_refusal_exchange_action'));
      expect(kAllowedCvcIntents, contains('crypto_vault_send_draft'));
      expect(kAllowedCvcIntents,
          contains('crypto_vault_clarify_usdt_network'));
    });

    test('card set is exactly the 10 documented cards', () {
      expect(kAllowedCvcCards, hasLength(10));
    });
  });


  group('CryptoVaultChatResponse.fromJson defensive parsing', () {

    test('unknown intent coerces to unrecognized', () {
      final r = _parse(_envelope(
        intent: 'random_new_intent_not_shipped',
        card: {'cardType': 'crypto_vault_balance_card'},
      ));
      expect(r.intent, 'crypto_vault_unrecognized');
    });

    test('unknown cardType coerces to unrecognized', () {
      final r = _parse(_envelope(
        intent: 'crypto_vault_balance',
        card: {'cardType': 'fake_card_type'},
      ));
      expect(r.card.cardType, 'crypto_vault_unrecognized_card');
    });

    test('missing card field falls back to unrecognized card', () {
      final r = CryptoVaultChatResponse.fromJson(<String, dynamic>{
        'intent': 'crypto_vault_show_vault',
      });
      expect(r.card.cardType, 'crypto_vault_unrecognized_card');
    });


    test('send-draft card ALWAYS has canBroadcast=false locally, '
        'even if backend accidentally set it true', () {
      final r = _parse(_envelope(
        intent: 'crypto_vault_send_draft',
        card: {
          'cardType':               'crypto_vault_send_draft_card',
          'asset':                  'ETH',
          'amount':                 '0.05',
          'recipient':              '0xdeadbeef',
          'canBroadcast':           true,
          'requiresPinUnlock':      false,
          'requiresTrustedDevice':  false,
          'requiresLocalSigning':   false,
        },
      ));
      expect(r.card.canBroadcast, isFalse,
          reason: 'the send-draft card must NEVER carry '
              'canBroadcast=true — chat cannot broadcast a send');
      expect(r.card.requiresPinUnlock, isTrue);
      expect(r.card.requiresTrustedDevice, isTrue);
      expect(r.card.requiresLocalSigning, isTrue);
      expect(r.card.requiresExplicitConfirmation, isTrue);
    });


    test('refusal card carries refusalReason and message', () {
      final r = _parse(_envelope(
        intent: 'crypto_vault_refusal_secret_material',
        card: {
          'cardType':      'crypto_vault_refusal_card',
          'refusalReason': 'secret_material_request',
          'message':       'SVaultAI never surfaces your seed.',
        },
      ));
      expect(r.isRefusal, isTrue);
      expect(r.card.refusalReason, 'secret_material_request');
      expect(r.card.message, contains('SVaultAI'));
    });


    test('clarify-usdt card carries the two-option list', () {
      final r = _parse(_envelope(
        intent: 'crypto_vault_clarify_usdt_network',
        card: {
          'cardType': 'crypto_vault_clarify_card',
          'message':  'Which USDT?',
          'options':  ['USDT_ERC20', 'USDT_TRC20'],
        },
      ));
      expect(r.isClarifyUsdt, isTrue);
      expect(r.card.options, equals(['USDT_ERC20', 'USDT_TRC20']));
    });
  });


  group('Card widget renders per closed-set card type', () {

    testWidgets('refusal card renders with the refusal key + message',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: CryptoVaultChatCard(
            cardType:      kCvcCardRefusal,
            refusalReason: kCvcRefusalReasonSecretMaterial,
            message:       kCvcRefusalCopySecretMaterial,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kCvcCardKeyRefusal)),
          findsOneWidget);
      expect(find.textContaining('SVaultAI never surfaces'),
          findsOneWidget);
    });

    testWidgets('clarify card renders both USDT options',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: CryptoVaultChatCard(
            cardType: kCvcCardClarify,
            message:  kCvcClarifyUsdtCopy,
            options:  const ['USDT_ERC20', 'USDT_TRC20'],
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kCvcCardKeyClarify)),
          findsOneWidget);
      expect(find.byKey(
          const Key('crypto_vault_chat_clarify_option_USDT_ERC20')),
          findsOneWidget);
      expect(find.byKey(
          const Key('crypto_vault_chat_clarify_option_USDT_TRC20')),
          findsOneWidget);
    });

    testWidgets(
        'send-draft card renders the summary + "Chat cannot '
        'broadcast" chip + optional Open-send-flow button',
        (tester) async {
      var openedSend = false;
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: const CryptoVaultChatCard(
            cardType:  kCvcCardSendDraft,
            asset:     'USDC_ERC20',
            amount:    '5',
            recipient: '0xabc',
          ),
          onOpenSendFlow: () => openedSend = true,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kCvcCardKeySendDraft)),
          findsOneWidget);
      expect(find.textContaining('Send 5 USDC_ERC20'), findsOneWidget);
      expect(
        find.byKey(const Key(
          'crypto_vault_chat_send_never_broadcasts',
        )),
        findsOneWidget,
      );
      expect(find.text('Chat cannot broadcast'), findsOneWidget);


      await tester.tap(find.byKey(const Key(
        'crypto_vault_chat_send_open_send_flow',
      )));
      await tester.pumpAndSettle();
      expect(openedSend, isTrue,
          reason: 'the send-draft card only OPENS the existing '
              'send flow — it never broadcasts');
    });

    testWidgets(
        'send-draft card never renders a Send/Broadcast button',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: const CryptoVaultChatCard(
            cardType: kCvcCardSendDraft,
            asset:    'ETH',
            amount:   '0.05',
            recipient: '0xdeadbeef',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      for (final banned in const [
        'Send now',
        'Broadcast',
        'Confirm and send',
        'Send from chat',
      ]) {
        expect(find.text(banned), findsNothing,
            reason: 'card must never expose a direct-send action: '
                '$banned');
      }
    });


    testWidgets('balance card renders asset name + no numeric amount',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: const CryptoVaultChatCard(
            cardType: kCvcCardBalance,
            asset:    'ETH',
            liveFetchRequired: true,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kCvcCardKeyBalance)),
          findsOneWidget);


      final numeric = RegExp(r'\d+(\.\d+)?\s*(ETH|USDT|USDC|SOL|XMR)');
      for (final el in find.byType(Text).evaluate()) {
        final t = (el.widget as Text).data ?? '';
        expect(numeric.hasMatch(t), isFalse,
            reason: 'balance card leaked a numeric amount: $t');
      }
    });


    testWidgets(
        'activity card renders "SVaultAI never invents activity."',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: const CryptoVaultChatCard(
            cardType: kCvcCardActivity,
            liveFetchRequired: true,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kCvcCardKeyActivity)),
          findsOneWidget);
      expect(find.textContaining('SVaultAI never invents activity'),
          findsOneWidget);
    });


    testWidgets(
        'scanner-status card offers Open-Monero action; renders '
        'the "wallet scanning" copy',
        (tester) async {
      String? opened;
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: const CryptoVaultChatCard(
            cardType: kCvcCardScannerStatus,
            asset:    'XMR',
            liveFetchRequired: true,
          ),
          onOpenAssetDetail: (a) => opened = a,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kCvcCardKeyScannerStatus)),
          findsOneWidget);


      expect(
        find.textContaining(RegExp(r'Scanner|scanning|Monero')),
        findsAtLeastNWidgets(1),
      );
      await tester.tap(find.byKey(
          const Key('crypto_vault_chat_scanner_open_xmr')));
      await tester.pumpAndSettle();
      expect(opened, 'XMR');
    });


    testWidgets('show-vault card renders + can open vault',
        (tester) async {
      var opened = false;
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: const CryptoVaultChatCard(cardType: kCvcCardShowVault),
          onOpenVault: () => opened = true,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kCvcCardKeyShowVault)),
          findsOneWidget);
      await tester.tap(find.byKey(
          const Key('crypto_vault_chat_show_vault_open_btn')));
      await tester.pumpAndSettle();
      expect(opened, isTrue);
    });


    testWidgets(
        'unrecognized card renders the fallback copy',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: const CryptoVaultChatCard(
            cardType: kCvcCardUnrecognized,
            message:  kCvcUnrecognizedCopy,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kCvcCardKeyUnrecognized)),
          findsOneWidget);
      expect(find.textContaining('Crypto Vault chat can answer'),
          findsOneWidget);
    });
  });


  group('Copy safety — no exchange verbs in any card copy', () {

    test('every user-visible copy constant is exchange-language free',
        () {
      const banned = <String>[
        ' buy ', ' sell ', ' swap ', ' trade ', ' stake ',
        ' bridge ', ' exchange ', ' convert ',
      ];
      for (final s in const <String>[
        kCvcRefusalCopySecretMaterial,

        kCvcClarifyUsdtCopy,
        kCvcUnrecognizedCopy,
      ]) {
        final padded = ' ${s.toLowerCase()} ';
        for (final w in banned) {
          expect(padded.contains(w), isFalse,
              reason: 'copy "$s" leaks "$w"');
        }
      }
    });


    test('exchange-refusal copy DOES name the disallowed verbs — '
        'that is the point of the refusal', () {
      final low = kCvcRefusalCopyExchangeAction.toLowerCase();
      for (final w in const [
        'buy', 'sell', 'swap', 'trade', 'stake', 'bridge', 'exchange',
      ]) {
        expect(low.contains(w), isTrue,
            reason: 'refusal copy should explicitly disavow "$w"');
      }
    });
  });


  group('No secrets in any user-visible card copy', () {

    test('no copy constant contains actual key material identifiers',
        () {
      const banned = <String>[
        'view_key_hex', 'spend_key_hex', 'privateSpendKey',
        'privateViewKey', 'encryptedWalletSecret',
        'seed_hex', 'mnemonic_words',
      ];
      for (final s in const <String>[
        kCvcRefusalCopySecretMaterial,
        kCvcRefusalCopyExchangeAction,
        kCvcClarifyUsdtCopy,
        kCvcUnrecognizedCopy,
      ]) {
        for (final w in banned) {
          expect(s.contains(w), isFalse,
              reason: 'copy leaked field name "$w"');
        }
      }
    });
  });


  group('Mobile — no overflow at 400 px', () {

    testWidgets(
        'send-draft card renders at 400x900 without overflow',
        (tester) async {
      await tester.pumpWidget(_wrap(
        CryptoVaultChatCardView(
          card: const CryptoVaultChatCard(
            cardType: kCvcCardSendDraft,
            asset:    'USDC_ERC20',
            amount:   '5',
            recipient: '0x1234567890abcdef1234567890abcdef12345678',
          ),
        ),
        size: const Size(400, 900),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('every card type renders at 400x900 without exception',
        (tester) async {
      for (final t in kAllowedCvcCards) {
        await tester.pumpWidget(_wrap(
          CryptoVaultChatCardView(
            card: CryptoVaultChatCard(
              cardType: t,
              asset:    'ETH',
              amount:   '1',
              options:  const ['USDT_ERC20', 'USDT_TRC20'],
              message:  'placeholder',
            ),
          ),
          size: const Size(400, 900),
        ));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull,
            reason: 'card $t threw at 400x900');
      }
    });
  });
}
