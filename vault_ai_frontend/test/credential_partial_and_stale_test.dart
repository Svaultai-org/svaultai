

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _credentialsMsg({
  required List<Map<String, dynamic>> files,
  String message = '',
  bool? isPartial,
  bool? stale,
  int? scannedCount,
  int? notScannedCount,
}) {
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kCredentialFiles,
    payload: <String, dynamic>{
      'files': files,
      if (scannedCount != null) 'scanned_count': scannedCount,
      if (notScannedCount != null) 'not_scanned_count': notScannedCount,
      if (isPartial != null) 'is_partial': isPartial,
      if (stale != null) 'stale': stale,
    },
  );
}

Map<String, dynamic> _verifiedRow({
  required String fileId,
  required String fileName,
  String? savedName,
  String? relativePath,
  String? mimeType,
  int recordCount = 3,
  String evidenceSource = 'file_text',
  String evidenceSourceLabel = 'file text',
  bool passwordPresent = true,
  List<String> services = const [],
  List<String> duplicatePaths = const [],
}) {
  return <String, dynamic>{
    'file_id': fileId,
    'file_name': fileName,
    if (savedName != null) 'saved_name': savedName,
    if (relativePath != null) 'relative_path': relativePath,
    if (mimeType != null) 'mime_type': mimeType,
    'record_count': recordCount,
    'evidence_source': evidenceSource,
    'evidence_source_label': evidenceSourceLabel,
    'password_present': passwordPresent,
    'safe_service_names': services,
    'duplicate_paths': duplicatePaths,
  };
}


Future<void> _pump(
  WidgetTester tester, {
  required ChatMessage msg,
  void Function(ChatMessage)? onOpen,
  bool Function({
    required String intent,
    required String normalizedQuery,
  })? isDeepScanActive,
  Size viewport = const Size(900, 1000),
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
            child: CredentialFileSearchCard(
              msg: msg,
              onOpen: onOpen,
              isDeepScanActive: isDeepScanActive,
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('CredentialFileSearchCard — simple-UI title', () {
    testWidgets('one verified file → "I found 1 file with saved credentials."',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'dump.txt')],
          scannedCount: 425,
          notScannedCount: 0,
        ),
      );
      expect(
        find.text('I found 1 file with saved credentials.'),
        findsOneWidget,
      );
      
      expect(find.text('Files with saved credentials'), findsNothing);
      expect(
        find.text('Partial results from already scanned files'),
        findsNothing,
      );
    });

    testWidgets('three verified files → "I found 3 files with saved '
        'credentials."', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(fileId: 'a', fileName: 'a.txt'),
            _verifiedRow(fileId: 'b', fileName: 'b.txt'),
            _verifiedRow(fileId: 'c', fileName: 'c.txt'),
          ],
          scannedCount: 425,
          notScannedCount: 0,
        ),
      );
      expect(
        find.text('I found 3 files with saved credentials.'),
        findsOneWidget,
      );
    });

    testWidgets('is_partial=true STILL uses the simple title — no '
        '"Partial results" debug header', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'a.txt')],
          scannedCount: 194,
          notScannedCount: 231,
          isPartial: true,
        ),
      );
      expect(
        find.text('I found 1 file with saved credentials.'),
        findsOneWidget,
      );
      expect(
        find.text('Partial results from already scanned files'),
        findsNothing,
      );
      expect(
        find.textContaining('These results are incomplete'),
        findsNothing,
      );
    });
  });

  group('CredentialFileSearchCard — debug copy removed', () {
    testWidgets("does NOT render \"I won't extract credentials\" footer",
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'a.txt')],
          scannedCount: 425,
          notScannedCount: 0,
        ),
      );
      expect(
        find.textContaining("won't extract credentials"),
        findsNothing,
      );
    });

    testWidgets('does NOT render "Some files could not be scanned" footer',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'a.txt')],
          scannedCount: 194,
          notScannedCount: 231,
          isPartial: true,
        ),
      );
      expect(
        find.textContaining('Some files could not be scanned'),
        findsNothing,
      );
    });

    testWidgets('does NOT render "Scan remaining files" button', (tester) async {
      bool tapped = false;
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'a.txt')],
          scannedCount: 194,
          notScannedCount: 231,
          isPartial: true,
        ),
      );
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.textContaining('Scan remaining files'), findsNothing);
      expect(tapped, false);
    });

    testWidgets('does NOT render any debug "These results are incomplete" hint',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'a.txt')],
          scannedCount: 50,
          notScannedCount: 375,
          isPartial: true,
        ),
      );
      expect(
        find.textContaining('These results are incomplete'),
        findsNothing,
      );
    });
  });

  group('CredentialFileSearchCard — stale + live scan = hidden', () {
    testWidgets('stale=true + host says scan active => card is HIDDEN '
        '(SizedBox.shrink)', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(fileId: 'a', fileName: 'dump.txt'),
            _verifiedRow(fileId: 'b', fileName: 'two.txt'),
          ],
          scannedCount: 425,
          notScannedCount: 0,
          stale: true,
        ),
        isDeepScanActive: ({
          required String intent,
          required String normalizedQuery,
        }) => true,
      );
      
      expect(find.text('dump.txt'), findsNothing);
      expect(find.text('two.txt'), findsNothing);
      
      expect(
        find.text('I found 2 files with saved credentials.'),
        findsNothing,
      );
      expect(find.textContaining('Older results'), findsNothing);
    });

    testWidgets('stale=true + no host predicate => legacy fallback '
        '(card still renders with rows)', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'dump.txt')],
          scannedCount: 425,
          notScannedCount: 0,
          stale: true,
        ),
      );
      
      
      expect(
        find.text('I found 1 file with saved credentials.'),
        findsOneWidget,
      );
      expect(find.text('dump.txt'), findsOneWidget);
    });

    testWidgets('stale=false renders normally', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'dump.txt')],
          scannedCount: 425,
          notScannedCount: 0,
        ),
      );
      expect(
        find.text('I found 1 file with saved credentials.'),
        findsOneWidget,
      );
    });
  });

  group('CredentialFileSearchCard — duplicate copies chip (preserved)', () {
    testWidgets('renders "same file found in 2 folders" for one dup',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'a', fileName: 'dump.txt',
              duplicatePaths: const ['Backups/Old/dump.txt'],
            ),
          ],
          scannedCount: 425,
          notScannedCount: 0,
        ),
      );
      expect(
        find.text('same file found in 2 folders'),
        findsOneWidget,
      );
    });

    testWidgets('no chip when duplicate_paths empty', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'dump.txt')],
          scannedCount: 425,
          notScannedCount: 0,
        ),
      );
      expect(find.textContaining('same file found in'), findsNothing);
    });

    testWidgets('chip path strings NEVER leak credential VALUES',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            <String, dynamic>{
              ..._verifiedRow(
                fileId: 'a', fileName: 'dump.txt',
                duplicatePaths: const ['Backups/Old/dump.txt'],
              ),
              
              'password': 'hunter2-leak',
              'token': 'tok-leak-99',
            },
          ],
          scannedCount: 425,
          notScannedCount: 0,
        ),
      );
      expect(find.textContaining('hunter2-leak'), findsNothing);
      expect(find.textContaining('tok-leak-99'), findsNothing);
    });
  });

  
  group('source guards — payload wiring + simple-UI copy', () {
    test('lib/ does not hardcode the literal 231 anywhere', () async {
      final libDir = Directory('lib');
      expect(libDir.existsSync(), isTrue);
      final files = libDir
          .listSync(recursive: true)
          .whereType<File>()
          .where((f) => f.path.toLowerCase().endsWith('.dart'))
          .toList();
      for (final f in files) {
        final src = f.readAsStringSync();
        final body = src
            .replaceAll(RegExp(r'/\*.*?\*/', dotAll: true), '')
            .split('\n')
            .map((line) {
              final idx = line.indexOf('//');
              return idx == -1 ? line : line.substring(0, idx);
            })
            .join('\n');
        final hits = RegExp(r'\b231\b').allMatches(body).length;
        expect(
          hits, 0,
          reason: 'literal "231" in ${f.path} — '
              'not_scanned_count must be dynamic',
        );
      }
    });

    test('chat_cards.dart references is_partial + stale + duplicate_paths',
        () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(src, contains("p['is_partial']"));
      expect(src, contains("p['stale']"));
      expect(src, contains("file['duplicate_paths']"));
    });

    test('chat_cards.dart uses the simple-UI title pattern', () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(
        src,
        contains('I found '),
        reason: 'simple-UI title must use the natural "I found N…" '
            'phrasing, not the debug "Files with saved credentials"',
      );
    });

    test('main.dart parser threads is_partial into the payload',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("'is_partial': decoded['is_partial']"));
      expect(src, contains("'is_partial': envelope['is_partial']"));
    });

    test('main.dart declares _markPriorCredentialCardsStale + '
        'wires it into _kickOffDeepAnswerScan', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('_markPriorCredentialCardsStale'));
      final idx = src.indexOf('Future<void> _kickOffDeepAnswerScan');
      expect(idx, greaterThan(-1));
      final endIdx = src.indexOf(
        'void _markPriorCredentialCardsStale', idx,
      );
      final body = src.substring(
        idx, endIdx == -1 ? src.length : endIdx,
      );
      expect(body, contains('_markPriorCredentialCardsStale()'));
    });
  });
}
