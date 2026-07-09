

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


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

Map<String, dynamic> _verifiedRow({
  required String fileId,
  required String fileName,
}) {
  return <String, dynamic>{
    'file_id': fileId,
    'file_name': fileName,
    'record_count': 3,
    'evidence_source': 'file_text',
    'evidence_source_label': 'file text',
    'password_present': true,
    'safe_service_names': const <String>[],
    'duplicate_paths': const <String>[],
  };
}


Future<void> _pump(
  WidgetTester tester, {
  required ChatMessage msg,
  void Function()? onScanRemaining,
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
              onScanRemaining: onScanRemaining,
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
  group('CredentialFileSearchCard — Scan-remaining button is GONE', () {
    testWidgets('partial state with 231 not_scanned NEVER renders the button',
        (tester) async {
      int taps = 0;
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'dump.txt')],
        ),
        onScanRemaining: () => taps++,
      );
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.textContaining('Scan remaining files'), findsNothing);
      expect(taps, 0);
    });

    testWidgets('empty-state with not_scanned > 0 NEVER renders the button',
        (tester) async {
      await _pump(
        tester,
        msg: ChatMessage(
          'assistant', '',
          kind: ChatMessage.kCredentialFiles,
          payload: <String, dynamic>{
            'files': const <Map<String, dynamic>>[],
            'scanned_count': 0,
            'not_scanned_count': 425,
            'is_partial': true,
            'actions': <Map<String, dynamic>>[
              <String, dynamic>{
                'type': 'scan_remaining',
                'label': 'Scan remaining files',
              },
            ],
          },
        ),
      );
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.textContaining('Scan remaining files'), findsNothing);
    });

    testWidgets('isDeepScanActive=true still must not render the button '
        '(no point disabling a button that no longer exists)',
        (tester) async {
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'dump.txt')],
        ),
        isDeepScanActive: ({
          required String intent,
          required String normalizedQuery,
        }) => true,
      );
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.text('Scanning…'), findsNothing);
      expect(find.textContaining('Scan remaining files'), findsNothing);
    });
  });

  group('CredentialFileSearchCard — isDeepScanActive predicate', () {
    testWidgets('predicate is called with credential intent + empty query',
        (tester) async {
      String? seenIntent;
      String? seenQuery;
      await _pump(
        tester,
        msg: _credentialsMsg(
          files: [_verifiedRow(fileId: 'a', fileName: 'dump.txt')],
        ),
        isDeepScanActive: ({
          required String intent,
          required String normalizedQuery,
        }) {
          seenIntent = intent;
          seenQuery = normalizedQuery;
          return false;
        },
      );
      expect(seenIntent, 'search_files_for_credentials');
      expect(seenQuery, '');
    });
  });

  
  group('source guards — dedupe wiring + final-only-on-ready', () {
    test('main.dart declares activeDeepScanJobId + isDeepScanActive',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('activeDeepScanJobId'));
      expect(src, contains('activeDeepScanIntent'));
      expect(src, contains('activeDeepScanQuery'));
      expect(src, contains('activeDeepScanStatus'));
      expect(src, contains('bool isDeepScanActive('));
      expect(src, contains('String normalizeDeepScanQuery('));
    });

    test('_kickOffDeepAnswerScan dedupes before POST', () async {
      final src = await File('lib/main.dart').readAsString();
      final start = src.indexOf('Future<void> _kickOffDeepAnswerScan');
      expect(start, greaterThan(-1));
      final endMarker = src.indexOf('\n  Future<', start + 1);
      final fallback = src.indexOf('\n  void ', start + 1);
      final end = (endMarker == -1 && fallback == -1)
          ? src.length
          : (endMarker == -1
              ? fallback
              : (fallback == -1 ? endMarker : (endMarker < fallback
                  ? endMarker : fallback)));
      final body = src.substring(start, end);
      expect(body, contains('isDeepScanActive('),
          reason: 'must call the dedupe predicate before POSTing');
      expect(body, contains('_focusActiveDeepScanCard'),
          reason: 'must focus the existing card on dedupe hit');
    });

    test('_kickOffDeepAnswerScan seeds the natural assistant bubble copy',
        () async {
      
      
      final src = await File('lib/main.dart').readAsString();
      expect(
        src,
        contains('Let me check your vault properly'),
      );
    });

    test('_promoteDeepAnswerResult gates on status == ready', () async {
      final src = await File('lib/main.dart').readAsString();
      final start = src.indexOf('void _promoteDeepAnswerResult');
      expect(start, greaterThan(-1));
      final endMarker = src.indexOf('\n  Future<', start + 1);
      final fallback = src.indexOf('\n  void ', start + 1);
      final end = (endMarker == -1 && fallback == -1)
          ? src.length
          : (endMarker == -1
              ? fallback
              : (fallback == -1 ? endMarker : (endMarker < fallback
                  ? endMarker : fallback)));
      final body = src.substring(start, end);
      expect(body, contains("status != 'ready'"),
          reason: 'final-result promotion MUST short-circuit when not ready');
    });

    test('_promoteDeepAnswerResult dedupes by job_id', () async {
      final src = await File('lib/main.dart').readAsString();
      final start = src.indexOf('void _promoteDeepAnswerResult');
      expect(start, greaterThan(-1));
      final body = src.substring(start, start + 4000);
      expect(body, contains('deep_answer_job_id'),
          reason: 'final result must be tagged with job_id so we can dedupe');
    });

    test('chat_message_list threads isDeepScanActive to ChatBubble',
        () async {
      final src = await File('lib/ui/chat/chat_message_list.dart')
          .readAsString();
      expect(src, contains('isDeepScanActive:'));
    });

    test('chat_bubble threads isDeepScanActive to CredentialFileSearchCard',
        () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('isDeepScanActive:'));
    });

    test('CredentialFileSearchCard declares isDeepScanActive parameter',
        () async {
      final src = await File('lib/ui/chat/chat_cards.dart').readAsString();
      expect(src, contains('isDeepScanActive'));
      expect(src, contains('_hostKnowsScanActive'));
    });
  });
}
