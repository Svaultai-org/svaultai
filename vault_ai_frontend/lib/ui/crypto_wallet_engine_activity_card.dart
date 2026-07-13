

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../services/durable_outgoing_history_store.dart';
import '../services/local_outgoing_tx_store.dart';
import 'crypto_wallet_engine_design.dart';


const String kActivityCardSchemaV1 = 'crypto_wallet_transaction_v1';

const String kActivityDirectionIncoming = 'incoming';
const String kActivityDirectionOutgoing = 'outgoing';

const String kActivityStatusPending   = 'pending';
const String kActivityStatusConfirmed = 'confirmed';
const String kActivityStatusFailed    = 'failed';
const String kActivityStatusUnknown   = 'unknown';

// 2026-07-13 canary correctness: locally-tracked outgoing states.
// Merged into the same list as indexer rows so a broadcast the
// indexer has not yet discovered still appears immediately.
const String kActivityStatusSubmitting          = 'submitting';
const String kActivityStatusSubmitted           = 'submitted';
const String kActivityStatusSubmissionUncertain = 'submission_uncertain';
const String kActivityStatusExplicitlyRejected  = 'explicitly_rejected';
const String kActivityStatusDropped             = 'dropped';

const String kActivitySourceIndexer = 'indexer';
const String kActivitySourceLocal   = 'local';
const String kActivitySourceDurable = 'durable';

const String kActivityTxsStatusAvailable   = 'available';
const String kActivityTxsStatusUnavailable = 'unavailable';

const String kActivityReasonIndexerNotConfigured = 'indexer_not_configured';
const String kActivityReasonUpstreamError       = 'upstream_error';
const String kActivityReasonNoWalletYet         = 'no_wallet_yet';
const String kActivityReasonInvalidAddress      = 'invalid_address';

const String kActivityCardHeaderLabel = 'Activity';

const String kActivityCopyHonestUnavailable =
    'Transaction history is not connected yet.';




const String kActivityCopyEmptyMainnet =
    'No activity yet. Sent and received transactions appear here after '
    'the Ethereum indexer sees them.';
const String kActivityCopyEmptySepolia =
    'No activity yet. Sent and received transactions appear here after '
    'the Ethereum Sepolia Testnet indexer sees them.';
const String kActivityCopyEmptyDefault =
    'No activity yet.';


const String kActivityCopyEmptyMainnetEth =
    'No activity yet. Sent and received ETH transactions appear here '
    'after the Ethereum indexer sees them.';
const String kActivityCopyEmptyMainnetUsdtErc20 =
    'No activity yet. Sent and received USDT transactions appear here '
    'after the Ethereum indexer sees them.';
const String kActivityCopyEmptyMainnetUsdcErc20 =
    'No activity yet. Sent and received USDC transactions appear here '
    'after the Ethereum indexer sees them.';




const String kActivityCopyEmptySolana =
    'No activity yet.';
const String kActivityCopyEmptyTron =
    'TRON activity history is not connected yet.';
const String kActivityCopyEmptyMonero =
    'Monero scanning is not available in this build yet.';


String activityCopyEmptyForNetwork(String? network, {String? asset}) {
  if (network == 'ethereum_mainnet') {
    if (asset == 'ETH')         return kActivityCopyEmptyMainnetEth;
    if (asset == 'USDT_ERC20')  return kActivityCopyEmptyMainnetUsdtErc20;
    if (asset == 'USDC_ERC20')  return kActivityCopyEmptyMainnetUsdcErc20;
    return kActivityCopyEmptyMainnet;
  }
  if (network == 'ethereum_sepolia') return kActivityCopyEmptySepolia;
  if (network == 'solana_mainnet')   return kActivityCopyEmptySolana;
  if (network == 'tron_mainnet')     return kActivityCopyEmptyTron;
  if (network == 'monero_mainnet')   return kActivityCopyEmptyMonero;
  return kActivityCopyEmptyDefault;
}


@Deprecated('Use activityCopyEmptyForNetwork(network) instead.')
const String kActivityCopyEmpty = kActivityCopyEmptyDefault;

const String kActivityCopyError =
    'Could not load transaction history.';
const String kActivityCopyLoading = 'Loading activity…';




const String kActivityCopyNoWalletYetMainnet =
    'Create your Ethereum Mainnet wallet first. Activity loads from '
    'the indexer using your public wallet address.';
const String kActivityCopyNoWalletYetSepolia =
    'Create your Ethereum Sepolia Testnet wallet first. Activity loads '
    'from the indexer using your public wallet address.';
const String kActivityCopyNoWalletYetDefault =
    'Create your wallet first. Activity loads from the indexer using '
    'your public wallet address.';


String activityCopyNoWalletYetForNetwork(String? network) {
  if (network == 'ethereum_mainnet') return kActivityCopyNoWalletYetMainnet;
  if (network == 'ethereum_sepolia') return kActivityCopyNoWalletYetSepolia;
  return kActivityCopyNoWalletYetDefault;
}


@Deprecated('Use activityCopyNoWalletYetForNetwork(network) instead.')
const String kActivityCopyNoWalletYet = kActivityCopyNoWalletYetDefault;

const String kActivityCopyTxHashCopied = 'Transaction hash copied';

const Set<String> kActivityLiveAssets = {
  'ETH', 'USDT_ERC20', 'USDC_ERC20',
};


String activityTxHashShort(String? raw) {
  if (raw == null || raw.length < 12) return '';
  final re = RegExp(r'^0x[0-9a-fA-F]{64}$');
  if (!re.hasMatch(raw)) return '';
  return '${raw.substring(0, 8)}…${raw.substring(raw.length - 4)}';
}


class CryptoWalletActivityRow {
  final String txHash;
  final String direction;
  final String amount;
  final String unit;
  final String status;
  final int confirmations;
  final String fromAddress;
  final String toAddress;
  final int? timestamp;
  final String source;

  const CryptoWalletActivityRow({
    required this.txHash,
    required this.direction,
    required this.amount,
    required this.unit,
    required this.status,
    required this.confirmations,
    required this.fromAddress,
    required this.toAddress,
    required this.timestamp,
    required this.source,
  });

  bool get isIncoming => direction == kActivityDirectionIncoming;
  bool get isOutgoing => direction == kActivityDirectionOutgoing;

  static CryptoWalletActivityRow? fromJson(Map<String, dynamic> raw) {
    final tx = raw['txHash'];
    if (tx is! String || tx.isEmpty) return null;
    return CryptoWalletActivityRow(
      txHash:        tx,
      direction:     (raw['direction'] ?? '').toString(),
      amount:        (raw['amount'] ?? '').toString(),
      unit:          (raw['unit'] ?? '').toString(),
      status:        (raw['status'] ?? kActivityStatusUnknown).toString(),
      confirmations: raw['confirmations'] is int
          ? raw['confirmations'] as int
          : 0,
      fromAddress:   (raw['fromAddress'] ?? '').toString(),
      toAddress:     (raw['toAddress'] ?? '').toString(),
      timestamp:     raw['timestamp'] is int
          ? raw['timestamp'] as int
          : null,
      source:        (raw['source'] ?? 'indexer').toString(),
    );
  }
}


class CryptoWalletActivityCard extends StatefulWidget {
  final String asset;
  final String? authToken;
  final VaultAIClient? apiClient;
  final int limit;
  final String? network;

  /// 2026-07-13 canary correctness: optional local outgoing store.
  /// Rows in the store are merged with indexer results (dedup by
  /// txHash, case-insensitive; local wins over durable in Merge
  /// precedence because it carries the honest submission-uncertain /
  /// dropped state that neither durable nor indexer expresses).
  final LocalOutgoingTxStore? localStore;

  /// 2026-07-13 durability slice: optional vault-scoped durable
  /// outgoing history. Rebuilds automatically when the store
  /// notifies. When wired, the activity card refreshes the durable
  /// snapshot on mount (and when the local store changes, since a
  /// new outgoing broadcast may have just landed).
  final DurableOutgoingHistoryStore? durableStore;

  const CryptoWalletActivityCard({
    super.key,
    required this.asset,
    this.authToken,
    this.apiClient,
    this.limit = 20,
    this.network,
    this.localStore,
    this.durableStore,
  });

  @override
  State<CryptoWalletActivityCard> createState() =>
      _CryptoWalletActivityCardState();
}

enum _ActivityFetchState { loading, ok, error }

class _CryptoWalletActivityCardState extends State<CryptoWalletActivityCard> {
  _ActivityFetchState _state = _ActivityFetchState.loading;
  String _txsStatus = kActivityTxsStatusUnavailable;
  String? _reason;
  List<CryptoWalletActivityRow> _rows = const [];

  @override
  void initState() {
    super.initState();
    widget.localStore?.addListener(_onLocalStoreChanged);
    widget.durableStore?.addListener(_onDurableStoreChanged);
    _load();
    _refreshDurableIfWired();
  }

  @override
  void didUpdateWidget(covariant CryptoWalletActivityCard old) {
    super.didUpdateWidget(old);
    if (!identical(old.localStore, widget.localStore)) {
      old.localStore?.removeListener(_onLocalStoreChanged);
      widget.localStore?.addListener(_onLocalStoreChanged);
    }
    if (!identical(old.durableStore, widget.durableStore)) {
      old.durableStore?.removeListener(_onDurableStoreChanged);
      widget.durableStore?.addListener(_onDurableStoreChanged);
      _refreshDurableIfWired();
    }
    if (old.network != widget.network) {
      _refreshDurableIfWired();
    }
  }

  @override
  void dispose() {
    widget.localStore?.removeListener(_onLocalStoreChanged);
    widget.durableStore?.removeListener(_onDurableStoreChanged);
    super.dispose();
  }

  void _onLocalStoreChanged() {
    if (!mounted) return;
    // No re-fetch of the INDEXER — its rows are unchanged. But a new
    // outgoing broadcast typically triggers a durable-history row to
    // land on the backend within the same request, so kick a durable
    // refresh here so the merged snapshot converges quickly instead
    // of waiting for the next mount.
    _refreshDurableIfWired();
    setState(() {});
  }

  void _onDurableStoreChanged() {
    if (!mounted) return;
    // Durable snapshot changed (fetch completed or was seeded). Just
    // repaint — `_merged()` picks up the new rows.
    setState(() {});
  }

  void _refreshDurableIfWired() {
    final ds = widget.durableStore;
    final net = widget.network;
    if (ds == null || net == null || net.isEmpty) return;
    // Fire-and-forget; the store captures errors internally.
    // ignore: discarded_futures
    ds.refresh(net);
  }

  bool get _hasWiring =>
      widget.authToken != null && widget.apiClient != null;

  Future<void> _load() async {
    if (!_hasWiring) {
      setState(() {
        _state = _ActivityFetchState.ok;
        _txsStatus = kActivityTxsStatusUnavailable;
        _reason = kActivityReasonIndexerNotConfigured;
        _rows = const [];
      });
      return;
    }
    setState(() {
      _state = _ActivityFetchState.loading;
    });
    try {
      final body = widget.network != null
          ? await widget.apiClient!.listCryptoWalletTransactionsNetwork(
              network: widget.network!,
              asset: widget.asset,
              authToken: widget.authToken!,
              limit: widget.limit,
            )
          : await widget.apiClient!.listCryptoWalletTransactions(
              asset: widget.asset,
              authToken: widget.authToken!,
              limit: widget.limit,
            );
      if (!mounted) return;
      final status = (body['transactionsStatus'] ?? '').toString();
      final reason = (body['reason'] ?? '').toString();
      final txsRaw = body['transactions'];
      final rows = <CryptoWalletActivityRow>[];
      if (txsRaw is List) {
        for (final raw in txsRaw) {
          if (raw is Map) {
            final row = CryptoWalletActivityRow.fromJson(
              raw.cast<String, dynamic>(),
            );
            if (row != null) rows.add(row);
          }
        }
      }
      setState(() {
        _state = _ActivityFetchState.ok;
        _txsStatus = status;
        _reason = reason.isEmpty ? null : reason;
        _rows = rows;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _state = _ActivityFetchState.error;
      });
    }
  }

  /// 2026-07-13 canary correctness + durability slice: merge three
  /// sources into a single Activity feed. Precedence, MOST
  /// AUTHORITATIVE first, is:
  ///
  ///   1. INDEXER — chain-observed truth. If the indexer says the
  ///      transaction is `confirmed` or `failed`, that WINS over
  ///      every other source. The chain is authoritative for what
  ///      actually happened.
  ///   2. DURABLE — backend-recorded broadcast outcome (`submitted`,
  ///      `submission_uncertain`, `already_known`, `explicitly_rejected`).
  ///      Survives page reload / browser restart / re-authentication
  ///      because it lives in Postgres. Wins over local because a
  ///      fresh browser session cannot rebuild an in-memory row.
  ///   3. LOCAL — in-session snapshot. Only wins over durable while
  ///      the local snapshot is FRESHER (e.g. the broadcast just
  ///      returned in this session and the durable refresh has not
  ///      yet caught up) OR the local row expresses a state the
  ///      durable row cannot (`submitting`, `dropped`).
  ///
  /// Deduplication key is the lower-case tx hash. Row timestamps
  /// come from whichever source ends up representing the hash.
  List<CryptoWalletActivityRow> _merged() {
    final byHashLower = <String, CryptoWalletActivityRow>{};

    // Base layer: indexer rows.
    for (final r in _rows) {
      byHashLower[r.txHash.toLowerCase()] = r;
    }

    // Middle layer: durable rows (backend). Only fill in hashes not
    // already covered by the indexer, and never downgrade a chain-
    // observed row. Durable rows that name a hash the indexer
    // already reported are SKIPPED — the indexer's confirmed/failed
    // is chain truth.
    final durableStore = widget.durableStore;
    if (durableStore != null && (widget.network ?? '').isNotEmpty) {
      final durables = durableStore.rowsFor(
        networkId: widget.network ?? '',
        asset: widget.asset,
      );
      for (final d in durables) {
        final hashLower = d.localTxHash.toLowerCase();
        if (hashLower.isEmpty) continue;
        final existing = byHashLower[hashLower];
        if (existing != null &&
            _isChainObservedStatus(existing.status)) {
          continue;
        }
        byHashLower[hashLower] = _durableToActivityRow(d);
      }
    }

    // Top layer: local session rows. Merge rules:
    //   * If the existing row is chain-observed (confirmed/failed),
    //     LOCAL is skipped — chain wins.
    //   * If the local row is a strictly TRANSIENT state that only
    //     the session can express (submitting/dropped), LOCAL wins.
    //   * Otherwise the newer of the two (durable or local) wins by
    //     timestamp — so a fresh submissionUncertain from this
    //     session is not shadowed by a stale durable snapshot from
    //     before the tab was reopened.
    final store = widget.localStore;
    if (store != null) {
      final locals = store.rowsFor(
        networkId: widget.network ?? '',
        asset: widget.asset,
      );
      for (final l in locals) {
        final hashLower = l.txHash.toLowerCase();
        if (hashLower.isEmpty) continue;
        final existing = byHashLower[hashLower];
        final localRow = _localToActivityRow(l);
        if (existing == null) {
          byHashLower[hashLower] = localRow;
          continue;
        }
        if (_isChainObservedStatus(existing.status)) {
          continue;
        }
        if (_isLocalOnlyStatus(l.status)) {
          byHashLower[hashLower] = localRow;
          continue;
        }
        // Neither chain-observed nor local-only. Compare timestamps
        // — the fresher observation wins so a stale durable
        // submissionUncertain doesn't override a fresh confirmed
        // status the client just fetched via /transaction/{hash}.
        final ex = existing.timestamp ?? 0;
        final ll = localRow.timestamp ?? 0;
        if (ll >= ex) {
          byHashLower[hashLower] = localRow;
        }
      }
    }

    final out = byHashLower.values.toList();
    out.sort((a, b) {
      final ta = a.timestamp ?? 0;
      final tb = b.timestamp ?? 0;
      return tb.compareTo(ta);
    });
    return out;
  }

  static bool _isChainObservedStatus(String status) {
    return status == kActivityStatusConfirmed ||
        status == kActivityStatusFailed;
  }

  static bool _isLocalOnlyStatus(LocalOutgoingTxStatus s) {
    return s == LocalOutgoingTxStatus.submitting ||
        s == LocalOutgoingTxStatus.dropped;
  }

  CryptoWalletActivityRow _durableToActivityRow(DurableOutgoingTx d) {
    // Render "amount unit" using the backend-projected wei / decimals.
    // For ETH: valueWei -> ether string. For ERC-20: amountBaseUnits
    // may be null (calldata-encoded); fall back to "…" in that case.
    String amountStr;
    if (d.asset == 'ETH') {
      amountStr = _formatWeiAsEth(d.valueWei);
    } else if (d.amountBaseUnits != null) {
      amountStr = _formatBaseUnits(d.amountBaseUnits!, d.decimals);
    } else {
      amountStr = '…';
    }
    return CryptoWalletActivityRow(
      txHash: d.localTxHash,
      direction: kActivityDirectionOutgoing,
      amount: amountStr,
      unit: d.unit,
      status: _durableWireStatus(d.broadcastOutcome),
      confirmations: 0,
      fromAddress: d.fromAddress,
      toAddress: d.destinationAddress,
      timestamp: _preferSecondsToMillis(
        d.consumedAt ?? d.createdAt,
      ),
      source: kActivitySourceDurable,
    );
  }

  static int? _preferSecondsToMillis(double? epochSeconds) {
    if (epochSeconds == null) return null;
    return (epochSeconds * 1000).round();
  }

  static String _durableWireStatus(String? backendOutcome) {
    switch (backendOutcome) {
      case 'submitted':
      case 'already_known':
        return kActivityStatusSubmitted;
      case 'submission_uncertain':
        return kActivityStatusSubmissionUncertain;
      case 'explicitly_rejected':
        return kActivityStatusExplicitlyRejected;
      default:
        // Row exists in `crypto_mainnet_drafts` (`consumed_at` set)
        // but no outcome recorded yet — the broadcast handler
        // crashed mid-flight. Present as `submission_uncertain` so
        // the honest "we don't know" state surfaces.
        return kActivityStatusSubmissionUncertain;
    }
  }

  // Wei / base-units formatting kept minimal — this is Activity
  // subtitle text, not a signing surface.

  static String _formatWeiAsEth(BigInt wei) {
    if (wei == BigInt.zero) return '0';
    final whole = wei ~/ BigInt.from(1000000000000000000);
    final frac = wei - (whole * BigInt.from(1000000000000000000));
    if (frac == BigInt.zero) return whole.toString();
    final fracStr = frac.toString().padLeft(18, '0');
    final trimmed = fracStr.replaceFirst(RegExp(r'0+$'), '');
    return trimmed.isEmpty ? whole.toString() : '$whole.$trimmed';
  }

  static String _formatBaseUnits(BigInt v, int decimals) {
    if (decimals <= 0) return v.toString();
    final divisor = BigInt.from(10).pow(decimals);
    final whole = v ~/ divisor;
    final frac = v - (whole * divisor);
    if (frac == BigInt.zero) return whole.toString();
    final fracStr = frac.toString().padLeft(decimals, '0');
    final trimmed = fracStr.replaceFirst(RegExp(r'0+$'), '');
    return trimmed.isEmpty ? whole.toString() : '$whole.$trimmed';
  }

  CryptoWalletActivityRow _localToActivityRow(LocalOutgoingTx l) {
    return CryptoWalletActivityRow(
      txHash: l.txHash,
      direction: kActivityDirectionOutgoing,
      amount: l.amount,
      unit: l.unit,
      status: _wireStatus(l.status),
      confirmations: 0,
      fromAddress: l.fromAddress,
      toAddress: l.toAddress,
      timestamp: l.createdAt.millisecondsSinceEpoch,
      source: kActivitySourceLocal,
    );
  }

  static String _wireStatus(LocalOutgoingTxStatus s) {
    switch (s) {
      case LocalOutgoingTxStatus.submitting:
        return kActivityStatusSubmitting;
      case LocalOutgoingTxStatus.submitted:
        return kActivityStatusSubmitted;
      case LocalOutgoingTxStatus.pending:
        return kActivityStatusPending;
      case LocalOutgoingTxStatus.submissionUncertain:
        return kActivityStatusSubmissionUncertain;
      case LocalOutgoingTxStatus.confirmed:
        return kActivityStatusConfirmed;
      case LocalOutgoingTxStatus.failed:
        return kActivityStatusFailed;
      case LocalOutgoingTxStatus.explicitlyRejected:
        return kActivityStatusExplicitlyRejected;
      case LocalOutgoingTxStatus.dropped:
        return kActivityStatusDropped;
    }
  }

  Future<void> _copyTxHash(String txHash) async {
    await Clipboard.setData(ClipboardData(text: txHash));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        key: Key('crypto_wallet_activity_card_copy_snackbar'),
        content: Text(kActivityCopyTxHashCopied),
      ),
    );
  }

  String _unavailableCopy() {
    switch (_reason) {
      case kActivityReasonNoWalletYet:
        return activityCopyNoWalletYetForNetwork(widget.network);
      case kActivityReasonIndexerNotConfigured:
      case kActivityReasonUpstreamError:
      case kActivityReasonInvalidAddress:
      default:
        return kActivityCopyHonestUnavailable;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('crypto_wallet_activity_card'),
      padding: const EdgeInsets.all(16),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: const [
              Icon(Icons.history_rounded, size: 18,
                  color: kWalletTextSecondary),
              SizedBox(width: 8),
              Text(
                kActivityCardHeaderLabel,
                style: kWalletSectionHeadingStyle,
              ),
            ],
          ),
          const SizedBox(height: 10),
          _buildBody(),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_state == _ActivityFetchState.loading) {
      return Padding(
        key: const Key('crypto_wallet_activity_card_loading'),
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: const [
            SizedBox(
              width: 14, height: 14,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(
                  kWalletAccentPrimary,
                ),
              ),
            ),
            SizedBox(width: 10),
            Text(
              kActivityCopyLoading,
              style: kWalletBodyStyle,
            ),
          ],
        ),
      );
    }
    if (_state == _ActivityFetchState.error) {
      return const Text(
        kActivityCopyError,
        key: Key('crypto_wallet_activity_card_error'),
        style: TextStyle(color: kWalletAccentDanger, fontSize: 13),
      );
    }
    final rows = _merged();
    // 2026-07-13 canary correctness: if the indexer is unavailable
    // (backend not connected, wallet not created yet) BUT the user
    // has a locally-tracked outgoing tx, the local rows still
    // render. The indexer-status message becomes a secondary line
    // above them.
    if (_txsStatus != kActivityTxsStatusAvailable && rows.isEmpty) {
      return Text(
        _unavailableCopy(),
        key: const Key('crypto_wallet_activity_card_unavailable'),
        style: kWalletBodyStyle,
      );
    }
    if (rows.isEmpty) {
      return Text(
        activityCopyEmptyForNetwork(widget.network, asset: widget.asset),
        key: const Key('crypto_wallet_activity_card_empty'),
        style: kWalletBodyStyle,
      );
    }
    return Column(
      key: const Key('crypto_wallet_activity_card_list'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final row in rows) _buildRow(row),
      ],
    );
  }

  Widget _buildRow(CryptoWalletActivityRow row) {
    final isIncoming = row.isIncoming;
    final accent = isIncoming
        ? kWalletAccentSuccess
        : kWalletAccentPrimarySoft;
    final shortHash = activityTxHashShort(row.txHash);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        key: Key('crypto_wallet_activity_card_row_${row.txHash}'),
        onTap: () => _copyTxHash(row.txHash),
        borderRadius: BorderRadius.circular(10),
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.symmetric(
            horizontal: 10, vertical: 10,
          ),
          decoration: BoxDecoration(
            color: kWalletSurfaceElevated,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: kWalletBorder),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                key: Key(
                  'crypto_wallet_activity_card_row_direction_'
                  '${row.txHash}',
                ),
                padding: const EdgeInsets.symmetric(
                  horizontal: 7, vertical: 3,
                ),
                decoration: BoxDecoration(
                  color: accent.withOpacity(0.16),
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: accent.withOpacity(0.55)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      isIncoming
                          ? Icons.south_rounded
                          : Icons.north_rounded,
                      size: 11, color: accent,
                    ),
                    const SizedBox(width: 3),
                    Text(
                      isIncoming ? 'In' : 'Out',
                      style: TextStyle(
                        color: accent,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.3,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${row.amount} ${row.unit}',
                            key: Key(
                              'crypto_wallet_activity_card_row_amount_'
                              '${row.txHash}',
                            ),
                            style: const TextStyle(
                              color: kWalletTextPrimary,
                              fontSize: 14,
                              fontWeight: FontWeight.w800,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        Container(
                          key: Key(
                            'crypto_wallet_activity_card_row_status_'
                            '${row.txHash}',
                          ),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 7, vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: _statusBg(row.status),
                            borderRadius: BorderRadius.circular(999),
                            border: Border.all(
                              color: _statusFg(row.status).withOpacity(0.5),
                            ),
                          ),
                          child: Text(
                            row.status,
                            style: TextStyle(
                              color: _statusFg(row.status),
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.2,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(
                      shortHash,
                      key: Key(
                        'crypto_wallet_activity_card_row_hash_'
                        '${row.txHash}',
                      ),
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 11,
                        color: kWalletTextMuted,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Color _statusBg(String status) {
    switch (status) {
      case kActivityStatusConfirmed:
        return kWalletAccentSuccess.withOpacity(0.14);
      case kActivityStatusPending:
        return kWalletAccentWarning.withOpacity(0.14);
      case kActivityStatusFailed:
        return kWalletAccentDanger.withOpacity(0.14);
      default:
        return kWalletSurface;
    }
  }

  Color _statusFg(String status) {
    switch (status) {
      case kActivityStatusConfirmed:
        return kWalletAccentSuccess;
      case kActivityStatusPending:
        return kWalletAccentWarning;
      case kActivityStatusFailed:
        return kWalletAccentDanger;
      default:
        return kWalletTextSecondary;
    }
  }
}
