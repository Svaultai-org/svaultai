
import 'dart:typed_data';

import 'package:pointycastle/digests/keccak.dart';


Uint8List moneroKeccak256(Uint8List data) {
  final digest = KeccakDigest(256);
  final out = Uint8List(32);
  digest.update(data, 0, data.length);
  digest.doFinal(out, 0);
  return out;
}


const List<int> _kMoneroBase58BlockSizes =
    <int>[0, 2, 3, 5, 6, 7, 9, 10, 11];

const String _kMoneroBase58Alphabet =
    '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';


String moneroBase58Encode(Uint8List data) {
  if (data.isEmpty) return '';
  final buf = StringBuffer();
  const int fullBlockSize = 8;
  const int fullEncodedSize = 11;
  final int fullBlocks = data.length ~/ fullBlockSize;
  final int leftover = data.length - fullBlocks * fullBlockSize;
  for (int i = 0; i < fullBlocks; i++) {
    buf.write(_encodeBlock(
      data.sublist(i * fullBlockSize, (i + 1) * fullBlockSize),
      fullEncodedSize,
    ));
  }
  if (leftover > 0) {
    buf.write(_encodeBlock(
      data.sublist(fullBlocks * fullBlockSize, data.length),
      _kMoneroBase58BlockSizes[leftover],
    ));
  }
  return buf.toString();
}


Uint8List? moneroBase58Decode(String s) {
  if (s.isEmpty) return Uint8List(0);
  const int fullEncodedSize = 11;
  final int fullBlocks = s.length ~/ fullEncodedSize;
  final int leftover = s.length - fullBlocks * fullEncodedSize;
  int? binaryLeftover;
  for (int i = 0; i < _kMoneroBase58BlockSizes.length; i++) {
    if (_kMoneroBase58BlockSizes[i] == leftover) {
      binaryLeftover = i;
      break;
    }
  }
  if (leftover != 0 && binaryLeftover == null) return null;
  final total = fullBlocks * 8 + (binaryLeftover ?? 0);
  final out = Uint8List(total);
  for (int i = 0; i < fullBlocks; i++) {
    final part = _decodeBlock(
      s.substring(i * fullEncodedSize, (i + 1) * fullEncodedSize), 8,
    );
    if (part == null) return null;
    out.setRange(i * 8, i * 8 + 8, part);
  }
  if ((binaryLeftover ?? 0) > 0) {
    final tail = _decodeBlock(
      s.substring(fullBlocks * fullEncodedSize, s.length),
      binaryLeftover!,
    );
    if (tail == null) return null;
    out.setRange(fullBlocks * 8, fullBlocks * 8 + binaryLeftover, tail);
  }
  return out;
}

String _encodeBlock(Uint8List block, int encodedSize) {
  BigInt num = BigInt.zero;
  for (final b in block) {
    num = (num << 8) | BigInt.from(b & 0xff);
  }
  final chars = List<int>.filled(encodedSize, _kMoneroBase58Alphabet.codeUnitAt(0));
  final radix = BigInt.from(58);
  int idx = encodedSize - 1;
  while (num > BigInt.zero && idx >= 0) {
    final rem = (num % radix).toInt();
    chars[idx] = _kMoneroBase58Alphabet.codeUnitAt(rem);
    num = num ~/ radix;
    idx -= 1;
  }
  return String.fromCharCodes(chars);
}

Uint8List? _decodeBlock(String block, int decodedSize) {
  BigInt num = BigInt.zero;
  final radix = BigInt.from(58);
  for (int i = 0; i < block.length; i++) {
    final ch = block.codeUnitAt(i);
    final idx = _kMoneroBase58Alphabet.indexOf(String.fromCharCode(ch));
    if (idx < 0) return null;
    num = num * radix + BigInt.from(idx);
  }
  final out = Uint8List(decodedSize);
  for (int i = decodedSize - 1; i >= 0; i--) {
    out[i] = (num & BigInt.from(0xff)).toInt();
    num = num >> 8;
  }
  if (num != BigInt.zero) return null;
  return out;
}


const int kMoneroMainnetPrimaryPrefix = 0x12;
const int kMoneroMainnetIntegratedPrefix = 0x13;
const int kMoneroMainnetSubaddressPrefix = 0x2A;


String buildMoneroPrimaryAddress({
  required Uint8List publicSpendKey,
  required Uint8List publicViewKey,
  int prefix = kMoneroMainnetPrimaryPrefix,
}) {
  if (publicSpendKey.length != 32) {
    throw ArgumentError.value(
      publicSpendKey.length, 'publicSpendKey.length',
      'publicSpendKey must be 32 bytes',
    );
  }
  if (publicViewKey.length != 32) {
    throw ArgumentError.value(
      publicViewKey.length, 'publicViewKey.length',
      'publicViewKey must be 32 bytes',
    );
  }
  final body = Uint8List(65);
  body[0] = prefix & 0xff;
  body.setRange(1, 33, publicSpendKey);
  body.setRange(33, 65, publicViewKey);
  final checksum = moneroKeccak256(body).sublist(0, 4);
  final full = Uint8List(69);
  full.setRange(0, 65, body);
  full.setRange(65, 69, checksum);
  return moneroBase58Encode(full);
}


bool moneroPrimaryAddressChecksumValid(String address, {int prefix = kMoneroMainnetPrimaryPrefix}) {
  if (address.length != 95) return false;
  final decoded = moneroBase58Decode(address);
  if (decoded == null || decoded.length != 69) return false;
  if (decoded[0] != (prefix & 0xff)) return false;
  final expected = moneroKeccak256(decoded.sublist(0, 65)).sublist(0, 4);
  for (int i = 0; i < 4; i++) {
    if (decoded[65 + i] != expected[i]) return false;
  }
  return true;
}
