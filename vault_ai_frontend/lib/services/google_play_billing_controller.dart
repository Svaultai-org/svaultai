import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/billing_client_wrappers.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';

const String kGooglePlayStorageProductId = 'svaultai_storage_50gb';
const String kGooglePlayStorageBasePlanId = 'monthly-auto';
const String kGooglePlayStorageBillingPeriod = 'P1M';

@immutable
class GooglePlayStorageTier {
  final String productId;
  final String basePlanId;
  final String billingPeriod;
  final int rank;
  final String capacityLabel;
  final int entitlementBytes;
  final int quantity;

  const GooglePlayStorageTier({
    required this.productId,
    required this.basePlanId,
    required this.billingPeriod,
    required this.rank,
    required this.capacityLabel,
    required this.entitlementBytes,
    required this.quantity,
  });
}

const List<GooglePlayStorageTier> kGooglePlayStorageTierAllowlist = [
  GooglePlayStorageTier(
    productId: 'svaultai_storage_50gb',
    basePlanId: kGooglePlayStorageBasePlanId,
    billingPeriod: kGooglePlayStorageBillingPeriod,
    rank: 1,
    capacityLabel: '50 GB',
    entitlementBytes: 53687091200,
    quantity: 1,
  ),
  GooglePlayStorageTier(
    productId: 'svaultai_storage_100gb',
    basePlanId: kGooglePlayStorageBasePlanId,
    billingPeriod: kGooglePlayStorageBillingPeriod,
    rank: 2,
    capacityLabel: '100 GB',
    entitlementBytes: 107374182400,
    quantity: 2,
  ),
  GooglePlayStorageTier(
    productId: 'svaultai_storage_150gb',
    basePlanId: kGooglePlayStorageBasePlanId,
    billingPeriod: kGooglePlayStorageBillingPeriod,
    rank: 3,
    capacityLabel: '150 GB',
    entitlementBytes: 161061273600,
    quantity: 3,
  ),
  GooglePlayStorageTier(
    productId: 'svaultai_storage_200gb',
    basePlanId: kGooglePlayStorageBasePlanId,
    billingPeriod: kGooglePlayStorageBillingPeriod,
    rank: 4,
    capacityLabel: '200 GB',
    entitlementBytes: 214748364800,
    quantity: 4,
  ),
  GooglePlayStorageTier(
    productId: 'svaultai_storage_250gb',
    basePlanId: kGooglePlayStorageBasePlanId,
    billingPeriod: kGooglePlayStorageBillingPeriod,
    rank: 5,
    capacityLabel: '250 GB',
    entitlementBytes: 268435456000,
    quantity: 5,
  ),
  GooglePlayStorageTier(
    productId: 'svaultai_storage_300gb',
    basePlanId: kGooglePlayStorageBasePlanId,
    billingPeriod: kGooglePlayStorageBillingPeriod,
    rank: 6,
    capacityLabel: '300 GB',
    entitlementBytes: 322122547200,
    quantity: 6,
  ),
  GooglePlayStorageTier(
    productId: 'svaultai_storage_500gb',
    basePlanId: kGooglePlayStorageBasePlanId,
    billingPeriod: kGooglePlayStorageBillingPeriod,
    rank: 7,
    capacityLabel: '500 GB',
    entitlementBytes: 536870912000,
    quantity: 10,
  ),
  GooglePlayStorageTier(
    productId: 'svaultai_storage_1tb',
    basePlanId: kGooglePlayStorageBasePlanId,
    billingPeriod: kGooglePlayStorageBillingPeriod,
    rank: 8,
    capacityLabel: '1 TB',
    entitlementBytes: 1073741824000,
    quantity: 20,
  ),
];

bool _isCanonicalStorageCatalog(List<GooglePlayStorageTier> catalog) {
  if (catalog.length != kGooglePlayStorageTierAllowlist.length) return false;
  for (var index = 0; index < catalog.length; index++) {
    final actual = catalog[index];
    final expected = kGooglePlayStorageTierAllowlist[index];
    if (actual.productId != expected.productId ||
        actual.basePlanId != expected.basePlanId ||
        actual.billingPeriod != expected.billingPeriod ||
        actual.rank != expected.rank ||
        actual.capacityLabel != expected.capacityLabel ||
        actual.entitlementBytes != expected.entitlementBytes ||
        actual.quantity != expected.quantity) {
      return false;
    }
  }
  return true;
}

List<GooglePlayStorageTier> parseGooglePlayStorageCatalog(
  Map<dynamic, dynamic> provider,
) {
  if (provider['product_id']?.toString() != kGooglePlayStorageProductId ||
      provider['base_plan_id']?.toString() != kGooglePlayStorageBasePlanId ||
      provider['base_plan_type']?.toString() != 'AUTO_RENEWING' ||
      provider['billing_period']?.toString() !=
          kGooglePlayStorageBillingPeriod) {
    throw StateError('google_play_catalog_contract_mismatch');
  }
  final rawIds = provider['product_ids'];
  final rawProducts = provider['products'];
  if (rawIds is! List || rawProducts is! List) {
    throw StateError('google_play_catalog_incomplete');
  }
  final ids = rawIds.map((value) => value.toString()).toList(growable: false);
  final expectedIds =
      kGooglePlayStorageTierAllowlist.map((tier) => tier.productId).toSet();
  if (ids.length != expectedIds.length ||
      !setEquals(ids.toSet(), expectedIds)) {
    throw StateError('google_play_catalog_product_ids_mismatch');
  }
  if (rawProducts.length != kGooglePlayStorageTierAllowlist.length) {
    throw StateError('google_play_catalog_incomplete');
  }

  final byId = <String, Map<dynamic, dynamic>>{};
  for (final raw in rawProducts) {
    if (raw is! Map) throw StateError('google_play_catalog_invalid_product');
    final productId = raw['product_id']?.toString() ?? '';
    if (productId.isEmpty || byId.containsKey(productId)) {
      throw StateError('google_play_catalog_duplicate_product');
    }
    byId[productId] = raw;
  }
  if (!setEquals(byId.keys.toSet(), expectedIds)) {
    throw StateError('google_play_catalog_unknown_product');
  }

  for (final expected in kGooglePlayStorageTierAllowlist) {
    final raw = byId[expected.productId]!;
    if (raw['base_plan_id']?.toString() != expected.basePlanId ||
        raw['billing_period']?.toString() != expected.billingPeriod ||
        (raw['tier_rank'] as num?)?.toInt() != expected.rank ||
        raw['display_capacity']?.toString() != expected.capacityLabel ||
        (raw['storage_entitlement_bytes'] as num?)?.toInt() !=
            expected.entitlementBytes ||
        (raw['quantity'] as num?)?.toInt() != expected.quantity) {
      throw StateError('google_play_catalog_tier_mismatch');
    }
  }
  return kGooglePlayStorageTierAllowlist;
}

bool matchesConfiguredGoogleStoragePlan(
  ProductDetails candidate, {
  String productId = kGooglePlayStorageProductId,
  String basePlanId = kGooglePlayStorageBasePlanId,
  String billingPeriod = kGooglePlayStorageBillingPeriod,
}) {
  if (candidate.id != productId || candidate is! GooglePlayProductDetails) {
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

typedef GooglePurchaseReconciler = Future<Map<String, dynamic>> Function({
  required List<String> purchaseTokens,
});

abstract class PlayBillingGateway {
  Stream<List<PurchaseDetails>> get purchaseStream;
  Future<bool> isAvailable();
  Future<ProductDetailsResponse> queryProductDetails(Set<String> productIds);
  Future<bool> buySubscription(PurchaseParam purchaseParam);
  Future<List<PurchaseDetails>> queryPurchases({String? applicationUserName});
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
  Future<List<PurchaseDetails>> queryPurchases({
    String? applicationUserName,
  }) async {
    final addition =
        _delegate.getPlatformAddition<InAppPurchaseAndroidPlatformAddition>();
    final response = await addition.queryPastPurchases(
      applicationUserName: applicationUserName,
    );
    final error = response.error;
    if (error != null) {
      throw StateError('Google Play purchase query failed: ${error.code}');
    }
    return response.pastPurchases;
  }

  @override
  Future<void> completePurchase(PurchaseDetails purchase) =>
      _delegate.completePurchase(purchase);
}

class GooglePlayBillingController extends ChangeNotifier {
  final PlayBillingGateway gateway;
  final GooglePurchaseVerifier verifyPurchase;
  final GooglePurchaseReconciler reconcilePurchases;
  final List<GooglePlayStorageTier> catalog;
  final String accountToken;
  final Duration connectionTimeout;
  final Duration actionTimeout;
  final Duration verificationTimeout;

  StreamSubscription<List<PurchaseDetails>>? _subscription;
  final Set<String> _verificationInFlight = <String>{};
  final Set<String> _completedTokens = <String>{};
  final Map<String, ProductDetails> _productsById = <String, ProductDetails>{};

  bool initialized = false;
  bool available = false;
  bool loading = false;
  bool restoring = false;
  String state = 'idle';
  String? message;

  Set<String> get productIds => catalog.map((tier) => tier.productId).toSet();
  bool get catalogReady => _productsById.length == catalog.length;
  List<ProductDetails> get products => catalog
      .map((tier) => _productsById[tier.productId])
      .whereType<ProductDetails>()
      .toList(growable: false);
  ProductDetails? get product => productFor(kGooglePlayStorageProductId);
  ProductDetails? productFor(String productId) => _productsById[productId];

  GooglePlayStorageTier? tierForProduct(String productId) {
    for (final tier in catalog) {
      if (tier.productId == productId) return tier;
    }
    return null;
  }

  GooglePlayStorageTier? tierForQuantity(int quantity) {
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

  GooglePlayBillingController({
    required this.gateway,
    required this.verifyPurchase,
    required this.reconcilePurchases,
    required List<GooglePlayStorageTier> catalog,
    required this.accountToken,
    this.connectionTimeout = const Duration(seconds: 12),
    this.actionTimeout = const Duration(seconds: 20),
    this.verificationTimeout = const Duration(seconds: 30),
  }) : catalog = List<GooglePlayStorageTier>.unmodifiable(catalog);

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
    _productsById.clear();
    state = 'connecting';
    message = 'Connecting to Google Play…';
    notifyListeners();
    try {
      if (!_isCanonicalStorageCatalog(catalog)) {
        throw StateError('google_play_catalog_invalid');
      }
      available = await gateway.isAvailable().timeout(connectionTimeout);
      if (!available) {
        state = 'unavailable';
        message = 'Google Play Billing is unavailable on this device.';
        notifyListeners();
        return;
      }
      final response = await gateway
          .queryProductDetails(productIds)
          .timeout(connectionTimeout);
      if (response.error != null || response.notFoundIDs.isNotEmpty) {
        throw StateError('google_play_catalog_query_failed');
      }
      if (response.productDetails.any(
        (item) => !productIds.contains(item.id),
      )) {
        throw StateError('google_play_catalog_unknown_product');
      }
      for (final tier in catalog) {
        final matches = response.productDetails
            .where(
              (item) => matchesConfiguredGoogleStoragePlan(
                item,
                productId: tier.productId,
                basePlanId: tier.basePlanId,
                billingPeriod: tier.billingPeriod,
              ),
            )
            .toList(growable: false);
        if (matches.length != 1 || matches.single.price.trim().isEmpty) {
          throw StateError('google_play_catalog_incomplete');
        }
        _productsById[tier.productId] = matches.single;
      }
      if (!catalogReady) throw StateError('google_play_catalog_incomplete');
      state = 'ready';
      message = null;
    } on TimeoutException {
      state = 'timed_out';
      message = 'Google Play took too long to respond. Tap Retry.';
    } catch (_) {
      _productsById.clear();
      state = 'unavailable';
      message =
          'The complete monthly storage catalog is not available in Google Play. Tap Retry.';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> retry() => initialize(forceRetry: true);

  Future<void> buy(String targetProductId, {String? currentProductId}) async {
    final targetProduct = productFor(targetProductId);
    final targetTier = tierForProduct(targetProductId);
    if (!canBuy || targetProduct == null || targetTier == null) return;
    loading = true;
    state = 'launching';
    message = null;
    notifyListeners();
    try {
      final purchases = await gateway
          .queryPurchases(applicationUserName: accountToken)
          .timeout(actionTimeout);
      if (purchases.any(
        (purchase) =>
            purchase.productID.startsWith('svaultai_storage_') &&
            !productIds.contains(purchase.productID),
      )) {
        state = 'ownership_conflict';
        message = 'Refresh your Google Play subscription before trying again.';
        return;
      }
      final owned = purchases.where((purchase) {
        return productIds.contains(purchase.productID) &&
            const {
              PurchaseStatus.purchased,
              PurchaseStatus.restored,
            }.contains(purchase.status) &&
            purchase.verificationData.serverVerificationData.trim().isNotEmpty;
      }).toList(growable: false);
      if (purchases.any(
        (purchase) =>
            productIds.contains(purchase.productID) &&
            purchase.status == PurchaseStatus.pending,
      )) {
        state = 'pending';
        message =
            'Purchase pending. Storage will update after Google confirms payment.';
        return;
      }

      ChangeSubscriptionParam? change;
      if (currentProductId == null) {
        if (owned.isNotEmpty) {
          state = 'ownership_conflict';
          message =
              'An existing Google Play subscription was found. Use Restore purchases / Refresh.';
          return;
        }
      } else {
        final currentTier = tierForProduct(currentProductId);
        if (currentTier == null || targetTier.rank <= currentTier.rank) {
          state = 'downgrade_not_supported';
          message = 'Only higher-tier storage upgrades are available here.';
          return;
        }
        final current = owned
            .where((purchase) => purchase.productID == currentProductId)
            .toList(growable: false);
        if (owned.length != 1 ||
            current.length != 1 ||
            current.single is! GooglePlayPurchaseDetails) {
          state = 'ownership_conflict';
          message =
              'Refresh your Google Play subscription before changing plans.';
          return;
        }
        change = ChangeSubscriptionParam(
          oldPurchaseDetails: current.single as GooglePlayPurchaseDetails,
          replacementMode: ReplacementMode.chargeProratedPrice,
        );
      }

      final launched = await gateway
          .buySubscription(
            GooglePlayPurchaseParam(
              productDetails: targetProduct,
              applicationUserName: accountToken,
              changeSubscriptionParam: change,
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

  Future<void> restore({bool silent = false}) async {
    if (!available || restoring) return;
    restoring = true;
    if (!silent) {
      state = 'restoring';
      message = null;
      notifyListeners();
    }
    try {
      final purchases = await gateway
          .queryPurchases(applicationUserName: accountToken)
          .timeout(actionTimeout);
      final current = purchases
          .where((purchase) => productIds.contains(purchase.productID))
          .toList(growable: false);
      if (current.isEmpty) {
        await _reconcileCurrentPurchases(const <PurchaseDetails>[]);
      } else {
        await _handlePurchases(current);
      }
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
    final current = <PurchaseDetails>[];
    var hadCanceled = false;
    var hadPendingOrCompleted = false;
    for (final purchase in purchases) {
      if (!productIds.contains(purchase.productID)) continue;
      current.add(purchase);
      switch (purchase.status) {
        case PurchaseStatus.pending:
          hadPendingOrCompleted = true;
          state = 'pending';
          message =
              'Purchase pending. Storage will update after Google confirms payment.';
          notifyListeners();
          break;
        case PurchaseStatus.purchased:
        case PurchaseStatus.restored:
          hadPendingOrCompleted = true;
          await _verifyThenComplete(purchase);
          break;
        case PurchaseStatus.canceled:
          hadCanceled = true;
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
    if (current.isNotEmpty) {
      await _reconcileCurrentPurchases(current);
    }
    if (hadCanceled && !hadPendingOrCompleted) {
      state = 'canceled';
      message = 'Purchase canceled. No storage change was made.';
      notifyListeners();
    }
  }

  Future<void> _reconcileCurrentPurchases(
    List<PurchaseDetails> purchases,
  ) async {
    final tokens = <String>[];
    var hasPendingPurchase = false;
    for (final purchase in purchases) {
      hasPendingPurchase =
          hasPendingPurchase || purchase.status == PurchaseStatus.pending;
      final token = purchase.verificationData.serverVerificationData.trim();
      if (token.isNotEmpty && !tokens.contains(token)) tokens.add(token);
    }
    if (hasPendingPurchase && tokens.isEmpty) {
      state = 'pending';
      message =
          'Purchase pending. Storage will update after Google confirms payment.';
      notifyListeners();
      return;
    }
    try {
      final result = await reconcilePurchases(
        purchaseTokens: tokens,
      ).timeout(verificationTimeout);
      if (result['reconciled'] != true) {
        throw StateError('server reconciliation rejected');
      }
      final serverStatus = result['status']?.toString() ?? 'none';
      final active = result['has_active_subscription'] == true;
      final clearedPending = result['cleared_pending'] == true;
      if (active) {
        state = 'verified';
        message = 'Subscription verified. Your storage limit is updated.';
      } else if (serverStatus == 'pending' ||
          (hasPendingPurchase && !clearedPending)) {
        state = 'pending';
        message =
            'Purchase pending. Storage will update after Google confirms payment.';
      } else {
        state = 'reconciled';
        message =
            'No active Google Play subscription was found. You can buy storage.';
      }
    } catch (_) {
      state = hasPendingPurchase ? 'pending' : 'verification_failed';
      message = hasPendingPurchase
          ? 'Purchase pending. Storage will update after Google confirms payment.'
          : 'Purchase verification is pending. Use Restore Purchases to retry.';
    }
    notifyListeners();
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
      final serverStatus = result['status']?.toString() ?? '';
      if (serverStatus == 'pending') {
        state = 'pending';
        message =
            'Purchase pending. Storage will update after Google confirms payment.';
        return;
      }
      if (!const {
        'active',
        'reactivated',
        'grace_period',
      }.contains(serverStatus)) {
        state = 'reconciled';
        message =
            'No active Google Play subscription was found. You can buy storage.';
        return;
      }
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
