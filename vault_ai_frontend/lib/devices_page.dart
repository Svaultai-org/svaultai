import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api_client.dart';
import 'l10n/app_localizations.dart';
import 'main.dart' show AppState, backendBaseUrl;


class DevicesPage extends StatefulWidget {
  const DevicesPage({super.key});

  @override
  State<DevicesPage> createState() => _DevicesPageState();
}

class _DevicesPageState extends State<DevicesPage> {
  late final VaultAIClient _client;
  Timer? _refreshTimer;
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _devices = const [];
  String? _pendingActionDeviceId;  

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
      final me = await _client.listDevices(authToken: token);
      if (!mounted) return;
      setState(() {
        _devices = List<Map<String, dynamic>>.from(
          (me['devices'] as List? ?? <dynamic>[])
              .whereType<Map>()
              .map((m) => Map<String, dynamic>.from(m)),
        );
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load devices: $e';
      });
    }
  }

  Future<void> _approve(String deviceId) async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    
    
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _pendingActionDeviceId = deviceId);
    try {
      await _client.approveDevice(
        authToken: token,
        deviceId: deviceId,
      );
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            AppLocalizations.of(context).snackDeviceApproved,
          ),
        ),
      );
      await _refresh();
    } catch (e) {
      messenger.showSnackBar(
        SnackBar(content: Text('Approve failed: $e')),
      );
    } finally {
      if (mounted) setState(() => _pendingActionDeviceId = null);
    }
  }

  Future<void> _confirmRevoke(Map<String, dynamic> device) async {
    final isCurrent = device['is_current'] == true;
    final label = (device['label'] ?? device['user_agent_brand'] ??
                   'this device').toString();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(isCurrent ? 'Revoke this device?' : 'Revoke device?'),
        content: Text(
          isCurrent
              ? 'You are about to revoke "$label" - the device you are '
                'currently using. You will be signed out immediately and '
                'will need to sign in on a different browser to come back.'
              : 'Revoke "$label"? This is permanent. To use it again, '
                'sign in fresh on that device.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(AppLocalizations.of(context).commonCancel),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
            child: Text(AppLocalizations.of(context).commonRevoke),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _revoke(device['device_id'].toString(), isCurrent: isCurrent);
  }

  Future<void> _revoke(String deviceId, {required bool isCurrent}) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) return;
    setState(() => _pendingActionDeviceId = deviceId);
    try {
      final result = await _client.revokeDevice(
        authToken: token,
        deviceId: deviceId,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            AppLocalizations.of(context).snackDeviceRevoked,
          ),
        ),
      );
      
      if (result['caller_revoked'] == true || isCurrent) {
        try {
          await app.signOut();
        } catch (_) {}
        if (!mounted) return;
        Navigator.pushNamedAndRemoveUntil(context, '/auth', (_) => false);
        return;
      }
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Revoke failed: $e')),
      );
    } finally {
      if (mounted) setState(() => _pendingActionDeviceId = null);
    }
  }

  String _shortId(String id) =>
      id.length <= 12 ? id : '${id.substring(0, 8)}...${id.substring(id.length - 4)}';

  Widget _deviceRow(Map<String, dynamic> d) {
    final deviceId = d['device_id'].toString();
    final status = d['status']?.toString() ?? 'unknown';
    final label = (d['label'] ?? d['user_agent_brand'] ?? _shortId(deviceId)).toString();
    final isCurrent = d['is_current'] == true;
    final lastSeen = d['last_seen_at']?.toString();
    final cooldown = d['cooldown_until']?.toString();
    final busy = _pendingActionDeviceId == deviceId;

    Color statusColor;
    switch (status) {
      case 'trusted': statusColor = const Color(0xFF66BB6A); break;
      case 'pending': statusColor = const Color(0xFFFFA726); break;
      case 'revoked': statusColor = const Color(0xFFE57373); break;
      default:        statusColor = const Color(0xFFB4B4B4);
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isCurrent ? Colors.white24 : Colors.white10,
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 8, height: 8,
            decoration: BoxDecoration(color: statusColor, shape: BoxShape.circle),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        label,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                    if (isCurrent) ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: Colors.white12,
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: const Text(
                          'this device',
                          style: TextStyle(fontSize: 11, color: Color(0xFFB4B4B4)),
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  '$status${lastSeen != null ? '  ·  last seen $lastSeen' : ''}'
                  '${cooldown != null ? '  ·  cooldown until $cooldown' : ''}',
                  style: const TextStyle(color: Color(0xFFB4B4B4), fontSize: 12),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          if (status == 'pending') ...[
            FilledButton.icon(
              onPressed: busy ? null : () => _approve(deviceId),
              icon: const Icon(Icons.check, size: 16),
              label: Text(AppLocalizations.of(context).commonApprove),
            ),
            const SizedBox(width: 6),
            OutlinedButton(
              onPressed: busy ? null : () => _confirmRevoke(d),
              child: Text(AppLocalizations.of(context).commonReject),
            ),
          ] else if (status == 'trusted') ...[
            OutlinedButton(
              onPressed: busy ? null : () => _confirmRevoke(d),
              child: Text(AppLocalizations.of(context).commonRevoke),
            ),
          ],
          
        ],
      ),
    );
  }

  Widget _section(String title, List<Map<String, dynamic>> rows) {
    if (rows.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(bottom: 6, left: 4),
            child: Text(
              title,
              style: const TextStyle(
                fontSize: 12, fontWeight: FontWeight.w700,
                letterSpacing: 1.2,
                color: Color(0xFFB4B4B4),
              ),
            ),
          ),
          ...rows.map(_deviceRow),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final pending = _devices.where((d) => d['status'] == 'pending').toList();
    final trusted = _devices.where((d) => d['status'] == 'trusted').toList();
    final revoked = _devices.where((d) => d['status'] == 'revoked').toList();

    return Scaffold(
      backgroundColor: const Color(0xFF1A1A1A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF1A1A1A),
        title: Text(AppLocalizations.of(context).devicesTitle),
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
                      : ListView(
                          children: [
                            const Text(
                              'Devices that have signed in to your vault. '
                              'Approve new devices from one you '
                              'already trust; revoke any device that should '
                              'no longer have access.',
                              style: TextStyle(
                                color: Color(0xFFB4B4B4),
                                height: 1.5,
                              ),
                            ),
                            _section('PENDING APPROVAL', pending),
                            _section('TRUSTED', trusted),
                            _section('REVOKED (history)', revoked),
                            if (_devices.isEmpty)
                              const Padding(
                                padding: EdgeInsets.only(top: 24),
                                child: Text(
                                  'No devices yet.',
                                  style: TextStyle(color: Color(0xFFB4B4B4)),
                                ),
                              ),
                          ],
                        ),
            ),
          ),
        ),
      ),
    );
  }
}
