
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n/app_localizations.dart';
import '../services/crypto_chat_live_cache.dart';
import '../services/vault_chat_router.dart';
import 'crypto_vault_chat_cards.dart';
import 'crypto_wallet_engine_design.dart';
import 'responsive.dart';

export 'crypto_vault_chat_cards.dart'
    show CryptoBalanceFetcher, CryptoActivityFetcher;
export '../services/crypto_chat_live_cache.dart'
    show CryptoChatLiveCache;


const String kVcrLoginViewList     = 'list';
const String kVcrLoginViewSearch   = 'search';
const String kVcrLoginViewDetail   = 'detail';
const String kVcrLoginViewChooser  = 'chooser';
const String kVcrLoginViewNotFound = 'not_found';
const String kVcrLoginViewDupes    = 'duplicates';


const String kVcrLoginActionShow    = 'show';
const String kVcrLoginActionOpen    = 'open';
const String kVcrLoginActionView    = 'view';
const String kVcrLoginActionEdit    = 'edit';
const String kVcrLoginActionDelete  = 'delete';
const String kVcrLoginActionCopy    = 'copy';
const String kVcrLoginActionSave    = 'save';


const String kVcrCardKeyOverview          = 'vault_chat_card_overview';
const String kVcrCardKeyFileResult        = 'vault_chat_card_file_result';
const String kVcrCardKeyDocumentResult    =
    'vault_chat_card_document_result';
const String kVcrCardKeySecureItem        = 'vault_chat_card_secure_item';
const String kVcrCardKeyLogin             = 'vault_chat_card_login';
const String kVcrCardKeyGeneratedLogin    =
    'vault_chat_card_generated_login';
const String kVcrCardKeyIdDocument        = 'vault_chat_card_id_document';
const String kVcrCardKeyBillingStatus     =
    'vault_chat_card_billing_status';
const String kVcrCardKeyStorageUsage      =
    'vault_chat_card_storage_usage';
const String kVcrCardKeyVaultActivity     =
    'vault_chat_card_vault_activity';
const String kVcrCardKeyCrossVaultSearch  =
    'vault_chat_card_cross_vault_search';
const String kVcrCardKeyConfirmationReq   =
    'vault_chat_card_confirmation_required';
const String kVcrCardKeyRefusal           = 'vault_chat_card_refusal';
const String kVcrCardKeyUnrecognized      =
    'vault_chat_card_unrecognized';
const String kVcrCardKeyFaq               = 'vault_chat_card_faq';


const String kVcrFaqActionOpenVault        = 'open_vault';
const String kVcrFaqActionOpenLogins       = 'open_logins_page';
const String kVcrFaqActionOpenIdDocs       = 'open_id_documents';
const String kVcrFaqActionOpenCryptoVault  = 'open_crypto_vault';
const String kVcrFaqActionOpenBilling      = 'open_billing_page';
const String kVcrFaqActionOpenStorage      = 'open_storage_page';
const String kVcrFaqActionOpenSecurity     = 'open_security_center';
const String kVcrFaqActionOpenHelpCenter   = 'open_help_center';
const String kVcrFaqActionOpenUpload       = 'open_upload_page';



class VaultChatCardView extends StatelessWidget {
  final VaultChatResponse response;
  final VoidCallback? onOpenVault;
  final void Function(String asset)? onOpenAssetDetail;
  final VoidCallback? onOpenSendFlow;
  final VoidCallback? onOpenSecurityPage;
  final VoidCallback? onOpenBillingPage;


  final VoidCallback? onOpenLoginsPage;
  final VoidCallback? onOpenIdDocumentsPage;
  final VoidCallback? onOpenCryptoVaultPage;
  final VoidCallback? onOpenStoragePage;
  final VoidCallback? onOpenHelpCenter;
  final VoidCallback? onOpenUploadPage;
  final void Function(String faqId)? onAskRelatedFaq;


  final CryptoBalanceFetcher? onFetchCryptoBalance;
  final CryptoActivityFetcher? onFetchCryptoActivity;


  final CryptoChatLiveCache? cryptoCache;


  final void Function(String service)?             onLoginEdit;
  final void Function(String service)?             onLoginDelete;
  final void Function(String service, String url)? onLoginOpenWebsite;

  final void Function(String query)? onLoginChooseCandidate;

  const VaultChatCardView({
    super.key,
    required this.response,
    this.onOpenVault,
    this.onOpenAssetDetail,
    this.onOpenSendFlow,
    this.onOpenSecurityPage,
    this.onOpenBillingPage,
    this.onOpenLoginsPage,
    this.onOpenIdDocumentsPage,
    this.onOpenCryptoVaultPage,
    this.onOpenStoragePage,
    this.onOpenHelpCenter,
    this.onOpenUploadPage,
    this.onAskRelatedFaq,
    this.onFetchCryptoBalance,
    this.onFetchCryptoActivity,
    this.cryptoCache,
    this.onLoginEdit,
    this.onLoginDelete,
    this.onLoginOpenWebsite,
    this.onLoginChooseCandidate,
  });

  @override
  Widget build(BuildContext context) {
    final c = response.card;


    if (response.isCryptoDelegated) {
      final inner = response.delegatedCryptoCard;
      if (inner != null) {
        return CryptoVaultChatCardView(
          card: inner,
          onOpenVault: onOpenVault,
          onOpenAssetDetail: onOpenAssetDetail,
          onOpenSendFlow: onOpenSendFlow,
          onFetchBalance:  onFetchCryptoBalance,
          onFetchActivity: onFetchCryptoActivity,
          cache:           cryptoCache,
        );
      }
    }

    switch (c.cardType) {
      case kVcrCardRefusal:
        return _RefusalCard(card: c);
      case kVcrCardConfirmationRequired:
        return _ConfirmationRequiredCard(card: c);
      case kVcrCardVaultOverview:
        return _VaultOverviewCard(card: c, onOpenVault: onOpenVault);
      case kVcrCardFileResult:
        return _FileResultCard(card: c);
      case kVcrCardDocumentResult:
        return _DocumentResultCard(card: c);
      case kVcrCardSecureItem:
        return _SecureItemCard(card: c);
      case kVcrCardLogin:
        return _LoginCard(
          card: c,
          onLoginEdit:            onLoginEdit,
          onLoginDelete:          onLoginDelete,
          onLoginOpenWebsite:     onLoginOpenWebsite,
          onLoginChooseCandidate: onLoginChooseCandidate,
        );
      case kVcrCardGeneratedLogin:
        return _GeneratedLoginCard(card: c);
      case kVcrCardIdDocument:
        return _IdDocumentCard(card: c);
      case kVcrCardBillingStatus:
        return _BillingStatusCard(card: c,
            onOpenBillingPage: onOpenBillingPage);
      case kVcrCardStorageUsage:
        return _StorageUsageCard(card: c);
      case kVcrCardVaultActivity:
        return _VaultActivityCard(card: c);
      case kVcrCardCrossVaultSearch:
        return _CrossVaultSearchCard(card: c);
      case kVcrCardFaq:
        return _FaqCard(
          card: c,
          onOpenVault:           onOpenVault,
          onOpenLoginsPage:      onOpenLoginsPage,
          onOpenIdDocumentsPage: onOpenIdDocumentsPage,
          onOpenCryptoVaultPage: onOpenCryptoVaultPage,
          onOpenBillingPage:     onOpenBillingPage,
          onOpenStoragePage:     onOpenStoragePage,
          onOpenSecurityPage:    onOpenSecurityPage,
          onOpenHelpCenter:      onOpenHelpCenter,
          onOpenUploadPage:      onOpenUploadPage,
          onAskRelatedFaq:       onAskRelatedFaq,
        );
      case kVcrCardUnrecognized:
      default:
        return _UnrecognizedCard(card: c);
    }
  }
}


Widget _shell({
  required String testKey,
  required Widget child,
  Color? accent,
}) {
  return Container(
    key: Key(testKey),
    padding: const EdgeInsets.all(14),
    decoration: walletDarkCard(accent: accent),
    child: child,
  );
}


Widget _pillMasked(String label) {
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(
      color: kWalletBgBase,
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: kWalletBorder),
    ),
    child: Text(
      label,
      style: const TextStyle(
        color: kWalletTextMuted,
        fontSize: 11,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}


class _RefusalCard extends StatelessWidget {
  final VaultChatCard card;
  const _RefusalCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final message = card.message ?? kVcrRefusalCopySecretMaterial;
    return _shell(
      testKey: kVcrCardKeyRefusal,
      accent: kWalletAccentDanger,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.block_rounded, size: 18,
              color: kWalletAccentDanger),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(
                color: kWalletTextPrimary, fontSize: 13, height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}


class _ConfirmationRequiredCard extends StatelessWidget {
  final VaultChatCard card;
  const _ConfirmationRequiredCard({required this.card});

  @override
  Widget build(BuildContext context) {
    return _shell(
      testKey: kVcrCardKeyConfirmationReq,
      accent: kWalletAccentWarning,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Confirmation required',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          Text(
            card.message ??
                'This action needs your explicit confirmation.',
            style: kWalletBodyStyle,
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 6, runSpacing: 6,
            children: [
              if (card.requiresTrustedDevice)
                _pillMasked('Trusted device'),
              if (card.requiresPinUnlock)
                _pillMasked('PIN unlock'),
              if (card.requiresLocalSigning)
                _pillMasked('Local signing'),
              if (card.requiresExplicitConfirmation)
                _pillMasked('Explicit confirmation'),
            ],
          ),
        ],
      ),
    );
  }
}


class _VaultOverviewCard extends StatelessWidget {
  final VaultChatCard card;
  final VoidCallback? onOpenVault;
  const _VaultOverviewCard({required this.card, this.onOpenVault});

  @override
  Widget build(BuildContext context) {
    final data = card.data;
    final available = data != null && data['available'] == true;
    final counts = (data?['counts'] as Map?)?.cast<String, dynamic>();
    final storage = (data?['storage'] as Map?)?.cast<String, dynamic>();

    return _shell(
      testKey: kVcrCardKeyOverview,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).vaultCardOverview,
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            const Text(
              'Files, secure items, logins, ID documents, Crypto Vault, '
              'storage, and recent activity. Values are masked by '
              'default — open an item to reveal it.',
              style: kWalletBodyStyle,
            )
          else if (counts != null) ...[
            Wrap(
              spacing: 6, runSpacing: 6,
              children: [
                _statPill('Files',       _asInt(counts['files'])),
                _statPill('Documents',   _asInt(counts['documents'])),
                _statPill('Logins',      _asInt(counts['logins'])),
                _statPill('Secure',      _asInt(counts['secure_items'])),
                _statPill('IDs',         _asInt(counts['id_documents'])),
                _statPill(
                  'Generated', _asInt(counts['generated_logins']),
                ),
              ],
            ),
            if (storage != null) ...[
              const SizedBox(height: 8),
              _StorageBar(
                used:  _asInt(storage['used_bytes']),
                quota: _asInt(storage['quota_bytes']),
                percent: _asDouble(storage['percent_used']),
              ),
            ],
          ] else
            const Text(
              'Vault summary unavailable right now.',
              style: kWalletBodyStyle,
            ),
          if (onOpenVault != null) ...[
            const SizedBox(height: 10),
            OutlinedButton(
              key: const Key('vault_chat_overview_open_btn'),
              onPressed: onOpenVault,
              style: walletGhostButtonStyle(),
              child: Text(
                AppLocalizations.of(context).vaultCardOpenVault,
              ),
            ),
          ],
        ],
      ),
    );
  }
}


int _asInt(dynamic v) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? 0;
  return 0;
}

double _asDouble(dynamic v) {
  if (v is double) return v;
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v) ?? 0.0;
  return 0.0;
}

String _formatBytes(int bytes) {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var size = bytes.toDouble();
  var i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  final digits = size >= 10 || i == 0 ? 0 : 1;
  return '${size.toStringAsFixed(digits)} ${units[i]}';
}


Widget _statPill(String label, int count) {
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      color: kWalletBgBase,
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: kWalletBorder),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '$count',
          style: const TextStyle(
            color: kWalletTextPrimary,
            fontSize: 13,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(width: 5),
        Text(
          label,
          style: const TextStyle(
            color: kWalletTextMuted,
            fontSize: 11,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    ),
  );
}


class _StorageBar extends StatelessWidget {
  final int used;
  final int quota;
  final double percent;
  const _StorageBar({
    required this.used, required this.quota, required this.percent,
  });

  @override
  Widget build(BuildContext context) {
    final pct = percent.clamp(0.0, 100.0);
    final usedLabel = _formatBytes(used);
    final quotaLabel = quota > 0
        ? _formatBytes(quota)
        : 'unlimited';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Storage $usedLabel / $quotaLabel'
          '${quota > 0 ? " (${pct.toStringAsFixed(0)}%)" : ""}',
          style: const TextStyle(
            color: kWalletTextMuted,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(
            key: const Key('vault_chat_overview_storage_bar'),
            value: quota > 0 ? (pct / 100.0) : 0,
            backgroundColor: kWalletBorder,
            minHeight: 6,
          ),
        ),
      ],
    );
  }
}


class _FileResultCard extends StatelessWidget {
  final VaultChatCard card;
  const _FileResultCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final q = card.query;
    return _shell(
      testKey: kVcrCardKeyFileResult,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Files', style: kWalletSectionHeadingStyle),
          const SizedBox(height: 6),
          Text(
            q != null
                ? 'Open the vault to see files matching "$q".'
                : 'Open the vault to see your files.',
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }
}


class _DocumentResultCard extends StatelessWidget {
  final VaultChatCard card;
  const _DocumentResultCard({required this.card});

  @override
  Widget build(BuildContext context) {
    return _shell(
      testKey: kVcrCardKeyDocumentResult,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).vaultCardDocumentSummary,
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          const Text(
            'Open the document to generate a summary. VaultAI never '
            'invents document content.',
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }
}


class _SecureItemCard extends StatelessWidget {
  final VaultChatCard card;
  const _SecureItemCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final data = card.data;
    final available = data != null && data['available'] == true;
    final items = _asMapList(data?['items']);
    final q = card.query;

    return _shell(
      testKey: kVcrCardKeySecureItem,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Secure items (${items.length})',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            Text(
              q != null
                  ? 'Open the vault to see secure items matching "$q". '
                    'Values are masked by default.'
                  : 'Open the vault to see your secure items. '
                    'Values are masked by default.',
              style: kWalletBodyStyle,
            )
          else if (items.isEmpty)
            Text(
              q != null && q.isNotEmpty
                  ? 'No secure items matching "$q" yet.'
                  : 'No secure items saved yet.',
              style: kWalletBodyStyle,
            )
          else ...[
            for (final it in items.take(10))
              _SecureItemRow(row: it),
            if (items.length > 10) ...[
              const SizedBox(height: 6),
              Text(
                '+${items.length - 10} more — open vault to view all',
                style: const TextStyle(
                  color: kWalletTextMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ],
          const SizedBox(height: 10),
          _pillMasked('Masked by default'),
        ],
      ),
    );
  }
}


class _SecureItemRow extends StatelessWidget {
  final Map<String, dynamic> row;
  const _SecureItemRow({required this.row});

  @override
  Widget build(BuildContext context) {
    final title = (row['title'] ?? '').toString();
    final type = (row['type'] ?? '').toString();
    final snippet = (row['snippet'] ?? '').toString();
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28, height: 28,
            decoration: BoxDecoration(
              color: kWalletBgBase,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: kWalletBorder),
            ),
            alignment: Alignment.center,
            child: const Icon(Icons.description_outlined,
                size: 16, color: kWalletTextMuted),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title.isEmpty ? 'Untitled' : title,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: kWalletTextPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (snippet.isNotEmpty || type.isNotEmpty)
                  Text(
                    snippet.isNotEmpty ? snippet : type,
                    overflow: TextOverflow.ellipsis,
                    maxLines: 2,
                    style: const TextStyle(
                      color: kWalletTextMuted,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


class _LoginCard extends StatelessWidget {
  final VaultChatCard card;
  final void Function(String service)?             onLoginEdit;
  final void Function(String service)?             onLoginDelete;
  final void Function(String service, String url)? onLoginOpenWebsite;
  final void Function(String query)?               onLoginChooseCandidate;

  const _LoginCard({
    required this.card,
    this.onLoginEdit,
    this.onLoginDelete,
    this.onLoginOpenWebsite,
    this.onLoginChooseCandidate,
  });

  @override
  Widget build(BuildContext context) {
    final data = card.data;
    final available = data != null && data['available'] == true;
    final query = card.query;

    final view = (data?['view'] as String?) ?? card.view ?? kVcrLoginViewList;

    // detail: full editable credential card (product decision 2026-07-11)
    if (available && view == kVcrLoginViewDetail) {
      final loginMap = data['login'];
      if (loginMap is Map<String, dynamic>) {
        return _LoginDetailCard(
          card: card,
          login: loginMap,
          pendingAction: (data['pending_action'] as String?)?.trim(),
          onEdit:         onLoginEdit,
          onDelete:       onLoginDelete,
          onOpenWebsite:  onLoginOpenWebsite,
        );
      }
    }

    // chooser: multi-match — user picks which one
    if (available && view == kVcrLoginViewChooser) {
      final logins = _asMapList(data['logins']);
      return _LoginChooserCard(
        card: card,
        logins: logins,
        onChooseCandidate: onLoginChooseCandidate,
      );
    }

    // not_found: friendly no-match state
    if (available && view == kVcrLoginViewNotFound) {
      return _shell(
        testKey: kVcrCardKeyLogin,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              query != null && query.isNotEmpty
                  ? 'No login found for "$query"'
                  : 'No login found',
              style: kWalletSectionHeadingStyle,
            ),
            const SizedBox(height: 6),
            const Text(
              'You do not have a saved login that matches this. Try '
              'another name, or open the Logins page to browse '
              'everything you have saved.',
              style: kWalletBodyStyle,
            ),
          ],
        ),
      );
    }


    final logins = _asMapList(data?['logins']);
    return _shell(
      testKey: kVcrCardKeyLogin,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            _loginHeader(view, query, logins.length),
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            const Text(
              'Open the vault to see your saved logins.',
              style: kWalletBodyStyle,
            )
          else if (logins.isEmpty) ...[
            Text(
              query != null && query.isNotEmpty
                  ? 'No logins matching "$query" yet.'
                  : 'No logins saved yet.',
              style: kWalletBodyStyle,
            ),
          ] else ...[
            for (final l in logins.take(10)) _LoginRow(row: l),
            if (logins.length > 10) ...[
              const SizedBox(height: 6),
              Text(
                '+${logins.length - 10} more — open vault to view all',
                style: const TextStyle(
                  color: kWalletTextMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}


/// Full editable saved-login card. Renders when the router LOGIN_SEARCH /
/// LOGIN_REVEAL / LOGIN_COPY dispatch resolves to a single specific
/// login and the vault key was verified for the current session.
///
/// The plaintext values (`username`, `password`, `website`, `notes`) come
/// from `card.data.login` — which is the ONLY server payload allowed to
/// carry a plaintext password (see backend
/// _sanitize_login_detail_payload). They are used inside this widget
/// only, never logged, never included in a plain-text chat message,
/// never sent back to OpenAI, never persisted in chat history.
class _LoginDetailCard extends StatefulWidget {
  final VaultChatCard card;
  final Map<String, dynamic> login;
  final String? pendingAction;
  final void Function(String service)?             onEdit;
  final void Function(String service)?             onDelete;
  final void Function(String service, String url)? onOpenWebsite;

  const _LoginDetailCard({
    required this.card,
    required this.login,
    this.pendingAction,
    this.onEdit,
    this.onDelete,
    this.onOpenWebsite,
  });

  @override
  State<_LoginDetailCard> createState() => _LoginDetailCardState();
}


class _LoginDetailCardState extends State<_LoginDetailCard> {
  bool _pendingDispatched = false;

  @override
  void initState() {
    super.initState();

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _maybeDispatchPendingAction();
    });
  }

  @override
  void didUpdateWidget(covariant _LoginDetailCard old) {
    super.didUpdateWidget(old);
    if (old.pendingAction != widget.pendingAction) {
      _pendingDispatched = false;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _maybeDispatchPendingAction();
      });
    }
  }

  void _maybeDispatchPendingAction() {
    if (_pendingDispatched) return;
    final action = (widget.pendingAction ?? '').trim();
    if (action.isEmpty) return;
    _pendingDispatched = true;
    final service = (widget.login['service'] ?? '').toString();
    final website = (widget.login['website'] ?? '').toString();
    switch (action) {
      case kVcrLoginActionEdit:
        if (widget.onEdit != null && service.isNotEmpty) {
          widget.onEdit!(service);
        }
        break;
      case kVcrLoginActionDelete:
        if (widget.onDelete != null && service.isNotEmpty) {
          widget.onDelete!(service);
        }
        break;
      case 'copy_username':
        _copyUsername();
        break;
      case 'copy_password':
        _copyPassword();
        break;
      case kVcrLoginActionCopy:

        _copyPassword();
        break;
      case kVcrLoginActionOpen:
        if (widget.onOpenWebsite != null &&
            service.isNotEmpty && website.isNotEmpty) {
          widget.onOpenWebsite!(service, website);
        }
        break;
      default:
        break;
    }
  }

  Future<void> _copyUsername() async {
    final v = (widget.login['username'] ?? '').toString();
    if (v.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: v));
    if (!mounted) return;
    _snack(context, 'Username copied');
  }

  Future<void> _copyPassword() async {
    final v = (widget.login['password'] ?? '').toString();
    if (v.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: v));
    if (!mounted) return;
    _snack(context, 'Password copied');
  }

  @override
  Widget build(BuildContext context) {
    final title    = (widget.login['title'] ?? '').toString();
    final service  = (widget.login['service'] ?? '').toString();
    final username = (widget.login['username'] ?? '').toString();
    final password = (widget.login['password'] ?? '').toString();
    final domain   = (widget.login['domain'] ?? '').toString();
    final website  = (widget.login['website'] ?? '').toString();
    final notes    = (widget.login['notes'] ?? '').toString();

    final vr = VaultResponsive.of(context);
    final narrow = vr.width < 380;

    return _shell(
      testKey: 'vault_chat_card_login_detail',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Container(
                width: 30, height: 30,
                decoration: BoxDecoration(
                  color: kWalletBgBase,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: kWalletBorder),
                ),
                alignment: Alignment.center,
                child: const Icon(Icons.vpn_key_outlined,
                    size: 18, color: kWalletTextPrimary),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title.isEmpty ? (service.isEmpty ? 'Login' : service)
                                : title,
                  key: const Key(
                    'vault_chat_card_login_detail_title',
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: kWalletSectionHeadingStyle,
                ),
              ),
            ],
          ),
          if (domain.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              domain,
              key: const Key(
                'vault_chat_card_login_detail_domain',
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: kWalletTextMuted,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
          const SizedBox(height: 12),

          if (username.isNotEmpty)
            _LoginDetailFieldRow(
              label: 'Username',
              valueKey: 'vault_chat_card_login_detail_username_value',
              copyKey:  'vault_chat_card_login_detail_username_copy',
              value: username,
              onCopy: _copyUsername,
              narrow: narrow,
            ),

          if (password.isNotEmpty) ...[
            const SizedBox(height: 8),
            _LoginDetailFieldRow(
              label: 'Password',
              valueKey: 'vault_chat_card_login_detail_password_value',
              copyKey:  'vault_chat_card_login_detail_password_copy',
              value: password,
              monospace: true,
              onCopy: _copyPassword,
              narrow: narrow,
            ),
          ],

          if (website.isNotEmpty) ...[
            const SizedBox(height: 8),
            _LoginDetailFieldRow(
              label: 'Website',
              valueKey: 'vault_chat_card_login_detail_website_value',
              copyKey:  'vault_chat_card_login_detail_website_open',
              value: website,
              copyIcon: Icons.open_in_new,
              onCopy: () {
                if (widget.onOpenWebsite != null && service.isNotEmpty) {
                  widget.onOpenWebsite!(service, website);
                }
              },
              narrow: narrow,
            ),
          ],

          if (notes.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              'Notes',
              style: const TextStyle(
                color: kWalletTextMuted,
                fontSize: 11,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.4,
              ),
            ),
            const SizedBox(height: 4),
            SelectableText(
              notes,
              key: const Key('vault_chat_card_login_detail_notes'),
              style: const TextStyle(
                color: kWalletTextPrimary, fontSize: 12,
              ),
            ),
          ],

          const SizedBox(height: 14),

          Wrap(
            spacing: 6, runSpacing: 6,
            children: [
              OutlinedButton.icon(
                key: const Key('vault_chat_card_login_detail_edit'),
                onPressed: (widget.onEdit != null && service.isNotEmpty)
                    ? () => widget.onEdit!(service)
                    : null,
                icon: const Icon(Icons.edit_outlined, size: 16),
                label: Text(
                  'Edit',
                  style: const TextStyle(fontSize: 12),
                ),
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 10, vertical: 6),
                  minimumSize: const Size(0, 32),
                ),
              ),
              OutlinedButton.icon(
                key: const Key('vault_chat_card_login_detail_delete'),
                onPressed: (widget.onDelete != null && service.isNotEmpty)
                    ? () => widget.onDelete!(service)
                    : null,
                icon: const Icon(Icons.delete_outline, size: 16),
                label: Text(
                  'Delete',
                  style: const TextStyle(fontSize: 12),
                ),
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 10, vertical: 6),
                  minimumSize: const Size(0, 32),
                  foregroundColor: const Color(0xFFE0605C),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}


class _LoginDetailFieldRow extends StatelessWidget {
  final String label;
  final String value;
  final String valueKey;
  final String copyKey;
  final bool monospace;
  final IconData copyIcon;
  final VoidCallback onCopy;
  final bool narrow;

  const _LoginDetailFieldRow({
    required this.label,
    required this.value,
    required this.valueKey,
    required this.copyKey,
    required this.onCopy,
    this.monospace = false,
    this.copyIcon = Icons.copy,
    this.narrow = false,
  });

  @override
  Widget build(BuildContext context) {
    final valueStyle = TextStyle(
      color: kWalletTextPrimary,
      fontSize: 13,
      fontFamily: monospace ? 'monospace' : null,
    );
    final labelStyle = const TextStyle(
      color: kWalletTextMuted,
      fontSize: 11,
      fontWeight: FontWeight.w700,
      letterSpacing: 0.4,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label.toUpperCase(), style: labelStyle),
        const SizedBox(height: 4),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Expanded(
              child: SelectableText(
                value,
                key: Key(valueKey),
                maxLines: 3,
                minLines: 1,
                style: valueStyle,
              ),
            ),
            const SizedBox(width: 8),
            IconButton(
              key: Key(copyKey),
              tooltip: MaterialLocalizations.of(context).copyButtonLabel,
              iconSize: 16,
              padding: EdgeInsets.zero,
              constraints: BoxConstraints.tightFor(
                width:  narrow ? 32 : 36,
                height: narrow ? 32 : 36,
              ),
              onPressed: onCopy,
              icon: Icon(copyIcon),
            ),
          ],
        ),
      ],
    );
  }
}


class _LoginChooserCard extends StatelessWidget {
  final VaultChatCard card;
  final List<Map<String, dynamic>> logins;
  final void Function(String query)? onChooseCandidate;

  const _LoginChooserCard({
    required this.card,
    required this.logins,
    this.onChooseCandidate,
  });

  @override
  Widget build(BuildContext context) {
    final q = card.query ?? '';
    return _shell(
      testKey: 'vault_chat_card_login_chooser',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            q.isNotEmpty
                ? '${logins.length} matches for "$q" — pick one'
                : 'Pick a login',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 8),
          for (final row in logins.take(20))
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: OutlinedButton(
                key: Key(
                  'vault_chat_card_login_chooser_option_'
                  '${(row['id'] ?? '').toString()}',
                ),
                onPressed: onChooseCandidate == null
                    ? null
                    : () {
                        final title = (row['title'] ??
                                       row['service'] ?? '').toString();
                        if (title.isNotEmpty) {
                          onChooseCandidate!(title);
                        }
                      },
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 12, vertical: 10),
                  minimumSize: const Size(double.infinity, 40),
                  alignment: Alignment.centerLeft,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      (row['title'] ?? row['service'] ?? '').toString(),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: kWalletTextPrimary,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    if ((row['username_masked'] ?? '').toString()
                        .isNotEmpty ||
                        (row['domain'] ?? '').toString().isNotEmpty)
                      Text(
                        [
                          if ((row['username_masked'] ?? '').toString()
                              .isNotEmpty)
                            (row['username_masked'] ?? '').toString(),
                          if ((row['domain'] ?? '').toString().isNotEmpty)
                            '· ${(row['domain'] ?? '').toString()}',
                        ].join(' '),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: kWalletTextMuted,
                          fontSize: 11,
                        ),
                      ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}


void _snack(BuildContext context, String message) {

  final m = ScaffoldMessenger.maybeOf(context);
  if (m == null) return;
  m.showSnackBar(
    SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
  );
}


String _loginHeader(String view, String? query, int count) {
  if (view == 'duplicates') {
    return 'Duplicate logins ($count)';
  }
  if (view == 'search' && query != null && query.isNotEmpty) {
    return 'Logins matching "$query" ($count)';
  }
  return 'Logins ($count)';
}


List<Map<String, dynamic>> _asMapList(dynamic raw) {
  if (raw is! List) return const <Map<String, dynamic>>[];
  final out = <Map<String, dynamic>>[];
  for (final e in raw) {
    if (e is Map<String, dynamic>) {
      out.add(e);
    } else if (e is Map) {
      out.add(e.cast<String, dynamic>());
    }
  }
  return out;
}


class _LoginRow extends StatelessWidget {
  final Map<String, dynamic> row;
  const _LoginRow({required this.row});

  @override
  Widget build(BuildContext context) {
    final title = (row['title'] ?? '').toString();
    final usernameMasked = (row['username_masked'] ?? '').toString();
    final domain = (row['domain'] ?? '').toString();
    final generated = row['generated'] == true;

    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: 28, height: 28,
            decoration: BoxDecoration(
              color: kWalletBgBase,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: kWalletBorder),
            ),
            alignment: Alignment.center,
            child: const Icon(Icons.lock_outline,
                size: 16, color: kWalletTextMuted),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title.isEmpty ? 'Untitled' : title,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: kWalletTextPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (usernameMasked.isNotEmpty || domain.isNotEmpty)
                  Text(
                    [
                      if (usernameMasked.isNotEmpty) usernameMasked,
                      if (domain.isNotEmpty) '· $domain',
                    ].join(' '),
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: kWalletTextMuted,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '•••••••••',
            style: const TextStyle(
              color: kWalletTextMuted,
              fontSize: 12,
              fontWeight: FontWeight.w800,
              letterSpacing: 1.2,
            ),
          ),
          if (generated) ...[
            const SizedBox(width: 8),
            const Icon(Icons.bolt,
                size: 14, color: kWalletTextMuted),
          ],
        ],
      ),
    );
  }
}


class _GeneratedLoginCard extends StatelessWidget {
  final VaultChatCard card;
  const _GeneratedLoginCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final isCreate = card.view == 'create_draft';
    return _shell(
      testKey: kVcrCardKeyGeneratedLogin,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).vaultCardGeneratedLogins,
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          Text(
            isCreate
                ? 'Chat can prepare a strong login draft. Saving the '
                  'generated login requires explicit confirmation '
                  'in the vault.'
                : 'Open the vault to see your generated logins.',
            style: kWalletBodyStyle,
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6, runSpacing: 6,
            children: [
              _pillMasked('•••••••••'),
              _pillMasked('Save requires confirmation'),
            ],
          ),
        ],
      ),
    );
  }
}


class _IdDocumentCard extends StatelessWidget {
  final VaultChatCard card;
  const _IdDocumentCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final data = card.data;
    final available = data != null && data['available'] == true;
    final docs = _asMapList(data?['documents']);

    return _shell(
      testKey: kVcrCardKeyIdDocument,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'ID documents (${docs.length})',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            const Text(
              'Sensitive numbers are masked by default. Reveal '
              'requires unlock + confirmation.',
              style: kWalletBodyStyle,
            )
          else if (docs.isEmpty)
            const Text(
              'No ID documents saved yet.',
              style: kWalletBodyStyle,
            )
          else ...[
            for (final d in docs.take(10)) _IdDocumentRow(row: d),
            if (docs.length > 10) ...[
              const SizedBox(height: 6),
              Text(
                '+${docs.length - 10} more — open vault to view all',
                style: const TextStyle(
                  color: kWalletTextMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ],
          const SizedBox(height: 8),
          Wrap(
            spacing: 6, runSpacing: 6,
            children: [
              _pillMasked('•••• •••• last-4'),
              _pillMasked('Reveal requires unlock'),
            ],
          ),
        ],
      ),
    );
  }
}


class _IdDocumentRow extends StatelessWidget {
  final Map<String, dynamic> row;
  const _IdDocumentRow({required this.row});

  @override
  Widget build(BuildContext context) {
    final type = (row['type'] ?? '').toString();
    final country = (row['issuing_country'] ?? '').toString();
    final state   = (row['issuing_state'] ?? '').toString();
    final expires = (row['expires_at'] ?? '').toString();
    final numberMasked = (row['id_number_masked'] ?? '').toString();

    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: 28, height: 28,
            decoration: BoxDecoration(
              color: kWalletBgBase,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: kWalletBorder),
            ),
            alignment: Alignment.center,
            child: const Icon(Icons.badge_outlined,
                size: 16, color: kWalletTextMuted),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  type.isEmpty ? 'ID document' : type.toUpperCase(),
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: kWalletTextPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (country.isNotEmpty ||
                    state.isNotEmpty ||
                    expires.isNotEmpty)
                  Text(
                    [
                      if (country.isNotEmpty) country,
                      if (state.isNotEmpty) state,
                      if (expires.isNotEmpty) 'exp $expires',
                    ].join(' · '),
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: kWalletTextMuted,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            numberMasked.isEmpty ? '•••' : numberMasked,
            style: const TextStyle(
              color: kWalletTextMuted,
              fontSize: 12,
              fontWeight: FontWeight.w800,
              letterSpacing: 1.2,
            ),
          ),
        ],
      ),
    );
  }
}


class _BillingStatusCard extends StatelessWidget {
  final VaultChatCard card;
  final VoidCallback? onOpenBillingPage;
  const _BillingStatusCard({
    required this.card, this.onOpenBillingPage,
  });

  @override
  Widget build(BuildContext context) {
    final upgrade = card.view == 'upgrade_prompt';
    final data = card.data;
    final available = data != null && data['available'] == true;
    final plan = (data?['plan'] ?? '').toString();
    final status = (data?['status'] ?? '').toString();
    final purchased = _asInt(data?['purchased_bytes']);
    final included = _asInt(data?['included_bytes']);
    final hasSub = data?['has_active_subscription'] == true;

    return _shell(
      testKey: kVcrCardKeyBillingStatus,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).vaultCardBilling,
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            Text(
              upgrade
                  ? 'To change plan or add storage, VaultAI will open '
                    'the existing gated checkout flow. Chat cannot '
                    'directly charge your card.'
                  : 'Open Billing to see your current plan.',
              style: kWalletBodyStyle,
            )
          else ...[
            Wrap(
              spacing: 6, runSpacing: 6,
              children: [
                Container(
                  key: const Key('vault_chat_billing_plan_pill'),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10, vertical: 5,
                  ),
                  decoration: BoxDecoration(
                    color: kWalletBgBase,
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: kWalletBorder),
                  ),
                  child: Text(
                    'Plan: ${plan.isEmpty ? "free" : plan}',
                    style: const TextStyle(
                      color: kWalletTextPrimary,
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                if (status.isNotEmpty)
                  _pillMasked('Status: $status'),
                if (hasSub) _pillMasked('Active'),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              purchased > 0
                  ? 'Included ${_formatBytes(included)} + '
                    'purchased ${_formatBytes(purchased)}.'
                  : 'Included ${_formatBytes(included)}.',
              style: const TextStyle(
                color: kWalletTextMuted,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
          if (onOpenBillingPage != null) ...[
            const SizedBox(height: 10),
            OutlinedButton(
              key: const Key('vault_chat_billing_open_btn'),
              onPressed: onOpenBillingPage,
              style: walletGhostButtonStyle(),
              child: Text(upgrade ? 'Open checkout' : 'Open billing'),
            ),
          ],
        ],
      ),
    );
  }
}


class _StorageUsageCard extends StatelessWidget {
  final VaultChatCard card;
  const _StorageUsageCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final data = card.data;
    final available = data != null && data['available'] == true;
    final used = _asInt(data?['used_bytes']);
    final quota = _asInt(data?['quota_bytes']);
    final pct = _asDouble(data?['percent_used']);
    final fileCount = _asInt(data?['file_count']);
    final docCount = _asInt(data?['document_count']);

    return _shell(
      testKey: kVcrCardKeyStorageUsage,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            AppLocalizations.of(context).storagePageTitle,
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            const Text(
              'Storage usage unavailable right now.',
              style: kWalletBodyStyle,
            )
          else ...[
            Text(
              quota > 0
                  ? '${_formatBytes(used)} of ${_formatBytes(quota)} '
                    'used (${pct.toStringAsFixed(0)}%)'
                  : '${_formatBytes(used)} used',
              style: const TextStyle(
                color: kWalletTextPrimary,
                fontSize: 13,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 6),
            _StorageBar(used: used, quota: quota, percent: pct),
            const SizedBox(height: 10),
            Wrap(
              spacing: 6, runSpacing: 6,
              children: [
                _statPill('Files',     fileCount),
                _statPill('Documents', docCount),
              ],
            ),
          ],
        ],
      ),
    );
  }
}


class _VaultActivityCard extends StatelessWidget {
  final VaultChatCard card;
  const _VaultActivityCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final data = card.data;
    final available = data != null && data['available'] == true;
    final events = _asMapList(data?['events']);

    return _shell(
      testKey: kVcrCardKeyVaultActivity,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Recent activity (${events.length})',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            const Text(
              'Open the vault to see a masked audit trail. VaultAI '
              'never leaks raw sensitive values in activity summaries.',
              style: kWalletBodyStyle,
            )
          else if (events.isEmpty)
            const Text(
              'No recent activity to show.',
              style: kWalletBodyStyle,
            )
          else ...[
            for (final e in events.take(10)) _ActivityRow(row: e),
            if (events.length > 10) ...[
              const SizedBox(height: 6),
              Text(
                '+${events.length - 10} more — open vault to view all',
                style: const TextStyle(
                  color: kWalletTextMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}


class _ActivityRow extends StatelessWidget {
  final Map<String, dynamic> row;
  const _ActivityRow({required this.row});

  @override
  Widget build(BuildContext context) {
    final action = (row['action'] ?? '').toString();
    final category = (row['category'] ?? '').toString();
    final title = (row['title'] ?? '').toString();
    final ts = (row['timestamp'] ?? '').toString();
    final label = action.replaceAll('_', ' ');
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: 8, height: 8,
            decoration: const BoxDecoration(
              color: kWalletTextMuted,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              [
                if (label.isNotEmpty) label,
                if (category.isNotEmpty) '· $category',
                if (title.isNotEmpty) '· $title',
              ].join(' '),
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: kWalletTextPrimary,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          if (ts.isNotEmpty)
            Text(
              ts.length > 10 ? ts.substring(0, 10) : ts,
              style: const TextStyle(
                color: kWalletTextMuted,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
        ],
      ),
    );
  }
}


class _CrossVaultSearchCard extends StatelessWidget {
  final VaultChatCard card;
  const _CrossVaultSearchCard({required this.card});

  @override
  Widget build(BuildContext context) {
    final data = card.data;
    final available = data != null && data['available'] == true;
    final groups = _asMapList(data?['groups']);
    final q = card.query ?? (data?['query'] ?? '').toString();

    return _shell(
      testKey: kVcrCardKeyCrossVaultSearch,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            q.isNotEmpty
                ? 'Vault search: "$q"'
                : 'Vault search',
            style: kWalletSectionHeadingStyle,
          ),
          const SizedBox(height: 6),
          if (!available)
            Text(
              q.isNotEmpty
                  ? 'Open the vault to search across files, secure '
                    'items, logins, and IDs for "$q".'
                  : 'Open the vault to search across categories.',
              style: kWalletBodyStyle,
            )
          else if (groups.isEmpty)
            Text(
              'No results for "$q" — try a broader term.',
              style: kWalletBodyStyle,
            )
          else ...[
            for (final g in groups) _SearchGroup(group: g),
          ],
        ],
      ),
    );
  }
}


class _SearchGroup extends StatelessWidget {
  final Map<String, dynamic> group;
  const _SearchGroup({required this.group});

  @override
  Widget build(BuildContext context) {
    final category = (group['category'] ?? '').toString();
    final count = _asInt(group['count']);
    final items = _asMapList(group['items']);
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '$category ($count)',
            style: const TextStyle(
              color: kWalletTextPrimary,
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 4),
          for (final it in items.take(5))
            Padding(
              padding: const EdgeInsets.only(top: 2, left: 6),
              child: Text(

                _safeSearchLabel(category, it),
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: kWalletTextMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
        ],
      ),
    );
  }
}


String _safeSearchLabel(String category, Map<String, dynamic> row) {
  if (category == 'logins') {
    final title = (row['title'] ?? row['service'] ?? '').toString();
    final u = (row['username_masked'] ?? '').toString();
    return u.isNotEmpty ? '$title — $u' : title;
  }
  if (category == 'secure_items') {
    return (row['title'] ?? 'Untitled').toString();
  }
  if (category == 'id_documents') {
    final t = (row['type'] ?? 'ID').toString();
    final m = (row['id_number_masked'] ?? '').toString();
    return m.isNotEmpty ? '$t — $m' : t;
  }
  if (category == 'files') {
    return (row['file_name'] ?? '').toString();
  }
  return (row['title'] ?? row['name'] ?? '').toString();
}


class _UnrecognizedCard extends StatelessWidget {
  final VaultChatCard card;
  const _UnrecognizedCard({required this.card});

  @override
  Widget build(BuildContext context) {
    return _shell(
      testKey: kVcrCardKeyUnrecognized,
      child: Text(
        card.message ?? 'That question is not something VaultAI chat '
            'can answer yet.',
        style: const TextStyle(
          color: kWalletTextMuted, fontSize: 13, height: 1.4,
        ),
      ),
    );
  }
}


class _FaqCard extends StatelessWidget {
  final VaultChatCard card;
  final VoidCallback? onOpenVault;
  final VoidCallback? onOpenLoginsPage;
  final VoidCallback? onOpenIdDocumentsPage;
  final VoidCallback? onOpenCryptoVaultPage;
  final VoidCallback? onOpenBillingPage;
  final VoidCallback? onOpenStoragePage;
  final VoidCallback? onOpenSecurityPage;
  final VoidCallback? onOpenHelpCenter;
  final VoidCallback? onOpenUploadPage;
  final void Function(String faqId)? onAskRelatedFaq;

  const _FaqCard({
    required this.card,
    this.onOpenVault,
    this.onOpenLoginsPage,
    this.onOpenIdDocumentsPage,
    this.onOpenCryptoVaultPage,
    this.onOpenBillingPage,
    this.onOpenStoragePage,
    this.onOpenSecurityPage,
    this.onOpenHelpCenter,
    this.onOpenUploadPage,
    this.onAskRelatedFaq,
  });

  VoidCallback? _handlerFor(String action) {
    switch (action) {
      case kVcrFaqActionOpenVault:        return onOpenVault;
      case kVcrFaqActionOpenLogins:       return onOpenLoginsPage;
      case kVcrFaqActionOpenIdDocs:       return onOpenIdDocumentsPage;
      case kVcrFaqActionOpenCryptoVault:  return onOpenCryptoVaultPage;
      case kVcrFaqActionOpenBilling:      return onOpenBillingPage;
      case kVcrFaqActionOpenStorage:      return onOpenStoragePage;
      case kVcrFaqActionOpenSecurity:     return onOpenSecurityPage;
      case kVcrFaqActionOpenHelpCenter:   return onOpenHelpCenter;
      case kVcrFaqActionOpenUpload:       return onOpenUploadPage;
      default:                            return null;
    }
  }

  String _actionLabel(String action) {
    switch (action) {
      case kVcrFaqActionOpenVault:        return 'Open vault';
      case kVcrFaqActionOpenLogins:       return 'Open Logins';
      case kVcrFaqActionOpenIdDocs:       return 'Open IDs';
      case kVcrFaqActionOpenCryptoVault:  return 'Open Crypto Vault';
      case kVcrFaqActionOpenBilling:      return 'Open Billing';
      case kVcrFaqActionOpenStorage:      return 'Open Storage';
      case kVcrFaqActionOpenSecurity:     return 'Open Security';
      case kVcrFaqActionOpenHelpCenter:   return 'Open Help Center';
      case kVcrFaqActionOpenUpload:       return 'Upload a file';
      default:                            return action;
    }
  }

  @override
  Widget build(BuildContext context) {
    final question = (card.faqQuestion ?? '').trim();
    final answer   = (card.faqAnswer ?? card.message ?? '').trim();
    final category = (card.faqCategoryLabel ?? '').trim();
    final relatedQuestions = card.faqRelatedQuestions;
    final relatedActions = card.faqRelatedActions
        .where((a) => _handlerFor(a) != null)
        .toList(growable: false);

    return _shell(
      testKey: kVcrCardKeyFaq,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.help_outline,
                  size: 18, color: Color(0xFF10A37F)),
              const SizedBox(width: 8),
              Text(
                'Help  •  $category',
                style: const TextStyle(
                  color: kWalletTextMuted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.4,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (question.isNotEmpty)
            Text(
              question,
              key: const Key('vault_faq_card_question'),
              style: const TextStyle(
                color: kWalletTextPrimary,
                fontSize: 15,
                fontWeight: FontWeight.w700,
                height: 1.35,
              ),
            ),
          if (question.isNotEmpty) const SizedBox(height: 6),
          Text(
            answer,
            key: const Key('vault_faq_card_answer'),
            style: const TextStyle(
              color: kWalletTextPrimary,
              fontSize: 13,
              height: 1.5,
            ),
          ),

          if (relatedActions.isNotEmpty) ...[
            const SizedBox(height: 12),
            Wrap(
              key: const Key('vault_faq_card_actions'),
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final action in relatedActions)
                  OutlinedButton.icon(
                    key: Key('vault_faq_action_$action'),
                    onPressed: _handlerFor(action),
                    icon: const Icon(Icons.open_in_new, size: 14),
                    label: Text(_actionLabel(action)),
                  ),
              ],
            ),
          ],

          if (relatedQuestions.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text(
              'Related',
              style: TextStyle(
                color: kWalletTextMuted,
                fontSize: 11,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.4,
              ),
            ),
            const SizedBox(height: 6),
            Wrap(
              key: const Key('vault_faq_card_related'),
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final r in relatedQuestions)
                  ActionChip(
                    key: Key('vault_faq_related_${r['id']}'),
                    label: Text(
                      r['question'] ?? '',
                      style: const TextStyle(fontSize: 12),
                    ),
                    onPressed: onAskRelatedFaq == null
                        ? null
                        : () => onAskRelatedFaq!(r['id'] ?? ''),
                  ),
              ],
            ),
          ],

          if (onOpenHelpCenter != null) ...[
            const SizedBox(height: 12),
            TextButton.icon(
              key: const Key('vault_faq_card_open_help_center'),
              onPressed: onOpenHelpCenter,
              icon: const Icon(Icons.menu_book_outlined, size: 14),
              label: Text(
                AppLocalizations.of(context).vaultCardBrowseAllHelp,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
