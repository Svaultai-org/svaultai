import 'dart:async';
import 'dart:collection';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/billing_client_wrappers.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';

import 'google_play_verification.dart';

/// These are total monthly tiers, not consumable or stackable storage units.
const Map<int, String> googlePlayStorageProductIds = {
  1: 'svaultai_storage_50gb',
  2: 'svaultai_storage_100gb',
  3: 'svaultai_storage_150gb',
  4: 'svaultai_storage_200gb',
  5: 'svaultai_storage_250gb',
  6: 'svaultai_storage_300gb',
  10: 'svaultai_storage_500gb',
  20: 'svaultai_storage_1tb',
};

bool get supportsGooglePlayIap =>
    !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

bool isGooglePlayStorageProduct(String id) =>
    googlePlayStorageProductIds.containsValue(id);

class GooglePlayProviderCatalog {
  GooglePlayProviderCatalog._(this.accountToken, this.quantities);

  /// Server-issued obfuscated correlator, never a vault name or bearer token.
  final String accountToken;
  final Map<String, int> quantities;

  factory GooglePlayProviderCatalog.fromProviders(Map<String, dynamic> data) {
    final value = data['google_play'];
    if (value is! Map ||
        value['base_plan_id'] != 'monthly-auto' ||
        value['base_plan_type'] != 'AUTO_RENEWING' ||
        value['billing_period'] != 'P1M' ||
        value['account_token'] is! String ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(value['account_token'] as String) ||
        value['products'] is! List) {
      throw const FormatException('Google Play billing catalog unavailable.');
    }
    final quantities = <String, int>{};
    for (final item in value['products'] as List) {
      if (item is! Map) {
        throw const FormatException('Google Play billing catalog unavailable.');
      }
      final id = item['product_id'];
      final quantity = item['quantity'];
      if (id is! String ||
          quantity is! int ||
          googlePlayStorageProductIds[quantity] != id ||
          quantities.containsKey(id) ||
          item['base_plan_id'] != 'monthly-auto' ||
          item['billing_period'] != 'P1M' ||
          item['storage_entitlement_bytes'] != quantity * 53687091200) {
        throw const FormatException('Google Play billing catalog unavailable.');
      }
      quantities[id] = quantity;
    }
    if (quantities.isEmpty) {
      throw const FormatException('Google Play billing catalog unavailable.');
    }
    return GooglePlayProviderCatalog._(
      value['account_token'] as String,
      Map.unmodifiable(quantities),
    );
  }

  @override
  String toString() => 'GooglePlayProviderCatalog(${quantities.length} tiers)';
}

class GooglePlayIapCatalog {
  const GooglePlayIapCatalog({
    required this.storeAvailable,
    required this.products,
    this.error,
  });
  final bool storeAvailable;
  final Map<int, GooglePlayProductDetails> products;
  final String? error;
  bool get canPurchase => storeAvailable && products.isNotEmpty;
}

abstract class GooglePlayStoreAdapter {
  Stream<List<PurchaseDetails>> get purchaseStream;
  Future<bool> isAvailable();
  Future<ProductDetailsResponse> queryProductDetails(Set<String> identifiers);
  Future<QueryPurchaseDetailsResponse> queryPurchases(String accountToken);
  Future<bool> buy(GooglePlayPurchaseParam parameters);
  Future<void> finish(PurchaseDetails purchase);
}

class _GooglePlayStoreAdapter implements GooglePlayStoreAdapter {
  InAppPurchase get _store => InAppPurchase.instance;
  @override
  Stream<List<PurchaseDetails>> get purchaseStream => _store.purchaseStream;
  @override
  Future<bool> isAvailable() => _store.isAvailable();
  @override
  Future<ProductDetailsResponse> queryProductDetails(Set<String> identifiers) =>
      _store.queryProductDetails(identifiers);
  @override
  Future<QueryPurchaseDetailsResponse> queryPurchases(String accountToken) =>
      _store
          .getPlatformAddition<InAppPurchaseAndroidPlatformAddition>()
          .queryPastPurchases(applicationUserName: accountToken);
  @override
  Future<bool> buy(GooglePlayPurchaseParam parameters) =>
      _store.buyNonConsumable(purchaseParam: parameters);
  @override
  Future<void> finish(PurchaseDetails purchase) =>
      _store.completePurchase(purchase);
}

/// Includes the purchase token only in a private, bounded in-memory identity.
/// Never serialize/log this key or use an order ID (renewals can change it).
String googlePlayTransactionKey(GooglePlayPurchaseDetails purchase) =>
    '${purchase.productID}:${purchase.verificationData.serverVerificationData}';

class GooglePlayRecoveryResult {
  const GooglePlayRecoveryResult(this.handled, this.verification);
  final bool handled;
  final Map<String, dynamic> verification;
}

/// Retries verification of an already-owned purchase, NEVER checkout.
class GooglePlayPurchaseRecovery {
  GooglePlayPurchaseRecovery({Future<void> Function(Duration)? delay})
      : _delay = delay ?? Future<void>.delayed;
  final Future<void> Function(Duration) _delay;
  final Map<String, Future<Map<String, dynamic>>> _inFlight = {};
  final LinkedHashMap<String, Map<String, dynamic>> _completed =
      LinkedHashMap();

  Future<GooglePlayRecoveryResult> recover({
    required String accountKey,
    required String transactionKey,
    required bool Function() isCurrent,
    required Future<Map<String, dynamic>> Function() verify,
    required Future<void> Function() finish,
    Future<void> Function()? retireTerminal,
  }) async {
    final key = '$accountKey:$transactionKey';
    final done = _completed[key];
    if (done != null) return GooglePlayRecoveryResult(false, done);
    final pending = _inFlight[key];
    if (pending != null) return GooglePlayRecoveryResult(false, await pending);
    final operation = _recover(isCurrent, verify, finish, retireTerminal);
    _inFlight[key] = operation;
    try {
      final result = await operation;
      _completed[key] = result;
      if (_completed.length > 100) _completed.remove(_completed.keys.first);
      return GooglePlayRecoveryResult(true, result);
    } finally {
      _inFlight.remove(key);
    }
  }

  Future<Map<String, dynamic>> _recover(
    bool Function() isCurrent,
    Future<Map<String, dynamic>> Function() verify,
    Future<void> Function() finish,
    Future<void> Function()? retireTerminal,
  ) async {
    for (var attempt = 0; attempt < 3; attempt++) {
      if (!isCurrent()) {
        throw const GooglePlayPurchaseVerificationException(statusCode: 403);
      }
      Map<String, dynamic> result;
      try {
        result = await verify();
      } on GooglePlayPurchaseVerificationException catch (error) {
        if (!error.isTransient || attempt == 2) rethrow;
        await _delay(Duration(milliseconds: 500 * (attempt + 1)));
        continue;
      }
      if (!isCurrent()) {
        throw const GooglePlayPurchaseVerificationException(statusCode: 403);
      }
      if (result['verified'] == true &&
          result['provider'] == 'google_play' &&
          const {'expired', 'refunded', 'revoked', 'canceled'}
              .contains(result['status']) &&
          retireTerminal != null) {
        // Retiring a server-confirmed terminal receipt is NOT a new grant or
        // an acknowledgement. Never erase merely on an empty Play query.
        await retireTerminal();
        return result;
      }
      if (result['verified'] != true ||
          result['provider'] != 'google_play' ||
          result['acknowledged'] != true ||
          result['status'] == 'pending') {
        throw const GooglePlayPurchaseVerificationException(
          statusCode: 200,
          code: 'activation_unconfirmed',
        );
      }
      // The server persists/verifies the entitlement and acknowledges first.
      // A failed plugin finish remains recoverable and is never a new charge.
      await finish();
      return result;
    }
    throw StateError('Google Play verification retry exhausted.');
  }
}

class GooglePlayIapService {
  GooglePlayIapService._() : _store = _GooglePlayStoreAdapter();
  @visibleForTesting
  GooglePlayIapService.forTesting({required GooglePlayStoreAdapter store})
      : _store = store,
        _supportedOverride = true;
  static final instance = GooglePlayIapService._();
  final GooglePlayStoreAdapter _store;
  bool? _supportedOverride;
  bool get _supported => _supportedOverride ?? supportsGooglePlayIap;
  final recovery = GooglePlayPurchaseRecovery();
  final _events = StreamController<List<PurchaseDetails>>.broadcast(sync: true);
  StreamSubscription<List<PurchaseDetails>>? _subscription;
  final Map<String, GooglePlayPurchaseDetails> _unresolved = {};
  final Map<String, Future<void>> _finishing = {};
  final LinkedHashSet<String> _finished = LinkedHashSet();
  Future<List<GooglePlayPurchaseDetails>>? _restoring;
  String? _checkoutProduct;
  String? _checkoutPreviousProduct;
  String? _checkoutPreviousToken;
  String? _checkoutAccountToken;
  bool _launching = false;

  bool get hasPendingStoreRequest =>
      _launching ||
      _checkoutProduct != null ||
      _unresolved.values.any((p) => p.status == PurchaseStatus.pending);
  bool get hasPendingActivation => _unresolved.values.any((p) =>
      p.status == PurchaseStatus.purchased ||
      p.status == PurchaseStatus.restored);

  List<GooglePlayPurchaseDetails> get retainedPurchases =>
      List.unmodifiable(_unresolved.values);

  Future<void> retireVerifiedTerminal(
      GooglePlayPurchaseDetails purchase) async {
    final key = googlePlayTransactionKey(purchase);
    _unresolved.remove(key);
    // Local terminal dedupe only; no acknowledgement/consumption is sent.
    _finished.add(key);
    if (_finished.length > 100) _finished.remove(_finished.first);
    if (purchase.productID == _checkoutProduct) _checkoutProduct = null;
  }

  Stream<List<PurchaseDetails>> get transactions => Stream.multi((controller) {
        final subscription = _events.stream.listen(controller.addSync,
            onError: controller.addErrorSync, onDone: controller.closeSync);
        controller.onCancel = subscription.cancel;
        if (_unresolved.isNotEmpty) {
          controller.addSync(List<PurchaseDetails>.of(_unresolved.values));
        }
      });

  void initialize() {
    if (!_supported || _subscription != null) return;
    _subscription = _store.purchaseStream.listen(_record, onError: (_) {
      // Connection loss is not a payment cancellation. Preserve an accepted
      // checkout until a terminal/correlated Play event resolves it.
      _events.addError(StateError('Google Play connection interrupted.'));
    });
  }

  void _record(List<PurchaseDetails> updates, {bool emit = true}) {
    final accepted = <PurchaseDetails>[];
    for (final purchase in updates) {
      // Pinned Android plugin0.5.3 emits a BASE PurchaseDetails with blank
      // IDs when the checkout is canceled/failed without a purchase list.
      // This closes only our one local checkout, never a receipt or quota.
      if (purchase is! GooglePlayPurchaseDetails &&
          purchase.productID.isEmpty &&
          purchase.purchaseID == '' &&
          purchase.verificationData.localVerificationData.isEmpty &&
          purchase.verificationData.serverVerificationData.isEmpty &&
          purchase.verificationData.source == 'google_play' &&
          (purchase.status == PurchaseStatus.canceled ||
              purchase.status == PurchaseStatus.error) &&
          _checkoutProduct != null) {
        accepted.add(PurchaseDetails(
            productID: _checkoutProduct!,
            verificationData: PurchaseVerificationData(
                localVerificationData: '',
                serverVerificationData: '',
                source: 'google_play'),
            transactionDate: null,
            status: purchase.status));
        _checkoutProduct = null;
        continue;
      }
      if (purchase is! GooglePlayPurchaseDetails ||
          !isGooglePlayStorageProduct(purchase.productID)) {
        continue;
      }
      final key = googlePlayTransactionKey(purchase);
      if (_finished.contains(key)) continue;
      accepted.add(purchase);
      final deferredReplacement =
          purchase.productID == _checkoutPreviousProduct &&
              purchase.billingClientPurchase.obfuscatedAccountId ==
                  _checkoutAccountToken &&
              purchase.verificationData.serverVerificationData.isNotEmpty &&
              purchase.verificationData.serverVerificationData !=
                  _checkoutPreviousToken &&
              (purchase.status == PurchaseStatus.purchased ||
                  purchase.status == PurchaseStatus.restored);
      if (purchase.status != PurchaseStatus.pending &&
          (purchase.productID == _checkoutProduct || deferredReplacement)) {
        _checkoutProduct = null;
        _checkoutPreviousProduct = null;
        _checkoutPreviousToken = null;
        _checkoutAccountToken = null;
      }
      if (purchase.status == PurchaseStatus.pending ||
          purchase.status == PurchaseStatus.purchased ||
          purchase.status == PurchaseStatus.restored) {
        if (!_finished.contains(key)) _unresolved[key] = purchase;
      } else {
        _unresolved.remove(key);
      }
    }
    if (emit && accepted.isNotEmpty) _events.add(accepted);
  }

  void replayPendingTransactions() {
    if (_unresolved.isNotEmpty) {
      _events.add(List<PurchaseDetails>.of(_unresolved.values));
    }
  }

  Future<GooglePlayIapCatalog> loadCatalog(
      GooglePlayProviderCatalog provider) async {
    initialize();
    if (!_supported || !await _store.isAvailable()) {
      return const GooglePlayIapCatalog(
          storeAvailable: false,
          products: {},
          error: 'Google Play billing is unavailable on this device.');
    }
    final response =
        await _store.queryProductDetails(provider.quantities.keys.toSet());
    if (response.error != null) {
      return const GooglePlayIapCatalog(
          storeAvailable: true,
          products: {},
          error:
              'Google Play storage plans could not be loaded. Please retry.');
    }
    final products = <int, GooglePlayProductDetails>{};
    for (final product in response.productDetails) {
      if (product is! GooglePlayProductDetails ||
          !provider.quantities.containsKey(product.id) ||
          !_isMonthlyBasePlan(product)) {
        continue;
      }
      final quantity = provider.quantities[product.id]!;
      // Ambiguous duplicate regular base plans fail closed for that tier.
      if (products.containsKey(quantity)) {
        return const GooglePlayIapCatalog(
            storeAvailable: true,
            products: {},
            error: 'Google Play storage plans could not be verified.');
      }
      products[quantity] = product;
    }
    return GooglePlayIapCatalog(
        storeAvailable: true,
        products: Map.unmodifiable(products),
        error: products.isEmpty
            ? 'No eligible monthly storage plans are available from Google Play.'
            : null);
  }

  bool _isMonthlyBasePlan(GooglePlayProductDetails product) {
    final index = product.subscriptionIndex;
    final offers = product.productDetails.subscriptionOfferDetails;
    if (product.productDetails.productType != ProductType.subs ||
        index == null ||
        offers == null ||
        index < 0 ||
        index >= offers.length) {
      return false;
    }
    final offer = offers[index];
    if (offer.basePlanId != 'monthly-auto' ||
        offer.offerId != null ||
        offer.offerIdToken.isEmpty ||
        offer.installmentPlanDetails != null ||
        offer.pricingPhases.length != 1) {
      return false;
    }
    final price = offer.pricingPhases.single;
    return price.billingPeriod == 'P1M' &&
        price.recurrenceMode == RecurrenceMode.infiniteRecurring &&
        price.priceAmountMicros > 0 &&
        price.formattedPrice.isNotEmpty;
  }

  /// Used for Restore, launch preparation and foreground recovery. Querying
  /// ownership never purchases/consumes anything. Empty results are valid.
  Future<List<GooglePlayPurchaseDetails>> queryOwnedPurchases(
      GooglePlayProviderCatalog provider,
      {bool emit = true}) {
    final pending = _restoring;
    if (pending != null) return pending;
    final operation = _queryOwned(provider, emit);
    _restoring = operation;
    return operation.whenComplete(() => _restoring = null);
  }

  Future<List<GooglePlayPurchaseDetails>> _queryOwned(
      GooglePlayProviderCatalog provider, bool emit) async {
    initialize();
    if (!_supported || !await _store.isAvailable()) {
      throw StateError('Google Play restoration unavailable.');
    }
    final response = await _store.queryPurchases(provider.accountToken);
    if (response.error != null) {
      throw StateError('Google Play restoration unavailable.');
    }
    final owned = response.pastPurchases
        .where((purchase) => isGooglePlayStorageProduct(purchase.productID))
        .toList();
    // Do not erase unresolved receipts just because a transient store query
    // omitted them. Backend reconciliation, never this list, controls quota.
    _record(owned, emit: emit);
    return owned;
  }

  Future<bool> buy({
    required GooglePlayProviderCatalog provider,
    required GooglePlayProductDetails product,
    required List<GooglePlayPurchaseDetails> ownedPurchases,
    String? currentProductId,
  }) async {
    initialize();
    if (!_supported || hasPendingStoreRequest) return false;
    if (hasPendingActivation) {
      throw StateError(
          'Restore the existing Google Play purchase before buying.');
    }
    if (!_isMonthlyBasePlan(product) ||
        !provider.quantities.containsKey(product.id)) {
      throw StateError('Google Play storage plan unavailable.');
    }
    final owned = ownedPurchases
        .where((p) =>
            p.status == PurchaseStatus.purchased ||
            p.status == PurchaseStatus.restored)
        .toList();
    GooglePlayPurchaseDetails? previous;
    if (currentProductId != null || owned.isNotEmpty) {
      // Cross-vault ownership cannot be inferred from a product or order ID.
      // Require a single real Play purchase with the SAME server correlator.
      final matches = owned
          .where((p) =>
              p.billingClientPurchase.obfuscatedAccountId ==
                  provider.accountToken &&
              (currentProductId == null || p.productID == currentProductId))
          .toList();
      if (owned.length != 1 ||
          matches.length != 1 ||
          matches.single.verificationData.serverVerificationData.isEmpty) {
        throw StateError(
            'Restore Purchases to verify the existing subscription before changing plans.');
      }
      previous = matches.single;
      if (previous.productID == product.id) return false;
    }
    final previousQuantity =
        previous == null ? null : provider.quantities[previous.productID];
    if (previous != null && previousQuantity == null) {
      throw StateError('Existing Google Play subscription unavailable.');
    }
    final quantity = provider.quantities[product.id]!;
    final parameters = GooglePlayPurchaseParam(
      productDetails: product,
      applicationUserName: provider.accountToken,
      offerToken: product.offerToken,
      changeSubscriptionParam: previous == null
          ? null
          : ChangeSubscriptionParam(
              oldPurchaseDetails: previous,
              replacementMode: quantity < previousQuantity!
                  ? ReplacementMode.deferred
                  : ReplacementMode.withTimeProration,
            ),
    );
    _launching = true;
    _checkoutProduct = product.id;
    _checkoutPreviousProduct = previous?.productID;
    _checkoutPreviousToken = previous?.verificationData.serverVerificationData;
    _checkoutAccountToken = provider.accountToken;
    try {
      final launched = await _store.buy(parameters);
      if (!launched) _checkoutProduct = null;
      return launched;
    } catch (_) {
      _checkoutProduct = null;
      rethrow;
    } finally {
      _launching = false;
    }
  }

  Future<void> finish(GooglePlayPurchaseDetails purchase) async {
    if (purchase.status != PurchaseStatus.purchased &&
        purchase.status != PurchaseStatus.restored) {
      throw StateError('A pending Google Play purchase cannot be finished.');
    }
    final key = googlePlayTransactionKey(purchase);
    if (purchase.verificationData.serverVerificationData.isEmpty) {
      throw StateError('Google Play purchase identity unavailable.');
    }
    if (_finished.contains(key)) return;
    final pending = _finishing[key];
    if (pending != null) return pending;
    final operation = () async {
      if (purchase.pendingCompletePurchase) await _store.finish(purchase);
      _finished.add(key);
      if (_finished.length > 100) _finished.remove(_finished.first);
      _unresolved.remove(key);
    }();
    _finishing[key] = operation;
    try {
      await operation;
    } finally {
      _finishing.remove(key);
    }
  }

  @visibleForTesting
  Future<void> disposeForTesting() async {
    await _subscription?.cancel();
    await _events.close();
  }
}
