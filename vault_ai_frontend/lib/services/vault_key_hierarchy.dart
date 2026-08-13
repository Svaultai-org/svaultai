// Vault key hierarchy: HKDF-domain-separated subkeys derived from
// the client's MVK (master vault key). Every subkey stays on the
// client; the server never possesses any of them.
//
// Info-string convention: every subkey uses a UTF-8 info label of
// the form "vaultai.<purpose>.v1". Bumping the version suffix
// forces a coexisting-key rotation; today only .v1 exists.
//
// This file uses only the `cryptography` package. It contains no
// bespoke cryptography.

import 'dart:convert';
import 'dart:math' show Random;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

final Hkdf _hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
final AesGcm _aesGcm = AesGcm.with256bits();

const int _aesGcmNonceBytes = 12;

class VaultKeyHierarchy {
  final SecretKey mvk;
  final Map<String, Future<SecretKey>> _subkeyCache =
      <String, Future<SecretKey>>{};
  VaultKeyHierarchy(this.mvk);

  Future<SecretKey> _deriveSubkey(String infoLabel) async {
    final mvkBytes = await mvk.extractBytes();
    return _hkdf.deriveKey(
      secretKey: SecretKey(mvkBytes),
      nonce: const [],
      info: utf8.encode(infoLabel),
    );
  }

  Future<SecretKey> _sub(String infoLabel) =>
      _subkeyCache.putIfAbsent(infoLabel, () => _deriveSubkey(infoLabel));

  Future<SecretKey> metadataKey() => _sub('vaultai.metadata.v1');
  Future<SecretKey> memoryKey() => _sub('vaultai.memory.v1');
  Future<SecretKey> credentialKey() => _sub('vaultai.credential.encryption.v2');
  Future<SecretKey> credentialLookupKey() =>
      _sub('vaultai.credential.lookup.v2');
  Future<SecretKey> walletWrapKey() => _sub('vaultai.wallet.v2');
  Future<SecretKey> walletBackupKey() =>
      _sub('vaultai.wallet.backup.encryption.v2');
  Future<SecretKey> displayNameKey() => _sub('vaultai.display.v1');
  Future<SecretKey> semanticLookupKey() => _sub('vaultai.lookup.semantic.v1');
  Future<SecretKey> memoryLookupKey() => _sub('vaultai.lookup.memory.v1');
  Future<SecretKey> walletLockLookupKey() =>
      _sub('vaultai.lookup.wallet.lock.v1');
}

/// Wrap plaintext under the given AES-GCM subkey. Envelope layout:
///     version(0x01) || nonce(12) || ciphertext || tag(16)
Future<Uint8List> aesGcmWrap(SecretKey key, List<int> plaintext) async {
  final nonce = _randomBytes(_aesGcmNonceBytes);
  final box = await _aesGcm.encrypt(
    plaintext,
    secretKey: key,
    nonce: nonce,
  );
  final out = BytesBuilder();
  out.addByte(0x01);
  out.add(nonce);
  out.add(box.cipherText);
  out.add(box.mac.bytes);
  return out.toBytes();
}

Future<Uint8List> aesGcmWrapWithAad(
  SecretKey key,
  List<int> plaintext, {
  required List<int> aad,
}) async {
  final nonce = _randomBytes(_aesGcmNonceBytes);
  final box =
      await _aesGcm.encrypt(plaintext, secretKey: key, nonce: nonce, aad: aad);
  final out = BytesBuilder()
    ..addByte(0x01)
    ..add(nonce)
    ..add(box.cipherText)
    ..add(box.mac.bytes);
  return out.toBytes();
}

Future<Uint8List> aesGcmUnwrap(SecretKey key, Uint8List envelope) async {
  if (envelope.isEmpty || envelope[0] != 0x01) {
    throw StateError('unknown ciphertext envelope version byte');
  }
  final nonce = envelope.sublist(1, 1 + _aesGcmNonceBytes);
  final tagStart = envelope.length - 16;
  final ct = envelope.sublist(1 + _aesGcmNonceBytes, tagStart);
  final tag = envelope.sublist(tagStart);
  final box = SecretBox(ct, nonce: nonce, mac: Mac(tag));
  return Uint8List.fromList(
    await _aesGcm.decrypt(box, secretKey: key),
  );
}

Future<Uint8List> aesGcmUnwrapWithAad(
  SecretKey key,
  Uint8List envelope, {
  required List<int> aad,
}) async {
  if (envelope.isEmpty ||
      envelope[0] != 0x01 ||
      envelope.length < 1 + _aesGcmNonceBytes + 16) {
    throw StateError('unknown ciphertext envelope version byte');
  }
  final nonce = envelope.sublist(1, 1 + _aesGcmNonceBytes);
  final tagStart = envelope.length - 16;
  final box = SecretBox(
    envelope.sublist(1 + _aesGcmNonceBytes, tagStart),
    nonce: nonce,
    mac: Mac(envelope.sublist(tagStart)),
  );
  return Uint8List.fromList(
      await _aesGcm.decrypt(box, secretKey: key, aad: aad));
}

/// Vault-scoped HMAC-SHA-256 used for keyed lookup hashes.
Future<Uint8List> keyedLookupHash(
    SecretKey lookupSubkey, List<int> plaintext) async {
  final subkeyBytes = await lookupSubkey.extractBytes();
  final hmac = Hmac.sha256();
  final mac = await hmac.calculateMac(
    plaintext,
    secretKey: SecretKey(subkeyBytes),
  );
  return Uint8List.fromList(mac.bytes);
}

Uint8List _randomBytes(int len) {
  final rng = Random.secure();
  final out = Uint8List(len);
  for (var i = 0; i < len; i++) {
    out[i] = rng.nextInt(256);
  }
  return out;
}

/// Base64url-encode without padding.
String b64urlEncode(List<int> raw) {
  const alphabet =
      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  final out = StringBuffer();
  final len = raw.length;
  final full = (len ~/ 3) * 3;
  for (var i = 0; i < full; i += 3) {
    final n = (raw[i] << 16) | (raw[i + 1] << 8) | raw[i + 2];
    out.write(alphabet[(n >> 18) & 0x3F]);
    out.write(alphabet[(n >> 12) & 0x3F]);
    out.write(alphabet[(n >> 6) & 0x3F]);
    out.write(alphabet[n & 0x3F]);
  }
  final rem = len - full;
  if (rem == 1) {
    final n = raw[full] << 16;
    out.write(alphabet[(n >> 18) & 0x3F]);
    out.write(alphabet[(n >> 12) & 0x3F]);
  } else if (rem == 2) {
    final n = (raw[full] << 16) | (raw[full + 1] << 8);
    out.write(alphabet[(n >> 18) & 0x3F]);
    out.write(alphabet[(n >> 12) & 0x3F]);
    out.write(alphabet[(n >> 6) & 0x3F]);
  }
  return out.toString();
}

Uint8List b64urlDecode(String s) {
  var padded = s;
  while (padded.length % 4 != 0) {
    padded += '=';
  }
  return Uint8List.fromList(base64Url.decode(padded));
}
