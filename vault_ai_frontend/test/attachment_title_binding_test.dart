import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/attachment_title_binding.dart';

String _readMain() => File('lib/main.dart').readAsStringSync();
String _readUploadQueue() =>
    File('lib/services/upload_queue.dart').readAsStringSync();
String _readApiClient() => File('lib/api_client.dart').readAsStringSync();

void main() {
  group('attachment title binding', () {
    test('treats simple Android composer text as the attachment title', () {
      expect(
        attachmentTitleFromComposerText(
          'daily dally',
          attachmentCount: 1,
        ),
        'daily dally',
      );
      expect(
        attachmentTitleFromComposerText(
          'osun road marking',
          attachmentCount: 1,
        ),
        'osun road marking',
      );
    });

    test('supports explicit naming commands', () {
      expect(
        attachmentTitleFromComposerText(
          'name it as daily dally',
          attachmentCount: 1,
        ),
        'daily dally',
      );
      expect(
        attachmentTitleFromComposerText(
          'save this file as osun road marking',
          attachmentCount: 1,
        ),
        'osun road marking',
      );
    });

    test('chosen FileV2 title keeps the media extension once', () {
      expect(
        filenameWithChosenTitle(
          originalFilename: 'video_1786488704915.webm',
          chosenTitle: 'beef video',
        ),
        'beef video.webm',
      );
      expect(
        filenameWithChosenTitle(
          originalFilename: 'recording.m4a',
          chosenTitle: 'interview.m4a',
        ),
        'interview.m4a',
      );
    });

    test('does not capture questions, instructions, or multi-file text', () {
      expect(
        attachmentTitleFromComposerText(
          'what is in this image?',
          attachmentCount: 1,
        ),
        isNull,
      );
      expect(
        attachmentTitleFromComposerText(
          'summarize this PDF',
          attachmentCount: 1,
        ),
        isNull,
      );
      expect(
        attachmentTitleFromComposerText(
          'daily dally',
          attachmentCount: 2,
        ),
        isNull,
      );
    });
  });

  group('attachment upload source guards', () {
    test('_send binds title text before upload and does not send it to chat',
        () {
      final src = _readMain();
      expect(src, contains('attachmentTitleFromComposerText('));
      expect(
        src,
        contains('accompanyingText: attachmentTitle == null ? text : null'),
      );
      expect(src, contains('if (hadAttachments && attachmentTitle != null)'));
      expect(src, contains('name: a.displayName ?? a.name'));
      expect(
        src,
        contains(
          '!sending && (input.text.trim().isNotEmpty || attachments.isNotEmpty)',
        ),
      );
      expect(src, contains('uploadCommitted && hadAttachments'));
      expect(
        src,
        contains('Your file was saved. I could not complete the optional'),
      );
    });

    test('upload jobs carry the user-visible title to the upload action', () {
      final queue = _readUploadQueue();
      expect(queue, contains('final String? displayName;'));
      expect(queue, contains('this.displayName,'));

      final main = _readMain();
      expect(main, contains('displayName: a.displayName,'));
      expect(main, contains('job.displayName?.trim()'));
      expect(main, contains('await ctx.client.nameVaultFile('));
    });

    test('Files list decrypts encrypted saved names and clears naming prompt',
        () {
      final api = _readApiClient();
      expect(api, contains('_decryptUploadedFileMetadataForActiveZkVault'));
      expect(
          api, contains("await fill('saved_name', 'saved_name_ciphertext')"));
      expect(api, contains("map['needs_naming'] = false"));

      final folderIdx = api.indexOf("Future<Map<String, dynamic>> listFolder(");
      expect(folderIdx, greaterThan(-1));
      final folderBody = api.substring(
        folderIdx,
        api.indexOf('Future<Map<String, dynamic>> startImport(', folderIdx),
      );
      expect(
        folderBody,
        contains('await _decryptUploadedFileMetadataForActiveZkVault(decoded)'),
      );
    });
  });
}
