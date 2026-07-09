

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/content_hash.dart';
import 'package:vault_ai_frontend/services/upload_queue.dart';
import 'package:vault_ai_frontend/ui/chat/duplicate_dialog.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


void main() {
  group('computeContentSha256', () {
    test('returns lowercase 64-char hex', () {
      final hex = computeContentSha256(Uint8List.fromList([1, 2, 3]));
      expect(hex.length, equals(64));
      expect(hex, equals(hex.toLowerCase()));
      expect(RegExp(r'^[0-9a-f]{64}$').hasMatch(hex), isTrue);
    });

    test('same bytes produce same hash on repeat calls', () {
      final a = computeContentSha256(Uint8List.fromList([1, 2, 3]));
      final b = computeContentSha256(Uint8List.fromList([1, 2, 3]));
      expect(a, equals(b));
    });

    test('different bytes produce different hashes', () {
      final a = computeContentSha256(Uint8List.fromList([1, 2, 3]));
      final b = computeContentSha256(Uint8List.fromList([1, 2, 4]));
      expect(a, isNot(equals(b)));
    });

    test('hash of empty bytes matches the known SHA-256 of "" ', () {
      
      expect(
        computeContentSha256(Uint8List(0)),
        equals(
          'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        ),
      );
    });

    test('hash of "abc" matches the known SHA-256 fixture', () {
      
      
      expect(
        computeContentSha256(Uint8List.fromList('abc'.codeUnits)),
        equals(
          'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
        ),
      );
    });

    test('hash works for large buffers (images / videos)', () {
      
      
      final big = Uint8List(1024 * 1024);
      for (var i = 0; i < big.length; i++) {
        big[i] = i & 0xFF;
      }
      final hex = computeContentSha256(big);
      expect(hex.length, equals(64));
    });
  });

  group('shortHashForLog', () {
    test('returns at most 8 chars', () {
      const fullHash =
          'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
      expect(shortHashForLog(fullHash), equals('e3b0c442'));
      expect(shortHashForLog(fullHash).length, equals(8));
    });

    test('returns "-" for null / empty', () {
      expect(shortHashForLog(null), equals('-'));
      expect(shortHashForLog(''), equals('-'));
    });

    test('never returns more than 8 chars for any input', () {
      for (final input in [
        'a' * 64,
        'deadbeef' * 8,
        'x' * 100,
      ]) {
        expect(shortHashForLog(input).length, lessThanOrEqualTo(8));
      }
    });
  });

  group('DuplicateAction wire values', () {
    test('all four actions have wire strings matching the backend', () {
      
      expect(DuplicateAction.prompt.wireValue, equals('prompt'));
      expect(DuplicateAction.skip.wireValue, equals('skip'));
      expect(DuplicateAction.keepBoth.wireValue, equals('keep_both'));
      expect(DuplicateAction.replace.wireValue, equals('replace'));
    });
  });

  group('DuplicateFoundDetail.fromJson', () {
    test('parses a full 409 detail block', () {
      final detail = DuplicateFoundDetail.fromJson({
        'existing_file_id': 'f-1',
        'existing_file_name': 'statement.pdf',
        'existing_saved_name': 'Bank Statement',
        'existing_relative_path': 'Bank/statement.pdf',
        'existing_uploaded_at': '2026-05-12T10:00:00Z',
        'incoming_file_name': 'statement.pdf',
        'incoming_size': 12345,
        'message': 'This file already exists in your vault.',
      });
      expect(detail.existingFileId, equals('f-1'));
      expect(detail.existingSavedName, equals('Bank Statement'));
      expect(detail.existingRelativePath, equals('Bank/statement.pdf'));
      expect(detail.incomingFileName, equals('statement.pdf'));
      expect(detail.incomingSize, equals(12345));
      expect(detail.message, contains('already exists'));
    });

    test('falls back gracefully when optional fields are missing', () {
      final detail = DuplicateFoundDetail.fromJson({
        'existing_file_id': 'f-1',
        'incoming_file_name': 'loose.pdf',
        'incoming_size': 100,
        'message': 'Dup.',
      });
      expect(detail.existingFileName, isNull);
      expect(detail.existingSavedName, isNull);
      expect(detail.existingRelativePath, isNull);
      expect(detail.existingUploadedAt, isNull);
    });
  });

  group('UploadQueueController — skippedDuplicate status', () {
    test('skippedDuplicate is terminal (no retry)', () {
      final job = UploadJob(
        id: 'j1',
        name: 'a.pdf',
        kind: 'file',
        size: 100,
        readBytes: () async => Uint8List(100),
      );
      job.status = UploadJobStatus.skippedDuplicate;
      expect(job.isTerminal, isTrue);
    });

    test('queue worker flips to skippedDuplicate on UploadResult flag',
        () async {
      final queue = UploadQueueController(
        action: (job, bytes, report) async {
          return const UploadResult(
            fileId: 'existing-1',
            skippedDuplicate: true,
            message: 'Already in your vault.',
          );
        },
        maxConcurrency: 1,
      );
      queue.enqueue(UploadJob(
        id: 'j1',
        name: 'a.pdf',
        kind: 'file',
        size: 5,
        readBytes: () async => Uint8List.fromList([1, 2, 3, 4, 5]),
      ));
      await queue.waitForIdle();
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.skippedDuplicate),
      );
      
      expect(
        queue.jobs.single.uploadedFileId,
        equals('existing-1'),
      );
      queue.dispose();
    });

    test('skippedDuplicateCount getter reports correctly', () async {
      var firstCall = true;
      final queue = UploadQueueController(
        action: (job, bytes, report) async {
          final isFirst = firstCall;
          firstCall = false;
          if (isFirst) {
            return const UploadResult(fileId: 'new-1');
          }
          return const UploadResult(
            fileId: 'existing-1',
            skippedDuplicate: true,
          );
        },
        maxConcurrency: 1,
      );
      queue.enqueueAll([
        UploadJob(
          id: 'j1',
          name: 'a.pdf',
          kind: 'file',
          size: 5,
          readBytes: () async => Uint8List(5),
        ),
        UploadJob(
          id: 'j2',
          name: 'a-copy.pdf',
          kind: 'file',
          size: 5,
          readBytes: () async => Uint8List(5),
        ),
      ]);
      await queue.waitForIdle();
      expect(queue.uploadedCount, equals(1));
      expect(queue.skippedDuplicateCount, equals(1));
      queue.dispose();
    });

    test(
        'waitForIdle does NOT count skipped-duplicate fileIds as '
        'newly uploaded',
        () async {
      final queue = UploadQueueController(
        action: (job, bytes, report) async {
          return const UploadResult(
            fileId: 'existing-1',
            skippedDuplicate: true,
          );
        },
        maxConcurrency: 1,
      );
      queue.enqueue(UploadJob(
        id: 'j1',
        name: 'a.pdf',
        kind: 'file',
        size: 5,
        readBytes: () async => Uint8List(5),
      ));
      final ids = await queue.waitForIdle();
      
      
      expect(ids, isEmpty);
      queue.dispose();
    });

    test('retry() is a no-op for skippedDuplicate jobs', () async {
      final queue = UploadQueueController(
        action: (job, bytes, report) async => const UploadResult(
          fileId: 'existing-1',
          skippedDuplicate: true,
        ),
        maxConcurrency: 1,
      );
      queue.enqueue(UploadJob(
        id: 'j1',
        name: 'a.pdf',
        kind: 'file',
        size: 5,
        readBytes: () async => Uint8List(5),
      ));
      await queue.waitForIdle();
      
      
      queue.retry('j1');
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.skippedDuplicate),
      );
      queue.dispose();
    });
  });

  group('formatImportSummary', () {
    test('exact spec copy: "Saved 218 files. Skipped 22 duplicates …"',
        () {
      expect(
        formatImportSummary(
          savedCount: 218,
          skippedDuplicateCount: 22,
          failedCount: 0,
        ),
        equals(
          'Saved 218 files. '
          'Skipped 22 duplicates already in your vault.',
        ),
      );
    });

    test('singular when only one of each', () {
      expect(
        formatImportSummary(
          savedCount: 1,
          skippedDuplicateCount: 1,
          failedCount: 0,
        ),
        equals(
          'Saved 1 file. '
          'Skipped 1 duplicate already in your vault.',
        ),
      );
    });

    test('omits zero buckets', () {
      expect(
        formatImportSummary(
          savedCount: 3,
          skippedDuplicateCount: 0,
          failedCount: 0,
        ),
        equals('Saved 3 files.'),
      );
    });

    test('includes failures when present', () {
      expect(
        formatImportSummary(
          savedCount: 10,
          skippedDuplicateCount: 2,
          failedCount: 3,
        ),
        contains('3 uploads failed.'),
      );
    });

    test('nothing-to-import edge case', () {
      expect(
        formatImportSummary(
          savedCount: 0,
          skippedDuplicateCount: 0,
          failedCount: 0,
        ),
        equals('Nothing to import.'),
      );
    });
  });

  group('DuplicateUploadDialog — interactive', () {
    DuplicateFoundDetail detailFixture({
      String existingPath = 'Bank/statement.pdf',
    }) {
      return DuplicateFoundDetail(
        existingFileId: 'f-1',
        existingFileName: 'statement.pdf',
        existingSavedName: 'Bank Statement',
        existingRelativePath: existingPath,
        existingUploadedAt: '2026-05-12T10:00:00Z',
        incomingFileName: 'statement.pdf',
        incomingSize: 1234,
        message: 'This file already exists in your vault.',
      );
    }

    testWidgets(
        'shows the existing file path and a Skip + Keep both pair',
        (tester) async {
      late BuildContext capturedCtx;
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: _testL10nDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Builder(builder: (ctx) {
            capturedCtx = ctx;
            return const SizedBox.shrink();
          }),
        ),
      );

      
      DuplicateUploadDialog.show(
        capturedCtx,
        detail: detailFixture(),
      );
      await tester.pumpAndSettle();

      expect(find.text('Bank Statement'), findsOneWidget);
      expect(find.text('Bank/statement.pdf'), findsOneWidget);
      expect(find.text('Skip'), findsOneWidget);
      expect(find.text('Keep both'), findsOneWidget);
    });

    testWidgets('Skip button resolves with DuplicateDialogChoice.skip',
        (tester) async {
      late BuildContext capturedCtx;
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: _testL10nDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Builder(builder: (ctx) {
            capturedCtx = ctx;
            return const SizedBox.shrink();
          }),
        ),
      );

      final future = DuplicateUploadDialog.show(
        capturedCtx,
        detail: detailFixture(),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Skip'));
      await tester.pumpAndSettle();
      expect(await future, equals(DuplicateDialogChoice.skip));
    });

    testWidgets(
        'Keep both button resolves with DuplicateDialogChoice.keepBoth',
        (tester) async {
      late BuildContext capturedCtx;
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: _testL10nDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Builder(builder: (ctx) {
            capturedCtx = ctx;
            return const SizedBox.shrink();
          }),
        ),
      );

      final future = DuplicateUploadDialog.show(
        capturedCtx,
        detail: detailFixture(),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Keep both'));
      await tester.pumpAndSettle();
      expect(await future, equals(DuplicateDialogChoice.keepBoth));
    });

    testWidgets(
        'omits the folder line when the existing file is un-foldered',
        (tester) async {
      late BuildContext capturedCtx;
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: _testL10nDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Builder(builder: (ctx) {
            capturedCtx = ctx;
            return const SizedBox.shrink();
          }),
        ),
      );

      
      DuplicateUploadDialog.show(
        capturedCtx,
        detail: detailFixture(existingPath: ''),
      );
      await tester.pumpAndSettle();
      expect(find.byIcon(Icons.folder_outlined), findsNothing);
    });
  });

  group('Source guard: main.dart wires hash + duplicate_action', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('imports the content_hash service', () {
      expect(readMain(), contains("services/content_hash.dart"));
    });

    test('computes SHA-256 inside _runUploadAction', () {
      final src = readMain();
      expect(src, contains('computeContentSha256(bytes)'));
    });

    test('routes batch uploads through duplicate_action: skip', () {
      final src = readMain();
      
      
      expect(src, contains("'skip'"));
      expect(src, contains("'prompt'"));
    });

    test('passes contentSha256 + duplicateAction to uploadVaultFile',
        () {
      final src = readMain();
      expect(src, contains('contentSha256: contentSha256'));
      expect(src, contains('duplicateAction: duplicateAction'));
    });

    test('catches DuplicateFoundUploadException from the API client',
        () {
      final src = readMain();
      expect(
        src,
        contains('on DuplicateFoundUploadException'),
        reason: 'the 409 path must be surfaced as a typed exception '
                'so the host can route to the dialog',
      );
    });

    test('skipped_duplicate response flips UploadResult flag', () {
      final src = readMain();
      
      expect(src, contains("'skipped_duplicate'"));
      expect(src, contains('skippedDuplicate: true'));
    });
  });

  group('Source guard: api_client.dart parses 409 duplicate_found', () {
    test('throws DuplicateFoundUploadException for 409 envelope', () {
      final file = File('lib/api_client.dart');
      expect(file.existsSync(), isTrue);
      final src = file.readAsStringSync();
      expect(src, contains("class DuplicateFoundUploadException"));
      expect(
        src,
        contains("'duplicate_found'"),
        reason: 'the parser must recognise the backend\'s detail.code',
      );
      expect(src, contains('throw DuplicateFoundUploadException('));
    });

    test('uploadVaultFile accepts contentSha256 + duplicateAction', () {
      final file = File('lib/api_client.dart');
      final src = file.readAsStringSync();
      expect(src, contains('String? contentSha256'));
      expect(src, contains('String? duplicateAction'));
      expect(
        src,
        contains("request.fields['content_sha256'] = contentSha256"),
      );
      expect(
        src,
        contains(
            "request.fields['duplicate_action'] = duplicateAction"),
      );
    });
  });

  group('Source guard: content_hash.dart uses crypto + log redactor',
      () {
    test('imports package:crypto and exposes the SHA-256 helper', () {
      final file = File('lib/services/content_hash.dart');
      expect(file.existsSync(), isTrue);
      final src = file.readAsStringSync();
      expect(src, contains("import 'package:crypto/crypto.dart';"));
      expect(src, contains('sha256.convert(bytes)'));
    });

    test('shortHashForLog caps output length at 8 chars', () {
      final file = File('lib/services/content_hash.dart');
      final src = file.readAsStringSync();
      expect(src, contains('substring(0, 8)'));
    });
  });

  group('Source guard: upload_queue.dart adds skippedDuplicate', () {
    test('enum has skippedDuplicate variant', () {
      final file = File('lib/services/upload_queue.dart');
      expect(file.existsSync(), isTrue);
      final src = file.readAsStringSync();
      expect(src, contains('skippedDuplicate,'));
    });

    test('isTerminal returns true for skippedDuplicate', () {
      final file = File('lib/services/upload_queue.dart');
      final src = file.readAsStringSync();
      expect(
        src,
        contains('UploadJobStatus.skippedDuplicate'),
      );
      
      expect(
        src.contains(
            'status == UploadJobStatus.skippedDuplicate'),
        isTrue,
      );
    });

    test('worker flips status to skippedDuplicate on flag', () {
      final file = File('lib/services/upload_queue.dart');
      final src = file.readAsStringSync();
      expect(src, contains('result.skippedDuplicate'));
      expect(
        src,
        contains('job.status = UploadJobStatus.skippedDuplicate'),
      );
    });
  });
}
