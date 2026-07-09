

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import 'crypto_wallet_engine_design.dart';


const String kActivityCardSchemaV1 = 'crypto_wallet_transaction_v1';

const String kActivityDirectionIncoming = 'incoming';
const String kActivityDirectionOutgoing = 'outgoing';

const String kActivityStatusPending   = 'pending';
const String kActivityStatusConfirmed = 'confirmed';
const String kActivityStatusFailed    = 'failed';
const String kActivityStatusUnknown   = 'unknown';

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

  const CryptoWalletActivityCard({
    super.key,
    required this.asset,
    this.authToken,
    this.apiClient,
    this.limit = 20,
    this.network,
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
    _load();
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
    if (_txsStatus != kActivityTxsStatusAvailable) {
      return Text(
        _unavailableCopy(),
        key: const Key('crypto_wallet_activity_card_unavailable'),
        style: kWalletBodyStyle,
      );
    }
    if (_rows.isEmpty) {
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
        for (final row in _rows) _buildRow(row),
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
