

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/crypto_wallet_features.dart';
import '../services/solana_transaction.dart';
import '../services/solana_wallet.dart';
import 'crypto_wallet_engine_design.dart';
import 'crypto_wallet_engine_send_layout.dart';


const String kSolanaSendPanelTitle = 'Send SOL';
const String kSolanaSendReviewHeading = 'Review Solana send';
const String kSolanaSendConfirmationWarning =
    'Review carefully. Solana transactions cannot be reversed.';
const String kSolanaSendNotEnabledMessage =
    'Solana sending is not enabled yet.';
const String kSolanaSendPausedMessage =
    'Solana sending is temporarily paused.';
const String kSolanaSendPinDialogTitle =
    'Enter your PIN to sign locally';
const String kSolanaSendPinDialogBody =
    'Your Solana secret is decrypted on this device only. VaultAI '
    'never sees the plaintext key.';
const String kSolanaSendSubmittedHeading = 'Broadcast submitted';
const String kSolanaSendSubmittedBody =
    'Your Solana transaction was submitted. History is not yet '
    'connected — check the signature below.';
const String kSolanaSendDestinationLabel = 'Destination address';
const String kSolanaSendAmountLabel = 'Amount (SOL)';
const String kSolanaSendReviewButtonLabel = 'Review';
const String kSolanaSendConfirmButtonLabel = 'Confirm and enter PIN';
const String kSolanaSendBroadcastFailedCopy =
    'Could not submit transaction.';
const String kSolanaSendInvalidDestinationCopy =
    'Destination must be a valid Solana base58 address.';
const String kSolanaSendInvalidAmountCopy =
    'Amount must be a decimal like 0.1 or 5 (up to 9 decimal places).';
const String kSolanaSendSelfSendCopy =
    'Destination address matches the from address. Refusing to '
    'draft a self-send.';


const String kSolanaSendPanelKey = 'solana_send_panel';
const String kSolanaSendDestinationInputKey =
    'solana_send_panel_destination_input';
const String kSolanaSendAmountInputKey =
    'solana_send_panel_amount_input';
const String kSolanaSendReviewButtonKey =
    'solana_send_panel_review_btn';
const String kSolanaSendReviewCardKey =
    'solana_send_panel_review_card';
const String kSolanaSendConfirmButtonKey =
    'solana_send_panel_confirm_btn';
const String kSolanaSendSubmittedCardKey =
    'solana_send_panel_submitted_card';
const String kSolanaSendPausedBannerKey =
    'solana_send_panel_paused_banner';
const String kSolanaSendDisabledBannerKey =
    'solana_send_panel_disabled_banner';
const String kSolanaSendWarningKey =
    'solana_send_panel_warning';
const String kSolanaSendPinInputKey =
    'solana_send_panel_pin_input';
const String kSolanaSendPinConfirmBtnKey =
    'solana_send_panel_pin_confirm_btn';


enum _SolanaSendStage { input, review, submitting, submitted }


const String kSolanaSendFeeEstimatedLabel = 'Estimated network fee';
const String kSolanaSendFeeRealLabel = 'Network fee';
const String kSolanaSendFeeUnavailableLabel =
    'Network fee estimate unavailable';
const String kSolanaSendStatusPollingCopy =
    'Checking Solana status…';
const String kSolanaSendStatusPendingCopy =
    'Status: pending';
const String kSolanaSendStatusConfirmedCopy =
    'Status: confirmed';
const String kSolanaSendStatusFailedCopy =
    'Status: failed';
const String kSolanaSendStatusUnavailableCopy =
    'Status temporarily unavailable';


String solanaSendFeeLabelFor(String? feeSource) {
  switch (feeSource) {
    case 'rpc_getFeeForMessage':
      return kSolanaSendFeeRealLabel;
    case 'default_lamports':
      return kSolanaSendFeeEstimatedLabel;
  }
  return kSolanaSendFeeEstimatedLabel;
}


String solanaSendStatusCopyFor(String? statusCode) {
  switch (statusCode) {
    case 'confirmed': return kSolanaSendStatusConfirmedCopy;
    case 'failed':    return kSolanaSendStatusFailedCopy;
    case 'pending':   return kSolanaSendStatusPendingCopy;
    case 'unavailable':
      return kSolanaSendStatusUnavailableCopy;
  }
  return kSolanaSendStatusPollingCopy;
}


class CryptoWalletEngineSolanaSendPanel extends StatefulWidget {
  final String authToken;
  final String fromAddress;
  final VaultAIClient client;
  final Future<String> Function(String ciphertext) decryptForVault;
  final bool Function() isVaultKeyAvailable;
  final Future<bool> Function(String pin)? verifyPin;
  final CryptoWalletFeatures? features;
  final String? prefilledDestination;
  final String? prefilledAmount;

  final String Function()? idempotencyKeyGenerator;

  const CryptoWalletEngineSolanaSendPanel({
    super.key,
    required this.authToken,
    required this.fromAddress,
    required this.client,
    required this.decryptForVault,
    required this.isVaultKeyAvailable,
    this.verifyPin,
    this.features,
    this.prefilledDestination,
    this.prefilledAmount,
    this.idempotencyKeyGenerator,
  });

  @override
  State<CryptoWalletEngineSolanaSendPanel> createState() =>
      _CryptoWalletEngineSolanaSendPanelState();
}


class _CryptoWalletEngineSolanaSendPanelState
    extends State<CryptoWalletEngineSolanaSendPanel> {
  final TextEditingController _destinationController =
      TextEditingController();
  final TextEditingController _amountController =
      TextEditingController();

  // 2026-07-13 mobile-keyboard fix: shared scroll controller +
  // FocusNodes so tapping / Next-key-hopping to a field slides it
  // above the mobile Safari keyboard.
  final ScrollController _formScrollCtrl = ScrollController();
  final FocusNode _destFocus = FocusNode(debugLabel: 'sol_send_dest');
  final FocusNode _amountFocus = FocusNode(debugLabel: 'sol_send_amount');

  _SolanaSendStage _stage = _SolanaSendStage.input;
  String? _error;
  Map<String, dynamic>? _draft;
  Map<String, dynamic>? _submitted;
  bool _broadcastInFlight = false;
  String? _idempotencyKey;
  String? _statusCode;
  int _statusPollCount = 0;
  bool _statusPollActive = false;
  Timer? _statusTimer;

  @override
  void initState() {
    super.initState();
    if (widget.prefilledDestination != null) {
      _destinationController.text = widget.prefilledDestination!;
    }
    if (widget.prefilledAmount != null) {
      _amountController.text = widget.prefilledAmount!;
    }
    _destFocus.addListener(_maybeScrollFocusedFieldIntoView);
    _amountFocus.addListener(_maybeScrollFocusedFieldIntoView);
  }

  @override
  void dispose() {
    _statusPollActive = false;
    _statusTimer?.cancel();
    _statusTimer = null;
    _destFocus.removeListener(_maybeScrollFocusedFieldIntoView);
    _amountFocus.removeListener(_maybeScrollFocusedFieldIntoView);
    _destFocus.dispose();
    _amountFocus.dispose();
    _formScrollCtrl.dispose();
    _destinationController.dispose();
    _amountController.dispose();
    super.dispose();
  }

  void _maybeScrollFocusedFieldIntoView() {
    if (!mounted) return;
    final BuildContext? focusedContext = _destFocus.hasFocus
        ? _destFocus.context
        : (_amountFocus.hasFocus ? _amountFocus.context : null);
    if (focusedContext == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (!focusedContext.mounted) return;
      Scrollable.ensureVisible(
        focusedContext,
        alignment: 0.25,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
      );
    });
  }

  bool get _sendEnabled =>
      widget.features?.solanaSendEnabled ?? false;

  bool get _sendPaused =>
      widget.features?.solanaSendPaused ?? false;

  Future<void> _onReview() async {
    setState(() {
      _error = null;
    });
    final destination = _destinationController.text.trim();
    if (!isValidSolanaAddress(destination)) {
      setState(() {
        _error = kSolanaSendInvalidDestinationCopy;
      });
      return;
    }
    if (destination == widget.fromAddress.trim()) {
      setState(() {
        _error = kSolanaSendSelfSendCopy;
      });
      return;
    }
    try {
      parseSolAmountToLamports(_amountController.text);
    } catch (_) {
      setState(() {
        _error = kSolanaSendInvalidAmountCopy;
      });
      return;
    }
    try {
      final draft = await widget.client.createCryptoWalletSendDraftNetwork(
        network: kSolanaNetworkId,
        asset: kSolanaAssetTicker,
        authToken: widget.authToken,
        fromAddress: widget.fromAddress,
        destinationAddress: destination,
        amountSol: _amountController.text.trim(),
      );
      final status = (draft['status'] ?? '').toString();
      if (status != 'draft_ready') {
        setState(() {
          _error = (draft['message'] ??
              'Solana draft not ready.').toString();
        });
        return;
      }
      setState(() {
        _draft = draft;
        _stage = _SolanaSendStage.review;
      });
    } catch (e) {
      setState(() {
        _error = 'Draft failed: $e';
      });
    }
  }

  Future<void> _onConfirmAndSign() async {
    if (_broadcastInFlight) return;
    if (!widget.isVaultKeyAvailable()) {
      setState(() {
        _error = 'Unlock your vault first.';
      });
      return;
    }
    if (widget.verifyPin != null) {
      final ok = await _promptPin();
      if (!ok) return;
    }
    _broadcastInFlight = true;
    setState(() {
      _stage = _SolanaSendStage.submitting;
      _error = null;
    });


    _idempotencyKey ??= (widget.idempotencyKeyGenerator != null)
        ? widget.idempotencyKeyGenerator!()
        : _defaultIdempotencyKey();

    Map<String, dynamic>? secretResp;
    Uint8List? plaintextSeed;
    Uint8List? plaintextSecret64;
    try {
      secretResp = await widget.client
          .getCryptoWalletEncryptedSecretNetwork(
        network: kSolanaNetworkId,
        asset: kSolanaAssetTicker,
        authToken: widget.authToken,
      );
      final status = (secretResp['wallet_engine'] ?? '').toString();
      if (status != 'encrypted_secret_ready') {
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.input;
          _error = 'Wallet secret not available for signing.';
        });
        return;
      }
      final ct = (secretResp['encryptedWalletSecret'] ?? '')
          .toString();
      if (ct.isEmpty) {
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.input;
          _error = 'Missing ciphertext.';
        });
        return;
      }
      final decrypted = await widget.decryptForVault(ct);
      final parsed = jsonDecode(decrypted);
      if (parsed is! Map<String, dynamic>) {
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.input;
          _error = 'Malformed Solana secret blob.';
        });
        return;
      }
      final secretB58 = (parsed['secretKeyBase58'] ?? '').toString();
      final decoded = base58Decode(secretB58);
      if (decoded == null || decoded.length != 64) {
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.input;
          _error = 'Malformed Solana secret bytes.';
        });
        return;
      }
      plaintextSecret64 = decoded;
      plaintextSeed = Uint8List(32);
      plaintextSeed.setRange(0, 32, plaintextSecret64.sublist(0, 32));

      final draft = _draft!;
      final lamports = int.parse(
        (draft['lamports'] ?? '0').toString(),
      );
      final signed = await signSolanaTransfer(
        fromAddressBase58:        widget.fromAddress,
        destinationAddressBase58: (draft['destinationAddress'] ?? '')
            .toString(),
        lamports:                  lamports,
        recentBlockhashBase58:      (draft['recentBlockhash'] ?? '')
            .toString(),
        ed25519Seed32:             plaintextSeed,
      );

      wipeSecretKey(plaintextSecret64);
      wipeSecretKey(plaintextSeed);
      plaintextSecret64 = null;
      plaintextSeed = null;

      final broadcastResp = await widget.client
          .broadcastCryptoWalletSignedTransactionNetwork(
        network:           kSolanaNetworkId,
        asset:             kSolanaAssetTicker,
        authToken:         widget.authToken,
        signedTransaction: signed.wireTransaction.base64,
        idempotencyKey:    _idempotencyKey,
      );
      final broadcastStatus =
          (broadcastResp['status'] ?? '').toString();
      if (broadcastStatus != 'submitted') {
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.review;
          _error = (broadcastResp['message']
              ?? kSolanaSendBroadcastFailedCopy).toString();
        });
        return;
      }
      setState(() {
        _broadcastInFlight = false;
        _stage = _SolanaSendStage.submitted;
        _submitted = broadcastResp;
      });
      _startStatusPolling();
    } catch (e) {
      if (plaintextSecret64 != null) {
        wipeSecretKey(plaintextSecret64);
      }
      if (plaintextSeed != null) {
        wipeSecretKey(plaintextSeed);
      }
      setState(() {
        _broadcastInFlight = false;
        _stage = _SolanaSendStage.review;
        _error = 'Sign/broadcast failed: $e';
      });
    }
  }

  String _defaultIdempotencyKey() {
    final now = DateTime.now().microsecondsSinceEpoch;
    final rand = now.toRadixString(36);
    return 'sol-${widget.fromAddress.substring(0, 8)}-$rand';
  }

  void _startStatusPolling() {
    if (_statusPollActive) return;
    final sig = (_submitted?['signature'] ?? '').toString();
    if (sig.isEmpty) return;
    _statusPollActive = true;
    _statusPollCount = 0;
    _statusCode = 'pending';
    if (mounted) setState(() {});
    _scheduleStatusPoll(sig);
  }

  void _scheduleStatusPoll(String sig) {
    if (!mounted || !_statusPollActive) return;
    if (_statusPollCount >= 12) {
      _statusPollActive = false;
      return;
    }
    _statusTimer?.cancel();
    _statusTimer = Timer(const Duration(seconds: 2), () async {
      if (!mounted || !_statusPollActive) return;
      _statusPollCount++;
      try {
        final resp = await widget.client
            .getCryptoWalletTransactionStatusNetwork(
          network:  kSolanaNetworkId,
          asset:    kSolanaAssetTicker,
          txHash:   sig,
          authToken: widget.authToken,
        );
        if (!mounted) return;
        final st = (resp['transactionStatus'] ?? '').toString();
        setState(() {
          _statusCode = st;
        });
        if (st == 'confirmed' || st == 'failed') {
          _statusPollActive = false;
          return;
        }
      } catch (_) {
        if (!mounted) return;
        setState(() {
          _statusCode = 'unavailable';
        });
      }
      _scheduleStatusPoll(sig);
    });
  }

  Future<bool> _promptPin() async {
    final controller = TextEditingController();
    var pinOk = false;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        key: const Key('solana_send_pin_dialog'),
        title: const Text(kSolanaSendPinDialogTitle),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(kSolanaSendPinDialogBody),
            const SizedBox(height: 12),
            TextField(
              key: const Key(kSolanaSendPinInputKey),
              controller: controller,
              obscureText: true,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'PIN',
              ),
              keyboardType: TextInputType.number,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: Text(AppLocalizations.of(ctx).commonCancel),
          ),
          ElevatedButton(
            key: const Key(kSolanaSendPinConfirmBtnKey),
            onPressed: () async {
              final entered = controller.text.trim();
              final ok = await widget.verifyPin!(entered);
              if (ok) {
                pinOk = true;
                if (ctx.mounted) Navigator.of(ctx).pop();
              } else {
                if (ctx.mounted) {
                  ScaffoldMessenger.of(ctx).showSnackBar(
                    const SnackBar(
                      content: Text(
                        'Wrong PIN — cannot sign transaction.',
                      ),
                    ),
                  );
                }
              }
            },
            child: Text(AppLocalizations.of(ctx).commonConfirm),
          ),
        ],
      ),
    );
    controller.clear();
    return pinOk;
  }

  @override
  Widget build(BuildContext context) {
    // 2026-07-13: Send SOL sheets adopt the shared compact layout —
    // network chip in the header row, sticky Review button pinned
    // above the keyboard, no duplicated `Send SOL` heading (the sheet
    // chrome already shows the sheet title).
    return WalletDarkPanelScope(
      child: KeyedSubtree(
        key: const Key(kSolanaSendPanelKey),
        child: _buildLayoutForStage(),
      ),
    );
  }

  Widget _buildLayoutForStage() {
    final header = walletSendNetworkChip(
      key: const Key('solana_send_panel_network_chip'),
      label: 'Solana Mainnet',
      isMainnet: true,
    );
    if (!_sendEnabled) {
      return WalletSendScaffold(
        sheetKey: 'solana_send_panel',
        header: header,
        body: _buildDisabledBanner(),
      );
    }
    if (_sendPaused) {
      return WalletSendScaffold(
        sheetKey: 'solana_send_panel',
        header: header,
        body: _buildPausedBanner(),
      );
    }
    switch (_stage) {
      case _SolanaSendStage.input:
        return WalletSendScaffold(
          sheetKey: 'solana_send_panel',
          header: header,
          body: _buildInputBody(),
          footer: _buildInputFooter(),
          scrollController: _formScrollCtrl,
        );
      case _SolanaSendStage.review:
        return WalletSendScaffold(
          sheetKey: 'solana_send_panel',
          header: header,
          body: _buildReviewBody(),
          footer: _buildReviewFooter(),
        );
      case _SolanaSendStage.submitting:
        return WalletSendScaffold(
          sheetKey: 'solana_send_panel',
          header: header,
          body: _buildSubmittingStage(),
        );
      case _SolanaSendStage.submitted:
        return WalletSendScaffold(
          sheetKey: 'solana_send_panel',
          header: header,
          body: _buildSubmittedStage(),
        );
    }
  }

  Widget _buildDisabledBanner() {
    return Container(
      key: const Key(kSolanaSendDisabledBannerKey),
      padding: const EdgeInsets.all(14),
      decoration: walletWarningPanel(),
      child: const Row(
        children: [
          Icon(Icons.hourglass_bottom_rounded,
              size: 18, color: kWalletAccentWarning),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              kSolanaSendNotEnabledMessage,
              style: TextStyle(
                color: kWalletAccentWarning,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPausedBanner() {
    return Container(
      key: const Key(kSolanaSendPausedBannerKey),
      padding: const EdgeInsets.all(14),
      decoration: walletWarningPanel(),
      child: const Row(
        children: [
          Icon(Icons.pause_circle_outline_rounded,
              size: 18, color: kWalletAccentWarning),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              kSolanaSendPausedMessage,
              style: TextStyle(
                color: kWalletAccentWarning,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInputBody() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          key: const Key(kSolanaSendDestinationInputKey),
          controller: _destinationController,
          focusNode: _destFocus,
          textInputAction: TextInputAction.next,
          autocorrect: false,
          enableSuggestions: false,
          onSubmitted: (_) => _amountFocus.requestFocus(),
          decoration: const InputDecoration(
            labelText: kSolanaSendDestinationLabel,
            isDense: true,
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key(kSolanaSendAmountInputKey),
          controller: _amountController,
          focusNode: _amountFocus,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _amountFocus.unfocus(),
          decoration: const InputDecoration(
            labelText: kSolanaSendAmountLabel,
            isDense: true,
          ),
          keyboardType: const TextInputType.numberWithOptions(
            decimal: true,
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 10),
          WalletSendWarning(
            text: _error!,
            tone: WalletSendWarningTone.critical,
          ),
        ],
      ],
    );
  }

  Widget _buildInputFooter() {
    return ElevatedButton(
      key: const Key(kSolanaSendReviewButtonKey),
      onPressed: _onReview,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: const Text(kSolanaSendReviewButtonLabel),
    );
  }

  Widget _buildReviewBody() {
    final draft = _draft!;
    return Column(
      key: const Key(kSolanaSendReviewCardKey),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        walletSendSectionHeading(kSolanaSendReviewHeading),
        WalletSendKvRow(label: 'Network', value: 'Solana'),
        WalletSendKvRow(
          label: 'From', value: widget.fromAddress, mono: true,
        ),
        WalletSendKvRow(
          label: 'Destination',
          value: (draft['destinationAddress'] ?? '').toString(),
          mono: true,
        ),
        WalletSendKvRow(
          label: 'Amount', value: '${draft['amountSol']} SOL',
        ),
        if (draft['feeSol'] != null)
          WalletSendKvRow(
            label: solanaSendFeeLabelFor(
              (draft['feeSource'] as String?),
            ),
            value: '${draft['feeSol']} SOL',
          ),
        const SizedBox(height: 10),
        const WalletSendWarning(
          key: Key(kSolanaSendWarningKey),
          text: kSolanaSendConfirmationWarning,
        ),
        if (_error != null) ...[
          const SizedBox(height: 8),
          WalletSendWarning(
            text: _error!,
            tone: WalletSendWarningTone.critical,
          ),
        ],
      ],
    );
  }

  Widget _buildReviewFooter() {
    return ElevatedButton(
      key: const Key(kSolanaSendConfirmButtonKey),
      onPressed:
          _broadcastInFlight ? null : _onConfirmAndSign,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: Text(
        _broadcastInFlight
            ? 'Submitting…'
            : kSolanaSendConfirmButtonLabel,
      ),
    );
  }

  Widget _buildSubmittingStage() {
    return const Center(
      key: Key('solana_send_panel_submitting'),
      child: Padding(
        padding: EdgeInsets.all(24),
        child: CircularProgressIndicator(),
      ),
    );
  }

  Widget _buildSubmittedStage() {
    final resp = _submitted!;
    final signature = (resp['signature'] ?? '').toString();
    return Container(
      key: const Key(kSolanaSendSubmittedCardKey),
      padding: const EdgeInsets.all(14),
      decoration: walletSuccessPanel(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kSolanaSendSubmittedHeading,
            style: TextStyle(
              color: kWalletAccentSuccess,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            kSolanaSendSubmittedBody,
            style: TextStyle(
              color: kWalletAccentSuccess,
              fontSize: 13,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            solanaSendStatusCopyFor(_statusCode),
            key: const Key('solana_send_panel_status_text'),
            style: TextStyle(
              color: _statusCode == 'failed'
                  ? kWalletAccentDanger
                  : (_statusCode == 'confirmed'
                      ? kWalletAccentSuccess
                      : kWalletAccentWarning),
              fontSize: 13,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 10),
          SelectableText(
            signature,
            key: const Key('solana_send_panel_signature_text'),
            style: kWalletMonoStyle,
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const Key('solana_send_panel_copy_sig_btn'),
            onPressed: () async {
              final copiedLabel =
                  AppLocalizations.of(context).cryptoSignatureCopied;
              await Clipboard.setData(
                ClipboardData(text: signature),
              );
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(copiedLabel)),
                );
              }
            },
            icon: const Icon(Icons.copy_rounded, size: 16),
            label: Text(
              AppLocalizations.of(context).cryptoCopySignature,
            ),
            style: walletGhostButtonStyle(),
          ),
        ],
      ),
    );
  }

}
