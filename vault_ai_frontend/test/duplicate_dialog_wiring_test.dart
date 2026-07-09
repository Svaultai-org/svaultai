

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/upload_queue.dart';


UploadJob _job(String id, {String? duplicateAction}) {
  return UploadJob(
    id: id,
    name: '$id.pdf',
    kind: 'file',
    size: 5,
    readBytes: () async => Uint8List.fromList([1, 2, 3, 4, 5]),
  )..duplicateAction = duplicateAction;
}

const _duplicateDetail = <String, dynamic>{
  'existing_file_id': 'existing-1',
  'existing_file_name': 'statement.pdf',
  'existing_saved_name': 'Bank Statement',
  'existing_relative_path': 'Bank/statement.pdf',
  'incoming_file_name': 'statement.pdf',
  'incoming_size': 5,
  'message': 'This file already exists in your vault.',
};


void main() {
  group('UploadQueueController — resolver invocation', () {
    test('throws → resolver called once with detail + job', () async {
      Map<String, dynamic>? capturedDetail;
      UploadJob? capturedJob;
      var resolverCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const DuplicateUploadDecisionRequired(_duplicateDetail);
        },
        onDuplicate: (job, detail) async {
          resolverCalls += 1;
          capturedDetail = detail;
          capturedJob = job;
          return DuplicateUploadDecision.skip;
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();

      expect(resolverCalls, equals(1));
      expect(capturedJob?.id, equals('j1'));
      expect(
        capturedDetail?['existing_file_id'],
        equals('existing-1'),
      );
      queue.dispose();
    });
  });

  group('Skip outcome', () {
    test('flips job to skippedDuplicate and exposes existing file id',
        () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const DuplicateUploadDecisionRequired(_duplicateDetail);
        },
        onDuplicate: (job, detail) async {
          return DuplicateUploadDecision.skip;
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();

      final job = queue.jobs.single;
      expect(job.status, equals(UploadJobStatus.skippedDuplicate));
      
      expect(job.uploadedFileId, equals('existing-1'));
      
      expect(
        job.duplicateDetail?['existing_relative_path'],
        equals('Bank/statement.pdf'),
      );
      queue.dispose();
    });

    test('does not count toward waitForIdle uploaded ids', () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const DuplicateUploadDecisionRequired(_duplicateDetail);
        },
        onDuplicate: (job, detail) async =>
            DuplicateUploadDecision.skip,
      );
      queue.enqueue(_job('j1'));
      final ids = await queue.waitForIdle();
      expect(ids, isEmpty);
      queue.dispose();
    });

    test('does not retry — second action call never happens', () async {
      var actionCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          actionCalls += 1;
          throw const DuplicateUploadDecisionRequired(_duplicateDetail);
        },
        onDuplicate: (job, detail) async =>
            DuplicateUploadDecision.skip,
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(actionCalls, equals(1));
      queue.dispose();
    });
  });

  group('Keep both outcome', () {
    test(
        're-runs action with duplicateAction=keep_both and succeeds',
        () async {
      var actionCalls = 0;
      String? secondCallDuplicateAction;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          actionCalls += 1;
          if (actionCalls == 1) {
            
            throw const DuplicateUploadDecisionRequired(_duplicateDetail);
          }
          
          
          secondCallDuplicateAction = job.duplicateAction;
          return const UploadResult(
            fileId: 'new-copy-id',
            message: 'Saved as statement (1).pdf',
          );
        },
        onDuplicate: (job, detail) async {
          return DuplicateUploadDecision.keepBoth;
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();

      expect(actionCalls, equals(2));
      expect(secondCallDuplicateAction, equals('keep_both'));

      final job = queue.jobs.single;
      expect(job.status, equals(UploadJobStatus.uploaded));
      expect(job.uploadedFileId, equals('new-copy-id'));
      queue.dispose();
    });

    test('uploaded id IS returned by waitForIdle on success', () async {
      var actionCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          actionCalls += 1;
          if (actionCalls == 1) {
            throw const DuplicateUploadDecisionRequired(_duplicateDetail);
          }
          return const UploadResult(fileId: 'new-copy-id');
        },
        onDuplicate: (job, detail) async =>
            DuplicateUploadDecision.keepBoth,
      );
      queue.enqueue(_job('j1'));
      final ids = await queue.waitForIdle();
      expect(ids, equals(['new-copy-id']));
      queue.dispose();
    });
  });

  group('Batch / auto-skip path', () {
    test(
        'batch upload returning skipped_duplicate flag never calls '
        'resolver', () async {
      var resolverCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          
          
          return const UploadResult(
            fileId: 'existing-1',
            skippedDuplicate: true,
          );
        },
        onDuplicate: (job, detail) async {
          resolverCalls += 1;
          return DuplicateUploadDecision.skip;
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();

      expect(resolverCalls, equals(0),
          reason: 'batch dedup must never surface a dialog per file');
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.skippedDuplicate),
      );
      queue.dispose();
    });

    test(
        'many batch dedups bump skippedDuplicateCount without any '
        'dialog interactions',
        () async {
      var resolverCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 2,
        action: (job, bytes, report) async => const UploadResult(
          fileId: 'existing-1',
          skippedDuplicate: true,
        ),
        onDuplicate: (job, detail) async {
          resolverCalls += 1;
          return DuplicateUploadDecision.skip;
        },
      );
      queue.enqueueAll([
        for (var i = 0; i < 5; i++) _job('j$i'),
      ]);
      await queue.waitForIdle();
      expect(resolverCalls, equals(0));
      expect(queue.skippedDuplicateCount, equals(5));
      queue.dispose();
    });
  });

  group('Non-duplicate uploads never trigger the resolver', () {
    test('plain success → resolver never called', () async {
      var resolverCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async => const UploadResult(
          fileId: 'new-1',
        ),
        onDuplicate: (job, detail) async {
          resolverCalls += 1;
          return DuplicateUploadDecision.skip;
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

    test('plain failure (not a duplicate) → resolver never called',
        () async {
      var resolverCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        maxAttempts: 1,
        action: (job, bytes, report) async {
          throw Exception('something else broke');
        },
        onDuplicate: (job, detail) async {
          resolverCalls += 1;
          return DuplicateUploadDecision.skip;
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(resolverCalls, equals(0));
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.failed),
      );
      queue.dispose();
    });
  });

  group('Safety defaults — no resolver attached', () {
    test('duplicate without resolver defaults to Skip, never re-runs',
        () async {
      var actionCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          actionCalls += 1;
          throw const DuplicateUploadDecisionRequired(_duplicateDetail);
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(actionCalls, equals(1),
          reason: 'must not silently retry without affirmative consent');
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.skippedDuplicate),
      );
      queue.dispose();
    });

    test('resolver returning null also defaults to Skip', () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const DuplicateUploadDecisionRequired(_duplicateDetail);
        },
        onDuplicate: (job, detail) async => null,
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.skippedDuplicate),
      );
      queue.dispose();
    });

    test('resolver throwing also defaults to Skip', () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const DuplicateUploadDecisionRequired(_duplicateDetail);
        },
        onDuplicate: (job, detail) async {
          throw Exception('host crashed mid-dialog');
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.skippedDuplicate),
      );
      queue.dispose();
    });
  });

  group('Source guard: main.dart wires the resolver + dialog', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('UploadQueueController is built with onDuplicate', () {
      final src = readMain();
      expect(
        src,
        contains('onDuplicate: _resolveUploadDuplicate'),
        reason:
            'the chat dashboard must hand the resolver to the queue '
            'so duplicate 409s pop the dialog',
      );
    });

    test('_resolveUploadDuplicate shows the DuplicateUploadDialog',
        () {
      final src = readMain();
      expect(
        src,
        contains('DuplicateUploadDialog.show('),
        reason: 'resolver must render the Skip / Keep both dialog',
      );
    });

    test('Skip path shows the "Skipped duplicate …" snack', () {
      final src = readMain();
      expect(
        src,
        contains('Skipped duplicate file already in your vault.'),
        reason: 'Skip must surface the spec-mandated snack copy',
      );
    });

    test('Keep both maps to DuplicateUploadDecision.keepBoth', () {
      final src = readMain();
      expect(
        src,
        contains('return DuplicateUploadDecision.keepBoth'),
      );
      expect(
        src,
        contains('return DuplicateUploadDecision.skip'),
      );
    });

    test('Batch context short-circuits the resolver to Skip', () {
      final src = readMain();
      
      
      expect(
        src,
        contains('isBatchUpload == true'),
        reason:
            'resolver must short-circuit when context says batch',
      );
    });

    test('main.dart imports the duplicate_dialog module', () {
      final src = readMain();
      expect(
        src,
        contains("import 'ui/chat/duplicate_dialog.dart'"),
      );
    });

    test('main.dart throws the queue-owned exception (not a private '
        'wrapper)', () {
      final src = readMain();
      expect(
        src,
        contains('throw DuplicateUploadDecisionRequired('),
      );
      
      
      expect(
        src,
        isNot(contains('_DuplicatePromptUploadException')),
      );
    });
  });

  group('Source guard: upload_queue.dart resolver contract', () {
    String readQueue() {
      final file = File('lib/services/upload_queue.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('exports DuplicateUploadDecisionRequired exception', () {
      expect(
        readQueue(),
        contains('class DuplicateUploadDecisionRequired'),
      );
    });

    test('exports DuplicateUploadDecision enum + DuplicateResolver typedef',
        () {
      final src = readQueue();
      expect(src, contains('enum DuplicateUploadDecision'));
      expect(src, contains('typedef DuplicateResolver'));
    });

    test('controller accepts onDuplicate in its constructor', () {
      expect(readQueue(), contains('this.onDuplicate'));
    });

    test('worker catches DuplicateUploadDecisionRequired', () {
      expect(
        readQueue(),
        contains('on DuplicateUploadDecisionRequired'),
      );
    });
  });
}
