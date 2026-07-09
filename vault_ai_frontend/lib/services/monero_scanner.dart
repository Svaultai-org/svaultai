
import 'dart:async';
import 'dart:typed_data';


enum MoneroScannerState {
  scannerUnavailable,
  notStarted,
  syncing,
  synced,
  failed,
  stopped,
}


class MoneroScannerErrorCode {
  static const String daemonUnreachable = 'daemon_unreachable';
  static const String daemonRejectedRequest = 'daemon_rejected_request';
  static const String invalidWalletSecret = 'invalid_wallet_secret';
  static const String scannerInternalError = 'scanner_internal_error';
  static const String scannerUnavailable = 'scanner_unavailable';
  static const String scanStopped = 'scan_stopped';
  static const String balanceStatusUnavailable = 'unavailable';
  static const String balanceStatusPartial = 'partial_syncing';
  static const String balanceStatusReady = 'available';

  static const Set<String> allowedErrorCodes = {
    daemonUnreachable,
    daemonRejectedRequest,
    invalidWalletSecret,
    scannerInternalError,
    scannerUnavailable,
    scanStopped,
  };
}


enum MoneroTransactionDirection { incoming, outgoing, unknown }


class MoneroScannerInput {

  final Uint8List privateViewKey;
  final Uint8List publicSpendKey;
  final String publicAddress;
  final int restoreHeight;
  final String? daemonUrl;

  const MoneroScannerInput({
    required this.privateViewKey,
    required this.publicSpendKey,
    required this.publicAddress,
    required this.restoreHeight,
    this.daemonUrl,
  });


  void wipe() {
    for (int i = 0; i < privateViewKey.length; i++) {
      privateViewKey[i] = 0;
    }
  }


  @override
  String toString() => 'MoneroScannerInput(<redacted>)';
}


class MoneroSyncStatus {
  final MoneroScannerState state;
  final int? currentHeight;
  final int? targetHeight;
  final int restoreHeight;
  final double? percent;
  final DateTime? lastUpdatedAt;
  final String? errorReason;

  const MoneroSyncStatus({
    required this.state,
    this.currentHeight,
    this.targetHeight,
    required this.restoreHeight,
    this.percent,
    this.lastUpdatedAt,
    this.errorReason,
  });

  factory MoneroSyncStatus.scannerUnavailable() {
    return const MoneroSyncStatus(
      state: MoneroScannerState.scannerUnavailable,
      restoreHeight: 0,
    );
  }

  factory MoneroSyncStatus.notStarted({required int restoreHeight}) {
    return MoneroSyncStatus(
      state: MoneroScannerState.notStarted,
      restoreHeight: restoreHeight,
    );
  }

  bool get isSyncing => state == MoneroScannerState.syncing;
  bool get isSynced => state == MoneroScannerState.synced;
  bool get isFailed => state == MoneroScannerState.failed;
  bool get isStopped => state == MoneroScannerState.stopped;
  bool get isUnavailable =>
      state == MoneroScannerState.scannerUnavailable;
}


class MoneroBalanceReading {

  final String status;

  final String? unlockedAmount;
  final String? lockedAmount;
  final String? totalAmount;
  final String unit;
  final String? reason;
  final bool isPartial;

  const MoneroBalanceReading({
    required this.status,
    this.unlockedAmount,
    this.lockedAmount,
    this.totalAmount,
    this.unit = 'XMR',
    this.reason,
    this.isPartial = false,
  });

  factory MoneroBalanceReading.unavailable({required String reason}) {
    return MoneroBalanceReading(
      status: MoneroScannerErrorCode.balanceStatusUnavailable,
      reason: reason,
    );
  }

  factory MoneroBalanceReading.ready({
    required String unlocked,
    required String locked,
    required String total,
  }) {
    return MoneroBalanceReading(
      status: MoneroScannerErrorCode.balanceStatusReady,
      unlockedAmount: unlocked,
      lockedAmount: locked,
      totalAmount: total,
    );
  }
}


class MoneroTransactionRow {
  final String txId;
  final MoneroTransactionDirection direction;
  final String? amount;
  final int? confirmations;
  final int? blockHeight;
  final DateTime? timestamp;
  final bool locked;

  const MoneroTransactionRow({
    required this.txId,
    required this.direction,
    this.amount,
    this.confirmations,
    this.blockHeight,
    this.timestamp,
    this.locked = false,
  });
}


abstract class MoneroScannerAdapter {
  bool get isAvailable;

  String get availabilityReason;

  Future<void> startScan(MoneroScannerInput input);

  Future<void> stopScan();

  Future<MoneroSyncStatus> getSyncStatus();

  Future<MoneroBalanceReading> getBalance();

  Future<List<MoneroTransactionRow>> getTransactions();

  Stream<MoneroSyncStatus> get syncStatusStream;
}


class NullMoneroScannerAdapter implements MoneroScannerAdapter {

  static const String kBlockerReason =
      'Client-side Monero scanning is not wired into this build. A safe '
      'pure-Dart output scanner or FFI to a vetted Monero wallet library '
      'ships in a follow-up slice. Balance and activity remain honestly '
      'unavailable until that slice lands.';

  const NullMoneroScannerAdapter();

  @override
  bool get isAvailable => false;

  @override
  String get availabilityReason => kBlockerReason;

  @override
  Future<void> startScan(MoneroScannerInput input) async {
    throw StateError(kBlockerReason);
  }

  @override
  Future<void> stopScan() async {
  }

  @override
  Future<MoneroSyncStatus> getSyncStatus() async {
    return MoneroSyncStatus.scannerUnavailable();
  }

  @override
  Future<MoneroBalanceReading> getBalance() async {
    return MoneroBalanceReading.unavailable(
      reason: MoneroScannerErrorCode.scannerUnavailable,
    );
  }

  @override
  Future<List<MoneroTransactionRow>> getTransactions() async {
    return const <MoneroTransactionRow>[];
  }

  @override
  Stream<MoneroSyncStatus> get syncStatusStream =>
      Stream<MoneroSyncStatus>.empty();
}


class InjectedMoneroScannerAdapter implements MoneroScannerAdapter {
  final bool _available;
  final String _reason;
  final Future<void> Function(MoneroScannerInput input)? onStart;
  final Future<void> Function()? onStop;
  MoneroSyncStatus _status;
  MoneroBalanceReading _balance;
  List<MoneroTransactionRow> _transactions;
  final StreamController<MoneroSyncStatus> _streamController =
      StreamController<MoneroSyncStatus>.broadcast();

  InjectedMoneroScannerAdapter({
    required bool available,
    String reason = '',
    MoneroSyncStatus? initialStatus,
    MoneroBalanceReading? initialBalance,
    List<MoneroTransactionRow>? initialTransactions,
    this.onStart,
    this.onStop,
  })  : _available = available,
        _reason = reason,
        _status = initialStatus ?? MoneroSyncStatus.notStarted(
          restoreHeight: 0,
        ),
        _balance = initialBalance ?? MoneroBalanceReading.unavailable(
          reason: MoneroScannerErrorCode.balanceStatusUnavailable,
        ),
        _transactions = initialTransactions ?? const <MoneroTransactionRow>[];

  @override
  bool get isAvailable => _available;

  @override
  String get availabilityReason => _reason;

  @override
  Future<void> startScan(MoneroScannerInput input) async {
    if (onStart != null) {
      await onStart!(input);
    }
  }

  @override
  Future<void> stopScan() async {
    if (onStop != null) {
      await onStop!();
    }
  }

  @override
  Future<MoneroSyncStatus> getSyncStatus() async => _status;

  @override
  Future<MoneroBalanceReading> getBalance() async => _balance;

  @override
  Future<List<MoneroTransactionRow>> getTransactions() async => _transactions;

  @override
  Stream<MoneroSyncStatus> get syncStatusStream => _streamController.stream;


  void setStatus(MoneroSyncStatus s) {
    _status = s;
    if (!_streamController.isClosed) {
      _streamController.add(s);
    }
  }

  void setBalance(MoneroBalanceReading b) {
    _balance = b;
  }

  void setTransactions(List<MoneroTransactionRow> txs) {
    _transactions = txs;
  }

  Future<void> dispose() async {
    if (!_streamController.isClosed) {
      await _streamController.close();
    }
  }
}
