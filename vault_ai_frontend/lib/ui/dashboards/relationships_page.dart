

import 'package:flutter/material.dart';
import '../../api_client.dart';
import '../../l10n/app_localizations.dart';
import '../motion.dart';
import '../primitives.dart';
import '../tokens.dart';
import 'dashboard_shell.dart';


const List<String> _relationOrder = [
  'travel_related',
  'identity_related',
  'business_related',
  'finance_related',
  'tax_related',
  'medical_related',
  'family_related',
  'security_related',
  'media_related',
  'inheritance_related',
];

String _relationLabel(AppLocalizations l, String type) {
  switch (type) {
    case 'travel_related':      return l.relationshipsTypeTravel;
    case 'identity_related':    return l.relationshipsTypeIdentity;
    case 'business_related':    return l.relationshipsTypeBusiness;
    case 'finance_related':     return l.relationshipsTypeFinance;
    case 'tax_related':         return l.relationshipsTypeTax;
    case 'medical_related':     return l.relationshipsTypeMedical;
    case 'family_related':      return l.relationshipsTypeFamily;
    case 'security_related':    return l.relationshipsTypeSecurity;
    case 'media_related':       return l.relationshipsTypeMedia;
    case 'inheritance_related': return l.relationshipsTypeInheritance;
    default:                    return type.replaceAll('_', ' ');
  }
}

const Map<String, IconData> _relationIcons = {
  'travel_related':      Icons.flight_takeoff,
  'identity_related':    Icons.badge_outlined,
  'business_related':    Icons.business_center_outlined,
  'finance_related':     Icons.payments_outlined,
  'tax_related':         Icons.account_balance_outlined,
  'medical_related':     Icons.medical_information_outlined,
  'family_related':      Icons.family_restroom_outlined,
  'security_related':    Icons.shield_outlined,
  'media_related':       Icons.movie_outlined,
  'inheritance_related': Icons.diversity_3,
};

const Map<String, Color> _relationAccents = {
  'travel_related':      VaultColors.severityInfo,
  'identity_related':    VaultColors.accentBright,
  'business_related':    VaultColors.severityWarn,
  'finance_related':     VaultColors.severityOk,
  'tax_related':         VaultColors.severityWarn,
  'medical_related':     VaultColors.severityCrit,
  'family_related':      VaultColors.severityCrit,
  'security_related':    VaultColors.accent,
  'media_related':       VaultColors.accentBright,
  'inheritance_related': VaultColors.severityInfo,
};

class RelationshipsPage extends StatefulWidget {
  final VaultAIClient client;
  final String authToken;
  final String vaultName;
  final bool isMobile;
  final void Function(String prompt)? onAskVaultAI;

  const RelationshipsPage({
    super.key,
    required this.client,
    required this.authToken,
    required this.vaultName,
    required this.isMobile,
    this.onAskVaultAI,
  });

  @override
  State<RelationshipsPage> createState() => _RelationshipsPageState();
}

class _RelationshipsPageState extends State<RelationshipsPage> {
  List<Map<String, dynamic>>? _items;
  Map<String, dynamic> _counts = const {};
  bool _loading = true;
  String? _error;
  String? _relationFilter;
  final TextEditingController _searchCtrl = TextEditingController();
  String _searchQuery = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant RelationshipsPage old) {
    super.didUpdateWidget(old);
    if (old.vaultName != widget.vaultName ||
        old.authToken != widget.authToken) {
      _load();
    }
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final res = await widget.client.getRelationshipList(
        authToken: widget.authToken,
        vaultName: widget.vaultName,
      );
      if (!mounted) return;
      final raw = (res['items'] as List?) ?? const [];
      final counts = (res['counts'] is Map)
          ? (res['counts'] as Map).cast<String, dynamic>()
          : const <String, dynamic>{};
      setState(() {
        _items = raw
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList();
        _counts = counts;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = '$e';
        _loading = false;
      });
    }
  }

  bool _matchesSearch(Map<String, dynamic> row, String q) {
    if (q.isEmpty) return true;
    final src = (row['source'] is Map)
        ? (row['source'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final tgt = (row['target'] is Map)
        ? (row['target'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final srcLabel = (src['label'] as String? ?? '').toLowerCase();
    final tgtLabel = (tgt['label'] as String? ?? '').toLowerCase();
    final rel = (row['relation_type'] as String? ?? '').toLowerCase();
    return srcLabel.contains(q) || tgtLabel.contains(q) || rel.contains(q);
  }

  List<Map<String, dynamic>> get _filteredItems {
    final all = _items ?? const <Map<String, dynamic>>[];
    final q = _searchQuery.trim().toLowerCase();
    return all.where((m) {
      if (_relationFilter != null &&
          m['relation_type'] != _relationFilter) {
        return false;
      }
      return _matchesSearch(m, q);
    }).toList();
  }

  Map<String, List<Map<String, dynamic>>> _groupByType(
      List<Map<String, dynamic>> items) {
    final out = <String, List<Map<String, dynamic>>>{};
    for (final m in items) {
      final t = (m['relation_type'] as String?) ?? 'other';
      out.putIfAbsent(t, () => []).add(m);
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return DashboardScaffold(
      isMobile: widget.isMobile,
      title: l.relationshipsTitle,
      subtitle: l.relationshipsSubtitle,
      icon: Icons.hub_outlined,
      iconColor: VaultColors.severityInfo,
      actions: [
        OutlinedButton.icon(
          onPressed: _loading ? null : _load,
          icon: const Icon(Icons.refresh, size: 18),
          label: Text(l.commonRefresh),
        ),
      ],
      body: _buildBody(l),
    );
  }

  Widget _buildBody(AppLocalizations l) {
    if (_loading && _items == null) {
      return DashboardLoading(message: l.relationshipsLoading);
    }
    if (_error != null && _items == null) {
      return DashboardError(
        message: '${l.relationshipsErrorPrefix} $_error',
        onRetry: _load,
      );
    }

    final all = _items ?? const <Map<String, dynamic>>[];
    if (all.isEmpty) {
      return DashboardEmpty(
        title: l.relationshipsEmptyTitle,
        subtitle: l.relationshipsEmptySub,
        icon: Icons.hub_outlined,
      );
    }

    final filtered = _filteredItems;
    final grouped = _groupByType(filtered);
    final orderedKeys = [
      for (final k in _relationOrder)
        if (grouped.containsKey(k)) k,
      for (final k in grouped.keys)
        if (!_relationOrder.contains(k)) k,
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _RelationshipControls(
          counts: _counts,
          totalCount: all.length,
          activeRelation: _relationFilter,
          searchCtrl: _searchCtrl,
          onRelationChanged: (t) => setState(() => _relationFilter = t),
          onSearchChanged: (q) => setState(() => _searchQuery = q),
        ),
        if (filtered.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: VaultSpacing.lg),
            child: DashboardEmpty(
              title: l.relationshipsNoMatchTitle,
              subtitle: l.relationshipsNoMatchSub,
              icon: Icons.search_off,
            ),
          )
        else
          for (final key in orderedKeys)
            _RelationCluster(
              relationType: key,
              rows: grouped[key]!,
              isMobile: widget.isMobile,
              onAskVaultAI: widget.onAskVaultAI,
            ),
      ],
    );
  }
}


class _RelationshipControls extends StatelessWidget {
  final Map<String, dynamic> counts;
  final int totalCount;
  final String? activeRelation;
  final TextEditingController searchCtrl;
  final ValueChanged<String?> onRelationChanged;
  final ValueChanged<String> onSearchChanged;

  const _RelationshipControls({
    required this.counts,
    required this.totalCount,
    required this.activeRelation,
    required this.searchCtrl,
    required this.onRelationChanged,
    required this.onSearchChanged,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: searchCtrl,
            onChanged: onSearchChanged,
            style: VaultText.body,
            decoration: InputDecoration(
              hintText: l.relationshipsSearchHint,
              prefixIcon: const Icon(Icons.search, size: 18),
              suffixIcon: searchCtrl.text.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.close, size: 16),
                      onPressed: () {
                        searchCtrl.clear();
                        onSearchChanged('');
                      },
                    ),
              isDense: true,
            ),
          ),
          const SizedBox(height: VaultSpacing.md),
          Wrap(
            spacing: VaultSpacing.sm,
            runSpacing: VaultSpacing.sm,
            children: [
              _RelChip(
                label: l.commonAll,
                count: totalCount,
                icon: Icons.all_inclusive,
                accent: VaultColors.textPrimary,
                selected: activeRelation == null,
                onTap: () => onRelationChanged(null),
              ),
              for (final type in _relationOrder)
                if ((counts[type] as int? ?? 0) > 0)
                  _RelChip(
                    label: _relationLabel(l, type),
                    count: counts[type] as int? ?? 0,
                    icon: _relationIcons[type] ?? Icons.hub_outlined,
                    accent: _relationAccents[type] ?? VaultColors.accent,
                    selected: activeRelation == type,
                    onTap: () => onRelationChanged(
                      activeRelation == type ? null : type,
                    ),
                  ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RelChip extends StatelessWidget {
  final String label;
  final int count;
  final IconData icon;
  final Color accent;
  final bool selected;
  final VoidCallback onTap;

  const _RelChip({
    required this.label,
    required this.count,
    required this.icon,
    required this.accent,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(VaultRadius.pill),
      child: AnimatedContainer(
        duration: VaultMotion.standard,
        curve: VaultMotion.curveStandard,
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.md,
          vertical: VaultSpacing.sm,
        ),
        decoration: BoxDecoration(
          color: selected ? accent.withValues(alpha: 0.14) : VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.pill),
          border: Border.all(
            color: selected
                ? accent.withValues(alpha: 0.5)
                : VaultColors.borderSubtle,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: selected ? accent : VaultColors.textSecondary),
            const SizedBox(width: VaultSpacing.sm),
            Text(
              label,
              style: VaultText.caption.copyWith(
                color: selected ? VaultColors.textPrimary : VaultColors.textSecondary,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
            const SizedBox(width: VaultSpacing.sm),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(
                color: selected ? accent.withValues(alpha: 0.20) : VaultColors.surface,
                borderRadius: BorderRadius.circular(VaultRadius.sm),
              ),
              child: Text(
                '$count',
                style: VaultText.caption.copyWith(
                  color: selected ? accent : VaultColors.textTertiary,
                  fontWeight: FontWeight.w700,
                  fontSize: 11,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}


class _RelationCluster extends StatelessWidget {
  final String relationType;
  final List<Map<String, dynamic>> rows;
  final bool isMobile;
  final void Function(String prompt)? onAskVaultAI;

  const _RelationCluster({
    required this.relationType,
    required this.rows,
    required this.isMobile,
    this.onAskVaultAI,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final label = _relationLabel(l, relationType);
    final accent = _relationAccents[relationType] ?? VaultColors.accent;
    final icon = _relationIcons[relationType] ?? Icons.hub_outlined;

    return DashboardSection(
      title: label,
      icon: icon,
      trailing: MetaPill(
        label: '${rows.length}',
        icon: Icons.density_medium,
        tint: accent,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < rows.length; i++)
            Padding(
              padding: EdgeInsets.only(
                bottom: i == rows.length - 1 ? 0 : VaultSpacing.sm,
              ),
              child: FadeSlideIn(
                delay: Duration(milliseconds: 25 * i),
                child: _EdgeRowCard(
                  row: rows[i],
                  isMobile: isMobile,
                  accent: accent,
                  onAskVaultAI: onAskVaultAI,
                ),
              ),
            ),
        ],
      ),
    );
  }
}


class _EdgeRowCard extends StatelessWidget {
  final Map<String, dynamic> row;
  final bool isMobile;
  final Color accent;
  final void Function(String prompt)? onAskVaultAI;

  const _EdgeRowCard({
    required this.row,
    required this.isMobile,
    required this.accent,
    this.onAskVaultAI,
  });

  @override
  Widget build(BuildContext context) {
    final src = (row['source'] is Map)
        ? (row['source'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final tgt = (row['target'] is Map)
        ? (row['target'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final confidence = (row['confidence'] is num)
        ? (row['confidence'] as num).toDouble()
        : 1.0;
    final updatedAt = (row['updated_at'] as String?) ?? '';
    final srcLabel = (src['label'] as String?) ?? 'asset';

    return VaultCard(
      color: VaultColors.surfaceElevated,
      padding: const EdgeInsets.all(VaultSpacing.lg),
      onTap: onAskVaultAI == null
          ? null
          : () => onAskVaultAI!(
              AppLocalizations.of(context).relationshipsAskRelated(srcLabel),
            ),
      child: isMobile
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _EndpointTile(endpoint: src, accent: accent),
                Padding(
                  padding: const EdgeInsets.symmetric(
                    vertical: VaultSpacing.sm,
                    horizontal: VaultSpacing.sm,
                  ),
                  child: _Connector(accent: accent),
                ),
                _EndpointTile(endpoint: tgt, accent: accent),
                const SizedBox(height: VaultSpacing.sm),
                _MetaRow(
                  confidence: confidence,
                  updatedAt: updatedAt,
                ),
              ],
            )
          : Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Expanded(child: _EndpointTile(endpoint: src, accent: accent)),
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: VaultSpacing.md,
                  ),
                  child: _Connector(accent: accent),
                ),
                Expanded(child: _EndpointTile(endpoint: tgt, accent: accent)),
                const SizedBox(width: VaultSpacing.md),
                SizedBox(
                  width: 110,
                  child: _MetaRow(
                    confidence: confidence,
                    updatedAt: updatedAt,
                    vertical: true,
                  ),
                ),
              ],
            ),
    );
  }
}

class _EndpointTile extends StatelessWidget {
  final Map<String, dynamic> endpoint;
  final Color accent;

  const _EndpointTile({required this.endpoint, required this.accent});

  @override
  Widget build(BuildContext context) {
    final label = (endpoint['label'] as String?) ?? 'asset';
    final kind = (endpoint['kind'] as String?) ?? '';
    final iconHint = (endpoint['icon'] as String?) ?? '';
    final subType = (endpoint['sub_type'] as String?) ?? '';
    final l = AppLocalizations.of(context);
    final kindLabel = kind == 'uploaded_file'
        ? l.relationshipsEndpointFile
        : l.relationshipsEndpointItem;

    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Row(
        children: [
          IconBadge(
            icon: _iconForHint(iconHint),
            color: accent,
            size: 36,
            radius: VaultRadius.sm,
          ),
          const SizedBox(width: VaultSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  label,
                  style: VaultText.subtitle.copyWith(fontSize: 14),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                Text(
                  subType.isNotEmpty
                      ? '$kindLabel / $subType'
                      : kindLabel,
                  style: VaultText.caption,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  IconData _iconForHint(String hint) {
    switch (hint) {
      case 'passport':       return Icons.book_outlined;
      case 'visa':           return Icons.flight_takeoff;
      case 'id_card':        return Icons.badge_outlined;
      case 'driver_license': return Icons.directions_car_outlined;
      case 'invoice':        return Icons.receipt_long_outlined;
      case 'receipt':        return Icons.receipt_outlined;
      case 'contract':       return Icons.handshake_outlined;
      case 'agreement':      return Icons.description_outlined;
      case 'medical':        return Icons.medical_information_outlined;
      case 'tax':            return Icons.account_balance_outlined;
      case 'business':       return Icons.business_center_outlined;
      case 'insurance':      return Icons.shield_outlined;
      case 'memory':         return Icons.auto_awesome_outlined;
      case 'travel':         return Icons.flight;
      case 'family':         return Icons.people_outline;
      case 'finance':        return Icons.payments_outlined;
      default:               return Icons.circle_outlined;
    }
  }
}

class _Connector extends StatelessWidget {
  final Color accent;
  const _Connector({required this.accent});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 36,
      height: 36,
      decoration: BoxDecoration(
        color: accent.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(VaultRadius.pill),
        border: Border.all(color: accent.withValues(alpha: 0.4)),
      ),
      child: Icon(Icons.swap_horiz, color: accent, size: 18),
    );
  }
}

class _MetaRow extends StatelessWidget {
  final double confidence;
  final String updatedAt;
  final bool vertical;

  const _MetaRow({
    required this.confidence,
    required this.updatedAt,
    this.vertical = false,
  });

  @override
  Widget build(BuildContext context) {
    final confidenceLabel = '${(confidence * 100).round()}%';
    final dateLabel =
        updatedAt.length >= 10 ? updatedAt.substring(0, 10) : updatedAt;

    final pills = <Widget>[
      MetaPill(
        label: confidenceLabel,
        icon: Icons.percent,
        dim: confidence < 0.5,
      ),
      if (dateLabel.isNotEmpty)
        MetaPill(label: dateLabel, icon: Icons.update),
    ];

    if (vertical) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < pills.length; i++) ...[
            pills[i],
            if (i != pills.length - 1) const SizedBox(height: VaultSpacing.xs),
          ],
        ],
      );
    }

    return Wrap(
      spacing: VaultSpacing.sm,
      runSpacing: VaultSpacing.xs,
      children: pills,
    );
  }
}
