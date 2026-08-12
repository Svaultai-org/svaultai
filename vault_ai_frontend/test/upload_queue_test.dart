

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/upload_queue.dart';


UploadJob _makeJob({
  required String id,
  int size = 16,
  Future<Uint8List> Function()? readBytes,
}) {
  return UploadJob(
    id: id,
    name: '$id.bin',
    kind: 'file',
    size: size,
    readBytes: readBytes ?? (() async => Uint8List(size)),
  );
}


void main() {
  group('UploadQueueController — lazy reads (the hang fix)', () {
    test('pending jobs do not pre-load bytes (only the active job reads)',
        () async {
      
      
      final reads = <String>{};
      final stuck = Completer<UploadResult>();
      final c = UploadQueueController(
        maxConcurrency: 1,
        action: (j, b, p) => stuck.future,
      );
      c.enqueueAll([
        _makeJob(
          id: 'a',
          readBytes: () async {
            reads.add('a');
            return Uint8List(4);
          },
        ),
        _makeJob(
          id: 'b',
          readBytes: () async {
            reads.add('b');
            return Uint8List(4);
          },
        ),
        _makeJob(
          id: 'c',
          readBytes: () async {
            reads.add('c');
            return Uint8List(4);
          },
        ),
      ]);
      await Future.delayed(const Duration(milliseconds: 50));
      expect(reads, equals({'a'}),
          reason: 'only the in-flight job should have read its bytes');
      c.dispose();
    });

    test('readBytes runs at most once per successful job', () async {
      var reads = 0;
      final job = _makeJob(
        id: 'a',
        readBytes: () async {
          reads += 1;
          return Uint8List(4);
        },
      );
      final c = UploadQueueController(
        action: (j, b, p) async => const UploadResult(fileId: 'f1'),
      );
      c.enqueue(job);
      await c.waitForIdle();
      expect(reads, 1);
      c.dispose();
    });

    test('successful upload clears cachedBytes (no held-bytes leak)',
        () async {
      final job = _makeJob(id: 'a', size: 1024);
      final c = UploadQueueController(
        action: (j, b, p) async => const UploadResult(fileId: 'f1'),
      );
      c.enqueue(job);
      await c.waitForIdle();
      expect(job.cachedBytes, isNull,
          reason: 'queue must release bytes after terminal success');
      c.dispose();
    });
  });

  group('UploadQueueController — bounded concurrency', () {
    test('at most maxConcurrency actions run at the same time',
        (() async {
      
      
      var concurrent = 0;
      var peak = 0;
      final releasers = <Completer<UploadResult>>[];

      final c = UploadQueueController(
        maxConcurrency: 3,
        action: (j, b, p) {
          concurrent += 1;
          if (concurrent > peak) peak = concurrent;
          final r = Completer<UploadResult>();
          releasers.add(r);
          return r.future.whenComplete(() => concurrent -= 1);
        },
      );

      
      for (var i = 0; i < 10; i++) {
        c.enqueue(_makeJob(id: 'j$i'));
      }

      
      await Future.delayed(const Duration(milliseconds: 50));
      expect(peak, 3,
          reason: 'queue must not start more than maxConcurrency jobs at once');
      expect(releasers.length, 3,
          reason: 'exactly maxConcurrency actions should have started');

      
      for (final r in [...releasers]) {
        r.complete(const UploadResult(fileId: 'fx'));
        
        await Future.delayed(const Duration(milliseconds: 5));
        
      }
      
      while (c.isBusy) {
        await Future.delayed(const Duration(milliseconds: 5));
        for (final r in releasers) {
          if (!r.isCompleted) {
            r.complete(const UploadResult(fileId: 'fx'));
            break;
          }
        }
      }

      expect(peak, 3,
          reason: 'cap must hold across the lifetime of the queue');
      c.dispose();
    }));
  });

  group('UploadQueueController — transient pause + retry', () {
    test('TransientUploadException retries the job until success',
        () async {
      var attemptsByJob = <String, int>{};
      final c = UploadQueueController(
        action: (j, b, p) async {
          attemptsByJob[j.id] = (attemptsByJob[j.id] ?? 0) + 1;
          if (attemptsByJob[j.id]! < 3) {
            throw const TransientUploadException('blip',
                pauseFor: Duration(milliseconds: 10));
          }
          return UploadResult(fileId: 'f-${j.id}');
        },
        maxAttempts: 5,
      );
      final job = _makeJob(id: 'a');
      c.enqueue(job);
      await c.waitForIdle();
      expect(job.status, UploadJobStatus.uploaded);
      expect(attemptsByJob['a'], 3);
      c.dispose();
    });

    test('TransientUploadException exhausts maxAttempts then fails',
        () async {
      var attempts = 0;
      final c = UploadQueueController(
        action: (j, b, p) async {
          attempts += 1;
          throw const TransientUploadException('always-fails',
              pauseFor: Duration(milliseconds: 5));
        },
        maxAttempts: 3,
      );
      final job = _makeJob(id: 'a');
      c.enqueue(job);
      await c.waitForIdle();
      expect(job.status, UploadJobStatus.failed);
      expect(attempts, 3);
      expect(job.errorMessage, contains('always-fails'));
      c.dispose();
    });

    test('pauseFor blocks NEWLY-enqueued jobs from starting until window closes',
        () async {
      
      
      var bAction = 0;
      final c = UploadQueueController(
        maxConcurrency: 3,
        maxAttempts: 1, 
        action: (j, b, p) async {
          if (j.id == 'a') {
            throw const TransientUploadException(
              'rate-limited',
              pauseFor: Duration(milliseconds: 300),
            );
          }
          bAction += 1;
          return UploadResult(fileId: 'f-${j.id}');
        },
      );

      c.enqueue(_makeJob(id: 'a'));

      
      await Future.delayed(const Duration(milliseconds: 50));
      expect(c.pauseRemaining, isNotNull,
          reason: 'pause window must be set after TransientUploadException');

      
      c.enqueue(_makeJob(id: 'b'));
      await Future.delayed(const Duration(milliseconds: 100));
      expect(bAction, 0,
          reason: 'pause window must block new dispatch');

      
      await Future.delayed(const Duration(milliseconds: 300));
      expect(bAction, 1, reason: 'after pause clears the queue resumes');
      c.dispose();
    });
  });

  group('UploadQueueController — failure modes', () {
    test('non-transient exception fails the job without retry', () async {
      var attempts = 0;
      final c = UploadQueueController(
        action: (j, b, p) async {
          attempts += 1;
          throw Exception('boom');
        },
        maxAttempts: 5,
      );
      final job = _makeJob(id: 'a');
      c.enqueue(job);
      await c.waitForIdle();
      expect(job.status, UploadJobStatus.failed);
      expect(attempts, 1,
          reason: 'non-transient errors must not retry');
      expect(job.errorMessage, contains('boom'));
      c.dispose();
    });

    test('readBytes failure marks job failed without invoking action',
        () async {
      var actionCalls = 0;
      final c = UploadQueueController(
        action: (j, b, p) async {
          actionCalls += 1;
          return const UploadResult(fileId: 'f1');
        },
      );
      c.enqueue(_makeJob(
        id: 'a',
        readBytes: () async => throw Exception('unreadable'),
      ));
      await c.waitForIdle();
      expect(actionCalls, 0);
      expect(c.failedCount, 1);
      c.dispose();
    });
  });

  group('UploadQueueController — cancellation', () {
    test('cancel before worker picks up flips to cancelled', () async {
      
      
      var bAction = 0;
      final aReleaser = Completer<void>();
      final c = UploadQueueController(
        maxConcurrency: 1,
        action: (j, b, p) async {
          if (j.id == 'a') {
            await aReleaser.future;
            return const UploadResult(fileId: 'fa');
          }
          bAction += 1;
          return const UploadResult(fileId: 'fb');
        },
      );
      final jobA = _makeJob(id: 'a');
      final jobB = _makeJob(id: 'b');
      c.enqueue(jobA);
      c.enqueue(jobB);
      await Future.delayed(const Duration(milliseconds: 30));
      c.cancel('b');
      aReleaser.complete();
      await c.waitForIdle();
      expect(jobB.status, UploadJobStatus.cancelled);
      expect(bAction, 0,
          reason: 'cancel before dispatch must short-circuit the action');
      c.dispose();
    });

    test('cancel mid-action: late success does NOT overwrite cancelled',
        () async {
      
      
      final canCancel = Completer<void>();
      final actionResolved = Completer<UploadResult>();
      final c = UploadQueueController(
        action: (j, b, p) async {
          canCancel.complete();
          return actionResolved.future;
        },
      );
      final job = _makeJob(id: 'a');
      c.enqueue(job);
      await canCancel.future;
      c.cancel('a');
      
      actionResolved.complete(const UploadResult(fileId: 'fa'));
      await c.waitForIdle();
      expect(job.status, UploadJobStatus.cancelled);
      expect(job.uploadedFileId, isNull,
          reason: 'cancelled job must not surface a fileId');
      c.dispose();
    });

    test('cancelAll flips every non-terminal job', () async {
      final aReleaser = Completer<UploadResult>();
      final c = UploadQueueController(
        maxConcurrency: 1,
        action: (j, b, p) async {
          if (j.id == 'a') return aReleaser.future;
          return const UploadResult(fileId: 'fx');
        },
      );
      c.enqueueAll([
        _makeJob(id: 'a'),
        _makeJob(id: 'b'),
        _makeJob(id: 'c'),
      ]);
      await Future.delayed(const Duration(milliseconds: 30));
      c.cancelAll();
      aReleaser.complete(const UploadResult(fileId: 'fa'));
      await c.waitForIdle();
      expect(c.jobs.where((j) => j.status == UploadJobStatus.cancelled).length,
          3);
      c.dispose();
    });
  });

  group('UploadQueueController — retry mechanics', () {
    test('retry(id) moves a failed job back to pending and runs again',
        () async {
      var attempts = 0;
      final c = UploadQueueController(
        action: (j, b, p) async {
          attempts += 1;
          if (attempts < 2) throw Exception('first');
          return const UploadResult(fileId: 'f1');
        },
      );
      final job = _makeJob(id: 'a');
      c.enqueue(job);
      await c.waitForIdle();
      expect(job.status, UploadJobStatus.failed);
      c.retry('a');
      await c.waitForIdle();
      expect(job.status, UploadJobStatus.uploaded);
      expect(attempts, 2);
      c.dispose();
    });

    test('retry reuses cached bytes when the picker stream is one-shot',
        () async {
      var reads = 0;
      var attempts = 0;
      final job = _makeJob(
        id: 'one-shot',
        readBytes: () async {
          reads += 1;
          if (reads > 1) throw StateError('stream already consumed');
          return Uint8List.fromList(const [1, 2, 3]);
        },
      );
      final c = UploadQueueController(
        action: (j, b, p) async {
          attempts += 1;
          if (attempts == 1) throw Exception('temporary failure');
          return const UploadResult(fileId: 'f1');
        },
      );
      c.enqueue(job);
      await c.waitForIdle();
      expect(job.status, UploadJobStatus.failed);
      c.retry(job.id);
      await c.waitForIdle();
      expect(job.status, UploadJobStatus.uploaded);
      expect(reads, 1);
      c.dispose();
    });

    test('retryAllFailed re-pends every failed job at once', () async {
      var calls = 0;
      final c = UploadQueueController(
        action: (j, b, p) async {
          calls += 1;
          if (calls <= 3) throw Exception('fail');
          return const UploadResult(fileId: 'fx');
        },
      );
      c.enqueueAll([
        _makeJob(id: 'a'),
        _makeJob(id: 'b'),
        _makeJob(id: 'c'),
      ]);
      await c.waitForIdle();
      expect(c.failedCount, 3);
      c.retryAllFailed();
      await c.waitForIdle();
      expect(c.uploadedCount, 3);
      c.dispose();
    });
  });

  group('UploadQueueController — observability + lifecycle', () {
    test('aggregate counts move as jobs progress', () async {
      var calls = 0;
      final c = UploadQueueController(
        action: (j, b, p) async {
          calls += 1;
          if (calls == 2) throw Exception('one fails');
          return UploadResult(fileId: 'f-${j.id}');
        },
      );
      c.enqueueAll([
        _makeJob(id: 'a'),
        _makeJob(id: 'b'),
        _makeJob(id: 'c'),
      ]);
      expect(c.totalCount, 3);
      await c.waitForIdle();
      expect(c.uploadedCount + c.failedCount, 3);
      expect(c.failedCount, 1);
      c.dispose();
    });

    test('waitForIdle on an empty queue resolves immediately', () async {
      final c = UploadQueueController(
        action: (j, b, p) async => const UploadResult(fileId: 'fx'),
      );
      final ids = await c.waitForIdle();
      expect(ids, isEmpty);
      c.dispose();
    });

    test('clearTerminal drops uploaded/failed/cancelled jobs', () async {
      var calls = 0;
      final c = UploadQueueController(
        action: (j, b, p) async {
          calls += 1;
          if (calls == 2) throw Exception('one fails');
          return UploadResult(fileId: 'f-${j.id}');
        },
      );
      c.enqueueAll([
        _makeJob(id: 'a'),
        _makeJob(id: 'b'),
      ]);
      await c.waitForIdle();
      expect(c.totalCount, 2);
      c.clearTerminal();
      expect(c.totalCount, 0);
      c.dispose();
    });

    test('reset cancels in-flight and clears everything', () async {
      final never = Completer<UploadResult>();
      final c = UploadQueueController(
        action: (j, b, p) async => never.future,
      );
      c.enqueueAll([
        _makeJob(id: 'a'),
        _makeJob(id: 'b'),
      ]);
      await Future.delayed(const Duration(milliseconds: 20));
      c.reset();
      expect(c.totalCount, 0);
      c.dispose();
    });
  });

  group('UploadQueueController — hasFailures + pauseRemaining', () {
    test('hasFailures flips true the moment one job exhausts retries',
        () async {
      final c = UploadQueueController(
        action: (j, b, p) async => throw Exception('boom'),
      );
      c.enqueue(_makeJob(id: 'a'));
      await c.waitForIdle();
      expect(c.hasFailures, isTrue);
      c.dispose();
    });

    test('pauseRemaining is null when no pause is active', () async {
      final c = UploadQueueController(
        action: (j, b, p) async => const UploadResult(fileId: 'fx'),
      );
      expect(c.pauseRemaining, isNull);
      c.dispose();
    });
  });
}
