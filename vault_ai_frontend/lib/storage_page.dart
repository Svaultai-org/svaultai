import 'dart:async' show StreamSubscription, unawaited;

import 'package:flutter/foundation.dart' show kIsWeb, kReleaseMode;
import 'package:flutter/material.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'l10n/app_localizations.dart';
import 'main.dart' show AppState, backendBaseUrl, kVaultStorageLimitBytes, vlog;
import 'services/apple_iap_service.dart';
import 'ui/tokens.dart';

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

  bool _autoOpenPickerRequested = false;
  bool _autoOpenPickerFired = false;

  String? _checkoutBanner;
  StreamSubscription<List<PurchaseDetails>>? _applePurchaseSubscription;

  @override
  void initState() {
    super.initState();
    _client = VaultAIClient(baseUrl: backendBaseUrl);
    if (supportsAppleIap) {
      AppleIapService.instance.initialize();
      _applePurchaseSubscription = AppleIapService.instance.transactions.listen(
        _handleAppleTransactions,
        onError: (_) => _showApplePurchaseError(
          'The App Store purchase could not be completed. Please try again.',
        ),
      );
    }
    _refresh();
  }

  @override
  void dispose() {
    _applePurchaseSubscription?.cancel();
    super.dispose();
  }

  Future<void> _handleAppleTransactions(
    List<PurchaseDetails> purchases,
  ) async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    for (final purchase in purchases) {
      if (blocksForAppleProduct(purchase.productID) == null) continue;
      if (purchase.status == PurchaseStatus.pending) {
        if (mounted) setState(() => _busyPurchase = true);
        continue;
      }
      if (purchase.status == PurchaseStatus.error) {
        if (mounted) setState(() => _busyPurchase = false);
        await _showApplePurchaseError(
          purchase.error?.message ?? 'The App Store purchase failed.',
        );
        continue;
      }
      if (purchase.status == PurchaseStatus.canceled) {
        if (mounted) setState(() => _busyPurchase = false);
        continue;
      }
      if (purchase.status != PurchaseStatus.purchased &&
          purchase.status != PurchaseStatus.restored) {
        continue;
      }

      try {
        await _client.verifyAppleStoragePurchase(
          authToken: token,
          signedTransaction: purchase.verificationData.serverVerificationData,
        );
        if (purchase.pendingCompletePurchase) {
          await AppleIapService.instance.finish(purchase);
        }
        await _refresh();
        if (!mounted) return;
        setState(() => _busyPurchase = false);
        final blocks = blocksForAppleProduct(purchase.productID) ?? 0;
        await showDialog<void>(
          context: context,
          builder: (_) => _UpgradeSuccessDialog(newLimitGb: blocks * 50),
        );
      } catch (_) {
        if (mounted) setState(() => _busyPurchase = false);
        // Do not finish an unverified transaction. StoreKit can redeliver it
        // after the backend/configuration problem is corrected.
        await _showApplePurchaseError(
          'Your purchase was received by Apple but could not yet be verified. '
          'You have not lost it; use Restore Purchases and try again.',
        );
      }
    }
  }

  Future<void> _showApplePurchaseError(String message) async {
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => _UpgradeErrorDialog(message: message),
    );
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final args = ModalRoute.of(context)?.settings.arguments;
    if (args is Map && args['autoOpenPicker'] == true) {
      _autoOpenPickerRequested = true;
      _maybeAutoOpenPicker();
    }

    if (_checkoutBanner == null) {
      String? flag;
      if (args is Map && args['checkout'] is String) {
        flag = args['checkout'] as String;
      } else {
        try {
          flag = Uri.base.queryParameters['checkout'];
        } catch (_) {
          flag = null;
        }
      }
      if (flag == 'success') {
        _checkoutBanner = 'success';

        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _runPostCheckoutPoll();
        });
      } else if (flag == 'cancel') {
        _checkoutBanner = 'cancel';
      }
    }
  }

  Future<void> _runPostCheckoutPoll() async {
    final app = context.read<AppState>();
    if (!mounted) return;
    unawaited(showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const _UpgradeProgressDialog(),
    ));

    final reachedData =
        await _pollEntitlementUntilPaidSubscriptionActive(app: app);

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

  void _dismissCheckoutBanner() {
    setState(() => _checkoutBanner = null);
  }

  void _maybeAutoOpenPicker() {
    if (!_autoOpenPickerRequested) return;
    if (_autoOpenPickerFired) return;
    if (_loading || _error != null || _data == null) return;
    _autoOpenPickerFired = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _onBuyStorage();
    });
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
      _maybeAutoOpenPicker();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load storage: $e';
      });
    }
  }

  Future<void> _onBuyStorage() async {
    if (supportsAppleIap) {
      await _onAppleBuyStorage();
      return;
    }
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

  Future<void> _onAppleBuyStorage() async {
    final data = _data;
    if (data == null) return;
    if (hasManageableStripeSubscription(data)) {
      await _showApplePurchaseError(
        'Your current storage plan is billed outside the App Store. '
        'Manage that subscription before switching to Apple billing.',
      );
      return;
    }
    setState(() => _busyPurchase = true);
    final catalog = await AppleIapService.instance.loadCatalog();
    if (!mounted) return;
    setState(() => _busyPurchase = false);
    if (!catalog.canPurchase) {
      await _showApplePurchaseError(
        catalog.error ?? 'Storage plans are unavailable from the App Store.',
      );
      return;
    }
    final picked = await showModalBottomSheet<int>(
      context: context,
      backgroundColor: VaultColors.canvas,
      isScrollControlled: true,
      builder: (_) => StoragePlanPicker(
        currentBlockCount: (data['block_count'] as num?)?.toInt() ?? 0,
        usedBytes: (data['used_bytes'] as num?)?.toInt() ?? 0,
        blockBytes: (data['block_bytes'] as num?)?.toInt() ?? 53687091200,
        blockPriceCentsUsd: 0,
        selfServiceMaxBlocks:
            (data['self_service_max_blocks'] as num?)?.toInt() ?? 100,
        hasActiveSubscription: hasActiveSubscription(data),
        storePrices: {
          for (final entry in catalog.products.entries)
            entry.key: entry.value.price,
        },
        applePurchase: true,
      ),
    );
    if (picked == null) return;
    final product = catalog.products[picked];
    final accountId = (data['account_id'] as String?) ?? '';
    if (product == null || accountId.isEmpty) {
      await _showApplePurchaseError('That storage plan is unavailable.');
      return;
    }
    setState(() => _busyPurchase = true);
    try {
      final started = await AppleIapService.instance.buy(
        product: product,
        accountId: accountId,
      );
      if (!started && mounted) {
        setState(() => _busyPurchase = false);
        await _showApplePurchaseError('The App Store did not start checkout.');
      }
    } catch (_) {
      if (mounted) setState(() => _busyPurchase = false);
      await _showApplePurchaseError(
        'The App Store checkout could not be opened. Please try again.',
      );
    }
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
    final s = error.toString();
    return s.contains('downgrade_not_supported');
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
        unawaited(showDialog<void>(
          context: context,
          barrierDismissible: false,
          builder: (_) => const _UpgradeProgressDialog(),
        ));

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
          builder: (_) => _UpgradeErrorDialog(message: e.toString()),
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
        final data = await _client.getBillingMe(
          authToken: token,
        );
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
    if (supportsAppleIap) {
      final launched = await launchUrl(
        Uri.parse('https://apps.apple.com/account/subscriptions'),
        mode: LaunchMode.externalApplication,
      );
      if (!launched) {
        await _showApplePurchaseError(
          'Apple subscription management could not be opened.',
        );
      }
      return;
    }
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

  Future<void> _onRestoreApplePurchases() async {
    final accountId = (_data?['account_id'] as String?) ?? '';
    if (!supportsAppleIap || accountId.isEmpty) return;
    setState(() => _busyPurchase = true);
    try {
      await AppleIapService.instance.restore(accountId: accountId);
    } catch (_) {
      if (mounted) setState(() => _busyPurchase = false);
      await _showApplePurchaseError(
        'Purchases could not be restored from the App Store.',
      );
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
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_checkoutBanner != null)
                CheckoutReturnBanner(
                  kind: _checkoutBanner!,
                  onDismiss: _dismissCheckoutBanner,
                ),
              Expanded(child: _buildBody()),
            ],
          ),
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
    return StorageBody(
      data: data,
      busy: _busyPurchase,
      onBuyStorage: (kIsWeb || supportsAppleIap) ? _onBuyStorage : null,
      onManageSubscription:
          kIsWeb || (supportsAppleIap && data['source'] == 'apple')
              ? _onManageSubscription
              : null,
      onRestorePurchases: supportsAppleIap ? _onRestoreApplePurchases : null,
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

  final source = (data['source'] as String?) ?? 'none';
  final status = (data['status'] as String?) ?? 'none';
  if (source != 'stripe') return false;
  return const {'active', 'in_grace', 'canceled_pending'}.contains(status);
}

bool hasManageableStripeSubscription(Map<String, dynamic> data) {
  final source = (data['source'] as String?) ?? 'none';
  final status = (data['status'] as String?) ?? 'none';
  if (source != 'stripe') return false;

  return status != 'none';
}

bool hasManageableSubscription(Map<String, dynamic> data) {
  final source = (data['source'] as String?) ?? 'none';
  final status = (data['status'] as String?) ?? 'none';
  return const {'stripe', 'apple'}.contains(source) && status != 'none';
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
  final VoidCallback? onRestorePurchases;

  const StorageBody({
    super.key,
    required this.data,
    this.busy = false,
    this.onBuyStorage,
    this.onManageSubscription,
    this.onRestorePurchases,
  });

  @override
  Widget build(BuildContext context) {
    final used = (data['used_bytes'] as num?)?.toInt() ?? 0;

    final limit = (data['effective_limit_bytes'] as num?)?.toInt() ??
        kVaultStorageLimitBytes;
    final percent = (data['percent_used'] as num?)?.toDouble() ?? 0.0;
    final accountType = (data['account_type'] as String?) ?? 'individual';
    final maxBlocks = (data['self_service_max_blocks'] as num?)?.toInt() ?? 100;
    final includedBytes =
        (data['included_bytes'] as num?)?.toInt() ?? kVaultStorageLimitBytes;

    final canBuy = onBuyStorage != null && !busy;
    final canManage = onManageSubscription != null &&
        hasManageableSubscription(data) &&
        !busy;

    return ListView(
      padding: const EdgeInsets.symmetric(
        horizontal: VaultSpacing.lg,
        vertical: VaultSpacing.xl,
      ),
      children: [
        _UsageCard(
          used: used,
          limit: limit,
          percentUsed: percent,
        ),
        const SizedBox(height: VaultSpacing.lg),

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

        // A disabled "Buy storage" button still looks like a broken IAP to
        // users and App Review. Purchase actions are omitted entirely when
        // the host platform has not supplied an approved purchase flow.
        if (onBuyStorage != null || onManageSubscription != null) ...[
          _PurchaseActionRow(
            canBuy: canBuy,
            canManage: canManage,
            hasActiveSub: hasActiveSubscription(data),
            onBuy: onBuyStorage,
            onManage: onManageSubscription,
          ),
          const SizedBox(height: VaultSpacing.lg),
        ],

        if (onRestorePurchases != null) ...[
          Center(
            child: TextButton(
              key: const Key('restore_apple_purchases_button'),
              onPressed: busy ? null : onRestorePurchases,
              child: const Text('Restore Purchases'),
            ),
          ),
          const SizedBox(height: VaultSpacing.lg),
        ],

        _AccountFactsCard(
          accountType: accountType,
          selfServiceMaxLabel: formatCapacityFromBlocks(maxBlocks),
        ),
        const SizedBox(height: VaultSpacing.lg),

        if (isOnFreeTierOnly(data))
          _FreeTierCard(includedBytes: includedBytes)
        else if (isGrandfathered(data))
          _GrandfatherCard(
            grantBytes: (data['storage_bytes_grant'] as num?)?.toInt() ?? 0,
            includedBytes: includedBytes,
          ),

        if (isOnFreeTierOnly(data) || isGrandfathered(data))
          const SizedBox(height: VaultSpacing.lg),

        const _PricingExamplesCard(),
        const SizedBox(height: VaultSpacing.xl),
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

  const _PurchaseActionRow({
    required this.canBuy,
    required this.canManage,
    required this.hasActiveSub,
    required this.onBuy,
    required this.onManage,
  });

  @override
  Widget build(BuildContext context) {
    final primaryLabel = hasActiveSub ? 'Upgrade storage' : 'Buy storage';
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
              padding: const EdgeInsets.symmetric(
                vertical: VaultSpacing.lg,
              ),
            ),
          ),
        ),
        if (canManage) const SizedBox(width: VaultSpacing.md),
        if (canManage)
          Expanded(
            child: OutlinedButton.icon(
              key: const Key('manage_subscription_button'),
              onPressed: onManage,
              icon: const Icon(Icons.settings_outlined),
              label: Text(
                AppLocalizations.of(context).settingsManageSubscription,
              ),
              style: OutlinedButton.styleFrom(
                foregroundColor: VaultColors.textPrimary,
                padding: const EdgeInsets.symmetric(
                  vertical: VaultSpacing.lg,
                ),
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
              Text('Used: ${formatBytes(used)}',
                  style: VaultText.bodySm.copyWith(
                    color: VaultColors.textSecondary,
                  )),
              const Spacer(),
              Text('Limit: ${formatBytes(limit)}',
                  style: VaultText.bodySm.copyWith(
                    color: VaultColors.textSecondary,
                  )),
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
          Expanded(
            child: Text(message, style: VaultText.body),
          ),
        ],
      ),
    );
  }
}

class _AccountFactsCard extends StatelessWidget {
  final String accountType;
  final String selfServiceMaxLabel;

  const _AccountFactsCard({
    required this.accountType,
    required this.selfServiceMaxLabel,
  });

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
          const SizedBox(height: VaultSpacing.sm),
          _kvRow('Self-service maximum', selfServiceMaxLabel),
        ],
      ),
    );
  }

  Widget _kvRow(String k, String v) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(k,
            style: VaultText.body.copyWith(
              color: VaultColors.textSecondary,
            )),
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
              const Icon(Icons.card_giftcard_outlined,
                  color: VaultColors.accent),
              const SizedBox(width: VaultSpacing.sm),
              Text(
                AppLocalizations.of(context).storageFreeTier,
                style: VaultText.title,
              ),
            ],
          ),
          const SizedBox(height: VaultSpacing.sm),
          Text(
            '${formatBytes(includedBytes)} included',
            style: VaultText.body.copyWith(
              color: VaultColors.textSecondary,
            ),
          ),
          const SizedBox(height: VaultSpacing.lg),
          Text(
            AppLocalizations.of(context).storageNeedMoreSpace,
            style: VaultText.subtitle,
          ),
          const SizedBox(height: VaultSpacing.sm),
          const Text(
            'Add storage anytime in 50 GB blocks. Your new limit '
            'updates automatically after payment.',
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
              const Icon(Icons.history_toggle_off,
                  color: VaultColors.severityInfo),
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
    ('50 GB', r'$14.99/month'),
    ('100 GB', r'$19.99/month'),
    ('150 GB', r'$24.99/month'),
    ('500 GB', r'$49.99/month'),
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
            style: VaultText.bodySm.copyWith(
              color: VaultColors.textSecondary,
            ),
          ),
          const SizedBox(height: VaultSpacing.md),
          ..._examples.map((e) => Padding(
                padding: const EdgeInsets.symmetric(vertical: VaultSpacing.xs),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(e.$1, style: VaultText.body),
                    Text(e.$2,
                        style: VaultText.mono.copyWith(
                          color: VaultColors.textSecondary,
                        )),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}

const List<int> kSelfServiceSkuBlockLadder = [
  1,
  2,
  3,
  4,
  5,
  10,
  20,
  40,
  100,
];

/// Web/Stripe monthly totals for the storage-plan ladder. StoreKit prices are
/// still read directly from Apple so localized App Store prices remain the
/// source of truth on iOS.
const Map<int, int> kWebStoragePlanPriceCentsUsd = {
  1: 1499,
  2: 1999,
  3: 2499,
  4: 2999,
  5: 3499,
  10: 4999,
  20: 7999,
  40: 12999,
  100: 19999,
};

class StoragePlanPicker extends StatelessWidget {
  final int currentBlockCount;
  final int usedBytes;
  final int blockBytes;
  final int blockPriceCentsUsd;
  final int selfServiceMaxBlocks;

  final bool hasActiveSubscription;
  final Map<int, String>? storePrices;
  final bool applePurchase;

  const StoragePlanPicker({
    super.key,
    required this.currentBlockCount,
    required this.usedBytes,
    required this.blockBytes,
    required this.blockPriceCentsUsd,
    required this.selfServiceMaxBlocks,
    this.hasActiveSubscription = false,
    this.storePrices,
    this.applePurchase = false,
  });

  int _priceCents(int blocks) =>
      kWebStoragePlanPriceCentsUsd[blocks] ?? blocks * blockPriceCentsUsd;

  String _formatUsd(int cents) {
    final dollars = cents ~/ 100;
    final remainder = (cents % 100).toString().padLeft(2, '0');
    return '\$$dollars.$remainder/month';
  }

  String _priceLabel(int blocks) {
    final storePrice = storePrices?[blocks];
    if (storePrice != null) return '$storePrice/month';
    return _formatUsd(_priceCents(blocks));
  }

  String _upgradePriceLabel(int targetBlocks) {
    final addedBlocks = targetBlocks - currentBlockCount;
    if (storePrices != null) return _priceLabel(addedBlocks);
    final addedCents =
        _priceCents(targetBlocks) - _priceCents(currentBlockCount);
    return _formatUsd(addedCents);
  }

  String _capacityLabel(int blocks) => formatCapacityFromBlocks(blocks,
      gbPerBlock: blockBytes ~/ (1024 * 1024 * 1024));

  String _newLimitLabel(int blocks) {
    final totalBytes = blocks * blockBytes;
    return formatBytes(totalBytes);
  }

  @override
  Widget build(BuildContext context) {
    final ladder = kSelfServiceSkuBlockLadder
        .where((b) => b <= selfServiceMaxBlocks)
        .where((b) => storePrices == null || storePrices!.containsKey(b))
        .toList();

    final title =
        hasActiveSubscription ? 'Upgrade Storage' : 'Buy More Storage';
    final intro = hasActiveSubscription
        ? applePurchase
            ? 'Choose a different monthly plan. Apple will confirm any '
                'upgrade, downgrade, or prorated charge.'
            : 'Pick a higher tier to bump your existing subscription. You '
                'will not be sent to Stripe Checkout — the change happens in '
                'place and the prorated upgrade charge runs immediately.'
        : applePurchase
            ? 'Choose a monthly storage plan. Payment is handled securely '
                'by the App Store.'
            : 'Choose a monthly storage plan. Checkout opens Stripe in a '
                'new tab.';
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
                        isUpgradeTile ? _upgradePriceLabel(blocks) : null,
                    prorationLabel: isUpgradeTile
                        ? applePurchase
                            ? 'Apple will confirm today\'s charge'
                            : 'Today\'s charge  ·  prorated by Stripe'
                        : null,
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
  final String? prorationLabel;
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
    this.prorationLabel,
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
                          if (prorationLabel != null)
                            Text(
                              prorationLabel!,
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
                const Icon(Icons.chevron_right,
                    color: VaultColors.textSecondary),
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
              "We're updating your Svaultai storage plan. This usually "
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

  const _UpgradeTimeoutDialog({
    required this.onRefresh,
    this.debugFields,
  });

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: VaultColors.surface,
      title: const Text(
        'Payment received',
        style: VaultText.title,
      ),
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
          border: Border.all(
            color: const Color(0xFF3A3A3A),
            width: 1,
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(
              Icons.info_outline,
              size: 16,
              color: Color(0xFFB4B4B4),
            ),
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
      title: const Text(
        'Changing to a lower plan',
        style: VaultText.title,
      ),
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
          label: Text(
            AppLocalizations.of(context).settingsManageSubscription,
          ),
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
            child: Text(
              "Upgrade couldn't start",
              style: VaultText.title,
            ),
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
