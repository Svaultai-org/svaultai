

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _progressMsg({
  required Map<String, dynamic> snapshot,
  String message = '',
}) {
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kDeepAnswerProgress,
    payload: snapshot,
  );
}


Future<void> _pumpProgress(
  WidgetTester tester, {
  required ChatMessage msg,
  Future<Map<String, dynamic>?> Function(String jobId)? onPoll,
  void Function(Map<String, dynamic>)? onReady,
  Size viewport = const Size(900, 1000),
  Duration pollInterval = const Duration(milliseconds: 50),
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
            child: DeepAnswerProgressCard(
              msg: msg,
              onPoll: onPoll,
              onReady: onReady,
              pollInterval: pollInterval,
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}


void main() {
  
  
  setUp(() => setDeepScanDebugUiEnabled(true));
  tearDown(() => setDeepScanDebugUiEnabled(false));

  group('DeepAnswerProgressCard — render', () {
    testWidgets('renders headline + scanned/total + remaining chips',
        (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message:
              'Scanning your vault for files that contain saved '
              'credentials. 42 of 256 files read. Reading '
              'documents... 214 remaining.',
          snapshot: {
            'job_id': 'job-1',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 256, 'scanned': 42,
                'pending': 200, 'processing': 14,
                'unsupported': 0, 'failed': 0,
                'scan_complete': false,
              },
              'current_stage': 'text_extraction',
              'stage_label': 'Reading documents',
              'elapsed_seconds': 4.2,
              'max_wallclock_seconds': 90.0,
            },
          },
        ),
      );
      
      expect(find.text('Scanning your vault'), findsOneWidget);
      expect(find.text('Deep Answer Mode'), findsNothing);
      expect(find.text('live'), findsNothing);
      expect(
        find.textContaining(
            'Scanning your vault for files that contain saved credentials'),
        findsOneWidget,
      );
      expect(find.text('42 of 256 checked'), findsOneWidget);
      expect(find.text('214 to go'), findsOneWidget);
      expect(find.text('Reading documents'), findsOneWidget);
      
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      
      
      expect(
        find.textContaining("I won't return final results"),
        findsNothing,
      );
      expect(
        find.textContaining('A slow accurate answer'),
        findsNothing,
      );
    });

    testWidgets('renders unsupported + failed chips when nonzero',
        (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: 'scanning',
          snapshot: {
            'job_id': 'job-2',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 256, 'scanned': 230,
                'pending': 12, 'processing': 4,
                'unsupported': 6, 'failed': 4,
                'scan_complete': false,
              },
              'current_stage': 'ocr',
              'stage_label': 'Running OCR on images',
            },
          },
        ),
      );
      expect(find.text('6 can’t be read'), findsOneWidget);
      expect(find.text('4 had errors'), findsOneWidget);
      expect(find.text('Running OCR on images'), findsOneWidget);
    });

    testWidgets('failed status surfaces the honest error hint and '
        'stops polling', (tester) async {
      var pollCalls = 0;
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: '',
          snapshot: {
            'job_id': 'job-3',
            'intent': 'search_files_for_credentials',
            'status': 'failed',
            'progress': {
              'coverage': {
                'total': 10, 'scanned': 4,
                'pending': 6, 'processing': 0,
                'unsupported': 0, 'failed': 0,
                'scan_complete': false,
              },
            },
            'error': 'final_results_failed',
          },
        ),
        onPoll: (_) async { pollCalls++; return null; },
      );
      
      await tester.pump(const Duration(milliseconds: 200));
      expect(pollCalls, 0,
          reason: 'failed jobs must not be polled further');
      expect(
        find.textContaining(
            "I couldn't finish reading your vault"),
        findsOneWidget,
      );
      
      expect(find.text("Scan didn't finish"), findsOneWidget);
    });
  });

  group('DeepAnswerProgressCard — polling', () {
    testWidgets('polls onPoll on the configured interval', (tester) async {
      final calls = <String>[];
      
      
      Map<String, dynamic> stillScanning(String jobId) => {
            'job_id': jobId,
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 10, 'scanned': 0,
                'pending': 10, 'processing': 0,
                'unsupported': 0, 'failed': 0, 'scan_complete': false,
              },
            },
          };
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: 'scanning',
          snapshot: {
            'job_id': 'job-poll',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {'coverage': {'total': 10, 'scanned': 0,
                'pending': 10, 'processing': 0,
                'unsupported': 0, 'failed': 0, 'scan_complete': false}},
          },
        ),
        onPoll: (jobId) async {
          calls.add(jobId);
          return stillScanning(jobId);
        },
        pollInterval: const Duration(milliseconds: 30),
      );
      
      await tester.pump(const Duration(milliseconds: 50));
      expect(calls, isNotEmpty);
      expect(calls.first, 'job-poll');
      final initialCalls = calls.length;
      
      
      await tester.pump(const Duration(milliseconds: 50));
      expect(calls.length, greaterThanOrEqualTo(initialCalls + 1));
    });

    testWidgets('null poll reply stops polling', (tester) async {
      
      
      final calls = <String>[];
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: 'scanning',
          snapshot: {
            'job_id': 'job-stop',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {'coverage': {'total': 10, 'scanned': 0,
                'pending': 10, 'processing': 0,
                'unsupported': 0, 'failed': 0, 'scan_complete': false}},
          },
        ),
        onPoll: (jobId) async {
          calls.add(jobId);
          return null;
        },
        pollInterval: const Duration(milliseconds: 30),
      );
      await tester.pump(const Duration(milliseconds: 200));
      expect(calls.length, 1);
    });

    testWidgets('fires onReady when the polled snapshot flips to ready',
        (tester) async {
      Map<String, dynamic>? readySnapshot;
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: 'scanning',
          snapshot: {
            'job_id': 'job-r',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {'coverage': {'total': 10, 'scanned': 0,
                'pending': 10, 'processing': 0,
                'unsupported': 0, 'failed': 0, 'scan_complete': false}},
          },
        ),
        onPoll: (jobId) async {
          return {
            'job_id': jobId,
            'intent': 'search_files_for_credentials',
            'status': 'ready',
            'progress': {'coverage': {'total': 10, 'scanned': 10,
                'pending': 0, 'processing': 0,
                'unsupported': 0, 'failed': 0, 'scan_complete': true}},
            'results': {
              'envelope': {
                'type': 'credential_files',
                'files': <Map<String, dynamic>>[],
                'sections': {
                  'confirmed': <Map<String, dynamic>>[],
                  'possible': <Map<String, dynamic>>[],
                  'filename_only': <Map<String, dynamic>>[],
                },
                'has_content_matches': false,
                'scanned_count': 10,
                'not_scanned_count': 0,
              },
              'scanned': 10,
              'not_scanned': 0,
              'match_count': 0,
            },
          };
        },
        onReady: (snap) => readySnapshot = snap,
        pollInterval: const Duration(milliseconds: 20),
      );
      await tester.pump(const Duration(milliseconds: 40));
      expect(readySnapshot, isNotNull);
      expect(readySnapshot!['status'], 'ready');
      
      await tester.pump(const Duration(milliseconds: 200));
    });

    testWidgets('initial snapshot status=ready fires onReady on first '
        'frame', (tester) async {
      Map<String, dynamic>? readySnapshot;
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: 'done',
          snapshot: {
            'job_id': 'job-instant',
            'status': 'ready',
            'intent': 'search_files_for_credentials',
            'progress': {'coverage': {'total': 0, 'scanned': 0,
                'pending': 0, 'processing': 0,
                'unsupported': 0, 'failed': 0, 'scan_complete': true}},
            'results': {'envelope': {'type': 'credential_files'}},
          },
        ),
        onReady: (snap) => readySnapshot = snap,
      );
      await tester.pump();
      expect(readySnapshot, isNotNull);
      expect(readySnapshot!['status'], 'ready');
    });
  });

  group('DeepAnswerProgressCard — security', () {
    testWidgets('hostile credential VALUES in payload never render',
        (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: '',
          snapshot: {
            'job_id': 'job-h',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 5, 'scanned': 2,
                'pending': 3, 'processing': 0,
                'unsupported': 0, 'failed': 0, 'scan_complete': false,
                
                'leaked_password': 'hunter2-deep-leak',
              },
              'current_stage': 'text_extraction',
              'stage_label': 'Reading documents',
              
              'leaked_token': 'tok-deep-9999-leak',
            },
            'leaked_value': 'value-deep-leak',
          },
        ),
      );
      for (final leak in const [
        'hunter2-deep-leak',
        'tok-deep-9999-leak',
        'value-deep-leak',
      ]) {
        expect(find.textContaining(leak), findsNothing,
            reason: 'deep-answer card must not surface "$leak"');
      }
    });
  });

  group('DeepAnswerProgressCard — mobile viewport', () {
    testWidgets('400-wide mobile viewport renders cleanly', (tester) async {
      await _pumpProgress(
        tester,
        viewport: const Size(400, 900),
        msg: _progressMsg(
          message:
              'Scanning your vault for files that contain saved '
              'credentials. 42 of 256 files read. Reading '
              'documents... 214 remaining.',
          snapshot: {
            'job_id': 'job-m',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 256, 'scanned': 42,
                'pending': 200, 'processing': 14,
                'unsupported': 6, 'failed': 4,
                'scan_complete': false,
              },
              'current_stage': 'text_extraction',
              'stage_label': 'Reading documents',
            },
          },
        ),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Scanning your vault'), findsOneWidget);
      expect(find.text('Deep Answer Mode'), findsNothing);
    });
  });

  group('CredentialFileSearchCard — Scan remaining wires '
      'onScanRemaining once per tap', () {
    testWidgets('tap fires the host callback then is disabled',
        (tester) async {
      var calls = 0;
      tester.view.physicalSize = const Size(900, 1200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      final msg = ChatMessage(
        'assistant',
        '',
        kind: ChatMessage.kCredentialFiles,
        payload: {
          'files': [
            {
              'file_id': 'a',
              'file_name': 'login.js',
              'confidence': 'weak',
              'tier': 'filename_only',
              'reasons': ['filename mentions "login"'],
            },
          ],
          'sections': {
            'confirmed': const [],
            'possible': const [],
            'filename_only': [
              {
                'file_id': 'a',
                'file_name': 'login.js',
                'confidence': 'weak',
                'tier': 'filename_only',
                'reasons': ['filename mentions "login"'],
              },
            ],
          },
          'has_content_matches': false,
          'not_scanned_count': 100,
          'actions': [
            {
              'type': 'scan_remaining',
              'label': 'Scan remaining files',
              'file_count': 100,
            },
          ],
        },
      );
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
                  onScanRemaining: () => calls++,
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      
      
      final scanButton = find.widgetWithText(
        OutlinedButton, 'Scan remaining files (100)',
      );
      await tester.ensureVisible(scanButton);
      await tester.pumpAndSettle();
      await tester.tap(scanButton);
      await tester.pumpAndSettle();
      expect(calls, 1, reason: 'host callback must fire once on tap');
      
      final disabledButton = find.widgetWithText(
        OutlinedButton, 'Scan started — analysis running in background',
      );
      await tester.ensureVisible(disabledButton);
      await tester.pumpAndSettle();
      await tester.tap(disabledButton);
      await tester.pumpAndSettle();
      expect(calls, 1, reason: 'disabled button must not re-fire');
    });
  });

  group('Source guards', () {
    test('chat_models.dart exposes kDeepAnswerProgress', () {
      expect(
        ChatMessage.kDeepAnswerProgress,
        equals('deep_answer_progress'),
      );
    });

    test('main.dart parser handles deep_answer_progress type',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'deep_answer_progress'"));
    });

    test('chat_bubble.dart routes kDeepAnswerProgress', () async {
      final src =
          await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('kDeepAnswerProgress'));
      expect(src, contains('DeepAnswerProgressCard'));
    });

    test('api_client.dart exposes startDeepAnswer + '
        'pollDeepAnswerJob methods', () async {
      final src = await File('lib/api_client.dart').readAsString();
      expect(src, contains('startDeepAnswer'));
      expect(src, contains('pollDeepAnswerJob'));
      expect(src, contains('/vault-analysis/deep-answer'));
    });

    test('CredentialFileSearchCard exposes onScanRemaining parameter',
        () async {
      final src =
          await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(src, contains('onScanRemaining'));
    });
  });

  
  group('DeepAnswerProgressCard — user-facing copy floor', () {
    testWidgets('never renders "Deep Answer Mode" or "live" anywhere',
        (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: '',
          snapshot: {
            'job_id': 'job-copy-1',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 100, 'scanned': 25,
                'pending': 70, 'processing': 5,
                'unsupported': 0, 'failed': 0,
                'scan_complete': false,
              },
              'stage_label': 'Reading files',
            },
          },
        ),
      );
      expect(find.text('Deep Answer Mode'), findsNothing);
      expect(find.text('live'), findsNothing);
      
      
      final visible = tester.widgetList<Text>(find.byType(Text));
      for (final t in visible) {
        final data = t.data ?? t.textSpan?.toPlainText() ?? '';
        for (final forbidden in const [
          'Deep Answer Mode',
          'deep answer',
          'Deep Answer',
          'job_id',
        ]) {
          expect(
            data.toLowerCase().contains(forbidden.toLowerCase()),
            isFalse,
            reason:
                'scan card must never surface "$forbidden" — '
                'rendered "$data"',
          );
        }
      }
      
      expect(find.textContaining('job-copy-1'), findsNothing);
    });

    testWidgets('renders friendly title "Scanning your vault"',
        (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: '',
          snapshot: {
            'job_id': 'job-friendly',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 50, 'scanned': 10,
                'pending': 40, 'processing': 0,
                'unsupported': 0, 'failed': 0,
                'scan_complete': false,
              },
            },
          },
        ),
      );
      expect(find.text('Scanning your vault'), findsOneWidget);
    });

    testWidgets('uses "Scan didn\'t finish" subtitle on failed status',
        (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: '',
          snapshot: {
            'job_id': 'job-fail',
            'intent': 'search_files_for_credentials',
            'status': 'failed',
            'progress': {
              'coverage': {
                'total': 10, 'scanned': 4,
                'pending': 0, 'processing': 0,
                'unsupported': 0, 'failed': 0,
                'scan_complete': false,
              },
            },
            'error': 'final_results_failed',
          },
        ),
      );
      expect(find.text("Scan didn't finish"), findsOneWidget);
      expect(find.text('Scan failed'), findsNothing);
    });
  });

  
  group('DeepAnswerProgressCard — honesty floor', () {
    testWidgets('scanned=0 / remaining>0 shows "Preparing scan…" and '
        'never "Scan complete"', (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: '',
          snapshot: {
            'job_id': 'job-zero',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 425, 'scanned': 0,
                'pending': 425, 'processing': 0,
                'unsupported': 0, 'failed': 0,
                'scan_complete': false,
              },
            },
          },
        ),
      );
      expect(find.text('Preparing scan…'), findsOneWidget);
      expect(find.text('Scan complete'), findsNothing);
      
      
      expect(find.text('0 of 425 checked'), findsNothing);
      
      
      expect(
        find.textContaining("I'm preparing to scan your vault"),
        findsOneWidget,
      );
    });

    testWidgets('scanned>0 / remaining>0 shows scanned/total subtitle',
        (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: '',
          snapshot: {
            'job_id': 'job-mid',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 425, 'scanned': 12,
                'pending': 410, 'processing': 3,
                'unsupported': 0, 'failed': 0,
                'scan_complete': false,
              },
            },
          },
        ),
      );
      expect(find.text('12 of 425 files read'), findsOneWidget);
      expect(find.text('Preparing scan…'), findsNothing);
      expect(find.text('Scan complete'), findsNothing);
    });

    testWidgets('scan_complete=true shows "Scan complete" subtitle',
        (tester) async {
      await _pumpProgress(
        tester,
        msg: _progressMsg(
          message: '',
          snapshot: {
            'job_id': 'job-done',
            'intent': 'search_files_for_credentials',
            'status': 'ready',
            'progress': {
              'coverage': {
                'total': 425, 'scanned': 425,
                'pending': 0, 'processing': 0,
                'unsupported': 0, 'failed': 0,
                'scan_complete': true,
              },
            },
          },
        ),
        onReady: (_) {},
      );
      expect(find.text('Scan complete'), findsOneWidget);
      expect(find.text('Preparing scan…'), findsNothing);
    });
  });

  
  group('DeepAnswerProgressCard — stalled scan honesty', () {
    testWidgets('shows honest hint after several no-progress polls',
        (tester) async {
      
      
      final pollCalls = <String>[];
      const initial = {
        'job_id': 'job-stall',
        'intent': 'search_files_for_credentials',
        'status': 'scanning',
        'progress': {
          'coverage': {
            'total': 50, 'scanned': 5,
            'pending': 45, 'processing': 0,
            'unsupported': 0, 'failed': 0,
            'scan_complete': false,
          },
        },
      };
      await _pumpProgress(
        tester,
        msg: _progressMsg(snapshot: initial),
        onPoll: (jobId) async {
          pollCalls.add(jobId);
          
          return Map<String, dynamic>.from(initial);
        },
        pollInterval: const Duration(milliseconds: 20),
      );
      
      expect(
        find.textContaining('Some files may need text extraction'),
        findsNothing,
      );
      
      
      for (var i = 0; i < 6; i++) {
        await tester.pump(const Duration(milliseconds: 30));
      }
      expect(pollCalls.length, greaterThanOrEqualTo(3),
          reason: 'enough polls must have fired to detect stall');
      expect(
        find.textContaining('Some files may need text extraction'),
        findsOneWidget,
        reason: 'card must surface honest stalled-scan hint',
      );
    });

    testWidgets('stall hint does NOT show when scanned advances',
        (tester) async {
      var tick = 5;
      Map<String, dynamic> snap() => {
            'job_id': 'job-moving',
            'intent': 'search_files_for_credentials',
            'status': 'scanning',
            'progress': {
              'coverage': {
                'total': 50, 'scanned': tick,
                'pending': 50 - tick, 'processing': 0,
                'unsupported': 0, 'failed': 0,
                'scan_complete': false,
              },
            },
          };
      await _pumpProgress(
        tester,
        msg: _progressMsg(snapshot: snap()),
        onPoll: (_) async {
          tick += 5;
          return snap();
        },
        pollInterval: const Duration(milliseconds: 20),
      );
      for (var i = 0; i < 6; i++) {
        await tester.pump(const Duration(milliseconds: 30));
      }
      expect(
        find.textContaining('Some files may need text extraction'),
        findsNothing,
        reason: 'progress is moving — no stalled hint allowed',
      );
    });
  });
}
