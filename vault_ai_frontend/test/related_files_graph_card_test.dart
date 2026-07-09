

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

ChatMessage _msg({
  required Map<String, dynamic> anchor,
  required List<Map<String, dynamic>> relationships,
  String message = '',
}) {
  final payload = <String, dynamic>{
    'anchor':        anchor,
    'relationships': relationships,
    'count':         relationships.length,
  };
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kRelatedFilesGraph,
    payload: payload,
  );
}

Map<String, dynamic> _anchor({
  String fileId = 'zip-anchor',
  String fileName = 'backup.zip',
  String? savedName = 'Backup',
  String? relativePath = '/Family/Backups',
  String mimeType = 'application/zip',
  String assetType = 'archive',
}) {
  return {
    'file_id':       fileId,
    'file_name':     fileName,
    'saved_name':    savedName,
    'relative_path': relativePath,
    'mime_type':     mimeType,
    'asset_type':    assetType,
  };
}

Map<String, dynamic> _relationship({
  required String fileId,
  required String fileName,
  String? savedName,
  String? relativePath,
  String mimeType = 'application/pdf',
  String assetType = 'file',
  String relationshipType = 'front_back_pair',
  double confidence = 0.92,
  String confidenceLabel = 'strong',
  List<String> reasons = const [
    'filename pattern suggests front/back pair of an ID',
    'same person name: Maureen',
  ],
  Map<String, dynamic> evidence = const {
    'shared_entity_names': ['Maureen'],
  },
}) {
  return {
    'file': {
      'file_id':       fileId,
      'file_name':     fileName,
      if (savedName != null) 'saved_name': savedName,
      if (relativePath != null) 'relative_path': relativePath,
      'mime_type':     mimeType,
      'asset_type':    assetType,
    },
    'relationship_type': relationshipType,
    'confidence':        confidence,
    'confidence_label':  confidenceLabel,
    'reasons':           reasons,
    'evidence':          evidence,
  };
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
            child: RelatedFilesGraphCard(msg: msg, onOpen: onOpen),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('RelatedFilesGraphCard — header + anchor', () {
    testWidgets('renders the title with the anchor saved_name',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(fileId: 'doc-1', fileName: 'a.pdf'),
          ],
        ),
      );
      expect(
        find.text('Related to "Backup"'),
        findsOneWidget,
      );
    });

    testWidgets('falls back to file_name when saved_name absent',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(savedName: null),
          relationships: [
            _relationship(fileId: 'doc-1', fileName: 'a.pdf'),
          ],
        ),
      );
      expect(
        find.text('Related to "backup.zip"'),
        findsOneWidget,
      );
    });

    testWidgets('renders the anchor row with the "Anchor file" caption',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(fileId: 'doc-1', fileName: 'a.pdf'),
          ],
        ),
      );
      
      
      expect(find.text('Backup'), findsWidgets);
      expect(find.text('Anchor file'), findsOneWidget);
      expect(find.text('/Family/Backups'), findsOneWidget);
    });

    testWidgets('shows count subtitle', (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(fileId: 'a', fileName: 'a.pdf'),
            _relationship(fileId: 'b', fileName: 'b.pdf'),
            _relationship(fileId: 'c', fileName: 'c.pdf'),
          ],
        ),
      );
      expect(find.text('3 related'), findsOneWidget);
    });
  });

  group('RelatedFilesGraphCard — related rows', () {
    testWidgets('renders each related row with saved_name override',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(
              fileId: 'doc-1',
              fileName: 'maureen_id_front.jpg',
              savedName: 'Maureen ID — Front',
              relativePath: '/Family/IDs',
            ),
          ],
        ),
      );
      expect(find.text('Maureen ID — Front'), findsOneWidget);
      expect(find.text('/Family/IDs'), findsOneWidget);
    });

    testWidgets('renders confidence badge', (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(
              fileId: 'doc-1', fileName: 'a.pdf',
              confidenceLabel: 'strong',
            ),
          ],
        ),
      );
      expect(find.text('STRONG'), findsOneWidget);
    });

    testWidgets('renders relationship_type chip with spaces',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(
              fileId: 'doc-1', fileName: 'a.pdf',
              relationshipType: 'front_back_pair',
            ),
          ],
        ),
      );
      
      expect(find.text('FRONT BACK PAIR'), findsOneWidget);
    });

    testWidgets('renders the reasons list (capped at 3)',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(
              fileId: 'doc-1', fileName: 'a.pdf',
              reasons: [
                'reason A',
                'reason B',
                'reason C',
                'reason D',
                'reason E',
              ],
            ),
          ],
        ),
      );
      expect(find.text('reason A'), findsOneWidget);
      expect(find.text('reason B'), findsOneWidget);
      expect(find.text('reason C'), findsOneWidget);
      
      expect(find.text('reason D'), findsNothing);
      expect(find.text('reason E'), findsNothing);
    });
  });

  group('RelatedFilesGraphCard — tap to open', () {
    testWidgets(
        'tapping a row fires onOpen with the related file_id (not anchor)',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(
              fileId: 'doc-1',
              fileName: 'maureen_id_back.jpg',
              savedName: 'Maureen ID — Back',
            ),
          ],
        ),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.text('Maureen ID — Back'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      
      expect(captured!.fileId, 'doc-1');
      expect(captured!.kind, ChatMessage.kVaultFile);
    });

    testWidgets('tapping the open icon also fires onOpen', (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(
              fileId: 'doc-1',
              fileName: 'maureen_id_back.jpg',
              savedName: 'Maureen ID — Back',
            ),
          ],
        ),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.byIcon(Icons.open_in_new).first);
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.fileId, 'doc-1');
    });
  });

  group('RelatedFilesGraphCard — empty state', () {
    testWidgets('empty relationships renders the empty-state copy',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: const [],
          message:
              'I don\'t see strong related files for "Backup" yet. '
              'As more files are analyzed, related items may appear.',
        ),
      );
      expect(find.text('No related files'), findsOneWidget);
      expect(
        find.textContaining("don't see strong related files"),
        findsOneWidget,
      );
      expect(
        find.textContaining('related items may appear'),
        findsOneWidget,
      );
      
      expect(find.text('Anchor file'), findsOneWidget);
    });
  });

  group('RelatedFilesGraphCard — overflow guards', () {
    testWidgets('100-row payload renders without overflow', (tester) async {
      final relationships = <Map<String, dynamic>>[];
      for (var i = 0; i < 100; i++) {
        relationships.add(
          _relationship(
            fileId: 'f$i',
            fileName: 'file_$i.pdf',
            savedName: 'File $i',
            relationshipType: i.isEven ? 'same_person' : 'same_folder',
            confidenceLabel: i.isEven ? 'strong' : 'weak',
            reasons: ['reason $i'],
          ),
        );
      }
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: relationships,
        ),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders cleanly on a mobile-width viewport',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          anchor: _anchor(),
          relationships: [
            _relationship(
              fileId: 'doc-1',
              fileName: 'a.pdf',
              relationshipType: 'same_person',
              reasons: const ['same person name: Maureen'],
            ),
          ],
        ),
        
        
        viewport: const Size(400, 740),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Related to "Backup"'), findsOneWidget);
    });
  });

  group('RelatedFilesGraphCard — security guards', () {
    testWidgets(
        'NEVER renders extracted text / summary / preview / password '
        'values even if the backend leaks them in the anchor / rows / '
        'evidence', (tester) async {
      const sentinels = [
        'hunter2',
        'SUPERSECRET-XYZ-123',
        'plaintext-summary-leak',
        'plaintext-preview-leak',
        'plaintext-content-leak',
        'archive-internal-secret',
      ];
      await _pump(
        tester,
        msg: _msg(
          anchor: {
            
            'file_id':       'zip-anchor',
            'file_name':     'backup.zip',
            'saved_name':    'Backup',
            'relative_path': '/Family/Backups',
            'mime_type':     'application/zip',
            'asset_type':    'archive',
            
            'summary':         'plaintext-summary-leak',
            'safe_preview':    'plaintext-preview-leak',
            'extracted_text':  'plaintext-content-leak',
            'password':        'hunter2',
            'token':           'SUPERSECRET-XYZ-123',
          },
          relationships: [
            {
              'file': {
                'file_id':       'doc-1',
                'file_name':     'a.pdf',
                'saved_name':    'A',
                'mime_type':     'application/pdf',
                
                'summary':       'plaintext-summary-leak',
                'extracted_text': 'plaintext-content-leak',
              },
              'relationship_type': 'same_person',
              'confidence':        0.8,
              'confidence_label':  'strong',
              'reasons':           ['same person name: Maureen'],
              'evidence': {
                'shared_entity_names': ['Maureen'],
                
                'archive_body':        'archive-internal-secret',
                'password':            'hunter2',
              },
            },
          ],
        ),
      );
      for (final sentinel in sentinels) {
        expect(
          find.textContaining(sentinel),
          findsNothing,
          reason:
              'the card MUST NOT surface backend-leaked sentinel '
              '$sentinel — the renderer reads only the declared keys',
        );
      }
    });
  });

  group('Source guards', () {
    test('chat_models.dart exposes kRelatedFilesGraph', () {
      expect(
        ChatMessage.kRelatedFilesGraph,
        equals('related_files_graph'),
      );
    });

    test('isCard returns true for kRelatedFilesGraph', () {
      final m = ChatMessage(
        'assistant',
        'x',
        kind: ChatMessage.kRelatedFilesGraph,
        payload: const <String, dynamic>{},
      );
      expect(m.isCard, isTrue);
    });

    test('main.dart parser handles related_files_graph type',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'related_files_graph'"));
      expect(
        src,
        contains("kind: 'related_files_graph'"),
        reason:
            'parser must produce a kRelatedFilesGraph ChatMessage',
      );
    });

    test('main.dart parser still has the legacy related_files branch',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'related_files'"));
    });

    test('chat_bubble.dart routes kRelatedFilesGraph to RelatedFilesGraphCard',
        () async {
      final src =
          await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('ChatMessage.kRelatedFilesGraph'));
      expect(src, contains('RelatedFilesGraphCard'));
    });
  });
}
