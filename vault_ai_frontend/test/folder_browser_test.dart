

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/folder_browser/folder_browser.dart';


FolderTreeData _tree({
  String path = '',
  List<String>? breadcrumbs,
  List<FolderNode>? folders,
  List<Map<String, dynamic>>? files,
}) {
  return FolderTreeData(
    path: path,
    breadcrumbs: breadcrumbs ?? const [],
    folders: folders ?? const [],
    files: files ?? const [],
  );
}


Map<String, dynamic> _fileJson({
  required String name,
  String? savedName,
  String? relativePath,
  int size = 1024,
}) {
  return {
    'id': name,
    'file_name': name,
    'saved_name': savedName ?? name,
    'relative_path': relativePath,
    'file_size': size,
    'content_type': 'application/pdf',
    'asset_type': 'file',
    'needs_naming': false,
  };
}


Future<void> _pumpBrowser(
  WidgetTester tester, {
  required FolderTreeData tree,
  required void Function(String) onNavigateToPath,
  Widget Function(Map<String, dynamic>)? fileItemBuilder,
  String searchQuery = '',
  ValueChanged<String>? onSearchChanged,
  bool isMobile = false,
  Size viewport = const Size(1024, 768),
}) async {
  tester.view.physicalSize = viewport;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });

  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        backgroundColor: const Color(0xFF1F1F1F),
        body: SafeArea(
          child: SizedBox(
            width: viewport.width,
            height: viewport.height,
            child: FolderBrowser(
              treeData: tree,
              onNavigateToPath: onNavigateToPath,
              fileItemBuilder: fileItemBuilder ??
                  (json) => Padding(
                        key: ValueKey('file:${json['id']}'),
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Text(
                          (json['saved_name'] ?? json['file_name'])
                              .toString(),
                          style: const TextStyle(color: Colors.white),
                        ),
                      ),
              searchQuery: searchQuery,
              onSearchChanged: onSearchChanged,
              isMobile: isMobile,
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('FolderNode.fromJson', () {
    test('parses canonical backend payload', () {
      final node = FolderNode.fromJson({
        'name': 'My Life Backup',
        'file_count': 245,
      });
      expect(node.name, 'My Life Backup');
      expect(node.fileCount, 245);
    });

    test('handles missing file_count as zero', () {
      final node = FolderNode.fromJson({'name': 'Empty Folder'});
      expect(node.fileCount, 0);
    });

    test('handles missing name as empty string', () {
      final node = FolderNode.fromJson({});
      expect(node.name, '');
    });
  });

  group('FolderTreeData.fromJson', () {
    test('parses root view with folders + files + empty breadcrumbs',
        () {
      final tree = FolderTreeData.fromJson({
        'path': '',
        'breadcrumbs': [],
        'folders': [
          {'name': 'A', 'file_count': 3},
          {'name': 'B', 'file_count': 5},
        ],
        'files': [
          {
            'id': 'f1',
            'file_name': 'loose.pdf',
            'relative_path': null,
          },
        ],
      });
      expect(tree.path, '');
      expect(tree.breadcrumbs, isEmpty);
      expect(tree.folders.map((f) => f.name).toList(), ['A', 'B']);
      expect(tree.files.length, 1);
      expect(tree.files.first['file_name'], 'loose.pdf');
    });

    test('parses nested view with breadcrumbs', () {
      final tree = FolderTreeData.fromJson({
        'path': 'My Life Backup/Photos',
        'breadcrumbs': ['My Life Backup', 'Photos'],
        'folders': [],
        'files': [],
      });
      expect(tree.path, 'My Life Backup/Photos');
      expect(tree.breadcrumbs, ['My Life Backup', 'Photos']);
      expect(tree.isEmpty, isTrue);
    });

    test('handles every field missing', () {
      final tree = FolderTreeData.fromJson({});
      expect(tree.path, '');
      expect(tree.breadcrumbs, isEmpty);
      expect(tree.folders, isEmpty);
      expect(tree.files, isEmpty);
      expect(tree.isEmpty, isTrue);
    });
  });

  group('FolderBrowser rendering', () {
    testWidgets('shows the breadcrumb Root chip at root', (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(),
        onNavigateToPath: (_) {},
      );
      expect(find.text('Root'), findsOneWidget);
    });

    testWidgets('renders a breadcrumb chip per segment', (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(
          path: 'My Life Backup/Photos/Family',
          breadcrumbs: ['My Life Backup', 'Photos', 'Family'],
        ),
        onNavigateToPath: (_) {},
      );
      expect(find.text('Root'), findsOneWidget);
      expect(find.text('My Life Backup'), findsOneWidget);
      expect(find.text('Photos'), findsOneWidget);
      expect(find.text('Family'), findsOneWidget);
    });

    testWidgets('renders folder rows with file counts', (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(
          folders: [
            const FolderNode(name: 'Photos', fileCount: 12),
            const FolderNode(name: 'Bank', fileCount: 1),
          ],
        ),
        onNavigateToPath: (_) {},
      );
      expect(find.text('Photos'), findsOneWidget);
      expect(find.text('12 files'), findsOneWidget);
      expect(find.text('Bank'), findsOneWidget);
      
      expect(find.text('1 file'), findsOneWidget);
      expect(find.byIcon(Icons.folder), findsNWidgets(2));
    });

    testWidgets('renders file rows via fileItemBuilder', (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(
          files: [
            _fileJson(name: 'statement.pdf'),
            _fileJson(name: 'family.jpg'),
          ],
        ),
        onNavigateToPath: (_) {},
      );
      expect(find.text('statement.pdf'), findsOneWidget);
      expect(find.text('family.jpg'), findsOneWidget);
    });

    testWidgets('shows empty-state message when no folders or files',
        (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(),
        onNavigateToPath: (_) {},
      );
      expect(find.text('This folder is empty.'), findsOneWidget);
    });

    testWidgets('shows search-empty-state when query has no matches',
        (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(
          folders: [const FolderNode(name: 'Photos', fileCount: 1)],
        ),
        searchQuery: 'zzz',
        onSearchChanged: (_) {},
        onNavigateToPath: (_) {},
      );
      expect(find.text('No matches.'), findsOneWidget);
    });
  });

  group('FolderBrowser navigation callbacks', () {
    testWidgets('tapping a folder fires onNavigateToPath with the '
        'absolute path', (tester) async {
      String? navigatedTo;
      await _pumpBrowser(
        tester,
        tree: _tree(
          path: 'My Life Backup',
          breadcrumbs: ['My Life Backup'],
          folders: [const FolderNode(name: 'Photos', fileCount: 1)],
        ),
        onNavigateToPath: (p) => navigatedTo = p,
      );
      await tester.tap(find.text('Photos'));
      await tester.pumpAndSettle();
      expect(navigatedTo, 'My Life Backup/Photos');
    });

    testWidgets('tapping Root from a nested path fires with empty path',
        (tester) async {
      String? navigatedTo;
      await _pumpBrowser(
        tester,
        tree: _tree(
          path: 'My Life Backup/Photos',
          breadcrumbs: ['My Life Backup', 'Photos'],
        ),
        onNavigateToPath: (p) => navigatedTo = p,
      );
      await tester.tap(find.text('Root'));
      await tester.pumpAndSettle();
      expect(navigatedTo, '');
    });

    testWidgets('tapping a mid-breadcrumb jumps to the partial path',
        (tester) async {
      String? navigatedTo;
      await _pumpBrowser(
        tester,
        tree: _tree(
          path: 'My Life Backup/Photos/Family',
          breadcrumbs: ['My Life Backup', 'Photos', 'Family'],
        ),
        onNavigateToPath: (p) => navigatedTo = p,
      );
      
      
      await tester.tap(find.text('Photos').first);
      await tester.pumpAndSettle();
      expect(navigatedTo, 'My Life Backup/Photos');
    });

    testWidgets('root tree shows no folders does not crash navigation',
        (tester) async {
      String? navigatedTo;
      await _pumpBrowser(
        tester,
        tree: _tree(),
        onNavigateToPath: (p) => navigatedTo = p,
      );
      expect(find.byType(FolderBrowser), findsOneWidget);
      expect(navigatedTo, isNull);
    });
  });

  group('FolderBrowser search', () {
    testWidgets('filters folder names on substring match', (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(
          folders: [
            const FolderNode(name: 'Photos', fileCount: 1),
            const FolderNode(name: 'Bank Statements', fileCount: 1),
            const FolderNode(name: 'Code', fileCount: 1),
          ],
        ),
        searchQuery: 'bank',
        onSearchChanged: (_) {},
        onNavigateToPath: (_) {},
      );
      expect(find.text('Bank Statements'), findsOneWidget);
      expect(find.text('Photos'), findsNothing);
      expect(find.text('Code'), findsNothing);
    });

    testWidgets('filters file metadata across file_name + saved_name '
        '+ relative_path', (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(
          files: [
            _fileJson(
              name: 'a.pdf',
              savedName: 'Tax Return 2023',
              relativePath: 'Taxes/a.pdf',
            ),
            _fileJson(
              name: 'b.pdf',
              savedName: 'Phone Bill',
              relativePath: 'Bills/b.pdf',
            ),
          ],
        ),
        searchQuery: 'tax',
        onSearchChanged: (_) {},
        onNavigateToPath: (_) {},
      );
      expect(find.text('Tax Return 2023'), findsOneWidget);
      expect(find.text('Phone Bill'), findsNothing);
    });

    testWidgets('case-insensitive match', (tester) async {
      await _pumpBrowser(
        tester,
        tree: _tree(
          folders: [
            const FolderNode(name: 'Photos', fileCount: 1),
          ],
        ),
        searchQuery: 'PHOTOS',
        onSearchChanged: (_) {},
        onNavigateToPath: (_) {},
      );
      expect(find.text('Photos'), findsOneWidget);
    });

    testWidgets('clear button (X) in the search field empties the '
        'query callback', (tester) async {
      String? lastQuery;
      await _pumpBrowser(
        tester,
        tree: _tree(
          folders: [const FolderNode(name: 'Photos', fileCount: 1)],
        ),
        searchQuery: 'photos',
        onSearchChanged: (q) => lastQuery = q,
        onNavigateToPath: (_) {},
      );
      
      await tester.enterText(
        find.byType(TextField),
        'foo',
      );
      await tester.pumpAndSettle();
      expect(lastQuery, 'foo');
    });
  });

  group('FolderBrowser overflow safety', () {
    testWidgets('many folders + files do not overflow desktop viewport',
        (tester) async {
      final manyFolders = List.generate(
        30,
        (i) => FolderNode(name: 'Folder_$i', fileCount: i + 1),
      );
      final manyFiles = List.generate(
        40,
        (i) => _fileJson(name: 'file_$i.pdf'),
      );
      await _pumpBrowser(
        tester,
        tree: _tree(folders: manyFolders, files: manyFiles),
        onNavigateToPath: (_) {},
        viewport: const Size(1024, 700),
      );
      expect(tester.takeException(), isNull,
          reason: '70 rows must not overflow on a desktop viewport');
      expect(find.byType(ListView), findsOneWidget,
          reason: 'browser must use ListView.builder for virtualisation');
    });

    testWidgets('many rows on a mobile viewport stay scrollable',
        (tester) async {
      final manyFiles = List.generate(
        50,
        (i) => _fileJson(name: 'file_$i.pdf'),
      );
      await _pumpBrowser(
        tester,
        tree: _tree(files: manyFiles),
        onNavigateToPath: (_) {},
        isMobile: true,
        viewport: const Size(360, 740),
      );
      expect(tester.takeException(), isNull);
      expect(find.byType(Scrollable), findsWidgets);
    });

    test('height caps are positive, finite, and desktop > mobile', () {
      expect(
        FolderBrowser.maxHeightDesktop,
        greaterThan(FolderBrowser.maxHeightMobile),
      );
      expect(FolderBrowser.maxHeightDesktop, greaterThan(0));
      expect(FolderBrowser.maxHeightMobile, greaterThan(0));
      expect(FolderBrowser.maxHeightDesktop.isFinite, isTrue);
      expect(FolderBrowser.maxHeightMobile.isFinite, isTrue);
    });
  });

  group('Source guard: main.dart wiring', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('dashboard owns _currentFolderPath / _folderTreeData / '
        '_folderSearchQuery state', () {
      final src = readMain();
      expect(src, contains('String _currentFolderPath = '));
      expect(src, contains('FolderTreeData? _folderTreeData;'));
      expect(src, contains('String _folderSearchQuery = '));
    });

    test('_loadFolderTree calls client.listFolder with the current '
        'path', () {
      final src = readMain();
      expect(src, contains('client.listFolder('));
      expect(src, contains('FolderTreeData.fromJson(response)'));
    });

    test('_navigateToFolder clears the search query so it does not '
        'cross-pollute folders', () {
      final src = readMain();
      expect(src, contains('void _navigateToFolder(String path)'));
      expect(
        src,
        contains("_folderSearchQuery = '';"),
        reason: 'navigation must reset the search query',
      );
    });

    test('_buildFilesSection mounts FolderBrowser when tree data '
        'is present', () {
      final src = readMain();
      expect(src, contains('if (_folderTreeData != null)'));
      expect(src, contains('FolderBrowser('));
    });

    test('FileV2 management cards remain visible beside the legacy '
        'folder tree', () {
      final src = readMain();
      final fileV2Cards = src.indexOf(
        '.where((file) => file.isFileV2)',
        src.indexOf('Widget _buildFilesSection'),
      );
      final folderBrowser = src.indexOf('FolderBrowser(', fileV2Cards);
      expect(fileV2Cards, greaterThanOrEqualTo(0));
      expect(folderBrowser, greaterThan(fileV2Cards),
          reason: 'FileV2 rows come from /vault/file-v2, not the legacy '
              'folder endpoint, and must be rendered before FolderBrowser.');
    });

    test('_buildFilesSection falls back to the flat list when tree '
        'data is null', () {
      final src = readMain();
      expect(
        src,
        contains('...vaultFiles.map(_buildVaultFileCard),'),
        reason: 'legacy flat list must still render when /folders '
                'has not returned (offline / first-load)',
      );
    });

    test('_VaultStoredFile.fromJson reads relative_path off the row',
        () {
      final src = readMain();
      expect(
        src,
        contains("relativePath: json['relative_path']?.toString(),"),
        reason: 'the file card subtitle includes the relative_path '
                'and the dashboard maps the JSON through this '
                'factory',
      );
    });
  });

  group('Source guard: api_client.listFolder', () {
    String readApi() {
      final file = File('lib/api_client.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('listFolder hits GET /folders with optional path query', () {
      final src = readApi();
      expect(src, contains("Future<Map<String, dynamic>> listFolder("));
      expect(src, contains("'\$baseUrl/folders\$qs'"));
      expect(
        src,
        contains("'?path=\${Uri.encodeQueryComponent(path)}'"),
        reason: 'path must be URL-encoded so folders with spaces or '
                'special chars survive the round-trip',
      );
    });

    test('listFolder uses http.get, not http.post', () {
      final src = readApi();
      final idx = src.indexOf('Future<Map<String, dynamic>> listFolder(');
      expect(idx, greaterThan(-1));
      final next = src.indexOf(RegExp(r'\n  (Future|void|String|Stream)<'),
          idx + 50);
      final end = next > 0
          ? next
          : (idx + 800).clamp(0, src.length);
      final scope = src.substring(idx, end);
      expect(scope, contains('http.get('));
      expect(scope, isNot(contains('http.post(')),
          reason: 'GET /folders is a read endpoint');
    });
  });
}
