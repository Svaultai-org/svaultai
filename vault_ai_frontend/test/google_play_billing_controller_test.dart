import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/billing_client_wrappers.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';
import 'package:vault_ai_frontend/services/google_play_billing_controller.dart';

const _productId = kGooglePlayStorageProductId;

ProductDetails _playProduct({
  String basePlanId = kGooglePlayStorageBasePlanId,
  String billingPeriod = kGooglePlayStorageBillingPeriod,
  RecurrenceMode recurrenceMode = RecurrenceMode.infiniteRecurring,
}) {
  final wrapper = ProductDetailsWrapper(
    description: 'Monthly storage subscription',
    name: '50 GB storage',
    productId: _productId,
    productType: ProductType.subs,
    title: '50 GB storage',
    subscriptionOfferDetails: [
      SubscriptionOfferDetailsWrapper(
        basePlanId: basePlanId,
        offerId: null,
        offerTags: const [],
        offerIdToken: 'offer-token-$basePlanId',
        pricingPhases: [
          PricingPhaseWrapper(
            billingCycleCount: 0,
            billingPeriod: billingPeriod,
            formattedPrice: r'$25.00',
            priceAmountMicros: 25000000,
            priceCurrencyCode: 'USD',
            recurrenceMode: recurrenceMode,
          ),
        ],
      ),
    ],
  );
  return GooglePlayProductDetails.fromProductDetails(wrapper).single;
}

class _Gateway implements PlayBillingGateway {
  _Gateway({List<ProductDetails>? products})
      : products = products ?? [_playProduct()];

  final controller = StreamController<List<PurchaseDetails>>.broadcast();
  final List<ProductDetails> products;
  bool available = true;
  int buyCalls = 0;
  int restoreCalls = 0;
  int completeCalls = 0;
  PurchaseParam? lastPurchaseParam;

  ProductDetails get product => products.first;

  @override
  Stream<List<PurchaseDetails>> get purchaseStream => controller.stream;

  @override
  Future<bool> isAvailable() async => available;

  @override
  Future<ProductDetailsResponse> queryProductDetails(Set<String> ids) async =>
      ProductDetailsResponse(
        productDetails: ids.contains(_productId) ? products : [],
        notFoundIDs: ids.contains(_productId) ? [] : ids.toList(),
      );

  @override
  Future<bool> buySubscription(PurchaseParam purchaseParam) async {
    buyCalls++;
    lastPurchaseParam = purchaseParam;
    return true;
  }

  @override
  Future<void> restorePurchases() async {
    restoreCalls++;
  }

  @override
  Future<void> completePurchase(PurchaseDetails purchase) async {
    completeCalls++;
  }
}

PurchaseDetails _purchase(PurchaseStatus status, {String token = 'token-1'}) {
  final purchase = PurchaseDetails(
    purchaseID: 'purchase-1',
    productID: _productId,
    verificationData: PurchaseVerificationData(
      localVerificationData: 'local-proof-not-used',
      serverVerificationData: token,
      source: 'google_play',
    ),
    transactionDate: '1786000000000',
    status: status,
  );
  purchase.pendingCompletePurchase = true;
  return purchase;
}

void main() {
  test('only monthly-auto P1M infinite-recurring base plan is accepted', () {
    expect(matchesConfiguredGoogleStoragePlan(_playProduct()), isTrue);
    expect(
      matchesConfiguredGoogleStoragePlan(
          _playProduct(basePlanId: 'wrong-plan')),
      isFalse,
    );
    expect(
      matchesConfiguredGoogleStoragePlan(_playProduct(billingPeriod: 'P1Y')),
      isFalse,
    );
    expect(
      matchesConfiguredGoogleStoragePlan(
        _playProduct(recurrenceMode: RecurrenceMode.nonRecurring),
      ),
      isFalse,
    );
  });

  test('controller refuses product response without configured base plan',
      () async {
    final gateway = _Gateway(
      products: [_playProduct(basePlanId: 'wrong-plan')],
    );
    final billing = GooglePlayBillingController(
      gateway: gateway,
      productId: _productId,
      accountToken: 'opaque-account-token',
      verifyPurchase: ({required productId, required purchaseToken}) async =>
          {'verified': true},
    );
    await billing.initialize();
    expect(billing.state, 'unavailable');
    expect(billing.product, isNull);
    expect(billing.canBuy, isFalse);
    billing.dispose();
    await gateway.controller.close();
  });

  test('queries Play product and launches with opaque account token', () async {
    final gateway = _Gateway();
    final billing = GooglePlayBillingController(
      gateway: gateway,
      productId: _productId,
      accountToken: 'opaque-account-token',
      verifyPurchase: ({required productId, required purchaseToken}) async =>
          {'verified': true},
    );
    await billing.initialize();
    expect(billing.state, 'ready');
    expect(billing.product?.price, r'$25.00');
    await billing.buy();
    expect(gateway.buyCalls, 1);
    expect(
        gateway.lastPurchaseParam?.applicationUserName, 'opaque-account-token');
    billing.dispose();
    await gateway.controller.close();
  });

  test('pending purchase is neither verified nor completed', () async {
    final gateway = _Gateway();
    var verifications = 0;
    final billing = GooglePlayBillingController(
      gateway: gateway,
      productId: _productId,
      accountToken: 'opaque-account-token',
      verifyPurchase: ({required productId, required purchaseToken}) async {
        verifications++;
        return {'verified': true};
      },
    );
    await billing.initialize();
    gateway.controller.add([_purchase(PurchaseStatus.pending)]);
    await Future<void>.delayed(Duration.zero);
    expect(billing.state, 'pending');
    expect(verifications, 0);
    expect(gateway.completeCalls, 0);
    billing.dispose();
    await gateway.controller.close();
  });

  test('verified duplicate callback completes exactly once', () async {
    final gateway = _Gateway();
    var verifications = 0;
    final billing = GooglePlayBillingController(
      gateway: gateway,
      productId: _productId,
      accountToken: 'opaque-account-token',
      verifyPurchase: ({required productId, required purchaseToken}) async {
        verifications++;
        return {'verified': true};
      },
    );
    await billing.initialize();
    final purchase = _purchase(PurchaseStatus.purchased);
    gateway.controller.add([purchase, purchase]);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(billing.state, 'verified');
    expect(verifications, 1);
    expect(gateway.completeCalls, 1);
    billing.dispose();
    await gateway.controller.close();
  });

  test('server rejection never completes purchase and restore remains usable',
      () async {
    final gateway = _Gateway();
    final billing = GooglePlayBillingController(
      gateway: gateway,
      productId: _productId,
      accountToken: 'opaque-account-token',
      verifyPurchase: ({required productId, required purchaseToken}) async =>
          {'verified': false},
    );
    await billing.initialize();
    gateway.controller.add([_purchase(PurchaseStatus.restored)]);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(billing.state, 'verification_failed');
    expect(gateway.completeCalls, 0);
    await billing.restore();
    expect(gateway.restoreCalls, 1);
    billing.dispose();
    await gateway.controller.close();
  });

  test('canceled purchase can be retried without reopening the page', () async {
    final gateway = _Gateway();
    final billing = GooglePlayBillingController(
      gateway: gateway,
      productId: _productId,
      accountToken: 'opaque-account-token',
      verifyPurchase: ({required productId, required purchaseToken}) async =>
          {'verified': true},
    );
    await billing.initialize();
    gateway.controller.add([_purchase(PurchaseStatus.canceled)]);
    await Future<void>.delayed(Duration.zero);
    expect(billing.state, 'canceled');
    expect(billing.canBuy, isTrue);
    await billing.buy();
    expect(gateway.buyCalls, 1);
    billing.dispose();
    await gateway.controller.close();
  });
}
