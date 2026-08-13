import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/app_release_controller_scope.dart';
import '../services/zk_active_mvk.dart' as zk_mvk_store;
import '../services/zk_outgoing_history_helper.dart' as zk_history_helper;
import '../services/zk_send_draft_helper.dart' as zk_draft_helper;
import '../services/crypto_wallet_features.dart';
import '../services/recipient_qr_parser.dart';
import '../services/solana_transaction.dart';
import '../services/solana_wallet.dart';
import '../services/wallet_v2_repository.dart';
import 'crypto_wallet_engine_design.dart';
import 'crypto_wallet_engine_send_layout.dart';
import 'scan_recipient_qr_sheet.dart';

const String kSolanaSendPanelTitle = 'Send SOL';
const String kSolanaSendReviewHeading = 'Review Solana send';
const String kSolanaSendConfirmationWarning =
    'Review carefully. Solana transactions cannot be reversed.';
const String kSolanaSendNotEnabledMessage =
    'Solana sending is not enabled yet.';
const String kSolanaSendPausedMessage = 'Solana sending is temporarily paused.';
const String kSolanaSendPinDialogTitle = 'Enter your PIN to sign locally';
const String kSolanaSendPinDialogBody =
    'Your Solana secret is decrypted on this device only. SVaultAI '
    'never sees the plaintext key.';
const String kSolanaSendSubmittedHeading = 'Broadcast submitted';
const String kSolanaSendSubmittedBody =
    'Your Solana transaction was submitted. History is not yet '
    'connected — check the signature below.';
const String kSolanaSendDestinationLabel = 'Destination address';
const String kSolanaSendAmountLabel = 'Amount (SOL)';
const String kSolanaSendReviewButtonLabel = 'Review';
const String kSolanaSendConfirmButtonLabel = 'Confirm and enter PIN';
const String kSolanaSendBroadcastFailedCopy = 'Could not submit transaction.';
const String kSolanaSendInvalidDestinationCopy =
    'Destination must be a valid Solana base58 address.';
const String kSolanaSendInvalidAmountCopy =
    'Amount must be a decimal like 0.1 or 5 (up to 9 decimal places).';
const String kSolanaSendSelfSendCopy =
    'Destination address matches the from address. Refusing to '
    'draft a self-send.';

// 2026-07-14 (Round 7 hardening): integer-exact lamport gate
// errors + honest post-broadcast result states + expiry.
const String kSolanaSendExactFeeUnverifiedError =
    'The exact network fee could not be verified against your SOL '
    'balance. Try again in a moment.';
const String kSolanaSendInsufficientLamportsError =
    'Your SOL balance is not enough to cover the amount plus the '
    'authorized network fee. Reduce the amount or top up SOL.';
const String kSolanaSendDraftExpiredError =
    'The Solana blockhash for this draft has expired. Return to '
    'form to obtain a fresh draft; recipient and amount are '
    'preserved.';
const String kSolanaSendResultHeadingSubmitted = 'Transaction submitted';
const String kSolanaSendResultHeadingUncertain =
    'Transaction status is uncertain';
const String kSolanaSendResultHeadingRejected = 'Transaction rejected';
const String kSolanaSendResultHeadingExpired = 'Draft expired before broadcast';
const String kSolanaSendResultBodyUncertain =
    'The Solana RPC did not confirm inclusion in the visibility '
    'window. SVaultAI will keep checking. Do not re-sign with a new '
    'blockhash until the status resolves.';
const String kSolanaSendResultBodyRejected =
    'The Solana RPC explicitly rejected this transaction. The '
    'draft was consumed under the single-attempt policy; retrying '
    'requires a fresh draft.';
const String kSolanaSendViewActivityLabel = 'View activity';
const String kSolanaSendCheckStatusLabel = 'Check status';
const String kSolanaSendReturnFormLabel = 'Start a new send';
const String kSolanaSendMaxActionLabel = 'Max';
const String kSolanaSendAvailableBalancePrefix = 'Available:';
// 2026-07-14 (Round 8 hardening): SOL Max needs a persisted draft
// so the authoritative feeLamports is available. If none exists
// yet, we fail closed with a clear next-step message rather than
// invent a client-side fee estimate.
const String kSolanaSendUpdatePendingError =
    'SVaultAI was updated. Refresh before starting a new send.';
// 2026-07-14 (Round 10 — Max UX): SOL Max no longer requires a
// persisted draft. It calls the fee-estimate endpoint with the
// destination the user has entered.
const String kSolanaSendMaxRequiresDestinationError =
    'Enter a destination address first so we can estimate the '
    'network fee.';
const String kSolanaSendMaxTemporarilyUnavailableError =
    'Maximum amount is temporarily unavailable. Try again.';
// Kept for backward compatibility only.
const String kSolanaSendMaxRequiresDraftError =
    kSolanaSendMaxTemporarilyUnavailableError;
const String kSolanaSendMaxBalanceUnverifiedError =
    'Your SOL balance is not verified. Try again after the balance '
    'refreshes.';

const String kSolanaSendPanelKey = 'solana_send_panel';
const String kSolanaSendDestinationInputKey =
    'solana_send_panel_destination_input';
const String kSolanaSendAmountInputKey = 'solana_send_panel_amount_input';
const String kSolanaSendReviewButtonKey = 'solana_send_panel_review_btn';
const String kSolanaSendReviewCardKey = 'solana_send_panel_review_card';
const String kSolanaSendConfirmButtonKey = 'solana_send_panel_confirm_btn';
const String kSolanaSendSubmittedCardKey = 'solana_send_panel_submitted_card';
const String kSolanaSendPausedBannerKey = 'solana_send_panel_paused_banner';
const String kSolanaSendDisabledBannerKey = 'solana_send_panel_disabled_banner';
const String kSolanaSendWarningKey = 'solana_send_panel_warning';
const String kSolanaSendPinInputKey = 'solana_send_panel_pin_input';
const String kSolanaSendPinConfirmBtnKey = 'solana_send_panel_pin_confirm_btn';

// 2026-07-14 (Round 7 hardening): terminal-result outcomes and
// the expired result state.
enum _SolanaSendStage {
  input,
  review,
  submitting,
  submitted,
  expired,
  rejected,
  uncertain,
}

const String kSolanaSendFeeEstimatedLabel = 'Estimated network fee';
const String kSolanaSendFeeRealLabel = 'Network fee';
const String kSolanaSendFeeUnavailableLabel =
    'Network fee estimate unavailable';
const String kSolanaSendStatusPollingCopy = 'Checking Solana status…';
const String kSolanaSendStatusPendingCopy = 'Status: pending';
const String kSolanaSendStatusConfirmedCopy = 'Status: confirmed';
const String kSolanaSendStatusFailedCopy = 'Status: failed';
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
    case 'confirmed':
      return kSolanaSendStatusConfirmedCopy;
    case 'failed':
      return kSolanaSendStatusFailedCopy;
    case 'pending':
      return kSolanaSendStatusPendingCopy;
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

  // 2026-07-13 QR-scan hook. Injectable for tests.
  final Future<String?> Function(
    BuildContext context,
    RecipientNetwork network,
    int? expectedChainId,
  )? scanRecipientQr;

  /// 2026-07-14 (Round 7 hardening): integer-exact lamport balance.
  /// When wired, this is the FINAL authorization gate before signing.
  /// Returns null if RPC is unavailable → hard-gate blocks. Never
  /// call double arithmetic on the returned value; always use BigInt.
  final Future<BigInt?> Function()? fetchAvailableLamports;

  /// 2026-07-14 (Round 7 hardening): optional callback fired once
  /// with the returned signature and lamport debit (value +
  /// authorized fee) after a non-rejected broadcast outcome. Used
  /// by the asset detail page to stamp an optimistic pending debit
  /// on the balance card.
  final void Function({
    required String signature,
    required BigInt debitLamports,
  })? onSuccessfulBroadcast;

  /// 2026-07-14 (Round 7 hardening): triggered when the user taps
  /// "View activity" from a submitted / uncertain result screen.
  /// The caller pops the sheet and scrolls to the activity card.
  final VoidCallback? onViewActivity;

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
    this.scanRecipientQr,
    this.fetchAvailableLamports,
    this.onSuccessfulBroadcast,
    this.onViewActivity,
  });

  @override
  State<CryptoWalletEngineSolanaSendPanel> createState() =>
      _CryptoWalletEngineSolanaSendPanelState();
}

class _CryptoWalletEngineSolanaSendPanelState
    extends State<CryptoWalletEngineSolanaSendPanel> {
  final TextEditingController _destinationController = TextEditingController();
  final TextEditingController _amountController = TextEditingController();

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
  // 2026-07-14 (Round 8 hardening): synchronous draft-in-flight
  // guard. Set BEFORE the first `await` in `_onReview` so a
  // rapid double-tap of the Review button cannot spawn a second
  // draft. Race is caught client-side, not delegated to backend
  // single-active-draft-per-sender as normal UX.
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

  bool get _sendEnabled => widget.features?.solanaSendEnabled ?? false;

  bool get _sendPaused => widget.features?.solanaSendPaused ?? false;

  Future<void> _onReview() async {
    // 2026-07-14 (Round 11 — release wiring): block a NEW Send if
    // the release-update controller reports a pending update.
    final rc = AppReleaseControllerScope.maybeOf(context);
    if (rc != null && rc.sendShouldBeBlocked()) {
      await rc.checkForUpdate();
      if (rc.sendShouldBeBlocked()) {
        setState(() => _error = kSolanaSendUpdatePendingError);
        return;
      }
    }
    // 2026-07-14 (Round 8 hardening): SYNCHRONOUS draft-in-flight
    // guard. Set BEFORE any await so a rapid double-tap does not
    // spawn a second draft. Backend single-active-draft-per-sender
    // remains as belt-and-braces but is NOT the primary UX.
    if (_draftInFlight) return;
    // Also guard against re-drafting after we already have a
    // review-ready draft — the user must explicitly return to form
    // (e.g. after `draft_expired`) to clear it.
    if (_draft != null && _stage != _SolanaSendStage.input) return;
    _draftInFlight = true;
    setState(() {
      _error = null;
    });
    try {
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
        final zkEnvelope = await zk_draft_helper.buildZkSendDraftEnvelope(
          activeMvk: zk_mvk_store.ZkActiveMvk.current(),
          fromAddress: widget.fromAddress,
          destinationAddress: destination,
          asset: kSolanaAssetTicker,
          amountSol: _amountController.text.trim(),
        );
        final draft = await widget.client.createCryptoWalletSendDraftNetwork(
          network: kSolanaNetworkId,
          asset: kSolanaAssetTicker,
          authToken: widget.authToken,
          fromAddress: widget.fromAddress,
          destinationAddress: destination,
          amountSol: _amountController.text.trim(),
          draftPayloadCiphertext: zkEnvelope?.draftPayloadCiphertext,
          senderAddressLookupHash: zkEnvelope?.senderAddressLookupHash,
        );
        final status = (draft['status'] ?? '').toString();
        if (status != 'draft_ready') {
          setState(() {
            _error = (draft['message'] ?? 'Solana draft not ready.').toString();
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
    } finally {
      _draftInFlight = false;
    }
  }

  Future<void> _onConfirmAndSign() async {
    // 2026-07-14 (Round 7 hardening): every entry gate must be
    // idempotent. Duplicate Review/PIN/broadcast taps or a browser
    // back+forward that re-runs this handler MUST be a no-op.
    if (_broadcastInFlight) return;
    if (_stage == _SolanaSendStage.submitted ||
        _stage == _SolanaSendStage.expired ||
        _stage == _SolanaSendStage.rejected ||
        _stage == _SolanaSendStage.uncertain) {
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
      _stage = _SolanaSendStage.submitting;
      _error = null;
    });

    // 2026-07-14 (Round 8 hardening): full pre-sign gate chain.
    //
    //   1. Integer-exact lamport authorization (fail closed on
    //      missing hook / null balance / malformed persisted
    //      values / insufficient).
    //   2. AUTHORITATIVE pre-secret expiry check via the backend
    //      draft-expiry endpoint (SOL block-height chain
    //      observation). Fail closed if unverifiable.
    //   3. Only if BOTH pass does the flow fetch the encrypted
    //      secret + decrypt + sign.
    //   4. A SECOND authoritative expiry check runs immediately
    //      before broadcast (further below).
    final draftForGate = _draft;
    if (draftForGate == null) {
      _broadcastInFlight = false;
      setState(() {
        _stage = _SolanaSendStage.review;
        _error = kSolanaSendExactFeeUnverifiedError;
      });
      return;
    }
    final gateError = await _verifyExactLamportAuthorization(
      draft: draftForGate,
    );
    if (gateError != null) {
      _broadcastInFlight = false;
      setState(() {
        _stage = _SolanaSendStage.review;
        _error = gateError;
      });
      return;
    }
    // Pre-secret expiry check.
    final preSecretExpiry = await _verifyDraftExpiryFailClosed(
      draft: draftForGate,
    );
    if (preSecretExpiry != null) {
      _broadcastInFlight = false;
      setState(() {
        _stage = _SolanaSendStage.expired;
        _error = preSecretExpiry;
      });
      return;
    }

    _idempotencyKey ??= (widget.idempotencyKeyGenerator != null)
        ? widget.idempotencyKeyGenerator!()
        : _defaultIdempotencyKey();

    Uint8List? plaintextSeed;
    Uint8List? plaintextSecret64;
    try {
      Map<String, dynamic> parsed;
      const walletV2Read =
          bool.fromEnvironment('WALLET_V2_READ_ENABLED', defaultValue: false);
      if (walletV2Read) {
        final repo = WalletV2Repository.current(
            api: widget.client, authToken: widget.authToken);
        if (repo == null) throw StateError('wallet_v2_requires_active_mvk');
        final envelope =
            await repo.find(chain: 'solana', publicAddress: widget.fromAddress);
        if (envelope == null) throw StateError('wallet_v2_not_found');
        parsed = await repo.decrypt(envelope);
      } else {
        final secretResp = await widget.client
            .getCryptoWalletEncryptedSecretNetwork(
                network: kSolanaNetworkId,
                asset: kSolanaAssetTicker,
                authToken: widget.authToken);
        if ((secretResp['wallet_engine'] ?? '').toString() !=
            'encrypted_secret_ready') {
          throw StateError('legacy_wallet_secret_unavailable');
        }
        final ct = (secretResp['encryptedWalletSecret'] ?? '').toString();
        if (ct.isEmpty) throw StateError('legacy_wallet_ciphertext_missing');
        final decodedPayload = jsonDecode(await widget.decryptForVault(ct));
        if (decodedPayload is! Map<String, dynamic>)
          throw StateError('legacy_wallet_secret_invalid');
        parsed = decodedPayload;
      }
      if (parsed.isEmpty) {
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
        fromAddressBase58: widget.fromAddress,
        destinationAddressBase58:
            (draft['destinationAddress'] ?? '').toString(),
        lamports: lamports,
        recentBlockhashBase58: (draft['recentBlockhash'] ?? '').toString(),
        ed25519Seed32: plaintextSeed,
      );

      wipeSecretKey(plaintextSecret64);
      wipeSecretKey(plaintextSeed);
      plaintextSecret64 = null;
      plaintextSeed = null;

      // 2026-07-14 (Round 8 hardening): SECOND authoritative
      // expiry check IMMEDIATELY before broadcast. Catches drafts
      // whose lastValidBlockHeight passed between the pre-secret
      // verify and now (the signing step + secret decrypt may
      // take hundreds of milliseconds). If this check flags
      // expired, we do NOT broadcast — the signed transaction is
      // discarded and the user is told the draft expired.
      final preBroadcastExpiry = await _verifyDraftExpiryFailClosed(
        draft: draft,
      );
      if (preBroadcastExpiry != null) {
        _broadcastInFlight = false;
        setState(() {
          _stage = _SolanaSendStage.expired;
          _error = preBroadcastExpiry;
        });
        return;
      }

      // 2026-07-14 (Round 7 hardening): draftId echoed to the
      // backend so the SOL state machine can enforce single-attempt
      // + record broadcast_outcome per draft.
      final draftIdEcho = (draft['draftId'] ?? '').toString();
      final broadcastResp =
          await widget.client.broadcastCryptoWalletSignedTransactionNetwork(
        network: kSolanaNetworkId,
        asset: kSolanaAssetTicker,
        authToken: widget.authToken,
        signedTransaction: signed.wireTransaction.base64,
        idempotencyKey: _idempotencyKey,
        draftId: draftIdEcho.isEmpty ? null : draftIdEcho,
      );
      final broadcastStatus = (broadcastResp['status'] ?? '').toString();
      // Honest outcome classification. Round-6 backend returns:
      //   submitted / already_submitted            → success
      //   submission_uncertain                     → uncertain
      //   broadcast_rejected / broadcast_failed    → rejected
      //   draft_expired                            → expired
      if (broadcastStatus == 'submitted' ||
          broadcastStatus == 'already_submitted') {
        _notifyOptimisticDebit(
          signature: (broadcastResp['signature'] ?? '').toString(),
          draft: draft,
        );
        unawaited(_persistZkOutgoingHistorySol(
          draft: draft,
          signature: (broadcastResp['signature'] ?? '').toString(),
          outcome: broadcastStatus,
        ));
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.submitted;
          _submitted = broadcastResp;
        });
        _startStatusPolling();
      } else if (broadcastStatus == 'submission_uncertain') {
        _notifyOptimisticDebit(
          signature: (broadcastResp['signature'] ?? '').toString(),
          draft: draft,
        );
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.uncertain;
          _submitted = broadcastResp;
        });
      } else if (broadcastStatus == 'broadcast_rejected' ||
          broadcastStatus == 'broadcast_failed') {
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.rejected;
          _submitted = broadcastResp;
        });
      } else if (broadcastStatus == 'draft_expired') {
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.expired;
          _submitted = broadcastResp;
        });
      } else {
        setState(() {
          _broadcastInFlight = false;
          _stage = _SolanaSendStage.review;
          _error = (broadcastResp['message'] ?? kSolanaSendBroadcastFailedCopy)
              .toString();
        });
      }
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

  // 2026-07-14 (Round 8 hardening): integer-exact lamport
  // authorization gate. FAIL CLOSED.
  //
  //   * `fetchAvailableLamports == null`  → block
  //   * balance fetch throws               → block
  //   * balance null                       → block
  //   * malformed persisted lamport/fee    → block
  //   * value + fee > available            → block
  //   * exact equality                     → allow
  //
  // BigInt end-to-end. Runs AFTER PIN verify, BEFORE encrypted-
  // secret fetch. Backend gate is additive; it is NOT permission
  // for this frontend gate to silently skip.
  Future<String?> _verifyExactLamportAuthorization({
    required Map<String, dynamic> draft,
  }) async {
    if (widget.fetchAvailableLamports == null) {
      // Production Send paths MUST wire this hook. Tests that omit
      // it deliberately are broken by design; the correct policy is
      // to block.
      return kSolanaSendExactFeeUnverifiedError;
    }
    // Prefer the draft-persisted fee (`feeLamports`) over any
    // client-computed number — this is the SAME figure the backend
    // wrote to the DB row, so the client authorization exactly
    // mirrors what the state machine will enforce.
    final rawValue = (draft['lamports'] ?? '').toString();
    final rawFee = (draft['feeLamports'] ?? '').toString();
    if (rawValue.isEmpty || rawFee.isEmpty) {
      return kSolanaSendExactFeeUnverifiedError;
    }
    final BigInt? valueLamports = BigInt.tryParse(rawValue);
    final BigInt? feeLamports = BigInt.tryParse(rawFee);
    if (valueLamports == null ||
        feeLamports == null ||
        valueLamports < BigInt.zero ||
        feeLamports < BigInt.zero) {
      return kSolanaSendExactFeeUnverifiedError;
    }
    BigInt? available;
    try {
      available = await widget.fetchAvailableLamports!();
    } catch (_) {
      available = null;
    }
    if (available == null) {
      return kSolanaSendExactFeeUnverifiedError;
    }
    final BigInt required = valueLamports + feeLamports;
    if (required > available) {
      return kSolanaSendInsufficientLamportsError;
    }
    return null;
  }

  // 2026-07-14 (Round 8 hardening): SOL Max button.
  //
  //   maxLamports = availableLamports - persistedFeeLamports
  //
  // BigInt only. Fail-closed on:
  //   * no `_draft` yet (fee unknown; use Review first)
  //   * `fetchAvailableLamports` returns null / throws
  //   * result <= 0 (nothing to send after fee)
  //
  // The final draft is still revalidated by
  // `_verifyExactLamportAuthorization` before signing — Max does
  // NOT replace the gate.
  Future<void> _onMaxTap() async {
    // 2026-07-14 (Round 10 — Max UX): SOL Max = verified lamports
    // minus authoritative fee-estimate for a transfer to the
    // destination the user has entered. NO persisted draft
    // required. Fee-estimate call goes to the dedicated endpoint;
    // any failure surfaces a simple "temporarily unavailable"
    // message.
    final destination = _destinationController.text.trim();
    if (destination.isEmpty || !isValidSolanaAddress(destination)) {
      setState(() {
        _error = kSolanaSendMaxRequiresDestinationError;
      });
      return;
    }
    if (widget.fetchAvailableLamports == null) {
      setState(() {
        _error = kSolanaSendMaxBalanceUnverifiedError;
      });
      return;
    }
    BigInt? available;
    try {
      available = await widget.fetchAvailableLamports!();
    } catch (_) {
      available = null;
    }
    if (available == null) {
      setState(() {
        _error = kSolanaSendMaxBalanceUnverifiedError;
      });
      return;
    }
    final BigInt? feeLamports = await _fetchAuthorizedMaxFeeLamports(
      destination: destination,
    );
    if (feeLamports == null || feeLamports <= BigInt.zero) {
      setState(() {
        _error = kSolanaSendMaxTemporarilyUnavailableError;
      });
      return;
    }
    final BigInt target = available - feeLamports;
    if (target <= BigInt.zero) {
      setState(() {
        _error = kSolanaSendInsufficientLamportsError;
      });
      return;
    }
    _amountController.text = _lamportsToSolString(target);
    setState(() {
      _error = null;
    });
  }

  Future<BigInt?> _fetchAuthorizedMaxFeeLamports({
    required String destination,
  }) async {
    Map<String, dynamic>? resp;
    try {
      resp = await widget.client.postCryptoWalletSendFeeEstimateNetwork(
        network: kSolanaNetworkId,
        fromAddress: widget.fromAddress,
        destinationAddress: destination,
        asset: 'SOL',
        authToken: widget.authToken,
      );
    } catch (_) {
      return null;
    }
    if (resp['status'] != 'fee_estimate_ready') return null;
    final raw = (resp['authorizedMaxFeeBaseUnits'] ?? '').toString();
    return BigInt.tryParse(raw);
  }

  static String _lamportsToSolString(BigInt lamports) {
    final divisor = BigInt.from(10).pow(9);
    final whole = lamports ~/ divisor;
    final frac = lamports - whole * divisor;
    if (frac == BigInt.zero) return whole.toString();
    final fracStr = frac.toString().padLeft(9, '0');
    final trimmed = fracStr.replaceFirst(RegExp(r'0+$'), '');
    return trimmed.isEmpty ? whole.toString() : '$whole.$trimmed';
  }

  // 2026-07-14 (Round 8 hardening): authoritative pre-sign +
  // pre-broadcast expiry verification via the backend. Fetches
  // current chain block height and compares against the persisted
  // `last_valid_block_height`. FAIL CLOSED on:
  //
  //   * missing draftId
  //   * network error contacting the endpoint
  //   * `expired: null` in the response (RPC unverifiable)
  //   * `expired: true`
  //
  // Only `expired: false` allows the flow to continue.
  Future<String?> _verifyDraftExpiryFailClosed({
    required Map<String, dynamic> draft,
  }) async {
    final draftId = (draft['draftId'] ?? '').toString();
    if (draftId.isEmpty) {
      return kSolanaSendExactFeeUnverifiedError;
    }
    Map<String, dynamic>? resp;
    try {
      resp = await widget.client.getCryptoWalletDraftExpiryNetwork(
        network: kSolanaNetworkId,
        draftId: draftId,
        authToken: widget.authToken,
      );
    } catch (_) {
      // Fail-closed on transport error — never assume "not expired"
      // because the endpoint was unreachable.
      return kSolanaSendDraftExpiredError;
    }
    // Strict fail-closed: ONLY `expired: false` (canonical bool) is
    // an allow. Anything else — null, missing field, string 'true'/
    // 'false', numeric 0/1, or any other unexpected shape — is
    // treated as unverifiable and BLOCKS. This prevents a malformed
    // backend envelope from becoming a silent green light.
    final expired = resp['expired'];
    if (expired is bool && expired == false) {
      return null;
    }
    return kSolanaSendDraftExpiredError;
  }

  void _notifyOptimisticDebit({
    required String signature,
    required Map<String, dynamic> draft,
  }) {
    final cb = widget.onSuccessfulBroadcast;
    if (cb == null) return;
    final BigInt valueLamports = BigInt.tryParse(
          (draft['lamports'] ?? '0').toString(),
        ) ??
        BigInt.zero;
    final BigInt feeLamports = BigInt.tryParse(
          (draft['feeLamports'] ?? '0').toString(),
        ) ??
        BigInt.zero;
    cb(signature: signature, debitLamports: valueLamports + feeLamports);
  }

  Future<void> _persistZkOutgoingHistorySol({
    required Map<String, dynamic> draft,
    required String signature,
    required String outcome,
  }) async {
    try {
      if (signature.isEmpty) return;
      final env = await zk_history_helper.buildZkOutgoingHistoryEnvelope(
        activeMvk: zk_mvk_store.ZkActiveMvk.current(),
        signature: signature,
        senderAddress: widget.fromAddress,
        destinationAddress: (draft['destinationAddress'] ?? '').toString(),
        asset: kSolanaAssetTicker,
        amount: (draft['amountSol'] ?? draft['lamports'] ?? '').toString(),
        outcome: outcome,
      );
      if (env == null) return;
      await widget.client.postCryptoOutgoingHistoryCiphertext(
        authToken: widget.authToken,
        network: 'solana',
        signatureLookupHash: env.signatureLookupHash,
        outcomePayloadCiphertext: env.outcomePayloadCiphertext,
      );
    } catch (_) {}
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
        final resp =
            await widget.client.getCryptoWalletTransactionStatusNetwork(
          network: kSolanaNetworkId,
          asset: kSolanaAssetTicker,
          txHash: sig,
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
      case _SolanaSendStage.uncertain:
      case _SolanaSendStage.rejected:
      case _SolanaSendStage.expired:
        return WalletSendScaffold(
          sheetKey: 'solana_send_panel',
          header: header,
          body: _buildResultStage(),
        );
    }
  }

  // 2026-07-14 (Round 7 hardening): honest result screen. Selects
  // heading + body copy + action buttons based on the terminal
  // stage set by the broadcast handler.
  Widget _buildResultStage() {
    String heading;
    String body;
    bool showViewActivity = true;
    bool showCheckStatus = false;
    bool showReturnForm = false;
    switch (_stage) {
      case _SolanaSendStage.submitted:
        heading = kSolanaSendResultHeadingSubmitted;
        body = kSolanaSendSubmittedBody;
        break;
      case _SolanaSendStage.uncertain:
        heading = kSolanaSendResultHeadingUncertain;
        body = kSolanaSendResultBodyUncertain;
        showCheckStatus = true;
        break;
      case _SolanaSendStage.rejected:
        heading = kSolanaSendResultHeadingRejected;
        body = kSolanaSendResultBodyRejected;
        showViewActivity = false;
        showReturnForm = true;
        break;
      case _SolanaSendStage.expired:
        heading = kSolanaSendResultHeadingExpired;
        body = kSolanaSendDraftExpiredError;
        showViewActivity = false;
        showReturnForm = true;
        break;
      default:
        heading = kSolanaSendSubmittedHeading;
        body = kSolanaSendSubmittedBody;
    }
    final sig = (_submitted?['signature'] ?? '').toString();
    return _buildSubmittedResultCard(
      heading: heading,
      body: body,
      signature: sig,
      showViewActivity: showViewActivity,
      showCheckStatus: showCheckStatus,
      showReturnForm: showReturnForm,
    );
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

  Future<void> _handleScanRecipientQr(BuildContext ctx) async {
    FocusManager.instance.primaryFocus?.unfocus();
    final scanHook = widget.scanRecipientQr;
    final scannedAddress = scanHook != null
        ? await scanHook(ctx, RecipientNetwork.solana, null)
        : await showScanRecipientQrSheet(
            context: ctx,
            network: RecipientNetwork.solana,
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
          key: const Key(kSolanaSendDestinationInputKey),
          controller: _destinationController,
          focusNode: _destFocus,
          textInputAction: TextInputAction.next,
          autocorrect: false,
          enableSuggestions: false,
          onSubmitted: (_) => _amountFocus.requestFocus(),
          decoration: InputDecoration(
            labelText: kSolanaSendDestinationLabel,
            isDense: true,
            suffixIcon: IconButton(
              key: const Key('solana_send_panel_scan_qr_btn'),
              icon: const Icon(Icons.qr_code_scanner_rounded),
              tooltip: 'Scan recipient QR',
              onPressed: () => _handleScanRecipientQr(context),
            ),
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key(kSolanaSendAmountInputKey),
          controller: _amountController,
          focusNode: _amountFocus,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _amountFocus.unfocus(),
          decoration: InputDecoration(
            labelText: kSolanaSendAmountLabel,
            isDense: true,
            // 2026-07-14 (Round 8 hardening): Max button using
            // authoritative persisted fee lamports from the most
            // recently drafted transaction. If no draft has been
            // created this session, Max fails closed with an
            // honest message. NEVER a hard-coded fee fallback.
            suffixIcon: TextButton(
              key: const Key('solana_send_panel_max_btn'),
              onPressed: _onMaxTap,
              child: const Text(
                kSolanaSendMaxActionLabel,
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
      key: const Key(kSolanaSendReviewButtonKey),
      // 2026-07-14 (Round 8 hardening): Review disabled while
      // drafting so a rapid double-tap cannot spawn a second draft
      // API call.
      onPressed: _draftInFlight ? null : _onReview,
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
          label: 'From',
          value: widget.fromAddress,
          mono: true,
        ),
        WalletSendKvRow(
          label: 'Destination',
          value: (draft['destinationAddress'] ?? '').toString(),
          mono: true,
        ),
        WalletSendKvRow(
          label: 'Amount',
          value: '${draft['amountSol']} SOL',
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
      onPressed: _broadcastInFlight ? null : _onConfirmAndSign,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: Text(
        _broadcastInFlight ? 'Submitting…' : kSolanaSendConfirmButtonLabel,
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
    return _buildSubmittedResultCard(
      heading: kSolanaSendSubmittedHeading,
      body: kSolanaSendSubmittedBody,
      signature: (_submitted?['signature'] ?? '').toString(),
      showViewActivity: true,
      showCheckStatus: false,
      showReturnForm: false,
    );
  }

  // 2026-07-14 (Round 7 hardening): honest-result-screen card
  // shared by submitted / uncertain / rejected / expired.
  Widget _buildSubmittedResultCard({
    required String heading,
    required String body,
    required String signature,
    required bool showViewActivity,
    required bool showCheckStatus,
    required bool showReturnForm,
  }) {
    final isSuccess = _stage == _SolanaSendStage.submitted;
    final isUncertain = _stage == _SolanaSendStage.uncertain;
    final headingColor = isSuccess
        ? kWalletAccentSuccess
        : (isUncertain ? kWalletAccentWarning : kWalletAccentDanger);
    return Container(
      key: const Key(kSolanaSendSubmittedCardKey),
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
            key: const Key('solana_send_panel_result_heading'),
            style: TextStyle(
              color: headingColor,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            body,
            key: const Key('solana_send_panel_result_body'),
            style: TextStyle(
              color: headingColor,
              fontSize: 13,
            ),
          ),
          if (isSuccess || isUncertain) ...[
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
          ],
          if (signature.isNotEmpty) ...[
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
          if (showCheckStatus) ...[
            const SizedBox(height: 6),
            OutlinedButton(
              key: const Key('solana_send_panel_check_status_btn'),
              onPressed: () {
                _statusPollActive = false;
                _startStatusPolling();
              },
              style: walletGhostButtonStyle(),
              child: const Text(kSolanaSendCheckStatusLabel),
            ),
          ],
          if (showViewActivity && widget.onViewActivity != null) ...[
            const SizedBox(height: 6),
            OutlinedButton(
              key: const Key('solana_send_panel_view_activity_btn'),
              onPressed: widget.onViewActivity,
              style: walletGhostButtonStyle(),
              child: const Text(kSolanaSendViewActivityLabel),
            ),
          ],
          if (showReturnForm) ...[
            const SizedBox(height: 6),
            OutlinedButton(
              key: const Key('solana_send_panel_return_form_btn'),
              onPressed: () {
                setState(() {
                  _stage = _SolanaSendStage.input;
                  _submitted = null;
                  _error = null;
                });
              },
              style: walletGhostButtonStyle(),
              child: const Text(kSolanaSendReturnFormLabel),
            ),
          ],
        ],
      ),
    );
  }
}
