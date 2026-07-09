

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../l10n/app_localizations.dart';


const Set<String> kReceiveSupportedNetworks = <String>{
  'BTC',
  'ETH',
  'USDT TRC20',
  'USDT ERC20',
  'USDC ERC20',
  'SOL',
  'BNB',
  'XMR',
};


const String kReceiveNetworkWarning =
    'Only send assets on the selected network to this address. '
    'Sending the wrong asset or network may permanently lose funds.';


const String kReceiveReceiveOnlyHint =
    'Receive-only. Your vault stores this address so you can '
    'share it to receive funds.';


String maskWalletAddressForReceive(String address) {
  final raw = address.replaceAll(RegExp(r'\s+'), '');
  if (raw.isEmpty) return '';
  if (raw.length < 12) return raw;
  return '${raw.substring(0, 6)}…${raw.substring(raw.length - 4)}';
}


class ReceivePanel extends StatelessWidget {
  const ReceivePanel({
    super.key,
    required this.title,
    required this.address,
    this.network,
    this.onCopy,
    this.onClose,
  });

  
  final String title;

  
  final String address;

  
  final String? network;

  
  final void Function(String address)? onCopy;

  
  final VoidCallback? onClose;

  Future<void> _defaultCopy(BuildContext context) async {
    final label = AppLocalizations.of(context).snackAddressCopied;
    await Clipboard.setData(ClipboardData(text: address));
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(label)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final masked = maskWalletAddressForReceive(address);
    final isMobile = MediaQuery.of(context).size.width < 480;
    final qrSize = isMobile ? 200.0 : 240.0;
    return ConstrainedBox(
      key: const Key('crypto_receive_panel'),
      constraints: const BoxConstraints(maxWidth: 480),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      key: const Key('crypto_receive_title'),
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 18,
                      ),
                    ),
                    if (network != null && network!.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      _NetworkChip(network: network!),
                    ],
                    if (masked.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(
                        masked,
                        key: const Key('crypto_receive_masked'),
                        style: const TextStyle(
                          color: Color(0xFFB4B4B4),
                          fontSize: 12,
                          fontFamily: 'monospace',
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (onClose != null)
                IconButton(
                  key: const Key('crypto_receive_close'),
                  tooltip: 'Close',
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: onClose,
                ),
            ],
          ),
          const SizedBox(height: 16),
          
          
          Center(
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
              ),
              child: QrImageView(
                key: const Key('crypto_receive_qr'),
                data: address,
                version: QrVersions.auto,
                size: qrSize,
                gapless: true,
                backgroundColor: Colors.white,
                errorStateBuilder: (context, error) {
                  return SizedBox(
                    width: qrSize,
                    height: qrSize,
                    child: const Center(
                      child: Text(
                        'QR could not render.',
                        style: TextStyle(color: Colors.black),
                      ),
                    ),
                  );
                },
              ),
            ),
          ),
          const SizedBox(height: 16),
          
          Container(
            decoration: BoxDecoration(
              color: const Color(0xFF1F1F1F),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.white12),
            ),
            padding: const EdgeInsets.all(12),
            child: SelectableText(
              address,
              key: const Key('crypto_receive_full_address'),
              style: const TextStyle(
                color: Colors.white,
                fontFamily: 'monospace',
                fontSize: 12,
                height: 1.4,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              ElevatedButton.icon(
                key: const Key('crypto_receive_copy_button'),
                onPressed: () {
                  if (onCopy != null) {
                    onCopy!(address);
                  } else {
                    _defaultCopy(context);
                  }
                },
                icon: const Icon(Icons.copy, size: 16),
                label: Text(AppLocalizations.of(context).cryptoCopyAddress),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF10A37F),
                  foregroundColor: Colors.white,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          
          Container(
            decoration: BoxDecoration(
              color: const Color(0xFF2C2410),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: const Color(0xFFE5B45A).withValues(alpha: 0.36),
              ),
            ),
            padding: const EdgeInsets.all(12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(
                  Icons.warning_amber_outlined,
                  color: Color(0xFFE5B45A),
                  size: 18,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    kReceiveNetworkWarning,
                    key: const Key('crypto_receive_warning'),
                    style: const TextStyle(
                      color: Color(0xFFE5B45A),
                      fontSize: 12,
                      height: 1.45,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            kReceiveReceiveOnlyHint,
            key: const Key('crypto_receive_only_hint'),
            style: const TextStyle(
              color: Color(0xFF888888),
              fontSize: 11,
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }
}


class _NetworkChip extends StatelessWidget {
  const _NetworkChip({required this.network});
  final String network;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: const Color(0xFF10A37F).withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        network,
        key: const Key('crypto_receive_network_chip'),
        style: const TextStyle(
          color: Color(0xFF10A37F),
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}


Future<void> showReceivePanelDialog(
  BuildContext context, {
  required String title,
  required String address,
  String? network,
  void Function(String address)? onCopy,
}) {
  return showDialog<void>(
    context: context,
    builder: (ctx) => Dialog(
      key: const Key('crypto_receive_dialog'),
      backgroundColor: const Color(0xFF1F1F1F),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(20),
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: ReceivePanel(
          title: title,
          address: address,
          network: network,
          onCopy: onCopy,
          onClose: () => Navigator.of(ctx).pop(),
        ),
      ),
    ),
  );
}
