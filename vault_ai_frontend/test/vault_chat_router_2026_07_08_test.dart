import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/services/vault_chat_router.dart';
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';

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

VaultChatResponse _parse({
  required String intent,
  required Map<String, dynamic> card,
}) {
  return VaultChatResponse.fromJson({
    'schema': 'vault_chat_router_v1',
    'intent': intent,
    'card': card,
  });
}

const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

void main() {
  group('Closed-set enums', () {
    test('intent set is exactly 33 entries', () {
      expect(kAllowedVcrIntents, hasLength(33));
    });

    test('card set is exactly 17 entries', () {
      expect(kAllowedVcrCards, hasLength(17));
    });

    test('every intent name is prefixed with "vault_"', () {
      for (final i in kAllowedVcrIntents) {
        expect(i.startsWith('vault_'), isTrue,
            reason: 'intent "$i" is not vault-namespaced');
      }
    });

    test('every card name ends with "_card"', () {
      for (final c in kAllowedVcrCards) {
        expect(c.endsWith('_card'), isTrue,
            reason: 'card "$c" is not _card-suffixed');
      }
    });
  });

  group('Defensive parsing', () {
    test('unknown intent → unrecognized', () {
      final r = _parse(
        intent: 'unknown_new_intent',
        card: {'cardType': 'vault_overview_card'},
      );
      expect(r.intent, 'vault_unrecognized');
    });

    test('unknown cardType → unrecognized_card', () {
      final r = _parse(
        intent: 'vault_overview',
        card: {'cardType': 'made_up_card'},
      );
      expect(r.card.cardType, 'vault_unrecognized_card');
    });

    test('missing card → unrecognized_card', () {
      final r = VaultChatResponse.fromJson({
        'intent': 'vault_overview',
      });
      expect(r.card.cardType, 'vault_unrecognized_card');
    });

    test(
        'confirmation_required card forces requiresPinUnlock=true '
        'and requiresTrustedDevice=true even if backend accidentally '
        'sent them as false', () {
      final r = _parse(
        intent: 'vault_login_reveal',
        card: {
          'cardType': 'vault_confirmation_required_card',
          'action': 'reveal_login_password',
          'requiresPinUnlock': false,
          'requiresTrustedDevice': false,
          'requiresExplicitConfirmation': false,
        },
      );
      expect(r.card.requiresPinUnlock, isTrue);
      expect(r.card.requiresTrustedDevice, isTrue);
      expect(r.card.requiresExplicitConfirmation, isTrue);
    });

    test('maskedByDefault defaults to true when absent', () {
      final r = _parse(
        intent: 'vault_login_list',
        card: {'cardType': 'vault_login_card'},
      );
      expect(r.card.maskedByDefault, isTrue);
    });

    test(
        'generated login card can never save without confirmation, '
        'regardless of backend claim', () {
      final r = _parse(
        intent: 'vault_generated_login_create_draft',
        card: {
          'cardType': 'vault_generated_login_card',
          'canSaveWithoutConfirmation': true,
        },
      );
      expect(r.card.canSaveWithoutConfirmation, isFalse,
          reason: 'saving a generated login must ALWAYS require '
              'explicit confirmation locally');
    });

    test('memory proposal card preserves editable encrypted-chat data', () {
      final r = _parse(
        intent: 'vault_memory_save_proposal',
        card: {
          'cardType': 'vault_memory_proposal_card',
          'view': 'save_proposal',
          'data': {
            'schema': 'vault_memory_proposal_v1',
            'proposal_id': 'mem-1',
            'title': "Dad's birthday",
            'value': 'December 12, 1975',
            'memory_type': 'date',
            'category': 'family',
            'subject': 'father',
            'attribute': 'birthday',
            'event_date': '1975-12-12',
            'actions': ['save', 'edit', 'cancel'],
            'password': 'must-strip',
          },
        },
      );
      expect(r.intent, 'vault_memory_save_proposal');
      expect(r.card.cardType, 'vault_memory_proposal_card');
      expect(r.card.data?['value'], 'December 12, 1975');
      expect(r.card.data?['event_date'], '1975-12-12');
      expect(r.card.data?.containsKey('password'), isFalse);
    });
  });

  group('Crypto delegation', () {
    test('isCryptoDelegated is true for vault_crypto_delegated', () {
      final r = _parse(
        intent: 'vault_crypto_delegated',
        card: {
          'cardType': 'vault_crypto_delegated_card',
          'innerIntent': 'crypto_vault_balance',
          'innerCard': {
            'cardType': 'crypto_vault_balance_card',
            'asset': 'ETH',
            'liveFetchRequired': true,
          },
        },
      );
      expect(r.isCryptoDelegated, isTrue);
      final inner = r.delegatedCryptoCard;
      expect(inner, isNotNull);
      expect(inner!.cardType, 'crypto_vault_balance_card');
      expect(inner.asset, 'ETH');
    });

    test(
        'delegated send draft never rolls back to canBroadcast=true '
        'via the outer envelope', () {
      final r = _parse(
        intent: 'vault_crypto_delegated',
        card: {
          'cardType': 'vault_crypto_delegated_card',
          'innerIntent': 'crypto_vault_send_draft',
          'innerCard': {
            'cardType': 'crypto_vault_send_draft_card',
            'asset': 'USDC_ERC20',
            'amount': '2',
            'recipient': '0x0000000000000000000000000000000000000000',
            'canBroadcast': true,
          },
        },
      );
      final inner = r.delegatedCryptoCard!;

      expect(inner.canBroadcast, isFalse,
          reason: 'delegation MUST NOT re-enable broadcast');
    });
  });

  group('Card widget renders per closed-set card type', () {
    testWidgets('vault overview card renders and can open vault',
        (tester) async {
      var opened = false;
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_overview',
            card: {'cardType': 'vault_overview_card', 'maskedByDefault': true},
          ),
          onOpenVault: () => opened = true,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kVcrCardKeyOverview)), findsOneWidget);
      await tester.tap(find.byKey(const Key('vault_chat_overview_open_btn')));
      await tester.pumpAndSettle();
      expect(opened, isTrue);
    });

    testWidgets('memory proposal card renders and sends edited data',
        (tester) async {
      Map<String, dynamic>? saved;
      var cancelled = false;
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_memory_save_proposal',
            card: {
              'cardType': 'vault_memory_proposal_card',
              'view': 'save_proposal',
              'data': {
                'schema': 'vault_memory_proposal_v1',
                'proposal_id': 'mem-1',
                'title': "Dad's birthday",
                'value': 'December 12, 1975',
                'memory_type': 'date',
                'category': 'family',
                'subject': 'father',
                'attribute': 'birthday',
                'event_date': '1975-12-12',
                'actions': ['save', 'edit', 'cancel'],
              },
            },
          ),
          onMemoryProposalSave: (data) {
            saved = data;
          },
          onMemoryProposalCancel: () => cancelled = true,
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key(kVcrCardKeyMemoryProposal)), findsOneWidget);
      expect(find.byKey(const Key('vault_chat_card_memory_title_field')),
          findsOneWidget);
      expect(find.byKey(const Key('vault_chat_card_memory_value_field')),
          findsOneWidget);
      expect(find.text('December 12, 1975'), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('vault_chat_card_memory_value_field')),
        'December 13, 1975',
      );
      await tester.tap(find.byKey(const Key('vault_chat_card_memory_save')));
      await tester.pumpAndSettle();

      expect(saved, isNotNull);
      expect(saved!['title'], "Dad's birthday");
      expect(saved!['value'], 'December 13, 1975');
      expect(saved!['attribute'], 'birthday');
      expect(cancelled, isFalse);
    });

    testWidgets(
        'memory proposal shows progress then saved after backend success',
        (tester) async {
      final completer = Completer<void>();
      var saveCalls = 0;
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_memory_save_proposal',
            card: {
              'cardType': 'vault_memory_proposal_card',
              'view': 'save_proposal',
              'data': {
                'schema': 'vault_memory_proposal_v1',
                'proposal_id': 'mem-1',
                'title': 'Preferred name',
                'value': 'Kola',
                'memory_type': 'identity',
                'category': 'personal',
                'actions': ['save', 'edit', 'cancel'],
              },
            },
          ),
          onMemoryProposalSave: (_) {
            saveCalls += 1;
            return completer.future;
          },
        ),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('vault_chat_card_memory_save')));
      await tester.pump();
      expect(find.text('Saving...'), findsOneWidget);
      expect(saveCalls, 1);

      completer.complete();
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('vault_chat_card_memory_saved')),
          findsOneWidget);
      expect(find.text('Memory saved.'), findsOneWidget);
      expect(
        tester
            .widget<ElevatedButton>(
              find.byKey(const Key('vault_chat_card_memory_save')),
            )
            .onPressed,
        isNull,
      );
    });

    testWidgets('memory proposal failure re-enables retry without duplicating',
        (tester) async {
      var saveCalls = 0;
      final first = Completer<void>();
      final second = Completer<void>();
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_memory_save_proposal',
            card: {
              'cardType': 'vault_memory_proposal_card',
              'view': 'save_proposal',
              'data': {
                'schema': 'vault_memory_proposal_v1',
                'proposal_id': 'mem-1',
                'title': 'Preferred name',
                'value': 'Kola',
                'memory_type': 'identity',
                'category': 'personal',
                'actions': ['save', 'edit', 'cancel'],
              },
            },
          ),
          onMemoryProposalSave: (_) {
            saveCalls += 1;
            return saveCalls == 1 ? first.future : second.future;
          },
        ),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('vault_chat_card_memory_save')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('vault_chat_card_memory_save')));
      await tester.pump();
      expect(saveCalls, 1);

      first.completeError(StateError('backend failed'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('vault_chat_card_memory_error')),
          findsOneWidget);
      expect(
        tester
            .widget<ElevatedButton>(
              find.byKey(const Key('vault_chat_card_memory_save')),
            )
            .onPressed,
        isNotNull,
      );

      await tester.tap(find.byKey(const Key('vault_chat_card_memory_save')));
      await tester.pump();
      expect(saveCalls, 2);

      second.complete();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('vault_chat_card_memory_saved')),
          findsOneWidget);
    });

    testWidgets('memory proposal timeout re-enables safe retry',
        (tester) async {
      var saveCalls = 0;
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_memory_save_proposal',
            card: {
              'cardType': 'vault_memory_proposal_card',
              'view': 'save_proposal',
              'data': {
                'schema': 'vault_memory_proposal_v1',
                'proposal_id': 'mem-1',
                'title': 'Preferred name',
                'value': 'Kola',
                'memory_type': 'identity',
                'category': 'personal',
                'actions': ['save', 'edit', 'cancel'],
              },
            },
          ),
          onMemoryProposalSave: (_) {
            saveCalls += 1;
            return Completer<void>().future;
          },
        ),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('vault_chat_card_memory_save')));
      await tester.pump();
      expect(find.text('Saving...'), findsOneWidget);

      await tester
          .pump(kMemoryProposalSaveTimeout + const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(saveCalls, 1);
      expect(find.byKey(const Key('vault_chat_card_memory_error')),
          findsOneWidget);
      expect(
        tester
            .widget<ElevatedButton>(
              find.byKey(const Key('vault_chat_card_memory_save')),
            )
            .onPressed,
        isNotNull,
      );
    });

    testWidgets(
        'login list card renders masked-username rows '
        'and no misleading "Reveal requires unlock" pill', (tester) async {
      // Product decision (2026-07-11): the LIST view still masks
      // usernames on every row (no plaintext leaks into a generic
      // list). The old "Reveal requires unlock" pill was removed as
      // misleading — the user is already unlocked; the reveal is
      // available by asking for a specific login. Detail-view
      // rendering is covered by
      // vault_chat_login_detail_card_2026_07_11_test.dart.
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_login_list',
            card: {
              'cardType': 'vault_login_card',
              'view': 'list',
              'data': {
                'schema': 'vault_login_data_v1',
                'available': true,
                'view': 'list',
                'logins': [
                  {
                    'id': 'x',
                    'title': 'Netflix',
                    'service': 'Netflix',
                    'username_masked': 'a***@example.com',
                    'has_username': true,
                    'domain': 'netflix.com',
                  },
                ],
                'count': 1,
              },
            },
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kVcrCardKeyLogin)), findsOneWidget);

      expect(find.textContaining('a***@example.com'), findsOneWidget);

      expect(find.textContaining('Reveal requires unlock'), findsNothing);
    });

    testWidgets('id document card masks by default + shows unlock hint',
        (tester) async {
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_id_document_list',
            card: {'cardType': 'vault_id_document_card'},
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kVcrCardKeyIdDocument)), findsOneWidget);
      expect(find.text('•••• •••• last-4'), findsOneWidget);

      expect(find.textContaining('Reveal requires unlock'),
          findsAtLeastNWidgets(1));
    });

    testWidgets('confirmation-required card renders every enabled safety pill',
        (tester) async {
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_login_reveal',
            card: {
              'cardType': 'vault_confirmation_required_card',
              'action': 'reveal_login_password',
              'message': 'Revealing requires confirmation.',
              'requiresPinUnlock': true,
              'requiresTrustedDevice': true,
              'requiresExplicitConfirmation': true,
            },
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kVcrCardKeyConfirmationReq)), findsOneWidget);
      expect(find.text('Trusted device'), findsOneWidget);
      expect(find.text('PIN unlock'), findsOneWidget);
      expect(find.text('Explicit confirmation'), findsOneWidget);
    });

    testWidgets('refusal card renders the refusal message', (tester) async {
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_refusal_secret_material',
            card: {
              'cardType': 'vault_refusal_card',
              'refusalReason': 'secret_material_request',
              'message': kVcrRefusalCopySecretMaterial,
            },
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kVcrCardKeyRefusal)), findsOneWidget);
      expect(find.textContaining('Svaultai never surfaces'), findsOneWidget);
    });

    testWidgets(
        'generated login card renders Save + Cancel action row '
        '(2026-08-01 rewrite — replaces the old placeholder pill)',
        (tester) async {
      // 2026-08-01: the "Save requires confirmation" pill was a
      // placeholder from an unfinished stub. The rewritten
      // _GeneratedLoginCard renders real Save/Cancel buttons that
      // fire onGeneratedLoginSave / onGeneratedLoginCancel
      // callbacks. Backend now nests the credential values inside
      // `card.data` (matching VaultChatCard.fromJson at
      // services/vault_chat_router.dart:251).
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_generated_login_create_draft',
            card: {
              'cardType': 'vault_generated_login_card',
              'view': 'create_draft',
              'data': {
                'view': 'create_draft',
                'service': 'HBO Max',
                'service_name': 'HBO Max',
                'username': 'beraves123@example.com',
                'password': 'SamplePassword1!',
                'draft_id': 'draft-router-test-1',
                'explicit_fields': ['username'],
                'actions': ['save', 'cancel'],
              },
            },
          ),
        ),
      ));
      await tester.pumpAndSettle();
      // Card mount marker.
      expect(find.byKey(const Key(kVcrCardKeyGeneratedLogin)), findsOneWidget);
      // The old placeholder text MUST NOT render.
      expect(find.text('Save requires confirmation'), findsNothing);
      // The real action buttons render.
      expect(
        find.byKey(const Key(
          'vault_chat_card_generated_login_save',
        )),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key(
          'vault_chat_card_generated_login_cancel',
        )),
        findsOneWidget,
      );
      // Service name is the title.
      expect(find.text('HBO Max'), findsOneWidget);
    });

    testWidgets('generated login batch renders every requested draft',
        (tester) async {
      final saved = <String>[];
      final response = _parse(
        intent: 'vault_generated_login_create_draft',
        card: {
          'cardType': 'vault_generated_login_card',
          'view': 'create_draft_batch',
          'data': {
            'view': 'create_draft_batch',
            'schema': 'vault_generated_login_draft_batch_v1',
            'count': 3,
            'actions': ['save', 'cancel'],
            'drafts': [
              {
                'view': 'create_draft',
                'service': 'Facebook',
                'service_name': 'Facebook',
                'username': 'facebook-user',
                'password': 'Password1!',
                'draft_id': 'draft-facebook',
                'actions': ['save', 'cancel'],
              },
              {
                'view': 'create_draft',
                'service': 'Instagram',
                'service_name': 'Instagram',
                'username': 'instagram-user',
                'password': 'Password2!',
                'draft_id': 'draft-instagram',
                'actions': ['save', 'cancel'],
              },
              {
                'view': 'create_draft',
                'service': 'HBO max',
                'service_name': 'HBO max',
                'username': 'hbo-user',
                'password': 'Password3!',
                'draft_id': 'draft-hbo',
                'actions': ['save', 'cancel'],
              },
            ],
          },
        },
      );
      final drafts = response.card.data!['drafts'] as List;
      expect(drafts, hasLength(3));
      expect(drafts.first['password'], 'Password1!');

      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: response,
          onGeneratedLoginSave: (data) {
            saved.add('${data['draft_id']}:${data['service']}');
          },
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Facebook'), findsOneWidget);
      expect(find.text('Instagram'), findsOneWidget);
      expect(find.text('HBO max'), findsOneWidget);
      expect(
        find.byKey(const Key('vault_chat_card_generated_login_save_batch_0')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('vault_chat_card_generated_login_save_batch_1')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('vault_chat_card_generated_login_save_batch_2')),
        findsOneWidget,
      );

      await tester.tap(
        find.byKey(const Key('vault_chat_card_generated_login_save_batch_0')),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const Key('vault_chat_card_generated_login_save_batch_1')),
      );
      await tester.pumpAndSettle();

      expect(saved, [
        'draft-facebook:Facebook',
        'draft-instagram:Instagram',
      ]);
    });

    testWidgets('billing card renders with route-to-checkout wording',
        (tester) async {
      var opened = false;
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_billing_upgrade',
            card: {
              'cardType': 'vault_billing_status_card',
              'view': 'upgrade_prompt'
            },
          ),
          onOpenBillingPage: () => opened = true,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key(kVcrCardKeyBillingStatus)), findsOneWidget);
      expect(find.textContaining('gated checkout flow'), findsOneWidget);
      await tester.tap(find.byKey(const Key('vault_chat_billing_open_btn')));
      await tester.pumpAndSettle();
      expect(opened, isTrue);
    });

    testWidgets('cross-vault search card carries the query', (tester) async {
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_cross_vault_search',
            card: {
              'cardType': 'vault_cross_vault_search_card',
              'query': 'Chase',
            },
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(
          find.byKey(const Key(kVcrCardKeyCrossVaultSearch)), findsOneWidget);

      expect(find.textContaining('"Chase"'), findsAtLeastNWidgets(1));
    });

    testWidgets('crypto-delegated response routes to the crypto card',
        (tester) async {
      await tester.pumpWidget(_wrap(
        VaultChatCardView(
          response: _parse(
            intent: 'vault_crypto_delegated',
            card: {
              'cardType': 'vault_crypto_delegated_card',
              'innerIntent': 'crypto_vault_send_draft',
              'innerCard': {
                'cardType': 'crypto_vault_send_draft_card',
                'asset': 'USDC_ERC20',
                'amount': '2',
                'recipient': '0xabcdef0000000000000000000000000000000000',
                'canBroadcast': true,
              },
            },
          ),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.textContaining('Send 2 USDC_ERC20'), findsOneWidget);
      expect(find.text('Chat cannot broadcast'), findsOneWidget);
    });
  });

  group('Safety — no card exposes secret fields', () {
    test(
        'no card constructor accepts a password/secret field '
        'even if backend adds one', () {
      final r = _parse(
        intent: 'vault_login_search',
        card: {
          'cardType': 'vault_login_card',
          'password': 'hunter2',
          'clearPassword': 'hunter2',
          'idNumber': '123-45-6789',
        },
      );

      expect(r.card.toString(), isNot(contains('hunter2')));
      expect(r.card.toString(), isNot(contains('123-45-6789')));
    });

    test(
        'refusal + confirmation-required copies never contain '
        'exchange verbs', () {
      const banned = <String>[
        ' buy ',
        ' sell ',
        ' swap ',
        ' trade ',
        ' stake ',
        ' bridge ',
        ' convert ',
      ];
      final strings = <String>[
        kVcrRefusalCopySecretMaterial,
        kVcrRefusalCopyBypassPin,
        kVcrRefusalCopyExportAll,
        kVcrRefusalCopyMassReveal,
      ];
      for (final s in strings) {
        final padded = ' ${s.toLowerCase()} ';
        for (final w in banned) {
          expect(padded.contains(w), isFalse, reason: 'copy "$s" leaks "$w"');
        }
      }
    });
  });

  group('Mobile — no overflow at 400 px', () {
    testWidgets('every card type renders at 400x900 without exception',
        (tester) async {
      const cardsToRender = <String>[
        'vault_overview_card',
        'vault_file_result_card',
        'vault_document_result_card',
        'vault_secure_item_card',
        'vault_login_card',
        'vault_generated_login_card',
        'vault_id_document_card',
        'vault_billing_status_card',
        'vault_storage_usage_card',
        'vault_activity_card',
        'vault_cross_vault_search_card',
        'vault_confirmation_required_card',
        'vault_refusal_card',
        'vault_unrecognized_card',
      ];
      for (final t in cardsToRender) {
        await tester.pumpWidget(_wrap(
          VaultChatCardView(
            response: _parse(
              intent: 'vault_overview',
              card: {
                'cardType': t,
                'query': 'chase',
                'action': 'reveal_login_password',
                'message': 'placeholder',
              },
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
