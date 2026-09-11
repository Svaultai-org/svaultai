

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../api_client.dart';
import '../services/crypto_wallet_features.dart';
import '../services/tron_wallet.dart';
import 'crypto_wallet_engine_design.dart';


const String kTronReceivePanelTitle = 'Receive USDT (TRC20)';
const String kTronReceiveNetworkBadge = 'TRON';
const String kTronReceiveCreateButtonLabel = 'Create my TRON wallet';
const String kTronReceiveCopyButtonLabel = 'Copy address';
const String kTronReceiveCopyDoneSnackbar = 'Address copied to clipboard';
const String kTronReceiveNonCustodialAttestation =
    'Non-custodial: Svaultai never sees your TRON secret key. Your '
    'wallet is encrypted with your PIN and stored as ciphertext only.';
const String kTronReceiveAssetWarning =
    'Only send USDT TRC20 on TRON to this address.';
const String kTronReceiveGasNote =
    'Sending from this address later will require TRX for network fees.';
const String kTronReceiveCreateBlockedNoVaultKey =
    'Unlock your vault with your PIN before creating a TRON wallet — '
    'the secret is encrypted with your vault key locally.';
const String kTronReceiveLoadingLabel = 'Loading TRON wallet…';
const String kTronReceiveDisabledMessage =
    'USDT TRC20 receive is temporarily unavailable.';
const String kTronReceivePanelKey = 'tron_receive_panel';
const String kTronReceivePanelCreateBtnKey =
    'tron_receive_panel_create_btn';
const String kTronReceivePanelQrKey = 'tron_receive_panel_qr';
const String kTronReceivePanelAddressTextKey =
    'tron_receive_panel_address_text';
const String kTronReceivePanelCopyBtnKey =
    'tron_receive_panel_copy_btn';
const String kTronReceivePanelWarningKey =
    'tron_receive_panel_warning';
const String kTronReceivePanelGasNoteKey =
    'tron_receive_panel_gas_note';
const String kTronReceivePanelDisabledKey =
    'tron_receive_panel_disabled';
const String kTronReceivePanelNoKeySnackKey =
    'tron_receive_panel_no_key_snackbar';


class CryptoWalletEngineTronReceivePanel extends StatefulWidget {
  final String authToken;
  final VaultAIClient client;
  final Future<String> Function(String plaintext) encryptForVault;
  final bool Function() isVaultKeyAvailable;
  final CryptoWalletFeatures? features;
  final String walletLabel;

  const CryptoWalletEngineTronReceivePanel({
    super.key,
    required this.authToken,
    required this.client,
    required this.encryptForVault,
    required this.isVaultKeyAvailable,
    this.features,
    this.walletLabel = 'Svaultai TRON wallet',
  });

  @override
  State<CryptoWalletEngineTronReceivePanel> createState() =>
      _CryptoWalletEngineTronReceivePanelState();
}

class _CryptoWalletEngineTronReceivePanelState
    extends State<CryptoWalletEngineTronReceivePanel> {
  Map<String, dynamic>? _state;
  bool _loading = true;
  String? _error;
  bool _creating = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  bool get _tronEnabled =>
      widget.features?.tronEnabled ?? true;

  Future<void> _load() async {
    if (!_tronEnabled) {
      setState(() {
        _state = {'wallet_engine': 'tron_not_enabled'};
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
        network: kTronNetworkId,
        asset: kTronAssetTicker,
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
          key: Key(kTronReceivePanelNoKeySnackKey),
          content: Text(
            kTronReceiveCreateBlockedNoVaultKey, maxLines: 3,
          ),
        ),
      );
      return;
    }
    setState(() {
      _creating = true;
      _error = null;
    });

    GeneratedTronWallet? wallet;
    String? encryptedSecret;
    String publicAddress = '';
    try {
      wallet = generateTronWallet();
      publicAddress = wallet.publicAddress;
      final secretJson = jsonEncode({
        'schema':        'tron_secret_v1',
        'keyOrigin':     'generated_client_side',
        'privateKeyHex': wallet.privateKeyHex,
      });
      encryptedSecret = await widget.encryptForVault(secretJson);
      wipeTronPrivateKeyHex(wallet.privateKeyHex);
      wallet = null;
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _error = 'TRON wallet generation failed: $e';
      });
      return;
    }

    try {
      await widget.client.createCryptoWalletAccountNetwork(
        network: kTronNetworkId,
        asset: kTronAssetTicker,
        authToken: widget.authToken,
        walletLabel: widget.walletLabel,
        publicAddress: publicAddress,
        encryptedWalletSecret: encryptedSecret,
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _error = 'Create TRON wallet failed: $e';
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
        content: Text(kTronReceiveCopyDoneSnackbar),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return WalletDarkPanelScope(
      child: SingleChildScrollView(
        key: const Key(kTronReceivePanelKey),
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
              kTronReceiveLoadingLabel,
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

    if (status == 'tron_not_enabled') {
      return Padding(
        key: const Key(kTronReceivePanelDisabledKey),
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
                  kTronReceiveDisabledMessage,
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
    if (status == 'create_tron_wallet_first' || status == 'no_account') {
      return _buildCreateState(context);
    }
    if (status == 'receive_ready') {
      return _buildReadyState(context, body);
    }
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Text('Unexpected TRON wallet status: $status'),
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
            kTronReceivePanelTitle,
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            kTronReceiveNetworkBadge,
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
                    kTronReceiveNonCustodialAttestation,
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
            key: const Key(kTronReceivePanelCreateBtnKey),
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
            label: const Text(kTronReceiveCreateButtonLabel),
            style: walletPrimaryButtonStyle(),
          ),
        ],
      ),
    );
  }

  Widget _buildReadyState(BuildContext ctx, Map<String, dynamic> body) {
    final addr = (body['publicAddress'] ?? '').toString();
    final label = (body['walletLabel'] ?? '').toString();
    // 2026-07-13 mobile fix: at 320 dp the fixed 18 dp outer padding
    // + a 220 dp QR container was leaving zero slack for asset warning
    // rows and the copy button, causing a 29 px right-side RenderFlex
    // overflow. Shrink outer padding + QR size on narrow viewports.
    final w = MediaQuery.of(ctx).size.width;
    final narrow = w < 380;
    final outerPad = narrow ? 12.0 : 18.0;
    final qrSize = narrow ? 180.0 : 220.0;
    return Padding(
      padding: EdgeInsets.all(outerPad),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kTronReceivePanelTitle,
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
          const Text(kTronReceiveNetworkBadge, style: kWalletMutedStyle),
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
                      key: const Key(kTronReceivePanelQrKey),
                      data: addr,
                      version: QrVersions.auto,
                      size: qrSize,
                      backgroundColor: Colors.white,
                    ),
                  )
                : const SizedBox.shrink(),
          ),
          const SizedBox(height: 14),
          // 2026-07-13 mobile fix: SelectableText for a 34-char TRON
          // address is a single unbroken token — Flutter's default text
          // wrap can't split at whitespace. At 320 dp the address
          // would overflow the panel to the right. Wrap in a horizontal
          // scroll pinned to the container's inner width so the
          // address stays fully copyable but its intrinsic width no
          // longer forces the outer layout to overflow.
          SizedBox(
            width: double.infinity,
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: kWalletBgBase,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: kWalletBorder),
              ),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: SelectableText(
                  addr,
                  key: const Key(kTronReceivePanelAddressTextKey),
                  style: kWalletMonoStyle,
                ),
              ),
            ),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const Key(kTronReceivePanelCopyBtnKey),
            onPressed: () => _copyAddress(addr),
            icon: const Icon(Icons.copy_rounded, size: 16),
            label: const Text(kTronReceiveCopyButtonLabel),
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
                        ?? kTronReceiveAssetWarning).toString(),
                    key: const Key(kTronReceivePanelWarningKey),
                    style: const TextStyle(
                      color: kWalletAccentWarning,
                      fontSize: 13,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: kWalletBgBase,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: kWalletBorder),
            ),
            child: Row(
              children: [
                const Icon(Icons.local_gas_station_outlined, size: 16,
                    color: kWalletTextSecondary),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    (body['gasNote']
                        ?? kTronReceiveGasNote).toString(),
                    key: const Key(kTronReceivePanelGasNoteKey),
                    style: kWalletMutedStyle,
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
