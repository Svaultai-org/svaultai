

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/chat/vault_file_view_messages.dart';

void main() {
  group('friendlyVaultFileOpenError', () {
    test('404 / not found maps to "file record exists" copy', () {
      const raw = 'Exception: Get download manifest failed: '
          '404 - Not Found';
      final msg = friendlyVaultFileOpenError(Exception(raw));
      expect(
        msg,
        contains('This file record exists, but the file content '
            'could not be found'),
      );
      
      expect(msg, isNot(contains('Get download manifest failed')));
      expect(msg, isNot(contains('404')));
    });

    test('plain "File not found" body maps to the same copy', () {
      final msg = friendlyVaultFileOpenError(
        Exception('Download file failed: 404 - File not found'),
      );
      expect(
        msg,
        contains('the file content could not be found'),
      );
    });

    test('401 / unauthorized maps to session-expired copy', () {
      final msg = friendlyVaultFileOpenError(
        Exception('Auth check failed: 401 - Unauthorized'),
      );
      expect(msg.toLowerCase(), contains('session expired'));
    });

    test('PIN failure maps to PIN retry copy', () {
      final msg = friendlyVaultFileOpenError(
        Exception('Invalid PIN or corrupted data'),
      );
      expect(msg.toLowerCase(), contains('pin'));
    });

    test('network error maps to connection copy', () {
      final msg = friendlyVaultFileOpenError(
        Exception('ClientException: Failed to fetch'),
      );
      expect(msg.toLowerCase(), contains('connection'));
    });

    test('unknown failure falls back to generic actionable copy', () {
      final msg = friendlyVaultFileOpenError(
        Exception('weird unexpected error'),
      );
      expect(msg.toLowerCase(), contains('try again'));
      expect(msg, isNot(contains('weird unexpected error')));
    });
  });

  group('unsupportedPreviewMessage', () {
    test('mentions Download for unknown mime', () {
      
      
      final msg = unsupportedPreviewMessage(mimeType: null);
      expect(msg.toLowerCase(), contains('download'));
      
      expect(msg.toLowerCase(), isNot(contains('open it in a new')));
      expect(msg.toLowerCase(), isNot(contains('browser tab')));
    });

    test('mentions the mime type when known', () {
      final msg = unsupportedPreviewMessage(
        mimeType: 'application/vnd.ms-excel',
      );
      expect(msg, contains('application/vnd.ms-excel'));
      expect(msg.toLowerCase(), contains('download'));
    });

    test('never pushes the user to a browser tab', () {
      for (final mime in [
        null,
        '',
        'application/pdf',
        'application/vnd.ms-excel',
        'image/png',
        'text/plain',
      ]) {
        final msg = unsupportedPreviewMessage(mimeType: mime);
        expect(
          msg.toLowerCase(), isNot(contains('open it in a new')),
          reason: 'unsupported copy must never push the user to a '
              'browser tab — mime $mime',
        );
        expect(
          msg.toLowerCase(), isNot(contains('browser tab')),
          reason: 'unsupported copy must never mention a browser '
              'tab — mime $mime',
        );
      }
    });

    test('empty mime gets the generic copy', () {
      expect(
        unsupportedPreviewMessage(mimeType: '  '),
        contains('this file type'),
      );
    });
  });

  group('pdfPreviewFailedMessage', () {
    test('honest in-app fallback never pushes to browser', () {
      final msg = pdfPreviewFailedMessage();
      expect(
        msg,
        contains('Preview could not load. You can download this file.'),
      );
      expect(msg.toLowerCase(), isNot(contains('browser')));
      expect(msg.toLowerCase(), isNot(contains('new tab')));
    });
  });

  group('isInAppPreviewableMime', () {
    test('PDF is in-app previewable', () {
      expect(isInAppPreviewableMime('application/pdf'), isTrue);
      expect(isInAppPreviewableMime('APPLICATION/PDF'), isTrue);
    });

    test('images are in-app previewable', () {
      expect(isInAppPreviewableMime('image/png'), isTrue);
      expect(isInAppPreviewableMime('image/jpeg'), isTrue);
    });

    test('text/plain + text/html are in-app previewable', () {
      expect(isInAppPreviewableMime('text/plain'), isTrue);
      expect(isInAppPreviewableMime('text/html'), isTrue);
    });

    test('docx / spreadsheets are NOT in-app previewable', () {
      expect(
        isInAppPreviewableMime(
            'application/vnd.openxmlformats-officedocument'
            '.wordprocessingml.document'),
        isFalse,
      );
      expect(
        isInAppPreviewableMime('application/vnd.ms-excel'),
        isFalse,
      );
    });

    test('null / empty is NOT in-app previewable', () {
      expect(isInAppPreviewableMime(null), isFalse);
      expect(isInAppPreviewableMime(''), isFalse);
      expect(isInAppPreviewableMime('   '), isFalse);
    });
  });

  group('source guards — preview dialog buttons', () {
    test(
        'main.dart shows the unsupported preview dialog via a '
        'dedicated method (not inline)', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(
        src,
        contains('_showUnsupportedPreviewDialog'),
        reason: 'the preview dialog must be a named method so we '
            'can keep the buttons in one place',
      );
    });

    test(
        'unsupported preview dialog includes a Download button '
        'wired to FileDownloader', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(
        src,
        contains('FileDownloader().downloadBytes('),
        reason: 'the Download button must invoke the platform '
            'downloader so saying "you can download it" actually '
            'gives the user a way to do it',
      );
      
      
      expect(
        src.contains("label: const Text('Download')") ||
            src.contains('commonDownload'),
        isTrue,
        reason:
            'unsupported preview dialog must expose a Download '
            'button (literal or AppLocalizations.commonDownload)',
      );
    });

    test(
        'main.dart removes the legacy "Open in browser" button from the '
        'unsupported preview dialog', () async {
      
      
      final src = await File('lib/main.dart').readAsString();
      final dialogIdx = src.indexOf(
        'Future<void> _showUnsupportedPreviewDialog',
      );
      expect(dialogIdx, greaterThan(-1));
      final endIdx = src.indexOf(
        'Future<void> _openPdfPreviewDialog',
        dialogIdx,
      );
      final body = src.substring(
        dialogIdx, endIdx == -1 ? src.length : endIdx,
      );
      expect(
        body, isNot(contains('openBytesInBrowser')),
        reason: 'unsupported preview dialog must NOT push to browser',
      );
      expect(
        body, isNot(contains("Open in browser")),
        reason: 'unsupported preview dialog must NOT label any button '
            '"Open in browser"',
      );
    });

    test('main.dart wires the in-app PDF preview dialog', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('_openPdfPreviewDialog'),
          reason: 'main.dart must declare the PDF preview dialog');
      
      
      final pdfCall = src.indexOf("'application/pdf'");
      final pdfDialog = src.indexOf('_openPdfPreviewDialog(');
      expect(pdfCall, greaterThan(-1),
          reason: 'main.dart must branch on application/pdf');
      expect(pdfDialog, greaterThan(pdfCall),
          reason: 'application/pdf must route to _openPdfPreviewDialog '
              'before any unsupported fallback');
      expect(src, contains('VaultPdfPreviewer'),
          reason: 'main.dart must instantiate VaultPdfPreviewer for '
              'the in-app preview');
    });

    test('main.dart does NOT push PDFs to browser', () async {
      final src = await File('lib/main.dart').readAsString();
      
      
      expect(src, isNot(contains('open it in a new browser tab')),
          reason: 'PDF (and any other) preview must never push the '
              'user to a browser tab');
    });

    test('FileDownloader stub exists for non-web builds', () async {
      final src = await File(
          'lib/file_downloader_stub.dart').readAsString();
      
      
      expect(src, contains('class FileDownloader'));
      expect(src, contains('return false'));
    });

    test('FileDownloader web build uses Blob + AnchorElement', () async {
      final src = await File(
          'lib/file_downloader_web.dart').readAsString();
      expect(src, contains('html.Blob'));
      expect(src, contains('html.AnchorElement'));
      expect(
        src,
        contains('revokeObjectUrl'),
        reason: 'the decrypted plaintext blob URL MUST be revoked '
            'after the download fires so the browser drops the '
            'bytes from memory — same crypto rule as the media '
            'player',
      );
    });

    test('file_downloader.dart conditional export wires web on dart:html',
        () async {
      final src = await File('lib/file_downloader.dart').readAsString();
      expect(src, contains("if (dart.library.html) "
          "'file_downloader_web.dart'"));
      expect(src, contains("'file_downloader_stub.dart'"));
    });
  });

  group('VaultFileCard — file_id wiring', () {
    testWidgets('View / Download buttons call onOpen, never fuzzy-lookup',
        (tester) async {
      var openCalls = 0;
      final msg = ChatMessage(
        'assistant',
        'Here is your file.',
        kind: ChatMessage.kVaultFile,
        fileId: 'file-abc',
        fileName: 'fema application.pdf',
        mimeType: 'application/pdf',
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
            body: SafeArea(
              child: VaultFileCard(
                msg: msg,
                onOpen: () => openCalls++,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('fema application.pdf'), findsOneWidget);

      
      await tester.tap(find.byIcon(Icons.visibility_outlined));
      await tester.pumpAndSettle();
      expect(openCalls, 1);

      await tester.tap(find.byIcon(Icons.file_download_outlined));
      await tester.pumpAndSettle();
      expect(openCalls, 2);
    });
  });

  group('source guards', () {
    test('main.dart maps fetch errors via friendlyVaultFileOpenError',
        () async {
      final src = await File('lib/main.dart').readAsString();
      
      
      expect(src, contains('friendlyVaultFileOpenError'));
      
      expect(
        src,
        isNot(contains("'Could not open file: \$e'")),
        reason: 'raw exception text MUST NOT be shown to the user',
      );
    });

    test('main.dart calls unsupportedPreviewMessage on the fallback path',
        () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains('unsupportedPreviewMessage('));
    });

    test('_fetchVaultFile falls back to /download-file on manifest 404',
        () async {
      final src = await File('lib/main.dart').readAsString();
      
      
      expect(
        src,
        contains('looksLikeMissingRoute'),
        reason: 'fetch must detect manifest 404 / not-found and fall '
                'back to the legacy /download-file endpoint',
      );
      
      
      expect(src, contains('client.downloadVaultFile('));
    });
  });
}
