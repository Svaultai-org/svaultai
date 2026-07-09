

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/logins_page.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


String _read(String relativePath) {
  return File(
    Directory.current.path + '/' + relativePath,
  ).readAsStringSync();
}

String _stripDartComments(String src) {
  src = src.replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '');
  src = src.replaceAll(RegExp(r'//[^\n]*'), '');
  return src;
}

ChatMessage _envelope({
  required List<Map<String, dynamic>> items,
  bool reveal = false,
  String? displayMode,
  String? message,
}) {
  return ChatMessage(
    'assistant',
    message ?? '',
    kind: ChatMessage.kSecureItemResults,
    payload: <String, dynamic>{
      'items':   items,
      'count':   items.length,
      'reveal':  reveal,
      if (displayMode != null) 'display_mode': displayMode,
      if (message != null) 'message': message,
    },
  );
}

Map<String, dynamic> _row({
  required String itemId,
  required String type,
  required String title,
  Map<String, dynamic>? preview,
  String? categoryLabel,
}) {
  return <String, dynamic>{
    'item_id':        itemId,
    'type':           type,
    'title':          title,
    'category_label': categoryLabel ?? type,
    'icon':           type,
    'preview':        preview ?? const <String, dynamic>{},
    'available_actions': const ['open', 'edit', 'delete'],
  };
}

Future<void> _pump(
  WidgetTester tester,
  Widget body, {
  bool spin = false,
}) async {
  await tester.binding.setSurfaceSize(const Size(1100, 900));
  await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      backgroundColor: const Color(0xFF111111),
      body: SingleChildScrollView(child: body),
    ),
  ));
  if (spin) {
    
    
    await tester.pump(const Duration(milliseconds: 50));
  } else {
    await tester.pumpAndSettle();
  }
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('Logins page — loading state never flashes empty', () {
    testWidgets('shows loading state while !hasLoaded', (tester) async {
      await _pump(
        tester,
        LoginsPage(
          isLoading: true,
          hasLoaded: false,
          logins: const <VaultLoginItem>[],
          vaultLabel: 'My Vault',
          onRefresh: () async {},
        ),
        spin: true,
      );
      expect(
        find.byKey(const Key('logins_page_loading_state')),
        findsOneWidget,
      );
      expect(find.text(kLoginsLoadingTitle), findsOneWidget);
      
      
      expect(find.text(kLoginsEmptyTitle), findsNothing);
    });

    testWidgets(
      'shows loading state when not loading AND not loaded yet',
      (tester) async {
        
        
        await _pump(
          tester,
          LoginsPage(
            isLoading: false,
            hasLoaded: false,
            logins: const <VaultLoginItem>[],
            vaultLabel: 'My Vault',
            onRefresh: () async {},
          ),
          spin: true,
        );
        expect(
          find.byKey(const Key('logins_page_loading_state')),
          findsOneWidget,
        );
        expect(find.text(kLoginsEmptyTitle), findsNothing);
      },
    );

    testWidgets('empty state renders ONLY after a loaded response',
        (tester) async {
      await _pump(
        tester,
        LoginsPage(
          isLoading: false,
          hasLoaded: true,
          logins: const <VaultLoginItem>[],
          vaultLabel: 'My Vault',
          onRefresh: () async {},
        ),
      );
      expect(find.text(kLoginsEmptyTitle), findsOneWidget);
      
      expect(
        find.byKey(const Key('logins_page_loading_state')),
        findsNothing,
      );
    });

    testWidgets('cards render once loaded with non-empty list',
        (tester) async {
      await _pump(
        tester,
        LoginsPage(
          isLoading: false,
          hasLoaded: true,
          logins: const [
            VaultLoginItem(
              service:  'Union Bank',
              itemType: 'login',
            ),
          ],
          vaultLabel: 'My Vault',
          onRefresh: () async {},
        ),
      );
      
      expect(find.text('Union Bank'), findsOneWidget);
      
      expect(
        find.byKey(const Key('logins_page_loading_state')),
        findsNothing,
      );
      expect(find.text(kLoginsEmptyTitle), findsNothing);
    });

    testWidgets('error state renders Retry button', (tester) async {
      var retried = false;
      await _pump(
        tester,
        LoginsPage(
          isLoading: false,
          hasLoaded: true,
          error: 'network down',
          logins: const <VaultLoginItem>[],
          vaultLabel: 'My Vault',
          onRefresh: () async {
            retried = true;
          },
        ),
      );
      expect(
        find.byKey(const Key('logins_page_error_state')),
        findsOneWidget,
      );
      expect(find.text(kLoginsErrorTitle), findsOneWidget);
      expect(
        find.byKey(const Key('logins_page_retry_button')),
        findsOneWidget,
      );
      await tester.tap(
        find.byKey(const Key('logins_page_retry_button')),
      );
      await tester.pumpAndSettle();
      expect(retried, isTrue);
    });
  });


  group('Chat card — login detail mode shows username + password', () {
    testWidgets(
      'display_mode=detail surfaces Username and Password lines',
      (tester) async {
        final msg = _envelope(
          reveal: true,
          displayMode: 'detail',
          items: [
            _row(
              itemId: 'a', type: 'login', title: 'Union Bank',
              preview: const {
                'username': 'user_union',
                'password': 'UBank-Hunter-7711',
                'revealed': true,
              },
            ),
          ],
        );
        await _pump(tester, SecureItemResultsCard(
          msg: msg,
          actions: SecureItemCardActions(
            onCopyUsername: (_) {},
            onCopyValue:    (_) {},
            onEdit:   (_, __) {},
            onDelete: (_, __) {},
          ),
        ));
        
        expect(
          find.byKey(const Key('secure_item_chat_card_detail_body')),
          findsOneWidget,
        );
        
        expect(find.text('user_union'),       findsOneWidget);
        expect(find.text('UBank-Hunter-7711'), findsOneWidget);
        
        
        expect(find.text('Username'), findsOneWidget);
        expect(find.text('Password'), findsOneWidget);
        
        
        expect(find.text('View'),         findsNothing);
        expect(find.text('Reveal'),       findsNothing);
        expect(find.text('Login saved'),  findsNothing);
        expect(find.text('Password saved'), findsNothing);
        
        expect(find.text('Copy username'), findsOneWidget);
        expect(find.text('Copy password'), findsOneWidget);
        expect(find.text('Edit'),    findsOneWidget);
        expect(find.text('Delete'),  findsOneWidget);
      },
    );

    testWidgets('Copy password copies the saved value', (tester) async {
      String? copied;
      final msg = _envelope(
        reveal: true,
        displayMode: 'detail',
        items: [
          _row(
            itemId: 'a', type: 'login', title: 'Union Bank',
            preview: const {
              'username': 'user_union',
              'password': 'UBank-Hunter-7711',
              'revealed': true,
            },
          ),
        ],
      );
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onCopyValue: (v) => copied = v,
        ),
      ));
      await tester.tap(
        find.byKey(const Key('secure_item_chat_card_copy_password')),
      );
      await tester.pumpAndSettle();
      expect(copied, 'UBank-Hunter-7711');
    });
  });


  group('Chat card — non-login detail mode shows saved value', () {
    testWidgets('Phone IMEI detail card surfaces the IMEI value',
        (tester) async {
      final msg = _envelope(
        reveal: true,
        displayMode: 'detail',
        items: [
          _row(
            itemId: 'a', type: 'imei', title: 'iPhone 15 IMEI',
            categoryLabel: 'Phone IMEI',
            preview: const {
              'imei_1': '352099001761481',
              'revealed': true,
            },
          ),
        ],
      );
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onCopyValue: (_) {},
          onEdit:   (_, __) {},
          onDelete: (_, __) {},
        ),
      ));
      expect(find.text('352099001761481'), findsOneWidget);
      expect(
        find.byKey(const Key('secure_item_chat_card_detail_value')),
        findsOneWidget,
      );
      
      expect(find.text('View'),   findsNothing);
      expect(find.text('Reveal'), findsNothing);
      
      expect(find.text('Copy value'), findsOneWidget);
      
      expect(find.text('Edit'),   findsOneWidget);
      expect(find.text('Delete'), findsOneWidget);
    });

    testWidgets('Norton license_key detail card surfaces the key value',
        (tester) async {
      final msg = _envelope(
        reveal: true,
        displayMode: 'detail',
        items: [
          _row(
            itemId: 'a', type: 'license_key', title: 'Norton key',
            categoryLabel: 'License key',
            preview: const {
              'license_key': 'NRT-AAAA-BBBB-CCCC',
              'revealed': true,
            },
          ),
        ],
      );
      String? copied;
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onCopyValue: (v) => copied = v,
        ),
      ));
      expect(find.text('NRT-AAAA-BBBB-CCCC'), findsOneWidget);
      expect(find.text('View'),   findsNothing);
      expect(find.text('Reveal'), findsNothing);
      
      await tester.tap(
        find.byKey(const Key('secure_item_chat_card_copy_value')),
      );
      await tester.pumpAndSettle();
      expect(copied, 'NRT-AAAA-BBBB-CCCC');
    });

    testWidgets('Private note detail card surfaces the note text',
        (tester) async {
      final msg = _envelope(
        reveal: true,
        displayMode: 'detail',
        items: [
          _row(
            itemId: 'a', type: 'private_note', title: 'Evening reminders',
            categoryLabel: 'Private note',
            preview: const {
              'private_value':
                  'blue tiger sleeps under the willow',
              'revealed': true,
            },
          ),
        ],
      );
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(
        find.text('blue tiger sleeps under the willow'),
        findsOneWidget,
      );
      expect(find.text('View'),   findsNothing);
      expect(find.text('Reveal'), findsNothing);
    });
  });


  group('Chat card — list mode keeps compact card + View', () {
    testWidgets('login list card shows masked preview + View / Edit / Delete',
        (tester) async {
      final msg = _envelope(
        reveal: false,
        displayMode: 'list',
        items: [
          _row(
            itemId: 'a', type: 'login', title: 'Revolut Bank',
            preview: const {
              'username': 'u',
              'has_password': true,
            },
          ),
          _row(
            itemId: 'b', type: 'login', title: 'Union Bank',
            preview: const {
              'username': 'v',
              'has_password': true,
            },
          ),
        ],
      );
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onView:   (_, __, ___) {},
          onEdit:   (_, __) {},
          onDelete: (_, __) {},
        ),
      ));
      
      expect(
        find.byKey(const Key('secure_item_chat_card_view')),
        findsNWidgets(2),
      );
      
      expect(
        find.byKey(const Key('secure_item_chat_card_detail_body')),
        findsNothing,
      );
      
      expect(find.text('Reveal'), findsNothing);
    });
  });


  group('Source-level guards', () {
    test('main.dart parses display_mode from the envelope', () {
      final src = _read('lib/main.dart');
      final exec = _stripDartComments(src);
      expect(
        exec,
        contains("'display_mode'"),
        reason:
            'main.dart must thread display_mode from the decoded '
            'envelope into the chat-card payload — otherwise the '
            'detail layout never fires on real chat messages.',
      );
    });

    test('logins_page.dart pins the closed-set state copy constants', () {
      final src = _read('lib/logins_page.dart');
      expect(src, contains('kLoginsLoadingTitle'));
      expect(src, contains('kLoginsLoadingBody'));
      expect(src, contains('kLoginsErrorTitle'));
      expect(src, contains('kLoginsErrorBody'));
    });

    test('chat_cards.dart wires display_mode into the row', () {
      final src = _read('lib/ui/chat/chat_cards.dart');
      final exec = _stripDartComments(src);
      expect(exec, contains("isDetail"));
      
      
      expect(exec, contains('_DetailBody'));
      expect(
        exec,
        contains('secure_item_chat_card_detail_body'),
      );
    });
  });
}
