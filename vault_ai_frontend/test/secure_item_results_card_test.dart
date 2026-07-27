

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

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
    'available_actions': const ['open', 'reveal', 'edit', 'delete'],
  };
}

Future<void> _pump(WidgetTester tester, Widget body) async {
  await tester.binding.setSurfaceSize(const Size(900, 800));
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      backgroundColor: const Color(0xFF111111),
      body: SingleChildScrollView(child: body),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('Header / count message', () {
    testWidgets('renders the envelope message line', (tester) async {
      final msg = _envelope(
        message: 'I found 3 saved items 🔐',
        items: [
          _row(itemId: 'a', type: 'login', title: 'Netflix'),
          _row(itemId: 'b', type: 'imei',  title: 'iPhone 15 IMEI'),
          _row(itemId: 'c', type: 'license_key', title: 'Norton key'),
        ],
      );
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('I found 3 saved items 🔐'), findsOneWidget);
    });

    testWidgets('empty envelope still renders the message', (tester) async {
      final msg = _envelope(
        items: const [],
        message: "You haven't saved any items like that yet.",
      );
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(
        find.text("You haven't saved any items like that yet."),
        findsOneWidget,
      );
    });
  });

  group('Per-item card rendering', () {
    testWidgets('IMEI card shows "IMEI ending NNNN"', (tester) async {
      final msg = _envelope(items: [
        _row(
          itemId: 'a', type: 'imei', title: 'iPhone 15 IMEI',
          categoryLabel: 'Phone IMEI',
          preview: const {'imei_1_mask': 'ending 5678'},
        ),
      ]);
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('iPhone 15 IMEI'), findsOneWidget);
      expect(find.text('Phone IMEI'), findsOneWidget);
      expect(find.text('IMEI ending 5678'), findsOneWidget);
    });

    testWidgets('Login card shows username + "Password saved"', (tester) async {
      final msg = _envelope(items: [
        _row(
          itemId: 'a', type: 'login', title: 'Netflix',
          categoryLabel: 'Login',
          preview: const {
            'username':     'alice',
            'has_password': true,
          },
        ),
      ]);
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('Netflix'), findsOneWidget);
      expect(find.textContaining('Username'), findsOneWidget);
      expect(find.textContaining('alice'), findsOneWidget);
      expect(find.textContaining('Password saved'), findsOneWidget);
    });

    testWidgets('revealed login detail renders custom fields in order',
        (tester) async {
      final msg = _envelope(
        reveal: true,
        items: [
          _row(
            itemId: 'a',
            type: 'login',
            title: 'Tinder',
            categoryLabel: 'Login',
            preview: const {
              'username': 'beraves',
              'password': 'bunty1234567',
              'fields': [
                {'label': 'Username', 'value': 'beraves'},
                {'label': 'Password', 'value': 'bunty1234567'},
                {'label': 'pin', 'value': '748291'},
                {'label': 'Recovery Code', 'value': 'blue-hill-42'},
              ],
            },
          ),
        ],
      );
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('Username'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);
      expect(find.text('pin'), findsOneWidget);
      expect(find.text('Recovery Code'), findsOneWidget);
      expect(find.text('beraves'), findsOneWidget);
      expect(find.text('bunty1234567'), findsOneWidget);
      expect(find.text('748291'), findsOneWidget);
      expect(find.text('blue-hill-42'), findsOneWidget);
    });

    testWidgets('Private note card shows hidden preview', (tester) async {
      final msg = _envelope(items: [
        _row(
          itemId: 'a', type: 'private_note', title: 'Secret word',
          categoryLabel: 'Private note',
          preview: const {'private_value_mask': '•••••• hidden'},
        ),
      ]);
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('Secret word'), findsOneWidget);
      expect(find.text('•••••• hidden'), findsOneWidget);
    });

    testWidgets('License key card shows hidden preview', (tester) async {
      final msg = _envelope(items: [
        _row(
          itemId: 'a', type: 'license_key', title: 'Norton key',
          categoryLabel: 'License key',
          preview: const {'license_key_mask': '•••••• hidden'},
        ),
      ]);
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('Norton key'), findsOneWidget);
      expect(find.text('•••••• hidden'), findsOneWidget);
    });

    testWidgets('Crypto wallet card shows mask + network chip', (tester) async {
      final msg = _envelope(items: [
        _row(
          itemId: 'a', type: 'crypto_wallet_address',
          title: 'USDT TRC20 wallet',
          categoryLabel: 'Crypto wallet',
          preview: const {
            'wallet_address_mask': 'TQxXxX…aBcD',
            'network':             'USDT TRC20',
          },
        ),
      ]);
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('USDT TRC20 wallet'), findsOneWidget);
      expect(find.textContaining('TQxXxX…aBcD'), findsOneWidget);
      expect(find.textContaining('USDT TRC20'), findsAtLeastNWidgets(1));
    });

    testWidgets('Seed phrase card shows hidden preview', (tester) async {
      final msg = _envelope(items: [
        _row(
          itemId: 'a', type: 'crypto_seed_phrase',
          title: 'BTC seed phrase',
          categoryLabel: 'Seed phrase',
          preview: const {'seed_phrase_mask': '•••••• hidden'},
        ),
      ]);
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('BTC seed phrase'), findsOneWidget);
      expect(find.textContaining('hidden'), findsAtLeastNWidgets(1));
    });
  });

  group('Card buttons + actions', () {
    testWidgets('View / Edit / Delete buttons render (no Reveal)',
        (tester) async {
      
      
      final msg = _envelope(items: [
        _row(itemId: 'a', type: 'imei', title: 'Phone IMEI'),
      ]);
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onView: (_, __, ___) {},
          onEdit: (_, __) {},
          onDelete: (_, __) {},
        ),
      ));
      expect(find.text('View'), findsOneWidget);
      expect(find.text('Reveal'), findsNothing);
      expect(
        find.byKey(const Key('secure_item_chat_card_reveal')),
        findsNothing,
      );
      expect(find.text('Edit'), findsOneWidget);
      expect(find.text('Delete'), findsOneWidget);
    });

    testWidgets('Login card adds Copy username button', (tester) async {
      final msg = _envelope(items: [
        _row(
          itemId: 'a', type: 'login', title: 'Netflix',
          preview: const {'username': 'alice', 'has_password': true},
        ),
      ]);
      String? copied;
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onCopyUsername: (u) => copied = u,
        ),
      ));
      expect(find.text('Copy username'), findsOneWidget);
      await tester.tap(find.text('Copy username'));
      await tester.pumpAndSettle();
      expect(copied, 'alice');
    });

    testWidgets('Reveal button NEVER renders, even on masked card',
        (tester) async {
      
      
      final msg = _envelope(items: [
        _row(itemId: 'a', type: 'imei', title: 'Phone IMEI',
            preview: const {'imei_1_mask': 'ending 1234'}),
      ]);
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('Reveal'), findsNothing);
      expect(
        find.byKey(const Key('secure_item_chat_card_reveal')),
        findsNothing,
      );
    });

    testWidgets('Reveal button NEVER renders even on revealed card',
        (tester) async {
      
      
      final msg = ChatMessage(
        'assistant',
        '',
        kind: ChatMessage.kSecureItemResults,
        payload: <String, dynamic>{
          'reveal': true,
          'count':  1,
          'items':  [
            _row(itemId: 'a', type: 'imei', title: 'Phone IMEI',
                preview: const {'imei_1': '123456789012345'}),
          ],
        },
      );
      await _pump(tester, SecureItemResultsCard(msg: msg));
      expect(find.text('Reveal'), findsNothing);
      
      expect(find.text('123456789012345'), findsOneWidget);
    });

    testWidgets(
      'Copy value renders on a REVEALED non-login card',
      (tester) async {
        String? copied;
        final msg = ChatMessage(
          'assistant',
          '',
          kind: ChatMessage.kSecureItemResults,
          payload: <String, dynamic>{
            'reveal': true,
            'count':  1,
            'items':  [
              _row(itemId: 'a', type: 'imei', title: 'Phone IMEI',
                  preview: const {'imei_1': '123456789012345'}),
            ],
          },
        );
        await _pump(tester, SecureItemResultsCard(
          msg: msg,
          actions: SecureItemCardActions(
            onCopyValue: (v) => copied = v,
          ),
        ));
        expect(find.text('Copy value'), findsOneWidget);
        await tester.tap(
          find.byKey(const Key('secure_item_chat_card_copy_value')),
        );
        await tester.pumpAndSettle();
        expect(copied, '123456789012345');
      },
    );

    testWidgets(
      'Copy value HIDDEN on a masked (reveal=false) non-login card',
      (tester) async {
        final msg = _envelope(items: [
          _row(
            itemId: 'a', type: 'imei', title: 'Phone IMEI',
            preview: const {'imei_1_mask': 'ending 5678'},
          ),
        ]);
        await _pump(tester, SecureItemResultsCard(msg: msg));
        expect(find.text('Copy value'), findsNothing);
      },
    );

    testWidgets(
      'Copy value HIDDEN on a REVEALED LOGIN card',
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
                itemId: 'a', type: 'login', title: 'Netflix',
                preview: const {
                  'username': 'alice', 'password': 'fishfish',
                },
              ),
            ],
          },
        );
        await _pump(tester, SecureItemResultsCard(msg: msg));
        expect(find.text('Copy value'), findsNothing);
        
        expect(find.text('Copy username'), findsOneWidget);
      },
    );

    testWidgets('View tap calls onView with (item_id, title, type)',
        (tester) async {
      String? capturedId, capturedTitle, capturedType;
      final msg = _envelope(items: [
        _row(itemId: 'uuid-9', type: 'license_key', title: 'Norton key'),
      ]);
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onView: (id, t, ty) {
            capturedId = id; capturedTitle = t; capturedType = ty;
          },
        ),
      ));
      await tester.tap(find.text('View'));
      await tester.pumpAndSettle();
      expect(capturedId, 'uuid-9');
      expect(capturedTitle, 'Norton key');
      expect(capturedType, 'license_key');
    });

    testWidgets('Delete tap calls onDelete with (title, type)',
        (tester) async {
      String? capturedTitle, capturedType;
      final msg = _envelope(items: [
        _row(itemId: 'uuid-9', type: 'imei', title: 'iPhone 15 IMEI'),
      ]);
      await _pump(tester, SecureItemResultsCard(
        msg: msg,
        actions: SecureItemCardActions(
          onDelete: (t, ty) {
            capturedTitle = t; capturedType = ty;
          },
        ),
      ));
      await tester.tap(find.text('Delete'));
      await tester.pumpAndSettle();
      expect(capturedTitle, 'iPhone 15 IMEI');
      expect(capturedType, 'imei');
    });
  });

  group('Masking — no raw value leakage', () {
    testWidgets(
      'IMEI card does NOT render raw 15-digit value from masked envelope',
      (tester) async {
        final msg = _envelope(items: [
          _row(
            itemId: 'a', type: 'imei', title: 'Phone IMEI',
            
            
            preview: const {'imei_1_mask': 'ending 5678'},
          ),
        ]);
        await _pump(tester, SecureItemResultsCard(msg: msg));
        expect(find.text('IMEI ending 5678'), findsOneWidget);
      },
    );

    testWidgets(
      'Private note card never shows raw value when masked',
      (tester) async {
        final msg = _envelope(items: [
          _row(
            itemId: 'a', type: 'private_note', title: 'Secret',
            preview: const {'private_value_mask': '•••••• hidden'},
          ),
        ]);
        await _pump(tester, SecureItemResultsCard(msg: msg));
        
        
        expect(find.text('•••••• hidden'), findsOneWidget);
      },
    );
  });

  group('ChatMessage.isCard recognises the new kind', () {
    test('kSecureItemResults flips isCard', () {
      final msg = ChatMessage(
        'assistant', '', kind: ChatMessage.kSecureItemResults,
      );
      expect(msg.isCard, isTrue);
    });

    test('constant is stable', () {
      expect(ChatMessage.kSecureItemResults, 'secure_item_results');
    });
  });
}
