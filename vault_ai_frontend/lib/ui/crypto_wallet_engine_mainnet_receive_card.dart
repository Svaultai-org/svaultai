
import 'package:flutter/material.dart';

import '../api_client.dart';
import '../services/evm_networks.dart';
import 'crypto_wallet_engine_design.dart';


const String kMainnetReceiveCardHeader = 'ETH Receive';
const String kMainnetReceiveNetworkLabel = 'Ethereum Mainnet';

const String kMainnetReceiveComingSoonHeadline =
    'Ethereum Mainnet receive is not enabled yet.';

const String kMainnetReceiveComingSoonBody =
    'Ethereum Mainnet receive is not enabled in this build.';

const String kMainnetReceiveEnabledOpenButton = 'Open receive';

const String kMainnetReceiveSendBlockedSnackbar =
    'Sending is not enabled yet.';

const String kMainnetReceiveCreateWalletFirstBanner =
    'Create your Ethereum Mainnet wallet first to see a receive address.';

const String kMainnetReceiveCardKey =
    'crypto_wallet_engine_mainnet_receive_card';
const String kMainnetReceiveStatusKey =
    'crypto_wallet_engine_mainnet_receive_status';
const String kMainnetReceiveAddressKey =
    'crypto_wallet_engine_mainnet_receive_address';
const String kMainnetReceiveSendDisabledKey =
    'crypto_wallet_engine_mainnet_send_disabled';


class CryptoWalletEngineMainnetReceiveCard extends StatefulWidget {
  final String? authToken;
  final VaultAIClient? apiClient;

  const CryptoWalletEngineMainnetReceiveCard({
    super.key,
    this.authToken,
    this.apiClient,
  });

  @override
  State<CryptoWalletEngineMainnetReceiveCard> createState() =>
      _CryptoWalletEngineMainnetReceiveCardState();
}

enum _MainnetFetchState { idle, loading, ready, noAccount, blocked, error }

class _CryptoWalletEngineMainnetReceiveCardState
    extends State<CryptoWalletEngineMainnetReceiveCard> {
  _MainnetFetchState _state = _MainnetFetchState.idle;
  String? _address;
  String? _statusMessage;

  bool get _hasWiring =>
      widget.authToken != null && widget.apiClient != null;

  Future<void> _loadReceive() async {
    if (!kCryptoWalletEngineMainnetReceiveEnabled) {
      setState(() {
        _state = _MainnetFetchState.blocked;
        _statusMessage = kMainnetReceiveComingSoonHeadline;
      });
      return;
    }
    if (!_hasWiring) {
      setState(() {
        _state = _MainnetFetchState.blocked;
        _statusMessage = kMainnetReceiveCreateWalletFirstBanner;
      });
      return;
    }
    setState(() {
      _state = _MainnetFetchState.loading;
      _statusMessage = null;
    });
    try {
      final body = await widget.apiClient!.getCryptoWalletReceiveNetwork(
        network: kEvmNetworkEthereumMainnet,
        asset: 'ETH',
        authToken: widget.authToken!,
      );
      if (!mounted) return;
      final status = (body['wallet_engine'] ?? '').toString();
      if (status == 'receive_ready') {
        final raw = body['publicAddress'];
        setState(() {
          _state = _MainnetFetchState.ready;
          _address = raw is String && raw.isNotEmpty ? raw : null;
          _statusMessage = (body['warning'] ?? '').toString();
        });
        return;
      }
      if (status == 'no_account') {
        setState(() {
          _state = _MainnetFetchState.noAccount;
          _statusMessage = kMainnetReceiveCreateWalletFirstBanner;
        });
        return;
      }
      setState(() {
        _state = _MainnetFetchState.blocked;
        _statusMessage = kMainnetReceiveComingSoonBody;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _state = _MainnetFetchState.error;
        _statusMessage = 'Balance temporarily unavailable.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final isEnabled = kCryptoWalletEngineMainnetReceiveEnabled;
    return Container(
      key: const Key(kMainnetReceiveCardKey),
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
              const Expanded(
                child: Text(
                  kMainnetReceiveCardHeader,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    color: kWalletTextPrimary,
                  ),
                ),
              ),
              _MainnetChip(
                label: kMainnetReceiveNetworkLabel,
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (isEnabled) ...[
            const Text(
              kEvmNetworkMainnetReceiveRealFundsHeadline,
              style: TextStyle(
                color: kWalletTextSecondary, fontSize: 13,
              ),
            ),
            const SizedBox(height: 8),
            _SendDisabledPill(
              key: const Key(kMainnetReceiveSendDisabledKey),
              label: kEvmNetworkMainnetSendBlockedCopy,
            ),
            const SizedBox(height: 12),
            ElevatedButton.icon(
              key: const Key(
                'crypto_wallet_engine_mainnet_receive_open_btn',
              ),
              onPressed: _loadReceive,
              icon: const Icon(Icons.south_rounded, size: 16),
              label: const Text(kMainnetReceiveEnabledOpenButton),
              style: walletPrimaryButtonStyle(),
            ),
            if (_state != _MainnetFetchState.idle) ...[
              const SizedBox(height: 10),
              _buildStatusBody(),
            ],
          ] else ...[
            const Text(
              kMainnetReceiveComingSoonBody,
              style: TextStyle(color: kWalletTextSecondary, fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStatusBody() {
    if (_state == _MainnetFetchState.loading) {
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
    if (_state == _MainnetFetchState.ready &&
        _address != null && _address!.isNotEmpty) {
      return Container(
        key: const Key(kMainnetReceiveAddressKey),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: kWalletBgBase,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: kWalletBorder),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Ethereum Mainnet address',
              style: TextStyle(
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
      key: const Key(kMainnetReceiveStatusKey),
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


class _MainnetChip extends StatelessWidget {
  final String label;
  const _MainnetChip({required this.label});

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
