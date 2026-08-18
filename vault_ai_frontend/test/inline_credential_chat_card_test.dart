import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/chat_bubble.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

void main() {
  testWidgets('credential lookup renders inline and masks password by default',
      (tester) async {
    final message = ChatMessage(
      'assistant',
      'Here is your RandomService login.',
      kind: ChatMessage.kInlineCredential,
      payload: const {
        'service': 'RandomService',
        'username': 'random-user',
        'password': 'random-secret',
      },
    );

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ChatBubble(msg: message, isMobile: false),
      ),
    ));

    expect(
        find.byKey(const Key('chat_inline_credential_card')), findsOneWidget);
    expect(find.text('RandomService'), findsOneWidget);
    expect(find.text('random-user'), findsOneWidget);
    expect(find.text('random-secret'), findsNothing);
    expect(find.text('••••••••••••'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat_inline_toggle_password')));
    await tester.pump();
    expect(find.text('random-secret'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat_inline_toggle_password')));
    await tester.pump();
    expect(find.text('random-secret'), findsNothing);
    expect(find.byKey(const Key('chat_inline_copy_username')), findsOneWidget);
    expect(find.byKey(const Key('chat_inline_copy_password')), findsOneWidget);
  });

  testWidgets('email-only retrieval does not render a blank username field',
      (tester) async {
    final message = ChatMessage(
      'assistant',
      'Here is your Ebay login.',
      kind: ChatMessage.kInlineCredential,
      payload: const {
        'service': 'Ebay',
        'username': 'test@example.com',
        'password': 'ExactPass!123',
        'fields': {
          'email': 'test@example.com',
          'password': 'ExactPass!123',
        },
      },
    );

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ChatBubble(msg: message, isMobile: false),
      ),
    ));

    expect(find.text('Email'), findsOneWidget);
    expect(find.text('test@example.com'), findsOneWidget);
    expect(find.text('Username'), findsNothing);
    expect(find.text('ExactPass!123'), findsNothing);

    await tester.tap(find.byKey(const Key('chat_inline_toggle_password')));
    await tester.pump();
    expect(find.text('ExactPass!123'), findsOneWidget);
  });

  testWidgets('typed and custom retrieval fields survive inline rendering',
      (tester) async {
    final message = ChatMessage(
      'assistant',
      'Here is your Mixed login.',
      kind: ChatMessage.kInlineCredential,
      payload: const {
        'service': 'Mixed',
        'username': 'member55',
        'password': 'ExactPass!XYZ',
        'fields': {
          'login_id': 'member55',
          'account_number': '123456789',
          'secure_value': 'alpha-beta',
          'pin': '9988',
          'password': 'ExactPass!XYZ',
        },
      },
    );

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ChatBubble(msg: message, isMobile: false),
      ),
    ));

    expect(find.text('Login ID'), findsOneWidget);
    expect(find.text('member55'), findsOneWidget);
    for (final value in [
      '123456789',
      'alpha-beta',
      '9988',
      'ExactPass!XYZ',
    ]) {
      expect(find.text(value), findsNothing);
    }

    await tester.tap(find.byKey(const Key('chat_inline_toggle_password')));
    await tester.pump();
    expect(find.text('Account number'), findsOneWidget);
    expect(find.text('Secure value'), findsOneWidget);
    expect(find.text('PIN'), findsOneWidget);
    for (final value in [
      '123456789',
      'alpha-beta',
      '9988',
      'ExactPass!XYZ',
    ]) {
      expect(find.text(value), findsOneWidget);
    }
  });

  test('legacy direct-open passes the complete decrypted field map', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('Future<void> _openLegacySecureItemDirect(');
    final end = source.indexOf(
      'CredentialV2Repository? _credentialV2Repository',
      start,
    );
    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));
    final body = source.substring(start, end);
    expect(body, contains("'fields': fields"));
    expect(body, contains("'email'"));
    expect(body, contains("'user_id'"));
    expect(body, contains("'login_id'"));
    expect(body, isNot(contains('fields.values.whereType<String>().firstOrNull')));
  });
}
