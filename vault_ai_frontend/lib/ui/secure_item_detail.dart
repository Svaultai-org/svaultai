

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n/app_localizations.dart';


const Map<String, String> kSecureItemTypeLabelsForDetail =
    <String, String>{
  'login':                       'Login',
  'credential':                  'Credential',
  'device':                      'Device',
  'device_info':                 'Device',
  'imei':                        'Phone IMEI',
  'serial_number':               'Serial number',
  'document_note':               'Note',
  'recovery_code':               'Recovery code',
  'recovery_phrase':             'Recovery phrase',
  'backup_code':                 'Backup code',
  'private_note':                'Private note',
  'account_note':                'Account note',
  'license_key':                 'License key',
  'product_key':                 'Product key',
  'activation_key':              'Activation key',
  'private_key':                 'Private key',
  'bank':                        'Bank record',
  'card':                        'Card record',
  'other':                       'Saved item',
  'other_secret':                'Saved secret',
  'crypto_wallet_address':       'Crypto wallet',
  'crypto_seed_phrase':          'Seed phrase',
  'crypto_private_key':          'Private key',
  'crypto_recovery_phrase':      'Recovery phrase',
  'crypto_note':                 'Crypto note',
  'crypto_transaction_note':     'Transaction note',
  'crypto_exchange_note':        'Exchange note',
  'crypto_hardware_wallet_note': 'Hardware wallet note',
};


bool isSecureItemLoginLike(String itemType) {
  return itemType == 'login' || itemType == 'credential';
}


String secureItemMaskedHintFor(String itemType) {
  if (isSecureItemLoginLike(itemType)) {
    return 'Username and password are stored. Ask your vault '
        'to show this login to see them.';
  }
  if (itemType == 'imei' || itemType == 'serial_number') {
    return 'Ask your vault to show this item to see the full number.';
  }
  if (itemType == 'crypto_wallet_address') {
    return 'Ask your vault to show this wallet to see the full address.';
  }
  if (itemType == 'crypto_seed_phrase'
      || itemType == 'crypto_private_key'
      || itemType == 'crypto_recovery_phrase') {
    return 'Anyone with this value controls the wallet — only ask '
        'your vault to show it when you mean to read it.';
  }
  if (itemType == 'private_note' || itemType == 'account_note') {
    return 'Ask your vault to show this note to read its full text.';
  }
  if (itemType == 'license_key'
      || itemType == 'product_key'
      || itemType == 'activation_key'
      || itemType == 'private_key') {
    return 'Ask your vault to show this key to see the full value.';
  }
  if (itemType == 'backup_code' || itemType == 'recovery_code') {
    return 'Ask your vault to show this item to see the codes.';
  }
  return 'Ask your vault to show this item to see the saved value.';
}


class SecureItemEditField {
  final String key;
  final String label;
  final bool obscureText;
  final int maxLines;

  const SecureItemEditField({
    required this.key,
    required this.label,
    this.obscureText = false,
    this.maxLines = 1,
  });
}


List<SecureItemEditField> secureItemEditFieldsFor(String itemType) {
  if (isSecureItemLoginLike(itemType)) {
    return const [
      SecureItemEditField(key: 'username', label: 'Username'),
      SecureItemEditField(
        key: 'password', label: 'Password',
        obscureText: true,
      ),
      SecureItemEditField(
        key: 'note',     label: 'Note',
        maxLines: 3,
      ),
    ];
  }
  if (itemType == 'imei') {
    return const [
      SecureItemEditField(key: 'imei_1', label: 'IMEI'),
      SecureItemEditField(
        key: 'notes', label: 'Notes', maxLines: 3,
      ),
    ];
  }
  if (itemType == 'serial_number') {
    return const [
      SecureItemEditField(key: 'serial_number', label: 'Serial number'),
      SecureItemEditField(
        key: 'notes', label: 'Notes', maxLines: 3,
      ),
    ];
  }
  if (itemType == 'private_note') {
    return const [
      SecureItemEditField(
        key: 'private_value', label: 'Private note',
        maxLines: 6,
      ),
    ];
  }
  if (itemType == 'account_note') {
    return const [
      SecureItemEditField(
        key: 'account_notes', label: 'Account note',
        maxLines: 6,
      ),
    ];
  }
  if (itemType == 'backup_code' || itemType == 'recovery_code') {
    return const [
      SecureItemEditField(
        key: 'backup_codes', label: 'Codes',
        maxLines: 4,
      ),
      SecureItemEditField(
        key: 'notes', label: 'Notes', maxLines: 3,
      ),
    ];
  }
  if (itemType == 'license_key'
      || itemType == 'product_key'
      || itemType == 'activation_key') {
    return [
      SecureItemEditField(
        key: itemType, label: kSecureItemTypeLabelsForDetail[itemType] ?? 'Key',
      ),
      const SecureItemEditField(
        key: 'notes', label: 'Notes', maxLines: 3,
      ),
    ];
  }
  if (itemType == 'private_key') {
    return const [
      SecureItemEditField(
        key: 'private_key', label: 'Private key',
        maxLines: 4,
      ),
      SecureItemEditField(
        key: 'notes', label: 'Notes', maxLines: 3,
      ),
    ];
  }
  if (itemType == 'recovery_phrase') {
    return const [
      SecureItemEditField(
        key: 'recovery_phrase', label: 'Recovery phrase',
        maxLines: 4,
      ),
      SecureItemEditField(
        key: 'notes', label: 'Notes', maxLines: 3,
      ),
    ];
  }
  
  
  return const [
    SecureItemEditField(
      key: 'secret_value', label: 'Value',
      maxLines: 4,
    ),
    SecureItemEditField(
      key: 'notes', label: 'Notes', maxLines: 3,
    ),
  ];
}


typedef SecureItemRevealHandler   = void Function(
    String title, String itemType);
typedef SecureItemEditHandler     = void Function(
    String title, String itemType);
typedef SecureItemDeleteHandler   = void Function(
    String title, String itemType);
typedef SecureItemCopyHandler     = void Function(String value);


class SecureItemDetailSheet extends StatelessWidget {
  final String title;
  final String itemType;
  
  
  final String? username;

  
  final SecureItemRevealHandler? onReveal;
  final SecureItemEditHandler?   onEdit;
  final SecureItemDeleteHandler? onDelete;
  final SecureItemCopyHandler?   onCopyUsername;
  final SecureItemCopyHandler?   onCopyValue;

  
  final String? revealedValue;

  const SecureItemDetailSheet({
    super.key,
    required this.title,
    required this.itemType,
    this.username,
    this.onReveal,
    this.onEdit,
    this.onDelete,
    this.onCopyUsername,
    this.onCopyValue,
    this.revealedValue,
  });

  @override
  Widget build(BuildContext context) {
    final isLogin = isSecureItemLoginLike(itemType);
    final chip    = kSecureItemTypeLabelsForDetail[itemType] ?? 'Saved item';
    final hint    = secureItemMaskedHintFor(itemType);

    return SafeArea(
      child: Container(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
        decoration: const BoxDecoration(
          color: Color(0xFF2A2A2A),
          borderRadius: BorderRadius.only(
            topLeft:  Radius.circular(20),
            topRight: Radius.circular(20),
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            
            Center(
              child: Container(
                width: 36, height: 4,
                decoration: BoxDecoration(
                  color: Colors.white24,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              title.trim().isEmpty ? 'Saved item' : title,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 20,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 8, vertical: 2,
              ),
              decoration: BoxDecoration(
                color: const Color(0xFF10A37F).withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                chip,
                style: const TextStyle(
                  color: Color(0xFF10A37F),
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(height: 14),
            
            if (revealedValue == null)
              Text(
                hint,
                style: const TextStyle(
                  color: Color(0xFFD0D0D0),
                  fontSize: 13, height: 1.4,
                ),
              )
            else
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF1F1F1F),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.white12),
                ),
                child: SelectableText(
                  revealedValue!,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 14,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            const SizedBox(height: 16),
            
            
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (isLogin
                    && username != null
                    && (username?.isNotEmpty ?? false))
                  OutlinedButton.icon(
                    key: const Key('secure_item_detail_copy_username'),
                    onPressed: onCopyUsername == null
                        ? () {
                            Clipboard.setData(
                              ClipboardData(text: username!),
                            );
                          }
                        : () => onCopyUsername!(username!),
                    icon: const Icon(Icons.copy_outlined, size: 18),
                    label: Text(
                      AppLocalizations.of(context).secureItemCopyUsername,
                    ),
                  ),
                if (!isLogin
                    && revealedValue != null
                    && revealedValue!.isNotEmpty)
                  OutlinedButton.icon(
                    key: const Key('secure_item_detail_copy_value'),
                    onPressed: onCopyValue == null
                        ? () {
                            Clipboard.setData(
                              ClipboardData(text: revealedValue!),
                            );
                          }
                        : () => onCopyValue!(revealedValue!),
                    icon: const Icon(Icons.copy_outlined, size: 18),
                    label: Text(
                      AppLocalizations.of(context).secureItemCopyValue,
                    ),
                  ),
                OutlinedButton.icon(
                  key: const Key('secure_item_detail_edit'),
                  onPressed: onEdit == null
                      ? null : () => onEdit!(title, itemType),
                  icon: const Icon(Icons.edit_outlined, size: 18),
                  label: const Text('Edit'),
                ),
                OutlinedButton.icon(
                  key: const Key('secure_item_detail_delete'),
                  onPressed: onDelete == null
                      ? null : () => onDelete!(title, itemType),
                  icon: const Icon(Icons.delete_outline, size: 18),
                  label: Text(AppLocalizations.of(context).commonDelete),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}


typedef SecureItemEditSaveHandler = Future<bool> Function({
  required String oldTitle,
  required String itemType,
  required String newTitle,
  required Map<String, String> fields,
});


class SecureItemEditDialog extends StatefulWidget {
  final String title;
  final String itemType;

  
  final Map<String, String>? initialFields;

  
  final SecureItemEditSaveHandler onSave;

  const SecureItemEditDialog({
    super.key,
    required this.title,
    required this.itemType,
    required this.onSave,
    this.initialFields,
  });

  @override
  State<SecureItemEditDialog> createState() => _SecureItemEditDialogState();
}


class _SecureItemEditDialogState extends State<SecureItemEditDialog> {
  late final TextEditingController _titleCtrl;
  late final Map<String, TextEditingController> _fieldCtrls;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _titleCtrl = TextEditingController(text: widget.title);
    
    
    final init = widget.initialFields ?? const <String, String>{};
    _fieldCtrls = {
      for (final f in secureItemEditFieldsFor(widget.itemType))
        f.key: TextEditingController(text: init[f.key] ?? ''),
    };
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    for (final c in _fieldCtrls.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _handleSave() async {
    
    
    if (_saving) return;
    setState(() => _saving = true);
    final newTitle = _titleCtrl.text.trim();
    final fields = <String, String>{
      for (final entry in _fieldCtrls.entries)
        if (entry.value.text.trim().isNotEmpty)
          entry.key: entry.value.text,
    };
    bool ok = false;
    try {
      ok = await widget.onSave(
        oldTitle: widget.title,
        itemType: widget.itemType,
        newTitle: newTitle.isEmpty ? widget.title : newTitle,
        fields:   fields,
      );
    } catch (_) {
      ok = false;
    }
    if (!mounted) return;
    if (ok) {
      
      
      Navigator.of(context).pop(true);
      return;
    }
    
    
    setState(() => _saving = false);
  }

  @override
  Widget build(BuildContext context) {
    final fields = secureItemEditFieldsFor(widget.itemType);
    final chip = kSecureItemTypeLabelsForDetail[widget.itemType]
        ?? 'Saved item';
    return AlertDialog(
      backgroundColor: const Color(0xFF2A2A2A),
      title: Text(
        'Edit $chip',
        style: const TextStyle(color: Colors.white, fontSize: 18),
      ),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              key: const Key('secure_item_edit_title'),
              controller: _titleCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: 'Title',
                labelStyle: TextStyle(color: Color(0xFFB4B4B4)),
              ),
            ),
            const SizedBox(height: 8),
            ...fields.map((f) => Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: TextField(
                    key: Key('secure_item_edit_${f.key}'),
                    controller: _fieldCtrls[f.key],
                    obscureText: f.obscureText,
                    maxLines: f.maxLines,
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      labelText: f.label,
                      labelStyle:
                          const TextStyle(color: Color(0xFFB4B4B4)),
                    ),
                  ),
                )),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.of(context).pop(false),
          child: Text(AppLocalizations.of(context).commonCancel),
        ),
        TextButton(
          key: const Key('secure_item_edit_save'),
          onPressed: _saving ? null : _handleSave,
          child: Text(AppLocalizations.of(context).commonSave),
        ),
      ],
    );
  }
}


Future<void> showSecureItemDetailSheet(
  BuildContext context, {
  required String title,
  required String itemType,
  String? username,
  String? revealedValue,
  SecureItemRevealHandler? onReveal,
  SecureItemEditHandler?   onEdit,
  SecureItemDeleteHandler? onDelete,
  SecureItemCopyHandler?   onCopyUsername,
  SecureItemCopyHandler?   onCopyValue,
}) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (ctx) => SecureItemDetailSheet(
      title:         title,
      itemType:      itemType,
      username:      username,
      revealedValue: revealedValue,
      onReveal:      onReveal,
      onEdit:        onEdit,
      onDelete:      onDelete,
      onCopyUsername: onCopyUsername,
      onCopyValue:   onCopyValue,
    ),
  );
}


Future<bool?> showSecureItemEditDialog(
  BuildContext context, {
  required String title,
  required String itemType,
  required SecureItemEditSaveHandler onSave,
  Map<String, String>? initialFields,
}) {
  return showDialog<bool>(
    context: context,
    builder: (ctx) => SecureItemEditDialog(
      title:    title,
      itemType: itemType,
      initialFields: initialFields,
      onSave:   onSave,
    ),
  );
}
