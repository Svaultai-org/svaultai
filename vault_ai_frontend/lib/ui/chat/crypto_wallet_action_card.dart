

import 'package:flutter/material.dart';

import '../crypto_wallet_engine_design.dart';
import 'chat_models.dart';


const String kCryptoWalletActionIntentOpenCryptoWallet =
    'open_crypto_wallet';
const String kCryptoWalletActionIntentShowWallet = 'show_wallet';
const String kCryptoWalletActionIntentShowBalance = 'show_balance';
const String kCryptoWalletActionIntentReceiveAddress = 'receive_address';
const String kCryptoWalletActionIntentReceiveQr = 'receive_qr';
const String kCryptoWalletActionIntentSendDraft = 'send_draft';
const String kCryptoWalletActionIntentShowTransactions = 'show_transactions';
const String kCryptoWalletActionIntentUnsupportedAsset =
    'unsupported_asset';
const String kCryptoWalletActionIntentUnsupportedNetwork =
    'unsupported_network';
const String kCryptoWalletActionIntentMoneroSpecial = 'monero_special';
const String kCryptoWalletActionIntentClarifyNetwork = 'clarify_network';

const List<String> kAllCryptoWalletActionIntents = [
  kCryptoWalletActionIntentOpenCryptoWallet,
  kCryptoWalletActionIntentShowWallet,
  kCryptoWalletActionIntentShowBalance,
  kCryptoWalletActionIntentReceiveAddress,
  kCryptoWalletActionIntentReceiveQr,
  kCryptoWalletActionIntentSendDraft,
  kCryptoWalletActionIntentShowTransactions,
  kCryptoWalletActionIntentUnsupportedAsset,
  kCryptoWalletActionIntentUnsupportedNetwork,
  kCryptoWalletActionIntentMoneroSpecial,
  kCryptoWalletActionIntentClarifyNetwork,
];


const Set<String> kCryptoWalletActionBlockedReasons = {
  'engine_disabled',
  'mainnet_disabled',
  'monero_special',
  'unsupported_asset',
  'unsupported_network',
  'clarify_network',
  'missing_send_fields',
};


typedef CryptoWalletActionCallback = void Function(
  CryptoWalletActionRequest request,
);

class CryptoWalletActionRequest {
  final String intent;
  final String? asset;
  final String? network;
  final String? amount;
  final String? amountUnit;
  final String? destinationAddress;
  final String? blockedReason;

  const CryptoWalletActionRequest({
    required this.intent,
    this.asset,
    this.network,
    this.amount,
    this.amountUnit,
    this.destinationAddress,
    this.blockedReason,
  });
}

// 2026-07-13 dark-mode refresh: the old CryptoWalletActionCard hardcoded
// Colors.white + light-blue/orange chips + a bright ElevatedButton, which
// looked pasted-in when it rendered inside SVaultAI's forced-dark chat
// UI. It now uses the same wallet design tokens (walletDarkCard,
// walletGhostButtonStyle, kWalletTextPrimary/Muted, kWalletAccent*) as
// its sibling crypto chat cards in lib/ui/crypto_vault_chat_cards.dart,
// so Balance / Receive / Send / Transactions chat replies belong to one
// coherent design system regardless of which router path they came from.
class CryptoWalletActionCard extends StatelessWidget {
  final ChatMessage msg;
  final CryptoWalletActionCallback? onAction;

  const CryptoWalletActionCard({
    super.key,
    required this.msg,
    this.onAction,
  });

  Map<String, dynamic> get _payload =>
      msg.payload ?? const <String, dynamic>{};

  String get _intent =>
      (_payload['intent'] ?? '').toString();

  String? get _asset {
    final raw = _payload['asset'];
    if (raw is String && raw.isNotEmpty) return raw;
    return null;
  }

  String? get _network {
    final raw = _payload['network'];
    if (raw is String && raw.isNotEmpty) return raw;
    return null;
  }

  String? get _amount {
    final raw = _payload['amount'];
    if (raw is String && raw.isNotEmpty) return raw;
    return null;
  }

  String? get _amountUnit {
    final raw = _payload['amountUnit'];
    if (raw is String && raw.isNotEmpty) return raw;
    return null;
  }

  String? get _destination {
    final raw = _payload['destinationAddress'];
    if (raw is String && raw.isNotEmpty) return raw;
    return null;
  }

  String? get _blockedReason {
    final raw = _payload['blockedReason'];
    if (raw is String && raw.isNotEmpty) return raw;
    return null;
  }

  bool get _isBlocked => _blockedReason != null;

  String get _actionLabel {
    switch (_intent) {
      case kCryptoWalletActionIntentSendDraft:
        return 'Open send review';
      case kCryptoWalletActionIntentReceiveAddress:
      case kCryptoWalletActionIntentReceiveQr:
        return 'Open receive';
      case kCryptoWalletActionIntentShowBalance:
        return 'Open balance';
      case kCryptoWalletActionIntentShowTransactions:
        return 'Open activity';
      case kCryptoWalletActionIntentOpenCryptoWallet:
      case kCryptoWalletActionIntentShowWallet:
      default:
        return 'Open Crypto Vault';
    }
  }

  IconData get _actionIcon {
    switch (_intent) {
      case kCryptoWalletActionIntentSendDraft:
        return Icons.north;
      case kCryptoWalletActionIntentReceiveAddress:
      case kCryptoWalletActionIntentReceiveQr:
        return Icons.south;
      case kCryptoWalletActionIntentShowBalance:
        return Icons.account_balance_wallet_outlined;
      case kCryptoWalletActionIntentShowTransactions:
        return Icons.history;
      case kCryptoWalletActionIntentOpenCryptoWallet:
      case kCryptoWalletActionIntentShowWallet:
      default:
        return Icons.open_in_new;
    }
  }

  String _headerLabel() {
    switch (_intent) {
      case kCryptoWalletActionIntentUnsupportedNetwork:
        return 'Ethereum Mainnet — not enabled';
      case kCryptoWalletActionIntentUnsupportedAsset:
        return 'Asset not connected yet';
      case kCryptoWalletActionIntentMoneroSpecial:
        return 'Monero — special design needed';
      case kCryptoWalletActionIntentClarifyNetwork:
        return 'Which network?';
      case kCryptoWalletActionIntentSendDraft:
        if (_isBlocked) return 'Send review — missing details';
        return 'Send review';
      case kCryptoWalletActionIntentReceiveAddress:
      case kCryptoWalletActionIntentReceiveQr:
        return 'Receive';
      case kCryptoWalletActionIntentShowBalance:
        return 'Balance';
      case kCryptoWalletActionIntentShowTransactions:
        return 'Transactions';
      case kCryptoWalletActionIntentOpenCryptoWallet:
      case kCryptoWalletActionIntentShowWallet:
      default:
        return 'Crypto Vault';
    }
  }

  Color _accentColor() {
    // Match the wallet dark palette. Warnings share the wallet warning
    // color; blocked/disabled uses the muted text color so the whole
    // card reads as "not actionable" without competing with actionable
    // Balance/Receive cards.
    if (_blockedReason == 'mainnet_disabled' ||
        _blockedReason == 'unsupported_network' ||
        _blockedReason == 'monero_special' ||
        _blockedReason == 'unsupported_asset' ||
        _blockedReason == 'clarify_network' ||
        _blockedReason == 'missing_send_fields') {
      return kWalletAccentWarning;
    }
    if (_blockedReason == 'engine_disabled') {
      return kWalletTextMuted;
    }
    return kWalletAccentPrimary;
  }

  Color _accentSoft(Color accent) =>
      Color.alphaBlend(accent.withOpacity(0.14), kWalletSurfaceElevated);

  @override
  Widget build(BuildContext context) {
    final accent = _accentColor();
    final header = _headerLabel();
    final asset = _asset;
    final network = _network;
    return Container(
      key: const Key('crypto_wallet_action_card'),
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(14),
      decoration: walletDarkCard(accent: accent),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Icon(_actionIcon, size: 18, color: accent),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  header,
                  key: const Key('crypto_wallet_action_card_header'),
                  overflow: TextOverflow.ellipsis,
                  maxLines: 2,
                  style: TextStyle(
                    color: accent,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.1,
                  ),
                ),
              ),
            ],
          ),
          if (asset != null || network != null) ...[
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                if (asset != null)
                  _Chip(
                    keyName: 'crypto_wallet_action_card_asset_chip',
                    label: asset,
                    accent: accent,
                    background: _accentSoft(accent),
                  ),
                if (network != null)
                  _Chip(
                    keyName: 'crypto_wallet_action_card_network_chip',
                    label: _networkDisplay(network),
                    accent: kWalletAccentWarning,
                    background: _accentSoft(kWalletAccentWarning),
                  ),
              ],
            ),
          ],
          const SizedBox(height: 10),
          Text(
            msg.text,
            key: const Key('crypto_wallet_action_card_message'),
            style: const TextStyle(
              fontSize: 13,
              height: 1.4,
              color: kWalletTextPrimary,
            ),
          ),
          if (_intent == kCryptoWalletActionIntentSendDraft &&
              !_isBlocked &&
              (_amount != null || _destination != null)) ...[
            const SizedBox(height: 10),
            Container(
              key: const Key('crypto_wallet_action_card_send_preview'),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: kWalletSurfaceElevated,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: kWalletBorder, width: 1),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (_amount != null)
                    Text(
                      'Amount: ${_amount!}'
                      '${_amountUnit != null ? ' $_amountUnit' : ''}',
                      key: const Key('crypto_wallet_action_card_amount'),
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: kWalletTextPrimary,
                      ),
                    ),
                  if (_destination != null) ...[
                    const SizedBox(height: 4),
                    SelectableText(
                      'To: ${_destination!}',
                      key: const Key(
                        'crypto_wallet_action_card_destination',
                      ),
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 12,
                        color: kWalletTextPrimary,
                      ),
                    ),
                  ],
                  const SizedBox(height: 6),
                  const Text(
                    'Review the address, amount, and fee on the next '
                    'screen. PIN is required to sign and broadcast.',
                    style: TextStyle(
                      color: kWalletTextMuted,
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
            ),
          ],
          if (!_isBlocked) ...[
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const Key('crypto_wallet_action_card_open_btn'),
              onPressed: onAction == null
                  ? null
                  : () => onAction!(_request()),
              icon: Icon(_actionIcon, size: 16),
              label: Text(
                _actionLabel,
                overflow: TextOverflow.ellipsis,
              ),
              style: walletGhostButtonStyle(),
            ),
          ] else ...[
            const SizedBox(height: 12),
            Container(
              key: const Key('crypto_wallet_action_card_blocker_note'),
              padding: const EdgeInsets.all(10),
              decoration: walletWarningPanel(),
              child: Text(
                _blockerHint(),
                style: const TextStyle(
                  color: kWalletTextPrimary,
                  fontSize: 12,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  CryptoWalletActionRequest _request() => CryptoWalletActionRequest(
        intent: _intent,
        asset: _asset,
        network: _network,
        amount: _amount,
        amountUnit: _amountUnit,
        destinationAddress: _destination,
        blockedReason: _blockedReason,
      );

  String _blockerHint() {
    switch (_blockedReason) {
      case 'engine_disabled':
        return 'The Crypto Wallet Engine is off in this build.';
      case 'mainnet_disabled':
        return 'Mainnet is not enabled. I can only act on Ethereum '
            'Sepolia testnet right now.';
      case 'monero_special':
        return 'Monero requires a separate privacy-wallet design.';
      case 'unsupported_asset':
        return 'This asset is not connected to the wallet engine yet.';
      case 'unsupported_network':
        return 'This network is not connected to the wallet engine yet.';
      case 'clarify_network':
        return 'Please name the network: Ethereum Sepolia testnet is '
            'the only network currently supported.';
      case 'missing_send_fields':
        return 'Please include both the amount and the destination '
            'address.';
      default:
        return 'This action cannot run from chat right now.';
    }
  }

  static String _networkDisplay(String network) {
    switch (network) {
      case 'ethereum_sepolia':
        return 'Ethereum Sepolia testnet';
      case 'ethereum_mainnet':
        return 'Ethereum Mainnet';
      default:
        return network;
    }
  }
}


class _Chip extends StatelessWidget {
  final String keyName;
  final String label;
  final Color accent;
  final Color background;

  const _Chip({
    required this.keyName,
    required this.label,
    required this.accent,
    required this.background,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key(keyName),
      constraints: const BoxConstraints(maxWidth: 220),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: accent.withOpacity(0.35), width: 1),
      ),
      child: Text(
        label,
        overflow: TextOverflow.ellipsis,
        maxLines: 1,
        style: TextStyle(
          color: accent,
          fontSize: 11,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.2,
        ),
      ),
    );
  }
}
