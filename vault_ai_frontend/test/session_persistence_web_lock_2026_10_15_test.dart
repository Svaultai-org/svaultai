import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/session_persistence_lock.dart'
    if (dart.library.html) 'package:vault_ai_frontend/services/session_persistence_lock_web.dart' as storage_lock;

void main() {
  test('same-origin session writes remain exclusive until async cleanup ends', () async {
    final entered = Completer<void>();
    final release = Completer<void>();
    var secondEntered = false;
    final first = storage_lock.withSessionPersistenceLock((exclusive) async {
      expect(exclusive, isTrue, reason: 'Chromium localhost must support Web Locks');
      entered.complete();
      await release.future;
      return 'cleanup-finished';
    });
    await entered.future;
    final second = storage_lock.withSessionPersistenceLock((exclusive) async {
      secondEntered = true;
      return 'new-login-persisted';
    });
    await Future<void>.delayed(const Duration(milliseconds: 30));
    expect(secondEntered, isFalse,
      reason: 'A second tab/session writer cannot enter during awaited cleanup.');
    release.complete();
    expect(await first, 'cleanup-finished');
    expect(await second, 'new-login-persisted');
  }, skip: !kIsWeb);

  test('a failed lock owner releases the queue for the next login', () async {
    final failed = storage_lock.withSessionPersistenceLock<void>((_) async {
      await Future<void>.delayed(Duration.zero);
      throw const FormatException('synthetic persistence failure');
    });
    await expectLater(failed, throwsA(isA<FormatException>()));
    final next = await storage_lock.withSessionPersistenceLock((_) async => 'ready');
    expect(next, 'ready');
  }, skip: !kIsWeb);
}
