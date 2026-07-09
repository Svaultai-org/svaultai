
import 'dart:typed_data';

import 'monero_crypto_primitives.dart';


final BigInt _q =
    (BigInt.one << 255) - BigInt.from(19);


final BigInt _l = (BigInt.one << 252)
    + BigInt.parse('27742317777372353535851937790883648493');


BigInt _modQ(BigInt x) {
  final r = x % _q;
  return r.isNegative ? r + _q : r;
}


BigInt _invModQ(BigInt x) {
  return _modPow(x, _q - BigInt.two, _q);
}


BigInt _modPow(BigInt base, BigInt exp, BigInt mod) {
  return base.modPow(exp, mod);
}


final BigInt _d = _modQ(
  BigInt.from(-121665) * _invModQ(BigInt.from(121666)),
);


final BigInt _Bx = BigInt.parse(
  '15112221349535400772501151409588531511454012693041857206046113283949847762202',
);
final BigInt _By = BigInt.parse(
  '46316835694926478169428394003475163141307993866256225615783033603165251855960',
);


class _EdPoint {

  final BigInt x;
  final BigInt y;
  final BigInt z;
  final BigInt t;

  const _EdPoint(this.x, this.y, this.z, this.t);

  static final _EdPoint identity = _EdPoint(
    BigInt.zero, BigInt.one, BigInt.one, BigInt.zero,
  );


  static _EdPoint fromAffine(BigInt xAff, BigInt yAff) {
    return _EdPoint(xAff, yAff, BigInt.one, _modQ(xAff * yAff));
  }

  _EdPoint doubled() {

    final xx = _modQ(x * x);
    final yy = _modQ(y * y);
    final zz2 = _modQ(z * z * BigInt.two);
    final e = _modQ((x + y) * (x + y) - xx - yy);
    final g = yy - xx;
    final f = g - zz2;
    final h = _modQ(-(xx) - yy);
    return _EdPoint(
      _modQ(e * f), _modQ(g * h), _modQ(f * g), _modQ(e * h),
    );
  }

  _EdPoint add(_EdPoint other) {

    final a = _modQ((y - x) * (other.y - other.x));
    final b = _modQ((y + x) * (other.y + other.x));
    final c = _modQ(t * BigInt.two * _d * other.t);
    final dd = _modQ(z * BigInt.two * other.z);
    final e = b - a;
    final f = dd - c;
    final g = dd + c;
    final h = b + a;
    return _EdPoint(
      _modQ(e * f), _modQ(g * h), _modQ(f * g), _modQ(e * h),
    );
  }


  Uint8List encode() {
    final zInv = _invModQ(z);
    final xAff = _modQ(x * zInv);
    final yAff = _modQ(y * zInv);
    final out = Uint8List(32);
    BigInt v = yAff;
    for (int i = 0; i < 32; i++) {
      out[i] = (v & BigInt.from(0xff)).toInt();
      v = v >> 8;
    }
    if (xAff.isOdd) {
      out[31] |= 0x80;
    }
    return out;
  }
}


final _EdPoint _basePoint = _EdPoint.fromAffine(_Bx, _By);



Uint8List ed25519ScalarMultBase(BigInt scalar) {
  BigInt k = scalar % _l;
  if (k.isNegative) k += _l;
  _EdPoint result = _EdPoint.identity;
  _EdPoint addend = _basePoint;
  while (k > BigInt.zero) {
    if (k.isOdd) {
      result = result.add(addend);
    }
    addend = addend.doubled();
    k = k >> 1;
  }
  return result.encode();
}



BigInt scalarFromLittleEndian32(Uint8List bytes) {
  if (bytes.length != 32) {
    throw ArgumentError.value(
      bytes.length, 'bytes.length', 'must be exactly 32',
    );
  }
  BigInt v = BigInt.zero;
  for (int i = 31; i >= 0; i--) {
    v = (v << 8) | BigInt.from(bytes[i] & 0xff);
  }
  return v;
}


Uint8List scRed32(Uint8List seed) {
  final reduced = scalarFromLittleEndian32(seed) % _l;
  final out = Uint8List(32);
  BigInt v = reduced;
  for (int i = 0; i < 32; i++) {
    out[i] = (v & BigInt.from(0xff)).toInt();
    v = v >> 8;
  }
  return out;
}


Uint8List moneroDerivePrivateViewKey(Uint8List privateSpendKey) {
  final hashed = moneroKeccak256(privateSpendKey);
  return scRed32(hashed);
}


Uint8List moneroDerivePublicKey(Uint8List privateKey) {
  return ed25519ScalarMultBase(scalarFromLittleEndian32(privateKey));
}
