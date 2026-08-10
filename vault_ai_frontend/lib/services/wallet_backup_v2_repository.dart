import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import '../api_client.dart';
import 'vault_key_hierarchy.dart';
import 'zk_active_mvk.dart';

class WalletBackupV2Envelope {
  const WalletBackupV2Envelope(
      {required this.backupRecordId,
      required this.secretType,
      required this.payloadCiphertext,
      required this.envelopeVersion});
  final String backupRecordId;
  final String secretType;
  final Uint8List payloadCiphertext;
  final String envelopeVersion;
}

/// Client-owned WalletBackupV2 encryption and opaque persistence lifecycle.
class WalletBackupV2Repository {
  WalletBackupV2Repository._(this._api, this._authToken, this._mvk);

  final VaultAIClient _api;
  final String _authToken;
  final SecretKey _mvk;
  static WalletBackupV2Repository? _active;

  static WalletBackupV2Repository? current({
    required VaultAIClient api,
    required String authToken,
  }) {
    final mvk = ZkActiveMvk.current();
    if (mvk == null) {
      _active = null;
      return null;
    }
    return _active ??= WalletBackupV2Repository._(api, authToken, mvk);
  }

  static void clear() => _active = null;

  static const supportedSecretTypes = <String>{
    'private_key',
    'seed_phrase',
    'recovery_phrase'
  };

  Future<SecretKey> _recordKey(String recordId) async {
    final hierarchy = VaultKeyHierarchy(_mvk);
    final domain = await hierarchy.walletBackupKey();
    return Hkdf(hmac: Hmac.sha256(), outputLength: 32).deriveKey(
      secretKey: domain,
      nonce: utf8.encode(recordId),
      info: utf8.encode('vaultai.wallet.backup.record.v2'),
    );
  }

  List<int> _aad(String id, String type, String version) =>
      utf8.encode('svaultai|client_mvk_v2|wallet_backup|$id|$type|$version');

  String _newOpaqueId() {
    final random = Random.secure();
    final bytes = List<int>.generate(24, (_) => random.nextInt(256));
    return base64Url.encode(bytes).replaceAll('=', '');
  }

  Future<String> create(
      {required String secretType, required String secretPlaintext}) async {
    if (!supportedSecretTypes.contains(secretType)) {
      throw ArgumentError.value(secretType, 'secretType', 'unsupported');
    }
    final id = _newOpaqueId();
    const version = 'client_mvk_v2';
    final ciphertext = await aesGcmWrapWithAad(
      await _recordKey(id),
      utf8.encode(secretPlaintext),
      aad: _aad(id, secretType, version),
    );
    await _api.createWalletBackupV2(
        authToken: _authToken,
        backupRecordId: id,
        secretType: secretType,
        payloadCiphertext: ciphertext);
    return id;
  }

  Future<List<Map<String, dynamic>>> list() =>
      _api.listWalletBackupV2(authToken: _authToken);

  Future<WalletBackupV2Envelope> read(String backupRecordId) async {
    final row = await _api.readWalletBackupV2(
        authToken: _authToken, backupRecordId: backupRecordId);
    return WalletBackupV2Envelope(
      backupRecordId: row['backup_record_id'] as String,
      secretType: row['secret_type'] as String,
      payloadCiphertext: b64urlDecode(row['payload_ciphertext'] as String),
      envelopeVersion: row['envelope_version'] as String,
    );
  }

  Future<String> decrypt(WalletBackupV2Envelope envelope) async {
    if (envelope.envelopeVersion != 'client_mvk_v2') {
      throw StateError('wallet_backup_v2_unknown_envelope');
    }
    final plaintext = await aesGcmUnwrapWithAad(
      await _recordKey(envelope.backupRecordId),
      envelope.payloadCiphertext,
      aad: _aad(envelope.backupRecordId, envelope.secretType,
          envelope.envelopeVersion),
    );
    return utf8.decode(plaintext);
  }

  Future<void> delete(String backupRecordId) => _api.deleteWalletBackupV2(
      authToken: _authToken, backupRecordId: backupRecordId);
}
