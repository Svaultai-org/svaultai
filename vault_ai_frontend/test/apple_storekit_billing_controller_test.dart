import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:vault_ai_frontend/services/apple_storekit_billing_controller.dart';

const _productId = 'synthetic.storage.monthly';

ProductDetails _product() => ProductDetails(
      id: _productId,
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
        productDetails: ids.contains(_productId) ? [_product()] : [],
        notFoundIDs: ids.contains(_productId) ? [] : ids.toList(),
      );

  @override
  Future<bool> buySubscription(PurchaseParam purchaseParam) async {
    buyCalls++;
    lastPurchaseParam = purchaseParam;
    return true;
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
      productId: _productId,
      appAccountToken: '00000000-0000-5000-8000-000000000001',
      verifyPurchase: verifier,
      connectionTimeout: const Duration(milliseconds: 20),
      actionTimeout: const Duration(milliseconds: 20),
      verificationTimeout: const Duration(milliseconds: 20),
    );

void main() {
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
}
