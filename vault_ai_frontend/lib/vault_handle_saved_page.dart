// Post-signup / post-adoption "save your Vault ID" screen.
//
// Shown once, after ZK signup or legacy → ZK adoption. The user is
// required to copy or acknowledge the Vault Handle before the flow
// continues. If they lose this value AND their PIN, VaultAI cannot
// recover their vault.
//
// This is a plain widget with no crypto, no network. It just shows
// the handle and gates progression on an explicit checkbox.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class VaultHandleSavedPage extends StatefulWidget {
  final String vaultHandle;
  final String continueRoute;
  final bool wasAdoption;

  const VaultHandleSavedPage({
    super.key,
    required this.vaultHandle,
    this.continueRoute = '/chat',
    this.wasAdoption = false,
  });

  @override
  State<VaultHandleSavedPage> createState() => _VaultHandleSavedPageState();
}

class _VaultHandleSavedPageState extends State<VaultHandleSavedPage> {
  bool _acknowledged = false;
  bool _copied = false;

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: widget.vaultHandle));
    if (!mounted) return;
    setState(() => _copied = true);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Vault ID copied to clipboard')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.of(context).size.width;
    return PopScope(
      canPop: false,
      child: Scaffold(
        body: Center(
          child: SizedBox(
            width: w < 480 ? w - 24 : 460,
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(vertical: 22),
              child: Container(
                padding: const EdgeInsets.all(22),
                decoration: BoxDecoration(
                  color: const Color(0xFF2F2F2F),
                  borderRadius: BorderRadius.circular(22),
                  border: Border.all(color: Colors.white10),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      widget.wasAdoption
                          ? 'Your new Vault ID'
                          : 'Save your Vault ID',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 22,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      widget.wasAdoption
                          ? 'VaultAI upgraded your account to a private '
                            'Vault ID for future logins. Save it somewhere '
                            'safe. VaultAI cannot recover your vault if you '
                            'lose both your Vault ID and your PIN.'
                          : 'This is your Vault ID. Use it together with '
                            'your PIN to log in from any device. VaultAI '
                            'cannot recover your vault if you lose both.',
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Color(0xFFB4B4B4)),
                    ),
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: const Color(0xFF10A37F).withValues(alpha: 0.10),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: const Color(0xFF10A37F).withValues(alpha: 0.55),
                        ),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          SelectableText(
                            widget.vaultHandle,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 18,
                              letterSpacing: 1.4,
                              fontWeight: FontWeight.w700,
                              color: Colors.white,
                            ),
                          ),
                          const SizedBox(height: 10),
                          OutlinedButton.icon(
                            onPressed: _copy,
                            icon: Icon(
                              _copied ? Icons.check : Icons.copy,
                              size: 18,
                            ),
                            label: Text(_copied ? 'Copied' : 'Copy Vault ID'),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    InkWell(
                      onTap: () => setState(() => _acknowledged = !_acknowledged),
                      borderRadius: BorderRadius.circular(8),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Checkbox(
                              value: _acknowledged,
                              onChanged: (v) =>
                                  setState(() => _acknowledged = v ?? false),
                            ),
                            const Expanded(
                              child: Padding(
                                padding: EdgeInsets.only(top: 12),
                                child: Text(
                                  'I have saved my Vault ID somewhere safe.',
                                  style: TextStyle(
                                    color: Color(0xFFE0E0E0),
                                    fontSize: 13,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: _acknowledged
                            ? () => Navigator.of(context)
                                .pushReplacementNamed(widget.continueRoute)
                            : null,
                        child: const Text('Continue'),
                      ),
                    ),
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
