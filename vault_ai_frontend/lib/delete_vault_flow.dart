
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api_client.dart';
import 'l10n/app_localizations.dart';




const String kDeleteVaultConfirmationPhrase = 'DELETE MY VAULT';


class DeleteVaultFlow extends StatefulWidget {
  final VaultAIClient client;
  final String authToken;
  final VoidCallback? onDeleted;

  const DeleteVaultFlow({
    super.key,
    required this.client,
    required this.authToken,
    this.onDeleted,
  });

  @override
  State<DeleteVaultFlow> createState() => _DeleteVaultFlowState();
}


class _DeleteVaultFlowState extends State<DeleteVaultFlow> {
  final TextEditingController _phraseCtrl = TextEditingController();
  final TextEditingController _pinCtrl = TextEditingController();

  bool _submitting = false;
  String? _errorText;

  @override
  void dispose() {
    _phraseCtrl.dispose();
    _pinCtrl.dispose();
    super.dispose();
  }

  bool get _phraseMatches =>
      _phraseCtrl.text == kDeleteVaultConfirmationPhrase;

  bool get _pinEntered => _pinCtrl.text.isNotEmpty;

  bool get _canDelete => _phraseMatches && _pinEntered && !_submitting;

  Future<void> _performDelete(AppLocalizations l) async {
    setState(() {
      _submitting = true;
      _errorText = null;
    });
    try {
      final req = await widget.client.requestDeleteVault(
        authToken: widget.authToken,
      );
      final token = (req['request_token'] ?? '').toString();
      if (token.isEmpty) {
        throw Exception('Missing delete request token');
      }
      await widget.client.confirmDeleteVault(
        authToken: widget.authToken,
        requestToken: token,
        pin: _pinCtrl.text,
        confirmationPhrase: _phraseCtrl.text,
      );
      if (!mounted) return;
      widget.onDeleted?.call();
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _errorText = _humaniseError(l, e);
      });
    }
  }

  String _humaniseError(AppLocalizations l, Object err) {
    final s = err.toString();
    if (s.contains('invalid_pin')) return l.deleteVaultErrorInvalidPin;
    if (s.contains('invalid_confirmation_phrase')) {
      return l.deleteVaultErrorInvalidPhrase;
    }
    if (s.contains('invalid_or_expired_request_token')) {
      return l.deleteVaultErrorExpired;
    }
    if (s.contains('device_not_trusted') || s.contains('trusted')) {
      return l.deleteVaultErrorNotTrusted;
    }
    return l.deleteVaultErrorGeneric;
  }

  @override
  Widget build(BuildContext context) {
    const dangerColor = Color(0xFFE0605C);
    final l = AppLocalizations.of(context);
    return AlertDialog(
      key: const Key('delete_vault_dialog'),
      backgroundColor: const Color(0xFF2A2A2A),
      title: Row(
        children: [
          const Icon(Icons.warning_amber_rounded,
              color: dangerColor, size: 26),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              l.deleteVaultTitle,
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
          ),
        ],
      ),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                l.deleteVaultBody,
                style: const TextStyle(
                  color: Color(0xFFD5D5D5), height: 1.5,
                ),
              ),
              const SizedBox(height: 14),
              Container(
                key: const Key('delete_vault_crypto_warning'),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: dangerColor.withValues(alpha: 0.08),
                  border: Border.all(
                    color: dangerColor.withValues(alpha: 0.30),
                  ),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  l.deleteVaultCryptoWarning,
                  style: const TextStyle(
                    color: dangerColor,
                    height: 1.45,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text(
                l.deleteVaultPhraseInstruction,
                style: const TextStyle(
                  color: Color(0xFFB4B4B4),
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 6),
              TextField(
                key: const Key('delete_vault_phrase_field'),
                controller: _phraseCtrl,
                enabled: !_submitting,
                onChanged: (_) => setState(() {}),
                autofocus: true,
                textDirection: TextDirection.ltr,
                decoration: InputDecoration(
                  hintText: kDeleteVaultConfirmationPhrase,
                  border: const OutlineInputBorder(),
                  errorText: _phraseCtrl.text.isEmpty ||
                          _phraseMatches
                      ? null
                      : l.deleteVaultPhraseMustMatch,
                ),
              ),
              const SizedBox(height: 14),
              Text(
                l.deleteVaultPinInstruction,
                style: const TextStyle(
                  color: Color(0xFFB4B4B4),
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 6),
              TextField(
                key: const Key('delete_vault_pin_field'),
                controller: _pinCtrl,
                enabled: !_submitting,
                obscureText: true,
                keyboardType: TextInputType.number,
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                ],
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(
                  hintText: l.deleteVaultPinHint,
                  border: const OutlineInputBorder(),
                ),
              ),
              if (_errorText != null) ...[
                const SizedBox(height: 10),
                Text(
                  _errorText!,
                  key: const Key('delete_vault_error_text'),
                  style: const TextStyle(
                    color: dangerColor,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key('delete_vault_cancel_button'),
          onPressed: _submitting
              ? null
              : () => Navigator.of(context).pop(false),
          child: Text(l.commonCancel),
        ),
        ElevatedButton(
          key: const Key('delete_vault_confirm_button'),
          onPressed: _canDelete ? () => _performDelete(l) : null,
          style: ElevatedButton.styleFrom(
            backgroundColor: dangerColor,
            foregroundColor: Colors.white,
          ),
          child: _submitting
              ? const SizedBox(
                  width: 16, height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor:
                        AlwaysStoppedAnimation<Color>(Colors.white),
                  ),
                )
              : Text(l.deleteVaultConfirmButton),
        ),
      ],
    );
  }
}


Future<bool> showDeleteVaultDialog(
  BuildContext context, {
  required VaultAIClient client,
  required String authToken,
  VoidCallback? onDeleted,
}) async {
  final result = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (_) => DeleteVaultFlow(
      client: client,
      authToken: authToken,
      onDeleted: onDeleted,
    ),
  );
  return result ?? false;
}
