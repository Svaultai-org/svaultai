import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

String _hex(List<int> bytes) {
  const alphabet = '0123456789abcdef';
  final out = StringBuffer();
  for (final byte in bytes) {
    out.write(alphabet[(byte >> 4) & 0x0f]);
    out.write(alphabet[byte & 0x0f]);
  }
  return out.toString();
}

void main() {
  test('Dart PBKDF2-HMAC-SHA256 matches the native fixed vectors', () async {
    final cases = [
      (
        password: 'password',
        salt: 'salt',
        iterations: 1,
        expected:
            '120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b',
      ),
      (
        password: 'password',
        salt: 'salt',
        iterations: 2,
        expected:
            'ae4d0c95af6b46d32d0adff928f06dd02a303f8ef3c251dfd6e2d85a95474c43',
      ),
      (
        password: 'password',
        salt: 'salt',
        iterations: 4096,
        expected:
            'c5e478d59288c841aa530db6845c4c8d962893a001ce4e11a4963873aa98134a',
      ),
    ];

    for (final vector in cases) {
      final algorithm = Pbkdf2(
        macAlgorithm: Hmac.sha256(),
        iterations: vector.iterations,
        bits: 256,
      );
      final key = await algorithm.deriveKey(
        secretKey: SecretKey(utf8.encode(vector.password)),
        nonce: utf8.encode(vector.salt),
      );
      expect(_hex(await key.extractBytes()), vector.expected);
    }
  });
}
