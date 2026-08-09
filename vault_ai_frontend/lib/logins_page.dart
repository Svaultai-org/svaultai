import 'package:flutter/material.dart';
import 'l10n/app_localizations.dart';
import 'ui/responsive.dart';

const bool qaCredentialV2TargetingEnabled = bool.fromEnvironment(
  'QA_CREDENTIAL_V2_TARGETING',
  defaultValue: false,
);
const String _credentialV2CryptoVersion = 'client_mvk_v2';

class VaultLoginItem {
  final String service;
  final String itemType;
  final DateTime? createdAt;
  final String? recordId;
  final String cryptoVersion;
  final String? migrationState;
  final String? verificationState;

  const VaultLoginItem({
    required this.service,
    this.itemType = 'login',
    this.createdAt,
    this.recordId,
    this.cryptoVersion = 'legacy_v1',
    this.migrationState,
    this.verificationState,
  });

  factory VaultLoginItem.fromJson(Map<String, dynamic> json) {
    DateTime? created;
    final rawCreated = json['created_at'];
    if (rawCreated is String && rawCreated.isNotEmpty) {
      created = DateTime.tryParse(rawCreated);
    }
    return VaultLoginItem(
      service: (json['service'] ?? '').toString(),
      itemType: (json['item_type'] ?? 'login').toString(),
      createdAt: created,
      recordId: json['record_id']?.toString(),
      cryptoVersion: json['crypto_version']?.toString() ?? 'legacy_v1',
      migrationState: json['migration_state']?.toString(),
      verificationState: json['verification_state']?.toString(),
    );
  }
}

bool isCredentialV2RollbackEligible(VaultLoginItem item) =>
    item.cryptoVersion == 'client_mvk_v2' &&
    const {
      'migration_pending',
      'v2_verified',
      'migrated',
      'rollback_pending',
    }.contains(item.migrationState);

const Map<String, String> kSecureItemTypeLabels = <String, String>{
  'login': 'Login',
  'credential': 'Credential',
  'device': 'Device',
  'device_info': 'Device',
  'imei': 'Phone IMEI',
  'serial_number': 'Serial number',
  'document_note': 'Note',
  'recovery_code': 'Recovery code',
  'backup_code': 'Backup code',
  'private_note': 'Private note',
  'account_note': 'Account note',
  'bank': 'Bank record',
  'card': 'Card record',
  'other': 'Saved item',
  'other_secret': 'Saved secret',
  'crypto_wallet_address': 'Crypto wallet',
  'crypto_seed_phrase': 'Seed phrase',
  'crypto_private_key': 'Private key',
  'crypto_recovery_phrase': 'Recovery phrase',
  'crypto_note': 'Crypto note',
  'crypto_transaction_note': 'Transaction note',
  'crypto_exchange_note': 'Exchange note',
  'crypto_hardware_wallet_note': 'Hardware wallet note',
};

const Map<String, IconData> kSecureItemTypeIcons = <String, IconData>{
  'login': Icons.lock_outline,
  'credential': Icons.vpn_key_outlined,
  'device': Icons.devices_other_outlined,
  'device_info': Icons.devices_other_outlined,
  'imei': Icons.smartphone_outlined,
  'serial_number': Icons.numbers_outlined,
  'document_note': Icons.sticky_note_2_outlined,
  'recovery_code': Icons.shield_outlined,
  'backup_code': Icons.backup_outlined,
  'private_note': Icons.notes_outlined,
  'account_note': Icons.note_outlined,
  'bank': Icons.account_balance_outlined,
  'card': Icons.credit_card_outlined,
  'other': Icons.inventory_2_outlined,
  'other_secret': Icons.policy_outlined,
  'crypto_wallet_address': Icons.account_balance_wallet_outlined,
  'crypto_seed_phrase': Icons.password_outlined,
  'crypto_private_key': Icons.key_outlined,
  'crypto_recovery_phrase': Icons.shield_outlined,
  'crypto_note': Icons.notes_outlined,
  'crypto_transaction_note': Icons.receipt_long_outlined,
  'crypto_exchange_note': Icons.swap_horiz_outlined,
  'crypto_hardware_wallet_note': Icons.usb_outlined,
};

class SecureItemCategoryChip {
  final String id;

  final String label;

  final IconData icon;

  const SecureItemCategoryChip({
    required this.id,
    required this.label,
    required this.icon,
  });
}

const SecureItemCategoryChip kCategoryChipAll = SecureItemCategoryChip(
  id: 'all',
  label: 'All',
  icon: Icons.inventory_2_outlined,
);
const SecureItemCategoryChip kCategoryChipLogins = SecureItemCategoryChip(
  id: 'logins',
  label: 'Logins',
  icon: Icons.lock_outline,
);
const SecureItemCategoryChip kCategoryChipNotes = SecureItemCategoryChip(
  id: 'notes',
  label: 'Notes',
  icon: Icons.notes_outlined,
);
const SecureItemCategoryChip kCategoryChipCodes = SecureItemCategoryChip(
  id: 'codes',
  label: 'Codes',
  icon: Icons.shield_outlined,
);
const SecureItemCategoryChip kCategoryChipDevice = SecureItemCategoryChip(
  id: 'device',
  label: 'Device details',
  icon: Icons.smartphone_outlined,
);
const SecureItemCategoryChip kCategoryChipCrypto = SecureItemCategoryChip(
  id: 'crypto',
  label: 'Crypto',
  icon: Icons.account_balance_wallet_outlined,
);
const SecureItemCategoryChip kCategoryChipOther = SecureItemCategoryChip(
  id: 'other',
  label: 'Other',
  icon: Icons.policy_outlined,
);

const List<SecureItemCategoryChip> kSecureItemCategoryChips =
    <SecureItemCategoryChip>[
  kCategoryChipAll,
  kCategoryChipLogins,
  kCategoryChipNotes,
  kCategoryChipCodes,
  kCategoryChipDevice,
  kCategoryChipCrypto,
  kCategoryChipOther,
];

String secureItemChipIdFor(String itemType) {
  switch (itemType) {
    case 'login':
    case 'credential':
      return kCategoryChipLogins.id;
    case 'private_note':
    case 'account_note':
    case 'document_note':
      return kCategoryChipNotes.id;
    case 'backup_code':
    case 'recovery_code':
    case 'recovery_phrase':
      return kCategoryChipCodes.id;
    case 'device':
    case 'device_info':
    case 'imei':
    case 'serial_number':
      return kCategoryChipDevice.id;
    case 'crypto_wallet_address':
    case 'crypto_seed_phrase':
    case 'crypto_private_key':
    case 'crypto_recovery_phrase':
    case 'crypto_note':
    case 'crypto_transaction_note':
    case 'crypto_exchange_note':
    case 'crypto_hardware_wallet_note':
      return kCategoryChipCrypto.id;
    case 'license_key':
    case 'product_key':
    case 'activation_key':
    case 'private_key':
    case 'bank':
    case 'card':
    case 'other':
    case 'other_secret':
    default:
      return kCategoryChipOther.id;
  }
}

bool secureItemMatchesChip(
  VaultLoginItem item,
  SecureItemCategoryChip chip,
) {
  if (chip.id == kCategoryChipAll.id) return true;
  return secureItemChipIdFor(item.itemType) == chip.id;
}

bool secureItemMatchesQuery(VaultLoginItem item, String query) {
  final q = query.trim().toLowerCase();
  if (q.isEmpty) return true;
  final svc = item.service.toLowerCase();
  final label = (kSecureItemTypeLabels[item.itemType] ?? '').toLowerCase();
  return svc.contains(q) || label.contains(q);
}

bool isLoginLikeType(String itemType) {
  switch (itemType) {
    case 'login':
    case 'credential':
      return true;
    default:
      return false;
  }
}

const Set<String> kSystemHiddenItemTypes = <String>{
  'crypto_wallet_account',
};

bool isSystemHiddenItemType(String itemType) {
  return kSystemHiddenItemTypes.contains(itemType);
}

String previewBlurbForType(String itemType) {
  if (isLoginLikeType(itemType)) {
    return 'Username & password stored. Use View, Edit, '
        'Delete, or ask your vault.';
  }
  if (itemType == 'crypto_seed_phrase' ||
      itemType == 'crypto_private_key' ||
      itemType == 'crypto_recovery_phrase') {
    return 'Anyone with this value controls the wallet — open '
        'only when you mean to read it.';
  }
  if (itemType == 'crypto_wallet_address') {
    return 'Tap View to see the full wallet address.';
  }
  if (itemType == 'imei' ||
      itemType == 'serial_number' ||
      itemType == 'backup_code' ||
      itemType == 'recovery_code') {
    return 'Tap View, Edit, Delete, or ask your vault.';
  }
  return 'Stored securely. Tap View to read.';
}

const String kLoginsPageHeading = 'Logins & Secure Items';
const String kLoginsPageSubtitle =
    'Your saved passwords, credentials, private notes, codes, '
    'device details, and other encrypted text records.';

const String kLoginsEmptyTitle = 'No secure items yet';
const String kLoginsEmptyBody =
    'Anything you type and save as private text (logins, IMEIs, '
    'backup codes, private notes, crypto wallet addresses, …) '
    'appears here. Anything you upload as a file goes to Files.';

const String kLoginsLoadingTitle = 'Loading saved items…';
const String kLoginsLoadingBody =
    'Reading your encrypted vault. This usually finishes in a '
    'moment.';

const String kLoginsErrorTitle = "Couldn't load saved items";
const String kLoginsErrorBody =
    'Your vault is unlocked, but reading the saved items list '
    'didn\'t come back. Tap Retry to try again.';

class LoginsPage extends StatefulWidget {
  final bool isLoading;

  final bool hasLoaded;
  final String? error;
  final List<VaultLoginItem> logins;
  final Future<void> Function() onRefresh;
  final void Function(String service)? onAskVault;

  final void Function(String service, String itemType)? onView;
  final void Function(String service, String itemType)? onEdit;
  final void Function(String service, String itemType)? onDelete;
  final void Function(VaultLoginItem item)? onViewItem;
  final void Function(VaultLoginItem item)? onEditItem;
  final void Function(VaultLoginItem item)? onDeleteItem;
  final void Function(VaultLoginItem item)? onMigrateItem;
  final void Function(VaultLoginItem item)? onRollbackItem;
  final String vaultLabel;

  const LoginsPage({
    super.key,
    required this.isLoading,
    required this.logins,
    required this.onRefresh,
    required this.vaultLabel,
    this.hasLoaded = false,
    this.error,
    this.onAskVault,
    this.onView,
    this.onEdit,
    this.onDelete,
    this.onViewItem,
    this.onEditItem,
    this.onDeleteItem,
    this.onMigrateItem,
    this.onRollbackItem,
  });

  @override
  State<LoginsPage> createState() => _LoginsPageState();
}

class _LoginsPageState extends State<LoginsPage> {
  String _query = '';
  SecureItemCategoryChip _activeChip = kCategoryChipAll;
  late final TextEditingController _searchCtrl;

  @override
  void initState() {
    super.initState();
    _searchCtrl = TextEditingController(text: '');
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  void _setQuery(String value) {
    setState(() {
      _query = value;
    });
  }

  void _setChip(SecureItemCategoryChip chip) {
    setState(() {
      _activeChip = chip;
    });
  }

  List<VaultLoginItem> get _visibleLogins {
    return widget.logins
        .where((item) =>
            !isSystemHiddenItemType(item.itemType) &&
            secureItemMatchesChip(item, _activeChip) &&
            secureItemMatchesQuery(item, _query))
        .toList(growable: false);
  }

  @override
  Widget build(BuildContext context) {
    if (widget.error != null) {
      return _Shell(
        child: _LoadingErrorEmptyState(
          key: const Key('logins_page_error_state'),
          title: kLoginsErrorTitle,
          body: '$kLoginsErrorBody\n\n${widget.error!}',
          onRetry: widget.onRefresh,
        ),
      );
    }
    if (widget.isLoading || !widget.hasLoaded) {
      return _Shell(
        child: _LoadingState(
          key: const Key('logins_page_loading_state'),
        ),
      );
    }

    final userVisibleLogins = widget.logins
        .where((i) => !isSystemHiddenItemType(i.itemType))
        .toList(growable: false);
    if (userVisibleLogins.isEmpty) {
      return _Shell(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              kLoginsPageHeading,
              key: const Key('logins_page_heading'),
              style: TextStyle(
                fontSize: vrHeadline(context),
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 10),
            const Text(
              kLoginsPageSubtitle,
              key: Key('logins_page_subtitle'),
              style: TextStyle(
                color: Color(0xFFB4B4B4),
                fontSize: 15,
                height: 1.6,
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              kLoginsEmptyTitle,
              key: Key('logins_page_empty_title'),
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              kLoginsEmptyBody,
              key: Key('logins_page_empty_body'),
              style: TextStyle(
                color: Color(0xFFB4B4B4),
                fontSize: 14,
                height: 1.5,
              ),
            ),
          ],
        ),
      );
    }

    final filtered = _visibleLogins;

    return SingleChildScrollView(
      key: const Key('logins_page'),
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _Header(
                vaultLabel: widget.vaultLabel,
                onRefresh: widget.onRefresh,
              ),
              const SizedBox(height: 16),
              _SearchBar(
                controller: _searchCtrl,
                onChanged: _setQuery,
              ),
              const SizedBox(height: 12),
              _CategoryChipStrip(
                active: _activeChip,
                onSelect: _setChip,
              ),
              const SizedBox(height: 12),
              if (filtered.isEmpty)
                _FilterEmptyState(
                  query: _query,
                  chip: _activeChip,
                )
              else
                ...filtered.map((login) {
                  final service = login.service.trim();
                  final cleanService =
                      service.isEmpty ? 'Unnamed item' : _titleize(service);
                  final itemType = login.itemType;
                  final label =
                      login.cryptoVersion == _credentialV2CryptoVersion &&
                              login.verificationState != 'client_verified'
                          ? 'Credential (verification pending)'
                          : kSecureItemTypeLabels[itemType] ?? 'Saved item';
                  final icon = kSecureItemTypeIcons[itemType] ??
                      Icons.inventory_2_outlined;
                  final safeIdentity = login.recordId?.trim();
                  return _SecureItemCard(
                    // Record IDs are opaque, stable, and unique across
                    // duplicate services. Service names remain only the
                    // compatibility fallback for legacy items without an
                    // identity field.
                    key: Key(safeIdentity != null && safeIdentity.isNotEmpty
                        ? 'secure_item_card_$itemType-$safeIdentity'
                        : 'secure_item_card_$itemType-$cleanService'),
                    qaRecordId:
                        qaCredentialV2TargetingEnabled ? login.recordId : null,
                    cleanService: cleanService,
                    rawService: service,
                    label: label,
                    icon: icon,
                    itemType: itemType,
                    vaultLabel: widget.vaultLabel,
                    onAskVault: widget.onAskVault,
                    onView: widget.onViewItem == null
                        ? widget.onView
                        : (_, __) => widget.onViewItem!(login),
                    onEdit: widget.onEditItem == null
                        ? widget.onEdit
                        : (_, __) => widget.onEditItem!(login),
                    onDelete: widget.onDeleteItem == null
                        ? widget.onDelete
                        : (_, __) => widget.onDeleteItem!(login),
                    onMigrate: widget.onMigrateItem == null ||
                            login.cryptoVersion != 'legacy_v1' ||
                            !isLoginLikeType(login.itemType)
                        ? null
                        : () => widget.onMigrateItem!(login),
                    onRollback: widget.onRollbackItem == null ||
                            !isCredentialV2RollbackEligible(login)
                        ? null
                        : () => widget.onRollbackItem!(login),
                  );
                }),
            ],
          ),
        ),
      ),
    );
  }

  static String _titleize(String value) {
    return value
        .split(' ')
        .where((e) => e.trim().isNotEmpty)
        .map((e) => e[0].toUpperCase() + e.substring(1))
        .join(' ');
  }
}

class _SecureItemCard extends StatelessWidget {
  final String? qaRecordId;
  final String cleanService;
  final String rawService;
  final String label;
  final IconData icon;
  final String itemType;
  final String vaultLabel;
  final void Function(String service)? onAskVault;

  final void Function(String service, String itemType)? onView;
  final void Function(String service, String itemType)? onEdit;
  final void Function(String service, String itemType)? onDelete;
  final VoidCallback? onMigrate;
  final VoidCallback? onRollback;

  const _SecureItemCard({
    super.key,
    required this.qaRecordId,
    required this.cleanService,
    required this.rawService,
    required this.label,
    required this.icon,
    required this.itemType,
    required this.vaultLabel,
    required this.onAskVault,
    required this.onView,
    required this.onEdit,
    required this.onDelete,
    required this.onMigrate,
    required this.onRollback,
  });

  @override
  Widget build(BuildContext context) {
    final blurb = previewBlurbForType(itemType);
    Widget targeted(String action, Widget child) {
      final recordId = qaRecordId;
      if (recordId == null || recordId.isEmpty) return child;
      return Semantics(
        container: true,
        identifier: 'credential-$action-$recordId',
        label: 'credential-$action-$recordId',
        child: child,
      );
    }

    final buttons = <Widget>[
      targeted(
          'reveal',
          OutlinedButton.icon(
            onPressed:
                onView == null ? null : () => onView!(rawService, itemType),
            icon: const Icon(Icons.visibility_outlined, size: 18),
            label: const Text('View'),
          )),
      targeted(
          'edit',
          OutlinedButton.icon(
            onPressed:
                onEdit == null ? null : () => onEdit!(rawService, itemType),
            icon: const Icon(Icons.edit_outlined, size: 18),
            label: const Text('Edit'),
          )),
      targeted(
          'delete',
          OutlinedButton.icon(
            onPressed:
                onDelete == null ? null : () => onDelete!(rawService, itemType),
            icon: const Icon(Icons.delete_outline, size: 18),
            label: Text(AppLocalizations.of(context).commonDelete),
          )),
      OutlinedButton.icon(
        onPressed: onAskVault == null ? null : () => onAskVault!(rawService),
        icon: const Icon(Icons.smart_toy_outlined, size: 18),
        label: Text('Ask $vaultLabel'),
      ),
      if (onMigrate != null)
        OutlinedButton.icon(
          key: Key('credential_v2_migrate_$itemType-$rawService'),
          onPressed: onMigrate,
          icon: const Icon(Icons.upgrade_outlined, size: 18),
          label: const Text('Migrate to v2 (QA)'),
        ),
      if (onRollback != null)
        OutlinedButton.icon(
          key: Key('credential_v2_rollback_$itemType-$rawService'),
          onPressed: onRollback,
          icon: const Icon(Icons.undo_outlined, size: 18),
          label: const Text('Rollback v2 (QA)'),
        ),
    ];

    final headerRow = Row(
      children: [
        Container(
          width: 54,
          height: 54,
          decoration: BoxDecoration(
            color: const Color(0xFF10A37F).withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(16),
          ),
          child: Icon(icon, color: const Color(0xFF10A37F)),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                cleanService,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFF10A37F).withValues(alpha: 0.18),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      label,
                      style: const TextStyle(
                        color: Color(0xFF10A37F),
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 360),
                    child: Text(
                      blurb,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Color(0xFF8E8E8E),
                        fontSize: 12,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );

    final card = Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF2A2A2A),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white10),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final stackVertically = constraints.maxWidth < 640 ||
              onMigrate != null ||
              onRollback != null;
          if (stackVertically) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                headerRow,
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: buttons,
                ),
              ],
            );
          }
          return Row(
            children: [
              Expanded(child: headerRow),
              const SizedBox(width: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: buttons,
              ),
            ],
          );
        },
      ),
    );
    final recordId = qaRecordId;
    if (recordId == null || recordId.isEmpty) return card;
    return Semantics(
      container: true,
      identifier: 'credential-card-$recordId',
      label: 'credential-card-$recordId',
      child: card,
    );
  }
}

const String kLoginsSearchHint =
    'Search by title or type (e.g. "Revolut", "IMEI")';

class _SearchBar extends StatelessWidget {
  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  const _SearchBar({
    required this.controller,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('logins_page_search_bar'),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white12),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          const Icon(
            Icons.search,
            color: Color(0xFF8E8E8E),
            size: 18,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              key: const Key('logins_page_search_field'),
              controller: controller,
              onChanged: onChanged,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 14,
              ),
              decoration: const InputDecoration(
                isCollapsed: true,
                contentPadding: EdgeInsets.symmetric(vertical: 14),
                hintText: kLoginsSearchHint,
                hintStyle: TextStyle(
                  color: Color(0xFF8E8E8E),
                  fontSize: 13,
                ),
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
              ),
            ),
          ),
          if (controller.text.isNotEmpty)
            IconButton(
              key: const Key('logins_page_search_clear'),
              tooltip: 'Clear search',
              icon: const Icon(
                Icons.close,
                size: 16,
                color: Color(0xFF8E8E8E),
              ),
              onPressed: () {
                controller.clear();
                onChanged('');
              },
            ),
        ],
      ),
    );
  }
}

class _CategoryChipStrip extends StatelessWidget {
  final SecureItemCategoryChip active;
  final ValueChanged<SecureItemCategoryChip> onSelect;

  const _CategoryChipStrip({
    required this.active,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return Wrap(
      key: const Key('logins_page_category_chip_strip'),
      spacing: 8,
      runSpacing: 8,
      children: kSecureItemCategoryChips.map((c) {
        final selected = c.id == active.id;
        return ChoiceChip(
          key: Key('logins_page_chip_${c.id}'),
          showCheckmark: false,
          avatar: Icon(
            c.icon,
            size: 16,
            color: selected ? const Color(0xFF10A37F) : const Color(0xFFB4B4B4),
          ),
          label: Text(c.label),
          labelStyle: TextStyle(
            color: selected ? const Color(0xFF10A37F) : const Color(0xFFB4B4B4),
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
          selected: selected,
          backgroundColor: const Color(0xFF1F1F1F),
          selectedColor: const Color(0xFF10A37F).withValues(alpha: 0.18),
          side: BorderSide(
            color: selected
                ? const Color(0xFF10A37F).withValues(alpha: 0.45)
                : Colors.white12,
          ),
          onSelected: (v) {
            if (v) onSelect(c);
          },
        );
      }).toList(growable: false),
    );
  }
}

class _FilterEmptyState extends StatelessWidget {
  final String query;
  final SecureItemCategoryChip chip;

  const _FilterEmptyState({
    required this.query,
    required this.chip,
  });

  @override
  Widget build(BuildContext context) {
    final isAll = chip.id == kCategoryChipAll.id;
    final pieces = <String>[];
    if (query.trim().isNotEmpty) {
      pieces.add('"${query.trim()}"');
    }
    if (!isAll) {
      pieces.add(chip.label);
    }
    final scope = pieces.isEmpty ? 'in this view' : pieces.join(' • ');
    return Container(
      key: const Key('logins_page_filter_empty_state'),
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      margin: const EdgeInsets.only(top: 4),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'No matching saved items',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Nothing matches $scope. Adjust the search or pick a '
            'different category chip.',
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 13,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  final String vaultLabel;
  final Future<void> Function() onRefresh;

  const _Header({required this.vaultLabel, required this.onRefresh});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: const Color(0xFF2F2F2F),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  kLoginsPageHeading,
                  key: const Key('logins_page_heading'),
                  style: TextStyle(
                    fontSize: vrHeadline(context),
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  kLoginsPageSubtitle,
                  key: Key('logins_page_subtitle'),
                  style: TextStyle(
                    color: Color(0xFFB4B4B4),
                    fontSize: 15,
                  ),
                ),
              ],
            ),
          ),
          OutlinedButton.icon(
            onPressed: onRefresh,
            icon: const Icon(Icons.refresh),
            label: Text(AppLocalizations.of(context).commonRefresh),
          ),
        ],
      ),
    );
  }
}

class _LoadingState extends StatelessWidget {
  const _LoadingState({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          kLoginsPageHeading,
          key: const Key('logins_page_heading'),
          style: TextStyle(
            fontSize: vrHeadline(context),
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 10),
        const Text(
          kLoginsPageSubtitle,
          key: Key('logins_page_subtitle'),
          style: TextStyle(
            color: Color(0xFFB4B4B4),
            fontSize: 15,
            height: 1.6,
          ),
        ),
        const SizedBox(height: 28),
        const Row(
          children: [
            SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(strokeWidth: 2.4),
            ),
            SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    kLoginsLoadingTitle,
                    key: Key('logins_page_loading_title'),
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  SizedBox(height: 6),
                  Text(
                    kLoginsLoadingBody,
                    key: Key('logins_page_loading_body'),
                    style: TextStyle(
                      color: Color(0xFFB4B4B4),
                      fontSize: 14,
                      height: 1.5,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _LoadingErrorEmptyState extends StatelessWidget {
  final String title;
  final String body;
  final Future<void> Function()? onRetry;

  const _LoadingErrorEmptyState({
    super.key,
    required this.title,
    required this.body,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          kLoginsPageHeading,
          key: const Key('logins_page_heading'),
          style: TextStyle(
            fontSize: vrHeadline(context),
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 10),
        const Text(
          kLoginsPageSubtitle,
          key: Key('logins_page_subtitle'),
          style: TextStyle(
            color: Color(0xFFB4B4B4),
            fontSize: 15,
            height: 1.6,
          ),
        ),
        const SizedBox(height: 24),
        Text(
          title,
          key: const Key('logins_page_error_title'),
          style: const TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          body,
          key: const Key('logins_page_error_body'),
          style: const TextStyle(
            color: Color(0xFFB4B4B4),
            fontSize: 14,
            height: 1.5,
          ),
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          key: const Key('logins_page_retry_button'),
          onPressed: onRetry == null ? null : () => onRetry!(),
          icon: const Icon(Icons.refresh),
          label: const Text('Retry'),
        ),
      ],
    );
  }
}

class _Shell extends StatelessWidget {
  final Widget child;

  const _Shell({required this.child});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: const Color(0xFF2F2F2F),
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: Colors.white10),
            ),
            child: child,
          ),
        ),
      ),
    );
  }
}
