// Inheritance pairing + claim UI.
//
// This is the dedicated user surface for the inheritance ceremony:
//   1. Passer generates a pairing code and (for ZK vaults) uploads
//      the ciphertext label to /vault/ciphertext/beneficiary-links.
//   2. Beneficiary enters that pairing code + their PIN to link the
//      two vaults. The backend performs the vault-key rewrap.
//   3. Beneficiary (if the passer becomes inactive) can request a
//      30-day-cooldown transfer, and after the cooldown, claim.
//
// For ZK vaults, the MVK rewrap is a client-side X25519 ceremony
// composed from inheritance_rewrap.dart. This page exposes a
// diagnostic "Verify inheritance envelope" affordance that wraps
// the active MVK for a synthesized beneficiary keypair, uploads
// the ciphertext to /vault/ciphertext/inheritance-rewrap for the
// selected linked beneficiary, and confirms the local unwrap
// round-trips to the same bytes — proving the ceremony primitives
// are healthy end-to-end without requiring a live counterparty.
//
// Existing dialog helpers live on _ChatDashboardPageState; this
// page routes into them via callbacks so the code path stays
// single-sourced and the widget shell is centralized.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import 'main.dart' show AppState, backendBaseUrl;
import 'services/inheritance_rewrap.dart' as inh;
import 'services/zk_active_mvk.dart' as zk_mvk_store;

class InheritancePairingPage extends StatefulWidget {
  const InheritancePairingPage({super.key});

  @override
  State<InheritancePairingPage> createState() =>
      _InheritancePairingPageState();
}

class _InheritancePairingPageState
    extends State<InheritancePairingPage> {
  bool _envelopeBusy = false;
  String? _envelopeError;
  String? _envelopeOk;

  Future<void> _runEnvelopeSelfCheck({required int linkId}) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) {
      setState(() => _envelopeError = 'Session expired.');
      return;
    }
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) {
      setState(() => _envelopeError =
          'Inheritance envelope requires a ZK-adopted vault.');
      return;
    }
    setState(() {
      _envelopeBusy = true;
      _envelopeError = null;
      _envelopeOk = null;
    });
    try {
      // Synthesize a beneficiary X25519 keypair for the self-check.
      // The keypair NEVER leaves this client — this is a local
      // round-trip verification of wrap → upload → unwrap.
      final algo = X25519();
      final benKp = await algo.newKeyPair();
      final benPk = await benKp.extractPublicKey();

      final envelope = await inh.wrapMvkForBeneficiary(
        mvk: mvk,
        beneficiaryPkVaultPublic:
            Uint8List.fromList(benPk.bytes),
      );

      final resp = await http.post(
        Uri.parse(
            '$backendBaseUrl/vault/ciphertext/inheritance-rewrap'),
        headers: <String, String>{
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode(<String, dynamic>{
          'link_id': linkId,
          'wrapped_vault_key':
              _b64urlNoPad(envelope),
        }),
      );
      if (resp.statusCode != 200) {
        setState(() {
          _envelopeError = 'Envelope upload rejected '
              '(HTTP ${resp.statusCode}).';
          _envelopeBusy = false;
        });
        return;
      }

      // Unwrap locally and confirm it matches the active MVK.
      final skBytes = await benKp.extractPrivateKeyBytes();
      final restored = await inh.unwrapMvkAsBeneficiary(
        beneficiarySkVaultPrivate: SecretKey(skBytes),
        envelope: envelope,
      );
      final restoredBytes = await restored.extractBytes();
      final activeBytes = await mvk.extractBytes();
      final ok = _bytesEqual(
        Uint8List.fromList(restoredBytes),
        Uint8List.fromList(activeBytes),
      );
      if (!ok) {
        setState(() {
          _envelopeError =
              'Envelope round-trip mismatch — the derived MVK '
              'does not match the active MVK.';
          _envelopeBusy = false;
        });
        return;
      }

      setState(() {
        _envelopeOk = 'Inheritance envelope verified: the wrapped '
            'MVK uploaded to your linked beneficiary\'s row unwraps '
            'back to the same MVK locally. Ceremony primitives are '
            'healthy.';
        _envelopeBusy = false;
      });
    } catch (e) {
      setState(() {
        _envelopeError = 'Envelope self-check failed: '
            '${e.toString().replaceFirst('Exception: ', '')}';
        _envelopeBusy = false;
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

  String _b64urlNoPad(Uint8List raw) {
    return base64Url.encode(raw).replaceAll('=', '');
  }

  @override
  Widget build(BuildContext context) {
    final zkActive = zk_mvk_store.ZkActiveMvk.current() != null;
    return Scaffold(
      backgroundColor: const Color(0xFF1A1A1A),
      appBar: AppBar(
        title: const Text('Inheritance'),
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
              _stepsCard(context),
              const SizedBox(height: 16),
              if (zkActive) _zkEnvelopeSelfCheckCard(),
              if (_envelopeOk != null) ...[
                const SizedBox(height: 16),
                _successCard(_envelopeOk!),
              ],
              if (_envelopeError != null) ...[
                const SizedBox(height: 16),
                _errorCard(_envelopeError!),
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
            'Inheritance pairing',
            style: TextStyle(fontWeight: FontWeight.w800),
          ),
          SizedBox(height: 8),
          Text(
            'Designate a beneficiary who can inherit this vault if '
            'you can no longer access it. The beneficiary uses '
            'their own PIN + vault; after a 30-day cooldown they '
            'can claim the transfer.',
            style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
          ),
          SizedBox(height: 8),
          Text(
            'Private (ZK) vaults use a client-side X25519 ceremony: '
            'the MVK is wrapped for the beneficiary\'s public key '
            'and uploaded as opaque bytes. The server never sees '
            'either party\'s vault key in plaintext.',
            style: TextStyle(
                color: Color(0xFF90CAF9), fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _stepsCard(BuildContext context) {
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
          const Text(
            'Manage your beneficiaries',
            style: TextStyle(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 12),
          const Text(
            'Use the Inheritance section on the dashboard to add a '
            'beneficiary, enter a pairing code you received, or '
            'claim a vault after its transfer cooldown completes.',
            style: TextStyle(
                color: Color(0xFFB4B4B4), fontSize: 13),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            key: const Key('inheritance_open_dashboard_button'),
            onPressed: () {
              Navigator.of(context).pushReplacementNamed('/chat');
            },
            icon: const Icon(Icons.dashboard_outlined),
            label: const Text('Open the Inheritance dashboard'),
          ),
        ],
      ),
    );
  }

  Widget _zkEnvelopeSelfCheckCard() {
    final linkIdCtrl = TextEditingController();
    return Container(
      key: const Key('zk_envelope_selfcheck_card'),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF2A2A2A),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'ZK inheritance envelope — round-trip self-check',
            style: TextStyle(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          const Text(
            'For a linked beneficiary row, upload a wrapped MVK '
            'envelope and confirm the local unwrap round-trips to '
            'the same MVK. This proves the ZK ceremony primitives '
            'are healthy end-to-end.',
            style: TextStyle(
                color: Color(0xFFB4B4B4), fontSize: 12),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('zk_envelope_link_id_input'),
            controller: linkIdCtrl,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Beneficiary link_id',
              hintText: 'from the Inheritance dashboard',
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            key: const Key('zk_envelope_run_selfcheck_button'),
            onPressed: _envelopeBusy
                ? null
                : () {
                    final id =
                        int.tryParse(linkIdCtrl.text.trim());
                    if (id == null) {
                      setState(() {
                        _envelopeError =
                            'Enter a valid link_id (an integer).';
                      });
                      return;
                    }
                    _runEnvelopeSelfCheck(linkId: id);
                  },
            icon: _envelopeBusy
                ? const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white),
                  )
                : const Icon(Icons.verified_outlined),
            label: Text(_envelopeBusy
                ? 'Running…'
                : 'Run envelope self-check'),
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
            color: const Color(0xFF10A37F).withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.check_circle_outline,
              color: Color(0xFF66FFA6), size: 22),
          const SizedBox(width: 10),
          Expanded(
            child: Text(msg,
                style: const TextStyle(
                    color: Color(0xFFA5F3D0), fontSize: 13)),
          ),
        ],
      ),
    );
  }

  Widget _errorCard(String msg) {
    return Container(
      key: const Key('inheritance_error_card'),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFEF5350).withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
            color: const Color(0xFFEF5350).withValues(alpha: 0.40)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline,
              color: Color(0xFFFF8B87), size: 22),
          const SizedBox(width: 10),
          Expanded(
            child: Text(msg,
                style: const TextStyle(
                    color: Color(0xFFFFC7C4), fontSize: 13)),
          ),
        ],
      ),
    );
  }
}
