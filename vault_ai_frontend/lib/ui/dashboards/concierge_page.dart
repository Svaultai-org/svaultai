

import 'package:flutter/material.dart';
import '../../api_client.dart';
import '../../l10n/app_localizations.dart';
import '../motion.dart';
import '../primitives.dart';
import '../tokens.dart';
import 'dashboard_shell.dart';

class ConciergePage extends StatefulWidget {
  final VaultAIClient client;
  final String authToken;
  final String vaultName;
  final bool isMobile;
  final void Function(String prompt)? onAskVaultAI;
  final VoidCallback? onOpenSecurityCenter;
  final VoidCallback? onOpenExpiry;
  final VoidCallback? onOpenInheritance;

  const ConciergePage({
    super.key,
    required this.client,
    required this.authToken,
    required this.vaultName,
    required this.isMobile,
    this.onAskVaultAI,
    this.onOpenSecurityCenter,
    this.onOpenExpiry,
    this.onOpenInheritance,
  });

  @override
  State<ConciergePage> createState() => _ConciergePageState();
}

class _ConciergePageState extends State<ConciergePage> {
  Map<String, dynamic>? _security;
  Map<String, dynamic>? _expiry;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant ConciergePage old) {
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
      
      final futures = await Future.wait([
        _safeLoadSecurity(),
        _safeLoadExpiry(),
      ]);
      if (!mounted) return;
      setState(() {
        _security = futures[0];
        _expiry = futures[1];
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

  Future<Map<String, dynamic>?> _safeLoadSecurity() async {
    try {
      return await widget.client.getSecurityCenterSummary(
        authToken: widget.authToken,
      );
    } catch (_) {
      return null;
    }
  }

  Future<Map<String, dynamic>?> _safeLoadExpiry() async {
    try {
      return await widget.client.getActiveExpiryAlerts(
        authToken: widget.authToken,
        vaultName: widget.vaultName,
      );
    } catch (_) {
      return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return DashboardScaffold(
      isMobile: widget.isMobile,
      title: l.conciergeTitle,
      subtitle: l.conciergeSubtitle,
      icon: Icons.auto_awesome_outlined,
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
    if (_loading && _security == null && _expiry == null) {
      return DashboardLoading(message: l.conciergeLoading);
    }
    if (_error != null && _security == null && _expiry == null) {
      return DashboardError(
        message: '${l.conciergeErrorPrefix} $_error',
        onRetry: _load,
      );
    }

    final allAlerts = _allExpiryAlerts;
    final recs = _recommendations;
    final critical = allAlerts
        .where((a) => (a['severity'] as String?) == 'critical')
        .toList();
    final warning = allAlerts
        .where((a) => (a['severity'] as String?) == 'warning')
        .toList();
    final timeline = allAlerts
        .where((a) {
          final d = a['days_until'];
          return d is int && d >= 0 && d <= 90;
        })
        .toList()
      ..sort(
          (a, b) => (a['days_until'] as int).compareTo(b['days_until'] as int));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _PostureRow(
          security: _security,
          expiry: _expiry,
          isMobile: widget.isMobile,
          onOpenSecurityCenter: widget.onOpenSecurityCenter,
          onOpenExpiry: widget.onOpenExpiry,
        ),
        if (critical.isNotEmpty)
          DashboardSection(
            title: l.conciergeCriticalNow,
            icon: Icons.error_outline,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (var i = 0; i < critical.length; i++)
                  Padding(
                    padding: EdgeInsets.only(
                      bottom: i == critical.length - 1 ? 0 : VaultSpacing.sm,
                    ),
                    child: FadeSlideIn(
                      delay: Duration(milliseconds: 30 * i),
                      child: _AlertActionRow(
                        row: critical[i],
                        onAskVaultAI: widget.onAskVaultAI,
                      ),
                    ),
                  ),
              ],
            ),
          ),

        if (warning.isNotEmpty)
          DashboardSection(
            title: l.conciergeComingUp,
            icon: Icons.schedule_outlined,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (var i = 0; i < warning.length; i++)
                  Padding(
                    padding: EdgeInsets.only(
                      bottom: i == warning.length - 1 ? 0 : VaultSpacing.sm,
                    ),
                    child: FadeSlideIn(
                      delay: Duration(milliseconds: 30 * i),
                      child: _AlertActionRow(
                        row: warning[i],
                        onAskVaultAI: widget.onAskVaultAI,
                      ),
                    ),
                  ),
              ],
            ),
          ),

        if (recs.isNotEmpty)
          DashboardSection(
            title: l.conciergeRecommendations,
            icon: Icons.lightbulb_outline,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (var i = 0; i < recs.length; i++)
                  Padding(
                    padding: EdgeInsets.only(
                      bottom: i == recs.length - 1 ? 0 : VaultSpacing.sm,
                    ),
                    child: FadeSlideIn(
                      delay: Duration(milliseconds: 30 * i),
                      child: _RecommendationRow(
                        rec: recs[i],
                        onAction: _routeRecommendation,
                      ),
                    ),
                  ),
              ],
            ),
          ),

        DashboardSection(
          title: l.conciergeTravelReadiness,
          icon: Icons.flight_takeoff,
          child: _TravelReadiness(
            alerts: allAlerts,
            onAskVaultAI: widget.onAskVaultAI,
          ),
        ),

        if (timeline.isNotEmpty)
          DashboardSection(
            title: l.conciergeRenewalTimeline,
            icon: Icons.timeline,
            child: _RenewalTimeline(items: timeline),
          ),

        if (critical.isEmpty && warning.isEmpty && recs.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: VaultSpacing.lg),
            child: DashboardEmpty(
              title: l.conciergeAllClear,
              subtitle: l.conciergeAllClearSub,
              icon: Icons.verified_outlined,
            ),
          ),
      ],
    );
  }

  
  List<Map<String, dynamic>> get _allExpiryAlerts {
    if (_expiry == null) return const [];
    final raw = (_expiry!['alerts'] as List?) ?? const [];
    return raw
        .whereType<Map>()
        .map((m) => m.cast<String, dynamic>())
        .toList();
  }

  List<Map<String, dynamic>> get _recommendations {
    if (_security == null) return const [];
    final raw = (_security!['recommendations'] as List?) ?? const [];
    return raw
        .whereType<Map>()
        .map((m) => m.cast<String, dynamic>())
        .toList();
  }

  void _routeRecommendation(Map<String, dynamic> rec) {
    final route = (rec['route'] as String?) ?? '';
    if (route == '/devices') {
      Navigator.pushNamed(context, '/devices');
      return;
    }
    if (route.isNotEmpty) {
      Navigator.pushNamed(context, route);
      return;
    }
    
    widget.onOpenSecurityCenter?.call();
  }
}


class _PostureRow extends StatelessWidget {
  final Map<String, dynamic>? security;
  final Map<String, dynamic>? expiry;
  final bool isMobile;
  final VoidCallback? onOpenSecurityCenter;
  final VoidCallback? onOpenExpiry;

  const _PostureRow({
    required this.security,
    required this.expiry,
    required this.isMobile,
    this.onOpenSecurityCenter,
    this.onOpenExpiry,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final score = (security?['score'] as num?)?.toInt();
    final scoreBand = (security?['score_band'] as String?) ?? '';
    final counts = (expiry?['counts'] is Map)
        ? (expiry!['counts'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final crit = (counts['critical'] is int) ? counts['critical'] as int : 0;
    final warn = (counts['warning'] is int) ? counts['warning'] as int : 0;
    final total = (counts['total'] is int) ? counts['total'] as int : 0;
    final inheritance = (security?['inheritance'] is Map)
        ? (security!['inheritance'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final inhConfigured = inheritance['configured'] == true;
    final inhFrozen = inheritance['frozen'] == true;

    final cards = <Widget>[
      _PostureCard(
        title: l.conciergePostureSecurity,
        value: score == null ? '–' : '$score',
        unit: score == null ? l.conciergePostureNoData : '/ 100',
        accent: _accentForBand(scoreBand),
        icon: Icons.shield_outlined,
        footer: scoreBand.isEmpty
            ? l.conciergePostureScoreHint
            : scoreBand.toUpperCase(),
        onTap: onOpenSecurityCenter,
      ),
      _PostureCard(
        title: l.conciergePostureExpiring,
        value: '$total',
        unit: total == 1 ? l.conciergeItem : l.conciergeItems,
        accent: _accentForExpiry(crit, warn),
        icon: Icons.event_busy_outlined,
        footer: _expiryFooter(l, crit, warn, total),
        onTap: onOpenExpiry,
      ),
      _PostureCard(
        title: l.conciergePostureInheritance,
        value: inhConfigured ? 'On' : 'Off',
        unit: inhFrozen
            ? l.conciergeInheritanceFrozen
            : (inhConfigured
                ? l.conciergeInheritanceConfigured
                : l.conciergeInheritanceUnset),
        accent: inhFrozen
            ? VaultColors.severityWarn
            : (inhConfigured ? VaultColors.accentBright : VaultColors.textTertiary),
        icon: Icons.family_restroom_outlined,
        footer: inhFrozen
            ? l.conciergePostureFrozen
            : (inhConfigured
                ? l.conciergePostureConfigured
                : l.conciergePostureUnset),
        onTap: null,
      ),
    ];

    if (isMobile) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < cards.length; i++)
            Padding(
              padding: EdgeInsets.only(
                bottom: i == cards.length - 1 ? 0 : VaultSpacing.md,
              ),
              child: cards[i],
            ),
        ],
      );
    }
    
    
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < cards.length; i++) ...[
            Expanded(child: cards[i]),
            if (i != cards.length - 1) const SizedBox(width: VaultSpacing.md),
          ],
        ],
      ),
    );
  }

  Color _accentForBand(String band) {
    switch (band.toLowerCase()) {
      case 'strong':   return VaultColors.severityOk;
      case 'moderate': return VaultColors.severityWarn;
      case 'weak':     return VaultColors.severityCrit;
      default:         return VaultColors.textSecondary;
    }
  }

  Color _accentForExpiry(int crit, int warn) {
    if (crit > 0) return VaultColors.severityCrit;
    if (warn > 0) return VaultColors.severityWarn;
    return VaultColors.severityOk;
  }

  String _expiryFooter(AppLocalizations l, int crit, int warn, int total) {
    if (total == 0) return l.conciergePostureNothingTracked;
    final parts = <String>[];
    if (crit > 0) parts.add(l.expiryCountCritical(crit));
    if (warn > 0) parts.add(l.expiryCountWarning(warn));
    if (parts.isEmpty) return l.conciergePostureAllFuture;
    return parts.join(' / ');
  }
}

class _PostureCard extends StatelessWidget {
  final String title;
  final String value;
  final String unit;
  final Color accent;
  final IconData icon;
  final String footer;
  final VoidCallback? onTap;

  const _PostureCard({
    required this.title,
    required this.value,
    required this.unit,
    required this.accent,
    required this.icon,
    required this.footer,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return VaultCard(
      onTap: onTap,
      padding: const EdgeInsets.all(VaultSpacing.lg),
      accentSide: BorderSide(color: accent, width: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              IconBadge(icon: icon, color: accent, size: 40),
              const Spacer(),
              if (onTap != null)
                const Icon(
                  Icons.chevron_right,
                  color: VaultColors.textTertiary,
                  size: 22,
                ),
            ],
          ),
          const SizedBox(height: VaultSpacing.md),
          Text(title, style: VaultText.caption),
          const SizedBox(height: 2),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                value,
                style: VaultText.display.copyWith(
                  color: accent,
                  fontSize: 32,
                  height: 1.0,
                ),
              ),
              const SizedBox(width: VaultSpacing.xs + 2),
              Padding(
                padding: const EdgeInsets.only(bottom: VaultSpacing.xs + 2),
                child: Text(unit, style: VaultText.caption),
              ),
            ],
          ),
          const SizedBox(height: VaultSpacing.sm),
          Text(footer, style: VaultText.caption),
        ],
      ),
    );
  }
}


class _AlertActionRow extends StatelessWidget {
  final Map<String, dynamic> row;
  final void Function(String prompt)? onAskVaultAI;

  const _AlertActionRow({required this.row, this.onAskVaultAI});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final severity = ((row['severity'] as String?) ?? 'info').toLowerCase();
    final accent = VaultColors.forSeverity(severity);
    final label = (row['doc_label'] as String?) ?? 'Document';
    final type = (row['expiry_type'] as String?) ?? '';
    final typeLabel = (row['expiry_type_label'] as String?) ?? type;
    final days = row['days_until'] is int ? row['days_until'] as int : null;
    final phrase = _phraseForDays(l, days);

    return VaultCard(
      color: VaultColors.surfaceElevated,
      accentSide: BorderSide(color: accent, width: 3),
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          IconBadge(icon: _iconForType(type), color: accent, size: 40),
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
                const SizedBox(height: 2),
                Text(phrase, style: VaultText.caption),
              ],
            ),
          ),
          const SizedBox(width: VaultSpacing.md),
          if (onAskVaultAI != null)
            FilledButton.tonal(
              onPressed: () => onAskVaultAI!(l.chatAskAbout(typeLabel)),
              style: FilledButton.styleFrom(
                backgroundColor: accent.withValues(alpha: 0.18),
                foregroundColor: accent,
                padding: const EdgeInsets.symmetric(
                  horizontal: VaultSpacing.md,
                  vertical: VaultSpacing.sm + 2,
                ),
              ),
              child: Text(l.commonAskVaultAI),
            ),
        ],
      ),
    );
  }

  String _phraseForDays(AppLocalizations l, int? d) {
    if (d == null) return l.conciergeNoExpiryDate;
    if (d < 0) return l.expiredAgo(-d);
    if (d == 0) return l.expiryToday;
    return l.expiryDaysLeft(d);
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
      case 'inheritance':    return Icons.family_restroom_outlined;
      default:               return Icons.event_outlined;
    }
  }
}


class _RecommendationRow extends StatelessWidget {
  final Map<String, dynamic> rec;
  final void Function(Map<String, dynamic> rec) onAction;

  const _RecommendationRow({required this.rec, required this.onAction});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final priority = ((rec['priority'] as String?) ?? 'moderate').toLowerCase();
    final severity = _severityFromPriority(priority);
    final accent = VaultColors.forSeverity(severity);
    final message = (rec['message'] as String?) ?? '';
    final id = (rec['id'] as String?) ?? '';

    return VaultCard(
      color: VaultColors.surfaceElevated,
      accentSide: BorderSide(color: accent, width: 3),
      padding: const EdgeInsets.all(VaultSpacing.lg),
      onTap: () => onAction(rec),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          IconBadge(icon: _iconForId(id), color: accent, size: 40),
          const SizedBox(width: VaultSpacing.md),
          Expanded(
            child: Text(message, style: VaultText.body),
          ),
          const SizedBox(width: VaultSpacing.md),
          SeverityChip(level: severity, label: _priorityLabel(l, priority)),
          const SizedBox(width: VaultSpacing.sm),
          const Icon(
            Icons.chevron_right,
            color: VaultColors.textTertiary,
            size: 22,
          ),
        ],
      ),
    );
  }

  String _severityFromPriority(String p) {
    switch (p) {
      case 'high':     return 'critical';
      case 'moderate': return 'warning';
      case 'low':      return 'info';
      default:         return 'info';
    }
  }

  String _priorityLabel(AppLocalizations l, String p) {
    switch (p) {
      case 'high':     return l.priorityHigh;
      case 'moderate': return l.priorityMedium;
      case 'low':      return l.priorityLow;
      default:         return p.toUpperCase();
    }
  }

  IconData _iconForId(String id) {
    switch (id) {
      case 'weak_passwords':       return Icons.password_outlined;
      case 'pending_device':       return Icons.devices_other;
      case 'pending_self_approval': return Icons.hourglass_top;
      case 'inactive_devices':     return Icons.device_unknown_outlined;
      case 'enable_inheritance':   return Icons.family_restroom_outlined;
      case 'unanalyzed_passwords': return Icons.analytics_outlined;
      default:                     return Icons.lightbulb_outline;
    }
  }
}


class _TravelReadiness extends StatelessWidget {
  final List<Map<String, dynamic>> alerts;
  final void Function(String prompt)? onAskVaultAI;

  const _TravelReadiness({required this.alerts, this.onAskVaultAI});

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final passport = alerts.firstWhere(
      (a) => a['expiry_type'] == 'passport',
      orElse: () => const <String, dynamic>{},
    );
    final visa = alerts.firstWhere(
      (a) => a['expiry_type'] == 'visa',
      orElse: () => const <String, dynamic>{},
    );

    final passportDays = passport['days_until'] is int
        ? passport['days_until'] as int
        : null;
    final visaDays =
        visa['days_until'] is int ? visa['days_until'] as int : null;

    final passportOk = passportDays != null && passportDays >= 180;
    final visaOk = visaDays != null && visaDays >= 30;
    final overall = passportOk && visaOk;
    final partial =
        (passportOk && visa.isEmpty) || (passport.isEmpty && visaOk);

    final accent = overall
        ? VaultColors.severityOk
        : (partial ? VaultColors.severityWarn : VaultColors.severityCrit);
    final headline = overall
        ? l.conciergeTravelReady
        : (partial ? l.conciergeTravelMostly : l.conciergeTravelAttention);
    final subline = overall
        ? l.conciergeTravelReadyDetail
        : (partial
            ? l.conciergeTravelMostlyDetail
            : l.conciergeTravelAttentionDetail);

    return VaultCard(
      accentSide: BorderSide(color: accent, width: 3),
      padding: const EdgeInsets.all(VaultSpacing.lg),
      onTap: onAskVaultAI == null
          ? null
          : () => onAskVaultAI!(l.conciergeAskTravel),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              IconBadge(
                icon: Icons.flight_takeoff,
                color: accent,
                size: 40,
              ),
              const SizedBox(width: VaultSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(headline, style: VaultText.subtitle),
                    const SizedBox(height: 2),
                    Text(subline, style: VaultText.caption),
                  ],
                ),
              ),
              SeverityChip(
                level: overall
                    ? 'ok'
                    : (partial ? 'warning' : 'critical'),
                label: overall ? 'OK' : (partial ? 'PARTIAL' : 'CHECK'),
              ),
            ],
          ),
          const SizedBox(height: VaultSpacing.md),
          Row(
            children: [
              Expanded(
                child: _TravelTile(
                  label: l.conciergePassport,
                  icon: Icons.book_outlined,
                  days: passportDays,
                  missing: passport.isEmpty,
                  okThreshold: 180,
                ),
              ),
              const SizedBox(width: VaultSpacing.md),
              Expanded(
                child: _TravelTile(
                  label: l.conciergeVisa,
                  icon: Icons.flight,
                  days: visaDays,
                  missing: visa.isEmpty,
                  okThreshold: 30,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TravelTile extends StatelessWidget {
  final String label;
  final IconData icon;
  final int? days;
  final bool missing;
  final int okThreshold;

  const _TravelTile({
    required this.label,
    required this.icon,
    required this.days,
    required this.missing,
    required this.okThreshold,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    Color tint;
    String value;
    String hint;
    if (missing) {
      tint = VaultColors.textTertiary;
      value = '–';
      hint = l.conciergePassportNotOnFile;
    } else if (days == null) {
      tint = VaultColors.textTertiary;
      value = '?';
      hint = l.conciergeNoExpiryDate;
    } else if (days! < 0) {
      tint = VaultColors.severityCrit;
      value = l.expiryDaysLeft(-days!);
      hint = l.conciergeExpired;
    } else if (days! < okThreshold) {
      tint = VaultColors.severityWarn;
      value = l.expiryDaysLeft(days!);
      hint = l.conciergeRenewSoon;
    } else {
      tint = VaultColors.severityOk;
      value = l.expiryDaysLeft(days!);
      hint = l.conciergeComfortable;
    }
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Row(
        children: [
          Icon(icon, color: tint, size: 18),
          const SizedBox(width: VaultSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(label, style: VaultText.caption),
                const SizedBox(height: 2),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      value,
                      style: VaultText.subtitle.copyWith(color: tint),
                    ),
                    const SizedBox(width: VaultSpacing.xs + 2),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 1),
                      child: Text(hint, style: VaultText.caption),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


class _RenewalTimeline extends StatelessWidget {
  final List<Map<String, dynamic>> items;
  const _RenewalTimeline({required this.items});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: items.map((item) {
          final severity = ((item['severity'] as String?) ?? 'info').toLowerCase();
          final accent = VaultColors.forSeverity(severity);
          final days = item['days_until'] as int;
          final label = (item['doc_label'] as String?) ?? '';
          final type = (item['expiry_type'] as String?) ?? '';
          return Padding(
            padding: const EdgeInsets.only(right: VaultSpacing.sm),
            child: Container(
              width: 140,
              padding: const EdgeInsets.all(VaultSpacing.md),
              decoration: BoxDecoration(
                color: VaultColors.surfaceElevated,
                borderRadius: BorderRadius.circular(VaultRadius.md),
                border: Border.all(color: VaultColors.borderSubtle),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(_iconForType(type), color: accent, size: 16),
                      const SizedBox(width: VaultSpacing.xs + 2),
                      Expanded(
                        child: Text(
                          (item['expiry_type_label'] as String?) ?? type,
                          style: VaultText.caption,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: VaultSpacing.sm),
                  Text(
                    label,
                    style: VaultText.bodySm,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const Spacer(),
                  Text(
                    days == 0
                        ? AppLocalizations.of(context).expiryToday
                        : AppLocalizations.of(context).expiryDaysLeft(days),
                    style: VaultText.subtitle.copyWith(
                      color: accent,
                      fontSize: 15,
                    ),
                  ),
                ],
              ),
            ),
          );
        }).toList(),
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
      case 'inheritance':    return Icons.family_restroom_outlined;
      default:               return Icons.event_outlined;
    }
  }
}
