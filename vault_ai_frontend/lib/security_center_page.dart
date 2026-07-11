import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api_client.dart';
import 'l10n/app_localizations.dart';
import 'ui/responsive.dart';
import 'main.dart' show AppState, backendBaseUrl;


class SecurityCenterPage extends StatefulWidget {
  const SecurityCenterPage({super.key});

  @override
  State<SecurityCenterPage> createState() => _SecurityCenterPageState();
}

class _SecurityCenterPageState extends State<SecurityCenterPage> {
  late final VaultAIClient _client;
  Timer? _refreshTimer;
  bool _loading = true;
  String? _error;
  Map<String, dynamic>? _summary;

  
  bool _analyzing = false;

  @override
  void initState() {
    super.initState();
    _client = const VaultAIClient(baseUrl: backendBaseUrl);
    _refresh();
    _refreshTimer = Timer.periodic(const Duration(seconds: 30), (_) => _refresh());
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    try {
      final data = await _client.getSecurityCenterSummary(
        authToken: token,
      );
      if (!mounted) return;
      setState(() {
        _summary = data;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load Security Center: $e';
      });
    }
  }

  
  Color _scoreColor(String band) {
    switch (band) {
      case 'strong':
        return const Color(0xFF66BB6A);
      case 'moderate':
        return const Color(0xFFFFA726);
      default:
        return const Color(0xFFE57373);
    }
  }

  Color _priorityColor(String priority) {
    switch (priority) {
      case 'high':
        return const Color(0xFFE57373);
      case 'moderate':
        return const Color(0xFFFFA726);
      default:
        return const Color(0xFF66BB6A);
    }
  }

  String _formatBytes(int bytes) {
    if (bytes >= 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
    }
    if (bytes >= 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(0)} MB';
    }
    if (bytes >= 1024) {
      return '${(bytes / 1024).toStringAsFixed(0)} KB';
    }
    return '$bytes B';
  }

  Widget _card(String title, Widget body, {Widget? trailing}) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.2,
                    color: Color(0xFFB4B4B4),
                  ),
                ),
              ),
              if (trailing != null) trailing,
            ],
          ),
          const SizedBox(height: 10),
          body,
        ],
      ),
    );
  }

  
  Widget _scoreHeader(Map<String, dynamic> s) {
    final score = (s['score'] ?? 0) as int;
    final band = (s['score_band'] ?? 'weak') as String;
    final c = _scoreColor(band);
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        children: [
          Container(
            width: 96,
            height: 96,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: c, width: 4),
            ),
            child: Text(
              '$score',
              style: TextStyle(
                fontSize: vrMetric(context),
                fontWeight: FontWeight.w800,
                color: c,
              ),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'SECURITY SCORE',
                  style: TextStyle(
                    fontSize: 12,
                    letterSpacing: 1.4,
                    color: Color(0xFFB4B4B4),
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  band.toUpperCase(),
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w800,
                    color: c,
                  ),
                ),
                const SizedBox(height: 4),
                const Text(
                  'Read-only overview of your vault health.',
                  style: TextStyle(fontSize: 12, color: Color(0xFF8C8C8C)),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _devicesSection(Map<String, dynamic> s) {
    final d = (s['devices'] ?? const {}) as Map;
    final trusted = (d['trusted'] ?? 0) as int;
    final pending = (d['pending'] ?? 0) as int;
    final revoked = (d['revoked'] ?? 0) as int;
    final inactive = (d['inactive_trusted'] ?? 0) as int;
    final pendingSelf = (d['pending_self_approval'] ?? 0) as int;
    return _card(
      'DEVICES',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 12,
            runSpacing: 6,
            children: [
              _dot('$trusted trusted', const Color(0xFF66BB6A)),
              _dot('$pending pending', const Color(0xFFFFA726)),
              _dot('$revoked revoked', const Color(0xFFE57373)),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            inactive == 0
                ? 'No inactive trusted devices.'
                : '$inactive inactive trusted device${inactive == 1 ? '' : 's'} (>90 days).',
            style: const TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
          ),
          if (pendingSelf > 0) ...[
            const SizedBox(height: 4),
            Text(
              'Pending self-approval cooldown in progress.',
              style: TextStyle(color: _priorityColor('high'), fontSize: 13),
            ),
          ],
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerRight,
            child: OutlinedButton(
              onPressed: () => Navigator.pushNamed(context, '/devices'),
              child: Text(
                AppLocalizations.of(context).securityManageDevices,
              ),
            ),
          ),
        ],
      ),
    );
  }

  
  Future<bool> _confirmAnalyzeWarning() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF262626),
        title: Text(
          AppLocalizations.of(context).securityAnalyzePasswordsTitle,
        ),
        content: const Text(
          'VaultAI will temporarily decrypt your saved logins on this '
          'device to compute password health. Passwords are never shown '
          'or stored on the server. Hashes are user-salted and used '
          'only to detect reused passwords inside your own vault.',
          style: TextStyle(height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(AppLocalizations.of(context).commonCancel),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(AppLocalizations.of(context).commonContinue),
          ),
        ],
      ),
    );
    return ok == true;
  }

  
  Future<({String vaultName, String pin})?> _promptVaultAndPin() async {
    final vaultCtl = TextEditingController();
    final pinCtl = TextEditingController();
    final result = await showDialog<({String vaultName, String pin})>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF262626),
        title: Text(AppLocalizations.of(context).securityEnterVaultPin),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: vaultCtl,
              decoration: const InputDecoration(labelText: 'Vault name'),
              autofocus: true,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: pinCtl,
              decoration: const InputDecoration(labelText: 'PIN'),
              obscureText: true,
              keyboardType: TextInputType.number,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, null),
            child: Text(AppLocalizations.of(context).commonCancel),
          ),
          FilledButton(
            onPressed: () {
              final v = vaultCtl.text.trim();
              final p = pinCtl.text.trim();
              if (v.isEmpty || p.isEmpty) return;
              Navigator.pop(ctx, (vaultName: v, pin: p));
            },
            child: Text(AppLocalizations.of(context).securityAnalyzeButton),
          ),
        ],
      ),
    );
    return result;
  }

  
  Future<bool> _showAnalyzeResult(Map<String, dynamic> r) async {
    final analyzed = (r['analyzed_count'] ?? 0) as int;
    final weak = (r['weak'] ?? 0) as int;
    final reused = (r['reused'] ?? 0) as int;
    final failed = (r['failed_count'] ?? 0) as int;
    final hasMore = (r['has_more'] ?? false) as bool;

    final lines = <String>[
      'Analyzed $analyzed password${analyzed == 1 ? '' : 's'}.',
      'Found $weak weak and $reused reused.',
    ];
    if (failed > 0) {
      lines.add('$failed item${failed == 1 ? '' : 's'} could not be read.');
    }

    final cont = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF262626),
        title: const Text('Done'),
        content: Text(lines.join('\n'), style: const TextStyle(height: 1.4)),
        actions: [
          if (hasMore)
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(AppLocalizations.of(context).securityAnalyzeMore),
            ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('OK'),
          ),
        ],
      ),
    );
    return cont == true;
  }

  Future<void> _runAnalyzePasswords() async {
    if (_analyzing) return;
    final messenger = ScaffoldMessenger.of(context);

    
    if (!await _confirmAnalyzeWarning()) return;

    
    int? cursor;
    setState(() => _analyzing = true);
    try {
      while (true) {
        final creds = await _promptVaultAndPin();
        if (creds == null) break;
        if (!mounted) return;
        final token = context.read<AppState>().sessionToken;
        if (token == null) {
          messenger.showSnackBar(
            SnackBar(
              content: Text(
                AppLocalizations.of(context).errorSessionExpired,
              ),
            ),
          );
          return;
        }
        Map<String, dynamic> result;
        try {
          result = await _client.analyzePasswords(
            authToken: token,
            vaultName: creds.vaultName,
            pin: creds.pin,
            cursor: cursor,
          );
        } catch (e) {
          if (!mounted) return;
          messenger.showSnackBar(
            SnackBar(content: Text('Analyze failed: $e')),
          );
          return;
        }
        if (!mounted) return;
        final wantsMore = await _showAnalyzeResult(result);
        if (!wantsMore) break;
        cursor = result['next_cursor'] as int?;
        if (cursor == null) break;
      }
    } finally {
      if (mounted) setState(() => _analyzing = false);
      
      await _refresh();
    }
  }

  Widget _passwordSection(Map<String, dynamic> s) {
    final p = (s['passwords'] ?? const {}) as Map;
    final weak = (p['weak'] ?? 0) as int;
    final moderate = (p['moderate'] ?? 0) as int;
    final strong = (p['strong'] ?? 0) as int;
    final reused = (p['reused'] ?? 0) as int;
    final generated = (p['generated_by_vaultai'] ?? 0) as int;
    final unanalyzed = (p['unanalyzed_count'] ?? 0) as int;
    final total = strong + moderate + weak;
    Widget bar() {
      if (total == 0) {
        return const Text(
          'No passwords analyzed yet.',
          style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
        );
      }
      return ClipRRect(
        borderRadius: BorderRadius.circular(999),
        child: SizedBox(
          height: 10,
          child: Row(
            children: [
              Expanded(
                flex: strong,
                child: Container(color: const Color(0xFF66BB6A)),
              ),
              Expanded(
                flex: moderate,
                child: Container(color: const Color(0xFFFFA726)),
              ),
              Expanded(
                flex: weak,
                child: Container(color: const Color(0xFFE57373)),
              ),
            ],
          ),
        ),
      );
    }

    return _card(
      'PASSWORD HEALTH',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          bar(),
          const SizedBox(height: 10),
          Text(
            '$strong strong   ·   $moderate moderate   ·   $weak weak',
            style: const TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
          ),
          const SizedBox(height: 6),
          Text(
            '$generated generated by VaultAI   ·   $reused reused group${reused == 1 ? '' : 's'}',
            style: const TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
          ),
          if (unanalyzed > 0) ...[
            const SizedBox(height: 6),
            Text(
              '$unanalyzed not yet analyzed (will score on save/view)',
              style: const TextStyle(color: Color(0xFF8C8C8C), fontSize: 12),
            ),
          ],
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerRight,
            child: OutlinedButton.icon(
              onPressed: _analyzing ? null : _runAnalyzePasswords,
              icon: _analyzing
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.fact_check_outlined, size: 18),
              label: Text(_analyzing
                  ? 'Analyzing...'
                  : 'Analyze all passwords'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _vaultSection(Map<String, dynamic> s) {
    final v = (s['vault'] ?? const {}) as Map;
    final items = (v['total_items'] ?? 0) as int;
    final files = (v['total_files'] ?? 0) as int;
    final raw = (v['tag_counts'] ?? const {}) as Map;
    final counts = raw.map<String, int>(
      (k, val) => MapEntry(k.toString(), (val ?? 0) as int),
    );
    final top = counts.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final shown = top.take(5).toList();
    final maxCount = shown.isEmpty
        ? 1
        : shown.map((e) => e.value).reduce((a, b) => a > b ? a : b);
    return _card(
      'VAULT INTELLIGENCE',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '$items items   ·   $files files',
            style: const TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
          ),
          const SizedBox(height: 10),
          if (shown.isEmpty)
            const Text(
              'No tagged items yet.',
              style: TextStyle(color: Color(0xFF8C8C8C), fontSize: 12),
            )
          else
            ...shown.map((e) {
              final ratio = (e.value / maxCount).clamp(0.0, 1.0);
              return Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    SizedBox(
                      width: 90,
                      child: Text(
                        e.key,
                        style: const TextStyle(fontSize: 12),
                      ),
                    ),
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(999),
                        child: LinearProgressIndicator(
                          value: ratio,
                          minHeight: 6,
                          backgroundColor: Colors.white10,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    SizedBox(
                      width: 24,
                      child: Text(
                        '${e.value}',
                        textAlign: TextAlign.right,
                        style: const TextStyle(
                            fontSize: 12, color: Color(0xFFB4B4B4)),
                      ),
                    ),
                  ],
                ),
              );
            }),
        ],
      ),
    );
  }

  Widget _storageSection(Map<String, dynamic> s) {
    final st = (s['storage'] ?? const {}) as Map;
    final enc = (s['encryption'] ?? const {}) as Map;
    final used = (st['used_bytes'] ?? 0) as int;
    final limit = (st['limit_bytes'] ?? 0) as int;
    final pending = (st['pending_bytes'] ?? 0) as int;
    final kdfIter = (enc['kdf_iterations'] ?? 0) as int;
    final kdfStrength = (enc['kdf_strength'] ?? 'legacy') as String;
    final kdfBadgeColor = kdfStrength == 'modern'
        ? const Color(0xFF66BB6A)
        : const Color(0xFFFFA726);
    final chunked = (enc['chunked_upload_enabled'] ?? false) as bool;
    final semantic = (enc['semantic_search_enabled'] ?? false) as bool;
    final ratio = limit > 0 ? (used / limit).clamp(0.0, 1.0) : 0.0;
    return _card(
      'STORAGE & ENCRYPTION',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(999),
                  child: LinearProgressIndicator(
                    value: ratio,
                    minHeight: 8,
                    backgroundColor: Colors.white10,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Text(
                '${_formatBytes(used)} / ${_formatBytes(limit)}',
                style:
                    const TextStyle(color: Color(0xFFB4B4B4), fontSize: 12),
              ),
            ],
          ),
          if (pending > 0) ...[
            const SizedBox(height: 4),
            Text(
              '${_formatBytes(pending)} in-flight upload',
              style:
                  const TextStyle(color: Color(0xFF8C8C8C), fontSize: 12),
            ),
          ],
          const SizedBox(height: 12),
          _kvRow('Encryption', 'AES-256-GCM'),
          _kvRow(
            'Key derivation',
            'PBKDF2 ${kdfIter.toString()}',
            badge: kdfStrength,
            badgeColor: kdfBadgeColor,
          ),
          _kvRow('Chunked file protection', chunked ? 'Active' : 'Inactive'),
          _kvRow('Semantic search', semantic ? 'Enabled' : 'Disabled'),
        ],
      ),
    );
  }

  Widget _inheritanceSection(Map<String, dynamic> s) {
    final inh = (s['inheritance'] ?? const {}) as Map;
    final configured = (inh['configured'] ?? false) as bool;
    final frozen = (inh['frozen'] ?? false) as bool;
    return _card(
      'RECOVERY & INHERITANCE',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            configured
                ? 'Inheritance configured.'
                : 'Inheritance not configured.',
            style: TextStyle(
              color: configured
                  ? const Color(0xFF66BB6A)
                  : const Color(0xFFB4B4B4),
              fontSize: 13,
            ),
          ),
          if (frozen) ...[
            const SizedBox(height: 4),
            const Text(
              'Vault is in a soft-freeze window.',
              style: TextStyle(color: Color(0xFFFFA726), fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }

  Widget _recommendationsSection(Map<String, dynamic> s) {
    final recs = (s['recommendations'] as List?) ?? const [];
    if (recs.isEmpty) {
      return _card(
        'RECOMMENDATIONS',
        const Text(
          'No recommendations - you are looking solid.',
          style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
        ),
      );
    }
    return _card(
      'RECOMMENDATIONS',
      Column(
        children: recs.map<Widget>((r) {
          final m = Map<String, dynamic>.from(r as Map);
          final pri = (m['priority'] ?? 'low').toString();
          final msg = (m['message'] ?? '').toString();
          final route = m['route'] as String?;
          return Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: _priorityColor(pri),
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    msg,
                    style: const TextStyle(fontSize: 13),
                  ),
                ),
                if (route != null) ...[
                  const SizedBox(width: 8),
                  OutlinedButton(
                    onPressed: () => Navigator.pushNamed(context, route),
                    child: const Text('Open'),
                  ),
                ],
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _dot(String label, Color color) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(fontSize: 13)),
      ],
    );
  }

  Widget _kvRow(String k, String v, {String? badge, Color? badgeColor}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          SizedBox(
            width: 160,
            child: Text(
              k,
              style:
                  const TextStyle(color: Color(0xFFB4B4B4), fontSize: 12),
            ),
          ),
          Expanded(child: Text(v, style: const TextStyle(fontSize: 13))),
          if (badge != null)
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: (badgeColor ?? Colors.white24).withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text(
                badge,
                style: TextStyle(
                  fontSize: 11,
                  color: badgeColor ?? Colors.white70,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF1A1A1A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF1A1A1A),
        title: Text(AppLocalizations.of(context).securityCenterTitle),
        actions: [
          IconButton(
            tooltip: AppLocalizations.of(context).commonRefresh,
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
                      ? Text(
                          _error!,
                          style: const TextStyle(color: Color(0xFFE57373)),
                        )
                      : RefreshIndicator(
                          onRefresh: _refresh,
                          child: ListView(
                            children: [
                              _scoreHeader(_summary!),
                              _devicesSection(_summary!),
                              _passwordSection(_summary!),
                              _vaultSection(_summary!),
                              _storageSection(_summary!),
                              _inheritanceSection(_summary!),
                              _recommendationsSection(_summary!),
                            ],
                          ),
                        ),
            ),
          ),
        ),
      ),
    );
  }
}
