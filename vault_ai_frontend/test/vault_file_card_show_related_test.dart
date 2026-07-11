

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

ChatMessage _vaultFileMsg({
  String? fileId = 'file-123',
  String fileName = 'statement.pdf',
  String mimeType = 'application/pdf',
  Map<String, dynamic>? extraPayload,
}) {
  final payload = <String, dynamic>{
    'asset_type':    'file',
    'relative_path': '/Bank',
    'saved_name':    'Statement',
    if (extraPayload != null) ...extraPayload,
  };
  return ChatMessage(
    'assistant',
    'I found your $fileName.',
    kind: ChatMessage.kVaultFile,
    fileId: fileId,
    fileName: fileName,
    mimeType: mimeType,
    payload: payload,
  );
}

Future<void> _pumpCard(
  WidgetTester tester, {
  required ChatMessage msg,
  void Function(String)? onShowRelated,
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
            child: VaultFileCard(
              msg: msg,
              onShowRelated: onShowRelated,
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('VaultFileCard — Show related button', () {
    testWidgets('renders when onShowRelated is supplied + file_id present',
        (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(),
        onShowRelated: (_) {},
      );
      expect(find.text('Show related'), findsOneWidget);
    });

    testWidgets('omitted when onShowRelated is null', (tester) async {
      await _pumpCard(tester, msg: _vaultFileMsg());
      expect(find.text('Show related'), findsNothing);
    });

    testWidgets('omitted when fileId is null', (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(fileId: null),
        onShowRelated: (_) {},
      );
      expect(find.text('Show related'), findsNothing);
    });

    testWidgets('omitted when fileId is empty', (tester) async {
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(fileId: ''),
        onShowRelated: (_) {},
      );
      expect(find.text('Show related'), findsNothing);
    });

    testWidgets('tapping fires onShowRelated with EXACT file_id '
        '(not filename)', (tester) async {
      String? captured;
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(
          fileId: 'abc-def-123',
          fileName: 'statement.pdf',
        ),
        onShowRelated: (id) => captured = id,
      );
      await tester.tap(find.text('Show related'));
      await tester.pumpAndSettle();
      expect(captured, 'abc-def-123');
      
      
      expect(captured, isNot('statement.pdf'));
    });

    testWidgets('renders cleanly on a mobile-width viewport',
        (tester) async {
      
      
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(),
        onShowRelated: (_) {},
        viewport: const Size(400, 700),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Show related'), findsOneWidget);
    });
  });

  group('VaultFileCard — security guards', () {
    testWidgets(
        'NEVER renders summary / extracted_text / password / token '
        'sentinel values from a regressed payload', (tester) async {
      const sentinels = [
        'plaintext-summary-leak',
        'plaintext-content-leak',
        'hunter2',
        'SUPERSECRET-XYZ-123',
      ];
      await _pumpCard(
        tester,
        msg: _vaultFileMsg(
          extraPayload: {
            
            
            'summary':         'plaintext-summary-leak',
            'safe_preview':    'plaintext-summary-leak',
            'extracted_text':  'plaintext-content-leak',
            'password':        'hunter2',
            'token':           'SUPERSECRET-XYZ-123',
          },
        ),
        onShowRelated: (_) {},
      );
      for (final sentinel in sentinels) {
        expect(
          find.textContaining(sentinel),
          findsNothing,
          reason:
              'VaultFileCard must NOT surface backend-leaked '
              'sentinel $sentinel — the card reads only the '
              'declared closed-set payload keys',
        );
      }
    });
  });

  group('Source guards', () {
    test('ApiClient exposes fetchRelatedFiles', () async {
      final src = await File('lib/api_client.dart').readAsString();
      
      
      expect(src, contains('Future<Map<String, dynamic>> fetchRelatedFiles'));
      expect(src, contains('required String fileId'));
      expect(src, contains('required String pin'));
      expect(src, contains('required String authToken'));
      expect(src, contains('/files/\$fileId/related'));
    });

    test('main.dart wires onShowRelated to a handler', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('onShowRelated:'));
      expect(src, contains('_showRelatedFilesForFile'));
    });

    test('main.dart handler uses fetchRelatedFiles directly '
        '(NO filename fuzzy lookup)', () async {
      final src = await File('lib/main.dart').readAsString();
      final idx = src.indexOf('_showRelatedFilesForFile');
      expect(idx, greaterThanOrEqualTo(0));
      
      final body = src.substring(
        idx,
        idx + 2500 < src.length ? idx + 2500 : src.length,
      );
      
      expect(body, contains('fetchRelatedFiles'));
      
      expect(body, isNot(contains('searchFilesByName')));
      expect(body, isNot(contains('classify_chat_intent')));
    });

    test('main.dart handler appends a kRelatedFilesGraph ChatMessage',
        () async {
      final src = await File('lib/main.dart').readAsString();
      final idx = src.indexOf('_showRelatedFilesForFile');
      expect(idx, greaterThanOrEqualTo(0));
      final body = src.substring(
        idx,
        idx + 2500 < src.length ? idx + 2500 : src.length,
      );
      expect(body, contains('ChatMessage.kRelatedFilesGraph'));
    });

    test('chat_bubble routes onShowRelated through to VaultFileCard',
        () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('onShowRelated'));

      // Anchor on the actual switch label and stop at the case
      // terminator so the window survives new props (onDownload,
      // isViewInFlight, isDownloadInFlight, viewInFlightFileIds,
      // downloadInFlightFileIds) being added to the case body.
      final idx = src.indexOf('ChatMessage.kVaultFile:');
      expect(idx, greaterThanOrEqualTo(0));
      final endIdx = src.indexOf('break;', idx);
      expect(endIdx, greaterThan(idx));
      final body = src.substring(idx, endIdx);
      expect(body, contains('onShowRelated:'));
    });

    test('VaultFileCard exposes onShowRelated parameter', () async {
      final src = await File('lib/ui/chat/chat_cards.dart').readAsString();
      final idx = src.indexOf('class VaultFileCard extends StatelessWidget');
      expect(idx, greaterThanOrEqualTo(0));
      
      final next = src.indexOf('class _', idx + 1);
      final classBody = src.substring(
        idx, next > 0 ? next : src.length,
      );
      expect(classBody, contains('onShowRelated'));
    });
  });
}
