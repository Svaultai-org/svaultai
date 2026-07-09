


import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/monero_ed25519.dart';


Uint8List _hex(String h) {
  final b = Uint8List(h.length ~/ 2);
  for (int i = 0; i < b.length; i++) {
    b[i] = int.parse(h.substring(i * 2, i * 2 + 2), radix: 16);
  }
  return b;
}


String _hexOf(Uint8List b) =>
    b.map((v) => v.toRadixString(16).padLeft(2, '0')).join();


Uint8List _rfc8032ClampedScalar(Uint8List seed) {
  final digest = sha512.convert(seed).bytes;
  final s = Uint8List.fromList(digest.sublist(0, 32));
  s[0] &= 248;
  s[31] &= 127;
  s[31] |= 64;
  return s;
}


void main() {
  group('Ed25519 ge_scalarmult_base — RFC 8032 verification', () {

    test('scalar=1 encodes the base point B', () {
      final result = ed25519ScalarMultBase(BigInt.one);
      const expected =
          '5866666666666666666666666666666666666666666666666666666666666666';
      expect(_hexOf(result), expected);
    });

    test('RFC 8032 test vector 1: seed 9d61..7f60 → pk d75a..511a',
        () {
      final seed = _hex(
        '9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60',
      );
      final clamped = _rfc8032ClampedScalar(seed);
      final pub = ed25519ScalarMultBase(
        scalarFromLittleEndian32(clamped),
      );
      expect(
        _hexOf(pub),
        'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a',
      );
    });

    test('RFC 8032 test vector 2: seed 4ccd..64f2 → pk 3d40..1f5b',
        () {
      final seed = _hex(
        '4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb',
      );
      final clamped = _rfc8032ClampedScalar(seed);
      final pub = ed25519ScalarMultBase(
        scalarFromLittleEndian32(clamped),
      );
      expect(
        _hexOf(pub),
        '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c',
      );
    });

    test('RFC 8032 test vector 3: seed c5aa..1cf7 → pk fc51..5025',
        () {
      final seed = _hex(
        'c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7',
      );
      final clamped = _rfc8032ClampedScalar(seed);
      final pub = ed25519ScalarMultBase(
        scalarFromLittleEndian32(clamped),
      );
      expect(
        _hexOf(pub),
        'fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025',
      );
    });
  });
}
