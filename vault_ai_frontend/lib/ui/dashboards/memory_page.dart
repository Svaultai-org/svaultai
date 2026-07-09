

import 'package:flutter/material.dart';
import '../../api_client.dart';
import '../../l10n/app_localizations.dart';
import '../motion.dart';
import '../primitives.dart';
import '../tokens.dart';
import 'dashboard_shell.dart';


const List<String> _memoryTypeOrder = [
  'identity',
  'people',
  'family',
  'business',
  'travel',
  'projects',
  'goals',
  'places',
  'dates',
  'life_event',
  'preferences',
  'note',
];

String _memoryTypeLabel(AppLocalizations l, String type) {
  switch (type) {
    case 'identity':    return l.memoryTypeIdentity;
    case 'people':      return l.memoryTypePeople;
    case 'family':      return l.memoryTypeFamily;
    case 'business':    return l.memoryTypeBusiness;
    case 'travel':      return l.memoryTypeTravel;
    case 'projects':    return l.memoryTypeProjects;
    case 'goals':       return l.memoryTypeGoals;
    case 'places':      return l.memoryTypePlaces;
    case 'dates':       return l.memoryTypeDates;
    case 'life_event':  return l.memoryTypeLifeEvent;
    case 'preferences': return l.memoryTypePreferences;
    case 'note':        return l.memoryTypeNote;
    default:            return type;
  }
}

const Map<String, IconData> _memoryTypeIcons = {
  'identity':    Icons.badge_outlined,
  'people':      Icons.people_outline,
  'family':      Icons.family_restroom_outlined,
  'business':    Icons.business_center_outlined,
  'travel':      Icons.flight_takeoff,
  'projects':    Icons.task_alt_outlined,
  'goals':       Icons.flag_outlined,
  'places':      Icons.place_outlined,
  'dates':       Icons.event_outlined,
  'life_event':  Icons.celebration_outlined,
  'preferences': Icons.tune_outlined,
  'note':        Icons.note_outlined,
};

const Map<String, Color> _memoryTypeAccents = {
  'identity':    VaultColors.severityInfo,
  'people':      VaultColors.accentBright,
  'family':      VaultColors.severityCrit,
  'business':    VaultColors.severityWarn,
  'travel':      VaultColors.severityInfo,
  'projects':    VaultColors.accentBright,
  'goals':       VaultColors.severityOk,
  'places':      VaultColors.severityInfo,
  'dates':       VaultColors.severityWarn,
  'life_event':  VaultColors.accentBright,
  'preferences': VaultColors.textSecondary,
  'note':        VaultColors.textSecondary,
};

class MemoryPage extends StatefulWidget {
  final VaultAIClient client;
  final String authToken;
  final String vaultName;
  final bool isMobile;
  final void Function(String prompt)? onAskVaultAI;

  const MemoryPage({
    super.key,
    required this.client,
    required this.authToken,
    required this.vaultName,
    required this.isMobile,
    this.onAskVaultAI,
  });

  @override
  State<MemoryPage> createState() => _MemoryPageState();
}

class _MemoryPageState extends State<MemoryPage> {
  List<Map<String, dynamic>>? _items;
  Map<String, dynamic> _counts = const {};
  bool _loading = true;
  String? _error;
  String? _typeFilter; 
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
  void didUpdateWidget(covariant MemoryPage old) {
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
      final res = await widget.client.getMemoryTimeline(
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

  List<Map<String, dynamic>> get _filteredItems {
    final all = _items ?? const <Map<String, dynamic>>[];
    final query = _searchQuery.trim().toLowerCase();
    return all.where((m) {
      if (_typeFilter != null && m['memory_type'] != _typeFilter) {
        return false;
      }
      if (query.isEmpty) return true;
      final key = (m['memory_key'] as String? ?? '').toLowerCase();
      final val = (m['memory_value'] as String? ?? '').toLowerCase();
      final type = (m['memory_type'] as String? ?? '').toLowerCase();
      return key.contains(query) || val.contains(query) || type.contains(query);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return DashboardScaffold(
      isMobile: widget.isMobile,
      title: l.memoryTitle,
      subtitle: l.memorySubtitle,
      icon: Icons.auto_stories_outlined,
      iconColor: VaultColors.accentBright,
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
      return DashboardLoading(message: l.memoryLoading);
    }
    if (_error != null && _items == null) {
      return DashboardError(
        message: '${l.memoryErrorPrefix} $_error',
        onRetry: _load,
      );
    }
    final raw = _items ?? const <Map<String, dynamic>>[];
    if (raw.isEmpty) {
      return DashboardEmpty(
        title: l.memoryEmptyTitle,
        subtitle: l.memoryEmptySub,
        icon: Icons.auto_stories_outlined,
      );
    }

    final filtered = _filteredItems;
    final groups = _groupByYear(filtered);
    final isMobile = widget.isMobile;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _FilterControls(
          counts: _counts,
          totalCount: raw.length,
          activeType: _typeFilter,
          searchCtrl: _searchCtrl,
          onTypeChanged: (t) => setState(() => _typeFilter = t),
          onSearchChanged: (q) => setState(() => _searchQuery = q),
        ),
        if (filtered.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: VaultSpacing.lg),
            child: DashboardEmpty(
              title: l.memoryNoMatchTitle,
              subtitle: l.memoryNoMatchSub,
              icon: Icons.search_off,
            ),
          )
        else
          for (final group in groups)
            _YearGroup(
              year: group.year,
              items: group.items,
              isMobile: isMobile,
              onAskVaultAI: widget.onAskVaultAI,
            ),
      ],
    );
  }

  List<_YearBucket> _groupByYear(List<Map<String, dynamic>> items) {
    
    
    final buckets = <String, List<Map<String, dynamic>>>{};
    for (final m in items) {
      final y = _yearFor(m);
      buckets.putIfAbsent(y, () => []).add(m);
    }
    
    for (final list in buckets.values) {
      list.sort((a, b) {
        final ad = a['event_date'] as String? ?? '';
        final bd = b['event_date'] as String? ?? '';
        if (ad != bd) return bd.compareTo(ad);
        final au = a['updated_at'] as String? ?? '';
        final bu = b['updated_at'] as String? ?? '';
        return bu.compareTo(au);
      });
    }
    
    final keys = buckets.keys.toList()
      ..sort((a, b) {
        if (a == '~') return 1;
        if (b == '~') return -1;
        return b.compareTo(a);
      });
    return keys.map((k) => _YearBucket(year: k, items: buckets[k]!)).toList();
  }

  String _yearFor(Map<String, dynamic> m) {
    final ed = m['event_date'] as String?;
    if (ed != null && ed.length >= 4) {
      final y = ed.substring(0, 4);
      if (RegExp(r'^\d{4}$').hasMatch(y)) return y;
    }
    final ua = m['updated_at'] as String?;
    if (ua != null && ua.length >= 4) {
      final y = ua.substring(0, 4);
      if (RegExp(r'^\d{4}$').hasMatch(y)) return y;
    }
    return '~';
  }
}

class _YearBucket {
  final String year;
  final List<Map<String, dynamic>> items;
  _YearBucket({required this.year, required this.items});
}


class _FilterControls extends StatelessWidget {
  final Map<String, dynamic> counts;
  final int totalCount;
  final String? activeType;
  final TextEditingController searchCtrl;
  final ValueChanged<String?> onTypeChanged;
  final ValueChanged<String> onSearchChanged;

  const _FilterControls({
    required this.counts,
    required this.totalCount,
    required this.activeType,
    required this.searchCtrl,
    required this.onTypeChanged,
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
              hintText: AppLocalizations.of(context).memorySearchHint,
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
              _FilterChip(
                label: l.commonAll,
                count: totalCount,
                icon: Icons.all_inclusive,
                accent: VaultColors.textPrimary,
                selected: activeType == null,
                onTap: () => onTypeChanged(null),
              ),
              for (final type in _memoryTypeOrder)
                if ((counts[type] as int? ?? 0) > 0)
                  _FilterChip(
                    label: _memoryTypeLabel(l, type),
                    count: counts[type] as int? ?? 0,
                    icon: _memoryTypeIcons[type] ?? Icons.circle_outlined,
                    accent: _memoryTypeAccents[type] ?? VaultColors.accent,
                    selected: activeType == type,
                    onTap: () => onTypeChanged(
                      activeType == type ? null : type,
                    ),
                  ),
            ],
          ),
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final int count;
  final IconData icon;
  final Color accent;
  final bool selected;
  final VoidCallback onTap;

  const _FilterChip({
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


class _YearGroup extends StatelessWidget {
  final String year;
  final List<Map<String, dynamic>> items;
  final bool isMobile;
  final void Function(String prompt)? onAskVaultAI;

  const _YearGroup({
    required this.year,
    required this.items,
    required this.isMobile,
    this.onAskVaultAI,
  });

  @override
  Widget build(BuildContext context) {
    return DashboardSection(
      title: year == '~'
          ? AppLocalizations.of(context).memoryUndated
          : year,
      icon: Icons.history,
      trailing: MetaPill(label: '${items.length}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < items.length; i++)
            Padding(
              padding: EdgeInsets.only(
                bottom: i == items.length - 1 ? 0 : VaultSpacing.sm,
              ),
              child: FadeSlideIn(
                delay: Duration(milliseconds: 25 * i),
                child: _MemoryRowCard(
                  row: items[i],
                  onAskVaultAI: onAskVaultAI,
                ),
              ),
            ),
        ],
      ),
    );
  }
}


class _MemoryRowCard extends StatelessWidget {
  final Map<String, dynamic> row;
  final void Function(String prompt)? onAskVaultAI;

  const _MemoryRowCard({required this.row, this.onAskVaultAI});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final type = (row['memory_type'] as String?) ?? 'note';
    final key = (row['memory_key'] as String?) ?? '';
    final value = (row['memory_value'] as String?) ?? '';
    final eventDate = (row['event_date'] as String?) ?? '';
    final updatedAt = (row['updated_at'] as String?) ?? '';
    final confidence = (row['confidence'] is num)
        ? (row['confidence'] as num).toDouble()
        : 1.0;
    final accent = _memoryTypeAccents[type] ?? VaultColors.accent;
    final typeLabel = _memoryTypeLabel(l, type);
    final icon = _memoryTypeIcons[type] ?? Icons.bookmark_border;

    return VaultCard(
      color: VaultColors.surfaceElevated,
      accentSide: BorderSide(color: accent, width: 3),
      padding: const EdgeInsets.all(VaultSpacing.lg),
      onTap: (onAskVaultAI == null || key.isEmpty)
          ? null
          : () => onAskVaultAI!(l.memoryAskAbout(key)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              IconBadge(icon: icon, color: accent, size: 40),
              const SizedBox(width: VaultSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      key.isNotEmpty ? key : l.memoryUnnamed,
                      style: VaultText.subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (value.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        value,
                        style: VaultText.bodySm.copyWith(
                          color: VaultColors.textSecondary,
                        ),
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: VaultSpacing.md),
              MetaPill(label: typeLabel, icon: icon, tint: accent),
            ],
          ),
          const SizedBox(height: VaultSpacing.md),
          Wrap(
            spacing: VaultSpacing.sm,
            runSpacing: VaultSpacing.xs + 2,
            children: [
              if (eventDate.isNotEmpty)
                MetaPill(label: eventDate, icon: Icons.event_outlined),
              if (eventDate.isEmpty && updatedAt.length >= 10)
                MetaPill(
                  label: 'saved ${updatedAt.substring(0, 10)}',
                  icon: Icons.update,
                ),
              if (confidence < 0.95)
                MetaPill(
                  label: 'conf ${(confidence * 100).round()}%',
                  icon: Icons.percent,
                  dim: true,
                ),
            ],
          ),
        ],
      ),
    );
  }
}
