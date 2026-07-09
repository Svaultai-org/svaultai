

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/crypto_wallet_features.dart';
import '../services/tron_transaction.dart';
import '../services/tron_wallet.dart';
import 'crypto_wallet_engine_design.dart';


const String kTronSendPanelTitle = 'Send USDT (TRC20)';
const String kTronSendReviewHeading = 'Review USDT TRC20 send';
const String kTronSendConfirmationWarning =
    'Review carefully. TRON transactions cannot be reversed.';
const String kTronSendFeeWarning =
    'USDT TRC20 transfers require TRX for TRON network fees.';
const String kTronSendLowTrxWarning =
    'This wallet may not have enough TRX for TRON network fees.';
const String kTronSendNotEnabledMessage =
    'USDT TRC20 sending is not enabled yet.';
const String kTronSendPausedMessage =
    'USDT TRC20 sending is temporarily paused.';
const String kTronSendPinDialogTitle =
    'Enter your PIN to sign locally';
const String kTronSendPinDialogBody =
    'Your TRON secret is decrypted on this device only. VaultAI '
    'never sees the plaintext key.';
const String kTronSendSubmittedHeading = 'Broadcast submitted';
const String kTronSendSubmittedBody =
    'Your USDT TRC20 transfer was submitted. Confirmation may take a '
    'few seconds.';
const String kTronSendDestinationLabel = 'Destination TRON address';
const String kTronSendAmountLabel = 'Amount (USDT)';
const String kTronSendReviewButtonLabel = 'Review';
const String kTronSendConfirmButtonLabel = 'Confirm and enter PIN';
const String kTronSendBroadcastFailedCopy =
    'Could not submit transaction.';
const String kTronSendInvalidDestinationCopy =
    'Destination must be a valid TRON Base58Check address.';
const String kTronSendInvalidAmountCopy =
    'Amount must be a decimal like 5 or 12.5 (up to 6 decimal places).';
const String kTronSendSelfSendCopy =
    'Destination address matches the from address. Refusing to '
    'draft a self-send.';


const String kTronSendPanelKey = 'tron_send_panel';
const String kTronSendDestinationInputKey =
    'tron_send_panel_destination_input';
const String kTronSendAmountInputKey =
    'tron_send_panel_amount_input';
const String kTronSendReviewButtonKey =
    'tron_send_panel_review_btn';
const String kTronSendReviewCardKey =
    'tron_send_panel_review_card';
const String kTronSendConfirmButtonKey =
    'tron_send_panel_confirm_btn';
const String kTronSendSubmittedCardKey =
    'tron_send_panel_submitted_card';
const String kTronSendPausedBannerKey =
    'tron_send_panel_paused_banner';
const String kTronSendDisabledBannerKey =
    'tron_send_panel_disabled_banner';
const String kTronSendWarningKey =
    'tron_send_panel_warning';
const String kTronSendFeeWarningKey =
    'tron_send_panel_fee_warning';
const String kTronSendLowTrxWarningKey =
    'tron_send_panel_low_trx_warning';
const String kTronSendPinInputKey =
    'tron_send_panel_pin_input';
const String kTronSendPinConfirmBtnKey =
    'tron_send_panel_pin_confirm_btn';
const String kTronSendStatusTextKey =
    'tron_send_panel_status_text';
const String kTronSendTxIdTextKey =
    'tron_send_panel_txid_text';
const String kTronSendCopyTxIdBtnKey =
    'tron_send_panel_copy_txid_btn';


const String kTronSendStatusPollingCopy =
    'Checking TRON status…';
const String kTronSendStatusPendingCopy =
    'Status: pending';
const String kTronSendStatusConfirmedCopy =
    'Status: confirmed';
const String kTronSendStatusFailedCopy =
    'Status: failed';
const String kTronSendStatusUnavailableCopy =
    'Status temporarily unavailable';


String tronSendStatusCopyFor(String? statusCode) {
  switch (statusCode) {
    case 'confirmed': return kTronSendStatusConfirmedCopy;
    case 'failed':    return kTronSendStatusFailedCopy;
    case 'pending':   return kTronSendStatusPendingCopy;
    case 'unavailable':
      return kTronSendStatusUnavailableCopy;
  }
  return kTronSendStatusPollingCopy;
}


enum _TronSendStage { input, review, submitting, submitted }


class CryptoWalletEngineTronSendPanel extends StatefulWidget {
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

  const CryptoWalletEngineTronSendPanel({
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
  State<CryptoWalletEngineTronSendPanel> createState() =>
      _CryptoWalletEngineTronSendPanelState();
}


class _CryptoWalletEngineTronSendPanelState
    extends State<CryptoWalletEngineTronSendPanel> {
  final TextEditingController _destinationController =
      TextEditingController();
  final TextEditingController _amountController =
      TextEditingController();

  _TronSendStage _stage = _TronSendStage.input;
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
  }

  @override
  void dispose() {
    _statusPollActive = false;
    _statusTimer?.cancel();
    _statusTimer = null;
    _destinationController.dispose();
    _amountController.dispose();
    super.dispose();
  }

  bool get _sendEnabled =>
      widget.features?.tronSendEnabled ?? false;

  bool get _sendPaused =>
      widget.features?.tronSendPaused ?? false;

  Future<void> _onReview() async {
    setState(() {
      _error = null;
    });
    final destination = _destinationController.text.trim();
    if (!isValidTronAddress(destination)) {
      setState(() {
        _error = kTronSendInvalidDestinationCopy;
      });
      return;
    }
    if (destination == widget.fromAddress.trim()) {
      setState(() {
        _error = kTronSendSelfSendCopy;
      });
      return;
    }
    try {
      parseUsdtAmountToBaseUnits(_amountController.text);
    } catch (_) {
      setState(() {
        _error = kTronSendInvalidAmountCopy;
      });
      return;
    }
    try {
      final draft = await widget.client.createCryptoWalletSendDraftNetwork(
        network: kTronNetworkId,
        asset: kTronAssetTicker,
        authToken: widget.authToken,
        fromAddress: widget.fromAddress,
        destinationAddress: destination,
        amountUsdt: _amountController.text.trim(),
      );
      final status = (draft['status'] ?? '').toString();
      if (status != 'draft_ready') {
        setState(() {
          _error = (draft['message'] ??
              'USDT TRC20 draft not ready.').toString();
        });
        return;
      }
      setState(() {
        _draft = draft;
        _stage = _TronSendStage.review;
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
      _stage = _TronSendStage.submitting;
      _error = null;
    });

    _idempotencyKey ??= (widget.idempotencyKeyGenerator != null)
        ? widget.idempotencyKeyGenerator!()
        : _defaultIdempotencyKey();

    String? plaintextPrivateKeyHex;
    try {
      final secretResp = await widget.client
          .getCryptoWalletEncryptedSecretNetwork(
        network: kTronNetworkId,
        asset: kTronAssetTicker,
        authToken: widget.authToken,
      );
      final status = (secretResp['wallet_engine'] ?? '').toString();
      if (status != 'encrypted_secret_ready') {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.input;
          _error = 'Wallet secret not available for signing.';
        });
        return;
      }
      final ct = (secretResp['encryptedWalletSecret'] ?? '').toString();
      if (ct.isEmpty) {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.input;
          _error = 'Missing ciphertext.';
        });
        return;
      }
      final decrypted = await widget.decryptForVault(ct);
      final parsed = jsonDecode(decrypted);
      if (parsed is! Map<String, dynamic>) {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.input;
          _error = 'Malformed TRON secret blob.';
        });
        return;
      }
      plaintextPrivateKeyHex =
          (parsed['privateKeyHex'] ?? '').toString();
      if (plaintextPrivateKeyHex.isEmpty) {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.input;
          _error = 'Malformed TRON secret payload.';
        });
        return;
      }

      final draft = _draft!;
      final unsigned = draft['unsignedTransaction'];
      final txIDHex = (draft['txID'] ?? '').toString();
      if (unsigned is! Map<String, dynamic> || txIDHex.isEmpty) {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.review;
          _error = 'Draft is missing unsigned transaction bytes.';
        });
        return;
      }

      final signed = signTronTrc20Transfer(
        unsignedTransaction: unsigned,
        txIDHex: txIDHex,
        privateKeyHex: plaintextPrivateKeyHex,
      );

      wipePrivateKeyHex(plaintextPrivateKeyHex);
      plaintextPrivateKeyHex = null;

      final broadcastResp = await widget.client
          .broadcastCryptoWalletSignedTransactionNetwork(
        network:           kTronNetworkId,
        asset:             kTronAssetTicker,
        authToken:         widget.authToken,
        signedTransaction: signed,
        idempotencyKey:    _idempotencyKey,
      );
      final broadcastStatus =
          (broadcastResp['status'] ?? '').toString();
      if (broadcastStatus != 'submitted') {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.review;
          _error = (broadcastResp['message']
              ?? kTronSendBroadcastFailedCopy).toString();
        });
        return;
      }
      setState(() {
        _broadcastInFlight = false;
        _stage = _TronSendStage.submitted;
        _submitted = broadcastResp;
      });
      _startStatusPolling();
    } catch (e) {
      if (plaintextPrivateKeyHex != null) {
        wipePrivateKeyHex(plaintextPrivateKeyHex);
      }
      setState(() {
        _broadcastInFlight = false;
        _stage = _TronSendStage.review;
        _error = 'Sign/broadcast failed: $e';
      });
    }
  }

  String _defaultIdempotencyKey() {
    final now = DateTime.now().microsecondsSinceEpoch;
    final rand = now.toRadixString(36);
    final safeFrom = widget.fromAddress.length >= 8
        ? widget.fromAddress.substring(0, 8)
        : widget.fromAddress;
    return 'tron-$safeFrom-$rand';
  }

  void _startStatusPolling() {
    if (_statusPollActive) return;
    final txid = (_submitted?['txHash'] ?? '').toString();
    if (txid.isEmpty) return;
    _statusPollActive = true;
    _statusPollCount = 0;
    _statusCode = 'pending';
    if (mounted) setState(() {});
    _scheduleStatusPoll(txid);
  }

  void _scheduleStatusPoll(String txid) {
    if (!mounted || !_statusPollActive) return;
    if (_statusPollCount >= 12) {
      _statusPollActive = false;
      return;
    }
    _statusTimer?.cancel();
    _statusTimer = Timer(const Duration(seconds: 3), () async {
      if (!mounted || !_statusPollActive) return;
      _statusPollCount++;
      try {
        final resp = await widget.client
            .getCryptoWalletTransactionStatusNetwork(
          network:   kTronNetworkId,
          asset:     kTronAssetTicker,
          txHash:    txid,
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
      _scheduleStatusPoll(txid);
    });
  }

  Future<bool> _promptPin() async {
    final controller = TextEditingController();
    var pinOk = false;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        key: const Key('tron_send_pin_dialog'),
        title: const Text(kTronSendPinDialogTitle),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(kTronSendPinDialogBody),
            const SizedBox(height: 12),
            TextField(
              key: const Key(kTronSendPinInputKey),
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
            key: const Key(kTronSendPinConfirmBtnKey),
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
    return WalletDarkPanelScope(
      child: SingleChildScrollView(
        key: const Key(kTronSendPanelKey),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: _buildBody(),
        ),
      ),
    );
  }

  Widget _buildBody() {
    if (_sendPaused) {
      return _buildPausedBanner();
    }
    if (!_sendEnabled) {
      return _buildDisabledBanner();
    }
    switch (_stage) {
      case _TronSendStage.input:
        return _buildInputStage();
      case _TronSendStage.review:
        return _buildReviewStage();
      case _TronSendStage.submitting:
        return _buildSubmittingStage();
      case _TronSendStage.submitted:
        return _buildSubmittedStage();
    }
  }

  Widget _buildDisabledBanner() {
    return Container(
      key: const Key(kTronSendDisabledBannerKey),
      padding: const EdgeInsets.all(14),
      decoration: walletWarningPanel(),
      child: const Row(
        children: [
          Icon(Icons.hourglass_bottom_rounded,
              size: 18, color: kWalletAccentWarning),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              kTronSendNotEnabledMessage,
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
      key: const Key(kTronSendPausedBannerKey),
      padding: const EdgeInsets.all(14),
      decoration: walletWarningPanel(),
      child: const Row(
        children: [
          Icon(Icons.pause_circle_outline_rounded,
              size: 18, color: kWalletAccentWarning),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              kTronSendPausedMessage,
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

  Widget _buildInputStage() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text(
          kTronSendPanelTitle,
          style: TextStyle(
            color: kWalletTextPrimary,
            fontSize: 20,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.2,
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key(kTronSendDestinationInputKey),
          controller: _destinationController,
          decoration: const InputDecoration(
            labelText: kTronSendDestinationLabel,
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key(kTronSendAmountInputKey),
          controller: _amountController,
          decoration: const InputDecoration(
            labelText: kTronSendAmountLabel,
          ),
          keyboardType: const TextInputType.numberWithOptions(
            decimal: true,
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 8),
          Text(
            _error!,
            style: const TextStyle(
              color: kWalletAccentDanger, fontSize: 13,
            ),
          ),
        ],
        const SizedBox(height: 16),
        ElevatedButton(
          key: const Key(kTronSendReviewButtonKey),
          onPressed: _onReview,
          style: walletPrimaryButtonStyle(),
          child: const Text(kTronSendReviewButtonLabel),
        ),
      ],
    );
  }

  Widget _buildReviewStage() {
    final draft = _draft!;
    final resourceStatus =
        (draft['resourceStatus'] ?? 'unavailable').toString();
    final feeLimitTrx = (draft['feeLimitTrx'] ?? '').toString();
    final trxBalance = (draft['trxBalance'] ?? '').toString();
    return Column(
      key: const Key(kTronSendReviewCardKey),
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text(
          kTronSendReviewHeading,
          style: TextStyle(
            color: kWalletTextPrimary,
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 8),
        _kv('Asset', 'USDT TRC20'),
        _kv('Network', 'TRON'),
        _kv('From', widget.fromAddress),
        _kv('Destination',
            (draft['destinationAddress'] ?? '').toString()),
        _kv('Amount', '${draft['amountUsdt']} USDT'),
        if (feeLimitTrx.isNotEmpty)
          _kv('Fee limit (max)', '$feeLimitTrx TRX'),
        if (trxBalance.isNotEmpty)
          _kv('TRX balance', '$trxBalance TRX'),
        _kv('Resource status', resourceStatus),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: walletWarningPanel(),
          child: const Row(
            children: [
              Icon(Icons.warning_amber_rounded,
                  size: 16, color: kWalletAccentWarning),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  kTronSendConfirmationWarning,
                  key: Key(kTronSendWarningKey),
                  style: TextStyle(
                    color: kWalletAccentWarning,
                    fontSize: 13,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: kWalletBgBase,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: kWalletBorder),
          ),
          child: Row(
            children: [
              const Icon(Icons.local_gas_station_outlined,
                  size: 16, color: kWalletTextSecondary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  kTronSendFeeWarning,
                  key: const Key(kTronSendFeeWarningKey),
                  style: kWalletMutedStyle,
                ),
              ),
            ],
          ),
        ),
        if (resourceStatus == 'low_trx') ...[
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: walletWarningPanel(),
            child: Row(
              children: [
                const Icon(Icons.error_outline,
                    size: 16, color: kWalletAccentWarning),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    kTronSendLowTrxWarning,
                    key: const Key(kTronSendLowTrxWarningKey),
                    style: const TextStyle(
                      color: kWalletAccentWarning,
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
        if (_error != null) ...[
          const SizedBox(height: 8),
          Text(
            _error!,
            style: const TextStyle(
              color: kWalletAccentDanger, fontSize: 13,
            ),
          ),
        ],
        const SizedBox(height: 16),
        ElevatedButton(
          key: const Key(kTronSendConfirmButtonKey),
          onPressed:
              _broadcastInFlight ? null : _onConfirmAndSign,
          style: walletPrimaryButtonStyle(),
          child: Text(
            _broadcastInFlight
                ? 'Submitting…'
                : kTronSendConfirmButtonLabel,
          ),
        ),
      ],
    );
  }

  Widget _buildSubmittingStage() {
    return const Center(
      key: Key('tron_send_panel_submitting'),
      child: Padding(
        padding: EdgeInsets.all(24),
        child: CircularProgressIndicator(),
      ),
    );
  }

  Widget _buildSubmittedStage() {
    final resp = _submitted!;
    final txid = (resp['txHash'] ?? '').toString();
    return Container(
      key: const Key(kTronSendSubmittedCardKey),
      padding: const EdgeInsets.all(14),
      decoration: walletSuccessPanel(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kTronSendSubmittedHeading,
            style: TextStyle(
              color: kWalletAccentSuccess,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            kTronSendSubmittedBody,
            style: TextStyle(
              color: kWalletAccentSuccess,
              fontSize: 13,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            tronSendStatusCopyFor(_statusCode),
            key: const Key(kTronSendStatusTextKey),
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
            txid,
            key: const Key(kTronSendTxIdTextKey),
            style: kWalletMonoStyle,
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const Key(kTronSendCopyTxIdBtnKey),
            onPressed: () async {
              final label = AppLocalizations.of(context).cryptoTxIdCopied;
              await Clipboard.setData(
                ClipboardData(text: txid),
              );
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(label)),
                );
              }
            },
            icon: const Icon(Icons.copy_rounded, size: 16),
            label: Text(AppLocalizations.of(context).cryptoCopyTxId),
            style: walletGhostButtonStyle(),
          ),
        ],
      ),
    );
  }

  Widget _kv(String key, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(
              key,
              style: const TextStyle(
                color: kWalletTextSecondary, fontSize: 12,
              ),
            ),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: kWalletMonoStyle,
            ),
          ),
        ],
      ),
    );
  }
}
