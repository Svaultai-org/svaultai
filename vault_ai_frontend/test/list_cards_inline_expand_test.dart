

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

Future<void> _pump(
  WidgetTester tester,
  Widget child, {
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
            child: child,
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Map<String, dynamic> _rowFile({
  String? fileId = 'file-1',
  String fileName = 'doc.pdf',
  String savedName = 'Doc',
  String mimeType = 'application/pdf',
  String relativePath = '/Bank',
  Map<String, dynamic>? extra,
}) {
  return {
    'file_id':       fileId,
    'file_name':     fileName,
    'saved_name':    savedName,
    'mime_type':     mimeType,
    'relative_path': relativePath,
    'asset_type':    'file',
    if (extra != null) ...extra,
  };
}

ChatMessage _vaultFileList(List<Map<String, dynamic>> files) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kVaultFileList,
    payload: {
      'title':       'Files',
      'count':       files.length,
      'total_count': files.length,
      'files':       files,
    },
  );
}

Map<String, dynamic> _envelope({
  required String anchorFileId,
  required List<Map<String, dynamic>> relationships,
  String anchorTitle = 'Doc',
  String message = '',
}) {
  return {
    'type':   'related_files_graph',
    'anchor': {
      'file_id':       anchorFileId,
      'file_name':     'doc.pdf',
      'saved_name':    anchorTitle,
      'relative_path': '/Bank',
      'mime_type':     'application/pdf',
      'asset_type':    'file',
    },
    'count':         relationships.length,
    'message':       message,
    'relationships': relationships,
  };
}

Map<String, dynamic> _rel({
  required String fileId,
  String fileName = 'related.pdf',
  String savedName = 'Related',
  String mimeType = 'application/pdf',
  String relativePath = '/Bank',
  String relationshipType = 'same_person',
  String confidenceLabel = 'strong',
  double confidence = 0.9,
  List<String> reasons = const ['shared person: Maureen'],
}) {
  return {
    'file': {
      'file_id':       fileId,
      'file_name':     fileName,
      'saved_name':    savedName,
      'relative_path': relativePath,
      'mime_type':     mimeType,
      'asset_type':    'file',
    },
    'relationship_type': relationshipType,
    'confidence':        confidence,
    'confidence_label':  confidenceLabel,
    'reasons':           reasons,
    'evidence':          const <String, dynamic>{},
  };
}

void main() {
  
  
  group('inline expand — loading state', () {
    testWidgets(
      'tap fires fetcher with EXACT row file_id (not filename)',
      (tester) async {
        String? capturedFid;
        final c = Completer<Map<String, dynamic>?>();
        await _pump(
          tester,
          VaultFileListCard(
            msg: _vaultFileList([
              _rowFile(
                fileId: 'pinned-id-B',
                fileName: 'tax.pdf', savedName: 'Tax',
              ),
            ]),
            onLoadRelated: (id) {
              capturedFid = id;
              return c.future;
            },
          ),
        );
        await tester.tap(find.byTooltip('Show related'));
        await tester.pump();
        expect(capturedFid, 'pinned-id-B');
        
        expect(capturedFid, isNot('tax.pdf'));
        c.complete(_envelope(
          anchorFileId: 'pinned-id-B', relationships: const [],
        ));
        await tester.pumpAndSettle();
      },
    );

    testWidgets('shows "Loading related files…" strip while in-flight',
        (tester) async {
      final c = Completer<Map<String, dynamic>?>();
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'a')]),
          onLoadRelated: (_) => c.future,
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      
      
      await tester.pump();
      expect(find.text('Loading related files…'), findsOneWidget);
      expect(find.text('Hide related'), findsOneWidget);
      
      c.complete(_envelope(
        anchorFileId: 'a', relationships: const [],
      ));
      await tester.pumpAndSettle();
    });
  });

  
  group('inline expand — success', () {
    testWidgets('renders compact related rows under tapped row',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'a', savedName: 'A')]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'a',
            relationships: [
              _rel(
                fileId: 'rel-1', savedName: 'Other ID',
                reasons: const ['same person: Maureen'],
              ),
            ],
          ),
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(find.text('Related to this file'), findsOneWidget);
      expect(find.text('Other ID'), findsOneWidget);
      expect(
        find.textContaining('same person: Maureen'),
        findsOneWidget,
      );
      expect(find.text('Hide related'), findsOneWidget);
    });

    testWidgets('renders empty-state copy when no relationships',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'a')]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'a', relationships: const [],
          ),
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(
        find.text("I don't see strong related files for this yet."),
        findsOneWidget,
      );
    });

    testWidgets('Open on a related row routes to the related file_id '
        '(not the parent row)', (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'parent-A')]),
          onOpen: (m) => captured = m,
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'parent-A',
            relationships: [_rel(fileId: 'related-B')],
          ),
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      
      
      await tester.tap(find.text('Related'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      
      expect(captured!.fileId, 'related-B');
      expect(captured!.fileId, isNot('parent-A'));
    });
  });

  
  group('inline expand — error', () {
    testWidgets('failed fetcher renders inline error + Retry button',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'a')]),
          onLoadRelated: (_) async {
            throw Exception('boom');
          },
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining("Couldn't load related files"),
        findsOneWidget,
      );
      expect(find.text('Retry'), findsOneWidget);
    });
  });

  
  group('inline expand — collapse', () {
    testWidgets('Hide related removes the expanded section',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'a')]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'a', relationships: const [],
          ),
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(find.text('Related to this file'), findsOneWidget);
      await tester.tap(find.text('Hide related'));
      await tester.pumpAndSettle();
      expect(find.text('Related to this file'), findsNothing);
    });

    testWidgets('tapping inline 🌳 a second time also collapses',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'a')]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'a', relationships: const [],
          ),
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(find.text('Related to this file'), findsOneWidget);
      
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(find.text('Related to this file'), findsNothing);
    });

    testWidgets('only one row expanded at a time — tapping a different '
        'row collapses the prior one', (tester) async {
      
      
      var fetchCount = 0;
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([
            _rowFile(fileId: 'a', savedName: 'AAA'),
            _rowFile(fileId: 'b', fileName: 'b.pdf', savedName: 'BBB'),
          ]),
          onLoadRelated: (_) async {
            fetchCount += 1;
            return _envelope(
              anchorFileId: 'a',
              relationships: [_rel(fileId: 'r-$fetchCount')],
            );
          },
        ),
      );
      
      await tester.tap(find.byTooltip('Show related').at(0));
      await tester.pumpAndSettle();
      expect(find.text('Related'), findsOneWidget);
      
      await tester.tap(find.byTooltip('Show related').at(1));
      await tester.pumpAndSettle();
      
      expect(find.text('Related to this file'), findsOneWidget);
    });
  });

  
  group('inline expand — overflow', () {
    testWidgets('100-row card with one expansion does NOT overflow',
        (tester) async {
      final rows = List<Map<String, dynamic>>.generate(
        100, (i) => _rowFile(fileId: 'f$i', fileName: 'f$i.pdf'),
      );
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList(rows),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'f0',
            relationships: List.generate(
              6, (i) => _rel(fileId: 'r$i', savedName: 'Rel $i'),
            ),
          ),
        ),
      );
      await tester.tap(find.byTooltip('Show related').first);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('mobile-width viewport renders cleanly with one '
        'expansion', (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'a')]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'a',
            relationships: [_rel(fileId: 'r-1')],
          ),
        ),
        viewport: const Size(400, 700),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('Related to this file'), findsOneWidget);
    });
  });

  
  group('inline expand — security guards', () {
    testWidgets(
      'NEVER renders summary / extracted_text / password / token '
      'sentinel values from a hostile envelope',
      (tester) async {
        const sentinels = [
          'plaintext-summary-leak',
          'plaintext-content-leak',
          'hunter2',
          'SUPERSECRET-XYZ-123',
        ];
        await _pump(
          tester,
          VaultFileListCard(
            msg: _vaultFileList([_rowFile(fileId: 'a')]),
            onLoadRelated: (_) async => {
              'type':   'related_files_graph',
              'anchor': {
                'file_id':       'a',
                'file_name':     'a.pdf',
                'saved_name':    'A',
                'mime_type':     'application/pdf',
                
                'summary':         'plaintext-summary-leak',
                'extracted_text':  'plaintext-content-leak',
                'password':        'hunter2',
              },
              'count':         1,
              'message':       '',
              'relationships': [
                {
                  'file': {
                    'file_id':       'r-1',
                    'file_name':     'r.pdf',
                    'saved_name':    'R',
                    'mime_type':     'application/pdf',
                    
                    'summary':         'plaintext-summary-leak',
                    'extracted_text':  'plaintext-content-leak',
                    'token':           'SUPERSECRET-XYZ-123',
                  },
                  'relationship_type': 'same_person',
                  'confidence':        0.9,
                  'confidence_label':  'strong',
                  'reasons':           const ['legit reason'],
                  'evidence':          const {
                    
                    'archive_body':    'plaintext-content-leak',
                    'password':        'hunter2',
                  },
                },
              ],
            },
          ),
        );
        await tester.tap(find.byTooltip('Show related'));
        await tester.pumpAndSettle();
        for (final s in sentinels) {
          expect(
            find.textContaining(s),
            findsNothing,
            reason:
                'inline section must NOT leak sentinel $s — reads '
                'ONLY the closed-set envelope keys',
          );
        }
      },
    );
  });

  
  group('Source guards', () {
    test('main.dart wires onLoadRelated to _fetchRelatedFilesEnvelope',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('onLoadRelated: _fetchRelatedFilesEnvelope'));
    });

    test('_fetchRelatedFilesEnvelope calls fetchRelatedFiles directly '
        '(no LLM / no filename search)', () async {
      final src = await File('lib/main.dart').readAsString();
      final idx = src.indexOf('_fetchRelatedFilesEnvelope');
      expect(idx, greaterThanOrEqualTo(0));
      final body = src.substring(
        idx,
        idx + 2000 < src.length ? idx + 2000 : src.length,
      );
      expect(body, contains('fetchRelatedFiles'),
          reason: 'fetcher must hit the typed API method');
      expect(body, isNot(contains('classify_chat_intent')));
      expect(body, isNot(contains('searchFilesByName')));
    });

    test('VaultFileCard chat-append onShowRelated still wired in main.dart',
        () async {
      final src = await File('lib/main.dart').readAsString();
      
      
      expect(src, contains('onShowRelated: _showRelatedFilesForFile'));
    });
  });
}
