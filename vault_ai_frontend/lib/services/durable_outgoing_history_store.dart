// 2026-07-13 (durability slice): durable outgoing-transaction store.
//
// The Round-3 canary fix stopped the user from losing the outgoing
// row DURING the broadcast HTTP call, but the row still evaporated
// on Flutter web reload / browser restart / re-authentication on
// another device. That is unacceptable for a real crypto wallet:
// a signed transaction whose fate is unknown MUST persist across
// sessions until either the chain confirms/rejects it or the user
// acknowledges the terminal state.
//
// This store holds the vault-scoped durable projection returned by
// GET /crypto/wallet/network/{network}/outgoing/history. The backend
// projects the `crypto_mainnet_drafts` table — the same rows the
// broadcast handler already writes to under Postgres transactions —
// so no duplicate transaction truth is created and vault isolation
// is enforced at the SQL WHERE clause.
//
// The Activity card merges three sources — see
// `crypto_wallet_engine_activity_card.dart._merged()` for the
// precedence rules:
//   * indexer          (chain-observed history from the indexer node)
//   * durable history  (this store: vault-owner persisted broadcasts)
//   * local in-memory  (`LocalOutgoingTxStore`: immediate UX feedback)
//
// Deduplication key is the local tx hash (case-insensitive). Chain-
// observed wins over durable, durable wins over local — so a stale
// `submission_uncertain` durable row is REPLACED by an on-chain
// `confirmed` result the moment the indexer sees the transaction.
//
// Nothing here is cached to disk — the DURABILITY is on the backend.
// This store just caches the network round-trip inside the current
// browser session and hands rows to the Activity card synchronously.

import 'package:flutter/foundation.dart';

import 'package:vault_ai_frontend/api_client.dart';


/// A single row of durable outgoing history projected from
/// `crypto_mainnet_drafts`. All fields are the client-friendly
/// projection returned by the backend (never a claim token, never a
/// draft lock/expiry field).
@immutable
class DurableOutgoingTx {
  /// Server-issued draft id (unique per broadcast attempt).
  final String draftId;

  final String networkId;
  final String asset;
  final String unit;
  final int decimals;

  /// Wallet the transaction was signed by.
  final String fromAddress;

  /// Human-facing recipient (never the contract for token sends —
  /// use `transactionTo` for that).
  final String destinationAddress;

  /// The `to` field actually set in the signed transaction:
  ///   * ETH send  → recipient
  ///   * ERC-20 send → token contract address
  final String transactionTo;

  /// Value of the signed transaction, in wei. For ERC-20 this is
  /// always 0; the token amount lives in `dataHex`.
  final BigInt valueWei;

  /// Amount in base units (wei for ETH; NULL for token sends — the
  /// client parses `dataHex` when it needs to render).
  final BigInt? amountBaseUnits;

  /// Calldata (`0x` for native ETH sends, an `ERC20.transfer(...)`
  /// encoding for token sends).
  final String dataHex;

  final BigInt gasLimit;
  final BigInt gasPrice;

  /// gasLimit * gasPrice, precomputed by the backend so the client
  /// does not have to redo the multiplication.
  final BigInt feeWei;

  final int chainId;

  /// keccak256(rawSignedTx) computed at broadcast time. The Activity
  /// card uses this hash to fetch chain-observed status via
  /// /crypto/wallet/network/{network}/{asset}/transaction/{txHash}.
  final String localTxHash;

  /// One of: null (draft still consumed but outcome not yet
  /// recorded), `submitted`, `submission_uncertain`, `already_known`,
  /// `explicitly_rejected`.
  final String? broadcastOutcome;

  /// UNIX seconds since epoch. NULL if not yet reported.
  final double? createdAt;
  final double? consumedAt;
  final double? outcomeRecordedAt;

  const DurableOutgoingTx({
    required this.draftId,
    required this.networkId,
    required this.asset,
    required this.unit,
    required this.decimals,
    required this.fromAddress,
    required this.destinationAddress,
    required this.transactionTo,
    required this.valueWei,
    required this.amountBaseUnits,
    required this.dataHex,
    required this.gasLimit,
    required this.gasPrice,
    required this.feeWei,
    required this.chainId,
    required this.localTxHash,
    required this.broadcastOutcome,
    required this.createdAt,
    required this.consumedAt,
    required this.outcomeRecordedAt,
  });

  factory DurableOutgoingTx.fromJson(Map<String, Object?> j) {
    BigInt bi(Object? v) {
      if (v == null) return BigInt.zero;
      if (v is BigInt) return v;
      if (v is int) return BigInt.from(v);
      return BigInt.parse(v.toString());
    }

    BigInt? maybeBi(Object? v) {
      if (v == null) return null;
      if (v is BigInt) return v;
      if (v is int) return BigInt.from(v);
      final s = v.toString();
      if (s.isEmpty) return null;
      return BigInt.parse(s);
    }

    double? maybeDouble(Object? v) {
      if (v == null) return null;
      if (v is double) return v;
      if (v is int) return v.toDouble();
      final s = v.toString();
      if (s.isEmpty) return null;
      return double.tryParse(s);
    }

    // 2026-07-14 (Round 7 hardening): make the parser polymorphic
    // across ETH / SOL / TRON. Each backend history endpoint uses
    // the same overall shape but with network-specific identity /
    // fee field names. Resolve to the same client-facing
    // `localTxHash` + `feeWei` slots.
    //
    // ETH (Round 4):
    //   localTxHash, valueWei, gasLimit, gasPrice, feeWei
    // SOL (Round 6):
    //   localSignature, amountBaseUnits (lamports), feeLamports,
    //   recentBlockhash, lastValidBlockHeight
    // TRON (Round 6):
    //   localTxIdHex, amountBaseUnits, feeLimitSun,
    //   tokenContractAddress, expirationMs, serverTxIdHex
    final networkId = (j['networkId'] ?? '').toString();
    final isSolana = networkId == 'solana_mainnet';
    final isTron = networkId == 'tron_mainnet';
    String localId;
    BigInt feeVal;
    BigInt gasLimitVal;
    BigInt gasPriceVal;
    BigInt valueVal;
    String transactionToVal;
    if (isSolana) {
      localId = (j['localSignature'] ?? '').toString();
      feeVal = bi(j['feeLamports']);
      gasLimitVal = BigInt.zero;
      gasPriceVal = BigInt.zero;
      valueVal = bi(j['amountBaseUnits']);
      transactionToVal = (j['destinationAddress'] ?? '').toString();
    } else if (isTron) {
      localId = (j['localTxIdHex'] ?? '').toString();
      feeVal = bi(j['feeLimitSun']);
      gasLimitVal = BigInt.zero;
      gasPriceVal = BigInt.zero;
      valueVal = BigInt.zero;
      transactionToVal = (j['tokenContractAddress']
              ?? j['destinationAddress'] ?? '').toString();
    } else {
      localId = (j['localTxHash'] ?? '').toString();
      feeVal = bi(j['feeWei']);
      gasLimitVal = bi(j['gasLimit']);
      gasPriceVal = bi(j['gasPrice']);
      valueVal = bi(j['valueWei']);
      transactionToVal = (j['transactionTo'] ?? '').toString();
    }
    return DurableOutgoingTx(
      draftId: (j['draftId'] ?? '').toString(),
      networkId: networkId,
      asset: (j['asset'] ?? '').toString(),
      unit: (j['unit'] ?? '').toString(),
      decimals: j['decimals'] is int
          ? j['decimals'] as int
          : int.tryParse((j['decimals'] ?? '18').toString()) ?? 18,
      fromAddress: (j['fromAddress'] ?? '').toString(),
      destinationAddress: (j['destinationAddress'] ?? '').toString(),
      transactionTo: transactionToVal,
      valueWei: valueVal,
      amountBaseUnits: maybeBi(j['amountBaseUnits']),
      dataHex: (j['dataHex'] ?? '0x').toString(),
      gasLimit: gasLimitVal,
      gasPrice: gasPriceVal,
      feeWei: feeVal,
      chainId: j['chainId'] is int
          ? j['chainId'] as int
          : int.tryParse((j['chainId'] ?? '0').toString()) ?? 0,
      localTxHash: localId,
      broadcastOutcome:
          j['broadcastOutcome']?.toString(),
      createdAt: maybeDouble(j['createdAt']),
      consumedAt: maybeDouble(j['consumedAt']),
      outcomeRecordedAt: maybeDouble(j['outcomeRecordedAt']),
    );
  }
}


/// Vault-scoped session cache of durable outgoing history. Reactive
/// via `ChangeNotifier` so the Activity card rebuilds when
/// `refresh()` completes.
///
/// Each `(networkId)` slot caches its own snapshot. `rowsFor` is a
/// synchronous lookup so widgets can call it inside `build`.
class DurableOutgoingHistoryStore extends ChangeNotifier {
  final VaultAIClient client;
  final String Function() authTokenProvider;

  DurableOutgoingHistoryStore({
    required this.client,
    required this.authTokenProvider,
  });

  final Map<String, List<DurableOutgoingTx>> _byNetwork =
      <String, List<DurableOutgoingTx>>{};

  final Map<String, DateTime> _lastRefreshedAt =
      <String, DateTime>{};

  final Map<String, Object> _lastRefreshError = <String, Object>{};

  /// Rows for a given network scoped to a single asset panel. Sorted
  /// newest-first by `consumedAt` (falling back to `createdAt`).
  List<DurableOutgoingTx> rowsFor({
    required String networkId,
    required String asset,
  }) {
    final all = _byNetwork[networkId] ?? const <DurableOutgoingTx>[];
    final xs = all.where((r) => r.asset == asset).toList();
    xs.sort((a, b) {
      final ac = a.consumedAt ?? a.createdAt ?? 0.0;
      final bc = b.consumedAt ?? b.createdAt ?? 0.0;
      return bc.compareTo(ac);
    });
    return xs;
  }

  /// Full snapshot for a network (unfiltered). Tests + debugging.
  List<DurableOutgoingTx> allFor(String networkId) {
    return List<DurableOutgoingTx>.unmodifiable(
      _byNetwork[networkId] ?? const <DurableOutgoingTx>[],
    );
  }

  DateTime? lastRefreshedAt(String networkId) =>
      _lastRefreshedAt[networkId];

  Object? lastRefreshError(String networkId) =>
      _lastRefreshError[networkId];

  /// Fetch the durable history for a network from the backend and
  /// replace the cached snapshot. Errors are captured (not thrown)
  /// so widgets that call this in `initState` do not crash the tree
  /// on backend outage. Callers that need to react to failure read
  /// `lastRefreshError(networkId)`.
  Future<void> refresh(String networkId) async {
    Map<String, dynamic> body;
    try {
      body = await client.getCryptoWalletOutgoingHistoryNetwork(
        network: networkId,
        authToken: authTokenProvider(),
      );
    } catch (e) {
      _lastRefreshError[networkId] = e;
      _lastRefreshedAt[networkId] = DateTime.now();
      notifyListeners();
      return;
    }
    final status = (body['status'] ?? '').toString();
    if (status != 'ok') {
      _lastRefreshError[networkId] =
          StateError('history_status_${body['status']}');
      _lastRefreshedAt[networkId] = DateTime.now();
      notifyListeners();
      return;
    }
    final raw = body['outgoing'];
    final rows = <DurableOutgoingTx>[];
    if (raw is List) {
      for (final entry in raw) {
        if (entry is Map<String, Object?>) {
          rows.add(DurableOutgoingTx.fromJson(entry));
        } else if (entry is Map) {
          rows.add(DurableOutgoingTx.fromJson(
            entry.map((k, v) => MapEntry(k.toString(), v)),
          ));
        }
      }
    }
    _byNetwork[networkId] = rows;
    _lastRefreshError.remove(networkId);
    _lastRefreshedAt[networkId] = DateTime.now();
    notifyListeners();
  }

  /// Test helper — replace the cached rows without hitting the wire.
  @visibleForTesting
  void seedForNetwork(
    String networkId, List<DurableOutgoingTx> rows,
  ) {
    _byNetwork[networkId] = List<DurableOutgoingTx>.of(rows);
    _lastRefreshedAt[networkId] = DateTime.now();
    _lastRefreshError.remove(networkId);
    notifyListeners();
  }

  /// Test helper — drop everything.
  @visibleForTesting
  void clear() {
    _byNetwork.clear();
    _lastRefreshedAt.clear();
    _lastRefreshError.clear();
    notifyListeners();
  }
}
