// Builds a view-only scan request from an address-verified, locally opened
// Wallet V2 backup. No spend key is passed to the scanner or server.

import 'dart:convert';
import 'dart:typed_data';

import 'monero_scanner.dart';
import 'wallet_v2_secret_validation.dart';

Future<MoneroScannerInput> moneroScannerInputFromVerifiedV2Secret({
  required String secret,
  required String publicAddress,
}) async {
  if (!await walletV2SecretMatchesAddress(
    'monero',
    secret,
    publicAddress,
  )) {
    throw const FormatException('Monero backup does not match this address');
  }
  final decoded = jsonDecode(secret);
  if (decoded is! Map<String, dynamic> ||
      decoded['schema'] != 'monero_wallet_secret_v1') {
    throw const FormatException('Invalid Monero wallet backup');
  }
  final restoreHeight = decoded['restoreHeight'];
  if (restoreHeight is! int || restoreHeight < 0 || restoreHeight > 100000000) {
    throw const FormatException('Invalid Monero restore height');
  }
  final privateViewKey = _decodeHex32(decoded['privateViewKeyHex']);
  final publicSpendKey = _decodeHex32(decoded['publicSpendKeyHex']);
  if (privateViewKey == null || publicSpendKey == null) {
    privateViewKey?.fillRange(0, privateViewKey.length, 0);
    throw const FormatException('Invalid Monero scan keys');
  }
  return MoneroScannerInput(
    privateViewKey: privateViewKey,
    publicSpendKey: publicSpendKey,
    publicAddress: publicAddress,
    restoreHeight: restoreHeight,
  );
}

Uint8List? _decodeHex32(Object? value) {
  if (value is! String || !RegExp(r'^[0-9a-fA-F]{64}$').hasMatch(value)) {
    return null;
  }
  return Uint8List.fromList([
    for (var i = 0; i < 64; i += 2)
      int.parse(value.substring(i, i + 2), radix: 16),
  ]);
}
