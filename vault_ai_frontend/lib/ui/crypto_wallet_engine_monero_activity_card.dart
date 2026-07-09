

import 'package:flutter/material.dart';

import '../services/crypto_wallet_features.dart';
import '../services/monero_scanner.dart';
import '../services/monero_scanner_status.dart';
import 'crypto_wallet_engine_design.dart';


const String kMoneroActivityCardHeading = 'Monero activity';
const String kMoneroActivityScannerNotEnabledCopy =
    'Monero activity requires wallet scanning.';
const String kMoneroActivityScannerNotStartedCopy =
    'Monero activity requires wallet scanning.';
const String kMoneroActivitySyncingCopy =
    'Monero scanner is syncing.';
const String kMoneroActivityDisabledCopy =
    'Monero activity requires wallet scanning.';
const String kMoneroActivityEmptyAfterSyncCopy =
    'No activity yet.';
const String kMoneroActivityCardKey = 'monero_activity_card';
const String kMoneroActivityScannerNotEnabledKey =
    'monero_activity_scanner_not_enabled';
const String kMoneroActivityScannerNotStartedKey =
    'monero_activity_scanner_not_started';
const String kMoneroActivitySyncingKey =
    'monero_activity_syncing';
const String kMoneroActivityDisabledKey =
    'monero_activity_disabled';
const String kMoneroActivityEmptyAfterSyncKey =
    'monero_activity_empty_after_sync';
const String kMoneroActivityRowKeyPrefix =
    'monero_activity_row_';


class CryptoWalletEngineMoneroActivityCard extends StatelessWidget {
  final CryptoWalletFeatures? features;
  final MoneroSyncStatus? scannerStatus;
  final MoneroScannerStatus? backendStatus;
  final List<MoneroTransactionRow> transactions;

  const CryptoWalletEngineMoneroActivityCard({
    super.key,
    this.features,
    this.scannerStatus,
    this.backendStatus,
    this.transactions = const <MoneroTransactionRow>[],
  });

  @override
  Widget build(BuildContext context) {


    final backend = backendStatus;
    if (backend != null) {
      const overrideReasons = <String>{
        kMoneroScannerReasonRequiresDesktop,
        kMoneroScannerReasonNotConfigured,
        kMoneroScannerReasonViewKeyMissing,
        kMoneroScannerReasonUnreachable,
        kMoneroScannerReasonSyncing,
      };
      if (overrideReasons.contains(backend.reason)) {
        return _shell(
          bodyKey:
              'monero_activity_backend_${backend.reason}',
          body: Text(
            moneroScannerActivityCopyForReason(backend.reason),
            style: kWalletBodyStyle,
          ),
        );
      }
    }

    final xmrOn = features?.xmrEnabled ?? true;
    if (!xmrOn) {
      return _shell(
        bodyKey: kMoneroActivityDisabledKey,
        body: const Text(
          kMoneroActivityDisabledCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    final s = scannerStatus;
    if (s == null || s.isUnavailable) {
      return _shell(
        bodyKey: kMoneroActivityScannerNotEnabledKey,
        body: const Text(
          kMoneroActivityScannerNotEnabledCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    if (s.state == MoneroScannerState.notStarted) {
      return _shell(
        bodyKey: kMoneroActivityScannerNotStartedKey,
        body: const Text(
          kMoneroActivityScannerNotStartedCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    if (s.isSyncing) {
      return _shell(
        bodyKey: kMoneroActivitySyncingKey,
        body: const Text(
          kMoneroActivitySyncingCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    if (transactions.isEmpty) {
      return _shell(
        bodyKey: kMoneroActivityEmptyAfterSyncKey,
        body: const Text(
          kMoneroActivityEmptyAfterSyncCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    return _shell(
      bodyKey: 'monero_activity_rows_${transactions.length}',
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (int i = 0; i < transactions.length; i++)
            _txRow(i, transactions[i]),
        ],
      ),
    );
  }

  Widget _shell({required String bodyKey, required Widget body}) {
    return Container(
      key: const Key(kMoneroActivityCardKey),
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
                kMoneroActivityCardHeading,
                style: kWalletSectionHeadingStyle,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Padding(
            key: Key(bodyKey),
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: body,
          ),
        ],
      ),
    );
  }

  Widget _txRow(int index, MoneroTransactionRow tx) {
    final shortId = tx.txId.length > 12
        ? '${tx.txId.substring(0, 12)}…' : tx.txId;
    final amount = tx.amount ?? '';
    final direction = tx.direction == MoneroTransactionDirection.incoming
        ? 'IN' : tx.direction == MoneroTransactionDirection.outgoing
            ? 'OUT' : '';
    return Padding(
      key: Key('$kMoneroActivityRowKeyPrefix$index'),
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Icon(
            tx.direction == MoneroTransactionDirection.incoming
                ? Icons.south_rounded
                : Icons.north_rounded,
            size: 14, color: kWalletTextSecondary,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '$direction  $amount XMR${tx.locked ? '  (locked)' : ''}',
                  style: const TextStyle(
                    color: kWalletTextPrimary, fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  '$shortId${tx.confirmations != null
                    ? '  ${tx.confirmations} conf' : ''}',
                  style: kWalletMutedStyle,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


const String kMoneroBalanceCardHeading = 'Monero balance';
const String kMoneroBalanceScannerNotEnabledCopy =
    'Scanner not enabled';
const String kMoneroBalanceScannerNotStartedCopy =
    'Scanner not enabled';
const String kMoneroBalanceSyncingCopy =
    'Scanner syncing';
const String kMoneroBalanceDisabledCopy =
    'Scanner not enabled';
const String kMoneroBalanceCardKey = 'monero_balance_card';
const String kMoneroBalanceScannerNotEnabledKey =
    'monero_balance_scanner_not_enabled';
const String kMoneroBalanceScannerNotStartedKey =
    'monero_balance_scanner_not_started';
const String kMoneroBalanceSyncingKey =
    'monero_balance_syncing';
const String kMoneroBalanceDisabledKey =
    'monero_balance_disabled';
const String kMoneroBalanceReadyKey =
    'monero_balance_ready';
const String kMoneroBalanceUnlockedKey =
    'monero_balance_unlocked';
const String kMoneroBalanceLockedKey =
    'monero_balance_locked';
const String kMoneroBalanceTotalKey =
    'monero_balance_total';


class CryptoWalletEngineMoneroBalanceCard extends StatelessWidget {
  final CryptoWalletFeatures? features;
  final MoneroSyncStatus? scannerStatus;
  final MoneroScannerStatus? backendStatus;
  final MoneroBalanceReading? balance;

  const CryptoWalletEngineMoneroBalanceCard({
    super.key,
    this.features,
    this.scannerStatus,
    this.backendStatus,
    this.balance,
  });

  @override
  Widget build(BuildContext context) {


    final backend = backendStatus;
    if (backend != null) {
      const overrideReasons = <String>{
        kMoneroScannerReasonRequiresDesktop,
        kMoneroScannerReasonNotConfigured,
        kMoneroScannerReasonViewKeyMissing,
        kMoneroScannerReasonUnreachable,
        kMoneroScannerReasonSyncing,
      };
      if (overrideReasons.contains(backend.reason)) {
        return _shell(
          bodyKey:
              'monero_balance_backend_${backend.reason}',
          body: Text(
            moneroScannerBalanceCopyForReason(backend.reason),
            style: kWalletBodyStyle,
          ),
        );
      }
    }

    final xmrOn = features?.xmrEnabled ?? true;
    if (!xmrOn) {
      return _shell(
        bodyKey: kMoneroBalanceDisabledKey,
        body: const Text(
          kMoneroBalanceDisabledCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    final s = scannerStatus;
    final b = balance;
    if (s == null || s.isUnavailable) {
      return _shell(
        bodyKey: kMoneroBalanceScannerNotEnabledKey,
        body: const Text(
          kMoneroBalanceScannerNotEnabledCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    if (s.state == MoneroScannerState.notStarted) {
      return _shell(
        bodyKey: kMoneroBalanceScannerNotStartedKey,
        body: const Text(
          kMoneroBalanceScannerNotStartedCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    if (s.isSyncing) {
      return _shell(
        bodyKey: kMoneroBalanceSyncingKey,
        body: const Text(
          kMoneroBalanceSyncingCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    if (b == null
        || b.status != MoneroScannerErrorCode.balanceStatusReady) {
      return _shell(
        bodyKey: kMoneroBalanceScannerNotEnabledKey,
        body: const Text(
          kMoneroBalanceScannerNotEnabledCopy,
          style: kWalletBodyStyle,
        ),
      );
    }
    return _shell(
      bodyKey: kMoneroBalanceReadyKey,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Total: ${b.totalAmount ?? '0'} ${b.unit}',
            key: const Key(kMoneroBalanceTotalKey),
            style: const TextStyle(
              color: kWalletTextPrimary, fontSize: 22,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Unlocked: ${b.unlockedAmount ?? '0'} ${b.unit}',
            key: const Key(kMoneroBalanceUnlockedKey),
            style: kWalletBodyStyle,
          ),
          Text(
            'Locked: ${b.lockedAmount ?? '0'} ${b.unit}',
            key: const Key(kMoneroBalanceLockedKey),
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }

  Widget _shell({required String bodyKey, required Widget body}) {
    return Container(
      key: const Key(kMoneroBalanceCardKey),
      padding: const EdgeInsets.all(14),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.account_balance_wallet_outlined, size: 18,
                  color: kWalletTextSecondary),
              SizedBox(width: 8),
              Text(
                kMoneroBalanceCardHeading,
                style: kWalletSectionHeadingStyle,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Padding(
            key: Key(bodyKey),
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: body,
          ),
        ],
      ),
    );
  }
}
