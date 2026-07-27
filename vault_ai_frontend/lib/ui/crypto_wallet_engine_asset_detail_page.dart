

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../services/asset_live_store.dart';
import 'responsive.dart' show vrDisplay;
import '../services/crypto_wallet_dashboard_reason.dart';
import '../services/evm_networks.dart';
import 'crypto_wallet_engine_activity_card.dart';
import 'crypto_wallet_engine_design.dart';
import 'crypto_wallet_engine_page.dart';
import '../services/crypto_wallet_balance_reason.dart';
import '../services/crypto_wallet_features.dart';
import '../services/monero_scanner.dart';
import '../services/monero_scanner_status.dart';
import '../services/monero_wallet.dart';
import 'crypto_wallet_engine_monero_scanner_card.dart';
import 'crypto_wallet_engine_receive_panel.dart';
import 'crypto_wallet_engine_sheet_chrome.dart';
import 'crypto_wallet_engine_solana_activity_card.dart';
import 'crypto_wallet_engine_solana_receive_panel.dart';
import 'crypto_wallet_engine_solana_send_panel.dart';
import 'crypto_wallet_engine_send_panel.dart';
import 'crypto_wallet_engine_tron_activity_card.dart';
import 'crypto_wallet_engine_tron_receive_panel.dart';
import 'crypto_wallet_engine_tron_send_panel.dart';
import 'crypto_wallet_engine_monero_activity_card.dart';
import 'crypto_wallet_engine_monero_receive_panel.dart';


const String kAssetDetailBalanceHeaderLabel = 'Balance';
const String kAssetDetailBalanceNotConnected =
    'Live balance loads after you create a wallet and the backend '
    'connects to the network indexer.';
const String kAssetDetailBalanceRefreshBtnKey =
    'crypto_wallet_engine_asset_detail_balance_refresh_btn';
const String kAssetDetailBalanceReasonMessageKey =
    'crypto_wallet_engine_asset_detail_balance_reason_message';
const String kAssetDetailAddressHeaderLabel = 'Wallet address';
const String kAssetDetailAddressNotConnected =
    'No wallet address yet. Tap Receive to create your wallet on '
    'this device.';
const String kAssetDetailCopyAddressLabel = 'Copy address';
const String kAssetDetailCopyDoneSnackbar = 'Address copied to clipboard';
const String kAssetDetailReceiveLabel = 'Receive';
const String kAssetDetailSendLabel = 'Send';
const String kAssetDetailSolanaSendDisabledMessage =
    'Solana sending is not enabled yet.';
const String kAssetDetailTronSendDisabledMessage =
    'USDT TRC20 sending is not enabled yet.';
const String kAssetDetailMoneroSendDisabledMessage =
    'Monero sending is not enabled yet.';
const String kAssetDetailActivityHeaderLabel = 'Activity';
const String kAssetDetailActivityNotConnected =
    'Transaction history not connected yet. Sent transactions show '
    'their hash and status after broadcast.';
const String kAssetDetailBackupHeaderLabel = 'Backup status';
const String kAssetDetailBackupSaved =
    'Encrypted backup saved. Your wallet ciphertext is stored under '
    'your vault key — VaultAI cannot decrypt it.';
const String kAssetDetailBackupMissing =
    'No backup saved yet. Your wallet backup is created automatically '
    'when you create the wallet.';




const String kAssetDetailNoWalletAddressCopy =
    'No wallet created yet.';
const String kAssetDetailNoWalletBalanceCopy =
    'Create wallet to view balance.';
const String kAssetDetailNoWalletActivityCopy =
    'Create wallet to view activity.';


const String kAssetDetailLoadingWalletCopy = 'Loading wallet…';
const String kAssetDetailLoadingBalanceCopy = 'Loading balance…';
const String kAssetDetailLoadingActivityCopy = 'Loading activity…';


const String kAssetDetailBalanceUnavailableCopy =
    'Balance temporarily unavailable.';
const String kAssetDetailActivityUnavailableCopy =
    'Activity temporarily unavailable.';


const Duration kAssetDetailReceiveTimeout = Duration(seconds: 8);
const Duration kAssetDetailBalanceTimeout = Duration(seconds: 10);
const String kAssetDetailComingSoonHeading = 'Unavailable';
const String kAssetDetailComingSoonBody =
    'This asset is not connected to the wallet engine on this '
    'network. No balance, no address, and no Send action are '
    'shown.';
const String kAssetDetailMoneroBanner =
    'Monero balance and activity require wallet scanning.';
const String kAssetDetailTokenSharedAddressNote =
    'This token uses your Ethereum wallet address. The same address '
    'holds your ETH and your ERC20 tokens.';
const String kAssetDetailTokenGasNote =
    'Gas fees for token transfers are paid in ETH from the same wallet.';
const String kAssetDetailSendNotReadyBanner =
    'Send is not ready for this asset yet. The Crypto Wallet Engine '
    'ships Send for ETH and ERC20 tokens on the effective Ethereum '
    'network.';
const String kAssetDetailReceiveNotReadyBanner =
    'Receive is not ready for this asset yet. The Crypto Wallet '
    'Engine ships Receive for ETH and ERC20 tokens on the effective '
    'Ethereum network.';


const String kAssetDetailEthereumMainnetLabel = 'Ethereum Mainnet';
const String kAssetDetailEthereumMainnetErc20Label =
    'Ethereum Mainnet · ERC20';
const String kAssetDetailEthereumSepoliaLabel =
    'Ethereum Sepolia Testnet';




String assetDetailNetworkLabel({
  required String asset,
  required String? network,
}) {
  final isEthereumFamily =
      asset == 'ETH' || asset == 'USDT_ERC20' || asset == 'USDC_ERC20';
  if (isEthereumFamily) {
    if (network == kEvmNetworkEthereumSepolia) {
      return kAssetDetailEthereumSepoliaLabel;
    }
    if (network == kEvmNetworkEthereumMainnet) {
      return asset == 'ETH'
          ? kAssetDetailEthereumMainnetLabel
          : kAssetDetailEthereumMainnetErc20Label;
    }


    return kCryptoWalletEngineNetworkLabels[asset] ?? '';
  }

  return kCryptoWalletEngineNetworkLabels[asset] ?? '';
}


bool assetDetailIsSepolia({
  required String asset,
  required String? network,
}) {
  final isEthereumFamily =
      asset == 'ETH' || asset == 'USDT_ERC20' || asset == 'USDC_ERC20';
  return isEthereumFamily && network == kEvmNetworkEthereumSepolia;
}


class CryptoWalletEngineAssetDetailPage extends StatefulWidget {
  final String asset;


  final String? authToken;
  final VaultAIClient? apiClient;
  final Future<String> Function(String plaintext)? encryptForVault;
  final bool Function()? isVaultKeyAvailable;


  final Future<String> Function(String ciphertext)? decryptForVault;
  final Future<bool> Function(String pin)? verifyPin;
  // 2026-07-13 network-scoped: the ETH Send from the asset-detail
  // page must resolve the SAME wallet the balance/receive path
  // resolves (which uses the network-scoped endpoint). See the
  // matching note on CryptoWalletEnginePage.loadFromAddress.
  final Future<String?> Function(String network)? loadFromAddress;


  final String? network;
  final CryptoWalletFeatures? features;
  final MoneroWalletAdapter moneroWalletAdapter;
  final MoneroScannerAdapter moneroScannerAdapter;

  const CryptoWalletEngineAssetDetailPage({
    super.key,
    required this.asset,
    this.authToken,
    this.apiClient,
    this.encryptForVault,
    this.isVaultKeyAvailable,
    this.decryptForVault,
    this.verifyPin,
    this.loadFromAddress,
    this.network,
    this.features,
    this.moneroWalletAdapter = const NullMoneroWalletAdapter(),
    this.moneroScannerAdapter = const NullMoneroScannerAdapter(),
  });

  String get effectiveNetwork =>
      network ?? kCompileTimeDefaultNetworkResolved;

  @override
  State<CryptoWalletEngineAssetDetailPage> createState() =>
      _CryptoWalletEngineAssetDetailPageState();
}

class _CryptoWalletEngineAssetDetailPageState
    extends State<CryptoWalletEngineAssetDetailPage> {
  String? _address;
  bool _addressLoading = false;
  String? _balance;
  String? _balanceUnit;
  String? _balanceReason;
  bool _balanceLoading = false;

  // 2026-07-13 (Round 5 hardening): integer wei / base-units mirror
  // of the display balance. Sourced from `weiAmount` (ETH) or
  // `baseUnits` (ERC-20) on the /balance response. Used to feed the
  // Send panel's exact-fee gate (`fetchAvailableBalanceWei`) so that
  // the client-side integer authorization actually runs on the
  // production Send path — previously the asset-detail Send opener
  // wired NEITHER `fetchAvailableBalance` NOR the wei hook, so the
  // Round-4 gate never ran in production and only the backend gate
  // caught misauthorized sends.
  BigInt? _balanceBaseUnits;
  BigInt? _ethBalanceWei;      // For ERC-20 sends: parent-ETH gas.
  DateTime? _balanceUpdatedAt; // For "last updated Ns ago" copy.
  // Optimistic pending debit stamped locally after a successful
  // Send. Cleared on the next successful live refresh.
  BigInt? _pendingDebitWei;
  BigInt? _pendingDebitBaseUnits;

  // Scroll controller so the Send-sheet close handler can restore a
  // sensible offset (top of the balance card) instead of leaving the
  // user stranded mid-scroll.
  final ScrollController _pageScrollCtrl = ScrollController();
  final GlobalKey _balanceCardAnchorKey = GlobalKey();


  MoneroSyncStatus? _moneroScannerStatus;
  MoneroBalanceReading? _moneroBalanceReading;
  List<MoneroTransactionRow> _moneroTransactions =
      const <MoneroTransactionRow>[];
  bool _moneroScannerStarting = false;
  String? _moneroScannerInlineMessage;


  MoneroScannerStatus? _backendMoneroScannerStatus;

  // Compact label for sheet titles — collapses ERC20 token asset IDs
  // to their short symbol so the sheet title reads "Send USDT" instead
  // of "Send USDT_ERC20". Called only from send sheet callers.
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

  bool get _isSolana =>
      widget.asset == 'SOL'
      && widget.network == 'solana_mainnet';

  bool get _isTron =>
      widget.asset == 'USDT_TRC20'
      && widget.network == 'tron_mainnet';

  bool get _isMoneroLive =>
      widget.asset == 'XMR'
      && widget.network == 'monero_mainnet';

  bool get _isSupported =>
      kAssetsWithLiveReceive.contains(widget.asset) ||
      kAssetsWithLiveSend.contains(widget.asset) ||
      _isSolana ||
      _isTron ||
      _isMoneroLive;

  bool get _isToken =>
      widget.asset == 'USDT_ERC20' || widget.asset == 'USDC_ERC20';

  bool get _isMonero => widget.asset == 'XMR';

  bool get _hasReceiveWiring =>
      widget.authToken != null &&
      widget.apiClient != null &&
      widget.encryptForVault != null &&
      widget.isVaultKeyAvailable != null;

  bool get _hasSendWiring =>
      _hasReceiveWiring &&
      widget.decryptForVault != null &&
      widget.loadFromAddress != null;

  @override
  void initState() {
    super.initState();
    if (_isSupported && _hasReceiveWiring) {
      _loadAddressAndBalance();
    }
    if (_isMoneroLive) {
      _loadMoneroScannerState();
      _loadBackendMoneroScannerStatus();
    }
  }

  @override
  void dispose() {
    _pageScrollCtrl.dispose();
    super.dispose();
  }

  // 2026-07-13 (Round 5 hardening): scroll the balance card back
  // into view after the Send sheet closes so the user does not
  // return to a mid-scroll offset that hides the balance and the
  // updated activity.
  void _restoreScrollToBalanceAnchor() {
    if (!mounted) return;
    final ctx = _balanceCardAnchorKey.currentContext;
    if (ctx == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (!ctx.mounted) return;
      Scrollable.ensureVisible(
        ctx,
        alignment: 0.05,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
      );
    });
  }

  // 2026-07-13 (Round 5 hardening): stamp an optimistic pending
  // debit immediately after a successful Send broadcast so the
  // Balance card visually reflects the outgoing transaction before
  // the next chain refresh converges. Not a substitute for the
  // authoritative live refresh — the live refresh clears the
  // pending mark on next success.
  void _applyOptimisticDebit({
    required BigInt debitBaseUnits,
    required bool isToken,
  }) {
    if (!mounted) return;
    setState(() {
      if (isToken) {
        _pendingDebitBaseUnits = debitBaseUnits;
      } else {
        _pendingDebitWei = debitBaseUnits;
      }
    });
  }


  Future<void> _loadBackendMoneroScannerStatus() async {
    if (!_isMoneroLive) return;
    final api = widget.apiClient;
    final token = widget.authToken;
    if (api == null || token == null || token.isEmpty) return;
    try {
      final raw = await api.getXmrScannerStatus(
        authToken: token,
        clientPlatform: moneroClientPlatform(),
      );
      if (!mounted) return;
      final parsed = MoneroScannerStatus.fromJson(raw);
      setState(() {
        _backendMoneroScannerStatus = parsed;
      });


      try {
        debugPrint(
          'xmr_scanner_ui_state '
          'platform=${moneroClientPlatform()} '
          'mode=${parsed.mode} '
          'reason=${parsed.reason}',
        );
      } catch (_) {}
    } catch (_) {


    }
  }

  Future<void> _loadMoneroScannerState() async {
    if (!_isMoneroLive) return;
    final adapter = widget.moneroScannerAdapter;
    try {
      final s = await adapter.getSyncStatus();
      final b = await adapter.getBalance();
      final txs = await adapter.getTransactions();
      if (!mounted) return;
      setState(() {
        _moneroScannerStatus = s;
        _moneroBalanceReading = b;
        _moneroTransactions = txs;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _moneroScannerStatus = MoneroSyncStatus.scannerUnavailable();
        _moneroBalanceReading = MoneroBalanceReading.unavailable(
          reason: MoneroScannerErrorCode.scannerInternalError,
        );
        _moneroTransactions = const <MoneroTransactionRow>[];
      });
    }
  }

  Future<void> _startMoneroScan() async {
    if (!_isMoneroLive) return;
    if (_moneroScannerStarting) return;
    final adapter = widget.moneroScannerAdapter;
    if (!adapter.isAvailable) {
      setState(() {
        _moneroScannerInlineMessage = adapter.availabilityReason;
      });
      return;
    }
    final addr = _address;
    if (addr == null || addr.isEmpty) {
      setState(() {
        _moneroScannerInlineMessage =
            'Create your Monero wallet first before scanning.';
      });
      return;
    }
    setState(() {
      _moneroScannerStarting = true;
      _moneroScannerInlineMessage = null;
    });
    try {
      await adapter.startScan(
        MoneroScannerInput(
          privateViewKey: Uint8List(32),
          publicSpendKey: Uint8List(32),
          publicAddress: addr,
          restoreHeight: 0,
        ),
      );
      await _loadMoneroScannerState();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _moneroScannerInlineMessage =
            'Monero scan failed to start on this device.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _moneroScannerStarting = false;
        });
      }
    }
  }

  Future<void> _stopMoneroScan() async {
    if (!_isMoneroLive) return;
    try {
      await widget.moneroScannerAdapter.stopScan();
    } catch (_) {
    }
    await _loadMoneroScannerState();
  }

  Future<void> _loadAddressAndBalance() async {
    if (!_isSupported || widget.apiClient == null ||
        widget.authToken == null) {
      return;
    }




    if (widget.network == null) {
      await _loadAddressAndBalanceLegacyDefault();
      return;
    }




    final asset = widget.asset;
    final network = widget.effectiveNetwork;
    final seq = AssetLiveStore.instance.claimSeq(asset);

    if (mounted) {
      setState(() {
        _addressLoading = true;
        _balanceLoading = true;
        _balanceReason = null;
      });
    }

    AssetLiveStore.instance.applyState(
      source: 'detail',
      asset: asset,
      seq: seq,
      state: const DashboardAssetLiveState.loading(),
      network: network,
    );

    final result = await loadAssetWalletState(
      apiClient: widget.apiClient!,
      authToken: widget.authToken!,
      network: network,
      asset: asset,
      receiveTimeout: kAssetDetailReceiveTimeout,
      balanceTimeout: kAssetDetailBalanceTimeout,
    );

    if (!mounted) return;

    AssetLiveStore.instance.applyState(
      source: 'detail',
      asset: asset,
      seq: seq,
      state: result,
      network: network,
    );

    setState(() {
      _addressLoading = false;
      _address = result.publicAddress;
      switch (result.kind) {
        case DashboardAssetLiveStateKind.available:
          _balance = result.balanceAmount;
          _balanceUnit = result.balanceUnit;
          _balanceReason = null;
          _balanceLoading = false;
          // A successful live refresh clears any prior optimistic
          // pending debit — the chain has caught up.
          _pendingDebitWei = null;
          _pendingDebitBaseUnits = null;
          _balanceUpdatedAt = DateTime.now();
          break;
        case DashboardAssetLiveStateKind.reason:
          // 2026-07-13 (Round 5 hardening): do NOT blank the
          // previous balance when a live refresh fails. Users must
          // never see a "0" or empty balance because of an RPC
          // hiccup. The stale copy persists; a staleness indicator
          // ("last updated Ns ago") explains why it's not fresh.
          _balanceReason = result.backendReason ?? 'rpc_error';
          _balanceLoading = false;
          break;
        case DashboardAssetLiveStateKind.noWallet:
          _balance = null;
          _balanceUnit = null;
          _balanceReason = 'no_wallet_yet';
          _balanceLoading = false;
          _pendingDebitWei = null;
          _pendingDebitBaseUnits = null;
          _balanceBaseUnits = null;
          _ethBalanceWei = null;
          break;
        case DashboardAssetLiveStateKind.loading:
          _balanceLoading = true;
          break;
      }
    });
    // 2026-07-13 (Round 5 hardening): the shared state loader
    // returns a formatted display balance but not integer wei /
    // base-units. Re-hit the balance endpoint here for the raw
    // integer so the Send panel's exact-fee gate can BigInt-compare
    // against the drafted `gasLimit * gasPrice + valueWei`.
    if (result.kind == DashboardAssetLiveStateKind.available &&
        result.publicAddress != null &&
        result.publicAddress!.isNotEmpty) {
      // ignore: discarded_futures
      _loadRawBalanceIntegers(result.publicAddress!);
    }
  }

  // 2026-07-13 (Round 5 hardening): fetch the raw integer balance
  // (wei for ETH; base units for ERC-20) plus the parent-ETH balance
  // in wei for ERC-20 sends. Cached on the state so the Send sheet
  // can wire `fetchAvailableBalanceWei` / `fetchEthBalanceWei` to a
  // synchronous getter that returns the last-known value.
  Future<void> _loadRawBalanceIntegers(String address) async {
    final api = widget.apiClient;
    final token = widget.authToken;
    if (api == null || token == null || token.isEmpty) return;
    if (widget.network == null) return;
    final asset = widget.asset;
    try {
      final body = await api.getCryptoWalletBalanceNetwork(
        network: widget.effectiveNetwork,
        asset: asset,
        authToken: token,
        address: address,
      ).timeout(kAssetDetailBalanceTimeout);
      final status = (body['balanceStatus'] ?? '').toString();
      if (status != 'available') return;
      // 2026-07-14 (Round 7 hardening): pick the raw-integer field
      // matching the asset. ETH: weiAmount. ERC-20: baseUnits.
      // SOL: lamports OR availableAmount * 1e9. TRON: baseUnits
      // (token) + trxBalanceSun for the parent-TRX check.
      BigInt? primary;
      if (asset == 'ETH') {
        final w = body['weiAmount'];
        if (w != null) primary = BigInt.tryParse(w.toString());
      } else if (asset == 'SOL') {
        final l = body['lamports'] ?? body['availableBaseUnits'];
        if (l != null) primary = BigInt.tryParse(l.toString());
      } else {
        // ERC-20 tokens, TRON tokens.
        final b = body['baseUnits'] ?? body['availableBaseUnits'];
        if (b != null) primary = BigInt.tryParse(b.toString());
      }
      if (!mounted) return;
      setState(() {
        _balanceBaseUnits = primary;
      });
      // ERC-20 sends also need the parent-ETH balance in wei for
      // the gas hard-gate. Fetch it separately.
      // 2026-07-14 (Round 7 hardening): USDT_TRC20 needs the
      // parent-chain TRX balance in sun for the TRON fee gate —
      // same reuse of the `_ethBalanceWei` slot as parent-chain
      // integer balance (semantic overload documented here).
      if (asset == 'USDT_ERC20' || asset == 'USDC_ERC20') {
        try {
          final ethBody = await api.getCryptoWalletBalanceNetwork(
            network: widget.effectiveNetwork,
            asset: 'ETH',
            authToken: token,
            address: address,
          ).timeout(kAssetDetailBalanceTimeout);
          final ethStatus =
              (ethBody['balanceStatus'] ?? '').toString();
          if (ethStatus == 'available') {
            final w = ethBody['weiAmount'];
            if (w != null && mounted) {
              setState(() {
                _ethBalanceWei = BigInt.tryParse(w.toString());
              });
            }
          }
        } catch (_) {
          // Intentional: the ETH-balance fetch failing does NOT
          // downgrade the token balance — the Send panel's gate
          // still refuses to sign in that case (fetchEthBalanceWei
          // returns null → gate blocks).
        }
      } else if (asset == 'USDT_TRC20') {
        // USDT_TRC20 needs the parent-TRX balance in sun.
        try {
          final trxBody = await api.getCryptoWalletBalanceNetwork(
            network: widget.effectiveNetwork,
            asset: 'TRX',
            authToken: token,
            address: address,
          ).timeout(kAssetDetailBalanceTimeout);
          final trxStatus =
              (trxBody['balanceStatus'] ?? '').toString();
          if (trxStatus == 'available') {
            final sun = trxBody['trxBalanceSun']
                ?? trxBody['baseUnits']
                ?? trxBody['availableBaseUnits'];
            if (sun != null && mounted) {
              setState(() {
                _ethBalanceWei = BigInt.tryParse(sun.toString());
              });
            }
          }
        } catch (_) {
          // Same fail-closed intent: gate blocks on null.
        }
      }
    } catch (_) {
      // Same intent: transient RPC error leaves the prior integer
      // balance in place; Send gate blocks if none was ever loaded.
    }
  }




  Future<void> _loadAddressAndBalanceLegacyDefault() async {
    if (mounted) {
      setState(() {
        _addressLoading = true;
        _balanceReason = null;
      });
    }
    String? addr;
    try {
      final body = await widget.apiClient!.getCryptoWalletReceive(
        asset: widget.asset,
        authToken: widget.authToken!,
      ).timeout(kAssetDetailReceiveTimeout);
      final status = (body['wallet_engine'] ?? '').toString();
      if (status == 'receive_ready') {
        final raw = body['publicAddress'];
        if (raw is String && raw.isNotEmpty) addr = raw;
      }
    } catch (_) {
      addr = null;
    } finally {
      if (mounted) {
        setState(() {
          _address = addr;
          _addressLoading = false;
          if (addr == null || addr.isEmpty) {
            _balance = null;
            _balanceUnit = null;
            _balanceReason = 'no_wallet_yet';
            _balanceLoading = false;
          }
        });
      }
    }
    if (addr != null && addr.isNotEmpty && mounted) {
      await _loadBalance(addr);
    }
  }

  Future<void> _loadBalance(String address) async {
    if (widget.apiClient == null || widget.authToken == null) return;
    if (mounted) {
      setState(() {
        _balanceLoading = true;
      });
    }
    String? bal;
    String? unit;
    String? reason;
    try {
      final body = widget.network != null
          ? await widget.apiClient!.getCryptoWalletBalanceNetwork(
              network: widget.effectiveNetwork,
              asset: widget.asset,
              authToken: widget.authToken!,
              address: address,
            ).timeout(kAssetDetailBalanceTimeout)
          : await widget.apiClient!.getCryptoWalletBalance(
              asset: widget.asset,
              authToken: widget.authToken!,
              address: address,
            ).timeout(kAssetDetailBalanceTimeout);
      final status = (body['balanceStatus'] ?? '').toString();
      if (status == 'available') {
        final raw = body['availableAmount'] ?? body['balance'];
        if (raw != null) bal = raw.toString();
        final u = body['unit'];
        if (u is String && u.isNotEmpty) unit = u;
      } else {
        final rawReason = body['reason'];
        if (rawReason is String && rawReason.isNotEmpty) {
          reason = rawReason;
        } else {
          final engineFlag = body['wallet_engine'];
          if (engineFlag is String && engineFlag.isNotEmpty) {
            reason = engineFlag;
          }
        }
      }
    } on TimeoutException catch (_) {
      bal = null;
      reason = 'rpc_error';
    } catch (_) {
      bal = null;
      reason = 'rpc_error';
    } finally {
      if (mounted) {
        setState(() {
          _balance = bal;
          _balanceUnit = unit;
          _balanceReason = reason;
          _balanceLoading = false;
        });
      }
    }
  }

  Future<void> _refreshBalance() async {
    final addr = _address;
    if (addr == null || addr.isEmpty) {
      setState(() {
        _balance = null;
        _balanceUnit = null;
        _balanceReason = 'no_wallet_yet';
      });
      return;
    }
    await _loadBalance(addr);
  }

  void _showSnackBar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        key: const Key('crypto_wallet_engine_asset_detail_snackbar'),
        content: Text(message, maxLines: 4),
        duration: const Duration(seconds: 4),
      ),
    );
  }

  void _openReceivePanel() {
    if (!_isSupported || !_hasReceiveWiring) {
      _showSnackBar(kAssetDetailReceiveNotReadyBanner);
      return;
    }
    final String sheetTitle = _isTron
        ? 'Receive USDT (TRC20)'
        : _isSolana
            ? 'Receive SOL'
            : _isMoneroLive
                ? 'Receive XMR'
                : 'Receive ${widget.asset}';
    showCryptoWalletSheet<void>(
      context: context,
      title: sheetTitle,
      sheetKey: 'crypto_wallet_engine_asset_detail_receive_sheet',
      child: _isSolana
          ? CryptoWalletEngineSolanaReceivePanel(
              key: const Key(
                'crypto_wallet_engine_asset_detail_solana_receive_panel',
              ),
              authToken: widget.authToken!,
              client: widget.apiClient!,
              encryptForVault: widget.encryptForVault!,
              isVaultKeyAvailable: widget.isVaultKeyAvailable!,
            )
          : _isTron
              ? CryptoWalletEngineTronReceivePanel(
                  key: const Key(
                    'crypto_wallet_engine_asset_detail_tron_receive_panel',
                  ),
                  authToken: widget.authToken!,
                  client: widget.apiClient!,
                  encryptForVault: widget.encryptForVault!,
                  isVaultKeyAvailable: widget.isVaultKeyAvailable!,
                  features: widget.features,
                )
              : _isMoneroLive
                  ? CryptoWalletEngineMoneroReceivePanel(
                      key: const Key(
                        'crypto_wallet_engine_asset_detail_monero_receive_panel',
                      ),
                      authToken: widget.authToken!,
                      client: widget.apiClient!,
                      features: widget.features,
                      walletAdapter: widget.moneroWalletAdapter,
                      encryptForVault: widget.encryptForVault,
                      isVaultKeyAvailable: widget.isVaultKeyAvailable,
                    )
                  : CryptoWalletEngineReceivePanel(
                      key: Key(
                        'crypto_wallet_engine_asset_detail_receive_panel_${widget.asset}',
                      ),
                      authToken: widget.authToken!,
                      client: widget.apiClient!,
                      encryptForVault: widget.encryptForVault!,
                      isVaultKeyAvailable: widget.isVaultKeyAvailable!,
                      asset: widget.asset,
                      network: widget.network,
                    ),
    ).whenComplete(() {
      if (mounted) _loadAddressAndBalance();
    });
  }

  Future<void> _openSendPanel() async {
    if (_isMoneroLive) {
      _showSnackBar(kAssetDetailMoneroSendDisabledMessage);
      return;
    }
    if (_isTron) {
      final sendOn = widget.features?.tronSendEnabled ?? false;
      if (!sendOn) {
        _showSnackBar(kAssetDetailTronSendDisabledMessage);
        return;
      }
      if (widget.authToken == null || widget.apiClient == null
          || widget.decryptForVault == null
          || widget.isVaultKeyAvailable == null) {
        _showSnackBar(kAssetDetailSendNotReadyBanner);
        return;
      }
      final fromAddress = _address;
      if (fromAddress == null || fromAddress.isEmpty) {
        _showSnackBar(
          'No TRON wallet exists yet. Tap Receive to create one '
          'before sending.',
        );
        return;
      }
      if (!mounted) return;
      // 2026-07-14 (Round 7 hardening): wire the TRON send panel
      // with balance hooks + optimistic pending debit + post-Send
      // refresh, matching the ETH/SOL shape.
      // ignore: discarded_futures
      showCryptoWalletSheet<void>(
        context: context,
        title: 'Send USDT (TRC20)',
        sheetKey: 'crypto_wallet_engine_asset_detail_tron_send_sheet',
        bodyOwnsLayout: true,
        child: CryptoWalletEngineTronSendPanel(
          key: const Key(
            'crypto_wallet_engine_asset_detail_tron_send_panel',
          ),
          authToken: widget.authToken!,
          fromAddress: fromAddress,
          client: widget.apiClient!,
          decryptForVault: widget.decryptForVault!,
          isVaultKeyAvailable: widget.isVaultKeyAvailable!,
          verifyPin: widget.verifyPin,
          features: widget.features,
          fetchAvailableTokenBaseUnits: () async => _balanceBaseUnits,
          fetchTrxBalanceSun: () async => _ethBalanceWei,
          onSuccessfulBroadcast: (
              {required String txHash,
               required BigInt tokenBaseUnitsDebit,
               required BigInt sunFeeDebit}) {
            _applyOptimisticDebit(
              debitBaseUnits: tokenBaseUnitsDebit, isToken: true,
            );
          },
          onViewActivity: () {
            Navigator.of(context).maybePop();
            _restoreScrollToBalanceAnchor();
          },
        ),
      ).whenComplete(() {
        if (mounted) {
          _loadAddressAndBalance();
          _restoreScrollToBalanceAnchor();
        }
      });
      return;
    }
    if (_isSolana) {
      final sendOn = widget.features?.solanaSendEnabled ?? false;
      if (!sendOn) {
        _showSnackBar(kAssetDetailSolanaSendDisabledMessage);
        return;
      }
      if (widget.authToken == null || widget.apiClient == null
          || widget.decryptForVault == null
          || widget.isVaultKeyAvailable == null) {
        _showSnackBar(kAssetDetailSendNotReadyBanner);
        return;
      }
      final fromAddress = _address;
      if (fromAddress == null || fromAddress.isEmpty) {
        _showSnackBar(
          'No Solana wallet exists yet. Tap Receive to create one '
          'before sending.',
        );
        return;
      }
      if (!mounted) return;
      // 2026-07-14 (Round 7 hardening): wire the SOL send panel with
      // the same shape as ETH — balance hook (lamports), onSuccessful-
      // Broadcast for optimistic pending debit, post-Send balance
      // refresh via .whenComplete.
      // ignore: discarded_futures
      showCryptoWalletSheet<void>(
        context: context,
        title: 'Send SOL',
        sheetKey: 'crypto_wallet_engine_asset_detail_solana_send_sheet',
        bodyOwnsLayout: true,
        child: CryptoWalletEngineSolanaSendPanel(
          key: const Key(
            'crypto_wallet_engine_asset_detail_solana_send_panel',
          ),
          authToken: widget.authToken!,
          fromAddress: fromAddress,
          client: widget.apiClient!,
          decryptForVault: widget.decryptForVault!,
          isVaultKeyAvailable: widget.isVaultKeyAvailable!,
          verifyPin: widget.verifyPin,
          features: widget.features,
          fetchAvailableLamports: () async => _balanceBaseUnits,
          onSuccessfulBroadcast: (
              {required String signature,
               required BigInt debitLamports}) {
            _applyOptimisticDebit(
              debitBaseUnits: debitLamports, isToken: false,
            );
          },
          onViewActivity: () {
            Navigator.of(context).maybePop();
            _restoreScrollToBalanceAnchor();
          },
        ),
      ).whenComplete(() {
        if (mounted) {
          _loadAddressAndBalance();
          _restoreScrollToBalanceAnchor();
        }
      });
      return;
    }
    if (!_isSupported || !_hasSendWiring) {
      _showSnackBar(kAssetDetailSendNotReadyBanner);
      return;
    }
    // 2026-07-13 fix: prefer the already-loaded _address (populated by
    // _loadAddressAndBalance → loadAssetWalletState which uses the
    // network-scoped endpoint — same source of truth as the Balance
    // and Receive displays). Fall back to the network-scoped
    // loadFromAddress callback if _address hasn't loaded yet.
    // Previously we called widget.loadFromAddress!() with no network
    // arg, which hit the legacy /crypto/wallet/ETH/receive endpoint
    // and returned no_account because the ETH mainnet wallet is
    // persisted under service='ETH:ethereum_mainnet' — the exact
    // production bug the user reported.
    String? fromAddress = _address;
    if (fromAddress == null || fromAddress.isEmpty) {
      fromAddress = await widget.loadFromAddress!(widget.effectiveNetwork);
    }
    if (fromAddress == null || fromAddress.isEmpty) {
      _showSnackBar(
        'No Ethereum wallet exists yet. Tap Receive to create one '
        'before sending.',
      );
      return;
    }
    if (!mounted) return;
    // 2026-07-13 (Round 5 hardening): thread the last-known live
    // balances into the Send panel so BOTH the pre-draft coarse
    // check (`fetchAvailableBalance` double) AND the post-draft
    // integer-exact fee gate (`fetchAvailableBalanceWei` +
    // `fetchEthBalanceWei` BigInt) actually run in production.
    // Previously the asset-detail Send opener wired NEITHER, so the
    // Round-4 integer-exact gate never fired on the ETH send path
    // and only the backend gate caught misauthorized attempts.
    final isToken =
        widget.asset == 'USDT_ERC20' || widget.asset == 'USDC_ERC20';

    // ignore: discarded_futures
    showCryptoWalletSheet<void>(
      context: context,
      title: 'Send ${_shortAssetLabel(widget.asset)}',
      sheetKey: 'crypto_wallet_engine_asset_detail_send_sheet',
      bodyOwnsLayout: true,
      child: CryptoWalletEngineSendPanel(
        key: Key(
          'crypto_wallet_engine_asset_detail_send_panel_${widget.asset}',
        ),
        authToken: widget.authToken!,
        fromAddress: fromAddress,
        client: widget.apiClient!,
        decryptForVault: widget.decryptForVault!,
        isVaultKeyAvailable: widget.isVaultKeyAvailable!,
        verifyPin: widget.verifyPin,
        asset: widget.asset,
        network: widget.effectiveNetwork,
        mainnetSendEnabled:
            widget.features?.effectiveMainnetSendEnabled ?? false,
        mainnetSendPaused: widget.features?.mainnetSendPaused ?? false,
        fetchAvailableBalance: () async {
          final s = _balance;
          if (s == null || s.isEmpty) return null;
          return double.tryParse(s);
        },
        fetchAvailableBalanceWei: () async => _balanceBaseUnits,
        fetchEthBalance: isToken
            ? () async {
                final w = _ethBalanceWei;
                if (w == null) return null;
                return w / BigInt.from(1000000000000000000);
              }
            : null,
        fetchEthBalanceWei: isToken ? () async => _ethBalanceWei : null,
        onSuccessfulBroadcast: (
          {required String txHash,
           required BigInt debitBaseUnits}) {
          _applyOptimisticDebit(
            debitBaseUnits: debitBaseUnits, isToken: isToken,
          );
        },
      ),
    ).whenComplete(() {
      // 2026-07-13 (Round 5 hardening): mirror the Receive-sheet
      // pattern. Sending a transaction always warrants a live
      // balance refresh — even the "cancelled" case, because the
      // user may have already triggered a broadcast in a background
      // browser tab.
      if (mounted) {
        _loadAddressAndBalance();
        _restoreScrollToBalanceAnchor();
      }
    });
  }

  Future<void> _copyAddress() async {
    final addr = _address;
    if (addr == null || addr.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: addr));
    if (!mounted) return;
    _showSnackBar(kAssetDetailCopyDoneSnackbar);
  }

  @override
  Widget build(BuildContext context) {
    final label = kCryptoWalletEngineAssetLabels[widget.asset] ?? widget.asset;
    final network = kCryptoWalletEngineNetworkLabels[widget.asset] ?? '';
    return Theme(
      data: walletDarkPanelTheme(context),
      child: Scaffold(
        key: const Key('crypto_wallet_engine_asset_detail_page'),
        backgroundColor: kWalletBgBase,
        appBar: AppBar(
          backgroundColor: kWalletBgBase,
          surfaceTintColor: kWalletBgBase,
          foregroundColor: kWalletTextPrimary,
          elevation: 0,
          // 2026-07-13 (Round 5 hardening): visible bottom border on
          // the app bar so scrolled content doesn't visually merge
          // with the header on iPhone Safari — the previous
          // opaque-same-color chrome made the balance card look as
          // if it started underneath the header, which was the
          // reported layout bug.
          shape: const Border(
            bottom: BorderSide(
              color: kWalletBorder,
              width: 1,
            ),
          ),
          title: Text(
            label,
            key: const Key('crypto_wallet_engine_asset_detail_title'),
            style: const TextStyle(
              color: kWalletTextPrimary,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        body: DecoratedBox(
          decoration: walletPageBackground(),
          child: SafeArea(
            // 2026-07-13 (Round 5 hardening): explicit bottom=false
            // so the SafeArea does not double-reserve iOS home-
            // indicator inset — the outer scroll view handles its
            // own bottom padding, and the AppBar reserves top.
            top: true,
            bottom: false,
            child: RefreshIndicator(
              key: const Key(
                'crypto_wallet_engine_asset_detail_refresh_indicator',
              ),
              onRefresh: () async {
                if (_isSupported && _hasReceiveWiring) {
                  await _loadAddressAndBalance();
                }
              },
              child: SingleChildScrollView(
                controller: _pageScrollCtrl,
                physics: const AlwaysScrollableScrollPhysics(),
                padding: EdgeInsets.only(
                  left: 18,
                  right: 18,
                  top: 18,
                  // Reserve room past the iOS home indicator so the
                  // last card is fully tappable.
                  bottom: 18 +
                      MediaQuery.of(context).viewPadding.bottom,
                ),
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 700),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _buildHeader(label, network),
                        const SizedBox(height: 18),

                        if (!_isSupported)
                          _buildComingSoonPanel()
                        else
                          ..._buildSupportedAssetSections(),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(String label, String fallbackNetwork) {
    final networkLabel = assetDetailNetworkLabel(
      asset: widget.asset,
      network: widget.effectiveNetwork,
    );
    final isSepolia = assetDetailIsSepolia(
      asset: widget.asset,
      network: widget.effectiveNetwork,
    );
    return Container(
      key: const Key('crypto_wallet_engine_asset_detail_header'),
      padding: const EdgeInsets.all(18),
      decoration: walletAssetCard(widget.asset),
      child: Row(
        children: [
          walletAssetIcon(widget.asset, size: 48),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(
                    color: kWalletTextPrimary,
                    fontSize: 22,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.2,
                  ),
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Icon(
                      isSepolia
                          ? Icons.science_outlined
                          : Icons.lock_outline,
                      size: 14,
                      color: kWalletTextSecondary,
                    ),
                    const SizedBox(width: 6),
                    Flexible(
                      child: Text(
                        networkLabel,
                        key: const Key(
                          'crypto_wallet_engine_asset_detail_network_label',
                        ),
                        style: const TextStyle(
                          color: kWalletTextSecondary, fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _buildSupportedAssetSections() {
    final addr = _address;
    final balText = _balance != null
        ? '${_balance!}${_balanceUnit != null ? ' $_balanceUnit' : ''}'
        : null;
    return [
      if (_isMoneroLive) ...[
        CryptoWalletEngineMoneroScannerCard(
          scannerAdapter: widget.moneroScannerAdapter,
          features: widget.features,
          status: _moneroScannerStatus,
          backendStatus: _backendMoneroScannerStatus,
          onStart: _startMoneroScan,
          onStop: _stopMoneroScan,
        ),
        if (_moneroScannerInlineMessage != null) ...[
          const SizedBox(height: 8),
          Container(
            key: const Key('monero_scanner_inline_message'),
            padding: const EdgeInsets.all(10),
            decoration: walletWarningPanel(),
            child: Text(
              _moneroScannerInlineMessage!,
              style: const TextStyle(
                color: kWalletAccentWarning, fontSize: 13,
              ),
            ),
          ),
        ],
        const SizedBox(height: 14),
        CryptoWalletEngineMoneroBalanceCard(
          features: widget.features,
          scannerStatus: _moneroScannerStatus,
          backendStatus: _backendMoneroScannerStatus,
          balance: _moneroBalanceReading,
        ),
        const SizedBox(height: 14),


        _buildMoneroDevReasonHint(),
      ] else
      _buildBalanceCard(balText),
      const SizedBox(height: 14),
      
      Container(
        key: const Key('crypto_wallet_engine_asset_detail_address'),
        padding: const EdgeInsets.all(18),
        decoration: walletDarkCard(),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              kAssetDetailAddressHeaderLabel,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: kWalletTextSecondary,
                letterSpacing: 0.3,
              ),
            ),
            const SizedBox(height: 8),
            if (_addressLoading)
              Row(
                key: const Key(
                  'crypto_wallet_engine_asset_detail_address_loading',
                ),
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Icon(
                    Icons.hourglass_top_outlined,
                    size: 14,
                    color: kWalletTextMuted,
                  ),
                  SizedBox(width: 8),
                  Text(kAssetDetailLoadingWalletCopy, style: kWalletBodyStyle),
                ],
              )
            else if (addr != null && addr.isNotEmpty)
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: kWalletBgBase,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: kWalletBorder),
                ),
                child: SelectableText(
                  addr,
                  key: const Key(
                    'crypto_wallet_engine_asset_detail_address_text',
                  ),
                  style: kWalletMonoStyle,
                ),
              )
            else
              const Text(
                kAssetDetailNoWalletAddressCopy,
                key: Key(
                  'crypto_wallet_engine_asset_detail_address_no_wallet',
                ),
                style: kWalletBodyStyle,
              ),
            if (addr != null && addr.isNotEmpty) ...[
              const SizedBox(height: 10),
              OutlinedButton.icon(
                key: const Key(
                  'crypto_wallet_engine_asset_detail_copy_btn',
                ),
                onPressed: _copyAddress,
                icon: const Icon(Icons.copy_rounded, size: 16),
                label: const Text(kAssetDetailCopyAddressLabel),
                style: walletGhostButtonStyle(),
              ),
            ],
          ],
        ),
      ),
      const SizedBox(height: 14),
      
      Wrap(
        key: const Key('crypto_wallet_engine_asset_detail_actions'),
        spacing: 10,
        runSpacing: 10,
        children: [
          ElevatedButton.icon(
            key: const Key(
              'crypto_wallet_engine_asset_detail_receive_btn',
            ),
            onPressed: _openReceivePanel,
            icon: const Icon(Icons.south_rounded, size: 18),
            label: const Text(kAssetDetailReceiveLabel),
            style: walletPrimaryButtonStyle(),
          ),
          if (!_isMonero)
            ElevatedButton.icon(
              key: const Key(
                'crypto_wallet_engine_asset_detail_send_btn',
              ),
              onPressed: _openSendPanel,
              icon: const Icon(Icons.north_rounded, size: 18),
              label: const Text(kAssetDetailSendLabel),
              style: walletSecondaryButtonStyle(),
            ),
        ],
      ),
      if (_isMonero) ...[
        const SizedBox(height: 8),
        Text(
          kAssetDetailMoneroSendDisabledMessage,
          key: const Key(
            'crypto_wallet_engine_asset_detail_xmr_send_disabled_note',
          ),
          style: const TextStyle(
            color: kWalletTextMuted, fontSize: 12,
          ),
        ),
      ],
      if (_isToken) ...[
        const SizedBox(height: 14),
        Container(
          key: const Key(
            'crypto_wallet_engine_asset_detail_token_shared_address',
          ),
          padding: const EdgeInsets.all(12),
          decoration: walletSuccessPanel(),
          child: const Row(
            children: [
              Icon(Icons.link_rounded, size: 16,
                  color: kWalletAccentSuccess),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  kAssetDetailTokenSharedAddressNote,
                  style: TextStyle(
                    color: kWalletAccentSuccess,
                    fontSize: 13,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        Container(
          key: const Key(
            'crypto_wallet_engine_asset_detail_token_gas_note',
          ),
          padding: const EdgeInsets.all(12),
          decoration: walletWarningPanel(),
          child: const Row(
            children: [
              Icon(Icons.local_gas_station_rounded, size: 16,
                  color: kWalletAccentWarning),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  kAssetDetailTokenGasNote,
                  style: TextStyle(
                    color: kWalletAccentWarning,
                    fontSize: 13,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
      const SizedBox(height: 16),
      _buildActivityPanel(),
      const SizedBox(height: 12),
      _buildBackupPanel(),
    ];
  }

  Widget _buildBalanceCard(String? balText) {
    final networkKind = walletNetworkKindFor(
      asset: widget.asset, network: widget.network,
    );
    String? effectiveReason = _balanceReason;
    if (effectiveReason == null
        && !_balanceLoading
        && !_addressLoading
        && (_address == null || _address!.isEmpty)) {
      effectiveReason = 'no_wallet_yet';
    }




    final showBalanceLoading = _balanceLoading || _addressLoading;

    final render = effectiveReason == null
        ? null
        : walletBalanceReasonRender(
            reason: effectiveReason,
            asset: widget.asset,
            networkKind: networkKind,
          );
    // 2026-07-13 (Round 5 hardening): humanized "last updated"
    // staleness copy. Shown when balance has ever loaded successfully
    // AND we know the timestamp — makes it obvious the number
    // could be stale after an RPC hiccup instead of pretending it's
    // fresh.
    String? staleness;
    if (balText != null && _balanceUpdatedAt != null) {
      final secs = DateTime.now()
          .difference(_balanceUpdatedAt!)
          .inSeconds;
      if (secs >= 8) {
        if (secs < 60) {
          staleness = 'Updated ${secs}s ago';
        } else if (secs < 3600) {
          staleness = 'Updated ${(secs / 60).floor()}m ago';
        } else {
          staleness = 'Updated ${(secs / 3600).floor()}h ago';
        }
      }
    }
    return Container(
      key: _balanceCardAnchorKey,
      padding: const EdgeInsets.all(18),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  kAssetDetailBalanceHeaderLabel,
                  key: Key('crypto_wallet_engine_asset_detail_balance'),
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: kWalletTextSecondary,
                    letterSpacing: 0.3,
                  ),
                ),
              ),
              IconButton(
                key: const Key(kAssetDetailBalanceRefreshBtnKey),
                tooltip: 'Refresh balance',
                iconSize: 18,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints.tightFor(
                  width: 28, height: 28,
                ),
                icon: const Icon(
                  Icons.refresh_rounded,
                  color: kWalletTextSecondary,
                ),
                onPressed: _balanceLoading ? null : _refreshBalance,
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (showBalanceLoading && balText == null)
            // Loading + never had a value → show honest "loading"
            // copy. If we DO already have a value, we render it
            // below with a refresh-in-progress hint so the number
            // never blanks to "0" or empty during a refetch.
            Row(
              key: const Key(
                'crypto_wallet_engine_asset_detail_balance_loading',
              ),
              mainAxisSize: MainAxisSize.min,
              children: const [
                Icon(
                  Icons.hourglass_top_outlined,
                  size: 14,
                  color: kWalletTextMuted,
                ),
                SizedBox(width: 8),
                Text(kAssetDetailLoadingBalanceCopy,
                    style: kWalletBodyStyle),
              ],
            )
          else if (balText != null)
            _buildBalanceValueBlock(balText, staleness, showBalanceLoading)
          else if (render != null)
            Text(
              render.message,
              key: Key(render.bodyKey),
              style: kWalletBodyStyle,
            )
          else
            const Text(
              kAssetDetailNoWalletBalanceCopy,
              key: Key(
                'crypto_wallet_engine_asset_detail_balance_no_reason_fallback',
              ),
              style: kWalletBodyStyle,
            ),
        ],
      ),
    );
  }

  // 2026-07-13 (Round 5 hardening): balance value block. Renders the
  // number with a `StrutStyle` so display-tier font sizes don't clip
  // their ascenders on iPhone Safari, plus an inline pending-debit
  // hint (if a Send just landed but the chain hasn't caught up) and
  // an "Updated Ns ago" staleness line so users can tell fresh from
  // stale at a glance.
  Widget _buildBalanceValueBlock(
    String balText, String? staleness, bool refreshInFlight,
  ) {
    final fontSize = vrDisplay(context);
    // Optimistic pending debit annotation. Only rendered when we
    // have a numeric-parseable balance and a pending debit.
    String? pendingHint;
    if (_pendingDebitWei != null || _pendingDebitBaseUnits != null) {
      pendingHint = 'Pending outgoing transaction — balance updates '
          'when the chain confirms';
    }
    return Column(
      key: const Key(
        'crypto_wallet_engine_asset_detail_balance_value_block',
      ),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          balText,
          key: const Key(
            'crypto_wallet_engine_asset_detail_balance_value',
          ),
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          strutStyle: StrutStyle(
            fontSize: fontSize,
            forceStrutHeight: true,
            leading: 0.2,
          ),
          style: TextStyle(
            color: kWalletTextPrimary,
            fontSize: fontSize,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.4,
            height: 1.05,
          ),
        ),
        if (refreshInFlight)
          const Padding(
            key: Key(
              'crypto_wallet_engine_asset_detail_balance_refresh_hint',
            ),
            padding: EdgeInsets.only(top: 4),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 10, height: 10,
                  child: CircularProgressIndicator(
                    strokeWidth: 1.5,
                    valueColor: AlwaysStoppedAnimation<Color>(
                      kWalletTextMuted,
                    ),
                  ),
                ),
                SizedBox(width: 6),
                Text('Refreshing…',
                    style: TextStyle(
                      color: kWalletTextMuted, fontSize: 11,
                    )),
              ],
            ),
          ),
        if (pendingHint != null)
          Padding(
            key: const Key(
              'crypto_wallet_engine_asset_detail_balance_pending_hint',
            ),
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              pendingHint,
              style: const TextStyle(
                color: kWalletAccentWarning, fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        if (staleness != null)
          Padding(
            key: const Key(
              'crypto_wallet_engine_asset_detail_balance_staleness',
            ),
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              staleness,
              style: const TextStyle(
                color: kWalletTextMuted, fontSize: 11,
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildMoneroDevReasonHint() {

    final s = _backendMoneroScannerStatus;
    final reason = s?.reason ?? 'unknown';
    final mode   = s?.mode   ?? 'unknown';
    final platform = moneroClientPlatform();
    return Visibility(
      visible: kDebugMode,
      maintainState: true,
      maintainSize:  false,
      maintainAnimation: true,
      child: Padding(
        key: const Key(
          'crypto_wallet_engine_asset_detail_monero_dev_reason',
        ),
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Text(
          'reason=$reason  mode=$mode  platform=$platform',
          style: const TextStyle(
            color: kWalletTextMuted,
            fontSize: 10,
            fontFamily: 'monospace',
          ),
        ),
      ),
    );
  }


  Widget _buildActivityPanel() {




    if (_isMoneroLive) {
      return Container(
        key: const Key(
          'crypto_wallet_engine_asset_detail_monero_activity',
        ),
        child: CryptoWalletEngineMoneroActivityCard(
          features: widget.features,
          scannerStatus: _moneroScannerStatus,
          backendStatus: _backendMoneroScannerStatus,
          transactions: _moneroTransactions,
        ),
      );
    }




    final walletKnownAbsent = !_addressLoading
        && (_address == null || _address!.isEmpty);
    if (walletKnownAbsent) {
      return _buildActivityNoWalletCard();
    }
    if (_addressLoading) {
      return _buildActivityLoadingCard();
    }




    if (_isSolana) {
      return Container(
        key: const Key(
          'crypto_wallet_engine_asset_detail_solana_activity',
        ),
        child: CryptoWalletEngineSolanaActivityCard(
          authToken: widget.authToken,
          apiClient: widget.apiClient,
          features: widget.features,
        ),
      );
    }
    if (_isTron) {
      return Container(
        key: const Key(
          'crypto_wallet_engine_asset_detail_tron_activity',
        ),
        child: CryptoWalletEngineTronActivityCard(
          features: widget.features,
        ),
      );
    }
    return Container(
      key: const Key('crypto_wallet_engine_asset_detail_activity'),
      child: CryptoWalletActivityCard(
        key: Key(
          'crypto_wallet_engine_asset_detail_activity_card_${widget.asset}',
        ),
        asset: widget.asset,
        authToken: widget.authToken,
        apiClient: widget.apiClient,
        network: widget.network,
      ),
    );
  }


  Widget _buildActivityNoWalletCard() {
    return Container(
      key: const Key(
        'crypto_wallet_engine_asset_detail_activity_no_wallet',
      ),
      padding: const EdgeInsets.all(16),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: const [
          Row(
            children: [
              Icon(Icons.history_rounded, size: 18,
                  color: kWalletTextSecondary),
              SizedBox(width: 8),
              Text(
                kAssetDetailActivityHeaderLabel,
                style: kWalletSectionHeadingStyle,
              ),
            ],
          ),
          SizedBox(height: 10),
          Text(
            kAssetDetailNoWalletActivityCopy,
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }

  Widget _buildActivityLoadingCard() {
    return Container(
      key: const Key(
        'crypto_wallet_engine_asset_detail_activity_loading',
      ),
      padding: const EdgeInsets.all(16),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: const [
          Row(
            children: [
              Icon(Icons.history_rounded, size: 18,
                  color: kWalletTextSecondary),
              SizedBox(width: 8),
              Text(
                kAssetDetailActivityHeaderLabel,
                style: kWalletSectionHeadingStyle,
              ),
            ],
          ),
          SizedBox(height: 10),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.hourglass_top_outlined,
                size: 14, color: kWalletTextMuted,
              ),
              SizedBox(width: 8),
              Text(
                kAssetDetailLoadingActivityCopy,
                style: kWalletBodyStyle,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildBackupPanel() {
    final hasAddress = _address != null && _address!.isNotEmpty;
    return Container(
      key: const Key('crypto_wallet_engine_asset_detail_backup'),
      padding: const EdgeInsets.all(16),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.shield_outlined,
                  size: 16, color: kWalletAccentSuccess),
              SizedBox(width: 8),
              Text(
                kAssetDetailBackupHeaderLabel,
                style: TextStyle(
                  color: kWalletTextPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            hasAddress
                ? kAssetDetailBackupSaved
                : kAssetDetailBackupMissing,
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }

  Widget _buildComingSoonPanel() {
    return Container(
      key: const Key('crypto_wallet_engine_asset_detail_coming_soon'),
      padding: const EdgeInsets.all(18),
      decoration: walletDarkCard(accent: kWalletAccentPrimarySoft),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              walletAssetIcon(widget.asset, size: 36),
              const SizedBox(width: 12),
              const Expanded(
                child: Text(
                  kAssetDetailComingSoonHeading,
                  style: TextStyle(
                    color: kWalletTextPrimary,
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.1,
                  ),
                ),
              ),
              walletStatusBadge(
                kCryptoWalletEngineFutureStateLabel[widget.asset]
                    ?? 'Unavailable',
                tone: WalletBadgeTone.planned,
                key: const Key(
                  'crypto_wallet_engine_asset_detail_coming_soon_badge',
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          const Text(
            kAssetDetailComingSoonBody,
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }
}


const String kAssetDetailTestnetWarning = kEvmNetworkTestnetWarning;
