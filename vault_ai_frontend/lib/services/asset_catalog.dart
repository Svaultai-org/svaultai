import 'evm_networks.dart';

const kAssetCatalogSchema = 'svaultai_asset_catalog_v1';
const kPaxgAssetId = 'PAXG_ERC20';
const kPaxgContractAddress = '0x45804880De22913dAFE09f4980848ECE6EcbAf78';
const kPaxgTransferNote = 'Issuer rules may pause or freeze transfers. '
    'Token-level fees can reduce the received amount; ETH pays network fees.';

enum VaultAssetCategory {
  cryptocurrency('cryptocurrency', 'Cryptocurrency'),
  digitalGold('digital_gold', 'Digital Gold'),
  digitalSilver('digital_silver', 'Digital Silver'),
  realEstate('tokenized_real_estate', 'Tokenized Real Estate'),
  gemstones('tokenized_diamonds_gemstones', 'Tokenized Diamonds and Gemstones'),
  artwork('tokenized_artwork', 'Tokenized Artwork'),
  collectibles(
      'tokenized_watches_collectibles', 'Tokenized Watches and Collectibles'),
  equipment('tokenized_vehicles_equipment', 'Tokenized Vehicles and Equipment');

  const VaultAssetCategory(this.id, this.label);
  final String id;
  final String label;
}

/// Closed token definitions, not arbitrary contracts supplied by the server.
/// Existing USDT/USDC network configuration stays in the current wallet engine.
class Erc20AssetSpec {
  const Erc20AssetSpec._(this.id, this.symbol, this.decimals);
  final String id;
  final String symbol;
  final int decimals;
}

const _erc20Specs = <String, Erc20AssetSpec>{
  'USDT_ERC20': Erc20AssetSpec._('USDT_ERC20', 'USDT', 6),
  'USDC_ERC20': Erc20AssetSpec._('USDC_ERC20', 'USDC', 6),
  kPaxgAssetId: Erc20AssetSpec._(kPaxgAssetId, 'PAXG', 18),
};

Erc20AssetSpec? erc20AssetSpec(String asset) => _erc20Specs[asset];
String walletAssetSymbol(String asset) =>
    erc20AssetSpec(asset)?.symbol ?? asset;

/// Integer-only conversion. Never rounds or truncates a transfer amount.
BigInt parseAssetBaseUnits(String amount, int decimals) {
  if (decimals < 0 ||
      decimals > 18 ||
      !RegExp(r'^(?:\d+(?:\.\d*)?|\.\d+)$').hasMatch(amount)) {
    throw const FormatException('Invalid token amount');
  }
  final parts = amount.split('.');
  final fraction = parts.length == 2 ? parts[1] : '';
  if (fraction.length > decimals) {
    throw const FormatException('Token amount exceeds supported precision');
  }
  final base = (parts[0].isEmpty ? BigInt.zero : BigInt.parse(parts[0])) *
      BigInt.from(10).pow(decimals);
  final result = base +
      (fraction.isEmpty
          ? BigInt.zero
          : BigInt.parse(fraction.padRight(decimals, '0')));
  if (result >= (BigInt.one << 256)) {
    throw const FormatException('Token amount exceeds transfer range');
  }
  return result;
}

/// Constructed only after the catalog matches the complete pinned token tuple.
/// The server controls availability, never the contract or precision we sign.
class RegisteredVaultAsset {
  const RegisteredVaultAsset._({
    required this.balanceEnabled,
    required this.receiveEnabled,
    required this.sendEnabled,
    required this.activityConnected,
    required this.transferNote,
    required this.verificationSource,
  });
  String get id => kPaxgAssetId;
  String get symbol => 'PAXG';
  String get name => 'PAX Gold';
  String get network => kEvmNetworkEthereumMainnet;
  int get chainId => 1;
  int get decimals => 18;
  String get contractAddress => kPaxgContractAddress;
  final bool balanceEnabled;
  final bool receiveEnabled;
  final bool sendEnabled;
  final bool activityConnected;
  final String transferNote;
  final String? verificationSource;

  bool matches(String asset, String network) =>
      asset == id && network == this.network;

  bool validatesBalance(Map<String, dynamic> balance, String address) {
    try {
      final amount = balance['availableAmount'];
      final base = balance['baseUnits'];
      return balance['balanceStatus'] == 'available' &&
          balance['asset'] == id &&
          balance['networkId'] == network &&
          balance['chainId'] == chainId &&
          balance['decimals'] == decimals &&
          balance['unit'] == symbol &&
          amount is String &&
          base is String &&
          (balance['publicAddress'] as String?)?.toLowerCase() ==
              address.toLowerCase() &&
          (balance['tokenContract'] as String?)?.toLowerCase() ==
              contractAddress.toLowerCase() &&
          BigInt.tryParse(base) == parseAssetBaseUnits(amount, decimals);
    } catch (_) {
      return false;
    }
  }

  /// Binding the reviewed transfer to its exact recipient, amount and issuer
  /// contract happens before any encrypted key is fetched or decrypted.
  bool validatesTransferDraft(
    Map<String, dynamic> draft, {
    required String fromAddress,
    required String destination,
    required String amount,
  }) {
    try {
      final baseUnits = parseAssetBaseUnits(amount, decimals);
      if (baseUnits <= BigInt.zero) return false;
      final recipient = destination.toLowerCase();
      if (!RegExp(r'^0x[0-9a-f]{40}$').hasMatch(recipient)) return false;
      final expectedData = '0xa9059cbb'
          '${recipient.substring(2).padLeft(64, '0')}'
          '${baseUnits.toRadixString(16).padLeft(64, '0')}';
      return draft['chainId'] == chainId &&
          (draft['fromAddress'] as String?)?.toLowerCase() ==
              fromAddress.toLowerCase() &&
          (draft['destinationAddress'] as String?)?.toLowerCase() ==
              recipient &&
          (draft['transactionTo'] as String?)?.toLowerCase() ==
              contractAddress.toLowerCase() &&
          (draft['dataHex'] as String?)?.toLowerCase() == expectedData &&
          draft['unit'] == symbol &&
          BigInt.tryParse('${draft['transactionValueWei']}') == BigInt.zero &&
          parseAssetBaseUnits('${draft['amount']}', decimals) == baseUnits &&
          (draft['amountBaseUnits'] == null ||
              BigInt.tryParse('${draft['amountBaseUnits']}') == baseUnits) &&
          (draft['decimals'] == null || draft['decimals'] == decimals);
    } catch (_) {
      return false;
    }
  }
}

class VaultAssetCatalog {
  const VaultAssetCatalog._(this.digitalGold, this.digitalGoldAvailable);
  const VaultAssetCatalog.unavailable()
      : digitalGold = null,
        digitalGoldAvailable = false;
  final RegisteredVaultAsset? digitalGold;
  final bool digitalGoldAvailable;

  factory VaultAssetCatalog.fromJson(Map<String, dynamic> raw) {
    if (raw['schema'] != kAssetCatalogSchema ||
        raw['categories'] is! List ||
        raw['assets'] is! List) {
      return const VaultAssetCatalog.unavailable();
    }
    final categories = (raw['categories'] as List)
        .whereType<Map>()
        .where((v) => v['id'] == VaultAssetCategory.digitalGold.id)
        .toList();
    final candidates = (raw['assets'] as List)
        .whereType<Map>()
        .where((v) => v['id'] == kPaxgAssetId)
        .toList();
    if (categories.length != 1 || candidates.length != 1) {
      return const VaultAssetCatalog.unavailable();
    }
    final token = candidates.single;
    if (token['verified'] != true ||
        token['category'] != VaultAssetCategory.digitalGold.id ||
        token['symbol'] != 'PAXG' ||
        token['name'] != 'PAX Gold' ||
        token['standard'] != 'ERC20' ||
        token['network'] != kEvmNetworkEthereumMainnet ||
        token['chainId'] != 1 ||
        token['decimals'] != 18 ||
        token['contractAddress'] is! String ||
        (token['contractAddress'] as String).toLowerCase() !=
            kPaxgContractAddress.toLowerCase()) {
      return const VaultAssetCatalog.unavailable();
    }
    // URLs are informational only and limited to the issuer's HTTPS site.
    final source = token['verificationSource'];
    final uri = source is String ? Uri.tryParse(source) : null;
    final safeSource = uri != null &&
            uri.scheme == 'https' &&
            (uri.host == 'paxos.com' ||
                uri.host.endsWith('.paxos.com') ||
                (uri.host == 'github.com' &&
                    (uri.path == '/paxosglobal/paxos-gold-contract' ||
                        uri.path.startsWith(
                            '/paxosglobal/paxos-gold-contract/')))) &&
            uri.userInfo.isEmpty
        ? uri.toString()
        : null;
    final asset = RegisteredVaultAsset._(
      balanceEnabled: token['balanceEnabled'] == true,
      receiveEnabled: token['receiveEnabled'] == true,
      sendEnabled: token['sendEnabled'] == true,
      activityConnected: token['activityConnected'] == true,
      transferNote: kPaxgTransferNote,
      verificationSource: safeSource,
    );
    final available = categories.single['available'] == true &&
        asset.balanceEnabled &&
        asset.receiveEnabled;
    return VaultAssetCatalog._(asset, available);
  }
}
