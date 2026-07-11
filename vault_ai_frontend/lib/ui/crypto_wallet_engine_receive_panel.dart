

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../api_client.dart';
import '../services/ethereum_wallet.dart';
import '../services/evm_networks.dart';
import 'crypto_wallet_engine_design.dart';


const String kEthReceivePanelTitle = 'Receive Ethereum';
const String kEthReceiveNetworkBadge = 'Ethereum Sepolia testnet';
const String kEthReceiveNetworkBadgeMainnet = 'Ethereum Mainnet';
const String kEthReceiveCreateButtonLabel = 'Create my Ethereum wallet';
const String kEthReceiveCopyButtonLabel = 'Copy address';
const String kEthReceiveCopyDoneSnackbar = 'Address copied to clipboard';
const String kEthReceiveNonCustodialAttestation =
    'Non-custodial: VaultAI never sees your private key. Your wallet is '
    'encrypted with your PIN and stored as ciphertext only.';
const String kEthReceiveAssetWarning =
    'Only send Ethereum (Sepolia testnet) to this address. Sending the '
    'wrong asset or sending on the wrong network may result in '
    'irreversible loss.';
const String kEthReceiveAssetWarningMainnet =
    'Only send ETH on Ethereum Mainnet to this address.';
const String kTokenReceiveAssetWarningMainnetTemplate =
    'Only send this ERC20 token on Ethereum Mainnet to this address.';
const String kTokenReceiveGasNoteMainnet =
    'Sending tokens requires ETH for gas.';
const String kEthReceiveCreateBlockedNoVaultKey =
    'Unlock your vault with your PIN before creating a wallet — the '
    'private key is encrypted with your vault key locally.';
const String kEthReceiveLoadingLabel = 'Loading wallet…';


const String kTokenReceiveSharedAddressBanner =
    'This token uses your existing Ethereum Sepolia wallet address. '
    'The same address holds USDT and USDC on Sepolia.';
const String kTokenReceiveSharedAddressBannerMainnet =
    'This token uses your existing Ethereum Mainnet wallet address. '
    'The same address holds USDT and USDC on Mainnet.';
const String kTokenReceiveCreateEthFirstBanner =
    'No Ethereum wallet exists yet. ERC20 tokens use your ETH '
    'Sepolia address — open the ETH card and tap Receive to create '
    'one first.';


const String _kEthNetworkLabel = 'Ethereum Sepolia';
const String _kEthNetworkLabelMainnet = 'Ethereum Mainnet';
const String _kEthAsset = 'ETH';
const String _kDefaultWalletLabel = 'VaultAI ETH wallet';


String receivePanelNetworkBadgeFor(String network) {
  return network == kEvmNetworkEthereumMainnet
      ? kEthReceiveNetworkBadgeMainnet
      : kEthReceiveNetworkBadge;
}


String receivePanelAssetWarningFor(String network, String asset) {
  if (network == kEvmNetworkEthereumMainnet) {
    if (asset == 'ETH') return kEthReceiveAssetWarningMainnet;
    return kTokenReceiveAssetWarningMainnetTemplate;
  }
  return kEthReceiveAssetWarning;
}


String receivePanelTokenSharedBannerFor(String network) {
  return network == kEvmNetworkEthereumMainnet
      ? kTokenReceiveSharedAddressBannerMainnet
      : kTokenReceiveSharedAddressBanner;
}


String receivePanelNetworkLabelFor(String network) {
  return network == kEvmNetworkEthereumMainnet
      ? _kEthNetworkLabelMainnet
      : _kEthNetworkLabel;
}


const Set<String> kReceivePanelTokenAssets = {'USDT_ERC20', 'USDC_ERC20'};


class CryptoWalletEngineReceivePanel extends StatefulWidget {
  final String authToken;
  final VaultAIClient client;
  final Future<String> Function(String plaintext) encryptForVault;
  final bool Function() isVaultKeyAvailable;


  final String asset;
  final String? network;

  const CryptoWalletEngineReceivePanel({
    super.key,
    required this.authToken,
    required this.client,
    required this.encryptForVault,
    required this.isVaultKeyAvailable,
    this.asset = _kEthAsset,
    this.network,
  });

  String get effectiveNetwork =>
      network ?? resolveCompileTimeDefaultNetwork();

  @override
  State<CryptoWalletEngineReceivePanel> createState() =>
      _CryptoWalletEngineReceivePanelState();
}

class _CryptoWalletEngineReceivePanelState
    extends State<CryptoWalletEngineReceivePanel> {
  
  
  Map<String, dynamic>? _state;
  bool _loading = true;
  String? _error;
  bool _creating = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  bool get _isToken =>
      kReceivePanelTokenAssets.contains(widget.asset);

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final body = widget.network != null
          ? await widget.client.getCryptoWalletReceiveNetwork(
              network: widget.effectiveNetwork,
              asset: widget.asset,
              authToken: widget.authToken,
            )
          : await widget.client.getCryptoWalletReceive(
              asset: widget.asset,
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
          key: Key('eth_receive_panel_no_key_snackbar'),
          content: Text(kEthReceiveCreateBlockedNoVaultKey, maxLines: 3),
        ),
      );
      return;
    }
    setState(() {
      _creating = true;
      _error = null;
    });
    
    
    GeneratedEthereumWallet? wallet = generateEthereumWallet();
    final pkLocal = wallet.privateKeyHex;
    final publicAddress = wallet.publicAddress;
    String? encryptedSecret;
    try {
      encryptedSecret = await widget.encryptForVault(pkLocal);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _error = 'Encryption failed: $e';
      });
      
      wallet = null;
      return;
    }
    
    
    wallet = null;
    try {
      if (widget.network != null) {
        await widget.client.createCryptoWalletAccountNetwork(
          network: widget.effectiveNetwork,
          asset: _kEthAsset,
          authToken: widget.authToken,
          walletLabel: _kDefaultWalletLabel,
          publicAddress: publicAddress,
          encryptedWalletSecret: encryptedSecret,
        );
      } else {
        await widget.client.createCryptoWalletAccount(
          asset: _kEthAsset,
          authToken: widget.authToken,
          walletLabel: _kDefaultWalletLabel,
          publicAddress: publicAddress,
          network: receivePanelNetworkLabelFor(widget.effectiveNetwork),
          encryptedWalletSecret: encryptedSecret,
        );
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _error = 'Create wallet failed: $e';
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
        key: Key('eth_receive_panel_copy_snackbar'),
        content: Text(kEthReceiveCopyDoneSnackbar),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return WalletDarkPanelScope(
      child: SingleChildScrollView(
        key: const Key('eth_receive_panel_scroll'),
        child: _buildBody(context),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_loading) {
      return Padding(
        key: const Key('eth_receive_panel_loading'),
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
              kEthReceiveLoadingLabel,
              style: TextStyle(color: kWalletTextPrimary),
            ),
          ],
        ),
      );
    }
    if (_error != null) {
      return Padding(
        key: const Key('eth_receive_panel_error'),
        padding: const EdgeInsets.all(16),
        child: Text(
          _error!,
          style: const TextStyle(color: kWalletAccentDanger),
        ),
      );
    }
    final body = _state ?? const <String, dynamic>{};
    final status = (body['wallet_engine'] ?? '').toString();

    if (status == 'engine_disabled') {
      return Padding(
        key: const Key('eth_receive_panel_engine_disabled'),
        padding: const EdgeInsets.all(18),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: walletWarningPanel(),
          child: Row(
            children: const [
              Icon(Icons.power_settings_new_rounded,
                  size: 18, color: kWalletAccentWarning),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Crypto Wallet Engine is disabled by the backend.',
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
    if (status == 'no_account') {
      
      
      if (_isToken) {
        return _buildCreateEthFirstState(context);
      }
      return _buildCreateState(context);
    }
    if (status == 'create_eth_wallet_first') {
      return _buildCreateEthFirstState(context);
    }
    if (status == 'receive_ready') {
      return _buildReadyState(context, body);
    }
    
    
    return Padding(
      key: const Key('eth_receive_panel_unknown_state'),
      padding: const EdgeInsets.all(16),
      child: Text('Unexpected wallet engine status: $status'),
    );
  }

  Widget _buildCreateEthFirstState(BuildContext ctx) {
    return Padding(
      key: const Key('eth_receive_panel_create_eth_first_state'),
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: const [
          Text(
            'Create an Ethereum wallet first',
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 18,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.2,
            ),
          ),
          SizedBox(height: 8),
          Text(
            kTokenReceiveCreateEthFirstBanner,
            maxLines: 4,
            style: kWalletBodyStyle,
          ),
        ],
      ),
    );
  }

  Widget _buildCreateState(BuildContext ctx) {
    return Padding(
      key: const Key('eth_receive_panel_create_state'),
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kEthReceivePanelTitle,
            style: TextStyle(
              color: kWalletTextPrimary,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            receivePanelNetworkBadgeFor(widget.effectiveNetwork),
            key: const Key('eth_receive_panel_network_badge'),
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
                    kEthReceiveNonCustodialAttestation,
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
            key: const Key('eth_receive_panel_create_btn'),
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
            label: const Text(kEthReceiveCreateButtonLabel),
            style: walletPrimaryButtonStyle(),
          ),
        ],
      ),
    );
  }

  Widget _buildReadyState(BuildContext ctx, Map<String, dynamic> body) {
    final addr = (body['publicAddress'] ?? '').toString();
    final label = (body['walletLabel'] ?? '').toString();
    final network = (body['network'] ?? _kEthNetworkLabel).toString();
    return Padding(
      key: const Key('eth_receive_panel_ready_state'),
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            kEthReceivePanelTitle,
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
          Text(network, style: kWalletMutedStyle),
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
                      key: const Key('eth_receive_panel_qr'),
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
              key: const Key('eth_receive_panel_address_text'),
              style: kWalletMonoStyle,
            ),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: const Key('eth_receive_panel_copy_btn'),
            onPressed: () => _copyAddress(addr),
            icon: const Icon(Icons.copy_rounded, size: 16),
            label: const Text(kEthReceiveCopyButtonLabel),
            style: walletGhostButtonStyle(),
          ),
          const SizedBox(height: 14),
          if (_isToken) ...[
            Container(
              key: const Key('eth_receive_panel_token_shared_banner'),
              padding: const EdgeInsets.all(12),
              decoration: walletSuccessPanel(),
              child: Row(
                children: [
                  const Icon(Icons.link_rounded, size: 16,
                      color: kWalletAccentSuccess),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      receivePanelTokenSharedBannerFor(
                        widget.effectiveNetwork,
                      ),
                      style: const TextStyle(
                        color: kWalletAccentSuccess,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            if (widget.effectiveNetwork
                == kEvmNetworkEthereumMainnet) ...[
              const SizedBox(height: 8),
              Container(
                key: const Key(
                  'eth_receive_panel_mainnet_gas_note',
                ),
                padding: const EdgeInsets.all(12),
                decoration: walletWarningPanel(),
                child: Row(
                  children: const [
                    Icon(Icons.local_gas_station_rounded, size: 16,
                        color: kWalletAccentWarning),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        kTokenReceiveGasNoteMainnet,
                        style: TextStyle(
                          color: kWalletAccentWarning,
                          fontSize: 13,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 10),
          ],
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
                        ?? receivePanelAssetWarningFor(
                          widget.effectiveNetwork,
                          widget.asset,
                        )).toString(),
                    key: const Key('eth_receive_panel_asset_warning'),
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
