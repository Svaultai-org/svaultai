

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _extractionReviewMsg({
  required List<Map<String, dynamic>> records,
  Map<String, dynamic>? file,
  String message = '',
  bool textAvailable = true,
}) {
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kCredentialExtractionReview,
    payload: <String, dynamic>{
      'records': records,
      'file': file ?? const <String, dynamic>{},
      'count': records.length,
      'text_available': textAvailable,
    },
  );
}


Future<void> _pumpExtractionReview(
  WidgetTester tester, {
  required ChatMessage msg,
  Size viewport = const Size(900, 1200),
}) async {
  tester.view.physicalSize = viewport;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        backgroundColor: const Color(0xFF0F1115),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: CredentialExtractionReviewCard(msg: msg),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('CredentialExtractionReviewCard', () {
    testWidgets('renders header + safety hint + records list',
        (tester) async {
      await _pumpExtractionReview(
        tester,
        msg: _extractionReviewMsg(
          message: 'I found 2 login records in bitwarden.json.',
          file: {
            'file_id': 'f1',
            'file_name': 'bitwarden.json',
            'saved_name': 'Bitwarden export',
            'relative_path': 'Secrets/bitwarden.json',
          },
          records: [
            {
              'service': 'Gmail',
              'username': null,
              'email': 'alice@example.com',
              'password_present': true,
              'pin_present': false,
              'note_present': false,
            },
            {
              'service': 'Wells Fargo',
              'username': null,
              'email': 'alice@example.com',
              'password_present': true,
              'pin_present': true,
              'note_present': true,
            },
          ],
        ),
      );
      expect(find.text('Review extracted logins'), findsOneWidget);
      expect(find.text('Bitwarden export'), findsOneWidget);
      expect(find.text('Gmail'), findsOneWidget);
      expect(find.text('Wells Fargo'), findsOneWidget);
      
      expect(find.text('alice@example.com'), findsWidgets);
      
      expect(find.text('password present'), findsNWidgets(2));
      
      expect(find.text('PIN present'), findsOneWidget);
      expect(find.text('note present'), findsOneWidget);
      
      expect(
        find.textContaining(
            'will not save anything until you confirm'),
        findsOneWidget,
      );
    });

    testWidgets('NEVER renders password / pin / note VALUES even if '
        'records carry them', (tester) async {
      
      
      await _pumpExtractionReview(
        tester,
        msg: _extractionReviewMsg(
          file: {'file_id': 'f1', 'file_name': 'big-leak.json'},
          records: [
            {
              'service': 'Gmail',
              'username': null,
              'email': 'alice@example.com',
              'password_present': true,
              'pin_present': true,
              'note_present': true,
              
              'password': 'hunter2-extraction',
              'pin': '7777',
              'note': 'note-value-extraction',
            },
          ],
        ),
      );
      for (final leaked in [
        'hunter2-extraction',
        '7777',
        'note-value-extraction',
      ]) {
        expect(
          find.textContaining(leaked), findsNothing,
          reason: 'extraction review must never render value "$leaked"',
        );
      }
    });

    testWidgets('shows "no password" chip when password_present is false',
        (tester) async {
      await _pumpExtractionReview(
        tester,
        msg: _extractionReviewMsg(
          file: {'file_id': 'f1', 'file_name': 'partial.json'},
          records: [
            {
              'service': 'Slack',
              'username': 'alice',
              'email': null,
              'password_present': false,
              'pin_present': false,
              'note_present': false,
            },
          ],
        ),
      );
      expect(find.text('no password'), findsOneWidget);
      expect(find.text('password present'), findsNothing);
    });

    testWidgets('shows "Run vault analysis" hint when text_available is '
        'false', (tester) async {
      await _pumpExtractionReview(
        tester,
        msg: _extractionReviewMsg(
          file: {'file_id': 'f1', 'file_name': 'locked.bin'},
          records: const <Map<String, dynamic>>[],
          textAvailable: false,
        ),
      );
      expect(
        find.textContaining('Run vault analysis'),
        findsOneWidget,
      );
    });
  });

  group('Source guards', () {
    test('chat_models.dart exposes kCredentialExtractionReview', () {
      expect(
        ChatMessage.kCredentialExtractionReview,
        equals('credential_extraction_review'),
      );
    });

    test('chat_bubble.dart routes kCredentialExtractionReview', () async {
      final src =
          await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('kCredentialExtractionReview'));
      expect(src, contains('CredentialExtractionReviewCard'));
    });

    test('main.dart parser handles credential_extraction_review type',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'credential_extraction_review'"));
    });

    test('main.dart parser still threads sections + actions + '
        'has_content_matches into payload', () async {
      
      
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("'sections': sections"),
          reason: 'parser must thread sections into the payload');
      expect(src, contains("'actions': actions"),
          reason: 'parser must thread actions into the payload');
      expect(
        src,
        contains("'has_content_matches': decoded['has_content_matches']"),
        reason: 'parser must thread has_content_matches into the payload',
      );
    });
  });
}
