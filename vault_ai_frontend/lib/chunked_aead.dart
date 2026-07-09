import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';


const int chunkNonceBytes = 12;
const int chunkTagBytes = 16;
const int chunkIndexAadBytes = 4;

final AesGcm _aesGcm = AesGcm.with256bits();

Uint8List _indexAad(int chunkIndex) {
  if (chunkIndex < 0) {
    throw ArgumentError('chunkIndex must be non-negative');
  }
  if (chunkIndex > 0xFFFFFFFF) {
    throw ArgumentError('chunkIndex exceeds 32-bit range');
  }
  final bd = ByteData(chunkIndexAadBytes);
  bd.setUint32(0, chunkIndex, Endian.big);
  return bd.buffer.asUint8List();
}


Future<Uint8List> encryptChunk({
  required List<int> plaintext,
  required List<int> key,
  required int chunkIndex,
}) async {
  final secretBox = await _aesGcm.encrypt(
    plaintext,
    secretKey: SecretKey(key),
    aad: _indexAad(chunkIndex),
  );
  return _concat([secretBox.nonce, secretBox.cipherText, secretBox.mac.bytes]);
}


Future<Uint8List> encryptChunkWithNonce({
  required List<int> plaintext,
  required List<int> key,
  required int chunkIndex,
  required List<int> nonce,
}) async {
  if (nonce.length != chunkNonceBytes) {
    throw ArgumentError('nonce must be exactly $chunkNonceBytes bytes');
  }
  final secretBox = await _aesGcm.encrypt(
    plaintext,
    secretKey: SecretKey(key),
    nonce: nonce,
    aad: _indexAad(chunkIndex),
  );
  return _concat([secretBox.nonce, secretBox.cipherText, secretBox.mac.bytes]);
}


Future<Uint8List> decryptChunk({
  required List<int> frame,
  required List<int> key,
  required int chunkIndex,
}) async {
  if (frame.length < chunkNonceBytes + chunkTagBytes) {
    throw ArgumentError('Chunk frame too short');
  }
  final nonce = frame.sublist(0, chunkNonceBytes);
  final mac = frame.sublist(frame.length - chunkTagBytes);
  final ct = frame.sublist(chunkNonceBytes, frame.length - chunkTagBytes);
  final secretBox = SecretBox(ct, nonce: nonce, mac: Mac(mac));
  final plaintext = await _aesGcm.decrypt(
    secretBox,
    secretKey: SecretKey(key),
    aad: _indexAad(chunkIndex),
  );
  return Uint8List.fromList(plaintext);
}

Uint8List _concat(List<List<int>> parts) {
  final total = parts.fold<int>(0, (acc, p) => acc + p.length);
  final out = Uint8List(total);
  var offset = 0;
  for (final p in parts) {
    out.setRange(offset, offset + p.length, p);
    offset += p.length;
  }
  return out;
}
