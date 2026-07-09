

import 'package:flutter/material.dart';

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
    if (_blockedReason == 'mainnet_disabled' ||
        _blockedReason == 'unsupported_network') {
      return const Color(0xFF995500);
    }
    if (_blockedReason == 'monero_special' ||
        _blockedReason == 'unsupported_asset') {
      return const Color(0xFF995500);
    }
    if (_blockedReason == 'engine_disabled') {
      return Colors.black54;
    }
    return const Color(0xFF1F3D7A);
  }

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
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE0E0E0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                _actionIcon, size: 18, color: accent,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  header,
                  key: const Key('crypto_wallet_action_card_header'),
                  style: TextStyle(
                    color: accent,
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          if (asset != null || network != null) ...[
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                if (asset != null)
                  Container(
                    key: Key('crypto_wallet_action_card_asset_chip'),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6, vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFFEEF2FB),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      asset,
                      style: const TextStyle(
                        color: Color(0xFF1F3D7A),
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                if (network != null)
                  Container(
                    key: const Key('crypto_wallet_action_card_network_chip'),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6, vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFF3E0),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      _networkDisplay(network),
                      style: const TextStyle(
                        color: Color(0xFF995500),
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
              ],
            ),
          ],
          const SizedBox(height: 8),
          Text(
            msg.text,
            key: const Key('crypto_wallet_action_card_message'),
            style: const TextStyle(fontSize: 13, color: Colors.black87),
          ),
          if (_intent == kCryptoWalletActionIntentSendDraft &&
              !_isBlocked &&
              (_amount != null || _destination != null)) ...[
            const SizedBox(height: 8),
            Container(
              key: const Key('crypto_wallet_action_card_send_preview'),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFFF5F8FF),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFD8E2F7)),
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
                        fontSize: 13, fontWeight: FontWeight.w700,
                      ),
                    ),
                  if (_destination != null) ...[
                    const SizedBox(height: 4),
                    SelectableText(
                      'To: ${_destination!}',
                      key: const Key('crypto_wallet_action_card_destination'),
                      style: const TextStyle(
                        fontFamily: 'monospace', fontSize: 12,
                      ),
                    ),
                  ],
                  const SizedBox(height: 6),
                  const Text(
                    'Review the address, amount, and fee on the next '
                    'screen. PIN is required to sign and broadcast.',
                    style: TextStyle(color: Colors.black54, fontSize: 11),
                  ),
                ],
              ),
            ),
          ],
          if (!_isBlocked) ...[
            const SizedBox(height: 10),
            ElevatedButton.icon(
              key: const Key('crypto_wallet_action_card_open_btn'),
              onPressed: onAction == null
                  ? null
                  : () => onAction!(_request()),
              icon: Icon(_actionIcon, size: 16),
              label: Text(_actionLabel),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF1F3D7A),
                foregroundColor: Colors.white,
                elevation: 0,
              ),
            ),
          ] else ...[
            const SizedBox(height: 10),
            Container(
              key: const Key('crypto_wallet_action_card_blocker_note'),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF5E5),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: const Color(0xFFE5C079)),
              ),
              child: Text(
                _blockerHint(),
                style: const TextStyle(
                  color: Color(0xFF6B4A00), fontSize: 12,
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
