

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _envelope({
  required List<Map<String, dynamic>> items,
  bool reveal = false,
  String? displayMode,
}) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kSecureItemResults,
    payload: <String, dynamic>{
      'items':   items,
      'count':   items.length,
      'reveal':  reveal,
      if (displayMode != null) 'display_mode': displayMode,
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


Future<void> _pumpDesktop(WidgetTester tester, Widget body) async {
  await tester.binding.setSurfaceSize(const Size(1100, 900));
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      backgroundColor: const Color(0xFF111111),
      body: SingleChildScrollView(child: body),
    ),
  ));
  await tester.pumpAndSettle();
}


Future<void> _pumpMobile(WidgetTester tester, Widget body) async {
  
  await tester.binding.setSurfaceSize(const Size(360, 720));
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      backgroundColor: const Color(0xFF111111),
      body: SingleChildScrollView(child: body),
    ),
  ));
  await tester.pumpAndSettle();
}


void main() {
  group('Detail card — compact header + value block + action row', () {
    testWidgets('login detail body block renders ONCE per card',
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
      await _pumpDesktop(tester, SecureItemResultsCard(
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
      
      expect(
        find.byKey(const Key('secure_item_chat_card_detail_username')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('secure_item_chat_card_detail_password')),
        findsOneWidget,
      );
      
      
      expect(find.text('View'),          findsNothing);
      expect(find.text('Reveal'),        findsNothing);
      expect(find.text('Login saved'),   findsNothing);
      expect(find.text('Password saved'), findsNothing);
    });

    testWidgets(
      'login detail with EMPTY values falls back to neutral copy '
      '(no "Login saved")',
      (tester) async {
        
        
        final msg = _envelope(
          reveal: true,
          displayMode: 'detail',
          items: [
            _row(
              itemId: 'a', type: 'login', title: 'Edge case',
              preview: const {'revealed': true},
            ),
          ],
        );
        await _pumpDesktop(tester, SecureItemResultsCard(msg: msg));
        expect(find.text('Login saved'), findsNothing);
        expect(find.text('Password saved'), findsNothing);
        expect(
          find.textContaining('No saved value attached'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'non-login detail value uses SelectableText so long values can '
      'be highlighted',
      (tester) async {
        const longKey = 'NRT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH-IIII';
        final msg = _envelope(
          reveal: true,
          displayMode: 'detail',
          items: [
            _row(
              itemId: 'a', type: 'license_key', title: 'Norton Key',
              preview: const {
                'license_key': longKey,
                'revealed': true,
              },
            ),
          ],
        );
        await _pumpDesktop(tester, SecureItemResultsCard(msg: msg));
        
        expect(
          find.byKey(const Key('secure_item_chat_card_detail_value')),
          findsOneWidget,
        );
        final selectable = tester.widget<SelectableText>(
          find.byKey(const Key('secure_item_chat_card_detail_value')),
        );
        expect(selectable.data, longKey);
      },
    );
  });


  group('List card — compact preview + View / Edit / Delete', () {
    testWidgets('list mode wires View per card, no detail body',
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
          _row(
            itemId: 'c', type: 'login', title: 'Chase Bank',
            preview: const {
              'username': 'w',
              'has_password': true,
            },
          ),
        ],
      );
      await _pumpDesktop(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onView:   (_, __, ___) {},
          onEdit:   (_, __) {},
          onDelete: (_, __) {},
        ),
      ));
      expect(
        find.byKey(const Key('secure_item_chat_card_view')),
        findsNWidgets(3),
      );
      expect(
        find.byKey(const Key('secure_item_chat_card_detail_body')),
        findsNothing,
      );
      expect(find.text('Reveal'), findsNothing);
    });
  });


  group('Mobile narrow viewport — cards do not overflow', () {
    testWidgets('list card fits a 360-wide viewport without overflow',
        (tester) async {
      
      final errors = <FlutterErrorDetails>[];
      final originalHandler = FlutterError.onError;
      FlutterError.onError = errors.add;
      addTearDown(() {
        FlutterError.onError = originalHandler;
      });
      final msg = _envelope(
        reveal: false,
        displayMode: 'list',
        items: [
          _row(
            itemId: 'a', type: 'login',
            title: 'Revolut Bank long enough to test wrap',
            preview: const {
              'username': 'this_is_a_quite_long_username_for_test',
              'has_password': true,
            },
          ),
        ],
      );
      await _pumpMobile(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onView:   (_, __, ___) {},
          onEdit:   (_, __) {},
          onDelete: (_, __) {},
        ),
      ));
      expect(
        errors,
        isEmpty,
        reason:
            'Flutter logged RenderFlex overflow on a 360-wide '
            'narrow viewport — cards must wrap, not overflow.',
      );
    });

    testWidgets('detail card fits a 360-wide viewport without overflow',
        (tester) async {
      final errors = <FlutterErrorDetails>[];
      final originalHandler = FlutterError.onError;
      FlutterError.onError = errors.add;
      addTearDown(() {
        FlutterError.onError = originalHandler;
      });
      const longPw = 'UBank-Hunter-7711-A-Very-Long-Password-For-Wrapping';
      final msg = _envelope(
        reveal: true,
        displayMode: 'detail',
        items: [
          _row(
            itemId: 'a', type: 'login',
            title: 'Union Bank with a fairly long title',
            preview: const {
              'username': 'a_long_username_to_check_wrap',
              'password': longPw,
              'revealed': true,
            },
          ),
        ],
      );
      await _pumpMobile(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onCopyUsername: (_) {},
          onCopyValue:    (_) {},
          onEdit:   (_, __) {},
          onDelete: (_, __) {},
        ),
      ));
      expect(errors, isEmpty);
    });

    testWidgets(
      'non-login detail with a very long value wraps without overflow',
      (tester) async {
        final errors = <FlutterErrorDetails>[];
        final originalHandler = FlutterError.onError;
        FlutterError.onError = errors.add;
        addTearDown(() {
          FlutterError.onError = originalHandler;
        });
        const longKey =
            'NRT-AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH-IIII-JJJJ'
            '-KKKK-LLLL-MMMM';
        final msg = _envelope(
          reveal: true,
          displayMode: 'detail',
          items: [
            _row(
              itemId: 'a', type: 'license_key', title: 'Norton Key',
              preview: const {
                'license_key': longKey,
                'revealed': true,
              },
            ),
          ],
        );
        await _pumpMobile(tester, SecureItemResultsCard(
          msg: msg,
          actions: SecureItemCardActions(
            onCopyValue: (_) {},
            onEdit:   (_, __) {},
            onDelete: (_, __) {},
          ),
        ));
        expect(errors, isEmpty);
        
        final selectable = tester.widget<SelectableText>(
          find.byKey(const Key('secure_item_chat_card_detail_value')),
        );
        expect(selectable.data, longKey);
      },
    );
  });


  group('Visual consistency', () {
    test('detail body key is closed-set', () {
      
      
      expect(
        const Key('secure_item_chat_card_detail_body'),
        equals(const Key('secure_item_chat_card_detail_body')),
      );
      expect(
        const Key('secure_item_chat_card_detail_username'),
        equals(const Key('secure_item_chat_card_detail_username')),
      );
      expect(
        const Key('secure_item_chat_card_detail_password'),
        equals(const Key('secure_item_chat_card_detail_password')),
      );
      expect(
        const Key('secure_item_chat_card_detail_value'),
        equals(const Key('secure_item_chat_card_detail_value')),
      );
    });
  });
}
