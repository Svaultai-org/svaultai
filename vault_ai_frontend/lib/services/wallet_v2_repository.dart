import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import '../api_client.dart';
import 'vault_key_hierarchy.dart';
import 'zk_active_mvk.dart';

class WalletV2Envelope {
  const WalletV2Envelope(
      {required this.walletRecordId,
      required this.chain,
      required this.network,
      required this.asset,
      required this.publicAddress,
      required this.walletLabel,
      required this.payloadCiphertext,
      required this.envelopeVersion,
      required this.migrationState});
  final String walletRecordId;
  final String chain;
  final String network;
  final String asset;
  final String publicAddress;
  final String walletLabel;
  final Uint8List payloadCiphertext;
  final String envelopeVersion;
  final String migrationState;
}

class WalletV2Crypto {
  WalletV2Crypto(this._mvk);

  final SecretKey _mvk;

  Future<SecretKey> _recordKey(String id) async =>
      Hkdf(hmac: Hmac.sha256(), outputLength: 32).deriveKey(
        secretKey: await VaultKeyHierarchy(_mvk).walletWrapKey(),
        nonce: utf8.encode(id),
        info: utf8.encode('vaultai.wallet.record.v2'),
      );

  List<int> _aad(String id, String chain) =>
      utf8.encode('svaultai|client_mvk_v2|wallet|$id|$chain|v2');

  Future<Uint8List> encrypt({
    required String walletRecordId,
    required String chain,
    required Map<String, dynamic> secretPayload,
  }) async {
    final plaintext = utf8.encode(jsonEncode({
      'version': 2,
      'chain': chain,
      'secretMaterial': secretPayload,
    }));
    return aesGcmWrapWithAad(await _recordKey(walletRecordId), plaintext,
        aad: _aad(walletRecordId, chain));
  }

  Future<Map<String, dynamic>> decrypt(WalletV2Envelope envelope) async {
    if (envelope.envelopeVersion != 'v2') {
      throw StateError('wallet_v2_version');
    }
    final raw = await aesGcmUnwrapWithAad(
      await _recordKey(envelope.walletRecordId),
      envelope.payloadCiphertext,
      aad: _aad(envelope.walletRecordId, envelope.chain),
    );
    final decoded = jsonDecode(utf8.decode(raw));
    if (decoded is! Map<String, dynamic> ||
        decoded['version'] != 2 ||
        decoded['chain'] != envelope.chain ||
        decoded['secretMaterial'] is! Map) {
      throw StateError('wallet_v2_payload_invalid');
    }
    return Map<String, dynamic>.from(decoded['secretMaterial'] as Map);
  }
}

class WalletV2Repository {
  WalletV2Repository._(this._api, this._authToken, this._mvk);
  final VaultAIClient _api;
  final String _authToken;
  final SecretKey _mvk;
  static WalletV2Repository? _active;

  static WalletV2Repository? current(
      {required VaultAIClient api, required String authToken}) {
    final mvk = ZkActiveMvk.current();
    if (mvk == null) {
      _active = null;
      return null;
    }
    if (_active == null ||
        _active!._api != api ||
        _active!._authToken != authToken ||
        _active!._mvk != mvk) {
      _active = WalletV2Repository._(api, authToken, mvk);
    }
    return _active;
  }

  static void clear() => _active = null;

  String _id() => base64Url
      .encode(List<int>.generate(24, (_) => Random.secure().nextInt(256)))
      .replaceAll('=', '');

  Future<String> create(
      {required String chain,
      required String network,
      required String asset,
      required String publicAddress,
      required String walletLabel,
      required Map<String, dynamic> secretPayload,
      String migrationState = 'v2_verified'}) async {
    if (!const {'evm', 'solana', 'tron', 'monero'}.contains(chain)) {
      throw ArgumentError.value(chain, 'chain');
    }
    final id = _id();
    final ciphertext = await WalletV2Crypto(_mvk).encrypt(
      walletRecordId: id,
      chain: chain,
      secretPayload: secretPayload,
    );
    await _api.createWalletV2(
        authToken: _authToken,
        walletRecordId: id,
        chain: chain,
        network: network,
        asset: asset,
        publicAddress: publicAddress,
        walletLabel: walletLabel,
        payloadCiphertext: ciphertext,
        migrationState: migrationState);
    return id;
  }

  Future<List<Map<String, dynamic>>> list() =>
      _api.listWalletV2(authToken: _authToken);

  Future<WalletV2Envelope> read(String id) async {
    final row =
        await _api.readWalletV2(authToken: _authToken, walletRecordId: id);
    return WalletV2Envelope(
        walletRecordId: row['wallet_record_id'] as String,
        chain: row['chain'] as String,
        network: row['network'] as String,
        asset: row['asset'] as String,
        publicAddress: row['public_address'] as String,
        walletLabel: row['wallet_label'] as String,
        payloadCiphertext: b64urlDecode(row['payload_ciphertext'] as String),
        envelopeVersion: row['envelope_version'] as String,
        migrationState: row['migration_state'] as String);
  }

  Future<WalletV2Envelope?> find(
      {required String chain, required String publicAddress}) async {
    for (final row in await list()) {
      if (row['chain'] == chain && row['public_address'] == publicAddress) {
        return read(row['wallet_record_id'] as String);
      }
    }
    return null;
  }

  Future<Map<String, dynamic>> decrypt(WalletV2Envelope envelope) =>
      WalletV2Crypto(_mvk).decrypt(envelope);

  Future<String> migrateLegacy({
    required String chain,
    required String network,
    required String asset,
    required String publicAddress,
    required String walletLabel,
    required Future<Map<String, dynamic>> Function() decryptLegacyLocally,
  }) async {
    const enabled = bool.fromEnvironment(
      'WALLET_V2_MIGRATION_ENABLED',
      defaultValue: false,
    );
    if (!enabled) throw StateError('wallet_v2_migration_disabled');
    final secret = await decryptLegacyLocally();
    final verificationId = _id();
    final crypto = WalletV2Crypto(_mvk);
    final verificationCiphertext = await crypto.encrypt(
      walletRecordId: verificationId,
      chain: chain,
      secretPayload: secret,
    );
    final verified = await crypto.decrypt(WalletV2Envelope(
      walletRecordId: verificationId,
      chain: chain,
      network: network,
      asset: asset,
      publicAddress: publicAddress,
      walletLabel: walletLabel,
      payloadCiphertext: verificationCiphertext,
      envelopeVersion: 'v2',
      migrationState: 'migration_pending',
    ));
    if (jsonEncode(verified) != jsonEncode(secret)) {
      throw StateError('wallet_v2_migration_verification_failed');
    }
    return create(
      chain: chain,
      network: network,
      asset: asset,
      publicAddress: publicAddress,
      walletLabel: walletLabel,
      secretPayload: secret,
      migrationState: 'v2_verified',
    );
  }

  Future<void> delete(String id) =>
      _api.deleteWalletV2(authToken: _authToken, walletRecordId: id);
}
