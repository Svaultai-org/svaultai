import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/asset_catalog.dart';

Map<String, dynamic> catalogFixture(
        {Map<String, dynamic> tokenOverrides = const {}}) =>
    {
      'schema': kAssetCatalogSchema,
      'categories': [
        {'id': 'digital_gold', 'available': true}
      ],
      'assets': [
        {
          'id': kPaxgAssetId,
          'category': 'digital_gold',
          'symbol': 'PAXG',
          'name': 'PAX Gold',
          'standard': 'ERC20',
          'network': 'ethereum_mainnet',
          'chainId': 1,
          'contractAddress': kPaxgContractAddress,
          'decimals': 18,
          'verified': true,
          'balanceEnabled': true,
          'receiveEnabled': true,
          'sendEnabled': true,
          'activityConnected': true,
          'verificationSource':
              'https://github.com/paxosglobal/paxos-gold-contract',
          ...tokenOverrides,
        }
      ],
    };

Map<String, dynamic> paxgDraftFixture(
    {String amount = '0.000000000000000001'}) {
  const from = '0x1111111111111111111111111111111111111111';
  const to = '0x2222222222222222222222222222222222222222';
  final base = parseAssetBaseUnits(amount, 18);
  return {
    'fromAddress': from,
    'destinationAddress': to,
    'transactionTo': kPaxgContractAddress,
    'chainId': 1,
    'unit': 'PAXG',
    'amount': amount,
    'amountBaseUnits': '$base',
    'decimals': 18,
    'transactionValueWei': '0',
    'dataHex': '0xa9059cbb${to.substring(2).padLeft(64, '0')}'
        '${base.toRadixString(16).padLeft(64, '0')}',
  };
}

void main() {
  test('eight exact categories with no trading category', () {
    expect(VaultAssetCategory.values.map((v) => v.label), [
      'Cryptocurrency',
      'Digital Gold',
      'Digital Silver',
      'Tokenized Real Estate',
      'Tokenized Diamonds and Gemstones',
      'Tokenized Artwork',
      'Tokenized Watches and Collectibles',
      'Tokenized Vehicles and Equipment',
    ]);
  });

  test('verified pinned PAXG is mainnet ERC20 with 18 decimal precision', () {
    final catalog = VaultAssetCatalog.fromJson(catalogFixture());
    expect(catalog.digitalGoldAvailable, isTrue);
    final asset = catalog.digitalGold!;
    expect(asset.network, 'ethereum_mainnet');
    expect(asset.decimals, 18);
    expect(asset.contractAddress, kPaxgContractAddress);
    expect(asset.verificationSource,
        startsWith('https://github.com/paxosglobal/'));
    expect(asset.transferNote, contains('freeze'));
    expect(asset.transferNote, contains('reduce the received amount'));
  });

  test('server cannot replace the contract, symbol, chain, network or decimals',
      () {
    for (final mismatch in [
      {'contractAddress': '0x1111111111111111111111111111111111111111'},
      {'symbol': 'FAKE'},
      {'chainId': 11155111},
      {'network': 'ethereum_sepolia'},
      {'decimals': 6},
      {'standard': 'ERC721'},
      {'category': 'digital_silver'},
      {'chainId': '1'},
      {'id': 'UNKNOWN_ERC20'},
    ]) {
      final catalog =
          VaultAssetCatalog.fromJson(catalogFixture(tokenOverrides: mismatch));
      expect(catalog.digitalGoldAvailable, isFalse, reason: '$mismatch');
      expect(catalog.digitalGold, isNull, reason: '$mismatch');
    }
  });

  test('missing, malformed, duplicate or disabled catalogs fail closed', () {
    final duplicate = catalogFixture();
    (duplicate['assets'] as List).add((duplicate['assets'] as List).first);
    for (final raw in [
      <String, dynamic>{},
      {'schema': 'future'},
      duplicate,
      catalogFixture(tokenOverrides: {'balanceEnabled': false}),
      catalogFixture(tokenOverrides: {'receiveEnabled': false}),
      catalogFixture(tokenOverrides: {'balanceEnabled': 'true'}),
      catalogFixture(tokenOverrides: {'verified': false}),
    ]) {
      expect(VaultAssetCatalog.fromJson(raw).digitalGoldAvailable, isFalse);
    }
  });

  test(
      'send and activity are independent capabilities, not fake connected history',
      () {
    final asset = VaultAssetCatalog.fromJson(catalogFixture(tokenOverrides: {
      'sendEnabled': false,
      'activityConnected': false,
    })).digitalGold!;
    expect(asset.balanceEnabled, isTrue);
    expect(asset.sendEnabled, isFalse);
    expect(asset.activityConnected, isFalse);
  });

  test('unknown tokens are not granted default decimals or symbols', () {
    expect(erc20AssetSpec('UNKNOWN_ERC20'), isNull);
    expect(erc20AssetSpec('USDT_ERC20')!.decimals, 6);
    expect(erc20AssetSpec('USDC_ERC20')!.decimals, 6);
    expect(erc20AssetSpec(kPaxgAssetId)!.decimals, 18);
    expect(walletAssetSymbol(kPaxgAssetId), 'PAXG');
  });

  test(
      'verified token balance never defaults missing or wrong-network data to zero',
      () {
    final token = VaultAssetCatalog.fromJson(catalogFixture()).digitalGold!;
    const address = '0x1111111111111111111111111111111111111111';
    final balance = <String, dynamic>{
      'balanceStatus': 'available',
      'asset': kPaxgAssetId,
      'networkId': 'ethereum_mainnet',
      'chainId': 1,
      'decimals': 18,
      'unit': 'PAXG',
      'availableAmount': '0.000000000000000001',
      'baseUnits': '1',
      'publicAddress': address,
      'tokenContract': kPaxgContractAddress,
    };
    expect(token.validatesBalance(balance, address), isTrue);
    for (final mutation in [
      {'availableAmount': null},
      {'baseUnits': null},
      {'unit': 'USDC'},
      {'networkId': 'ethereum_sepolia'},
      {'chainId': 11155111},
      {'decimals': 6},
      {'availableAmount': '0'},
      {'tokenContract': address},
      {'publicAddress': '0x2222222222222222222222222222222222222222'},
    ]) {
      expect(
          token.validatesBalance({...balance, ...mutation}, address), isFalse,
          reason: '$mutation');
    }
    expect(
        token.validatesBalance(
            {...balance, 'baseUnits': '0', 'availableAmount': '0'}, address),
        isTrue);
  });

  test(
      'PAXG conversion preserves 18 decimals and rejects rounding or uint256 overflow',
      () {
    expect(parseAssetBaseUnits('0.000000000000000001', 18), BigInt.one);
    expect(parseAssetBaseUnits('1.234567890123456789', 18),
        BigInt.parse('1234567890123456789'));
    expect(parseAssetBaseUnits('.5', 6), BigInt.from(500000));
    expect(parseAssetBaseUnits('1.', 6), BigInt.from(1000000));
    for (final amount in [
      '0.0000000000000000001',
      '1e3',
      '-1',
      ' 1',
      '1.2.3'
    ]) {
      expect(() => parseAssetBaseUnits(amount, 18), throwsFormatException);
    }
    expect(() => parseAssetBaseUnits('${BigInt.one << 256}', 18),
        throwsFormatException);
    expect(() => parseAssetBaseUnits('0.0000001', 6), throwsFormatException);
  });

  test(
      'PAXG draft is bound to exact contract, network, debit amount and recipient',
      () {
    final asset = VaultAssetCatalog.fromJson(catalogFixture()).digitalGold!;
    bool validate(Map<String, dynamic> draft) =>
        asset.validatesTransferDraft(draft,
            fromAddress: '0x1111111111111111111111111111111111111111',
            destination: '0x2222222222222222222222222222222222222222',
            amount: '0.000000000000000001');
    expect(validate(paxgDraftFixture()), isTrue);
    for (final mutation in [
      {'transactionTo': '0x1111111111111111111111111111111111111111'},
      {'chainId': 11155111},
      {'unit': 'USDC'},
      {'amount': '1'},
      {'transactionValueWei': '1'},
      {'amountBaseUnits': '100'},
      {'decimals': 6},
      {'dataHex': '0xa9059cbb'},
      {'destinationAddress': '0x1111111111111111111111111111111111111111'},
      {'fromAddress': '0x2222222222222222222222222222222222222222'},
    ]) {
      expect(validate({...paxgDraftFixture(), ...mutation}), isFalse,
          reason: '$mutation');
    }
  });
}
