

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

Map<String, dynamic> _safeFile({
  String fileId = 'f-1',
  String fileName = 'doc.pdf',
  String savedName = 'Doc',
  String relativePath = '/Bank',
  String mimeType = 'application/pdf',
}) {
  return {
    'file_id':       fileId,
    'file_name':     fileName,
    'saved_name':    savedName,
    'relative_path': relativePath,
    'mime_type':     mimeType,
    'asset_type':    'file',
  };
}

Map<String, dynamic> _cluster({
  required String clusterId,
  required String title,
  required String clusterType,
  required String confidence,
  required List<Map<String, dynamic>> representativeFiles,
  int fileCount = 0,
  int relationshipCount = 1,
  int strongRelationshipCount = 1,
  List<String> mainReasons = const [],
  List<String> warnings = const [],
}) {
  return {
    'cluster_id':                 clusterId,
    'cluster_type':               clusterType,
    'title':                      title,
    'confidence':                 confidence,
    'file_count':                 fileCount == 0
        ? representativeFiles.length
        : fileCount,
    'relationship_count':         relationshipCount,
    'strong_relationship_count':  strongRelationshipCount,
    'main_reasons':               mainReasons,
    'representative_files':       representativeFiles,
    'related_file_ids':           representativeFiles
        .map((f) => f['file_id'] as String)
        .toList(),
    'warnings':                   warnings,
  };
}

ChatMessage _msg(List<Map<String, dynamic>> clusters, {String text = ''}) {
  return ChatMessage(
    'assistant',
    text,
    kind: ChatMessage.kVaultRelationshipClusters,
    payload: {
      'count':    clusters.length,
      'clusters': clusters,
    },
  );
}

void main() {
  group('VaultRelationshipClustersCard — header', () {
    testWidgets('renders title + cluster count', (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Maureen identity documents',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [_safeFile()],
            ),
          ]),
        ),
      );
      expect(
        find.text('Connected groups in your vault'),
        findsOneWidget,
      );
      expect(find.text('1 group'), findsOneWidget);
    });

    testWidgets('renders pluralised subtitle for > 1 cluster',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Identity',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [_safeFile(fileId: 'a')],
            ),
            _cluster(
              clusterId: 'c2',
              title: 'Travel',
              clusterType: 'travel',
              confidence: 'strong',
              representativeFiles: [_safeFile(fileId: 'b')],
            ),
          ]),
        ),
      );
      expect(find.text('2 groups'), findsOneWidget);
    });

    testWidgets('empty cluster list renders empty-state header',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg(const [],
              text:
                  "I don't see connected groups in your vault yet. "
                  'As more files are analyzed, document groups may appear.'),
        ),
      );
      expect(find.text('No connected groups yet'), findsOneWidget);
      expect(
        find.textContaining("don't see connected groups"),
        findsOneWidget,
      );
    });
  });

  group('VaultRelationshipClustersCard — cluster row content', () {
    testWidgets('renders title + type chip + confidence + reasons',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Maureen identity documents',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [_safeFile()],
              fileCount: 4,
              mainReasons: const [
                'same person name: Maureen',
                'front/back ID pair',
              ],
            ),
          ]),
        ),
      );
      expect(find.text('Maureen identity documents'), findsOneWidget);
      expect(find.text('IDENTITY'), findsOneWidget);
      expect(find.text('STRONG'), findsOneWidget);
      expect(find.text('4 files'), findsOneWidget);
      expect(
        find.textContaining('same person name: Maureen'),
        findsOneWidget,
      );
      expect(find.textContaining('front/back ID pair'), findsOneWidget);
    });

    testWidgets('reasons capped at 3', (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'X',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [_safeFile()],
              mainReasons: const [
                'reason A',
                'reason B',
                'reason C',
                'reason D',
              ],
            ),
          ]),
        ),
      );
      expect(find.text('reason A'), findsOneWidget);
      expect(find.text('reason B'), findsOneWidget);
      expect(find.text('reason C'), findsOneWidget);
      
      
      expect(find.text('reason D'), findsNothing);
    });

    testWidgets('warnings render with info icon + italic caption',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'X',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [_safeFile()],
              warnings: const [
                'Some connections may still be refreshing.',
              ],
            ),
          ]),
        ),
      );
      expect(
        find.text('Some connections may still be refreshing.'),
        findsOneWidget,
      );
    });
  });

  group('VaultRelationshipClustersCard — representative files', () {
    testWidgets('renders saved_name + folder for each file',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Identity',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [
                _safeFile(
                  fileId: 'f-front',
                  fileName: 'front.jpg',
                  savedName: 'Maureen ID — Front',
                  relativePath: '/Family/IDs',
                  mimeType: 'image/jpeg',
                ),
                _safeFile(
                  fileId: 'f-back',
                  fileName: 'back.jpg',
                  savedName: 'Maureen ID — Back',
                  relativePath: '/Family/IDs',
                  mimeType: 'image/jpeg',
                ),
              ],
            ),
          ]),
        ),
      );
      expect(find.text('Maureen ID — Front'), findsOneWidget);
      expect(find.text('Maureen ID — Back'), findsOneWidget);
      expect(find.text('/Family/IDs'), findsNWidgets(2));
    });

    testWidgets('tap routes through onOpen with EXACT file_id',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Identity',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [
                _safeFile(
                  fileId: 'PINNED-FILE-ID',
                  fileName: 'front.jpg',
                  savedName: 'Front',
                ),
              ],
            ),
          ]),
          onOpen: (m) => captured = m,
        ),
      );
      await tester.tap(find.text('Front'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.fileId, 'PINNED-FILE-ID');
      expect(captured!.fileId, isNot('front.jpg'));
      expect(captured!.fileId, isNot('c1'));
    });

    testWidgets('Show related tap fires with EXACT file_id when '
        'callback wired', (tester) async {
      String? captured;
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Identity',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [
                _safeFile(
                  fileId: 'PINNED-FILE-ID',
                  fileName: 'front.jpg',
                  savedName: 'Front',
                ),
              ],
            ),
          ]),
          onShowRelated: (id) => captured = id,
        ),
      );
      await tester.tap(find.byTooltip('Show related'));
      await tester.pumpAndSettle();
      expect(captured, 'PINNED-FILE-ID');
      expect(captured, isNot('front.jpg'));
    });

    testWidgets('Show related button hidden when onShowRelated null',
        (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Identity',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [_safeFile()],
            ),
          ]),
        ),
      );
      expect(find.byTooltip('Show related'), findsNothing);
    });

    testWidgets('Show related button hidden per-row when file_id '
        'missing', (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Identity',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [
                _safeFile(fileId: ''),
                _safeFile(
                  fileId: 'f-2', fileName: 'b.pdf', savedName: 'B',
                ),
              ],
            ),
          ]),
          onShowRelated: (_) {},
        ),
      );
      
      
      expect(find.byTooltip('Show related'), findsOneWidget);
    });
  });

  group('VaultRelationshipClustersCard — overflow + mobile', () {
    testWidgets('100 clusters render without overflow', (tester) async {
      final clusters = List<Map<String, dynamic>>.generate(
        100,
        (i) => _cluster(
          clusterId: 'c-$i',
          title: 'Group $i',
          clusterType: i.isEven ? 'identity' : 'same_person',
          confidence: i.isEven ? 'strong' : 'medium',
          representativeFiles: [
            _safeFile(fileId: 'f-$i', fileName: '$i.pdf'),
          ],
        ),
      );
      await _pump(
        tester,
        VaultRelationshipClustersCard(msg: _msg(clusters)),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('mobile-width viewport renders cleanly', (tester) async {
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            _cluster(
              clusterId: 'c1',
              title: 'Maureen identity documents',
              clusterType: 'identity',
              confidence: 'strong',
              representativeFiles: [_safeFile()],
              mainReasons: const ['same person name: Maureen'],
            ),
          ]),
        ),
        viewport: const Size(400, 1000),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Maureen identity documents'), findsOneWidget);
    });
  });

  group('VaultRelationshipClustersCard — security guards', () {
    testWidgets(
        'NEVER renders summary / safe_preview / extracted_text / '
        'password / token sentinel values from a hostile payload',
        (tester) async {
      const sentinels = [
        'plaintext-summary-leak',
        'plaintext-preview-leak',
        'plaintext-content-leak',
        'hunter2',
        'SUPERSECRET-XYZ-123',
      ];
      await _pump(
        tester,
        VaultRelationshipClustersCard(
          msg: _msg([
            {
              'cluster_id':            'c1',
              'cluster_type':          'identity',
              'title':                 'Identity',
              'confidence':            'strong',
              'file_count':            1,
              'relationship_count':    1,
              'strong_relationship_count': 1,
              'main_reasons':          const ['safe reason'],
              'related_file_ids':      const ['f-1'],
              'warnings':              const [],
              'representative_files': [
                {
                  'file_id':         'f-1',
                  'file_name':       'x.pdf',
                  'saved_name':      'X',
                  'relative_path':   '/x',
                  'mime_type':       'application/pdf',
                  'asset_type':      'file',
                  
                  'summary':         'plaintext-summary-leak',
                  'safe_preview':    'plaintext-preview-leak',
                  'extracted_text':  'plaintext-content-leak',
                  'password':        'hunter2',
                  'token':           'SUPERSECRET-XYZ-123',
                },
              ],
            },
          ]),
        ),
      );
      for (final s in sentinels) {
        expect(
          find.textContaining(s),
          findsNothing,
          reason: 'card must not surface sentinel $s — reads ONLY '
              'the declared closed-set keys',
        );
      }
    });
  });

  group('VaultRelationshipClustersCard — source guards', () {
    test('chat_models exposes kVaultRelationshipClusters', () {
      expect(
        ChatMessage.kVaultRelationshipClusters,
        equals('vault_relationship_clusters'),
      );
    });

    test('isCard returns true for kVaultRelationshipClusters', () {
      final m = ChatMessage(
        'assistant',
        'x',
        kind: ChatMessage.kVaultRelationshipClusters,
        payload: const <String, dynamic>{},
      );
      expect(m.isCard, isTrue);
    });

    test('main.dart parser handles vault_relationship_clusters type',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'vault_relationship_clusters'"));
      expect(
        src,
        contains("kind: 'vault_relationship_clusters'"),
        reason:
            'parser must produce a kVaultRelationshipClusters ChatMessage',
      );
    });

    test('chat_bubble.dart routes kVaultRelationshipClusters to '
        'VaultRelationshipClustersCard', () async {
      final src =
          await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('ChatMessage.kVaultRelationshipClusters'));
      expect(src, contains('VaultRelationshipClustersCard('));
    });
  });
}
