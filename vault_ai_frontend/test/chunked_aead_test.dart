import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/chunked_aead.dart';


void main() {
  final Random rand = Random.secure();

  Uint8List randomKey() {
    final out = Uint8List(32);
    for (var i = 0; i < out.length; i++) {
      out[i] = rand.nextInt(256);
    }
    return out;
  }

  test('frame length = 12 + N + 16', () async {
    final key = randomKey();
    final plaintext = Uint8List(4096);
    for (var i = 0; i < plaintext.length; i++) {
      plaintext[i] = i & 0xff;
    }
    final frame =
        await encryptChunk(plaintext: plaintext, key: key, chunkIndex: 0);
    expect(
      frame.length,
      equals(chunkNonceBytes + plaintext.length + chunkTagBytes),
    );
  });

  test('round-trip restores plaintext', () async {
    final key = randomKey();
    final big = Uint8List(18 * 1024);
    for (var i = 0; i < big.length; i++) {
      big[i] = i & 0xff;
    }
    final frame = await encryptChunk(plaintext: big, key: key, chunkIndex: 0);
    final out = await decryptChunk(frame: frame, key: key, chunkIndex: 0);
    expect(out, equals(big));
  });

  test('wrong chunkIndex fails authentication', () async {
    final key = randomKey();
    final plaintext = Uint8List.fromList([1, 2, 3, 4, 5]);
    final frame =
        await encryptChunk(plaintext: plaintext, key: key, chunkIndex: 0);
    expect(
      () => decryptChunk(frame: frame, key: key, chunkIndex: 1),
      throwsA(isA<SecretBoxAuthenticationError>()),
    );
  });

  test('tampered ciphertext fails authentication', () async {
    final key = randomKey();
    final plaintext = Uint8List.fromList(List<int>.generate(64, (i) => i));
    final frame =
        await encryptChunk(plaintext: plaintext, key: key, chunkIndex: 0);
    final tampered = Uint8List.fromList(frame);
    
    tampered[chunkNonceBytes + 5] ^= 0x01;
    expect(
      () => decryptChunk(frame: tampered, key: key, chunkIndex: 0),
      throwsA(isA<SecretBoxAuthenticationError>()),
    );
  });

  test('wrong key fails authentication', () async {
    final key = randomKey();
    final wrongKey = randomKey();
    final plaintext = Uint8List.fromList([9, 9, 9, 9]);
    final frame =
        await encryptChunk(plaintext: plaintext, key: key, chunkIndex: 0);
    expect(
      () => decryptChunk(frame: frame, key: wrongKey, chunkIndex: 0),
      throwsA(isA<SecretBoxAuthenticationError>()),
    );
  });

  test('frame too short rejects', () {
    final key = randomKey();
    expect(
      () => decryptChunk(
        frame: Uint8List(chunkNonceBytes + chunkTagBytes - 1),
        key: key,
        chunkIndex: 0,
      ),
      throwsArgumentError,
    );
  });

  test('negative chunkIndex rejects', () async {
    final key = randomKey();
    await expectLater(
      () => encryptChunk(
        plaintext: Uint8List.fromList([0]),
        key: key,
        chunkIndex: -1,
      ),
      throwsArgumentError,
    );
  });

  test('chunkIndex >32-bit rejects', () async {
    final key = randomKey();
    await expectLater(
      () => encryptChunk(
        plaintext: Uint8List.fromList([0]),
        key: key,
        chunkIndex: 0x100000000,
      ),
      throwsArgumentError,
    );
  });

  
  group('cross-language vector (Python <-> Dart)', () {
    final vecKey = _hex(
      '000102030405060708090a0b0c0d0e0f'
      '101112131415161718191a1b1c1d1e1f',
    );
    final vecNonce = _hex('0102030405060708090a0b0c');
    final vecPlaintext = Uint8List.fromList('hello vaultai 9.8.A'.codeUnits);
    const vecIndex = 7;

    
    const expectedVectorHex =
        '0102030405060708090a0b0c'
        '6d8f36b983b486e739ce17267933d306'
        '7a6da03c5d4d4d83895d586fc9aaff84c3db19';

    test('Dart re-encrypt produces identical bytes', () async {
      final frame = await encryptChunkWithNonce(
        plaintext: vecPlaintext,
        key: vecKey,
        chunkIndex: vecIndex,
        nonce: vecNonce,
      );
      expect(_toHex(frame), equals(expectedVectorHex));
    });

    test('Dart decrypts the Python-produced frame', () async {
      final frame = _hex(expectedVectorHex);
      final out = await decryptChunk(
        frame: frame,
        key: vecKey,
        chunkIndex: vecIndex,
      );
      expect(out, equals(vecPlaintext));
    });
  });
}

Uint8List _hex(String s) {
  final clean = s.replaceAll(RegExp(r'\s+'), '');
  if (clean.length.isOdd) {
    throw ArgumentError('hex string must have even length');
  }
  final out = Uint8List(clean.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = int.parse(clean.substring(i * 2, i * 2 + 2), radix: 16);
  }
  return out;
}

String _toHex(List<int> bytes) {
  final sb = StringBuffer();
  for (final b in bytes) {
    sb.write(b.toRadixString(16).padLeft(2, '0'));
  }
  return sb.toString();
}
