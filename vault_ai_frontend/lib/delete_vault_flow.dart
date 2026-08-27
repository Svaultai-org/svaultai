import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, TargetPlatform;
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'l10n/app_localizations.dart';

const String kDeleteVaultConfirmationPhrase = 'DELETE MY VAULT';
const String kAppleSubscriptionsManagementUrl =
    'https://apps.apple.com/account/subscriptions';

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
  bool _checkingSubscription = false;
  bool _deletionAllowed = true;
  String _appleSubscriptionState = 'unknown';
  String? _errorText;

  @override
  void initState() {
    super.initState();
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      _deletionAllowed = false;
      _refreshDeletionStatus();
    }
  }

  @override
  void dispose() {
    _phraseCtrl.dispose();
    _pinCtrl.dispose();
    super.dispose();
  }

  bool get _phraseMatches => _phraseCtrl.text == kDeleteVaultConfirmationPhrase;

  bool get _pinEntered => _pinCtrl.text.isNotEmpty;

  bool get _canDelete => _phraseMatches && _pinEntered && !_submitting &&
      !_checkingSubscription && _deletionAllowed;

  Future<void> _refreshDeletionStatus() async {
    if (!mounted) return;
    setState(() {
      _checkingSubscription = true;
      _errorText = null;
    });
    try {
      final status = await widget.client.getDeleteStatus(
        authToken: widget.authToken,
      );
      if (!mounted) return;
      setState(() {
        _appleSubscriptionState =
            (status['apple_subscription_state'] ?? 'unknown').toString();
        _deletionAllowed = status['deletion_allowed'] == true;
        _checkingSubscription = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _appleSubscriptionState = 'temporarily_unavailable';
        _deletionAllowed = false;
        _checkingSubscription = false;
      });
    }
  }

  Future<void> _openAppleSubscriptions() async {
    await launchUrl(
      Uri.parse(kAppleSubscriptionsManagementUrl),
      mode: LaunchMode.externalApplication,
    );
  }

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
    if (s.contains(
        'active_apple_subscription_must_be_canceled_before_final_deletion')) {
      _appleSubscriptionState = 'active_auto_renewing';
      _deletionAllowed = false;
      return 'Cancel your active App Store subscription before deleting your '
          'final SVaultAI vault. After cancellation, tap Check again.';
    }
    if (s.contains('apple_subscription_status_temporarily_unavailable')) {
      _appleSubscriptionState = 'temporarily_unavailable';
      _deletionAllowed = false;
      return 'Apple subscription status is temporarily unavailable. Your '
          'vault was not deleted. Please tap Check again.';
    }
    return l.deleteVaultErrorGeneric;
  }

  @override
  Widget build(BuildContext context) {
    const dangerColor = Color(0xFFE0605C);
    final l = AppLocalizations.of(context);
    final mq = MediaQuery.of(context);
    // Subtract AlertDialog's own inset (24 on each side by default) so the
    // content column never exceeds the visible viewport at 320dp.
    final double contentWidth = (mq.size.width - 48).clamp(240.0, 480.0);
    return AlertDialog(
      key: const Key('delete_vault_dialog'),
      backgroundColor: const Color(0xFF2A2A2A),
      insetPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
      title: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, color: dangerColor, size: 26),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              l.deleteVaultTitle,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
          ),
        ],
      ),
      content: SizedBox(
        width: contentWidth,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                l.deleteVaultBody,
                style: const TextStyle(
                  color: Color(0xFFD5D5D5),
                  height: 1.5,
                ),
              ),
              if (defaultTargetPlatform == TargetPlatform.iOS) ...[
                const SizedBox(height: 14),
                const Text(
                  'Your App Store subscription is managed separately by '
                  'Apple. Deleting this vault does not cancel it. Manage or '
                  'cancel it in Apple Subscriptions.',
                  key: Key('delete_vault_apple_subscription_disclosure'),
                  style: TextStyle(
                    color: Color(0xFFD5D5D5),
                    height: 1.45,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    key: const Key('delete_vault_manage_apple_subscription'),
                    onPressed: _submitting ? null : _openAppleSubscriptions,
                    icon: const Icon(Icons.open_in_new, size: 18),
                    label: const Text('Manage Apple subscription'),
                  ),
                ),
                if (_checkingSubscription)
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: LinearProgressIndicator(
                      key: Key('delete_vault_apple_status_loading'),
                    ),
                  ),
                if (!_checkingSubscription &&
                    _appleSubscriptionState == 'active_auto_renewing')
                  const Text(
                    'Final vault deletion is blocked while this verified App '
                    'Store subscription is set to renew. Cancel it with Apple, '
                    'then check again. You can delete immediately once Apple '
                    'confirms auto-renewal is off.',
                    key: Key('delete_vault_apple_active_block'),
                    style: TextStyle(color: dangerColor, height: 1.4),
                  ),
                if (!_checkingSubscription &&
                    _appleSubscriptionState == 'temporarily_unavailable')
                  const Text(
                    'We cannot verify your Apple subscription status right '
                    'now. Your vault will not be deleted until verification '
                    'succeeds.',
                    key: Key('delete_vault_apple_status_unavailable'),
                    style: TextStyle(color: dangerColor, height: 1.4),
                  ),
                if (!_checkingSubscription && !_deletionAllowed)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton.icon(
                      key: const Key('delete_vault_check_again'),
                      onPressed: _submitting ? null : _refreshDeletionStatus,
                      icon: const Icon(Icons.refresh, size: 18),
                      label: const Text('Check again'),
                    ),
                  ),
              ],
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
                  errorText: _phraseCtrl.text.isEmpty || _phraseMatches
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
          onPressed:
              _submitting ? null : () => Navigator.of(context).pop(false),
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
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
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
