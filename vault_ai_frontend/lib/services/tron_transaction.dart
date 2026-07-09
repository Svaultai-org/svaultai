

import 'dart:typed_data';

import 'package:pointycastle/api.dart' show PrivateKeyParameter;
import 'package:pointycastle/digests/sha256.dart';
import 'package:pointycastle/ecc/api.dart';
import 'package:pointycastle/ecc/curves/secp256k1.dart';
import 'package:pointycastle/macs/hmac.dart';
import 'package:pointycastle/signers/ecdsa_signer.dart';


final ECDomainParameters _tronSecp256k1 = ECCurve_secp256k1();


class TronSigningFailure implements Exception {
  final String message;
  const TronSigningFailure(this.message);
  @override
  String toString() => 'TronSigningFailure: $message';
}


String signTronTxIDHex({
  required String txIDHex,
  required String privateKeyHex,
}) {
  final txidClean = _stripHexPrefix(txIDHex);
  if (txidClean.length != 64) {
    throw ArgumentError(
      'txID must be 64 hex chars (got ${txidClean.length}).',
    );
  }
  if (!RegExp(r'^[0-9a-fA-F]{64}$').hasMatch(txidClean)) {
    throw ArgumentError('txID must be valid hex.');
  }
  final txidBytes = _bytesFromHex(txidClean);

  var pkHex = _stripHexPrefix(privateKeyHex);
  if (pkHex.length != 64) {
    throw ArgumentError(
      'privateKeyHex must be 64 hex chars (got ${pkHex.length}).',
    );
  }
  final pkBytes = _bytesFromHex(pkHex);
  final pkBigInt = _bigIntFromBytes(pkBytes);
  if (pkBigInt <= BigInt.zero || pkBigInt >= _tronSecp256k1.n) {
    throw ArgumentError(
      'privateKeyHex is outside the secp256k1 valid range [1, n).',
    );
  }

  final signer = ECDSASigner(null, HMac(SHA256Digest(), 64));
  signer.init(
    true,
    PrivateKeyParameter<ECPrivateKey>(
      ECPrivateKey(pkBigInt, _tronSecp256k1),
    ),
  );
  final sig = signer.generateSignature(txidBytes) as ECSignature;
  var r = sig.r;
  var s = sig.s;
  final halfOrder = _tronSecp256k1.n >> 1;
  if (s.compareTo(halfOrder) > 0) {
    s = _tronSecp256k1.n - s;
  }

  final knownPublicKey = (_tronSecp256k1.G * pkBigInt)!;
  int? recoveryId;
  for (var candidate = 0; candidate < 2; candidate++) {
    final candidatePub = _recoverPublicKey(
      hash: txidBytes, r: r, s: s, recoveryId: candidate,
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
    throw const TronSigningFailure(
      'Could not resolve secp256k1 recoveryId for TRON.',
    );
  }

  final rBytes = _padTo32(r);
  final sBytes = _padTo32(s);
  final full = Uint8List(65);
  full.setRange(0, 32, rBytes);
  full.setRange(32, 64, sBytes);
  full[64] = recoveryId;
  return _hex(full);
}


Map<String, dynamic> attachTronSignatureToUnsigned({
  required Map<String, dynamic> unsignedTransaction,
  required String signatureHex,
}) {
  if (!RegExp(r'^[0-9a-fA-F]{130}$').hasMatch(signatureHex)) {
    throw ArgumentError('TRON signature must be 130 hex chars.');
  }
  final txID = unsignedTransaction['txID'];
  final rawDataHex = unsignedTransaction['raw_data_hex'];
  final rawData = unsignedTransaction['raw_data'];
  if (txID is! String || rawDataHex is! String || rawData == null) {
    throw ArgumentError(
      'unsignedTransaction must include txID, raw_data, and '
      'raw_data_hex.',
    );
  }
  return <String, dynamic>{
    'txID':         txID,
    'raw_data':     rawData,
    'raw_data_hex': rawDataHex,
    'signature':    <String>[signatureHex.toLowerCase()],
    'visible':      unsignedTransaction['visible'] ?? false,
  };
}


Map<String, dynamic> signTronTrc20Transfer({
  required Map<String, dynamic> unsignedTransaction,
  required String txIDHex,
  required String privateKeyHex,
}) {
  final signatureHex = signTronTxIDHex(
    txIDHex: txIDHex,
    privateKeyHex: privateKeyHex,
  );
  return attachTronSignatureToUnsigned(
    unsignedTransaction: unsignedTransaction,
    signatureHex: signatureHex,
  );
}


int parseUsdtAmountToBaseUnits(String amount) {
  final s = amount.trim();
  if (s.isEmpty) {
    throw ArgumentError('Amount must not be empty.');
  }
  if (!RegExp(r'^\d+(?:\.\d+)?$').hasMatch(s)) {
    throw ArgumentError(
      'Amount must be a non-negative decimal like 5 or 12.5.',
    );
  }
  String whole;
  String frac;
  if (s.contains('.')) {
    final parts = s.split('.');
    whole = parts[0];
    frac = parts[1];
  } else {
    whole = s;
    frac = '';
  }
  if (frac.length > 6) {
    throw ArgumentError(
      'USDT TRC20 amounts support at most 6 decimal places.',
    );
  }
  final fracPadded = frac.padRight(6, '0');
  final wholeBI = whole.isEmpty ? BigInt.zero : BigInt.parse(whole);
  final fracBI = fracPadded.isEmpty
      ? BigInt.zero
      : BigInt.parse(fracPadded);
  final base = wholeBI * BigInt.from(1000000) + fracBI;
  if (base <= BigInt.zero) {
    throw ArgumentError('Amount must be greater than zero.');
  }
  if (base > BigInt.from(1) << 62) {
    throw ArgumentError('Amount is unreasonably large.');
  }
  return base.toInt();
}


void wipePrivateKeyHex(String key) {

  key.codeUnits;
}


String _stripHexPrefix(String s) {
  if (s.startsWith('0x') || s.startsWith('0X')) {
    return s.substring(2);
  }
  return s;
}


ECPoint? _recoverPublicKey({
  required Uint8List hash,
  required BigInt r,
  required BigInt s,
  required int recoveryId,
}) {
  if (recoveryId < 0 || recoveryId > 3) return null;
  final n = _tronSecp256k1.n;
  if (r <= BigInt.zero || r >= n) return null;
  if (s <= BigInt.zero || s >= n) return null;
  final x = r + ((BigInt.from(recoveryId) >> 1) * n);
  final curve = _tronSecp256k1.curve;
  final p = (curve as dynamic).q as BigInt;
  if (x >= p) return null;
  final R = _decompressPoint(curve, x, (recoveryId & 1) == 1);
  if (R == null) return null;
  if ((R * n) != _tronSecp256k1.curve.infinity) return null;
  final e = _bigIntFromBytes(hash);
  final rInv = r.modInverse(n);
  final eInv = (n - e) % n;
  final sR = R * s;
  final eG = _tronSecp256k1.G * eInv;
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
  if (hex.length.isOdd) {
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
