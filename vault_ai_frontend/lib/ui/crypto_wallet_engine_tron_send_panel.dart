

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/app_release_controller_scope.dart';
import '../services/crypto_wallet_features.dart';
import '../services/zk_active_mvk.dart' as zk_mvk_store;
import '../services/zk_outgoing_history_helper.dart'
    as zk_history_helper;
import '../services/zk_send_draft_helper.dart' as zk_draft_helper;
import '../services/recipient_qr_parser.dart';
import '../services/tron_transaction.dart';
import '../services/tron_wallet.dart';
import 'crypto_wallet_engine_design.dart';
import 'crypto_wallet_engine_send_layout.dart';
import 'scan_recipient_qr_sheet.dart';


const String kTronSendUpdatePendingError =
    'SVaultAI was updated. Refresh before starting a new send.';
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
    'Your TRON secret is decrypted on this device only. SVaultAI '
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


// 2026-07-14 (Round 7 hardening): terminal-result states for the
// honest post-broadcast result screen.
enum _TronSendStage {
  input, review, submitting, submitted, uncertain, rejected, expired,
}


// 2026-07-14 (Round 7 hardening): TRON-specific gate + result copy.
const String kTronSendExactFeeUnverifiedError =
    'The exact TRX resource authorization could not be verified. '
    'Try again in a moment.';
const String kTronSendInsufficientTokenError =
    'Your USDT balance is not enough for this draft. Reduce the '
    'amount or top up USDT and re-draft.';
const String kTronSendInsufficientTrxError =
    'Your TRX balance is not enough to cover the authorized network '
    'fee for this draft. Top up TRX and re-draft.';
const String kTronSendDraftExpiredError =
    'The TRON draft expired before broadcast. Return to form to '
    'obtain a fresh draft; recipient and amount are preserved.';
const String kTronSendResultHeadingSubmitted =
    'Transaction submitted';
const String kTronSendResultHeadingUncertain =
    'Transaction status is uncertain';
const String kTronSendResultHeadingRejected =
    'Transaction rejected';
const String kTronSendResultHeadingExpired =
    'Draft expired before broadcast';
const String kTronSendResultBodyUncertain =
    'The TRON provider did not confirm inclusion within the '
    'visibility window. SVaultAI will keep checking. Do not re-sign '
    'until the status resolves.';
const String kTronSendResultBodyRejected =
    'The TRON provider explicitly rejected this transaction. The '
    'draft was consumed under the single-attempt policy; retrying '
    'requires a fresh draft.';
const String kTronSendViewActivityLabel = 'View activity';
const String kTronSendCheckStatusLabel = 'Check status';
const String kTronSendReturnFormLabel = 'Start a new send';
const String kTronSendMaxActionLabel = 'Max';
// 2026-07-14 (Round 8 hardening): Max fail-closed error strings.
const String kTronSendMaxBalanceUnverifiedError =
    'Your USDT balance is not verified. Try again after the balance '
    'refreshes.';

// 2026-07-14 (Round 8 hardening): TRON review-copy labels for
// separate token amount / max-authorized fee display.
const String kTronReviewNetworkLabel = 'Network';
const String kTronReviewNetworkValue = 'TRON Mainnet';
const String kTronReviewUsdtAmountLabel = 'USDT amount';
const String kTronReviewMaxAuthorizedFeeLabel =
    'Maximum authorized network cost (TRX)';
const String kTronReviewMaxAuthorizedFeeSunLabel =
    'Maximum authorized fee (sun)';
const String kTronReviewMaxAuthorizedFeeCaution =
    'This is the maximum you authorize the network to charge. The '
    'actual TRX cost may be lower, but it will never exceed this '
    'limit.';
const String kTronReviewExpirationLabel =
    'This draft expires shortly — sign and broadcast promptly, or '
    're-draft.';


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

  // 2026-07-13 QR-scan hook. Injectable for tests.
  final Future<String?> Function(
    BuildContext context,
    RecipientNetwork network,
    int? expectedChainId,
  )? scanRecipientQr;

  /// 2026-07-14 (Round 7): integer-exact USDT_TRC20 base-units
  /// balance. Non-null and >= draft base units → allowed.
  final Future<BigInt?> Function()? fetchAvailableTokenBaseUnits;

  /// 2026-07-14 (Round 7): integer-exact TRX balance in sun.
  /// Non-null and >= draft fee_limit_sun → allowed.
  final Future<BigInt?> Function()? fetchTrxBalanceSun;

  /// 2026-07-14 (Round 7): fired with the returned txID + base-unit
  /// token debit + sun fee debit after a non-rejected broadcast
  /// outcome. Used by asset detail to stamp an optimistic pending
  /// debit on the token balance card.
  final void Function({
    required String txHash,
    required BigInt tokenBaseUnitsDebit,
    required BigInt sunFeeDebit,
  })? onSuccessfulBroadcast;

  /// 2026-07-14 (Round 7): triggered when the user taps
  /// "View activity" from a submitted / uncertain result screen.
  final VoidCallback? onViewActivity;

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
    this.scanRecipientQr,
    this.fetchAvailableTokenBaseUnits,
    this.fetchTrxBalanceSun,
    this.onSuccessfulBroadcast,
    this.onViewActivity,
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

  // 2026-07-13 mobile-keyboard fix: shared scroll controller +
  // FocusNodes so tapping / Next-key-hopping to a field slides it
  // above the mobile Safari keyboard.
  final ScrollController _formScrollCtrl = ScrollController();
  final FocusNode _destFocus = FocusNode(debugLabel: 'tron_send_dest');
  final FocusNode _amountFocus = FocusNode(debugLabel: 'tron_send_amount');

  _TronSendStage _stage = _TronSendStage.input;
  String? _error;
  Map<String, dynamic>? _draft;
  Map<String, dynamic>? _submitted;
  bool _broadcastInFlight = false;
  // 2026-07-14 (Round 8 hardening): synchronous draft-in-flight
  // guard. Set BEFORE the first `await` in `_onReview` so a rapid
  // double-tap of Review cannot spawn a second draft.
  bool _draftInFlight = false;
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
      widget.features?.tronSendEnabled ?? false;

  bool get _sendPaused =>
      widget.features?.tronSendPaused ?? false;

  Future<void> _onReview() async {
    // 2026-07-14 (Round 11 — release wiring): block a NEW Send if
    // the release-update controller reports a pending update.
    final rc = AppReleaseControllerScope.maybeOf(context);
    if (rc != null && rc.sendShouldBeBlocked()) {
      await rc.checkForUpdate();
      if (rc.sendShouldBeBlocked()) {
        setState(() => _error = kTronSendUpdatePendingError);
        return;
      }
    }
    // 2026-07-14 (Round 8 hardening): synchronous draft-in-flight
    // guard. Rapid double-tap → single draft.
    if (_draftInFlight) return;
    if (_draft != null && _stage != _TronSendStage.input) return;
    _draftInFlight = true;
    setState(() {
      _error = null;
    });
    try {
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
        final zkEnvelope = await zk_draft_helper.buildZkSendDraftEnvelope(
          activeMvk: zk_mvk_store.ZkActiveMvk.current(),
          fromAddress: widget.fromAddress,
          destinationAddress: destination,
          asset: kTronAssetTicker,
          amountUsdt: _amountController.text.trim(),
        );
        final draft = await widget.client
            .createCryptoWalletSendDraftNetwork(
          network: kTronNetworkId,
          asset: kTronAssetTicker,
          authToken: widget.authToken,
          fromAddress: widget.fromAddress,
          destinationAddress: destination,
          amountUsdt: _amountController.text.trim(),
          draftPayloadCiphertext: zkEnvelope?.draftPayloadCiphertext,
          senderAddressLookupHash: zkEnvelope?.senderAddressLookupHash,
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
    } finally {
      _draftInFlight = false;
    }
  }

  Future<void> _onConfirmAndSign() async {
    // 2026-07-14 (Round 7 hardening): idempotent entry. Duplicate
    // Review/PIN/broadcast taps + browser back+forward must be
    // no-ops.
    if (_broadcastInFlight) return;
    if (_stage == _TronSendStage.submitted
        || _stage == _TronSendStage.uncertain
        || _stage == _TronSendStage.rejected
        || _stage == _TronSendStage.expired) {
      return;
    }
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

    // 2026-07-14 (Round 8 hardening): full pre-sign gate chain
    // for TRON, FAIL CLOSED throughout.
    //
    //   1. Integer-exact sun+token authorization.
    //   2. AUTHORITATIVE pre-secret expiry check via the backend
    //      draft-expiry endpoint.
    //   3. Only then encrypted secret + decrypt + sign.
    //   4. A SECOND expiry check runs immediately before broadcast.
    final draftForGate = _draft;
    if (draftForGate == null) {
      _broadcastInFlight = false;
      setState(() {
        _stage = _TronSendStage.review;
        _error = kTronSendExactFeeUnverifiedError;
      });
      return;
    }
    final gateError = await _verifyExactSunAuthorization(
      draft: draftForGate,
    );
    if (gateError != null) {
      _broadcastInFlight = false;
      setState(() {
        _stage = _TronSendStage.review;
        _error = gateError;
      });
      return;
    }
    final preSecretExpiry = await _verifyDraftExpiryFailClosed(
      draft: draftForGate,
    );
    if (preSecretExpiry != null) {
      _broadcastInFlight = false;
      setState(() {
        _stage = _TronSendStage.expired;
        _error = preSecretExpiry;
      });
      return;
    }

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

      // 2026-07-14 (Round 8 hardening): SECOND authoritative
      // expiry check IMMEDIATELY before broadcast. TRON's on-chain
      // `expiration` field is enforced by the network; a draft
      // whose expiration passed between the pre-secret verify and
      // now MUST NOT be broadcast.
      final preBroadcastExpiry = await _verifyDraftExpiryFailClosed(
        draft: draft,
      );
      if (preBroadcastExpiry != null) {
        _broadcastInFlight = false;
        setState(() {
          _stage = _TronSendStage.expired;
          _error = preBroadcastExpiry;
        });
        return;
      }

      // 2026-07-14 (Round 7 hardening): draftId echoed so the state
      // machine can enforce single-attempt + record outcomes.
      final draftIdEcho = (draft['draftId'] ?? '').toString();
      final broadcastResp = await widget.client
          .broadcastCryptoWalletSignedTransactionNetwork(
        network:           kTronNetworkId,
        asset:             kTronAssetTicker,
        authToken:         widget.authToken,
        signedTransaction: signed,
        idempotencyKey:    _idempotencyKey,
        draftId:           draftIdEcho.isEmpty ? null : draftIdEcho,
      );
      final broadcastStatus =
          (broadcastResp['status'] ?? '').toString();
      // Honest outcome classification. Round-6 backend returns:
      //   submitted / already_submitted            → success
      //   submission_uncertain                     → uncertain
      //   broadcast_rejected / broadcast_failed    → rejected
      //   draft_expired                            → expired
      if (broadcastStatus == 'submitted'
          || broadcastStatus == 'already_submitted') {
        _notifyOptimisticDebit(
          txHash: (broadcastResp['txHash'] ?? '').toString(),
          draft: draft,
        );
        unawaited(_persistZkOutgoingHistoryTron(
          draft: draft,
          txHash: (broadcastResp['txHash'] ?? '').toString(),
          outcome: broadcastStatus,
        ));
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.submitted;
          _submitted = broadcastResp;
        });
        _startStatusPolling();
      } else if (broadcastStatus == 'submission_uncertain') {
        _notifyOptimisticDebit(
          txHash: (broadcastResp['txHash'] ?? '').toString(),
          draft: draft,
        );
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.uncertain;
          _submitted = broadcastResp;
        });
      } else if (broadcastStatus == 'broadcast_rejected'
          || broadcastStatus == 'broadcast_failed') {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.rejected;
          _submitted = broadcastResp;
        });
      } else if (broadcastStatus == 'draft_expired') {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.expired;
          _submitted = broadcastResp;
        });
      } else {
        setState(() {
          _broadcastInFlight = false;
          _stage = _TronSendStage.review;
          _error = (broadcastResp['message']
              ?? kTronSendBroadcastFailedCopy).toString();
        });
      }
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

  // 2026-07-14 (Round 8 hardening): integer-exact TRX+token gate.
  // FAIL CLOSED.
  //
  //   * `fetchAvailableTokenBaseUnits == null`  → block
  //   * `fetchTrxBalanceSun == null`            → block
  //   * token balance null / throws             → block
  //   * TRX balance null / throws               → block
  //   * malformed persisted token / fee values  → block
  //   * token 1 base unit short                 → block
  //   * TRX 1 sun short                         → block
  //   * exact equality                          → allow
  Future<String?> _verifyExactSunAuthorization({
    required Map<String, dynamic> draft,
  }) async {
    if (widget.fetchAvailableTokenBaseUnits == null) {
      return kTronSendExactFeeUnverifiedError;
    }
    if (widget.fetchTrxBalanceSun == null) {
      return kTronSendExactFeeUnverifiedError;
    }
    final rawAmount = (draft['amountBaseUnits'] ?? '').toString();
    final rawFee = (draft['feeLimitSun'] ?? '').toString();
    if (rawAmount.isEmpty || rawFee.isEmpty) {
      return kTronSendExactFeeUnverifiedError;
    }
    final BigInt? tokenAmount = BigInt.tryParse(rawAmount);
    final BigInt? feeLimitSun = BigInt.tryParse(rawFee);
    if (tokenAmount == null || feeLimitSun == null
        || tokenAmount < BigInt.zero || feeLimitSun < BigInt.zero) {
      return kTronSendExactFeeUnverifiedError;
    }
    BigInt? tokenAvail;
    try {
      tokenAvail = await widget.fetchAvailableTokenBaseUnits!();
    } catch (_) {
      tokenAvail = null;
    }
    if (tokenAvail == null) return kTronSendExactFeeUnverifiedError;
    if (tokenAmount > tokenAvail) return kTronSendInsufficientTokenError;
    BigInt? trxSun;
    try {
      trxSun = await widget.fetchTrxBalanceSun!();
    } catch (_) {
      trxSun = null;
    }
    if (trxSun == null) return kTronSendExactFeeUnverifiedError;
    if (feeLimitSun > trxSun) return kTronSendInsufficientTrxError;
    return null;
  }

  // 2026-07-14 (Round 8 hardening): authoritative pre-sign +
  // pre-broadcast expiry verification via the backend TRON draft
  // expiry endpoint. FAIL CLOSED on transport error, unknown /
  // consumed draft, or `expired == null`.
  Future<String?> _verifyDraftExpiryFailClosed({
    required Map<String, dynamic> draft,
  }) async {
    final draftId = (draft['draftId'] ?? '').toString();
    if (draftId.isEmpty) {
      return kTronSendExactFeeUnverifiedError;
    }
    Map<String, dynamic>? resp;
    try {
      resp = await widget.client.getCryptoWalletDraftExpiryNetwork(
        network: kTronNetworkId,
        draftId: draftId,
        authToken: widget.authToken,
      );
    } catch (_) {
      return kTronSendDraftExpiredError;
    }
    // Strict fail-closed: ONLY `expired: false` (canonical bool) is
    // an allow. Anything else — null, missing field, string 'true'/
    // 'false', numeric 0/1, or any other unexpected shape — is
    // treated as unverifiable and BLOCKS.
    final expired = resp['expired'];
    if (expired is bool && expired == false) {
      return null;
    }
    return kTronSendDraftExpiredError;
  }

  // 2026-07-14 (Round 8 hardening): TRON USDT Max button.
  //
  //   Max = exact verified USDT base-unit balance
  //
  // Never subtracts TRX from USDT. TRX fee authorization is
  // enforced separately by `_verifyExactSunAuthorization` before
  // signing.
  Future<void> _onMaxTap() async {
    if (widget.fetchAvailableTokenBaseUnits == null) {
      setState(() {
        _error = kTronSendMaxBalanceUnverifiedError;
      });
      return;
    }
    BigInt? tokenAvail;
    try {
      tokenAvail = await widget.fetchAvailableTokenBaseUnits!();
    } catch (_) {
      tokenAvail = null;
    }
    if (tokenAvail == null) {
      setState(() {
        _error = kTronSendMaxBalanceUnverifiedError;
      });
      return;
    }
    if (tokenAvail <= BigInt.zero) {
      setState(() {
        _error = kTronSendInsufficientTokenError;
      });
      return;
    }
    _amountController.text = _usdtBaseUnitsToString(tokenAvail);
    setState(() {
      _error = null;
    });
  }

  static String _usdtBaseUnitsToString(BigInt base) {
    // USDT_TRC20 has 6 decimals.
    final divisor = BigInt.from(10).pow(6);
    final whole = base ~/ divisor;
    final frac = base - whole * divisor;
    if (frac == BigInt.zero) return whole.toString();
    final fracStr = frac.toString().padLeft(6, '0');
    final trimmed = fracStr.replaceFirst(RegExp(r'0+$'), '');
    return trimmed.isEmpty ? whole.toString() : '$whole.$trimmed';
  }

  void _notifyOptimisticDebit({
    required String txHash,
    required Map<String, dynamic> draft,
  }) {
    final cb = widget.onSuccessfulBroadcast;
    if (cb == null) return;
    final BigInt tokenAmount = BigInt.tryParse(
      (draft['amountBaseUnits'] ?? '0').toString(),
    ) ?? BigInt.zero;
    final BigInt feeLimitSun = BigInt.tryParse(
      (draft['feeLimitSun'] ?? '0').toString(),
    ) ?? BigInt.zero;
    cb(
      txHash: txHash,
      tokenBaseUnitsDebit: tokenAmount,
      sunFeeDebit: feeLimitSun,
    );
  }

  Future<void> _persistZkOutgoingHistoryTron({
    required Map<String, dynamic> draft,
    required String txHash,
    required String outcome,
  }) async {
    try {
      if (txHash.isEmpty) return;
      final env = await zk_history_helper.buildZkOutgoingHistoryEnvelope(
        activeMvk: zk_mvk_store.ZkActiveMvk.current(),
        signature: txHash,
        senderAddress: widget.fromAddress,
        destinationAddress:
            (draft['destinationAddress'] ?? '').toString(),
        asset: kTronAssetTicker,
        amount: (draft['amountUsdt']
            ?? draft['amountBaseUnits'] ?? '').toString(),
        outcome: outcome,
      );
      if (env == null) return;
      await widget.client.postCryptoOutgoingHistoryCiphertext(
        authToken: widget.authToken,
        network: 'tron',
        signatureLookupHash: env.signatureLookupHash,
        outcomePayloadCiphertext: env.outcomePayloadCiphertext,
      );
    } catch (_) {}
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
    // 2026-07-13: Send TRC20 sheets adopt the shared compact layout —
    // network chip, sticky Confirm button pinned above the keyboard,
    // no duplicated `Send USDT (TRC20)` heading (chrome supplies it).
    return WalletDarkPanelScope(
      child: KeyedSubtree(
        key: const Key(kTronSendPanelKey),
        child: _buildLayoutForStage(),
      ),
    );
  }

  Widget _buildLayoutForStage() {
    final header = walletSendNetworkChip(
      key: const Key('tron_send_panel_network_chip'),
      label: 'TRON Mainnet',
      isMainnet: true,
    );
    if (_sendPaused) {
      return WalletSendScaffold(
        sheetKey: 'tron_send_panel',
        header: header,
        body: _buildPausedBanner(),
      );
    }
    if (!_sendEnabled) {
      return WalletSendScaffold(
        sheetKey: 'tron_send_panel',
        header: header,
        body: _buildDisabledBanner(),
      );
    }
    switch (_stage) {
      case _TronSendStage.input:
        return WalletSendScaffold(
          sheetKey: 'tron_send_panel',
          header: header,
          body: _buildInputBody(),
          footer: _buildInputFooter(),
          scrollController: _formScrollCtrl,
        );
      case _TronSendStage.review:
        return WalletSendScaffold(
          sheetKey: 'tron_send_panel',
          header: header,
          body: _buildReviewBody(),
          footer: _buildReviewFooter(),
        );
      case _TronSendStage.submitting:
        return WalletSendScaffold(
          sheetKey: 'tron_send_panel',
          header: header,
          body: _buildSubmittingStage(),
        );
      case _TronSendStage.submitted:
      case _TronSendStage.uncertain:
      case _TronSendStage.rejected:
      case _TronSendStage.expired:
        return WalletSendScaffold(
          sheetKey: 'tron_send_panel',
          header: header,
          body: _buildResultStage(),
        );
    }
  }

  // 2026-07-14 (Round 7 hardening): honest result screen shared by
  // submitted / uncertain / rejected / expired.
  Widget _buildResultStage() {
    final isSuccess = _stage == _TronSendStage.submitted;
    final isUncertain = _stage == _TronSendStage.uncertain;
    final isRejected = _stage == _TronSendStage.rejected;
    final isExpired = _stage == _TronSendStage.expired;
    String heading;
    String body;
    bool showViewActivity = true;
    bool showCheckStatus = false;
    bool showReturnForm = false;
    if (isSuccess) {
      heading = kTronSendResultHeadingSubmitted;
      body = kTronSendSubmittedBody;
    } else if (isUncertain) {
      heading = kTronSendResultHeadingUncertain;
      body = kTronSendResultBodyUncertain;
      showCheckStatus = true;
    } else if (isRejected) {
      heading = kTronSendResultHeadingRejected;
      body = kTronSendResultBodyRejected;
      showViewActivity = false;
      showReturnForm = true;
    } else if (isExpired) {
      heading = kTronSendResultHeadingExpired;
      body = kTronSendDraftExpiredError;
      showViewActivity = false;
      showReturnForm = true;
    } else {
      heading = kTronSendSubmittedHeading;
      body = kTronSendSubmittedBody;
    }
    final txHash = (_submitted?['txHash'] ?? '').toString();
    final headingColor = isSuccess
        ? kWalletAccentSuccess
        : (isUncertain ? kWalletAccentWarning : kWalletAccentDanger);
    return Container(
      key: const Key(kTronSendSubmittedCardKey),
      padding: const EdgeInsets.all(14),
      decoration: isSuccess
          ? walletSuccessPanel()
          : (isUncertain ? walletWarningPanel() : walletDangerPanel()),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            heading,
            key: const Key('tron_send_panel_result_heading'),
            style: TextStyle(
              color: headingColor, fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            body,
            key: const Key('tron_send_panel_result_body'),
            style: TextStyle(color: headingColor, fontSize: 13),
          ),
          if (isSuccess || isUncertain) ...[
            const SizedBox(height: 6),
            Text(
              _statusCode == 'confirmed'
                  ? kTronSendStatusConfirmedCopy
                  : _statusCode == 'failed'
                      ? kTronSendStatusFailedCopy
                      : _statusCode == 'unavailable'
                          ? kTronSendStatusUnavailableCopy
                          : kTronSendStatusPendingCopy,
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
          ],
          if (txHash.isNotEmpty) ...[
            const SizedBox(height: 10),
            SelectableText(
              txHash,
              key: const Key('tron_send_panel_txhash_text'),
              style: kWalletMonoStyle,
            ),
          ],
          if (showCheckStatus) ...[
            const SizedBox(height: 6),
            OutlinedButton(
              key: const Key('tron_send_panel_check_status_btn'),
              onPressed: () {
                _statusPollActive = false;
                _startStatusPolling();
              },
              style: walletGhostButtonStyle(),
              child: const Text(kTronSendCheckStatusLabel),
            ),
          ],
          if (showViewActivity && widget.onViewActivity != null) ...[
            const SizedBox(height: 6),
            OutlinedButton(
              key: const Key('tron_send_panel_view_activity_btn'),
              onPressed: widget.onViewActivity,
              style: walletGhostButtonStyle(),
              child: const Text(kTronSendViewActivityLabel),
            ),
          ],
          if (showReturnForm) ...[
            const SizedBox(height: 6),
            OutlinedButton(
              key: const Key('tron_send_panel_return_form_btn'),
              onPressed: () {
                setState(() {
                  _stage = _TronSendStage.input;
                  _submitted = null;
                  _error = null;
                });
              },
              style: walletGhostButtonStyle(),
              child: const Text(kTronSendReturnFormLabel),
            ),
          ],
        ],
      ),
    );
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

  Future<void> _handleScanRecipientQr(BuildContext ctx) async {
    FocusManager.instance.primaryFocus?.unfocus();
    final scanHook = widget.scanRecipientQr;
    final scannedAddress = scanHook != null
        ? await scanHook(ctx, RecipientNetwork.tron, null)
        : await showScanRecipientQrSheet(
            context: ctx,
            network: RecipientNetwork.tron,
          );
    if (scannedAddress == null || !mounted) return;
    setState(() {
      _destinationController.text = scannedAddress;
    });
  }

  Widget _buildInputBody() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          key: const Key(kTronSendDestinationInputKey),
          controller: _destinationController,
          focusNode: _destFocus,
          textInputAction: TextInputAction.next,
          autocorrect: false,
          enableSuggestions: false,
          onSubmitted: (_) => _amountFocus.requestFocus(),
          decoration: InputDecoration(
            labelText: kTronSendDestinationLabel,
            isDense: true,
            suffixIcon: IconButton(
              key: const Key('tron_send_panel_scan_qr_btn'),
              icon: const Icon(Icons.qr_code_scanner_rounded),
              tooltip: 'Scan recipient QR',
              onPressed: () => _handleScanRecipientQr(context),
            ),
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key(kTronSendAmountInputKey),
          controller: _amountController,
          focusNode: _amountFocus,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _amountFocus.unfocus(),
          decoration: InputDecoration(
            labelText: kTronSendAmountLabel,
            isDense: true,
            // 2026-07-14 (Round 8 hardening): Max button. Uses the
            // full verified token base-unit balance. Never
            // subtracts TRX — TRX fee authorization is enforced
            // separately by the exact-sun gate before signing.
            suffixIcon: TextButton(
              key: const Key('tron_send_panel_max_btn'),
              onPressed: _onMaxTap,
              child: const Text(
                kTronSendMaxActionLabel,
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.2,
                ),
              ),
            ),
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
      key: const Key(kTronSendReviewButtonKey),
      // 2026-07-14 (Round 8 hardening): Review disabled while
      // drafting so a rapid double-tap cannot spawn a second draft.
      onPressed: _draftInFlight ? null : _onReview,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: const Text(kTronSendReviewButtonLabel),
    );
  }

  Widget _buildReviewBody() {
    final draft = _draft!;
    final resourceStatus =
        (draft['resourceStatus'] ?? 'unavailable').toString();
    final feeLimitTrx = (draft['feeLimitTrx'] ?? '').toString();
    final feeLimitSun = (draft['feeLimitSun'] ?? '').toString();
    final trxBalance = (draft['trxBalance'] ?? '').toString();
    final expirationMs = (draft['expirationMs'] ?? '').toString();
    return Column(
      key: const Key(kTronSendReviewCardKey),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        walletSendSectionHeading(kTronSendReviewHeading),
        WalletSendKvRow(label: 'Asset', value: 'USDT TRC20'),
        // 2026-07-14 (Round 8 hardening): explicit network label so
        // the user knows this is TRON Mainnet at Review time.
        WalletSendKvRow(
          label: kTronReviewNetworkLabel,
          value: kTronReviewNetworkValue,
        ),
        WalletSendKvRow(
          label: 'From', value: widget.fromAddress, mono: true,
        ),
        WalletSendKvRow(
          label: 'Destination',
          value: (draft['destinationAddress'] ?? '').toString(),
          mono: true,
        ),
        // 2026-07-14 (Round 8 hardening): USDT amount labelled
        // separately from any TRX/fee reference so the user can
        // read the value at a glance.
        WalletSendKvRow(
          key: const Key('tron_send_panel_review_usdt_amount_row'),
          label: kTronReviewUsdtAmountLabel,
          value: '${draft['amountUsdt']} USDT',
        ),
        // 2026-07-14 (Round 8 hardening): TRX MAX AUTHORIZED cost,
        // explicitly labelled as maximum authorized (not the
        // guaranteed fee).
        if (feeLimitTrx.isNotEmpty)
          WalletSendKvRow(
            key: const Key(
              'tron_send_panel_review_max_authorized_fee_trx_row',
            ),
            label: kTronReviewMaxAuthorizedFeeLabel,
            value: '$feeLimitTrx TRX',
          ),
        // Sun-precision figure for auditability. Not shown when the
        // network cost field is missing.
        if (feeLimitSun.isNotEmpty)
          WalletSendKvRow(
            key: const Key(
              'tron_send_panel_review_max_authorized_fee_sun_row',
            ),
            label: kTronReviewMaxAuthorizedFeeSunLabel,
            value: '$feeLimitSun sun',
          ),
        if (feeLimitTrx.isNotEmpty || feeLimitSun.isNotEmpty)
          Padding(
            key: const Key(
              'tron_send_panel_review_max_authorized_caution',
            ),
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              kTronReviewMaxAuthorizedFeeCaution,
              style: kWalletMutedStyle,
            ),
          ),
        if (trxBalance.isNotEmpty)
          WalletSendKvRow(
            label: 'TRX balance',
            value: '$trxBalance TRX',
          ),
        WalletSendKvRow(
          label: 'Resource status',
          value: resourceStatus,
        ),
        if (expirationMs.isNotEmpty && expirationMs != '0')
          Padding(
            key: const Key(
              'tron_send_panel_review_expiration_notice',
            ),
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              kTronReviewExpirationLabel,
              style: kWalletMutedStyle,
            ),
          ),
        const SizedBox(height: 10),
        const WalletSendWarning(
          key: Key(kTronSendWarningKey),
          text: kTronSendConfirmationWarning,
        ),
        // Compact muted fee-notice line — replaces the old bordered
        // fee-warning card so the review stage stays scan-able. The
        // key is preserved so existing keyed test lookups continue to
        // find it.
        const SizedBox(height: 6),
        Row(
          key: Key('${kTronSendFeeWarningKey}_row'),
          crossAxisAlignment: CrossAxisAlignment.start,
          children: const [
            Icon(Icons.local_gas_station_outlined,
                size: 14, color: kWalletTextMuted),
            SizedBox(width: 6),
            Expanded(
              child: Text(
                kTronSendFeeWarning,
                key: Key(kTronSendFeeWarningKey),
                style: kWalletMutedStyle,
              ),
            ),
          ],
        ),
        if (resourceStatus == 'low_trx') ...[
          const SizedBox(height: 6),
          const WalletSendWarning(
            key: Key(kTronSendLowTrxWarningKey),
            text: kTronSendLowTrxWarning,
            tone: WalletSendWarningTone.critical,
          ),
        ],
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
      key: const Key(kTronSendConfirmButtonKey),
      onPressed:
          _broadcastInFlight ? null : _onConfirmAndSign,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: Text(
        _broadcastInFlight
            ? 'Submitting…'
            : kTronSendConfirmButtonLabel,
      ),
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

}
