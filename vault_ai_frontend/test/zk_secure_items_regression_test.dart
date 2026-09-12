import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('ZK secure items use ciphertext list, view, update, and delete paths',
      () {
    final source = File('lib/api_client.dart').readAsStringSync();

    expect(source, contains(r"'$baseUrl/vault/ciphertext/vault-items'"));
    expect(
      source,
      contains(r"'$baseUrl/vault/ciphertext/vault-items/$itemId'"),
    );
    expect(source, contains("return _listZkVaultItems(authToken: authToken)"));
    expect(source, contains('existingItemId: existingItemId'));
    expect(source, contains("'fields': rawFields is Map"));
    expect(source, contains("'id': raw['item_id']"));
  });

  test('new secure-item dialog does not fetch a nonexistent empty service', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(source, contains('if (resolved.isEmpty && !createMode)'));
  });
}
