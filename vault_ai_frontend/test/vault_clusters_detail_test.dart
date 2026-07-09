

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  Size viewport = const Size(900, 2400),
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

Map<String, dynamic> _safeFile({
  String fileId = 'f-1',
  String fileName = 'doc.pdf',
  String savedName = 'Doc',
  String relativePath = '/Bank',
  String mimeType = 'application/pdf',
  Map<String, dynamic>? hostile,
}) {
  return {
    'file_id':       fileId,
    'file_name':     fileName,
    'saved_name':    savedName,
    'relative_path': relativePath,
    'mime_type':     mimeType,
    'asset_type':    'file',
    if (hostile != null) ...hostile,
  };
}

Map<String, dynamic> _cluster({
  required String clusterId,
  required String title,
  required String clusterType,
  required String confidence,
  required List<Map<String, dynamic>> representativeFiles,
  int? fileCount,
}) {
  return {
    'cluster_id':                 clusterId,
    'cluster_type':               clusterType,
    'title':                      title,
    'confidence':                 confidence,
    'file_count':                 fileCount ?? representativeFiles.length,
    'relationship_count':         representativeFiles.length,
    'strong_relationship_count':  representativeFiles.length,
    'main_reasons':               const [],
    'representative_files':       representativeFiles,
    'related_file_ids':           representativeFiles
        .map((f) => f['file_id'] as String)
        .toList(),
    'warnings':                   const [],
  };
}

ChatMessage _msg(List<Map<String, dynamic>> clusters) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kVaultRelationshipClusters,
    payload: {
      'count':    clusters.length,
      'clusters': clusters,
    },
  );
}

List<Map<String, dynamic>> _files(int n, {String prefix = 'f'}) {
  return List<Map<String, dynamic>>.generate(
    n,
    (i) => _safeFile(
      fileId: '$prefix-$i',
      fileName: '$prefix-$i.pdf',
      savedName: '${prefix.toUpperCase()} $i',
      relativePath: '/Cluster',
    ),
  );
}

void main() {
  group('VaultRelationshipClustersCard — View cluster visibility', () {
    testWidgets('hidden when cluster has ≤ 5 files', (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Small',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(5),
            ),
          ]),
        ),
      );
      expect(find.textContaining('View cluster'), findsNothing);
      expect(find.text('Hide cluster'), findsNothing);
    });

    testWidgets('visible when cluster has > 5 files', (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Big',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(12),
            ),
          ]),
        ),
      );
      
      expect(
        find.text('View cluster — +7 more'),
        findsOneWidget,
      );
    });
  });

  group('VaultRelationshipClustersCard — expand inline', () {
    testWidgets('collapsed shows only the first 5 files',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Big',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(10),
            ),
          ]),
        ),
      );
      
      for (int i = 0; i < 5; i++) {
        expect(find.text('F $i'), findsOneWidget);
      }
      
      for (int i = 5; i < 10; i++) {
        expect(find.text('F $i'), findsNothing);
      }
    });

    testWidgets('tap expands inline; ALL files render under the row',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Big',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(10),
            ),
          ]),
        ),
      );
      await tester.tap(find.text('View cluster — +5 more'));
      await tester.pumpAndSettle();
      
      for (int i = 0; i < 10; i++) {
        expect(find.text('F $i'), findsOneWidget);
      }
      
      expect(find.text('Hide cluster'), findsOneWidget);
      expect(find.textContaining('View cluster'), findsNothing);
    });

    testWidgets('tap Hide cluster collapses back to preview',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Big',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(10),
            ),
          ]),
        ),
      );
      await tester.tap(find.text('View cluster — +5 more'));
      await tester.pumpAndSettle();
      
      
      await tester.ensureVisible(find.text('Hide cluster'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Hide cluster'));
      await tester.pumpAndSettle();
      
      
      expect(find.text('View cluster — +5 more'), findsOneWidget);
      expect(find.text('Hide cluster'), findsNothing);
    });

    testWidgets('per-cluster expansion is independent', (tester) async {
      
      
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'A',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(7, prefix: 'a'),
            ),
            _cluster(
              clusterId: 'c2',
              title: 'B',
              clusterType: 'travel',
              confidence: 'strong',
              representativeFiles: _files(7, prefix: 'b'),
            ),
          ]),
        ),
      );
      
      
      expect(find.text('View cluster — +2 more'), findsNWidgets(2));
      
      
      await tester.tap(find.text('View cluster — +2 more').first);
      await tester.pumpAndSettle();
      expect(find.text('Hide cluster'), findsOneWidget);
    });
  });

  group('VaultRelationshipClustersCard — tap routing in expansion',
      () {
    testWidgets(
        'Open on a row > 5 routes through onOpen with EXACT file_id',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Big',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(10),
            ),
          ]),
          onOpen: (m) => captured = m,
        ),
      );
      await tester.tap(find.text('View cluster — +5 more'));
      await tester.pumpAndSettle();
      
      
      await tester.ensureVisible(find.text('F 7'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('F 7'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.fileId, 'f-7');
    });

    testWidgets('Show related on a row > 5 fires callback with '
        'EXACT file_id', (tester) async {
      String? captured;
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Big',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(10),
            ),
          ]),
          onShowRelated: (id) => captured = id,
        ),
      );
      await tester.tap(find.text('View cluster — +5 more'));
      await tester.pumpAndSettle();
      
      
      await tester.ensureVisible(find.byTooltip('Show related').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Show related').last);
      await tester.pumpAndSettle();
      
      
      expect(captured, 'f-9');
    });
  });

  group('VaultRelationshipClustersCard — overflow + mobile', () {
    testWidgets('expanded cluster with 50 files renders without overflow',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Huge',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(50),
            ),
          ]),
        ),
      );
      await tester.tap(find.text('View cluster — +45 more'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('mobile-width viewport renders cleanly with cluster '
        'expanded', (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Mobile cluster',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(8),
            ),
          ]),
        ),
        viewport: const Size(400, 1200),
      );
      await tester.tap(find.text('View cluster — +3 more'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      
      for (int i = 0; i < 8; i++) {
        expect(find.text('F $i'), findsOneWidget);
      }
    });
  });

  group('VaultRelationshipClustersCard — backend truncation hint', () {
    testWidgets(
        'expanded view shows "+N more" hint when true cluster size '
        'exceeds backend per-cluster cap', (tester) async {
      
      
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Truncated cluster',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: _files(50),
              fileCount: 73,  
            ),
          ]),
        ),
      );
      await tester.tap(find.text('View cluster — +45 more'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('+23 more'),
        findsOneWidget,
        reason: 'expanded view must honestly disclose backend '
            'truncation (73 true - 50 shipped = 23 missing)',
      );
    });
  });

  group('VaultRelationshipClustersCard — security in expansion', () {
    testWidgets(
        'expanded view NEVER renders summary / extracted_text / '
        'password / token sentinels from hostile representative '
        'files', (tester) async {
      const sentinels = [
        'plaintext-summary-leak',
        'plaintext-preview-leak',
        'plaintext-content-leak',
        'hunter2',
        'SUPERSECRET-XYZ-123',
      ];
      
      
      final files = <Map<String, dynamic>>[
        for (int i = 0; i < 5; i++)
          _safeFile(
            fileId: 'safe-$i',
            fileName: 's-$i.pdf',
            savedName: 'Safe $i',
          ),
        for (int i = 0; i < 3; i++)
          _safeFile(
            fileId: 'hostile-$i',
            fileName: 'h-$i.pdf',
            savedName: 'Hostile $i',
            hostile: const {
              'summary':         'plaintext-summary-leak',
              'safe_preview':    'plaintext-preview-leak',
              'extracted_text':  'plaintext-content-leak',
              'password':        'hunter2',
              'token':           'SUPERSECRET-XYZ-123',
            },
          ),
      ];
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Mixed',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: files,
            ),
          ]),
        ),
      );
      await tester.tap(find.text('View cluster — +3 more'));
      await tester.pumpAndSettle();
      for (final s in sentinels) {
        expect(
          find.textContaining(s),
          findsNothing,
          reason:
              'expanded cluster detail must NOT surface '
              'sentinel $s — reads ONLY the closed-set keys',
        );
      }
    });
  });
}
