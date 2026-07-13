

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/crypto_wallet_features.dart';
import '../services/durable_outgoing_history_store.dart';
import '../services/local_outgoing_tx_store.dart';
import 'crypto_wallet_engine_design.dart';


const String kSolanaActivityCardHeading = 'Solana activity';
const String kSolanaActivityNoWalletCopy = 'Create Solana wallet first.';
const String kSolanaActivityRpcMissingCopy =
    'Solana activity is not connected yet.';
const String kSolanaActivityEmptyCopy = 'No Solana activity yet.';
const String kSolanaActivityErrorCopy =
    'Solana activity temporarily unavailable.';
const String kSolanaActivityDirectionLabel = 'Activity';
const String kSolanaActivityLoadingCopy = 'Loading Solana activity…';
const String kSolanaActivityStatusPendingCopy = 'Pending';
const String kSolanaActivityStatusConfirmedCopy = 'Confirmed';
const String kSolanaActivityStatusFailedCopy = 'Failed';
const String kSolanaActivityStatusUnknownCopy = 'Unknown';


const String kSolanaActivityCardKey = 'solana_activity_card';
const String kSolanaActivityListKey = 'solana_activity_list';
const String kSolanaActivityEmptyKey = 'solana_activity_empty';
const String kSolanaActivityNoWalletKey =
    'solana_activity_no_wallet';
const String kSolanaActivityRpcMissingKey =
    'solana_activity_rpc_missing';
const String kSolanaActivityErrorKey = 'solana_activity_error';
const String kSolanaActivityLoadingKey = 'solana_activity_loading';


String solanaActivityStatusCopyFor(String? status) {
  switch (status) {
    case 'confirmed': return kSolanaActivityStatusConfirmedCopy;
    case 'pending':   return kSolanaActivityStatusPendingCopy;
    case 'failed':    return kSolanaActivityStatusFailedCopy;
  }
  return kSolanaActivityStatusUnknownCopy;
}


String solanaActivityShortSignature(String? sig) {
  if (sig == null || sig.length < 12) return sig ?? '';
  return '${sig.substring(0, 6)}…${sig.substring(sig.length - 4)}';
}


class CryptoWalletEngineSolanaActivityCard extends StatefulWidget {
  final String? authToken;
  final VaultAIClient? apiClient;
  final CryptoWalletFeatures? features;
  final int limit;

  /// 2026-07-14 (Round 7 hardening): three-source merge stores.
  final LocalOutgoingTxStore? localStore;
  final DurableOutgoingHistoryStore? durableStore;

  const CryptoWalletEngineSolanaActivityCard({
    super.key,
    this.authToken,
    this.apiClient,
    this.features,
    this.limit = 20,
    this.localStore,
    this.durableStore,
  });

  @override
  State<CryptoWalletEngineSolanaActivityCard> createState() =>
      _CryptoWalletEngineSolanaActivityCardState();
}


enum _SolanaActivityState { loading, ready }


class _CryptoWalletEngineSolanaActivityCardState
    extends State<CryptoWalletEngineSolanaActivityCard> {
  _SolanaActivityState _state = _SolanaActivityState.loading;
  String _status = 'unavailable';
  String? _reason;
  List<Map<String, dynamic>> _rows = const [];

  @override
  void initState() {
    super.initState();
    widget.localStore?.addListener(_onLocalChanged);
    widget.durableStore?.addListener(_onDurableChanged);
    _load();
    _refreshDurable();
  }

  @override
  void didUpdateWidget(covariant CryptoWalletEngineSolanaActivityCard old) {
    super.didUpdateWidget(old);
    if (!identical(old.localStore, widget.localStore)) {
      old.localStore?.removeListener(_onLocalChanged);
      widget.localStore?.addListener(_onLocalChanged);
    }
    if (!identical(old.durableStore, widget.durableStore)) {
      old.durableStore?.removeListener(_onDurableChanged);
      widget.durableStore?.addListener(_onDurableChanged);
      _refreshDurable();
    }
  }

  @override
  void dispose() {
    widget.localStore?.removeListener(_onLocalChanged);
    widget.durableStore?.removeListener(_onDurableChanged);
    super.dispose();
  }

  void _onLocalChanged() {
    if (!mounted) return;
    // A new outgoing broadcast typically produces a durable row on
    // the same request; kick a durable refresh here so the merged
    // snapshot converges quickly.
    _refreshDurable();
    setState(() {});
  }

  void _onDurableChanged() {
    if (!mounted) return;
    setState(() {});
  }

  void _refreshDurable() {
    final ds = widget.durableStore;
    if (ds == null) return;
    // ignore: discarded_futures
    ds.refresh('solana_mainnet');
  }

  Future<void> refreshAllForTest() async {
    await _load();
    _refreshDurable();
  }

  Future<void> _load() async {
    if (widget.apiClient == null || widget.authToken == null) {
      setState(() {
        _state = _SolanaActivityState.ready;
        _status = 'unavailable';
        _reason = 'rpc_not_configured';
        _rows = const [];
      });
      return;
    }
    setState(() {
      _state = _SolanaActivityState.loading;
    });
    try {
      final body = await widget.apiClient!
          .listCryptoWalletTransactionsNetwork(
        network:  kSolanaNetworkId,
        asset:    kSolanaAssetTicker,
        authToken: widget.authToken!,
        limit:    widget.limit,
      );
      if (!mounted) return;
      final status = (body['transactionsStatus'] ?? '').toString();
      final reason = (body['reason'] as String?);
      final raw = body['transactions'];
      final rows = <Map<String, dynamic>>[];
      if (raw is List) {
        for (final r in raw) {
          if (r is Map<String, dynamic>) {
            rows.add(r);
          }
        }
      }
      setState(() {
        _state = _SolanaActivityState.ready;
        _status = status;
        _reason = reason;
        _rows = rows;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _state = _SolanaActivityState.ready;
        _status = 'unavailable';
        _reason = 'rpc_error';
        _rows = const [];
      });
    }
  }

  Future<void> _copy(String text) async {
    final label = AppLocalizations.of(context).cryptoSignatureCopied;
    await Clipboard.setData(ClipboardData(text: text));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(label)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key(kSolanaActivityCardKey),
      padding: const EdgeInsets.all(14),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.history_rounded, size: 18,
                  color: kWalletTextSecondary),
              SizedBox(width: 8),
              Text(
                kSolanaActivityCardHeading,
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
    if (_state == _SolanaActivityState.loading) {
      return const Padding(
        key: Key(kSolanaActivityLoadingKey),
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Text(
          kSolanaActivityLoadingCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    if (_status == 'unavailable') {
      if (_reason == 'no_wallet_yet') {
        return const Padding(
          key: Key(kSolanaActivityNoWalletKey),
          padding: EdgeInsets.symmetric(vertical: 8),
          child: Text(
            kSolanaActivityNoWalletCopy,
            style: kWalletBodyStyle,
          ),
        );
      }
      if (_reason == 'rpc_not_configured') {
        return const Padding(
          key: Key(kSolanaActivityRpcMissingKey),
          padding: EdgeInsets.symmetric(vertical: 8),
          child: Text(
            kSolanaActivityRpcMissingCopy,
            style: kWalletBodyStyle,
          ),
        );
      }
      return const Padding(
        key: Key(kSolanaActivityErrorKey),
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Text(
          kSolanaActivityErrorCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    final rows = _merged();
    if (rows.isEmpty) {
      return const Padding(
        key: Key(kSolanaActivityEmptyKey),
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Text(
          kSolanaActivityEmptyCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    return Column(
      key: const Key(kSolanaActivityListKey),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final r in rows) _buildRow(r),
      ],
    );
  }

  /// 2026-07-14 (Round 7 hardening): three-source merge.
  ///
  /// Precedence (most authoritative first):
  ///   1. INDEXER (`_rows`) — chain-observed `confirmed` / `failed`
  ///      always wins.
  ///   2. DURABLE (backend history) — survives browser reload; wins
  ///      over local unless local has fresher timestamp or expresses
  ///      a strictly-transient state (`submitting`, `dropped`).
  ///   3. LOCAL — in-session snapshot with `submitting` /
  ///      `submissionUncertain` states that neither source can name.
  ///
  /// Deduplication key is the lower-case signature.
  List<Map<String, dynamic>> _merged() {
    final byKey = <String, Map<String, dynamic>>{};
    // Base: indexer.
    for (final r in _rows) {
      final sig = (r['txHash'] ?? '').toString().toLowerCase();
      if (sig.isEmpty) continue;
      byKey[sig] = r;
    }
    // Middle: durable rows. Never downgrade chain-observed.
    final durable = widget.durableStore;
    if (durable != null) {
      final durRows = durable.rowsFor(
        networkId: 'solana_mainnet', asset: 'SOL',
      );
      for (final d in durRows) {
        final sig = d.localTxHash.toLowerCase();
        if (sig.isEmpty) continue;
        final existing = byKey[sig];
        if (existing != null &&
            _isChainObservedStatus(
              (existing['status'] ?? '').toString(),
            )) {
          continue;
        }
        byKey[sig] = _durableToRow(d);
      }
    }
    // Top: local rows.
    final local = widget.localStore;
    if (local != null) {
      final locRows = local.rowsFor(
        networkId: 'solana_mainnet', asset: 'SOL',
      );
      for (final l in locRows) {
        final sig = l.txHash.toLowerCase();
        if (sig.isEmpty) continue;
        final existing = byKey[sig];
        final asRow = _localToRow(l);
        if (existing == null) {
          byKey[sig] = asRow;
          continue;
        }
        if (_isChainObservedStatus(
          (existing['status'] ?? '').toString(),
        )) {
          continue;
        }
        if (l.status == LocalOutgoingTxStatus.submitting
            || l.status == LocalOutgoingTxStatus.dropped) {
          byKey[sig] = asRow;
          continue;
        }
        // Otherwise newest wins.
        final exTs = (existing['timestamp'] is num)
            ? (existing['timestamp'] as num).toInt()
            : 0;
        final loTs = (asRow['timestamp'] as num).toInt();
        if (loTs >= exTs) byKey[sig] = asRow;
      }
    }
    final out = byKey.values.toList();
    out.sort((a, b) {
      final ta = a['timestamp'] is num
          ? (a['timestamp'] as num).toInt() : 0;
      final tb = b['timestamp'] is num
          ? (b['timestamp'] as num).toInt() : 0;
      return tb.compareTo(ta);
    });
    return out;
  }

  static bool _isChainObservedStatus(String status) =>
      status == 'confirmed' || status == 'failed';

  Map<String, dynamic> _durableToRow(DurableOutgoingTx d) {
    final ts = (d.consumedAt ?? d.createdAt ?? 0).toInt();
    return <String, dynamic>{
      'txHash': d.localTxHash,
      'status': _durableStatus(d.broadcastOutcome),
      'timestamp': ts,
      'source': 'durable',
    };
  }

  Map<String, dynamic> _localToRow(LocalOutgoingTx l) {
    return <String, dynamic>{
      'txHash': l.txHash,
      'status': _localStatus(l.status),
      'timestamp': (l.createdAt.millisecondsSinceEpoch / 1000).round(),
      'source': 'local',
    };
  }

  static String _durableStatus(String? outcome) {
    switch (outcome) {
      case 'submitted':
      case 'already_known':
        return 'pending';   // durable submitted → still awaits chain
      case 'submission_uncertain':
        return 'submission_uncertain';
      case 'explicitly_rejected':
        return 'rejected';
      default:
        return 'submission_uncertain';
    }
  }

  static String _localStatus(LocalOutgoingTxStatus s) {
    switch (s) {
      case LocalOutgoingTxStatus.submitting:  return 'submitting';
      case LocalOutgoingTxStatus.submitted:    return 'pending';
      case LocalOutgoingTxStatus.pending:      return 'pending';
      case LocalOutgoingTxStatus.submissionUncertain:
        return 'submission_uncertain';
      case LocalOutgoingTxStatus.confirmed:    return 'confirmed';
      case LocalOutgoingTxStatus.failed:       return 'failed';
      case LocalOutgoingTxStatus.explicitlyRejected: return 'rejected';
      case LocalOutgoingTxStatus.dropped:      return 'dropped';
    }
  }

  Widget _buildRow(Map<String, dynamic> row) {
    final sig = (row['txHash'] ?? '').toString();
    final status = (row['status'] ?? 'unknown').toString();
    final ts = row['timestamp'];
    final tsText = (ts is num)
        ? DateTime.fromMillisecondsSinceEpoch(
            ts.toInt() * 1000, isUtc: true,
          ).toIso8601String().substring(0, 19).replaceFirst('T', ' ')
        : '';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Icon(
            status == 'confirmed'
                ? Icons.check_circle_outline
                : status == 'failed'
                    ? Icons.error_outline
                    : Icons.hourglass_bottom_rounded,
            size: 16,
            color: status == 'confirmed'
                ? kWalletAccentSuccess
                : status == 'failed'
                    ? kWalletAccentDanger
                    : kWalletAccentWarning,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        kSolanaActivityDirectionLabel,
                        style: kWalletBodyStyle,
                      ),
                    ),
                    Text(
                      solanaActivityStatusCopyFor(status),
                      style: TextStyle(
                        color: status == 'confirmed'
                            ? kWalletAccentSuccess
                            : status == 'failed'
                                ? kWalletAccentDanger
                                : kWalletAccentWarning,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                SelectableText(
                  solanaActivityShortSignature(sig),
                  style: kWalletMonoStyle,
                ),
                if (tsText.isNotEmpty)
                  Text(
                    tsText,
                    style: kWalletMutedStyle,
                  ),
              ],
            ),
          ),
          IconButton(
            key: Key('solana_activity_row_copy_${sig.substring(
                0, sig.length < 6 ? sig.length : 6)}'),
            icon: const Icon(Icons.copy_rounded, size: 16),
            onPressed: () => _copy(sig),
            tooltip: 'Copy signature',
          ),
        ],
      ),
    );
  }
}
