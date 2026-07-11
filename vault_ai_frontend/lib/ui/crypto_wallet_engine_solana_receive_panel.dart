

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../api_client.dart';
import '../services/crypto_wallet_features.dart';
import '../services/solana_wallet.dart';
import 'crypto_wallet_engine_design.dart';


const String kSolanaReceivePanelTitle = 'Receive Solana';
const String kSolanaReceiveNetworkBadge = 'Solana';
const String kSolanaReceiveCreateButtonLabel = 'Create my Solana wallet';
const String kSolanaReceiveCopyButtonLabel = 'Copy address';
const String kSolanaReceiveCopyDoneSnackbar = 'Address copied to clipboard';
const String kSolanaReceiveNonCustodialAttestation =
    'Non-custodial: VaultAI never sees your Solana secret key. Your '
    'wallet is encrypted with your PIN and stored as ciphertext only.';
const String kSolanaReceiveAssetWarning =
    'Only send SOL on Solana to this address.';
const String kSolanaReceiveCreateBlockedNoVaultKey =
    'Unlock your vault with your PIN before creating a Solana wallet — '
    'the secret is encrypted with your vault key locally.';
const String kSolanaReceiveLoadingLabel = 'Loading Solana wallet…';
const String kSolanaReceiveDisabledMessage =
    'Solana receive is temporarily unavailable.';
const String kSolanaReceivePanelKey = 'solana_receive_panel';
const String kSolanaReceivePanelCreateBtnKey =
    'solana_receive_panel_create_btn';
const String kSolanaReceivePanelQrKey = 'solana_receive_panel_qr';
const String kSolanaReceivePanelAddressTextKey =
    'solana_receive_panel_address_text';
const String kSolanaReceivePanelCopyBtnKey =
    'solana_receive_panel_copy_btn';
const String kSolanaReceivePanelWarningKey =
    'solana_receive_panel_warning';
const String kSolanaReceivePanelDisabledKey =
    'solana_receive_panel_disabled';
const String kSolanaReceivePanelNoKeySnackKey =
    'solana_receive_panel_no_key_snackbar';


class CryptoWalletEngineSolanaReceivePanel extends StatefulWidget {
  final String authToken;
  final VaultAIClient client;
  final Future<String> Function(String plaintext) encryptForVault;
  final bool Function() isVaultKeyAvailable;
  final CryptoWalletFeatures? features;
  final String walletLabel;

  const CryptoWalletEngineSolanaReceivePanel({
    super.key,
    required this.authToken,
    required this.client,
    required this.encryptForVault,
    required this.isVaultKeyAvailable,
    this.features,
    this.walletLabel = 'VaultAI SOL wallet',
  });

  @override
  State<CryptoWalletEngineSolanaReceivePanel> createState() =>
      _CryptoWalletEngineSolanaReceivePanelState();
}

class _CryptoWalletEngineSolanaReceivePanelState
    extends State<CryptoWalletEngineSolanaReceivePanel> {
  Map<String, dynamic>? _state;
  bool _loading = true;
  String? _error;
  bool _creating = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  bool get _solanaEnabled =>
      widget.features?.solanaEnabled ?? true;

  Future<void> _load() async {
    if (!_solanaEnabled) {
      setState(() {
        _state = {'wallet_engine': 'solana_not_enabled'};
        _loading = false;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final body = await widget.client.getCryptoWalletReceiveNetwork(
        network: kSolanaNetworkId,
        asset: kSolanaAssetTicker,
        authToken: widget.authToken,
      );
      if (!mounted) return;
      setState(() {
        _state = body;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _createWallet() async {
    if (!widget.isVaultKeyAvailable()) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          key: Key(kSolanaReceivePanelNoKeySnackKey),
          content: Text(
            kSolanaReceiveCreateBlockedNoVaultKey, maxLines: 3,
          ),
        ),
      );
      return;
    }
    setState(() {
      _creating = true;
      _error = null;
    });

    GeneratedSolanaWallet? wallet;
    Uint8List? plaintextSecret;
    String? encryptedSecret;
    String publicAddress = '';
    try {
      wallet = await generateSolanaWallet();
      plaintextSecret = wallet.secretKeyBytes;
      publicAddress = wallet.publicAddress;
      final secretJson = jsonEncode({
        'schema':        'solana_secret_v1',
        'keyOrigin':     'generated_client_side',
        'secretKeyBase58': wallet.secretKeyBase58,
      });
      encryptedSecret = await widget.encryptForVault(secretJson);
    } catch (e) {
      if (!mounted) return;
      if (plaintextSecret != null) {
        wipeSecretKey(plaintextSecret);
      }
      setState(() {
        _creating = false;
        _error = 'Solana wallet generation failed: $e';
      });
      return;
    }

    if (plaintextSecret != null) {
      wipeSecretKey(plaintextSecret);
    }
    plaintextSecret = null;
    wallet = null;

    try {
      await widget.client.createCryptoWalletAccountNetwork(
        network: kSolanaNetworkId,
        asset: kSolanaAssetTicker,
        authToken: widget.authToken,
        walletLabel: widget.walletLabel,
        publicAddress: publicAddress,
        encryptedWalletSecret: encryptedSecret,
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _error = 'Create Solana wallet failed: $e';
      });
      return;
    }
    encryptedSecret = null;
    if (!mounted) return;
    setState(() {
      _creating = false;
    });
    await _load();
  }

  Future<void> _copyAddress(String address) async {
    await Clipboard.setData(ClipboardData(text: address));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(kSolanaReceiveCopyDoneSnackbar),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return WalletDarkPanelScope(
      child: SingleChildScrollView(
        key: const Key(kSolanaReceivePanelKey),
        child: _buildBody(context),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_loading) {
      return Padding(
        padding: EdgeInsets.all(
            MediaQuery.of(context).size.width < 600 ? 16 : 24),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 18, height: 18,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(
                  kWalletAccentPrimary,
                ),
              ),
            ),
            SizedBox(width: 12),
            Text(
              kSolanaReceiveLoadingLabel,
              style: TextStyle(color: kWalletTextPrimary),
            ),
          ],
        ),
      );
    }
    if (_error != null) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          _error!,
          style: const TextStyle(color: kWalletAccentDanger),
        ),
      );
    }
    final body = _state ?? const <String, dynamic>{};
    final status = (body['wallet_engine'] ?? '').toString();

    if (status == 'solana_not_enabled') {
      return Padding(
        key: const Key(kSolanaReceivePanelDisabledKey),
        padding: const EdgeInsets.all(18),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: walletWarningPanel(),
          child: const Row(
            children: [
              Icon(Icons.hourglass_bottom_rounded,
                  size: 18, color: kWalletAccentWarning),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  kSolanaReceiveDisabledMessage,
                  style: TextStyle(
                    color: kWalletAccentWarning,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                  maxLines: 3,
                ),
              ),
            ],
          ),
        ),
      );
    }
    if (status == 'create_solana_wallet_first' || status == 'no_account') {
      return _buildCreateState(context);
    }
    if (status == 'receive_ready') {
      return _buildReadyState(context, body);
    }
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Text('Unexpected Solana wallet status: $status'),
    );
  }

  Widget _buildCreateState(BuildContext ctx) {
    return Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kSolanaReceivePanelTitle,
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            kSolanaReceiveNetworkBadge,
            style: kWalletBodyStyle,
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: walletSuccessPanel(),
            child: const Row(
              children: [
                Icon(Icons.shield_outlined, size: 16,
                    color: kWalletAccentSuccess),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    kSolanaReceiveNonCustodialAttestation,
                    style: TextStyle(
                      color: kWalletAccentSuccess,
                      fontSize: 13,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          ElevatedButton.icon(
            key: const Key(kSolanaReceivePanelCreateBtnKey),
            onPressed: _creating ? null : _createWallet,
            icon: _creating
                ? const SizedBox(
                    width: 14, height: 14,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      valueColor: AlwaysStoppedAnimation<Color>(
                        Colors.white,
                      ),
                    ),
                  )
                : const Icon(Icons.account_balance_wallet_outlined),
            label: const Text(kSolanaReceiveCreateButtonLabel),
            style: walletPrimaryButtonStyle(),
          ),
        ],
      ),
    );
  }

  Widget _buildReadyState(BuildContext ctx, Map<String, dynamic> body) {
    final addr = (body['publicAddress'] ?? '').toString();
    final label = (body['walletLabel'] ?? '').toString();
    return Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kSolanaReceivePanelTitle,
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 4),
          Text(label, style: kWalletBodyStyle),
          const SizedBox(height: 2),
          const Text(kSolanaReceiveNetworkBadge, style: kWalletMutedStyle),
          const SizedBox(height: 14),
          Center(
            child: addr.isNotEmpty
                ? Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: kWalletBorderStrong),
                    ),
                    child: QrImageView(
                      key: const Key(kSolanaReceivePanelQrKey),
                      data: addr,
                      version: QrVersions.auto,
                      size: 220,
                      backgroundColor: Colors.white,
                    ),
                  )
                : const SizedBox.shrink(),
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: kWalletBgBase,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: kWalletBorder),
            ),
            child: SelectableText(
              addr,
              key: const Key(kSolanaReceivePanelAddressTextKey),
              style: kWalletMonoStyle,
            ),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const Key(kSolanaReceivePanelCopyBtnKey),
            onPressed: () => _copyAddress(addr),
            icon: const Icon(Icons.copy_rounded, size: 16),
            label: const Text(kSolanaReceiveCopyButtonLabel),
            style: walletGhostButtonStyle(),
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: walletWarningPanel(),
            child: Row(
              children: [
                const Icon(Icons.warning_amber_rounded, size: 16,
                    color: kWalletAccentWarning),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    (body['warning']
                        ?? kSolanaReceiveAssetWarning).toString(),
                    key: const Key(kSolanaReceivePanelWarningKey),
                    style: const TextStyle(
                      color: kWalletAccentWarning,
                      fontSize: 13,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
