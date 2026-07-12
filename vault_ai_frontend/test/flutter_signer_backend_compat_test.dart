// 2026-07-13: Flutter <-> Python signed-transaction compat lock.
//
// The mainnet broadcast route on the Python backend decodes the
// signed transaction with `evm_signed_tx_verify.decode_and_recover`
// and compares every field to the drafted values. If the Dart
// signer's output ever drifts from what the Python decoder expects,
// EVERY mainnet send would fail with `decode_or_recover_failed`.
//
// This test signs a specific canonical set of legacy tx inputs
// using `signLegacyEthTransaction` and asserts the output hex is
// BYTE-IDENTICAL to the reference vector at
// `vault_ai_backend/test_flutter_signer_compat_2026_07_13.py`.
//
// If either signer changes its output (e.g. a pointycastle bump
// alters ECDSA k-derivation, a private-key normalization tweaks
// the s-value, or an eth-account upgrade changes byte encoding),
// both tests fail — surfacing the incompatibility BEFORE it
// reaches production mainnet broadcast.

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/ethereum_transaction.dart';


const String _kCanonicalPrivKeyHex =
    '0000000000000000000000000000000000000000000000000000000000000001';
const String _kCanonicalTo =
    '0x1111111111111111111111111111111111111111';
const int    _kCanonicalNonce      = 42;
const int    _kCanonicalGasPrice   = 30000000000;
const int    _kCanonicalGasLimit   = 21000;
const int    _kCanonicalValueWei   = 1000000000000000; // 0.001 ETH
const String _kCanonicalDataHex    = '';
const int    _kCanonicalChainId    = 1;




const String _kCanonicalSignedHex =
    '0xf86b2a8506fc23ac0082520894'
    '1111111111111111111111111111111111111111'
    '87038d7ea4c680008026'
    'a039f4ba24838a18898f1585c090b3fe757ca26777469ff3f2b1051574528ebe9f'
    'a017d121ac8e32d562638af46baf25a8f97b72a3f1718ed0772509ffcddacc76e1';


void main() {
  group('Flutter signer <-> Python backend compat (2026-07-13)', () {

    test(
      'signLegacyEthTransaction produces the canonical mainnet '
      'reference hex the Python decoder locks in',
      () {
        final signed = signLegacyEthTransaction(
          nonce:         BigInt.from(_kCanonicalNonce),
          gasPrice:      BigInt.from(_kCanonicalGasPrice),
          gasLimit:      BigInt.from(_kCanonicalGasLimit),
          toAddress:     _kCanonicalTo,
          valueWei:      BigInt.from(_kCanonicalValueWei),
          dataHex:       _kCanonicalDataHex,
          chainId:       _kCanonicalChainId,
          privateKeyHex: _kCanonicalPrivKeyHex,
        );
        expect(
          signed.toLowerCase(),
          equals(_kCanonicalSignedHex.toLowerCase()),
          reason:
            'Dart signer output must match the reference vector '
            'the Python backend decoder locks in. If this fails, '
            'the Python backend WILL reject legitimate Flutter-'
            'signed mainnet transactions.',
        );
      },
    );


    test(
      'signLegacyEthTransaction is deterministic (RFC 6979)',
      () {
        String signOnce() => signLegacyEthTransaction(
          nonce:         BigInt.from(_kCanonicalNonce),
          gasPrice:      BigInt.from(_kCanonicalGasPrice),
          gasLimit:      BigInt.from(_kCanonicalGasLimit),
          toAddress:     _kCanonicalTo,
          valueWei:      BigInt.from(_kCanonicalValueWei),
          dataHex:       _kCanonicalDataHex,
          chainId:       _kCanonicalChainId,
          privateKeyHex: _kCanonicalPrivKeyHex,
        );
        expect(signOnce(), equals(signOnce()));
      },
    );
  });
}
