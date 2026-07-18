

import 'package:flutter/material.dart';
import '../../api_client.dart';
import '../../l10n/app_localizations.dart';
import '../motion.dart';
import '../primitives.dart';
import '../tokens.dart';
import 'dashboard_shell.dart';

class ExpiryPage extends StatefulWidget {
  final VaultAIClient client;
  final String authToken;
  final String vaultName;
  final bool isMobile;

  
  final void Function(String prompt)? onAskVaultAI;

  const ExpiryPage({
    super.key,
    required this.client,
    required this.authToken,
    required this.vaultName,
    required this.isMobile,
    this.onAskVaultAI,
  });

  @override
  State<ExpiryPage> createState() => _ExpiryPageState();
}

enum _Window { d7, d30, d90, all }

extension _WindowExt on _Window {
  int? get maxDays {
    switch (this) {
      case _Window.d7:  return 7;
      case _Window.d30: return 30;
      case _Window.d90: return 90;
      case _Window.all: return null;
    }
  }
}

String _windowLabel(AppLocalizations l, _Window w) {
  switch (w) {
    case _Window.d7:  return l.expiryWindow7d;
    case _Window.d30: return l.expiryWindow30d;
    case _Window.d90: return l.expiryWindow90d;
    case _Window.all: return l.expiryWindowAll;
  }
}

class _ExpiryPageState extends State<ExpiryPage> {
  List<Map<String, dynamic>>? _alerts;
  Map<String, dynamic> _counts = const {};
  bool _loading = true;
  String? _error;
  _Window _window = _Window.d90;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant ExpiryPage old) {
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
      final res = await widget.client.getActiveExpiryAlerts(
        authToken: widget.authToken,
        vaultName: widget.vaultName,
      );
      if (!mounted) return;
      final list = (res['alerts'] as List?) ?? const [];
      final counts = (res['counts'] is Map)
          ? (res['counts'] as Map).cast<String, dynamic>()
          : const <String, dynamic>{};
      setState(() {
        _alerts = list
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

  List<Map<String, dynamic>> get _filteredAlerts {
    final src = _alerts ?? const <Map<String, dynamic>>[];
    final cap = _window.maxDays;
    if (cap == null) return src;
    return src.where((a) {
      final d = a['days_until'];
      if (d is int) return d <= cap;
      return true; 
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return DashboardScaffold(
      isMobile: widget.isMobile,
      title: l.expiryTitle,
      subtitle: l.expirySubtitle,
      icon: Icons.event_busy_outlined,
      iconColor: VaultColors.severityWarn,
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
    if (_loading && _alerts == null) {
      return DashboardLoading(message: l.expiryLoading);
    }
    if (_error != null) {
      return DashboardError(
        message: '${l.expiryErrorPrefix} $_error',
        onRetry: _load,
      );
    }

    final all = _alerts ?? const <Map<String, dynamic>>[];
    if (all.isEmpty) {
      return DashboardEmpty(
        title: l.expiryEmptyTitle,
        subtitle: l.expiryEmptySub,
        icon: Icons.check_circle_outline,
      );
    }

    final filtered = _filteredAlerts;
    final byBucket = <String, List<Map<String, dynamic>>>{
      'critical': <Map<String, dynamic>>[],
      'warning':  <Map<String, dynamic>>[],
      'info':     <Map<String, dynamic>>[],
    };
    for (final a in filtered) {
      final s = (a['severity'] as String?)?.toLowerCase() ?? 'info';
      (byBucket[s] ?? byBucket['info']!).add(a);
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _WindowFilterBar(
          selected: _window,
          counts: _counts,
          onChanged: (w) => setState(() => _window = w),
        ),
        if (filtered.isEmpty) ...[
          const SizedBox(height: VaultSpacing.lg),
          DashboardEmpty(
            title: l.expiryNoneInWindow,
            subtitle: l.expiryNoneInWindowSub(
              _windowLabel(l, _window).toLowerCase(),
            ),
            icon: Icons.event_available_outlined,
          ),
        ] else ...[
          for (final entry in byBucket.entries)
            if (entry.value.isNotEmpty)
              _SeverityBucket(
                severity: entry.key,
                rows: entry.value,
                onAskVaultAI: widget.onAskVaultAI,
              ),
        ],
      ],
    );
  }
}


class _WindowFilterBar extends StatelessWidget {
  final _Window selected;
  final Map<String, dynamic> counts;
  final ValueChanged<_Window> onChanged;

  const _WindowFilterBar({
    required this.selected,
    required this.counts,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.md),
      child: Row(
        children: [
          Expanded(
            child: Wrap(
              spacing: VaultSpacing.sm,
              runSpacing: VaultSpacing.sm,
              children: _Window.values.map((w) {
                final selectedNow = w == selected;
                return InkWell(
                  onTap: () => onChanged(w),
                  borderRadius: BorderRadius.circular(VaultRadius.pill),
                  child: AnimatedContainer(
                    duration: VaultMotion.standard,
                    curve: VaultMotion.curveStandard,
                    padding: const EdgeInsets.symmetric(
                      horizontal: VaultSpacing.md + 2,
                      vertical: VaultSpacing.sm,
                    ),
                    decoration: BoxDecoration(
                      color: selectedNow
                          ? VaultColors.accentSoft
                          : VaultColors.surfaceMuted,
                      borderRadius: BorderRadius.circular(VaultRadius.pill),
                      border: Border.all(
                        color: selectedNow
                            ? VaultColors.accent.withValues(alpha: 0.4)
                            : VaultColors.borderSubtle,
                      ),
                    ),
                    child: Text(
                      _windowLabel(l, w),
                      style: VaultText.caption.copyWith(
                        color: selectedNow
                            ? VaultColors.textPrimary
                            : VaultColors.textSecondary,
                        fontWeight:
                            selectedNow ? FontWeight.w700 : FontWeight.w500,
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(width: VaultSpacing.md),
          _CountChips(counts: counts),
        ],
      ),
    );
  }
}

class _CountChips extends StatelessWidget {
  final Map<String, dynamic> counts;
  const _CountChips({required this.counts});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final c = (counts['critical'] is int) ? counts['critical'] as int : 0;
    final w = (counts['warning'] is int)  ? counts['warning']  as int : 0;
    return Wrap(
      spacing: VaultSpacing.sm,
      children: [
        if (c > 0) SeverityChip(level: 'critical', label: l.expiryCountCritical(c)),
        if (w > 0) SeverityChip(level: 'warning',  label: l.expiryCountWarning(w)),
      ],
    );
  }
}


class _SeverityBucket extends StatelessWidget {
  final String severity;
  final List<Map<String, dynamic>> rows;
  final void Function(String prompt)? onAskVaultAI;

  const _SeverityBucket({
    required this.severity,
    required this.rows,
    this.onAskVaultAI,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return DashboardSection(
      title: _humanSeverity(l, severity),
      icon: _iconForSeverity(severity),
      trailing: SeverityChip(level: severity, label: '${rows.length}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < rows.length; i++)
            Padding(
              padding: EdgeInsets.only(
                bottom: i == rows.length - 1 ? 0 : VaultSpacing.sm,
              ),
              child: FadeSlideIn(
                delay: Duration(milliseconds: 30 * i),
                child: _ExpiryRowCard(
                  row: rows[i],
                  onAskVaultAI: onAskVaultAI,
                ),
              ),
            ),
        ],
      ),
    );
  }

  String _humanSeverity(AppLocalizations l, String s) {
    switch (s) {
      case 'critical': return l.expiryBucketCritical;
      case 'warning':  return l.expiryBucketWarning;
      case 'info':     return l.expiryBucketInfo;
      default:         return s;
    }
  }

  IconData _iconForSeverity(String s) {
    switch (s) {
      case 'critical': return Icons.error_outline;
      case 'warning':  return Icons.warning_amber_outlined;
      case 'info':     return Icons.info_outline;
      default:         return Icons.circle_outlined;
    }
  }
}


class _ExpiryRowCard extends StatelessWidget {
  final Map<String, dynamic> row;
  final void Function(String prompt)? onAskVaultAI;

  const _ExpiryRowCard({required this.row, this.onAskVaultAI});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final severity = ((row['severity'] as String?) ?? 'info').toLowerCase();
    final accent = VaultColors.forSeverity(severity);
    final label = (row['doc_label'] as String?) ?? 'Document';
    final type = (row['expiry_type'] as String?) ?? '';
    final typeLabel = (row['expiry_type_label'] as String?) ?? type;
    final date = (row['expiry_date'] as String?) ?? '';
    final days = row['days_until'] is int ? row['days_until'] as int : null;

    return VaultCard(
      color: VaultColors.surfaceElevated,
      accentSide: BorderSide(color: accent, width: 3),
      padding: const EdgeInsets.all(VaultSpacing.lg),
      onTap: onAskVaultAI == null
          ? null
          : () => onAskVaultAI!(l.chatAskAbout(typeLabel)),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          IconBadge(
            icon: _iconForType(type),
            color: accent,
            size: 44,
            radius: VaultRadius.md,
          ),
          const SizedBox(width: VaultSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  label,
                  style: VaultText.subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: VaultSpacing.xs),
                Row(
                  children: [
                    if (typeLabel.isNotEmpty) ...[
                      MetaPill(
                        label: typeLabel,
                        icon: Icons.label_outline,
                      ),
                      const SizedBox(width: VaultSpacing.sm),
                    ],
                    if (date.isNotEmpty)
                      MetaPill(
                        label: date,
                        icon: Icons.event_outlined,
                      ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: VaultSpacing.md),
          _DaysBadge(days: days, severity: severity),
        ],
      ),
    );
  }

  IconData _iconForType(String t) {
    switch (t) {
      case 'passport':       return Icons.book_outlined;
      case 'visa':           return Icons.flight_takeoff;
      case 'id_card':        return Icons.badge_outlined;
      case 'driver_license': return Icons.directions_car_outlined;
      case 'insurance':      return Icons.shield_outlined;
      case 'tax':            return Icons.account_balance_outlined;
      case 'contract':       return Icons.handshake_outlined;
      case 'subscription':   return Icons.autorenew;
      case 'custom':         return Icons.bookmark_border;
      default:               return Icons.event_outlined;
    }
  }
}

class _DaysBadge extends StatelessWidget {
  final int? days;
  final String severity;

  const _DaysBadge({required this.days, required this.severity});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final accent = VaultColors.forSeverity(severity);
    String big;
    String small;
    if (days == null) {
      big = '–';
      small = l.expiryNoDate;
    } else if (days! < 0) {
      big = l.expiryDaysLeft(-days!);
      small = l.conciergeExpired;
    } else if (days == 0) {
      big = l.expiryToday;
      small = l.expiryDaysExpires;
    } else {
      big = l.expiryDaysLeft(days!);
      small = l.expiryDays;
    }
    return Container(
      width: 72,
      padding: const EdgeInsets.symmetric(
        vertical: VaultSpacing.sm,
        horizontal: VaultSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: VaultColors.forSeveritySoft(severity),
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: accent.withValues(alpha: 0.3)),
      ),
      child: Column(
        children: [
          Text(
            big,
            textAlign: TextAlign.center,
            style: VaultText.title.copyWith(color: accent, fontSize: 18),
          ),
          const SizedBox(height: 2),
          Text(
            small,
            textAlign: TextAlign.center,
            style: VaultText.caption.copyWith(
              color: accent,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.4,
            ),
          ),
        ],
      ),
    );
  }
}
