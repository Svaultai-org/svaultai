

import 'evm_networks.dart';

const String kCryptoWalletFeaturesSchemaV1 = 'crypto_wallet_features_v1';

const String kSolanaNetworkId = 'solana_mainnet';
const String kSolanaNetworkLabel = 'Solana';
const String kSolanaAssetTicker = 'SOL';

const String kTronNetworkId = 'tron_mainnet';
const String kTronNetworkLabel = 'TRON';
const String kTronAssetTicker = 'USDT_TRC20';
const String kTronTokenStandard = 'TRC20';
const String kTronTokenUnit = 'USDT';

const String kMoneroNetworkId = 'monero_mainnet';
const String kMoneroNetworkLabel = 'Monero';
const String kMoneroAssetTicker = 'XMR';


class CryptoWalletFeatures {
  final bool walletEngineEnabled;
  final bool sepoliaReceiveEnabled;
  final bool sepoliaSendEnabled;
  final bool mainnetReceiveEnabled;
  final bool mainnetErc20ReceiveEnabled;
  final bool mainnetSendEnabled;
  final bool mainnetSendPaused;
  final String defaultNetwork;
  final bool defaultNetworkConfigValid;
  final bool solanaEnabled;
  final bool solanaReceiveEnabled;
  final bool solanaBalanceEnabled;
  final bool solanaSendEnabled;
  final bool solanaSendPaused;
  final bool solanaActivityConnected;
  final bool solanaStatusReady;
  final bool solanaFeeReady;
  final bool tronEnabled;
  final bool tronReceiveEnabled;
  final bool tronBalanceEnabled;
  final bool tronSendEnabled;
  final bool tronSendPaused;
  final bool tronActivityConnected;
  final bool tronUsdtContractConfigured;
  final bool xmrEnabled;
  final bool xmrReceiveEnabled;
  final bool xmrBalanceEnabled;
  final bool xmrSendEnabled;
  final bool xmrActivityConnected;
  final String xmrScannerMode;
  final bool xmrClientScannerSupported;
  final bool xmrBackendScannerEnabled;
  final List<String> supportedNetworks;
  final Map<String, List<String>> supportedAssetsByNetwork;

  const CryptoWalletFeatures({
    required this.walletEngineEnabled,
    required this.sepoliaReceiveEnabled,
    required this.sepoliaSendEnabled,
    required this.mainnetReceiveEnabled,
    required this.mainnetErc20ReceiveEnabled,
    required this.mainnetSendEnabled,
    required this.mainnetSendPaused,
    required this.defaultNetwork,
    required this.defaultNetworkConfigValid,
    required this.solanaEnabled,
    required this.solanaReceiveEnabled,
    required this.solanaBalanceEnabled,
    required this.solanaSendEnabled,
    required this.solanaSendPaused,
    required this.solanaActivityConnected,
    required this.solanaStatusReady,
    required this.solanaFeeReady,
    required this.tronEnabled,
    required this.tronReceiveEnabled,
    required this.tronBalanceEnabled,
    required this.tronSendEnabled,
    required this.tronSendPaused,
    required this.tronActivityConnected,
    required this.tronUsdtContractConfigured,
    required this.xmrEnabled,
    required this.xmrReceiveEnabled,
    required this.xmrBalanceEnabled,
    required this.xmrSendEnabled,
    required this.xmrActivityConnected,
    required this.xmrScannerMode,
    required this.xmrClientScannerSupported,
    required this.xmrBackendScannerEnabled,
    required this.supportedNetworks,
    required this.supportedAssetsByNetwork,
  });


  const CryptoWalletFeatures.unknown()
      : walletEngineEnabled = false,
        sepoliaReceiveEnabled = false,
        sepoliaSendEnabled = false,
        mainnetReceiveEnabled = false,
        mainnetErc20ReceiveEnabled = false,
        mainnetSendEnabled = false,
        mainnetSendPaused = false,
        defaultNetwork = '',
        defaultNetworkConfigValid = false,
        solanaEnabled = false,
        solanaReceiveEnabled = false,
        solanaBalanceEnabled = false,
        solanaSendEnabled = false,
        solanaSendPaused = false,
        solanaActivityConnected = false,
        solanaStatusReady = false,
        solanaFeeReady = false,
        tronEnabled = false,
        tronReceiveEnabled = false,
        tronBalanceEnabled = false,
        tronSendEnabled = false,
        tronSendPaused = false,
        tronActivityConnected = false,
        tronUsdtContractConfigured = false,
        xmrEnabled = false,
        xmrReceiveEnabled = false,
        xmrBalanceEnabled = false,
        xmrSendEnabled = false,
        xmrActivityConnected = false,
        xmrScannerMode = 'none',
        xmrClientScannerSupported = false,
        xmrBackendScannerEnabled = false,
        supportedNetworks = const [],
        supportedAssetsByNetwork = const {};

  factory CryptoWalletFeatures.fromBackend(Map<String, dynamic> raw) {
    bool b(String k) => (raw[k] as bool?) ?? false;
    String s(String k) => (raw[k] as String?) ?? '';
    final nets = (raw['supportedNetworks'] as List?)
            ?.map((e) => e.toString())
            .toList() ??
        const <String>[];
    final assets = <String, List<String>>{};
    final rawAssets = raw['supportedAssetsByNetwork'];
    if (rawAssets is Map) {
      for (final entry in rawAssets.entries) {
        final key = entry.key.toString();
        final value = entry.value;
        if (value is List) {
          assets[key] = value.map((e) => e.toString()).toList();
        }
      }
    }
    return CryptoWalletFeatures(
      walletEngineEnabled:      b('walletEngineEnabled'),
      sepoliaReceiveEnabled:    b('sepoliaReceiveEnabled'),
      sepoliaSendEnabled:       b('sepoliaSendEnabled'),
      mainnetReceiveEnabled:    b('mainnetReceiveEnabled'),
      mainnetErc20ReceiveEnabled: b('mainnetErc20ReceiveEnabled'),
      mainnetSendEnabled:       b('mainnetSendEnabled'),
      mainnetSendPaused:        b('mainnetSendPaused'),
      defaultNetwork:           s('defaultNetwork'),
      defaultNetworkConfigValid: b('defaultNetworkConfigValid'),
      solanaEnabled:            b('solanaEnabled'),
      solanaReceiveEnabled:     b('solanaReceiveEnabled'),
      solanaBalanceEnabled:     b('solanaBalanceEnabled'),
      solanaSendEnabled:        b('solanaSendEnabled'),
      solanaSendPaused:         b('solanaSendPaused'),
      solanaActivityConnected:  b('solanaActivityConnected'),
      solanaStatusReady:        b('solanaStatusReady'),
      solanaFeeReady:           b('solanaFeeReady'),
      tronEnabled:              b('tronEnabled'),
      tronReceiveEnabled:       b('tronReceiveEnabled'),
      tronBalanceEnabled:       b('tronBalanceEnabled'),
      tronSendEnabled:          b('tronSendEnabled'),
      tronSendPaused:           b('tronSendPaused'),
      tronActivityConnected:    b('tronActivityConnected'),
      tronUsdtContractConfigured: b('tronUsdtContractConfigured'),
      xmrEnabled:               b('xmrEnabled'),
      xmrReceiveEnabled:        b('xmrReceiveEnabled'),
      xmrBalanceEnabled:        b('xmrBalanceEnabled'),
      xmrSendEnabled:           b('xmrSendEnabled'),
      xmrActivityConnected:     b('xmrActivityConnected'),
      xmrScannerMode:           s('xmrScannerMode').isEmpty
                                    ? 'none' : s('xmrScannerMode'),
      xmrClientScannerSupported: b('xmrClientScannerSupported'),
      xmrBackendScannerEnabled: b('xmrBackendScannerEnabled'),
      supportedNetworks:        nets,
      supportedAssetsByNetwork: assets,
    );
  }


  bool get effectiveMainnetReceiveEnabled =>
      mainnetReceiveEnabled
      && kCryptoWalletEngineMainnetReceiveEnabled;

  bool get effectiveMainnetErc20ReceiveEnabled =>
      mainnetErc20ReceiveEnabled
      && kCryptoWalletEngineMainnetErc20ReceiveEnabled;

  bool get effectiveMainnetSendEnabled =>
      mainnetSendEnabled
      && kCryptoWalletEngineMainnetSendEnabled
      && !mainnetSendPaused;


  String get effectiveDefaultNetwork => resolveEffectiveDefaultNetwork(
        backendDefaultNetwork: defaultNetwork,
        backendDefaultNetworkConfigValid: defaultNetworkConfigValid,
      );


  bool get isMainnetDefault =>
      effectiveDefaultNetwork == kEvmNetworkEthereumMainnet;




  bool get mainnetActive =>
      isMainnetDefault
      && effectiveMainnetReceiveEnabled
      && effectiveMainnetErc20ReceiveEnabled;
}
