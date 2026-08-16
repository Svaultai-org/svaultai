import 'package:flutter/foundation.dart' show kReleaseMode;

/// Compile-time client/backend contract for production releases.
///
/// Explicit `--dart-define` values still win for QA and staged rollouts. The
/// release-mode defaults are the safety net for Xcode archives and ordinary
/// Android release builds, which historically omitted the web wrapper's
/// defines and called legacy routes disabled by the production backend.
const String svaultAiCoreApiContract = 'svaultai-core-v2-2026-08-16';

const bool zkV2CredentialReadEnabled = bool.fromEnvironment(
  'ZK_V2_READ_ENABLED',
  defaultValue: kReleaseMode,
);
const bool zkV2CredentialWriteEnabled = bool.fromEnvironment(
  'ZK_V2_WRITE_ENABLED',
  defaultValue: false,
);
const bool zkV2CredentialMigrationEnabled = bool.fromEnvironment(
  'ZK_V2_MIGRATION_ENABLED',
  defaultValue: false,
);

const bool memoryV2ReadEnabled = bool.fromEnvironment(
  'MEMORY_V2_READ_ENABLED',
  defaultValue: kReleaseMode,
);
const bool memoryV2WriteEnabled = bool.fromEnvironment(
  'MEMORY_V2_WRITE_ENABLED',
  defaultValue: kReleaseMode,
);
const bool memoryV2MigrationEnabled = bool.fromEnvironment(
  'MEMORY_V2_MIGRATION_ENABLED',
  defaultValue: false,
);

const bool fileV2ReadEnabled = bool.fromEnvironment(
  'FILE_V2_READ_ENABLED',
  defaultValue: kReleaseMode,
);
const bool fileV2WriteEnabled = bool.fromEnvironment(
  'FILE_V2_WRITE_ENABLED',
  defaultValue: kReleaseMode,
);
const bool fileV2MigrationEnabled = bool.fromEnvironment(
  'FILE_V2_MIGRATION_ENABLED',
  defaultValue: false,
);

const bool walletBackupV2ReadEnabled = bool.fromEnvironment(
  'WALLET_BACKUP_V2_READ_ENABLED',
  defaultValue: false,
);
const bool walletBackupV2WriteEnabled = bool.fromEnvironment(
  'WALLET_BACKUP_V2_WRITE_ENABLED',
  defaultValue: false,
);
const bool walletBackupV2MigrationEnabled = bool.fromEnvironment(
  'WALLET_BACKUP_V2_MIGRATION_ENABLED',
  defaultValue: false,
);

const bool walletV2ReadEnabled = bool.fromEnvironment(
  'WALLET_V2_READ_ENABLED',
  defaultValue: false,
);
const bool walletV2WriteEnabled = bool.fromEnvironment(
  'WALLET_V2_WRITE_ENABLED',
  defaultValue: false,
);
const bool walletV2MigrationEnabled = bool.fromEnvironment(
  'WALLET_V2_MIGRATION_ENABLED',
  defaultValue: false,
);

const bool privateVaultLocalRoutingEnabled = bool.fromEnvironment(
  'PRIVATE_VAULT_LOCAL_ROUTING_ENABLED',
  defaultValue: false,
);
