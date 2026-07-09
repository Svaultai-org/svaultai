

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/secure_item_detail.dart';


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
  String? message,
}) {
  return ChatMessage(
    'assistant',
    message ?? 'I found ${items.length} saved items 🔐',
    kind: ChatMessage.kSecureItemResults,
    payload: <String, dynamic>{
      'items':   items,
      'count':   items.length,
      'reveal':  reveal,
      'message': message ?? 'I found ${items.length} saved items 🔐',
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


Future<void> _pump(WidgetTester tester, Widget body) async {
  await tester.binding.setSurfaceSize(const Size(900, 800));
  await tester.pumpWidget(MaterialApp(
        localizationsDelegates: _testL10nDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
    home: Scaffold(
      backgroundColor: const Color(0xFF111111),
      body: SingleChildScrollView(child: body),
    ),
  ));
  await tester.pumpAndSettle();
}




const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('Source-level guards — no Reveal button anywhere', () {
    test('chat_cards.dart contains no executable "Reveal" button label',
        () {
      final src = _read('lib/ui/chat/chat_cards.dart');
      final exec = _stripDartComments(src);
      
      
      expect(
        exec,
        isNot(contains("Text('Reveal'")),
        reason:
            'chat_cards.dart still renders a "Reveal" button. '
            'Operator brief: Reveal removed entirely.',
      );
    });

    test('chat_cards.dart has no reveal-button widget key', () {
      final src = _read('lib/ui/chat/chat_cards.dart');
      final exec = _stripDartComments(src);
      expect(
        exec,
        isNot(contains('secure_item_chat_card_reveal')),
        reason:
            'Removed Reveal button keeps its widget key alive — '
            'a test could still tap it and the user could too.',
      );
    });

    test('secure_item_detail.dart contains no executable Reveal button',
        () {
      final src = _read('lib/ui/secure_item_detail.dart');
      final exec = _stripDartComments(src);
      expect(
        exec,
        isNot(contains("Text('Reveal')")),
        reason:
            'The detail sheet still renders Reveal. Operator '
            'brief: Reveal removed entirely.',
      );
      expect(
        exec,
        isNot(contains('secure_item_detail_reveal')),
        reason:
            'Reveal widget key still lives in the detail sheet.',
      );
    });

    test('secure_item_detail.dart no longer prompts "Tap Reveal"', () {
      final src = _read('lib/ui/secure_item_detail.dart');
      final exec = _stripDartComments(src);
      expect(
        exec,
        isNot(contains('Tap Reveal')),
        reason:
            'Per-type masked hint still nudges the user toward a '
            'removed Reveal button. Update copy to "Ask your vault".',
      );
    });

    test('logins_page.dart never advertises a Reveal action', () {
      final src = _read('lib/logins_page.dart');
      final exec = _stripDartComments(src);
      
      
      expect(
        exec,
        isNot(contains("Text('Reveal')")),
      );
      expect(
        exec,
        isNot(contains("label: const Text('Reveal'")),
      );
    });
  });

  group('Widget render — no Reveal button on masked or revealed card', () {
    testWidgets('chat card with masked envelope renders no Reveal',
        (tester) async {
      final msg = _envelope(items: [
        _row(
          itemId: 'a',
          type: 'login',
          title: 'Revolut Bank',
          preview: const {
            'username': 'user_revolut',
            'has_password': true,
          },
        ),
      ]);
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onView:   (_, __, ___) {},
          onEdit:   (_, __) {},
          onDelete: (_, __) {},
          onCopyUsername: (_) {},
        ),
      ));
      expect(find.text('Reveal'), findsNothing);
      expect(find.text('View'),   findsOneWidget);
      expect(find.text('Edit'),   findsOneWidget);
      expect(find.text('Delete'), findsOneWidget);
      expect(find.text('Copy username'), findsOneWidget);
    });

    testWidgets('chat card with revealed login shows username + password',
        (tester) async {
      
      
      final msg = ChatMessage(
        'assistant',
        '',
        kind: ChatMessage.kSecureItemResults,
        payload: <String, dynamic>{
          'reveal': true,
          'count':  1,
          'items':  [
            _row(
              itemId: 'a', type: 'login', title: 'Revolut Bank',
              preview: const {
                'username': 'user_revolut',
                'password': 'RBank-Hunter-3399',
                'revealed': true,
              },
            ),
          ],
        },
      );
      String? copied;
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onCopyUsername: (u) => copied = u,
          onCopyValue:    (v) => copied = v,
        ),
      ));
      expect(find.text('Reveal'), findsNothing);
      
      
      expect(find.text('user_revolut'), findsOneWidget);
      expect(find.text('RBank-Hunter-3399'), findsOneWidget);
      expect(find.text('Username'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);
      
      expect(find.text('Copy username'), findsOneWidget);
      expect(find.text('Copy password'), findsOneWidget);

      await tester.tap(
        find.byKey(const Key('secure_item_chat_card_copy_password')),
      );
      await tester.pumpAndSettle();
      expect(copied, 'RBank-Hunter-3399');
    });

    testWidgets('chat card with revealed non-login shows Copy value',
        (tester) async {
      final msg = ChatMessage(
        'assistant',
        '',
        kind: ChatMessage.kSecureItemResults,
        payload: <String, dynamic>{
          'reveal': true,
          'count':  1,
          'items':  [
            _row(
              itemId: 'a',
              type: 'license_key',
              title: 'Norton key',
              preview: const {
                'license_key': 'NRT-AAAA-BBBB-CCCC',
                'revealed':    true,
              },
            ),
          ],
        },
      );
      String? copied;
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onCopyValue: (v) => copied = v,
        ),
      ));
      expect(find.text('Reveal'), findsNothing);
      expect(find.text('Copy value'), findsOneWidget);
      
      expect(find.text('Copy username'), findsNothing);

      await tester.tap(
        find.byKey(const Key('secure_item_chat_card_copy_value')),
      );
      await tester.pumpAndSettle();
      expect(copied, 'NRT-AAAA-BBBB-CCCC');
    });
  });

  group('SecureItemDetailSheet — Reveal removed', () {
    testWidgets('detail sheet for non-login never shows Reveal',
        (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'Phone IMEI',
          itemType: 'imei',
        ),
      );
      expect(find.text('Reveal'), findsNothing);
      expect(
        find.byKey(const Key('secure_item_detail_reveal')),
        findsNothing,
      );
    });

    testWidgets('detail sheet for login never shows Reveal',
        (tester) async {
      await _pump(
        tester,
        const SecureItemDetailSheet(
          title: 'Netflix',
          itemType: 'login',
          username: 'alice',
        ),
      );
      expect(find.text('Reveal'), findsNothing);
      
      expect(find.text('Copy username'), findsOneWidget);
    });
  });
}
