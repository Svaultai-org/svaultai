




enum WalletNetworkKind { ethereum, solana, tron, monero, unknown }


WalletNetworkKind walletNetworkKindFor({
  required String asset,
  required String? network,
}) {
  if (asset == 'ETH' || asset == 'USDT_ERC20' || asset == 'USDC_ERC20') {
    return WalletNetworkKind.ethereum;
  }
  if (asset == 'SOL') return WalletNetworkKind.solana;
  if (asset == 'USDT_TRC20') return WalletNetworkKind.tron;
  if (asset == 'XMR') return WalletNetworkKind.monero;
  if (network == null) return WalletNetworkKind.unknown;
  if (network.startsWith('ethereum')) return WalletNetworkKind.ethereum;
  if (network.startsWith('solana')) return WalletNetworkKind.solana;
  if (network.startsWith('tron')) return WalletNetworkKind.tron;
  if (network.startsWith('monero')) return WalletNetworkKind.monero;
  return WalletNetworkKind.unknown;
}


String walletBalanceUnitLabel(String asset) {
  switch (asset) {
    case 'ETH':         return 'ETH';
    case 'USDT_ERC20':  return 'USDT';
    case 'USDC_ERC20':  return 'USDC';
    case 'SOL':         return 'SOL';
    case 'USDT_TRC20':  return 'USDT';
    case 'XMR':         return 'XMR';
  }
  return asset;
}


const String kWalletBalanceReasonKeyNoWallet =
    'wallet_balance_reason_no_wallet';
const String kWalletBalanceReasonKeyRpcMissing =
    'wallet_balance_reason_rpc_missing';
const String kWalletBalanceReasonKeyTokenContractMissing =
    'wallet_balance_reason_token_contract_missing';
const String kWalletBalanceReasonKeyRpcError =
    'wallet_balance_reason_rpc_error';
const String kWalletBalanceReasonKeyFeatureDisabled =
    'wallet_balance_reason_feature_disabled';
const String kWalletBalanceReasonKeyInvalidAddress =
    'wallet_balance_reason_invalid_address';
const String kWalletBalanceReasonKeyXmrScanner =
    'wallet_balance_reason_xmr_scanner_not_enabled';
const String kWalletBalanceReasonKeyUnknown =
    'wallet_balance_reason_unknown';




const String kWalletBalanceReasonKeyAuthExpired =
    'wallet_balance_reason_auth_expired';
const String kWalletBalanceReasonKeyDeviceNotTrusted =
    'wallet_balance_reason_device_not_trusted';
const String kWalletBalanceReasonKeyReceiveTimeout =
    'wallet_balance_reason_receive_timeout';
const String kWalletBalanceReasonKeyBalanceTimeout =
    'wallet_balance_reason_balance_timeout';




const String kWalletBalanceReasonKeyTronApiNotConfigured =
    'wallet_balance_reason_tron_api_not_configured';
const String kWalletBalanceReasonKeyTronApiKeyMissing =
    'wallet_balance_reason_tron_api_key_missing';
const String kWalletBalanceReasonKeyTronApiUnauthorized =
    'wallet_balance_reason_tron_api_unauthorized';
const String kWalletBalanceReasonKeyTronRateLimited =
    'wallet_balance_reason_tron_rate_limited';
const String kWalletBalanceReasonKeyTronProviderUnreachable =
    'wallet_balance_reason_tron_provider_unreachable';
const String kWalletBalanceReasonKeyTronContractNotConfigured =
    'wallet_balance_reason_tron_contract_not_configured';
const String kWalletBalanceReasonKeyTronContractReadFailed =
    'wallet_balance_reason_tron_contract_read_failed';
const String kWalletBalanceReasonKeyTronInvalidAddress =
    'wallet_balance_reason_tron_invalid_address';
const String kWalletBalanceReasonKeyTronProviderError =
    'wallet_balance_reason_tron_provider_error';


const String kWalletBalanceCopyNoWallet = 'Create wallet to view balance.';
const String kWalletBalanceCopyRpcMissingEthereum =
    'Ethereum RPC is not configured.';
const String kWalletBalanceCopyRpcMissingSolana =
    'Solana RPC is not configured.';
const String kWalletBalanceCopyRpcMissingTron =
    'TRON API is not configured.';
const String kWalletBalanceCopyRpcMissingMonero =
    'Scanner not enabled';




const String kWalletBalanceCopyMoneroScannerNote =
    'Monero balance requires wallet scanning.';
const String kWalletBalanceCopyTokenContractMissing =
    'Token contract is not configured.';
const String kWalletBalanceCopyRpcError =
    'Balance temporarily unavailable.';
const String kWalletBalanceCopyFeatureDisabled =
    'This asset is not enabled yet.';
const String kWalletBalanceCopyInvalidAddress =
    'Wallet address is not valid for this network.';
const String kWalletBalanceCopyXmrScanner =
    'Scanner not enabled';




const String kWalletBalanceCopyAuthExpired =
    'Session expired. Sign in again to see balance.';
const String kWalletBalanceCopyDeviceNotTrusted =
    'This device is not yet trusted for balance lookup.';
const String kWalletBalanceCopyReceiveTimeout =
    'Balance lookup is taking longer than expected. Retry in a moment.';
const String kWalletBalanceCopyBalanceTimeout =
    'Balance lookup is taking longer than expected. Retry in a moment.';




const String kWalletBalanceCopyTronApiNotConfigured =
    'TRON API is not configured.';
const String kWalletBalanceCopyTronApiKeyMissing =
    'TRON API key is not configured.';
const String kWalletBalanceCopyTronApiUnauthorized =
    'TRON API key was rejected.';
const String kWalletBalanceCopyTronRateLimited =
    'TRON provider rate limit reached.';
const String kWalletBalanceCopyTronProviderUnreachable =
    'TRON provider temporarily unavailable.';
const String kWalletBalanceCopyTronContractNotConfigured =
    'Token contract is not configured.';
const String kWalletBalanceCopyTronContractReadFailed =
    'Token contract read failed.';
const String kWalletBalanceCopyTronInvalidAddress =
    'Invalid TRON address.';
const String kWalletBalanceCopyTronProviderError =
    'Balance temporarily unavailable.';


class WalletBalanceReasonRender {
  final String bodyKey;
  final String message;

  const WalletBalanceReasonRender({
    required this.bodyKey,
    required this.message,
  });
}



const Set<String> _kRpcErrorReasonSet = {
  'rpc_unreachable', 'rpc_error', 'rpc_timeout', 'rpc_http',
  'rpc_bad_json', 'rpc_io', 'rpc_returned_error', 'rpc_bad_result',
  'contract_read_failed', 'network_error', 'invalid_response',
  'server_error', 'tron_api_error', 'tron_returned_error',
  'sol_returned_error', 'evm_returned_error',
};

const Set<String> _kFeatureDisabledReasonSet = {
  'feature_disabled', 'network_not_enabled', 'network_disabled',
  'engine_disabled', 'asset_not_enabled_on_mainnet',
  'token_receive_disabled', 'solana_special', 'tron_special',
  'monero_special', 'xmr_privacy_wallet_later',
  'unsupported_asset',
};


WalletBalanceReasonRender walletBalanceReasonRender({
  required String? reason,
  required String asset,
  required WalletNetworkKind networkKind,
}) {
  final r = (reason ?? '').trim();
  if (r == 'no_wallet_yet') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyNoWallet,
      message: kWalletBalanceCopyNoWallet,
    );
  }
  if (r == 'rpc_not_configured') {
    switch (networkKind) {
      case WalletNetworkKind.ethereum:
        return const WalletBalanceReasonRender(
          bodyKey: kWalletBalanceReasonKeyRpcMissing,
          message: kWalletBalanceCopyRpcMissingEthereum,
        );
      case WalletNetworkKind.solana:
        return const WalletBalanceReasonRender(
          bodyKey: kWalletBalanceReasonKeyRpcMissing,
          message: kWalletBalanceCopyRpcMissingSolana,
        );
      case WalletNetworkKind.tron:
        return const WalletBalanceReasonRender(
          bodyKey: kWalletBalanceReasonKeyRpcMissing,
          message: kWalletBalanceCopyRpcMissingTron,
        );
      case WalletNetworkKind.monero:
        return const WalletBalanceReasonRender(
          bodyKey: kWalletBalanceReasonKeyXmrScanner,
          message: kWalletBalanceCopyRpcMissingMonero,
        );
      case WalletNetworkKind.unknown:
        return const WalletBalanceReasonRender(
          bodyKey: kWalletBalanceReasonKeyRpcMissing,
          message: kWalletBalanceCopyRpcError,
        );
    }
  }
  if (r == 'token_contract_not_configured'
      || r == 'invalid_contract_address') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTokenContractMissing,
      message: kWalletBalanceCopyTokenContractMissing,
    );
  }
  if (r == 'invalid_address') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyInvalidAddress,
      message: kWalletBalanceCopyInvalidAddress,
    );
  }
  if (r == 'xmr_scanner_not_enabled') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyXmrScanner,
      message: kWalletBalanceCopyXmrScanner,
    );
  }
  if (_kFeatureDisabledReasonSet.contains(r)) {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyFeatureDisabled,
      message: kWalletBalanceCopyFeatureDisabled,
    );
  }
  if (_kRpcErrorReasonSet.contains(r)) {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyRpcError,
      message: kWalletBalanceCopyRpcError,
    );
  }








  if (r == 'tron_api_not_configured') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronApiNotConfigured,
      message: kWalletBalanceCopyTronApiNotConfigured,
    );
  }
  if (r == 'tron_api_key_missing') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronApiKeyMissing,
      message: kWalletBalanceCopyTronApiKeyMissing,
    );
  }
  if (r == 'tron_api_unauthorized') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronApiUnauthorized,
      message: kWalletBalanceCopyTronApiUnauthorized,
    );
  }
  if (r == 'tron_rate_limited') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronRateLimited,
      message: kWalletBalanceCopyTronRateLimited,
    );
  }
  if (r == 'tron_provider_unreachable') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronProviderUnreachable,
      message: kWalletBalanceCopyTronProviderUnreachable,
    );
  }
  if (r == 'tron_contract_not_configured') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronContractNotConfigured,
      message: kWalletBalanceCopyTronContractNotConfigured,
    );
  }
  if (r == 'tron_contract_read_failed') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronContractReadFailed,
      message: kWalletBalanceCopyTronContractReadFailed,
    );
  }
  if (r == 'tron_invalid_address') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronInvalidAddress,
      message: kWalletBalanceCopyTronInvalidAddress,
    );
  }
  if (r == 'tron_provider_error') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyTronProviderError,
      message: kWalletBalanceCopyTronProviderError,
    );
  }

  if (r == 'auth_expired') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyAuthExpired,
      message: kWalletBalanceCopyAuthExpired,
    );
  }
  if (r == 'device_not_trusted') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyDeviceNotTrusted,
      message: kWalletBalanceCopyDeviceNotTrusted,
    );
  }
  if (r == 'receive_timeout') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyReceiveTimeout,
      message: kWalletBalanceCopyReceiveTimeout,
    );
  }
  if (r == 'balance_timeout') {
    return const WalletBalanceReasonRender(
      bodyKey: kWalletBalanceReasonKeyBalanceTimeout,
      message: kWalletBalanceCopyBalanceTimeout,
    );
  }

  return const WalletBalanceReasonRender(
    bodyKey: kWalletBalanceReasonKeyUnknown,
    message: kWalletBalanceCopyRpcError,
  );
}


String walletBalanceRealZeroCopy(String asset) {
  return '0 ${walletBalanceUnitLabel(asset)}';
}
