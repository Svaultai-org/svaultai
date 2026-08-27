import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('generated v2 save verifies before finalizing the draft', () {
    final source = File('lib/main.dart').readAsStringSync();
    final saveStart = source.indexOf(
      'Future<void> _saveGeneratedLoginDraftOnce',
    );
    expect(saveStart, greaterThanOrEqualTo(0));
    final saveEnd = source.indexOf(
      'Future<void> _saveGeneratedLoginAuthoritatively',
      saveStart,
    );
    expect(saveEnd, greaterThan(saveStart));
    final save = source.substring(saveStart, saveEnd);

    expect(save, contains('credentialV2MigrationOperationId(recordId)'));
    final readback = save.indexOf('repository.reveal(recordId)');
    final verify = save.indexOf('repository.api.verify(recordId, operationId)');
    final finalize = save.indexOf('repository.api.finalizeGeneratedDraft(');
    expect(readback, greaterThanOrEqualTo(0));
    expect(verify, greaterThan(readback));
    expect(finalize, greaterThan(verify));
  });

  test('generated v2 preflight failure is retryable, not successful', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf(
      'Future<void> _saveGeneratedLoginDraftOnce',
    );
    final end = source.indexOf(
      'Future<void> _saveGeneratedLoginAuthoritatively',
      start,
    );
    final save = source.substring(start, end);
    final guard = save.indexOf('repository == null');
    expect(guard, greaterThanOrEqualTo(0));
    final guardEnd = save.indexOf('}', guard);
    final preflight = save.substring(guard, guardEnd + 1);
    expect(preflight, contains('generated_v2_preflight_failed'));
  });
}
