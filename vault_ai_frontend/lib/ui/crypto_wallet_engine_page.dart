import 'dart:developer' as developer;

import 'package:flutter/foundation.dart' show kDebugMode, kIsWeb, kReleaseMode;
import 'package:flutter/material.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/asset_live_store.dart';
import 'responsive.dart' show vrDisplay;
import '../services/crypto_wallet_balance_reason.dart';
import '../services/crypto_wallet_dashboard_reason.dart';
import '../services/crypto_wallet_features.dart';
import '../services/evm_networks.dart';
import '../services/monero_scanner.dart';
import '../services/monero_wallet.dart';
import 'crypto_wallet_engine_asset_detail_page.dart';
import 'crypto_wallet_engine_design.dart';
import 'crypto_wallet_engine_receive_panel.dart';
import 'crypto_wallet_engine_security_page.dart';
import 'crypto_wallet_engine_send_panel.dart';
import 'crypto_wallet_engine_sheet_chrome.dart';
import 'crypto_wallet_engine_solana_receive_panel.dart';
import 'crypto_wallet_engine_tron_receive_panel.dart';
import 'crypto_wallet_engine_monero_receive_panel.dart';

const String kCryptoWalletEngineMainnetNotReadyKey =
    'crypto_wallet_engine_mainnet_not_ready';
const String kCryptoWalletEngineMainnetNotReadyMessage =
    'Ethereum Mainnet is not ready yet.';
const String kCryptoWalletEngineSendPausedKey =
    'crypto_wallet_engine_send_paused';
const String kCryptoWalletEngineSendPausedMessage =
    'Mainnet sending is temporarily paused.';

void _cryptoWalletCapabilityDiag(
  String branch,
  Map<String, Object?> data,
) {
  final payload =
      data.entries.map((entry) => '${entry.key}=${entry.value}').join(' ');
  if (kReleaseMode && !kIsWeb) return;
  // ignore: avoid_print
  print('[crypto-wallet-capability-diag] branch=$branch $payload');
}

const List<String> kCryptoWalletEngineAssets = [
  'ETH',
  'USDT_ERC20',
  'USDC_ERC20',
  'SOL',
  'USDT_TRC20',
  'XMR',
];

const Map<String, String> kCryptoWalletEngineAssetLabels = {
  'ETH': 'Ethereum',
  'USDT_ERC20': 'USDT (ERC20)',
  'USDC_ERC20': 'USDC (ERC20)',
  'SOL': 'Solana',
  'USDT_TRC20': 'USDT (TRC20)',
  'XMR': 'Monero',
};

const Map<String, String> kCryptoWalletEngineNetworkLabels = {
  'ETH': 'Ethereum',
  'USDT_ERC20': 'Ethereum ERC20',
  'USDC_ERC20': 'Ethereum ERC20',
  'SOL': 'Solana',
  'USDT_TRC20': 'Tron TRC20',
  'XMR': 'Monero',
};

String portfolioRowAssetName(String asset) {
  switch (asset) {
    case 'ETH':
      return 'Ethereum';
    case 'USDT_ERC20':
      return 'USDT';
    case 'USDC_ERC20':
      return 'USDC';
    case 'SOL':
      return 'Solana';
    case 'USDT_TRC20':
      return 'USDT';
    case 'XMR':
      return 'Monero';
  }
  return asset;
}

String? portfolioRowNetworkTag(String asset) {
  switch (asset) {
    case 'ETH':
      return 'Mainnet';
    case 'USDT_ERC20':
      return 'ERC20';
    case 'USDC_ERC20':
      return 'ERC20';
    case 'USDT_TRC20':
      return 'TRC20';
  }
  return null;
}

String portfolioUnavailableChipLabel(int count) {
  if (count <= 0) return '';
  if (count == 1) return '1 balance unavailable';
  return '$count balances unavailable';
}

const Set<String> kCryptoWalletEngineMainPageLiveAssets = {
  'ETH',
  'USDT_ERC20',
  'USDC_ERC20',
};

const List<String> kVaultBalanceSummaryAssets = [
  'ETH',
  'USDT_ERC20',
  'USDC_ERC20',
  'SOL',
  'USDT_TRC20',
];

const Set<String> kCryptoWalletEngineLaunchedAssets = {
  'ETH',
  'USDT_ERC20',
  'USDC_ERC20',
  'SOL',
  'USDT_TRC20',
  'XMR',
};

const Map<String, String> kCryptoWalletEngineFutureStateLabel =
    <String, String>{};

const Set<String> kAssetsWithLiveReceive = {
  'ETH',
  'USDT_ERC20',
  'USDC_ERC20',
};

const Set<String> kAssetsWithLiveSend = {
  'ETH',
  'USDT_ERC20',
  'USDC_ERC20',
};

const String kCryptoWalletEngineHeading = 'Svaultai Crypto Wallet';
const String kCryptoWalletEngineSubheading =
    'Your keys. Your crypto. Svaultai cannot move funds without your '
    'approval.';

const String kCryptoWalletEnginePortfolioLiveBalancesNoteMainnet =
    'Live balances shown from connected Mainnet networks.';
const String kCryptoWalletEnginePortfolioLiveBalancesNoteSepolia =
    'Testnet balances shown from connected test networks.';
const String kCryptoWalletEnginePortfolioNoWalletsBody =
    'Create wallets to view your Vault balance.';
const String kCryptoWalletEnginePortfolioHonestSubcopy =
    'Svaultai only shows real on-chain balances. No synthetic totals '
    'are displayed.';
const String kCryptoWalletEnginePortfolioBalancesUnavailable =
    'Live balances temporarily unavailable.';
const String kCryptoWalletEnginePortfolioActivityNote =
    'Transaction history is real when indexer is connected. Svaultai '
    'never invents activity.';

const String kCryptoWalletEngineFutureStateBody =
    'Wallet engine support for this asset is not live yet. No '
    'address, no balance, no transactions are shown.';

const Map<String, String> kCryptoWalletEngineFutureStateBodyByAsset =
    <String, String>{};

const String kCryptoWalletEngineReceiveNotReadyBanner =
    'Wallet engine not ready. The receive address ships in a later '
    'slice — there is no address to display yet.';

const String kCryptoWalletEngineSendNotReadyBanner =
    'Send is not yet supported. When the wallet engine ships send, '
    'the flow will build an unsigned draft, show a review screen, '
    'require your PIN, sign locally on this device, and broadcast '
    'the signed transaction. Tapping Send right now will never '
    'broadcast a transaction.';

const String kCryptoWalletEngineTransactionsEmptyBanner =
    'No transactions to display. Transaction history connects when '
    'the asset is wired to its RPC / indexer endpoint.';

const String kCryptoWalletEngineSavedRecordsHint =
    'Tip: Crypto Vault keeps your saved public addresses, encrypted '
    'backups, and manual notes alongside live wallet accounts. Switch '
    'to the Saved records tab below.';

const String kCryptoWalletEngineNonCustodialAttestation =
    'Non-custodial: your keys, your coins. Svaultai cannot move your '
    'funds.';

const String kCryptoWalletEnginePortfolioHeading = 'Vault balance';

const String kCryptoWalletEngineAssetsHeading = 'Stored assets';

const String kCryptoWalletEngineActivityHeading = 'Vault activity';

const String kCryptoWalletEngineActivityEmptyPrimary = 'No activity yet.';
const String kCryptoWalletEngineActivityEmptySubcopy =
    'Real transactions will appear here when activity history is '
    'connected.';
const String kCryptoWalletEngineActivityHonestSubcopy =
    'Svaultai never invents transaction history.';

const String kCryptoWalletEngineActivityHonestEmpty =
    kCryptoWalletEngineActivityEmptyPrimary;

const String kCryptoWalletEngineActivityIndexerMixedNote =
    'Activity history is not connected for every network yet.';

const String kCryptoWalletCardActivityEmpty = 'No activity yet';
const String kCryptoWalletCardActivityIndexerMissing =
    'Activity history not connected';
const String kCryptoWalletCardActivityProviderError =
    'Activity temporarily unavailable';
const String kCryptoWalletCardActivityXmrScannerMissing = 'Scanner not enabled';

@Deprecated('use kCryptoWalletCardActivityEmpty / '
    'kCryptoWalletCardActivityIndexerMissing / '
    'kCryptoWalletCardActivityProviderError / '
    'kCryptoWalletCardActivityXmrScannerMissing')
const String kCryptoWalletEngineAssetCardActivityUnavailableCompact =
    kCryptoWalletCardActivityIndexerMissing;

const String kCryptoWalletEngineBackupHeading = 'Security & Backup';
const String kCryptoWalletEngineBackupBody =
    'Your encrypted wallet backup lives in your vault. Backups stay '
    'ciphertext-only — Svaultai cannot decrypt them. Reveal flows ask '
    'for your PIN every time.';
const String kCryptoWalletEngineBackupOpenLabel = 'Open backup tools';

const String kCryptoWalletEngineNotesHeading = 'Wallet notes';
const String kCryptoWalletEngineNotesBody =
    'Wallet notes and manual transaction notes live in the saved '
    'records area. Use them for non-spendable references like '
    'addresses you watch or counterparty contacts.';
const String kCryptoWalletEngineNotesOpenLabel = 'Open wallet notes';

const String kCryptoWalletEngineAskAiHeading = 'Ask Svaultai';
const String kCryptoWalletEngineAskAiSubheading =
    'Ask Svaultai to drive the wallet for you. Sensitive actions '
    'still require your PIN and your on-screen confirmation.';

const List<String> kCryptoWalletEngineAskAiSuggestedPrompts = [
  'Show my ETH balance',
  'Give me my ETH receive QR',
  'Send 0.01 ETH on Sepolia',
  'Show my transactions',
  'Show my USDT ERC20 balance',
];

const String kCryptoWalletEnginePrimaryReceiveLabel = 'Receive';
const String kCryptoWalletEnginePrimarySendLabel = 'Send';
const String kCryptoWalletEnginePrimaryActivityLabel = 'Activity';
const String kCryptoWalletEnginePrimaryBackupLabel = 'Security';
const String kCryptoWalletEnginePrimarySecurityLabel = 'Security';

const String kCryptoWalletEngineSecurityHeading = 'Security';
const String kCryptoWalletEngineSecurityBody =
    'Wallet backups are encrypted. Svaultai cannot decrypt or move '
    'your funds.';
const String kCryptoWalletEngineSecurityOpenLabel = 'Open security';

class CryptoWalletEnginePage extends StatefulWidget {
  // 2026-07-12: onOpenLite parameter removed — CryptoVaultLitePage
  // is retired. The engine page is the sole Crypto Vault surface;
  // this parameter was never invoked from production callers
  // (guarded by test_crypto_wallet_engine_dashboard_cleanup CL13).
  final void Function(String prompt)? onSendChatPrompt;

  final String? authToken;
  final VaultAIClient? apiClient;
  final Future<String> Function(String plaintext)? encryptForVault;
  final bool Function()? isVaultKeyAvailable;

  final Future<String> Function(String ciphertext)? decryptForVault;
  final Future<bool> Function(String pin)? verifyPin;

  // 2026-07-13 network-scoped: production bug was that the ETH Send
  // path called a legacy /crypto/wallet/{asset}/receive endpoint which
  // queries the wallet row keyed by service='ETH', while the actual
  // mainnet ETH wallet is stored with service='ETH:ethereum_mainnet'
  // (see backend routes/crypto_wallet_routes.py:_service_key_for_network).
  // Balance/Receive already use the network-scoped endpoint; the Send
  // handlers here now pass the caller's effectiveNetwork so
  // loadFromAddress resolves the SAME wallet the balance/receive
  // path resolves.
  final Future<String?> Function(String network)? loadFromAddress;

  final MoneroWalletAdapter moneroWalletAdapter;
  final MoneroScannerAdapter moneroScannerAdapter;

  const CryptoWalletEnginePage({
    super.key,
    this.onSendChatPrompt,
    this.authToken,
    this.apiClient,
    this.encryptForVault,
    this.isVaultKeyAvailable,
    this.decryptForVault,
    this.verifyPin,
    this.loadFromAddress,
    this.moneroWalletAdapter = const NullMoneroWalletAdapter(),
    this.moneroScannerAdapter = const NullMoneroScannerAdapter(),
  });

  @override
  State<CryptoWalletEnginePage> createState() => _CryptoWalletEnginePageState();
}

class _CryptoWalletEnginePageState extends State<CryptoWalletEnginePage> {
  CryptoWalletFeatures? _features;

  final AssetLiveStore _liveStore = AssetLiveStore.instance;

  final GlobalKey _activitySectionKey =
      GlobalKey(debugLabel: 'crypto_wallet_engine_activity_section');

  @override
  void initState() {
    super.initState();
    _liveStore.addListener(_onLiveStoreChanged);
    _loadFeatures();
  }

  @override
  void dispose() {
    _liveStore.removeListener(_onLiveStoreChanged);
    super.dispose();
  }

  void _onLiveStoreChanged() {
    if (mounted) setState(() {});
  }

  Map<String, DashboardAssetLiveState> get _liveAssetState =>
      _liveStore.statesSnapshot;

  void _cvLog(String message) {
    if (!kDebugMode) return;
    developer.log(message, name: 'CryptoVault');
  }

  Future<void> _loadFeatures() async {
    if (widget.apiClient == null || widget.authToken == null) {
      _cvLog('features_skip apiClient_null='
          '${widget.apiClient == null} '
          'authToken_null=${widget.authToken == null}');
      return;
    }
    try {
      final body = await widget.apiClient!.getCryptoWalletFeatures(
        authToken: widget.authToken!,
      );
      if (!mounted) return;
      setState(() {
        _features = CryptoWalletFeatures.fromBackend(body);
      });
      final f = _features!;
      _cryptoWalletCapabilityDiag('features_loaded', {
        'mainnetSendEnabled': f.mainnetSendEnabled,
        'mainnetSendPaused': f.mainnetSendPaused,
        'effectiveMainnetSendEnabled': f.effectiveMainnetSendEnabled,
      });
      _cvLog(
        'features_loaded '
        'default_network=${f.effectiveDefaultNetwork} '
        'mainnet_receive=${f.mainnetReceiveEnabled} '
        'mainnet_erc20=${f.mainnetErc20ReceiveEnabled} '
        'solana=${f.solanaEnabled} '
        'tron=${f.tronEnabled} xmr=${f.xmrEnabled}',
      );

      _fanOutInitialLiveRefresh();
    } catch (e) {
      _cvLog('features_failed error=${e.runtimeType}');
      if (!mounted) return;
      setState(() {
        _features = null;
      });
    }
  }

  Future<void> _fanOutInitialLiveRefresh() async {
    final f = _features;
    if (f == null) {
      _cvLog('fanout_skip features_null=true');
      return;
    }
    final assets = dashboardAssetsForInitialLiveRefresh(f);
    _cvLog('fanout_start '
        'effective_network=$_effectiveNetwork '
        'assets=$assets');

    for (final asset in assets) {
      if (!mounted) return;
      await _refreshLiveAssetState(asset);
    }
    _cvLog('fanout_done assets=$assets');
  }

  Future<void> _refreshLiveAssetState(String asset) async {
    if (widget.apiClient == null || widget.authToken == null) {
      _cvLog('refresh_skip asset=$asset apiClient_null='
          '${widget.apiClient == null} '
          'authToken_null=${widget.authToken == null}');
      return;
    }
    if (!mounted) return;

    final routeNetwork = networkForAssetRoute(
      asset: asset,
      features: _features,
      effectiveMainnetNetwork: _effectiveNetwork,
    );

    final seq = _liveStore.claimSeq(asset);
    _liveStore.applyState(
      source: 'dashboard',
      asset: asset,
      seq: seq,
      state: const DashboardAssetLiveState.loading(),
      network: routeNetwork,
    );
    _cvLog('refresh_started asset=$asset network=$routeNetwork '
        'seq=$seq');

    final result = await loadAssetWalletState(
      apiClient: widget.apiClient!,
      authToken: widget.authToken!,
      network: routeNetwork,
      asset: asset,
    );
    if (!mounted) return;

    _liveStore.applyState(
      source: 'dashboard',
      asset: asset,
      seq: seq,
      state: result,
      network: routeNetwork,
    );
    _cvLog('refresh_done asset=$asset kind=${result.kind.name} seq=$seq');
  }

  String get _effectiveNetwork {
    final f = _features;
    if (f != null &&
        f.defaultNetwork.isNotEmpty &&
        f.defaultNetworkConfigValid) {
      return f.effectiveDefaultNetwork;
    }
    return kCompileTimeDefaultNetworkResolved;
  }

  bool get _isMainnetActive => _effectiveNetwork == kEvmNetworkEthereumMainnet;

  bool get _mainnetNotReady {
    if (!_isMainnetActive) return false;
    final f = _features;
    if (f == null) return false;
    if (!f.defaultNetworkConfigValid) return true;
    if (!f.mainnetReceiveEnabled) return true;
    return false;
  }

  bool get _sendPausedForActive {
    final f = _features;
    if (f == null) return false;
    if (_isMainnetActive) return f.mainnetSendPaused;
    return false;
  }

  bool get _sendEnabledForActive {
    final f = _features;
    if (f == null) return false;
    if (_isMainnetActive) return f.effectiveMainnetSendEnabled;
    return false;
  }

  @override
  Widget build(BuildContext context) {
    return _CryptoWalletEnginePageBody(
      onSendChatPrompt: widget.onSendChatPrompt,
      authToken: widget.authToken,
      apiClient: widget.apiClient,
      encryptForVault: widget.encryptForVault,
      isVaultKeyAvailable: widget.isVaultKeyAvailable,
      decryptForVault: widget.decryptForVault,
      verifyPin: widget.verifyPin,
      loadFromAddress: widget.loadFromAddress,
      effectiveNetwork: _effectiveNetwork,
      isMainnetActive: _isMainnetActive,
      mainnetNotReady: _mainnetNotReady,
      sendEnabled: _sendEnabledForActive,
      sendPaused: _sendPausedForActive,
      features: _features,
      onFeatureRefreshRequested: _loadFeatures,
      liveAssetState: Map<String, DashboardAssetLiveState>.unmodifiable(
        _liveAssetState,
      ),
      onAssetLiveRefreshRequested: _refreshLiveAssetState,
      moneroWalletAdapter: widget.moneroWalletAdapter,
      moneroScannerAdapter: widget.moneroScannerAdapter,
      activitySectionKey: _activitySectionKey,
    );
  }
}

class _CryptoWalletEnginePageBody extends StatelessWidget {
  final void Function(String prompt)? onSendChatPrompt;

  final String? authToken;
  final VaultAIClient? apiClient;
  final Future<String> Function(String plaintext)? encryptForVault;
  final bool Function()? isVaultKeyAvailable;

  final Future<String> Function(String ciphertext)? decryptForVault;
  final Future<bool> Function(String pin)? verifyPin;
  // 2026-07-13: network-scoped signature — see notes on the public
  // widget's field of the same name.
  final Future<String?> Function(String network)? loadFromAddress;

  final String effectiveNetwork;
  final bool isMainnetActive;
  final bool mainnetNotReady;
  final bool sendEnabled;
  final bool sendPaused;
  final CryptoWalletFeatures? features;
  final Future<void> Function()? onFeatureRefreshRequested;
  final Map<String, DashboardAssetLiveState> liveAssetState;
  final Future<void> Function(String asset)? onAssetLiveRefreshRequested;
  final MoneroWalletAdapter moneroWalletAdapter;
  final MoneroScannerAdapter moneroScannerAdapter;

  final Key activitySectionKey;

  const _CryptoWalletEnginePageBody({
    this.onSendChatPrompt,
    this.authToken,
    this.apiClient,
    this.encryptForVault,
    this.isVaultKeyAvailable,
    this.decryptForVault,
    this.verifyPin,
    this.loadFromAddress,
    required this.effectiveNetwork,
    required this.isMainnetActive,
    required this.mainnetNotReady,
    required this.sendEnabled,
    required this.sendPaused,
    required this.features,
    this.onFeatureRefreshRequested,
    this.liveAssetState = const <String, DashboardAssetLiveState>{},
    this.onAssetLiveRefreshRequested,
    required this.moneroWalletAdapter,
    required this.moneroScannerAdapter,
    Key? activitySectionKey,
  }) : activitySectionKey = activitySectionKey ??
            const Key('crypto_wallet_engine_activity_section');

  bool get _hasReceiveWiring =>
      authToken != null &&
      apiClient != null &&
      encryptForVault != null &&
      isVaultKeyAvailable != null;

  bool asset_solanaLive() => features?.solanaEnabled ?? false;

  bool asset_tronLive() => features?.tronEnabled ?? false;

  bool asset_moneroLive() => features?.xmrEnabled ?? false;

  bool get _hasSendWiring =>
      _hasReceiveWiring && decryptForVault != null && loadFromAddress != null;

  void _openReceivePanel(BuildContext ctx, String assetForPanel) {
    if (!_hasReceiveWiring) {
      _showNotReadyBanner(ctx, kCryptoWalletEngineReceiveNotReadyBanner);
      return;
    }
    final isSolanaAsset =
        assetForPanel == 'SOL' && (features?.solanaEnabled ?? false);
    final isTronAsset =
        assetForPanel == 'USDT_TRC20' && (features?.tronEnabled ?? false);
    final isMoneroAsset =
        assetForPanel == 'XMR' && (features?.xmrEnabled ?? false);
    if (!isSolanaAsset && !isTronAsset && !isMoneroAsset && mainnetNotReady) {
      _showNotReadyBanner(
        ctx,
        kCryptoWalletEngineMainnetNotReadyMessage,
      );
      return;
    }
    final String sheetTitle = isTronAsset
        ? 'Receive USDT (TRC20)'
        : isSolanaAsset
            ? 'Receive SOL'
            : isMoneroAsset
                ? 'Receive XMR'
                : 'Receive $assetForPanel';
    showCryptoWalletSheet<void>(
      context: ctx,
      title: sheetTitle,
      sheetKey: 'crypto_wallet_engine_receive_sheet',
      child: isSolanaAsset
          ? CryptoWalletEngineSolanaReceivePanel(
              key: const Key('solana_receive_panel_SOL'),
              authToken: authToken!,
              client: apiClient!,
              encryptForVault: encryptForVault!,
              isVaultKeyAvailable: isVaultKeyAvailable!,
              features: features,
            )
          : isTronAsset
              ? CryptoWalletEngineTronReceivePanel(
                  key: const Key('tron_receive_panel_USDT_TRC20'),
                  authToken: authToken!,
                  client: apiClient!,
                  encryptForVault: encryptForVault!,
                  isVaultKeyAvailable: isVaultKeyAvailable!,
                  features: features,
                )
              : isMoneroAsset
                  ? CryptoWalletEngineMoneroReceivePanel(
                      key: const Key('monero_receive_panel_XMR'),
                      authToken: authToken!,
                      client: apiClient!,
                      features: features,
                      walletAdapter: moneroWalletAdapter,
                      encryptForVault: encryptForVault,
                      isVaultKeyAvailable: isVaultKeyAvailable,
                    )
                  : CryptoWalletEngineReceivePanel(
                      key: Key('eth_receive_panel_$assetForPanel'),
                      authToken: authToken!,
                      client: apiClient!,
                      encryptForVault: encryptForVault!,
                      isVaultKeyAvailable: isVaultKeyAvailable!,
                      asset: assetForPanel,
                      network: effectiveNetwork,
                    ),
    ).whenComplete(() {
      onFeatureRefreshRequested?.call();
      onAssetLiveRefreshRequested?.call(assetForPanel);
    });
  }

  // Compact label for send-sheet titles — collapses long asset IDs
  // to short symbols so the sheet header reads "Send USDT" instead of
  // "Send USDT_ERC20".
  String _shortAssetLabel(String asset) {
    switch (asset) {
      case 'USDT_ERC20':
        return 'USDT';
      case 'USDC_ERC20':
        return 'USDC';
      case 'USDT_TRC20':
        return 'USDT (TRC20)';
    }
    return asset;
  }

  Future<void> _openSendPanel(
    BuildContext ctx,
    String assetForPanel,
  ) async {
    if (!_hasSendWiring) {
      _showNotReadyBanner(ctx, kCryptoWalletEngineSendNotReadyBanner);
      return;
    }
    if (mainnetNotReady) {
      _showNotReadyBanner(
        ctx,
        kCryptoWalletEngineMainnetNotReadyMessage,
      );
      return;
    }
    if (sendPaused) {
      _showNotReadyBanner(
        ctx,
        kCryptoWalletEngineSendPausedMessage,
      );
      return;
    }
    // 2026-07-13 fix: pass the effectiveNetwork so the callback hits
    // the SAME network-scoped wallet-lookup endpoint the balance /
    // receive paths use. Previously loadFromAddress was ()->Future,
    // and the provider called the legacy /crypto/wallet/ETH/receive
    // endpoint that queries service='ETH' — but the mainnet ETH
    // wallet is persisted with service='ETH:ethereum_mainnet', so an
    // existing wallet with a live balance was reported as missing.
    final fromAddress = await loadFromAddress!(effectiveNetwork);
    if (fromAddress == null || fromAddress.isEmpty) {
      _showNotReadyBanner(
        ctx,
        'No Ethereum wallet exists yet. Tap Receive on the ETH '
        'card to create one before sending.',
      );
      return;
    }
    if (!ctx.mounted) return;
    showCryptoWalletSheet<void>(
      context: ctx,
      title: 'Send ${_shortAssetLabel(assetForPanel)}',
      sheetKey: 'crypto_wallet_engine_send_sheet',
      bodyOwnsLayout: true,
      child: CryptoWalletEngineSendPanel(
        key: Key('eth_send_panel_$assetForPanel'),
        authToken: authToken!,
        fromAddress: fromAddress,
        client: apiClient!,
        decryptForVault: decryptForVault!,
        isVaultKeyAvailable: isVaultKeyAvailable!,
        verifyPin: verifyPin,
        asset: assetForPanel,
        network: effectiveNetwork,
        mainnetSendEnabled: sendEnabled,
        mainnetSendPaused: sendPaused,
      ),
    );
  }

  void _showNotReadyBanner(BuildContext ctx, String message) {
    ScaffoldMessenger.of(ctx).showSnackBar(
      SnackBar(
        key: const Key('crypto_wallet_engine_not_ready_snackbar'),
        content: Text(message, maxLines: 4),
        duration: const Duration(seconds: 4),
      ),
    );
  }

  void _scrollActivityIntoView() {
    final k = activitySectionKey;
    if (k is! GlobalKey) return;
    final ctx = k.currentContext;
    if (ctx == null) return;
    Scrollable.ensureVisible(
      ctx,
      duration: const Duration(milliseconds: 320),
      curve: Curves.easeOutCubic,
      alignment: 0.1,
    );
  }

  void _openAssetDetail(BuildContext ctx, String asset) {
    final networkForDetail = networkForAssetRoute(
      asset: asset,
      features: features,
      effectiveMainnetNetwork: effectiveNetwork,
    );
    Navigator.of(ctx)
        .push<void>(
      MaterialPageRoute(
        builder: (_) => CryptoWalletEngineAssetDetailPage(
          asset: asset,
          authToken: authToken,
          apiClient: apiClient,
          encryptForVault: encryptForVault,
          isVaultKeyAvailable: isVaultKeyAvailable,
          decryptForVault: decryptForVault,
          verifyPin: verifyPin,
          loadFromAddress: loadFromAddress,
          network: networkForDetail,
          features: features,
          moneroWalletAdapter: moneroWalletAdapter,
          moneroScannerAdapter: moneroScannerAdapter,
        ),
      ),
    )
        .then((_) {
      onFeatureRefreshRequested?.call();

      onAssetLiveRefreshRequested?.call(asset);
    });
  }

  @override
  Widget build(BuildContext context) {
    final isMobile = MediaQuery.of(context).size.width < 700;
    return Container(
      key: kWalletPageBackgroundKey,
      decoration: walletPageBackground(),
      child: DefaultTextStyle.merge(
        style: const TextStyle(color: kWalletTextPrimary),
        child: IconTheme.merge(
          data: const IconThemeData(color: kWalletTextSecondary),
          // 2026-07-14 (Round 7 hardening): pull-to-refresh on the
          // vault summary/dashboard. Fires every asset's live-state
          // refresh via the existing callback wire — same source of
          // truth as the asset-detail Balance card.
          child: RefreshIndicator(
            key: const Key('crypto_wallet_engine_page_refresh_indicator'),
            onRefresh: () async {
              final cb = onAssetLiveRefreshRequested;
              if (cb == null) return;
              for (final asset in kCryptoWalletEngineAssets) {
                try {
                  await cb(asset);
                } catch (_) {
                  // Fail-open per asset — one asset's RPC hiccup
                  // must not block the others' refresh.
                }
              }
            },
            child: SingleChildScrollView(
              key: const Key('crypto_wallet_engine_page'),
              physics: const AlwaysScrollableScrollPhysics(),
              padding: EdgeInsets.all(isMobile ? 14 : 22),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1100),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _buildHeader(),
                      const SizedBox(height: 12),
                      _buildChipRow(),
                      _buildMainnetNotReadyBanner(),
                      _buildSendPausedBanner(),
                      const SizedBox(height: 16),
                      _buildPortfolioSummary(context),
                      const SizedBox(height: 14),
                      _buildPrimaryActionRow(context),
                      const SizedBox(height: 22),
                      _buildAssetsHeading(),
                      const SizedBox(height: 10),
                      _buildAssetGrid(context, isMobile),
                      const SizedBox(height: 22),
                      _buildActivitySection(),
                      const SizedBox(height: 12),
                      _buildSecuritySection(context),
                      const SizedBox(height: 12),
                      _buildAskAiSection(context),
                      const SizedBox(height: 18),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          kCryptoWalletEngineHeading,
          key: Key('crypto_wallet_engine_heading'),
          style: kWalletHeadingStyle,
        ),
        const SizedBox(height: 6),
        const Text(
          kCryptoWalletEngineSubheading,
          key: Key('crypto_wallet_engine_subheading'),
          style: kWalletSubheadingStyle,
        ),
      ],
    );
  }

  Widget _buildChipRow() {
    final label = isMainnetActive
        ? kEvmNetworkMainnetDashboardChipLabel
        : kEvmNetworkSepoliaDashboardChipLabel;
    return Wrap(
      key: const Key('crypto_wallet_engine_network_badge'),
      spacing: 8,
      runSpacing: 8,
      children: [
        walletStatusBadge(
          label,
          tone: isMainnetActive
              ? WalletBadgeTone.mainnet
              : WalletBadgeTone.testnet,
          key: const Key('crypto_wallet_engine_chip_testnet'),
        ),
        walletStatusBadge(
          'Non-custodial',
          tone: WalletBadgeTone.live,
          key: const Key('crypto_wallet_engine_chip_non_custodial'),
        ),
      ],
    );
  }

  Widget _buildMainnetNotReadyBanner() {
    if (!mainnetNotReady) return const SizedBox.shrink();
    return Container(
      key: const Key(kCryptoWalletEngineMainnetNotReadyKey),
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(12),
      decoration: walletWarningPanel(),
      child: Row(
        children: const [
          Icon(Icons.warning_amber_rounded,
              size: 18, color: kWalletAccentWarning),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              kCryptoWalletEngineMainnetNotReadyMessage,
              style: TextStyle(
                color: kWalletAccentWarning,
                fontSize: 13,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSendPausedBanner() {
    _cryptoWalletCapabilityDiag('top_banner', {
      'mainnetSendEnabled': features?.mainnetSendEnabled ?? false,
      'mainnetSendPaused': features?.mainnetSendPaused ?? false,
      'effectiveMainnetSendEnabled':
          features?.effectiveMainnetSendEnabled ?? false,
      'reason': sendPaused ? 'mainnet_send_paused' : 'none',
    });
    if (!sendPaused) return const SizedBox.shrink();
    return Container(
      key: const Key(kCryptoWalletEngineSendPausedKey),
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(12),
      decoration: walletWarningPanel(),
      child: Row(
        children: const [
          Icon(Icons.pause_circle_outline_rounded,
              size: 18, color: kWalletAccentWarning),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              kCryptoWalletEngineSendPausedMessage,
              style: TextStyle(
                color: kWalletAccentWarning,
                fontSize: 13,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPortfolioSummary(BuildContext context) {
    final availableRows = <_PortfolioBalanceRow>[];
    bool anyLoading = false;
    int erroredCount = 0;
    for (final asset in kVaultBalanceSummaryAssets) {
      final s = liveAssetState[asset];
      if (s == null) continue;
      switch (s.kind) {
        case DashboardAssetLiveStateKind.loading:
          anyLoading = true;
          break;
        case DashboardAssetLiveStateKind.available:
          availableRows.add(_PortfolioBalanceRow(
            asset: asset,
            amount: s.balanceAmount ?? '0',
            unit: (s.balanceUnit != null && s.balanceUnit!.isNotEmpty)
                ? s.balanceUnit!
                : walletBalanceUnitLabel(asset),
          ));
          break;
        case DashboardAssetLiveStateKind.reason:
          erroredCount++;
          break;
        case DashboardAssetLiveStateKind.noWallet:
          break;
      }
    }

    final hasAvailable = availableRows.isNotEmpty;
    final anyErrored = erroredCount > 0;

    return Container(
      key: const Key('crypto_wallet_engine_portfolio_summary'),
      padding: const EdgeInsets.all(18),
      decoration: walletDarkCard(accent: kWalletAccentPrimary),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      kWalletAccentPrimary,
                      Color.alphaBlend(
                        Colors.black.withOpacity(0.35),
                        kWalletAccentPrimary,
                      ),
                    ],
                  ),
                ),
                alignment: Alignment.center,
                child: const Icon(
                  Icons.pie_chart_rounded,
                  size: 16,
                  color: Colors.white,
                ),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  kCryptoWalletEnginePortfolioHeading,
                  style: kWalletSectionHeadingStyle,
                ),
              ),
              const Icon(
                Icons.lock_outline,
                size: 14,
                color: kWalletTextMuted,
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (hasAvailable) ...[
            Column(
              key: const Key(
                'crypto_wallet_engine_portfolio_balance_list',
              ),
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final row in availableRows) _buildPortfolioBalanceRow(row),
              ],
            ),
            if (anyErrored) ...[
              const SizedBox(height: 10),
              _buildPortfolioUnavailableChip(erroredCount),
            ],
          ] else if (anyLoading) ...[
            Column(
              key: const Key(
                'crypto_wallet_engine_portfolio_balance_skeleton',
              ),
              children: List.generate(
                3,
                (_) => _buildPortfolioSkeletonRow(),
              ),
            ),
          ] else ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  '—',
                  key: const Key(
                    'crypto_wallet_engine_portfolio_total_dash',
                  ),
                  style: TextStyle(
                    color: kWalletTextPrimary,
                    fontSize: vrDisplay(context),
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.5,
                    height: 1.0,
                  ),
                ),
                const SizedBox(width: 8),
                const Flexible(
                  child: Padding(
                    padding: EdgeInsets.only(bottom: 4),
                    child: Text(
                      'no synthetic USD total',
                      style: kWalletMutedStyle,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            const Text(
              kCryptoWalletEnginePortfolioNoWalletsBody,
              key: Key('crypto_wallet_engine_portfolio_no_wallets_body'),
              style: kWalletBodyStyle,
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildPortfolioBalanceRow(_PortfolioBalanceRow row) {
    final assetName = portfolioRowAssetName(row.asset);
    final networkTag = portfolioRowNetworkTag(row.asset);
    return Padding(
      key: Key(
        'crypto_wallet_engine_portfolio_balance_row_${row.asset}',
      ),
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Flexible(
            child: RichText(
              overflow: TextOverflow.ellipsis,
              text: TextSpan(
                children: [
                  TextSpan(
                    text: assetName,
                    style: const TextStyle(
                      color: kWalletTextPrimary,
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (networkTag != null)
                    TextSpan(
                      text: '  ·  $networkTag',
                      style: const TextStyle(
                        color: kWalletTextMuted,
                        fontSize: 12,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Container(
              height: 1,
              color: kWalletBorder,
            ),
          ),
          const SizedBox(width: 10),
          Text(
            '${row.amount} ${row.unit}',
            key: Key(
              'crypto_wallet_engine_portfolio_balance_amount_${row.asset}',
            ),
            style: const TextStyle(
              color: kWalletTextPrimary,
              fontSize: 14,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPortfolioUnavailableChip(int count) {
    return Container(
      key: const Key('crypto_wallet_engine_portfolio_unavailable_chip'),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: kWalletAccentWarning.withOpacity(0.10),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(
          color: kWalletAccentWarning.withOpacity(0.35),
          width: 1,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(
            Icons.info_outline_rounded,
            size: 14,
            color: kWalletAccentWarning,
          ),
          const SizedBox(width: 6),
          Text(
            portfolioUnavailableChipLabel(count),
            style: const TextStyle(
              color: kWalletAccentWarning,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPortfolioSkeletonRow() {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Container(
            width: 60,
            height: 10,
            decoration: BoxDecoration(
              color: kWalletBorder,
              borderRadius: BorderRadius.circular(4),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Container(
              height: 1,
              color: kWalletBorder,
            ),
          ),
          const SizedBox(width: 8),
          Container(
            width: 48,
            height: 10,
            decoration: BoxDecoration(
              color: kWalletBorder,
              borderRadius: BorderRadius.circular(4),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPrimaryActionRow(BuildContext ctx) {
    return Wrap(
      key: const Key('crypto_wallet_engine_primary_actions'),
      spacing: 10,
      runSpacing: 10,
      children: [
        ElevatedButton.icon(
          key: const Key('crypto_wallet_engine_primary_receive_btn'),
          onPressed: () {
            if (_hasReceiveWiring) {
              _openReceivePanel(ctx, 'ETH');
            } else {
              _showNotReadyBanner(
                ctx,
                kCryptoWalletEngineReceiveNotReadyBanner,
              );
            }
          },
          icon: const Icon(Icons.south_rounded, size: 16),
          label: const Text(kCryptoWalletEnginePrimaryReceiveLabel),
          style: walletPrimaryButtonStyle(),
        ),
        ElevatedButton.icon(
          key: const Key('crypto_wallet_engine_primary_send_btn'),
          onPressed: () {
            if (_hasSendWiring) {
              _openSendPanel(ctx, 'ETH');
            } else {
              _showNotReadyBanner(
                ctx,
                kCryptoWalletEngineSendNotReadyBanner,
              );
            }
          },
          icon: const Icon(Icons.north_rounded, size: 16),
          label: const Text(kCryptoWalletEnginePrimarySendLabel),
          style: walletSecondaryButtonStyle(),
        ),
        OutlinedButton.icon(
          key: const Key('crypto_wallet_engine_primary_activity_btn'),
          onPressed: () => _scrollActivityIntoView(),
          icon: const Icon(Icons.history_rounded, size: 16),
          label: const Text(kCryptoWalletEnginePrimaryActivityLabel),
          style: walletGhostButtonStyle(),
        ),
        OutlinedButton.icon(
          key: const Key('crypto_wallet_engine_primary_backup_btn'),
          onPressed: () => _openSecurityPage(ctx),
          icon: const Icon(Icons.shield_outlined, size: 16),
          label: const Text(kCryptoWalletEnginePrimarySecurityLabel),
          style: walletGhostButtonStyle(),
        ),
      ],
    );
  }

  Widget _buildAssetsHeading() {
    return Row(
      key: const Key('crypto_wallet_engine_assets_heading'),
      children: const [
        Text(
          kCryptoWalletEngineAssetsHeading,
          style: kWalletSectionHeadingStyle,
        ),
      ],
    );
  }

  Widget _buildAssetGrid(BuildContext ctx, bool isMobile) {
    final cols = isMobile ? 1 : 2;
    final solanaLive = asset_solanaLive();
    final tronLive = asset_tronLive();
    final moneroLive = asset_moneroLive();
    return LayoutBuilder(
      builder: (context, constraints) {
        return Wrap(
          key: const Key('crypto_wallet_engine_asset_grid'),
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final asset in kCryptoWalletEngineAssets)
              SizedBox(
                width: (constraints.maxWidth - (cols - 1) * 12) / cols,
                child: () {
                  final capability = dashboardAssetActionCapability(
                    asset: asset,
                    features: features,
                    hasReceiveWiring: _hasReceiveWiring,
                    hasSendWiring: _hasSendWiring,
                  );
                  final reason = dashboardAssetBalanceReason(
                    asset: asset,
                    features: features,
                  );
                  final live = liveAssetState[asset];
                  return _CryptoWalletEngineAssetCard(
                    asset: asset,
                    solanaLive: solanaLive,
                    tronLive: tronLive,
                    moneroLive: moneroLive,
                    balanceReason: reason,
                    featuresLoaded: features != null,
                    capability: capability,
                    liveState: live,
                    features: features,
                    onCardTap: kCryptoWalletEngineLaunchedAssets.contains(asset)
                        ? () => _openAssetDetail(ctx, asset)
                        : null,
                    onReceive: capability.receive
                        ? () => _openReceivePanel(ctx, asset)
                        : null,
                    onSend: capability.send
                        ? () => _openSendPanel(ctx, asset)
                        : null,
                    onTransactions: capability.transactions
                        ? () => _openAssetDetail(ctx, asset)
                        : null,
                  );
                }(),
              ),
          ],
        );
      },
    );
  }

  Widget _buildActivitySection() {
    return KeyedSubtree(
      key: activitySectionKey,
      child: Container(
        key: const Key('crypto_wallet_engine_activity_section'),
        padding: const EdgeInsets.all(16),
        decoration: walletDarkCard(),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: const [
                Icon(Icons.history_rounded,
                    size: 18, color: kWalletTextSecondary),
                SizedBox(width: 8),
                Text(
                  kCryptoWalletEngineActivityHeading,
                  style: kWalletSectionHeadingStyle,
                ),
              ],
            ),
            const SizedBox(height: 10),
            const Text(
              kCryptoWalletEngineActivityEmptyPrimary,
              key: Key('crypto_wallet_engine_activity_empty_primary'),
              style: kWalletBodyStyle,
            ),
            const SizedBox(height: 6),
            const Text(
              kCryptoWalletEngineActivityEmptySubcopy,
              key: Key('crypto_wallet_engine_activity_empty_subcopy'),
              style: kWalletMutedStyle,
            ),
            const SizedBox(height: 6),
            const Text(
              kCryptoWalletEngineActivityHonestSubcopy,
              key: Key('crypto_wallet_engine_activity_honest_subcopy'),
              style: kWalletMutedStyle,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSecuritySection(BuildContext ctx) {
    return Container(
      key: const Key('crypto_wallet_engine_security_section'),
      padding: const EdgeInsets.all(16),
      decoration: walletDarkCard(accent: kWalletAccentSuccess),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.shield_outlined,
                  size: 18, color: kWalletAccentSuccess),
              SizedBox(width: 8),
              Text(
                kCryptoWalletEngineSecurityHeading,
                style: kWalletSectionHeadingStyle,
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            kCryptoWalletEngineSecurityBody,
            style: kWalletBodyStyle,
          ),
          const SizedBox(height: 12),
          ElevatedButton.icon(
            key: const Key('crypto_wallet_engine_security_open_btn'),
            onPressed: () => _openSecurityPage(ctx),
            icon: const Icon(Icons.shield_outlined, size: 16),
            label: const Text(kCryptoWalletEngineSecurityOpenLabel),
            style: walletSecondaryButtonStyle(),
          ),
        ],
      ),
    );
  }

  void _openSecurityPage(BuildContext ctx) {
    Navigator.of(ctx).push<void>(
      MaterialPageRoute<void>(
        settings: const RouteSettings(
          name: 'crypto_wallet_engine_security_page',
        ),
        builder: (_) => const CryptoWalletEngineSecurityPage(),
      ),
    );
  }

  Widget _buildAskAiSection(BuildContext ctx) {
    return Container(
      key: const Key('crypto_wallet_engine_ask_ai_section'),
      padding: const EdgeInsets.all(16),
      decoration: walletDarkCard(accent: kWalletAccentPrimarySoft),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.auto_awesome_rounded,
                  size: 18, color: kWalletAccentPrimarySoft),
              SizedBox(width: 8),
              Text(
                kCryptoWalletEngineAskAiHeading,
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                  color: kWalletAccentPrimarySoft,
                  letterSpacing: 0.1,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            kCryptoWalletEngineAskAiSubheading,
            style: kWalletBodyStyle,
          ),
          const SizedBox(height: 12),
          Wrap(
            key: const Key('crypto_wallet_engine_ask_ai_prompts'),
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final prompt in kCryptoWalletEngineAskAiSuggestedPrompts)
                ActionChip(
                  key: Key(
                    'crypto_wallet_engine_ask_ai_prompt_'
                    '${prompt.hashCode}',
                  ),
                  label: Text(
                    prompt,
                    style: const TextStyle(color: kWalletTextPrimary),
                  ),
                  backgroundColor: kWalletSurfaceElevated,
                  side: const BorderSide(color: kWalletBorder),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(999),
                    side: const BorderSide(color: kWalletBorder),
                  ),
                  onPressed: () {
                    if (onSendChatPrompt != null) {
                      onSendChatPrompt!(prompt);
                    } else {
                      _showNotReadyBanner(
                        ctx,
                        'Open the chat from the side menu to ask: '
                        '"$prompt".',
                      );
                    }
                  },
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PortfolioBalanceRow {
  final String asset;
  final String amount;
  final String unit;
  const _PortfolioBalanceRow({
    required this.asset,
    required this.amount,
    required this.unit,
  });
}

class _CryptoWalletEngineAssetCard extends StatelessWidget {
  final String asset;
  final VoidCallback? onCardTap;

  final VoidCallback? onReceive;
  final VoidCallback? onSend;
  final VoidCallback? onTransactions;
  final bool solanaLive;
  final bool tronLive;
  final bool moneroLive;
  final String? balanceReason;
  final bool featuresLoaded;
  final DashboardAssetActionCapability capability;
  final DashboardAssetLiveState? liveState;
  final CryptoWalletFeatures? features;

  const _CryptoWalletEngineAssetCard({
    required this.asset,
    required this.onCardTap,
    required this.onReceive,
    required this.onSend,
    required this.onTransactions,
    required this.capability,
    required this.balanceReason,
    required this.featuresLoaded,
    this.solanaLive = false,
    this.tronLive = false,
    this.moneroLive = false,
    this.liveState,
    this.features,
  });

  String _tickerForAsset(String asset) {
    switch (asset) {
      case 'ETH':
        return 'ETH';
      case 'USDT_ERC20':
        return 'USDT';
      case 'USDC_ERC20':
        return 'USDC';
      case 'SOL':
        return 'SOL';
      case 'USDT_TRC20':
        return 'USDT';
      case 'XMR':
        return 'XMR';
    }
    return asset;
  }

  String _displayNameForAsset(String asset) {
    switch (asset) {
      case 'ETH':
        return 'Ethereum';
      case 'USDT_ERC20':
        return 'USDT';
      case 'USDC_ERC20':
        return 'USDC';
      case 'SOL':
        return 'Solana';
      case 'USDT_TRC20':
        return 'USDT';
      case 'XMR':
        return 'Monero';
    }
    return kCryptoWalletEngineAssetLabels[asset] ?? asset;
  }

  @override
  Widget build(BuildContext context) {
    final displayName = _displayNameForAsset(asset);
    final ticker = _tickerForAsset(asset);
    final network = kCryptoWalletEngineNetworkLabels[asset] ?? '';
    final isLive = kCryptoWalletEngineLaunchedAssets.contains(asset);
    final futureLabel =
        isLive ? null : kCryptoWalletEngineFutureStateLabel[asset];

    final Widget? badge = isLive
        ? walletStatusBadge(
            'Live',
            tone: WalletBadgeTone.live,
            key: Key('crypto_wallet_engine_card_live_$asset'),
          )
        : futureLabel != null
            ? walletStatusBadge(
                futureLabel,
                tone: asset == 'XMR'
                    ? WalletBadgeTone.privacy
                    : asset == 'SOL'
                        ? WalletBadgeTone.comingNext
                        : WalletBadgeTone.planned,
                key: Key('crypto_wallet_engine_card_future_state_$asset'),
              )
            : null;

    final headerRow = Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        walletAssetIcon(asset, size: 38),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      displayName,
                      key: Key('crypto_wallet_engine_card_label_$asset'),
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: kWalletTextPrimary,
                        fontSize: 17,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -0.1,
                      ),
                    ),
                  ),
                  if (badge != null) ...[
                    const SizedBox(width: 6),
                    badge,
                  ],
                ],
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  Text(
                    ticker,
                    style: const TextStyle(
                      color: kWalletTextSecondary,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.4,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Container(
                    width: 3,
                    height: 3,
                    decoration: const BoxDecoration(
                      color: kWalletTextMuted,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      network,
                      key: Key('crypto_wallet_engine_card_network_$asset'),
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: kWalletTextSecondary,
                        fontSize: 12,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );

    final networkKind = walletNetworkKindFor(asset: asset, network: null);

    Widget balanceLine;
    if (!featuresLoaded) {
      balanceLine = Row(
        key: Key('crypto_wallet_engine_card_balance_skeleton_$asset'),
        children: const [
          Icon(
            Icons.hourglass_top_outlined,
            size: 16,
            color: kWalletTextMuted,
          ),
          SizedBox(width: 8),
          Text(
            'Checking…',
            style: TextStyle(
              color: kWalletTextSecondary,
              fontSize: 13,
            ),
          ),
        ],
      );
    } else if (liveState != null &&
        liveState!.kind == DashboardAssetLiveStateKind.loading) {
      balanceLine = Row(
        key: Key('crypto_wallet_engine_card_balance_refreshing_$asset'),
        children: const [
          Icon(
            Icons.hourglass_top_outlined,
            size: 16,
            color: kWalletTextMuted,
          ),
          SizedBox(width: 8),
          Text(
            'Refreshing…',
            style: TextStyle(
              color: kWalletTextSecondary,
              fontSize: 13,
            ),
          ),
        ],
      );
    } else if (liveState != null && liveState!.hasAvailableBalance) {
      final unit = liveState!.balanceUnit ?? walletBalanceUnitLabel(asset);
      final amountText = '${liveState!.balanceAmount} $unit';
      balanceLine = Row(
        children: [
          const Icon(
            Icons.savings_outlined,
            size: 16,
            color: kWalletTextMuted,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              amountText,
              key: Key('crypto_wallet_engine_card_balance_value_$asset'),
              style: const TextStyle(
                color: kWalletTextPrimary,
                fontSize: 15,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      );
    } else {
      final String? effectiveReason;
      if (liveState != null &&
          liveState!.kind == DashboardAssetLiveStateKind.reason) {
        effectiveReason = liveState!.backendReason;
      } else if (liveState != null &&
          liveState!.kind == DashboardAssetLiveStateKind.noWallet) {
        effectiveReason = 'no_wallet_yet';
      } else {
        effectiveReason = balanceReason;
      }
      final render = effectiveReason == null
          ? null
          : walletBalanceReasonRender(
              reason: effectiveReason,
              asset: asset,
              networkKind: networkKind,
            );
      balanceLine = Row(
        children: [
          const Icon(
            Icons.savings_outlined,
            size: 16,
            color: kWalletTextMuted,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              render?.message ?? '',
              key: Key(
                'crypto_wallet_engine_card_balance_reason_$asset',
              ),
              style: const TextStyle(
                color: kWalletTextSecondary,
                fontSize: 13,
              ),
            ),
          ),
        ],
      );
    }

    final body = isLive
        ? Container(
            key: Key('crypto_wallet_engine_card_balance_$asset'),
            padding: const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 10,
            ),
            decoration: BoxDecoration(
              color: kWalletSurfaceElevated,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: kWalletBorder),
            ),
            child: balanceLine,
          )
        : Container(
            key: Key('crypto_wallet_engine_card_future_body_$asset'),
            padding: const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 10,
            ),
            decoration: BoxDecoration(
              color: kWalletSurfaceElevated.withOpacity(0.6),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: kWalletBorder),
            ),
            child: Text(
              kCryptoWalletEngineFutureStateBodyByAsset[asset] ??
                  kCryptoWalletEngineFutureStateBody,
              style: const TextStyle(
                color: kWalletTextSecondary,
                fontSize: 13,
                height: 1.4,
              ),
            ),
          );

    final headerArea = isLive && onCardTap != null
        ? Material(
            color: Colors.transparent,
            child: InkWell(
              key: Key('crypto_wallet_engine_card_tap_$asset'),
              borderRadius: BorderRadius.circular(10),
              onTap: onCardTap,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: headerRow,
              ),
            ),
          )
        : Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: headerRow,
          );

    return Container(
      key: Key('crypto_wallet_engine_card_$asset'),
      decoration: walletAssetCard(asset),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            headerArea,
            const SizedBox(height: 12),
            body,
            if (isLive) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (capability.receive && onReceive != null)
                    ElevatedButton.icon(
                      key: Key(
                        'crypto_wallet_engine_card_receive_btn_$asset',
                      ),
                      onPressed: onReceive,
                      icon: const Icon(Icons.south_rounded, size: 16),
                      label: Text(AppLocalizations.of(context).commonReceive),
                      style: walletPrimaryButtonStyle(),
                    ),
                  if (capability.send && onSend != null)
                    ElevatedButton.icon(
                      key: Key(
                        'crypto_wallet_engine_card_send_btn_$asset',
                      ),
                      onPressed: onSend,
                      icon: const Icon(Icons.north_rounded, size: 16),
                      label: const Text('Send'),
                      style: walletSecondaryButtonStyle(),
                    ),
                  if (capability.transactions && onTransactions != null)
                    OutlinedButton.icon(
                      key: Key(
                        'crypto_wallet_engine_card_tx_btn_$asset',
                      ),
                      onPressed: onTransactions,
                      icon: const Icon(Icons.list_alt_rounded, size: 16),
                      label: Text(
                        AppLocalizations.of(context).cryptoTransactionsTab,
                      ),
                      style: walletGhostButtonStyle(),
                    ),
                ],
              ),
              if (!capability.send &&
                  capability.sendUnavailableReason != null) ...[
                const SizedBox(height: 10),
                Row(
                  key: Key(
                    'crypto_wallet_engine_card_send_unavailable_$asset',
                  ),
                  children: [
                    const Icon(
                      Icons.info_outline_rounded,
                      size: 14,
                      color: kWalletTextMuted,
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        capability.sendUnavailableReason!,
                        style: const TextStyle(
                          color: kWalletTextMuted,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
              if (!capability.transactions &&
                  capability.transactionsUnavailableReason != null) ...[
                const SizedBox(height: 6),
                Builder(builder: (_) {
                  final kind = dashboardCardActivityKind(
                    asset: asset,
                    features: features,
                  );
                  final label = dashboardCardActivityChipCopy(kind);
                  return Container(
                    key: Key(
                      'crypto_wallet_engine_card_activity_chip_$asset',
                    ),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 3,
                    ),
                    decoration: BoxDecoration(
                      color: kWalletBorder.withOpacity(0.35),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      label,
                      style: const TextStyle(
                        color: kWalletTextMuted,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  );
                }),
              ],
              if (asset == 'XMR') ...[
                const SizedBox(height: 8),
                Text(
                  kWalletBalanceCopyMoneroScannerNote,
                  key: const Key(
                    'crypto_wallet_engine_card_xmr_scanner_note',
                  ),
                  style: const TextStyle(
                    color: kWalletTextMuted,
                    fontSize: 11,
                    height: 1.4,
                  ),
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }
}
