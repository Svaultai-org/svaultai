

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart'
    show setDeepScanDebugUiEnabled;
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _credentialMsg({int notScanned = 100}) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kCredentialFiles,
    payload: <String, dynamic>{
      'files': [
        {
          'file_id': 'a',
          'file_name': 'login.js',
          'tier': 'filename_only',
          'confidence': 'weak',
          'reasons': ['filename mentions "login"'],
        },
      ],
      'sections': {
        'confirmed': const <Map<String, dynamic>>[],
        'possible': const <Map<String, dynamic>>[],
        'filename_only': [
          {
            'file_id': 'a',
            'file_name': 'login.js',
            'tier': 'filename_only',
            'confidence': 'weak',
            'reasons': ['filename mentions "login"'],
          },
        ],
      },
      'has_content_matches': false,
      'not_scanned_count': notScanned,
      'actions': [
        {
          'type': 'scan_remaining',
          'label': 'Scan remaining files',
          'file_count': notScanned,
        },
      ],
    },
  );
}


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


Future<void> _pumpMessageList(
  WidgetTester tester, {
  required List<ChatMessage> messages,
  void Function(ChatMessage credentialMsg)? onScanRemaining,
  Future<Map<String, dynamic>?> Function(String jobId)? onDeepAnswerPoll,
  void Function(Map<String, dynamic> snapshot)? onDeepAnswerReady,
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
          child: ChatMessageList(
            messages: messages,
            thinking: false,
            streaming: false,
            isMobile: false,
            onScanRemaining: onScanRemaining,
            onDeepAnswerPoll: onDeepAnswerPoll,
            onDeepAnswerReady: onDeepAnswerReady,
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('Scan-remaining → ChatMessageList → host wiring', () {
    testWidgets('tap on Scan remaining invokes host callback with the '
        'exact credential message (debug-toggle ON)', (tester) async {
      
      
      setDeepScanDebugUiEnabled(true);
      addTearDown(() => setDeepScanDebugUiEnabled(false));

      ChatMessage? captured;
      var calls = 0;
      final credentialMsg = _credentialMsg(notScanned: 231);
      await _pumpMessageList(
        tester,
        messages: [credentialMsg],
        onScanRemaining: (msg) {
          captured = msg;
          calls++;
        },
      );
      final btn = find.widgetWithText(
        OutlinedButton, 'Scan remaining files (231)',
      );
      await tester.ensureVisible(btn);
      await tester.pumpAndSettle();
      await tester.tap(btn);
      await tester.pumpAndSettle();
      expect(calls, 1, reason: 'host onScanRemaining must fire once');
      expect(captured, isNotNull);
      expect(captured!.kind, ChatMessage.kCredentialFiles);
      expect((captured!.payload!['not_scanned_count'] as int), 231);
    });

    testWidgets('callback is not invoked without an unscanned hint',
        (tester) async {
      
      
      var calls = 0;
      final msg = ChatMessage(
        'assistant', '',
        kind: ChatMessage.kCredentialFiles,
        payload: <String, dynamic>{
          'files': [
            {
              'file_id': 'a', 'file_name': 'dump.txt',
              'tier': 'confirmed', 'confidence': 'strong',
              'reasons': ['content contains ...'],
            },
          ],
          'sections': {
            'confirmed': [
              {
                'file_id': 'a', 'file_name': 'dump.txt',
                'tier': 'confirmed', 'confidence': 'strong',
                'reasons': ['content contains ...'],
              },
            ],
            'possible': const <Map<String, dynamic>>[],
            'filename_only': const <Map<String, dynamic>>[],
          },
          'has_content_matches': true,
          'not_scanned_count': 0,
          'actions': const <Map<String, dynamic>>[],
        },
      );
      await _pumpMessageList(
        tester,
        messages: [msg],
        onScanRemaining: (_) => calls++,
      );
      expect(
        find.widgetWithText(OutlinedButton, 'Scan remaining files (0)'),
        findsNothing,
      );
      expect(calls, 0);
    });
  });

  group('Progress card → poll + ready wiring', () {
    testWidgets('progress card invokes host poll on the configured '
        'interval', (tester) async {
      final pollCalls = <String>[];
      final snap = {
        'job_id': 'job-w',
        'intent': 'search_files_for_credentials',
        'status': 'scanning',
        'progress': {
          'coverage': {
            'total': 256, 'scanned': 42,
            'pending': 200, 'processing': 14,
            'unsupported': 0, 'failed': 0, 'scan_complete': false,
          },
          'stage_label': 'Reading documents',
        },
      };
      await _pumpMessageList(
        tester,
        messages: [_progressMsg(snapshot: snap, message: 'scanning')],
        onDeepAnswerPoll: (jobId) async {
          pollCalls.add(jobId);
          
          
          return Map<String, dynamic>.from(snap);
        },
      );
      
      
      expect(find.text('Scanning your vault'), findsNothing);
      expect(find.text('Deep Answer Mode'), findsNothing);
      expect(find.text('42 of 256 checked'), findsNothing);
      
      
      await tester.pump(const Duration(seconds: 2));
      expect(pollCalls, isNotEmpty,
          reason: 'list must thread onDeepAnswerPoll to the card');
      expect(pollCalls.first, 'job-w');
    });

    testWidgets('progress card with terminal snapshot fires onReady '
        'with the snapshot', (tester) async {
      Map<String, dynamic>? captured;
      final readySnap = {
        'job_id': 'job-r',
        'intent': 'search_files_for_credentials',
        'status': 'ready',
        'progress': {
          'coverage': {
            'total': 10, 'scanned': 10,
            'pending': 0, 'processing': 0,
            'unsupported': 0, 'failed': 0, 'scan_complete': true,
          },
        },
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
        },
      };
      await _pumpMessageList(
        tester,
        messages: [_progressMsg(snapshot: readySnap, message: 'done')],
        onDeepAnswerReady: (snap) => captured = snap,
      );
      
      
      await tester.pump();
      expect(captured, isNotNull);
      expect(captured!['status'], 'ready');
      expect(captured!['results'], isA<Map>());
    });
  });

  group('Source guards — dashboard helpers exist + are wired', () {
    test('_ChatDashboardPageState declares _handleScanRemaining + '
        '_pollDeepAnswerJob + _promoteDeepAnswerResult', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('void _handleScanRemaining'),
          reason: 'host must declare the scan-remaining handler');
      expect(src, contains('_pollDeepAnswerJob'),
          reason: 'host must declare the poll wrapper');
      expect(src, contains('_promoteDeepAnswerResult'),
          reason: 'host must declare the ready promoter');
    });

    test('_kickOffDeepAnswerScan calls api_client.startDeepAnswer + '
        'appends DeepAnswerProgressCard message', () async {
      final src = await File('lib/main.dart').readAsString();
      
      
      expect(src, contains('client.startDeepAnswer'),
          reason: 'host must POST /vault-analysis/deep-answer');
      expect(
        src,
        contains('kind: ChatMessage.kDeepAnswerProgress'),
        reason: 'host must append a progress card to the chat',
      );
    });

    test('_pollDeepAnswerJob calls api_client.pollDeepAnswerJob',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('client.pollDeepAnswerJob'));
    });

    test('_promoteDeepAnswerResult appends a kCredentialFiles message',
        () async {
      final src = await File('lib/main.dart').readAsString();
      final idx = src.indexOf('void _promoteDeepAnswerResult');
      expect(idx, greaterThan(-1));
      
      final endIdx = src.indexOf('\n  }\n', idx);
      final body = src.substring(idx, endIdx == -1 ? src.length : endIdx);
      expect(body, contains('kind: ChatMessage.kCredentialFiles'),
          reason: 'ready promoter must build the final credential card');
      expect(body, contains("envelope['files']"),
          reason: 'promoter reads the final files list');
    });

    test('ChatMessageList wires onScanRemaining + onDeepAnswerPoll + '
        'onDeepAnswerReady from the dashboard', () async {
      final src = await File('lib/main.dart').readAsString();
      
      
      final cmIdx = src.indexOf('ChatMessageList(');
      expect(cmIdx, greaterThan(-1));
      final end = src.indexOf('),\n        ),\n', cmIdx);
      final block = src.substring(cmIdx, end == -1 ? src.length : end);
      expect(block, contains('onScanRemaining: _handleScanRemaining'),
          reason: 'list must receive the host scan-remaining handler');
      expect(block, contains('onDeepAnswerPoll: _pollDeepAnswerJob'),
          reason: 'list must receive the host poll wrapper');
      expect(block,
          contains('onDeepAnswerReady: _promoteDeepAnswerResult'),
          reason: 'list must receive the host ready promoter');
    });

    test('handler short-circuits when session token / vault id is null',
        () async {
      
      
      final src = await File('lib/main.dart').readAsString();
      final idx = src.indexOf('Future<void> _kickOffDeepAnswerScan');
      expect(idx, greaterThan(-1));
      final endIdx = src.indexOf('Future<Map<String, dynamic>?> _pollDeepAnswerJob', idx);
      final body = src.substring(idx, endIdx == -1 ? src.length : endIdx);
      expect(body, contains('Session expired'),
          reason: 'host must surface a safe error when session is null');
      expect(body, contains('Vault is locked'),
          reason: 'host must surface a safe error when PIN is missing');
    });

    test('chat_bubble.dart threads onScanRemaining → '
        'CredentialFileSearchCard', () async {
      final src =
          await File('lib/ui/chat/chat_bubble.dart').readAsString();
      
      
      expect(src, contains('onScanRemaining: onScanRemaining == null'),
          reason: 'bubble must pass through host callback');
      expect(src, contains('=> onScanRemaining!(msg)'),
          reason: 'bubble must invoke with the credential ChatMessage');
    });
  });
}
