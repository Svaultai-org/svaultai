

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _relatedMsg({
  Map<String, dynamic>? anchor,
  required List<Map<String, dynamic>> results,
  String message = '',
}) {
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kRelatedFiles,
    payload: <String, dynamic>{
      'anchor': anchor ??
          {
            'file_id': 'a1',
            'file_name': 'maureen id back.jpg',
            'saved_name': 'Maureen ID back',
            'relative_path': 'Identity/maureen id back.jpg',
          },
      'count': results.length,
      'results': results,
    },
  );
}


Future<void> _pump(
  WidgetTester tester, {
  required ChatMessage msg,
  void Function(ChatMessage)? onOpen,
  Size viewport = const Size(900, 800),
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
            child: RelatedFilesCard(msg: msg, onOpen: onOpen),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('RelatedFilesCard — header', () {
    testWidgets('shows anchor label and match count', (tester) async {
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f1',
              'file_name': 'maureen id front.jpg',
              'saved_name': 'Maureen ID front',
              'relative_path': 'Identity/maureen id front.jpg',
              'confidence': 'strong',
              'reasons': [
                {
                  'code': 'filename_front_back_pair',
                  'label': 'matching front/back filename pair',
                  'weight': 2.0,
                },
              ],
            },
          ],
        ),
      );
      expect(find.textContaining('Related to Maureen ID back'),
          findsOneWidget);
      expect(find.textContaining('1 match'), findsOneWidget);
    });
  });

  group('RelatedFilesCard — confidence badges', () {
    testWidgets('strong shows STRONG chip', (tester) async {
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f1',
              'file_name': 'maureen id front.jpg',
              'confidence': 'strong',
              'reasons': [
                {
                  'code': 'filename_front_back_pair',
                  'label': 'matching front/back filename pair',
                  'weight': 2.0,
                },
              ],
            },
          ],
        ),
      );
      expect(find.text('STRONG'), findsOneWidget);
    });

    testWidgets('medium shows MEDIUM chip', (tester) async {
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f1',
              'file_name': 'something.jpg',
              'confidence': 'medium',
              'reasons': [
                {
                  'code': 'shared_filename_token',
                  'label': 'shared filename token',
                  'weight': 0.5,
                },
              ],
            },
          ],
        ),
      );
      expect(find.text('MEDIUM'), findsOneWidget);
    });

    testWidgets('weak shows WEAK chip', (tester) async {
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f1',
              'file_name': 'random.jpg',
              'confidence': 'weak',
              'reasons': [
                {
                  'code': 'same_import_batch',
                  'label': 'same import batch',
                  'weight': 0.3,
                },
              ],
            },
          ],
        ),
      );
      expect(find.text('WEAK'), findsOneWidget);
    });
  });

  group('RelatedFilesCard — reasons line', () {
    testWidgets('joins multiple reason labels with " · "', (tester) async {
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f1',
              'file_name': 'maureen id front.jpg',
              'saved_name': 'Maureen ID front',
              'relative_path': 'Identity/maureen id front.jpg',
              'confidence': 'strong',
              'reasons': [
                {
                  'code': 'filename_front_back_pair',
                  'label': 'matching front/back filename pair',
                  'weight': 2.0,
                },
                {
                  'code': 'same_folder',
                  'label': 'same folder',
                  'weight': 0.6,
                },
              ],
            },
          ],
        ),
      );
      expect(
        find.textContaining(
            'matching front/back filename pair · same folder'),
        findsOneWidget,
      );
    });

    testWidgets('shows folder path when relative_path present',
        (tester) async {
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f1',
              'file_name': 'maureen id front.jpg',
              'saved_name': 'Maureen ID front',
              'relative_path': 'Identity/maureen id front.jpg',
              'confidence': 'strong',
              'reasons': [
                {
                  'code': 'same_folder',
                  'label': 'same folder',
                  'weight': 0.6,
                },
              ],
            },
          ],
        ),
      );
      expect(find.text('Identity/maureen id front.jpg'), findsOneWidget);
    });
  });

  group('RelatedFilesCard — weak-only disclaimer', () {
    testWidgets('weak-only results render the spec disclaimer',
        (tester) async {
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f1',
              'file_name': 'a.jpg',
              'confidence': 'weak',
              'reasons': [
                {
                  'code': 'same_import_batch',
                  'label': 'same import batch',
                  'weight': 0.3,
                },
              ],
            },
            {
              'file_id': 'f2',
              'file_name': 'b.jpg',
              'confidence': 'weak',
              'reasons': [
                {
                  'code': 'same_import_batch',
                  'label': 'same import batch',
                  'weight': 0.3,
                },
              ],
            },
          ],
        ),
      );
      expect(
        find.textContaining("I'm not sure they're actually related"),
        findsOneWidget,
      );
      expect(find.textContaining('weak only'), findsOneWidget);
    });

    testWidgets('non-weak-only results suppress the disclaimer',
        (tester) async {
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f1',
              'file_name': 'a.jpg',
              'confidence': 'strong',
              'reasons': [
                {
                  'code': 'filename_front_back_pair',
                  'label': 'matching front/back filename pair',
                  'weight': 2.0,
                },
              ],
            },
            {
              'file_id': 'f2',
              'file_name': 'b.jpg',
              'confidence': 'weak',
              'reasons': [
                {
                  'code': 'same_import_batch',
                  'label': 'same import batch',
                  'weight': 0.3,
                },
              ],
            },
          ],
        ),
      );
      expect(
        find.textContaining("I'm not sure they're actually related"),
        findsNothing,
      );
    });
  });

  group('RelatedFilesCard — empty state', () {
    testWidgets('no results renders friendly copy', (tester) async {
      await _pump(
        tester,
        msg: ChatMessage(
          'assistant',
          "I couldn't find any clearly related files for Maureen ID back.",
          kind: ChatMessage.kRelatedFiles,
          payload: const <String, dynamic>{
            'anchor': {
              'file_id': 'a1',
              'file_name': 'maureen id back.jpg',
              'saved_name': 'Maureen ID back',
            },
            'count': 0,
            'results': <Map<String, dynamic>>[],
          },
        ),
      );
      expect(find.text('No clearly related files'), findsOneWidget);
    });
  });

  group('RelatedFilesCard — onOpen', () {
    testWidgets('tapping a result synthesises a single-file ChatMessage',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _relatedMsg(
          results: [
            {
              'file_id': 'f-related',
              'file_name': 'related.jpg',
              'saved_name': 'Related',
              'confidence': 'strong',
              'reasons': [
                {
                  'code': 'filename_front_back_pair',
                  'label': 'matching front/back filename pair',
                  'weight': 2.0,
                },
              ],
            },
          ],
        ),
        onOpen: (m) => captured = m,
      );
      
      await tester.tap(find.text('Related'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.kind, ChatMessage.kVaultFile);
      expect(captured!.fileId, 'f-related');
      expect(captured!.fileName, 'related.jpg');
    });
  });

  group('RelatedFilesCard — overflow guards', () {
    testWidgets('100-row payload does not overflow', (tester) async {
      final many = List.generate(
        100,
        (i) => <String, dynamic>{
          'file_id': 'f$i',
          'file_name': 'related_$i.jpg',
          'confidence': i.isEven ? 'medium' : 'weak',
          'reasons': [
            {
              'code': 'shared_filename_token',
              'label': 'shared filename token',
              'weight': 0.5,
            },
          ],
        },
      );
      await _pump(
        tester,
        msg: _relatedMsg(results: many),
        viewport: const Size(900, 700),
      );
      expect(tester.takeException(), isNull);
    });
  });

  group('RelatedFilesCard — source guards', () {
    test('chat_models.dart exposes kRelatedFiles', () {
      expect(ChatMessage.kRelatedFiles, equals('related_files'));
    });

    test('main.dart parser handles related_files type', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'related_files'"));
    });

    test('chat_bubble.dart routes kRelatedFiles to RelatedFilesCard',
        () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('ChatMessage.kRelatedFiles'));
      expect(src, contains('RelatedFilesCard'));
    });
  });
}
