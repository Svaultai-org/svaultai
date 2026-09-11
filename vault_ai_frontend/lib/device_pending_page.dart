import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:provider/provider.dart';

import 'api_client.dart';
import 'device_id.dart';
import 'l10n/app_localizations.dart';
import 'ui/responsive.dart';
import 'main.dart' show AppState, backendBaseUrl;


class DevicePendingPage extends StatefulWidget {
  
  
  final String? status;
  final String? deviceId;
  final String? message;

  const DevicePendingPage({
    super.key,
    this.status,
    this.message,
    this.deviceId,
  });

  @override
  State<DevicePendingPage> createState() => _DevicePendingPageState();
}

class _DevicePendingPageState extends State<DevicePendingPage> {
  Timer? _pollTimer;
  bool _checking = false;
  String? _checkError;

  
  Map<String, dynamic>? _diagnosis;
  bool _diagnosing = false;
  String? _diagnoseError;

  
  late final String _status;
  late final String? _deviceId;
  late final String _message;
  bool _argsResolved = false;

  
  DateTime? _cooldownUntil;
  Timer? _countdownTimer;
  bool _selfApprovalBusy = false;
  String? _selfApprovalError;

  void _resolveArgs() {
    if (_argsResolved) return;
    final args = ModalRoute.of(context)?.settings.arguments;
    final Map argsMap = args is Map ? args : const {};
    _status = widget.status ??
        (argsMap['status']?.toString() ?? 'pending');
    _deviceId = widget.deviceId ?? argsMap['device_id']?.toString();
    _message = widget.message ??
        (argsMap['message']?.toString() ?? 'This device is not trusted.');
    _argsResolved = true;

    
    if (_status == 'pending') {
      _pollTimer = Timer.periodic(
        const Duration(seconds: 5),
        (_) => _check(silent: true),
      );
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _countdownTimer?.cancel();
    super.dispose();
  }

  
  Future<Map<String, String>?> _promptVaultAndPin({
    required String title,
    required String confirmLabel,
  }) async {
    final vaultCtrl = TextEditingController();
    final pinCtrl = TextEditingController();
    final result = await showDialog<Map<String, String>?>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: vaultCtrl,
              decoration: const InputDecoration(labelText: 'Vault name'),
              autofocus: true,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: pinCtrl,
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
              final v = vaultCtrl.text.trim();
              final p = pinCtrl.text.trim();
              if (v.isEmpty || p.isEmpty) return;
              Navigator.pop(ctx, {'vault_name': v, 'pin': p});
            },
            child: Text(confirmLabel),
          ),
        ],
      ),
    );
    vaultCtrl.dispose();
    pinCtrl.dispose();
    return result;
  }

  void _startCountdown() {
    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return;
      if (_cooldownUntil == null ||
          DateTime.now().isAfter(_cooldownUntil!)) {
        t.cancel();
      }
      setState(() {});
    });
  }

  Future<void> _requestSelfApproval() async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    final creds = await _promptVaultAndPin(
      title: 'Request self-approval',
      confirmLabel: 'Start cooldown',
    );
    if (creds == null) return;

    setState(() {
      _selfApprovalBusy = true;
      _selfApprovalError = null;
    });
    try {
      final r = await VaultAIClient(baseUrl: backendBaseUrl)
          .requestSelfApproval(
        authToken: token,
        vaultName: creds['vault_name']!,
        pin: creds['pin']!,
      );
      final iso = r['cooldown_until']?.toString();
      if (iso != null) {
        _cooldownUntil = DateTime.tryParse(iso)?.toLocal();
        _startCountdown();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _selfApprovalError = e.toString();
        });
      }
    } finally {
      if (mounted) setState(() => _selfApprovalBusy = false);
    }
  }

  Future<void> _finalizeSelfApproval() async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    final creds = await _promptVaultAndPin(
      title: 'Confirm with PIN',
      confirmLabel: 'Finalize',
    );
    if (creds == null) return;

    setState(() {
      _selfApprovalBusy = true;
      _selfApprovalError = null;
    });
    try {
      await VaultAIClient(baseUrl: backendBaseUrl).finalizeSelfApproval(
        authToken: token,
        vaultName: creds['vault_name']!,
        pin: creds['pin']!,
      );
      _countdownTimer?.cancel();
      _pollTimer?.cancel();
      if (!mounted) return;
      Navigator.pushNamedAndRemoveUntil(context, '/pin', (_) => false);
    } catch (e) {
      if (mounted) {
        setState(() {
          _selfApprovalError = e.toString();
        });
      }
    } finally {
      if (mounted) setState(() => _selfApprovalBusy = false);
    }
  }

  Future<void> _cancelSelfApproval() async {
    final token = context.read<AppState>().sessionToken;
    if (token == null) return;
    setState(() {
      _selfApprovalBusy = true;
      _selfApprovalError = null;
    });
    try {
      await VaultAIClient(baseUrl: backendBaseUrl).cancelSelfApproval(
        authToken: token,
      );
      _countdownTimer?.cancel();
      if (mounted) setState(() => _cooldownUntil = null);
    } catch (e) {
      if (mounted) {
        setState(() {
          _selfApprovalError = e.toString();
        });
      }
    } finally {
      if (mounted) setState(() => _selfApprovalBusy = false);
    }
  }

  String _formatRemaining(Duration d) {
    final s = d.inSeconds.clamp(0, 86400);
    final m = (s ~/ 60).toString().padLeft(1, '0');
    final ss = (s % 60).toString().padLeft(2, '0');
    return '$m:$ss';
  }

  Widget _selfApprovalSection() {
    final now = DateTime.now();
    final cooldown = _cooldownUntil;
    final inCooldown = cooldown != null && cooldown.isAfter(now);
    final cooldownElapsed = cooldown != null && !cooldown.isAfter(now);

    if (cooldown == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Divider(color: Colors.white12, height: 32),
          const Text(
            'Or recover from this device',
            style: TextStyle(
              color: Color(0xFFB4B4B4),
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'You can self-approve this device by entering your PIN. For '
            'safety, the device activates only after a short waiting period '
            'during which any of your other trusted devices can cancel.',
            style: TextStyle(color: Color(0xFFB4B4B4), height: 1.5, fontSize: 13),
          ),
          if (_selfApprovalError != null) ...[
            const SizedBox(height: 8),
            Text(
              _selfApprovalError!,
              style: const TextStyle(color: Color(0xFFE57373), fontSize: 13),
            ),
          ],
          const SizedBox(height: 10),
          FilledButton.icon(
            onPressed: _selfApprovalBusy ? null : _requestSelfApproval,
            icon: const Icon(Icons.lock_clock),
            label: Text(
              AppLocalizations.of(context).devicePendingRequestSelfApproval,
            ),
          ),
        ],
      );
    }

    final remaining = cooldown.difference(now);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Divider(color: Colors.white12, height: 32),
        const Text(
          'Self-approval in progress',
          style: TextStyle(
            color: Color(0xFFFFA726),
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          inCooldown
              ? 'For your safety, this device will activate after '
                '${_formatRemaining(remaining)}. Any of your other '
                'trusted devices can cancel this approval before then.'
              : 'Cooldown elapsed. Enter your PIN to finalize approval.',
          style: const TextStyle(color: Color(0xFFB4B4B4), height: 1.5, fontSize: 13),
        ),
        if (inCooldown) ...[
          const SizedBox(height: 12),
          Text(
            '${_formatRemaining(remaining)} remaining',
            style: TextStyle(
              fontSize: vrMetric(context),
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
        if (_selfApprovalError != null) ...[
          const SizedBox(height: 8),
          Text(
            _selfApprovalError!,
            style: const TextStyle(color: Color(0xFFE57373), fontSize: 13),
          ),
        ],
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: (cooldownElapsed && !_selfApprovalBusy)
                    ? _finalizeSelfApproval
                    : null,
                icon: const Icon(Icons.check),
                label: Text(
                  AppLocalizations.of(context).devicePendingFinalize,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _selfApprovalBusy ? null : _cancelSelfApproval,
                icon: const Icon(Icons.close),
                label: Text(
                  AppLocalizations.of(context).devicePendingCancelApproval,
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  
  Future<void> _diagnose() async {
    if (_diagnosing) return;
    setState(() {
      _diagnosing = true;
      _diagnoseError = null;
    });
    try {
      final token = context.read<AppState>().sessionToken;
      if (token == null) {
        if (mounted) {
          setState(() {
            _diagnoseError = 'No active session — please sign in again.';
          });
        }
        return;
      }
      final res = await VaultAIClient(baseUrl: backendBaseUrl)
          .diagnoseTrust(authToken: token);
      if (mounted) setState(() => _diagnosis = res);
    } catch (e) {
      if (mounted) setState(() => _diagnoseError = 'Diagnose failed: $e');
    } finally {
      if (mounted) setState(() => _diagnosing = false);
    }
  }

  
  Future<void> _registerDeviceAndRetry() async {
    if (_checking) return;
    setState(() {
      _checking = true;
      _checkError = null;
    });
    try {
      final token = context.read<AppState>().sessionToken;
      if (token == null) {
        if (mounted) {
          Navigator.pushNamedAndRemoveUntil(context, '/auth', (_) => false);
        }
        return;
      }
      final id = currentDeviceId() ?? await getOrCreateDeviceId();
      final res = await VaultAIClient(baseUrl: backendBaseUrl).registerDevice(
        authToken: token,
        deviceId: id,
        label: 'this browser',
      );
      final status = res['status']?.toString();
      if (status == 'trusted') {
        _pollTimer?.cancel();
        if (!mounted) return;
        Navigator.pushNamedAndRemoveUntil(context, '/pin', (_) => false);
        return;
      }
      
      
      await _check(silent: false);
    } catch (e) {
      if (mounted) {
        setState(() => _checkError = 'Register failed: $e');
      }
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _check({bool silent = false}) async {
    if (_checking) return;
    setState(() {
      _checking = true;
      _checkError = null;
    });

    final token = context.read<AppState>().sessionToken;
    if (token == null) {
      
      
      if (mounted) {
        Navigator.pushNamedAndRemoveUntil(context, '/auth', (_) => false);
      }
      return;
    }

    try {
      final me = await VaultAIClient(baseUrl: backendBaseUrl).listDevices(
        authToken: token,
      );
      final currentId = me['current_device_id']?.toString();
      final devices = me['devices'];
      if (devices is List) {
        for (final d in devices) {
          if (d is Map &&
              d['device_id']?.toString() == currentId &&
              d['status']?.toString() == 'trusted') {
            
            
            if (!mounted) return;
            _pollTimer?.cancel();
            final app = context.read<AppState>();
            final destination = app.unlocked ? '/chat' : '/pin';
            Navigator.pushNamedAndRemoveUntil(
              context, destination, (_) => false,
            );
            return;
          }
        }
      }
      if (!silent && mounted) {
        setState(() {
          _checkError =
              'Still pending. Try approving this device from a trusted one.';
        });
      }
    } catch (e) {
      if (!silent && mounted) {
        setState(() {
          _checkError = 'Could not refresh: $e';
        });
      }
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _signOut() async {
    _pollTimer?.cancel();
    try {
      await context.read<AppState>().signOut();
    } catch (_) {}
    if (!mounted) return;
    Navigator.pushNamedAndRemoveUntil(context, '/auth', (_) => false);
  }

  String _shortDeviceId() {
    final id = _deviceId ?? currentDeviceId() ?? '';
    if (id.length <= 12) return id;
    return '${id.substring(0, 8)}...${id.substring(id.length - 4)}';
  }

  String _title() {
    switch (_status) {
      case 'revoked':
        return 'This device was revoked';
      case 'missing_device_id':
        return 'Your app is out of date';
      case 'missing':
        return 'This device is not registered';
      case 'pending':
        return 'This device is not trusted yet';
      default:
        
        
        return 'This device is not trusted yet';
    }
  }

  Widget _bodyCopy() {
    switch (_status) {
      case 'revoked':
        return const Text(
          'You revoked this device. Sign in from a different browser, or '
          'sign out and start fresh. (Signing back in on this browser will '
          'still hit the same revoked record.)',
          style: TextStyle(color: Color(0xFFB4B4B4), height: 1.5),
        );
      case 'missing_device_id':
        return const Text(
          'Your app does not send the device-id header that the server '
          'expects. Refresh this page (web) or reinstall the app (native) '
          'and sign in again.',
          style: TextStyle(color: Color(0xFFB4B4B4), height: 1.5),
        );
      case 'missing':
        return const Text(
          'This browser sent a device id the server has no record of. This '
          'usually means registration was interrupted on first sign-in. '
          'Tap "Register this device" below, or sign out and sign back in '
          'to re-register.',
          style: TextStyle(color: Color(0xFFB4B4B4), height: 1.5),
        );
      case 'pending':
      default:
        return const Text(
          'For security, Svaultai asks you to approve each new device from '
          'a device you already trust.\n\n'
          'To approve this device:\n'
          '  1. Open Svaultai on a device you already trust.\n'
          '  2. Go to Settings -> Devices.\n'
          '  3. Click "Approve" next to this device.\n\n'
          'This page checks automatically every few seconds; you can also '
          'tap "Check again" below.',
          style: TextStyle(color: Color(0xFFB4B4B4), height: 1.5),
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    _resolveArgs();
    final isPending = _status == 'pending';
    return Scaffold(
      backgroundColor: const Color(0xFF1A1A1A),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            
            
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.shield_outlined,
                    size: 48,
                    color: Color(0xFFB4B4B4),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    _title(),
                    style: const TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 12),
                  
                  
                  Text(
                    _message,
                    style: const TextStyle(
                      color: Color(0xFFE0E0E0),
                      fontSize: 14,
                    ),
                  ),
                  const SizedBox(height: 12),
                  _bodyCopy(),
                  const SizedBox(height: 20),
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFF262626),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Device: ${_shortDeviceId()}',
                          style: const TextStyle(
                            color: Color(0xFFB4B4B4),
                            fontSize: 13,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          
                          
                          'Status: $_status',
                          style: const TextStyle(
                            color: Color(0xFFB4B4B4),
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (_checkError != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      _checkError!,
                      style: const TextStyle(
                        color: Color(0xFFE57373),
                        fontSize: 13,
                      ),
                    ),
                  ],
                  const SizedBox(height: 20),
                  Row(
                    children: [
                      if (isPending)
                        Expanded(
                          child: ElevatedButton.icon(
                            onPressed: _checking ? null : () => _check(silent: false),
                            icon: _checking
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Icon(Icons.refresh),
                            label: Text(
                              AppLocalizations.of(context).devicePendingCheckAgain,
                            ),
                          ),
                        ),
                      if (_status == 'missing')
                        Expanded(
                          child: ElevatedButton.icon(
                            onPressed:
                                _checking ? null : _registerDeviceAndRetry,
                            icon: _checking
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Icon(Icons.app_registration),
                            label: Text(
                              AppLocalizations.of(context).devicePendingRegisterDevice,
                            ),
                          ),
                        ),
                      if (isPending || _status == 'missing')
                        const SizedBox(width: 12),
                      Expanded(
                        child: OutlinedButton(
                          onPressed: _signOut,
                          child: Text(
                            AppLocalizations.of(context).commonSignOut,
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (isPending) _selfApprovalSection(),
                  
                  
                  const Divider(color: Colors.white12, height: 32),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _diagnosing ? null : _diagnose,
                          icon: _diagnosing
                              ? const SizedBox(
                                  width: 16,
                                  height: 16,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.search),
                          label: Text(
                            AppLocalizations.of(context).devicePendingDiagnoseTrust,
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (_diagnoseError != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      _diagnoseError!,
                      style: const TextStyle(
                        color: Color(0xFFE57373),
                        fontSize: 13,
                      ),
                    ),
                  ],
                  if (_diagnosis != null) ...[
                    const SizedBox(height: 12),
                    _DiagnosticBlock(diagnosis: _diagnosis!),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}


class _DiagnosticBlock extends StatelessWidget {
  const _DiagnosticBlock({required this.diagnosis});

  final Map<String, dynamic> diagnosis;

  String _formatField(Object? value) {
    if (value == null) return 'null';
    if (value is String) return value;
    try {
      
      return const JsonEncoder.withIndent('  ').convert(value);
    } catch (_) {
      return value.toString();
    }
  }

  String _composeClipboardText() {
    
    
    final lines = <String>[
      'verdict: ${_formatField(diagnosis['verdict'])}',
      'sent_device_id_prefix: '
          '${_formatField(diagnosis['sent_device_id_prefix'])}',
      'sent_device_id_present: '
          '${_formatField(diagnosis['sent_device_id_present'])}',
      'trusted_device_count: '
          '${_formatField(diagnosis['trusted_device_count'])}',
      'auto_trust_guardrail_would_fire: '
          '${_formatField(diagnosis['auto_trust_guardrail_would_fire'])}',
      'current_device_row:',
      _formatField(diagnosis['current_device_row']),
      'other_device_rows '
          '(${_formatField(diagnosis['other_devices_total'])} total):',
      _formatField(diagnosis['other_devices']),
      'user_id_tail: ${_formatField(diagnosis['user_id_tail'])}',
    ];
    return lines.join('\n');
  }

  Widget _row(String label, Object? value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.5,
            ),
          ),
          const SizedBox(height: 2),
          
          
          SelectableText(
            _formatField(value),
            style: const TextStyle(
              color: Color(0xFFE0E0E0),
              fontSize: 12,
              height: 1.4,
              fontFamily: 'monospace',
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          
          SelectableText(
            'Verdict: ${diagnosis['verdict']}',
            style: const TextStyle(
              color: Color(0xFFE0E0E0),
              fontWeight: FontWeight.w800,
              fontSize: 13,
              fontFamily: 'monospace',
            ),
          ),
          const SizedBox(height: 10),
          _row('sent_device_id_prefix', diagnosis['sent_device_id_prefix']),
          _row('trusted_device_count', diagnosis['trusted_device_count']),
          _row(
            'auto_trust_guardrail_would_fire',
            diagnosis['auto_trust_guardrail_would_fire'],
          ),
          _row('current_device_row', diagnosis['current_device_row']),
          _row(
            'other_device_rows '
            '(${diagnosis['other_devices_total']} total)',
            diagnosis['other_devices'],
          ),
          _row('user_id_tail', diagnosis['user_id_tail']),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              icon: const Icon(Icons.copy, size: 16),
              label: Text(
                AppLocalizations.of(context).devicePendingCopyDiagnostics,
              ),
              onPressed: () async {


                final messenger = ScaffoldMessenger.maybeOf(context);
                final copiedLabel = AppLocalizations.of(context)
                    .devicePendingDiagnosticsCopied;
                await Clipboard.setData(
                  ClipboardData(text: _composeClipboardText()),
                );
                messenger?.clearSnackBars();
                messenger?.showSnackBar(
                  SnackBar(
                    content: Text(copiedLabel),
                    duration: const Duration(seconds: 2),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
