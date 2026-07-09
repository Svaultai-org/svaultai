
import 'package:flutter/material.dart';

import '../api_client.dart';
import '../services/evm_networks.dart';
import 'crypto_wallet_engine_design.dart';


const String kMainnetErc20ReceiveCardHeader = 'Ethereum Mainnet · ERC20';

const String kMainnetErc20ReceiveComingSoonHeadline =
    'Ethereum Mainnet token receive is not enabled yet.';

const String kMainnetErc20ReceiveComingSoonBody =
    'Ethereum Mainnet token receive is not enabled in this build.';

const String kMainnetErc20ReceiveEnabledOpenButton = 'Open receive';

const String kMainnetErc20ReceiveCreateEthFirstBanner =
    'Create your Ethereum Mainnet wallet first. USDT and USDC on '
    'Ethereum Mainnet share your ETH wallet address.';

const String kMainnetErc20ReceiveCardKey =
    'crypto_wallet_engine_mainnet_erc20_receive_card';
const String kMainnetErc20ReceiveStatusKey =
    'crypto_wallet_engine_mainnet_erc20_receive_status';
const String kMainnetErc20ReceiveAddressKey =
    'crypto_wallet_engine_mainnet_erc20_receive_address';
const String kMainnetErc20ReceiveSendDisabledKey =
    'crypto_wallet_engine_mainnet_erc20_send_disabled';
const String kMainnetErc20ReceiveSharedAddressKey =
    'crypto_wallet_engine_mainnet_erc20_shared_address_note';
const String kMainnetErc20ReceiveGasNoteKey =
    'crypto_wallet_engine_mainnet_erc20_gas_note';


const String kMainnetErc20AssetUsdt = 'USDT_ERC20';
const String kMainnetErc20AssetUsdc = 'USDC_ERC20';

String _tokenLabelForAsset(String asset) {
  if (asset == kMainnetErc20AssetUsdt) return 'USDT';
  if (asset == kMainnetErc20AssetUsdc) return 'USDC';
  return asset;
}


class CryptoWalletEngineMainnetErc20ReceiveCard extends StatefulWidget {
  final String asset;
  final String? authToken;
  final VaultAIClient? apiClient;

  const CryptoWalletEngineMainnetErc20ReceiveCard({
    super.key,
    required this.asset,
    this.authToken,
    this.apiClient,
  });

  @override
  State<CryptoWalletEngineMainnetErc20ReceiveCard> createState() =>
      _CryptoWalletEngineMainnetErc20ReceiveCardState();
}

enum _MainnetTokenFetchState {
  idle, loading, ready, createEthFirst, blocked, error,
}

class _CryptoWalletEngineMainnetErc20ReceiveCardState
    extends State<CryptoWalletEngineMainnetErc20ReceiveCard> {
  _MainnetTokenFetchState _state = _MainnetTokenFetchState.idle;
  String? _address;
  String? _statusMessage;

  bool get _hasWiring =>
      widget.authToken != null && widget.apiClient != null;

  Future<void> _loadReceive() async {
    if (!kCryptoWalletEngineMainnetErc20ReceiveEnabled) {
      setState(() {
        _state = _MainnetTokenFetchState.blocked;
        _statusMessage = kMainnetErc20ReceiveComingSoonHeadline;
      });
      return;
    }
    if (!_hasWiring) {
      setState(() {
        _state = _MainnetTokenFetchState.blocked;
        _statusMessage = kMainnetErc20ReceiveCreateEthFirstBanner;
      });
      return;
    }
    setState(() {
      _state = _MainnetTokenFetchState.loading;
      _statusMessage = null;
    });
    try {
      final body = await widget.apiClient!.getCryptoWalletReceiveNetwork(
        network: kEvmNetworkEthereumMainnet,
        asset: widget.asset,
        authToken: widget.authToken!,
      );
      if (!mounted) return;
      final status = (body['wallet_engine'] ?? '').toString();
      if (status == 'receive_ready') {
        final raw = body['publicAddress'];
        setState(() {
          _state = _MainnetTokenFetchState.ready;
          _address = raw is String && raw.isNotEmpty ? raw : null;
          _statusMessage = (body['warning'] ?? '').toString();
        });
        return;
      }
      if (status == 'create_eth_mainnet_wallet_first') {
        setState(() {
          _state = _MainnetTokenFetchState.createEthFirst;
          _statusMessage = kMainnetErc20ReceiveCreateEthFirstBanner;
        });
        return;
      }
      setState(() {
        _state = _MainnetTokenFetchState.blocked;
        _statusMessage = kMainnetErc20ReceiveComingSoonBody;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _state = _MainnetTokenFetchState.error;
        _statusMessage = 'Balance temporarily unavailable.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final isEnabled = kCryptoWalletEngineMainnetErc20ReceiveEnabled;
    final tokenLabel = _tokenLabelForAsset(widget.asset);
    final title = '$tokenLabel Receive';
    return Container(
      key: const Key(kMainnetErc20ReceiveCardKey),
      padding: const EdgeInsets.all(14),
      decoration: walletDarkCard(
        accent: kWalletAccentPrimary,
        elevated: true,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.south_rounded,
                size: 18,
                color: kWalletAccentPrimarySoft,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    color: kWalletTextPrimary,
                  ),
                ),
              ),
              _NetworkChip(label: kMainnetErc20ReceiveCardHeader),
            ],
          ),
          const SizedBox(height: 10),
          if (isEnabled) ...[
            Text(
              kEvmNetworkMainnetTokenReceiveRealFundsHeadline
                  .replaceAll('{token}', tokenLabel),
              style: const TextStyle(
                color: kWalletTextSecondary, fontSize: 13,
              ),
            ),
            const SizedBox(height: 8),
            _CompactNote(
              key: const Key(kMainnetErc20ReceiveSharedAddressKey),
              icon: Icons.link_rounded,
              label: kEvmNetworkMainnetTokenSharedAddressNote,
            ),
            const SizedBox(height: 6),
            _CompactNote(
              key: const Key(kMainnetErc20ReceiveGasNoteKey),
              icon: Icons.local_gas_station_outlined,
              label: kEvmNetworkMainnetTokenGasNote,
            ),
            const SizedBox(height: 8),
            _SendDisabledPill(
              key: const Key(kMainnetErc20ReceiveSendDisabledKey),
              label: kEvmNetworkMainnetTokenSendBlockedCopy,
            ),
            const SizedBox(height: 12),
            ElevatedButton.icon(
              key: const Key(
                'crypto_wallet_engine_mainnet_erc20_receive_open_btn',
              ),
              onPressed: _loadReceive,
              icon: const Icon(Icons.south_rounded, size: 16),
              label: const Text(kMainnetErc20ReceiveEnabledOpenButton),
              style: walletPrimaryButtonStyle(),
            ),
            if (_state != _MainnetTokenFetchState.idle) ...[
              const SizedBox(height: 10),
              _buildStatusBody(tokenLabel),
            ],
          ] else ...[
            const Text(
              kMainnetErc20ReceiveComingSoonBody,
              style: TextStyle(color: kWalletTextSecondary, fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStatusBody(String tokenLabel) {
    if (_state == _MainnetTokenFetchState.loading) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: const [
          SizedBox(
            width: 14, height: 14,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              valueColor: AlwaysStoppedAnimation<Color>(
                kWalletAccentPrimary,
              ),
            ),
          ),
          SizedBox(width: 8),
          Text(
            'Loading…',
            style: TextStyle(color: kWalletTextSecondary, fontSize: 13),
          ),
        ],
      );
    }
    if (_state == _MainnetTokenFetchState.ready &&
        _address != null && _address!.isNotEmpty) {
      return Container(
        key: const Key(kMainnetErc20ReceiveAddressKey),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: kWalletBgBase,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: kWalletBorder),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Ethereum Mainnet $tokenLabel address',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: kWalletTextSecondary,
                letterSpacing: 0.3,
              ),
            ),
            const SizedBox(height: 4),
            SelectableText(
              _address!,
              style: kWalletMonoStyle,
            ),
          ],
        ),
      );
    }
    return Container(
      key: const Key(kMainnetErc20ReceiveStatusKey),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: kWalletBgBase,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: kWalletBorder),
      ),
      child: Text(
        _statusMessage ?? '',
        style: const TextStyle(color: kWalletTextSecondary, fontSize: 12),
      ),
    );
  }
}


class _NetworkChip extends StatelessWidget {
  final String label;
  const _NetworkChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: kWalletAccentPrimary.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: kWalletAccentPrimary.withOpacity(0.4)),
      ),
      child: Text(
        label,
        style: const TextStyle(
          color: kWalletAccentPrimarySoft,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}


class _CompactNote extends StatelessWidget {
  final IconData icon;
  final String label;
  const _CompactNote({
    super.key,
    required this.icon,
    required this.label,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: kWalletBgBase,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: kWalletBorder),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: kWalletTextSecondary),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              label,
              style: const TextStyle(
                color: kWalletTextSecondary,
                fontSize: 12,
              ),
            ),
          ),
        ],
      ),
    );
  }
}


class _SendDisabledPill extends StatelessWidget {
  final String label;
  const _SendDisabledPill({super.key, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: kWalletAccentWarning.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: kWalletAccentWarning.withOpacity(0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(
            Icons.pause_circle_outline_rounded,
            size: 13,
            color: kWalletAccentWarning,
          ),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              color: kWalletAccentWarning,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}
