import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/main.dart' show AppState;
import 'package:vault_ai_frontend/services/upload_queue.dart';

class _UnlockedAppState extends AppState {
  _UnlockedAppState() {
    unlocked = true;
  }
}

UploadJob _makeJob({
  required String id,
  Future<Uint8List> Function()? readBytes,
}) {
  return UploadJob(
    id: id,
    name: '$id.bin',
    kind: 'file',
    size: 16,
    readBytes: readBytes ?? (() async => Uint8List(16)),
  );
}

void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  group('AppState.shouldLockOnInactivityExpiry — no probes', () {
    test('returns true when unlocked and nothing is registered', () {
      final app = _UnlockedAppState();
      expect(app.shouldLockOnInactivityExpiry(), isTrue,
          reason: 'legacy behavior — no activity, so lock');
    });

    test('returns false when the vault is already locked', () {
      final app = AppState();
      expect(app.unlocked, isFalse);
      expect(
        app.shouldLockOnInactivityExpiry(),
        isFalse,
        reason: 'nothing to do — vault is already locked',
      );
    });
  });

  group('AppState.shouldLockOnInactivityExpiry — keep-alive probes', () {
    test('a probe that returns true defers the lock', () {
      final app = _UnlockedAppState();
      app.registerKeepAliveProbe(() => true);
      expect(
        app.shouldLockOnInactivityExpiry(),
        isFalse,
        reason: 'active probe must keep the vault unlocked',
      );
    });

    test('a probe that returns false does NOT block the lock', () {
      final app = _UnlockedAppState();
      app.registerKeepAliveProbe(() => false);
      expect(
        app.shouldLockOnInactivityExpiry(),
        isTrue,
        reason: 'idle probe is the same as no probe',
      );
    });

    test('mixed probes: ANY active probe defers the lock', () {
      final app = _UnlockedAppState();
      app.registerKeepAliveProbe(() => false);
      app.registerKeepAliveProbe(() => false);
      app.registerKeepAliveProbe(() => true);
      app.registerKeepAliveProbe(() => false);
      expect(app.shouldLockOnInactivityExpiry(), isFalse);
    });

    test('a throwing probe is treated as not active (safe default)', () {
      final app = _UnlockedAppState();
      app.registerKeepAliveProbe(() => throw StateError('boom'));

      expect(app.shouldLockOnInactivityExpiry(), isTrue,
          reason: 'throwing probe must default to "not active"');
    });

    test(
        'registerKeepAliveProbe is idempotent — same closure twice '
        'still removable in one call', () {
      final app = _UnlockedAppState();
      bool active = true;
      bool probe() => active;
      app.registerKeepAliveProbe(probe);
      app.registerKeepAliveProbe(probe);
      expect(app.shouldLockOnInactivityExpiry(), isFalse);

      app.unregisterKeepAliveProbe(probe);
      expect(app.shouldLockOnInactivityExpiry(), isTrue,
          reason: 'one unregister must clear the duplicate too');
    });

    test('unregisterKeepAliveProbe removes the exact closure', () {
      final app = _UnlockedAppState();
      bool probeA() => true;
      bool probeB() => false;
      app.registerKeepAliveProbe(probeA);
      app.registerKeepAliveProbe(probeB);

      app.unregisterKeepAliveProbe(probeA);
      expect(
        app.shouldLockOnInactivityExpiry(),
        isTrue,
        reason: 'after removing the only active probe, lock can fire',
      );
    });
  });

  group('AppState native picker keep-alive', () {
    test('defers inactivity lock only while the native picker is open',
        () async {
      final app = _UnlockedAppState();
      final picker = Completer<String?>();

      final resultFuture = app.runWithNativePickerKeepAlive(
        () => picker.future,
      );
      expect(
        app.shouldLockOnInactivityExpiry(),
        isFalse,
        reason: 'Apple picker must be allowed to return its selected file',
      );

      picker.complete('selected-file');
      expect(await resultFuture, 'selected-file');
      expect(
        app.shouldLockOnInactivityExpiry(),
        isTrue,
        reason: 'normal inactivity locking must resume after picker closes',
      );
    });

    test('picker exception always releases the keep-alive', () async {
      final app = _UnlockedAppState();

      await expectLater(
        app.runWithNativePickerKeepAlive<String>(
          () async => throw StateError('picker failed'),
        ),
        throwsStateError,
      );
      expect(app.shouldLockOnInactivityExpiry(), isTrue);
    });
  });

  group('AppState shutdown hooks', () {
    test('clearSession runs every registered shutdown hook', () async {
      final app = AppState();
      final fired = <String>[];
      app.registerShutdownHook(() => fired.add('a'));
      app.registerShutdownHook(() => fired.add('b'));
      await app.clearSession();
      expect(fired, ['a', 'b']);
    });

    test('a throwing hook does NOT block subsequent hooks', () async {
      final app = AppState();
      final fired = <String>[];
      app.registerShutdownHook(() => fired.add('a'));
      app.registerShutdownHook(() => throw StateError('boom'));
      app.registerShutdownHook(() => fired.add('c'));
      await app.clearSession();
      expect(fired, ['a', 'c'],
          reason: 'one bad hook must not abort the cleanup chain');
    });

    test('unregisterShutdownHook removes the exact callback', () async {
      final app = AppState();
      final fired = <String>[];
      void hookA() => fired.add('a');
      void hookB() => fired.add('b');
      app.registerShutdownHook(hookA);
      app.registerShutdownHook(hookB);
      app.unregisterShutdownHook(hookA);
      await app.clearSession();
      expect(fired, ['b']);
    });

    test(
        'shutdown hooks run BEFORE session token is cleared so '
        'cancelAll sees a still-valid identity', () async {
      // 2026-07-20: this test previously asserted app.unlocked was
      // true at hook time, but the strict AppState.unlocked getter
      // now requires a live key-cache entry that the mock cannot
      // populate. What the test actually cares about is that the
      // session token is still present when hooks fire — assert
      // that directly.
      final app = _UnlockedAppState();
      app.sessionToken = 'test-session-token';
      String? tokenAtHookTime;
      app.registerShutdownHook(() {
        tokenAtHookTime = app.sessionToken;
      });
      await app.clearSession();
      expect(
        tokenAtHookTime,
        'test-session-token',
        reason: 'hooks must fire while session token is still '
            'available — otherwise cancelAll would race the lock',
      );
      expect(
        app.sessionToken,
        isNull,
        reason: 'sessionToken must be cleared AFTER hooks complete',
      );
    });
  });

  group('UploadQueueController.isBusy covers every "active" state', () {
    test('a pending job alone counts as busy', () async {
      final never = Completer<UploadResult>();
      final c = UploadQueueController(
        maxConcurrency: 1,
        action: (j, b, p) => never.future,
      );
      c.enqueueAll([_makeJob(id: 'a'), _makeJob(id: 'b')]);

      expect(c.isBusy, isTrue);

      c.cancelAll();
      never.complete(const UploadResult(fileId: 'fx'));
      await c.waitForIdle();
      c.dispose();
    });

    test('a reading/uploading job counts as busy', () async {
      final never = Completer<UploadResult>();
      final c = UploadQueueController(
        action: (j, b, p) => never.future,
      );
      c.enqueue(_makeJob(id: 'a'));
      await Future.delayed(const Duration(milliseconds: 30));
      expect(c.isBusy, isTrue);
      c.cancelAll();
      never.complete(const UploadResult(fileId: 'fx'));
      await c.waitForIdle();
      c.dispose();
    });

    test('a retrying job counts as busy', () async {
      var attempts = 0;
      final secondAttemptStarted = Completer<void>();
      final secondAttemptRelease = Completer<UploadResult>();
      final c = UploadQueueController(
        maxAttempts: 5,
        action: (j, b, p) async {
          attempts += 1;
          if (attempts == 1) {
            throw const TransientUploadException(
              'one-off',
              pauseFor: Duration(milliseconds: 80),
            );
          }
          secondAttemptStarted.complete();
          return secondAttemptRelease.future;
        },
      );
      c.enqueue(_makeJob(id: 'a'));

      await Future.delayed(const Duration(milliseconds: 40));
      expect(c.isBusy, isTrue,
          reason: 'a job awaiting its retry must keep the queue busy');

      await secondAttemptStarted.future;
      secondAttemptRelease.complete(const UploadResult(fileId: 'fx'));
      await c.waitForIdle();
      c.dispose();
    });

    test('a queue with only terminal jobs is NOT busy', () async {
      final c = UploadQueueController(
        action: (j, b, p) async => const UploadResult(fileId: 'fx'),
      );
      c.enqueue(_makeJob(id: 'a'));
      await c.waitForIdle();
      expect(c.uploadedCount, 1);
      expect(c.isBusy, isFalse,
          reason: 'completed jobs must not pin the vault open forever');
      c.dispose();
    });

    test('cancelled jobs are NOT busy', () async {
      final never = Completer<UploadResult>();
      final c = UploadQueueController(
        action: (j, b, p) => never.future,
      );
      c.enqueueAll([_makeJob(id: 'a'), _makeJob(id: 'b')]);
      await Future.delayed(const Duration(milliseconds: 30));
      c.cancelAll();

      never.complete(const UploadResult(fileId: 'fx'));
      await c.waitForIdle();
      expect(c.isBusy, isFalse,
          reason: 'manual cancel must release the keep-alive');
      c.dispose();
    });

    test('failed terminal job is NOT busy (no infinite retry loop)', () async {
      final c = UploadQueueController(
        maxAttempts: 1,
        action: (j, b, p) async => throw Exception('hard fail'),
      );
      c.enqueue(_makeJob(id: 'a'));
      await c.waitForIdle();
      expect(c.failedCount, 1);
      expect(
        c.isBusy,
        isFalse,
        reason: 'a job that exhausted retries must release the keep-alive',
      );
      c.dispose();
    });
  });

  group('Source guard: main.dart wiring is in place', () {
    String readMain() {
      final file = File('lib/main.dart');
      expect(file.existsSync(), isTrue);
      return file.readAsStringSync();
    }

    test('dashboard registers _uploadQueue.isBusy as a keep-alive probe', () {
      final src = readMain();
      expect(
        src,
        contains('_uploadQueue.isBusy'),
        reason: 'something must observe the busy flag',
      );
      expect(
        src,
        contains('registerKeepAliveProbe(_uploadKeepAliveProbe!)'),
        reason: 'the probe must be registered with AppState',
      );
    });

    test('dashboard registers cancelAll as a shutdown hook', () {
      final src = readMain();
      expect(
        src,
        contains('_uploadQueue.cancelAll()'),
        reason: 'shutdown hook must cancel in-flight uploads',
      );
      expect(
        src,
        contains('registerShutdownHook(_uploadShutdownHook!)'),
        reason: 'the cancel hook must be registered with AppState',
      );
    });

    test('dashboard unregisters both on dispose', () {
      final src = readMain();
      expect(
        src,
        contains('unregisterKeepAliveProbe(_uploadKeepAliveProbe!)'),
        reason: 'no dangling references after dispose',
      );
      expect(
        src,
        contains('unregisterShutdownHook(_uploadShutdownHook!)'),
      );
    });

    test('queue listener resets idle timer on busy → idle transition', () {
      final src = readMain();

      expect(
        src,
        contains('_wasUploadQueueBusy && !nowBusy'),
        reason: 'busy→idle transition must be detected',
      );
      expect(
        src,
        contains('app.resetInactivityTimer()'),
        reason: 'timer must restart from zero on idle',
      );
    });

    test('clearSession calls _runShutdownHooks BEFORE clearing token', () {
      final src = readMain();

      final clearSessionStart = src.indexOf(
        'Future<void> clearSession(',
      );
      expect(clearSessionStart, greaterThan(-1),
          reason: 'clearSession must exist in main.dart');

      final scope = src.substring(
        clearSessionStart,
        (clearSessionStart + 2000).clamp(0, src.length),
      );
      final hooksIdx = scope.indexOf('_runShutdownHooks();');
      final tokenIdx = scope.indexOf('sessionToken = null;');
      expect(hooksIdx, greaterThan(-1),
          reason: '_runShutdownHooks must be called inside clearSession');
      expect(tokenIdx, greaterThan(-1));
      expect(
        hooksIdx,
        lessThan(tokenIdx),
        reason: 'shutdown hooks must run BEFORE session token wipe',
      );
    });

    test('_onInactivityExpired defers when keep-alive is active', () {
      final src = readMain();
      expect(
        src,
        contains('_hasActiveKeepAlive()'),
        reason: '_onInactivityExpired must consult the keep-alive '
            'registry before locking',
      );
    });
  });
}
