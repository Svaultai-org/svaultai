import 'dart:async';
import 'dart:collection';

import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb, visibleForTesting;
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_storekit/in_app_purchase_storekit.dart';

import 'apple_purchase_recovery.dart';

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

/// Restore compatibility only. These exact historical products are never
/// offered by the new-purchase picker; the server verifies their entitlement.
const Set<String> appleLegacyStorageProductIds = {
  'svaultai.storage.50gb.monthly',
  'svaultai.storage.100gb.monthly',
  'svaultai.storage.150gb.monthly',
  'svaultai.storage.200gb.monthly',
  'svaultai.storage.250gb.monthly',
  'svaultai.storage.300gb.monthly',
  'svaultai.storage.500gb.monthly',
  'svaultai.storage.1tb.monthly',
};

bool isAppleStorageProduct(String productId) =>
    appleStorageProductIds.containsValue(productId) ||
    appleLegacyStorageProductIds.contains(productId);

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

/// Injectable boundary used to test recovery without purchasing from Apple.
abstract class AppleStoreAdapter {
  Stream<List<PurchaseDetails>> get purchaseStream;
  Future<bool> isAvailable();
  Future<ProductDetailsResponse> queryProductDetails(Set<String> identifiers);
  Future<bool> buy(PurchaseParam purchaseParam);
  Future<void> restore(String appAccountToken);
  Future<void> finish(PurchaseDetails purchase);
}

class _AppleStoreAdapter implements AppleStoreAdapter {
  final InAppPurchase _store = InAppPurchase.instance;

  @override
  Stream<List<PurchaseDetails>> get purchaseStream => _store.purchaseStream;
  @override
  Future<bool> isAvailable() => _store.isAvailable();
  @override
  Future<ProductDetailsResponse> queryProductDetails(Set<String> identifiers) =>
      _store.queryProductDetails(identifiers);
  @override
  Future<bool> buy(PurchaseParam purchaseParam) =>
      _store.buyNonConsumable(purchaseParam: purchaseParam);
  @override
  Future<void> restore(String appAccountToken) =>
      _store.restorePurchases(applicationUserName: appAccountToken);
  @override
  Future<void> finish(PurchaseDetails purchase) =>
      _store.completePurchase(purchase);
}

String appleTransactionKey(PurchaseDetails purchase) {
  final id = purchase.purchaseID;
  if (id != null && id.isNotEmpty) return '${purchase.productID}:id:$id';
  // Never collapse unrelated transactions whose purchaseID is null.
  final signed = purchase.verificationData.serverVerificationData;
  if (signed.isNotEmpty) return '${purchase.productID}:signed:$signed';
  // Malformed receipt callbacks cannot be verified/finished, but still need
  // separate identities until StoreKit redelivers valid transaction data.
  return '${purchase.productID}:missing:${purchase.transactionDate}:${identityHashCode(purchase)}';
}

class AppleIapService {
  AppleIapService._() : _store = _AppleStoreAdapter();

  @visibleForTesting
  AppleIapService.forTesting({required AppleStoreAdapter store})
      : _store = store,
        _supportedForTesting = true;

  static final AppleIapService instance = AppleIapService._();
  final AppleStoreAdapter _store;
  bool _supportedForTesting = false;
  final ApplePurchaseRecovery recovery = ApplePurchaseRecovery();
  final StreamController<List<PurchaseDetails>> _transactions =
      StreamController<List<PurchaseDetails>>.broadcast();
  StreamSubscription<List<PurchaseDetails>>? _storeSubscription;
  final Map<String, PurchaseDetails> _unresolvedTransactions = {};
  final Map<String, Future<void>> _finishing = {};
  final LinkedHashSet<String> _finished = LinkedHashSet();
  bool _startingCheckout = false;
  bool _waitingForStore = false;
  Future<void>? _restoring;

  bool get _supported => _supportedForTesting || supportsAppleIap;
  bool get hasPendingStoreRequest =>
      _startingCheckout ||
      _waitingForStore ||
      _unresolvedTransactions.values.any(
        (purchase) => purchase.status == PurchaseStatus.pending,
      );
  bool get hasPendingActivation => _unresolvedTransactions.values.any(
        (purchase) =>
            purchase.status == PurchaseStatus.purchased ||
            purchase.status == PurchaseStatus.restored,
      );

  Stream<List<PurchaseDetails>> get transactions => Stream.multi((controller) {
        // Subscribe BEFORE replay so no StoreKit event is lost between them.
        final subscription = _transactions.stream.listen(
          controller.add,
          onError: controller.addError,
          onDone: controller.close,
        );
        controller.onCancel = subscription.cancel;
        if (_unresolvedTransactions.isNotEmpty) {
          controller.add(_unresolvedTransactions.values.toList());
        }
      });

  void replayPendingTransactions() {
    if (_unresolvedTransactions.isNotEmpty) {
      _transactions.add(_unresolvedTransactions.values.toList());
    }
  }

  /// Called during app startup so interrupted purchases are observed even if
  /// the user has not opened the Storage screen yet.
  void initialize() {
    if (!_supported || _storeSubscription != null) return;
    _storeSubscription = _store.purchaseStream.listen(
      (purchases) {
        for (final purchase in purchases) {
          if (!isAppleStorageProduct(purchase.productID)) continue;
          final key = appleTransactionKey(purchase);
          if (purchase.status == PurchaseStatus.pending ||
              purchase.status == PurchaseStatus.purchased ||
              purchase.status == PurchaseStatus.restored) {
            if (!_finished.contains(key)) {
              _unresolvedTransactions[key] = purchase;
            }
          } else {
            _unresolvedTransactions.remove(key);
          }
          if (purchase.status != PurchaseStatus.pending) {
            _waitingForStore = false;
          }
        }
        _transactions.add(purchases);
      },
      onError: _transactions.addError,
    );
  }

  Future<AppleIapCatalog> loadCatalog() async {
    if (!_supported) {
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
    required String appAccountToken,
  }) async {
    if (hasPendingStoreRequest) return false;
    if (hasPendingActivation) {
      throw StateError(
          'Restore the existing App Store purchase before purchasing again.');
    }
    _startingCheckout = true;
    // Use the backend-issued opaque binding token, not the raw account UUID.
    // The verifier checks this exact value against the authenticated account.
    try {
      _waitingForStore = true;
      final started = await _store.buy(Sk2PurchaseParam(
        productDetails: product,
        applicationUserName: appAccountToken,
      ));
      if (!started) _waitingForStore = false;
      return started;
    } catch (_) {
      _waitingForStore = false;
      rethrow;
    } finally {
      _startingCheckout = false;
    }
  }

  Future<void> restore({required String appAccountToken}) async {
    final pending = _restoring;
    if (pending != null) return pending;
    final operation = _store.restore(appAccountToken);
    _restoring = operation;
    try {
      await operation;
      replayPendingTransactions();
    } finally {
      _restoring = null;
    }
  }

  Future<void> finish(PurchaseDetails purchase) async {
    final key = appleTransactionKey(purchase);
    if (_finished.contains(key)) return;
    final pending = _finishing[key];
    if (pending != null) return pending;
    final operation = () async {
      if (purchase.pendingCompletePurchase) await _store.finish(purchase);
      _finished.add(key);
      if (_finished.length > 100) _finished.remove(_finished.first);
      _unresolvedTransactions.remove(key);
    }();
    _finishing[key] = operation;
    try {
      await operation;
    } finally {
      _finishing.remove(key);
    }
  }

  @visibleForTesting
  Future<void> disposeForTesting() async {
    await _storeSubscription?.cancel();
    await _transactions.close();
  }
}
