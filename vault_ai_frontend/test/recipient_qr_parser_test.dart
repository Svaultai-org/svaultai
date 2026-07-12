// 2026-07-13: pure-Dart tests for `RecipientQrParser`.
//
// Locks in the accepted / rejected QR shapes per network, plus the
// universal safety rejections (seed phrase / private key). If any
// of these regress the Send flow could be tricked into populating
// the destination field with something dangerous.

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/recipient_qr_parser.dart';


// Known-valid addresses (also used elsewhere in the test tree).
const String _kEthAddr = '0xffffffffffffffffffffffffffffffffffffffff';
const String _kEthAddr2 = '0x1111111111111111111111111111111111111111';
const String _kSolAddr = 'So11111111111111111111111111111111111111112';
const String _kTronAddr = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t';


void main() {
  group('RecipientQrParser — Ethereum', () {
    test('plain 0x address passes', () {
      final r = RecipientQrParser.parse(
        raw: _kEthAddr,
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isTrue);
      expect(r.address, _kEthAddr);
    });

    test('ethereum: URI without chain hint passes', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:$_kEthAddr',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isTrue);
      expect(r.address, _kEthAddr);
    });

    test('ethereum: URI with matching @chainId passes', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:$_kEthAddr@1',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isTrue);
      expect(r.address, _kEthAddr);
    });

    test('ethereum: URI with WRONG @chainId is rejected', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:$_kEthAddr@137', // Polygon
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.wrongChainId);
    });

    test('ethereum: URI with ?value=... does NOT populate amount, '
        'but does populate address', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:$_kEthAddr?value=2000000000000000000',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isTrue);
      expect(r.address, _kEthAddr);
    });

    test('EIP-681 pay-<token>/transfer URI is REJECTED so a token '
        'contract cannot be treated as the recipient', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:pay-$_kEthAddr@1/transfer'
             '?address=$_kEthAddr2&uint256=1000000',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.ambiguousToken);
    });

    test('URI with `data=` (arbitrary contract call) is rejected', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:$_kEthAddr?data=0xdeadbeef',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.unsupportedPayload);
    });

    test('URI with contract function segment `/transfer` is '
        'rejected', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:$_kEthAddr/transfer?to=$_kEthAddr2',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.unsupportedPayload);
    });

    test('malformed 0x string is rejected', () {
      final r = RecipientQrParser.parse(
        raw: '0xNOTHEX',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason,
          RecipientQrRejectReason.invalidEthereumAddress);
    });

    test('bare TRON address on ETH screen is rejected (cross-'
        'network)', () {
      final r = RecipientQrParser.parse(
        raw: _kTronAddr,
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.crossNetwork);
    });

    test('solana: URI on ETH screen is rejected (cross-network)', () {
      final r = RecipientQrParser.parse(
        raw: 'solana:$_kSolAddr',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.crossNetwork);
    });

    test('32-byte private key (0x + 64 hex) on ETH screen is '
        'REJECTED, never populated as address', () {
      final r = RecipientQrParser.parse(
        raw: '0x' + 'ab' * 32,
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.privateKeyRejected);
    });

    test('24-word mnemonic is REJECTED', () {
      const seed = 'abandon abandon abandon abandon abandon abandon '
          'abandon abandon abandon abandon abandon abandon '
          'abandon abandon abandon abandon abandon abandon '
          'abandon abandon abandon abandon abandon art';
      final r = RecipientQrParser.parse(
        raw: seed,
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.seedPhraseRejected);
    });

    test('empty QR is rejected', () {
      final r = RecipientQrParser.parse(
        raw: '',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.empty);
    });

    test('unknown chain hint (@abc) is rejected', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:$_kEthAddr@nope',
        network: RecipientNetwork.ethereum,
        expectedChainId: 1,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.unsupportedPayload);
    });
  });


  group('RecipientQrParser — Solana', () {
    test('plain Solana address passes', () {
      final r = RecipientQrParser.parse(
        raw: _kSolAddr,
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isTrue);
      expect(r.address, _kSolAddr);
    });

    test('solana: URI passes and strips ?amount=... query', () {
      final r = RecipientQrParser.parse(
        raw: 'solana:$_kSolAddr?amount=0.5',
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isTrue);
      expect(r.address, _kSolAddr);
    });

    test('solana: URI with program segment (/) is rejected', () {
      final r = RecipientQrParser.parse(
        raw: 'solana:$_kSolAddr/transfer?to=$_kSolAddr',
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.unsupportedPayload);
    });

    test('Ethereum address on Solana screen is rejected', () {
      final r = RecipientQrParser.parse(
        raw: _kEthAddr,
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.crossNetwork);
    });

    test('ethereum: URI on Solana screen is rejected', () {
      final r = RecipientQrParser.parse(
        raw: 'ethereum:$_kEthAddr',
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.crossNetwork);
    });

    test('TRON address on Solana screen is rejected', () {
      final r = RecipientQrParser.parse(
        raw: _kTronAddr,
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.crossNetwork);
    });

    test('malformed Solana base58 rejected as invalid address', () {
      final r = RecipientQrParser.parse(
        raw: 'notavalidsolanaaddress',
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.invalidSolanaAddress);
    });

    test('long private-key-shape base58 (>44 chars) is rejected as '
        'private key', () {
      final r = RecipientQrParser.parse(
        raw: '1' * 88,
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.privateKeyRejected);
    });

    test('mnemonic seed on Solana screen is rejected', () {
      const seed = 'abandon abandon abandon abandon abandon abandon '
          'abandon abandon abandon abandon abandon art';
      final r = RecipientQrParser.parse(
        raw: seed,
        network: RecipientNetwork.solana,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.seedPhraseRejected);
    });
  });


  group('RecipientQrParser — TRON', () {
    test('plain TRON address passes', () {
      final r = RecipientQrParser.parse(
        raw: _kTronAddr,
        network: RecipientNetwork.tron,
      );
      expect(r.ok, isTrue);
      expect(r.address, _kTronAddr);
    });

    test('tron: URI passes and strips ?amount=... query', () {
      final r = RecipientQrParser.parse(
        raw: 'tron:$_kTronAddr?amount=42',
        network: RecipientNetwork.tron,
      );
      expect(r.ok, isTrue);
      expect(r.address, _kTronAddr);
    });

    test('malformed TRON address is rejected', () {
      final r = RecipientQrParser.parse(
        raw: 'TR7NOTAVALIDCHECKSUM_______________',
        network: RecipientNetwork.tron,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.invalidTronAddress);
    });

    test('Ethereum address on TRON screen is rejected', () {
      final r = RecipientQrParser.parse(
        raw: _kEthAddr,
        network: RecipientNetwork.tron,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.crossNetwork);
    });

    test('solana: URI on TRON screen is rejected', () {
      final r = RecipientQrParser.parse(
        raw: 'solana:$_kSolAddr',
        network: RecipientNetwork.tron,
      );
      expect(r.ok, isFalse);
      expect(r.rejectReason, RecipientQrRejectReason.crossNetwork);
    });

    test('mnemonic seed on TRON screen is rejected', () {
      const seed = 'legal winner thank year wave sausage worth '
          'useful legal winner thank yellow';
      final r = RecipientQrParser.parse(
        raw: seed,
        network: RecipientNetwork.tron,
      );
      expect(r.ok, isFalse);
      expect(
          r.rejectReason, RecipientQrRejectReason.seedPhraseRejected);
    });
  });
}
