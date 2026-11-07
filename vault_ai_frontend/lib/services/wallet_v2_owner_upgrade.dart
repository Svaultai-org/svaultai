// One explicit owner action to move older wallet ciphertext into MVK V2.
// The source remains on the server until local exact readback and a fresh
// OPAQUE proof authorize its atomic retirement.

import 'dart:convert';

import 'legacy_ciphertext_export_client.dart';
import 'legacy_ciphertext_migration_codec.dart';
import 'wallet_v2_active_client.dart';
import 'wallet_v2_migration.dart';

class WalletV2UpgradeResult {
  final int migrated;
  final int prepared;
  final int inspected;

  const WalletV2UpgradeResult({
    required this.migrated,
    this.prepared = 0,
    required this.inspected,
  });
}

class WalletV2OwnerUpgrade {
  final LegacyCiphertextExportClient export;
  final LegacyCiphertextMigrationCodec legacyCodec;
  final WalletV2ActiveClient wallet;
  final Future<String> Function() proofProvider;
  final bool Function() accessIsCurrent;

  const WalletV2OwnerUpgrade({
    required this.export,
    required this.legacyCodec,
    required this.wallet,
    required this.proofProvider,
    required this.accessIsCurrent,
  });

  void _requireAccess() {
    if (!accessIsCurrent() || !wallet.accessIsCurrent()) {
      throw StateError('Wallet access changed');
    }
  }

  /// Preparation verifies a pending V2 copy while the old wallet remains
  /// usable. Retirement is a separate, explicit owner action.
  Future<WalletV2UpgradeResult> run({bool prepareOnly = false}) async {
    _requireAccess();
    // The inventory may include saved items. Never read their ciphertext.
    final inventory = await export.listItemsBounded(maxRecords: 5000);
    _requireAccess();
    var migrated = 0;
    var prepared = 0;
    var inspected = 0;
    for (final row in inventory) {
      if (row['item_type'] != 'crypto_wallet_account') continue;
      inspected++;
      _requireAccess();
      final itemId = row['item_id'];
      final chars = row['ciphertext_chars'];
      if (itemId is! int ||
          itemId <= 0 ||
          chars is! int ||
          chars <= 0 ||
          chars > 64 * 1024) {
        throw const FormatException('Invalid older wallet inventory');
      }
      final source = await export.readItemSource(
        itemId: itemId,
        ciphertextChars: chars,
      );
      _requireAccess();
      if (source.sourceMetadata['item_type'] != 'crypto_wallet_account') {
        throw const FormatException('Older wallet source changed');
      }
      final outer = source.ciphertext.trimLeft().startsWith('{')
          ? source.ciphertext
          : await legacyCodec.decodeLegacyString(source.ciphertext);
      _requireAccess();
      final decoded = jsonDecode(outer);
      if (decoded is! Map<String, dynamic> ||
          decoded['schema'] != 'crypto_wallet_account_v1' ||
          decoded['asset'] is! String ||
          decoded['network'] is! String ||
          decoded['publicAddress'] is! String ||
          decoded['walletLabel'] is! String ||
          decoded['encryptedWalletSecret'] is! String) {
        throw const FormatException('Invalid older wallet account');
      }
      final asset = decoded['asset'] as String;
      final network = canonicalWalletNetwork(decoded['network'] as String);
      final chain = switch ((asset, network)) {
        ('ETH', 'ethereum_mainnet' || 'ethereum_sepolia') => 'evm',
        ('SOL', 'solana_mainnet') => 'solana',
        ('USDT_TRC20', 'tron_mainnet') => 'tron',
        ('XMR', 'monero_mainnet') => 'monero',
        _ => null,
      };
      if (chain == null || network == null) {
        throw const FormatException('Unsupported older wallet account');
      }
      final slot = WalletV2AccountSlot(chain, network, asset)..validate();
      if (await wallet.findVerified(slot) != null) {
        // An active old row beside a verified V2 slot is a conflict, never a
        // reason to discard the old source or silently skip the account.
        throw StateError('Conflicting verified wallet');
      }
      _requireAccess();
      final identity = WalletV2Identity(
        recordId: wallet.newRecordId(),
        chain: chain,
        network: network,
        asset: asset,
        publicAddress: decoded['publicAddress'] as String,
        label: decoded['walletLabel'] as String,
      );
      identity.validate();
      final migrator = WalletV2MigrationClient(
        codec: wallet.codec,
        post: wallet.post,
        get: wallet.get,
        proofProvider: proofProvider,
        decryptLegacyItem: legacyCodec.decodeLegacyString,
        decryptLegacySecret: legacyCodec.decodeLegacyString,
        secretMatchesAddress: (secret, address) =>
            wallet.secretMatchesAddress(chain, secret, address),
        accessIsCurrent: () => accessIsCurrent() && wallet.accessIsCurrent(),
      );
      final recordId = prepareOnly
          ? await migrator.prepareLegacy(
              legacyItemId: itemId,
              source: source,
              identity: identity,
            )
          : await migrator.migrateLegacy(
              legacyItemId: itemId,
              source: source,
              identity: identity,
            );
      _requireAccess();
      if (prepareOnly) {
        final pending = await wallet.findPending(slot);
        if (pending == null ||
            pending.identity.recordId != recordId ||
            pending.identity.publicAddress != identity.publicAddress ||
            pending.identity.label != identity.label ||
            pending.legacyItemId != itemId ||
            pending.legacySourceSnapshot != source.sourceSnapshot) {
          throw StateError('Prepared wallet is not visible');
        }
        prepared++;
        continue;
      }
      final published = await wallet.findVerified(slot);
      if (published == null ||
          published.recordId != recordId ||
          published.publicAddress != identity.publicAddress ||
          published.label != identity.label) {
        throw StateError('Upgraded wallet is not visible');
      }
      await wallet.readSigningSecret(published);
      _requireAccess();
      migrated++;
    }
    return WalletV2UpgradeResult(
      migrated: migrated,
      prepared: prepared,
      inspected: inspected,
    );
  }
}
