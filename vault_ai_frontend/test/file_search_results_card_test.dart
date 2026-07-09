

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

ChatMessage _msg({
  required List<Map<String, dynamic>> results,
  String query = 'Wells Fargo',
  String message = 'I found 1 file about "Wells Fargo".',
  int? pendingCount,
  bool isComplete = true,
  String? queryKind,
  String? requestedPersonName,
}) {
  final payload = <String, dynamic>{
    'results': results,
    'query': query,
    if (requestedPersonName != null)
      'requested_person_name': requestedPersonName,
    'count': results.length,
    'is_complete': isComplete,
    if (queryKind != null) 'query_kind': queryKind,
    if (pendingCount != null) 'pending_count': pendingCount,
  };
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kFileSearchResults,
    payload: payload,
  );
}

List<Map<String, dynamic>> _twoMixedResults() {
  return [
    {
      'file_id': 'wf',
      'file_name': 'january_statement.pdf',
      'saved_name': 'January Statement',
      'mime_type': 'application/pdf',
      'asset_type': 'file',
      'match_type': 'entity',
      'match_reason': 'entity match: Wells Fargo',
      'match_confidence': 'strong',
      'purpose': 'generic_text',
      'purpose_label': null,
      'relative_path': 'Finance/Banking/january_statement.pdf',
    },
    {
      'file_id': 'fn_only',
      'file_name': 'wells-cathedral-photo.jpg',
      'saved_name': 'Wells Cathedral',
      'mime_type': 'image/jpeg',
      'asset_type': 'file',
      'match_type': 'filename',
      'match_reason': 'filename match: wells-cathedral-photo.jpg',
      'match_confidence': 'weak',
      'purpose': null,
      'purpose_label': null,
    },
  ];
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
            child: FileSearchResultsCard(msg: msg, onOpen: onOpen),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('FileSearchResultsCard — header', () {
    testWidgets('renders the title with the user query', (tester) async {
      await _pump(
        tester,
        msg: _msg(results: _twoMixedResults(), query: 'Wells Fargo'),
      );
      expect(
        find.text('Search results for "Wells Fargo"'),
        findsOneWidget,
      );
    });

    testWidgets('shows match count subtitle', (tester) async {
      await _pump(tester, msg: _msg(results: _twoMixedResults()));
      expect(find.text('2 matches'), findsOneWidget);
    });

    testWidgets('singular subtitle for one match', (tester) async {
      await _pump(
        tester,
        msg: _msg(results: [_twoMixedResults().first]),
      );
      expect(find.text('1 match'), findsOneWidget);
    });

    testWidgets('falls back to generic title when query is empty',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: _twoMixedResults(), query: ''),
      );
      expect(find.text('Search results'), findsOneWidget);
    });
  });

  group('FileSearchResultsCard — rows', () {
    testWidgets('renders each result row with saved_name', (tester) async {
      await _pump(tester, msg: _msg(results: _twoMixedResults()));
      expect(find.text('January Statement'), findsOneWidget);
      expect(find.text('Wells Cathedral'), findsOneWidget);
    });

    testWidgets('falls back to file_name when saved_name absent',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: [
          {
            'file_id': 'a',
            'file_name': 'raw.pdf',
            'saved_name': '',
            'mime_type': 'application/pdf',
            'match_type': 'entity',
            'match_reason': 'entity match: X',
            'match_confidence': 'strong',
          },
        ]),
      );
      expect(find.text('raw.pdf'), findsOneWidget);
    });

    testWidgets('renders confidence badges per row', (tester) async {
      await _pump(tester, msg: _msg(results: _twoMixedResults()));
      expect(find.text('STRONG'), findsOneWidget);
      expect(find.text('WEAK'), findsOneWidget);
    });

    testWidgets('renders match_type chip', (tester) async {
      await _pump(tester, msg: _msg(results: _twoMixedResults()));
      expect(find.text('ENTITY'), findsOneWidget);
      expect(find.text('FILENAME'), findsOneWidget);
    });

    testWidgets('renders match_reason caption', (tester) async {
      await _pump(tester, msg: _msg(results: _twoMixedResults()));
      expect(
        find.text('entity match: Wells Fargo'),
        findsOneWidget,
      );
    });

    testWidgets('renders purpose_label when present', (tester) async {
      await _pump(
        tester,
        msg: _msg(results: [
          {
            'file_id': 'logins',
            'file_name': 'my_notes.txt',
            'saved_name': 'My Notes',
            'mime_type': 'text/plain',
            'match_type': 'purpose',
            'match_reason': 'purpose match: saved website/app login records',
            'match_confidence': 'strong',
            'purpose': 'saved_login_list',
            'purpose_label': 'saved website/app login records',
          },
        ]),
      );
      expect(
        find.text('saved website/app login records'),
        findsOneWidget,
      );
    });

    testWidgets('renders folder path when relative_path present',
        (tester) async {
      await _pump(tester, msg: _msg(results: _twoMixedResults()));
      expect(
        find.text('Finance/Banking/january_statement.pdf'),
        findsOneWidget,
      );
    });

    testWidgets('omits purpose_label line when null', (tester) async {
      await _pump(
        tester,
        msg: _msg(results: [
          {
            'file_id': 'wf',
            'file_name': 'statement.pdf',
            'saved_name': 'January Statement',
            'mime_type': 'application/pdf',
            'match_type': 'entity',
            'match_reason': 'entity match: Wells Fargo',
            'match_confidence': 'strong',
            'purpose_label': null,
          },
        ]),
      );
      
      expect(find.byIcon(Icons.assignment_outlined), findsNothing);
    });
  });

  group('FileSearchResultsCard — tap to open', () {
    testWidgets('tapping a row fires onOpen with the file_id',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(results: [_twoMixedResults().first]),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.text('January Statement'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.fileId, 'wf');
      expect(captured!.kind, ChatMessage.kVaultFile);
    });

    testWidgets('tapping the open icon also fires onOpen', (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(results: [_twoMixedResults().first]),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.byIcon(Icons.open_in_new).first);
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.fileId, 'wf');
    });
  });

  group('FileSearchResultsCard — pending strip', () {
    testWidgets('shows pending strip when pending_count > 0',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: _twoMixedResults(), pendingCount: 3),
      );
      expect(
        find.textContaining('3 files still being analyzed'),
        findsOneWidget,
      );
    });

    testWidgets('singular phrasing for one pending file', (tester) async {
      await _pump(
        tester,
        msg: _msg(results: _twoMixedResults(), pendingCount: 1),
      );
      expect(
        find.textContaining('1 file still being analyzed'),
        findsOneWidget,
      );
    });

    testWidgets('no pending strip when pending_count is 0',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: _twoMixedResults(), pendingCount: 0),
      );
      expect(find.byIcon(Icons.hourglass_empty), findsNothing);
    });
  });

  group('FileSearchResultsCard — empty state', () {
    testWidgets(
      'empty results on a completed search renders '
      '"No matches found" — never "No matches yet"',
      (tester) async {
        await _pump(
          tester,
          msg: _msg(
            results: const [],
            message: 'I didn\'t find any files about "ghost".',
            query: 'ghost',
          ),
        );
        
        
        expect(find.text('Search results for "ghost"'), findsOneWidget);
        expect(find.text('No matches found'), findsOneWidget);
        expect(find.text('No matches yet'), findsNothing);
        expect(
          find.textContaining('didn\'t find any files'),
          findsOneWidget,
        );
      },
    );

    testWidgets('empty results + pending shows the strip too',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: const [], pendingCount: 5, query: 'x'),
      );
      expect(
        find.textContaining('5 files still being analyzed'),
        findsOneWidget,
      );
    });

    testWidgets(
      'empty results on an INCOMPLETE search renders '
      '"Search incomplete" subtitle',
      (tester) async {
        
        
        await _pump(
          tester,
          msg: _msg(
            results: const [],
            isComplete: false,
            query: 'ghost',
            message: 'Search incomplete. I checked what I could.',
          ),
        );
        expect(find.text('Search incomplete'), findsOneWidget);
        expect(find.text('No matches found'), findsNothing);
        expect(find.text('No matches yet'), findsNothing);
      },
    );

    testWidgets(
      'ID-photo strict-mode empty + completed search renders '
      '"ID photo results" / "No matches found"',
      (tester) async {
        await _pump(
          tester,
          msg: _msg(
            results: const [],
            isComplete: true,
            queryKind: 'id_photo_visual',
            query: 'find me an ID photo for Bob Smith',
            message:
                'I found ID documents in your vault, but none '
                'matched Bob Smith.',
          ),
        );
        expect(find.text('ID photo results'), findsOneWidget);
        expect(find.text('No matches found'), findsOneWidget);
        expect(find.text('No matches yet'), findsNothing);
        expect(
          find.textContaining('none matched Bob Smith'),
          findsOneWidget,
        );
      },
    );

    
    testWidgets(
      'stale "I\'m still analyzing your vault" body is sanitized '
      'to the strict empty-state copy when complete=true + count=0',
      (tester) async {
        await _pump(
          tester,
          msg: _msg(
            results: const [],
            isComplete: true,
            queryKind: 'id_photo_visual',
            query: 'find me an ID photo for Bob Smith',
            requestedPersonName: 'Bob Smith',
            message:
                "I'm still analyzing your vault. Ask again in a "
                "moment and I'll have more to show you.",
          ),
        );
        
        expect(find.textContaining('still analyzing'), findsNothing);
        expect(find.textContaining('Ask again'), findsNothing);
        expect(find.textContaining('in a moment'), findsNothing);
        
        expect(
          find.textContaining("I couldn't find an ID photo for Bob Smith"),
          findsOneWidget,
        );
        expect(find.text('No matches found'), findsOneWidget);
      },
    );

    testWidgets(
      'stale "No matches yet" body is sanitized + subtitle is '
      '"No matches found" on a completed search',
      (tester) async {
        await _pump(
          tester,
          msg: _msg(
            results: const [],
            isComplete: true,
            queryKind: 'id_photo_visual',
            query: 'show me all ID photos',
            message: 'No matches yet — still working on it.',
          ),
        );
        expect(find.textContaining('No matches yet'), findsNothing);
        expect(find.text('No matches found'), findsOneWidget);
        expect(
          find.textContaining('No matching ID photo found'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'stale hedge body on an INCOMPLETE search gets replaced '
      'with "Search incomplete" copy',
      (tester) async {
        await _pump(
          tester,
          msg: _msg(
            results: const [],
            isComplete: false,
            queryKind: 'id_photo_visual',
            query: 'show me all ID photos',
            message:
                "I'm still analyzing your vault. Ask again in a "
                "moment.",
          ),
        );
        expect(find.textContaining('still analyzing'), findsNothing);
        expect(find.textContaining('Ask again'), findsNothing);
        expect(find.text('Search incomplete'), findsOneWidget);
        expect(
          find.textContaining(
            'Search incomplete. I checked what I could, but the '
            'search hit its limit.',
          ),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'a clean message body passes through the sanitizer untouched',
      (tester) async {
        await _pump(
          tester,
          msg: _msg(
            results: const [],
            isComplete: true,
            queryKind: 'id_photo_visual',
            query: 'find me an ID photo for Bob Smith',
            requestedPersonName: 'Bob Smith',
            message:
                'I found ID documents in your vault, but none '
                'matched Bob Smith.',
          ),
        );
        
        
        expect(
          find.textContaining('none matched Bob Smith'),
          findsOneWidget,
        );
      },
    );
  });

  group('FileSearchResultsCard — overflow guards', () {
    testWidgets('100-row payload renders without overflow', (tester) async {
      final results = <Map<String, dynamic>>[];
      for (var i = 0; i < 100; i++) {
        results.add({
          'file_id': 'f$i',
          'file_name': 'file_$i.pdf',
          'saved_name': 'File $i',
          'mime_type': 'application/pdf',
          'match_type': 'entity',
          'match_reason': 'entity match: X',
          'match_confidence': 'strong',
        });
      }
      await _pump(
        tester,
        msg: _msg(results: results, query: 'X'),
        viewport: const Size(900, 800),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders cleanly on a mobile-width viewport',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: _twoMixedResults()),
        viewport: const Size(360, 740),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Search results for "Wells Fargo"'), findsOneWidget);
    });
  });

  group('FileSearchResultsCard — security guards', () {
    testWidgets(
        'NEVER renders extracted text / summary / preview / password '
        'values even if the backend leaks them',
        (tester) async {
      const sentinels = [
        'hunter2',
        'SUPERSECRET-XYZ-123',
        'plaintext-summary-leak',
        'plaintext-preview-leak',
        'plaintext-content-leak',
      ];
      await _pump(
        tester,
        msg: _msg(results: [
          {
            'file_id': 'wf',
            'file_name': 'statement.pdf',
            'saved_name': 'January Statement',
            'mime_type': 'application/pdf',
            'match_type': 'entity',
            'match_reason': 'entity match: Wells Fargo',
            'match_confidence': 'strong',
            
            
            'summary': 'plaintext-summary-leak',
            'safe_preview': 'plaintext-preview-leak',
            'extracted_text': 'plaintext-content-leak',
            'password': 'hunter2',
            'token': 'SUPERSECRET-XYZ-123',
          },
        ]),
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

  
  group('FileSearchResultsCard — archive-content chip', () {
    Map<String, dynamic> archiveRow({
      bool isArchiveMatch = true,
      String matchType = 'entity',
      String matchReason =
          'archive content match: notes.md mentions Wells Fargo',
    }) {
      return {
        'file_id': 'zip-1',
        'file_name': 'backup.zip',
        'saved_name': 'Backup',
        'mime_type': 'application/zip',
        'asset_type': 'archive',
        'match_type': matchType,
        'match_reason': matchReason,
        'match_confidence': 'strong',
        'is_archive_match': isArchiveMatch,
      };
    }

    testWidgets('renders ARCHIVE CONTENT chip when is_archive_match=true',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: [archiveRow()], query: 'Wells Fargo'),
      );
      expect(find.text('ARCHIVE CONTENT'), findsOneWidget);
    });

    testWidgets(
        'renders the regular match_type chip ALONGSIDE the archive chip',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: [archiveRow()], query: 'Wells Fargo'),
      );
      
      
      expect(find.text('ARCHIVE CONTENT'), findsOneWidget);
      expect(find.text('ENTITY'), findsOneWidget);
    });

    testWidgets(
        'omits the chip when is_archive_match is missing', (tester) async {
      final row = archiveRow();
      row.remove('is_archive_match');
      await _pump(
        tester,
        msg: _msg(results: [row], query: 'Wells Fargo'),
      );
      expect(find.text('ARCHIVE CONTENT'), findsNothing);
      
      expect(find.text('ENTITY'), findsOneWidget);
    });

    testWidgets(
        'omits the chip when is_archive_match=false', (tester) async {
      await _pump(
        tester,
        msg: _msg(
          results: [archiveRow(isArchiveMatch: false)],
          query: 'Wells Fargo',
        ),
      );
      expect(find.text('ARCHIVE CONTENT'), findsNothing);
    });

    testWidgets(
        'omits the chip when is_archive_match is a wrong-typed value',
        (tester) async {
      
      
      await _pump(
        tester,
        msg: _msg(
          results: [
            {
              'file_id': 'a',
              'file_name': 'doc.pdf',
              'saved_name': 'Doc',
              'mime_type': 'application/pdf',
              'match_type': 'entity',
              'match_reason': 'entity match: Wells Fargo',
              'match_confidence': 'strong',
              'is_archive_match': 'true',  
            },
            {
              'file_id': 'b',
              'file_name': 'other.pdf',
              'saved_name': 'Other',
              'mime_type': 'application/pdf',
              'match_type': 'entity',
              'match_reason': 'entity match: Wells Fargo',
              'match_confidence': 'strong',
              'is_archive_match': 1,  
            },
          ],
          query: 'Wells Fargo',
        ),
      );
      expect(find.text('ARCHIVE CONTENT'), findsNothing);
    });

    testWidgets(
        'archive-aware match_reason still renders alongside the chip',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(results: [archiveRow()], query: 'Wells Fargo'),
      );
      expect(
        find.text(
          'archive content match: notes.md mentions Wells Fargo',
        ),
        findsOneWidget,
      );
    });

    testWidgets(
        'tapping an archive row opens the PARENT archive file_id',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(results: [archiveRow()], query: 'Wells Fargo'),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.text('Backup'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      
      
      expect(captured!.fileId, 'zip-1');
      expect(captured!.kind, ChatMessage.kVaultFile);
    });

    testWidgets(
        '100 archive rows with is_archive_match=true render without overflow',
        (tester) async {
      final results = <Map<String, dynamic>>[];
      for (var i = 0; i < 100; i++) {
        results.add({
          'file_id': 'zip-$i',
          'file_name': 'backup_$i.zip',
          'saved_name': 'Backup $i',
          'mime_type': 'application/zip',
          'asset_type': 'archive',
          'match_type': 'entity',
          'match_reason':
              'archive content match: notes.md mentions Wells Fargo',
          'match_confidence': 'strong',
          'is_archive_match': true,
        });
      }
      await _pump(
        tester,
        msg: _msg(results: results, query: 'Wells Fargo'),
        viewport: const Size(900, 800),
      );
      expect(tester.takeException(), isNull);
      
      
      expect(find.text('ARCHIVE CONTENT'), findsWidgets);
    });

    testWidgets(
        'hostile sentinels on an archive-match row never reach the tree',
        (tester) async {
      const sentinels = [
        'hunter2',
        'SUPERSECRET-XYZ-123',
        'plaintext-inner-file-leak',
        'archive-internal-secret',
      ];
      await _pump(
        tester,
        msg: _msg(results: [
          {
            'file_id': 'zip-x',
            'file_name': 'backup.zip',
            'saved_name': 'Backup',
            'mime_type': 'application/zip',
            'asset_type': 'archive',
            'match_type': 'purpose',
            'match_reason':
                'archive content match: accounts.txt appears to '
                'contain saved-login records',
            'match_confidence': 'strong',
            'is_archive_match': true,
            
            
            'extracted_text': 'plaintext-inner-file-leak',
            'archive_signals': {
              'inner_files': [
                {'path': 'leaked.txt', 'body': 'archive-internal-secret'},
              ],
            },
            'password': 'hunter2',
            'token': 'SUPERSECRET-XYZ-123',
          },
        ], query: 'saved logins'),
      );
      for (final sentinel in sentinels) {
        expect(
          find.textContaining(sentinel),
          findsNothing,
          reason:
              'the chip + row MUST NOT surface backend-leaked '
              'sentinel $sentinel — the renderer reads only the '
              'declared keys',
        );
      }
    });
  });

  
  group('FileSearchResultsCard — inner match details', () {
    Map<String, dynamic> archiveRowWithDetails({
      List<Map<String, dynamic>>? innerMatches,
      int? totalInner,
    }) {
      final defaultInner = [
        {
          'path': 'notes.md',
          'reason': 'mentions Wells Fargo',
          'kind': 'entity',
          'confidence': 'strong',
        },
        {
          'path': 'accounts.txt',
          'reason': 'appears to contain saved-login records',
          'kind': 'credentials',
          'confidence': 'strong',
        },
      ];
      final inner = innerMatches ?? defaultInner;
      return {
        'file_id': 'zip-1',
        'file_name': 'backup.zip',
        'saved_name': 'Backup',
        'mime_type': 'application/zip',
        'asset_type': 'archive',
        'match_type': 'entity',
        'match_reason':
            'archive content match: notes.md mentions Wells Fargo',
        'match_confidence': 'strong',
        'is_archive_match': true,
        'archive_match_details': {
          'inner_matches': inner,
          'total_inner_matches': totalInner ?? inner.length,
        },
      };
    }

    testWidgets('renders "Show inner matches" toggle with the count',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          results: [archiveRowWithDetails()],
          query: 'Wells Fargo',
        ),
      );
      expect(find.text('Show inner matches (2)'), findsOneWidget);
    });

    testWidgets('toggle reflects total_inner_matches when list is capped',
        (tester) async {
      
      
      final inner = List<Map<String, dynamic>>.generate(
        10,
        (i) => {
          'path': 'notes_$i.md',
          'reason': 'mentions Wells Fargo',
          'kind': 'entity',
          'confidence': 'strong',
        },
      );
      await _pump(
        tester,
        msg: _msg(
          results: [
            archiveRowWithDetails(
              innerMatches: inner,
              totalInner: 25,
            ),
          ],
          query: 'Wells Fargo',
        ),
      );
      expect(find.text('Show inner matches (25)'), findsOneWidget);
    });

    testWidgets('inner list is hidden until the toggle is tapped',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          results: [archiveRowWithDetails()],
          query: 'Wells Fargo',
        ),
      );
      
      expect(find.text('notes.md'), findsNothing);
      expect(find.text('accounts.txt'), findsNothing);
    });

    testWidgets('tapping the toggle expands the inner list',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          results: [archiveRowWithDetails()],
          query: 'Wells Fargo',
        ),
      );
      await tester.tap(find.text('Show inner matches (2)'));
      await tester.pumpAndSettle();
      expect(find.text('notes.md'), findsOneWidget);
      expect(find.text('accounts.txt'), findsOneWidget);
      
      expect(find.text('Hide inner matches'), findsOneWidget);
      expect(find.text('Show inner matches (2)'), findsNothing);
    });

    testWidgets('expanded list shows each entry path + reason',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(
          results: [archiveRowWithDetails()],
          query: 'Wells Fargo',
        ),
      );
      await tester.tap(find.text('Show inner matches (2)'));
      await tester.pumpAndSettle();
      expect(find.text('mentions Wells Fargo'), findsOneWidget);
      expect(
        find.text('appears to contain saved-login records'),
        findsOneWidget,
      );
    });

    testWidgets(
        'tapping the toggle does NOT open the parent archive',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(
          results: [archiveRowWithDetails()],
          query: 'Wells Fargo',
        ),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.text('Show inner matches (2)'));
      await tester.pumpAndSettle();
      
      expect(captured, isNull);
    });

    testWidgets(
        'tapping the row body still opens the PARENT archive file_id',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(
          results: [archiveRowWithDetails()],
          query: 'Wells Fargo',
        ),
        onOpen: (m) => captured = m,
      );
      
      await tester.tap(find.text('Backup'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.fileId, 'zip-1');
      expect(captured!.kind, ChatMessage.kVaultFile);
    });

    testWidgets(
        'expanded inner entries are NOT independently tappable for open',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(
          results: [archiveRowWithDetails()],
          query: 'Wells Fargo',
        ),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.text('Show inner matches (2)'));
      await tester.pumpAndSettle();
      
      
      expect(find.byIcon(Icons.open_in_new), findsOneWidget);
      
      
      await tester.tap(find.text('notes.md'));
      await tester.pumpAndSettle();
      if (captured != null) {
        expect(captured!.fileId, 'zip-1');
      }
    });

    testWidgets(
        'archive_match_details missing → no expand control',
        (tester) async {
      final row = archiveRowWithDetails();
      row.remove('archive_match_details');
      await _pump(
        tester,
        msg: _msg(results: [row], query: 'Wells Fargo'),
      );
      expect(find.textContaining('Show inner matches'), findsNothing);
      expect(find.textContaining('Hide inner matches'), findsNothing);
    });

    testWidgets(
        'empty inner_matches → no expand control',
        (tester) async {
      final row = archiveRowWithDetails(
        innerMatches: const [],
        totalInner: 0,
      );
      await _pump(
        tester,
        msg: _msg(results: [row], query: 'Wells Fargo'),
      );
      expect(find.textContaining('Show inner matches'), findsNothing);
    });

    testWidgets(
        'archive_match_details on non-archive row is ignored',
        (tester) async {
      
      
      final row = archiveRowWithDetails();
      row['is_archive_match'] = false;
      await _pump(
        tester,
        msg: _msg(results: [row], query: 'Wells Fargo'),
      );
      expect(find.textContaining('Show inner matches'), findsNothing);
    });

    testWidgets(
        'hostile sentinels on inner entries never reach the tree',
        (tester) async {
      const sentinels = [
        'hunter2',
        'SUPERSECRET-XYZ-123',
        'plaintext-inner-body-leak',
        'archive-internal-secret',
      ];
      final row = archiveRowWithDetails(
        innerMatches: [
          {
            'path': 'notes.md',
            'reason': 'mentions Wells Fargo',
            'kind': 'entity',
            'confidence': 'strong',
            
            
            'body': 'plaintext-inner-body-leak',
            'raw': 'archive-internal-secret',
            'password': 'hunter2',
            'token': 'SUPERSECRET-XYZ-123',
          },
        ],
        totalInner: 1,
      );
      await _pump(
        tester,
        msg: _msg(results: [row], query: 'Wells Fargo'),
      );
      
      await tester.tap(find.text('Show inner matches (1)'));
      await tester.pumpAndSettle();
      for (final sentinel in sentinels) {
        expect(
          find.textContaining(sentinel),
          findsNothing,
          reason:
              'inner-match row MUST NOT render hostile key '
              '$sentinel — only path/reason/kind/confidence are read',
        );
      }
    });

    testWidgets(
        '100 archive rows + expanded inner lists render without overflow',
        (tester) async {
      final results = <Map<String, dynamic>>[];
      for (var i = 0; i < 100; i++) {
        results.add({
          'file_id': 'zip-$i',
          'file_name': 'backup_$i.zip',
          'saved_name': 'Backup $i',
          'mime_type': 'application/zip',
          'asset_type': 'archive',
          'match_type': 'entity',
          'match_reason':
              'archive content match: notes.md mentions Wells Fargo',
          'match_confidence': 'strong',
          'is_archive_match': true,
          'archive_match_details': {
            'inner_matches': [
              {
                'path': 'notes.md',
                'reason': 'mentions Wells Fargo',
                'kind': 'entity',
                'confidence': 'strong',
              },
            ],
            'total_inner_matches': 1,
          },
        });
      }
      await _pump(
        tester,
        msg: _msg(results: results, query: 'Wells Fargo'),
        viewport: const Size(900, 800),
      );
      expect(tester.takeException(), isNull);
      
      expect(find.textContaining('Show inner matches'), findsWidgets);
    });

    testWidgets(
        'wrong-typed archive_match_details is ignored',
        (tester) async {
      final row = archiveRowWithDetails();
      
      row['archive_match_details'] = 'not-a-map';
      await _pump(
        tester,
        msg: _msg(results: [row], query: 'Wells Fargo'),
      );
      expect(find.textContaining('Show inner matches'), findsNothing);
    });
  });

  group('Source guards', () {
    test('chat_models.dart exposes kFileSearchResults', () {
      expect(
        ChatMessage.kFileSearchResults,
        equals('file_search_results'),
      );
    });

    test('isCard returns true for kFileSearchResults', () {
      final m = ChatMessage(
        'assistant',
        'x',
        kind: ChatMessage.kFileSearchResults,
        payload: const <String, dynamic>{},
      );
      expect(m.isCard, isTrue);
    });

    test('main.dart parser handles file_search_results type',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'file_search_results'"));
      expect(
        src,
        contains("kind: 'file_search_results'"),
        reason:
            'parser must produce a kFileSearchResults ChatMessage',
      );
    });

    test('main.dart parser still has the fallback for unknown envelopes',
        () async {
      
      
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("fallbackMessage = decoded['message']"));
    });

    test(
        'chat_bubble.dart routes kFileSearchResults to '
        'FileSearchResultsCard', () async {
      final src =
          await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('ChatMessage.kFileSearchResults'));
      expect(src, contains('FileSearchResultsCard'));
    });
  });
}
