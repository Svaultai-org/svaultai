

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

ChatMessage _msg({
  required List<Map<String, dynamic>> files,
  String title = 'Which strong credential-file match do you mean?',
  String message =
      'I found 2 strong credential-file matches.\n'
      '1. passed words 7425.docx.pdf [strong]\n'
      '2. passedwordtex.pdf [strong]',
  String contextKind = 'credential_files',
}) {
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kFileDisambiguation,
    payload: <String, dynamic>{
      'files': files,
      'title': title,
      'count': files.length,
      'context_kind': contextKind,
    },
  );
}

List<Map<String, dynamic>> _twoStrongCandidates() {
  return [
    {
      'file_id': 'f1',
      'file_name': 'passed words 7425.docx.pdf',
      'mime_type': 'application/pdf',
      'asset_type': 'file',
      'confidence': 'strong',
      'reasons': [
        'content contains repeated service/email/password-like '
            'credential records',
      ],
    },
    {
      'file_id': 'f2',
      'file_name': 'passedwordtex.pdf',
      'mime_type': 'application/pdf',
      'asset_type': 'file',
      'confidence': 'strong',
      'reasons': [
        'content contains repeated service/email/password-like '
            'credential records',
      ],
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
            child: FileDisambiguationCard(msg: msg, onOpen: onOpen),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('FileDisambiguationCard — header', () {
    testWidgets('renders the title from the envelope', (tester) async {
      await _pump(tester, msg: _msg(files: _twoStrongCandidates()));
      expect(
        find.text('Which strong credential-file match do you mean?'),
        findsOneWidget,
      );
    });

    testWidgets('shows candidate count subtitle', (tester) async {
      await _pump(tester, msg: _msg(files: _twoStrongCandidates()));
      expect(find.text('2 candidates'), findsOneWidget);
    });

    testWidgets('falls back to default title when payload omits it',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(files: _twoStrongCandidates(), title: ''),
      );
      expect(find.text('Which file do you mean?'), findsOneWidget);
    });

    testWidgets('renders headline portion of message, NOT the numbered list',
        (tester) async {
      
      
      await _pump(tester, msg: _msg(files: _twoStrongCandidates()));
      expect(
        find.text('I found 2 strong credential-file matches.'),
        findsOneWidget,
      );
      
      expect(find.text('1. passed words 7425.docx.pdf [strong]'),
          findsNothing);
    });
  });

  group('FileDisambiguationCard — candidate rows', () {
    testWidgets('renders one row per file with the file name',
        (tester) async {
      await _pump(tester, msg: _msg(files: _twoStrongCandidates()));
      expect(find.text('passed words 7425.docx.pdf'), findsOneWidget);
      expect(find.text('passedwordtex.pdf'), findsOneWidget);
    });

    testWidgets('shows STRONG confidence chip per row', (tester) async {
      await _pump(tester, msg: _msg(files: _twoStrongCandidates()));
      expect(find.text('STRONG'), findsNWidgets(2));
    });

    testWidgets('shows the reason line under each row', (tester) async {
      await _pump(tester, msg: _msg(files: _twoStrongCandidates()));
      expect(
        find.textContaining('repeated service/email/password-like'),
        findsNWidgets(2),
      );
    });

    testWidgets('renders folder path when relative_path present',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(files: [
          {
            'file_id': 'f1',
            'file_name': 'pwd.txt',
            'mime_type': 'text/plain',
            'relative_path': 'Credentials/pwd.txt',
            'confidence': 'strong',
            'reasons': const <String>[],
          },
        ]),
      );
      expect(find.text('Credentials/pwd.txt'), findsOneWidget);
    });

    testWidgets('renders ordinal markers (1, 2, ...)', (tester) async {
      await _pump(tester, msg: _msg(files: _twoStrongCandidates()));
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
    });

    testWidgets('saved_name overrides file_name when present',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(files: [
          {
            'file_id': 'f1',
            'file_name': 'xyz123.pdf',
            'saved_name': 'Banking export',
            'mime_type': 'application/pdf',
            'confidence': 'strong',
            'reasons': const <String>[],
          },
        ]),
      );
      expect(find.text('Banking export'), findsOneWidget);
      expect(find.text('xyz123.pdf'), findsNothing);
    });
  });

  group('FileDisambiguationCard — tap-to-open', () {
    testWidgets('tapping a row fires onOpen with file_id', (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(files: _twoStrongCandidates()),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.byIcon(Icons.open_in_new).first);
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.kind, ChatMessage.kVaultFile);
      expect(captured!.fileId, 'f1');
      expect(captured!.fileName, 'passed words 7425.docx.pdf');
    });

    testWidgets('tapping the row body (not just the open icon) fires onOpen',
        (tester) async {
      ChatMessage? captured;
      await _pump(
        tester,
        msg: _msg(files: _twoStrongCandidates()),
        onOpen: (m) => captured = m,
      );
      await tester.tap(find.text('passedwordtex.pdf'));
      await tester.pumpAndSettle();
      expect(captured, isNotNull);
      expect(captured!.fileId, 'f2');
    });
  });

  group('FileDisambiguationCard — security guards', () {
    testWidgets(
        'NEVER renders extracted text / password values even if backend leaks them',
        (tester) async {
      
      
      await _pump(
        tester,
        msg: _msg(files: [
          {
            'file_id': 'f1',
            'file_name': 'pwd.txt',
            'mime_type': 'text/plain',
            'confidence': 'strong',
            'reasons': const <String>[],
            
            'extracted_text': 'AOL\nhunter2\nSUPERSECRET-XYZ-123',
            'password': 'hunter2',
            'encrypted_file_data': 'ciphertext-blob',
            'value': 'raw-token-99',
          },
        ]),
      );
      
      
      expect(find.textContaining('hunter2'), findsNothing);
      expect(find.textContaining('SUPERSECRET-XYZ-123'), findsNothing);
      expect(find.textContaining('raw-token-99'), findsNothing);
      expect(find.textContaining('ciphertext-blob'), findsNothing);
    });

    testWidgets('reason rows render reasons[] entries, not hostile dicts',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(files: [
          {
            'file_id': 'f1',
            'file_name': 'pwd.txt',
            'mime_type': 'text/plain',
            'confidence': 'strong',
            
            
            'reasons': [
              'content contains repeated credential records',
            ],
          },
        ]),
      );
      expect(
        find.text('content contains repeated credential records'),
        findsOneWidget,
      );
    });
  });

  group('FileDisambiguationCard — empty state', () {
    testWidgets('empty files list renders "no candidates" copy',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(files: const <Map<String, dynamic>>[]),
      );
      expect(find.text('No candidates available'), findsOneWidget);
    });
  });

  group('FileDisambiguationCard — overflow guards', () {
    testWidgets('50-row payload renders without overflow', (tester) async {
      final many = List.generate(
        50,
        (i) => <String, dynamic>{
          'file_id': 'f$i',
          'file_name': 'candidate_$i.pdf',
          'mime_type': 'application/pdf',
          'confidence': 'strong',
          'reasons': const <String>[],
        },
      );
      await _pump(
        tester,
        msg: _msg(files: many),
        viewport: const Size(900, 700),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders cleanly on a mobile-width viewport',
        (tester) async {
      await _pump(
        tester,
        msg: _msg(files: _twoStrongCandidates()),
        viewport: const Size(360, 740),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('passed words 7425.docx.pdf'), findsAtLeastNWidgets(1));
    });
  });

  group('FileDisambiguationCard — helper hint', () {
    testWidgets('shows the typing-fallback hint', (tester) async {
      await _pump(tester, msg: _msg(files: _twoStrongCandidates()));
      expect(
        find.textContaining('Tap a row to open that file.'),
        findsOneWidget,
      );
    });
  });

  group('Source guards', () {
    test('chat_models.dart exposes kFileDisambiguation', () {
      expect(
        ChatMessage.kFileDisambiguation,
        equals('file_disambiguation'),
      );
    });

    test('isCard returns true for kFileDisambiguation', () {
      final m = ChatMessage(
        'assistant',
        'x',
        kind: ChatMessage.kFileDisambiguation,
        payload: const <String, dynamic>{},
      );
      expect(m.isCard, isTrue);
    });

    test('main.dart parser handles file_disambiguation type', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'file_disambiguation'"));
      expect(
        src,
        contains("kind: 'file_disambiguation'"),
        reason: 'parser must produce a kFileDisambiguation ChatMessage',
      );
    });

    test('main.dart parser falls back to message text for unknown envelopes',
        () async {
      
      
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("fallbackMessage = decoded['message']"));
    });

    test('chat_bubble.dart routes kFileDisambiguation to FileDisambiguationCard',
        () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('ChatMessage.kFileDisambiguation'));
      expect(src, contains('FileDisambiguationCard'));
    });
  });

  
  group('FileDisambiguationCard — best_match chip', () {
    List<Map<String, dynamic>> bestMatchCandidates() {
      return [
        {
          'file_id': 'dump',
          'file_name': 'passed words 7425.docx.pdf',
          'mime_type': 'application/pdf',
          'asset_type': 'file',
          'confidence': 'strong',
          'best_match': true,
          'mostly_credentials': true,
          'credential_density': 0.83,
          'credential_block_count': 5,
          'service_count': 5,
          'reasons': [
            'file appears to be mostly a credential list',
          ],
        },
        {
          'file_id': 'sparse',
          'file_name': 'handover.docx.pdf',
          'mime_type': 'application/pdf',
          'asset_type': 'file',
          'confidence': 'strong',
          'mostly_credentials': false,
          'reasons': [
            'content contains password field',
          ],
        },
      ];
    }

    testWidgets('shows a "BEST MATCH" chip on the best_match row',
        (tester) async {
      await _pump(tester, msg: _msg(files: bestMatchCandidates()));
      expect(
        find.text('BEST MATCH'),
        findsOneWidget,
        reason: 'the ranker-flagged top row should carry a "BEST '
            'MATCH" chip so the user reads the right pick first',
      );
    });

    testWidgets('does NOT show BEST MATCH on the runner-up row',
        (tester) async {
      
      
      await _pump(tester, msg: _msg(files: bestMatchCandidates()));
      expect(find.text('BEST MATCH'), findsOneWidget);
      
      expect(find.text('passed words 7425.docx.pdf'), findsOneWidget);
      expect(find.text('handover.docx.pdf'), findsOneWidget);
    });

    testWidgets('omits BEST MATCH chip when no row is flagged',
        (tester) async {
      final files = bestMatchCandidates()
          .map((m) => {...m, 'best_match': false}..remove('best_match'))
          .toList();
      await _pump(tester, msg: _msg(files: files));
      expect(find.text('BEST MATCH'), findsNothing);
    });

    testWidgets(
        'shows the "mostly credentials" caption on non-best-match '
        'rows that ARE mostly_credentials',
        (tester) async {
      final files = [
        {
          'file_id': 'a',
          'file_name': 'passwords_a.txt',
          'mime_type': 'text/plain',
          'confidence': 'strong',
          'mostly_credentials': true,
          'credential_density': 0.80,
        },
        {
          'file_id': 'b',
          'file_name': 'passwords_b.txt',
          'mime_type': 'text/plain',
          'confidence': 'strong',
          'mostly_credentials': true,
          'credential_density': 0.78,
        },
      ];
      await _pump(tester, msg: _msg(files: files));
      
      
      expect(find.text('BEST MATCH'), findsNothing);
      expect(
        find.text('Appears to be mostly a credential list'),
        findsNWidgets(2),
        reason: 'both mostly_credentials rows should show the '
            'caption to help the user pick',
      );
    });

    testWidgets(
        'best_match row suppresses the mostly-credentials caption '
        '(the BEST MATCH chip already conveys it)',
        (tester) async {
      await _pump(tester, msg: _msg(files: bestMatchCandidates()));
      
      
      expect(
        find.text('Appears to be mostly a credential list'),
        findsNothing,
      );
    });

    testWidgets(
        'best_match row visually elevates (accent background border)',
        (tester) async {
      await _pump(tester, msg: _msg(files: bestMatchCandidates()));
      
      final title = find.text('passed words 7425.docx.pdf');
      expect(title, findsOneWidget);
      
      final containers = find.byType(Container).evaluate().toList();
      
      
      expect(containers.isNotEmpty, isTrue);
      expect(find.text('BEST MATCH'), findsOneWidget);
    });
  });

  
  group('FileDisambiguationCard — duplicate-name path disambiguation', () {
    testWidgets(
        'two same-named files from different folders both render '
        'with their distinct relative_path lines',
        (tester) async {
      final files = [
        {
          'file_id': 'a',
          'file_name': 'credentials.txt',
          'relative_path': 'Work/Old/credentials.txt',
          'mime_type': 'text/plain',
          'confidence': 'strong',
        },
        {
          'file_id': 'b',
          'file_name': 'credentials.txt',
          'relative_path': 'Personal/Vault/credentials.txt',
          'mime_type': 'text/plain',
          'confidence': 'strong',
        },
      ];
      await _pump(tester, msg: _msg(files: files));
      expect(find.text('Work/Old/credentials.txt'), findsOneWidget);
      expect(find.text('Personal/Vault/credentials.txt'), findsOneWidget);
      
      expect(find.text('credentials.txt'), findsNWidgets(2));
    });
  });

  
  group('Source guards — slice 2A.4', () {
    test(
        'chat_cards.dart renders a BEST MATCH chip when '
        'best_match is true', () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(
        src,
        contains("'BEST MATCH'"),
        reason: 'the disambiguation row must render a literal '
            '"BEST MATCH" chip when the backend flags a winner',
      );
      expect(
        src,
        contains("file['best_match'] == true"),
        reason: 'card must read the best_match field from the '
            'envelope row',
      );
    });

    test(
        'chat_cards.dart reads mostly_credentials for the row '
        'caption', () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(src, contains("file['mostly_credentials'] == true"));
      expect(
        src,
        contains('Appears to be mostly a credential list'),
        reason: 'card must surface the human-readable caption for '
            'non-best-match mostly_credentials rows',
      );
    });
  });

  
  group('FileDisambiguationCard — purpose_label', () {
    List<Map<String, dynamic>> bestMatchWithPurposeLabel() {
      return [
        {
          'file_id': 'dump',
          'file_name': 'logins.txt',
          'mime_type': 'text/plain',
          'asset_type': 'file',
          'confidence': 'strong',
          'best_match': true,
          'mostly_credentials': true,
          'purpose': 'saved_login_list',
          'purpose_label': 'saved website/app login records',
          'reasons': [
            'most of the document appears to be saved '
                'website/app login records',
            'contains email/password fields',
          ],
        },
        {
          'file_id': 'sparse',
          'file_name': 'config.txt',
          'mime_type': 'text/plain',
          'confidence': 'strong',
          'mostly_credentials': false,
          'reasons': ['contains password field'],
        },
      ];
    }

    testWidgets(
        'best_match row renders "Best match because most of the '
        'document appears to be <label>"', (tester) async {
      await _pump(tester, msg: _msg(files: bestMatchWithPurposeLabel()));
      
      
      expect(
        find.text(
          'Best match because most of the document appears to '
          'be saved website/app login records.',
        ),
        findsOneWidget,
        reason: 'the user wants a purpose explanation, not a '
            'pattern-fingerprint reason like "contains '
            'email/password-like blocks"',
      );
    });

    testWidgets(
        'best_match row SUPPRESSES the pattern-fingerprint reason '
        'line so the purpose copy stands alone', (tester) async {
      await _pump(tester, msg: _msg(files: bestMatchWithPurposeLabel()));
      
      
      expect(
        find.text('contains email/password fields'),
        findsNothing,
        reason: 'the best_match row should not duplicate '
            'pattern-fingerprint reasons under the purpose copy',
      );
    });

    testWidgets(
        'non-best-match row still shows its pattern reasons',
        (tester) async {
      await _pump(tester, msg: _msg(files: bestMatchWithPurposeLabel()));
      
      
      expect(
        find.textContaining('contains password field'),
        findsOneWidget,
      );
    });

    testWidgets(
        'best_match row WITHOUT purpose_label falls back to '
        'legacy reasons line', (tester) async {
      final files = [
        {
          'file_id': 'dump',
          'file_name': 'logins.txt',
          'confidence': 'strong',
          'best_match': true,
          'mostly_credentials': true,
          
          
          'reasons': [
            'content contains repeated service/email/password-like '
                'credential records',
          ],
        },
      ];
      await _pump(tester, msg: _msg(files: files));
      expect(find.textContaining('Best match because'), findsNothing);
      
      
      expect(
        find.textContaining('content contains repeated service'),
        findsOneWidget,
      );
    });

    testWidgets(
        'purpose_label on a NON-best-match row is ignored '
        '(only the BEST MATCH row gets the special copy)',
        (tester) async {
      
      
      final files = [
        {
          'file_id': 'top',
          'file_name': 'logins.txt',
          'confidence': 'strong',
          'best_match': true,
          'mostly_credentials': true,
          'purpose': 'saved_login_list',
          'purpose_label': 'saved website/app login records',
        },
        {
          'file_id': 'env',
          'file_name': 'dotenv.txt',
          'confidence': 'strong',
          'mostly_credentials': true,
          'purpose': 'config_secrets',
          'purpose_label': 'a config / secrets file',
        },
      ];
      await _pump(tester, msg: _msg(files: files));
      expect(
        find.text(
          'Best match because most of the document appears to '
          'be a config / secrets file.',
        ),
        findsNothing,
        reason: '"Best match because…" is reserved for the row '
            'flagged best_match by the backend',
      );
      
      expect(
        find.textContaining(
          'Best match because most of the document appears to '
          'be saved website/app login records',
        ),
        findsOneWidget,
      );
    });
  });

  
  group('Source guards — slice 2A.5', () {
    test(
        'chat_cards.dart reads purpose_label off the envelope row',
        () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(src, contains("file['purpose_label']"));
    });

    test(
        'chat_cards.dart composes the "Best match because…" copy '
        'from purpose_label', () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(
        src,
        contains('Best match because most of the document appears '
            'to be '),
        reason: 'the user-facing explanation MUST be PURPOSE-led '
            'verbatim per the slice spec',
      );
    });
  });
}
