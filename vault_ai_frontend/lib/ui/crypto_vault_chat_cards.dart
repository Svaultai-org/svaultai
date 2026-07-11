
import 'dart:async';

import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../services/crypto_chat_live_cache.dart';
import '../services/crypto_vault_chat_control.dart';
import 'crypto_wallet_engine_design.dart';




typedef CryptoBalanceFetcher = Future<Map<String, dynamic>> Function({
  required String asset,
  required String address,
});


typedef CryptoActivityFetcher = Future<Map<String, dynamic>> Function({
  required String asset,
  required String address,
  int limit,
});


const String kCvcCardKeyRefusal      = 'crypto_vault_chat_card_refusal';
const String kCvcCardKeyClarify      = 'crypto_vault_chat_card_clarify';
const String kCvcCardKeyBalance      = 'crypto_vault_chat_card_balance';
const String kCvcCardKeyReceive      = 'crypto_vault_chat_card_receive';
const String kCvcCardKeyReceiveQr    = 'crypto_vault_chat_card_receive_qr';
const String kCvcCardKeyScannerStatus =
    'crypto_vault_chat_card_scanner_status';
const String kCvcCardKeyActivity     = 'crypto_vault_chat_card_activity';
const String kCvcCardKeySendDraft    = 'crypto_vault_chat_card_send_draft';
const String kCvcCardKeyShowVault    = 'crypto_vault_chat_card_show_vault';
const String kCvcCardKeyUnrecognized =
    'crypto_vault_chat_card_unrecognized';



class CryptoVaultChatCardView extends StatelessWidget {
  final CryptoVaultChatCard card;
  final VoidCallback? onOpenVault;
  final void Function(String asset)? onOpenAssetDetail;
  final VoidCallback? onOpenSendFlow;


  final CryptoBalanceFetcher? onFetchBalance;
  final CryptoActivityFetcher? onFetchActivity;


  final CryptoChatLiveCache? cache;


  final bool cryptoEntitled;

  final VoidCallback? onOpenUpgrade;

  const CryptoVaultChatCardView({
    super.key,
    required this.card,
    this.onOpenVault,
    this.onOpenAssetDetail,
    this.onOpenSendFlow,
    this.onFetchBalance,
    this.onFetchActivity,
    this.cache,
    this.cryptoEntitled = true,
    this.onOpenUpgrade,
  });

  @override
  Widget build(BuildContext context) {
    switch (card.cardType) {
      case kCvcCardRefusal:
        return _RefusalCard(card: card);
      case kCvcCardClarify:
        return _ClarifyCard(card: card);
      case kCvcCardBalance:
        return _BalanceCard(card: card,
            onOpenAssetDetail: onOpenAssetDetail,
            onFetchBalance: onFetchBalance,
            cache: cache);
      case kCvcCardReceive:
        return _ReceiveCard(card: card,
            onOpenAssetDetail: onOpenAssetDetail);
      case kCvcCardReceiveQr:
        return _ReceiveQrCard(card: card,
            onOpenAssetDetail: onOpenAssetDetail);
      case kCvcCardScannerStatus:
        return _ScannerStatusCard(card: card,
            onOpenAssetDetail: onOpenAssetDetail);
      case kCvcCardActivity:
        return _ActivityCard(card: card,
            onOpenAssetDetail: onOpenAssetDetail,
            onFetchActivity: onFetchActivity,
            cache: cache);
      case kCvcCardSendDraft:
        return _SendDraftCard(card: card,
            onOpenSendFlow: onOpenSendFlow);
      case kCvcCardShowVault:
        return _ShowVaultCard(
          card: card,
          onOpenVault: onOpenVault,
          onOpenAssetDetail: onOpenAssetDetail,
          onFetchBalance: onFetchBalance,
          cache: cache,
          cryptoEntitled: cryptoEntitled,
          onOpenUpgrade: onOpenUpgrade,
        );
      case kCvcCardUnrecognized:
      default:
        return _UnrecognizedCard(card: card);
    }
  }
}


Widget _shell({
  required String testKey,
  required Widget child,
  Color? accent,
}) {
  return Container(
    key: Key(testKey),
    padding: const EdgeInsets.all(14),
    decoration: walletDarkCard(
      accent: accent,
    ),
    child: child,
  );
}


class _RefusalCard extends StatelessWidget {
  final CryptoVaultChatCard card;
  const _RefusalCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final message = card.message
        ?? (card.refusalReason == kCvcRefusalReasonSecretMaterial
            ? kCvcRefusalCopySecretMaterial
            : kCvcRefusalCopyExchangeAction);
    return _shell(
      testKey: kCvcCardKeyRefusal,
      accent: kWalletAccentDanger,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.block_rounded, size: 18,
              color: kWalletAccentDanger),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(
                color: kWalletTextPrimary, fontSize: 13, height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}


class _ClarifyCard extends StatelessWidget {
  final CryptoVaultChatCard card;
  const _ClarifyCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final options = card.options ?? const <String>[];
    return _shell(
      testKey: kCvcCardKeyClarify,
      accent: kWalletAccentPrimary,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            card.message ?? kCvcClarifyUsdtCopy,
            style: const TextStyle(
              color: kWalletTextPrimary, fontSize: 13, height: 1.4,
            ),
          ),
          if (options.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              children: [
                for (final o in options)
                  Container(
                    key: Key('crypto_vault_chat_clarify_option_$o'),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10, vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: kWalletSurfaceElevated,
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(color: kWalletBorder),
                    ),
                    child: Text(
                      o,
                      style: const TextStyle(
                        color: kWalletTextPrimary,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}


class _BalanceCard extends StatefulWidget {
  final CryptoVaultChatCard card;
  final void Function(String asset)? onOpenAssetDetail;
  final CryptoBalanceFetcher? onFetchBalance;
  final CryptoChatLiveCache? cache;
  const _BalanceCard({
    required this.card, this.onOpenAssetDetail,
    this.onFetchBalance, this.cache,
  });

  @override
  State<_BalanceCard> createState() => _BalanceCardState();
}


class _BalanceCardState extends State<_BalanceCard> {
  String? _liveStatus;
  String? _liveAmount;
  String? _liveUnit;
  String? _liveReason;
  bool _fetchInFlight = false;

  @override
  void initState() {
    super.initState();


    _primeFromCache();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeFetch());
  }


  void _primeFromCache() {
    final cache = widget.cache;
    if (cache == null) return;
    final data = widget.card.data;
    final asset   = widget.card.asset ?? '';
    final address = (data?['publicAddress'] ?? '').toString();
    if (asset.isEmpty || address.isEmpty) return;
    if (asset == 'XMR') return;
    final cached = cache.peek(
      type: kCryptoChatCacheRequestBalance,
      asset: asset, address: address,
    );
    if (cached == null) return;
    _liveStatus = (cached['balanceStatus'] ?? '').toString();
    final amount = cached['availableAmount'];
    _liveAmount = amount is String
        ? amount
        : (amount is num ? amount.toString() : null);
    _liveUnit   = (cached['unit']   ?? '').toString();
    _liveReason = (cached['reason'] ?? '').toString();
  }

  @override
  void didUpdateWidget(covariant _BalanceCard old) {
    super.didUpdateWidget(old);
    if (old.card.asset != widget.card.asset) {
      _liveStatus = null;
      _liveAmount = null;
      _liveUnit = null;
      _liveReason = null;
      _maybeFetch();
    }
  }

  Future<void> _maybeFetch({bool bypassCache = false}) async {
    if (_fetchInFlight) return;
    final fetcher = widget.onFetchBalance;
    if (fetcher == null) return;
    final data = widget.card.data;
    final status = (data?['balanceStatus'] ?? '').toString();
    final asset = widget.card.asset ?? '';
    final address = (data?['publicAddress'] ?? '').toString();

    if (status != 'pending_live_fetch' && !bypassCache) return;
    if (asset.isEmpty || address.isEmpty) return;

    if (asset == 'XMR') return;
    _fetchInFlight = true;
    try {
      final cache = widget.cache;
      final Future<Map<String, dynamic>> future;
      if (cache != null) {
        if (bypassCache) {
          cache.invalidate(
            type:    kCryptoChatCacheRequestBalance,
            asset:   asset,
            address: address,
          );
        }
        future = cache.fetch(
          type:    kCryptoChatCacheRequestBalance,
          asset:   asset,
          address: address,
          run:     () => fetcher(asset: asset, address: address),
        );
      } else {
        future = fetcher(asset: asset, address: address);
      }
      final res = await future;
      if (!mounted) return;
      setState(() {
        _liveStatus = (res['balanceStatus'] ?? '').toString();


        final amount = res['availableAmount'];
        _liveAmount = amount is String
            ? amount
            : (amount is num ? amount.toString() : null);
        _liveUnit = (res['unit'] ?? '').toString();
        _liveReason = (res['reason'] ?? '').toString();
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _liveStatus = 'unavailable';
        _liveReason = 'network_error';
      });
    } finally {
      _fetchInFlight = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final card = widget.card;
    final asset = card.asset ?? '';
    final data = card.data;
    final label = (data?['label'] ?? asset).toString();


    final backendStatus = (data?['balanceStatus'] ?? '').toString();
    final backendReason = (data?['reason'] ?? '').toString();
    final effectiveStatus = _liveStatus ?? backendStatus;
    final effectiveReason = _liveReason?.isNotEmpty == true
        ? _liveReason!
        : backendReason;


    String? displayBalance;
    if (_liveStatus == 'available'
        && _liveAmount != null
        && _liveAmount!.isNotEmpty) {
      final unit = (_liveUnit ?? '').isNotEmpty
          ? _liveUnit!
          : _defaultUnitFor(asset);
      displayBalance = '${_liveAmount!} $unit'.trim();
    } else if (_liveStatus == null && backendStatus == 'available') {

      final maybeBalance = data?['displayBalance'];
      if (maybeBalance is String && maybeBalance.isNotEmpty) {
        displayBalance = maybeBalance;
      }
    }

    return _shell(
      testKey: kCvcCardKeyBalance,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Balance: $label',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (displayBalance != null)
            Text(
              displayBalance,
              key: const Key(
                'crypto_vault_chat_balance_display_value',
              ),
              style: const TextStyle(
                color: kWalletTextPrimary,
                fontSize: 20,
                fontWeight: FontWeight.w800,
              ),
            )
          else if (effectiveStatus == 'scanner_gated')
            _balanceGatedRow(
              effectiveReason,
              'Monero balance is gated by the scanner. Open the '
              'Monero card for the exact status.',
            )
          else if (effectiveStatus == 'requires_desktop')
            _balanceGatedRow(
              effectiveReason,
              'Monero scanning requires the desktop app. On web '
              'VaultAI cannot show the balance.',
            )
          else if (effectiveStatus == 'pending_live_fetch')
            const Text(
              'Loading live balance…',
              key: Key('crypto_vault_chat_balance_loading'),
              style: kWalletBodyStyle,
            )
          else if (effectiveStatus == 'unavailable') ...[
            _balanceGatedRow(
              effectiveReason,
              'Balance unavailable right now. Open the asset '
              'to retry.',
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              key: const Key('crypto_vault_chat_balance_retry'),
              onPressed: _fetchInFlight
                  ? null
                  : () => _maybeFetch(bypassCache: true),
              style: walletGhostButtonStyle(),
              child: const Text('Retry'),
            ),
          ]
          else
            const Text(
              'VaultAI will read your on-chain balance when you '
              'open this asset.',
              style: kWalletBodyStyle,
            ),
          if (asset.isNotEmpty && widget.onOpenAssetDetail != null)
            ...[
              const SizedBox(height: 10),
              OutlinedButton(
                key: Key('crypto_vault_chat_balance_open_$asset'),
                onPressed: () => widget.onOpenAssetDetail!(asset),
                style: walletGhostButtonStyle(),
                child: Text(AppLocalizations.of(context).cryptoOpenAsset),
              ),
            ],
        ],
      ),
    );
  }
}


String _defaultUnitFor(String asset) {
  switch (asset) {
    case 'ETH':        return 'ETH';
    case 'USDT_ERC20':
    case 'USDT_TRC20': return 'USDT';
    case 'USDC_ERC20': return 'USDC';
    case 'SOL':        return 'SOL';
    case 'XMR':        return 'XMR';
    default:           return asset;
  }
}


Widget _balanceGatedRow(String reason, String fallback) {
  final safeReason = reason.isEmpty
      ? fallback
      : '$fallback (${reason.replaceAll('_', ' ')})';
  return Text(
    safeReason,
    key: const Key('crypto_vault_chat_balance_gated'),
    style: const TextStyle(
      color: kWalletTextMuted, fontSize: 12,
      fontWeight: FontWeight.w600, height: 1.35,
    ),
  );
}


class _ReceiveCard extends StatelessWidget {
  final CryptoVaultChatCard card;
  final void Function(String asset)? onOpenAssetDetail;
  const _ReceiveCard({required this.card, this.onOpenAssetDetail});

  @override
  Widget build(BuildContext context) {
    final asset = card.asset ?? '';
    final data = card.data;
    final label = (data?['label'] ?? asset).toString();
    final receiveReady = data?['receiveReady'] == true;
    final publicAddress = (data?['publicAddress'] ?? '').toString();
    final network = (data?['network'] ?? '').toString();
    final warning = (data?['warning'] ?? '').toString();

    return _shell(
      testKey: kCvcCardKeyReceive,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Receive: $label', style: kWalletSectionHeadingStyle),
          const SizedBox(height: 6),
          if (!receiveReady)
            const Text(
              'No wallet yet. Create one in Crypto Vault to get a '
              'real receive address.',
              key: Key('crypto_vault_chat_receive_no_wallet'),
              style: kWalletBodyStyle,
            )
          else ...[
            SelectableText(
              publicAddress,
              key: const Key(
                'crypto_vault_chat_receive_public_address',
              ),
              style: const TextStyle(
                color: kWalletTextPrimary,
                fontSize: 12,
                fontFamily: 'monospace',
                fontWeight: FontWeight.w700,
                height: 1.35,
              ),
            ),
            if (network.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                'Network: $network',
                style: const TextStyle(
                  color: kWalletTextMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
            if (warning.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                warning,
                key: const Key(
                  'crypto_vault_chat_receive_warning',
                ),
                style: const TextStyle(
                  color: kWalletAccentWarning,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ],
          if (asset.isNotEmpty && onOpenAssetDetail != null) ...[
            const SizedBox(height: 10),
            OutlinedButton(
              key: Key('crypto_vault_chat_receive_open_$asset'),
              onPressed: () => onOpenAssetDetail!(asset),
              style: walletGhostButtonStyle(),
              child: Text(AppLocalizations.of(context).cryptoOpenAsset),
            ),
          ],
        ],
      ),
    );
  }
}


class _ReceiveQrCard extends StatelessWidget {
  final CryptoVaultChatCard card;
  final void Function(String asset)? onOpenAssetDetail;
  const _ReceiveQrCard({required this.card, this.onOpenAssetDetail});

  @override
  Widget build(BuildContext context) {
    final asset = card.asset ?? '';
    final data = card.data;
    final label = (data?['label'] ?? asset).toString();
    final receiveReady = data?['receiveReady'] == true;
    final publicAddress = (data?['publicAddress'] ?? '').toString();
    final qrPayload = (data?['qrPayload'] ?? '').toString();
    return _shell(
      testKey: kCvcCardKeyReceiveQr,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Receive QR: $label',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!receiveReady)
            const Text(
              'No wallet yet. Create one in Crypto Vault to view '
              'the QR for your receive address.',
              key: Key('crypto_vault_chat_qr_no_wallet'),
              style: kWalletBodyStyle,
            )
          else ...[
            if (qrPayload.isNotEmpty)
              Container(
                key: const Key(
                  'crypto_vault_chat_qr_payload',
                ),
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: kWalletBgBase,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: kWalletBorder),
                ),
                child: Text(
                  'QR payload ready. Open the asset to render '
                  'the QR code.',
                  style: const TextStyle(
                    color: kWalletTextMuted,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            if (publicAddress.isNotEmpty) ...[
              const SizedBox(height: 6),
              SelectableText(
                publicAddress,
                key: const Key(
                  'crypto_vault_chat_qr_public_address',
                ),
                style: const TextStyle(
                  color: kWalletTextPrimary,
                  fontSize: 11,
                  fontFamily: 'monospace',
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ],
          if (asset.isNotEmpty && onOpenAssetDetail != null) ...[
            const SizedBox(height: 10),
            OutlinedButton(
              key: Key('crypto_vault_chat_qr_open_$asset'),
              onPressed: () => onOpenAssetDetail!(asset),
              style: walletGhostButtonStyle(),
              child: Text(AppLocalizations.of(context).cryptoOpenAsset),
            ),
          ],
        ],
      ),
    );
  }
}


class _ScannerStatusCard extends StatelessWidget {
  final CryptoVaultChatCard card;
  final void Function(String asset)? onOpenAssetDetail;
  const _ScannerStatusCard({
    required this.card, this.onOpenAssetDetail,
  });

  @override
  Widget build(BuildContext context) {
    final data = card.data;
    final scannerStatus =
        (data?['scannerStatus'] ?? '').toString();
    final reason = (data?['reason'] ?? '').toString();
    final message = (data?['message'] ?? '').toString();
    final canBalance = data?['canShowBalance'] == true;
    final canActivity = data?['canShowActivity'] == true;

    final headline = _scannerHeadline(reason, scannerStatus);
    final body = message.isNotEmpty
        ? message
        : _scannerFallbackCopy(reason, scannerStatus);

    return _shell(
      testKey: kCvcCardKeyScannerStatus,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).cryptoMoneroScannerStatus,
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          Text(
            headline,
            key: const Key(
              'crypto_vault_chat_scanner_headline',
            ),
            style: const TextStyle(
              color: kWalletTextPrimary,
              fontSize: 14,
              fontWeight: FontWeight.w800,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            body,
            style: const TextStyle(
              color: kWalletTextMuted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6, runSpacing: 6,
            children: [
              _scannerPill('Balance',
                  canBalance ? 'live' : 'gated'),
              _scannerPill('Activity',
                  canActivity ? 'live' : 'gated'),
              const _ScannerPillNoSend(),
            ],
          ),
          if (onOpenAssetDetail != null) ...[
            const SizedBox(height: 10),
            OutlinedButton(
              key: const Key('crypto_vault_chat_scanner_open_xmr'),
              onPressed: () => onOpenAssetDetail!('XMR'),
              style: walletGhostButtonStyle(),
              child: Text(AppLocalizations.of(context).cryptoOpenMonero),
            ),
          ],
        ],
      ),
    );
  }
}


String _scannerHeadline(String reason, String scannerStatus) {
  if (reason == 'scanner_requires_desktop') {
    return 'Scanner requires the desktop app';
  }
  if (scannerStatus == 'ready') {
    return 'Scanner ready';
  }
  if (scannerStatus == 'syncing') {
    return 'Scanner syncing';
  }
  if (scannerStatus == 'unreachable' ||
      scannerStatus == 'unavailable') {
    return 'Scanner temporarily unavailable';
  }
  if (scannerStatus == 'ready_local_scanner_available') {
    return 'Local scanner available';
  }
  return 'Scanner not enabled';
}


String _scannerFallbackCopy(String reason, String scannerStatus) {
  if (reason == 'scanner_requires_desktop') {
    return 'Monero scanning requires the desktop app. On web, '
        'VaultAI cannot show your balance or activity.';
  }
  if (scannerStatus == 'ready') {
    return 'Balance and activity are available.';
  }
  if (scannerStatus == 'syncing') {
    return 'Wallet is catching up to the chain. Balance and '
        'activity will populate once sync completes.';
  }
  return 'Monero scanning is not enabled in this build. Balance '
      'and activity are gated until scanning is configured.';
}


Widget _scannerPill(String label, String state) {
  return Container(
    padding: const EdgeInsets.symmetric(
      horizontal: 8, vertical: 3,
    ),
    decoration: BoxDecoration(
      color: kWalletBgBase,
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: kWalletBorder),
    ),
    child: Text(
      '$label: $state',
      style: const TextStyle(
        color: kWalletTextMuted,
        fontSize: 11,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}


class _ScannerPillNoSend extends StatelessWidget {
  const _ScannerPillNoSend();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('crypto_vault_chat_scanner_no_send_pill'),
      padding: const EdgeInsets.symmetric(
        horizontal: 8, vertical: 3,
      ),
      decoration: BoxDecoration(
        color: kWalletBgBase,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: kWalletAccentWarning),
      ),
      child: const Text(
        'Send: disabled',
        style: TextStyle(
          color: kWalletAccentWarning,
          fontSize: 11,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}


class _ActivityCard extends StatefulWidget {
  final CryptoVaultChatCard card;
  final void Function(String asset)? onOpenAssetDetail;
  final CryptoActivityFetcher? onFetchActivity;
  final CryptoChatLiveCache? cache;
  const _ActivityCard({
    required this.card, this.onOpenAssetDetail,
    this.onFetchActivity, this.cache,
  });

  @override
  State<_ActivityCard> createState() => _ActivityCardState();
}


class _ActivityCardState extends State<_ActivityCard> {
  String? _liveStatus;
  String? _liveReason;
  List<Map<String, dynamic>>? _liveEntries;
  bool _fetchInFlight = false;

  @override
  void initState() {
    super.initState();
    _primeFromCache();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeFetch());
  }


  void _primeFromCache() {
    final cache = widget.cache;
    if (cache == null) return;
    final asset = widget.card.asset ?? '';
    if (asset.isEmpty || asset == 'XMR') return;
    const cacheAddress = '_activity_';
    final cached = cache.peek(
      type: kCryptoChatCacheRequestActivity,
      asset: asset, address: cacheAddress,
    );
    if (cached == null) return;
    _liveStatus = 'available';
    _liveReason = (cached['reason'] ?? '').toString();
    final rawEntries = cached['transactions'] ?? cached['entries'];
    _liveEntries = rawEntries is List
        ? rawEntries
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : <Map<String, dynamic>>[];
  }

  Future<void> _maybeFetch({bool bypassCache = false}) async {
    if (_fetchInFlight) return;
    final fetcher = widget.onFetchActivity;
    if (fetcher == null) return;
    final data = widget.card.data;
    final status = (data?['activityStatus'] ?? '').toString();
    final asset = widget.card.asset ?? '';


    if (status != 'pending_live_fetch' && !bypassCache) return;
    if (asset.isEmpty) return;
    if (asset == 'XMR') return;
    _fetchInFlight = true;
    try {
      final cache = widget.cache;
      const cacheAddress = '_activity_';
      final Future<Map<String, dynamic>> future;
      if (cache != null) {
        if (bypassCache) {
          cache.invalidate(
            type: kCryptoChatCacheRequestActivity,
            asset: asset, address: cacheAddress,
          );
        }
        future = cache.fetch(
          type:    kCryptoChatCacheRequestActivity,
          asset:   asset,
          address: cacheAddress,
          run: () =>
              fetcher(asset: asset, address: '', limit: 10),
        );
      } else {
        future = fetcher(asset: asset, address: '', limit: 10);
      }
      final res = await future;
      if (!mounted) return;
      setState(() {
        _liveStatus = 'available';
        _liveReason = (res['reason'] ?? '').toString();
        final rawEntries = res['transactions'] ?? res['entries'];
        if (rawEntries is List) {
          _liveEntries = rawEntries
              .whereType<Map>()
              .map((m) => m.cast<String, dynamic>())
              .toList();
        } else {
          _liveEntries = <Map<String, dynamic>>[];
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _liveStatus = 'unavailable';
        _liveReason = 'network_error';
      });
    } finally {
      _fetchInFlight = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final card = widget.card;
    final data = card.data;
    final backendStatus =
        (data?['activityStatus'] ?? '').toString();
    final backendReason = (data?['reason'] ?? '').toString();
    final effectiveStatus = _liveStatus ?? backendStatus;
    final effectiveReason = _liveReason?.isNotEmpty == true
        ? _liveReason!
        : backendReason;
    final entries = _liveEntries ?? const <Map<String, dynamic>>[];
    final asset = card.asset ?? '';

    return _shell(
      testKey: kCvcCardKeyActivity,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            asset.isNotEmpty
                ? 'Recent $asset activity'
                : 'Recent crypto activity',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (backendStatus == 'scanner_gated')
            Text(
              'Activity is gated by the Monero scanner. '
              '${effectiveReason.replaceAll('_', ' ')}',
              key: const Key(
                'crypto_vault_chat_activity_scanner_gated',
              ),
              style: kWalletBodyStyle,
            )
          else if (effectiveStatus == 'pending_live_fetch')
            const Text(
              'Loading recent transactions…',
              key: Key('crypto_vault_chat_activity_loading'),
              style: kWalletBodyStyle,
            )
          else if (effectiveStatus == 'unavailable') ...[
            Text(
              'Activity unavailable right now. '
              '${effectiveReason.isEmpty ? "" : "(${effectiveReason.replaceAll('_', ' ')})"}',
              key: const Key(
                'crypto_vault_chat_activity_unavailable',
              ),
              style: kWalletBodyStyle,
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              key: const Key('crypto_vault_chat_activity_retry'),
              onPressed: _fetchInFlight
                  ? null
                  : () => _maybeFetch(bypassCache: true),
              style: walletGhostButtonStyle(),
              child: const Text('Retry'),
            ),
          ]
          else if (_liveStatus == 'available' && entries.isEmpty)
            const Text(
              'No activity yet.',
              key: Key('crypto_vault_chat_activity_empty'),
              style: kWalletBodyStyle,
            )
          else if (_liveStatus == 'available' && entries.isNotEmpty)
            _buildEntriesList(entries)
          else
            const Text(
              'Open Crypto Vault to see real transaction history. '
              'VaultAI never invents activity.',
              style: kWalletBodyStyle,
            ),
        ],
      ),
    );
  }

  Widget _buildEntriesList(List<Map<String, dynamic>> entries) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final e in entries.take(10)) _activityRow(e),
        if (entries.length > 10) ...[
          const SizedBox(height: 4),
          Text(
            '+${entries.length - 10} more — open asset for full list',
            style: const TextStyle(
              color: kWalletTextMuted, fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ],
    );
  }

  Widget _activityRow(Map<String, dynamic> row) {
    final direction = (row['direction'] ?? '').toString();
    final status = (row['status'] ?? '').toString();
    final hashOrSig = (row['hash']
        ?? row['signature']
        ?? row['txid']
        ?? '').toString();
    final short = hashOrSig.length > 12
        ? '${hashOrSig.substring(0, 8)}…'
          '${hashOrSig.substring(hashOrSig.length - 4)}'
        : hashOrSig;
    return Padding(

      padding: const EdgeInsets.only(top: 4),
      child: Row(
        children: [
          Container(
            width: 8, height: 8,
            decoration: const BoxDecoration(
              color: kWalletTextMuted, shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              [
                if (direction.isNotEmpty) direction,
                if (status.isNotEmpty) status,
                if (short.isNotEmpty) short,
              ].join(' · '),
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: kWalletTextPrimary, fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}


class _SendDraftCard extends StatelessWidget {
  final CryptoVaultChatCard card;
  final VoidCallback? onOpenSendFlow;
  const _SendDraftCard({required this.card, this.onOpenSendFlow});

  @override
  Widget build(BuildContext context) {
    final asset     = card.asset     ?? '';
    final amount    = card.amount    ?? '';
    final recipient = card.recipient ?? '';
    final data = card.data;
    final network = (data?['network'] ?? '').toString();
    final xmrDisabled =
        (data?['sendDisabledReason'] ?? '').toString() ==
        'xmr_send_not_supported';

    return _shell(
      testKey: kCvcCardKeySendDraft,
      accent: kWalletAccentWarning,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).cryptoSendDraftHeading,
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          Text(
            'Send $amount $asset'
            '${recipient.isNotEmpty ? " to $recipient" : ""}',
            key: const Key('crypto_vault_chat_send_draft_summary'),
            style: kWalletBodyStyle,
          ),
          if (network.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              'Network: $network',
              style: const TextStyle(
                color: kWalletTextMuted, fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
          if (xmrDisabled) ...[
            const SizedBox(height: 6),
            const Text(
              'Monero send is disabled in VaultAI. This draft '
              'cannot be sent.',
              key: Key('crypto_vault_chat_send_xmr_disabled'),
              style: TextStyle(
                color: kWalletAccentWarning, fontSize: 12,
                fontWeight: FontWeight.w800,
              ),
            ),
          ] else ...[
            const SizedBox(height: 6),
            const Text(
              'This is only a draft. To send, open the asset, '
              'review the fee, unlock with your PIN, sign on this '
              'device, and confirm the broadcast.',
              style: kWalletMutedStyle,
            ),
          ],
          const SizedBox(height: 8),
          Wrap(
            spacing: 6, runSpacing: 6,
            children: [
              _sendSafetyPill('Trusted device'),
              _sendSafetyPill('PIN unlock'),
              _sendSafetyPill('Local signing'),
              _sendSafetyPill('Explicit confirmation'),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8, runSpacing: 6,
            children: [
              if (onOpenSendFlow != null && !xmrDisabled)
                OutlinedButton(
                  key: const Key(
                    'crypto_vault_chat_send_open_send_flow',
                  ),
                  onPressed: onOpenSendFlow,
                  style: walletGhostButtonStyle(),
                  child: Text(
                    AppLocalizations.of(context).cryptoOpenSendFlow,
                  ),
                ),
              Container(
                key: const Key(
                  'crypto_vault_chat_send_never_broadcasts',
                ),
                padding: const EdgeInsets.symmetric(
                  horizontal: 8, vertical: 4,
                ),
                decoration: BoxDecoration(
                  color: kWalletBgBase,
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: kWalletBorder),
                ),
                child: const Text(
                  'Chat cannot broadcast',
                  style: TextStyle(
                    color: kWalletTextMuted,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}


Widget _sendSafetyPill(String label) {
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(
      color: kWalletBgBase,
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: kWalletBorder),
    ),
    child: Text(
      label,
      style: const TextStyle(
        color: kWalletTextMuted,
        fontSize: 11,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}


class _ShowVaultCard extends StatefulWidget {
  final CryptoVaultChatCard? card;
  final VoidCallback? onOpenVault;
  final void Function(String asset)? onOpenAssetDetail;
  final CryptoBalanceFetcher? onFetchBalance;
  final CryptoChatLiveCache? cache;

  final bool cryptoEntitled;

  final VoidCallback? onOpenUpgrade;
  const _ShowVaultCard({
    this.card, this.onOpenVault, this.onOpenAssetDetail,
    this.onFetchBalance, this.cache,
    this.cryptoEntitled = true,
    this.onOpenUpgrade,
  });

  @override
  State<_ShowVaultCard> createState() => _ShowVaultCardState();
}


class _ShowVaultCardState extends State<_ShowVaultCard> {

  final Map<String, Map<String, dynamic>> _liveByAsset =
      <String, Map<String, dynamic>>{};

  @override
  void initState() {
    super.initState();
    _primeAllFromCache();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeFetchAll());
  }


  void _primeAllFromCache() {
    final cache = widget.cache;
    if (cache == null) return;
    final data = widget.card?.data;
    if (data == null) return;
    final assetsRaw = data['assets'];
    if (assetsRaw is! List) return;
    for (final raw in assetsRaw) {
      if (raw is! Map) continue;
      final row = raw.cast<String, dynamic>();
      final asset = (row['asset'] ?? '').toString();
      final address = (row['publicAddress'] ?? '').toString();
      if (asset.isEmpty || address.isEmpty) continue;
      if (asset == 'XMR') continue;
      final cached = cache.peek(
        type: kCryptoChatCacheRequestBalance,
        asset: asset, address: address,
      );
      if (cached == null) continue;
      _liveByAsset[asset] = <String, dynamic>{
        'balanceStatus':   (cached['balanceStatus'] ?? '').toString(),
        'availableAmount': cached['availableAmount']?.toString(),
        'unit':            (cached['unit']   ?? '').toString(),
        'reason':          (cached['reason'] ?? '').toString(),
      };
    }
  }

  Future<void> _maybeFetchAll({bool bypassCache = false}) async {
    final fetcher = widget.onFetchBalance;
    if (fetcher == null) return;
    final data = widget.card?.data;
    if (data == null) return;
    final assetsRaw = data['assets'];
    if (assetsRaw is! List) return;

    for (final raw in assetsRaw) {
      if (raw is! Map) continue;
      final row = raw.cast<String, dynamic>();
      final status = (row['balanceStatus'] ?? '').toString();
      final asset = (row['asset'] ?? '').toString();
      final address = (row['publicAddress'] ?? '').toString();


      if (status != 'pending_live_fetch') continue;
      if (asset.isEmpty || address.isEmpty) continue;

      if (asset == 'XMR') continue;

      unawaited(_fetchRow(fetcher, asset, address,
          bypassCache: bypassCache));
    }
  }

  Future<void> _fetchRow(
    CryptoBalanceFetcher fetcher, String asset, String address, {
    bool bypassCache = false,
  }) async {
    try {
      final cache = widget.cache;
      final Future<Map<String, dynamic>> future;
      if (cache != null) {
        if (bypassCache) {
          cache.invalidate(
            type:    kCryptoChatCacheRequestBalance,
            asset:   asset,
            address: address,
          );
        }
        future = cache.fetch(
          type:    kCryptoChatCacheRequestBalance,
          asset:   asset,
          address: address,
          run:     () => fetcher(asset: asset, address: address),
        );
      } else {
        future = fetcher(asset: asset, address: address);
      }
      final res = await future;
      if (!mounted) return;
      setState(() {
        _liveByAsset[asset] = <String, dynamic>{
          'balanceStatus':   (res['balanceStatus'] ?? '').toString(),
          'availableAmount': res['availableAmount']?.toString(),
          'unit':            (res['unit'] ?? '').toString(),
          'reason':          (res['reason'] ?? '').toString(),
        };
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _liveByAsset[asset] = <String, dynamic>{
          'balanceStatus': 'unavailable',
          'reason':        'network_error',
        };
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final card = widget.card;
    final data = card?.data;
    final available = data != null && data['available'] == true;
    final assetsRaw = data?['assets'];
    final assets = assetsRaw is List
        ? assetsRaw
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final xmrScannerStatus =
        (data?['xmrScannerStatus'] ?? '').toString();
    final xmrReason = (data?['xmrReason'] ?? '').toString();

    return _shell(
      testKey: kCvcCardKeyShowVault,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).sidebarCryptoVault,
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            const Text(
              'ETH, USDT ERC20, USDC ERC20, SOL, USDT TRC20, and '
              'XMR. Non-custodial: your keys, your coins.',
              style: kWalletBodyStyle,
            )
          else ...[
            for (final a in assets)
              _CryptoAssetRow(
                row: _mergeLive(a),
                onTap: widget.onOpenAssetDetail,
              ),
            if (xmrScannerStatus.isNotEmpty ||
                xmrReason.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                'Monero scanner: '
                '${xmrScannerStatus.isEmpty ? "not enabled" : xmrScannerStatus}'
                '${xmrReason.isEmpty ? "" : " · $xmrReason"}',
                key: const Key(
                  'crypto_vault_chat_show_vault_xmr_scanner',
                ),
                style: const TextStyle(
                  color: kWalletTextMuted, fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ],
          if (_hasFailedRows()) ...[
            const SizedBox(height: 8),
            OutlinedButton(
              key: const Key(
                'crypto_vault_chat_show_vault_retry_failed',
              ),
              onPressed: () => _retryFailedRows(),
              style: walletGhostButtonStyle(),
              child: Text(AppLocalizations.of(context).cryptoRetryFailed),
            ),
          ],
          if (_isLocked()) ...[

            const SizedBox(height: 10),
            Text(
              'Crypto Vault is not included in your current plan. '
              'Upgrade to unlock wallet addresses, seed phrases, and '
              'receive QR codes secured by your PIN.',
              key: const Key(
                'crypto_vault_chat_show_vault_upgrade_body',
              ),
              style: const TextStyle(
                color: kWalletTextMuted, fontSize: 12,
              ),
            ),
            const SizedBox(height: 10),
            OutlinedButton(
              key: const Key(
                'crypto_vault_chat_show_vault_upgrade_btn',
              ),
              onPressed: widget.onOpenUpgrade,
              style: walletGhostButtonStyle(),
              child: const Text(
                'Upgrade required',
              ),
            ),
          ] else if (widget.onOpenVault != null) ...[
            const SizedBox(height: 10),
            OutlinedButton(
              key: const Key(
                'crypto_vault_chat_show_vault_open_btn',
              ),
              onPressed: widget.onOpenVault,
              style: walletGhostButtonStyle(),
              child: Text(
                AppLocalizations.of(context).cryptoOpenCryptoVault,
              ),
            ),
          ],
        ],
      ),
    );
  }


  bool _hasFailedRows() {
    for (final entry in _liveByAsset.entries) {
      final status = entry.value['balanceStatus'];
      if (status == 'unavailable') return true;
    }
    return false;
  }


  /// Belt-and-braces entitlement check. The card is locked when EITHER
  /// the server payload says so (backend saw `user_tier != upgraded`)
  /// OR the client-side AppState billing snapshot lacks an active
  /// storage plan. Either signal alone triggers the upgrade CTA; a
  /// stale client snapshot cannot override a server "locked" verdict.
  bool _isLocked() {
    if (!widget.cryptoEntitled) return true;
    final data = widget.card?.data;
    if (data is Map<String, dynamic>) {
      if (data['locked'] == true) return true;
      if (data['entitlement'] == 'upgrade_required') return true;
    }
    return false;
  }


  Future<void> _retryFailedRows() async {
    final fetcher = widget.onFetchBalance;
    if (fetcher == null) return;
    final data = widget.card?.data;
    if (data == null) return;
    final assetsRaw = data['assets'];
    if (assetsRaw is! List) return;


    final failedAssets = <String>{};
    for (final entry in _liveByAsset.entries) {
      if (entry.value['balanceStatus'] == 'unavailable') {
        failedAssets.add(entry.key);
      }
    }
    for (final raw in assetsRaw) {
      if (raw is! Map) continue;
      final row = raw.cast<String, dynamic>();
      final asset = (row['asset'] ?? '').toString();
      final address = (row['publicAddress'] ?? '').toString();
      if (!failedAssets.contains(asset)) continue;
      if (asset.isEmpty || address.isEmpty) continue;
      if (asset == 'XMR') continue;
      unawaited(_fetchRow(fetcher, asset, address, bypassCache: true));
    }
  }


  Map<String, dynamic> _mergeLive(Map<String, dynamic> row) {
    final asset = (row['asset'] ?? '').toString();
    final live = _liveByAsset[asset];
    if (live == null) return row;
    final merged = <String, dynamic>{...row};
    final status = live['balanceStatus'];
    if (status is String && status.isNotEmpty) {
      merged['balanceStatus'] = status;
    }
    if (status == 'available'
        && live['availableAmount'] is String
        && (live['availableAmount'] as String).isNotEmpty) {
      final unit = (live['unit'] as String?)?.isNotEmpty == true
          ? live['unit'] as String
          : _defaultUnitFor(asset);
      merged['displayBalance'] =
          '${live['availableAmount']} $unit'.trim();
    }
    if (live['reason'] is String
        && (live['reason'] as String).isNotEmpty) {
      merged['reason'] = live['reason'];
    }
    return merged;
  }
}




class _CryptoAssetRow extends StatelessWidget {
  final Map<String, dynamic> row;
  final void Function(String asset)? onTap;
  const _CryptoAssetRow({required this.row, this.onTap});

  @override
  Widget build(BuildContext context) {
    final asset = (row['asset'] ?? '').toString();
    final label = (row['label'] ?? asset).toString();
    final network = (row['network'] ?? '').toString();
    final balanceStatus =
        (row['balanceStatus'] ?? '').toString();
    final receiveReady = row['receiveReady'] == true;
    final sendEnabled = row['sendEnabled'] == true;

    String balanceCopy;
    if (balanceStatus == 'available'
        && row['displayBalance'] is String
        && (row['displayBalance'] as String).isNotEmpty) {
      balanceCopy = row['displayBalance'] as String;
    } else if (balanceStatus == 'pending_live_fetch') {
      balanceCopy = 'balance loading';
    } else if (balanceStatus == 'scanner_gated') {
      balanceCopy = 'scanner gated';
    } else if (balanceStatus == 'requires_desktop') {
      balanceCopy = 'requires desktop';
    } else {
      balanceCopy = 'unavailable';
    }

    return Padding(
      key: Key('crypto_vault_chat_show_vault_row_$asset'),
      padding: const EdgeInsets.only(top: 6),
      child: InkWell(
        onTap: onTap == null ? null : () => onTap!(asset),
        borderRadius: BorderRadius.circular(6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Container(
              width: 28, height: 28,
              decoration: BoxDecoration(
                color: kWalletBgBase,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: kWalletBorder),
              ),
              alignment: Alignment.center,
              child: const Icon(
                Icons.currency_bitcoin,
                size: 16, color: kWalletTextMuted,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: kWalletTextPrimary,
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  Text(
                    [
                      if (network.isNotEmpty) network,
                      balanceCopy,
                      if (receiveReady) 'receive ✓',
                      if (!sendEnabled) 'send disabled',
                    ].join(' · '),
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: kWalletTextMuted,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}


class _UnrecognizedCard extends StatelessWidget {
  final CryptoVaultChatCard card;
  const _UnrecognizedCard({required this.card});

  @override
  Widget build(BuildContext context) {
    return _shell(
      testKey: kCvcCardKeyUnrecognized,
      child: Text(
        card.message ?? kCvcUnrecognizedCopy,
        style: const TextStyle(
          color: kWalletTextMuted, fontSize: 13, height: 1.4,
        ),
      ),
    );
  }
}
