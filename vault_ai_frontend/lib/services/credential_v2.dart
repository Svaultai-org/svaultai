import 'dart:convert';
import 'dart:math' show Random;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';

const String credentialV2CryptoVersion = 'client_mvk_v2';
const String credentialV2CipherSuite = 'aes_256_gcm_v1';
const String credentialV2KeyDomain = 'credential';
const String _recordInfo = 'vaultai.credential.record.v2';
const int credentialV2NonceBytes = 12;
const int credentialV2TagBytes = 16;

final Hkdf _recordHkdf = Hkdf(hmac: Hmac.sha256(), outputLength: 32);
final AesGcm _aesGcm = AesGcm.with256bits();

class CredentialV2Plaintext {
  final String service;
  final String username;
  final String password;
  final String? url;
  final String? notes;
  final String? totpSecret;
  final Map<String, String> customFields;

  const CredentialV2Plaintext({
    required this.service,
    required this.username,
    required this.password,
    this.url,
    this.notes,
    this.totpSecret,
    this.customFields = const {},
  });

  Map<String, dynamic> toJson() => <String, dynamic>{
        'service': service,
        'username': username,
        'password': password,
        if (url != null) 'url': url,
        if (notes != null) 'notes': notes,
        if (totpSecret != null) 'totp_secret': totpSecret,
        'custom_fields': customFields,
      };

  static CredentialV2Plaintext fromJson(Map<String, dynamic> json) {
    final fields = json['custom_fields'];
    if (fields is! Map) throw const FormatException('invalid custom fields');
    return CredentialV2Plaintext(
      service: json['service'] as String,
      username: json['username'] as String,
      password: json['password'] as String,
      url: json['url'] as String?,
      notes: json['notes'] as String?,
      totpSecret: json['totp_secret'] as String?,
      customFields: fields.map(
        (key, value) => MapEntry(key.toString(), value as String),
      ),
    );
  }

  bool semanticallyEquals(CredentialV2Plaintext other) =>
      jsonEncode(toJson()) == jsonEncode(other.toJson());
}

class CredentialV2Envelope {
  final String recordId;
  final String nonce;
  final String ciphertext;
  final String authenticationTag;
  final Map<String, String> blindIndexes;

  const CredentialV2Envelope({
    required this.recordId,
    required this.nonce,
    required this.ciphertext,
    required this.authenticationTag,
    required this.blindIndexes,
  });

  Map<String, dynamic> toRequestBody({String? migrationOperationId}) => {
        'record_id': recordId,
        'crypto_version': credentialV2CryptoVersion,
        'cipher_suite': credentialV2CipherSuite,
        'key_domain': credentialV2KeyDomain,
        'nonce': nonce,
        'ciphertext': ciphertext,
        'authentication_tag': authenticationTag,
        'blind_indexes': blindIndexes,
        if (migrationOperationId != null)
          'migration_operation_id': migrationOperationId,
      };

  static CredentialV2Envelope fromResponse(Map<String, dynamic> json) {
    if (json['crypto_version'] != credentialV2CryptoVersion) {
      throw const FormatException('unsupported credential crypto version');
    }
    if (json['cipher_suite'] != credentialV2CipherSuite) {
      throw const FormatException('unsupported credential cipher suite');
    }
    if (json['key_domain'] != credentialV2KeyDomain) {
      throw const FormatException('wrong credential key domain');
    }
    return CredentialV2Envelope(
      recordId: json['record_id'] as String,
      nonce: json['nonce'] as String,
      ciphertext: json['ciphertext'] as String,
      authenticationTag: json['authentication_tag'] as String,
      blindIndexes: (json['blind_indexes'] as Map).map(
        (key, value) => MapEntry(key.toString(), value as String),
      ),
    );
  }
}

class CredentialV2Crypto {
  final VaultKeyHierarchy hierarchy;
  final Random _random;

  CredentialV2Crypto(this.hierarchy, {Random? randomForTest})
      : _random = randomForTest ?? Random.secure();

  Future<SecretKey> _recordKey(String recordId) async {
    _validateRecordId(recordId);
    return _recordHkdf.deriveKey(
      secretKey: await hierarchy.credentialKey(),
      nonce: utf8.encode(recordId),
      info: utf8.encode(_recordInfo),
    );
  }

  static List<int> _aad(String recordId) => utf8.encode(
      'svaultai|$credentialV2CryptoVersion|$credentialV2KeyDomain|$recordId');

  Future<CredentialV2Envelope> encrypt({
    required String recordId,
    required CredentialV2Plaintext plaintext,
    String? serviceForLookup,
  }) async {
    _validateRecordId(recordId);
    final nonce = Uint8List.fromList(
      List<int>.generate(credentialV2NonceBytes, (_) => _random.nextInt(256)),
    );
    final box = await _aesGcm.encrypt(
      utf8.encode(jsonEncode(plaintext.toJson())),
      secretKey: await _recordKey(recordId),
      nonce: nonce,
      aad: _aad(recordId),
    );
    final indexes = <String, String>{};
    if (serviceForLookup != null && serviceForLookup.trim().isNotEmpty) {
      indexes['service'] = await blindIndex('service', serviceForLookup);
    }
    if (plaintext.username.trim().isNotEmpty) {
      indexes['username'] = await blindIndex('username', plaintext.username);
    }
    final host = _normalizedUrlHost(plaintext.url);
    if (host != null) indexes['url_host'] = await blindIndex('url_host', host);
    return CredentialV2Envelope(
      recordId: recordId,
      nonce: b64urlEncode(nonce),
      ciphertext: b64urlEncode(box.cipherText),
      authenticationTag: b64urlEncode(box.mac.bytes),
      blindIndexes: indexes,
    );
  }

  Future<CredentialV2Plaintext> decrypt(CredentialV2Envelope envelope) async {
    _validateRecordId(envelope.recordId);
    final nonce = b64urlDecode(envelope.nonce);
    final tag = b64urlDecode(envelope.authenticationTag);
    if (nonce.length != credentialV2NonceBytes ||
        tag.length != credentialV2TagBytes) {
      throw const FormatException('invalid credential envelope lengths');
    }
    final clear = await _aesGcm.decrypt(
      SecretBox(
        b64urlDecode(envelope.ciphertext),
        nonce: nonce,
        mac: Mac(tag),
      ),
      secretKey: await _recordKey(envelope.recordId),
      aad: _aad(envelope.recordId),
    );
    final decoded = jsonDecode(utf8.decode(clear));
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('invalid credential payload');
    }
    return CredentialV2Plaintext.fromJson(decoded);
  }

  Future<String> blindIndex(String field, String value) async {
    if (!const {'service', 'username', 'url_host'}.contains(field)) {
      throw ArgumentError('unsupported credential blind-index field');
    }
    final normalized = normalizeExactLookup(value);
    final token = await keyedLookupHash(
      await hierarchy.credentialLookupKey(),
      utf8.encode('$field\u0000$normalized'),
    );
    return b64urlEncode(token);
  }
}

String normalizeExactLookup(String value) =>
    value.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');

String? _normalizedUrlHost(String? value) {
  if (value == null || value.trim().isEmpty) return null;
  final candidate = value.contains('://') ? value : 'https://$value';
  final uri = Uri.tryParse(candidate);
  return uri == null || uri.host.isEmpty ? null : uri.host.toLowerCase();
}

void _validateRecordId(String recordId) {
  if (!RegExp(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$').hasMatch(recordId)) {
    throw ArgumentError('invalid credential record ID');
  }
}
