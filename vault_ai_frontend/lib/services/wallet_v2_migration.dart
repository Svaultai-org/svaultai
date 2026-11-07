// Wallet secret migration is local to the owner device. The server receives
// only an opaque MVK-wrapped envelope and never a PIN, key or wallet secret.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'legacy_ciphertext_export_client.dart';
import 'vault_key_hierarchy.dart';

const walletV2SecretSchema = 'vaultai.wallet.secret.v2';

/// Legacy wallet-engine JSON stored a display label, while route/service
/// identity uses a canonical network ID. Accept only the exact known labels.
String? canonicalWalletNetwork(String value) {
  final normalized = value.trim().toLowerCase().replaceAll(RegExp(r'[ -]+'), '_');
  switch (normalized) {
    case 'ethereum_mainnet':
    case 'ethereum_sepolia':
    case 'solana_mainnet':
    case 'tron_mainnet':
    case 'monero_mainnet':
      return normalized;
    case 'solana':
      return 'solana_mainnet';
    case 'tron':
      return 'tron_mainnet';
    case 'monero':
    case 'xmr':
      return 'monero_mainnet';
    default:
      return null;
  }
}

typedef WalletV2Post = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> body,
);
typedef WalletV2Get = Future<Map<String, dynamic>> Function(String path);

class WalletV2Identity {
  final String recordId;
  final String chain;
  final String network;
  final String asset;
  final String publicAddress;
  final String label;

  const WalletV2Identity({
    required this.recordId,
    required this.chain,
    required this.network,
    required this.asset,
    required this.publicAddress,
    required this.label,
  });

  void validate() {
    if (!RegExp(r'^[A-Za-z0-9_-]{16,128}$').hasMatch(recordId) ||
        !const {'evm', 'solana', 'tron', 'monero'}.contains(chain) ||
        network.isEmpty ||
        asset.isEmpty ||
        publicAddress.isEmpty ||
        label.isEmpty) {
      throw const FormatException('Invalid wallet identity');
    }
  }
}

class WalletV2EnvelopeCodec {
  final SecretKey mvk;

  const WalletV2EnvelopeCodec(this.mvk);

  Future<String> wrap(
    WalletV2Identity identity,
    String secret, {
    Map<String, dynamic> legacyRecord = const {},
  }) async {
    identity.validate();
    if (secret.isEmpty) throw const FormatException('Empty wallet secret');
    final key = await VaultKeyHierarchy(mvk).walletWrapKey();
    final payload = utf8.encode(jsonEncode({
      'schema': walletV2SecretSchema,
      'wallet_record_id': identity.recordId,
      'chain': identity.chain,
      'network': identity.network,
      'asset': identity.asset,
      'public_address': identity.publicAddress,
      'wallet_label': identity.label,
      'secret': secret,
      'legacy_record': legacyRecord,
    }));
    return base64Url.encode(await aesGcmWrap(key, payload)).replaceAll('=', '');
  }

  Future<WalletV2Decrypted> unwrap(
      WalletV2Identity identity, String ciphertext) async {
    identity.validate();
    final bytes = base64Url.decode(base64Url.normalize(ciphertext));
    final key = await VaultKeyHierarchy(mvk).walletWrapKey();
    final decoded = jsonDecode(utf8.decode(
      await aesGcmUnwrap(key, Uint8List.fromList(bytes)),
    ));
    if (decoded is! Map<String, dynamic> ||
        decoded['schema'] != walletV2SecretSchema ||
        decoded['wallet_record_id'] != identity.recordId ||
        decoded['chain'] != identity.chain ||
        decoded['network'] != identity.network ||
        decoded['asset'] != identity.asset ||
        decoded['public_address'] != identity.publicAddress ||
        decoded['wallet_label'] != identity.label ||
        decoded['secret'] is! String ||
        (decoded['secret'] as String).isEmpty ||
        decoded['legacy_record'] is! Map<String, dynamic>) {
      throw const FormatException('Wallet envelope identity mismatch');
    }
    return WalletV2Decrypted(
      secret: decoded['secret'] as String,
      legacyRecord: decoded['legacy_record'] as Map<String, dynamic>,
    );
  }
}

class WalletV2Decrypted {
  final String secret;
  final Map<String, dynamic> legacyRecord;

  const WalletV2Decrypted({required this.secret, required this.legacyRecord});
}

class WalletV2MigrationClient {
  final WalletV2EnvelopeCodec codec;
  final WalletV2Post post;
  final WalletV2Get get;
  final Future<String> Function() proofProvider;
  final Future<String> Function(String legacyItemCiphertext) decryptLegacyItem;
  final Future<String> Function(String legacySecretCiphertext)
      decryptLegacySecret;
  final Future<bool> Function(String secret, String publicAddress)
      secretMatchesAddress;
  final bool Function() accessIsCurrent;

  const WalletV2MigrationClient({
    required this.codec,
    required this.post,
    required this.get,
    required this.proofProvider,
    required this.decryptLegacyItem,
    required this.decryptLegacySecret,
    required this.secretMatchesAddress,
    required this.accessIsCurrent,
  });

  void _checkAccess() {
    if (!accessIsCurrent()) throw StateError('Wallet access changed');
  }

  /// Returns a verified V2 secret only to the local signer. Pending staged
  /// records never become a wallet source, even if their ciphertext decrypts.
  Future<WalletV2Decrypted> readVerified(WalletV2Identity identity) async {
    identity.validate();
    _checkAccess();
    final row = await get('/vault/wallet-v2/${identity.recordId}');
    _checkAccess();
    if (row['migration_state'] != 'v2_verified' ||
        row['envelope_version'] != 'v2' ||
        row['wallet_record_id'] != identity.recordId ||
        row['chain'] != identity.chain ||
        row['network'] != identity.network ||
        row['asset'] != identity.asset ||
        row['public_address'] != identity.publicAddress ||
        row['wallet_label'] != identity.label ||
        row['payload_ciphertext'] is! String) {
      throw const FormatException('Verified wallet record mismatch');
    }
    final decoded = await codec.unwrap(
      identity,
      row['payload_ciphertext'] as String,
    );
    _checkAccess();
    if (!await secretMatchesAddress(decoded.secret, identity.publicAddress)) {
      throw const FormatException('Wallet secret does not match address');
    }
    return decoded;
  }

  /// Prepare an exact, locally verified V2 copy without retiring the source.
  /// A prepared wallet is pending and cannot be used for receiving or signing.
  Future<String> prepareLegacy({
    required int legacyItemId,
    required LegacyCiphertextSource source,
    required WalletV2Identity identity,
  }) => _stageOrMigrateLegacy(
    legacyItemId: legacyItemId,
    source: source,
    identity: identity,
    retire: false,
  );

  /// Stages, reads back, locally decrypts, then retires one exact legacy row.
  /// Any failure before retirement leaves the legacy source intact.
  Future<String> migrateLegacy({
    required int legacyItemId,
    required LegacyCiphertextSource source,
    required WalletV2Identity identity,
  }) => _stageOrMigrateLegacy(
    legacyItemId: legacyItemId,
    source: source,
    identity: identity,
    retire: true,
  );

  Future<String> _stageOrMigrateLegacy({
    required int legacyItemId,
    required LegacyCiphertextSource source,
    required WalletV2Identity identity,
    required bool retire,
  }) async {
    identity.validate();
    _checkAccess();
    if (legacyItemId <= 0 ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(source.sourceSnapshot) ||
        source.sourceMetadata['item_type'] != 'crypto_wallet_account') {
      throw const FormatException('Invalid legacy wallet source');
    }
    // Wallet-engine records store structural outer JSON directly, with the
    // wallet secret encrypted inside it. A distinct legacy item variant may
    // instead wrap the whole JSON in a PIN-key envelope; only that variant
    // calls the owner's local outer decryptor.
    final outer = source.ciphertext.trimLeft().startsWith('{')
        ? source.ciphertext
        : await decryptLegacyItem(source.ciphertext);
    final legacy = jsonDecode(outer);
    _checkAccess();
    if (legacy is! Map<String, dynamic> ||
        legacy['schema'] != 'crypto_wallet_account_v1' ||
        legacy['asset'] != identity.asset ||
        legacy['network'] is! String ||
        canonicalWalletNetwork(legacy['network'] as String) != identity.network ||
        legacy['publicAddress'] != identity.publicAddress ||
        legacy['walletLabel'] != identity.label ||
        legacy['encryptedWalletSecret'] is! String ||
        (legacy['encryptedWalletSecret'] as String).isEmpty) {
      throw const FormatException('Legacy wallet identity mismatch');
    }
    final secret =
        await decryptLegacySecret(legacy['encryptedWalletSecret'] as String);
    _checkAccess();
    if (secret.isEmpty ||
        !await secretMatchesAddress(secret, identity.publicAddress)) {
      throw const FormatException('Wallet secret does not match address');
    }
    final preserved = Map<String, dynamic>.from(legacy)
      ..remove('encryptedWalletSecret');
    // A previous attempt may have staged this wallet and stopped before the
    // proof-gated retirement. Reuse its exact record/envelope when the legacy
    // source is unchanged; a fresh AES-GCM nonce or record ID would conflict
    // with the unique account slot and leave the old stage hidden.
    final pendingResponse = await get('/vault/wallet-v2/pending');
    _checkAccess();
    final pendingRows = pendingResponse['wallets'];
    if (pendingRows is! List ||
        pendingRows.any((row) => row is! Map<String, dynamic>)) {
      throw const FormatException('Invalid pending wallet list');
    }
    final matching = pendingRows.cast<Map<String, dynamic>>().where((row) =>
        row['legacy_item_id'] == legacyItemId ||
        (row['chain'] == identity.chain &&
         row['network'] == identity.network &&
         row['asset'] == identity.asset)).toList(growable: false);
    if (matching.length > 1) {
      throw const FormatException('Conflicting pending wallet migrations');
    }
    var activeIdentity = identity;
    Map<String, dynamic>? previousReadback;
    if (matching.isNotEmpty) {
      final row = matching.single;
      if (row['migration_state'] != 'migration_pending' ||
          row['legacy_item_id'] != legacyItemId ||
          row['chain'] != identity.chain ||
          row['network'] != identity.network ||
          row['asset'] != identity.asset ||
          row['public_address'] != identity.publicAddress ||
          row['wallet_label'] != identity.label ||
          row['legacy_source_snapshot'] is! String) {
        throw const FormatException('Pending wallet migration mismatch');
      }
      activeIdentity = WalletV2Identity(
        recordId: row['wallet_record_id']?.toString() ?? '',
        chain: identity.chain,
        network: identity.network,
        asset: identity.asset,
        publicAddress: identity.publicAddress,
        label: identity.label,
      );
      activeIdentity.validate();
      if (row['legacy_source_snapshot'] == source.sourceSnapshot) {
        previousReadback =
            await get('/vault/wallet-v2/${activeIdentity.recordId}');
        _checkAccess();
      }
    }
    final ciphertext = previousReadback == null
        ? await codec.wrap(activeIdentity, secret, legacyRecord: preserved)
        : previousReadback['payload_ciphertext'];
    if (ciphertext is! String) {
      throw const FormatException('Pending wallet ciphertext missing');
    }
    _checkAccess();
    if (previousReadback == null) {
      final staged = await post('/vault/wallet-v2/migrate/stage', {
        'legacy_item_id': legacyItemId,
        'source_snapshot': source.sourceSnapshot,
        'wallet_record_id': activeIdentity.recordId,
        'chain': activeIdentity.chain,
        'network': activeIdentity.network,
        'asset': activeIdentity.asset,
        'public_address': activeIdentity.publicAddress,
        'wallet_label': activeIdentity.label,
        'payload_ciphertext': ciphertext,
        'envelope_version': 'v2',
      });
      _checkAccess();
      if (staged['migration_state'] != 'migration_pending' ||
          staged['wallet_record_id'] != activeIdentity.recordId) {
        throw const FormatException('Invalid wallet stage response');
      }
    }
    final readback = previousReadback ??
        await get('/vault/wallet-v2/${activeIdentity.recordId}');
    _checkAccess();
    if (readback['migration_state'] != 'migration_pending' ||
        readback['envelope_version'] != 'v2' ||
        readback['wallet_record_id'] != activeIdentity.recordId ||
        readback['chain'] != activeIdentity.chain ||
        readback['network'] != activeIdentity.network ||
        readback['asset'] != activeIdentity.asset ||
        readback['public_address'] != activeIdentity.publicAddress ||
        readback['wallet_label'] != activeIdentity.label ||
        readback['payload_ciphertext'] != ciphertext ||
        readback['legacy_item_id'] != legacyItemId ||
        readback['legacy_source_snapshot'] != source.sourceSnapshot ||
        readback['readback_receipt'] is! String) {
      throw const FormatException('Wallet readback mismatch');
    }
    final verified = await codec.unwrap(activeIdentity, ciphertext);
    _checkAccess();
    if (verified.secret != secret ||
        jsonEncode(verified.legacyRecord) != jsonEncode(preserved) ||
        !await secretMatchesAddress(
            verified.secret, activeIdentity.publicAddress)) {
      throw const FormatException('Wallet readback verification failed');
    }
    // Preparation must not request a retirement proof or remove the legacy
    // wallet. The verified pending ciphertext can be resumed later.
    if (!retire) return activeIdentity.recordId;
    final proof = await proofProvider();
    _checkAccess();
    if (proof.isEmpty) throw StateError('Wallet proof unavailable');
    final retired = await post('/vault/wallet-v2/migrate/retire', {
      'legacy_item_id': legacyItemId,
      'wallet_record_id': activeIdentity.recordId,
      'source_snapshot': source.sourceSnapshot,
      'readback_receipt': readback['readback_receipt'],
      'zk_proof_token': proof,
      'client_verified_exact_bytes': true,
    });
    _checkAccess();
    if (retired['retired'] != true ||
        retired['wallet_record_id'] != activeIdentity.recordId) {
      throw const FormatException('Wallet retirement was not confirmed');
    }
    return activeIdentity.recordId;
  }
}
