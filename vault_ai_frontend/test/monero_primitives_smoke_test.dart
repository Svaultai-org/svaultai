


import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/monero_crypto_primitives.dart';


const String _kDonationAddress =
    '44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb'
    '98uNbr2VBBEt7f2wfn3RVGQBEP3A';


Uint8List _hex(String h) {
  final b = Uint8List(h.length ~/ 2);
  for (int i = 0; i < b.length; i++) {
    b[i] = int.parse(h.substring(i * 2, i * 2 + 2), radix: 16);
  }
  return b;
}


void main() {
  group('Monero Keccak-256', () {
    test('empty input matches known Monero-variant vector', () {
      final out = moneroKeccak256(Uint8List(0));
      expect(
        out.map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
        'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470',
      );
    });

    test('"abc" input matches Keccak-256 vector', () {
      final out = moneroKeccak256(
        Uint8List.fromList(utf8.encode('abc')),
      );
      expect(
        out.map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
        '4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45',
      );
    });
  });

  group('Monero base58', () {
    test('round-trip on the donation address matches', () {
      final decoded = moneroBase58Decode(_kDonationAddress);
      expect(decoded, isNotNull);
      expect(decoded!.length, 69);
      expect(decoded[0], kMoneroMainnetPrimaryPrefix);
      final reencoded = moneroBase58Encode(decoded);
      expect(reencoded, _kDonationAddress);
    });

    test('rejects a corrupted alphabet char', () {
      final bad = 'O' + _kDonationAddress.substring(1);
      expect(moneroBase58Decode(bad), isNull);
    });
  });

  group('Monero address checksum', () {
    test('donation address passes checksum validation', () {
      expect(
        moneroPrimaryAddressChecksumValid(_kDonationAddress),
        true,
      );
    });

    test('mutated last char fails checksum validation', () {
      final tail = _kDonationAddress[_kDonationAddress.length - 1] == 'A'
          ? 'B' : 'A';
      final mutated =
          _kDonationAddress.substring(0, _kDonationAddress.length - 1) + tail;
      expect(
        moneroPrimaryAddressChecksumValid(mutated),
        false,
      );
    });

    test('wrong prefix byte fails checksum validation', () {
      final decoded = moneroBase58Decode(_kDonationAddress);
      expect(decoded, isNotNull);
      final tampered = Uint8List.fromList(decoded!);
      tampered[0] = 0x00;
      final reencoded = moneroBase58Encode(tampered);
      expect(
        moneroPrimaryAddressChecksumValid(reencoded),
        false,
      );
    });
  });

  group('buildMoneroPrimaryAddress', () {
    test('rebuilds the donation address from its extracted public keys',
        () {
      final decoded = moneroBase58Decode(_kDonationAddress)!;
      final pkSpend = Uint8List.fromList(decoded.sublist(1, 33));
      final pkView = Uint8List.fromList(decoded.sublist(33, 65));
      final rebuilt = buildMoneroPrimaryAddress(
        publicSpendKey: pkSpend, publicViewKey: pkView,
      );
      expect(rebuilt, _kDonationAddress);
    });

    test('requires 32-byte public keys', () {
      expect(
        () => buildMoneroPrimaryAddress(
          publicSpendKey: Uint8List(31),
          publicViewKey: Uint8List(32),
        ),
        throwsArgumentError,
      );
      expect(
        () => buildMoneroPrimaryAddress(
          publicSpendKey: Uint8List(32),
          publicViewKey: Uint8List(31),
        ),
        throwsArgumentError,
      );
    });
  });
}
