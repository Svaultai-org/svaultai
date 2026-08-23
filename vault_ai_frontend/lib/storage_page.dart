import 'dart:async' show TimeoutException, unawaited;

import 'package:flutter/foundation.dart'
    show kIsWeb, kReleaseMode, defaultTargetPlatform, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_storekit/in_app_purchase_storekit.dart';
import 'package:in_app_purchase_storekit/store_kit_2_wrappers.dart';
import 'package:in_app_purchase_storekit/store_kit_wrappers.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'l10n/app_localizations.dart';
import 'main.dart' show AppState, backendBaseUrl, kVaultStorageLimitBytes, vlog;
import 'privacy_policy_page.dart' show kVaultAiPrivacyUrl;
import 'services/apple_storekit_billing_controller.dart';
import 'services/google_play_billing_controller.dart';
import 'ui/tokens.dart';

const String kAppleStoreKitEnvironment = String.fromEnvironment(
  'APPLE_STOREKIT_ENVIRONMENT',
  defaultValue: 'production',
);

const Duration kStoreConnectionTimeout = Duration(seconds: 12);
const String kGooglePlayPackageName = 'com.svaultai.app';
const String kAppleManageSubscriptionsUrl =
    'https://apps.apple.com/account/subscriptions';

const String kAppleStandardEulaUrl =
    'https://www.apple.com/legal/internet-services/itunes/dev/stdeula/';

String? buildCheckoutRedirectUrl(String queryFlag) {
  if (!kIsWeb) return null;
  try {
    final base = Uri.base;
    return Uri(
      scheme: base.scheme,
      host: base.host,
      port: base.hasPort ? base.port : null,
      path: '/storage',
      queryParameters: {'checkout': queryFlag},
    ).toString();
  } catch (_) {
    return null;
  }
}

String? buildPortalReturnUrl() {
  if (!kIsWeb) return null;
  try {
    final base = Uri.base;
    return Uri(
      scheme: base.scheme,
      host: base.host,
      port: base.hasPort ? base.port : null,
      path: '/storage',
    ).toString();
  } catch (_) {
    return null;
  }
}

const String kAndroidApplicationId = 'com.svaultai.app';

Uri buildGooglePlaySubscriptionManagementUri({
  String productId = kGooglePlayStorageProductId,
  String packageName = kAndroidApplicationId,
}) {
  return Uri.https(
    'play.google.com',
    '/store/account/subscriptions',
    <String, String>{'sku': productId, 'package': packageName},
  );
}

bool shouldShowStoreConnectionRetry({
  required String? storeState,
  required bool loading,
  required bool connectionInFlight,
  String? connectionError,
}) {
  if (loading || connectionInFlight) return false;
  if ((connectionError ?? '').trim().isNotEmpty) return true;
  return const <String>{
    'unavailable',
    'timed_out',
  }.contains((storeState ?? '').trim().toLowerCase());
}

@immutable
class StoreStorageTierChoice {
  final String productId;
  final String capacityLabel;
  final String localizedPrice;
  final int rank;
  final String periodLabel;

  const StoreStorageTierChoice({
    required this.productId,
    required this.capacityLabel,
    required this.localizedPrice,
    required this.rank,
    this.periodLabel = 'month',
  });
}

@immutable
class AppleStoragePlanConfig {
  final String productId;
  final String capacityLabel;
  final int entitlementBytes;
  final String billingPeriod;

  const AppleStoragePlanConfig({
    required this.productId,
    required this.capacityLabel,
    required this.entitlementBytes,
    required this.billingPeriod,
  });
}

List<AppleStoragePlanConfig> parseAppleStorageCatalog(
    Map<dynamic, dynamic> data) {
  final rawProducts = data['products'];
  final plans = <AppleStoragePlanConfig>[];
  if (rawProducts is List) {
    for (final raw in rawProducts) {
      if (raw is! Map) continue;
      final productId = raw['product_id']?.toString().trim() ?? '';
      final capacity = raw['display_capacity']?.toString().trim() ?? '';
      final bytes = (raw['storage_entitlement_bytes'] as num?)?.toInt() ?? 0;
      final period = raw['billing_period']?.toString().trim() ?? '';
      if (productId.isEmpty ||
          capacity.isEmpty ||
          bytes <= 0 ||
          period.isEmpty) {
        continue;
      }
      plans.add(AppleStoragePlanConfig(
        productId: productId,
        capacityLabel: capacity,
        entitlementBytes: bytes,
        billingPeriod: period,
      ));
    }
  }
  // Compatibility with the already-deployed one-product provider contract.
  // It still supplies a backend-recognized product, period, and entitlement;
  // no client-side tier is invented.
  if (plans.isEmpty) {
    final productId = data['product_id']?.toString().trim() ?? '';
    final bytes = (data['storage_entitlement_bytes'] as num?)?.toInt() ?? 0;
    final period = data['billing_period']?.toString().trim() ?? '';
    if (productId.isNotEmpty && bytes > 0 && period.isNotEmpty) {
      plans.add(AppleStoragePlanConfig(
        productId: productId,
        capacityLabel: formatBytes(bytes),
        entitlementBytes: bytes,
        billingPeriod: period,
      ));
    }
  }
  return List<AppleStoragePlanConfig>.unmodifiable(plans);
}

String? appleStoreKitPeriodLabel(ProductDetails product) {
  if (product is AppStoreProduct2Details) {
    final period = product.sk2Product.subscription?.subscriptionPeriod;
    if (period == null || period.value != 1) return null;
    return switch (period.unit) {
      SK2SubscriptionPeriodUnit.day => 'day',
      SK2SubscriptionPeriodUnit.week => 'week',
      SK2SubscriptionPeriodUnit.month => 'month',
      SK2SubscriptionPeriodUnit.year => 'year',
    };
  }
  if (product is AppStoreProductDetails) {
    final period = product.skProduct.subscriptionPeriod;
    if (period == null || period.numberOfUnits != 1) return null;
    return switch (period.unit) {
      SKSubscriptionPeriodUnit.day => 'day',
      SKSubscriptionPeriodUnit.week => 'week',
      SKSubscriptionPeriodUnit.month => 'month',
      SKSubscriptionPeriodUnit.year => 'year',
    };
  }
  return null;
}

String recurringPeriodAdverb(String periodLabel) => switch (periodLabel) {
      'day' => 'daily',
      'week' => 'weekly',
      'month' => 'monthly',
      'year' => 'yearly',
      _ => 'on its displayed subscription period',
    };

List<StoreStorageTierChoice> selectableGooglePlayStorageTiers(
  List<StoreStorageTierChoice> choices, {
  int? currentTierRank,
  bool hasActiveSubscription = false,
}) {
  if (!hasActiveSubscription) {
    return List<StoreStorageTierChoice>.unmodifiable(choices);
  }
  if (currentTierRank == null) return const <StoreStorageTierChoice>[];
  return List<StoreStorageTierChoice>.unmodifiable(
    choices.where((choice) => choice.rank > currentTierRank),
  );
}

String billingProvider(Map<String, dynamic> data) {
  final authoritative = data['provider']?.toString().trim().toLowerCase();
  if (authoritative != null && authoritative.isNotEmpty) {
    return authoritative == 'stripe_legacy' ? 'web_card' : authoritative;
  }
  final legacy = data['source']?.toString().trim().toLowerCase() ?? 'free';
  return switch (legacy) {
    'stripe' || 'stripe_legacy' => 'web_card',
    'none' || 'safe_default' => 'free',
    _ => legacy,
  };
}

String billingDisplayTier(Map<String, dynamic> data) {
  final explicit = data['display_tier']?.toString().trim();
  if (explicit != null && explicit.isNotEmpty) return explicit;
  final productId = data['product_id']?.toString().toLowerCase() ?? '';
  if (productId.endsWith('1tb') || productId.contains('1tb')) return '1 TB';
  final bytes = (data['storage_bytes'] as num?)?.toInt() ??
      (data['effective_limit_bytes'] as num?)?.toInt() ??
      0;
  if (bytes == 1073741824000) return '1 TB';
  return formatBytes(bytes);
}

bool webCardPurchaseAllowed(Map<String, dynamic> data) {
  final provider = billingProvider(data);
  if ({'google_play', 'apple'}.contains(provider)) return false;
  if (data['conflict_reason_code'] != null ||
      data['migration_status'] == 'pending') {
    return false;
  }
  if (data['web_card_purchase_allowed'] is bool) {
    return data['web_card_purchase_allowed'] == true;
  }
  return true;
}

Uri? providerManageSubscriptionUri(Map<String, dynamic> data) {
  if (!hasActiveSubscription(data)) return null;
  switch (billingProvider(data)) {
    case 'google_play':
      final productId = data['product_id']?.toString().trim() ?? '';
      if (productId.isEmpty) return null;
      return Uri.https('play.google.com', '/store/account/subscriptions', {
        'sku': productId,
        'package': kGooglePlayPackageName,
      });
    case 'apple':
      return Uri.parse(kAppleManageSubscriptionsUrl);
    default:
      return null;
  }
}

String billedThroughLabel(Map<String, dynamic> data) {
  return switch (billingProvider(data)) {
    'google_play' => 'Billed through Google Play',
    'apple' => 'Billed through Apple',
    'web_card' => 'Billed on SVaultAI web',
    _ => '',
  };
}

class StoragePage extends StatefulWidget {
  const StoragePage({super.key});

  @override
  State<StoragePage> createState() => _StoragePageState();
}

class _StoragePageState extends State<StoragePage> {
  late final VaultAIClient _client;
  bool _loading = true;
  bool _busyPurchase = false;
  String? _error;
  Map<String, dynamic>? _data;
  GooglePlayBillingController? _playBilling;
  AppleStoreKitBillingController? _appleBilling;
  List<AppleStoragePlanConfig> _applePlanCatalog =
      const <AppleStoragePlanConfig>[];
  String? _lastPlayBillingState;
  String? _lastAppleBillingState;
  String? _storeConnectionError;
  bool _storeConnectionInFlight = false;

  @override
  void initState() {
    super.initState();
    _client = VaultAIClient(baseUrl: backendBaseUrl);
    _refresh();
  }

  bool get _usesGooglePlayBilling =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  bool get _usesAppleBilling =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;

  @override
  void dispose() {
    _playBilling?.dispose();
    _appleBilling?.dispose();
    super.dispose();
  }

  Future<void> _initializeAppleBilling(
    String authToken, {
    bool retry = false,
  }) async {
    if (!_usesAppleBilling || _storeConnectionInFlight) return;
    if (_appleBilling != null) {
      if (retry) await _appleBilling!.retry();
      return;
    }
    if (mounted) {
      setState(() {
        _storeConnectionInFlight = true;
        _storeConnectionError = null;
      });
    }
    try {
      final providers = await _client
          .getBillingProviders(authToken: authToken)
          .timeout(kStoreConnectionTimeout);
      final apple = providers['apple'];
      if (apple is! Map || apple['configured'] != true) {
        throw StateError('app_store_not_configured');
      }
      final catalog = parseAppleStorageCatalog(apple);
      final appAccountToken = apple['app_account_token']?.toString() ?? '';
      if (catalog.isEmpty || appAccountToken.isEmpty || !mounted) {
        throw StateError('app_store_configuration_incomplete');
      }
      final controller = AppleStoreKitBillingController(
        gateway: FlutterAppleBillingGateway(),
        productIds: catalog.map((plan) => plan.productId).toList(),
        appAccountToken: appAccountToken,
        environment:
            kAppleStoreKitEnvironment == 'sandbox' ? 'sandbox' : 'production',
        verifyPurchase: ({
          required String signedTransaction,
          required String environment,
        }) =>
            _client.verifyAppleTransaction(
          authToken: authToken,
          signedTransaction: signedTransaction,
          environment: environment,
        ),
      );
      controller.addListener(_onAppleBillingChanged);
      setState(() {
        _applePlanCatalog = catalog;
        _appleBilling = controller;
      });
      await controller.initialize();
    } on TimeoutException {
      if (mounted) {
        setState(
          () => _storeConnectionError =
              'The App Store took too long to respond. Tap Retry.',
        );
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _storeConnectionError =
              'The App Store is temporarily unavailable. Tap Retry.',
        );
      }
    } finally {
      if (mounted) setState(() => _storeConnectionInFlight = false);
    }
  }

  Future<void> _chooseAppleStorage(
    List<StoreStorageTierChoice> choices,
  ) async {
    final selectedProductId = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: VaultColors.canvas,
      isScrollControlled: true,
      builder: (_) => AppleStoragePlanPicker(choices: choices),
    );
    if (selectedProductId == null || !mounted) return;
    final controller = _appleBilling;
    if (controller == null ||
        controller.productFor(selectedProductId) == null) {
      return;
    }
    await controller.buy(selectedProductId);
  }

  void _onAppleBillingChanged() {
    final controller = _appleBilling;
    if (!mounted || controller == null) return;
    final state = controller.state;
    setState(() {});
    if (state == 'verified' && _lastAppleBillingState != 'verified') {
      unawaited(_refresh());
    }
    _lastAppleBillingState = state;
  }

  Future<void> _retryStoreBilling() async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    if (_usesAppleBilling) {
      await _initializeAppleBilling(token, retry: true);
    } else if (_usesGooglePlayBilling) {
      final play = _playBilling;
      if (play == null) {
        await _initializeGooglePlayBilling(token);
      } else {
        if (mounted) {
          setState(() {
            _storeConnectionError = null;
            _storeConnectionInFlight = true;
          });
        }
        try {
          await play.initialize(forceRetry: true);
        } finally {
          if (mounted) setState(() => _storeConnectionInFlight = false);
        }
      }
    }
  }

  Future<void> _manageGooglePlaySubscription({String? productId}) async {
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busyPurchase = true);
    try {
      final launched = await launchUrl(
        buildGooglePlaySubscriptionManagementUri(
          productId: productId ?? kGooglePlayStorageProductId,
        ),
        mode: LaunchMode.externalApplication,
      );
      if (!launched) {
        throw StateError('Google Play subscription page did not open.');
      }
    } catch (_) {
      messenger.showSnackBar(
        const SnackBar(
          content: Text('Could not open Google Play subscriptions.'),
        ),
      );
    } finally {
      if (mounted) setState(() => _busyPurchase = false);
    }
  }

  Future<void> _initializeGooglePlayBilling(String authToken) async {
    if (!_usesGooglePlayBilling ||
        _playBilling != null ||
        _storeConnectionInFlight) {
      return;
    }
    if (mounted) {
      setState(() {
        _storeConnectionInFlight = true;
        _storeConnectionError = null;
      });
    }
    try {
      final providers = await _client
          .getBillingProviders(authToken: authToken)
          .timeout(kStoreConnectionTimeout);
      final google = providers['google_play'];
      if (google is! Map) throw StateError('google_play_not_configured');
      final catalog = parseGooglePlayStorageCatalog(google);
      final accountToken = google['account_token']?.toString() ?? '';
      if (accountToken.isEmpty || !mounted) {
        throw StateError('google_play_configuration_incomplete');
      }
      final controller = GooglePlayBillingController(
        gateway: FlutterPlayBillingGateway(),
        catalog: catalog,
        accountToken: accountToken,
        verifyPurchase: (
                {required String productId, required String purchaseToken}) =>
            _client.verifyGooglePlayPurchase(
          authToken: authToken,
          productId: productId,
          purchaseToken: purchaseToken,
        ),
        reconcilePurchases: ({required List<String> purchaseTokens}) =>
            _client.reconcileGooglePlayPurchases(
          authToken: authToken,
          purchaseTokens: purchaseTokens,
        ),
      );
      controller.addListener(_onGooglePlayBillingChanged);
      setState(() => _playBilling = controller);
      await controller.initialize();
      await controller.restore(silent: true);
    } on TimeoutException {
      if (mounted) {
        setState(
          () => _storeConnectionError =
              'Google Play took too long to respond. Tap Retry.',
        );
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _storeConnectionError =
              'Google Play Billing is temporarily unavailable. Tap Retry.',
        );
      }
    } finally {
      if (mounted) setState(() => _storeConnectionInFlight = false);
    }
  }

  Future<void> _buyGooglePlayTier(String targetProductId) async {
    final play = _playBilling;
    final data = _data;
    if (play == null || data == null) return;
    final ownsPlaySubscription =
        hasActiveSubscription(data) && billingSource(data) == 'google_play';
    final currentTier = ownsPlaySubscription
        ? play.tierForQuantity((data['block_count'] as num?)?.toInt() ?? 0)
        : null;
    if (ownsPlaySubscription && currentTier == null) return;
    await play.buy(targetProductId, currentProductId: currentTier?.productId);
  }

  void _onGooglePlayBillingChanged() {
    final controller = _playBilling;
    if (!mounted || controller == null) return;
    final state = controller.state;
    setState(() {});
    if (const {'verified', 'reconciled'}.contains(state) &&
        _lastPlayBillingState != state) {
      unawaited(_refresh());
    }
    _lastPlayBillingState = state;
  }

  Future<void> _runPostCheckoutPoll() async {
    final app = context.read<AppState>();
    if (!mounted) return;
    unawaited(
      showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (_) => const _UpgradeProgressDialog(),
      ),
    );

    final reachedData = await _pollEntitlementUntilPaidSubscriptionActive(
      app: app,
    );

    if (mounted) {
      Navigator.of(context, rootNavigator: true).pop();
    }
    if (!mounted) return;

    if (reachedData != null) {
      final limitBytes =
          (reachedData['effective_limit_bytes'] as num?)?.toInt() ?? 0;
      final newLimitGb = limitBytes ~/ (1024 * 1024 * 1024);
      await showDialog<void>(
        context: context,
        builder: (_) => _UpgradeSuccessDialog(newLimitGb: newLimitGb),
      );
    } else {
      final debugFields = _billingDebugFields(_data ?? const {});
      await showDialog<void>(
        context: context,
        builder: (dialogCtx) => _UpgradeTimeoutDialog(
          debugFields: debugFields,
          onRefresh: () async {
            Navigator.of(dialogCtx).pop();

            await _runPostCheckoutPoll();
          },
        ),
      );
    }
  }

  Future<Map<String, dynamic>?> _pollEntitlementUntilPaidSubscriptionActive({
    required AppState app,
  }) async {
    final token = app.sessionToken;
    if (token == null) return null;
    const maxAttempts = 20;
    const interval = Duration(seconds: 1);
    for (var attempt = 0; attempt < maxAttempts; attempt++) {
      if (attempt > 0) await Future.delayed(interval);
      if (!mounted) return null;
      try {
        final data = await _client.getBillingMe(authToken: token);
        if (!mounted) return null;
        setState(() {
          _data = data;
          _loading = false;
          _error = null;
        });

        app.applyBillingPayload(data);
        final blocks = (data['block_count'] as num?)?.toInt() ?? 0;
        final active = (data['has_active_subscription'] as bool?) ?? false;

        vlog('billing-debug', _billingDebugFields(data, attempt: attempt));
        if (blocks > 0 && active) return data;
      } catch (_) {}
    }
    return null;
  }

  Map<String, Object?> _billingDebugFields(
    Map<String, dynamic> data, {
    int? attempt,
  }) {
    final acctId = (data['account_id'] as String?) ?? '';
    final blocks = (data['block_count'] as num?)?.toInt() ?? 0;
    final active = (data['has_active_subscription'] as bool?) ?? false;
    final limit = (data['effective_limit_bytes'] as num?)?.toInt() ?? 0;
    final lwRaw = data['last_webhook_event'];
    String lastWebhook = 'none';
    if (lwRaw is Map) {
      final type = lwRaw['event_type']?.toString() ?? '';
      final outcome = lwRaw['outcome']?.toString() ?? '';
      final age = lwRaw['age_seconds']?.toString() ?? '';
      final evIdPrefix = lwRaw['event_id_prefix']?.toString() ?? '';
      lastWebhook = '$evIdPrefix/$type/$outcome/${age}s';
    }
    final out = <String, Object?>{
      'account': acctId.length >= 8 ? acctId.substring(0, 8) : acctId,
      'block_count': blocks,
      'active': active,
      'limit': limit,
      'last_webhook': lastWebhook,
    };
    if (attempt != null) out['poll_attempt'] = attempt;
    return out;
  }

  Future<void> _refresh() async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) {
      if (!mounted) return;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        Navigator.of(context).pushReplacementNamed('/auth');
      });
      return;
    }
    try {
      final data = await _client.getBillingMe(authToken: token);
      if (!mounted) return;
      setState(() {
        _data = data;
        _loading = false;
        _error = null;
      });
      unawaited(_initializeGooglePlayBilling(token));
      unawaited(_initializeAppleBilling(token));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load storage: $e';
      });
    }
  }

  Future<void> _onBuyStorage() async {
    final data = _data;
    if (data == null) return;
    final picked = await showModalBottomSheet<int>(
      context: context,
      backgroundColor: VaultColors.canvas,
      isScrollControlled: true,
      builder: (_) => StoragePlanPicker(
        currentBlockCount: (data['block_count'] as num?)?.toInt() ?? 0,
        usedBytes: (data['used_bytes'] as num?)?.toInt() ?? 0,
        blockBytes: (data['block_bytes'] as num?)?.toInt() ?? 53687091200,
        blockPriceCentsUsd:
            (data['block_price_cents_usd'] as num?)?.toInt() ?? 2500,
        selfServiceMaxBlocks:
            (data['self_service_max_blocks'] as num?)?.toInt() ?? 100,
        hasActiveSubscription: hasActiveSubscription(data),
      ),
    );
    if (picked == null) return;

    final currentBlocks = (data['block_count'] as num?)?.toInt() ?? 0;
    if (hasActiveSubscription(data) && picked < currentBlocks) {
      await _showLowerPlanDialog();
      return;
    }

    await _startCheckout(picked);
  }

  Future<void> _showLowerPlanDialog() async {
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (dialogCtx) => _LowerPlanDialog(
        onManageSubscription: () async {
          Navigator.of(dialogCtx).pop();
          await _onManageSubscription();
        },
      ),
    );
  }

  bool _isDowngradeNotSupportedError(Object error) {
    if (error is BillingCheckoutException) {
      return error.code == 'downgrade_not_supported';
    }
    final s = error.toString();
    return s.contains('downgrade_not_supported');
  }

  String _friendlyCheckoutErrorMessage(Object error) {
    if (error is BillingCheckoutException) return error.message;
    return "We couldn't start checkout. Please try again.";
  }

  Future<void> _startCheckout(int blockCount) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) return;
    setState(() => _busyPurchase = true);
    try {
      final result = await _client.createStripeCheckoutSession(
        authToken: token,
        blockCount: blockCount,
        successUrl: buildCheckoutRedirectUrl('success'),
        cancelUrl: buildCheckoutRedirectUrl('cancel'),
      );

      final action = (result['action'] as String?) ?? 'open_checkout';

      if (action == 'updated_existing') {
        final newBlocks = (result['new_blocks'] as num?)?.toInt() ?? blockCount;
        final targetGb = newBlocks * 50;

        if (!mounted) return;
        unawaited(
          showDialog<void>(
            context: context,
            barrierDismissible: false,
            builder: (_) => const _UpgradeProgressDialog(),
          ),
        );

        final reached = await _pollEntitlementForBlocks(
          targetBlocks: newBlocks,
          app: app,
        );

        if (mounted) {
          Navigator.of(context, rootNavigator: true).pop();
        }
        if (!mounted) return;

        await showDialog<void>(
          context: context,
          builder: (dialogCtx) => reached
              ? _UpgradeSuccessDialog(newLimitGb: targetGb)
              : _UpgradeTimeoutDialog(
                  debugFields: _billingDebugFields(_data ?? const {}),
                  onRefresh: () async {
                    Navigator.of(dialogCtx).pop();
                    await _refresh();
                  },
                ),
        );
        return;
      }

      final url = (result['checkout_url'] as String?) ?? '';
      if (url.isEmpty) {
        throw Exception('Checkout URL was empty.');
      }

      final launched = await launchUrl(
        Uri.parse(url),
        mode: kIsWeb
            ? LaunchMode.platformDefault
            : LaunchMode.externalApplication,
        webOnlyWindowName: kIsWeb ? '_self' : null,
      );
      if (!launched) {
        throw Exception('Could not open the Stripe checkout page.');
      }
    } catch (e) {
      if (!mounted) return;

      if (_isDowngradeNotSupportedError(e)) {
        await _showLowerPlanDialog();
      } else {
        await showDialog<void>(
          context: context,
          builder: (_) =>
              _UpgradeErrorDialog(message: _friendlyCheckoutErrorMessage(e)),
        );
      }
    } finally {
      if (mounted) setState(() => _busyPurchase = false);
    }
  }

  Future<bool> _pollEntitlementForBlocks({
    required int targetBlocks,
    required AppState app,
  }) async {
    final token = app.sessionToken;
    if (token == null) return false;
    const maxAttempts = 10;
    const interval = Duration(seconds: 1);

    for (var attempt = 0; attempt < maxAttempts; attempt++) {
      if (attempt > 0) await Future.delayed(interval);
      if (!mounted) return false;
      try {
        final data = await _client.getBillingMe(authToken: token);
        if (!mounted) return false;
        setState(() {
          _data = data;
          _loading = false;
          _error = null;
        });

        app.applyBillingPayload(data);
        final blocks = (data['block_count'] as num?)?.toInt() ?? 0;
        if (blocks >= targetBlocks) return true;
      } catch (_) {}
    }
    return false;
  }

  Future<void> _onManageSubscription() async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busyPurchase = true);
    try {
      final result = await _client.createStripePortalSession(
        authToken: token,
        returnUrl: buildPortalReturnUrl(),
      );
      final url = (result['portal_url'] as String?) ?? '';
      if (url.isEmpty) {
        throw Exception('Portal URL was empty.');
      }
      final launched = await launchUrl(
        Uri.parse(url),
        mode: LaunchMode.externalApplication,
      );
      if (!launched) {
        throw Exception('Could not open the subscription portal.');
      }
    } catch (e) {
      messenger.showSnackBar(
        SnackBar(content: Text('Could not open portal: $e')),
      );
    } finally {
      if (mounted) setState(() => _busyPurchase = false);
    }
  }

  Future<void> _onManageProviderSubscription(Map<String, dynamic> data) async {
    final uri = providerManageSubscriptionUri(data);
    if (uri == null) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busyPurchase = true);
    try {
      final launched = await launchUrl(
        uri,
        mode: LaunchMode.externalApplication,
      );
      if (!launched) throw StateError('subscription_management_unavailable');
    } catch (_) {
      messenger.showSnackBar(
        const SnackBar(
          content: Text('Could not open subscription management.'),
        ),
      );
    } finally {
      if (mounted) setState(() => _busyPurchase = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: VaultColors.canvas,
      appBar: AppBar(
        backgroundColor: VaultColors.canvas,
        title: Text(
          AppLocalizations.of(context).storagePageTitle,
          style: VaultText.title,
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: VaultColors.textSecondary),
            tooltip: AppLocalizations.of(context).commonRefresh,
            onPressed: _loading ? null : _refresh,
          ),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: _buildBody(),
        ),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Padding(
        padding: EdgeInsets.all(VaultSpacing.xl2),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_error != null) {
      return Padding(
        padding: const EdgeInsets.all(VaultSpacing.xl2),
        child: _ErrorCard(message: _error!, onRetry: _refresh),
      );
    }
    final data = _data;
    if (data == null) {
      return Padding(
        padding: const EdgeInsets.all(VaultSpacing.xl2),
        child: Center(
          child: Text(
            AppLocalizations.of(context).storageNoDataAvailable,
            style: VaultText.body,
          ),
        ),
      );
    }
    final play = _playBilling;
    final apple = _appleBilling;
    final activeSubscription = hasActiveSubscription(data);
    final activeProvider = billingProviderLabel(data);
    final provider = billingProvider(data);
    final providerManageUri = providerManageSubscriptionUri(data);
    final playOwnsSubscription =
        activeSubscription && billingSource(data) == 'google_play';
    final appleOwnsSubscription =
        activeSubscription && billingSource(data) == 'apple';
    final currentPlayTier = playOwnsSubscription
        ? play?.tierForQuantity((data['block_count'] as num?)?.toInt() ?? 0)
        : null;
    final playCatalogReady = play?.catalogReady ?? false;
    final showPlayOperationalMessage = const <String>{
      'launching',
      'pending',
      'verifying',
      'canceled',
      'error',
      'verification_failed',
      'ownership_conflict',
      'downgrade_not_supported',
    }.contains(play?.state);
    final playMessage = playOwnsSubscription
        ? (currentPlayTier == null
            ? 'The active Google Play storage tier could not be matched. '
                'Use Restore purchases / Refresh.'
            : (!playCatalogReady
                ? (_storeConnectionError ?? play?.message)
                : (showPlayOperationalMessage ? play?.message : null)))
        : activeSubscription
            ? 'Your storage entitlement is active through $activeProvider. '
                'It is not a Google Play subscription.'
            : (_storeConnectionError ??
                play?.message ??
                (play?.state == 'ready' ? null : 'Connecting to Google Play…'));
    final appleMessage = appleOwnsSubscription
        ? 'Your App Store storage subscription is active. Billing and '
            'cancellation are managed by Apple.'
        : activeSubscription
            ? 'Your storage entitlement is active through $activeProvider. '
                'It is not an App Store subscription.'
            : (_storeConnectionError ??
                apple?.message ??
                (apple?.state == 'ready'
                    ? null
                    : 'Connecting to the App Store…'));
    final storeCanBuy = _usesGooglePlayBilling
        ? (play?.canBuy ?? false)
        : (_usesAppleBilling && (apple?.canBuy ?? false));
    final allPlayTierChoices = <StoreStorageTierChoice>[];
    if (_usesGooglePlayBilling && playCatalogReady) {
      for (final tier in play!.catalog) {
        final product = play.productFor(tier.productId);
        if (product == null) continue;
        allPlayTierChoices.add(
          StoreStorageTierChoice(
            productId: tier.productId,
            capacityLabel: tier.capacityLabel,
            localizedPrice: product.price,
            rank: tier.rank,
          ),
        );
      }
    }
    final playTierChoices = selectableGooglePlayStorageTiers(
      allPlayTierChoices,
      currentTierRank: currentPlayTier?.rank,
      hasActiveSubscription: playOwnsSubscription,
    );
    final appleTierChoices = <StoreStorageTierChoice>[];
    // A canceled StoreKit sheet changes the controller's transient state to
    // `canceled`, but it does not invalidate the ProductDetails catalog.
    // `canBuy` is the authoritative readiness gate: it requires StoreKit to
    // be available and at least one returned product to remain cached.
    if (_usesAppleBilling && apple?.canBuy == true) {
      for (var index = 0; index < _applePlanCatalog.length; index++) {
        final plan = _applePlanCatalog[index];
        final product = apple!.productFor(plan.productId);
        if (product == null) continue;
        final periodLabel = appleStoreKitPeriodLabel(product);
        // The backend mapping and StoreKit must independently agree that the
        // product is monthly before it can be shown or purchased.
        if (plan.billingPeriod != 'P1M' || periodLabel != 'month') continue;
        appleTierChoices.add(StoreStorageTierChoice(
          productId: plan.productId,
          capacityLabel: plan.capacityLabel,
          localizedPrice: product.price,
          rank: index + 1,
          periodLabel: periodLabel!,
        ));
      }
    }
    final storeNeedsRetry = _usesGooglePlayBilling
        ? shouldShowStoreConnectionRetry(
            storeState: play?.state,
            loading: play?.loading ?? false,
            connectionInFlight: _storeConnectionInFlight,
            connectionError: _storeConnectionError,
          )
        : (_usesAppleBilling &&
            shouldShowStoreConnectionRetry(
              storeState: apple?.state,
              loading: apple?.loading ?? false,
              connectionInFlight: _storeConnectionInFlight,
              connectionError: _storeConnectionError,
            ));
    return StorageBody(
      data: data,
      busy: _busyPurchase ||
          (play?.loading ?? false) ||
          (apple?.loading ?? false) ||
          _storeConnectionInFlight,
      onBuyStorage: (_usesGooglePlayBilling || _usesAppleBilling) &&
              !activeSubscription &&
              storeCanBuy
          ? (_usesAppleBilling && appleTierChoices.isNotEmpty
              ? () => _chooseAppleStorage(appleTierChoices)
              : null)
          : null,
      onManageSubscription: kIsWeb
          ? (providerManageUri != null
              ? () => _onManageProviderSubscription(data)
              : (provider == 'web_card' && activeSubscription
                  ? _onManageSubscription
                  : null))
          : (playOwnsSubscription && currentPlayTier != null
              ? () => _manageGooglePlaySubscription(
                    productId: currentPlayTier.productId,
                  )
              : (appleOwnsSubscription && providerManageUri != null
                  ? () => _onManageProviderSubscription(data)
                  : null)),
      unavailableMessage: kIsWeb
          ? (activeSubscription && {'google_play', 'apple'}.contains(provider)
              ? 'Storage changes are managed through '
                  '${provider == 'google_play' ? 'Google Play' : 'Apple'}. '
                  'Web purchase is disabled while this subscription is active.'
              : 'Storage upgrades are temporarily unavailable while we update '
                  'our payment provider.')
          : (_usesGooglePlayBilling
              ? playMessage
              : (_usesAppleBilling
                  ? appleMessage
                  : 'Storage upgrades are not available on this platform.')),
      storePrice: _usesGooglePlayBilling
          ? (currentPlayTier == null
              ? null
              : play?.productFor(currentPlayTier.productId)?.price)
          : (_usesAppleBilling ? apple?.product?.price : null),
      activeStorePlanLabel: currentPlayTier?.capacityLabel,
      storeName: _usesAppleBilling ? 'the App Store' : 'Google Play',
      showAppleSubscriptionDisclosure: _usesAppleBilling,
      onRestorePurchases: _usesGooglePlayBilling && play?.available == true
          ? play!.restore
          : (_usesAppleBilling && apple?.available == true
              ? apple!.restore
              : null),
      onRetryStore: storeNeedsRetry ? _retryStoreBilling : null,
      purchasablePlanLabel: _usesAppleBilling ? 'storage' : null,
      showStorePlanSummary: !kIsWeb && playOwnsSubscription,
      storeTierChoices: playTierChoices,
      onSelectStoreTier: _usesGooglePlayBilling &&
              storeCanBuy &&
              (!playOwnsSubscription || currentPlayTier != null)
          ? _buyGooglePlayTier
          : null,
      // Only ProductDetails-backed native tiers are rendered above. Stripe-era
      // examples are not store products and must not be advertised.
      showPricingExamples: false,
    );
  }
}

bool nearsLimitWarning(num percentUsed) =>
    percentUsed >= 80.0 && percentUsed < 100.0;

bool limitReachedWarning(num percentUsed) => percentUsed >= 100.0;

bool isOnFreeTierOnly(Map<String, dynamic> data) {
  final blockCount = (data['block_count'] as num?) ?? 0;
  final grant = (data['storage_bytes_grant'] as num?) ?? 0;
  return blockCount.toInt() == 0 && grant.toInt() == 0;
}

bool isGrandfathered(Map<String, dynamic> data) {
  final blockCount = (data['block_count'] as num?) ?? 0;
  final grant = (data['storage_bytes_grant'] as num?) ?? 0;
  return blockCount.toInt() == 0 && grant.toInt() > 0;
}

String formatBytes(num bytes) {
  if (bytes < 0) return '0 B';
  if (bytes.toInt() == 1073741824000) return '1 TB';
  const kib = 1024.0;
  const mib = 1024.0 * 1024.0;
  const gib = 1024.0 * 1024.0 * 1024.0;
  const tib = 1024.0 * 1024.0 * 1024.0 * 1024.0;
  if (bytes >= tib) {
    final v = bytes / tib;
    return '${_trimZeros(v.toStringAsFixed(2))} TB';
  }
  if (bytes >= gib) {
    final v = bytes / gib;
    return '${_trimZeros(v.toStringAsFixed(2))} GB';
  }
  if (bytes >= mib) {
    final v = bytes / mib;
    return '${_trimZeros(v.toStringAsFixed(1))} MB';
  }
  if (bytes >= kib) {
    final v = bytes / kib;
    return '${_trimZeros(v.toStringAsFixed(1))} KB';
  }
  return '${bytes.toInt()} B';
}

String _trimZeros(String s) {
  if (!s.contains('.')) return s;
  var out = s;
  while (out.endsWith('0')) {
    out = out.substring(0, out.length - 1);
  }
  if (out.endsWith('.')) {
    out = out.substring(0, out.length - 1);
  }
  return out;
}

String formatCapacityFromBlocks(int blocks, {int gbPerBlock = 50}) {
  if (blocks <= 0) return '0 GB';
  final gigabytes = blocks * gbPerBlock;
  if (gigabytes >= 1000) {
    final tb = gigabytes / 1000.0;
    return '${_trimZeros(tb.toStringAsFixed(2))} TB';
  }
  return '$gigabytes GB';
}

bool hasActiveSubscription(Map<String, dynamic> data) {
  final flag = data['has_active_subscription'];
  if (flag is bool) return flag;

  final provider = billingProvider(data);
  final status = data['subscription_status']?.toString() ??
      data['status']?.toString() ??
      'none';
  if (!{'google_play', 'apple', 'web_card'}.contains(provider)) return false;
  return const {'active', 'in_grace', 'canceled_pending'}.contains(status);
}

String billingSource(Map<String, dynamic> data) => billingProvider(data);

String billingProviderLabel(Map<String, dynamic> data) {
  return switch (billingSource(data)) {
    'apple' => 'the App Store',
    'google_play' => 'Google Play',
    'web_card' => 'the web billing provider',
    'stripe' || 'stripe_legacy' => 'the legacy web billing provider',
    _ => 'another verified provider',
  };
}

bool hasManageableStripeSubscription(Map<String, dynamic> data) {
  final source = (data['source'] as String?) ?? 'none';
  final status = (data['status'] as String?) ?? 'none';
  if (source != 'stripe') return false;

  return status != 'none';
}

const String kStorageInGraceBannerMessage =
    'Your last payment did not go through. Manage subscription to '
    'update payment before the grace period ends.';
const String kStorageCanceledPendingBannerMessage =
    'Your storage plan is scheduled to cancel at the end of this '
    'billing period. Storage will drop back to the included tier.';
const String kStorageOverQuotaGraceBannerMessage =
    'Your subscription ended and your vault is over the included '
    'storage limit. Upgrade storage before the grace period ends.';

bool isSubscriptionInGrace(Map<String, dynamic> data) {
  final status = (data['status'] as String?) ?? 'none';
  return status == 'in_grace';
}

bool isSubscriptionCanceledPending(Map<String, dynamic> data) {
  final status = (data['status'] as String?) ?? 'none';
  final cancelAtEnd = data['cancel_at_period_end'] == true;
  return status == 'canceled_pending' || cancelAtEnd;
}

bool isSubscriptionOverQuotaGrace(Map<String, dynamic> data) {
  final status = (data['status'] as String?) ?? 'none';
  return status == 'over_quota_grace';
}

class StorageBody extends StatelessWidget {
  final Map<String, dynamic> data;
  final bool busy;
  final VoidCallback? onBuyStorage;
  final VoidCallback? onManageSubscription;
  final String? unavailableMessage;
  final String? storePrice;
  final String? activeStorePlanLabel;
  final String storeName;
  final bool showAppleSubscriptionDisclosure;
  final VoidCallback? onRestorePurchases;
  final VoidCallback? onRetryStore;
  final String? purchasablePlanLabel;
  final bool showStorePlanSummary;
  final bool showPricingExamples;
  final List<StoreStorageTierChoice> storeTierChoices;
  final ValueChanged<String>? onSelectStoreTier;

  const StorageBody({
    super.key,
    required this.data,
    this.busy = false,
    this.onBuyStorage,
    this.onManageSubscription,
    this.unavailableMessage,
    this.storePrice,
    this.activeStorePlanLabel,
    this.storeName = 'Google Play',
    this.showAppleSubscriptionDisclosure = false,
    this.onRestorePurchases,
    this.onRetryStore,
    this.purchasablePlanLabel,
    this.showStorePlanSummary = false,
    this.showPricingExamples = false,
    this.storeTierChoices = const <StoreStorageTierChoice>[],
    this.onSelectStoreTier,
  });

  @override
  Widget build(BuildContext context) {
    final used = (data['used_bytes'] as num?)?.toInt() ?? 0;

    final limit = (data['effective_limit_bytes'] as num?)?.toInt() ??
        kVaultStorageLimitBytes;
    final percent = (data['percent_used'] as num?)?.toDouble() ?? 0.0;
    final accountType = (data['account_type'] as String?) ?? 'individual';
    final includedBytes =
        (data['included_bytes'] as num?)?.toInt() ?? kVaultStorageLimitBytes;

    final storeBilled = hasActiveSubscription(data) &&
        {'google_play', 'apple'}.contains(billingProvider(data));
    final canBuy =
        onBuyStorage != null && webCardPurchaseAllowed(data) && !busy;
    final canManage =
        onManageSubscription != null && hasActiveSubscription(data) && !busy;
    final showPurchaseActions = !storeBilled &&
        webCardPurchaseAllowed(data) &&
        (onBuyStorage != null || unavailableMessage == null);

    return ListView(
      padding: const EdgeInsets.symmetric(
        horizontal: VaultSpacing.lg,
        vertical: VaultSpacing.xl,
      ),
      children: [
        _UsageCard(used: used, limit: limit, percentUsed: percent),
        const SizedBox(height: VaultSpacing.lg),
        if (!showStorePlanSummary || !hasActiveSubscription(data)) ...[
          _CurrentBillingPlanCard(
            data: data,
            busy: busy,
            onManage: canManage ? onManageSubscription : null,
          ),
          const SizedBox(height: VaultSpacing.lg),
        ],
        if (limitReachedWarning(percent))
          const _WarningBanner(
            severity: 'critical',
            icon: Icons.error_outline,
            message: 'Storage limit reached. Upgrade storage to continue '
                'uploading files.',
          )
        else if (nearsLimitWarning(percent))
          const _WarningBanner(
            severity: 'warning',
            icon: Icons.warning_amber_rounded,
            message: 'Your vault is nearing its storage limit.',
          ),
        if (nearsLimitWarning(percent) || limitReachedWarning(percent))
          const SizedBox(height: VaultSpacing.lg),
        if (isSubscriptionInGrace(data)) ...[
          const _WarningBanner(
            key: Key('storage_in_grace_banner'),
            severity: 'critical',
            icon: Icons.credit_card_off_rounded,
            message: kStorageInGraceBannerMessage,
          ),
          const SizedBox(height: VaultSpacing.lg),
        ],
        if (isSubscriptionOverQuotaGrace(data)) ...[
          const _WarningBanner(
            key: Key('storage_over_quota_grace_banner'),
            severity: 'critical',
            icon: Icons.warning_amber_rounded,
            message: kStorageOverQuotaGraceBannerMessage,
          ),
          const SizedBox(height: VaultSpacing.lg),
        ],
        if (isSubscriptionCanceledPending(data) &&
            !isSubscriptionInGrace(data)) ...[
          const _WarningBanner(
            key: Key('storage_canceled_pending_banner'),
            severity: 'warning',
            icon: Icons.event_busy_rounded,
            message: kStorageCanceledPendingBannerMessage,
          ),
          const SizedBox(height: VaultSpacing.lg),
        ],
        if (isOnFreeTierOnly(data)) ...[
          _FreeTierCard(includedBytes: includedBytes),
          const SizedBox(height: VaultSpacing.lg),
        ],
        if (showStorePlanSummary && hasActiveSubscription(data))
          _ActiveStoreSubscriptionCard(
            capacityLabel: activeStorePlanLabel ?? formatBytes(limit),
            localizedPrice: storePrice,
            storeName: storeName,
            busy: busy,
            onManage: onManageSubscription,
          )
        else if (storeTierChoices.isEmpty && showPurchaseActions)
          _PurchaseActionRow(
            canBuy: canBuy,
            canManage: canManage,
            hasActiveSub: hasActiveSubscription(data),
            onBuy: onBuyStorage,
            onManage: onManageSubscription,
            buyPlanLabel: purchasablePlanLabel,
          ),
        if (storeTierChoices.isNotEmpty) ...[
          const SizedBox(height: VaultSpacing.lg),
          _StoreTierSelector(
            choices: storeTierChoices,
            upgrading: hasActiveSubscription(data),
            busy: busy,
            onSelect: onSelectStoreTier,
          ),
        ],
        if (storePrice != null &&
            !showStorePlanSummary &&
            storeTierChoices.isEmpty) ...[
          const SizedBox(height: VaultSpacing.md),
          _BillingAvailabilityCard(
            message: showAppleSubscriptionDisclosure
                ? 'SVaultAI 50 GB Storage — 1 month, $storePrice through '
                    '$storeName. Provides 50 GB total storage and renews '
                    'automatically each month until canceled.'
                : '$storePrice per month through $storeName. Provides the '
                    'selected total storage limit and renews automatically '
                    'until canceled.',
            icon: Icons.shop_2_outlined,
          ),
        ],
        if (showAppleSubscriptionDisclosure) ...[
          const SizedBox(height: VaultSpacing.sm),
          const _AppleSubscriptionLegalLinks(),
        ],
        if (unavailableMessage != null) ...[
          const SizedBox(height: VaultSpacing.md),
          _BillingAvailabilityCard(message: unavailableMessage!),
        ],
        if (onRestorePurchases != null || onRetryStore != null) ...[
          const SizedBox(height: VaultSpacing.md),
          _StoreRecoveryActions(
            busy: busy,
            onRestorePurchases: onRestorePurchases,
            onRetryStore: onRetryStore,
          ),
        ],
        const SizedBox(height: VaultSpacing.lg),
        _AccountFactsCard(accountType: accountType),
        const SizedBox(height: VaultSpacing.lg),
        if (isGrandfathered(data))
          _GrandfatherCard(
            grantBytes: (data['storage_bytes_grant'] as num?)?.toInt() ?? 0,
            includedBytes: includedBytes,
          ),
        if (isGrandfathered(data)) const SizedBox(height: VaultSpacing.lg),
        if (showPricingExamples) const _PricingExamplesCard(),
        const SizedBox(height: VaultSpacing.xl),
      ],
    );
  }
}

class _AppleSubscriptionLegalLinks extends StatelessWidget {
  const _AppleSubscriptionLegalLinks();

  Future<void> _open(String url) async {
    await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: VaultSpacing.sm,
      runSpacing: VaultSpacing.sm,
      children: [
        TextButton(
          onPressed: () => _open(kVaultAiPrivacyUrl),
          child: const Text('Privacy Policy'),
        ),
        TextButton(
          onPressed: () => _open(kAppleStandardEulaUrl),
          child: const Text('Terms of Use (EULA)'),
        ),
      ],
    );
  }
}

class _CurrentBillingPlanCard extends StatelessWidget {
  final Map<String, dynamic> data;
  final bool busy;
  final VoidCallback? onManage;

  const _CurrentBillingPlanCard({
    required this.data,
    required this.busy,
    this.onManage,
  });

  @override
  Widget build(BuildContext context) {
    final provider = billingProvider(data);
    final active = hasActiveSubscription(data);
    final conflict = data['conflict_reason_code'] != null ||
        data['ownership_status'] == 'conflict';
    final tier = billingDisplayTier(data);
    final freeLabel = provider == 'free' && !active;
    final billedThrough = billedThroughLabel(data);

    return Container(
      key: const Key('storage_current_billing_plan'),
      width: double.infinity,
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.surface,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Current plan', style: VaultText.subtitle),
          const SizedBox(height: VaultSpacing.sm),
          Text(
            freeLabel ? 'Free — 1 GB' : tier,
            key: const Key('storage_current_plan_tier'),
            style: VaultText.headline,
          ),
          if (conflict) ...[
            const SizedBox(height: VaultSpacing.sm),
            Text(
              'Billing ownership needs review. Your current storage limit '
              'remains available, and new purchases are blocked.',
              key: const Key('storage_billing_owner_conflict'),
              style: VaultText.body.copyWith(color: VaultColors.severityWarn),
            ),
          ] else if (active) ...[
            const SizedBox(height: VaultSpacing.sm),
            const Text(
              'Subscription active',
              key: Key('storage_subscription_active'),
              style: VaultText.body,
            ),
            if (billedThrough.isNotEmpty) ...[
              const SizedBox(height: VaultSpacing.xs),
              Text(
                billedThrough,
                key: const Key('storage_billed_through'),
                style: VaultText.body.copyWith(
                  color: VaultColors.textSecondary,
                ),
              ),
            ],
          ],
          if (onManage != null) ...[
            const SizedBox(height: VaultSpacing.lg),
            OutlinedButton.icon(
              key: const Key('storage_manage_provider_subscription'),
              onPressed: busy ? null : onManage,
              icon: const Icon(Icons.settings_outlined),
              label: Text(
                provider == 'web_card'
                    ? 'Manage billing'
                    : 'Manage subscription',
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _BillingAvailabilityCard extends StatelessWidget {
  final String message;
  final IconData icon;

  const _BillingAvailabilityCard({
    required this.message,
    this.icon = Icons.info_outline,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(VaultSpacing.lg),
      decoration: BoxDecoration(
        color: VaultColors.surface,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Row(
        children: [
          Icon(icon, color: VaultColors.accent),
          const SizedBox(width: VaultSpacing.md),
          Expanded(child: Text(message, style: VaultText.body)),
        ],
      ),
    );
  }
}

class _StoreTierSelector extends StatelessWidget {
  final List<StoreStorageTierChoice> choices;
  final bool upgrading;
  final bool busy;
  final ValueChanged<String>? onSelect;

  const _StoreTierSelector({
    required this.choices,
    required this.upgrading,
    required this.busy,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('storage_real_tier_selector'),
      width: double.infinity,
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.surface,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(color: VaultColors.borderSubtle),
        boxShadow: VaultShadows.e1,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            upgrading ? 'Upgrade storage' : 'Choose storage',
            style: VaultText.titleLg,
          ),
          const SizedBox(height: VaultSpacing.sm),
          Text(
            upgrading
                ? 'Choose a higher total storage limit.'
                : 'Choose your total storage limit.',
            style: VaultText.bodySm.copyWith(color: VaultColors.textSecondary),
          ),
          const SizedBox(height: VaultSpacing.lg),
          for (var index = 0; index < choices.length; index++) ...[
            OutlinedButton(
              key: Key('storage_tier_${choices[index].productId}'),
              onPressed: busy || onSelect == null
                  ? null
                  : () => onSelect!(choices[index].productId),
              style: OutlinedButton.styleFrom(
                foregroundColor: VaultColors.textPrimary,
                padding: const EdgeInsets.symmetric(
                  horizontal: VaultSpacing.lg,
                  vertical: VaultSpacing.lg,
                ),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      choices[index].capacityLabel,
                      style: VaultText.subtitle,
                    ),
                  ),
                  Text(
                    '${choices[index].localizedPrice}/month',
                    style: VaultText.body,
                  ),
                  const SizedBox(width: VaultSpacing.sm),
                  const Icon(Icons.chevron_right),
                ],
              ),
            ),
            if (index != choices.length - 1)
              const SizedBox(height: VaultSpacing.sm),
          ],
        ],
      ),
    );
  }
}

class AppleStoragePlanPicker extends StatefulWidget {
  final List<StoreStorageTierChoice> choices;

  const AppleStoragePlanPicker({super.key, required this.choices});

  @override
  State<AppleStoragePlanPicker> createState() => _AppleStoragePlanPickerState();
}

class _AppleStoragePlanPickerState extends State<AppleStoragePlanPicker> {
  String? _selectedProductId;

  @override
  Widget build(BuildContext context) {
    StoreStorageTierChoice? selected;
    for (final choice in widget.choices) {
      if (choice.productId == _selectedProductId) selected = choice;
    }
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(VaultSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Choose storage', style: VaultText.titleLg),
            const SizedBox(height: VaultSpacing.sm),
            Text(
              'Free storage is 1 GB total. Select an App Store plan to review.',
              style: VaultText.bodySm.copyWith(
                color: VaultColors.textSecondary,
              ),
            ),
            const SizedBox(height: VaultSpacing.lg),
            for (final choice in widget.choices) ...[
              Semantics(
                selected: choice.productId == _selectedProductId,
                button: true,
                child: OutlinedButton(
                  key: Key('apple_storage_plan_${choice.productId}'),
                  onPressed: () =>
                      setState(() => _selectedProductId = choice.productId),
                  style: OutlinedButton.styleFrom(
                    side: BorderSide(
                      color: choice.productId == _selectedProductId
                          ? VaultColors.accentBright
                          : VaultColors.borderSubtle,
                      width: choice.productId == _selectedProductId ? 2 : 1,
                    ),
                    foregroundColor: VaultColors.textPrimary,
                    padding: const EdgeInsets.all(VaultSpacing.lg),
                  ),
                  child: Row(
                    children: [
                      Icon(choice.productId == _selectedProductId
                          ? Icons.radio_button_checked
                          : Icons.radio_button_unchecked),
                      const SizedBox(width: VaultSpacing.md),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(choice.capacityLabel,
                                style: VaultText.subtitle),
                            const SizedBox(height: VaultSpacing.xs),
                            Text(
                              '${choice.localizedPrice} / '
                              '${choice.periodLabel}',
                              style: VaultText.body,
                            ),
                            const SizedBox(height: VaultSpacing.xs),
                            Text(
                              '${choice.capacityLabel} total storage — billed '
                              '${recurringPeriodAdverb(choice.periodLabel)} '
                              'through the App Store.',
                              style: VaultText.bodySm.copyWith(
                                color: VaultColors.textSecondary,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: VaultSpacing.sm),
            ],
            if (selected != null) ...[
              const SizedBox(height: VaultSpacing.sm),
              Text(
                'Selected: ${selected.capacityLabel} total storage at '
                '${selected.localizedPrice} / ${selected.periodLabel}.',
                key: const Key('apple_storage_selected_review'),
                style: VaultText.body,
              ),
            ],
            const SizedBox(height: VaultSpacing.lg),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    key: const Key('apple_storage_cancel'),
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('Cancel'),
                  ),
                ),
                const SizedBox(width: VaultSpacing.md),
                Expanded(
                  child: ElevatedButton(
                    key: const Key('apple_storage_continue'),
                    onPressed: selected == null
                        ? null
                        : () => Navigator.of(context).pop(selected!.productId),
                    child: const Text('Continue / Subscribe'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ActiveStoreSubscriptionCard extends StatelessWidget {
  final String capacityLabel;
  final String? localizedPrice;
  final String storeName;
  final bool busy;
  final VoidCallback? onManage;

  const _ActiveStoreSubscriptionCard({
    required this.capacityLabel,
    required this.localizedPrice,
    required this.storeName,
    required this.busy,
    required this.onManage,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('storage_active_store_plan'),
      width: double.infinity,
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.surface,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(color: VaultColors.borderSubtle),
        boxShadow: VaultShadows.e1,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Current plan', style: VaultText.subtitle),
          const SizedBox(height: VaultSpacing.sm),
          Text(capacityLabel, style: VaultText.headline),
          const SizedBox(height: VaultSpacing.sm),
          Text(
            'Subscription active',
            style: VaultText.body.copyWith(color: VaultColors.accentBright),
          ),
          if (localizedPrice != null) ...[
            const SizedBox(height: VaultSpacing.xs),
            Text('$localizedPrice/month', style: VaultText.body),
          ],
          const SizedBox(height: VaultSpacing.xs),
          Text(
            'Managed by $storeName',
            style: VaultText.bodySm.copyWith(color: VaultColors.textSecondary),
          ),
          if (onManage != null) ...[
            const SizedBox(height: VaultSpacing.lg),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                key: const Key('storage_manage_subscription'),
                onPressed: busy ? null : onManage,
                icon: const Icon(Icons.settings_outlined),
                label: const Text('Manage subscription'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: VaultColors.accent,
                  foregroundColor: VaultColors.textOnAccent,
                  padding: const EdgeInsets.symmetric(
                    vertical: VaultSpacing.lg,
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _StoreRecoveryActions extends StatelessWidget {
  final bool busy;
  final VoidCallback? onRestorePurchases;
  final VoidCallback? onRetryStore;

  const _StoreRecoveryActions({
    required this.busy,
    required this.onRestorePurchases,
    required this.onRetryStore,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Having trouble?',
          style: VaultText.bodySm.copyWith(color: VaultColors.textSecondary),
        ),
        if (onRestorePurchases != null)
          TextButton.icon(
            key: const Key('storage_restore_purchases'),
            onPressed: busy ? null : onRestorePurchases,
            icon: const Icon(Icons.restore),
            label: const Text('Restore purchases / Refresh'),
          ),
        if (onRetryStore != null)
          OutlinedButton.icon(
            key: const Key('storage_store_retry'),
            onPressed: busy ? null : onRetryStore,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry store connection'),
          ),
      ],
    );
  }
}

class _PurchaseActionRow extends StatelessWidget {
  final bool canBuy;
  final bool canManage;
  final bool hasActiveSub;
  final VoidCallback? onBuy;
  final VoidCallback? onManage;
  final String? buyPlanLabel;

  const _PurchaseActionRow({
    required this.canBuy,
    required this.canManage,
    required this.hasActiveSub,
    required this.onBuy,
    required this.onManage,
    required this.buyPlanLabel,
  });

  @override
  Widget build(BuildContext context) {
    final primaryLabel = hasActiveSub
        ? 'Upgrade storage'
        : (buyPlanLabel == 'storage'
            ? 'Choose storage'
            : (buyPlanLabel == null ? 'Buy storage' : 'Buy $buyPlanLabel'));
    final primaryIcon = hasActiveSub ? Icons.upgrade : Icons.add;
    return Row(
      children: [
        Expanded(
          child: ElevatedButton.icon(
            onPressed: canBuy ? onBuy : null,
            icon: Icon(primaryIcon),
            label: Text(primaryLabel),
            style: ElevatedButton.styleFrom(
              backgroundColor: VaultColors.accent,
              foregroundColor: VaultColors.textOnAccent,
              padding: const EdgeInsets.symmetric(vertical: VaultSpacing.lg),
            ),
          ),
        ),
        if (canManage) const SizedBox(width: VaultSpacing.md),
        if (canManage)
          Expanded(
            child: OutlinedButton.icon(
              onPressed: onManage,
              icon: const Icon(Icons.settings_outlined),
              label: Text(
                AppLocalizations.of(context).settingsManageSubscription,
              ),
              style: OutlinedButton.styleFrom(
                foregroundColor: VaultColors.textPrimary,
                padding: const EdgeInsets.symmetric(vertical: VaultSpacing.lg),
              ),
            ),
          ),
      ],
    );
  }
}

class _UsageCard extends StatelessWidget {
  final int used;
  final int limit;
  final double percentUsed;

  const _UsageCard({
    required this.used,
    required this.limit,
    required this.percentUsed,
  });

  @override
  Widget build(BuildContext context) {
    final progress = (percentUsed / 100.0).clamp(0.0, 1.0);

    final barColor = limitReachedWarning(percentUsed)
        ? VaultColors.severityCrit
        : nearsLimitWarning(percentUsed)
            ? VaultColors.severityWarn
            : VaultColors.accent;

    return Container(
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.surface,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(color: VaultColors.borderSubtle),
        boxShadow: VaultShadows.e1,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).storageUsageHeading,
            style: VaultText.titleLg,
          ),
          const SizedBox(height: VaultSpacing.md),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                '${formatBytes(used)} / ${formatBytes(limit)}',
                style: VaultText.headline,
              ),
              const SizedBox(width: VaultSpacing.sm),
              Text(
                '(${percentUsed.toStringAsFixed(1)}% used)',
                style: VaultText.body.copyWith(
                  color: VaultColors.textSecondary,
                ),
              ),
            ],
          ),
          const SizedBox(height: VaultSpacing.lg),
          ClipRRect(
            borderRadius: BorderRadius.circular(VaultRadius.pill),
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 10,
              backgroundColor: VaultColors.surfaceMuted,
              valueColor: AlwaysStoppedAnimation<Color>(barColor),
            ),
          ),
          const SizedBox(height: VaultSpacing.sm),
          Row(
            children: [
              Text(
                'Used: ${formatBytes(used)}',
                style: VaultText.bodySm.copyWith(
                  color: VaultColors.textSecondary,
                ),
              ),
              const Spacer(),
              Text(
                'Limit: ${formatBytes(limit)}',
                style: VaultText.bodySm.copyWith(
                  color: VaultColors.textSecondary,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _WarningBanner extends StatelessWidget {
  final String severity;
  final IconData icon;
  final String message;
  const _WarningBanner({
    super.key,
    required this.severity,
    required this.icon,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    final color = VaultColors.forSeverity(severity);
    final soft = VaultColors.forSeveritySoft(severity);
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      decoration: BoxDecoration(
        color: soft,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color),
          const SizedBox(width: VaultSpacing.md),
          Expanded(child: Text(message, style: VaultText.body)),
        ],
      ),
    );
  }
}

class _AccountFactsCard extends StatelessWidget {
  final String accountType;

  const _AccountFactsCard({required this.accountType});

  @override
  Widget build(BuildContext context) {
    final prettyType =
        accountType == 'organization' ? 'Organization' : 'Individual';
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.surface,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).storageAccountHeading,
            style: VaultText.subtitle,
          ),
          const SizedBox(height: VaultSpacing.md),
          _kvRow('Account type', prettyType),
        ],
      ),
    );
  }

  Widget _kvRow(String k, String v) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          k,
          style: VaultText.body.copyWith(color: VaultColors.textSecondary),
        ),
        Text(v, style: VaultText.body),
      ],
    );
  }
}

class _FreeTierCard extends StatelessWidget {
  final int includedBytes;
  const _FreeTierCard({required this.includedBytes});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.surface,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.card_giftcard_outlined,
                color: VaultColors.accent,
              ),
              const SizedBox(width: VaultSpacing.sm),
              Text('Free plan', style: VaultText.title),
            ],
          ),
          const SizedBox(height: VaultSpacing.sm),
          Text(
            '${formatBytes(includedBytes)} included',
            style: VaultText.body.copyWith(color: VaultColors.textSecondary),
          ),
          const SizedBox(height: VaultSpacing.lg),
          Text(
            AppLocalizations.of(context).storageNeedMoreSpace,
            style: VaultText.subtitle,
          ),
          const SizedBox(height: VaultSpacing.sm),
          const Text(
            'Paid storage options are shown only when they are available '
            'from your device\'s store.',
            style: VaultText.body,
          ),
        ],
      ),
    );
  }
}

class _GrandfatherCard extends StatelessWidget {
  final int grantBytes;
  final int includedBytes;
  const _GrandfatherCard({
    required this.grantBytes,
    required this.includedBytes,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.severityInfoSoft,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(
          color: VaultColors.severityInfo.withValues(alpha: 0.4),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.history_toggle_off,
                color: VaultColors.severityInfo,
              ),
              const SizedBox(width: VaultSpacing.sm),
              Text(
                AppLocalizations.of(context).storageGrandfathered,
                style: VaultText.subtitle,
              ),
            ],
          ),
          const SizedBox(height: VaultSpacing.sm),
          Text(
            'You\'re using ${formatBytes(grantBytes + includedBytes)} '
            'while the new billing rolls out. Subscribe or trim to '
            '${formatBytes(includedBytes)} before this grant ends; we\'ll '
            'remind you well in advance and we will never delete your data.',
            style: VaultText.body,
          ),
        ],
      ),
    );
  }
}

class _PricingExamplesCard extends StatelessWidget {
  const _PricingExamplesCard();

  static const _examples = [
    ('50 GB', r'$25/month'),
    ('100 GB', r'$50/month'),
    ('150 GB', r'$75/month'),
    ('500 GB', r'$250/month'),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.surface,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).storageAdditionalPricing,
            style: VaultText.subtitle,
          ),
          const SizedBox(height: VaultSpacing.sm),
          Text(
            'Choose how much storage you want to add.',
            style: VaultText.bodySm.copyWith(color: VaultColors.textSecondary),
          ),
          const SizedBox(height: VaultSpacing.md),
          ..._examples.map(
            (e) => Padding(
              padding: const EdgeInsets.symmetric(vertical: VaultSpacing.xs),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(e.$1, style: VaultText.body),
                  Text(
                    e.$2,
                    style: VaultText.mono.copyWith(
                      color: VaultColors.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

const List<int> kSelfServiceSkuBlockLadder = [1, 2, 3, 4, 5, 10, 20, 40, 100];

class StoragePlanPicker extends StatelessWidget {
  final int currentBlockCount;
  final int usedBytes;
  final int blockBytes;
  final int blockPriceCentsUsd;
  final int selfServiceMaxBlocks;

  final bool hasActiveSubscription;

  const StoragePlanPicker({
    super.key,
    required this.currentBlockCount,
    required this.usedBytes,
    required this.blockBytes,
    required this.blockPriceCentsUsd,
    required this.selfServiceMaxBlocks,
    this.hasActiveSubscription = false,
  });

  String _priceLabel(int blocks) {
    final cents = blocks * blockPriceCentsUsd;
    final dollars = cents ~/ 100;
    return '\$$dollars/month';
  }

  String _capacityLabel(int blocks) => formatCapacityFromBlocks(
        blocks,
        gbPerBlock: blockBytes ~/ (1024 * 1024 * 1024),
      );

  String _newLimitLabel(int blocks) {
    final totalBytes = blocks * blockBytes;
    return formatBytes(totalBytes);
  }

  @override
  Widget build(BuildContext context) {
    final ladder = kSelfServiceSkuBlockLadder
        .where((b) => b <= selfServiceMaxBlocks)
        .toList();

    final title =
        hasActiveSubscription ? 'Upgrade Storage' : 'Buy More Storage';
    final intro = hasActiveSubscription
        ? 'Pick a higher tier to bump your existing subscription. You '
            'will not be sent to Stripe Checkout — the change happens in '
            'place and the prorated upgrade charge runs immediately.'
        : 'Each block adds 50 GB to your account for \$25/month. '
            'Checkout opens Stripe in a new tab.';
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          VaultSpacing.lg,
          VaultSpacing.lg,
          VaultSpacing.lg,
          VaultSpacing.xl,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(title, style: VaultText.titleLg),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
            const SizedBox(height: VaultSpacing.sm),
            Text(intro, style: VaultText.body),
            if (hasActiveSubscription) ...[
              const SizedBox(height: VaultSpacing.sm),
              Text(
                'Current: ${_capacityLabel(currentBlockCount)} / '
                '${_priceLabel(currentBlockCount)}',
                style: VaultText.body.copyWith(
                  color: VaultColors.textSecondary,
                ),
              ),
            ],
            const SizedBox(height: VaultSpacing.lg),
            Flexible(
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: ladder.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: VaultSpacing.sm),
                itemBuilder: (_, i) {
                  final blocks = ladder[i];
                  final isCurrent = blocks == currentBlockCount;
                  final isUpgradeTile = hasActiveSubscription &&
                      !isCurrent &&
                      blocks > currentBlockCount;

                  final isLowerTile = hasActiveSubscription &&
                      !isCurrent &&
                      blocks < currentBlockCount;
                  final addedBlocks = blocks - currentBlockCount;
                  return _PlanTile(
                    additionalLabel: _capacityLabel(blocks),
                    monthlyLabel: _priceLabel(blocks),
                    newLimitLabel: _newLimitLabel(blocks),
                    addedCapacityLabel:
                        isUpgradeTile ? _capacityLabel(addedBlocks) : null,
                    addedMonthlyLabel:
                        isUpgradeTile ? _priceLabel(addedBlocks) : null,
                    showProrationNote: isUpgradeTile,
                    isCurrent: isCurrent,
                    isLowerThanCurrent: isLowerTile,
                    onTap: isCurrent
                        ? null
                        : () => Navigator.of(context).pop(blocks),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PlanTile extends StatelessWidget {
  final String additionalLabel;
  final String monthlyLabel;
  final String newLimitLabel;

  final String? addedCapacityLabel;
  final String? addedMonthlyLabel;
  final bool showProrationNote;
  final bool isCurrent;

  final bool isLowerThanCurrent;
  final VoidCallback? onTap;

  const _PlanTile({
    required this.additionalLabel,
    required this.monthlyLabel,
    required this.newLimitLabel,
    required this.isCurrent,
    required this.onTap,
    this.addedCapacityLabel,
    this.addedMonthlyLabel,
    this.showProrationNote = false,
    this.isLowerThanCurrent = false,
  });

  @override
  Widget build(BuildContext context) {
    final isUpgradeTile =
        addedCapacityLabel != null && addedMonthlyLabel != null;
    return Material(
      color: isCurrent ? VaultColors.accentSoft : VaultColors.surface,
      borderRadius: BorderRadius.circular(VaultRadius.md),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        child: Padding(
          padding: const EdgeInsets.all(VaultSpacing.lg),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: isUpgradeTile
                      ? [
                          Text(
                            'New plan  ·  $additionalLabel / $monthlyLabel',
                            style: VaultText.subtitle,
                          ),
                          const SizedBox(height: VaultSpacing.xs),
                          Text(
                            'Added today  ·  +$addedCapacityLabel / '
                            '+$addedMonthlyLabel',
                            style: VaultText.body.copyWith(
                              color: VaultColors.textSecondary,
                            ),
                          ),
                          if (showProrationNote)
                            Text(
                              'Today\'s charge  ·  prorated by Stripe',
                              style: VaultText.body.copyWith(
                                color: VaultColors.textSecondary,
                              ),
                            ),
                          Text(
                            'New storage limit  ·  $newLimitLabel',
                            style: VaultText.body.copyWith(
                              color: VaultColors.textSecondary,
                            ),
                          ),
                        ]
                      : [
                          Text(
                            'Additional storage  ·  $additionalLabel',
                            style: VaultText.subtitle,
                          ),
                          const SizedBox(height: VaultSpacing.xs),
                          Text(
                            'Monthly cost  ·  $monthlyLabel',
                            style: VaultText.body.copyWith(
                              color: VaultColors.textSecondary,
                            ),
                          ),
                          Text(
                            'New storage limit  ·  $newLimitLabel',
                            style: VaultText.body.copyWith(
                              color: VaultColors.textSecondary,
                            ),
                          ),
                        ],
                ),
              ),
              if (isCurrent)
                Text(
                  AppLocalizations.of(context).commonCurrent,
                  style: VaultText.caption,
                )
              else if (isLowerThanCurrent)
                Text(
                  AppLocalizations.of(context).storagePlanLower,
                  style: VaultText.caption,
                )
              else
                const Icon(
                  Icons.chevron_right,
                  color: VaultColors.textSecondary,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorCard({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.xl),
      decoration: BoxDecoration(
        color: VaultColors.severityCritSoft,
        borderRadius: BorderRadius.circular(VaultRadius.lg),
        border: Border.all(
          color: VaultColors.severityCrit.withValues(alpha: 0.4),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.error_outline, color: VaultColors.severityCrit),
              const SizedBox(width: VaultSpacing.sm),
              Text(
                AppLocalizations.of(context).storageCouldNotLoad,
                style: VaultText.subtitle,
              ),
            ],
          ),
          const SizedBox(height: VaultSpacing.sm),
          Text(message, style: VaultText.body),
          const SizedBox(height: VaultSpacing.md),
          Align(
            alignment: Alignment.centerRight,
            child: OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: Text(AppLocalizations.of(context).commonRetry),
            ),
          ),
        ],
      ),
    );
  }
}

class CheckoutReturnBanner extends StatelessWidget {
  final String kind;
  final VoidCallback onDismiss;

  const CheckoutReturnBanner({
    super.key,
    required this.kind,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    final isSuccess = kind == 'success';
    final color =
        isSuccess ? VaultColors.severityOk : VaultColors.textSecondary;
    final soft =
        isSuccess ? VaultColors.severityOkSoft : VaultColors.surfaceMuted;
    final icon = isSuccess ? Icons.check_circle_outline : Icons.info_outline;
    final title = isSuccess ? 'Payment confirmed' : 'Checkout cancelled';
    final body = isSuccess
        ? 'Your new storage will appear here in a moment. '
            'If it does not, tap refresh.'
        : 'No changes were made. You can try again whenever you are '
            'ready.';

    return Container(
      margin: const EdgeInsets.fromLTRB(
        VaultSpacing.lg,
        VaultSpacing.lg,
        VaultSpacing.lg,
        0,
      ),
      padding: const EdgeInsets.all(VaultSpacing.lg),
      decoration: BoxDecoration(
        color: soft,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color),
          const SizedBox(width: VaultSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: VaultText.subtitle),
                const SizedBox(height: VaultSpacing.xs),
                Text(body, style: VaultText.body),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Dismiss',
            onPressed: onDismiss,
            icon: const Icon(Icons.close, size: 18),
            color: VaultColors.textSecondary,
          ),
        ],
      ),
    );
  }
}

class _UpgradeProgressDialog extends StatelessWidget {
  const _UpgradeProgressDialog();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: VaultColors.surface,
      title: const Text('Checking your upgrade…', style: VaultText.title),
      content: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: const [
          SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(strokeWidth: 2.5),
          ),
          SizedBox(width: VaultSpacing.md),
          Expanded(
            child: Text(
              "We're updating your SVaultAI storage plan. This usually "
              'takes a few seconds.',
              style: VaultText.body,
            ),
          ),
        ],
      ),
    );
  }
}

class _UpgradeSuccessDialog extends StatelessWidget {
  final int newLimitGb;
  const _UpgradeSuccessDialog({required this.newLimitGb});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: VaultColors.surface,
      title: Row(
        children: const [
          Icon(Icons.check_circle_outline, color: VaultColors.severityOk),
          SizedBox(width: VaultSpacing.sm),
          Expanded(
            child: Text(
              'Storage upgraded successfully',
              style: VaultText.title,
            ),
          ),
        ],
      ),
      content: Text(
        'Your storage limit is now $newLimitGb GB.',
        style: VaultText.body,
      ),
      actions: [
        FilledButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Done'),
        ),
      ],
    );
  }
}

class _UpgradeTimeoutDialog extends StatelessWidget {
  final Future<void> Function() onRefresh;

  final Map<String, Object?>? debugFields;

  const _UpgradeTimeoutDialog({required this.onRefresh, this.debugFields});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: VaultColors.surface,
      title: const Text('Payment received', style: VaultText.title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "We're still applying your upgrade. Refresh in a moment.",
            style: VaultText.body,
          ),
          if (!kReleaseMode && debugFields != null)
            _BillingDebugCard(fields: debugFields!),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
        FilledButton(
          onPressed: onRefresh,
          child: Text(AppLocalizations.of(context).storageRefreshNow),
        ),
      ],
    );
  }
}

class _BillingDebugCard extends StatelessWidget {
  final Map<String, Object?> fields;
  const _BillingDebugCard({required this.fields});

  @override
  Widget build(BuildContext context) {
    final body = fields.entries.map((e) => '${e.key}=${e.value}').join(', ');
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: const Color(0xFF262626),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFF3A3A3A), width: 1),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.info_outline, size: 16, color: Color(0xFFB4B4B4)),
            const SizedBox(width: 8),
            Expanded(
              child: SelectableText(
                'Billing debug: $body',
                style: const TextStyle(
                  color: Color(0xFFB4B4B4),
                  fontSize: 11,
                  fontFamily: 'monospace',
                  height: 1.4,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LowerPlanDialog extends StatelessWidget {
  final Future<void> Function() onManageSubscription;
  const _LowerPlanDialog({required this.onManageSubscription});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: VaultColors.surface,
      title: const Text('Changing to a lower plan', style: VaultText.title),
      content: const Text(
        'To reduce your storage plan, open Manage Subscription. '
        'Changes to a lower plan may take effect at the end of your '
        'billing period.',
        style: VaultText.body,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
        FilledButton.icon(
          onPressed: onManageSubscription,
          icon: const Icon(Icons.settings_outlined),
          label: Text(AppLocalizations.of(context).settingsManageSubscription),
        ),
      ],
    );
  }
}

class _UpgradeErrorDialog extends StatelessWidget {
  final String message;
  const _UpgradeErrorDialog({required this.message});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: VaultColors.surface,
      title: Row(
        children: const [
          Icon(Icons.error_outline, color: VaultColors.severityCrit),
          SizedBox(width: VaultSpacing.sm),
          Expanded(
            child: Text("Upgrade couldn't start", style: VaultText.title),
          ),
        ],
      ),
      content: SelectableText(message, style: VaultText.body),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    );
  }
}
