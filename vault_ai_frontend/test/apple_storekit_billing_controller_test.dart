import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:vault_ai_frontend/services/apple_storekit_billing_controller.dart';

const _productId = 'synthetic.storage.monthly';
const _secondProductId = 'synthetic.storage.100gb.monthly';

const _tier = AppleStorageTier(
  productId: _productId,
  billingPeriod: 'P1M',
  capacityLabel: '50 GB',
  entitlementBytes: 53687091200,
  quantity: 1,
);

const _secondTier = AppleStorageTier(
  productId: _secondProductId,
  billingPeriod: 'P1M',
  capacityLabel: '100 GB',
  entitlementBytes: 107374182400,
  quantity: 2,
);

ProductDetails _product([String productId = _productId]) => ProductDetails(
      id: productId,
      title: 'Synthetic storage',
      description: 'Synthetic test product',
      price: r'$1.00',
      rawPrice: 1,
      currencyCode: 'USD',
    );

class _Gateway implements AppleBillingGateway {
  final controller = StreamController<List<PurchaseDetails>>.broadcast();
  bool available = true;
  bool hangAvailability = false;
  final Set<String> availableProductIds = <String>{_productId};
  Completer<bool>? buyCompleter;
  int buyCalls = 0;
  int restoreCalls = 0;
  int completeCalls = 0;
  PurchaseParam? lastPurchaseParam;

  @override
  Stream<List<PurchaseDetails>> get purchaseStream => controller.stream;

  @override
  Future<bool> isAvailable() => hangAvailability
      ? Completer<bool>().future
      : Future<bool>.value(available);

  @override
  Future<ProductDetailsResponse> queryProductDetails(Set<String> ids) async =>
      ProductDetailsResponse(
        productDetails: ids
            .where(availableProductIds.contains)
            .map(_product)
            .toList(growable: false),
        notFoundIDs: ids
            .where((id) => !availableProductIds.contains(id))
            .toList(growable: false),
      );

  @override
  Future<bool> buySubscription(PurchaseParam purchaseParam) async {
    buyCalls++;
    lastPurchaseParam = purchaseParam;
    return buyCompleter?.future ?? true;
  }

  @override
  Future<void> restorePurchases() async => restoreCalls++;

  @override
  Future<void> completePurchase(PurchaseDetails purchase) async =>
      completeCalls++;
}

PurchaseDetails _purchase(PurchaseStatus status, {String jws = 'signed-jws'}) {
  final purchase = PurchaseDetails(
    purchaseID: 'synthetic-transaction',
    productID: _productId,
    verificationData: PurchaseVerificationData(
      localVerificationData: 'local-proof-never-trusted',
      serverVerificationData: jws,
      source: 'app_store',
    ),
    transactionDate: '1786000000000',
    status: status,
  );
  purchase.pendingCompletePurchase = true;
  return purchase;
}

AppleStoreKitBillingController _billing(
  _Gateway gateway, {
  required ApplePurchaseVerifier verifier,
}) =>
    AppleStoreKitBillingController(
      gateway: gateway,
      catalog: const <AppleStorageTier>[_tier],
      appAccountToken: '00000000-0000-5000-8000-000000000001',
      verifyPurchase: verifier,
      connectionTimeout: const Duration(milliseconds: 20),
      actionTimeout: const Duration(milliseconds: 20),
      verificationTimeout: const Duration(milliseconds: 20),
    );

void main() {
  test('provider catalog is authoritative and sorted by entitlement', () {
    final catalog = parseAppleStorageCatalog({
      'configured': true,
      'product_ids': [_secondProductId, _productId],
      'products': [
        {
          'product_id': _secondProductId,
          'billing_period': 'P1M',
          'display_capacity': '100 GB',
          'storage_entitlement_bytes': 107374182400,
          'quantity': 2,
        },
        {
          'product_id': _productId,
          'billing_period': 'P1M',
          'display_capacity': '50 GB',
          'storage_entitlement_bytes': 53687091200,
          'quantity': 1,
        },
      ],
    });

    expect(catalog.map((tier) => tier.productId), [
      _productId,
      _secondProductId,
    ]);
    expect(catalog.map((tier) => tier.capacityLabel), ['50 GB', '100 GB']);
  });

  test('queries product and launches with opaque App Account Token', () async {
    final gateway = _Gateway();
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async =>
          {'verified': true},
    );
    await billing.initialize();
    expect(billing.state, 'ready');
    await billing.buy();
    expect(gateway.buyCalls, 1);
    expect(billing.message, contains('Complete your purchase'));
    billing.dispose();
    await gateway.controller.close();
  });

  test('connection is bounded and retry recovers', () async {
    final gateway = _Gateway()..hangAvailability = true;
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async =>
          {'verified': true},
    );
    await billing.initialize();
    expect(billing.state, 'timed_out');
    expect(billing.message, contains('Tap Retry'));

    gateway.hangAvailability = false;
    await billing.retry();
    expect(billing.state, 'ready');
    expect(billing.product?.id, _productId);
    billing.dispose();
    await gateway.controller.close();
  });

  test('partial StoreKit catalog keeps available server-approved plans',
      () async {
    final gateway = _Gateway();
    final billing = AppleStoreKitBillingController(
      gateway: gateway,
      catalog: const <AppleStorageTier>[_tier, _secondTier],
      appAccountToken: '00000000-0000-5000-8000-000000000001',
      verifyPurchase:
          ({required signedTransaction, required environment}) async =>
              {'verified': true},
    );

    await billing.initialize();
    expect(billing.state, 'ready');
    expect(billing.products.map((product) => product.id), [_productId]);
    expect(billing.message, contains('Some App Store plans'));
    expect(billing.canBuy, isTrue);
    billing.dispose();
    await gateway.controller.close();
  });

  test('server verification precedes transaction completion', () async {
    final gateway = _Gateway();
    var verified = false;
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async {
        expect(signedTransaction, 'signed-jws');
        verified = true;
        return {'verified': true};
      },
    );
    await billing.initialize();
    gateway.controller.add([_purchase(PurchaseStatus.purchased)]);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(verified, isTrue);
    expect(gateway.completeCalls, 1);
    expect(billing.state, 'verified');
    billing.dispose();
    await gateway.controller.close();
  });

  test('signed TestFlight transaction selects sandbox verification', () async {
    final gateway = _Gateway();
    String? verifiedEnvironment;
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async {
        verifiedEnvironment = environment;
        return {'verified': true};
      },
    );
    await billing.initialize();
    const sandboxJws =
        'header.eyJlbnZpcm9ubWVudCI6IlNhbmRib3gifQ.signature';
    gateway.controller.add([
      _purchase(PurchaseStatus.purchased, jws: sandboxJws),
    ]);
    await Future<void>.delayed(const Duration(milliseconds: 10));

    expect(verifiedEnvironment, 'sandbox');
    expect(billing.state, 'verified');
    billing.dispose();
    await gateway.controller.close();
  });

  test('late buy timeout cannot overwrite verified purchase state', () async {
    final gateway = _Gateway()..buyCompleter = Completer<bool>();
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async =>
          {'verified': true},
    );
    await billing.initialize();

    final buy = billing.buy();
    gateway.controller.add([_purchase(PurchaseStatus.purchased)]);
    await Future<void>.delayed(const Duration(milliseconds: 30));
    await buy;

    expect(billing.state, 'verified');
    expect(billing.loading, isFalse);
    billing.dispose();
    await gateway.controller.close();
  });

  test('canceled state retains valid cached plan and can retry purchase',
      () async {
    final gateway = _Gateway();
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async =>
          {'verified': true},
    );
    await billing.initialize();
    gateway.controller.add([_purchase(PurchaseStatus.canceled)]);
    await Future<void>.delayed(Duration.zero);

    expect(billing.state, 'canceled');
    expect(billing.product?.id, _productId);
    expect(billing.canBuy, isTrue);
    billing.dispose();
    await gateway.controller.close();
  });

  test('pending and rejected purchases are never completed', () async {
    final gateway = _Gateway();
    var verifications = 0;
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async {
        verifications++;
        return {'verified': false};
      },
    );
    await billing.initialize();
    gateway.controller.add([_purchase(PurchaseStatus.pending)]);
    await Future<void>.delayed(Duration.zero);
    expect(verifications, 0);
    expect(gateway.completeCalls, 0);

    gateway.controller.add([_purchase(PurchaseStatus.restored)]);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(billing.state, 'verification_failed');
    expect(gateway.completeCalls, 0);
    billing.dispose();
    await gateway.controller.close();
  });

  test('restore verifies and completes a restored transaction once', () async {
    final gateway = _Gateway();
    var verifications = 0;
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async {
        verifications++;
        expect(signedTransaction, 'signed-jws');
        return {'verified': true};
      },
    );
    await billing.initialize();

    await billing.restore();
    expect(gateway.restoreCalls, 1);
    gateway.controller.add([_purchase(PurchaseStatus.restored)]);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(verifications, 1);
    expect(gateway.completeCalls, 1);
    expect(billing.state, 'verified');

    gateway.controller.add([_purchase(PurchaseStatus.restored)]);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(verifications, 1);
    expect(gateway.completeCalls, 1);
    billing.dispose();
    await gateway.controller.close();
  });
}
