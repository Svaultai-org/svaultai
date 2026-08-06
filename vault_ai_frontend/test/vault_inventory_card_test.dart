

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _inventoryMsg({
  int totalFiles = 312,
  int totalBytes = 4831838208,
  int folderCount = 8,
  List<Map<String, dynamic>>? topFolders,
  Map<String, dynamic>? typeCounts,
  List<Map<String, dynamic>>? recentFiles,
  String? message,
}) {
  return ChatMessage(
    'assistant',
    message ??
        'Your vault has $totalFiles files across $folderCount folders.',
    kind: ChatMessage.kVaultInventory,
    payload: <String, dynamic>{
      'total_files': totalFiles,
      'total_bytes': totalBytes,
      'folder_count': folderCount,
      'top_folders': topFolders ??
          [
            {'name': 'My Life Backup', 'file_count': 218},
            {'name': 'Documents', 'file_count': 42},
            {'name': 'Photos', 'file_count': 31},
          ],
      'type_counts': typeCounts ??
          {
            'PDFs': 87,
            'Images': 142,
            'Videos': 23,
            'Audio': 12,
            'Documents': 18,
            'Scripts': 8,
            'Archives': 4,
          },
      'recent_files': recentFiles ??
          [
            {
              'file_id': 'f1',
              'file_name': 'passport.pdf',
              'saved_name': 'Maureen passport',
              'mime_type': 'application/pdf',
              'asset_type': 'file',
              'relative_path': 'Travel/passport.pdf',
            },
            {
              'file_id': 'f2',
              'file_name': 'maureen id back.jpg',
              'saved_name': '',
              'mime_type': 'image/jpeg',
              'asset_type': 'file',
              'relative_path': 'Identity/maureen id back.jpg',
            },
          ],
    },
  );
}


Future<void> _pump(
  WidgetTester tester, {
  required ChatMessage msg,
  void Function(ChatMessage)? onOpen,
  Size viewport = const Size(900, 900),
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
            child: VaultInventoryCard(msg: msg, onOpen: onOpen),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('VaultInventoryCard — totals + headline', () {
    testWidgets('renders the hero count + folder count', (tester) async {
      await _pump(tester, msg: _inventoryMsg());
      expect(
        find.textContaining('312 files across 8 folders'),
        findsOneWidget,
      );
    });

    testWidgets('shows the total-files pill', (tester) async {
      await _pump(tester, msg: _inventoryMsg(totalFiles: 312));
      expect(find.text('312 files'), findsOneWidget);
    });

    testWidgets('handles singular file/folder copy', (tester) async {
      await _pump(
        tester,
        msg: _inventoryMsg(
          totalFiles: 1,
          folderCount: 1,
          topFolders: [
            {'name': 'Solo', 'file_count': 1},
          ],
          typeCounts: const {'PDFs': 1},
          recentFiles: const [],
        ),
      );
      expect(
        find.textContaining('1 file across 1 folder'),
        findsOneWidget,
      );
    });
  });

  group('VaultInventoryCard — type breakdown', () {
    testWidgets('renders only non-zero buckets', (tester) async {
      await _pump(
        tester,
        msg: _inventoryMsg(
          typeCounts: const {
            'PDFs': 5,
            'Images': 0, 
            'Videos': 2,
          },
          recentFiles: const [],
          topFolders: const [],
        ),
      );
      expect(find.text('5 PDFs'), findsOneWidget);
      expect(find.text('2 Videos'), findsOneWidget);
      expect(find.textContaining('Images'), findsNothing);
    });
  });

  group('VaultInventoryCard — top folders', () {
    testWidgets('renders one row per folder with count', (tester) async {
      await _pump(tester, msg: _inventoryMsg());
      expect(find.text('My Life Backup'), findsOneWidget);
      expect(find.text('218 files'), findsOneWidget);
      expect(find.text('Documents'), findsOneWidget);
      expect(find.text('42 files'), findsOneWidget);
      expect(find.text('Photos'), findsOneWidget);
      expect(find.text('31 files'), findsOneWidget);
    });
  });

  group('VaultInventoryCard — recent files', () {
    testWidgets('renders title + folder path per recent row',
        (tester) async {
      await _pump(tester, msg: _inventoryMsg());
      expect(find.text('Maureen passport'), findsOneWidget);
      
      expect(find.text('maureen id back.jpg'), findsOneWidget);
      expect(find.text('Travel/passport.pdf'), findsOneWidget);
      expect(find.text('Identity/maureen id back.jpg'), findsOneWidget);
    });

    testWidgets('tapping a recent row fires onOpen with synthesised msg',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _inventoryMsg(),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.byIcon(Icons.open_in_new).first);
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.kind, ChatMessage.kVaultFile);
      expect(captured!.fileId, 'f1');
      expect(captured!.fileName, 'passport.pdf');
    });
  });

  group('VaultInventoryCard — empty state', () {
    testWidgets('empty vault renders friendly empty copy', (tester) async {
      await _pump(
        tester,
        msg: ChatMessage(
          'assistant',
          "I don't see any uploaded files in your vault yet.",
          kind: ChatMessage.kVaultInventory,
          payload: const <String, dynamic>{
            'total_files': 0,
            'total_bytes': 0,
            'folder_count': 0,
            'top_folders': <Map<String, dynamic>>[],
            'type_counts': <String, dynamic>{},
            'recent_files': <Map<String, dynamic>>[],
          },
        ),
      );
      expect(
        find.text("I don't see any uploaded files in your vault yet."),
        findsOneWidget,
      );
      expect(find.text('Empty vault'), findsOneWidget);
    });

    testWidgets('NEVER renders an "I can\'t list your files" message',
        (tester) async {
      await _pump(tester, msg: _inventoryMsg());
      expect(
        find.textContaining("can't list"),
        findsNothing,
        reason: 'spec rule: SVaultAI must know what is in the vault',
      );
    });
  });

  group('VaultInventoryCard — overflow guards', () {
    testWidgets('100 recent files do not overflow', (tester) async {
      final manyRecent = List.generate(
        100,
        (i) => <String, dynamic>{
          'file_id': 'f$i',
          'file_name': 'file_$i.pdf',
          'saved_name': 'File $i',
          'mime_type': 'application/pdf',
          'asset_type': 'file',
        },
      );
      await _pump(
        tester,
        msg: _inventoryMsg(recentFiles: manyRecent),
        viewport: const Size(900, 700),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders cleanly on a mobile-width viewport',
        (tester) async {
      await _pump(
        tester,
        msg: _inventoryMsg(),
        viewport: const Size(360, 740),
      );
      expect(tester.takeException(), isNull);
      
      expect(find.textContaining('312 files'), findsAtLeastNWidgets(1));
    });
  });

  group('VaultInventoryCard — source guards', () {
    test('chat_models.dart exposes kVaultInventory', () {
      expect(ChatMessage.kVaultInventory, equals('vault_inventory'));
    });

    test('parser branch is wired into main.dart', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(
        src,
        contains("type == 'vault_inventory'"),
        reason:
            'main.dart must parse the vault_inventory envelope into a '
            'kVaultInventory ChatMessage',
      );
    });

    test('chat_bubble.dart routes kVaultInventory to VaultInventoryCard',
        () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('ChatMessage.kVaultInventory'));
      expect(src, contains('VaultInventoryCard'));
    });

    test('isCard returns true for kVaultInventory', () {
      final m = ChatMessage(
        'assistant',
        'x',
        kind: ChatMessage.kVaultInventory,
        payload: const <String, dynamic>{},
      );
      expect(m.isCard, isTrue);
    });
  });
}
