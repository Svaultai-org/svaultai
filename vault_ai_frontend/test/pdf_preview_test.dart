

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/pdf_preview.dart';
import 'package:vault_ai_frontend/ui/chat/vault_file_view_messages.dart';


void main() {
  group('VaultPdfPreviewer — stub on non-web', () {
    test('stub reports available = false on this (non-web) test runner',
        () {
      
      
      expect(VaultPdfPreviewer().available, isFalse);
    });

    test('stub register() returns false', () {
      final p = VaultPdfPreviewer();
      final ok = p.register(
        viewType: 'vault-pdf-test',
        bytes: Uint8List.fromList(const [0x25, 0x50, 0x44, 0x46]),
      );
      expect(ok, isFalse);
    });

    test('stub dispose() is a safe no-op', () {
      final p = VaultPdfPreviewer();
      p.dispose();
      p.dispose();  
    });
  });

  
  group('preview copy contract', () {
    test('pdfPreviewFailedMessage reads exactly the spec line', () {
      
      
      expect(
        pdfPreviewFailedMessage(),
        equals('Preview could not load. You can download this file.'),
      );
    });

    test('unsupportedPreviewMessage no longer says '
        '"Preview is not available for application/pdf"', () {
      
      
      final all = [
        unsupportedPreviewMessage(mimeType: null),
        unsupportedPreviewMessage(mimeType: ''),
        unsupportedPreviewMessage(mimeType: '   '),
        unsupportedPreviewMessage(mimeType: 'application/octet-stream'),
      ];
      for (final msg in all) {
        expect(
          msg, isNot(contains('application/pdf')),
          reason: 'unsupported preview copy must not mention PDF; '
              'PDFs are now handled in-app',
        );
        expect(
          msg.toLowerCase(), isNot(contains('open it in a new')),
          reason: 'unsupported preview copy must never push to '
              'browser',
        );
      }
    });
  });

  
  group('main.dart wiring — in-app PDF preview', () {
    late String mainSrc;
    setUpAll(() async {
      mainSrc = await File('lib/main.dart').readAsString();
    });

    test('imports the pdf_preview conditional', () {
      expect(mainSrc, contains("import 'pdf_preview.dart'"));
    });

    test('_openPdfPreviewDialog is declared with an HtmlElementView '
        'render path', () {
      final idx = mainSrc.indexOf('Future<void> _openPdfPreviewDialog');
      expect(idx, greaterThan(-1),
          reason: 'main.dart must declare the in-app PDF preview '
              'dialog');
      final end = mainSrc.indexOf(
        'Future<void> _showPdfPreviewFailureDialog', idx,
      );
      final body = mainSrc.substring(
        idx, end == -1 ? mainSrc.length : end,
      );
      expect(body, contains('HtmlElementView'),
          reason: 'PDF preview must render via HtmlElementView');
      expect(body, contains('VaultPdfPreviewer'),
          reason: 'PDF preview must use VaultPdfPreviewer');
      
      
      expect(body, contains('Icons.download_outlined'),
          reason: 'PDF preview dialog must offer a Download action');
      
      expect(
        body, isNot(contains('Open in browser')),
        reason: 'PDF preview must NEVER offer Open in browser',
      );
      expect(
        body, isNot(contains('openBytesInBrowser')),
        reason: 'PDF preview must NEVER call openBytesInBrowser',
      );
    });

    test('failure dialog never pushes the user to a browser', () {
      final idx = mainSrc.indexOf(
        'Future<void> _showPdfPreviewFailureDialog',
      );
      expect(idx, greaterThan(-1));
      final end = mainSrc.indexOf('\n  }\n', idx);
      final body = mainSrc.substring(
        idx, end == -1 ? mainSrc.length : end,
      );
      expect(body, contains('pdfPreviewFailedMessage'),
          reason: 'failure dialog must use the spec failure copy');
      expect(body, contains('Icons.download_outlined'),
          reason: 'failure dialog must still offer Download');
      expect(
        body, isNot(contains('openBytesInBrowser')),
        reason: 'failure dialog must NEVER push to browser',
      );
      expect(
        body, isNot(contains('Open in browser')),
      );
    });

    test('chat handler routes PDF to the in-app dialog BEFORE the '
        'unsupported fallback', () {
      
      
      final pdfMimeIdx = mainSrc.indexOf("'application/pdf'");
      final pdfDialogIdx = mainSrc.indexOf('_openPdfPreviewDialog(');
      final unsupportedIdx =
          mainSrc.indexOf('_showUnsupportedPreviewDialog(');
      expect(pdfMimeIdx, greaterThan(-1));
      expect(pdfDialogIdx, greaterThan(pdfMimeIdx));
      expect(unsupportedIdx, greaterThan(pdfDialogIdx),
          reason: 'PDF branch must run BEFORE the unsupported '
              'fallback dialog');
    });
  });

  
  group('vault privacy in PDF preview', () {
    test('pdf_preview_web does not interpolate vault_name / file_id '
        'into the blob URL or iframe attributes', () async {
      final src = await File('lib/pdf_preview_web.dart').readAsString();
      
      
      final stripped = src
          .replaceAll(RegExp(r'/\*.*?\*/', dotAll: true), '')
          .split('\n')
          .map((line) {
            final idx = line.indexOf('//');
            return idx == -1 ? line : line.substring(0, idx);
          })
          .join('\n');
      
      
      final body = stripped.replaceAll(
        RegExp(r'class\s+\w*Vault\w*'), '',
      );
      for (final smell in const [
        'vault_name', 'vaultName',
        'vault_id', 'vaultId',
        'file_id', 'fileId',
        'session_token', 'sessionToken',
      ]) {
        expect(
          body.contains(smell), isFalse,
          reason: 'pdf_preview_web.dart body must not reference '
              '$smell — the iframe surface should be value-blind',
        );
      }
    });

    test('preview-failure copy carries no identifiers', () {
      final msg = pdfPreviewFailedMessage();
      
      
      expect(msg, isNot(contains('http')));
      expect(msg, isNot(contains('://')));
      expect(msg.toLowerCase(), isNot(contains('token')));
    });
  });
}
