
import 'package:flutter/foundation.dart';




class PerfSpan {
  final String name;
  final DateTime startedAt;
  final DateTime endedAt;
  final int elapsedMs;

  const PerfSpan({
    required this.name,
    required this.startedAt,
    required this.endedAt,
    required this.elapsedMs,
  });

  Map<String, Object?> toSafeJson() => <String, Object?>{
        'name': name,
        'started_at_ms':
            startedAt.millisecondsSinceEpoch,
        'ended_at_ms':
            endedAt.millisecondsSinceEpoch,
        'elapsed_ms': elapsedMs,
      };
}


bool _looksSensitive(String s) {
  final low = s.toLowerCase();
  const banned = <String>[
    'pin', 'password', 'seed', 'mnemonic',
    'private_key', 'privatekey', 'spend_key',
    'view_key', 'bearer', 'authorization',
    'auth_token', 'authtoken', 'api_key', 'apikey',
    'encrypted_data', 'session_token', 'sessiontoken',
    'pin_verifier',
  ];
  for (final b in banned) {
    if (low.contains(b)) return true;
  }
  return false;
}


class UnsafePerfSpanNameException implements Exception {
  final String name;
  const UnsafePerfSpanNameException(this.name);
  @override
  String toString() =>
      'UnsafePerfSpanNameException: perf span name "$name" '
      'looks like it might contain a secret';
}


class PerfTrace {
  PerfTrace._();

  static final PerfTrace instance = PerfTrace._();

  final List<PerfSpan> _spans = <PerfSpan>[];
  final Map<String, int> _requestCounters = <String, int>{};
  final Map<String, DateTime> _requestFirstSeen =
      <String, DateTime>{};

  DateTime Function() nowClock = () => DateTime.now();

  bool _enabled = !kReleaseMode;

  bool get enabled => _enabled;

  void setEnabledForTests(bool v) {
    _enabled = v;
  }

  T span<T>(String name, T Function() body) {
    if (!_enabled) return body();
    if (_looksSensitive(name)) {
      throw UnsafePerfSpanNameException(name);
    }
    final start = nowClock();
    try {
      return body();
    } finally {
      final end = nowClock();
      _spans.add(
        PerfSpan(
          name: name,
          startedAt: start,
          endedAt: end,
          elapsedMs: end.difference(start).inMilliseconds,
        ),
      );
    }
  }

  Future<T> spanAsync<T>(
    String name, Future<T> Function() body,
  ) async {
    if (!_enabled) return body();
    if (_looksSensitive(name)) {
      throw UnsafePerfSpanNameException(name);
    }
    final start = nowClock();
    try {
      return await body();
    } finally {
      final end = nowClock();
      _spans.add(
        PerfSpan(
          name: name,
          startedAt: start,
          endedAt: end,
          elapsedMs: end.difference(start).inMilliseconds,
        ),
      );
    }
  }

  void recordRequest(String requestKind) {
    if (!_enabled) return;
    if (_looksSensitive(requestKind)) {
      throw UnsafePerfSpanNameException(requestKind);
    }
    _requestCounters[requestKind] =
        (_requestCounters[requestKind] ?? 0) + 1;
    _requestFirstSeen.putIfAbsent(
      requestKind, () => nowClock(),
    );
  }

  int requestCount(String requestKind) =>
      _requestCounters[requestKind] ?? 0;

  int duplicateCount(String requestKind) {
    final n = requestCount(requestKind);
    return n <= 1 ? 0 : n - 1;
  }

  List<PerfSpan> spans() => List.unmodifiable(_spans);

  Map<String, int> requestCountersSnapshot() =>
      Map.unmodifiable(_requestCounters);

  void resetForTests() {
    _spans.clear();
    _requestCounters.clear();
    _requestFirstSeen.clear();
  }
}



const String kSpanChatSendClicked           = 'chat.send.clicked';
const String kSpanChatUserBubbleShown       = 'chat.user_bubble.shown';
const String kSpanChatThinkingShown         = 'chat.thinking.shown';
const String kSpanChatFirstAssistantResponse = 'chat.assistant.first_response';
const String kSpanChatTotalResponse         = 'chat.assistant.total_response';

const String kSpanScreenOpenSettings        = 'screen.open.settings';
const String kSpanScreenOpenHelpCenter      = 'screen.open.help_center';
const String kSpanScreenOpenCryptoVault     = 'screen.open.crypto_vault';
const String kSpanScreenOpenLogins          = 'screen.open.logins';
const String kSpanScreenOpenSecureItems     = 'screen.open.secure_items';
const String kSpanScreenOpenIdDocs          = 'screen.open.id_documents';
const String kSpanScreenOpenBilling         = 'screen.open.billing';
const String kSpanScreenOpenDeleteVaultModal =
    'screen.open.delete_vault_modal';



const String kRequestChatSend          = 'request.chat.send';
const String kRequestCryptoBalance     = 'request.crypto.balance';
const String kRequestCryptoActivity    = 'request.crypto.activity';
const String kRequestVaultOverview     = 'request.vault.overview';
const String kRequestStorageQuota      = 'request.storage.quota';
const String kRequestBillingStatus     = 'request.billing.status';
const String kRequestVaultDeleteStatus = 'request.vault_delete.status';
