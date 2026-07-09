

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
  int? count,
  int? scannedCount,
  int? notScannedCount,
  List<Map<String, dynamic>>? actions,
}) {
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kCredentialFiles,
    payload: <String, dynamic>{
      'files': files,
      if (count != null) 'count': count,
      if (scannedCount != null) 'scanned_count': scannedCount,
      if (notScannedCount != null) 'not_scanned_count': notScannedCount,
      if (actions != null) 'actions': actions,
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
  };
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
            child: CredentialFileSearchCard(msg: msg, onOpen: onOpen),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('CredentialFileSearchCard — strict-verifier surface', () {
    testWidgets('renders simple "I found N…" title + count subtitle',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'f1', fileName: 'dump.txt',
              mimeType: 'text/plain', recordCount: 5,
              evidenceSource: 'file_text',
              evidenceSourceLabel: 'file text',
            ),
          ],
        ),
      );
      expect(
        find.text('I found 1 file with saved credentials.'),
        findsOneWidget,
      );
      expect(find.text('1 file'), findsOneWidget);
      
      expect(find.text('Files with saved credentials'), findsNothing);
      
      expect(find.textContaining('may contain'), findsNothing);
      expect(find.textContaining('Confirmed credential files'), findsNothing);
      expect(find.textContaining('Possible credential files'), findsNothing);
      expect(find.textContaining('Filename-only matches'), findsNothing);
      expect(find.textContaining('Only filename matches'), findsNothing);
      expect(find.text('STRONG'), findsNothing);
      expect(find.text('MEDIUM'), findsNothing);
      expect(find.text('WEAK'), findsNothing);
    });

    testWidgets('simple title uses plural when >1',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(fileId: 'a', fileName: 'a.txt', recordCount: 2),
            _verifiedRow(fileId: 'b', fileName: 'b.txt', recordCount: 4),
            _verifiedRow(fileId: 'c', fileName: 'c.txt', recordCount: 1),
          ],
        ),
      );
      expect(
        find.text('I found 3 files with saved credentials.'),
        findsOneWidget,
      );
      expect(find.text('3 files'), findsOneWidget);
    });

    testWidgets('row renders record-count + evidence-source + '
        'password-present pills', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'f1', fileName: 'dump.txt',
              recordCount: 12,
              evidenceSource: 'file_text',
              evidenceSourceLabel: 'file text',
              passwordPresent: true,
            ),
          ],
        ),
      );
      expect(find.text('12 records'), findsOneWidget);
      expect(find.text('evidence: file text'), findsOneWidget);
      expect(find.text('password present'), findsOneWidget);
    });

    testWidgets('row renders evidence source = OCR for screenshots',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'f1', fileName: 'screenshot.png',
              evidenceSource: 'ocr',
              evidenceSourceLabel: 'OCR',
            ),
          ],
        ),
      );
      expect(find.text('evidence: OCR'), findsOneWidget);
    });

    testWidgets('row renders evidence source = archive for archives',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'f1', fileName: 'backup.zip',
              evidenceSource: 'archive',
              evidenceSourceLabel: 'archive',
            ),
          ],
        ),
      );
      expect(find.text('evidence: archive'), findsOneWidget);
    });

    testWidgets('row renders service-name pills when present',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'f1', fileName: 'dump.txt',
              services: const ['Gmail', 'AOL', 'Wells Fargo'],
            ),
          ],
        ),
      );
      expect(find.text('Gmail'), findsOneWidget);
      expect(find.text('AOL'), findsOneWidget);
      expect(find.text('Wells Fargo'), findsOneWidget);
    });

    testWidgets('does NOT show the legacy privacy disclaimer',
        (tester) async {
      
      
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(fileId: 'f1', fileName: 'dump.txt'),
          ],
        ),
      );
      expect(
        find.textContaining(
            "I won't extract credentials unless you ask explicitly"),
        findsNothing,
      );
    });
  });

  group('CredentialFileSearchCard — file identity', () {
    testWidgets('renders saved_name when present', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'f1', fileName: 'pwd.txt',
              savedName: 'Old passwords',
              relativePath: 'Credentials/pwd.txt',
              mimeType: 'text/plain',
            ),
          ],
        ),
      );
      expect(find.text('Old passwords'), findsOneWidget);
      expect(find.text('Credentials/pwd.txt'), findsOneWidget);
    });

    testWidgets('falls back to file_name when saved_name is empty',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'f1', fileName: 'accounts.txt',
              savedName: '', mimeType: 'text/plain',
            ),
          ],
        ),
      );
      expect(find.text('accounts.txt'), findsOneWidget);
    });
  });

  group('CredentialFileSearchCard — defence in depth', () {
    testWidgets('NEVER surfaces password / token VALUES smuggled by '
        'a hostile payload', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            <String, dynamic>{
              ..._verifiedRow(fileId: 'f1', fileName: 'pwd.txt'),
              
              'password': 'hunter2',
              'value': 'super-secret-token-9999',
              'pin': '1234',
            },
          ],
        ),
      );
      expect(find.textContaining('hunter2'), findsNothing,
          reason: 'card MUST NOT render password values');
      expect(find.textContaining('super-secret-token-9999'), findsNothing,
          reason: 'card MUST NOT render arbitrary value-looking fields');
      expect(find.textContaining('1234'), findsNothing,
          reason: 'card MUST NOT render PIN values');
    });

    testWidgets('drops rows that carry legacy tier=filename_only',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            
            <String, dynamic>{
              'file_id': 'fname',
              'file_name': 'login.html',
              'mime_type': 'text/html',
              'tier': 'filename_only',
              'confidence': 'weak',
              'reasons': ['filename mentions "login"'],
            },
            
            _verifiedRow(fileId: 'verified', fileName: 'dump.txt'),
          ],
        ),
      );
      expect(find.text('dump.txt'), findsOneWidget);
      expect(find.text('login.html'), findsNothing);
      
      expect(find.text('1 file'), findsOneWidget);
    });

    testWidgets('drops rows that carry legacy tier=possible / '
        'confidence=medium', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            <String, dynamic>{
              'file_id': 'p',
              'file_name': 'maybe.txt',
              'mime_type': 'text/plain',
              'tier': 'possible',
              'confidence': 'medium',
              'reasons': ['contains password label'],
            },
            <String, dynamic>{
              'file_id': 'w',
              'file_name': 'login.html',
              'mime_type': 'text/html',
              'confidence': 'weak',
              'reasons': ['filename mentions "login"'],
            },
            _verifiedRow(fileId: 'verified', fileName: 'dump.txt'),
          ],
        ),
      );
      expect(find.text('maybe.txt'), findsNothing);
      expect(find.text('login.html'), findsNothing);
      expect(find.text('dump.txt'), findsOneWidget);
    });

    testWidgets('accepts rows where tier=confirmed or confidence=strong '
        'is explicitly set (back-compat)', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            <String, dynamic>{
              ..._verifiedRow(fileId: 'a', fileName: 'a.txt'),
              'tier': 'confirmed',
              'confidence': 'strong',
            },
          ],
        ),
      );
      expect(find.text('a.txt'), findsOneWidget);
      expect(find.text('1 file'), findsOneWidget);
    });
  });

  group('CredentialFileSearchCard — empty state', () {
    testWidgets('shows simple empty copy when scanned_count > 0',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: const <Map<String, dynamic>>[],
          scannedCount: 425,
        ),
      );
      expect(
        find.textContaining(
            "I didn't find any files with saved credentials"),
        findsOneWidget,
      );
      expect(find.text('No credential files found'), findsOneWidget);
      
      expect(
        find.textContaining('I only found filename matches'),
        findsNothing,
      );
      expect(find.textContaining('may contain'), findsNothing);
      expect(find.text('No verified credential files'), findsNothing);
    });

    testWidgets('shows conservative empty copy when nothing scanned yet',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: const <Map<String, dynamic>>[],
        ),
      );
      expect(
        find.textContaining(
            "didn't find any uploaded files with saved credential records"),
        findsOneWidget,
      );
      expect(
        find.textContaining('show my saved logins'),
        findsOneWidget,
      );
    });
  });

  group('CredentialFileSearchCard — onOpen', () {
    testWidgets('tapping a row synthesises a single-file ChatMessage',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [
            _verifiedRow(
              fileId: 'f-xyz', fileName: 'pwd.txt',
              mimeType: 'text/plain',
            ),
          ],
        ),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.byIcon(Icons.open_in_new).first);
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.kind, ChatMessage.kVaultFile);
      expect(captured!.fileId, 'f-xyz');
      expect(captured!.fileName, 'pwd.txt');
    });
  });

  group('CredentialFileSearchCard — overflow guards', () {
    testWidgets('100-file payload does not overflow', (tester) async {
      final many = List.generate(
        100,
        (i) => _verifiedRow(
          fileId: 'f$i', fileName: 'creds_$i.txt',
          mimeType: 'text/plain',
        ),
      );
      await _pump(
        tester,
        msg: _credentialsMsg(files: many),
        viewport: const Size(900, 700),
      );
      expect(tester.takeException(), isNull);
    });
  });

  group('CredentialFileSearchCard — unscanned banner removed (simple UI)', () {
    testWidgets('does NOT render "These results are incomplete" banner '
        'in normal mode', (tester) async {
      
      
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'f1', fileName: 'dump.txt')],
          scannedCount: 4,
          notScannedCount: 7,
        ),
      );
      expect(
        find.textContaining('These results are incomplete'),
        findsNothing,
      );
      expect(
        find.textContaining('text extraction is not available yet'),
        findsNothing,
      );
      
      expect(
        find.text('I found 1 file with saved credentials.'),
        findsOneWidget,
      );
    });

    testWidgets('does NOT render the unscanned footer when count is 0',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'f1', fileName: 'dump.txt')],
          scannedCount: 1,
          notScannedCount: 0,
        ),
      );
      expect(
        find.textContaining('text extraction is not available yet'),
        findsNothing,
      );
    });

    testWidgets('empty-state under partial scan keeps the simple copy '
        '(no debug footer)', (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: const <Map<String, dynamic>>[],
          scannedCount: 4,
          notScannedCount: 12,
        ),
      );
      expect(
        find.textContaining('text extraction is not available yet'),
        findsNothing,
      );
      expect(
        find.textContaining(
            "I didn't find any files with saved credentials"),
        findsOneWidget,
      );
    });
  });

  group('CredentialFileSearchCard — source guards', () {
    test('chat_models.dart exposes kCredentialFiles', () {
      expect(ChatMessage.kCredentialFiles, equals('credential_files'));
    });

    test('main.dart parser handles credential_files type', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'credential_files'"));
    });

    test('main.dart parser threads not_scanned_count into payload',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(
        src,
        contains("'not_scanned_count': decoded['not_scanned_count']"),
        reason: 'parser must surface the not_scanned_count so the card '
                'can render the separate honesty footer',
      );
    });

    test('chat_bubble.dart routes kCredentialFiles', () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('ChatMessage.kCredentialFiles'));
      expect(src, contains('CredentialFileSearchCard'));
    });

    test('chat_cards.dart card NEVER renders deprecated section copy',
        () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      
      
      expect(src, isNot(contains('Confirmed credential files')));
      expect(src, isNot(contains('Possible credential files')));
      expect(src, isNot(contains('Filename-only matches')));
      expect(src, isNot(contains('Only filename matches')));
      expect(src, isNot(contains('may contain login details')));
    });
  });
}
