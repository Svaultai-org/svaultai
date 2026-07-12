

import 'package:flutter/material.dart';


const String kCryptoVaultLockedType = 'crypto_vault_locked';


const String kCryptoVaultDefaultTitle  = 'Crypto Vault';
const String kCryptoVaultDefaultStatus = 'Upgrade required';
const String kCryptoVaultActiveStatus  = 'Active';


const String kCryptoVaultLoadingStatus = 'Checking access…';
const String kCryptoVaultDefaultBody   =
    "Crypto Vault is a real, non-custodial wallet — receive, "
    "send, and view balance on supported networks, with keys "
    "that stay on your device. It's not available on your "
    "current plan. Upgrade your account to unlock it.";

const String kCryptoVaultActiveBody =
    "Crypto Vault is active on your account. Open it to pick "
    "a supported asset, use Receive for the wallet address and "
    "QR code, use Send to enter a recipient and amount, and "
    "view balance and transaction history where supported.";


const String kCryptoVaultLoadingBody =
    'Loading your Crypto Vault access.';
const String kCryptoVaultLearnMoreLabel        = 'Learn more';
const String kCryptoVaultUpgradeRequiredLabel  = 'Upgrade required';
const String kCryptoVaultOpenCryptoVaultLabel  = 'Open Crypto Vault';


const String kCryptoVaultLearnMoreBody =
    "Crypto Vault is a real, non-custodial wallet built into "
    "VaultAI. Upgrade your account to unlock it, then open "
    "Crypto Vault to pick a supported asset, use Receive for "
    "the wallet address and QR code, use Send to enter a "
    "recipient and amount, and view balance and transaction "
    "history where supported. Every send requires PIN unlock "
    "and local signing on your device — VaultAI never moves "
    "funds on its own.";


const String kActionLearnMore        = 'crypto_vault_learn_more';
const String kActionUpgradeRequired  = 'crypto_vault_upgrade_required';
const String kActionOpenCryptoVault  = 'crypto_vault_open';


const String kTierFreeLabel     = 'free';
const String kTierBasicLabel    = 'basic';
const String kTierUpgradedLabel = 'upgraded';
const String kTierLoadingLabel  = 'loading';


const String kCryptoUpgradeRoute = '/storage';
const Map<String, Object?> kCryptoUpgradeRouteArgs = <String, Object?>{
  'autoOpenPicker': true,
};


class CryptoVaultLockedCard extends StatelessWidget {
  const CryptoVaultLockedCard({
    super.key,
    this.envelope,
    this.tier,
    this.onLearnMore,
    this.onUpgradeRequired,
    this.onOpenCryptoVault,
  });

  
  final Map<String, dynamic>? envelope;

  
  final String? tier;

  
  final VoidCallback? onLearnMore;

  
  final VoidCallback? onUpgradeRequired;

  
  final VoidCallback? onOpenCryptoVault;

  String _str(String key, String fallback) {
    final raw = envelope?[key];
    if (raw is String && raw.trim().isNotEmpty) return raw;
    return fallback;
  }

  
  String get _effectiveTier {
    String? candidate = tier;
    if (candidate == null || candidate.trim().isEmpty) {
      final raw = envelope?['tier'];
      if (raw is String && raw.trim().isNotEmpty) candidate = raw;
    }
    final cleaned = (candidate ?? '').trim().toLowerCase();
    if (cleaned == kTierUpgradedLabel) return kTierUpgradedLabel;
    if (cleaned == kTierBasicLabel)    return kTierBasicLabel;
    if (cleaned == kTierLoadingLabel)  return kTierLoadingLabel;
    return kTierFreeLabel;
  }

  bool get _isUpgraded => _effectiveTier == kTierUpgradedLabel;
  bool get _isLoading  => _effectiveTier == kTierLoadingLabel;

  @override
  Widget build(BuildContext context) {
    final title  = _str('title',  kCryptoVaultDefaultTitle);
    final upgraded = _isUpgraded;
    final loading  = _isLoading;
    
    
    final String defaultStatus;
    if (loading) {
      defaultStatus = kCryptoVaultLoadingStatus;
    } else if (upgraded) {
      defaultStatus = kCryptoVaultActiveStatus;
    } else {
      defaultStatus = kCryptoVaultDefaultStatus;
    }
    final status = _str('status', defaultStatus);
    
    
    final String defaultBody;
    if (loading) {
      defaultBody = kCryptoVaultLoadingBody;
    } else if (upgraded) {
      defaultBody = kCryptoVaultActiveBody;
    } else {
      defaultBody = kCryptoVaultDefaultBody;
    }
    final body = _str('body', defaultBody);

    return Container(
      key: Key(loading
          ? 'crypto_vault_loading_card'
          : (upgraded
              ? 'crypto_vault_active_card'
              : 'crypto_vault_locked_card')),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              
              
              if (loading)
                const SizedBox(
                  key: Key('crypto_vault_loading_icon'),
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2.5,
                    valueColor: AlwaysStoppedAnimation<Color>(
                      Color(0xFFB4B4B4),
                    ),
                  ),
                )
              else
                Icon(
                  upgraded
                      ? Icons.check_circle_outline
                      : Icons.lock_outline,
                  color: const Color(0xFFB4B4B4),
                  key: Key(upgraded
                      ? 'crypto_vault_active_icon'
                      : 'crypto_vault_lock_icon'),
                ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      key: const Key('crypto_vault_title'),
                      style: const TextStyle(
                        fontSize: 18, fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      status,
                      key: const Key('crypto_vault_status'),
                      style: const TextStyle(
                        color: Color(0xFF10A37F),
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            body,
            key: const Key('crypto_vault_body'),
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 13,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 16),
          Wrap(
            alignment: WrapAlignment.end,
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton(
                key: const Key('crypto_vault_learn_more_button'),
                onPressed: () {
                  if (onLearnMore != null) {
                    onLearnMore!();
                    return;
                  }
                  showCryptoVaultLearnMoreDialog(context);
                },
                child: const Text(kCryptoVaultLearnMoreLabel),
              ),
              
              
              if (loading)
                ElevatedButton(
                  key: const Key('crypto_vault_loading_button'),
                  onPressed: null,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF10A37F),
                    foregroundColor: Colors.white,
                  ),
                  child: const Text('Checking…'),
                )
              else if (upgraded)
                ElevatedButton(
                  key: const Key('crypto_vault_open_button'),
                  onPressed: () {
                    if (onOpenCryptoVault != null) {
                      onOpenCryptoVault!();
                      return;
                    }
                    
                    
                    Navigator.pushNamed(context, '/crypto-vault');
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF10A37F),
                    foregroundColor: Colors.white,
                  ),
                  child: const Text(kCryptoVaultOpenCryptoVaultLabel),
                )
              else
                ElevatedButton(
                  key: const Key('crypto_vault_upgrade_required_button'),
                  onPressed: () {
                    if (onUpgradeRequired != null) {
                      onUpgradeRequired!();
                      return;
                    }
                    Navigator.pushNamed(
                      context, kCryptoUpgradeRoute,
                      arguments: kCryptoUpgradeRouteArgs,
                    );
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF10A37F),
                    foregroundColor: Colors.white,
                  ),
                  child: const Text(kCryptoVaultUpgradeRequiredLabel),
                ),
            ],
          ),
        ],
      ),
    );
  }
}


Future<void> showCryptoVaultLearnMoreDialog(BuildContext context) {
  return showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      key: const Key('crypto_vault_learn_more_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      title: const Text(
        kCryptoVaultDefaultTitle,
        key: Key('crypto_vault_learn_more_dialog_title'),
      ),
      content: const Text(
        kCryptoVaultLearnMoreBody,
        key: Key('crypto_vault_learn_more_dialog_body'),
      ),
      actions: [
        TextButton(
          key: const Key('crypto_vault_learn_more_dialog_close'),
          onPressed: () => Navigator.of(ctx).pop(),
          child: const Text('Close'),
        ),
      ],
    ),
  );
}
