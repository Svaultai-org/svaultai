import 'dart:async' show StreamSubscription;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'public_download_badges.dart';
import 'l10n/app_localizations.dart';
import 'main.dart' show AppState, backendBaseUrl, kVaultStorageLimitBytes;
import 'services/apple_iap_service.dart';
import 'services/apple_purchase_recovery.dart';
import 'ui/tokens.dart';

class StoragePage extends StatefulWidget {
  const StoragePage({super.key});

  @override
  State<StoragePage> createState() => _StoragePageState();
}

class _StoragePageState extends State<StoragePage> with WidgetsBindingObserver {
  late final VaultAIClient _client;
  bool _loading = true;
  bool _busyPurchase = false;
  bool _appleActionInProgress = false;
  final Set<String> _processingAppleTransactions = {};
  final Set<String> _reportedActivationErrors = {};
  String? _error;
  Map<String, dynamic>? _data;

  bool _autoOpenPickerRequested = false;
  bool _autoOpenPickerFired = false;

  StreamSubscription<List<PurchaseDetails>>? _applePurchaseSubscription;

  @override
  void initState() {
    super.initState();
    _client = VaultAIClient(baseUrl: backendBaseUrl);
    if (supportsAppleIap) {
      WidgetsBinding.instance.addObserver(this);
      AppleIapService.instance.initialize();
      _applePurchaseSubscription = AppleIapService.instance.transactions.listen(
        _handleAppleTransactions,
        onError: (_) => _showApplePurchaseError(
          'The App Store connection was interrupted. If Apple accepted a purchase, '
          'use Restore Purchases; do not purchase again.',
        ),
      );
    }
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _applePurchaseSubscription?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed &&
        supportsAppleIap &&
        !_busyPurchase &&
        mounted) {
      AppleIapService.instance.replayPendingTransactions();
      _refresh();
    }
  }

  Future<void> _handleAppleTransactions(
    List<PurchaseDetails> purchases,
  ) async {
    if (!mounted) return;
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    for (final purchase in purchases) {
      if (!isAppleStorageProduct(purchase.productID)) continue;
      if (purchase.status == PurchaseStatus.pending) {
        if (mounted) setState(() => _busyPurchase = true);
        continue;
      }
      if (purchase.status == PurchaseStatus.error) {
        if (mounted) {
          setState(
              () => _busyPurchase = _processingAppleTransactions.isNotEmpty);
        }
        await _showApplePurchaseError(
          purchase.error?.message ?? 'The App Store purchase failed.',
        );
        continue;
      }
      if (purchase.status == PurchaseStatus.canceled) {
        if (mounted) {
          setState(
              () => _busyPurchase = _processingAppleTransactions.isNotEmpty);
        }
        continue;
      }
      if (purchase.status != PurchaseStatus.purchased &&
          purchase.status != PurchaseStatus.restored) {
        continue;
      }
      final transactionKey = appleTransactionKey(purchase);
      final signedTransaction =
          purchase.verificationData.serverVerificationData;
      if (!_processingAppleTransactions.add(transactionKey)) continue;
      if (mounted) setState(() => _busyPurchase = true);
      try {
        final result = await AppleIapService.instance.recovery.recover(
          accountKey: token,
          transactionKey: transactionKey,
          verify: () => _client.verifyAppleStoragePurchase(
            authToken: token,
            signedTransaction: signedTransaction,
          ),
          finish: () => AppleIapService.instance.finish(purchase),
        );
        if (!mounted || context.read<AppState>().sessionToken != token) return;
        if (!result.handled) continue;
        _reportedActivationErrors.remove(transactionKey);
        await _refresh();
        if (!mounted || context.read<AppState>().sessionToken != token) return;
        if (_error != null) {
          await _showApplePurchaseError(
            'Apple verified your purchase, but the storage display could not refresh. '
            'Refresh this page or use Restore Purchases. Do not purchase again.',
            title: 'Storage refresh pending',
          );
          continue;
        }
        if (_data?['source'] != 'apple' || !hasActiveSubscription(_data!)) {
          await _showApplePurchaseError(
            'Your App Store purchase was verified and your storage was refreshed. '
            'This restored subscription is not currently active.',
            title: 'Subscription restored',
          );
          continue;
        }
        // Only the verified server quota is displayed, never a local SKU guess.
        final limitBytes =
            (_data?['effective_limit_bytes'] as num?)?.toInt() ?? 0;
        await showDialog<void>(
          context: context,
          builder: (_) => _UpgradeSuccessDialog(
            newLimitGb: limitBytes ~/ (1024 * 1024 * 1024),
          ),
        );
      } catch (error) {
        if (!mounted || context.read<AppState>().sessionToken != token) return;
        // Do not finish an unverified transaction. StoreKit can redeliver it
        // after the backend/configuration problem is corrected.
        if (_reportedActivationErrors.add(transactionKey)) {
          final failure = error is ApplePurchaseVerificationException
              ? error
              : error is AuthExpiredException ||
                      error is SessionTerminatedException ||
                      error is DeviceNotTrustedException
                  ? const ApplePurchaseVerificationException(statusCode: 403)
                  : const ApplePurchaseVerificationException(
                      statusCode: 200, code: 'activation_unconfirmed');
          await _showApplePurchaseError(
            failure.userMessage,
            title: failure.userTitle,
          );
        }
      } finally {
        _processingAppleTransactions.remove(transactionKey);
        if (mounted) {
          setState(() => _busyPurchase = _appleActionInProgress ||
              _processingAppleTransactions.isNotEmpty);
        }
      }
    }
  }

  Future<void> _showApplePurchaseError(
    String message, {
    String title = "Upgrade couldn't start",
  }) async {
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => _UpgradeErrorDialog(message: message, title: title),
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
  }

  void _maybeAutoOpenPicker() {
    if (!supportsAppleIap || !_autoOpenPickerRequested) return;
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
      if (!mounted || context.read<AppState>().sessionToken != token) return;
      context.read<AppState>().applyBillingPayload(data);
      setState(() {
        _data = data;
        _loading = false;
        _error = null;
      });
      _maybeAutoOpenPicker();
    } catch (e) {
      if (!mounted || context.read<AppState>().sessionToken != token) return;
      setState(() {
        _loading = false;
        _error = 'Could not load storage: $e';
      });
    }
  }

  Future<void> _onBuyStorage() async {
    if (supportsAppleIap) await _onAppleBuyStorage();
  }

  Future<String> _appleAppAccountToken(String token) async {
    final providers = await _client.getBillingProviders(authToken: token);
    final apple = providers['apple'];
    final appAccountToken =
        apple is Map ? (apple['app_account_token'] as String?) ?? '' : '';
    if (appAccountToken.isEmpty) {
      throw StateError('App Store billing could not be loaded.');
    }
    return appAccountToken;
  }

  Future<void> _onAppleBuyStorage() async {
    if (_busyPurchase || _appleActionInProgress) return;
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    final data = _data;
    if (data == null) return;
    if (AppleIapService.instance.hasPendingActivation) {
      await _showApplePurchaseError(
        'An existing App Store purchase is awaiting activation. '
        'Use Restore Purchases; do not purchase again.',
        title: 'Purchase activation pending',
      );
      return;
    }
    if (data['source'] == 'google_play' && hasActiveSubscription(data)) {
      await _showApplePurchaseError(
        'Your current storage plan is billed through Google Play. '
        'Manage that subscription in Google Play before switching stores.',
      );
      return;
    }
    _appleActionInProgress = true;
    setState(() => _busyPurchase = true);
    var checkoutStarted = false;
    try {
      final catalog = await AppleIapService.instance.loadCatalog();
      if (!mounted || context.read<AppState>().sessionToken != token) return;
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
      if (!mounted ||
          context.read<AppState>().sessionToken != token ||
          picked == null) return;
      final product = catalog.products[picked];
      if (product == null) {
        await _showApplePurchaseError('That storage plan is unavailable.');
        return;
      }
      final appAccountToken = await _appleAppAccountToken(token);
      if (!mounted || context.read<AppState>().sessionToken != token) return;
      checkoutStarted = await AppleIapService.instance.buy(
        product: product,
        appAccountToken: appAccountToken,
      );
      if (!checkoutStarted && mounted) {
        await _showApplePurchaseError(
          'An App Store request is already in progress. Wait for it to complete. '
          'If Apple accepted a purchase, use Restore Purchases; do not purchase again.',
        );
      }
    } catch (_) {
      await _showApplePurchaseError(
        'The App Store checkout could not be opened. If Apple accepted a purchase, '
        'use Restore Purchases; do not purchase again.',
      );
    } finally {
      _appleActionInProgress = false;
      if (mounted) {
        setState(() => _busyPurchase =
            _processingAppleTransactions.isNotEmpty ||
                AppleIapService.instance.hasPendingStoreRequest);
      }
    }
  }

  Future<void> _onManageSubscription() async {
    final source = _data?['source'];
    final url = source == 'apple'
        ? 'https://apps.apple.com/account/subscriptions'
        : source == 'google_play'
            ? 'https://play.google.com/store/account/subscriptions'
            : null;
    if (url == null) return;
    final launched = await launchUrl(
      Uri.parse(url),
      mode:
          kIsWeb ? LaunchMode.platformDefault : LaunchMode.externalApplication,
    );
    if (!launched) {
      await _showApplePurchaseError(
        'Store subscription management could not be opened.',
      );
    }
  }

  Future<void> _onRestoreApplePurchases() async {
    if (!supportsAppleIap || _busyPurchase || _appleActionInProgress) return;
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    _appleActionInProgress = true;
    _reportedActivationErrors.clear();
    setState(() => _busyPurchase = true);
    try {
      final appAccountToken = await _appleAppAccountToken(token);
      if (!mounted || context.read<AppState>().sessionToken != token) return;
      await AppleIapService.instance.restore(
        appAccountToken: appAccountToken,
      );
      if (mounted) await _refresh();
    } catch (_) {
      await _showApplePurchaseError(
        'Purchases could not be restored from the App Store. '
        'The existing purchase remains recoverable. Do not purchase again.',
        title: 'Restore unavailable',
      );
    } finally {
      _appleActionInProgress = false;
      // Restore may legitimately return no transactions; do not leave the
      // screen busy forever while waiting for a callback that will not arrive.
      if (mounted) {
        setState(() => _busyPurchase = _processingAppleTransactions.isNotEmpty);
      }
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
      onBuyStorage: supportsAppleIap ? _onBuyStorage : null,
      onManageSubscription:
          hasManageableSubscription(data) ? _onManageSubscription : null,
      showStorePurchaseNotice: kIsWeb,
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
  final source = (data['source'] as String?) ?? 'none';
  if (!const {'apple', 'google_play'}.contains(source)) return false;
  final flag = data['has_active_subscription'];
  if (flag is bool) return flag;
  final status = (data['status'] as String?) ?? 'none';
  return const {'active', 'in_grace', 'canceled_pending'}.contains(status);
}

bool hasManageableSubscription(Map<String, dynamic> data) {
  final source = (data['source'] as String?) ?? 'none';
  final status = (data['status'] as String?) ?? 'none';
  return const {'apple', 'google_play'}.contains(source) && status != 'none';
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
  final bool showStorePurchaseNotice;

  const StorageBody({
    super.key,
    required this.data,
    this.busy = false,
    this.onBuyStorage,
    this.onManageSubscription,
    this.onRestorePurchases,
    this.showStorePurchaseNotice = false,
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

        if (showStorePurchaseNotice) ...[
          const _StorePurchaseNotice(),
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

class _StorePurchaseNotice extends StatelessWidget {
  const _StorePurchaseNotice();

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(VaultSpacing.xl),
        decoration: BoxDecoration(
          color: VaultColors.surface,
          borderRadius: BorderRadius.circular(VaultRadius.lg),
          border: Border.all(color: VaultColors.borderSubtle),
        ),
        child: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Storage subscriptions', style: VaultText.subtitle),
            SizedBox(height: VaultSpacing.sm),
            Text(
              'SVaultAI uses Apple App Store and Google Play billing only. '
              'Use your store subscription with the same vault on the web. '
              'Web card checkout is not available.',
              style: VaultText.body,
            ),
            SizedBox(height: VaultSpacing.lg),
            PlatformDownloadBadges(compact: true),
          ],
        ),
      );
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
        if (onBuy != null)
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
        if (canManage && onBuy != null) const SizedBox(width: VaultSpacing.md),
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

/// Illustrative USD monthly plan prices. The App Store supplies the actual
/// localized purchase prices; these examples do not initiate web payments.
const Map<int, int> kStoragePlanPriceExamplesCentsUsd = {
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
      kStoragePlanPriceExamplesCentsUsd[blocks] ?? blocks * blockPriceCentsUsd;

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
            : 'Choose a different monthly plan. Your app store will confirm '
                'the price and when the change takes effect.'
        : applePurchase
            ? 'Choose a monthly storage plan. Payment is handled securely '
                'by the App Store.'
            : 'Choose a monthly storage plan in the App Store or Google Play.';
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
                            : 'Your app store will confirm today\'s charge'
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

class _UpgradeErrorDialog extends StatelessWidget {
  final String message;
  final String title;
  const _UpgradeErrorDialog({required this.message, required this.title});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: VaultColors.surface,
      title: Row(
        children: [
          const Icon(Icons.error_outline, color: VaultColors.severityCrit),
          const SizedBox(width: VaultSpacing.sm),
          Expanded(
            child: Text(
              title,
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
