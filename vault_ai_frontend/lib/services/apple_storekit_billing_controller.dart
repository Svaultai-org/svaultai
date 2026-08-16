import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

typedef ApplePurchaseVerifier = Future<Map<String, dynamic>> Function({
  required String signedTransaction,
  required String environment,
});

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
  final String productId;
  final String appAccountToken;
  final String environment;
  final Duration connectionTimeout;
  final Duration actionTimeout;
  final Duration verificationTimeout;

  StreamSubscription<List<PurchaseDetails>>? _subscription;
  final Set<String> _verificationInFlight = <String>{};
  final Set<String> _completedTransactions = <String>{};

  bool initialized = false;
  bool available = false;
  bool loading = false;
  bool restoring = false;
  ProductDetails? product;
  String state = 'idle';
  String? message;

  bool get canBuy =>
      available &&
      product != null &&
      !loading &&
      !restoring &&
      !const {'launching', 'pending', 'verifying'}.contains(state);

  bool get canRetry => !loading && !restoring && state != 'ready';

  AppleStoreKitBillingController({
    required this.gateway,
    required this.verifyPurchase,
    required this.productId,
    required this.appAccountToken,
    this.environment = 'production',
    this.connectionTimeout = const Duration(seconds: 12),
    this.actionTimeout = const Duration(seconds: 20),
    this.verificationTimeout = const Duration(seconds: 30),
  });

  Future<void> initialize({bool forceRetry = false}) async {
    if ((initialized && !forceRetry) || loading) return;
    initialized = true;
    _subscription ??= gateway.purchaseStream.listen(
      _handlePurchases,
      onError: (_) {
        state = 'unavailable';
        message = 'The App Store is temporarily unavailable. Tap Retry.';
        notifyListeners();
      },
    );
    loading = true;
    available = false;
    product = null;
    state = 'connecting';
    message = 'Connecting to the App Store…';
    notifyListeners();
    try {
      available = await gateway.isAvailable().timeout(connectionTimeout);
      if (!available) {
        state = 'unavailable';
        message = 'App Store purchases are unavailable on this device.';
        return;
      }
      final response = await gateway
          .queryProductDetails({productId}).timeout(connectionTimeout);
      final matches = response.productDetails
          .where((candidate) => candidate.id == productId)
          .toList(growable: false);
      if (response.error != null || matches.length != 1) {
        state = 'unavailable';
        message =
            'The monthly storage subscription is unavailable in the App Store. Tap Retry.';
      } else {
        product = matches.single;
        state = 'ready';
        message = null;
      }
    } on TimeoutException {
      state = 'timed_out';
      message = 'The App Store took too long to respond. Tap Retry.';
    } catch (_) {
      state = 'unavailable';
      message = 'The App Store is temporarily unavailable. Tap Retry.';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> retry() => initialize(forceRetry: true);

  Future<void> buy() async {
    final currentProduct = product;
    if (!canBuy || currentProduct == null) return;
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
      if (!launched) {
        state = 'unavailable';
        message = 'The App Store could not start the purchase. Tap Retry.';
      } else {
        message = 'Complete your purchase in the App Store.';
      }
    } on TimeoutException {
      state = 'timed_out';
      message = 'The App Store took too long to respond. Tap Retry.';
    } catch (_) {
      state = 'unavailable';
      message = 'The App Store could not start the purchase. Tap Retry.';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> restore() async {
    if (!available || restoring) return;
    restoring = true;
    state = 'restoring';
    message = null;
    notifyListeners();
    try {
      await gateway.restorePurchases().timeout(actionTimeout);
      message = 'Checking your App Store subscriptions…';
    } on TimeoutException {
      state = 'timed_out';
      message = 'The App Store took too long to respond. Tap Retry.';
    } catch (_) {
      state = 'unavailable';
      message = 'The App Store could not restore purchases. Tap Retry.';
    } finally {
      restoring = false;
      notifyListeners();
    }
  }

  Future<void> _handlePurchases(List<PurchaseDetails> purchases) async {
    for (final purchase in purchases) {
      if (purchase.productID != productId) continue;
      switch (purchase.status) {
        case PurchaseStatus.pending:
          state = 'pending';
          message =
              'Purchase pending. Storage will update after Apple confirms payment.';
          notifyListeners();
          break;
        case PurchaseStatus.purchased:
        case PurchaseStatus.restored:
          await _verifyThenComplete(purchase);
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

  Future<void> _verifyThenComplete(PurchaseDetails purchase) async {
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
        environment: environment,
      ).timeout(verificationTimeout);
      if (result['verified'] != true) {
        throw StateError('server verification rejected');
      }
      if (purchase.pendingCompletePurchase) {
        await gateway.completePurchase(purchase).timeout(actionTimeout);
      }
      _completedTransactions.add(signedTransaction);
      state = 'verified';
      message = 'Subscription verified. Your storage limit is updated.';
    } catch (_) {
      state = 'verification_failed';
      message =
          'Purchase verification is pending. Use Restore Purchases to retry.';
    } finally {
      _verificationInFlight.remove(signedTransaction);
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _subscription?.cancel();
    super.dispose();
  }
}
