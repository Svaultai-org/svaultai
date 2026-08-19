import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/billing_client_wrappers.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';
import 'package:vault_ai_frontend/services/google_play_billing_controller.dart';

Map<String, dynamic> _providerCatalog() => {
      'product_id': kGooglePlayStorageProductId,
      'product_ids': kGooglePlayStorageTierAllowlist
          .map((tier) => tier.productId)
          .toList(),
      'base_plan_id': kGooglePlayStorageBasePlanId,
      'base_plan_type': 'AUTO_RENEWING',
      'billing_period': kGooglePlayStorageBillingPeriod,
      'products': kGooglePlayStorageTierAllowlist
          .map(
            (tier) => {
              'product_id': tier.productId,
              'base_plan_id': tier.basePlanId,
              'billing_period': tier.billingPeriod,
              'tier_rank': tier.rank,
              'display_capacity': tier.capacityLabel,
              'storage_entitlement_bytes': tier.entitlementBytes,
              'quantity': tier.quantity,
            },
          )
          .toList(),
    };

ProductDetails _playProduct(
  String productId, {
  String basePlanId = kGooglePlayStorageBasePlanId,
  String billingPeriod = kGooglePlayStorageBillingPeriod,
  RecurrenceMode recurrenceMode = RecurrenceMode.infiniteRecurring,
  String? formattedPrice,
}) {
  final tier = kGooglePlayStorageTierAllowlist.firstWhere(
    (candidate) => candidate.productId == productId,
  );
  final wrapper = ProductDetailsWrapper(
    description: 'Monthly storage subscription',
    name: '${tier.capacityLabel} storage',
    productId: productId,
    productType: ProductType.subs,
    title: '${tier.capacityLabel} storage',
    subscriptionOfferDetails: [
      SubscriptionOfferDetailsWrapper(
        basePlanId: basePlanId,
        offerId: null,
        offerTags: const [],
        offerIdToken: 'offer-token-$productId-$basePlanId',
        pricingPhases: [
          PricingPhaseWrapper(
            billingCycleCount: 0,
            billingPeriod: billingPeriod,
            formattedPrice: formattedPrice ?? 'localized-${tier.rank}',
            priceAmountMicros: tier.rank * 1000000,
            priceCurrencyCode: 'USD',
            recurrenceMode: recurrenceMode,
          ),
        ],
      ),
    ],
  );
  return GooglePlayProductDetails.fromProductDetails(wrapper).single;
}

List<ProductDetails> _allProducts() => kGooglePlayStorageTierAllowlist
    .map((tier) => _playProduct(tier.productId))
    .toList();

class _Gateway implements PlayBillingGateway {
  _Gateway({List<ProductDetails>? products})
      : products = products ?? _allProducts();

  final controller = StreamController<List<PurchaseDetails>>.broadcast();
  final List<ProductDetails> products;
  bool available = true;
  int buyCalls = 0;
  int queryPurchaseCalls = 0;
  int completeCalls = 0;
  PurchaseParam? lastPurchaseParam;
  List<PurchaseDetails> queriedPurchases = <PurchaseDetails>[];
  Set<String> lastProductQuery = <String>{};
  List<String>? notFoundOverride;

  @override
  Stream<List<PurchaseDetails>> get purchaseStream => controller.stream;

  @override
  Future<bool> isAvailable() async => available;

  @override
  Future<ProductDetailsResponse> queryProductDetails(Set<String> ids) async {
    lastProductQuery = ids;
    final returned =
        products.where((product) => ids.contains(product.id)).toList();
    final found = returned.map((product) => product.id).toSet();
    return ProductDetailsResponse(
      productDetails: returned,
      notFoundIDs: notFoundOverride ?? ids.difference(found).toList(),
    );
  }

  @override
  Future<bool> buySubscription(PurchaseParam purchaseParam) async {
    buyCalls++;
    lastPurchaseParam = purchaseParam;
    return true;
  }

  @override
  Future<List<PurchaseDetails>> queryPurchases({
    String? applicationUserName,
  }) async {
    queryPurchaseCalls++;
    return queriedPurchases;
  }

  @override
  Future<void> completePurchase(PurchaseDetails purchase) async {
    completeCalls++;
  }
}

PurchaseDetails _purchase(
  String productId,
  PurchaseStatus status, {
  String token = 'token-1',
}) {
  final purchase = PurchaseDetails(
    purchaseID: 'purchase-1',
    productID: productId,
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

GooglePlayPurchaseDetails _ownedPurchase(
  String productId, {
  String token = 'owned-token',
}) {
  const packageName = 'com.svaultai.app';
  final wrapper = PurchaseWrapper(
    orderId: 'order-$productId',
    packageName: packageName,
    purchaseTime: 1786000000000,
    purchaseToken: token,
    signature: 'synthetic-signature',
    products: [productId],
    isAutoRenewing: true,
    originalJson: '{}',
    isAcknowledged: true,
    purchaseState: PurchaseStateWrapper.purchased,
  );
  return GooglePlayPurchaseDetails.fromPurchase(wrapper).single;
}

Future<Map<String, dynamic>> _noSubscription({
  required List<String> purchaseTokens,
}) async =>
    {
      'reconciled': true,
      'status': 'none',
      'has_active_subscription': false,
      'cleared_pending': true,
    };

Future<Map<String, dynamic>> _activeSubscription({
  required List<String> purchaseTokens,
}) async =>
    {
      'reconciled': true,
      'status': 'active',
      'has_active_subscription': true,
      'cleared_pending': false,
    };

Future<Map<String, dynamic>> _pendingSubscription({
  required List<String> purchaseTokens,
}) async =>
    {
      'reconciled': true,
      'status': 'pending',
      'has_active_subscription': false,
      'cleared_pending': false,
    };

GooglePlayBillingController _billing(
  _Gateway gateway, {
  GooglePurchaseReconciler? reconcile,
  GooglePurchaseVerifier? verify,
}) =>
    GooglePlayBillingController(
      gateway: gateway,
      catalog: kGooglePlayStorageTierAllowlist,
      accountToken: 'opaque-account-token',
      reconcilePurchases: reconcile ?? _noSubscription,
      verifyPurchase: verify ??
          ({required productId, required purchaseToken}) async => {
                'verified': true,
                'status': 'active',
              },
    );

void main() {
  test('backend catalog parser requires the exact eight-tier allowlist', () {
    final parsed = parseGooglePlayStorageCatalog(_providerCatalog());
    expect(parsed, hasLength(8));
    expect(parsed.first.productId, 'svaultai_storage_50gb');
    expect(parsed.last.productId, 'svaultai_storage_1tb');

    final missing = _providerCatalog();
    (missing['products'] as List).removeLast();
    expect(() => parseGooglePlayStorageCatalog(missing), throwsStateError);

    final wrongTier = _providerCatalog();
    ((wrongTier['products'] as List)[1] as Map)['quantity'] = 99;
    expect(() => parseGooglePlayStorageCatalog(wrongTier), throwsStateError);
  });

  test('controller rejects a noncanonical local catalog before Play query',
      () async {
    final gateway = _Gateway();
    final invalidCatalog = <GooglePlayStorageTier>[
      ...kGooglePlayStorageTierAllowlist.take(7),
      const GooglePlayStorageTier(
        productId: 'svaultai_storage_1tb',
        basePlanId: kGooglePlayStorageBasePlanId,
        billingPeriod: kGooglePlayStorageBillingPeriod,
        rank: 8,
        capacityLabel: '1 TB',
        entitlementBytes: 1073741824000,
        quantity: 21,
      ),
    ];
    final billing = GooglePlayBillingController(
      gateway: gateway,
      catalog: invalidCatalog,
      accountToken: 'opaque-account-token',
      reconcilePurchases: _noSubscription,
      verifyPurchase: ({required productId, required purchaseToken}) async => {
        'verified': true,
        'status': 'active',
      },
    );

    await billing.initialize();

    expect(billing.state, 'unavailable');
    expect(billing.catalogReady, isFalse);
    expect(gateway.lastProductQuery, isEmpty);
  });

  test(
    'only the configured product monthly-auto P1M base plan is accepted',
    () {
      const productId = 'svaultai_storage_100gb';
      expect(
        matchesConfiguredGoogleStoragePlan(
          _playProduct(productId),
          productId: productId,
        ),
        isTrue,
      );
      expect(
        matchesConfiguredGoogleStoragePlan(
          _playProduct(productId, basePlanId: 'wrong-plan'),
          productId: productId,
        ),
        isFalse,
      );
      expect(
        matchesConfiguredGoogleStoragePlan(
          _playProduct(productId, billingPeriod: 'P1Y'),
          productId: productId,
        ),
        isFalse,
      );
      expect(
        matchesConfiguredGoogleStoragePlan(
          _playProduct(productId, recurrenceMode: RecurrenceMode.nonRecurring),
          productId: productId,
        ),
        isFalse,
      );
    },
  );

  test('queries and retains all eight localized ProductDetails', () async {
    final gateway = _Gateway();
    final billing = _billing(gateway);
    await billing.initialize();

    expect(billing.state, 'ready');
    expect(gateway.lastProductQuery, billing.productIds);
    expect(gateway.lastProductQuery, hasLength(8));
    expect(billing.products, hasLength(8));
    expect(billing.productFor('svaultai_storage_250gb')?.price, 'localized-5');
    expect(billing.catalogReady, isTrue);

    billing.dispose();
    await gateway.controller.close();
  });

  test(
    'fails closed when any required product or base plan is missing',
    () async {
      final missingProduct = _Gateway(products: _allProducts()..removeLast());
      final missingBilling = _billing(missingProduct);
      await missingBilling.initialize();
      expect(missingBilling.state, 'unavailable');
      expect(missingBilling.catalogReady, isFalse);
      expect(missingBilling.canBuy, isFalse);
      missingBilling.dispose();
      await missingProduct.controller.close();

      final wrongPlanProducts = _allProducts();
      wrongPlanProducts.removeWhere(
        (product) => product.id == 'svaultai_storage_250gb',
      );
      wrongPlanProducts.add(
        _playProduct('svaultai_storage_250gb', basePlanId: 'wrong-plan'),
      );
      final wrongPlan = _Gateway(products: wrongPlanProducts);
      final wrongPlanBilling = _billing(wrongPlan);
      await wrongPlanBilling.initialize();
      expect(wrongPlanBilling.state, 'unavailable');
      expect(wrongPlanBilling.canBuy, isFalse);
      wrongPlanBilling.dispose();
      await wrongPlan.controller.close();
    },
  );

  test('fails closed on duplicate configured product/base plan', () async {
    final products = _allProducts();
    products.add(_playProduct('svaultai_storage_100gb'));
    final gateway = _Gateway(products: products);
    final billing = _billing(gateway);
    await billing.initialize();
    expect(billing.state, 'unavailable');
    expect(billing.catalogReady, isFalse);
    billing.dispose();
    await gateway.controller.close();
  });

  test(
    'free user can select any real tier using localized ProductDetails',
    () async {
      final gateway = _Gateway();
      final billing = _billing(gateway);
      await billing.initialize();
      await billing.buy('svaultai_storage_100gb');

      expect(gateway.buyCalls, 1);
      expect(gateway.queryPurchaseCalls, 1);
      expect(gateway.lastPurchaseParam, isA<GooglePlayPurchaseParam>());
      final param = gateway.lastPurchaseParam! as GooglePlayPurchaseParam;
      expect(param.productDetails.id, 'svaultai_storage_100gb');
      expect(param.productDetails.price, 'localized-2');
      expect(param.applicationUserName, 'opaque-account-token');
      expect(param.changeSubscriptionParam, isNull);

      billing.dispose();
      await gateway.controller.close();
    },
  );

  for (final transition in const [
    ('svaultai_storage_50gb', 'svaultai_storage_100gb'),
    ('svaultai_storage_50gb', 'svaultai_storage_250gb'),
    ('svaultai_storage_100gb', 'svaultai_storage_500gb'),
    ('svaultai_storage_250gb', 'svaultai_storage_500gb'),
    ('svaultai_storage_500gb', 'svaultai_storage_1tb'),
  ]) {
    test(
      '${transition.$1} replaces into ${transition.$2} without stacking',
      () async {
        final gateway = _Gateway();
        final oldPurchase = _ownedPurchase(transition.$1);
        gateway.queriedPurchases = [oldPurchase];
        final billing = _billing(gateway);
        await billing.initialize();
        await billing.buy(transition.$2, currentProductId: transition.$1);

        expect(gateway.buyCalls, 1);
        final param = gateway.lastPurchaseParam! as GooglePlayPurchaseParam;
        expect(param.productDetails.id, transition.$2);
        expect(param.changeSubscriptionParam, isNotNull);
        expect(
          param.changeSubscriptionParam!.oldPurchaseDetails,
          same(oldPurchase),
        );
        expect(
          param.changeSubscriptionParam!.replacementMode,
          ReplacementMode.chargeProratedPrice,
        );

        billing.dispose();
        await gateway.controller.close();
      },
    );
  }

  test('downgrade and equal-tier replacement are never launched', () async {
    final gateway = _Gateway();
    gateway.queriedPurchases = [_ownedPurchase('svaultai_storage_250gb')];
    final billing = _billing(gateway);
    await billing.initialize();
    await billing.buy(
      'svaultai_storage_100gb',
      currentProductId: 'svaultai_storage_250gb',
    );
    expect(gateway.buyCalls, 0);
    expect(billing.state, 'downgrade_not_supported');

    await billing.buy(
      'svaultai_storage_250gb',
      currentProductId: 'svaultai_storage_250gb',
    );
    expect(gateway.buyCalls, 0);

    billing.dispose();
    await gateway.controller.close();
  });

  test(
    'existing owned tier blocks a free-flow purchase instead of stacking',
    () async {
      final gateway = _Gateway();
      gateway.queriedPurchases = [_ownedPurchase('svaultai_storage_50gb')];
      final billing = _billing(gateway);
      await billing.initialize();
      await billing.buy('svaultai_storage_100gb');
      expect(gateway.buyCalls, 0);
      expect(billing.state, 'ownership_conflict');
      expect(billing.message, contains('existing Google Play subscription'));
      billing.dispose();
      await gateway.controller.close();
    },
  );

  test('pending purchase is neither verified nor completed', () async {
    final gateway = _Gateway();
    var verifications = 0;
    final billing = _billing(
      gateway,
      reconcile: _pendingSubscription,
      verify: ({required productId, required purchaseToken}) async {
        verifications++;
        return {'verified': true};
      },
    );
    await billing.initialize();
    gateway.controller.add([
      _purchase('svaultai_storage_100gb', PurchaseStatus.pending),
    ]);
    await Future<void>.delayed(Duration.zero);
    expect(billing.state, 'pending');
    expect(verifications, 0);
    expect(gateway.completeCalls, 0);
    expect(billing.canBuy, isFalse);
    billing.dispose();
    await gateway.controller.close();
  });

  test('verified duplicate callback completes exactly once', () async {
    final gateway = _Gateway();
    var verifications = 0;
    final billing = _billing(
      gateway,
      reconcile: _activeSubscription,
      verify: ({required productId, required purchaseToken}) async {
        verifications++;
        return {'verified': true, 'status': 'active'};
      },
    );
    await billing.initialize();
    final purchase = _purchase(
      'svaultai_storage_500gb',
      PurchaseStatus.purchased,
    );
    gateway.controller.add([purchase, purchase]);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(billing.state, 'verified');
    expect(verifications, 1);
    expect(gateway.completeCalls, 1);
    billing.dispose();
    await gateway.controller.close();
  });

  test('canceled upgrade remains canceled and can be retried', () async {
    final gateway = _Gateway();
    final billing = _billing(gateway);
    await billing.initialize();
    gateway.controller.add([
      _purchase('svaultai_storage_250gb', PurchaseStatus.canceled),
    ]);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(billing.state, 'canceled');
    expect(billing.message, contains('No storage change'));
    expect(billing.canBuy, isTrue);
    billing.dispose();
    await gateway.controller.close();
  });
}
