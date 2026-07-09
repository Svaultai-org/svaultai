

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


List<Map<String, dynamic>> _fixtureFiles({
  int count = 3,
  String folder = 'Bank',
}) {
  return List.generate(
    count,
    (i) => <String, dynamic>{
      'file_id': 'f$i',
      'file_name': 'file$i.pdf',
      'saved_name': 'File $i',
      'relative_path': '$folder/file$i.pdf',
      'asset_type': 'file',
      'mime_type': 'application/pdf',
      'size_bytes': 1024 * (i + 1),
    },
  );
}


ChatMessage _listMsg({
  required List<Map<String, dynamic>> files,
  String title = 'Files inside Bank',
  String message = 'I found 3 files inside Bank.',
  int? totalCount,
  int? moreCount,
  String? requestedName,
}) {
  final payload = <String, dynamic>{
    'files': files,
    'title': title,
    'count': files.length,
    'total_count': totalCount ?? files.length,
  };
  if (moreCount != null) payload['more_count'] = moreCount;
  if (requestedName != null) payload['requested_name'] = requestedName;
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kVaultFileList,
    payload: payload,
  );
}


Future<void> _pumpList(
  WidgetTester tester, {
  required ChatMessage msg,
  void Function(ChatMessage)? onOpen,
  Size viewport = const Size(900, 700),
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
            child: VaultFileListCard(msg: msg, onOpen: onOpen),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('VaultFileListCard — header + count', () {
    testWidgets('renders the envelope title as the card header',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 3),
          title: 'Files inside Bank',
        ),
      );
      expect(find.text('Files inside Bank'), findsOneWidget);
    });

    testWidgets('shows the message field as the card body sentence',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 3),
          message: 'I found 3 files inside Bank.',
        ),
      );
      expect(find.text('I found 3 files inside Bank.'), findsOneWidget);
    });

    testWidgets('renders subtitle with total count when capped',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 25),
          totalCount: 60,
          moreCount: 35,
        ),
      );
      expect(find.text('60 files'), findsOneWidget);
    });
  });

  group('VaultFileListCard — file rows', () {
    testWidgets('renders one row per file with title + folder path',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 3, folder: 'Bank'),
        ),
      );
      
      expect(find.text('File 0'), findsOneWidget);
      expect(find.text('File 1'), findsOneWidget);
      expect(find.text('File 2'), findsOneWidget);
      
      expect(find.text('Bank/file0.pdf'), findsOneWidget);
      expect(find.text('Bank/file1.pdf'), findsOneWidget);
      expect(find.text('Bank/file2.pdf'), findsOneWidget);
      
      
      expect(
        find.byIcon(Icons.folder_outlined),
        findsNWidgets(3),
      );
    });

    testWidgets('falls back to file_name when saved_name is empty',
        (tester) async {
      final files = [
        <String, dynamic>{
          'file_id': 'f1',
          'file_name': 'statement.pdf',
          'saved_name': '',
          'relative_path': 'Bank/statement.pdf',
          'asset_type': 'file',
          'mime_type': 'application/pdf',
        },
      ];
      await _pumpList(
        tester,
        msg: _listMsg(files: files),
      );
      expect(find.text('statement.pdf'), findsOneWidget);
    });

    testWidgets('omits the folder-path line when relative_path is empty',
        (tester) async {
      final files = [
        <String, dynamic>{
          'file_id': 'f1',
          'file_name': 'loose.pdf',
          'saved_name': 'Loose',
          'asset_type': 'file',
          'mime_type': 'application/pdf',
        },
      ];
      await _pumpList(
        tester,
        msg: _listMsg(files: files),
      );
      expect(find.text('Loose'), findsOneWidget);
      
      expect(find.byIcon(Icons.folder_outlined), findsNothing);
    });
  });

  group('VaultFileListCard — +N more', () {
    testWidgets('renders "+N more results" copy when more_count > 0',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 25),
          totalCount: 60,
          moreCount: 35,
        ),
      );
      
      
      expect(
        find.textContaining('+35 more results'),
        findsOneWidget,
      );
      expect(
        find.textContaining('refine'),
        findsOneWidget,
      );
    });

    testWidgets('omits the more-results line when more_count is 0',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 3),
          totalCount: 3,
        ),
      );
      expect(find.textContaining('more results'), findsNothing);
    });
  });

  group('VaultFileListCard — overflow guards', () {
    testWidgets('50-card envelope does not overflow on desktop',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 25),  
          totalCount: 50,
          moreCount: 25,
        ),
        viewport: const Size(900, 700),
      );
      expect(tester.takeException(), isNull,
          reason: 'list must scroll inside its bounded box, never '
                  'overflow the bubble');
    });

    testWidgets('25-card envelope on a small mobile screen scrolls cleanly',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 25),
          totalCount: 25,
        ),
        viewport: const Size(360, 740),
      );
      expect(tester.takeException(), isNull);
      
      
      expect(find.text('File 0'), findsOneWidget);
    });

    testWidgets('disambiguation header appears for requested_name',
        (tester) async {
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 2),
          title: 'Files named "statement.pdf"',
          message:
              'I found 2 files named "statement.pdf". Which one?',
          requestedName: 'statement.pdf',
        ),
      );
      expect(
        find.text('Files named "statement.pdf"'),
        findsOneWidget,
      );
    });
  });

  group('VaultFileListCard — onOpen wiring', () {
    testWidgets(
        'tapping a row calls onOpen with a synthetic vault_file message',
        (tester) async {
      ChatMessage? captured;
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 2),
        ),
        onOpen: (m) => captured = m,
      );

      
      await tester.tap(find.byIcon(Icons.open_in_new).first);
      await tester.pumpAndSettle();

      expect(captured, isNotNull);
      expect(captured!.kind, equals(ChatMessage.kVaultFile));
      expect(captured!.fileId, equals('f0'));
      expect(captured!.fileName, equals('file0.pdf'));
      expect(captured!.mimeType, equals('application/pdf'));
      
      
      expect(
        (captured!.payload ?? const {})['relative_path'],
        equals('Bank/file0.pdf'),
      );
    });

    testWidgets('tapping the row InkWell also triggers onOpen',
        (tester) async {
      ChatMessage? captured;
      await _pumpList(
        tester,
        msg: _listMsg(
          files: _fixtureFiles(count: 2),
        ),
        onOpen: (m) => captured = m,
      );

      
      await tester.tap(find.text('File 1'));
      await tester.pumpAndSettle();

      expect(captured?.fileId, equals('f1'));
    });
  });

  group('Source guard: chat_models.dart exposes kVaultFileList', () {
    test('the constant exists and equals "vault_file_list"', () {
      expect(ChatMessage.kVaultFileList, equals('vault_file_list'));
    });

    test('isCard returns true for kVaultFileList', () {
      final msg = ChatMessage(
        'assistant',
        '',
        kind: ChatMessage.kVaultFileList,
      );
      expect(msg.isCard, isTrue);
    });
  });

  group('Source guard: chat_bubble.dart routes kVaultFileList', () {
    test('chat_bubble switch dispatches to VaultFileListCard', () {
      final file = File('lib/ui/chat/chat_bubble.dart');
      expect(file.existsSync(), isTrue);
      final src = file.readAsStringSync();
      expect(
        src,
        contains('ChatMessage.kVaultFileList'),
        reason: 'bubble must switch on kVaultFileList',
      );
      expect(
        src,
        contains('VaultFileListCard('),
        reason: 'bubble must construct VaultFileListCard for the '
                'vault_file_list kind',
      );
    });
  });

  group('Source guard: main.dart parses vault_file_list envelope', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('parser branches on type == vault_file_list', () {
      expect(
        readMain(),
        contains("type == 'vault_file_list'"),
        reason:
            'parser must branch on the new structured envelope type',
      );
    });

    test('parser threads files / title / more_count into payload', () {
      final src = readMain();
      expect(src, contains("decoded['files']"));
      expect(src, contains("decoded['title']"));
      expect(src, contains("decoded['more_count']"));
    });

    test('parser falls back to message field for unknown envelopes',
        () {
      
      
      final src = readMain();
      expect(
        src,
        contains("decoded['message']?.toString()"),
        reason:
            'parser must read a message fallback for older clients',
      );
    });
  });
}
