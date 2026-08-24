import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/chat_bubble.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

Widget _host(ChatMessage message, {required bool streaming}) => MaterialApp(
      home: Scaffold(
        body: ChatBubble(
          msg: message,
          isMobile: false,
          isStreaming: streaming,
        ),
      ),
    );

void main() {
  testWidgets('empty streaming assistant placeholder paints no ellipsis',
      (tester) async {
    await tester.pumpWidget(_host(ChatMessage('assistant', ''), streaming: true));

    expect(find.text('...'), findsNothing);
    expect(find.byType(SelectableText), findsNothing);
  });

  testWidgets('meaningful assistant ellipsis is preserved', (tester) async {
    await tester.pumpWidget(
      _host(ChatMessage('assistant', 'Wait...'), streaming: false),
    );

    expect(find.text('Wait...'), findsOneWidget);
  });
}
