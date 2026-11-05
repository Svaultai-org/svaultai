import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_pin_gate_migration_handoff.dart';

void main() {
  test('only an opted-in OPAQUE PIN-gate unlock queues migrations', () {
    for (final requested in [false, true]) {
      for (final restored in [false, true]) {
        final scheduled = <String>[];
        runZkPinGateMigrationBestEffort(
          pinGateRequested: requested,
          opaqueRestored: restored,
          scheduleMetadata: () => scheduled.add('metadata'),
          scheduleContent: () => scheduled.add('content'),
        );
        expect(
          scheduled,
          requested && restored ? ['metadata', 'content'] : isEmpty,
          reason: 'requested=$requested restored=$restored',
        );
      }
    }
  });

  test('a failed metadata scheduler does not block content or unlock', () {
    var contentCalls = 0;
    final failures = <ZkPinGateMigrationScheduleFailure>[];
    expect(
      () => runZkPinGateMigrationBestEffort(
        pinGateRequested: true,
        opaqueRestored: true,
        scheduleMetadata: () => throw StateError('synthetic metadata error'),
        scheduleContent: () => contentCalls++,
        onScheduleFailure: failures.add,
      ),
      returnsNormally,
    );
    expect(contentCalls, 1);
    expect(failures, [ZkPinGateMigrationScheduleFailure.metadata]);
  });

  test('a failed content scheduler does not turn unlock into a failure', () {
    var metadataCalls = 0;
    final failures = <ZkPinGateMigrationScheduleFailure>[];
    expect(
      () => runZkPinGateMigrationBestEffort(
        pinGateRequested: true,
        opaqueRestored: true,
        scheduleMetadata: () => metadataCalls++,
        scheduleContent: () => throw StateError('synthetic content error'),
        onScheduleFailure: failures.add,
      ),
      returnsNormally,
    );
    expect(metadataCalls, 1);
    expect(failures, [ZkPinGateMigrationScheduleFailure.content]);
  });

  test('PIN screen opts in after verified OPAQUE unlock', () {
    final source = File('lib/main.dart').readAsStringSync();
    final verification = source.indexOf('Future<bool> verifyPin(');
    final verificationEnd = source.indexOf(
      'Future<bool> applyFreshKdfMetadata(',
      verification,
    );
    final pinSubmit = source.indexOf('final ok = await app.verifyPin(');
    expect(verification, greaterThan(-1));
    expect(verificationEnd, greaterThan(verification));
    expect(pinSubmit, greaterThan(verificationEnd));

    final verifyBody = source.substring(verification, verificationEnd);
    final unlock = verifyBody.lastIndexOf('unlocked = true;');
    final handoff = verifyBody.indexOf('runZkPinGateMigrationBestEffort(');
    expect(unlock, greaterThan(-1));
    expect(handoff, greaterThan(unlock));
    expect(
      verifyBody.substring(handoff),
      contains('opaqueRestored: zkRestore != null'),
    );
    expect(
      verifyBody.substring(handoff),
      contains('scheduleContent: () => _scheduleLegacyContentStage'),
    );

    final call = source.substring(pinSubmit, source.indexOf(');', pinSubmit));
    expect(call, contains('restoreZkSessionKeys: true'));
    expect(call, contains('scheduleZkMigrationAfterUnlock: true'));
  });
}
