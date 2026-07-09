

import 'package:flutter/material.dart';

import '../services/crypto_wallet_features.dart';
import 'crypto_wallet_engine_design.dart';


const String kTronActivityCardHeading = 'USDT TRC20 activity';
const String kTronActivityNotConnectedCopy =
    'USDT TRC20 activity is not connected yet.';
const String kTronActivityDisabledCopy =
    'USDT TRC20 activity is temporarily unavailable.';
const String kTronActivityCardKey = 'tron_activity_card';
const String kTronActivityNotConnectedKey =
    'tron_activity_not_connected';
const String kTronActivityDisabledKey = 'tron_activity_disabled';


class CryptoWalletEngineTronActivityCard extends StatelessWidget {
  final CryptoWalletFeatures? features;

  const CryptoWalletEngineTronActivityCard({
    super.key,
    this.features,
  });

  @override
  Widget build(BuildContext context) {
    final tronOn = features?.tronEnabled ?? true;
    final message = tronOn
        ? kTronActivityNotConnectedCopy
        : kTronActivityDisabledCopy;
    final bodyKey = tronOn
        ? kTronActivityNotConnectedKey
        : kTronActivityDisabledKey;
    return Container(
      key: const Key(kTronActivityCardKey),
      padding: const EdgeInsets.all(14),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.history_rounded, size: 18,
                  color: kWalletTextSecondary),
              SizedBox(width: 8),
              Text(
                kTronActivityCardHeading,
                style: kWalletSectionHeadingStyle,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Padding(
            key: Key(bodyKey),
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
              message,
              style: kWalletBodyStyle,
            ),
          ),
        ],
      ),
    );
  }
}
