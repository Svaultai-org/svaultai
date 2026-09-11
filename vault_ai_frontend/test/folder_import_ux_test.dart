

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/upload_queue.dart';
import 'package:vault_ai_frontend/ui/chat/storage_limit_dialog.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];


UploadJob _job(String id, {int size = 1024}) {
  return UploadJob(
    id: id,
    name: '$id.pdf',
    kind: 'file',
    size: size,
    readBytes: () async => Uint8List(size),
  );
}


void main() {
  group('NotEnoughStorageDialog — copy + buttons', () {
    testWidgets(
        'renders folder name, planned/available size, and the right '
        'buttons',
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

      
      NotEnoughStorageDialog.show(
        capturedCtx,
        plannedBytes: 2 * 1024 * 1024 * 1024,  
        availableBytes: 512 * 1024 * 1024,     
        folderName: 'big_folder',
      );
      await tester.pumpAndSettle();

      
      expect(find.textContaining('big_folder'), findsOneWidget);
      
      expect(find.textContaining('2.0 GB'), findsOneWidget);
      expect(find.textContaining('512 MB'), findsOneWidget);
      
      expect(find.text('Cancel'), findsOneWidget);
      expect(find.text('Upgrade storage'), findsOneWidget);
    });

    testWidgets(
        'falls back to generic title when folder name is null',
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

      
      NotEnoughStorageDialog.show(
        capturedCtx,
        plannedBytes: 1024 * 1024,
        availableBytes: 0,
      );
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Not enough storage'),
        findsOneWidget,
      );
    });

    testWidgets('Cancel resolves with StorageLimitDialogChoice.cancel',
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

      final future = NotEnoughStorageDialog.show(
        capturedCtx,
        plannedBytes: 1024,
        availableBytes: 0,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(await future, equals(StorageLimitDialogChoice.cancel));
    });

    testWidgets(
        'Upgrade storage resolves with StorageLimitDialogChoice.upgrade',
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

      final future = NotEnoughStorageDialog.show(
        capturedCtx,
        plannedBytes: 1024,
        availableBytes: 0,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Upgrade storage'));
      await tester.pumpAndSettle();
      expect(await future, equals(StorageLimitDialogChoice.upgrade));
    });
  });

  group('formatStorageBytes — unit picking', () {
    test('0 bytes', () => expect(formatStorageBytes(0), equals('0 B')));
    test('bytes',
        () => expect(formatStorageBytes(500), equals('500 B')));
    test('kilobytes',
        () => expect(formatStorageBytes(512 * 1024), equals('512 KB')));
    test('megabytes — large value, no decimal', () {
      expect(formatStorageBytes(800 * 1024 * 1024), equals('800 MB'));
    });
    test('gigabytes — small value, one decimal', () {
      expect(
        formatStorageBytes((1.5 * 1024 * 1024 * 1024).round()),
        equals('1.5 GB'),
      );
    });
    test('negative folds to 0 B',
        () => expect(formatStorageBytes(-10), equals('0 B')));
  });

  group('UploadQueueController — Phase 5 storage stop', () {
    test('stoppedForStorage is terminal (no retry)', () {
      final job = _job('j1');
      job.status = UploadJobStatus.stoppedForStorage;
      expect(job.isTerminal, isTrue);
    });

    test(
        'storage 413 from one job cascades stoppedForStorage onto '
        'every still-pending job',
        () async {
      
      
      var hitCalls = 0;
      var actionCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          actionCalls += 1;
          if (job.id == 'j1') {
            throw const StorageLimitDuringUploadException(
              message: 'Vault storage limit reached.',
              usedBytes: 1024,
              limitBytes: 1024,
            );
          }
          return UploadResult(fileId: 'new-${job.id}');
        },
        onStorageLimitHit: (err) {
          hitCalls += 1;
        },
      );
      queue.enqueueAll([for (var i = 1; i <= 5; i++) _job('j$i')]);
      await queue.waitForIdle();

      expect(actionCalls, equals(1),
          reason: 'pending jobs must NOT have been started after the cascade');
      expect(queue.stoppedForStorageCount, equals(5));
      expect(queue.stoppedForStorage, isTrue);
      expect(hitCalls, equals(1));
      queue.dispose();
    });

    test(
        'skipped duplicates that completed BEFORE the storage hit are '
        'preserved (cascade only touches non-terminal jobs)',
        () async {
      
      
      var calls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          calls += 1;
          if (job.id == 'j1') {
            return const UploadResult(
              fileId: 'existing-1',
              skippedDuplicate: true,
            );
          }
          if (job.id == 'j2') {
            throw const StorageLimitDuringUploadException(
              message: 'limit reached',
            );
          }
          return UploadResult(fileId: 'new-${job.id}');
        },
      );
      queue.enqueueAll([for (var i = 1; i <= 4; i++) _job('j$i')]);
      await queue.waitForIdle();

      expect(calls, equals(2),
          reason: 'j3/j4 must NOT have started');
      
      expect(
        queue.jobs.firstWhere((j) => j.id == 'j1').status,
        equals(UploadJobStatus.skippedDuplicate),
      );
      
      expect(queue.stoppedForStorageCount, equals(3));
      queue.dispose();
    });

    test(
        'plain non-storage failure does NOT trigger the cascade',
        () async {
      var hitCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 1,
        maxAttempts: 1,
        action: (job, bytes, report) async {
          if (job.id == 'j1') throw Exception('network died');
          return UploadResult(fileId: 'new-${job.id}');
        },
        onStorageLimitHit: (_) => hitCalls += 1,
      );
      queue.enqueueAll([for (var i = 1; i <= 3; i++) _job('j$i')]);
      await queue.waitForIdle();

      expect(hitCalls, equals(0));
      expect(queue.stoppedForStorage, isFalse);
      
      expect(
        queue.jobs.firstWhere((j) => j.id == 'j1').status,
        equals(UploadJobStatus.failed),
      );
      expect(queue.uploadedCount, equals(2));
      queue.dispose();
    });

    test(
        'onStorageLimitHit fires exactly once even when concurrent '
        'workers race into 413',
        () async {
      var hitCalls = 0;
      final queue = UploadQueueController(
        maxConcurrency: 4,
        action: (job, bytes, report) async {
          
          
          throw const StorageLimitDuringUploadException(
            message: 'limit reached',
          );
        },
        onStorageLimitHit: (_) => hitCalls += 1,
      );
      queue.enqueueAll([for (var i = 1; i <= 8; i++) _job('j$i')]);
      await queue.waitForIdle();

      expect(hitCalls, equals(1),
          reason: 'host snack must not stack');
      expect(queue.stoppedForStorageCount, equals(8));
      queue.dispose();
    });

    test('no resolver attached → cascade still happens cleanly',
        () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const StorageLimitDuringUploadException(
            message: 'limit',
          );
        },
      );
      queue.enqueue(_job('j1'));
      queue.enqueue(_job('j2'));
      await queue.waitForIdle();
      expect(queue.stoppedForStorageCount, equals(2));
      queue.dispose();
    });

    test('retry() is a no-op for stoppedForStorage', () async {
      final queue = UploadQueueController(
        maxConcurrency: 1,
        action: (job, bytes, report) async {
          throw const StorageLimitDuringUploadException(
            message: 'limit',
          );
        },
      );
      queue.enqueue(_job('j1'));
      await queue.waitForIdle();
      queue.retry('j1');
      expect(
        queue.jobs.single.status,
        equals(UploadJobStatus.stoppedForStorage),
      );
      queue.dispose();
    });
  });

  group('Source guard: main.dart pre-flight + queue wiring', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('imports the storage_limit_dialog module', () {
      expect(
        readMain(),
        contains("import 'ui/chat/storage_limit_dialog.dart'"),
      );
    });

    test(
        'pre-flight storage gate runs BEFORE the user bubble is added',
        () {
      final src = readMain();
      
      
      final dialogIdx = src.indexOf('NotEnoughStorageDialog.show(');
      
      
      int userBubbleIdx = src.indexOf("msgs.add(_Msg(\n        'user'");
      if (userBubbleIdx == -1) {
        userBubbleIdx = src.indexOf("msgs.add(_Msg(\r\n        'user'");
      }
      expect(dialogIdx, greaterThan(-1),
          reason: 'main.dart must show the storage dialog');
      expect(userBubbleIdx, greaterThan(-1));
      expect(
        dialogIdx,
        lessThan(userBubbleIdx),
        reason: 'storage gate must run BEFORE the user bubble',
      );
    });

    test('storage dialog Upgrade path routes to /storage', () {
      final src = readMain();
      expect(
        src,
        contains("Navigator.pushNamed(context, '/storage')"),
        reason: 'Upgrade button must navigate to the Storage page',
      );
    });

    test('_runUploadAction catches StorageLimitExceededException', () {
      final src = readMain();
      
      
      expect(
        src,
        contains('throw StorageLimitDuringUploadException('),
        reason: 'mid-import handler must rethrow as the queue type '
                'so the worker can cascade stoppedForStorage',
      );
    });

    test('queue is constructed with onStorageLimitHit', () {
      expect(
        readMain(),
        contains('onStorageLimitHit: _onStorageLimitHit'),
      );
    });

    test('_onStorageLimitHit emits the spec snack copy', () {
      final src = readMain();
      expect(
        src,
        contains(
            "_showSnack('Import stopped — not enough storage.')"),
        reason: 'snack copy must match the spec verbatim',
      );
    });

    test(
        'final import summary uses formatImportSummary instead of '
        'the legacy "Saved N files using their original filenames"',
        () {
      final src = readMain();
      expect(
        src,
        contains('formatImportSummary('),
        reason: 'final summary must use the shared formatter so '
                'duplicates / renames / failures roll up',
      );
      
      expect(
        src,
        isNot(contains("using their original filenames")),
        reason: 'legacy summary copy must be removed',
      );
    });
  });

  group('Source guard: composer + button menu', () {
    String readMain() {
      final file = File('lib/main.dart');
      return file.readAsStringSync();
    }

    test('composer uses a single PopupMenuButton (+ menu)', () {
      final src = readMain();
      expect(
        src,
        contains('Widget _buildAttachmentPlusMenu()'),
        reason: 'the + menu must be a named helper',
      );
      expect(
        src,
        contains('Icons.add_circle_outline'),
        reason: 'the + button icon must be the standard add icon',
      );
    });

    test('+ menu contains every spec\'d option', () {
      final src = readMain();
      
      



      const optionToKey = <String, String>{
        'Upload file':   'filesUploadFile',
        'Upload photo':  'filesUploadPhoto',
        'Upload video':  'filesUploadVideo',
        'Upload audio':  'filesUploadAudio',
        'Upload folder': 'filesUploadFolder',
        'Record voice':  'filesRecordVoice',
        'Record video':  'filesRecordVideo',
      };
      for (final entry in optionToKey.entries) {
        final option = entry.key;
        final key = entry.value;
        expect(
          src.contains("Text('$option')") || src.contains(key),
          isTrue,
          reason:
              '+ menu must include the "$option" entry '
              '(either literal or via AppLocalizations.$key)',
        );
      }
    });

    test(
        'legacy per-type IconButton row is gone from both composer '
        'layouts',
        () {
      final src = readMain();
      
      
      final menuRefs = '_buildAttachmentPlusMenu()'.allMatches(src).length;
      expect(
        menuRefs,
        greaterThanOrEqualTo(2),
        reason: '+ menu must be referenced by BOTH composer layouts',
      );
      
      
      final fileBtns = 'Icon(Icons.attach_file)'.allMatches(src).length;
      final imageBtns = 'Icon(Icons.image)'.allMatches(src).length;
      expect(
        fileBtns,
        lessThanOrEqualTo(1),
        reason: 'legacy attach_file IconButton must no longer be in '
                'either composer toolbar row',
      );
      expect(
        imageBtns,
        lessThanOrEqualTo(1),
        reason: 'legacy image IconButton must no longer be in either '
                'composer toolbar row',
      );
    });

    test('folder option in + menu is hidden when picker is '
        'unsupported on the platform', () {
      final src = readMain();
      expect(
        src,
        contains('if (supportsFolderUpload)'),
        reason: 'folder option must not be built on unsupported mobile',
      );
      expect(
        src,
        isNot(contains('enabled: _folderPicker.isSupported')),
        reason: 'unsupported mobile folder upload must be hidden, not disabled',
      );
    });
  });

  group(
      'Source guard: chat_bubble.dart folder-summary threshold', () {
    test(
        'MessageAttachmentList exposes folderSummaryThreshold and '
        'folder card path',
        () {
      final file = File('lib/ui/chat/chat_bubble.dart');
      expect(file.existsSync(), isTrue);
      final src = file.readAsStringSync();
      expect(
        src,
        contains('static const int folderSummaryThreshold ='),
        reason: 'threshold must be exposed for tests + pinning',
      );
      expect(
        src,
        contains('_FolderSummaryCard('),
        reason: 'compact folder card path must exist',
      );
      expect(
        src,
        contains('Icons.folder_copy_outlined'),
        reason: 'folder icon anchors the summary card',
      );
    });
  });

  group('Source guard: upload_queue.dart Phase 5 contract', () {
    String readQueue() {
      final file = File('lib/services/upload_queue.dart');
      return file.readAsStringSync();
    }

    test(
        'exports StorageLimitDuringUploadException + '
        'StorageLimitHandler typedef',
        () {
      final src = readQueue();
      expect(
        src,
        contains('class StorageLimitDuringUploadException'),
      );
      expect(src, contains('typedef StorageLimitHandler'));
    });

    test('UploadJobStatus enum includes stoppedForStorage', () {
      expect(readQueue(), contains('stoppedForStorage,'));
    });

    test('worker catches StorageLimitDuringUploadException', () {
      expect(
        readQueue(),
        contains('on StorageLimitDuringUploadException'),
      );
    });

    test('controller accepts onStorageLimitHit', () {
      expect(readQueue(), contains('this.onStorageLimitHit'));
    });

    test(
        'stoppedForStorage is in isTerminal so the queue does NOT '
        'retry it', () {
      final src = readQueue();
      expect(
        src,
        contains('status == UploadJobStatus.stoppedForStorage'),
      );
    });
  });

  group('Source guard: api_client.dart upload 413 routes to typed exception',
      () {
    test('uploadVaultFile parses 413 into StorageLimitExceededException',
        () {
      final file = File('lib/api_client.dart');
      final src = file.readAsStringSync();
      
      
      expect(
        src,
        contains('if (response.statusCode == 413) {'),
      );
      expect(
        src,
        contains('throw _parseStorageLimitException(responseBody)'),
      );
    });
  });
}
