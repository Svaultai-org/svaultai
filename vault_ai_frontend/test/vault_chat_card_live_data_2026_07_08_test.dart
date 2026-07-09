
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


VaultChatResponse _resp({
  required String intent,
  required Map<String, dynamic> card,
}) {
  return VaultChatResponse.fromJson(<String, dynamic>{
    'schema': 'vault_chat_router_v1',
    'intent': intent,
    'card':   card,
  });
}





const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {


  group('VaultChatCard.data + defensive parsing', () {

    test('data field is preserved by fromJson', () {
      final r = _resp(
        intent: 'vault_overview',
        card: {
          'cardType': 'vault_overview_card',
          'data': {
            'schema': 'vault_overview_data_v1',
            'available': true,
            'counts': {'files': 5, 'logins': 3},
          },
        },
      );
      expect(r.card.data, isNotNull);
      expect(r.card.data!['available'], isTrue);
      expect(r.card.data!['counts']['files'], 5);
    });

    test('forbidden top-level keys are stripped from data', () {
      final r = _resp(
        intent: 'vault_login_list',
        card: {
          'cardType': 'vault_login_card',
          'data': {
            'schema': 'vault_login_data_v1',
            'password': 'hunter2',
            'private_key': '0xdeadbeef',
            'seed_phrase': 'correct horse battery staple',
            'title': 'safe',
          },
        },
      );
      final d = r.card.data;
      expect(d, isNotNull);
      expect(d!['title'], 'safe');
      expect(d.containsKey('password'), isFalse);
      expect(d.containsKey('private_key'), isFalse);
      expect(d.containsKey('seed_phrase'), isFalse);
    });

    test('forbidden nested keys are stripped from data', () {
      final r = _resp(
        intent: 'vault_login_list',
        card: {
          'cardType': 'vault_login_card',
          'data': {
            'schema': 'vault_login_data_v1',
            'logins': [
              {
                'title':           'gmail',
                'username_masked': 'u***@example.com',

                'password':        'hunter2',
                'raw_id_number':   'AB1234567',
              },
            ],
          },
        },
      );
      final logins = (r.card.data!['logins'] as List);
      expect(logins.length, 1);
      final l = (logins.first as Map).cast<String, dynamic>();
      expect(l['title'], 'gmail');
      expect(l.containsKey('password'), isFalse);
      expect(l.containsKey('raw_id_number'), isFalse);
    });

    test('unavailable state is exposed', () {
      final r = _resp(
        intent: 'vault_overview',
        card: {
          'cardType': 'vault_overview_card',
          'data': {
            'schema': 'vault_overview_data_v1',
            'available': false,
            'unavailable_reason': 'internal_error',
          },
        },
      );
      expect(r.card.isAvailable, isFalse);
      expect(r.card.unavailableReason, 'internal_error');
    });
  });



  group('Populated vault overview renders counts + storage', () {

    testWidgets('overview shows count pills and storage bar',
        (tester) async {
      final r = _resp(
        intent: 'vault_overview',
        card: {
          'cardType': 'vault_overview_card',
          'data': {
            'schema':    'vault_overview_data_v1',
            'available': true,
            'counts': {
              'files':          12,
              'documents':      3,
              'logins':         7,
              'secure_items':   4,
              'id_documents':   2,
              'generated_logins': 1,
            },
            'storage': {
              'used_bytes':   1048576,
              'quota_bytes':  10485760,
              'percent_used': 10.0,
            },
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.byKey(const Key(kVcrCardKeyOverview)), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
      expect(find.text('Files'), findsOneWidget);
      expect(find.text('Logins'), findsOneWidget);
      expect(find.byKey(
          const Key('vault_chat_overview_storage_bar')),
          findsOneWidget);
    });

    testWidgets('unavailable overview shows summary copy only',
        (tester) async {
      final r = _resp(
        intent: 'vault_overview',
        card: {
          'cardType': 'vault_overview_card',
          'data': {
            'schema':    'vault_overview_data_v1',
            'available': false,
            'unavailable_reason': 'internal_error',
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();

      expect(find.byKey(
          const Key('vault_chat_overview_storage_bar')),
          findsNothing);
    });
  });



  group('Populated login card renders masked rows', () {

    testWidgets('login card shows masked usernames, no password',
        (tester) async {
      final r = _resp(
        intent: 'vault_login_list',
        card: {
          'cardType': 'vault_login_card',
          'view':     'list',
          'data': {
            'schema':    'vault_login_data_v1',
            'available': true,
            'logins': [
              {
                'title':           'Gmail',
                'username_masked': 'a***@example.com',
                'domain':          'example.com',
                'generated':       false,
              },
              {
                'title':           'Netflix',
                'username_masked': 'user@n***.com',
                'domain':          'netflix.com',
                'generated':       true,
              },
            ],
            'count': 2,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.text('Gmail'), findsOneWidget);
      expect(find.text('Netflix'), findsOneWidget);


      expect(find.text('hunter2'), findsNothing);
      expect(find.textContaining('a***@example.com'),
          findsOneWidget);


      expect(find.text('•••••••••'), findsAtLeastNWidgets(1));
    });

    testWidgets('login card empty state',
        (tester) async {
      final r = _resp(
        intent: 'vault_login_list',
        card: {
          'cardType': 'vault_login_card',
          'view':     'list',
          'data': {
            'schema':    'vault_login_data_v1',
            'available': true,
            'logins': [],
            'count': 0,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.textContaining('No logins saved yet'),
          findsOneWidget);
    });

    testWidgets(
        'login card injects password field via data — still not shown',
        (tester) async {

      final r = _resp(
        intent: 'vault_login_list',
        card: {
          'cardType': 'vault_login_card',
          'view':     'list',
          'data': {
            'schema':    'vault_login_data_v1',
            'available': true,
            'logins': [
              {
                'title':           'Chase',
                'username_masked': 'c***',


                'password':        'hunter2',
                'raw_password':    'hunter2',
              },
            ],
            'count': 1,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.text('hunter2'), findsNothing);
    });
  });



  group('Populated ID document card masks IDs', () {

    testWidgets('id card shows masked numbers, never raw',
        (tester) async {
      final r = _resp(
        intent: 'vault_id_document_list',
        card: {
          'cardType': 'vault_id_document_card',
          'view':     'list',
          'data': {
            'schema':    'vault_id_document_data_v1',
            'available': true,
            'documents': [
              {
                'type':             'passport',
                'issuing_country':  'US',
                'expires_at':       '2030-01-01',
                'id_number_masked': '•••4567',
              },
            ],
            'count': 1,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.text('PASSPORT'), findsOneWidget);
      expect(find.textContaining('•••4567'),
          findsAtLeastNWidgets(1));


      expect(find.textContaining('AB1234567'), findsNothing);
    });

    testWidgets('id card strips raw id_number field via data',
        (tester) async {
      final r = _resp(
        intent: 'vault_id_document_list',
        card: {
          'cardType': 'vault_id_document_card',
          'view':     'list',
          'data': {
            'schema':    'vault_id_document_data_v1',
            'available': true,
            'documents': [
              {
                'type':             'passport',
                'id_number_masked': '•••4567',
                'id_number':        'AB1234567',
                'raw_id_number':    'AB1234567',
              },
            ],
            'count': 1,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.textContaining('AB1234567'), findsNothing);
    });
  });



  group('Populated storage / billing / activity / secure item', () {

    testWidgets('storage card shows usage / quota / percent',
        (tester) async {
      final r = _resp(
        intent: 'vault_storage_usage',
        card: {
          'cardType': 'vault_storage_usage_card',
          'data': {
            'schema':    'vault_storage_data_v1',
            'available': true,
            'used_bytes':    2097152,
            'quota_bytes':  10485760,
            'percent_used':  20.0,
            'file_count':    8,
            'document_count': 2,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();

      expect(find.textContaining('20%'), findsAtLeastNWidgets(1));
      expect(find.text('Files'), findsOneWidget);
    });

    testWidgets('billing card shows plan / status', (tester) async {
      final r = _resp(
        intent: 'vault_billing_status',
        card: {
          'cardType': 'vault_billing_status_card',
          'data': {
            'schema':    'vault_billing_data_v1',
            'available': true,
            'plan':      'free',
            'status':    'no_account',
            'block_count':    0,
            'purchased_bytes': 0,
            'included_bytes':  10485760,
            'has_active_subscription': false,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();

      expect(find.byKey(
          const Key('vault_chat_billing_plan_pill')),
          findsOneWidget);
      expect(find.textContaining('Plan: free'),
          findsOneWidget);
    });

    testWidgets('activity card shows events with dates',
        (tester) async {
      final r = _resp(
        intent: 'vault_activity_recent',
        card: {
          'cardType': 'vault_activity_card',
          'data': {
            'schema':    'vault_activity_data_v1',
            'available': true,
            'events': [
              {
                'action':    'file_uploaded',
                'category':  'file',
                'title':     'passport.pdf',
                'timestamp': '2026-07-08T12:00:00',
              },
              {
                'action':    'item_saved',
                'category':  'login',
                'title':     'Gmail',
                'timestamp': '2026-07-07T09:30:00',
              },
            ],
            'count': 2,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();

      expect(find.textContaining('file uploaded'),
          findsAtLeastNWidgets(1));
      expect(find.textContaining('passport.pdf'),
          findsAtLeastNWidgets(1));
      expect(find.text('2026-07-08'), findsOneWidget);
    });

    testWidgets('secure item card shows title + snippet, masks values',
        (tester) async {
      final r = _resp(
        intent: 'vault_secure_item_list',
        card: {
          'cardType': 'vault_secure_item_card',
          'data': {
            'schema':    'vault_secure_item_data_v1',
            'available': true,
            'items': [
              {
                'id':      'i1',
                'title':   'Bike lock combo',
                'type':    'note',
                'snippet': 'Bike shed combination note',
              },
            ],
            'count': 1,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.text('Bike lock combo'), findsOneWidget);
      expect(find.textContaining('Bike shed combination note'),
          findsOneWidget);


      expect(find.text('Masked by default'), findsOneWidget);
    });
  });



  group('Cross-vault search — grouped results', () {

    testWidgets('search card groups results by category',
        (tester) async {
      final r = _resp(
        intent: 'vault_cross_vault_search',
        card: {
          'cardType': 'vault_cross_vault_search_card',
          'query':    'Chase',
          'data': {
            'schema':    'vault_search_data_v1',
            'available': true,
            'query':     'Chase',
            'groups': [
              {
                'category': 'logins',
                'count':    1,
                'items': [
                  {
                    'title':           'Chase',
                    'username_masked': 'c***@example.com',
                  },
                ],
              },
              {
                'category': 'files',
                'count':    1,
                'items': [
                  {'file_name': 'chase-statement.pdf'},
                ],
              },
            ],
            'group_count': 2,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.textContaining('Vault search: "Chase"'),
          findsOneWidget);
      expect(find.text('logins (1)'), findsOneWidget);
      expect(find.text('files (1)'), findsOneWidget);

      expect(find.textContaining('chase-statement.pdf'),
          findsAtLeastNWidgets(1));
    });

    testWidgets('empty search results still show query',
        (tester) async {
      final r = _resp(
        intent: 'vault_cross_vault_search',
        card: {
          'cardType': 'vault_cross_vault_search_card',
          'query':    'Chase',
          'data': {
            'schema':    'vault_search_data_v1',
            'available': true,
            'query':     'Chase',
            'groups':    [],
            'group_count': 0,
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();
      expect(find.textContaining('No results for "Chase"'),
          findsOneWidget);
    });
  });



  group('Mobile overflow safety with populated data', () {


    Future<void> _pumpPopulatedNoOverflow(
      WidgetTester tester, String intent, String cardType,
      Map<String, dynamic> data,
    ) async {
      final r = _resp(
        intent: intent,
        card: {'cardType': cardType, 'data': data},
      );
      await tester.pumpWidget(_wrap(
        VaultChatCardView(response: r),
        size: const Size(400, 900),
      ));
      await tester.pump();
      expect(tester.takeException(), isNull,
          reason: 'populated $cardType overflows at 400x900');
    }

    testWidgets('populated overview fits at 400x900', (tester) async {
      await _pumpPopulatedNoOverflow(
        tester, 'vault_overview', 'vault_overview_card',
        {
          'schema':    'vault_overview_data_v1',
          'available': true,
          'counts': {
            'files': 42, 'documents': 15, 'logins': 30,
            'secure_items': 12, 'id_documents': 4,
            'generated_logins': 8,
          },
          'storage': {
            'used_bytes': 3000000000,
            'quota_bytes': 10000000000,
            'percent_used': 30.0,
          },
        },
      );
    });

    testWidgets('populated login card fits at 400x900', (tester) async {
      await _pumpPopulatedNoOverflow(
        tester, 'vault_login_list', 'vault_login_card',
        {
          'schema':    'vault_login_data_v1',
          'available': true,
          'logins': List.generate(5, (i) => {
            'title':           'ServiceWithAVeryLongNameThatMightWrap$i',
            'username_masked': 'longusername***$i@corp.example.com',
            'domain':          'sub$i.corp.example.com',
            'generated':       i % 2 == 0,
          }),
          'count': 5,
        },
      );
    });

    testWidgets('populated id card fits at 400x900', (tester) async {
      await _pumpPopulatedNoOverflow(
        tester, 'vault_id_document_list', 'vault_id_document_card',
        {
          'schema':    'vault_id_document_data_v1',
          'available': true,
          'documents': [
            {
              'type':             'passport',
              'issuing_country':  'United States of America',
              'issuing_state':    'California',
              'expires_at':       '2030-01-01',
              'id_number_masked': '•••4567',
            },
          ],
          'count': 1,
        },
      );
    });

    testWidgets('populated activity card fits at 400x900',
        (tester) async {
      await _pumpPopulatedNoOverflow(
        tester, 'vault_activity_recent', 'vault_activity_card',
        {
          'schema':    'vault_activity_data_v1',
          'available': true,
          'events': List.generate(8, (i) => {
            'action':    'file_uploaded',
            'category':  'file',
            'title':     'very_long_filename_that_might_wrap_$i.pdf',
            'timestamp': '2026-07-0${(i % 9) + 1}T12:00:00',
          }),
          'count': 8,
        },
      );
    });

    testWidgets('populated search card fits at 400x900',
        (tester) async {
      await _pumpPopulatedNoOverflow(
        tester, 'vault_cross_vault_search',
        'vault_cross_vault_search_card',
        {
          'schema':    'vault_search_data_v1',
          'available': true,
          'query':     'Chase',
          'groups': [
            {
              'category': 'logins',
              'count':    3,
              'items': [
                {
                  'title':           'Chase Bank',
                  'username_masked': 'ch***@example.com',
                },
              ],
            },
            {
              'category': 'files',
              'count':    2,
              'items': [
                {'file_name': 'chase-statement-2026-01-january.pdf'},
              ],
            },
          ],
        },
      );
    });
  });



  group('No-fake-crypto-balance regression', () {


    testWidgets('crypto delegated card carries no data field even '
                'when backend accidentally sends one',
        (tester) async {
      final r = _resp(
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
          },

          'data': {
            'schema':    'made_up',
            'available': true,
            'balance':   '999.9999',
          },
        },
      );
      await tester.pumpWidget(_wrap(VaultChatCardView(response: r)));
      await tester.pump();


      expect(find.text('999.9999'), findsNothing);
    });
  });
}
