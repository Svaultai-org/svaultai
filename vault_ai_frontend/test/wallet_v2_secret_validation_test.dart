import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/ethereum_transaction.dart';
import 'package:vault_ai_frontend/services/ethereum_wallet.dart';
import 'package:vault_ai_frontend/services/monero_crypto_primitives.dart';
import 'package:vault_ai_frontend/services/monero_ed25519.dart';
import 'package:vault_ai_frontend/services/solana_transaction.dart';
import 'package:vault_ai_frontend/services/solana_wallet.dart';
import 'package:vault_ai_frontend/services/tron_transaction.dart';
import 'package:vault_ai_frontend/services/tron_wallet.dart';
import 'package:vault_ai_frontend/services/wallet_v2_secret_validation.dart';

String hex(List<int> bytes) =>
    bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();

void main() {
  const syntheticKey =
      '0000000000000000000000000000000000000000000000000000000000000001';

  test('EVM V2 secret validates and signs only a local zero-value fixture',
      () async {
    final address = deriveEthereumAddressFromPrivateKeyHex(syntheticKey);
    expect(await walletV2SecretMatchesAddress('evm', syntheticKey, address),
        isTrue);
    expect(
        await walletV2SecretMatchesAddress(
            'evm', syntheticKey, '0x0000000000000000000000000000000000000002'),
        isFalse);
    final signed = signLegacyEthTransaction(
      nonce: BigInt.zero,
      gasPrice: BigInt.one,
      gasLimit: BigInt.from(21000),
      toAddress: '0x0000000000000000000000000000000000000002',
      valueWei: BigInt.zero,
      dataHex: '',
      chainId: 1,
      privateKeyHex: syntheticKey,
    );
    expect(signed, startsWith('0x'));
  });

  test('TRON V2 JSON validates and signs only a local synthetic digest',
      () async {
    final address = deriveTronAddressFromPrivateKeyHex(syntheticKey);
    final secret = jsonEncode({
      'schema': 'tron_secret_v1',
      'keyOrigin': 'generated_client_side',
      'privateKeyHex': syntheticKey,
    });
    expect(await walletV2SecretMatchesAddress('tron', secret, address), isTrue);
    expect(
        await walletV2SecretMatchesAddress('tron', secret, 'Twrong'), isFalse);
    final signature = signTronTxIDHex(
      txIDHex: List<String>.filled(32, '11').join(),
      privateKeyHex: syntheticKey,
    );
    expect(signature.length, greaterThan(100));
  });

  test('Solana V2 seed/public pair is rederived before local signing',
      () async {
    final wallet = await generateSolanaWallet();
    final secret = jsonEncode({
      'schema': 'solana_secret_v1',
      'keyOrigin': 'generated_client_side',
      'secretKeyBase58': wallet.secretKeyBase58,
    });
    expect(
        await walletV2SecretMatchesAddress(
            'solana', secret, wallet.publicAddress),
        isTrue);
    expect(
        await walletV2SecretMatchesAddress('solana', secret, 'wrong-address'),
        isFalse);
    final signed = await signSolanaMessageBytes(
      messageBytes: Uint8List.fromList([1, 2, 3]),
      ed25519Seed32: wallet.secretKeyBytes.sublist(0, 32),
    );
    expect(signed, hasLength(64));
    wipeSecretKey(wallet.secretKeyBytes);
  });

  test('Monero V2 private/public keys reconstruct the exact address', () async {
    final spend = scRed32(Uint8List.fromList(List<int>.filled(32, 7)));
    final view = moneroDerivePrivateViewKey(spend);
    final publicSpend = moneroDerivePublicKey(spend);
    final publicView = moneroDerivePublicKey(view);
    final address = buildMoneroPrimaryAddress(
      publicSpendKey: publicSpend,
      publicViewKey: publicView,
    );
    final secret = jsonEncode({
      'schema': 'monero_wallet_secret_v1',
      'privateSpendKeyHex': hex(spend),
      'privateViewKeyHex': hex(view),
      'publicSpendKeyHex': hex(publicSpend),
      'publicViewKeyHex': hex(publicView),
      'restoreHeight': 0,
    });
    expect(
        await walletV2SecretMatchesAddress('monero', secret, address), isTrue);
    expect(
        await walletV2SecretMatchesAddress('monero', secret, 'wrong-address'),
        isFalse);
    for (final bytes in [spend, view, publicSpend, publicView]) {
      bytes.fillRange(0, bytes.length, 0);
    }
  });
}
