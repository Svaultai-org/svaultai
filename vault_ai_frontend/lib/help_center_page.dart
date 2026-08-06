import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import 'help_center_content.dart';
import 'help_center_content_i18n.dart' as faq_i18n;
import 'l10n/app_localizations.dart';
import 'ui/responsive.dart';

enum HelpCenterMode { public, signedIn }

typedef HelpLaunchMailFn = Future<bool> Function(Uri uri);
typedef HelpClipboardWriteFn = Future<void> Function(String text);

Future<void> _defaultClipboardWrite(String text) =>
    Clipboard.setData(ClipboardData(text: text));

const String kHelpCenterTitle = 'SVaultAI Help Center';
const String kHelpCenterHeading = kHelpCenterTitle;
const String kHelpCenterSubtitle =
    'Answers to common questions about SVaultAI. Search below or '
    'browse by category — the AI assistant answers from the same '
    'set of topics.';
const String kHelpCenterEmpty = 'No matching help topics';
const String kHelpCenterEmptyBody =
    'Try a different search term, or pick a category chip.';
const String kHelpCenterSupportNote =
    'Live customer support is not available yet. Use this Help '
    'Center or ask SVaultAI Chat for help.';
const String kHelpCenterPublicHint =
    "You're viewing the public Help Center. Sign in to ask "
    'SVaultAI and see account details.';

const String kHelpContactSupportEmail = 'vaultai@svaultai.com';
const String kHelpPrivacyPolicyUrl = 'https://app.svaultai.com/privacy';
const String kHelpTermsOfServiceUrl = 'https://app.svaultai.com/terms';
const String kHelpContactSupportMailtoUrl = 'mailto:vaultai@svaultai.com'
    '?subject=SVaultAI%20Support'
    '&body=Please%20describe%20your%20issue%20below.'
    '%0A%0ADevice:%20'
    '%0APlatform:%20Android/iPhone/Web/Desktop'
    '%0AApp%20Version:%20';

String localisedFaqCategoryLabel(AppLocalizations l, String categoryId) {
  switch (categoryId) {
    case 'getting_started':
      return l.helpCategoryGettingStarted;
    case 'security':
      return l.helpCategorySecurity;
    case 'files':
      return l.helpCategoryFiles;
    case 'secure_items':
      return l.helpCategorySecureItems;
    case 'ids':
      return l.helpCategoryIds;
    case 'crypto':
      return l.helpCategoryCrypto;
    case 'billing':
      return l.helpCategoryBilling;
    case 'troubleshooting':
      return l.helpCategoryTroubleshooting;
    default:
      for (final category in kFaqCategories) {
        if (category.id == categoryId) return category.label;
      }
      return categoryId;
  }
}

class HelpCenterPage extends StatefulWidget {
  final HelpCenterMode mode;

  final void Function(String question)? onAskAssistant;

  final VoidCallback? onRequireSignIn;

  final VoidCallback? onClose;

  final HelpLaunchMailFn? launchMailOverride;

  final HelpClipboardWriteFn? clipboardWriteOverride;

  const HelpCenterPage({
    super.key,
    this.mode = HelpCenterMode.signedIn,
    this.onAskAssistant,
    this.onRequireSignIn,
    this.onClose,
    this.launchMailOverride,
    this.clipboardWriteOverride,
  });

  @override
  State<HelpCenterPage> createState() => _HelpCenterPageState();
}

class _HelpCenterPageState extends State<HelpCenterPage> {
  String _query = '';
  FaqCategory? _activeCategory;
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

  List<FaqEntry> _visibleEntriesFor(String? localeCode) {
    final base = faq_i18n.localizedFaqEntriesMatchingQuery(
      localeCode,
      _query,
    );
    if (_activeCategory == null) return base;
    return base
        .where((e) => e.category == _activeCategory!.id)
        .toList(growable: false);
  }

  bool get _isPublic => widget.mode == HelpCenterMode.public;

  @override
  Widget build(BuildContext context) {
    final localeCode = Localizations.localeOf(context).languageCode;
    final entries = _visibleEntriesFor(localeCode);
    return SingleChildScrollView(
      key: Key(_isPublic ? 'help_center_page_public' : 'help_center_page'),
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _HelpHeader(
                onClose: widget.onClose,
                isPublic: _isPublic,
              ),
              if (_isPublic) ...[
                const SizedBox(height: 12),
                _PublicModeBanner(
                  onRequireSignIn: widget.onRequireSignIn,
                ),
              ],
              const SizedBox(height: 16),
              Container(
                key: const Key('help_center_privacy_summary'),
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFF10A37F).withValues(alpha: .10),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(
                      color: const Color(0xFF10A37F).withValues(alpha: .35)),
                ),
                child: const Text(
                    'Your vault belongs to you. SVaultAI cannot open your vault. We do not have a master key, developer backdoor, or support tool that reveals protected vault contents.',
                    style: TextStyle(height: 1.5, fontWeight: FontWeight.w600)),
              ),
              const SizedBox(height: 10),
              const _TrustCard(
                key: Key('help_center_wallet_summary'),
                icon: Icons.account_balance_wallet_outlined,
                title: 'You control your wallet',
                body:
                    'Your wallet is controlled through your protected vault. SVaultAI cannot independently move, freeze, or recover your funds.',
              ),
              const SizedBox(height: 10),
              const _TrustCard(
                key: Key('help_center_inactivity_summary'),
                icon: Icons.schedule_outlined,
                title: 'Keep an unsubscribed vault active',
                body:
                    'An unsubscribed vault that is not logged into for six months may be automatically deleted.',
              ),
              const SizedBox(height: 16),
              _HelpSearchBar(
                controller: _searchCtrl,
                onChanged: (v) => setState(() => _query = v),
              ),
              const SizedBox(height: 12),
              _HelpCategoryStrip(
                active: _activeCategory,
                onSelect: (c) => setState(() {
                  _activeCategory = (c == _activeCategory) ? null : c;
                }),
              ),
              const SizedBox(height: 12),
              if (entries.isEmpty)
                const _HelpEmptyState()
              else
                ...entries.map((e) => _HelpEntryCard(
                      key: Key('help_center_entry_${e.id}'),
                      entry: e,
                      isPublic: _isPublic,
                      onAskAssistant: widget.onAskAssistant,
                      onRequireSignIn: widget.onRequireSignIn,
                    )),
              const SizedBox(height: 24),
              const _HelpSupportNote(),
              const SizedBox(height: 12),
              _HelpContactSupport(
                launchMailOverride: widget.launchMailOverride,
                clipboardWriteOverride: widget.clipboardWriteOverride,
              ),
              Wrap(
                key: const Key('help_center_legal_links'),
                spacing: 8,
                children: [
                  TextButton(
                      key: const Key('help_privacy_policy_link'),
                      onPressed: () =>
                          launchUrl(Uri.parse(kHelpPrivacyPolicyUrl)),
                      child: const Text('Privacy Policy')),
                  TextButton(
                      key: const Key('help_terms_link'),
                      onPressed: () =>
                          launchUrl(Uri.parse(kHelpTermsOfServiceUrl)),
                      child: const Text('Terms of Service')),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TrustCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String body;
  const _TrustCard(
      {super.key, required this.icon, required this.title, required this.body});

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(icon, color: const Color(0xFF10A37F)),
            const SizedBox(width: 12),
            Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                  Text(title,
                      style: const TextStyle(fontWeight: FontWeight.w800)),
                  const SizedBox(height: 4),
                  Text(body, style: const TextStyle(height: 1.45)),
                ])),
          ]),
        ),
      );
}

class _HelpHeader extends StatelessWidget {
  final VoidCallback? onClose;
  final bool isPublic;
  const _HelpHeader({this.onClose, this.isPublic = false});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: const Color(0xFF2F2F2F),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  kHelpCenterTitle,
                  key: const Key('help_center_heading'),
                  style: TextStyle(
                    fontSize: vrHeadline(context),
                    fontWeight: FontWeight.w800,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'SVaultAI is designed to protect the things you would normally keep in a private vault—documents, credentials, memories, and digital assets. This Help Center explains how the vault works, what SVaultAI can and cannot access, and what you should do to protect your account.',
                  key: const Key('help_center_subtitle'),
                  style: const TextStyle(
                    color: Color(0xFFB4B4B4),
                    fontSize: 15,
                    height: 1.5,
                  ),
                ),
              ],
            ),
          ),
          if (onClose != null)
            IconButton(
              key: const Key('help_center_close'),
              tooltip: l.commonClose,
              icon: const Icon(Icons.close, color: Colors.white70),
              onPressed: onClose,
            ),
        ],
      ),
    );
  }
}

class _PublicModeBanner extends StatelessWidget {
  final VoidCallback? onRequireSignIn;
  const _PublicModeBanner({this.onRequireSignIn});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      key: const Key('help_center_public_banner'),
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF10A37F).withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: const Color(0xFF10A37F).withValues(alpha: 0.30),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline, size: 16, color: Color(0xFF10A37F)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              l.helpCenterPublicHint,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
                height: 1.5,
              ),
            ),
          ),
          if (onRequireSignIn != null) ...[
            const SizedBox(width: 12),
            OutlinedButton(
              key: const Key('help_center_public_sign_in'),
              onPressed: onRequireSignIn,
              child: Text(l.commonSignIn),
            ),
          ],
        ],
      ),
    );
  }
}

class _HelpSearchBar extends StatelessWidget {
  final TextEditingController controller;
  final ValueChanged<String> onChanged;
  const _HelpSearchBar({
    required this.controller,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      key: const Key('help_center_search_bar'),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white12),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          const Icon(Icons.search, color: Color(0xFF8E8E8E), size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              key: const Key('help_center_search_field'),
              controller: controller,
              onChanged: onChanged,
              style: const TextStyle(color: Colors.white, fontSize: 14),
              decoration: InputDecoration(
                isCollapsed: true,
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
                hintText: l.helpCenterSearchHint,
                hintStyle:
                    const TextStyle(color: Color(0xFF8E8E8E), fontSize: 13),
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
              ),
            ),
          ),
          if (controller.text.isNotEmpty)
            IconButton(
              key: const Key('help_center_search_clear'),
              tooltip: l.helpCenterClearSearch,
              icon: const Icon(Icons.close, size: 16, color: Color(0xFF8E8E8E)),
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

class _HelpCategoryStrip extends StatelessWidget {
  final FaqCategory? active;
  final ValueChanged<FaqCategory> onSelect;
  const _HelpCategoryStrip({
    required this.active,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Wrap(
      key: const Key('help_center_category_strip'),
      spacing: 8,
      runSpacing: 8,
      children: kFaqCategories.map((c) {
        final selected = c.id == active?.id;
        return ChoiceChip(
          key: Key('help_center_chip_${c.id}'),
          showCheckmark: false,
          label: Text(localisedFaqCategoryLabel(l, c.id)),
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
          onSelected: (_) => onSelect(c),
        );
      }).toList(growable: false),
    );
  }
}

class _HelpEntryCard extends StatelessWidget {
  final FaqEntry entry;
  final bool isPublic;
  final void Function(String question)? onAskAssistant;
  final VoidCallback? onRequireSignIn;
  const _HelpEntryCard({
    super.key,
    required this.entry,
    this.isPublic = false,
    this.onAskAssistant,
    this.onRequireSignIn,
  });

  Widget? _buildAskAction(AppLocalizations l) {
    if (isPublic) {
      if (onRequireSignIn == null) return null;
      return OutlinedButton.icon(
        key: Key('help_entry_signin_${entry.id}'),
        onPressed: onRequireSignIn,
        icon: const Icon(Icons.login, size: 14),
        label: Text(l.helpCenterSignInToAsk),
      );
    }
    if (onAskAssistant == null) return null;
    return OutlinedButton.icon(
      key: Key('help_entry_ask_${entry.id}'),
      onPressed: () => onAskAssistant!(entry.question),
      icon: const Icon(Icons.smart_toy_outlined, size: 14),
      label: Text(l.commonAskVaultAI),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final askButton = _buildAskAction(l);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      clipBehavior: Clip.antiAlias,
      child: ExpansionTile(
        key: Key('help_entry_expansion_${entry.id}'),
        title: Text(
          entry.question,
          key: Key('help_entry_question_${entry.id}'),
          style: const TextStyle(
              fontSize: 15, fontWeight: FontWeight.w700, height: 1.35),
        ),
        subtitle: Text(localisedFaqCategoryLabel(l, entry.category)),
        childrenPadding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              entry.answer,
              key: Key('help_entry_answer_${entry.id}'),
              style: const TextStyle(fontSize: 14, height: 1.55),
            ),
          ),
          if (askButton != null) ...[
            const SizedBox(height: 10),
            askButton,
          ],
        ],
      ),
    );
  }
}

class _HelpEmptyState extends StatelessWidget {
  const _HelpEmptyState();

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      key: const Key('help_center_empty'),
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l.helpCenterEmpty,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            l.helpCenterEmptyBody,
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

class _HelpContactSupport extends StatelessWidget {
  final HelpLaunchMailFn? launchMailOverride;
  final HelpClipboardWriteFn? clipboardWriteOverride;
  const _HelpContactSupport({
    this.launchMailOverride,
    this.clipboardWriteOverride,
  });

  Future<void> _openMail(BuildContext context) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.maybeOf(context);
    final uri = Uri.parse(kHelpContactSupportMailtoUrl);
    bool ok = false;
    try {
      final launcher = launchMailOverride ?? launchUrl;
      ok = await launcher(uri);
    } catch (_) {
      ok = false;
    }
    if (!ok && messenger != null && context.mounted) {
      messenger.showSnackBar(
        SnackBar(
          key: const Key('help_contact_support_snackbar'),
          content: Text(
            l.helpContactSupportEmailOpenFailed(
              kHelpContactSupportEmail,
            ),
          ),
        ),
      );
    }
  }

  Future<void> _copyEmail(BuildContext context) async {
    final l = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.maybeOf(context);
    final writer = clipboardWriteOverride ?? _defaultClipboardWrite;
    try {
      await writer(kHelpContactSupportEmail);
    } catch (_) {
      return;
    }
    if (messenger != null && context.mounted) {
      messenger.showSnackBar(
        SnackBar(
          key: const Key('help_contact_support_copy_snackbar'),
          content: Text(l.helpContactSupportEmailCopied),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      key: const Key('help_center_contact_support'),
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l.helpContactSupportTitle,
            key: const Key('help_contact_support_title'),
            style: const TextStyle(
              color: Colors.white,
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            l.helpContactSupportBody,
            key: const Key('help_contact_support_body'),
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 13,
              height: 1.5,
            ),
          ),
          const SizedBox(height: 12),
          Semantics(
            button: true,
            label: l.helpContactSupportEmailA11yLabel(
              kHelpContactSupportEmail,
            ),
            child: InkWell(
              key: const Key('help_contact_support_email_link'),
              onTap: () => _openMail(context),
              borderRadius: BorderRadius.circular(10),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
                child: Row(
                  children: [
                    const Icon(
                      Icons.mail_outline,
                      size: 18,
                      color: Color(0xFF10A37F),
                    ),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        kHelpContactSupportEmail,
                        key: const Key(
                          'help_contact_support_email_text',
                        ),
                        style: const TextStyle(
                          color: Color(0xFF10A37F),
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          decoration: TextDecoration.underline,
                          decorationColor: Color(0xFF10A37F),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 4),
          Semantics(
            button: true,
            label: l.helpContactSupportCopyEmailA11yLabel(
              kHelpContactSupportEmail,
            ),
            child: InkWell(
              key: const Key('help_contact_support_copy_email_button'),
              onTap: () => _copyEmail(context),
              borderRadius: BorderRadius.circular(10),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
                child: Row(
                  children: [
                    const Icon(
                      Icons.copy_rounded,
                      size: 16,
                      color: Color(0xFFB4B4B4),
                    ),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        l.helpContactSupportCopyEmailLabel,
                        key: const Key(
                          'help_contact_support_copy_email_text',
                        ),
                        style: const TextStyle(
                          color: Color(0xFFB4B4B4),
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HelpSupportNote extends StatelessWidget {
  const _HelpSupportNote();

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Container(
      key: const Key('help_center_support_note'),
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline, size: 16, color: Color(0xFF8E8E8E)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              l.helpCenterSupportNote,
              style: const TextStyle(
                color: Color(0xFFB4B4B4),
                fontSize: 12,
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
