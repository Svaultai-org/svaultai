

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api_client.dart';
import '../l10n/app_localizations.dart';
import '../services/ethereum_transaction.dart';
import '../services/evm_networks.dart';
import 'crypto_wallet_engine_design.dart';


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
  }

  @override
  void dispose() {
    _destCtrl.dispose();
    _amountCtrl.dispose();
    _confirmPhraseCtrl.dispose();
    super.dispose();
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
    Widget body;
    switch (_stage) {
      case _Stage.form:
        body = _buildFormStage(context);
        break;
      case _Stage.loadingDraft:
        body = _buildBusyStage(
          key: const Key('eth_send_panel_loading_draft'),
          label: 'Loading network fee data…',
        );
        break;
      case _Stage.review:
        body = _buildReviewStage(context);
        break;
      case _Stage.confirmPhrase:
        body = _buildConfirmPhraseStage(context);
        break;
      case _Stage.signing:
        body = _buildBusyStage(
          key: const Key('eth_send_panel_signing'),
          label: kEthSendBroadcastPendingLabel,
        );
        break;
      case _Stage.submitted:
        body = _buildSubmittedStage(context);
        break;
    }
    final isMainnet = widget.isMainnet;
    return SingleChildScrollView(
      key: Key(isMainnet
          ? 'eth_send_panel_mainnet'
          : 'eth_send_panel'),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              kEthSendPanelTitle,
              style: TextStyle(
                color: kWalletTextPrimary,
                fontSize: 20,
                fontWeight: FontWeight.w800,
                letterSpacing: -0.2,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              isMainnet
                  ? kEthSendMainnetNetworkBadge
                  : kEthSendNetworkBadge,
              style: TextStyle(
                color: isMainnet
                    ? kWalletAccentWarning
                    : kWalletTextSecondary,
                fontSize: 13,
                fontWeight: isMainnet
                    ? FontWeight.w700
                    : FontWeight.w400,
              ),
            ),
            if (isMainnet) ...[
              const SizedBox(height: 6),
              Container(
                key: const Key('eth_send_panel_mainnet_real_funds'),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF5E5),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: const Color(0xFFE5C079)),
                ),
                child: Text(
                  widget.asset == 'ETH'
                      ? kEvmNetworkMainnetSendRealFundsHeadline
                      : kEvmNetworkMainnetTokenSendRealFundsHeadline
                          .replaceAll('{token}',
                              widget.asset == 'USDT_ERC20'
                                  ? 'USDT'
                                  : 'USDC'),
                  style: const TextStyle(
                    color: Color(0xFF6B4A00), fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (!kCryptoWalletEngineMainnetSendEnabled) ...[
                const SizedBox(height: 6),
                Container(
                  key: const Key('eth_send_panel_mainnet_send_disabled'),
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFDECEC),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: const Color(0xFFE5A0A0)),
                  ),
                  child: const Text(
                    kEthSendMainnetSendDisabledBanner,
                    style: TextStyle(
                      color: Color(0xFF8B1A1A), fontSize: 12,
                    ),
                  ),
                ),
              ],
              if (widget.mainnetSendPaused) ...[
                const SizedBox(height: 6),
                Container(
                  key: const Key(kMainnetSendPausedBannerKey),
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFDECEC),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: const Color(0xFFE5A0A0)),
                  ),
                  child: const Text(
                    kMainnetSendPausedBanner,
                    style: TextStyle(
                      color: Color(0xFF8B1A1A), fontSize: 12,
                    ),
                  ),
                ),
              ],
            ],
            const SizedBox(height: 12),
            body,
            if (_error != null) ...[
              const SizedBox(height: 12),
              Container(
                key: const Key('eth_send_panel_error_banner'),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFFFDECEC),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: const Color(0xFFE5A0A0)),
                ),
                child: Text(
                  _error!,
                  style: const TextStyle(
                    color: Color(0xFF8B1A1A), fontSize: 13,
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
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

  Widget _buildFormStage(BuildContext ctx) {
    return Column(
      key: const Key('eth_send_panel_form_stage'),
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          key: const Key('eth_send_panel_destination_input'),
          controller: _destCtrl,
          decoration: const InputDecoration(
            labelText: kEthSendDestinationLabel,
            border: OutlineInputBorder(),
            hintText: '0x...',
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key('eth_send_panel_amount_input'),
          controller: _amountCtrl,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(
            labelText: kEthSendAmountLabel,
            border: OutlineInputBorder(),
            hintText: '0.01',
          ),
        ),
        const SizedBox(height: 12),
        ElevatedButton(
          key: const Key('eth_send_panel_review_btn'),
          onPressed: _onReview,
          child: const Text(kEthSendReviewButtonLabel),
        ),
      ],
    );
  }

  Widget _buildReviewStage(BuildContext ctx) {
    final d = _draft!;
    final isToken = widget.asset != 'ETH';
    final isMainnet = widget.isMainnet;
    final networkLabel = isMainnet
        ? 'Ethereum Mainnet'
        : 'Ethereum Sepolia';
    final feeNotice = isToken
        ? (isMainnet
            ? 'Gas requires Ethereum Mainnet ETH on this wallet.'
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
        _kvRow('From', d.fromAddress),
        
        
        if (isMainnet)
          _buildDestinationWarningCard(d.destinationAddress)
        else
          _kvRow('Destination', d.destinationAddress),
        if (isMainnet && _recipientCheckRan && !_isKnownRecipient)
          _buildNewRecipientBanner(),
        _kvRow('Amount', '${d.amount} ${d.unit}'),
        
        
        _kvRow('Network fee', '${_formatWeiAsEth(d.feeWei)} ETH'),
        if (feeNotice != null) _kvRow('Fee notice', feeNotice),
        _kvRow('Network', networkLabel),
        if (isMainnet)
          _kvRow('Chain ID', '${d.chainId}'),
        if (isMainnet && _balanceCheckUnverified)
          _buildBalanceUnverifiedBanner(),
        if (isMainnet && _insufficientGas)
          _buildInsufficientGasBanner(),
        const SizedBox(height: 12),
        Container(
          key: Key(isMainnet
              ? 'eth_send_panel_mainnet_review_warning'
              : 'eth_send_panel_review_warning_container'),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: isMainnet
                ? const Color(0xFFFFE9C7)
                : const Color(0xFFFFF5E5),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: isMainnet
                  ? const Color(0xFFE5A055)
                  : const Color(0xFFE5C079),
            ),
          ),
          child: Text(
            reviewWarning,
            key: const Key('eth_send_panel_review_warning'),
            style: const TextStyle(color: Color(0xFF6B4A00)),
          ),
        ),
        const SizedBox(height: 12),
        ElevatedButton(
          key: const Key('eth_send_panel_confirm_btn'),
          onPressed: _onReviewConfirmTap,
          child: const Text(kEthSendReviewConfirmButtonLabel),
        ),
      ],
    );
  }

  
  Widget _buildConfirmPhraseStage(BuildContext ctx) {
    final expected = mainnetSendConfirmPhraseFor(widget.asset);
    final prompt = mainnetSendConfirmPhrasePromptFor(widget.asset);
    return Column(
      key: const Key(kMainnetSendConfirmPhraseStageKey),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: const Color(0xFFFFE9C7),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: const Color(0xFFE5A055)),
          ),
          child: Text(
            prompt,
            style: const TextStyle(
              color: Color(0xFF6B4A00),
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        const SizedBox(height: 8),
        TextField(
          key: const Key(kMainnetSendConfirmPhraseInputKey),
          controller: _confirmPhraseCtrl,
          decoration: InputDecoration(
            labelText: 'Type: $expected',
            border: const OutlineInputBorder(),
          ),
          textCapitalization: TextCapitalization.characters,
        ),
        const SizedBox(height: 12),
        ElevatedButton(
          key: const Key(kMainnetSendConfirmPhraseContinueBtnKey),
          onPressed: _broadcastInFlight
              ? null
              : _onMainnetConfirmPhraseContinue,
          child: Text(AppLocalizations.of(context).cryptoContinueToPin),
        ),
      ],
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
      decoration: BoxDecoration(
        color: const Color(0xFFFFF5E5),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFE5C079)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            kMainnetSendDestinationCardHeader,
            style: TextStyle(
              color: Color(0xFF6B4A00),
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          SelectableText(
            destination,
            style: const TextStyle(
              fontFamily: 'monospace', fontSize: 13,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            'Highlighted: ${_shortAddressLabel(destination)}',
            style: const TextStyle(
              fontFamily: 'monospace',
              color: Color(0xFF6B4A00), fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const Key(kMainnetSendDestinationCopyBtnKey),
              icon: const Icon(Icons.copy, size: 16),
              label: Text(
                AppLocalizations.of(context).cryptoCopyDestination,
              ),
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
    return Container(
      key: const Key(kMainnetSendNewRecipientBannerKey),
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF0E6),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: const Color(0xFFE5C079)),
      ),
      child: const Text(
        kMainnetSendNewRecipientWarning,
        style: TextStyle(color: Color(0xFF6B4A00), fontSize: 12),
      ),
    );
  }

  Widget _buildBalanceUnverifiedBanner() {
    return Container(
      key: const Key(kMainnetSendBalanceUnverifiedKey),
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF0E6),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: const Color(0xFFE5C079)),
      ),
      child: const Text(
        kMainnetSendBalanceUnverifiedWarning,
        style: TextStyle(color: Color(0xFF6B4A00), fontSize: 12),
      ),
    );
  }

  Widget _buildInsufficientGasBanner() {
    return Container(
      key: const Key(kMainnetSendInsufficientGasKey),
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: const Color(0xFFFDECEC),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: const Color(0xFFE5A0A0)),
      ),
      child: const Text(
        kMainnetSendInsufficientGasWarning,
        style: TextStyle(color: Color(0xFF8B1A1A), fontSize: 12),
      ),
    );
  }

  Widget _buildSubmittedStage(BuildContext ctx) {
    return Column(
      key: const Key('eth_send_panel_submitted_stage'),
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text(
          kEthSendSuccessHeading,
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 8),
        SelectableText(
          'Transaction hash:\n${_submittedTxHash ?? ''}',
          key: const Key('eth_send_panel_tx_hash_text'),
          style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
        ),
        const SizedBox(height: 8),
        const Text(
          'Status: pending — check the transaction page for confirmation.',
          style: TextStyle(color: Colors.black54),
        ),
      ],
    );
  }

  Widget _kvRow(String k, String v) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 110,
            child: Text(k,
                style: const TextStyle(color: Colors.black54)),
          ),
          Expanded(
            child: SelectableText(
              v,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
            ),
          ),
        ],
      ),
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
