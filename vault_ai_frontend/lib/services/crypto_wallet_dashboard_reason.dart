


import 'dart:async';
import 'dart:developer' as developer;

import 'package:flutter/foundation.dart' show kDebugMode;

import '../api_client.dart';
import 'crypto_wallet_features.dart';




const String kDashboardReasonAuthExpired = 'auth_expired';
const String kDashboardReasonDeviceNotTrusted = 'device_not_trusted';
const String kDashboardReasonReceiveTimeout = 'receive_timeout';
const String kDashboardReasonBalanceTimeout = 'balance_timeout';




String _classifyLoaderException(Object e) {
  if (e is AuthExpiredException) return kDashboardReasonAuthExpired;
  if (e is DeviceNotTrustedException) return kDashboardReasonDeviceNotTrusted;
  if (e is TimeoutException) return kDashboardReasonReceiveTimeout;
  return 'rpc_error';
}




void _walletBalanceDevLog(String message) {
  if (!kDebugMode) return;
  developer.log(message, name: 'CryptoVault');
}




enum DashboardAssetLiveStateKind {
  loading,
  noWallet,
  available,
  reason,
}


class DashboardAssetLiveState {
  final DashboardAssetLiveStateKind kind;
  final String? balanceAmount;
  final String? balanceUnit;
  final String? backendReason;




  final String? publicAddress;

  const DashboardAssetLiveState._({
    required this.kind,
    this.balanceAmount,
    this.balanceUnit,
    this.backendReason,
    this.publicAddress,
  });

  const DashboardAssetLiveState.loading()
      : this._(kind: DashboardAssetLiveStateKind.loading);

  const DashboardAssetLiveState.noWallet()
      : this._(kind: DashboardAssetLiveStateKind.noWallet);

  const DashboardAssetLiveState.available({
    required String amount, String? unit, String? publicAddress,
  }) : this._(
    kind: DashboardAssetLiveStateKind.available,
    balanceAmount: amount,
    balanceUnit: unit,
    publicAddress: publicAddress,
  );

  const DashboardAssetLiveState.reason({
    required String reason, String? publicAddress,
  }) : this._(
    kind: DashboardAssetLiveStateKind.reason,
    backendReason: reason,
    publicAddress: publicAddress,
  );

  bool get hasAvailableBalance =>
      kind == DashboardAssetLiveStateKind.available
      && balanceAmount != null;




  bool get publicAddressPresent =>
      publicAddress != null && publicAddress!.isNotEmpty;
}




List<String> dashboardAssetsForInitialLiveRefresh(CryptoWalletFeatures f) {
  final out = <String>[];
  if (f.mainnetReceiveEnabled) out.add('ETH');
  if (f.mainnetErc20ReceiveEnabled) {
    out.add('USDT_ERC20');
    out.add('USDC_ERC20');
  }
  if (f.solanaEnabled) out.add('SOL');
  if (f.tronEnabled) out.add('USDT_TRC20');


  return out;
}








String networkForAssetRoute({
  required String asset,
  required CryptoWalletFeatures? features,
  required String effectiveMainnetNetwork,
}) {
  switch (asset) {
    case 'SOL':
      if (features?.solanaEnabled ?? false) return 'solana_mainnet';
      break;
    case 'USDT_TRC20':
      if (features?.tronEnabled ?? false) return 'tron_mainnet';
      break;
    case 'XMR':
      if (features?.xmrEnabled ?? false) return 'monero_mainnet';
      break;
  }
  return effectiveMainnetNetwork;
}




Future<DashboardAssetLiveState> loadWalletReceiveAndBalance({
  required VaultAIClient apiClient,
  required String authToken,
  required String network,
  required String asset,
  Duration receiveTimeout = const Duration(seconds: 8),
  Duration balanceTimeout = const Duration(seconds: 10),
}) =>
    loadAssetWalletState(
      apiClient: apiClient,
      authToken: authToken,
      network: network,
      asset: asset,
      receiveTimeout: receiveTimeout,
      balanceTimeout: balanceTimeout,
    );


Future<DashboardAssetLiveState> loadAssetWalletState({
  required VaultAIClient apiClient,
  required String authToken,
  required String network,
  required String asset,
  Duration receiveTimeout = const Duration(seconds: 8),
  Duration balanceTimeout = const Duration(seconds: 10),
}) async {
  _walletBalanceDevLog(
    'live_refresh_started asset=$asset network=$network',
  );




  Map<String, dynamic> receive;
  try {
    receive = await apiClient
        .getCryptoWalletReceiveNetwork(
          network: network,
          asset: asset,
          authToken: authToken,
        )
        .timeout(receiveTimeout);
  } catch (e) {
    final classified = _classifyLoaderException(e);
    _walletBalanceDevLog(
      'receive_call_failed asset=$asset '
      'error=${e.runtimeType} classified=$classified',
    );




    return DashboardAssetLiveState.reason(reason: classified);
  }

  final receiveEngineStatus = (receive['wallet_engine'] ?? '').toString();
  final rawAddr = receive['publicAddress'];
  final walletExists = receiveEngineStatus == 'receive_ready'
      && rawAddr is String
      && rawAddr.isNotEmpty;
  _walletBalanceDevLog(
    'receive_response asset=$asset '
    'wallet_engine=$receiveEngineStatus wallet_exists=$walletExists',
  );

  if (!walletExists) {
    _walletBalanceDevLog(
      'live_refresh_result asset=$asset kind=no_wallet '
      'engine_status=$receiveEngineStatus',
    );
    return const DashboardAssetLiveState.noWallet();
  }




  final address = rawAddr;
  try {
    final balance = await apiClient
        .getCryptoWalletBalanceNetwork(
          network: network,
          asset: asset,
          authToken: authToken,
          address: address,
        )
        .timeout(balanceTimeout);




    final sortedKeys = (balance.keys.toList()..sort()).join(',');
    final balanceStatus = (balance['balanceStatus'] ?? '').toString();
    final hasAvailableAmount = balance['availableAmount'] != null;
    final unitRaw = balance['unit'];
    final unitStr = (unitRaw is String && unitRaw.isNotEmpty) ? unitRaw : '';
    final reasonRaw = balance['reason'];
    final reasonStr = (reasonRaw is String) ? reasonRaw : '';
    _walletBalanceDevLog(
      'balance_shape asset=$asset '
      'body_top_keys=$sortedKeys '
      'balanceStatus=$balanceStatus '
      'availableAmount_present=$hasAvailableAmount '
      'unit=$unitStr '
      'reason=$reasonStr',
    );

    if (balanceStatus == 'available') {
      final amt = balance['availableAmount'] ?? balance['balance'];
      final unit = balance['unit'];
      final amount = amt?.toString() ?? '0';
      final resolvedUnit =
          (unit is String && unit.isNotEmpty) ? unit : null;
      _walletBalanceDevLog(
        'balance_available asset=$asset '
        'amount=$amount unit=$resolvedUnit',
      );
      return DashboardAssetLiveState.available(
        amount: amount, unit: resolvedUnit,
        publicAddress: address,
      );
    }
    final rawReason = balance['reason'];
    final resolvedReason =
        (rawReason is String && rawReason.isNotEmpty)
            ? rawReason : 'rpc_error';
    _walletBalanceDevLog(
      'balance_unavailable asset=$asset '
      'balance_status=$balanceStatus reason=$resolvedReason',
    );
    return DashboardAssetLiveState.reason(
      reason: resolvedReason,
      publicAddress: address,
    );
  } catch (e) {

    var classified = _classifyLoaderException(e);
    if (classified == kDashboardReasonReceiveTimeout) {
      classified = kDashboardReasonBalanceTimeout;
    }
    _walletBalanceDevLog(
      'balance_call_failed asset=$asset '
      'error=${e.runtimeType} classified=$classified',
    );
    return DashboardAssetLiveState.reason(
      reason: classified,
      publicAddress: address,
    );
  }
}




String? dashboardAssetBalanceReason({
  required String asset,
  required CryptoWalletFeatures? features,
}) {
  if (features == null) return null;
  switch (asset) {
    case 'ETH':
      if (!features.mainnetReceiveEnabled) return 'feature_disabled';
      return 'no_wallet_yet';
    case 'USDT_ERC20':
    case 'USDC_ERC20':
      if (!features.mainnetErc20ReceiveEnabled) return 'feature_disabled';
      return 'no_wallet_yet';
    case 'SOL':
      if (!features.solanaEnabled) return 'feature_disabled';
      if (!features.solanaBalanceEnabled) return 'rpc_not_configured';
      return 'no_wallet_yet';
    case 'USDT_TRC20':
      if (!features.tronEnabled) return 'feature_disabled';
      if (!features.tronBalanceEnabled) return 'rpc_not_configured';
      if (!features.tronUsdtContractConfigured) {
        return 'token_contract_not_configured';
      }
      return 'no_wallet_yet';
    case 'XMR':
      if (!features.xmrEnabled) return 'feature_disabled';
      return 'xmr_scanner_not_enabled';
  }
  return null;
}




class DashboardAssetActionCapability {
  final bool receive;
  final bool send;
  final bool transactions;
  final String? sendUnavailableReason;
  final String? transactionsUnavailableReason;

  const DashboardAssetActionCapability({
    required this.receive,
    required this.send,
    required this.transactions,
    this.sendUnavailableReason,
    this.transactionsUnavailableReason,
  });
}


const String kAssetSendUnavailableMonero =
    'Monero sending is not enabled yet.';
const String kAssetSendUnavailableTronDisabled =
    'USDT TRC20 sending is not enabled yet.';
const String kAssetSendUnavailableTronPaused =
    'USDT TRC20 sending is temporarily paused.';
const String kAssetSendUnavailableTronProviderNotReady =
    'Send not ready';
const String kAssetSendUnavailableSolanaDisabled =
    'Solana sending is not enabled yet.';
const String kAssetSendUnavailableSolanaPaused =
    'Solana sending is temporarily paused.';
const String kAssetSendUnavailableMainnetDisabled =
    'Mainnet sending is not enabled yet.';
const String kAssetSendUnavailableMainnetPaused =
    'Mainnet sending is temporarily paused.';

const String kAssetActivityUnavailableMonero =
    'Monero scanning is not available in this build yet.';
const String kAssetActivityUnavailableTron =
    'TRON activity feed is not connected yet.';
const String kAssetActivityUnavailableSolana =
    'Solana activity feed is not connected yet.';
const String kAssetActivityUnavailableEthereum =
    'Activity feed is not connected yet.';




enum DashboardCardActivityKind {
  empty,
  historyNotConnected,
  temporarilyUnavailable,
  xmrScannerMissing,
}




DashboardCardActivityKind dashboardCardActivityKind({
  required String asset,
  required CryptoWalletFeatures? features,
}) {
  final f = features;
  switch (asset) {
    case 'ETH':
    case 'USDT_ERC20':
    case 'USDC_ERC20':




      return DashboardCardActivityKind.empty;

    case 'SOL':
      if (f == null) return DashboardCardActivityKind.empty;
      if (!f.solanaEnabled) return DashboardCardActivityKind.empty;
      if (!f.solanaActivityConnected) {
        return DashboardCardActivityKind.historyNotConnected;
      }
      return DashboardCardActivityKind.empty;

    case 'USDT_TRC20':




      return DashboardCardActivityKind.empty;

    case 'XMR':
      if (f == null) return DashboardCardActivityKind.empty;
      if (!f.xmrEnabled) return DashboardCardActivityKind.empty;
      return DashboardCardActivityKind.xmrScannerMissing;
  }
  return DashboardCardActivityKind.empty;
}




String dashboardCardActivityChipCopy(DashboardCardActivityKind kind) {
  switch (kind) {
    case DashboardCardActivityKind.empty:
      return 'No activity yet';
    case DashboardCardActivityKind.historyNotConnected:
      return 'Activity history not connected';
    case DashboardCardActivityKind.temporarilyUnavailable:
      return 'Activity temporarily unavailable';
    case DashboardCardActivityKind.xmrScannerMissing:
      return 'Scanner not enabled';
  }
}




DashboardAssetActionCapability dashboardAssetActionCapability({
  required String asset,
  required CryptoWalletFeatures? features,
  required bool hasReceiveWiring,
  required bool hasSendWiring,
}) {
  final f = features;
  if (f == null) {
    return const DashboardAssetActionCapability(
      receive: false, send: false, transactions: false,
    );
  }
  switch (asset) {
    case 'ETH':
    case 'USDT_ERC20':
    case 'USDC_ERC20': {
      final receive = hasReceiveWiring
          && (asset == 'ETH'
              ? f.mainnetReceiveEnabled
              : f.mainnetErc20ReceiveEnabled);
      final sendOn = f.effectiveMainnetSendEnabled;
      final send = receive && hasSendWiring && sendOn;
      return DashboardAssetActionCapability(
        receive: receive,
        send: send,
        transactions: false,
        sendUnavailableReason: send
            ? null
            : (f.mainnetSendPaused
                ? kAssetSendUnavailableMainnetPaused
                : kAssetSendUnavailableMainnetDisabled),
        transactionsUnavailableReason: kAssetActivityUnavailableEthereum,
      );
    }
    case 'SOL': {
      final receive = hasReceiveWiring && f.solanaEnabled;
      final sendOn = f.solanaSendEnabled && !f.solanaSendPaused;
      return DashboardAssetActionCapability(
        receive: receive,
        send: receive && sendOn,
        transactions: receive && f.solanaActivityConnected,
        sendUnavailableReason: sendOn
            ? null
            : (f.solanaSendPaused
                ? kAssetSendUnavailableSolanaPaused
                : kAssetSendUnavailableSolanaDisabled),
        transactionsUnavailableReason: f.solanaActivityConnected
            ? null
            : kAssetActivityUnavailableSolana,
      );
    }
    case 'USDT_TRC20': {
      final receive = hasReceiveWiring && f.tronEnabled;
      final sendOn = f.tronSendEnabled && !f.tronSendPaused;




      final providerReady = f.tronBalanceEnabled
          && f.tronUsdtContractConfigured;
      final send = receive && hasSendWiring && sendOn && providerReady;
      final String? sendReason;
      if (send) {
        sendReason = null;
      } else if (f.tronSendPaused) {
        sendReason = kAssetSendUnavailableTronPaused;
      } else if (!f.tronSendEnabled) {
        sendReason = kAssetSendUnavailableTronDisabled;
      } else if (!providerReady) {


        sendReason = kAssetSendUnavailableTronProviderNotReady;
      } else {
        sendReason = kAssetSendUnavailableTronDisabled;
      }
      return DashboardAssetActionCapability(
        receive: receive,
        send: send,
        transactions: receive && f.tronActivityConnected,
        sendUnavailableReason: sendReason,
        transactionsUnavailableReason: f.tronActivityConnected
            ? null
            : kAssetActivityUnavailableTron,
      );
    }
    case 'XMR': {
      final receive = hasReceiveWiring && f.xmrEnabled;
      return DashboardAssetActionCapability(
        receive: receive,
        send: false,
        transactions: false,
        sendUnavailableReason: kAssetSendUnavailableMonero,
        transactionsUnavailableReason: kAssetActivityUnavailableMonero,
      );
    }
  }
  return const DashboardAssetActionCapability(
    receive: false, send: false, transactions: false,
  );
}
