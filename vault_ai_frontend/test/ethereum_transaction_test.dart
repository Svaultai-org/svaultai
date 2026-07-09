

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/ethereum_transaction.dart';

void main() {
  group('ethereum_transaction slice 3', () {
    
    
    const pk =
        '0000000000000000000000000000000000000000000000000000000000000001';
    const toAddr = '0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf';
    const oneEthWei = 1000000000000000000;
    const twentyGwei = 20000000000;
    const sepoliaChainId = 11155111;

    String _signCanonical(BigInt nonce) {
      return signLegacyEthTransaction(
        nonce: nonce,
        gasPrice: BigInt.from(twentyGwei),
        gasLimit: BigInt.from(21000),
        toAddress: toAddr,
        valueWei: BigInt.from(oneEthWei),
        dataHex: '',
        chainId: sepoliaChainId,
        privateKeyHex: pk,
      );
    }

    test('ET1: deterministic — same inputs produce same signed tx', () {
      final a = _signCanonical(BigInt.zero);
      final b = _signCanonical(BigInt.zero);
      expect(a, equals(b));
    });

    test('ET2: signed transaction has RLP-plausible shape', () {
      final hex = _signCanonical(BigInt.zero);
      expect(hex.startsWith('0x'), isTrue);
      
      
      expect(hex.length, greaterThan(200));
      expect(hex.length, lessThan(400));
      
      expect((hex.length - 2) % 2 == 0, isTrue);
      
      
      expect(hex[2], equals('f'));
    });

    test('ET3: different nonce → different signed tx', () {
      final a = _signCanonical(BigInt.zero);
      final b = _signCanonical(BigInt.one);
      expect(a, isNot(equals(b)));
    });

    test('ET4: chainId enters the v computation per EIP-155', () {
      
      
      final sepolia = _signCanonical(BigInt.zero);
      final mainnet = signLegacyEthTransaction(
        nonce: BigInt.zero,
        gasPrice: BigInt.from(twentyGwei),
        gasLimit: BigInt.from(21000),
        toAddress: toAddr,
        valueWei: BigInt.from(oneEthWei),
        dataHex: '',
        chainId: 1,
        privateKeyHex: pk,
      );
      expect(sepolia, isNot(equals(mainnet)));
    });

    test('ET5: zero private key raises', () {
      expect(
        () => signLegacyEthTransaction(
          nonce: BigInt.zero,
          gasPrice: BigInt.from(twentyGwei),
          gasLimit: BigInt.from(21000),
          toAddress: toAddr,
          valueWei: BigInt.from(oneEthWei),
          dataHex: '',
          chainId: sepoliaChainId,
          privateKeyHex:
              '0000000000000000000000000000000000000000000000000000000000000000',
        ),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('ET5b: wrong-length private key raises', () {
      expect(
        () => signLegacyEthTransaction(
          nonce: BigInt.zero,
          gasPrice: BigInt.from(twentyGwei),
          gasLimit: BigInt.from(21000),
          toAddress: toAddr,
          valueWei: BigInt.from(oneEthWei),
          dataHex: '',
          chainId: sepoliaChainId,
          privateKeyHex: '01',
        ),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('ET5c: malformed to-address raises', () {
      expect(
        () => signLegacyEthTransaction(
          nonce: BigInt.zero,
          gasPrice: BigInt.from(twentyGwei),
          gasLimit: BigInt.from(21000),
          toAddress: 'not-an-address',
          valueWei: BigInt.from(oneEthWei),
          dataHex: '',
          chainId: sepoliaChainId,
          privateKeyHex: pk,
        ),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('ET5d: negative nonce raises', () {
      expect(
        () => signLegacyEthTransaction(
          nonce: BigInt.from(-1),
          gasPrice: BigInt.from(twentyGwei),
          gasLimit: BigInt.from(21000),
          toAddress: toAddr,
          valueWei: BigInt.from(oneEthWei),
          dataHex: '',
          chainId: sepoliaChainId,
          privateKeyHex: pk,
        ),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('ET5e: non-positive chainId raises', () {
      expect(
        () => signLegacyEthTransaction(
          nonce: BigInt.zero,
          gasPrice: BigInt.from(twentyGwei),
          gasLimit: BigInt.from(21000),
          toAddress: toAddr,
          valueWei: BigInt.from(oneEthWei),
          dataHex: '',
          chainId: 0,
          privateKeyHex: pk,
        ),
        throwsA(isA<ArgumentError>()),
      );
    });
  });
}
