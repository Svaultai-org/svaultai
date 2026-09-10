import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('memory dashboard uses client-side ciphertext APIs only', () async {
    final page =
        await File('lib/ui/dashboards/memory_page.dart').readAsString();
    final api = await File('lib/api_client.dart').readAsString();

    expect(page, contains('listZkMemories('));
    expect(page, contains('upsertZkMemory('));
    expect(page, contains('deleteZkMemory('));
    expect(page, isNot(contains('.listMemories(')));
    expect(page, isNot(contains('.createMemory(')));
    expect(page, isNot(contains('.updateMemory(')));
    expect(page, isNot(contains('.deleteMemory(')));
    expect(api, contains('/vault/ciphertext/vault-ai-memory/list'));
    expect(api, contains('aesGcmUnwrap('));
  });

  test('chat transport failures preserve the request without raw error UI',
      () async {
    final main = await File('lib/main.dart').readAsString();
    expect(main, contains('connection closed before full header'));
    expect(main, contains('Your request was kept—tap send to retry.'));
  });
}
