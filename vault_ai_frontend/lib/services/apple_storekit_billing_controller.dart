import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

typedef ApplePurchaseVerifier = Future<Map<String, dynamic>> Function({
  required String signedTransaction,
  required String environment,
});

@immutable
class AppleStorageTier {
  final String productId;
  final String billingPeriod;
  final String capacityLabel;
  final int entitlementBytes;
  final int quantity;

  const AppleStorageTier({
    required this.productId,
    required this.billingPeriod,
    required this.capacityLabel,
    required this.entitlementBytes,
    required this.quantity,
  });
}

List<AppleStorageTier> parseAppleStorageCatalog(Map<dynamic, dynamic> provider) {
  if (provider['configured'] != true) {
    throw StateError('app_store_not_configured');
  }
  final rawIds = provider['product_ids'];
  final rawProducts = provider['products'];
  if (rawIds is! List || rawProducts is! List || rawIds.isEmpty) {
    throw StateError('app_store_catalog_incomplete');
  }
  final ids = rawIds.map((value) => value.toString().trim()).toSet();
  if (ids.length != rawIds.length || ids.any((id) => id.isEmpty)) {
    throw StateError('app_store_catalog_invalid_ids');
  }
  final tiers = <AppleStorageTier>[];
  for (final raw in rawProducts) {
    if (raw is! Map) throw StateError('app_store_catalog_invalid_product');
    final productId = raw['product_id']?.toString().trim() ?? '';
    final billingPeriod = raw['billing_period']?.toString().trim() ?? '';
    final capacityLabel = raw['display_capacity']?.toString().trim() ?? '';
    final entitlementBytes =
        (raw['storage_entitlement_bytes'] as num?)?.toInt() ?? 0;
    final quantity = (raw['quantity'] as num?)?.toInt() ?? 0;
    if (!ids.contains(productId) ||
        billingPeriod != 'P1M' ||
        capacityLabel.isEmpty ||
        entitlementBytes < 1 ||
        quantity < 1) {
      throw StateError('app_store_catalog_tier_mismatch');
    }
    tiers.add(AppleStorageTier(
      productId: productId,
      billingPeriod: billingPeriod,
      capacityLabel: capacityLabel,
      entitlementBytes: entitlementBytes,
      quantity: quantity,
    ));
  }
  if (tiers.length != ids.length ||
      tiers.map((tier) => tier.productId).toSet().length != ids.length) {
    throw StateError('app_store_catalog_incomplete');
  }
  tiers.sort((a, b) => a.entitlementBytes.compareTo(b.entitlementBytes));
  return List<AppleStorageTier>.unmodifiable(tiers);
}

String appleTransactionEnvironment(
  String signedTransaction, {
  String fallback = 'production',
}) {
  try {
    final parts = signedTransaction.split('.');
    if (parts.length < 2) throw const FormatException();
    final normalized = base64Url.normalize(parts[1]);
    final payload = jsonDecode(utf8.decode(base64Url.decode(normalized)));
    final environment = payload is Map
        ? payload['environment']?.toString().trim().toLowerCase()
        : null;
    if (environment == 'sandbox') return 'sandbox';
    if (environment == 'production') return 'production';
  } catch (_) {
    // Environment only selects the server verification endpoint. The server
    // still cryptographically verifies the signed transaction and product.
  }
  return fallback.trim().toLowerCase() == 'sandbox'
      ? 'sandbox'
      : 'production';
}

abstract class AppleBillingGateway {
  Stream<List<PurchaseDetails>> get purchaseStream;
  Future<bool> isAvailable();
  Future<ProductDetailsResponse> queryProductDetails(Set<String> productIds);
  Future<bool> buySubscription(PurchaseParam purchaseParam);
  Future<void> restorePurchases();
  Future<void> completePurchase(PurchaseDetails purchase);
}

class FlutterAppleBillingGateway implements AppleBillingGateway {
  final InAppPurchase _delegate;

  FlutterAppleBillingGateway({InAppPurchase? delegate})
      : _delegate = delegate ?? InAppPurchase.instance;

  @override
  Stream<List<PurchaseDetails>> get purchaseStream => _delegate.purchaseStream;

  @override
  Future<bool> isAvailable() => _delegate.isAvailable();

  @override
  Future<ProductDetailsResponse> queryProductDetails(Set<String> productIds) =>
      _delegate.queryProductDetails(productIds);

  @override
  Future<bool> buySubscription(PurchaseParam purchaseParam) =>
      _delegate.buyNonConsumable(purchaseParam: purchaseParam);

  @override
  Future<void> restorePurchases() => _delegate.restorePurchases();

  @override
  Future<void> completePurchase(PurchaseDetails purchase) =>
      _delegate.completePurchase(purchase);
}

class AppleStoreKitBillingController extends ChangeNotifier {
  final AppleBillingGateway gateway;
  final ApplePurchaseVerifier verifyPurchase;
  final List<AppleStorageTier> catalog;
  final String appAccountToken;
  final String environment;
  final Duration connectionTimeout;
  final Duration actionTimeout;
  final Duration verificationTimeout;

  StreamSubscription<List<PurchaseDetails>>? _subscription;
  final Set<String> _verificationInFlight = <String>{};
  final Set<String> _completedTransactions = <String>{};
  final Map<String, ProductDetails> _productsById = <String, ProductDetails>{};
  int _operationGeneration = 0;

  bool initialized = false;
  bool available = false;
  bool loading = false;
  bool restoring = false;
  String state = 'idle';
  String? message;

  Set<String> get productIds => catalog.map((tier) => tier.productId).toSet();
  bool get catalogReady => _productsById.isNotEmpty;
  List<ProductDetails> get products => catalog
      .map((tier) => _productsById[tier.productId])
      .whereType<ProductDetails>()
      .toList(growable: false);
  ProductDetails? get product => products.isEmpty ? null : products.first;
  ProductDetails? productFor(String productId) => _productsById[productId];

  AppleStorageTier? tierForProduct(String productId) {
    for (final tier in catalog) {
      if (tier.productId == productId) return tier;
    }
    return null;
  }

  AppleStorageTier? tierForQuantity(int quantity) {
    for (final tier in catalog) {
      if (tier.quantity == quantity) return tier;
    }
    return null;
  }

  bool get canBuy =>
      available &&
      catalogReady &&
      !loading &&
      !restoring &&
      !const {'launching', 'pending', 'verifying'}.contains(state);

  bool get canRetry => !loading && !restoring && state != 'ready';

  AppleStoreKitBillingController({
    required this.gateway,
    required this.verifyPurchase,
    required List<AppleStorageTier> catalog,
    required this.appAccountToken,
    this.environment = 'production',
    this.connectionTimeout = const Duration(seconds: 12),
    this.actionTimeout = const Duration(seconds: 20),
    this.verificationTimeout = const Duration(seconds: 30),
  }) : catalog = List<AppleStorageTier>.unmodifiable(catalog);

  Future<void> initialize({bool forceRetry = false}) async {
    if ((initialized && !forceRetry) || loading) return;
    final operation = ++_operationGeneration;
    initialized = true;
    _subscription ??= gateway.purchaseStream.listen(
      _handlePurchases,
      onError: (_) {
        _operationGeneration++;
        loading = false;
        restoring = false;
        state = 'unavailable';
        message = 'The App Store is temporarily unavailable. Tap Retry.';
        notifyListeners();
      },
    );
    loading = true;
    state = 'connecting';
    message = 'Connecting to the App Store…';
    notifyListeners();
    try {
      final storeAvailable =
          await gateway.isAvailable().timeout(connectionTimeout);
      if (operation != _operationGeneration) return;
      available = storeAvailable;
      if (!storeAvailable) {
        state = 'unavailable';
        message = 'App Store purchases are unavailable on this device.';
        return;
      }
      final response = await gateway
          .queryProductDetails(productIds).timeout(connectionTimeout);
      if (operation != _operationGeneration) return;
      final matches = <String, ProductDetails>{};
      for (final candidate in response.productDetails) {
        if (productIds.contains(candidate.id) &&
            candidate.price.trim().isNotEmpty &&
            !matches.containsKey(candidate.id)) {
          matches[candidate.id] = candidate;
        }
      }
      if (matches.isEmpty) {
        if (_productsById.isNotEmpty) {
          state = 'ready';
          message =
              'Using the last available App Store plans. Tap Retry to refresh.';
        } else {
          state = 'unavailable';
          message =
              'Monthly storage plans are unavailable in the App Store. Tap Retry.';
        }
      } else {
        _productsById
          ..clear()
          ..addAll(matches);
        state = 'ready';
        final missing = productIds.length - matches.length;
        message = missing > 0 || response.error != null
            ? 'Some App Store plans are temporarily unavailable.'
            : null;
      }
    } on TimeoutException {
      if (operation == _operationGeneration) {
        state = _productsById.isEmpty ? 'timed_out' : 'ready';
        message = _productsById.isEmpty
            ? 'The App Store took too long to respond. Tap Retry.'
            : 'Using the last available App Store plans. Tap Retry to refresh.';
      }
    } catch (_) {
      if (operation == _operationGeneration) {
        state = _productsById.isEmpty ? 'unavailable' : 'ready';
        message = _productsById.isEmpty
            ? 'The App Store is temporarily unavailable. Tap Retry.'
            : 'Using the last available App Store plans. Tap Retry to refresh.';
      }
    } finally {
      if (operation == _operationGeneration) {
        loading = false;
        notifyListeners();
      }
    }
  }

  Future<void> retry() => initialize(forceRetry: true);

  Future<void> buy([String? targetProductId]) async {
    final currentProduct = targetProductId == null
        ? product
        : productFor(targetProductId);
    if (!canBuy || currentProduct == null) return;
    final operation = ++_operationGeneration;
    loading = true;
    state = 'launching';
    message = null;
    notifyListeners();
    try {
      final launched = await gateway
          .buySubscription(PurchaseParam(
            productDetails: currentProduct,
            applicationUserName: appAccountToken,
          ))
          .timeout(actionTimeout);
      if (operation != _operationGeneration) return;
      if (!launched) {
        state = 'unavailable';
        message = 'The App Store could not start the purchase. Tap Retry.';
      } else {
        message = 'Complete your purchase in the App Store.';
      }
    } on TimeoutException {
      if (operation == _operationGeneration) {
        state = 'timed_out';
        message = 'The App Store took too long to respond. Tap Retry.';
      }
    } catch (_) {
      if (operation == _operationGeneration) {
        state = 'unavailable';
        message = 'The App Store could not start the purchase. Tap Retry.';
      }
    } finally {
      if (operation == _operationGeneration) {
        loading = false;
        notifyListeners();
      }
    }
  }

  Future<void> restore() async {
    if (!available || restoring) return;
    final operation = ++_operationGeneration;
    restoring = true;
    state = 'restoring';
    message = null;
    notifyListeners();
    try {
      await gateway.restorePurchases().timeout(actionTimeout);
      if (operation != _operationGeneration) return;
      message = 'Checking your App Store subscriptions…';
    } on TimeoutException {
      if (operation == _operationGeneration) {
        state = 'timed_out';
        message = 'The App Store took too long to respond. Tap Retry.';
      }
    } catch (_) {
      if (operation == _operationGeneration) {
        state = 'unavailable';
        message = 'The App Store could not restore purchases. Tap Retry.';
      }
    } finally {
      if (operation == _operationGeneration) {
        restoring = false;
        notifyListeners();
      }
    }
  }

  Future<void> _handlePurchases(List<PurchaseDetails> purchases) async {
    final configuredPurchases = purchases
        .where((purchase) => productIds.contains(purchase.productID))
        .toList(growable: false);
    if (configuredPurchases.isEmpty) return;
    final operation = ++_operationGeneration;
    loading = false;
    restoring = false;
    for (final purchase in configuredPurchases) {
      switch (purchase.status) {
        case PurchaseStatus.pending:
          state = 'pending';
          message =
              'Purchase pending. Storage will update after Apple confirms payment.';
          notifyListeners();
          break;
        case PurchaseStatus.purchased:
        case PurchaseStatus.restored:
          await _verifyThenComplete(purchase, operation);
          break;
        case PurchaseStatus.canceled:
          state = 'canceled';
          message = 'Purchase canceled. No storage change was made.';
          notifyListeners();
          break;
        case PurchaseStatus.error:
          state = 'error';
          message = 'The App Store could not complete the purchase.';
          notifyListeners();
          break;
      }
    }
  }

  Future<void> _verifyThenComplete(
    PurchaseDetails purchase,
    int operation,
  ) async {
    final signedTransaction = purchase.verificationData.serverVerificationData;
    if (signedTransaction.isEmpty ||
        _completedTransactions.contains(signedTransaction) ||
        !_verificationInFlight.add(signedTransaction)) {
      return;
    }
    state = 'verifying';
    message = 'Verifying your App Store purchase…';
    notifyListeners();
    try {
      final result = await verifyPurchase(
        signedTransaction: signedTransaction,
        environment: appleTransactionEnvironment(
          signedTransaction,
          fallback: environment,
        ),
      ).timeout(verificationTimeout);
      if (result['verified'] != true) {
        throw StateError('server verification rejected');
      }
      if (purchase.pendingCompletePurchase) {
        await gateway.completePurchase(purchase).timeout(actionTimeout);
      }
      _completedTransactions.add(signedTransaction);
      if (operation == _operationGeneration) {
        state = 'verified';
        message = 'Subscription verified. Your storage limit is updated.';
      }
    } catch (error) {
      if (operation == _operationGeneration) {
        state = 'verification_failed';
        final text = error.toString();
        if (text.contains('subscription_bound_to_another_active_account')) {
          message = 'This App Store subscription is already linked to another '
              'SVaultAI account. Sign in to that account or manage the '
              'subscription with Apple.';
        } else if (text.contains(
            'apple_subscription_status_temporarily_unavailable')) {
          message = 'Apple subscription status is temporarily unavailable. '
              'Use Restore Purchases to retry.';
        } else {
          message = 'Purchase verification is pending. Use Restore Purchases '
              'to retry.';
        }
      }
    } finally {
      _verificationInFlight.remove(signedTransaction);
      if (operation == _operationGeneration) notifyListeners();
    }
  }

  @override
  void dispose() {
    _subscription?.cancel();
    super.dispose();
  }
}
