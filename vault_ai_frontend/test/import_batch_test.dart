

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/upload_queue.dart';


void main() {
  group('UploadJob.importId round-trip', () {
    test('importId is preserved on the UploadJob', () {
      final job = UploadJob(
        id: 'a',
        name: 'file.pdf',
        kind: 'file',
        size: 100,
        importId: 'batch-uuid-1',
        readBytes: () async => Uint8List(100),
      );
      expect(job.importId, 'batch-uuid-1');
    });

    test('importId is null when no batch context', () {
      final job = UploadJob(
        id: 'a',
        name: 'file.pdf',
        kind: 'file',
        size: 100,
        readBytes: () async => Uint8List(100),
      );
      expect(job.importId, isNull);
    });

    test('importId is independent from relativePath', () {
      
      
      final batchOnly = UploadJob(
        id: 'a',
        name: 'file.pdf',
        kind: 'file',
        size: 100,
        importId: 'batch-uuid-1',
        readBytes: () async => Uint8List(100),
      );
      expect(batchOnly.importId, isNotNull);
      expect(batchOnly.relativePath, isNull);

      final folderOnly = UploadJob(
        id: 'b',
        name: 'file.pdf',
        kind: 'file',
        size: 100,
        relativePath: 'Bank/statement.pdf',
        readBytes: () async => Uint8List(100),
      );
      expect(folderOnly.importId, isNull);
      expect(folderOnly.relativePath, 'Bank/statement.pdf');
    });
  });

  group('StorageLimitExceededException shape', () {
    test('carries message and optional byte triples', () {
      const ex = StorageLimitExceededException(
        message: 'Not enough storage.',
        usedBytes: 1024,
        limitBytes: 2048,
        projectedBytes: 4096,
      );
      expect(ex.message, 'Not enough storage.');
      expect(ex.usedBytes, 1024);
      expect(ex.limitBytes, 2048);
      expect(ex.projectedBytes, 4096);
      expect(
        ex.toString(),
        contains('Not enough storage.'),
        reason: 'toString must surface the message for logs',
      );
    });

    test('bytes are optional', () {
      const ex = StorageLimitExceededException(
        message: 'msg',
      );
      expect(ex.usedBytes, isNull);
      expect(ex.limitBytes, isNull);
      expect(ex.projectedBytes, isNull);
    });
  });

  group('ImportBatchTerminalException shape', () {
    test('carries message and status', () {
      const ex = ImportBatchTerminalException(
        message: 'already done',
        status: 'completed',
      );
      expect(ex.message, 'already done');
      expect(ex.status, 'completed');
      expect(ex.toString(), contains('completed'));
    });
  });

  group('Source guard: api_client wiring', () {
    String readApi() {
      final file = File('lib/api_client.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('api_client exposes all four lifecycle methods', () {
      final src = readApi();
      for (final sig in [
        'Future<Map<String, dynamic>> startImport(',
        'Future<Map<String, dynamic>> getImport(',
        'Future<Map<String, dynamic>> cancelImport(',
        'Future<Map<String, dynamic>> completeImport(',
      ]) {
        expect(
          src,
          contains(sig),
          reason: 'api_client must expose $sig',
        );
      }
    });

    test('startImport hits POST /imports/start with the planned '
        'bytes/files in the JSON body', () {
      final src = readApi();
      expect(src, contains("'\$baseUrl/imports/start'"));
      expect(src, contains("'total_files': totalFiles"));
      expect(src, contains("'total_bytes_planned': totalBytesPlanned"));
    });

    test('getImport hits GET /imports/{import_id}', () {
      final src = readApi();
      expect(src, contains("'\$baseUrl/imports/\$importId'"));
    });

    test('cancelImport hits POST /imports/{id}/cancel', () {
      final src = readApi();
      expect(src, contains("'\$baseUrl/imports/\$importId/cancel'"));
    });

    test('completeImport hits POST /imports/{id}/complete and '
        'forwards both deltas', () {
      final src = readApi();
      expect(src, contains("'\$baseUrl/imports/\$importId/complete'"));
      expect(src, contains("'failed_count_delta': failedCountDelta"));
      expect(
        src,
        contains(
            "'skipped_duplicate_count_delta': skippedDuplicateCountDelta"),
      );
    });

    test('startImport maps 413 to StorageLimitExceededException', () {
      final src = readApi();
      expect(
        src,
        contains('throw _parseStorageLimitException(response.body)'),
        reason: '413 must throw the typed exception, not a generic one',
      );
    });

    test('uploadVaultFile threads importId as a multipart form field, '
        'omitting when null', () {
      final src = readApi();
      
      
      expect(
        src,
        contains("request.fields['import_id'] = importId"),
        reason: 'multipart upload must forward import_id',
      );
      expect(
        src,
        contains(
            "if (importId != null && importId.isNotEmpty) {"),
        reason: 'null/empty importId must be omitted from the wire',
      );
    });

    test('initChunkedUpload threads importId in JSON body, '
        'omitting when null', () {
      final src = readApi();
      expect(
        src,
        contains("'import_id': importId"),
        reason: 'chunked init must forward import_id',
      );
      expect(
        src,
        contains(
            "if (importId != null && importId.isNotEmpty)"),
      );
    });

    test('both upload methods declare a String? importId parameter', () {
      final src = readApi();
      final count = 'String? importId'.allMatches(src).length;
      expect(
        count,
        greaterThanOrEqualTo(2),
        reason: 'uploadVaultFile + initChunkedUpload must both '
                'declare importId',
      );
    });
  });

  group('Source guard: main.dart batch lifecycle wiring', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('_uploadAttachments calls client.startImport when '
        'multi-file or folder context is present', () {
      final src = readMain();
      expect(
        src,
        contains('client.startImport('),
        reason: '_uploadAttachments must create a server-side batch',
      );
      
      expect(
        src,
        contains('isMultiFileBatch || hasFolderContext'),
        reason: 'batch is created for multi-file OR folder picks',
      );
    });

    test('_uploadAttachments calls client.completeImport after '
        'waitForIdle', () {
      final src = readMain();
      final completeIdx = src.indexOf('client.completeImport(');
      final waitForIdleIdx = src.indexOf('_uploadQueue.waitForIdle()');
      expect(completeIdx, greaterThan(-1),
          reason: '_uploadAttachments must complete the batch');
      expect(waitForIdleIdx, greaterThan(-1));
      expect(
        completeIdx,
        greaterThan(waitForIdleIdx),
        reason: 'completeImport must run AFTER the queue drains',
      );
    });

    test('_uploadAttachments forwards failedCountDelta from the queue',
        () {
      final src = readMain();
      expect(
        src,
        contains('failedCountDelta: _uploadQueue.failedCount'),
        reason: 'completion must report failed count from the queue',
      );
    });

    test('_uploadAttachments skips completion when user cancelled',
        () {
      final src = readMain();
      
      
      expect(
        src,
        contains('UploadJobStatus.cancelled'),
        reason: 'completion must check for cancelled jobs',
      );
      expect(
        src,
        contains('if (!cancelledByUser)'),
        reason: 'completion must be skipped after user cancel',
      );
    });

    test('_uploadAttachments stamps importId on every fresh '
        'attachment before enqueueing', () {
      final src = readMain();
      expect(
        src,
        contains('a.importId = importId;'),
        reason: 'each attachment must carry the batch id forward',
      );
    });

    test('StorageLimitExceededException short-circuits the import '
        'without enqueueing any jobs', () {
      final src = readMain();
      expect(
        src,
        contains('on StorageLimitExceededException catch'),
        reason: 'storage 413 must be handled with a typed catch',
      );
      
      
      final startImportIdx = src.indexOf('startImport(');
      expect(startImportIdx, greaterThan(-1),
          reason: 'pre-flight handler lives next to startImport()');
      final catchIdx = src.indexOf(
        'on StorageLimitExceededException catch',
        startImportIdx,
      );
      expect(catchIdx, greaterThan(-1));
      final earlyReturn = src.indexOf(
        '_UploadAttachmentsOutcome',
        catchIdx,
      );
      expect(earlyReturn, greaterThan(-1));
      expect(
        earlyReturn - catchIdx,
        lessThan(800),
        reason: 'storage handler must return quickly without '
                'falling through to enqueueAll',
      );
    });

    test('_cancelActiveUploads calls client.cancelImport BEFORE '
        '_uploadQueue.cancelAll()', () {
      final src = readMain();
      final fnIdx = src.indexOf('void _cancelActiveUploads()');
      expect(fnIdx, greaterThan(-1));
      final scope = src.substring(
        fnIdx,
        (fnIdx + 2000).clamp(0, src.length),
      );
      final cancelImportIdx = scope.indexOf('cancelImport(');
      final cancelAllIdx = scope.indexOf('_uploadQueue.cancelAll()');
      expect(cancelImportIdx, greaterThan(-1),
          reason: 'cancel must reach the backend batch endpoint');
      expect(cancelAllIdx, greaterThan(-1));
      expect(
        cancelImportIdx,
        lessThan(cancelAllIdx),
        reason: 'fire-and-forget /cancel must dispatch BEFORE '
                'flipping local jobs (otherwise the snapshot of '
                '_currentUploadContext used in the cancel call may '
                'race the queue teardown)',
      );
    });

    test('UploadJob construction in _uploadAttachments threads '
        'importId', () {
      final src = readMain();
      expect(
        src,
        contains('importId: a.importId,'),
        reason: 'jobs must carry the batch id',
      );
    });

    test('_runUploadAction passes importId to uploadVaultFile and '
        '_chunkedUpload', () {
      final src = readMain();
      
      
      final count = 'importId: job.importId,'.allMatches(src).length;
      expect(
        count,
        greaterThanOrEqualTo(3),
        reason: 'all three upload-dispatch paths must forward importId',
      );
    });
  });

  group('Source guard: chat composer batch context', () {
    String readMain() {
      final file = File('lib/main.dart');
      return file.readAsStringSync();
    }

    test('_UploadContext carries importId for the cancel surface', () {
      final src = readMain();
      
      
      expect(
        src,
        contains('final String? importId;'),
        reason: '_UploadContext must hold the active batch id',
      );
    });

    test('_Attachment.importId is part of the public surface and '
        'survives copy()', () {
      final src = readMain();
      expect(
        src,
        contains('String? importId;'),
        reason: '_Attachment must declare importId',
      );
      
      
      expect(
        src,
        contains('importId: importId,'),
        reason: '_Attachment.copy() must thread importId',
      );
    });
  });
}
