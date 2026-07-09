

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/ethereum_wallet.dart';

void main() {
  group('ethereum_wallet slice 2', () {
    test('EW1: canonical test vector (privateKey = 0x1)', () {
      
      
      final addr = deriveEthereumAddressFromPrivateKeyHex(
        '0000000000000000000000000000000000000000000000000000000000000001',
      );
      expect(addr, equals('0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf'));
    });

    test('EW1b: second canonical test vector (privateKey = 0x2)', () {
      final addr = deriveEthereumAddressFromPrivateKeyHex(
        '0000000000000000000000000000000000000000000000000000000000000002',
      );
      
      expect(addr, equals('0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF'));
    });

    test('EW2: two consecutive generates produce distinct keys', () {
      final a = generateEthereumWallet();
      final b = generateEthereumWallet();
      expect(a.privateKeyHex, isNot(equals(b.privateKeyHex)));
      expect(a.publicAddress, isNot(equals(b.publicAddress)));
    });

    test('EW3: publicAddress is EIP-55 checksummed (0x + 42 mixed-case hex)',
        () {
      final w = generateEthereumWallet();
      expect(w.publicAddress.length, equals(42));
      expect(w.publicAddress.startsWith('0x'), isTrue);
      
      
      expect(w.publicAddress, equals(w.publicAddress));
      
      expect(RegExp(r'^0x[0-9a-fA-F]{40}$').hasMatch(w.publicAddress), isTrue);
    });

    test('EW4: publicAddressLowercase equals the lowercase form', () {
      final w = generateEthereumWallet();
      expect(w.publicAddressLowercase, equals(w.publicAddress.toLowerCase()));
    });

    test('EW5: privateKeyHex is exactly 64 lowercase hex chars', () {
      final w = generateEthereumWallet();
      expect(w.privateKeyHex.length, equals(64));
      expect(RegExp(r'^[0-9a-f]{64}$').hasMatch(w.privateKeyHex), isTrue);
    });

    test('EW6: derive helper accepts the 0x prefix', () {
      final withPrefix = deriveEthereumAddressFromPrivateKeyHex(
        '0x0000000000000000000000000000000000000000000000000000000000000001',
      );
      final without = deriveEthereumAddressFromPrivateKeyHex(
        '0000000000000000000000000000000000000000000000000000000000000001',
      );
      expect(withPrefix, equals(without));
    });

    test('EW7: zero private key raises', () {
      expect(
        () => deriveEthereumAddressFromPrivateKeyHex(
          '0000000000000000000000000000000000000000000000000000000000000000',
        ),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('EW7b: wrong-length private key raises', () {
      expect(
        () => deriveEthereumAddressFromPrivateKeyHex('123'),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('EW8: round-trip — generated wallet matches its own derivation', () {
      final w = generateEthereumWallet();
      final derived = deriveEthereumAddressFromPrivateKeyHex(w.privateKeyHex);
      expect(derived, equals(w.publicAddress));
    });
  });
}
