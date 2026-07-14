// Recovery Kit Settings + Restore-Verify UI.
//
// Recovery Kit is OPT-IN. When the user enables it, the client
// generates a 32-byte seed, wraps the vault's MVK with an
// Argon2id-derived KEK, and POSTs the ciphertext to
// /vault/ciphertext/recovery-kit. The seed is shown to the user
// ONCE and never sent to the server. The user MUST transcribe it
// or copy it — a lost seed post-enrollment reverts the vault to
// "PIN loss = data loss" (unchanged from the base guarantee).
//
// This page also offers a *local* seed-verification affordance
// that the user can run any time after enrollment: paste the seed
// back in and confirm it unwraps correctly against the wrapped
// MVK bytes the client received at enrollment time.
//
// This page is a leaf under Settings/Security. It only runs while
// a vault is unlocked (ZK MVK is active). Legacy vaults see the
// page but the enable button is disabled with an explanatory
// message — Recovery Kit only makes sense after ZK adoption.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import 'main.dart' show AppState, backendBaseUrl;
import 'services/recovery_kit.dart';
import 'services/zk_active_mvk.dart' as zk_mvk_store;

class RecoveryKitSettingsPage extends StatefulWidget {
  const RecoveryKitSettingsPage({super.key});

  @override
  State<RecoveryKitSettingsPage> createState() =>
      _RecoveryKitSettingsPageState();
}

class _RecoveryKitSettingsPageState
    extends State<RecoveryKitSettingsPage> {
  bool _busy = false;
  String? _error;
  RecoveryKit? _lastKit;
  String? _successMessage;

  Future<void> _enable() async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) {
      setState(() => _error = 'Session expired — please sign in.');
      return;
    }
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) {
      setState(() {
        _error = 'Recovery Kit is only available for private (ZK) '
            'vaults. Your current vault has not been adopted to '
            'the ZK path yet — sign in again with your PIN to '
            'complete the one-time adoption.';
      });
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _successMessage = null;
    });
    try {
      final kit = await createRecoveryKitForMvk(mvk);
      final body = recoveryKitUploadBody(kit);
      final resp = await http.post(
        Uri.parse('$backendBaseUrl/vault/ciphertext/recovery-kit'),
        headers: <String, String>{
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode(body),
      );
      if (resp.statusCode != 200) {
        setState(() {
          _error = 'Server refused the Recovery Kit upload '
              '(HTTP ${resp.statusCode}).';
          _busy = false;
        });
        return;
      }
      setState(() {
        _lastKit = kit;
        _busy = false;
        _successMessage =
            'Recovery Kit enabled. Save the seed below — it will '
            'never be shown again.';
      });
    } catch (e) {
      setState(() {
        _error = 'Could not enable Recovery Kit: '
            '${e.toString().replaceFirst('Exception: ', '')}';
        _busy = false;
      });
    }
  }

  Future<void> _verifySeed() async {
    final kit = _lastKit;
    if (kit == null) return;
    final ctrl = TextEditingController();
    final result = await showDialog<String>(
      context: context,
      builder: (dctx) {
        return AlertDialog(
          backgroundColor: const Color(0xFF2F2F2F),
          title: const Text('Verify your Recovery Kit seed'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Type or paste the seed you just saved. We will '
                  'unwrap the MVK locally and confirm the seed is '
                  'correct — the seed never leaves this device.',
                  style: TextStyle(
                    color: Color(0xFFB4B4B4), fontSize: 12,
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('recovery_verify_seed_input'),
                  controller: ctrl,
                  maxLines: 3,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Recovery seed',
                    hintText: '32 groups of 4 characters',
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dctx),
              child: const Text('Cancel'),
            ),
            FilledButton(
              key: const Key('recovery_verify_seed_submit'),
              onPressed: () =>
                  Navigator.pop(dctx, ctrl.text.trim()),
              child: const Text('Verify'),
            ),
          ],
        );
      },
    );
    if (result == null || result.isEmpty) return;
    try {
      final parsed = parseHumanReadableSeed(result);
      if (parsed.length != kit.seed.length ||
          !_bytesEqual(parsed, kit.seed)) {
        setState(() {
          _error = 'The seed you entered does not match the seed '
              'we just generated.';
        });
        return;
      }
      final restored = await restoreMvkFromRecovery(
        seed: parsed,
        wrappedMvk: kit.wrappedMvk,
        recoverySalt: kit.recoverySalt,
      );
      final mvk = zk_mvk_store.ZkActiveMvk.current();
      if (mvk == null) {
        setState(() {
          _error = 'Vault was locked mid-verify. Please try again.';
        });
        return;
      }
      final a = await mvk.extractBytes();
      final b = await restored.extractBytes();
      if (!_bytesEqual(Uint8List.fromList(a),
          Uint8List.fromList(b))) {
        setState(() {
          _error = 'Recovered MVK does not match the active MVK — '
              'the seed is wrong or the kit is corrupt.';
        });
        return;
      }
      setState(() {
        _successMessage = 'Verified — this seed correctly unwraps '
            'your MVK.';
        _error = null;
      });
    } catch (e) {
      setState(() {
        _error = 'Verification failed: '
            '${e.toString().replaceFirst('Exception: ', '')}';
      });
    }
  }

  bool _bytesEqual(Uint8List a, Uint8List b) {
    if (a.length != b.length) return false;
    for (int i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }

  @override
  Widget build(BuildContext context) {
    final canEnable =
        zk_mvk_store.ZkActiveMvk.current() != null && !_busy;
    return Scaffold(
      backgroundColor: const Color(0xFF1A1A1A),
      appBar: AppBar(
        title: const Text('Recovery Kit'),
        backgroundColor: const Color(0xFF1A1A1A),
        elevation: 0,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _explainerCard(),
              const SizedBox(height: 16),
              _enableCard(canEnable),
              if (_successMessage != null) ...[
                const SizedBox(height: 16),
                _successCard(_successMessage!),
              ],
              if (_lastKit != null) ...[
                const SizedBox(height: 16),
                _seedDisplayCard(_lastKit!),
              ],
              if (_error != null) ...[
                const SizedBox(height: 16),
                _errorCard(_error!),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _explainerCard() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF2A2A2A),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Recovery Kit is opt-in.',
            style: TextStyle(fontWeight: FontWeight.w800),
          ),
          SizedBox(height: 8),
          Text(
            'Enabling it lets you regain access if you lose your '
            'PIN, using a 32-byte seed you save locally. The seed '
            'never touches VaultAI\'s servers. Anyone with your '
            'seed can decrypt your vault, so keep it as private '
            'as your PIN.',
            style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
          ),
          SizedBox(height: 8),
          Text(
            'If you enable the Kit and then lose the seed, your '
            'vault reverts to "PIN loss = data loss." VaultAI '
            'cannot recover it.',
            style: TextStyle(color: Color(0xFFFFA726), fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _enableCard(bool canEnable) {
    final zkAdopted = zk_mvk_store.ZkActiveMvk.current() != null;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF2A2A2A),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!zkAdopted)
            const Padding(
              padding: EdgeInsets.only(bottom: 12),
              child: Text(
                'Your vault has not been adopted to the private '
                '(ZK) path yet. Sign in again with your PIN to '
                'complete adoption, then return here to enable '
                'the Recovery Kit.',
                style: TextStyle(
                    color: Color(0xFFB4B4B4), fontSize: 12),
              ),
            ),
          FilledButton.icon(
            key: const Key('recovery_kit_enable_button'),
            onPressed: canEnable ? _enable : null,
            icon: _busy
                ? const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(Icons.enhanced_encryption_outlined),
            label: Text(_busy
                ? 'Enabling…'
                : (_lastKit == null
                    ? 'Enable Recovery Kit'
                    : 'Re-enable (rotate seed)')),
          ),
        ],
      ),
    );
  }

  Widget _successCard(String msg) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF10A37F).withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: const Color(0xFF10A37F).withValues(alpha: 0.35),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.check_circle_outline,
              color: Color(0xFF66FFA6), size: 22),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              msg,
              style: const TextStyle(
                  color: Color(0xFFA5F3D0), fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }

  Widget _errorCard(String msg) {
    return Container(
      key: const Key('recovery_kit_error_card'),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFEF5350).withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: const Color(0xFFEF5350).withValues(alpha: 0.40),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline,
              color: Color(0xFFFF8B87), size: 22),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              msg,
              style: const TextStyle(
                  color: Color(0xFFFFC7C4), fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }

  Widget _seedDisplayCard(RecoveryKit kit) {
    final seed = kit.toHumanReadableSeed();
    return Container(
      key: const Key('recovery_kit_seed_display'),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF3B82F6).withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: const Color(0xFF3B82F6).withValues(alpha: 0.45),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Your Recovery Seed',
            style: TextStyle(
              fontWeight: FontWeight.w800,
              color: Color(0xFFCFE2FF),
            ),
          ),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A1A),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.white10),
            ),
            child: SelectableText(
              seed,
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 14,
                color: Color(0xFFF5F5F5),
                letterSpacing: 1.2,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('recovery_kit_copy_seed'),
                  onPressed: () async {
                    await Clipboard.setData(
                      ClipboardData(text: seed),
                    );
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text(
                          'Seed copied to clipboard')),
                    );
                  },
                  icon: const Icon(Icons.copy_all_outlined),
                  label: const Text('Copy seed'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('recovery_kit_verify_seed'),
                  onPressed: _verifySeed,
                  icon: const Icon(Icons.verified_outlined),
                  label: const Text('Verify'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'This is the only time this seed is shown. If you lose '
            'it, you cannot recover your vault after a PIN loss.',
            style: TextStyle(
                color: Color(0xFF90CAF9), fontSize: 12),
          ),
        ],
      ),
    );
  }
}
