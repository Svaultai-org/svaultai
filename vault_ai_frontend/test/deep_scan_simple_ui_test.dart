

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _progressMsg({
  required Map<String, dynamic> coverage,
  String status = 'scanning',
  String? blockerReason,
  String text = "Let me check your vault properly. "
      "I'll read the files before giving the result.",
}) {
  return ChatMessage(
    'assistant', text,
    kind: ChatMessage.kDeepAnswerProgress,
    payload: <String, dynamic>{
      'job_id': 'job-simple',
      'status': status,
      'progress': <String, dynamic>{
        'coverage':      coverage,
        if (blockerReason != null) 'blocker_reason': blockerReason,
      },
    },
  );
}


ChatMessage _credentialsMsg({
  required List<Map<String, dynamic>> files,
  int scannedCount = 194,
  int notScannedCount = 231,
  bool isPartial = true,
}) {
  return ChatMessage(
    'assistant', '',
    kind: ChatMessage.kCredentialFiles,
    payload: <String, dynamic>{
      'files': files,
      'scanned_count': scannedCount,
      'not_scanned_count': notScannedCount,
      'is_partial': isPartial,
      'actions': <Map<String, dynamic>>[
        <String, dynamic>{
          'type': 'scan_remaining',
          'label': 'Scan remaining files',
        },
      ],
    },
  );
}

Map<String, dynamic> _verifiedRow(String name) => <String, dynamic>{
      'file_id': 'fid-$name',
      'file_name': name,
      'record_count': 3,
      'evidence_source': 'file_text',
      'evidence_source_label': 'file text',
      'password_present': true,
      'safe_service_names': const <String>[],
      'duplicate_paths': const <String>[],
    };


Future<void> _pumpProgress(WidgetTester tester, ChatMessage msg) async {
  tester.view.physicalSize = const Size(900, 1200);
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
            child: DeepAnswerProgressCard(
              msg: msg,
              pollInterval: const Duration(seconds: 60),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}


Future<void> _pumpCredentials(WidgetTester tester, ChatMessage msg) async {
  tester.view.physicalSize = const Size(900, 1200);
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
            child: CredentialFileSearchCard(msg: msg),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  
  
  setUp(() => setDeepScanDebugUiEnabled(false));
  tearDown(() => setDeepScanDebugUiEnabled(false));

  group('Debug toggle defaults', () {
    test('toggle defaults to OFF even in flutter_test (which runs in '
        'kDebugMode)', () {
      expect(isDeepScanDebugUiEnabled(), isFalse);
    });

    test('setDeepScanDebugUiEnabled(true) opts in', () {
      setDeepScanDebugUiEnabled(true);
      expect(isDeepScanDebugUiEnabled(), isTrue);
      setDeepScanDebugUiEnabled(false);
      expect(isDeepScanDebugUiEnabled(), isFalse);
    });
  });

  group('Normal user mode — DeepAnswerProgressCard renders simply', () {
    testWidgets('shows the natural assistant bubble while scanning',
        (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 0, 'pending': 425},
        ),
      );
      expect(
        find.textContaining('Let me check your vault properly'),
        findsOneWidget,
      );
    });

    testWidgets('NO progress card chrome in normal mode', (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 4, 'pending': 421},
        ),
      );
      expect(find.text('Scanning your vault'), findsNothing);
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(find.textContaining('of 425 checked'), findsNothing);
      expect(find.textContaining('to go'), findsNothing);
      expect(find.textContaining('Reading files'), findsNothing);
      expect(find.textContaining('Preparing scan'), findsNothing);
      expect(find.textContaining('Deep Answer Mode'), findsNothing);
      expect(find.textContaining('live'), findsNothing);
      expect(
        find.textContaining('A slow accurate answer'),
        findsNothing,
      );
      expect(
        find.textContaining("I won't return final results"),
        findsNothing,
      );
    });

    testWidgets('terminal-ready snapshot renders nothing (result card '
        'takes over)', (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          status: 'ready',
          coverage: const {
            'total': 10, 'scanned': 10, 'pending': 0,
            'scan_complete': true,
          },
        ),
      );
      expect(find.textContaining('Let me check'), findsNothing);
      expect(find.text('Scan complete'), findsNothing);
    });
  });

  group('Normal user mode — CredentialFileSearchCard renders simply',
      () {
    testWidgets('verified card uses simple "I found N…" title',
        (tester) async {
      await _pumpCredentials(
        tester,
        _credentialsMsg(
          files: [
            _verifiedRow('a.txt'),
            _verifiedRow('b.txt'),
            _verifiedRow('c.txt'),
            _verifiedRow('d.txt'),
            _verifiedRow('e.txt'),
          ],
        ),
      );
      expect(
        find.text('I found 5 files with saved credentials.'),
        findsOneWidget,
      );
      
      expect(find.text('Files with saved credentials'), findsNothing);
      expect(
        find.text('Partial results from already scanned files'),
        findsNothing,
      );
    });

    testWidgets('NO Scan-remaining button in normal mode', (tester) async {
      await _pumpCredentials(
        tester,
        _credentialsMsg(files: [_verifiedRow('a.txt')]),
      );
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.textContaining('Scan remaining files'), findsNothing);
    });

    testWidgets('NO chatty footer copy in normal mode', (tester) async {
      await _pumpCredentials(
        tester,
        _credentialsMsg(files: [_verifiedRow('a.txt')]),
      );
      expect(
        find.textContaining("won't extract credentials"),
        findsNothing,
      );
      expect(
        find.textContaining('These results are incomplete'),
        findsNothing,
      );
      expect(
        find.textContaining('Some files could not be scanned'),
        findsNothing,
      );
      expect(
        find.textContaining('text extraction is not available yet'),
        findsNothing,
      );
    });
  });

  group('Honest failure copy', () {
    testWidgets('blocker_reason renders the natural failure line',
        (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 0, 'pending': 425},
          blockerReason: 'queue_empty_but_coverage_pending',
        ),
      );
      expect(
        find.textContaining(
            "I couldn't finish checking the vault because file "
            'analysis is not moving'),
        findsOneWidget,
      );
      expect(
        find.textContaining(
            'Try running vault analysis or check the backend workers'),
        findsOneWidget,
      );
      
      
      expect(find.textContaining('to go'), findsNothing);
      expect(find.text('Scanning your vault'), findsNothing);
      expect(find.byType(LinearProgressIndicator), findsNothing);
    });

    testWidgets('status=ready + scanned=0 (backend lie) → honest failure',
        (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          status: 'ready',
          coverage: const {
            'total': 425, 'scanned': 0, 'pending': 425,
            'scan_complete': true,
          },
        ),
      );
      expect(find.text('Scan complete'), findsNothing);
      expect(
        find.textContaining(
            "I couldn't finish checking the vault because file "
            'analysis is not moving'),
        findsOneWidget,
      );
    });
  });

  group('Debug-toggle gate (kDebugMode-equivalent opt-in)', () {
    testWidgets('with toggle ON, the big diagnostic progress card renders',
        (tester) async {
      setDeepScanDebugUiEnabled(true);
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 4, 'pending': 421},
        ),
      );
      
      expect(find.text('Scanning your vault'), findsOneWidget);
      expect(find.textContaining('of 425 checked'), findsOneWidget);
      expect(find.textContaining('to go'), findsOneWidget);
    });

    testWidgets('with toggle ON, the credential card Scan-remaining button '
        'is back', (tester) async {
      setDeepScanDebugUiEnabled(true);
      await _pumpCredentials(
        tester,
        _credentialsMsg(files: [_verifiedRow('a.txt')]),
      );
      expect(find.byType(OutlinedButton), findsOneWidget);
      expect(find.textContaining('Scan remaining files'), findsOneWidget);
    });

    testWidgets('with toggle OFF (default), neither debug surface renders',
        (tester) async {
      
      
      setDeepScanDebugUiEnabled(false);
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 4, 'pending': 421},
        ),
      );
      expect(find.text('Scanning your vault'), findsNothing);
      expect(find.byType(LinearProgressIndicator), findsNothing);
    });
  });
}
