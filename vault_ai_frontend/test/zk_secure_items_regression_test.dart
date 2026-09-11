import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('ZK secure items use ciphertext list, view, update, and delete paths',
      () {
    final source = File('lib/api_client.dart').readAsStringSync();

    expect(source, contains('/vault/ciphertext/vault-items/list'));
    expect(source, contains('/vault/ciphertext/vault-items/delete'));
    expect(source, contains("return _listZkVaultItems(authToken: authToken)"));
    expect(source, contains('existingItemId: existingItemId'));
    expect(source, contains("'fields': rawFields is Map"));
  });

  test('new secure-item dialog does not fetch a nonexistent empty service', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('if (resolved.isEmpty && !createMode)'));
  });
}
