import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/apple_iap_service.dart';

void main() {
  test('new Apple storage catalog exposes every supported monthly tier', () {
    expect(appleStorageProductIds.keys.toList(), [1, 2, 3, 4, 5, 10, 20, 40, 100]);
    expect(appleStorageProductIds.values.toSet().length, 9);
    expect(appleStorageProductIds[1], contains('50gb.monthly.v2'));
    expect(appleStorageProductIds[100], contains('5tb.monthly.v2'));
  });

  test('retired product namespace is never reused', () {
    for (final id in appleStorageProductIds.values) {
      expect(id, isNot(startsWith('svaultai.storage.')));
    }
  });

  test('product-to-entitlement mapping is closed and reversible', () {
    for (final entry in appleStorageProductIds.entries) {
      expect(blocksForAppleProduct(entry.value), entry.key);
    }
    expect(blocksForAppleProduct('unknown.product'), isNull);
  });
}

