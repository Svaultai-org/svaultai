

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
  Size viewport = const Size(900, 1400),
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
  String fileId = 'parent-A',
  String fileName = 'tax.pdf',
  String savedName = 'Tax',
  String mimeType = 'application/pdf',
  String relativePath = '/Tax/2024',
}) {
  return {
    'file_id':       fileId,
    'file_name':     fileName,
    'saved_name':    savedName,
    'mime_type':     mimeType,
    'relative_path': relativePath,
    'asset_type':    'file',
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

Map<String, dynamic> _rel(int i) => {
      'file': {
        'file_id':       'rel-$i',
        'file_name':     'r$i.pdf',
        'saved_name':    'Rel $i',
        'relative_path': '/Rel',
        'mime_type':     'application/pdf',
        'asset_type':    'file',
      },
      'relationship_type': 'same_person',
      'confidence':        0.8,
      'confidence_label':  'strong',
      'reasons':           const ['shared person'],
      'evidence':          const <String, dynamic>{},
    };

Map<String, dynamic> _envelope({
  required String anchorFileId,
  required int relationshipCount,
}) {
  return {
    'type':   'related_files_graph',
    'anchor': {
      'file_id':       anchorFileId,
      'file_name':     'parent.pdf',
      'saved_name':    'Parent',
      'relative_path': '/Parent',
      'mime_type':     'application/pdf',
      'asset_type':    'file',
    },
    'count':         relationshipCount,
    'message':       '',
    'relationships':
        List<Map<String, dynamic>>.generate(relationshipCount, _rel),
  };
}

void main() {
  group('inline "+N more" promotion — visibility', () {
    testWidgets('hidden when relationships <= inline cap (6)',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile()]),
          onLoadRelated: (_) async =>
              _envelope(anchorFileId: 'parent-A', relationshipCount: 6),
          onShowRelated: (_) {},
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      
      expect(find.textContaining('more'), findsNothing);
      expect(find.text('View full graph'), findsNothing);
    });

    testWidgets('shows "View full graph" link when count > cap '
        'AND onShowRelated wired', (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile()]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'parent-A', relationshipCount: 10,
          ),
          onShowRelated: (_) {},
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      
      expect(find.textContaining('+4 more'), findsOneWidget);
      expect(find.text('View full graph'), findsOneWidget);
    });

    testWidgets('falls back to static caption when onShowRelated null',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile()]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'parent-A', relationshipCount: 10,
          ),
          
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      
      expect(
        find.text('+4 more — open the file to see the full graph.'),
        findsOneWidget,
      );
      expect(find.text('View full graph'), findsNothing);
    });
  });

  group('inline "+N more" promotion — tap routing', () {
    
    
    Future<void> scrollFooterIntoView(WidgetTester tester) async {
      await tester.ensureVisible(find.text('View full graph'));
      await tester.pumpAndSettle();
    }

    testWidgets('tap fires onShowRelated with EXACT parent row file_id '
        '(not filename, not a related file_id)', (tester) async {
      String? captured;
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([
            _rowFile(fileId: 'parent-PINNED', fileName: 'tax.pdf'),
          ]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'parent-PINNED', relationshipCount: 10,
          ),
          onShowRelated: (id) => captured = id,
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      await scrollFooterIntoView(tester);
      await tester.tap(find.text('View full graph'));
      await tester.pumpAndSettle();
      
      
      expect(captured, 'parent-PINNED');
      expect(captured, isNot('tax.pdf'));
      expect(captured, isNot(startsWith('rel-')));
    });

    testWidgets('tap does NOT trigger onOpen on the parent row',
        (tester) async {
      ChatMessage? openCaptured;
      String? promoteCaptured;
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([
            _rowFile(fileId: 'parent-A'),
          ]),
          onOpen: (m) => openCaptured = m,
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'parent-A', relationshipCount: 10,
          ),
          onShowRelated: (id) => promoteCaptured = id,
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      await scrollFooterIntoView(tester);
      await tester.tap(find.text('View full graph'));
      await tester.pumpAndSettle();
      expect(promoteCaptured, 'parent-A');
      
      expect(openCaptured, isNull);
    });

    testWidgets('tap does NOT call onLoadRelated a second time',
        (tester) async {
      var fetchCount = 0;
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile()]),
          onLoadRelated: (_) async {
            fetchCount += 1;
            return _envelope(
              anchorFileId: 'parent-A', relationshipCount: 10,
            );
          },
          onShowRelated: (_) {},
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(fetchCount, 1);
      await scrollFooterIntoView(tester);
      await tester.tap(find.text('View full graph'));
      await tester.pumpAndSettle();
      
      
      expect(fetchCount, 1);
    });
  });

  group('inline "+N more" promotion — overflow + safety', () {
    testWidgets('mobile-width viewport renders cleanly with footer',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile()]),
          onLoadRelated: (_) async => _envelope(
            anchorFileId: 'parent-A', relationshipCount: 10,
          ),
          onShowRelated: (_) {},
        ),
        viewport: const Size(400, 700),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('View full graph'), findsOneWidget);
    });

    testWidgets('hostile envelope keys NEVER surface in the footer area',
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
          msg: _vaultFileList([_rowFile()]),
          onLoadRelated: (_) async => {
            'type':   'related_files_graph',
            'anchor': {
              'file_id':       'parent-A',
              'file_name':     'parent.pdf',
              'saved_name':    'Parent',
              'mime_type':     'application/pdf',
              'summary':         'plaintext-summary-leak',
              'extracted_text':  'plaintext-content-leak',
              'password':        'hunter2',
            },
            'count':         10,
            'message':       'SUPERSECRET-XYZ-123',  
            'relationships': List<Map<String, dynamic>>.generate(
              10,
              (i) => {
                ..._rel(i),
                'file': {
                  ..._rel(i)['file'] as Map<String, dynamic>,
                  'summary':         'plaintext-summary-leak',
                  'extracted_text':  'plaintext-content-leak',
                  'password':        'hunter2',
                },
              },
            ),
          },
          onShowRelated: (_) {},
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      
      expect(find.text('View full graph'), findsOneWidget);
      for (final s in sentinels) {
        expect(find.textContaining(s), findsNothing,
            reason: 'inline section + footer must not leak $s');
      }
    });
  });

  group('inline "+N more" promotion — chat-bubble wiring', () {
    test('chat_bubble.dart passes BOTH onLoadRelated AND '
        'onShowRelated to every list card', () async {
      final src =
          await File('lib/ui/chat/chat_bubble.dart').readAsString();
      for (final card in [
        'VaultFileListCard',
        'VaultInventoryCard',
        'CredentialFileSearchCard',
        'FileSearchResultsCard',
        'RelatedFilesGraphCard',
      ]) {
        final ctorIdx = src.indexOf('$card(');
        expect(ctorIdx, greaterThanOrEqualTo(0));
        final end = src.indexOf(');', ctorIdx);
        final ctor = src.substring(ctorIdx, end);
        expect(ctor, contains('onLoadRelated:'),
            reason: '$card needs onLoadRelated for inline');
        expect(ctor, contains('onShowRelated:'),
            reason: '$card needs onShowRelated for "+N more" '
                'promotion');
      }
    });

    test('full VaultFileCard chat-append onShowRelated wiring is '
        'unchanged', () async {
      
      
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('onShowRelated: _showRelatedFilesForFile'));
    });
  });
}
