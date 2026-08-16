import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/billing_client_wrappers.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';

const String kGooglePlayStorageProductId = 'svaultai_storage_50gb';
const String kGooglePlayStorageBasePlanId = 'monthly-auto';
const String kGooglePlayStorageBillingPeriod = 'P1M';

bool matchesConfiguredGoogleStoragePlan(
  ProductDetails candidate, {
  String basePlanId = kGooglePlayStorageBasePlanId,
  String billingPeriod = kGooglePlayStorageBillingPeriod,
}) {
  if (candidate.id != kGooglePlayStorageProductId ||
      candidate is! GooglePlayProductDetails) {
    return false;
  }
  final index = candidate.subscriptionIndex;
  final offers = candidate.productDetails.subscriptionOfferDetails;
  if (index == null || offers == null || index >= offers.length) {
    return false;
  }
  final offer = offers[index];
  if (offer.basePlanId != basePlanId ||
      offer.offerId != null ||
      offer.installmentPlanDetails != null) {
    return false;
  }
  return offer.pricingPhases.any(
    (phase) =>
        phase.billingPeriod == billingPeriod &&
        phase.recurrenceMode == RecurrenceMode.infiniteRecurring,
  );
}

typedef GooglePurchaseVerifier = Future<Map<String, dynamic>> Function({
  required String productId,
  required String purchaseToken,
});

abstract class PlayBillingGateway {
  Stream<List<PurchaseDetails>> get purchaseStream;
  Future<bool> isAvailable();
  Future<ProductDetailsResponse> queryProductDetails(Set<String> productIds);
  Future<bool> buySubscription(PurchaseParam purchaseParam);
  Future<void> restorePurchases();
  Future<void> completePurchase(PurchaseDetails purchase);
}

class FlutterPlayBillingGateway implements PlayBillingGateway {
  final InAppPurchase _delegate;

  FlutterPlayBillingGateway({InAppPurchase? delegate})
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

class GooglePlayBillingController extends ChangeNotifier {
  final PlayBillingGateway gateway;
  final GooglePurchaseVerifier verifyPurchase;
  final String productId;
  final String accountToken;
  final String basePlanId;
  final String billingPeriod;
  final Duration connectionTimeout;
  final Duration actionTimeout;
  final Duration verificationTimeout;

  StreamSubscription<List<PurchaseDetails>>? _subscription;
  final Set<String> _verificationInFlight = <String>{};
  final Set<String> _completedTokens = <String>{};

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

  GooglePlayBillingController({
    required this.gateway,
    required this.verifyPurchase,
    required this.productId,
    required this.accountToken,
    this.basePlanId = kGooglePlayStorageBasePlanId,
    this.billingPeriod = kGooglePlayStorageBillingPeriod,
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
        message = 'Google Play Billing is temporarily unavailable.';
        notifyListeners();
      },
    );
    loading = true;
    available = false;
    product = null;
    state = 'connecting';
    message = 'Connecting to Google Play…';
    notifyListeners();
    try {
      available = await gateway.isAvailable().timeout(connectionTimeout);
      if (!available) {
        state = 'unavailable';
        message = 'Google Play Billing is unavailable on this device.';
        notifyListeners();
        return;
      }
      final response = await gateway
          .queryProductDetails({productId}).timeout(connectionTimeout);
      final configuredProducts = response.productDetails
          .where(
            (item) => matchesConfiguredGoogleStoragePlan(
              item,
              basePlanId: basePlanId,
              billingPeriod: billingPeriod,
            ),
          )
          .toList(growable: false);
      if (response.error != null || configuredProducts.isEmpty) {
        state = 'unavailable';
        message =
            'The monthly auto-renewing storage subscription is not available '
            'in Google Play.';
      } else {
        product = configuredProducts.first;
        state = 'ready';
        message = null;
      }
    } on TimeoutException {
      state = 'timed_out';
      message = 'Google Play took too long to respond. Tap Retry.';
    } catch (_) {
      state = 'unavailable';
      message = 'Google Play Billing is temporarily unavailable. Tap Retry.';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> retry() => initialize(forceRetry: true);

  Future<void> buy() async {
    final currentProduct = product;
    if (!available || currentProduct == null || loading) return;
    loading = true;
    state = 'launching';
    message = null;
    notifyListeners();
    try {
      final launched = await gateway
          .buySubscription(
            PurchaseParam(
              productDetails: currentProduct,
              applicationUserName: accountToken,
            ),
          )
          .timeout(actionTimeout);
      if (!launched) {
        state = 'unavailable';
        message = 'Google Play could not start the purchase.';
      } else {
        message = 'Complete your purchase in Google Play.';
      }
    } on TimeoutException {
      state = 'timed_out';
      message = 'Google Play took too long to respond. Tap Retry.';
    } catch (_) {
      state = 'unavailable';
      message = 'Google Play could not start the purchase.';
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
      message = 'Checking your Google Play subscriptions…';
    } on TimeoutException {
      state = 'timed_out';
      message = 'Google Play took too long to respond. Tap Retry.';
    } catch (_) {
      state = 'unavailable';
      message = 'Google Play could not restore purchases.';
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
              'Purchase pending. Storage will update after Google confirms payment.';
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
          message = 'Google Play could not complete the purchase.';
          notifyListeners();
          break;
      }
    }
  }

  Future<void> _verifyThenComplete(PurchaseDetails purchase) async {
    final token = purchase.verificationData.serverVerificationData;
    if (token.isEmpty || _completedTokens.contains(token)) return;
    if (!_verificationInFlight.add(token)) return;
    state = 'verifying';
    message = 'Verifying your purchase…';
    notifyListeners();
    try {
      final result = await verifyPurchase(
        productId: purchase.productID,
        purchaseToken: token,
      ).timeout(verificationTimeout);
      if (result['verified'] != true) {
        throw StateError('server verification rejected');
      }
      // completePurchase is deliberately after server verification. The
      // backend also acknowledges with the Developer API for reliability;
      // this client completion is safe and idempotent.
      if (purchase.pendingCompletePurchase) {
        await gateway.completePurchase(purchase).timeout(actionTimeout);
      }
      _completedTokens.add(token);
      state = 'verified';
      message = 'Subscription verified. Your storage limit is updated.';
    } catch (_) {
      state = 'verification_failed';
      message =
          'Purchase verification is pending. Use Restore Purchases to retry.';
    } finally {
      _verificationInFlight.remove(token);
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _subscription?.cancel();
    super.dispose();
  }
}
