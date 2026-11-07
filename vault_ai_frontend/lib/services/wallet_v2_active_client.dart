// Active V2 wallet access. Secret unwrap and address validation happen only
// on the owner device. The server receives metadata and MVK ciphertext.

import 'dart:convert';
import 'dart:math';

import 'wallet_v2_migration.dart';
import 'wallet_v2_secret_validation.dart';

typedef WalletV2SecretValidator = Future<bool> Function(
  String chain,
  String secret,
  String address,
);

class WalletV2AccountSlot {
  final String chain;
  final String network;
  final String asset;

  const WalletV2AccountSlot(this.chain, this.network, this.asset);

  void validate() {
    final allowed = switch (chain) {
      'evm' =>
        (network == 'ethereum_mainnet' || network == 'ethereum_sepolia') &&
            asset == 'ETH',
      'solana' => network == 'solana_mainnet' && asset == 'SOL',
      'tron' => network == 'tron_mainnet' && asset == 'USDT_TRC20',
      'monero' => network == 'monero_mainnet' && asset == 'XMR',
      _ => false,
    };
    if (!allowed) throw const FormatException('Unsupported wallet account');
  }
}

class WalletV2PendingStageError extends StateError {
  WalletV2PendingStageError()
      : super('An unfinished wallet setup needs recovery. '
            'No new wallet was created.');
}

class WalletV2PendingRecord {
  final WalletV2Identity identity;
  final int? legacyItemId;
  final String? legacySourceSnapshot;

  const WalletV2PendingRecord({
    required this.identity,
    required this.legacyItemId,
    required this.legacySourceSnapshot,
  });
}

class WalletV2ActiveClient {
  final WalletV2EnvelopeCodec codec;
  final WalletV2Post post;
  final WalletV2Get get;
  final bool Function() accessIsCurrent;
  final WalletV2SecretValidator secretMatchesAddress;
  final String Function() newRecordId;
  final bool creationEnabled;

  WalletV2ActiveClient({
    required this.codec,
    required this.post,
    required this.get,
    required this.accessIsCurrent,
    this.creationEnabled = false,
    WalletV2SecretValidator? secretMatchesAddress,
    String Function()? newRecordId,
  })  : secretMatchesAddress =
            secretMatchesAddress ?? walletV2SecretMatchesAddress,
        newRecordId = newRecordId ?? _secureRecordId;

  static String _secureRecordId() {
    final random = Random.secure();
    return base64Url
        .encode(List<int>.generate(24, (_) => random.nextInt(256)))
        .replaceAll('=', '');
  }

  void _checkAccess() {
    if (!accessIsCurrent()) throw StateError('Wallet access changed');
  }

  bool _sameSlot(Map<String, dynamic> row, WalletV2AccountSlot slot) =>
      row['chain'] == slot.chain &&
      row['network'] == slot.network &&
      row['asset'] == slot.asset &&
      row['migration_state'] == 'v2_verified';

  Future<List<Map<String, dynamic>>> _verifiedList() async {
    _checkAccess();
    final response = await get('/vault/wallet-v2');
    _checkAccess();
    final rows = response['wallets'];
    if (rows is! List) throw const FormatException('Invalid wallet list');
    return rows.map((row) {
      if (row is! Map<String, dynamic>) {
        throw const FormatException('Invalid wallet metadata');
      }
      return row;
    }).toList(growable: false);
  }

  /// The caller still checks the legacy Receive endpoint for an existing
  /// account. A V2 list alone cannot prove there is no old wallet.
  Future<WalletV2Identity?> findVerified(WalletV2AccountSlot slot) async {
    slot.validate();
    final matches = (await _verifiedList())
        .where((row) => _sameSlot(row, slot))
        .toList(growable: false);
    if (matches.length > 1) {
      throw const FormatException('Conflicting wallet records');
    }
    if (matches.isEmpty) return null;
    final row = matches.single;
    final identity = WalletV2Identity(
      recordId: row['wallet_record_id']?.toString() ?? '',
      chain: slot.chain,
      network: slot.network,
      asset: slot.asset,
      publicAddress: row['public_address']?.toString() ?? '',
      label: row['wallet_label']?.toString() ?? '',
    );
    identity.validate();
    return identity;
  }

  /// Pending rows are listed separately so receive and signing never treat
  /// an interrupted stage as a usable wallet.
  Future<WalletV2PendingRecord?> findPending(WalletV2AccountSlot slot) async {
    slot.validate();
    _checkAccess();
    final response = await get('/vault/wallet-v2/pending');
    _checkAccess();
    final rows = response['wallets'];
    if (rows is! List) throw const FormatException('Invalid pending wallet list');
    final matches = rows.where((row) => row is Map<String, dynamic> &&
        row['chain'] == slot.chain && row['network'] == slot.network &&
        row['asset'] == slot.asset).toList(growable: false);
    if (matches.length > 1) {
      throw const FormatException('Conflicting pending wallet records');
    }
    if (matches.isEmpty) return null;
    final row = matches.single as Map<String, dynamic>;
    final legacyItemId = row['legacy_item_id'];
    final snapshot = row['legacy_source_snapshot'];
    if (row['migration_state'] != 'migration_pending' ||
        (legacyItemId != null && (legacyItemId is! int || legacyItemId <= 0)) ||
        (snapshot != null && snapshot is! String) ||
        ((legacyItemId == null) != (snapshot == null))) {
      throw const FormatException('Invalid pending wallet metadata');
    }
    final identity = WalletV2Identity(
      recordId: row['wallet_record_id']?.toString() ?? '',
      chain: slot.chain,
      network: slot.network,
      asset: slot.asset,
      publicAddress: row['public_address']?.toString() ?? '',
      label: row['wallet_label']?.toString() ?? '',
    );
    identity.validate();
    return WalletV2PendingRecord(
      identity: identity,
      legacyItemId: legacyItemId as int?,
      legacySourceSnapshot: snapshot as String?,
    );
  }

  /// Continue the exact server-held MVK envelope after an interrupted create.
  /// No fresh key is generated and no pending ciphertext is deleted.
  Future<WalletV2Identity?> recoverPendingNew(WalletV2AccountSlot slot) async {
    if (!creationEnabled) throw StateError('Wallet V2 creation is disabled');
    slot.validate();
    _checkAccess();
    final verified = await findVerified(slot);
    if (verified != null) return verified;
    final pending = await findPending(slot);
    if (pending == null) return null;
    if (pending.legacyItemId != null) throw WalletV2PendingStageError();
    final identity = pending.identity;
    final readback = await get('/vault/wallet-v2/${identity.recordId}');
    _checkAccess();
    if (readback['wallet_record_id'] != identity.recordId ||
        readback['chain'] != identity.chain ||
        readback['network'] != identity.network ||
        readback['asset'] != identity.asset ||
        readback['public_address'] != identity.publicAddress ||
        readback['wallet_label'] != identity.label ||
        readback['migration_state'] != 'migration_pending' ||
        readback['envelope_version'] != 'v2' ||
        readback['legacy_item_id'] != null ||
        readback['legacy_source_snapshot'] != null ||
        readback['payload_ciphertext'] is! String ||
        readback['readback_receipt'] is! String) {
      throw const FormatException('Pending wallet readback mismatch');
    }
    final opened = await codec.unwrap(
      identity, readback['payload_ciphertext'] as String,
    );
    _checkAccess();
    if (opened.legacyRecord.isNotEmpty ||
        !await secretMatchesAddress(
        identity.chain, opened.secret, identity.publicAddress)) {
      throw const FormatException('Pending wallet address mismatch');
    }
    _checkAccess();
    final published = await post(
      '/vault/wallet-v2/${identity.recordId}/publish-new',
      {
        'readback_receipt': readback['readback_receipt'],
        'client_verified_exact_bytes': true,
      },
    );
    _checkAccess();
    if (published['wallet_record_id'] != identity.recordId ||
        published['migration_state'] != 'v2_verified') {
      throw const FormatException('Pending wallet publish mismatch');
    }
    final reread = await readSigningSecret(identity);
    _checkAccess();
    if (reread != opened.secret) {
      throw const FormatException('Published wallet bytes changed');
    }
    return identity;
  }

  Future<String> readSigningSecret(WalletV2Identity identity) async {
    WalletV2AccountSlot(identity.chain, identity.network, identity.asset)
        .validate();
    _checkAccess();
    final row = await get('/vault/wallet-v2/${identity.recordId}');
    _checkAccess();
    if (row['wallet_record_id'] != identity.recordId ||
        row['chain'] != identity.chain ||
        row['network'] != identity.network ||
        row['asset'] != identity.asset ||
        row['public_address'] != identity.publicAddress ||
        row['wallet_label'] != identity.label ||
        row['envelope_version'] != 'v2' ||
        row['migration_state'] != 'v2_verified' ||
        row['payload_ciphertext'] is! String) {
      throw const FormatException('Wallet record changed');
    }
    final opened = await codec.unwrap(
      identity,
      row['payload_ciphertext'] as String,
    );
    _checkAccess();
    if (!await secretMatchesAddress(
      identity.chain,
      opened.secret,
      identity.publicAddress,
    )) {
      throw const FormatException('Wallet secret/address mismatch');
    }
    _checkAccess();
    return opened.secret;
  }

  /// Signing and backup callers must bind the secret to the exact displayed
  /// account. A missing V2 row never falls back to a legacy PIN ciphertext.
  Future<String> readSigningSecretForAddress(
    WalletV2AccountSlot slot,
    String displayedAddress,
  ) async {
    final identity = await findVerified(slot);
    final matches = identity != null && (slot.chain == 'evm'
        ? identity.publicAddress.toLowerCase() == displayedAddress.toLowerCase()
        : identity.publicAddress == displayedAddress);
    if (!matches) {
      throw const FormatException('Verified wallet address mismatch');
    }
    return readSigningSecret(identity);
  }

  /// Stage only; publish after exact server readback, local decrypt, and
  /// independent secret-derived address validation. Any failure leaves a
  /// pending, unavailable ciphertext row rather than a usable wallet.
  Future<WalletV2Identity> createNew({
    required WalletV2AccountSlot slot,
    required String publicAddress,
    required String label,
    required String secret,
  }) async {
    if (!creationEnabled) throw StateError('Wallet V2 creation is disabled');
    slot.validate();
    _checkAccess();
    if (secret.isEmpty ||
        !await secretMatchesAddress(slot.chain, secret, publicAddress)) {
      throw const FormatException('Wallet secret/address mismatch');
    }
    _checkAccess();
    if (await findVerified(slot) != null) {
      throw StateError('Wallet already exists');
    }
    if (await findPending(slot) != null) {
      throw WalletV2PendingStageError();
    }
    final identity = WalletV2Identity(
      recordId: newRecordId(),
      chain: slot.chain,
      network: slot.network,
      asset: slot.asset,
      publicAddress: publicAddress,
      label: label,
    );
    identity.validate();
    final ciphertext = await codec.wrap(identity, secret);
    _checkAccess();
    final staged = await post('/vault/wallet-v2', {
      'wallet_record_id': identity.recordId,
      'chain': identity.chain,
      'network': identity.network,
      'asset': identity.asset,
      'public_address': identity.publicAddress,
      'wallet_label': identity.label,
      'payload_ciphertext': ciphertext,
      'envelope_version': 'v2',
      'migration_state': 'migration_pending',
    });
    _checkAccess();
    if (staged['wallet_record_id'] != identity.recordId ||
        staged['migration_state'] != 'migration_pending') {
      throw const FormatException('Wallet stage response mismatch');
    }
    final readback = await get('/vault/wallet-v2/${identity.recordId}');
    _checkAccess();
    if (readback['wallet_record_id'] != identity.recordId ||
        readback['chain'] != identity.chain ||
        readback['network'] != identity.network ||
        readback['asset'] != identity.asset ||
        readback['public_address'] != identity.publicAddress ||
        readback['wallet_label'] != identity.label ||
        readback['payload_ciphertext'] != ciphertext ||
        readback['envelope_version'] != 'v2' ||
        readback['migration_state'] != 'migration_pending' ||
        readback['legacy_item_id'] != null ||
        readback['readback_receipt'] is! String) {
      throw const FormatException('Wallet readback mismatch');
    }
    final opened = await codec.unwrap(identity, ciphertext);
    _checkAccess();
    if (opened.secret != secret ||
        !await secretMatchesAddress(
            slot.chain, opened.secret, identity.publicAddress)) {
      throw const FormatException('Wallet readback verification failed');
    }
    _checkAccess();
    final published = await post(
      '/vault/wallet-v2/${identity.recordId}/publish-new',
      {
        'readback_receipt': readback['readback_receipt'],
        'client_verified_exact_bytes': true,
      },
    );
    _checkAccess();
    if (published['wallet_record_id'] != identity.recordId ||
        published['migration_state'] != 'v2_verified') {
      throw const FormatException('Wallet publish response mismatch');
    }
    final reread = await readSigningSecret(identity);
    _checkAccess();
    if (reread != secret) {
      throw const FormatException('Wallet published bytes changed');
    }
    return identity;
  }
}
