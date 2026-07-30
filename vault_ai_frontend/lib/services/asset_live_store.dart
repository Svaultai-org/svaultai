


import 'dart:developer' as developer;

import 'package:flutter/foundation.dart' show kDebugMode, ChangeNotifier;

import 'crypto_wallet_dashboard_reason.dart';




class AssetLiveStore extends ChangeNotifier {

  static final AssetLiveStore instance = AssetLiveStore._();

  AssetLiveStore._();




  final Map<String, DashboardAssetLiveState> _states = {};




  final Map<String, int> _seqCounter = {};




  final Map<String, int> _seqLatestApplied = {};




  Map<String, DashboardAssetLiveState> get statesSnapshot =>
      Map<String, DashboardAssetLiveState>.unmodifiable(_states);




  DashboardAssetLiveState? getState(String asset) => _states[asset];




  int claimSeq(String asset) {
    final s = (_seqCounter[asset] ?? 0) + 1;
    _seqCounter[asset] = s;
    return s;
  }




  bool applyState({
    required String source,
    required String asset,
    required int seq,
    required DashboardAssetLiveState state,
    String? network,
  }) {
    final latest = _seqLatestApplied[asset] ?? 0;
    if (seq < latest) {
      _log(
        'asset_live_store_drop_stale '
        'source=$source asset=$asset '
        'network=${network ?? ""} '
        'seq=$seq latest_applied=$latest '
        'kind=${state.kind.name}',
      );
      return false;
    }

    _seqLatestApplied[asset] = seq;
    _states[asset] = state;
    _log(
      '${source}_asset_state asset=$asset '
      'network=${network ?? ""} '
      'kind=${state.kind.name} '
      'amount_present=${state.balanceAmount != null} '
      'unit=${state.balanceUnit ?? ""} '
      'reason=${state.backendReason ?? ""} '
      'seq=$seq',
    );
    notifyListeners();
    return true;
  }




  void clear() {
    _states.clear();
    _seqCounter.clear();
    _seqLatestApplied.clear();
    notifyListeners();
  }

  void resetForTest() {
    clear();
  }

  void _log(String message) {
    if (!kDebugMode) return;
    developer.log(message, name: 'CryptoVault');
  }
}
