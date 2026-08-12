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
}
