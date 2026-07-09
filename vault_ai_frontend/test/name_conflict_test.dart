

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
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


UploadJob _job(String id) {
  return UploadJob(
    id: id,
    name: '$id.pdf',
    kind: 'file',
    size: 5,
    readBytes: () async => Uint8List.fromList([1, 2, 3, 4, 5]),
  );
}

const _nameConflictDetail = <String, dynamic>{
  'existing_file_id': 'f-1',
  'existing_file_name': 'statement.pdf',
  'existing_saved_name': 'statement.pdf',
  'existing_relative_path': 'Bank',
  'existing_uploaded_at': '2026-04-01T10:00:00Z',
  'incoming_file_name': 'statement.pdf',
  'incoming_size': 5,
  'proposed_versioned_name': 'statement (1).pdf',
  'message':
      'A file with this name already exists in this folder, but the '
      'content is different. (Existing at Bank)',
};


void main() {
  group('NameConflictDetail.fromJson', () {
    test('parses a full 409 detail block', () {
      final detail = NameConflictDetail.fromJson(_nameConflictDetail);
      expect(detail.existingFileId, equals('f-1'));
      expect(detail.existingFileName, equals('statement.pdf'));
      expect(detail.existingSavedName, equals('statement.pdf'));
      expect(detail.existingRelativePath, equals('Bank'));
      expect(detail.proposedVersionedName, equals('statement (1).pdf'));
      expect(detail.incomingFileName, equals('statement.pdf'));
      expect(detail.incomingSize, equals(5));
      expect(detail.message, contains('content is different'));
    });

    test('falls back gracefully when optional fields are missing', () {
      final detail = NameConflictDetail.fromJson({
        'existing_file_id': 'f-1',
        'incoming_file_name': 'loose.pdf',
        'incoming_size': 100,
      });
      expect(detail.existingFileName, isNull);
      expect(detail.existingSavedName, isNull);
      expect(detail.existingRelativePath, isNull);
      expect(detail.proposedVersionedName, isNull);
      
      expect(detail.message, contains('content is different'));
    });
  });

  group('UploadQueueController — name-conflict resolver', () {
    test('resolver is called when the action throws', () async {
      var resolverCalls = 0;
      Map<String, dynamic>? capturedDetail;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const NameConflictDecisionRequired(
            _nameConflictDetail,
          );
        },
        onNameConflict: (job, detail) async {
          resolverCalls += 1;
          capturedDetail = detail;
          return NameConflictDecision.cancel;
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(resolverCalls, equals(1));
      expect(
        capturedDetail?['proposed_versioned_name'],
        equals('statement (1).pdf'),
      );
      queue.dispose();
    });

    test('Cancel flips the job to cancelled (nothing saved)', () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const NameConflictDecisionRequired(
            _nameConflictDetail,
          );
        },
        onNameConflict: (job, detail) async =>
            NameConflictDecision.cancel,
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.cancelled),
      );
      
      expect(
        queue.jobs.single.duplicateDetail?['existing_file_id'],
        equals('f-1'),
      );
      queue.dispose();
    });

    test(
        'Keep both re-runs action with duplicateAction=keep_both and '
        'succeeds',
        () async {
      var actionCalls = 0;
      String? secondCallAction;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          actionCalls += 1;
          if (actionCalls == 1) {
            throw const NameConflictDecisionRequired(
              _nameConflictDetail,
            );
          }
          secondCallAction = job.duplicateAction;
          return const UploadResult(
            fileId: 'new-versioned-id',
            renamed: true,
            originalSavedName: 'statement.pdf',
            message: 'Saved as statement (1).pdf',
          );
        },
        onNameConflict: (job, detail) async =>
            NameConflictDecision.keepBoth,
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(actionCalls, equals(2));
      expect(secondCallAction, equals('keep_both'));

      final job = queue.jobs.single;
      expect(job.status, equals(UploadJobStatus.uploaded));
      expect(job.uploadedFileId, equals('new-versioned-id'));
      expect(job.lastResult?.renamed, isTrue);
      queue.dispose();
    });

    test('no resolver attached → defaults to Cancel', () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const NameConflictDecisionRequired(
            _nameConflictDetail,
          );
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.cancelled),
      );
      queue.dispose();
    });

    test('resolver throwing → defaults to Cancel', () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const NameConflictDecisionRequired(
            _nameConflictDetail,
          );
        },
        onNameConflict: (job, detail) async {
          throw Exception('host crashed mid-dialog');
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.cancelled),
      );
      queue.dispose();
    });

    test(
        'replace decision is also treated as Cancel (deferred per spec)',
        () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const NameConflictDecisionRequired(
            _nameConflictDetail,
          );
        },
        onNameConflict: (job, detail) async =>
            NameConflictDecision.replace,
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.cancelled),
      );
      queue.dispose();
    });
  });

  group('Batch auto-version (no resolver invocation)', () {
    test(
        'batch action returning renamed: true never calls resolver, '
        'job is uploaded',
        () async {
      var resolverCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          
          
          return const UploadResult(
            fileId: 'new-1',
            renamed: true,
            originalSavedName: 'statement.pdf',
          );
        },
        onNameConflict: (job, detail) async {
          resolverCalls += 1;
          return NameConflictDecision.cancel;
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(resolverCalls, equals(0));
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.uploaded),
      );
      queue.dispose();
    });

    test(
        'many batch auto-versions bump renamedCount without any '
        'dialog interactions',
        () async {
      var resolverCalls = 0;
      var counter = 0;
      final queue = UploadQueueController(
        maxConcurrency: 2,
        action: (job, bytes, report) async {
          counter += 1;
          return UploadResult(
            fileId: 'new-$counter',
            renamed: true,
            originalSavedName: 'statement.pdf',
          );
        },
        onNameConflict: (job, detail) async {
          resolverCalls += 1;
          return NameConflictDecision.cancel;
        },
      );
      queue.enqueueAll([for (var i = 0; i < 3; i++) _job('j$i')]);
      await queue.waitForIdle();
      expect(resolverCalls, equals(0));
      expect(queue.renamedCount, equals(3));
      expect(queue.uploadedCount, equals(3));
      queue.dispose();
    });
  });

  group('Non-conflict uploads never trigger the resolver', () {
    test('plain success → resolver never called', () async {
      var resolverCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async => const UploadResult(
          fileId: 'new-1',
        ),
        onNameConflict: (job, detail) async {
          resolverCalls += 1;
          return NameConflictDecision.cancel;
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(resolverCalls, equals(0));
      expect(queue.renamedCount, equals(0));
      queue.dispose();
    });
  });

  group('formatImportSummary — Phase 4.1 rename copy', () {
    test('emits "Renamed N files to avoid name conflicts." when renamed',
        () {
      expect(
        formatImportSummary(
          savedCount: 20,
          skippedDuplicateCount: 0,
          failedCount: 0,
          renamedCount: 3,
        ),
        equals(
          'Saved 20 files. '
          'Renamed 3 files to avoid name conflicts.',
        ),
      );
    });

    test('singular when renamedCount == 1', () {
      expect(
        formatImportSummary(
          savedCount: 5,
          skippedDuplicateCount: 0,
          failedCount: 0,
          renamedCount: 1,
        ),
        equals(
          'Saved 5 files. '
          'Renamed 1 file to avoid name conflicts.',
        ),
      );
    });

    test('combined with skipped duplicates: full Phase 4 + 4.1 copy', () {
      expect(
        formatImportSummary(
          savedCount: 218,
          skippedDuplicateCount: 22,
          failedCount: 0,
          renamedCount: 3,
        ),
        equals(
          'Saved 218 files. '
          'Renamed 3 files to avoid name conflicts. '
          'Skipped 22 duplicates already in your vault.',
        ),
      );
    });

    test('omitted when renamedCount is 0 (Phase 4 baseline behaviour)',
        () {
      expect(
        formatImportSummary(
          savedCount: 5,
          skippedDuplicateCount: 0,
          failedCount: 0,
          renamedCount: 0,
        ),
        equals('Saved 5 files.'),
      );
    });
  });

  group('NameConflictDialog — interactive', () {
    NameConflictDetail detailFixture({
      String existingPath = 'Bank',
      String? proposed = 'statement (1).pdf',
    }) {
      return NameConflictDetail(
        existingFileId: 'f-1',
        existingFileName: 'statement.pdf',
        existingSavedName: 'statement.pdf',
        existingRelativePath: existingPath,
        existingUploadedAt: '2026-04-01T10:00:00Z',
        incomingFileName: 'statement.pdf',
        incomingSize: 5,
        proposedVersionedName: proposed,
        message:
            'A file with this name already exists in this folder, '
            'but the content is different.',
      );
    }

    testWidgets(
        'shows the conflict copy, the path, the proposed name + '
        'Cancel + Keep both buttons',
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

      
      NameConflictDialog.show(
        capturedCtx,
        detail: detailFixture(),
      );
      await tester.pumpAndSettle();

      
      expect(
        find.textContaining('content is different'),
        findsOneWidget,
      );
      
      expect(find.text('statement.pdf'), findsWidgets);
      expect(find.text('Bank'), findsOneWidget);
      
      expect(
        find.textContaining('statement (1).pdf'),
        findsOneWidget,
      );
      
      expect(find.text('Cancel'), findsOneWidget);
      expect(find.text('Keep both'), findsOneWidget);
    });

    testWidgets('Cancel resolves with NameConflictDialogChoice.cancel',
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

      final future = NameConflictDialog.show(
        capturedCtx,
        detail: detailFixture(),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(await future, equals(NameConflictDialogChoice.cancel));
    });

    testWidgets(
        'Keep both resolves with NameConflictDialogChoice.keepBoth',
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

      final future = NameConflictDialog.show(
        capturedCtx,
        detail: detailFixture(),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Keep both'));
      await tester.pumpAndSettle();
      expect(await future, equals(NameConflictDialogChoice.keepBoth));
    });

    testWidgets(
        'omits the proposed-name preview line when proposed is null',
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

      
      NameConflictDialog.show(
        capturedCtx,
        detail: detailFixture(proposed: null),
      );
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Keep both will save the new file as'),
        findsNothing,
      );
    });
  });

  group('Source guard: api_client.dart parses 409 name_conflict', () {
    test('throws NameConflictUploadException for code=name_conflict',
        () {
      final file = File('lib/api_client.dart');
      expect(file.existsSync(), isTrue);
      final src = file.readAsStringSync();
      expect(src, contains('class NameConflictUploadException'));
      expect(src, contains("'name_conflict'"));
      expect(src, contains('throw NameConflictUploadException('));
    });
  });

  group('Source guard: main.dart wires the resolver + dialog', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('UploadQueueController is built with onNameConflict', () {
      expect(
        readMain(),
        contains('onNameConflict: _resolveNameConflict'),
      );
    });

    test('_runUploadAction catches NameConflictUploadException', () {
      expect(
        readMain(),
        contains('on NameConflictUploadException'),
      );
    });

    test(
        '_runUploadAction throws NameConflictDecisionRequired so the '
        'queue can route it',
        () {
      expect(
        readMain(),
        contains('throw NameConflictDecisionRequired('),
      );
    });

    test('_resolveNameConflict shows the NameConflictDialog', () {
      expect(readMain(), contains('NameConflictDialog.show('));
    });

    test('Batch context short-circuits the name-conflict resolver',
        () {
      expect(
        readMain(),
        contains(
          'if (_currentUploadContext?.isBatchUpload == true)',
        ),
      );
    });

    test('UploadResult carries renamed + original_saved_name', () {
      final src = readMain();
      expect(src, contains("result['renamed'] == true"));
      expect(src, contains("result['original_saved_name']"));
    });
  });

  group('Source guard: upload_queue.dart name-conflict contract', () {
    String readQueue() {
      final file = File('lib/services/upload_queue.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('exports NameConflictDecisionRequired exception', () {
      expect(
        readQueue(),
        contains('class NameConflictDecisionRequired'),
      );
    });

    test('exports NameConflictDecision enum + NameConflictResolver typedef',
        () {
      final src = readQueue();
      expect(src, contains('enum NameConflictDecision'));
      expect(src, contains('typedef NameConflictResolver'));
    });

    test('controller accepts onNameConflict in its constructor', () {
      expect(readQueue(), contains('this.onNameConflict'));
    });

    test('worker catches NameConflictDecisionRequired', () {
      expect(
        readQueue(),
        contains('on NameConflictDecisionRequired'),
      );
    });

    test('renamedCount getter reads from UploadResult.renamed', () {
      expect(
        readQueue(),
        contains('j.lastResult?.renamed == true'),
      );
    });
  });
}
