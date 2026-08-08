import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('generated v2 save verifies before finalizing the draft', () {
    final source = File('lib/main.dart').readAsStringSync();
    final saveStart = source.indexOf("if (action == 'generated_login_save')");
    expect(saveStart, greaterThanOrEqualTo(0));
    final saveEnd = source.indexOf(
      "if (action == 'generated_login_cancel')",
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
}
