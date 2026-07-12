

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/ethereum_transaction.dart';
import '../services/evm_networks.dart';
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


const String kMainnetSendConfirmPhrasePromptEth =
    'Type "SEND ETH" to continue.';
const String kMainnetSendConfirmPhrasePromptUsdt =
    'Type "SEND USDT" to continue.';
const String kMainnetSendConfirmPhrasePromptUsdc =
    'Type "SEND USDC" to continue.';
const String kMainnetSendConfirmPhraseMismatch =
    'Confirmation phrase does not match. Type it exactly.';
const String kMainnetSendDestinationCardHeader =
    'Verify this address carefully.';
const String kMainnetSendNewRecipientWarning =
    'This is a new recipient address.';
const String kMainnetSendBalanceUnverifiedWarning =
    'Balance could not be verified. Review carefully before sending.';
const String kMainnetSendInsufficientGasWarning =
    'You may not have enough ETH for gas. Top up before sending.';
const String kMainnetSendInsufficientBalanceError =
    'Amount exceeds your available balance.';
const String kMainnetSendFeeEstimateFailedError =
    'Could not estimate network fee. Review and try again.';
const String kMainnetSendPausedBanner =
    'Mainnet sending is temporarily paused.';
const String kMainnetSendBroadcastSafeError =
    'Could not submit transaction.';
const String kMainnetSendRateLimitedError =
    'Too many recent send attempts. Wait a moment before retrying.';

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
    this.idempotencyKeyGenerator,
    this.scanRecipientQr,
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

  
  bool _isKnownRecipient = false;
  bool _recipientCheckRan = false;
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

  Future<void> _onReview() async {
    
    
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
    final amountDouble = double.tryParse(amount);
    if (amountDouble == null || amountDouble <= 0) {
      setState(() => _error = kEthSendFormValidationBadAmount);
      return;
    }

    
    if (widget.isMainnet) {
      _balanceCheckUnverified = false;
      _insufficientGas = false;
      final isToken = widget.asset != 'ETH';
      double? availableBal;
      if (widget.fetchAvailableBalance != null) {
        try {
          availableBal = await widget.fetchAvailableBalance!();
        } catch (_) {
          availableBal = null;
        }
      }
      if (availableBal == null) {
        _balanceCheckUnverified = true;
      } else if (amountDouble > availableBal) {
        setState(() =>
            _error = kMainnetSendInsufficientBalanceError);
        return;
      }
      if (isToken && widget.fetchEthBalance != null) {
        double? ethBal;
        try {
          ethBal = await widget.fetchEthBalance!();
        } catch (_) {
          ethBal = null;
        }
        
        
        if (ethBal != null && ethBal < 0.0005) {
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
    if (widget.isMainnet) {
      
      
      _confirmPhraseCtrl.clear();
      setState(() {
        _stage = _Stage.confirmPhrase;
        _error = null;
      });
      return;
    }
    await _onConfirmAndPin();
  }

  Future<void> _onMainnetConfirmPhraseContinue() async {
    final typed = _confirmPhraseCtrl.text.trim();
    final expected = mainnetSendConfirmPhraseFor(widget.asset);
    if (typed != expected) {
      setState(() => _error = kMainnetSendConfirmPhraseMismatch);
      return;
    }
    setState(() => _error = null);
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
      
      if (walletEngine == 'mainnet_send_paused' ||
          status == 'mainnet_send_paused') {
        setState(() {
          _stage = _Stage.review;
          _error = kMainnetSendPausedBanner;
        });
        return;
      }
      if (walletEngine == 'rate_limited' || status == 'rate_limited') {
        setState(() {
          _stage = _Stage.review;
          _error = kMainnetSendRateLimitedError;
        });
        return;
      }
      if (status != 'submitted') {
        
        
        setState(() {
          _stage = _Stage.review;
          _error = widget.isMainnet
              ? kMainnetSendBroadcastSafeError
              : '$kEthSendErrorBroadcastFailed (${body['reason'] ?? 'unknown'})';
        });
        return;
      }
      setState(() {
        _submittedTxHash = body['txHash'].toString();
        _stage = _Stage.submitted;
      });
    } catch (e) {
      setState(() {
        _stage = _Stage.review;
        _error = widget.isMainnet
            ? kMainnetSendBroadcastSafeError
            : '$kEthSendErrorBroadcastFailed';
      });
    } finally {
      _broadcastInFlight = false;
    }
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
          decoration: const InputDecoration(
            labelText: kEthSendAmountLabel,
            hintText: '0.01',
            isDense: true,
          ),
        ),
      ],
    );
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
    setState(() {
      _destCtrl.text = scannedAddress;
    });
  }

  Widget _buildFormFooter(BuildContext ctx) {
    return ElevatedButton(
      key: const Key('eth_send_panel_review_btn'),
      onPressed: _onReview,
      style: walletPrimaryButtonStyle().copyWith(
        minimumSize: WidgetStatePropertyAll(const Size.fromHeight(46)),
      ),
      child: const Text(kEthSendReviewButtonLabel),
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
    return Column(
      key: const Key('eth_send_panel_submitted_stage'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        walletSendSectionHeading(kEthSendSuccessHeading),
        SelectableText(
          'Transaction hash:\n${_submittedTxHash ?? ''}',
          key: const Key('eth_send_panel_tx_hash_text'),
          style: kWalletMonoStyle,
        ),
        const SizedBox(height: 8),
        const Text(
          'Status: pending — check the transaction page for '
          'confirmation.',
          style: TextStyle(color: kWalletTextMuted, fontSize: 12),
        ),
      ],
    );
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
