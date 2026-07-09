

const String kEvmNetworkEthereumSepolia = 'ethereum_sepolia';
const String kEvmNetworkEthereumMainnet = 'ethereum_mainnet';

const List<String> kAllEvmNetworks = [
  kEvmNetworkEthereumSepolia,
  kEvmNetworkEthereumMainnet,
];


const Map<String, String> kEvmNetworkDisplayName = {
  kEvmNetworkEthereumSepolia: 'Ethereum Sepolia',
  kEvmNetworkEthereumMainnet: 'Ethereum Mainnet',
};


const Map<String, int> kEvmNetworkChainId = {
  kEvmNetworkEthereumSepolia: 11155111,
  kEvmNetworkEthereumMainnet: 1,
};


const Map<String, bool> kEvmNetworkIsTestnet = {
  kEvmNetworkEthereumSepolia: true,
  kEvmNetworkEthereumMainnet: false,
};


const String kEvmNetworkTestnetWarning =
    'This is Ethereum Sepolia testnet. Do not send mainnet ETH or '
    'mainnet ERC20 tokens to this address — they will not arrive.';

const String kEvmNetworkMainnetWarning =
    'This uses real Ethereum mainnet funds. Double-check the '
    'destination address — mainnet transactions cannot be '
    'reversed.';


const String kEvmNetworkMainnetComingSoon =
    'Ethereum Mainnet is not enabled in this build.';


const String kEvmNetworkDefault = kEvmNetworkEthereumSepolia;


const String kCryptoWalletDefaultNetworkRaw = String.fromEnvironment(
  'CRYPTO_WALLET_DEFAULT_NETWORK',
  defaultValue: '',
);


const String kCompileTimeDefaultNetworkResolved =
    kCryptoWalletDefaultNetworkRaw == kEvmNetworkEthereumMainnet
        ? kEvmNetworkEthereumMainnet
        : kEvmNetworkEthereumSepolia;


String resolveCompileTimeDefaultNetwork() {
  final normalized = kCryptoWalletDefaultNetworkRaw.trim().toLowerCase();
  if (normalized == kEvmNetworkEthereumMainnet
      || normalized == kEvmNetworkEthereumSepolia) {
    return normalized;
  }
  return kEvmNetworkEthereumSepolia;
}


bool compileTimeDefaultNetworkConfigValid() {
  final normalized = kCryptoWalletDefaultNetworkRaw.trim().toLowerCase();
  if (normalized.isEmpty) return true;
  return normalized == kEvmNetworkEthereumMainnet
      || normalized == kEvmNetworkEthereumSepolia;
}


String resolveEffectiveDefaultNetwork({
  required String backendDefaultNetwork,
  required bool backendDefaultNetworkConfigValid,
}) {
  final backendNorm = backendDefaultNetwork.trim().toLowerCase();
  final backendValid = backendDefaultNetworkConfigValid
      && (backendNorm == kEvmNetworkEthereumMainnet
          || backendNorm == kEvmNetworkEthereumSepolia);
  if (backendValid) return backendNorm;
  if (compileTimeDefaultNetworkConfigValid()
      && kCryptoWalletDefaultNetworkRaw.trim().isNotEmpty) {
    return resolveCompileTimeDefaultNetwork();
  }
  return kEvmNetworkEthereumSepolia;
}


const bool kCryptoWalletEngineMainnetReceiveEnabled = bool.fromEnvironment(
  'CRYPTO_WALLET_ENGINE_MAINNET_RECEIVE_ENABLED',
  defaultValue: false,
);


bool compileTimeEffectiveMainnetIsDefault() {
  return resolveCompileTimeDefaultNetwork() == kEvmNetworkEthereumMainnet
      && kCryptoWalletEngineMainnetReceiveEnabled;
}


const String kEvmNetworkMainnetDashboardChipLabel = 'Ethereum Mainnet';
const String kEvmNetworkSepoliaDashboardChipLabel =
    'Ethereum Sepolia Testnet';


String compileTimeDashboardChipLabel() {
  return compileTimeEffectiveMainnetIsDefault()
      ? kEvmNetworkMainnetDashboardChipLabel
      : kEvmNetworkSepoliaDashboardChipLabel;
}


const String kEvmNetworkMainnetSendBlockedCopy =
    'Sending is not enabled yet.';


const String kEvmNetworkMainnetReceiveRealFundsHeadline =
    'Only send ETH on Ethereum Mainnet to this address.';


const bool kCryptoWalletEngineMainnetErc20ReceiveEnabled =
    bool.fromEnvironment(
  'CRYPTO_WALLET_ENGINE_MAINNET_ERC20_RECEIVE_ENABLED',
  defaultValue: false,
);


const String kEvmNetworkMainnetTokenSendBlockedCopy =
    'Sending is not enabled yet.';


const String kEvmNetworkMainnetTokenReceiveRealFundsHeadline =
    'Only send {token} on Ethereum Mainnet to this address.';


const String kEvmNetworkMainnetTokenSharedAddressNote =
    'Shares your Ethereum wallet address.';


const String kEvmNetworkMainnetTokenGasNote =
    'Sending tokens later requires ETH for gas.';


const bool kCryptoWalletEngineMainnetSendEnabled = bool.fromEnvironment(
  'CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED',
  defaultValue: false,
);


const String kEvmNetworkMainnetSendRealFundsHeadline =
    'This sends real ETH on Ethereum Mainnet. Transactions cannot '
    'be reversed.';


const String kEvmNetworkMainnetTokenSendRealFundsHeadline =
    'This sends real {token} on Ethereum Mainnet. Gas is paid in '
    'ETH. Mainnet transactions cannot be reversed.';


String evmNetworkDisplayName(String? networkId) {
  if (networkId == null) return 'Unknown';
  return kEvmNetworkDisplayName[networkId] ?? networkId;
}


bool evmNetworkIsTestnet(String? networkId) {
  if (networkId == null) return false;
  return kEvmNetworkIsTestnet[networkId] ?? false;
}


bool isKnownEvmNetwork(String? networkId) {
  if (networkId == null) return false;
  return kAllEvmNetworks.contains(networkId);
}
