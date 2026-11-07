// Verifies a locally opened wallet secret against its public address before
// migration, read, or signing. No secret leaves this client module.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'ethereum_wallet.dart';
import 'monero_crypto_primitives.dart';
import 'monero_ed25519.dart';
import 'solana_wallet.dart' as solana;
import 'tron_wallet.dart' as tron;

Future<bool> walletV2SecretMatchesAddress(
  String chain,
  String secret,
  String publicAddress,
) async {
  try {
    switch (chain) {
      case 'evm':
        return deriveEthereumAddressFromPrivateKeyHex(secret).toLowerCase() ==
            publicAddress.toLowerCase();
      case 'tron':
        final record = jsonDecode(secret);
        return record is Map<String, dynamic> &&
            record['schema'] == 'tron_secret_v1' &&
            record['privateKeyHex'] is String &&
            tron.deriveTronAddressFromPrivateKeyHex(
                  record['privateKeyHex'] as String,
                ) ==
                publicAddress;
      case 'solana':
        final record = jsonDecode(secret);
        if (record is! Map<String, dynamic> ||
            record['schema'] != 'solana_secret_v1' ||
            record['secretKeyBase58'] is! String) {
          return false;
        }
        final bytes = solana.base58Decode(record['secretKeyBase58'] as String);
        if (bytes == null || bytes.length != 64) return false;
        try {
          final pair = await Ed25519().newKeyPairFromSeed(bytes.sublist(0, 32));
          final derived = (await pair.extractPublicKey()).bytes;
          for (var i = 0; i < 32; i++) {
            if (derived[i] != bytes[i + 32]) return false;
          }
          return solana.base58Encode(Uint8List.fromList(derived)) ==
              publicAddress;
        } finally {
          solana.wipeSecretKey(bytes);
        }
      case 'monero':
        final record = jsonDecode(secret);
        if (record is! Map<String, dynamic> ||
            record['schema'] != 'monero_wallet_secret_v1') {
          return false;
        }
        final spend = _decodeHex32(record['privateSpendKeyHex']);
        final view = _decodeHex32(record['privateViewKeyHex']);
        final pubSpend = _decodeHex32(record['publicSpendKeyHex']);
        final pubView = _decodeHex32(record['publicViewKeyHex']);
        if (spend == null ||
            view == null ||
            pubSpend == null ||
            pubView == null) return false;
        try {
          if (!_sameBytes(moneroDerivePrivateViewKey(spend), view) ||
              !_sameBytes(moneroDerivePublicKey(spend), pubSpend) ||
              !_sameBytes(moneroDerivePublicKey(view), pubView)) {
            return false;
          }
          return buildMoneroPrimaryAddress(
                publicSpendKey: pubSpend,
                publicViewKey: pubView,
              ) ==
              publicAddress;
        } finally {
          for (final bytes in [spend, view, pubSpend, pubView]) {
            bytes.fillRange(0, bytes.length, 0);
          }
        }
      default:
        return false;
    }
  } catch (_) {
    return false;
  }
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

bool _sameBytes(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  var mismatch = 0;
  for (var i = 0; i < a.length; i++) {
    mismatch |= a[i] ^ b[i];
  }
  return mismatch == 0;
}
