/// PIN-free private-vault inheritance envelope.
///
/// The owner encrypts its 32-byte MVK for the beneficiary's registered
/// X25519 public key. The server holds only the envelope and releases it
/// under the existing inheritance approval/countdown state machine.
library;

import 'dart:convert';
import 'dart:math' show Random;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

const int inheritanceMvkCryptoVersion = 2;
const String _info = 'vaultai.inh-mvk.v2';
final _aes = AesGcm.with256bits();
final _hkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);

/// Full SHA-256 fingerprint of the beneficiary's locally derived X25519 key.
/// The owner must obtain it from the beneficiary over an independent channel.
Future<String> beneficiaryPublicKeyFingerprint(Uint8List publicKey) async {
  if (publicKey.length != 32) {
    throw ArgumentError('Invalid beneficiary public key');
  }
  final digest = await Sha256().hash(publicKey);
  final hex =
      digest.bytes.map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();
  return [for (var i = 0; i < hex.length; i += 8) hex.substring(i, i + 8)]
      .join('-');
}

Future<String> beneficiaryPrivateKeyFingerprint(SecretKey privateKey) async {
  final seed = await privateKey.extractBytes();
  if (seed.length != 32) {
    throw ArgumentError('Invalid beneficiary private key');
  }
  final pair = await X25519().newKeyPairFromSeed(seed);
  final publicKey = await pair.extractPublicKey();
  return beneficiaryPublicKeyFingerprint(Uint8List.fromList(publicKey.bytes));
}

bool beneficiaryFingerprintMatches(String expected, String entered) {
  String normalized(String value) =>
      value.replaceAll(RegExp(r'[\s-]'), '').toLowerCase();
  final left = normalized(expected);
  final right = normalized(entered);
  if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(left) ||
      !RegExp(r'^[0-9a-f]{64}$').hasMatch(right)) {
    return false;
  }
  var difference = 0;
  for (var i = 0; i < 64; i++) {
    difference |= left.codeUnitAt(i) ^ right.codeUnitAt(i);
  }
  return difference == 0;
}

class InheritanceMvkEnvelope {
  final String encryptedPayload;
  final String payloadNonce;
  final String wrappedKey;
  final String wrappingEphemeralPk;
  final String wrappingNonce;

  const InheritanceMvkEnvelope({
    required this.encryptedPayload,
    required this.payloadNonce,
    required this.wrappedKey,
    required this.wrappingEphemeralPk,
    required this.wrappingNonce,
  });

  Map<String, dynamic> toRequestBody(int linkId) => {
        'beneficiary_link_id': linkId,
        'crypto_version': inheritanceMvkCryptoVersion,
        'encrypted_payload': encryptedPayload,
        'payload_nonce': payloadNonce,
        'wrapped_key': wrappedKey,
        'wrapping_ephemeral_pk': wrappingEphemeralPk,
        'wrapping_nonce': wrappingNonce,
      };
}

class DecryptedInheritanceMvk {
  final int beneficiaryLinkId;
  final String ownerVaultId;
  final SecretKey ownerMvk;

  const DecryptedInheritanceMvk({
    required this.beneficiaryLinkId,
    required this.ownerVaultId,
    required this.ownerMvk,
  });
}

Future<InheritanceMvkEnvelope> encryptInheritanceMvk({
  required int beneficiaryLinkId,
  required String ownerVaultId,
  required SecretKey ownerMvk,
  required Uint8List beneficiaryPublicKey,
  Random? randomForTest,
}) async {
  if (beneficiaryLinkId <= 0 ||
      ownerVaultId.isEmpty ||
      beneficiaryPublicKey.length != 32) {
    throw ArgumentError('Invalid inheritance envelope context');
  }
  final mvkBytes = await ownerMvk.extractBytes();
  if (mvkBytes.length != 32) {
    throw StateError('Owner private vault key is unavailable');
  }
  final random = randomForTest ?? Random.secure();
  final cek = _randomBytes(random, 32);
  final payloadNonce = _randomBytes(random, 12);
  final plain = utf8.encode(jsonEncode({
    'version': inheritanceMvkCryptoVersion,
    'beneficiary_link_id': beneficiaryLinkId,
    'owner_vault_id': ownerVaultId,
    'mvk': _b64(mvkBytes),
  }));
  final payloadBox = await _aes.encrypt(
    plain,
    secretKey: SecretKey(cek),
    nonce: payloadNonce,
  );

  final x25519 = X25519();
  final ephemeral = await x25519.newKeyPair();
  final ephemeralPublic = await ephemeral.extractPublicKey();
  final shared = await x25519.sharedSecretKey(
    keyPair: ephemeral,
    remotePublicKey: SimplePublicKey(
      beneficiaryPublicKey,
      type: KeyPairType.x25519,
    ),
  );
  final wrapKey = await _hkdf.deriveKey(
    secretKey: shared,
    nonce: ephemeralPublic.bytes,
    info: utf8.encode(_info),
  );
  final wrapNonce = _randomBytes(random, 12);
  final wrapBox = await _aes.encrypt(
    cek,
    secretKey: wrapKey,
    nonce: wrapNonce,
  );
  return InheritanceMvkEnvelope(
    encryptedPayload: _b64([...payloadBox.cipherText, ...payloadBox.mac.bytes]),
    payloadNonce: _b64(payloadNonce),
    wrappedKey: _b64([...wrapBox.cipherText, ...wrapBox.mac.bytes]),
    wrappingEphemeralPk: _b64(ephemeralPublic.bytes),
    wrappingNonce: _b64(wrapNonce),
  );
}

Future<DecryptedInheritanceMvk> decryptInheritanceMvk({
  required int expectedLinkId,
  required SecretKey beneficiaryPrivateKey,
  required Map<String, dynamic> rawPackage,
}) async {
  if (expectedLinkId <= 0 ||
      rawPackage['crypto_version'] != inheritanceMvkCryptoVersion ||
      rawPackage['beneficiary_link_id'] != expectedLinkId) {
    throw const FormatException('Inheritance package context mismatch');
  }
  final sk = await beneficiaryPrivateKey.extractBytes();
  if (sk.length != 32) {
    throw const FormatException('Invalid beneficiary private key');
  }
  final eph = _decodeField(rawPackage, 'wrapping_ephemeral_pk', 32);
  final wrappingNonce = _decodeField(rawPackage, 'wrapping_nonce', 12);
  final wrapped = _decodeField(rawPackage, 'wrapped_key', 48);
  final payloadNonce = _decodeField(rawPackage, 'payload_nonce', 12);
  final encrypted = _decodeField(rawPackage, 'encrypted_payload', null);
  if (encrypted.length < 32 || encrypted.length > 65536) {
    throw const FormatException('Invalid encrypted inheritance payload');
  }
  final x25519 = X25519();
  final keyPair = await x25519.newKeyPairFromSeed(sk);
  final shared = await x25519.sharedSecretKey(
    keyPair: keyPair,
    remotePublicKey: SimplePublicKey(eph, type: KeyPairType.x25519),
  );
  final wrapKey = await _hkdf.deriveKey(
    secretKey: shared,
    nonce: eph,
    info: utf8.encode(_info),
  );
  final cek = await _aes.decrypt(
    _box(wrapped, wrappingNonce),
    secretKey: wrapKey,
  );
  if (cek.length != 32) throw const FormatException('Invalid wrapped key');
  final clear = await _aes.decrypt(
    _box(encrypted, payloadNonce),
    secretKey: SecretKey(cek),
  );
  final decoded = jsonDecode(utf8.decode(clear));
  if (decoded is! Map ||
      decoded['version'] != inheritanceMvkCryptoVersion ||
      decoded['beneficiary_link_id'] != expectedLinkId ||
      decoded['owner_vault_id'] is! String ||
      (decoded['owner_vault_id'] as String).isEmpty ||
      decoded.containsKey('pin') ||
      decoded.containsKey('username')) {
    throw const FormatException('Invalid inheritance key payload');
  }
  final mvk = _decode(decoded['mvk']);
  if (mvk.length != 32) {
    throw const FormatException('Invalid inherited vault key');
  }
  return DecryptedInheritanceMvk(
    beneficiaryLinkId: expectedLinkId,
    ownerVaultId: decoded['owner_vault_id'] as String,
    ownerMvk: SecretKey(mvk),
  );
}

Uint8List _randomBytes(Random rng, int length) =>
    Uint8List.fromList(List<int>.generate(length, (_) => rng.nextInt(256)));

String _b64(List<int> bytes) => base64Url.encode(bytes).replaceAll('=', '');

Uint8List _decode(Object? value) {
  if (value is! String ||
      value.isEmpty ||
      !RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(value)) {
    throw const FormatException('Invalid inheritance package field');
  }
  final decoded = base64Url.decode(value + '=' * ((4 - value.length % 4) % 4));
  if (_b64(decoded) != value) {
    throw const FormatException('Noncanonical inheritance package field');
  }
  return Uint8List.fromList(decoded);
}

Uint8List _decodeField(Map<String, dynamic> package, String key, int? length) {
  final value = _decode(package[key]);
  if (length != null && value.length != length) {
    throw const FormatException('Invalid inheritance package length');
  }
  return value;
}

SecretBox _box(Uint8List encrypted, Uint8List nonce) {
  if (encrypted.length < 16) {
    throw const FormatException('Inheritance ciphertext too short');
  }
  return SecretBox(
    encrypted.sublist(0, encrypted.length - 16),
    nonce: nonce,
    mac: Mac(encrypted.sublist(encrypted.length - 16)),
  );
}
