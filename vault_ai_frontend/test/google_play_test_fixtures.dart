import 'dart:async';

import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/billing_client_wrappers.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';
import 'package:vault_ai_frontend/services/google_play_iap_service.dart';

const googleAccountToken =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const googleOtherAccountToken =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

Map<String, dynamic> googleProvidersFixture() => {
      'google_play': {
        'account_token': googleAccountToken,
        'base_plan_id': 'monthly-auto',
        'base_plan_type': 'AUTO_RENEWING',
        'billing_period': 'P1M',
        'products': [
          for (final entry in googlePlayStorageProductIds.entries)
            {
              'product_id': entry.value,
              'quantity': entry.key,
              'base_plan_id': 'monthly-auto',
              'billing_period': 'P1M',
              'storage_entitlement_bytes': entry.key * 53687091200,
            }
        ],
      },
    };

GooglePlayProductDetails googleProductFixture({
  int quantity = 1,
  String basePlan = 'monthly-auto',
  String? offerId,
  String period = 'P1M',
  RecurrenceMode recurrence = RecurrenceMode.infiniteRecurring,
  String offerToken = 'synthetic-offer-token',
  int priceMicros = 14990000,
}) =>
    GooglePlayProductDetails.fromProductDetails(ProductDetailsWrapper(
      description: 'Monthly storage',
      name: 'Storage',
      title: 'Storage',
      productId: googlePlayStorageProductIds[quantity]!,
      productType: ProductType.subs,
      subscriptionOfferDetails: [
        SubscriptionOfferDetailsWrapper(
          basePlanId: basePlan,
          offerId: offerId,
          offerTags: const [],
          offerIdToken: offerToken,
          pricingPhases: [
            PricingPhaseWrapper(
                billingCycleCount: 0,
                billingPeriod: period,
                formattedPrice: '£14.99',
                priceAmountMicros: priceMicros,
                priceCurrencyCode: 'GBP',
                recurrenceMode: recurrence)
          ],
        )
      ],
    )).single;

GooglePlayPurchaseDetails googlePurchaseFixture({
  int quantity = 1,
  String token = 'synthetic-purchase-token',
  String? accountToken = googleAccountToken,
  bool acknowledged = false,
  PurchaseStatus status = PurchaseStatus.purchased,
  String? product,
}) =>
    GooglePlayPurchaseDetails(
      purchaseID: 'synthetic-order',
      productID: product ?? googlePlayStorageProductIds[quantity]!,
      verificationData: PurchaseVerificationData(
          localVerificationData: '',
          serverVerificationData: token,
          source: 'google_play'),
      transactionDate: '1234',
      status: status,
      billingClientPurchase: PurchaseWrapper(
          orderId: 'synthetic-order',
          packageName: 'com.svaultai.app',
          purchaseTime: 1234,
          purchaseToken: token,
          signature: '',
          products: [product ?? googlePlayStorageProductIds[quantity]!],
          isAutoRenewing: true,
          originalJson: '',
          isAcknowledged: acknowledged,
          purchaseState: status == PurchaseStatus.pending
              ? PurchaseStateWrapper.pending
              : PurchaseStateWrapper.purchased,
          obfuscatedAccountId: accountToken),
    );

PurchaseDetails googleEmptyCheckoutFixture(PurchaseStatus status) =>
    PurchaseDetails(
        purchaseID: '',
        productID: '',
        transactionDate: null,
        status: status,
        verificationData: PurchaseVerificationData(
            localVerificationData: '',
            serverVerificationData: '',
            source: 'google_play'));

class FakeGooglePlayStore implements GooglePlayStoreAdapter {
  final updates = StreamController<List<PurchaseDetails>>.broadcast(sync: true);
  bool available = true;
  List<ProductDetails> products = [
    googleProductFixture(),
    googleProductFixture(quantity: 6)
  ];
  List<GooglePlayPurchaseDetails> owned = [];
  int buys = 0, queries = 0, finishes = 0;
  GooglePlayPurchaseParam? lastBuy;
  String? lastAccountToken;
  Set<String>? queriedIds;
  bool failFinish = false;
  IAPError? queryError;
  Completer<bool>? buyGate;
  Completer<void>? finishGate;
  Completer<QueryPurchaseDetailsResponse>? queryGate;
  @override
  Stream<List<PurchaseDetails>> get purchaseStream => updates.stream;
  @override
  Future<bool> isAvailable() async => available;
  @override
  Future<ProductDetailsResponse> queryProductDetails(
      Set<String> identifiers) async {
    queriedIds = identifiers;
    return ProductDetailsResponse(productDetails: products, notFoundIDs: []);
  }

  @override
  Future<QueryPurchaseDetailsResponse> queryPurchases(
      String accountToken) async {
    queries++;
    lastAccountToken = accountToken;
    return queryGate == null
        ? QueryPurchaseDetailsResponse(pastPurchases: owned, error: queryError)
        : await queryGate!.future;
  }

  @override
  Future<bool> buy(GooglePlayPurchaseParam parameters) async {
    buys++;
    lastBuy = parameters;
    return buyGate == null ? true : await buyGate!.future;
  }

  @override
  Future<void> finish(PurchaseDetails purchase) async {
    finishes++;
    if (failFinish) throw StateError('Synthetic finish failure');
    if (finishGate != null) await finishGate!.future;
  }
}
