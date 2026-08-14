import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:vault_ai_frontend/services/apple_storekit_billing_controller.dart';

const _productId = 'svaultai.storage.50gb.monthly';

ProductDetails _product() => ProductDetails(
      id: _productId,
      title: 'SVaultAI 50 GB Storage',
      description: '50 GB additional encrypted storage, billed monthly',
      price: r'$25.00',
      rawPrice: 25,
      currencyCode: 'USD',
    );

class _Gateway implements AppleBillingGateway {
  final controller = StreamController<List<PurchaseDetails>>.broadcast();
  bool available = true;
  int buyCalls = 0;
  int restoreCalls = 0;
  int completeCalls = 0;
  PurchaseParam? lastPurchaseParam;

  @override
  Stream<List<PurchaseDetails>> get purchaseStream => controller.stream;

  @override
  Future<bool> isAvailable() async => available;

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
    purchaseID: 'transaction-1',
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
    );

void main() {
  test('queries localized product and launches with App Account Token',
      () async {
    final gateway = _Gateway();
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async =>
          {'verified': true},
    );
    await billing.initialize();
    expect(billing.state, 'ready');
    expect(billing.product?.price, r'$25.00');
    await billing.buy();
    expect(gateway.buyCalls, 1);
    expect(gateway.lastPurchaseParam?.applicationUserName,
        '00000000-0000-5000-8000-000000000001');
    billing.dispose();
    await gateway.controller.close();
  });

  test('pending transaction is never verified or finished', () async {
    final gateway = _Gateway();
    var verifications = 0;
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async {
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

  test('verified duplicate transaction is finished exactly once', () async {
    final gateway = _Gateway();
    var verifications = 0;
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async {
        verifications++;
        expect(signedTransaction, 'signed-jws');
        expect(environment, 'production');
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

  test('unverified transaction is never finished and restore retries',
      () async {
    final gateway = _Gateway();
    final billing = _billing(
      gateway,
      verifier: ({required signedTransaction, required environment}) async =>
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
}
