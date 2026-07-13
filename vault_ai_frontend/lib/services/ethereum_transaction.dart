

import 'dart:typed_data';

import 'package:pointycastle/api.dart' show PrivateKeyParameter;
import 'package:pointycastle/digests/keccak.dart';
import 'package:pointycastle/digests/sha256.dart';
import 'package:pointycastle/ecc/api.dart';
import 'package:pointycastle/ecc/curves/secp256k1.dart';
import 'package:pointycastle/macs/hmac.dart';
import 'package:pointycastle/signers/ecdsa_signer.dart';

import 'ethereum_wallet.dart' show deriveEthereumAddressFromPrivateKeyHex;


final ECDomainParameters _secp256k1 = ECCurve_secp256k1();


/// 2026-07-13 canary correctness: derive `keccak256(raw)` — the
/// canonical Ethereum transaction hash — from the fully signed RLP
/// hex the client just built. Matches the backend's
/// `evm_signed_tx_verify.compute_local_tx_hash`. Used by the send
/// panel to (a) key the local outgoing Activity row and (b) drive
/// post-broadcast status polling.
String computeLocalEthTxHash(String signedTxHex) {
  final hex = signedTxHex.startsWith('0x')
      ? signedTxHex.substring(2)
      : signedTxHex;
  if (hex.length.isOdd || hex.isEmpty) {
    throw ArgumentError('signedTxHex must be non-empty even hex');
  }
  final bytes = Uint8List(hex.length ~/ 2);
  for (var i = 0; i < bytes.length; i++) {
    bytes[i] = int.parse(hex.substring(i * 2, i * 2 + 2), radix: 16);
  }
  final hash = KeccakDigest(256).process(bytes);
  final buf = StringBuffer('0x');
  for (final b in hash) {
    buf.write(b.toRadixString(16).padLeft(2, '0'));
  }
  return buf.toString();
}


String signLegacyEthTransaction({
  required BigInt nonce,
  required BigInt gasPrice,
  required BigInt gasLimit,
  required String toAddress,    
  required BigInt valueWei,
  required String dataHex,      
  required int chainId,
  required String privateKeyHex,
}) {
  
  _requireUnsignedBigInt('nonce', nonce);
  _requireUnsignedBigInt('gasPrice', gasPrice);
  _requireUnsignedBigInt('gasLimit', gasLimit);
  _requireUnsignedBigInt('valueWei', valueWei);
  if (chainId <= 0) {
    throw ArgumentError('chainId must be positive');
  }
  final toBytes = _addressBytes(toAddress);
  final dataBytes = _dataBytes(dataHex);
  
  var pkHex = privateKeyHex;
  if (pkHex.startsWith('0x') || pkHex.startsWith('0X')) {
    pkHex = pkHex.substring(2);
  }
  if (pkHex.length != 64) {
    throw ArgumentError(
      'privateKeyHex must be 64 hex chars (got ${pkHex.length}).',
    );
  }
  final pkBytes = _bytesFromHex(pkHex);
  final pkBigInt = _bigIntFromBytes(pkBytes);
  if (pkBigInt <= BigInt.zero || pkBigInt >= _secp256k1.n) {
    throw ArgumentError(
      'privateKeyHex is outside the secp256k1 valid range [1, n).',
    );
  }

  
  final unsignedRlp = _rlpEncodeList(<List<int>>[
    _encodeUInt(nonce),
    _encodeUInt(gasPrice),
    _encodeUInt(gasLimit),
    toBytes,
    _encodeUInt(valueWei),
    dataBytes,
    _encodeUInt(BigInt.from(chainId)),
    _encodeUInt(BigInt.zero),
    _encodeUInt(BigInt.zero),
  ]);
  final hash = KeccakDigest(256).process(unsignedRlp);

  
  final signer = ECDSASigner(null, HMac(SHA256Digest(), 64));
  signer.init(
    true, 
    PrivateKeyParameter<ECPrivateKey>(
      ECPrivateKey(pkBigInt, _secp256k1),
    ),
  );
  final sig = signer.generateSignature(hash) as ECSignature;
  var r = sig.r;
  var s = sig.s;
  
  final halfOrder = _secp256k1.n >> 1;
  if (s.compareTo(halfOrder) > 0) {
    s = _secp256k1.n - s;
  }

  
  final knownPublicKey = (_secp256k1.G * pkBigInt)!;
  int? recoveryId;
  for (var candidate = 0; candidate < 2; candidate++) {
    final candidatePub = _recoverPublicKey(
      hash: hash, r: r, s: s, recoveryId: candidate,
    );
    if (candidatePub == null) continue;
    if (candidatePub.x!.toBigInteger()! ==
            knownPublicKey.x!.toBigInteger()! &&
        candidatePub.y!.toBigInteger()! ==
            knownPublicKey.y!.toBigInteger()!) {
      recoveryId = candidate;
      break;
    }
  }
  if (recoveryId == null) {
    throw const SigningFailure(
      'Could not resolve secp256k1 recoveryId. This is statistically '
      'near-impossible for a well-formed signature — investigate the '
      'pointycastle dependency.',
    );
  }

  
  final v = BigInt.from(recoveryId + 35 + chainId * 2);

  
  final signedRlp = _rlpEncodeList(<List<int>>[
    _encodeUInt(nonce),
    _encodeUInt(gasPrice),
    _encodeUInt(gasLimit),
    toBytes,
    _encodeUInt(valueWei),
    dataBytes,
    _encodeUInt(v),
    _encodeUInt(r),
    _encodeUInt(s),
  ]);
  
  
  deriveEthereumAddressFromPrivateKeyHex(pkHex); 
  return '0x' + _hex(signedRlp);
}


class SigningFailure implements Exception {
  final String message;
  const SigningFailure(this.message);
  @override
  String toString() => 'SigningFailure: $message';
}


ECPoint? _recoverPublicKey({
  required Uint8List hash,
  required BigInt r,
  required BigInt s,
  required int recoveryId,
}) {
  if (recoveryId < 0 || recoveryId > 3) return null;
  final n = _secp256k1.n;
  if (r <= BigInt.zero || r >= n) return null;
  if (s <= BigInt.zero || s >= n) return null;
  
  final x = r + ((BigInt.from(recoveryId) >> 1) * n);
  
  final curve = _secp256k1.curve;
  final p = (curve as dynamic).q as BigInt;
  if (x >= p) return null;

  
  final R = _decompressPoint(curve, x, (recoveryId & 1) == 1);
  if (R == null) return null;
  if ((R * n) != _secp256k1.curve.infinity) return null;

  
  final e = _bigIntFromBytes(hash);

  
  final rInv = r.modInverse(n);
  final eInv = (n - e) % n;
  final sR = R * s;
  final eG = _secp256k1.G * eInv;
  final sum = sR! + eG!;
  return (sum! * rInv)!;
}

ECPoint? _decompressPoint(ECCurve curve, BigInt x, bool oddY) {
  try {
    
    final xBytes = _padTo32(x);
    final prefix = oddY ? 0x03 : 0x02;
    final encoded = Uint8List(33);
    encoded[0] = prefix;
    encoded.setRange(1, 33, xBytes);
    return curve.decodePoint(encoded);
  } catch (_) {
    return null;
  }
}


Uint8List _rlpEncodeBytes(List<int> bytes) {
  if (bytes.length == 1 && bytes[0] < 0x80) {
    return Uint8List.fromList(bytes);
  }
  if (bytes.length <= 55) {
    return Uint8List.fromList([0x80 + bytes.length, ...bytes]);
  }
  final lenBytes = _bigEndianLenBytes(bytes.length);
  return Uint8List.fromList(
    [0xb7 + lenBytes.length, ...lenBytes, ...bytes],
  );
}

Uint8List _rlpEncodeList(List<List<int>> items) {
  final payloadParts = items.map((b) => _rlpEncodeBytes(b)).toList();
  var payloadLen = 0;
  for (final p in payloadParts) {
    payloadLen += p.length;
  }
  final out = <int>[];
  if (payloadLen <= 55) {
    out.add(0xc0 + payloadLen);
  } else {
    final lenBytes = _bigEndianLenBytes(payloadLen);
    out.add(0xf7 + lenBytes.length);
    out.addAll(lenBytes);
  }
  for (final p in payloadParts) {
    out.addAll(p);
  }
  return Uint8List.fromList(out);
}

Uint8List _bigEndianLenBytes(int n) {
  if (n == 0) return Uint8List(0);
  final out = <int>[];
  while (n > 0) {
    out.insert(0, n & 0xff);
    n >>= 8;
  }
  return Uint8List.fromList(out);
}


void _requireUnsignedBigInt(String name, BigInt v) {
  if (v < BigInt.zero) {
    throw ArgumentError('$name must be non-negative');
  }
}

Uint8List _addressBytes(String to) {
  var s = to;
  if (s.startsWith('0x') || s.startsWith('0X')) s = s.substring(2);
  if (s.length != 40) {
    throw ArgumentError('toAddress must be 40 hex chars (got ${s.length}).');
  }
  if (!RegExp(r'^[0-9a-fA-F]{40}$').hasMatch(s)) {
    throw ArgumentError('toAddress must be valid hex.');
  }
  return _bytesFromHex(s);
}

Uint8List _dataBytes(String dataHex) {
  if (dataHex.isEmpty || dataHex == '0x' || dataHex == '0X') {
    return Uint8List(0);
  }
  var s = dataHex;
  if (s.startsWith('0x') || s.startsWith('0X')) s = s.substring(2);
  if (s.length % 2 != 0) {
    throw ArgumentError('dataHex must have even hex length.');
  }
  if (!RegExp(r'^[0-9a-fA-F]*$').hasMatch(s)) {
    throw ArgumentError('dataHex must be valid hex.');
  }
  return _bytesFromHex(s);
}


Uint8List _encodeUInt(BigInt n) {
  if (n < BigInt.zero) {
    throw ArgumentError('_encodeUInt requires non-negative value');
  }
  if (n == BigInt.zero) return Uint8List(0);
  var hex = n.toRadixString(16);
  if (hex.length % 2 != 0) hex = '0' + hex;
  return _bytesFromHex(hex);
}

BigInt _bigIntFromBytes(Uint8List bytes) {
  var result = BigInt.zero;
  for (final b in bytes) {
    result = (result << 8) | BigInt.from(b);
  }
  return result;
}

Uint8List _padTo32(BigInt n) {
  var hex = n.toRadixString(16);
  if (hex.length < 64) {
    hex = '0' * (64 - hex.length) + hex;
  }
  return _bytesFromHex(hex);
}

Uint8List _bytesFromHex(String hex) {
  if (hex.length % 2 != 0) {
    throw ArgumentError('Hex string must have even length.');
  }
  final out = Uint8List(hex.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = int.parse(hex.substring(i * 2, i * 2 + 2), radix: 16);
  }
  return out;
}

String _hex(Uint8List bytes) {
  final sb = StringBuffer();
  for (final b in bytes) {
    sb.write(b.toRadixString(16).padLeft(2, '0'));
  }
  return sb.toString();
}
