
import 'package:flutter/material.dart';

import 'help_center_content.dart';
import 'help_center_content_i18n.dart' as faq_i18n;
import 'l10n/app_localizations.dart';
import 'ui/responsive.dart';


enum HelpCenterMode { public, signedIn }




const String kHelpCenterTitle    = 'Help & FAQ';
const String kHelpCenterHeading  = kHelpCenterTitle;
const String kHelpCenterSubtitle =
    'Answers to common questions about VaultAI. Search below or '
    'browse by category — the AI assistant answers from the same '
    'set of topics.';
const String kHelpCenterEmpty     = 'No matching help topics';
const String kHelpCenterEmptyBody =
    'Try a different search term, or pick a category chip.';
const String kHelpCenterSupportNote =
    'Live customer support is not available yet. Use this Help '
    'Center or ask VaultAI Chat for help.';
const String kHelpCenterPublicHint =
    "You're viewing the public Help Center. Sign in to ask "
    'VaultAI and see account details.';




String localisedFaqCategoryLabel(AppLocalizations l, String categoryId) {
  switch (categoryId) {
    case 'getting_started': return l.helpCategoryGettingStarted;
    case 'security':        return l.helpCategorySecurity;
    case 'files':           return l.helpCategoryFiles;
    case 'secure_items':    return l.helpCategorySecureItems;
    case 'ids':             return l.helpCategoryIds;
    case 'crypto':          return l.helpCategoryCrypto;
    case 'billing':         return l.helpCategoryBilling;
    case 'troubleshooting': return l.helpCategoryTroubleshooting;
    default:                return categoryId;
  }
}


class HelpCenterPage extends StatefulWidget {
  final HelpCenterMode mode;


  final void Function(String question)? onAskAssistant;


  final VoidCallback? onRequireSignIn;


  final VoidCallback? onClose;

  const HelpCenterPage({
    super.key,
    this.mode = HelpCenterMode.signedIn,
    this.onAskAssistant,
    this.onRequireSignIn,
    this.onClose,
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
      localeCode, _query,
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
      key: Key(_isPublic
          ? 'help_center_page_public'
          : 'help_center_page'),
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
            ],
          ),
        ),
      ),
    );
  }
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
                  l.helpCenterTitle,
                  key: const Key('help_center_heading'),
                  style: TextStyle(
                    fontSize: vrHeadline(context),
                    fontWeight: FontWeight.w800,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  l.helpCenterSubtitle,
                  key: const Key('help_center_subtitle'),
                  style: const TextStyle(
                    color: Color(0xFFB4B4B4), fontSize: 15,
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
          const Icon(Icons.info_outline,
              size: 16, color: Color(0xFF10A37F)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              l.helpCenterPublicHint,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13, height: 1.5,
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
    required this.controller, required this.onChanged,
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
          const Icon(Icons.search,
              color: Color(0xFF8E8E8E), size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              key: const Key('help_center_search_field'),
              controller: controller,
              onChanged: onChanged,
              style: const TextStyle(
                  color: Colors.white, fontSize: 14),
              decoration: InputDecoration(
                isCollapsed: true,
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
                hintText: l.helpCenterSearchHint,
                hintStyle: const TextStyle(
                    color: Color(0xFF8E8E8E), fontSize: 13),
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
              icon: const Icon(Icons.close,
                  size: 16, color: Color(0xFF8E8E8E)),
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
    required this.active, required this.onSelect,
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
            color: selected
                ? const Color(0xFF10A37F)
                : const Color(0xFFB4B4B4),
            fontSize: 12, fontWeight: FontWeight.w600,
          ),
          selected: selected,
          backgroundColor: const Color(0xFF1F1F1F),
          selectedColor:
              const Color(0xFF10A37F).withValues(alpha: 0.18),
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
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF2A2A2A),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8, runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: const Color(0xFF10A37F)
                      .withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  localisedFaqCategoryLabel(l, entry.category),
                  style: const TextStyle(
                    color: Color(0xFF10A37F),
                    fontSize: 11, fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            entry.question,
            key: Key('help_entry_question_${entry.id}'),
            style: const TextStyle(
              color: Colors.white, fontSize: 15,
              fontWeight: FontWeight.w700, height: 1.35,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            entry.answer,
            key: Key('help_entry_answer_${entry.id}'),
            style: const TextStyle(
              color: Color(0xFFDCDCDC),
              fontSize: 13, height: 1.5,
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
              color: Colors.white, fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            l.helpCenterEmptyBody,
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 13, height: 1.5,
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
          const Icon(Icons.info_outline,
              size: 16, color: Color(0xFF8E8E8E)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              l.helpCenterSupportNote,
              style: const TextStyle(
                color: Color(0xFFB4B4B4),
                fontSize: 12, height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
