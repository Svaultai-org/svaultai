import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/crypto_wallet_engine_activity_card.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {
  group('Per-asset ERC20 empty-state activity copy', () {

    test('ETH detail page says "Sent and received ETH transactions"', () {
      final copy = activityCopyEmptyForNetwork(
        'ethereum_mainnet', asset: 'ETH',
      );
      expect(copy, contains('No activity yet.'));
      expect(copy, contains('Sent and received ETH transactions'));
      expect(copy, contains('Ethereum indexer'));
      expect(copy.toLowerCase(), isNot(contains('sepolia')));
      expect(copy.toLowerCase(), isNot(contains('testnet')));
    });

    test('USDT ERC20 detail page says "Sent and received USDT '
        'transactions"', () {
      final copy = activityCopyEmptyForNetwork(
        'ethereum_mainnet', asset: 'USDT_ERC20',
      );
      expect(copy, contains('No activity yet.'));
      expect(copy, contains('Sent and received USDT transactions'));
      expect(copy, contains('Ethereum indexer'));
      expect(copy, isNot(contains('USDC')));
      expect(copy, isNot(contains('ETH ')));
      expect(copy.toLowerCase(), isNot(contains('sepolia')));
    });

    test('USDC ERC20 detail page says "Sent and received USDC '
        'transactions"', () {
      final copy = activityCopyEmptyForNetwork(
        'ethereum_mainnet', asset: 'USDC_ERC20',
      );
      expect(copy, contains('No activity yet.'));
      expect(copy, contains('Sent and received USDC transactions'));
      expect(copy, contains('Ethereum indexer'));
      expect(copy, isNot(contains('USDT')));
      expect(copy, isNot(contains('ETH ')));
      expect(copy.toLowerCase(), isNot(contains('sepolia')));
    });

    test('Ethereum Mainnet without an asset stays on the generic '
        '"transactions" copy — no regression for callers that '
        'do not pass asset', () {
      final copy = activityCopyEmptyForNetwork('ethereum_mainnet');
      expect(copy, kActivityCopyEmptyMainnet);
      expect(copy, contains('Sent and received transactions'));
      expect(copy, isNot(contains('USDC')));
      expect(copy, isNot(contains('USDT')));
    });

    test('Sepolia stays untouched even when an asset is passed', () {
      final copy = activityCopyEmptyForNetwork(
        'ethereum_sepolia', asset: 'USDC_ERC20',
      );
      expect(copy, kActivityCopyEmptySepolia);
      expect(copy.toLowerCase(), contains('sepolia testnet'));
    });

    test('Solana / TRON / Monero ignore the asset parameter — they '
        'have their own network-specific copies', () {
      expect(
        activityCopyEmptyForNetwork('solana_mainnet', asset: 'SOL'),
        kActivityCopyEmptySolana,
      );
      expect(
        activityCopyEmptyForNetwork(
          'tron_mainnet', asset: 'USDT_TRC20',
        ),
        kActivityCopyEmptyTron,
      );
      expect(
        activityCopyEmptyForNetwork('monero_mainnet', asset: 'XMR'),
        kActivityCopyEmptyMonero,
      );
    });

    test('Unknown network falls back to the chain-agnostic default '
        'even when asset is passed', () {
      expect(
        activityCopyEmptyForNetwork(null, asset: 'USDC_ERC20'),
        kActivityCopyEmptyDefault,
      );
      expect(
        activityCopyEmptyForNetwork('weird_chain', asset: 'ETH'),
        kActivityCopyEmptyDefault,
      );
    });
  });


  group('Per-asset copies never contain buy/sell/swap/trade/stake/'
      'bridge/exchange/convert', () {

    test('every new per-asset ERC20 empty string is safe', () {
      const banned = ['buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
                      'exchange', 'convert'];
      final strings = <String>[
        kActivityCopyEmptyMainnetEth,
        kActivityCopyEmptyMainnetUsdtErc20,
        kActivityCopyEmptyMainnetUsdcErc20,
      ];
      for (final s in strings) {
        final low = s.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'copy "$s" leaks "$b"');
        }
      }
    });
  });


  group('Activity card render site passes the asset', () {

    test('the render site calls activityCopyEmptyForNetwork with '
        'widget.asset — not just widget.network', () {
      // 2026-07-13 canary correctness: the render site merges
      // indexer rows with the LocalOutgoingTxStore, so the empty
      // branch is now guarded by `rows.isEmpty` (merged snapshot)
      // rather than `_rows.isEmpty` (indexer-only field). The
      // intent — that the empty-copy call passes widget.asset —
      // still holds.
      final src = _readLib('ui/crypto_wallet_engine_activity_card.dart');

      final emptyBlockStart = src.indexOf('rows.isEmpty');
      expect(emptyBlockStart, greaterThan(-1),
          reason: 'expected the render site to have a rows.isEmpty '
              'branch');
      final emptyBlock = src.substring(emptyBlockStart,
          emptyBlockStart + 400);

      expect(
        emptyBlock.contains(
          'activityCopyEmptyForNetwork(widget.network, '
          'asset: widget.asset)',
        ),
        isTrue,
        reason: 'the render site must pass widget.asset so ERC20 '
            'detail pages get their asset-specific empty copy.',
      );
    });
  });
}
