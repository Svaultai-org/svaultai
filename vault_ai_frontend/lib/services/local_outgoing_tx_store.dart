// 2026-07-13 (canary correctness): local outgoing-transaction store.
//
// The canary incident revealed two related bugs:
//   * The backend falsely persisted `submitted` for a transaction
//     that never appeared on-chain (fixed in the routes /
//     visibility gate).
//   * The outgoing attempt was ALSO missing from Activity — the
//     failed canary disappeared entirely from the user's history.
//     The user had no local record they could point at to say
//     "here is what I signed, and here is what it looks like now".
//
// This store is the second half of the fix. Every ETH-family
// broadcast that reaches the RPC (whether it comes back
// `submitted`, `submission_uncertain`, `already_submitted`, or
// `broadcast_rejected`) MUST result in a local Activity row keyed
// by the LOCAL transaction hash (`keccak256(raw)`). The row is
// merged into the Activity card ALONGSIDE indexer results,
// deduplicated by txHash. The row is updated as the status endpoint
// reports back — `submitting → pending → confirmed | failed |
// dropped`.
//
// This module is client-only. Nothing is uploaded. Rows persist
// in memory for the session; a browser reload clears them (the
// indexer takes over once the tx propagates and is discovered).
//
// Threading model: single `ChangeNotifier` per store instance,
// `provider`-friendly. Widgets that display Activity call
// `context.watch<LocalOutgoingTxStore>()` OR pass the store to
// `CryptoWalletActivityCard(localStore: ...)`.

import 'package:flutter/foundation.dart';

/// Coarse local status classification. Maps 1:1 to the honest
/// user-facing state; NOT a mirror of the backend's
/// `broadcast_outcome` (which is finer-grained).
enum LocalOutgoingTxStatus {
  /// Broadcast in flight; no backend response yet. Shown as
  /// "Submitting…" in Activity.
  submitting,

  /// Backend replied `submitted` — at least one Ethereum RPC saw
  /// the transaction. The user should not re-broadcast.
  submitted,

  /// Backend replied `submitted` AND `getTransactionByHash` +
  /// `getTransactionReceipt` are both non-null. Not yet mined.
  pending,

  /// Backend replied `submission_uncertain`. The transaction MAY be
  /// on-chain but no node has yet confirmed it. Client keeps
  /// polling the status endpoint; do NOT re-sign with a new nonce.
  submissionUncertain,

  /// Receipt.status == "0x1". Terminal happy state.
  confirmed,

  /// Receipt.status == "0x0". Terminal failure state (execution
  /// reverted; nonce was consumed anyway).
  failed,

  /// Backend replied `broadcast_rejected` (JSON-RPC error object).
  /// The draft was consumed under the single-attempt policy; a
  /// fresh draft is required to retry.
  explicitlyRejected,

  /// After `submissionUncertain` remained invisible past the
  /// documented time window (`kLocalOutgoingDroppedAfter`). The
  /// transaction is treated as DROPPED — the nonce is likely free
  /// again but re-signing with the SAME nonce could still race with
  /// a delayed inclusion. UI should prompt the user to inspect the
  /// explorer manually.
  dropped,
}

extension LocalOutgoingTxStatusX on LocalOutgoingTxStatus {
  String get wireName {
    switch (this) {
      case LocalOutgoingTxStatus.submitting:
        return 'submitting';
      case LocalOutgoingTxStatus.submitted:
        return 'submitted';
      case LocalOutgoingTxStatus.pending:
        return 'pending';
      case LocalOutgoingTxStatus.submissionUncertain:
        return 'submission_uncertain';
      case LocalOutgoingTxStatus.confirmed:
        return 'confirmed';
      case LocalOutgoingTxStatus.failed:
        return 'failed';
      case LocalOutgoingTxStatus.explicitlyRejected:
        return 'explicitly_rejected';
      case LocalOutgoingTxStatus.dropped:
        return 'dropped';
    }
  }

  /// Whether the row still needs future status polls.
  bool get isTerminal {
    switch (this) {
      case LocalOutgoingTxStatus.confirmed:
      case LocalOutgoingTxStatus.failed:
      case LocalOutgoingTxStatus.explicitlyRejected:
      case LocalOutgoingTxStatus.dropped:
        return true;
      default:
        return false;
    }
  }
}

/// A single local outgoing transaction record. Persisted only for
/// the current session. Merged with indexer results by `txHash`
/// (case-insensitive).
@immutable
class LocalOutgoingTx {
  /// Deterministic local attempt identifier. Generated before the
  /// broadcast call and stable across the row's lifecycle so the UI
  /// can reason about "one user confirmation -> one outgoing
  /// attempt" even before/alongside the transaction hash.
  final String localAttemptId;

  /// keccak256(rawSignedTx). Non-empty. Case is preserved.
  final String txHash;

  /// Sender wallet address (0x-prefixed, non-empty).
  final String fromAddress;

  /// Recipient address (0x-prefixed, non-empty). For ERC-20 this is
  /// the token-recipient argument, NOT the contract address.
  final String toAddress;

  /// Human-friendly amount, e.g. "0.0056". Preserved verbatim from
  /// the Send form so Review + Activity show the same string.
  final String amount;

  /// Unit label ("ETH", "USDT", "USDC", ...).
  final String unit;

  /// Estimated network-fee wei at broadcast time. NULL if unknown.
  final BigInt? feeWei;

  /// Chain/network identifier (e.g. `ethereum_mainnet`).
  final String networkId;

  /// Asset id (`ETH`, `USDT_ERC20`, `USDC_ERC20`).
  final String asset;

  /// EVM chain id from the server-authorized draft.
  final int? chainId;

  /// EVM nonce from the server-authorized draft.
  final BigInt? nonce;

  /// Local wall-clock time the row was created (broadcast start).
  final DateTime createdAt;

  /// Last time the row was updated by a status poll.
  final DateTime updatedAt;

  final LocalOutgoingTxStatus status;

  /// Optional rejection reason from the backend (`upstream_rpc`,
  /// `returned_hash_mismatch`, `not_yet_visible`, ...) — surfaced
  /// only for uncertain / rejected states.
  final String? reason;

  const LocalOutgoingTx({
    String? localAttemptId,
    required this.txHash,
    required this.fromAddress,
    required this.toAddress,
    required this.amount,
    required this.unit,
    required this.feeWei,
    required this.networkId,
    required this.asset,
    this.chainId,
    this.nonce,
    required this.createdAt,
    required this.updatedAt,
    required this.status,
    this.reason,
  }) : localAttemptId = localAttemptId ?? txHash;

  LocalOutgoingTx copyWith({
    LocalOutgoingTxStatus? status,
    String? reason,
    DateTime? updatedAt,
  }) {
    return LocalOutgoingTx(
      txHash: txHash,
      fromAddress: fromAddress,
      toAddress: toAddress,
      amount: amount,
      unit: unit,
      feeWei: feeWei,
      networkId: networkId,
      asset: asset,
      localAttemptId: localAttemptId,
      chainId: chainId,
      nonce: nonce,
      createdAt: createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      status: status ?? this.status,
      reason: reason ?? this.reason,
    );
  }
}

/// In-memory store of local outgoing transactions for the current
/// session. Widgets read via `provider`.
///
/// Rows are grouped by `(networkId, asset)` and read back via
/// `rowsFor(networkId: ..., asset: ...)`. This keeps the Activity
/// card scoped — an ETH Activity card doesn't accidentally show a
/// SOL row (and vice versa) even though the store is app-wide.
class LocalOutgoingTxStore extends ChangeNotifier {
  final Map<String, LocalOutgoingTx> _byHash = <String, LocalOutgoingTx>{};

  /// Deterministic key normalisation. Case-insensitive.
  static String _norm(String hash) => hash.toLowerCase();

  /// Rows for the given asset panel. Sorted newest-first by
  /// `createdAt`.
  List<LocalOutgoingTx> rowsFor({
    required String networkId,
    required String asset,
  }) {
    final xs = _byHash.values
        .where(
          (r) => r.networkId == networkId && r.asset == asset,
        )
        .toList();
    xs.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return xs;
  }

  /// Full snapshot. Used by tests + debugging tools.
  List<LocalOutgoingTx> get all {
    final xs = _byHash.values.toList();
    xs.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return xs;
  }

  LocalOutgoingTx? byHash(String txHash) => _byHash[_norm(txHash)];

  /// Insert-or-replace by hash.
  void upsert(LocalOutgoingTx row) {
    if (row.txHash.trim().isEmpty) {
      return;
    }
    _byHash[_norm(row.txHash)] = row;
    notifyListeners();
  }

  /// True only for signed/broadcast-known rows that still need
  /// protection from duplicate user action. Unsigned drafts are not
  /// represented in this store and an empty hash can never block.
  bool hasBlockingTransfer({
    required String networkId,
    required String asset,
  }) {
    return rowsFor(networkId: networkId, asset: asset).any(
      (row) => row.txHash.trim().isNotEmpty && !row.status.isTerminal,
    );
  }

  /// Update status of an existing row. No-op if the row is unknown.
  void updateStatus(
    String txHash,
    LocalOutgoingTxStatus status, {
    String? reason,
  }) {
    final key = _norm(txHash);
    final prev = _byHash[key];
    if (prev == null) return;
    _byHash[key] = prev.copyWith(
      status: status,
      reason: reason,
      updatedAt: DateTime.now(),
    );
    notifyListeners();
  }

  /// Test-only: drop everything.
  @visibleForTesting
  void clear() {
    _byHash.clear();
    notifyListeners();
  }
}

/// Documented time window after which a `submissionUncertain` row
/// is escalated to `dropped` — the backend has said "not yet
/// visible" and long enough has passed that the transaction is
/// treated as lost. Not a hard timeout on any backend request;
/// only a client-side hint for the UI to stop implying inclusion
/// is imminent.
const Duration kLocalOutgoingDroppedAfter = Duration(hours: 6);
