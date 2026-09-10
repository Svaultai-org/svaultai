import 'dart:async';

import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb;
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_storekit/in_app_purchase_storekit.dart';

/// New product identifiers. The retired `svaultai.storage.*.monthly`
/// products must never be put back on sale.
const Map<int, String> appleStorageProductIds = {
  1: 'com.svaultai.app.storage.50gb.monthly.v2',
  2: 'com.svaultai.app.storage.100gb.monthly.v2',
  3: 'com.svaultai.app.storage.150gb.monthly.v2',
  4: 'com.svaultai.app.storage.200gb.monthly.v2',
  5: 'com.svaultai.app.storage.250gb.monthly.v2',
  10: 'com.svaultai.app.storage.500gb.monthly.v2',
  20: 'com.svaultai.app.storage.1tb.monthly.v2',
  40: 'com.svaultai.app.storage.2tb.monthly.v2',
  100: 'com.svaultai.app.storage.5tb.monthly.v2',
};

int? blocksForAppleProduct(String productId) {
  for (final entry in appleStorageProductIds.entries) {
    if (entry.value == productId) return entry.key;
  }
  return null;
}

bool get supportsAppleIap =>
    !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;

class AppleIapCatalog {
  final bool storeAvailable;
  final Map<int, ProductDetails> products;
  final Set<String> missingProductIds;
  final String? error;

  const AppleIapCatalog({
    required this.storeAvailable,
    required this.products,
    this.missingProductIds = const {},
    this.error,
  });

  bool get canPurchase => storeAvailable && products.isNotEmpty;
}

class AppleIapService {
  AppleIapService._();

  static final AppleIapService instance = AppleIapService._();
  final InAppPurchase _store = InAppPurchase.instance;
  final StreamController<List<PurchaseDetails>> _transactions =
      StreamController<List<PurchaseDetails>>.broadcast();
  StreamSubscription<List<PurchaseDetails>>? _storeSubscription;
  List<PurchaseDetails>? _lastTransactions;

  Stream<List<PurchaseDetails>> get transactions async* {
    final pending = _lastTransactions;
    if (pending != null && pending.isNotEmpty) yield pending;
    yield* _transactions.stream;
  }

  /// Called during app startup so interrupted purchases are observed even if
  /// the user has not opened the Storage screen yet.
  void initialize() {
    if (!supportsAppleIap || _storeSubscription != null) return;
    _storeSubscription = _store.purchaseStream.listen(
      (purchases) {
        _lastTransactions = purchases;
        _transactions.add(purchases);
      },
      onError: _transactions.addError,
    );
  }

  Future<AppleIapCatalog> loadCatalog() async {
    if (!supportsAppleIap) {
      return const AppleIapCatalog(storeAvailable: false, products: {});
    }
    try {
      final available = await _store.isAvailable();
      if (!available) {
        return const AppleIapCatalog(
          storeAvailable: false,
          products: {},
          error: 'The App Store is unavailable on this device.',
        );
      }
      final response = await _store
          .queryProductDetails(appleStorageProductIds.values.toSet());
      final byBlocks = <int, ProductDetails>{};
      for (final product in response.productDetails) {
        final blocks = blocksForAppleProduct(product.id);
        if (blocks != null) byBlocks[blocks] = product;
      }
      return AppleIapCatalog(
        storeAvailable: true,
        products: byBlocks,
        missingProductIds: response.notFoundIDs.toSet(),
        error: response.error?.message,
      );
    } catch (_) {
      return const AppleIapCatalog(
        storeAvailable: false,
        products: {},
        error: 'Storage plans could not be loaded from the App Store.',
      );
    }
  }

  Future<bool> buy({
    required ProductDetails product,
    required String accountId,
  }) {
    // accountId is an opaque UUID and becomes StoreKit 2's appAccountToken.
    return _store.buyNonConsumable(
      purchaseParam: Sk2PurchaseParam(
        productDetails: product,
        applicationUserName: accountId,
      ),
    );
  }

  Future<void> restore({required String accountId}) =>
      _store.restorePurchases(applicationUserName: accountId);

  Future<void> finish(PurchaseDetails purchase) async {
    await _store.completePurchase(purchase);
    _lastTransactions = _lastTransactions
        ?.where((candidate) => candidate.purchaseID != purchase.purchaseID)
        .toList();
  }
}
