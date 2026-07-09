

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
    'I found ${files.length} files.',
    kind: ChatMessage.kVaultFileList,
    payload: {
      'title':       'Files',
      'count':       files.length,
      'total_count': files.length,
      'files':       files,
    },
  );
}

ChatMessage _credentialSearch(List<Map<String, dynamic>> files) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kCredentialFiles,
    payload: {
      'count': files.length,
      'files': files,
    },
  );
}

ChatMessage _fileSearchResults(List<Map<String, dynamic>> files) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kFileSearchResults,
    payload: {
      'query':         'tax',
      'count':         files.length,
      'pending_count': 0,
      'results': files.map((f) => {
            ...f,
            'match_type':       'entity',
            'match_reason':     'matched entity: Wells Fargo',
            'match_confidence': 'strong',
          }).toList(),
    },
  );
}

ChatMessage _inventoryWithRecent(List<Map<String, dynamic>> files) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kVaultInventory,
    payload: {
      'total_files':  files.length,
      'total_bytes':  1024,
      'folder_count': 1,
      'top_folders':  const [],
      'type_counts':  const {'PDFs': 1},
      'recent_files': files,
    },
  );
}

ChatMessage _relatedGraph(
  Map<String, dynamic> anchor,
  List<Map<String, dynamic>> rels,
) {
  return ChatMessage(
    'assistant',
    rels.isEmpty ? "I don't see strong related files yet." : '',
    kind: ChatMessage.kRelatedFilesGraph,
    payload: {
      'anchor':        anchor,
      'count':         rels.length,
      'relationships': rels,
    },
  );
}


Future<Map<String, dynamic>?> _neverResolves(String _) {
  
  return Future<Map<String, dynamic>?>(() async {
    await Future<void>.delayed(const Duration(days: 365));
    return null;
  });
}

void main() {
  
  
  group('VaultFileListCard — inline Show related', () {
    testWidgets('renders button per row when fetcher + file_id present',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([
            _rowFile(fileId: 'a'),
            _rowFile(fileId: 'b', fileName: 'b.pdf', savedName: 'Bee'),
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsNWidgets(2));
    });

    testWidgets('button hidden per-row when file_id missing',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([
            _rowFile(fileId: 'a'),
            _rowFile(fileId: null, fileName: 'no-id.pdf', savedName: 'No id'),
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsOneWidget);
    });

    testWidgets('button hidden everywhere when fetcher null',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([
            _rowFile(fileId: 'a'),
            _rowFile(fileId: 'b', fileName: 'b.pdf', savedName: 'Bee'),
          ]),
        ),
      );
      expect(find.byTooltip('Show related'), findsNothing);
    });

    testWidgets('Open icon still routes to onOpen — not Show related',
        (tester) async {
      String? openFid;
      String? fetcherFid;
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([_rowFile(fileId: 'aaa')]),
          onOpen: (m) => openFid = m.fileId,
          onLoadRelated: (id) async {
            fetcherFid = id;
            return null;
          },
        ),
      );
      await tester.tap(find.byIcon(Icons.open_in_new).first);
      await tester.pumpAndSettle();
      expect(openFid, 'aaa');
      
      expect(fetcherFid, isNull);
    });
  });

  
  group('VaultInventoryCard — recent-file inline Show related', () {
    testWidgets('renders button per recent row', (tester) async {
      await _pump(
        tester,
        VaultInventoryCard(
          msg: _inventoryWithRecent([
            _rowFile(fileId: 'r-1'),
            _rowFile(fileId: 'r-2', fileName: '2.pdf', savedName: 'Two'),
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsNWidgets(2));
    });

    testWidgets('button hidden when recent row lacks file_id',
        (tester) async {
      await _pump(
        tester,
        VaultInventoryCard(
          msg: _inventoryWithRecent([
            _rowFile(fileId: 'r-1'),
            _rowFile(fileId: '', fileName: 'empty.pdf', savedName: 'E'),
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsOneWidget);
    });
  });

  
  group('CredentialFileSearchCard — inline Show related', () {
    testWidgets('renders button per verified row', (tester) async {
      
      
      await _pump(
        tester,
        CredentialFileSearchCard(
          msg: _credentialSearch([
            _rowFile(
              fileId: 'c-1',
              extra: const {
                'record_count': 5,
                'evidence_source': 'file_text',
                'evidence_source_label': 'file text',
                'password_present': true,
              },
            ),
            _rowFile(
              fileId: 'c-2',
              fileName: 'c2.pdf', savedName: 'C2',
              extra: const {
                'record_count': 3,
                'evidence_source': 'ocr',
                'evidence_source_label': 'OCR',
                'password_present': true,
              },
            ),
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsNWidgets(2));
    });

    testWidgets('hidden when file_id missing', (tester) async {
      await _pump(
        tester,
        CredentialFileSearchCard(
          msg: _credentialSearch([
            _rowFile(
              fileId: null,
              extra: const {
                'record_count': 2,
                'evidence_source': 'file_text',
                'evidence_source_label': 'file text',
                'password_present': true,
              },
            ),
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsNothing);
    });
  });

  
  group('FileSearchResultsCard — inline Show related', () {
    testWidgets('renders button per result row', (tester) async {
      await _pump(
        tester,
        FileSearchResultsCard(
          msg: _fileSearchResults([
            _rowFile(fileId: 's-1'),
            _rowFile(fileId: 's-2', fileName: '2.pdf', savedName: 'Two'),
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsNWidgets(2));
    });

    testWidgets('hidden when file_id missing', (tester) async {
      await _pump(
        tester,
        FileSearchResultsCard(
          msg: _fileSearchResults([
            _rowFile(fileId: 's-1'),
            _rowFile(fileId: null, fileName: '2.pdf', savedName: 'Two'),
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsOneWidget);
    });
  });

  
  group('RelatedFilesGraphCard — chaining Show related', () {
    Map<String, dynamic> anchor() => const {
          'file_id':       'anchor-A',
          'file_name':     'maureen_id_front.jpg',
          'saved_name':    'Maureen ID — Front',
          'relative_path': '/Family/IDs',
          'mime_type':     'image/jpeg',
          'asset_type':    'image',
        };

    List<Map<String, dynamic>> twoRels() => [
          {
            'file': _rowFile(
              fileId: 'rel-1',
              fileName: 'maureen_id_back.jpg',
              savedName: 'Maureen ID — Back',
              mimeType: 'image/jpeg',
              relativePath: '/Family/IDs',
            ),
            'relationship_type': 'front_back_pair',
            'confidence':        0.92,
            'confidence_label':  'strong',
            'reasons':           const ['front-back pattern'],
            'evidence':          const {},
          },
          {
            'file': _rowFile(
              fileId: 'rel-2',
              fileName: 'application_form.pdf',
              savedName: 'Application',
              mimeType: 'application/pdf',
              relativePath: '/Applications',
            ),
            'relationship_type': 'supporting_document',
            'confidence':        0.7,
            'confidence_label':  'medium',
            'reasons':           const ['supporting identity document'],
            'evidence':          const {},
          },
        ];

    testWidgets('renders inline Show related on each related row',
        (tester) async {
      await _pump(
        tester,
        RelatedFilesGraphCard(
          msg: _relatedGraph(anchor(), twoRels()),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsNWidgets(2));
    });

    testWidgets('button hidden per-row when related file lacks file_id',
        (tester) async {
      final rels = twoRels();
      (rels[0]['file'] as Map)['file_id'] = null;
      await _pump(
        tester,
        RelatedFilesGraphCard(
          msg: _relatedGraph(anchor(), rels),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(find.byTooltip('Show related'), findsOneWidget);
    });
  });

  
  group('overflow guards — 100 rows render cleanly', () {
    testWidgets('VaultFileListCard 100 rows', (tester) async {
      final rows = List<Map<String, dynamic>>.generate(
        100, (i) => _rowFile(fileId: 'f$i', fileName: 'f$i.pdf'),
      );
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList(rows),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('FileSearchResultsCard 100 rows', (tester) async {
      final rows = List<Map<String, dynamic>>.generate(
        100, (i) => _rowFile(fileId: 's$i', fileName: 's$i.pdf'),
      );
      await _pump(
        tester,
        FileSearchResultsCard(
          msg: _fileSearchResults(rows),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('CredentialFileSearchCard 25 rows (its maxRows)',
        (tester) async {
      final rows = List<Map<String, dynamic>>.generate(
        25,
        (i) => _rowFile(
          fileId: 'c$i',
          fileName: 'c$i.pdf',
          extra: const {'reasons': ['x'], 'confidence': 'weak'},
        ),
      );
      await _pump(
        tester,
        CredentialFileSearchCard(
          msg: _credentialSearch(rows),
          onLoadRelated: _neverResolves,
        ),
      );
      expect(tester.takeException(), isNull);
    });
  });

  
  group('list cards — security guards', () {
    const sentinels = [
      'plaintext-summary-leak',
      'plaintext-content-leak',
      'hunter2',
      'SUPERSECRET-XYZ-123',
    ];

    Map<String, dynamic> hostile(String fid) => _rowFile(
          fileId: fid,
          extra: const {
            'summary':         'plaintext-summary-leak',
            'safe_preview':    'plaintext-summary-leak',
            'extracted_text':  'plaintext-content-leak',
            'password':        'hunter2',
            'token':           'SUPERSECRET-XYZ-123',
          },
        );

    testWidgets('VaultFileListCard ignores hostile payload',
        (tester) async {
      await _pump(
        tester,
        VaultFileListCard(
          msg: _vaultFileList([hostile('h-1')]),
          onLoadRelated: _neverResolves,
        ),
      );
      for (final s in sentinels) {
        expect(find.textContaining(s), findsNothing,
            reason: 'must not leak $s');
      }
    });

    testWidgets('FileSearchResultsCard ignores hostile payload',
        (tester) async {
      await _pump(
        tester,
        FileSearchResultsCard(
          msg: _fileSearchResults([hostile('h-1')]),
          onLoadRelated: _neverResolves,
        ),
      );
      for (final s in sentinels) {
        expect(find.textContaining(s), findsNothing,
            reason: 'must not leak $s');
      }
    });

    testWidgets('CredentialFileSearchCard ignores hostile payload',
        (tester) async {
      await _pump(
        tester,
        CredentialFileSearchCard(
          msg: _credentialSearch([
            {
              ...hostile('h-1'),
              'reasons':    const ['legit reason'],
              'confidence': 'strong',
            },
          ]),
          onLoadRelated: _neverResolves,
        ),
      );
      for (final s in sentinels) {
        expect(find.textContaining(s), findsNothing,
            reason: 'must not leak $s');
      }
    });
  });

  
  group('Source guards', () {
    test('chat_bubble.dart plumbs onLoadRelated through to every '
        'list card', () async {
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
        expect(ctorIdx, greaterThanOrEqualTo(0),
            reason: 'expected ctor $card( in chat_bubble.dart');
        final end = src.indexOf(');', ctorIdx);
        expect(end, greaterThan(ctorIdx));
        final ctor = src.substring(ctorIdx, end);
        expect(ctor, contains('onLoadRelated:'),
            reason: 'chat_bubble must pass onLoadRelated to $card');
      }
    });

    test('every list card class declares onLoadRelated parameter',
        () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      for (final card in [
        'class VaultFileListCard extends StatefulWidget',
        'class VaultInventoryCard extends StatefulWidget',
        'class CredentialFileSearchCard extends StatefulWidget',
        'class FileSearchResultsCard extends StatefulWidget',
        'class RelatedFilesGraphCard extends StatefulWidget',
      ]) {
        final idx = src.indexOf(card);
        expect(idx, greaterThanOrEqualTo(0),
            reason: 'expected $card in chat_cards.dart (each list '
                'card must now be StatefulWidget for inline '
                'expand-in-place state)');
        final ctorEnd = src.indexOf('});', idx);
        expect(ctorEnd, greaterThan(idx));
        final body = src.substring(idx, ctorEnd);
        expect(body, contains('onLoadRelated'),
            reason: 'card $card must declare an onLoadRelated '
                'parameter');
      }
    });

    test('VaultFileCard still uses onShowRelated (chat-append, '
        'NOT inline)', () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      final idx = src.indexOf('class VaultFileCard extends StatelessWidget');
      expect(idx, greaterThanOrEqualTo(0),
          reason:
              'VaultFileCard must remain a StatelessWidget; the '
              'inline expand-in-place pattern applies ONLY to '
              'list cards');
      final next = src.indexOf('class _', idx + 1);
      final classBody = src.substring(idx, next > 0 ? next : src.length);
      expect(classBody, contains('onShowRelated'),
          reason:
              'VaultFileCard keeps its chat-append onShowRelated '
              'callback');
      
      
      expect(classBody, contains('void Function(String fileId)? onShowRelated'),
          reason: 'VaultFileCard.onShowRelated must remain void');
    });
  });
}
