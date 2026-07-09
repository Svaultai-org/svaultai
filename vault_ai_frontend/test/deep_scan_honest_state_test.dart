

import 'dart:io';

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
  String? stageLabel,
  String text = '',
}) {
  return ChatMessage(
    'assistant', text,
    kind: ChatMessage.kDeepAnswerProgress,
    payload: <String, dynamic>{
      'job_id': 'job-honest',
      'status': status,
      'progress': <String, dynamic>{
        'coverage':      coverage,
        if (blockerReason != null) 'blocker_reason': blockerReason,
        if (stageLabel != null) 'stage_label': stageLabel,
      },
    },
  );
}


ChatMessage _credentialsMsg({
  required List<Map<String, dynamic>> files,
  bool stale = false,
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
      'stale': stale,
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


Future<void> _pumpCredentials(
  WidgetTester tester, {
  required ChatMessage msg,
  bool Function({
    required String intent,
    required String normalizedQuery,
  })? isDeepScanActive,
}) async {
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
            child: CredentialFileSearchCard(
              msg: msg,
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
  group('DeepAnswerProgressCard — never claims Scan complete at 0/N', () {
    testWidgets(
        'status=ready + scanned=0 + total=425 NEVER renders "Scan complete"',
        (tester) async {
      
      
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {
            'total':           425,
            'scanned':         0,
            'pending':         425,
            'scan_complete':   true,   
          },
          status: 'ready',
        ),
      );
      expect(
        find.text('Scan complete'),
        findsNothing,
        reason: 'never claim "Scan complete" when scanned < total',
      );
      
      expect(
        find.textContaining(
            "I couldn't finish checking the vault because file "
            'analysis is not moving'),
        findsOneWidget,
      );
    });

    testWidgets('status=ready + scanned=10/total=10 collapses to nothing '
        '(result card takes over)', (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {
            'total':         10,
            'scanned':       10,
            'pending':       0,
            'scan_complete': true,
          },
          status: 'ready',
        ),
      );
      
      expect(find.text('Scan complete'), findsNothing);
    });

    testWidgets('status=ready + total=0 (empty vault) also collapses',
        (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {
            'total':         0,
            'scanned':       0,
            'pending':       0,
            'scan_complete': true,
          },
          status: 'ready',
        ),
      );
      expect(find.text('Scan complete'), findsNothing);
    });
  });

  group('DeepAnswerProgressCard — backend blocker_reason flips to honest copy',
      () {
    testWidgets('queue_empty_but_coverage_pending surfaces honest copy',
        (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {
            'total': 425, 'scanned': 0, 'pending': 425,
          },
          status: 'scanning',
          blockerReason: 'queue_empty_but_coverage_pending',
        ),
      );
      expect(
        find.textContaining(
            "I couldn't finish checking the vault because file "
            'analysis is not moving'),
        findsOneWidget,
      );
    });

    testWidgets('no_worker_registered surfaces honest copy', (tester) async {
      await _pumpProgress(
        tester,
        _progressMsg(
          coverage: const {
            'total': 425, 'scanned': 0, 'pending': 425,
          },
          status: 'scanning',
          blockerReason: 'no_worker_registered:text_extraction',
        ),
      );
      expect(
        find.textContaining(
            "I couldn't finish checking the vault because file "
            'analysis is not moving'),
        findsOneWidget,
      );
    });
  });

  group('CredentialFileSearchCard — hidden when live scan active', () {
    testWidgets('stale + host scan active => card is HIDDEN (no rows, '
        'no title)', (tester) async {
      await _pumpCredentials(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow('dump.txt'), _verifiedRow('other.txt')],
          stale: true,
        ),
        isDeepScanActive: ({
          required String intent,
          required String normalizedQuery,
        }) => true,
      );
      
      expect(find.text('dump.txt'), findsNothing);
      expect(find.text('other.txt'), findsNothing);
      
      
      expect(
        find.textContaining('I found '),
        findsNothing,
      );
      
      expect(find.textContaining('Older results'), findsNothing);
    });

    testWidgets('stale BUT no host scan active => keeps simple title + rows '
        '(legacy fallback)', (tester) async {
      await _pumpCredentials(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow('dump.txt')],
          stale: true,
        ),
      );
      expect(
        find.text('I found 1 file with saved credentials.'),
        findsOneWidget,
      );
      expect(find.text('dump.txt'), findsOneWidget);
    });

    testWidgets('not stale + host scan active => still renders full card',
        (tester) async {
      await _pumpCredentials(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow('dump.txt')],
          stale: false,
        ),
        isDeepScanActive: ({
          required String intent,
          required String normalizedQuery,
        }) => true,
      );
      expect(find.text('dump.txt'), findsOneWidget);
      expect(
        find.text('I found 1 file with saved credentials.'),
        findsOneWidget,
      );
    });
  });

  
  group('source guards — promote-routine honest-state defence', () {
    test('_promoteDeepAnswerResult bails when envelope says scanned==0 + '
        'not_scanned>0', () async {
      final src = await File('lib/main.dart').readAsString();
      final start = src.indexOf('void _promoteDeepAnswerResult');
      expect(start, greaterThan(-1));
      final body = src.substring(start, start + 3500);
      expect(body, contains("status != 'ready'"));
      expect(body, contains('envScanned'));
      expect(body, contains('envNotScanned'));
      expect(body, contains('envScanned == 0'));
    });

    test('DeepAnswerProgressCard carries the honest-state guard', () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(
        src,
        contains('isLyingAboutCompletion'),
        reason: 'the honest-state guard must live in chat_cards.dart',
      );
    });

    test('DeepAnswerProgressCard normal-mode bubble copy is the natural '
        '"Let me check your vault properly" line', () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(src, contains('Let me check your vault properly'));
    });

    test('DeepAnswerProgressCard honest-failure copy is wired', () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      
      
      expect(src, contains("I couldn't finish checking the vault"));
      expect(src, contains('analysis is not moving'));
      expect(src, contains('check the backend workers'));
    });

    test('backend wiring: enqueue_missing_fn threaded into both step calls',
        () async {
      final src = await File('../vault_ai_backend/routes/deep_answer_routes.py')
          .readAsString();
      final calls = RegExp(r'enqueue_missing_fn=_enqueue_missing_fn')
          .allMatches(src)
          .length;
      expect(calls, greaterThanOrEqualTo(2),
          reason: 'engine must enqueue on BOTH start and poll');
    });

    test('backend wiring: debug endpoint registered', () async {
      final src = await File('../vault_ai_backend/routes/deep_answer_routes.py')
          .readAsString();
      expect(
        src,
        contains('/vault-analysis/deep-answer/{job_id}/debug'),
      );
      expect(src, contains('debug_job_snapshot'));
    });
  });
}
