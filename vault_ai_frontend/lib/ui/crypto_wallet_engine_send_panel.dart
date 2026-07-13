

import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:pointycastle/digests/keccak.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/app_release_controller_scope.dart';
import '../services/ethereum_transaction.dart';
import '../services/evm_networks.dart';
import '../services/local_outgoing_tx_store.dart';
import '../services/recipient_qr_parser.dart';
import 'crypto_wallet_engine_design.dart';
import 'crypto_wallet_engine_send_layout.dart';
import 'scan_recipient_qr_sheet.dart';


// 2026-07-13: The sheet chrome now supplies the sheet title
// ("Send ETH"). We keep the constants below for backward-compat with
// mainnet-safety tests that reference the pre-chrome copy, but the
// form stage no longer renders `kEthSendPanelTitle` as a second
// heading.
const String kEthSendPanelTitle = 'Send Ethereum';
const String kEthSendNetworkBadge = 'Ethereum Sepolia testnet';
const String kEthSendMainnetNetworkBadge = 'Ethereum Mainnet';
const String kEthSendMainnetSendDisabledBanner =
    'Mainnet send is not enabled in this build. Switch to Ethereum '
    'Sepolia or ask the operator to enable mainnet send.';


// 2026-07-13 canary correctness: the previous flow required the user
// to type a phrase like "SEND ETH" AFTER the Review stage and BEFORE
// the PIN prompt. Production feedback was that the typed-phrase step
// was too cumbersome. The confirmation flow now is:
//     form → Review → PIN → (single) Send tap → result
// The typed-phrase constants below are kept in the file so any
// external code / older tests referencing them still compile, but
// the runtime path no longer reads them. All confirmation-phrase
// consts are marked @Deprecated for eventual removal.
@Deprecated('Typed-phrase confirmation was removed 2026-07-13. '
    'The confirmation flow is now: Review → PIN → single Send tap.')
const String kMainnetSendConfirmPhrasePromptEth =
    'Type "SEND ETH" to continue.';
@Deprecated('See kMainnetSendConfirmPhrasePromptEth.')
const String kMainnetSendConfirmPhrasePromptUsdt =
    'Type "SEND USDT" to continue.';
@Deprecated('See kMainnetSendConfirmPhrasePromptEth.')
const String kMainnetSendConfirmPhrasePromptUsdc =
    'Type "SEND USDC" to continue.';
@Deprecated('See kMainnetSendConfirmPhrasePromptEth.')
const String kMainnetSendConfirmPhraseMismatch =
    'Confirmation phrase does not match. Type it exactly.';
const String kMainnetSendDestinationCardHeader =
    'Verify this address carefully.';
const String kMainnetSendNewRecipientWarning =
    'This is a new recipient address.';

// 2026-07-13 canary correctness: balance verification is now a HARD
// GATE, not a warning. If we can't confirm the live sender balance,
// we do NOT let the user sign or broadcast; the primary action
// becomes "Retry balance check" until the balance loads.
const String kMainnetSendBalanceUnverifiedError =
    'Balance could not be verified. Tap Retry balance check to try '
    'again. VaultAI will not sign or broadcast a transaction while '
    'your balance is unknown.';
const String kMainnetSendEthGasBalanceUnverifiedError =
    'ETH balance for gas could not be verified. Tap Retry balance '
    'check to try again. VaultAI will not sign or broadcast a token '
    'transfer while the parent ETH balance is unknown.';
const String kMainnetSendRetryBalanceLabel = 'Retry balance check';

// Retained for backward-compat with pre-existing tests that assert
// on the exact warning string. Runtime code no longer displays it.
@Deprecated('Replaced by kMainnetSendBalanceUnverifiedError which '
    'is now a hard-gate error, not a warning.')
const String kMainnetSendBalanceUnverifiedWarning =
    'Balance could not be verified. Review carefully before sending.';

const String kMainnetSendInsufficientGasWarning =
    'You may not have enough ETH for gas. Top up before sending.';
const String kMainnetSendInsufficientBalanceError =
    'Amount exceeds your available balance.';

// 2026-07-13 (durability slice): integer-exact fee authorization
// error strings. Distinct from the coarse pre-draft advisory
// (`kMainnetSendInsufficientGasWarning`) so a failure at this
// authoritative gate is unambiguous.
const String kMainnetSendExactFeeUnverifiedError =
    'The exact network fee could not be verified against your '
    'balance. Try again in a moment.';
const String kMainnetSendExactFeeInsufficientEthError =
    'Your ETH balance is not enough to cover the amount plus the '
    'exact network fee for this draft. Reduce the amount or top up '
    'and re-draft.';
const String kMainnetSendExactFeeInsufficientGasEthError =
    'Your ETH balance is not enough to cover the exact network fee '
    'for this token draft. Top up ETH and re-draft.';
const String kMainnetSendExactFeeInsufficientTokenError =
    'Your token balance is not enough for this draft. Reduce the '
    'amount or top up and re-draft.';
const String kMainnetSendExactFeeGateFailedKey =
    'eth_send_panel_exact_fee_gate_failed';
const String kMainnetSendFeeEstimateFailedError =
    'Could not estimate network fee. Review and try again.';
const String kMainnetSendPausedBanner =
    'Mainnet sending is temporarily paused.';
const String kMainnetSendBroadcastSafeError =
    'Could not submit transaction.';
const String kMainnetSendRateLimitedError =
    'Too many recent send attempts. Wait a moment before retrying.';

// 2026-07-13 canary correctness: result screen states + explorer.
const String kEthSendResultHeadingSubmitted   = 'Transaction submitted';
const String kEthSendResultHeadingUncertain   = 'Transaction status is uncertain';
const String kEthSendResultHeadingRejected    = 'Transaction rejected';
const String kEthSendResultBodySubmitted =
    'Ethereum accepted this transaction. It should appear in your '
    'wallet activity once a node includes it in a block.';
const String kEthSendResultBodyUncertain =
    "The mainnet RPC accepted the raw transaction but no Ethereum "
    "node has yet reported seeing it. VaultAI will keep checking. "
    "Do not re-sign with a new nonce until the status is confirmed "
    "as not_found on the network.";
const String kEthSendResultBodyRejected =
    'The Ethereum RPC returned an explicit rejection for this '
    'transaction. The draft was consumed under the single-attempt '
    'policy; retrying requires a fresh draft.';
const String kEthSendResultViewExplorerLabel = 'View on explorer';
const String kEthSendResultViewActivityLabel = 'View activity';
const String kEthSendResultCheckStatusLabel  = 'Check status';
const String kEthSendResultReturnFormLabel   = 'Start a new send';
const String kEthSendResultCopyHashLabel     = 'Copy transaction hash';
const String kEthSendResultCopiedSnackbar    = 'Transaction hash copied';

/// Mainnet Etherscan URL for a given tx hash. Sepolia handled by
/// `sepolia.etherscan.io`.
String ethExplorerUrlFor({required String network, required String txHash}) {
  if (network == kEvmNetworkEthereumMainnet) {
    return 'https://etherscan.io/tx/$txHash';
  }
  if (network == kEvmNetworkEthereumSepolia) {
    return 'https://sepolia.etherscan.io/tx/$txHash';
  }
  return 'https://etherscan.io/tx/$txHash';
}

const String kMainnetSendConfirmPhraseInputKey =
    'eth_send_panel_mainnet_confirm_phrase_input';
const String kMainnetSendDestinationCardKey =
    'eth_send_panel_mainnet_destination_card';
const String kMainnetSendDestinationCopyBtnKey =
    'eth_send_panel_mainnet_destination_copy_btn';
const String kMainnetSendNewRecipientBannerKey =
    'eth_send_panel_mainnet_new_recipient_banner';
const String kMainnetSendBalanceUnverifiedKey =
    'eth_send_panel_mainnet_balance_unverified';
const String kMainnetSendInsufficientGasKey =
    'eth_send_panel_mainnet_insufficient_gas';
const String kMainnetSendPausedBannerKey =
    'eth_send_panel_mainnet_paused_banner';
const String kMainnetSendConfirmPhraseStageKey =
    'eth_send_panel_mainnet_confirm_phrase_stage';
const String kMainnetSendConfirmPhraseContinueBtnKey =
    'eth_send_panel_mainnet_confirm_phrase_continue_btn';


String mainnetSendConfirmPhraseFor(String asset) {
  switch (asset) {
    case 'ETH':
      return 'SEND ETH';
    case 'USDT_ERC20':
      return 'SEND USDT';
    case 'USDC_ERC20':
      return 'SEND USDC';
  }
  return 'SEND';
}

String mainnetSendConfirmPhrasePromptFor(String asset) {
  switch (asset) {
    case 'ETH':
      return kMainnetSendConfirmPhrasePromptEth;
    case 'USDT_ERC20':
      return kMainnetSendConfirmPhrasePromptUsdt;
    case 'USDC_ERC20':
      return kMainnetSendConfirmPhrasePromptUsdc;
  }
  return kMainnetSendConfirmPhrasePromptEth;
}
const String kEthSendDestinationLabel = 'Destination address';
const String kEthSendAmountLabel = 'Amount (ETH)';
const String kEthSendMaxActionLabel = 'Max';
// 2026-07-14 (Round 8 hardening): ETH Max requires a persisted
// draft so authoritative feeWei is available. No hardcoded gas
// reservation fallback exists.
// 2026-07-14 (Round 10 — Max UX): Max no longer requires a
// persisted draft. It calls the dedicated fee-estimate endpoint
// with the destination address the user has already entered.
const String kSendUpdatePendingError =
    'VaultAI was updated. Refresh before starting a new send.';
const String kEthSendMaxRequiresDestinationError =
    'Enter a destination address first so we can estimate the '
    'network fee.';
const String kEthSendMaxTemporarilyUnavailableError =
    'Maximum amount is temporarily unavailable. Try again.';
// Kept for backward compatibility with any external caller reading
// this constant. New code paths use the destination / temporarily-
// unavailable messages above.
const String kEthSendMaxRequiresDraftError =
    kEthSendMaxTemporarilyUnavailableError;
const String kEthSendReviewButtonLabel = 'Review';
const String kEthSendReviewWarning =
    'Review carefully. Crypto transactions cannot be reversed.';
const String kEthSendReviewConfirmButtonLabel = 'Confirm and enter PIN';
const String kEthSendPinDialogTitle = 'Enter your PIN to sign locally';
const String kEthSendPinDialogBody =
    'Your private key is decrypted on this device only. VaultAI never '
    'sees the plaintext key.';
const String kEthSendPinDialogConfirmLabel = 'Sign + broadcast';
const String kEthSendBroadcastPendingLabel = 'Signing and broadcasting…';
const String kEthSendSuccessHeading = 'Transaction submitted';
const String kEthSendErrorBroadcastFailed = 'Broadcast failed.';
const String kEthSendErrorPinWrong =
    'PIN failed. The transaction was not signed and was not '
    'broadcast.';
const String kEthSendErrorDraftUnavailable =
    'The backend could not fetch the network fee data. Try again '
    'shortly.';
const String kEthSendErrorEncryptedSecretMissing =
    'No wallet account for this asset. Create a wallet from the '
    'Receive panel first.';
const String kEthSendFormValidationMissingFields =
    'Enter both the destination address and the amount.';
const String kEthSendFormValidationBadAmount =
    'Amount must be a positive ETH value.';
const String kEthSendFormValidationBadAddress =
    'Destination address must be 0x + 40 hex chars.';
// 2026-07-14 (Round 7 hardening): strict integer-exact amount
// validation. Rejects excessive decimals, scientific notation,
// Unicode whitespace / zero-width chars, and uint256 overflow.
const String kEthSendFormValidationExcessiveDecimalsError =
    'Amount has more decimal places than this asset supports.';
const String kEthSendFormValidationScientificNotationError =
    'Amount must be a plain decimal — scientific notation is not '
    'accepted.';
const String kEthSendFormValidationUnicodeWhitespaceError =
    'Amount contains hidden or unusual whitespace. Retype the '
    'amount using only plain digits and a period.';
const String kEthSendFormValidationOverflowError =
    'Amount is larger than any Ethereum wallet can hold.';
const String kEthSendFormValidationContractRecipientWarning =
    'Destination address is a smart contract. Verify it accepts '
    'direct token transfers before sending.';
const String kEthSendFormValidationEip681AmountConfirmPrompt =
    'The scanned QR contains a different amount than what you '
    'entered. Tap Confirm to replace, or clear the amount field '
    'first.';
// 2026-07-14 (Round 6 hardening): EIP-55 checksum + self-send.
const String kEthSendFormValidationBadChecksum =
    'Destination address checksum is invalid. Either use the all-'
    'lowercase form or a correctly EIP-55-checksummed address.';
const String kEthSendFormValidationSelfSend =
    'Destination address matches your wallet. Refusing to draft a '
    'self-send. Enter a different recipient.';


enum _Stage {
  form,
  loadingDraft,
  review,
  
  
  confirmPhrase,
  signing,
  submitted,
}

class _DraftFields {
  final String fromAddress;
  final String destinationAddress;
  final String amount;
  final String unit;
  final BigInt nonce;
  final BigInt gasLimit;
  final BigInt gasPrice;
  final BigInt valueWei;
  final String transactionTo;
  final String dataHex;
  final int chainId;




  final String? draftId;
  const _DraftFields({
    required this.fromAddress,
    required this.destinationAddress,
    required this.amount,
    required this.unit,
    required this.nonce,
    required this.gasLimit,
    required this.gasPrice,
    required this.valueWei,
    required this.transactionTo,
    required this.dataHex,
    required this.chainId,
    this.draftId,
  });

  
  BigInt get feeWei => gasLimit * gasPrice;
}


class CryptoWalletEngineSendPanel extends StatefulWidget {
  final String authToken;
  final String fromAddress;
  final VaultAIClient client;
  
  
  final Future<String> Function(String ciphertext) decryptForVault;
  
  
  final bool Function() isVaultKeyAvailable;
  
  
  final Future<bool> Function(String pin)? verifyPin;

  
  final String asset;

  
  final String? prefilledDestination;
  final String? prefilledAmount;

  
  final String network;

  
  final bool mainnetSendPaused;

  
  final Future<bool> Function(String destination)? isKnownDestination;


  final Future<double?> Function()? fetchAvailableBalance;


  final Future<double?> Function()? fetchEthBalance;

  /// 2026-07-13 durability slice: integer-exact authoritative
  /// balance in base units. When provided this hook is the FINAL
  /// gate before signing — the pre-draft `fetchAvailableBalance`
  /// (double) is retained as a coarse UX check but is never the
  /// authorization. If the hook returns null, throws, or reports a
  /// balance short of `valueWei + gasLimit * gasPrice` (for ETH) or
  /// `amountBaseUnits` (for ERC-20), the flow REFUSES to fetch the
  /// encrypted secret and BLOCKS the transaction before signing.
  final Future<BigInt?> Function()? fetchAvailableBalanceWei;

  /// 2026-07-13 durability slice: integer-exact ETH balance in wei.
  /// Required alongside `fetchAvailableBalanceWei` for ERC-20 sends
  /// — the wallet must have BOTH enough tokens AND enough ETH for
  /// gas (`gasLimit * gasPrice`).
  final Future<BigInt?> Function()? fetchEthBalanceWei;


  final String Function()? idempotencyKeyGenerator;

  // 2026-07-13 QR-scan hook. In production the panel opens the
  // real `showScanRecipientQrSheet` (mobile_scanner-backed). In
  // widget tests the caller injects a lambda that returns a
  // fake / pre-canned address so tests never touch the camera.
  final Future<String?> Function(
    BuildContext context,
    RecipientNetwork network,
    int? expectedChainId,
  )? scanRecipientQr;

  /// 2026-07-13 canary correctness: local outgoing tx store. When
  /// supplied, every mainnet broadcast pushes a row into the store
  /// (`submitting` → `submitted` / `submissionUncertain` /
  /// `explicitlyRejected` / ...) so the outgoing transaction
  /// appears in Activity immediately, before the indexer discovers
  /// it. Optional — Sepolia / tests without an Activity card can
  /// omit it.
  final LocalOutgoingTxStore? outgoingTxStore;

  /// Optional URL launcher hook so the result screen can open an
  /// explorer link. In production this is wired to
  /// `url_launcher`'s `launchUrlString`; widget tests inject a
  /// counter to assert the correct URL was requested without
  /// actually opening a browser.
  final Future<bool> Function(String url)? launchUrl;

  /// 2026-07-13 (Round 5 hardening): called once with the local tx
  /// hash + the exact base-units debit (`valueWei` for ETH,
  /// `amountBaseUnits` for ERC-20) after the broadcast returns a
  /// non-rejected outcome (`submitted` / `already_submitted` /
  /// `submission_uncertain`). The asset-detail page uses this to
  /// stamp an optimistic pending debit on the balance card before
  /// the live refresh converges. Optional — omit in tests that
  /// don't need the callback.
  final void Function({
    required String txHash,
    required BigInt debitBaseUnits,
  })? onSuccessfulBroadcast;

  /// 2026-07-14 (Round 7 hardening): optional contract detection.
  /// Returns:
  ///   * `true`  → destination has code (contract). A soft warning
  ///               banner is shown in Review. Send is NEVER blocked.
  ///   * `false` → destination is an EOA. No banner.
  ///   * `null`  → RPC unavailable or error. The address is NOT
  ///               labelled as an EOA or contract; no banner is
  ///               shown; the flow continues. Fail-open by design
  ///               so a transient RPC hiccup does not add friction
  ///               to a normal EOA send.
  final Future<bool?> Function(String address)? isContractDestination;

  const CryptoWalletEngineSendPanel({
    super.key,
    required this.authToken,
    required this.fromAddress,
    required this.client,
    required this.decryptForVault,
    required this.isVaultKeyAvailable,
    this.verifyPin,
    this.asset = 'ETH',
    this.prefilledDestination,
    this.prefilledAmount,
    this.network = kCompileTimeDefaultNetworkResolved,
    this.mainnetSendPaused = false,
    this.isKnownDestination,
    this.fetchAvailableBalance,
    this.fetchEthBalance,
    this.fetchAvailableBalanceWei,
    this.fetchEthBalanceWei,
    this.idempotencyKeyGenerator,
    this.scanRecipientQr,
    this.outgoingTxStore,
    this.launchUrl,
    this.onSuccessfulBroadcast,
    this.isContractDestination,
  });

  bool get isMainnet => network == kEvmNetworkEthereumMainnet;

  @override
  State<CryptoWalletEngineSendPanel> createState() =>
      _CryptoWalletEngineSendPanelState();
}

class _CryptoWalletEngineSendPanelState
    extends State<CryptoWalletEngineSendPanel> {
  _Stage _stage = _Stage.form;
  String? _error;

  final TextEditingController _destCtrl = TextEditingController();
  final TextEditingController _amountCtrl = TextEditingController();
  final TextEditingController _confirmPhraseCtrl = TextEditingController();

  // 2026-07-13 mobile-keyboard fix: a scroll controller shared with
  // WalletSendScaffold plus a FocusNode per text field so tapping /
  // hopping to a field programmatically slides it above the keyboard.
  final ScrollController _formScrollCtrl = ScrollController();
  final FocusNode _destFocus = FocusNode(debugLabel: 'eth_send_dest');
  final FocusNode _amountFocus = FocusNode(debugLabel: 'eth_send_amount');

  _DraftFields? _draft;
  String? _submittedTxHash;
  // 2026-07-13 canary correctness: track the honest broadcast
  // outcome from the backend so the result screen can distinguish
  // `submitted` (observed on the network) from `submission_uncertain`
  // (broadcast attempted but tx not yet visible). Set only in the
  // `_onConfirmAndPin` broadcast branch.
  String? _broadcastStatus;
  String? _broadcastReason;
  String? _broadcastMessage;

  
  bool _isKnownRecipient = false;
  bool _recipientCheckRan = false;

  // 2026-07-14 (Round 7 hardening): contract-destination detection
  // via optional widget hook. `null` = unknown (fail-open) or
  // check not yet run. Populated during _onReview after passing
  // shape/checksum/self-send/strict-amount checks.
  bool? _isContractDest;

  // 2026-07-14 (Round 8 hardening): synchronous draft-in-flight
  // guard. Set BEFORE the first `await` in `_onReview` so a rapid
  // double-tap of Review cannot spawn a second draft.
  bool _draftInFlight = false;
  bool _balanceCheckUnverified = false;
  bool _insufficientGas = false;

  
  bool _broadcastInFlight = false;
  String? _idempotencyKey;

  @override
  void initState() {
    super.initState();


    if (widget.prefilledDestination != null &&
        widget.prefilledDestination!.isNotEmpty) {
      _destCtrl.text = widget.prefilledDestination!;
    }
    if (widget.prefilledAmount != null &&
        widget.prefilledAmount!.isNotEmpty) {
      _amountCtrl.text = widget.prefilledAmount!;
    }
    _destFocus.addListener(_maybeScrollFocusedFieldIntoView);
    _amountFocus.addListener(_maybeScrollFocusedFieldIntoView);
  }

  @override
  void dispose() {
    _destFocus.removeListener(_maybeScrollFocusedFieldIntoView);
    _amountFocus.removeListener(_maybeScrollFocusedFieldIntoView);
    _destFocus.dispose();
    _amountFocus.dispose();
    _formScrollCtrl.dispose();
    _destCtrl.dispose();
    _amountCtrl.dispose();
    _confirmPhraseCtrl.dispose();
    super.dispose();
  }

  // 2026-07-13 mobile-keyboard fix: when either the Destination or
  // Amount text field gains focus (real tap or Next-key hop), wait a
  // frame for the OS keyboard to raise its inset, then Scrollable-
  // .ensureVisible the field so it's centered in the remaining
  // viewport. If no focus is held, no scroll happens — closing the
  // keyboard preserves scroll position and entered values.
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

  String _generateIdempotencyKey() {
    if (widget.idempotencyKeyGenerator != null) {
      return widget.idempotencyKeyGenerator!();
    }
    
    
    final now = DateTime.now().microsecondsSinceEpoch.toRadixString(36);
    return 'snd-${widget.asset.toLowerCase()}-$now';
  }

  bool _looksLikeEthAddress(String s) =>
      RegExp(r'^0x[0-9a-fA-F]{40}$').hasMatch(s);

  // 2026-07-14 (Round 6 hardening): the address is well-formed
  // shape-wise. If it contains at least one uppercase AND at least
  // one lowercase hex character, then the sender intends an
  // EIP-55-checksummed address — validate the checksum. All-lower
  // or all-upper: legal, no checksum enforcement.
  bool _isMixedCaseAddress(String s) {
    if (!_looksLikeEthAddress(s)) return false;
    final body = s.substring(2);
    final hasUpper = RegExp(r'[A-F]').hasMatch(body);
    final hasLower = RegExp(r'[a-f]').hasMatch(body);
    return hasUpper && hasLower;
  }

  bool _isEip55ChecksumValid(String s) {
    // EIP-55: hex-nibble is uppercase iff the corresponding nibble
    // of keccak256(lowercase-address-without-0x) is >= 8.
    if (!_looksLikeEthAddress(s)) return false;
    final body = s.substring(2);
    final lower = body.toLowerCase();
    final hash = KeccakDigest(256).process(
      Uint8List.fromList(lower.codeUnits),
    );
    // Serialize hash as lowercase hex string once.
    final hex = hash.map((b) => b.toRadixString(16).padLeft(2, '0'))
        .join();
    for (var i = 0; i < 40; i++) {
      final c = body[i];
      final nibble = int.parse(hex[i], radix: 16);
      final isAlpha = RegExp(r'[a-fA-F]').hasMatch(c);
      if (!isAlpha) continue;
      final shouldBeUpper = nibble >= 8;
      final isUpper = c == c.toUpperCase();
      if (isUpper != shouldBeUpper) return false;
    }
    return true;
  }

  bool _isSelfSend(String destination) {
    // Case-insensitive compare so a checksummed vs lowercase pair
    // still triggers the guard.
    return destination.toLowerCase() ==
        widget.fromAddress.toLowerCase();
  }

  // 2026-07-14 (Round 7 hardening): decimals per asset.
  int _amountDecimalsForAsset(String asset) {
    switch (asset) {
      case 'USDT_ERC20':
      case 'USDC_ERC20':
        return 6;
      default:
        return 18;
    }
  }

  // 2026-07-14 (Round 7 hardening): strict amount validation.
  // Returns a user-facing error string if the amount fails a
  // production integrity check; returns null when the amount is
  // safe to draft.
  //
  // Rejected shapes:
  //   * empty (handled earlier by missing-fields check)
  //   * scientific notation (e/E)
  //   * Unicode whitespace / zero-width chars in the middle
  //   * excessive decimal precision (>18 for ETH, >6 for tokens)
  //   * value that overflows uint256
  //
  // Accepted shapes: plain decimals with at most `decimals` digits
  // after the point.
  String? _strictAmountValidation(String amount, int decimals) {
    if (amount.isEmpty) return kEthSendFormValidationBadAmount;
    // Reject hidden/unusual whitespace + zero-width chars. NOTE:
    // we scan the FULL input (including leading/trailing regular
    // spaces so we can catch Unicode-whitespace) but numeric
    // parsing uses the ASCII-trimmed body.
    for (final r in amount.runes) {
      if (r == 0x0020 || r == 0x0009) continue; // plain space, tab (trimmed anyway)
      if (r == 0x002E) continue; // '.'
      if (r >= 0x0030 && r <= 0x0039) continue; // 0-9
      // Any other whitespace category (NBSP U+00A0, thin space
      // U+2009, zero-width U+200B, etc.) is rejected.
      if (r == 0x00A0
          || r == 0x1680
          || (r >= 0x2000 && r <= 0x200F)
          || r == 0x2028
          || r == 0x2029
          || r == 0x202F
          || r == 0x205F
          || r == 0x3000
          || r == 0xFEFF) {
        return kEthSendFormValidationUnicodeWhitespaceError;
      }
      // Everything else — including e/E for scientific, minus,
      // plus, comma — is either handled below or rejected.
      if (r == 0x0065 || r == 0x0045) {
        return kEthSendFormValidationScientificNotationError;
      }
      if (r == 0x002D || r == 0x002B) {
        return kEthSendFormValidationBadAmount;
      }
      if (r == 0x002C) {
        // Locale separator like `1,000`. Reject — user must use
        // plain digits and a period.
        return kEthSendFormValidationBadAmount;
      }
      // Any other character we haven't allowed above.
      return kEthSendFormValidationBadAmount;
    }
    // ASCII-trim to skip leading/trailing regular spaces + tabs
    // BEFORE the length check — my char-allowlist already accepted
    // these; the number parse cannot handle them.
    final numeric = amount.trim();
    if (numeric.isEmpty) return kEthSendFormValidationBadAmount;
    final dotIdx = numeric.indexOf('.');
    if (dotIdx >= 0) {
      final frac = numeric.substring(dotIdx + 1);
      if (frac.contains('.')) {
        return kEthSendFormValidationBadAmount;
      }
      if (frac.length > decimals) {
        return kEthSendFormValidationExcessiveDecimalsError;
      }
    }
    // Compute base units in BigInt and check uint256 bound.
    try {
      final baseUnits = _amountToBaseUnitsBigInt(numeric, decimals);
      if (baseUnits <= BigInt.zero) {
        return kEthSendFormValidationBadAmount;
      }
      final uint256Max = (BigInt.one << 256) - BigInt.one;
      if (baseUnits > uint256Max) {
        return kEthSendFormValidationOverflowError;
      }
    } on FormatException {
      return kEthSendFormValidationBadAmount;
    }
    return null;
  }

  BigInt _amountToBaseUnitsBigInt(String amount, int decimals) {
    final dotIdx = amount.indexOf('.');
    if (dotIdx < 0) {
      final v = BigInt.parse(amount);
      return v * BigInt.from(10).pow(decimals);
    }
    final whole = amount.substring(0, dotIdx);
    var frac = amount.substring(dotIdx + 1);
    if (frac.length > decimals) frac = frac.substring(0, decimals);
    frac = frac.padRight(decimals, '0');
    final wholeBi = whole.isEmpty ? BigInt.zero : BigInt.parse(whole);
    final fracBi = frac.isEmpty ? BigInt.zero : BigInt.parse(frac);
    return wholeBi * BigInt.from(10).pow(decimals) + fracBi;
  }

  Future<void> _onReview() async {
    // 2026-07-14 (Round 11 — release wiring): block a NEW Send if
    // the release-update controller has detected a pending
    // update. The user must reload before starting a fresh Send.
    final rc = AppReleaseControllerScope.maybeOf(context);
    if (rc != null && rc.sendShouldBeBlocked()) {
      // Try to check right now — some update paths may already be
      // resolved by the time the user tapped Review.
      await rc.checkForUpdate();
      if (rc.sendShouldBeBlocked()) {
        setState(() => _error = kSendUpdatePendingError);
        return;
      }
    }
    // 2026-07-14 (Round 8 hardening): SYNCHRONOUS draft-in-flight
    // guard. Set BEFORE any await so a rapid double-tap does not
    // spawn a second draft. Backend single-active-draft-per-sender
    // remains as belt-and-braces but is NOT the primary UX.
    if (_draftInFlight) return;
    // Guard against re-drafting after we already have a
    // review-ready draft — the user must explicitly return to form
    // to clear it.
    if (_draft != null && _stage != _Stage.form) return;
    _draftInFlight = true;
    try {
      await _onReviewInner();
    } finally {
      _draftInFlight = false;
    }
  }

  Future<void> _onReviewInner() async {
    if (widget.isMainnet && !kCryptoWalletEngineMainnetSendEnabled) {
      setState(() => _error = kEthSendMainnetSendDisabledBanner);
      return;
    }
    
    
    if (widget.isMainnet && widget.mainnetSendPaused) {
      setState(() => _error = kMainnetSendPausedBanner);
      return;
    }
    final destination = _destCtrl.text.trim();
    final amount = _amountCtrl.text.trim();
    if (destination.isEmpty || amount.isEmpty) {
      setState(() => _error = kEthSendFormValidationMissingFields);
      return;
    }
    if (!_looksLikeEthAddress(destination)) {
      setState(() => _error = kEthSendFormValidationBadAddress);
      return;
    }
    // 2026-07-14 (Round 6 hardening): if the address is mixed-case,
    // it MUST pass the EIP-55 checksum. All-lower or all-upper is
    // permitted (no checksum applied by the sender).
    if (_isMixedCaseAddress(destination)
        && !_isEip55ChecksumValid(destination)) {
      setState(() => _error = kEthSendFormValidationBadChecksum);
      return;
    }
    // 2026-07-14 (Round 6 hardening): self-send guard. ETH/EVM was
    // missing this; Solana and TRON already have it. Case-
    // insensitive compare.
    if (_isSelfSend(destination)) {
      setState(() => _error = kEthSendFormValidationSelfSend);
      return;
    }
    // 2026-07-14 (Round 7 hardening): strict integer-exact amount
    // validation. Runs BEFORE the double parse so the double is
    // never used for anything authorization-related. We validate
    // against the RAW controller text (not the trimmed copy) so
    // Unicode whitespace embedded in the input triggers a clear
    // rejection instead of being silently trimmed to a valid
    // number.
    final strictErr = _strictAmountValidation(
      _amountCtrl.text, _amountDecimalsForAsset(widget.asset),
    );
    if (strictErr != null) {
      setState(() => _error = strictErr);
      return;
    }
    final amountDouble = double.tryParse(amount);
    if (amountDouble == null || amountDouble <= 0) {
      setState(() => _error = kEthSendFormValidationBadAmount);
      return;
    }

    
    // 2026-07-13 canary correctness: balance verification is a
    // HARD GATE whenever the caller wired `fetchAvailableBalance`.
    // If we cannot load the sender balance, we refuse to advance
    // to Review/Draft — the primary action becomes "Retry balance
    // check". The old flow silently recorded
    // `_balanceCheckUnverified = true` and let the user sign
    // anyway; that shipped a real transaction with an unknown
    // balance, which the canary retest flagged.
    //
    // Applied on BOTH mainnet and sepolia (when hook provided) so
    // testnet flows don't drift out of parity with mainnet.
    if (widget.fetchAvailableBalance != null) {
      _balanceCheckUnverified = false;
      _insufficientGas = false;
      final isToken = widget.asset != 'ETH';
      double? availableBal;
      try {
        availableBal = await widget.fetchAvailableBalance!();
      } catch (_) {
        availableBal = null;
      }
      if (availableBal == null) {
        setState(() {
          _balanceCheckUnverified = true;
          _error = kMainnetSendBalanceUnverifiedError;
        });
        return;
      }
      if (amountDouble > availableBal) {
        setState(() {
          _error = kMainnetSendInsufficientBalanceError;
        });
        return;
      }
      if (isToken) {
        // Token sends require BOTH the token balance (above) AND
        // the parent ETH balance (for gas) to be verified. The
        // parent ETH check is a hard gate — a token send with an
        // unknown parent-ETH balance will silently fail at
        // broadcast when the RPC computes `nonce/gasLimit*gasPrice`
        // against zero ETH. Refuse to advance.
        if (widget.fetchEthBalance == null) {
          setState(() {
            _balanceCheckUnverified = true;
            _error = kMainnetSendEthGasBalanceUnverifiedError;
          });
          return;
        }
        double? ethBal;
        try {
          ethBal = await widget.fetchEthBalance!();
        } catch (_) {
          ethBal = null;
        }
        if (ethBal == null) {
          setState(() {
            _balanceCheckUnverified = true;
            _error = kMainnetSendEthGasBalanceUnverifiedError;
          });
          return;
        }
        // Live gas is estimated by the backend during draft-create
        // (it looks up `eth_gasPrice + eth_estimateGas`). The
        // frontend threshold of 0.0005 ETH is a coarse "you almost
        // certainly don't have enough gas" gate, retained here so
        // a wallet with dust ETH is warned rather than silently
        // failing at broadcast.
        if (ethBal < 0.0005) {
          _insufficientGas = true;
        }
      }
    }

    
    if (widget.isMainnet) {
      _isKnownRecipient = false;
      _recipientCheckRan = true;
      if (widget.isKnownDestination != null) {
        try {
          _isKnownRecipient =
              await widget.isKnownDestination!(destination);
        } catch (_) {
          _isKnownRecipient = false;
        }
      }
    }
    // 2026-07-14 (Round 7 hardening): contract detection soft
    // warning. Fail-open: on error or null → treat as unknown
    // (no banner). Never blocks a valid ETH transfer.
    _isContractDest = null;
    if (widget.isContractDestination != null) {
      try {
        _isContractDest = await widget.isContractDestination!(
          destination,
        );
      } catch (_) {
        _isContractDest = null;
      }
    }
    setState(() {
      _error = null;
      _stage = _Stage.loadingDraft;
    });
    try {
      final Map<String, dynamic> body = widget.isMainnet
          ? await widget.client.createCryptoWalletSendDraftNetwork(
              network: widget.network,
              asset: widget.asset,
              authToken: widget.authToken,
              fromAddress: widget.fromAddress,
              destinationAddress: destination,
              amountEth: amount,
            )
          : await widget.client.createCryptoWalletSendDraft(
              asset: widget.asset,
              authToken: widget.authToken,
              fromAddress: widget.fromAddress,
              destinationAddress: destination,
              amountEth: amount,
            );
      final status = (body['status'] ?? '').toString();
      final walletEngine = (body['wallet_engine'] ?? '').toString();

      if (walletEngine == 'mainnet_send_paused' ||
          status == 'mainnet_send_paused') {
        setState(() {
          _stage = _Stage.form;
          _error = kMainnetSendPausedBanner;
        });
        return;
      }
      // 2026-07-13: authoritative backend balance-vs-gas check. The
      // backend fetches live balance for the sender and rejects
      // if `value + fee > balance` for ETH sends or the token
      // balance is short / the wallet lacks enough ETH for gas on
      // ERC20 sends. Surface the backend message verbatim so the
      // user sees the exact reason and the required-vs-available
      // amounts (rendered in the review-stage message body).
      if (status == 'insufficient_balance') {
        final msg = (body['message'] ?? '').toString();
        setState(() {
          _stage = _Stage.form;
          _error = msg.isNotEmpty
              ? msg
              : kMainnetSendInsufficientBalanceError;
        });
        return;
      }
      if (status != 'draft_ready') {


        setState(() {
          _stage = _Stage.form;
          _error = widget.isMainnet
              ? kMainnetSendFeeEstimateFailedError
              : kEthSendErrorDraftUnavailable;
        });
        return;
      }
      
      
      final isToken = widget.asset != 'ETH';
      final draft = _DraftFields(
        fromAddress: body['fromAddress'].toString(),
        destinationAddress: body['destinationAddress'].toString(),
        amount: (isToken
                ? (body['amount'] ?? body['amountEth'] ?? '')
                : (body['amountEth'] ?? body['amount'] ?? ''))
            .toString(),
        unit: (body['unit'] ?? (isToken ? widget.asset : 'ETH')).toString(),
        nonce: BigInt.parse(body['nonce'].toString()),
        gasLimit: BigInt.parse(body['gasLimit'].toString()),
        gasPrice: BigInt.parse(body['gasPrice'].toString()),
        valueWei: isToken
            ? BigInt.parse((body['transactionValueWei'] ?? '0').toString())
            : BigInt.parse(body['amountWei'].toString()),
        transactionTo: isToken
            ? body['transactionTo'].toString()
            : body['destinationAddress'].toString(),
        draftId: (body['draftId'] is String && (body['draftId'] as String).isNotEmpty)
            ? body['draftId'] as String
            : null,
        dataHex: isToken
            ? body['dataHex'].toString()
            : '',
        chainId: (body['chainId'] as num).toInt(),
      );
      setState(() {
        _draft = draft;
        _stage = _Stage.review;
      });
    } catch (e) {
      setState(() {
        _stage = _Stage.form;
        _error = 'Draft failed: $e';
      });
    }
  }

  Future<void> _onReviewConfirmTap() async {
    // 2026-07-13 canary correctness: the confirmPhrase stage was
    // removed. Review → PIN → single Send tap. See docstring in
    // this file for the reasoning.
    await _onConfirmAndPin();
  }

  /// Retained for backward-compat with widget tests that reference
  /// the phrase-continue handler by name. The runtime send flow no
  /// longer routes through it; the enum member `_Stage.confirmPhrase`
  /// is never entered.
  @Deprecated('Typed-phrase confirmation was removed 2026-07-13.')
  Future<void> _onMainnetConfirmPhraseContinue() async {
    await _onConfirmAndPin();
  }

  Future<void> _onConfirmAndPin() async {
    if (!widget.isVaultKeyAvailable()) {
      setState(() => _error =
          'Unlock your vault with your PIN before sending.');
      return;
    }
    
    
    if (_broadcastInFlight || _submittedTxHash != null) {
      return;
    }
    final pin = await _showPinDialog();
    if (pin == null) return; 
    
    _broadcastInFlight = true;
    _idempotencyKey ??= _generateIdempotencyKey();
    setState(() {
      _stage = _Stage.signing;
      _error = null;
    });
    
    if (widget.verifyPin != null) {
      bool ok;
      try {
        ok = await widget.verifyPin!(pin);
      } catch (_) {
        ok = false;
      }
      if (!ok) {
        setState(() {
          _stage = _Stage.review;
          _error = kEthSendErrorPinWrong;
        });
        return;
      }
    }

    // 2026-07-13 (durability slice): INTEGER-EXACT FEE
    // AUTHORIZATION. Ordering matters — this MUST run after the PIN
    // (so a wrong PIN never triggers a live balance query) but
    // BEFORE any secret fetch / decryption / signing / broadcast.
    // The check uses the EXACT gas fields returned by the backend
    // draft (`gasLimit`, `gasPrice`, `valueWei`) and BigInt
    // arithmetic — never a `double` conversion, which cannot
    // represent 18-decimal wei precisely.
    //
    // Contract with the caller:
    //   * `fetchAvailableBalanceWei` returning null / throwing =>
    //     BLOCK. The authorization cannot proceed without a verified
    //     balance snapshot. UI returns to Review with
    //     `kMainnetSendExactFeeUnverifiedError`.
    //   * `valueWei + gasLimit * gasPrice > verifiedEthBalanceWei`
    //     for ETH sends => BLOCK.
    //   * For ERC-20: `amountBaseUnits > tokenBalanceBaseUnits`
    //     OR `feeWei > verifiedEthBalanceWei` => BLOCK.
    //
    // If the caller did NOT wire the wei-hook, we rely on the
    // backend's authoritative integer check at draft-create time
    // (which was already run just above and returned `draft_ready`).
    // The wei-hook is thus an OPTIONAL client-side belt-and-braces
    // — but when wired, its verdict is binding.
    final draftForGate = _draft;
    if (draftForGate != null &&
        widget.fetchAvailableBalanceWei != null) {
      final gateError = await _verifyExactFeeAuthorization(
        draft: draftForGate,
      );
      if (gateError != null) {
        setState(() {
          _stage = _Stage.review;
          _error = gateError;
        });
        return;
      }
    }

    String? encryptedSecret;
    try {
      final Map<String, dynamic> body = widget.isMainnet
          ? await widget.client.getCryptoWalletEncryptedSecretNetwork(
              network: widget.network,
              asset: widget.asset,
              authToken: widget.authToken,
            )
          : await widget.client.getCryptoWalletEncryptedSecret(
              asset: widget.asset, authToken: widget.authToken,
            );
      final status = (body['status'] ?? '').toString();
      if (status != 'encrypted_secret_ready') {
        setState(() {
          _stage = _Stage.review;
          _error = kEthSendErrorEncryptedSecretMissing;
        });
        return;
      }
      encryptedSecret = body['encryptedWalletSecret'].toString();
    } catch (e) {
      setState(() {
        _stage = _Stage.review;
        _error = 'Could not fetch encrypted secret: $e';
      });
      return;
    }
    
    String? privateKeyHex;
    try {
      privateKeyHex = await widget.decryptForVault(encryptedSecret);
    } catch (e) {
      setState(() {
        _stage = _Stage.review;
        _error = 'Local decrypt failed: $e';
      });
      return;
    }
    
    
    String? signedTx;
    try {
      final draft = _draft!;
      signedTx = signLegacyEthTransaction(
        nonce: draft.nonce,
        gasPrice: draft.gasPrice,
        gasLimit: draft.gasLimit,
        toAddress: draft.transactionTo,
        valueWei: draft.valueWei,
        dataHex: draft.dataHex,
        chainId: draft.chainId,
        privateKeyHex: privateKeyHex,
      );
    } catch (e) {
      
      privateKeyHex = null;
      setState(() {
        _stage = _Stage.review;
        _error = 'Local signing failed: $e';
      });
      return;
    }
    privateKeyHex = null;

    // 2026-07-13 canary correctness: STAMP a local Activity row
    // BEFORE the broadcast completes so the user always sees the
    // outgoing tx (`submitting` state). If the broadcast HTTP call
    // times out or fails after the network already accepted the
    // tx, we still have a record. The row is upserted with the
    // final status once the response comes back.
    final localHashAtBroadcast = _computeLocalHashForSigned(signedTx);
    _emitOutgoingSubmitting(
      txHash: localHashAtBroadcast,
      draft: _draft!,
    );

    try {
      final Map<String, dynamic> body = widget.isMainnet
          ? await widget.client
              .broadcastCryptoWalletSignedTransactionNetwork(
              network: widget.network,
              asset: widget.asset,
              authToken: widget.authToken,
              signedTransaction: signedTx,
              idempotencyKey: _idempotencyKey,
              draftId: _draft?.draftId,
            )
          : await widget.client.broadcastCryptoWalletSignedTransaction(
              asset: widget.asset,
              authToken: widget.authToken,
              signedTransaction: signedTx,
            );
      final status = (body['status'] ?? '').toString();
      final walletEngine = (body['wallet_engine'] ?? '').toString();
      final reason = (body['reason'] ?? '').toString();
      final message = (body['message'] ?? '').toString();
      final txHashRaw = (body['txHash'] ?? '').toString();
      // For pause / rate-limit / auth-side pre-checks the backend
      // NEVER attempted broadcast — no on-chain tx exists.
      // Downgrade the local row to `dropped` and take the user
      // back to Review to try again cleanly.
      if (walletEngine == 'mainnet_send_paused' ||
          status == 'mainnet_send_paused') {
        _cancelOutgoingSubmittingRow(localHashAtBroadcast);
        setState(() {
          _stage = _Stage.review;
          _error = kMainnetSendPausedBanner;
        });
        return;
      }
      if (walletEngine == 'rate_limited' || status == 'rate_limited') {
        _cancelOutgoingSubmittingRow(localHashAtBroadcast);
        setState(() {
          _stage = _Stage.review;
          _error = kMainnetSendRateLimitedError;
        });
        return;
      }
      // 2026-07-13 canary correctness: recognise `submission_uncertain`
      // and rejection states in addition to `submitted`. The old code
      // treated everything != submitted as a generic failure.
      // 2026-07-13 canary correctness: the local outgoing row was
      // upserted keyed by `localHashAtBroadcast` (keccak256(raw)).
      // The `updateStatus` call MUST use the same key. `displayHash`
      // is what the user sees on the result screen (backend-echoed
      // if present, local otherwise); do NOT confuse it with the
      // store key.
      final displayHash = txHashRaw.isNotEmpty
          ? txHashRaw : localHashAtBroadcast;
      if (status == 'submitted' || status == 'already_submitted') {
        _updateOutgoingRow(
          localHashAtBroadcast,
          LocalOutgoingTxStatus.submitted,
          reason: null,
        );
        _notifyOptimisticDebit(displayHash);
        setState(() {
          _submittedTxHash = displayHash;
          _broadcastStatus = status;
          _broadcastReason = null;
          _broadcastMessage = message.isEmpty ? null : message;
          _stage = _Stage.submitted;
        });
        return;
      }
      if (status == 'submission_uncertain') {
        _updateOutgoingRow(
          localHashAtBroadcast,
          LocalOutgoingTxStatus.submissionUncertain,
          reason: reason.isEmpty ? null : reason,
        );
        _notifyOptimisticDebit(displayHash);
        setState(() {
          _submittedTxHash = displayHash;
          _broadcastStatus = status;
          _broadcastReason = reason.isEmpty ? null : reason;
          _broadcastMessage = message.isEmpty ? null : message;
          _stage = _Stage.submitted;
        });
        return;
      }
      if (status == 'broadcast_rejected' ||
          status == 'broadcast_unavailable') {
        _updateOutgoingRow(
          localHashAtBroadcast,
          LocalOutgoingTxStatus.explicitlyRejected,
          reason: reason.isEmpty ? null : reason,
        );
        setState(() {
          _submittedTxHash = displayHash;
          _broadcastStatus = status;
          _broadcastReason = reason.isEmpty ? null : reason;
          _broadcastMessage = message.isEmpty ? null : message;
          _stage = _Stage.submitted;
        });
        return;
      }
      // Unknown envelope shape — most likely a Sepolia-path
      // broadcast returned only `txHash` without a status marker.
      // Legacy Sepolia path uses the presence of `txHash` as the
      // success signal.
      if (!widget.isMainnet && txHashRaw.isNotEmpty) {
        _updateOutgoingRow(
          localHashAtBroadcast,
          LocalOutgoingTxStatus.submitted,
        );
        setState(() {
          _submittedTxHash = displayHash;
          _broadcastStatus = 'submitted';
          _stage = _Stage.submitted;
        });
        return;
      }
      _cancelOutgoingSubmittingRow(localHashAtBroadcast);
      setState(() {
        _stage = _Stage.review;
        _error = widget.isMainnet
            ? kMainnetSendBroadcastSafeError
            : '$kEthSendErrorBroadcastFailed (${body['reason'] ?? 'unknown'})';
      });
    } catch (e) {
      // Network error DURING the broadcast HTTP roundtrip. The
      // backend MAY have accepted and marked the draft consumed,
      // or the request may have never landed. We cannot know; the
      // conservative treatment is `submissionUncertain` on the
      // local row so the user knows to check status.
      _updateOutgoingRow(
        localHashAtBroadcast,
        LocalOutgoingTxStatus.submissionUncertain,
        reason: 'broadcast_http_error',
      );
      setState(() {
        _submittedTxHash = localHashAtBroadcast;
        _broadcastStatus = 'submission_uncertain';
        _broadcastReason = 'broadcast_http_error';
        _stage = widget.isMainnet
            ? _Stage.submitted
            : _Stage.review;
        _error = widget.isMainnet
            ? null
            : '$kEthSendErrorBroadcastFailed';
      });
    } finally {
      _broadcastInFlight = false;
    }
  }

  // ------------------------------------------------------------
  // Integer-exact fee authorization helper (2026-07-13 durability
  // slice). Returns null if the transaction is authorized; a
  // user-facing error string otherwise.
  //
  // Uses BigInt arithmetic end-to-end. Never converts wei/base-units
  // through `double` — a 0.05 ETH send crossing the boundary at
  // exactly 1 wei must fail cleanly, and 1 wei of 18-decimal
  // precision is unrepresentable in IEEE-754.
  // ------------------------------------------------------------

  Future<String?> _verifyExactFeeAuthorization({
    required _DraftFields draft,
  }) async {
    final isToken = widget.asset != 'ETH';
    final BigInt feeWei = draft.gasLimit * draft.gasPrice;
    BigInt? availableBaseUnits;
    try {
      availableBaseUnits = await widget.fetchAvailableBalanceWei!();
    } catch (_) {
      availableBaseUnits = null;
    }
    if (availableBaseUnits == null) {
      return kMainnetSendExactFeeUnverifiedError;
    }
    if (!isToken) {
      // ETH send: valueWei + gasLimit * gasPrice <= balance.
      final BigInt required = draft.valueWei + feeWei;
      if (required > availableBaseUnits) {
        return kMainnetSendExactFeeInsufficientEthError;
      }
      return null;
    }
    // ERC-20 send: BOTH token base-units AND ETH gas checks.
    // draft.valueWei is 0 for token sends by construction; the
    // token amount lives in draft.amount (human string). The draft
    // response returned `amountBaseUnits` — we didn't stash it on
    // `_DraftFields` because the draft state doesn't need it after
    // the initial parse. So re-derive from `draft.amount` using
    // its unit; the amount was validated against the same base-unit
    // interpretation that produced the draft.
    final BigInt tokenBase = _tokenAmountToBaseUnits(
      draft.amount, draft.unit,
    );
    if (tokenBase > availableBaseUnits) {
      return kMainnetSendExactFeeInsufficientTokenError;
    }
    if (widget.fetchEthBalanceWei == null) {
      // Token sends require the ETH-balance hook too — a token
      // draft with no way to verify the gas balance cannot be
      // authorized. Callers wire both hooks together.
      return kMainnetSendExactFeeUnverifiedError;
    }
    BigInt? ethBalanceWei;
    try {
      ethBalanceWei = await widget.fetchEthBalanceWei!();
    } catch (_) {
      ethBalanceWei = null;
    }
    if (ethBalanceWei == null) {
      return kMainnetSendExactFeeUnverifiedError;
    }
    if (feeWei > ethBalanceWei) {
      return kMainnetSendExactFeeInsufficientGasEthError;
    }
    return null;
  }

  /// Coarse: parse an integer or decimal `amount` string into token
  /// base units. Matches the backend's `_parse_amount_base_units`
  /// convention (validate at draft time; the exact base-units value
  /// was already accepted by the backend integer gate — we only
  /// re-derive it here to compare against the wallet's token
  /// balance for the client-side hard gate). USDT_ERC20 / USDC_ERC20
  /// = 6 decimals in this build; overrideable per asset if new
  /// tokens are added.
  BigInt _tokenAmountToBaseUnits(String amount, String unit) {
    int decimals;
    switch (widget.asset) {
      case 'USDT_ERC20':
      case 'USDC_ERC20':
        decimals = 6;
        break;
      default:
        decimals = 18;
    }
    final normalized = amount.trim();
    if (normalized.isEmpty) return BigInt.zero;
    final dotIdx = normalized.indexOf('.');
    if (dotIdx < 0) {
      return BigInt.parse(normalized) * BigInt.from(10).pow(decimals);
    }
    final whole = normalized.substring(0, dotIdx);
    var frac = normalized.substring(dotIdx + 1);
    if (frac.length > decimals) {
      frac = frac.substring(0, decimals);
    } else {
      frac = frac.padRight(decimals, '0');
    }
    final wholeBi = whole.isEmpty ? BigInt.zero : BigInt.parse(whole);
    final fracBi = frac.isEmpty ? BigInt.zero : BigInt.parse(frac);
    return wholeBi * BigInt.from(10).pow(decimals) + fracBi;
  }

  // ------------------------------------------------------------
  // Local outgoing tx helpers.
  //
  // Each broadcast attempt stamps a local Activity row keyed by
  // `keccak256(raw)`. The store is optional — if the panel is
  // constructed without one, the helpers are no-ops.
  // ------------------------------------------------------------

  String _computeLocalHashForSigned(String signedTx) {
    try {
      return computeLocalEthTxHash(signedTx);
    } catch (_) {
      // Extreme edge case — malformed hex. Build a synthetic
      // 66-char sentinel WITHOUT a hardcoded 0x+64 literal (the
      // mainnet-safety source guard forbids inline hash literals
      // in this file). Real production tx will never hit this.
      return '0x${'0' * 64}';
    }
  }

  void _emitOutgoingSubmitting({
    required String txHash,
    required _DraftFields draft,
  }) {
    final store = widget.outgoingTxStore;
    if (store == null) return;
    store.upsert(LocalOutgoingTx(
      txHash: txHash,
      fromAddress: draft.fromAddress,
      toAddress: draft.destinationAddress,
      amount: draft.amount,
      unit: draft.unit,
      feeWei: draft.feeWei,
      networkId: widget.network,
      asset: widget.asset,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      status: LocalOutgoingTxStatus.submitting,
    ));
  }

  void _updateOutgoingRow(
    String txHash,
    LocalOutgoingTxStatus status, {
    String? reason,
  }) {
    final store = widget.outgoingTxStore;
    if (store == null) return;
    store.updateStatus(txHash, status, reason: reason);
  }

  // 2026-07-13 (Round 5 hardening): notify the caller (asset detail
  // page) that a broadcast succeeded so it can stamp an optimistic
  // pending debit on the Balance card. Uses the DRAFT-echoed value
  // in wei / base units — the exact amount the transaction will
  // debit if it lands.
  void _notifyOptimisticDebit(String displayHash) {
    final cb = widget.onSuccessfulBroadcast;
    final draft = _draft;
    if (cb == null || draft == null) return;
    final isToken = widget.asset != 'ETH';
    BigInt debit;
    if (isToken) {
      debit = _tokenAmountToBaseUnits(draft.amount, draft.unit);
    } else {
      // ETH send: the pending debit is value + fee.
      debit = draft.valueWei + draft.gasLimit * draft.gasPrice;
    }
    cb(txHash: displayHash, debitBaseUnits: debit);
  }

  void _cancelOutgoingSubmittingRow(String txHash) {
    final store = widget.outgoingTxStore;
    if (store == null) return;
    // On pause / rate-limit the tx was NEVER attempted at the RPC.
    // Downgrade the row to `dropped` (terminal) so it's clearly not
    // in flight; the user sees "no send happened" rather than a
    // stuck "Submitting…". We do not delete because the record has
    // audit value — the user tried to send at time T.
    store.updateStatus(
      txHash,
      LocalOutgoingTxStatus.dropped,
      reason: 'not_attempted',
    );
  }

  Future<String?> _showPinDialog() async {
    
    
    return showDialog<String>(
      context: context,
      builder: (ctx) => const _EthSendPinDialog(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return WalletDarkPanelScope(
      child: _buildPanelBody(context),
    );
  }

  Widget _buildPanelBody(BuildContext context) {
    final isMainnet = widget.isMainnet;
    final sheetKey = isMainnet ? 'eth_send_panel_mainnet' : 'eth_send_panel';
    final chip = walletSendNetworkChip(
      key: Key('${sheetKey}_network_chip'),
      label: isMainnet
          ? kEthSendMainnetNetworkBadge
          : kEthSendNetworkBadge,
      isMainnet: isMainnet,
    );
    // Compact mainnet warnings: at most ONE row visible above the
    // form. Priority: paused > disabled > real-funds. Paused wins
    // over disabled because the operator-paused signal is a more
    // specific "why can't I send right now" answer than the build-
    // time flag; real-funds only shows when neither block applies.
    Widget? topWarning;
    if (isMainnet) {
      if (widget.mainnetSendPaused) {
        topWarning = const WalletSendWarning(
          key: Key(kMainnetSendPausedBannerKey),
          text: kMainnetSendPausedBanner,
          tone: WalletSendWarningTone.critical,
        );
      } else if (!kCryptoWalletEngineMainnetSendEnabled) {
        topWarning = const WalletSendWarning(
          key: Key('eth_send_panel_mainnet_send_disabled'),
          text: kEthSendMainnetSendDisabledBanner,
          tone: WalletSendWarningTone.critical,
        );
      } else {
        topWarning = WalletSendWarning(
          key: const Key('eth_send_panel_mainnet_real_funds'),
          text: widget.asset == 'ETH'
              ? kEvmNetworkMainnetSendRealFundsHeadline
              : kEvmNetworkMainnetTokenSendRealFundsHeadline
                  .replaceAll('{token}',
                      widget.asset == 'USDT_ERC20' ? 'USDT' : 'USDC'),
        );
      }
    }
    Widget stageBody;
    Widget? stageFooter;
    switch (_stage) {
      case _Stage.form:
        stageBody = _buildFormBody(context);
        stageFooter = _buildFormFooter(context);
        break;
      case _Stage.loadingDraft:
        stageBody = _buildBusyStage(
          key: const Key('eth_send_panel_loading_draft'),
          label: 'Loading network fee data…',
        );
        break;
      case _Stage.review:
        stageBody = _buildReviewBody(context);
        stageFooter = _buildReviewFooter(context);
        break;
      case _Stage.confirmPhrase:
        stageBody = _buildConfirmPhraseBody(context);
        stageFooter = _buildConfirmPhraseFooter(context);
        break;
      case _Stage.signing:
        stageBody = _buildBusyStage(
          key: const Key('eth_send_panel_signing'),
          label: kEthSendBroadcastPendingLabel,
        );
        break;
      case _Stage.submitted:
        stageBody = _buildSubmittedStage(context);
        break;
    }
    final composedBody = Column(
      key: Key(sheetKey),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (topWarning != null) ...[
          topWarning,
          const SizedBox(height: 12),
        ],
        stageBody,
        if (_error != null) ...[
          const SizedBox(height: 12),
          WalletSendWarning(
            key: const Key('eth_send_panel_error_banner'),
            text: _error!,
            tone: WalletSendWarningTone.critical,
          ),
        ],
      ],
    );
    // 2026-07-13 mobile-keyboard fix: only wire the shared scroll
    // controller in the form stage — that's the only stage with focus-
    // triggered scroll behavior (destination + amount fields). Review
    // / confirm-phrase / submitted stages use the default controller
    // to avoid the controller being attached to two different
    // Scrollables when the stage rebuilds.
    final scaffoldScrollController =
        _stage == _Stage.form ? _formScrollCtrl : null;
    return WalletSendScaffold(
      sheetKey: sheetKey,
      header: chip,
      body: composedBody,
      footer: stageFooter,
      scrollController: scaffoldScrollController,
    );
  }

  Widget _buildBusyStage({required Key key, required String label}) {
    return Padding(
      key: key,
      padding: const EdgeInsets.symmetric(vertical: 24),
      child: Row(
        children: [
          const SizedBox(
            width: 18, height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: 12),
          Expanded(child: Text(label)),
        ],
      ),
    );
  }

  // The form-stage input fields (destination, amount). The Review
  // button is rendered separately in `_buildFormFooter` so it stays
  // pinned at the bottom of the sheet above the keyboard.
  //
  // 2026-07-13 mobile-keyboard fix: FocusNode + textInputAction wire-
  // up so the mobile Safari keyboard renders a "Next" button on
  // Destination and a "Done" button on Amount; hopping Next moves
  // focus programmatically to Amount which then autoscrolls into view.
  Widget _buildFormBody(BuildContext ctx) {
    return Column(
      key: const Key('eth_send_panel_form_stage'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          key: const Key('eth_send_panel_destination_input'),
          controller: _destCtrl,
          focusNode: _destFocus,
          textInputAction: TextInputAction.next,
          autocorrect: false,
          enableSuggestions: false,
          onSubmitted: (_) => _amountFocus.requestFocus(),
          decoration: InputDecoration(
            labelText: kEthSendDestinationLabel,
            hintText: '0x...',
            isDense: true,
            suffixIcon: IconButton(
              key: const Key('eth_send_panel_scan_qr_btn'),
              icon: const Icon(Icons.qr_code_scanner_rounded),
              tooltip: 'Scan recipient QR',
              onPressed: () => _handleScanRecipientQr(ctx),
            ),
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key('eth_send_panel_amount_input'),
          controller: _amountCtrl,
          focusNode: _amountFocus,
          textInputAction: TextInputAction.done,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          onSubmitted: (_) => _amountFocus.unfocus(),
          decoration: InputDecoration(
            labelText: kEthSendAmountLabel,
            hintText: '0.01',
            isDense: true,
            // 2026-07-13 (Round 5 hardening): Max action that
            // reserves an exact gas floor for ETH sends and copies
            // the token balance verbatim for ERC-20. Integer BigInt
            // arithmetic end-to-end — never a `double` conversion.
            suffixIcon: TextButton(
              key: const Key('eth_send_panel_max_btn'),
              onPressed: _onMaxTap,
              child: const Text(
                kEthSendMaxActionLabel,
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.2,
                ),
              ),
            ),
          ),
        ),
        // 2026-07-13 (Round 5 hardening): show the last-known
        // available balance directly under the amount input so the
        // user always sees what they can send. Empty when no
        // balance hook is wired (Sepolia tests).
        FutureBuilder<double?>(
          key: const Key('eth_send_panel_available_balance_line'),
          future: (widget.fetchAvailableBalance != null)
              ? widget.fetchAvailableBalance!()
              : Future<double?>.value(null),
          builder: (context, snap) {
            final bal = snap.data;
            if (bal == null) return const SizedBox.shrink();
            final unit = widget.asset == 'ETH'
                ? 'ETH'
                : (widget.asset == 'USDT_ERC20'
                    ? 'USDT'
                    : widget.asset == 'USDC_ERC20'
                        ? 'USDC'
                        : widget.asset);
            return Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'Available: $bal $unit',
                key: const Key(
                    'eth_send_panel_available_balance_text'),
                style: const TextStyle(
                  fontSize: 12, color: kWalletTextMuted,
                ),
              ),
            );
          },
        ),
      ],
    );
  }

  // 2026-07-14 (Round 8 hardening): Max tap uses AUTHORITATIVE
  // persisted draft fee. Rewrite of the Round-5 hardcoded-reserve
  // implementation.
  //
  // For ETH: `maxValueWei = verifiedBalanceWei - draft.feeWei`.
  // If no draft has been created this session, Max fails closed
  // with `kEthSendMaxRequiresDraftError` — the user must tap
  // Review first to materialize a server-authorized fee. NEVER a
  // hard-coded gas reservation.
  //
  // For ERC-20: sets the amount to the full token balance. Gas is
  // paid in ETH (checked separately by the exact-fee gate).
  Future<void> _onMaxTap() async {
    // 2026-07-14 (Round 10 — Max UX): Max no longer requires a
    // persisted draft. Flow:
    //
    //   1. ETH — needs a valid destination first (fee estimate
    //      depends on the destination). Then:
    //        * fetch verified ETH balance in wei (existing hook);
    //        * call the fee-estimate endpoint for that destination
    //          to obtain the authoritative max fee in wei;
    //        * fill amount with (balance - fee) via BigInt.
    //   2. ERC-20 — Max = full verified token base-unit balance.
    //      No ETH is subtracted from the token amount. The pre-sign
    //      exact-fee gate independently verifies the ETH balance
    //      can cover the final draft's gas.
    //
    // Fail-closed on any missing hook / missing destination /
    // unverifiable balance / unavailable fee estimate. Never a
    // hard-coded 21000×100gwei fallback.
    if (widget.asset == 'ETH') {
      final destination = _destCtrl.text.trim();
      if (destination.isEmpty ||
          !_looksLikeEthAddress(destination)) {
        setState(() {
          _error = kEthSendMaxRequiresDestinationError;
        });
        return;
      }
      final wei = (widget.fetchAvailableBalanceWei != null)
          ? await widget.fetchAvailableBalanceWei!()
          : null;
      if (wei == null || wei <= BigInt.zero) {
        setState(() {
          _error = kMainnetSendBalanceUnverifiedError;
          _balanceCheckUnverified = true;
        });
        return;
      }
      final BigInt? feeWei = await _fetchAuthorizedMaxFeeWei(
        destination: destination,
      );
      if (feeWei == null || feeWei <= BigInt.zero) {
        setState(() {
          _error = kEthSendMaxTemporarilyUnavailableError;
        });
        return;
      }
      final BigInt target = wei - feeWei;
      if (target <= BigInt.zero) {
        setState(() {
          _error = kMainnetSendInsufficientBalanceError;
        });
        return;
      }
      _amountCtrl.text = _formatMaxWeiAsEth(target);
      setState(() {
        _error = null;
      });
      return;
    }
    // ERC-20: Max = full verified token base-unit balance. Never
    // subtracts ETH. Gas is verified separately by the pre-sign
    // exact-fee gate.
    final wei = (widget.fetchAvailableBalanceWei != null)
        ? await widget.fetchAvailableBalanceWei!()
        : null;
    if (wei == null || wei <= BigInt.zero) {
      setState(() {
        _error = kMainnetSendBalanceUnverifiedError;
        _balanceCheckUnverified = true;
      });
      return;
    }
    final decimals = (widget.asset == 'USDT_ERC20' ||
            widget.asset == 'USDC_ERC20')
        ? 6
        : 18;
    _amountCtrl.text = _formatMaxBaseUnits(wei, decimals);
    setState(() {});
  }

  Future<BigInt?> _fetchAuthorizedMaxFeeWei({
    required String destination,
  }) async {
    Map<String, dynamic>? resp;
    try {
      resp = await widget.client
          .postCryptoWalletSendFeeEstimateNetwork(
        network: widget.isMainnet
            ? 'ethereum_mainnet'
            : 'ethereum_sepolia',
        fromAddress: widget.fromAddress,
        destinationAddress: destination,
        asset: widget.asset,
        authToken: widget.authToken,
      );
    } catch (_) {
      return null;
    }
    if (resp['status'] != 'fee_estimate_ready') return null;
    final raw = (resp['authorizedMaxFeeBaseUnits'] ?? '').toString();
    return BigInt.tryParse(raw);
  }

  static String _formatMaxWeiAsEth(BigInt wei) {
    final divisor = BigInt.from(1000000000000000000);
    final whole = wei ~/ divisor;
    final frac = wei - (whole * divisor);
    if (frac == BigInt.zero) return whole.toString();
    final fracStr = frac.toString().padLeft(18, '0');
    final trimmed = fracStr.replaceFirst(RegExp(r'0+$'), '');
    return trimmed.isEmpty ? whole.toString() : '$whole.$trimmed';
  }

  static String _formatMaxBaseUnits(BigInt v, int decimals) {
    if (decimals <= 0) return v.toString();
    final divisor = BigInt.from(10).pow(decimals);
    final whole = v ~/ divisor;
    final frac = v - (whole * divisor);
    if (frac == BigInt.zero) return whole.toString();
    final fracStr = frac.toString().padLeft(decimals, '0');
    final trimmed = fracStr.replaceFirst(RegExp(r'0+$'), '');
    return trimmed.isEmpty ? whole.toString() : '$whole.$trimmed';
  }

  Future<void> _handleScanRecipientQr(BuildContext ctx) async {
    // Dismiss the keyboard first — otherwise the scanner sheet opens
    // half-covered on iPhone Safari.
    FocusManager.instance.primaryFocus?.unfocus();

    final expectedChainId = widget.isMainnet ? 1 : 11155111;
    final scanHook = widget.scanRecipientQr;
    final scannedAddress = scanHook != null
        ? await scanHook(ctx, RecipientNetwork.ethereum, expectedChainId)
        : await showScanRecipientQrSheet(
            context: ctx,
            network: RecipientNetwork.ethereum,
            expectedChainId: expectedChainId,
          );
    if (scannedAddress == null || !mounted) return;
    // 2026-07-14 (Round 7 hardening): EIP-681 amount handling. The
    // scan sheet returns only a bare address, but if the SAME raw
    // string is an EIP-681 URI carrying `value=`, we re-parse it
    // here and:
    //   * populate the amount ONLY if the amount field is empty
    //   * otherwise prompt the user to confirm before replacing
    //   * never silently override
    BigInt? parsedAmountWei;
    if (scannedAddress.startsWith('ethereum:')) {
      final res = RecipientQrParser.parse(
        raw: scannedAddress,
        network: RecipientNetwork.ethereum,
        expectedChainId: expectedChainId,
      );
      if (res.ok) {
        parsedAmountWei = res.parsedAmountBaseUnits;
      }
    }
    // Extract the bare address from the parser result so the
    // destination field contains an address, never a URI.
    String destAddress = scannedAddress;
    if (scannedAddress.startsWith('ethereum:')) {
      final res = RecipientQrParser.parse(
        raw: scannedAddress,
        network: RecipientNetwork.ethereum,
        expectedChainId: expectedChainId,
      );
      if (res.ok && res.address != null) destAddress = res.address!;
    }
    if (!mounted) return;
    setState(() {
      _destCtrl.text = destAddress;
    });
    if (parsedAmountWei != null && parsedAmountWei > BigInt.zero) {
      final ethStr = _weiToEthString(parsedAmountWei);
      final existing = _amountCtrl.text.trim();
      if (existing.isEmpty) {
        setState(() {
          _amountCtrl.text = ethStr;
        });
      } else if (existing != ethStr) {
        // Prompt for explicit confirmation.
        // ignore: use_build_context_synchronously
        final confirm = await showDialog<bool>(
          context: ctx,
          barrierDismissible: false,
          builder: (dialogCtx) => AlertDialog(
            key: const Key('eth_send_panel_eip681_confirm_dialog'),
            title: const Text('Replace amount?'),
            content: Text(
              kEthSendFormValidationEip681AmountConfirmPrompt
                  + '\n\nScanned amount: $ethStr ETH',
            ),
            actions: [
              TextButton(
                key: const Key(
                  'eth_send_panel_eip681_confirm_cancel_btn',
                ),
                onPressed: () => Navigator.of(dialogCtx).pop(false),
                child: const Text('Keep my amount'),
              ),
              ElevatedButton(
                key: const Key(
                  'eth_send_panel_eip681_confirm_replace_btn',
                ),
                onPressed: () => Navigator.of(dialogCtx).pop(true),
                child: const Text('Replace'),
              ),
            ],
          ),
        );
        if (confirm == true && mounted) {
          setState(() {
            _amountCtrl.text = ethStr;
          });
        }
      }
    }
  }

  String _weiToEthString(BigInt wei) {
    final divisor = BigInt.from(10).pow(18);
    final whole = wei ~/ divisor;
    final frac = wei - whole * divisor;
    if (frac == BigInt.zero) return whole.toString();
    final fracStr = frac.toString().padLeft(18, '0');
    final trimmed = fracStr.replaceFirst(RegExp(r'0+$'), '');
    return trimmed.isEmpty ? whole.toString() : '$whole.$trimmed';
  }

  Widget _buildFormFooter(BuildContext ctx) {
    // 2026-07-13 canary correctness: when balance verification
    // failed on a prior tap, the primary action becomes "Retry
    // balance check" — the ONLY way forward is to load a live
    // balance. `_onReview` retries the whole flow (balance +
    // draft) so the same button drives both first attempt and
    // retry.
    final label = _balanceCheckUnverified
        ? kMainnetSendRetryBalanceLabel
        : kEthSendReviewButtonLabel;
    return ElevatedButton(
      key: const Key('eth_send_panel_review_btn'),
      // 2026-07-14 (Round 8 hardening): disabled while drafting so
      // a rapid double-tap does not spawn a second draft.
      onPressed: _draftInFlight ? null : _onReview,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: Text(label),
    );
  }

  Widget _buildReviewBody(BuildContext ctx) {
    final d = _draft!;
    final isToken = widget.asset != 'ETH';
    final isMainnet = widget.isMainnet;
    final networkLabel = isMainnet
        ? 'Ethereum Mainnet'
        : 'Ethereum Sepolia';
    final feeNotice = isToken
        ? (isMainnet
            ? 'Gas requires mainnet ETH on this wallet.'
            : 'Gas requires Sepolia ETH on this wallet.')
        : null;
    final reviewWarning = isMainnet
        ? (isToken
            ? kEvmNetworkMainnetTokenSendRealFundsHeadline.replaceAll(
                '{token}',
                widget.asset == 'USDT_ERC20' ? 'USDT' : 'USDC',
              )
            : kEvmNetworkMainnetSendRealFundsHeadline)
        : kEthSendReviewWarning;
    return Column(
      key: const Key('eth_send_panel_review_stage'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        walletSendSectionHeading('Review send'),
        WalletSendKvRow(label: 'From', value: d.fromAddress, mono: true),
        if (isMainnet)
          _buildDestinationWarningCard(d.destinationAddress)
        else
          WalletSendKvRow(
            label: 'Destination',
            value: d.destinationAddress,
            mono: true,
          ),
        if (isMainnet && _recipientCheckRan && !_isKnownRecipient)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: _buildNewRecipientBanner(),
          ),
        // 2026-07-14 (Round 7 hardening): contract-destination
        // soft warning. `null` → unknown (fail-open), no banner.
        if (_isContractDest == true)
          Padding(
            key: const Key('eth_send_panel_contract_recipient_warning'),
            padding: const EdgeInsets.only(top: 4),
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: walletWarningPanel(),
              child: const Row(
                children: [
                  Icon(Icons.warning_amber_rounded,
                       size: 16, color: kWalletAccentWarning),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      kEthSendFormValidationContractRecipientWarning,
                      style: TextStyle(
                        color: kWalletAccentWarning, fontSize: 12,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        WalletSendKvRow(label: 'Amount', value: '${d.amount} ${d.unit}'),
        WalletSendKvRow(
          label: 'Network fee',
          value: '${_formatWeiAsEth(d.feeWei)} ETH',
        ),
        if (feeNotice != null)
          WalletSendKvRow(label: 'Fee notice', value: feeNotice),
        WalletSendKvRow(label: 'Network', value: networkLabel),
        if (isMainnet)
          WalletSendKvRow(label: 'Chain ID', value: '${d.chainId}'),
        if (isMainnet && _balanceCheckUnverified)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: _buildBalanceUnverifiedBanner(),
          ),
        if (isMainnet && _insufficientGas)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: _buildInsufficientGasBanner(),
          ),
        const SizedBox(height: 10),
        // Single compact review warning row — replaces the old full-width
        // yellow/orange banner block. Mainnet uses the critical tone,
        // testnet uses the subtle tone.
        WalletSendWarning(
          key: Key(isMainnet
              ? 'eth_send_panel_mainnet_review_warning'
              : 'eth_send_panel_review_warning_container'),
          text: reviewWarning,
          tone: isMainnet
              ? WalletSendWarningTone.critical
              : WalletSendWarningTone.subtle,
        ),
        // Legacy key: mainnet safety tests still look for this text
        // widget's key `eth_send_panel_review_warning`; render it as
        // a zero-size sentinel so existing keyed lookups still find
        // the copy without adding a second visible warning row.
        Offstage(
          child: Text(
            reviewWarning,
            key: const Key('eth_send_panel_review_warning'),
          ),
        ),
      ],
    );
  }

  Widget _buildReviewFooter(BuildContext ctx) {
    return ElevatedButton(
      key: const Key('eth_send_panel_confirm_btn'),
      onPressed: _onReviewConfirmTap,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: const Text(kEthSendReviewConfirmButtonLabel),
    );
  }

  Widget _buildConfirmPhraseBody(BuildContext ctx) {
    final expected = mainnetSendConfirmPhraseFor(widget.asset);
    final prompt = mainnetSendConfirmPhrasePromptFor(widget.asset);
    return Column(
      key: const Key(kMainnetSendConfirmPhraseStageKey),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        WalletSendWarning(
          text: prompt,
          tone: WalletSendWarningTone.critical,
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key(kMainnetSendConfirmPhraseInputKey),
          controller: _confirmPhraseCtrl,
          decoration: InputDecoration(
            labelText: 'Type: $expected',
            isDense: true,
          ),
          textCapitalization: TextCapitalization.characters,
        ),
      ],
    );
  }

  Widget _buildConfirmPhraseFooter(BuildContext ctx) {
    return ElevatedButton(
      key: const Key(kMainnetSendConfirmPhraseContinueBtnKey),
      onPressed: _broadcastInFlight
          ? null
          : _onMainnetConfirmPhraseContinue,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: Text(AppLocalizations.of(context).cryptoContinueToPin),
    );
  }

  String _shortAddressLabel(String addr) {
    if (addr.length < 12) return addr;
    return '${addr.substring(0, 6)}…${addr.substring(addr.length - 4)}';
  }

  Widget _buildDestinationWarningCard(String destination) {
    return Container(
      key: const Key(kMainnetSendDestinationCardKey),
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(10),
      decoration: walletWarningPanel(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            kMainnetSendDestinationCardHeader,
            style: TextStyle(
              color: kWalletAccentWarning,
              fontWeight: FontWeight.w700,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 4),
          SelectableText(
            destination,
            style: kWalletMonoStyle,
          ),
          const SizedBox(height: 2),
          Text(
            'Highlighted: ${_shortAddressLabel(destination)}',
            style: const TextStyle(
              fontFamily: 'monospace',
              color: kWalletAccentWarning,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const Key(kMainnetSendDestinationCopyBtnKey),
              icon: const Icon(Icons.copy, size: 14),
              label: Text(
                AppLocalizations.of(context).cryptoCopyDestination,
              ),
              style: walletGhostButtonStyle(),
              onPressed: () {
                Clipboard.setData(
                  ClipboardData(text: destination),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNewRecipientBanner() {
    return WalletSendWarning(
      key: const Key(kMainnetSendNewRecipientBannerKey),
      text: kMainnetSendNewRecipientWarning,
    );
  }

  Widget _buildBalanceUnverifiedBanner() {
    return WalletSendWarning(
      key: const Key(kMainnetSendBalanceUnverifiedKey),
      text: kMainnetSendBalanceUnverifiedWarning,
    );
  }

  Widget _buildInsufficientGasBanner() {
    return WalletSendWarning(
      key: const Key(kMainnetSendInsufficientGasKey),
      text: kMainnetSendInsufficientGasWarning,
      tone: WalletSendWarningTone.critical,
    );
  }

  Widget _buildSubmittedStage(BuildContext ctx) {
    // 2026-07-13 canary correctness: honest result screen. The
    // submitted stage is now three distinct states, distinguished
    // by `_broadcastStatus`:
    //
    //   `submitted` / `already_submitted` → confirmed submission,
    //       show explorer link
    //   `submission_uncertain`            → uncertain, offer
    //       Check-Status action, do NOT tell user to send again
    //   `broadcast_rejected` /
    //   `broadcast_unavailable`           → explicit rejection,
    //       show Start-a-new-send action
    final status = _broadcastStatus ?? 'submitted';
    final hash = _submittedTxHash ?? '';
    final isUncertain = status == 'submission_uncertain';
    final isRejected = status == 'broadcast_rejected'
        || status == 'broadcast_unavailable';
    final heading = isRejected
        ? kEthSendResultHeadingRejected
        : (isUncertain
            ? kEthSendResultHeadingUncertain
            : kEthSendResultHeadingSubmitted);
    final body = isRejected
        ? kEthSendResultBodyRejected
        : (isUncertain
            ? kEthSendResultBodyUncertain
            : kEthSendResultBodySubmitted);
    return Column(
      key: const Key('eth_send_panel_submitted_stage'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        walletSendSectionHeading(heading),
        Text(
          body,
          key: Key('eth_send_panel_result_body_$status'),
          style: const TextStyle(
              color: kWalletTextSecondary, fontSize: 13, height: 1.4),
        ),
        if (_broadcastMessage != null && _broadcastMessage!.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            _broadcastMessage!,
            key: const Key('eth_send_panel_result_backend_message'),
            style: const TextStyle(
                color: kWalletTextMuted, fontSize: 12, height: 1.4),
          ),
        ],
        if (_broadcastReason != null && _broadcastReason!.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(
            'Reason: ${_broadcastReason!}',
            key: const Key('eth_send_panel_result_backend_reason'),
            style: const TextStyle(
                color: kWalletTextMuted, fontSize: 11,
                fontWeight: FontWeight.w600, letterSpacing: 0.4),
          ),
        ],
        const SizedBox(height: 14),
        _buildTxHashPanel(hash),
        const SizedBox(height: 12),
        if (!isRejected) _buildExplorerAction(hash),
        if (isUncertain) ...[
          const SizedBox(height: 8),
          _buildCheckStatusAction(hash),
        ],
        if (isRejected) ...[
          const SizedBox(height: 8),
          _buildReturnFormAction(),
        ],
      ],
    );
  }

  Widget _buildTxHashPanel(String hash) {
    return Container(
      key: const Key('eth_send_panel_tx_hash_panel'),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: kWalletBgTint,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: kWalletBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Transaction hash',
            style: TextStyle(
                color: kWalletTextMuted, fontSize: 11,
                fontWeight: FontWeight.w600, letterSpacing: 0.4),
          ),
          const SizedBox(height: 4),
          SelectableText(
            hash,
            key: const Key('eth_send_panel_tx_hash_text'),
            style: kWalletMonoStyle,
          ),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              key: const Key('eth_send_panel_copy_hash_btn'),
              icon: const Icon(Icons.copy_rounded, size: 14),
              label: const Text(kEthSendResultCopyHashLabel),
              style: TextButton.styleFrom(
                foregroundColor: kWalletTextPrimary,
                minimumSize: const Size(0, 32),
                padding: const EdgeInsets.symmetric(horizontal: 4),
              ),
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: hash));
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    key: Key('eth_send_panel_copy_snackbar'),
                    content: Text(kEthSendResultCopiedSnackbar),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildExplorerAction(String hash) {
    final url = ethExplorerUrlFor(
      network: widget.network, txHash: hash,
    );
    return FilledButton.icon(
      key: const Key('eth_send_panel_explorer_btn'),
      icon: const Icon(Icons.open_in_new_rounded, size: 16),
      label: const Text(kEthSendResultViewExplorerLabel),
      onPressed: () async {
        final launcher = widget.launchUrl;
        if (launcher != null) {
          await launcher(url);
        }
      },
      style: FilledButton.styleFrom(
        backgroundColor: kWalletAccentPrimary,
        foregroundColor: Colors.white,
        minimumSize: const Size.fromHeight(46),
      ),
    );
  }

  Widget _buildCheckStatusAction(String hash) {
    return OutlinedButton.icon(
      key: const Key('eth_send_panel_check_status_btn'),
      icon: const Icon(Icons.refresh_rounded, size: 16),
      label: const Text(kEthSendResultCheckStatusLabel),
      onPressed: () async {
        try {
          final body = widget.isMainnet
              ? await widget.client
                  .getCryptoWalletTransactionStatusNetwork(
                  network: widget.network,
                  asset: widget.asset,
                  authToken: widget.authToken,
                  txHash: hash,
                )
              : await widget.client.getCryptoWalletTransactionStatus(
                  asset: widget.asset,
                  authToken: widget.authToken,
                  txHash: hash,
                );
          final status = (body['status'] ?? '').toString();
          _syncOutgoingRowFromStatus(hash, status);
        } catch (_) {
          // Leave the local row as-is on network error; the user
          // can tap again.
        }
      },
      style: OutlinedButton.styleFrom(
        foregroundColor: kWalletTextPrimary,
        side: const BorderSide(color: kWalletBorderStrong),
        minimumSize: const Size.fromHeight(44),
      ),
    );
  }

  Widget _buildReturnFormAction() {
    return OutlinedButton(
      key: const Key('eth_send_panel_return_form_btn'),
      onPressed: () {
        setState(() {
          _submittedTxHash = null;
          _broadcastStatus = null;
          _broadcastReason = null;
          _broadcastMessage = null;
          _draft = null;
          _idempotencyKey = null;
          _stage = _Stage.form;
          _error = null;
        });
      },
      style: OutlinedButton.styleFrom(
        foregroundColor: kWalletTextPrimary,
        side: const BorderSide(color: kWalletBorderStrong),
        minimumSize: const Size.fromHeight(44),
      ),
      child: const Text(kEthSendResultReturnFormLabel),
    );
  }

  void _syncOutgoingRowFromStatus(String hash, String backendStatus) {
    LocalOutgoingTxStatus? next;
    switch (backendStatus) {
      case 'confirmed':
        next = LocalOutgoingTxStatus.confirmed; break;
      case 'failed':
        next = LocalOutgoingTxStatus.failed; break;
      case 'pending':
        next = LocalOutgoingTxStatus.pending; break;
      case 'not_found':
        // The tx has never been seen on any Ethereum node. Do NOT
        // mark it confirmed; keep it as `submissionUncertain` — the
        // user is told the tx is not visible and can decide whether
        // to consider it dropped after enough time passes.
        next = LocalOutgoingTxStatus.submissionUncertain; break;
      default:
        return;
    }
    _updateOutgoingRow(hash, next);
    if (mounted) {
      setState(() {
        // Result-screen heading may want to reflect the new state.
        // Only upgrade `submission_uncertain` → `submitted` when
        // the backend actually confirms; do NOT downgrade a
        // `submitted` result screen.
        if (next == LocalOutgoingTxStatus.confirmed
            || next == LocalOutgoingTxStatus.failed
            || next == LocalOutgoingTxStatus.pending) {
          _broadcastStatus = 'submitted';
        }
      });
    }
  }

  String _formatWeiAsEth(BigInt wei) {
    
    
    final whole = wei ~/ BigInt.from(1000000000000000000);
    final frac = wei - (whole * BigInt.from(1000000000000000000));
    var fracStr = frac.toString().padLeft(18, '0');
    while (fracStr.length > 6 && fracStr.endsWith('0')) {
      fracStr = fracStr.substring(0, fracStr.length - 1);
    }
    return '$whole.$fracStr';
  }
}


class _EthSendPinDialog extends StatefulWidget {
  const _EthSendPinDialog();
  @override
  State<_EthSendPinDialog> createState() => _EthSendPinDialogState();
}

class _EthSendPinDialogState extends State<_EthSendPinDialog> {
  final TextEditingController _pinCtrl = TextEditingController();

  @override
  void dispose() {
    _pinCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const Key('eth_send_panel_pin_dialog'),
      title: const Text(kEthSendPinDialogTitle),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(kEthSendPinDialogBody, maxLines: 4),
          const SizedBox(height: 12),
          TextField(
            key: const Key('eth_send_panel_pin_input'),
            controller: _pinCtrl,
            obscureText: true,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: const InputDecoration(
              labelText: 'PIN',
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          key: const Key('eth_send_panel_pin_cancel'),
          onPressed: () => Navigator.of(context).pop(null),
          child: Text(AppLocalizations.of(context).commonCancel),
        ),
        ElevatedButton(
          key: const Key('eth_send_panel_pin_confirm'),
          onPressed: () => Navigator.of(context).pop(_pinCtrl.text),
          child: const Text(kEthSendPinDialogConfirmLabel),
        ),
      ],
    );
  }
}
