

import 'package:flutter/material.dart';

import '../services/crypto_wallet_features.dart';
import '../services/durable_outgoing_history_store.dart';
import '../services/local_outgoing_tx_store.dart';
import 'crypto_wallet_engine_design.dart';


const String kTronActivityCardHeading = 'USDT TRC20 activity';
const String kTronActivityNotConnectedCopy =
    'USDT TRC20 activity is not connected yet.';
const String kTronActivityDisabledCopy =
    'USDT TRC20 activity is temporarily unavailable.';
const String kTronActivityEmptyCopy = 'No TRON activity yet.';
const String kTronActivityCardKey = 'tron_activity_card';
const String kTronActivityListKey = 'tron_activity_list';
const String kTronActivityNotConnectedKey =
    'tron_activity_not_connected';
const String kTronActivityDisabledKey = 'tron_activity_disabled';
const String kTronActivityEmptyKey = 'tron_activity_empty';


// 2026-07-14 (Round 7 hardening): the TRON activity card is now
// stateful and consumes the LocalOutgoingTxStore + the durable
// history store. Three-source merge with the same precedence as
// ETH: indexer > durable > local. The indexer branch stays as a
// stub-empty (indexer wiring is TODO) so today the merge is
// effectively durable + local; when the indexer comes online the
// same code path handles it without a rewrite.
class CryptoWalletEngineTronActivityCard extends StatefulWidget {
  final CryptoWalletFeatures? features;
  final LocalOutgoingTxStore? localStore;
  final DurableOutgoingHistoryStore? durableStore;

  const CryptoWalletEngineTronActivityCard({
    super.key,
    this.features,
    this.localStore,
    this.durableStore,
  });

  @override
  State<CryptoWalletEngineTronActivityCard> createState() =>
      _CryptoWalletEngineTronActivityCardState();
}

class _CryptoWalletEngineTronActivityCardState
    extends State<CryptoWalletEngineTronActivityCard> {

  @override
  void initState() {
    super.initState();
    widget.localStore?.addListener(_onChanged);
    widget.durableStore?.addListener(_onChanged);
    _refreshDurable();
  }

  @override
  void didUpdateWidget(
    covariant CryptoWalletEngineTronActivityCard old,
  ) {
    super.didUpdateWidget(old);
    if (!identical(old.localStore, widget.localStore)) {
      old.localStore?.removeListener(_onChanged);
      widget.localStore?.addListener(_onChanged);
    }
    if (!identical(old.durableStore, widget.durableStore)) {
      old.durableStore?.removeListener(_onChanged);
      widget.durableStore?.addListener(_onChanged);
      _refreshDurable();
    }
  }

  @override
  void dispose() {
    widget.localStore?.removeListener(_onChanged);
    widget.durableStore?.removeListener(_onChanged);
    super.dispose();
  }

  void _onChanged() {
    if (!mounted) return;
    _refreshDurable();
    setState(() {});
  }

  void _refreshDurable() {
    final ds = widget.durableStore;
    if (ds == null) return;
    // ignore: discarded_futures
    ds.refresh('tron_mainnet');
  }

  @override
  Widget build(BuildContext context) {
    final tronOn = widget.features?.tronEnabled ?? true;
    final rows = _merged();
    return Container(
      key: const Key(kTronActivityCardKey),
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
                kTronActivityCardHeading,
                style: kWalletSectionHeadingStyle,
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (rows.isNotEmpty)
            Column(
              key: const Key(kTronActivityListKey),
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [for (final r in rows) _buildRow(r)],
            )
          else if (!tronOn)
            const Padding(
              key: Key(kTronActivityDisabledKey),
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text(kTronActivityDisabledCopy,
                  style: kWalletBodyStyle),
            )
          else
            const Padding(
              key: Key(kTronActivityNotConnectedKey),
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text(kTronActivityNotConnectedCopy,
                  style: kWalletBodyStyle),
            ),
        ],
      ),
    );
  }

  /// Merges durable + local into a display list. No indexer branch
  /// yet (backend endpoint stubbed at `[]` for TRON transactions).
  /// Precedence: durable > local for the same txID; local can
  /// still surface `submitting`/`dropped` states unavailable
  /// server-side.
  List<Map<String, dynamic>> _merged() {
    final byKey = <String, Map<String, dynamic>>{};
    final durable = widget.durableStore;
    if (durable != null) {
      final durRows = durable.rowsFor(
        networkId: 'tron_mainnet', asset: 'USDT_TRC20',
      );
      for (final d in durRows) {
        final k = d.localTxHash.toLowerCase();
        if (k.isEmpty) continue;
        byKey[k] = <String, dynamic>{
          'txId': d.localTxHash,
          'status': _durableStatus(d.broadcastOutcome),
          'timestamp': (d.consumedAt ?? d.createdAt ?? 0).toInt(),
          'source': 'durable',
        };
      }
    }
    final local = widget.localStore;
    if (local != null) {
      final locRows = local.rowsFor(
        networkId: 'tron_mainnet', asset: 'USDT_TRC20',
      );
      for (final l in locRows) {
        final k = l.txHash.toLowerCase();
        if (k.isEmpty) continue;
        final asRow = <String, dynamic>{
          'txId': l.txHash,
          'status': _localStatus(l.status),
          'timestamp':
              (l.createdAt.millisecondsSinceEpoch / 1000).round(),
          'source': 'local',
        };
        final existing = byKey[k];
        if (existing == null) {
          byKey[k] = asRow;
          continue;
        }
        if (l.status == LocalOutgoingTxStatus.submitting
            || l.status == LocalOutgoingTxStatus.dropped) {
          byKey[k] = asRow;
        }
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

  static String _durableStatus(String? outcome) {
    switch (outcome) {
      case 'submitted':
      case 'already_known':
        return 'pending';
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
      case LocalOutgoingTxStatus.submitting: return 'submitting';
      case LocalOutgoingTxStatus.submitted:  return 'pending';
      case LocalOutgoingTxStatus.pending:    return 'pending';
      case LocalOutgoingTxStatus.submissionUncertain:
        return 'submission_uncertain';
      case LocalOutgoingTxStatus.confirmed:  return 'confirmed';
      case LocalOutgoingTxStatus.failed:     return 'failed';
      case LocalOutgoingTxStatus.explicitlyRejected:
        return 'rejected';
      case LocalOutgoingTxStatus.dropped:    return 'dropped';
    }
  }

  Widget _buildRow(Map<String, dynamic> row) {
    final tx = (row['txId'] ?? '').toString();
    final status = (row['status'] ?? 'unknown').toString();
    final short = tx.length < 12
        ? tx
        : '${tx.substring(0, 6)}…${tx.substring(tx.length - 4)}';
    Color? color;
    switch (status) {
      case 'confirmed': color = kWalletAccentSuccess; break;
      case 'failed':
      case 'rejected':  color = kWalletAccentDanger;  break;
      default:          color = kWalletAccentWarning;
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Icon(Icons.history_rounded, size: 14, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              short,
              key: Key('tron_activity_row_txid_$short'),
              style: kWalletMonoStyle,
            ),
          ),
          Text(
            status,
            style: TextStyle(
              color: color, fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}
