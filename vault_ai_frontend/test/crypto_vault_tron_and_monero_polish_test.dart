


import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/crypto_wallet_balance_reason.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {


  group('Part A — closed-set TRON reasons render honest per-reason copy '
      '(no more "Balance temporarily unavailable" for auth/rate/'
      'unreachable)', () {

    WalletBalanceReasonRender _render(String reason) =>
        walletBalanceReasonRender(
          reason: reason, asset: 'USDT_TRC20',
          networkKind: WalletNetworkKind.tron,
        );

    test('tron_api_not_configured → "TRON API is not configured."', () {
      final r = _render('tron_api_not_configured');
      expect(r.message, 'TRON API is not configured.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronApiNotConfigured);
      expect(r.message, isNot(kWalletBalanceCopyRpcError));
    });

    test('tron_api_key_missing → "TRON API key is not configured."', () {
      final r = _render('tron_api_key_missing');
      expect(r.message, 'TRON API key is not configured.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronApiKeyMissing);
    });

    test('tron_api_unauthorized → "TRON API key was rejected."', () {
      final r = _render('tron_api_unauthorized');
      expect(r.message, 'TRON API key was rejected.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronApiUnauthorized);
    });

    test('tron_rate_limited → "TRON provider rate limit reached."', () {
      final r = _render('tron_rate_limited');
      expect(r.message, 'TRON provider rate limit reached.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronRateLimited);
    });

    test('tron_provider_unreachable → "TRON provider temporarily '
        'unavailable."', () {
      final r = _render('tron_provider_unreachable');
      expect(r.message, 'TRON provider temporarily unavailable.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronProviderUnreachable);
    });

    test('tron_contract_not_configured → "Token contract is not '
        'configured."', () {
      final r = _render('tron_contract_not_configured');
      expect(r.message, 'Token contract is not configured.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronContractNotConfigured);
    });

    test('tron_contract_read_failed → "Token contract read failed."', () {
      final r = _render('tron_contract_read_failed');
      expect(r.message, 'Token contract read failed.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronContractReadFailed);
    });

    test('tron_invalid_address → "Invalid TRON address."', () {
      final r = _render('tron_invalid_address');
      expect(r.message, 'Invalid TRON address.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronInvalidAddress);
    });

    test('tron_provider_error → calm generic "Balance temporarily '
        'unavailable."', () {
      final r = _render('tron_provider_error');
      expect(r.message, 'Balance temporarily unavailable.');
      expect(r.bodyKey, kWalletBalanceReasonKeyTronProviderError);
    });

    test('closed-set copies never leak API key, base URL, wallet '
        'address, or provider internals', () {
      const banned = ['api_key', 'apikey', 'base_url', 'baseurl',
                      'trongrid', 'tron-pro', 'x-api-key',
                      'wallet_address', 'wallet_addr', 'holder_address',
                      'contract_hex'];
      final copies = <String>[
        kWalletBalanceCopyTronApiNotConfigured,
        kWalletBalanceCopyTronApiKeyMissing,
        kWalletBalanceCopyTronApiUnauthorized,
        kWalletBalanceCopyTronRateLimited,
        kWalletBalanceCopyTronProviderUnreachable,
        kWalletBalanceCopyTronContractNotConfigured,
        kWalletBalanceCopyTronContractReadFailed,
        kWalletBalanceCopyTronInvalidAddress,
        kWalletBalanceCopyTronProviderError,
      ];
      for (final c in copies) {
        final low = c.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'copy "$c" leaks "$b"');
        }
      }
    });

    test('every tron copy stays compact (< 45 chars) so it fits on a '
        'single dashboard row', () {
      final copies = <String>[
        kWalletBalanceCopyTronApiNotConfigured,
        kWalletBalanceCopyTronApiKeyMissing,
        kWalletBalanceCopyTronApiUnauthorized,
        kWalletBalanceCopyTronRateLimited,
        kWalletBalanceCopyTronProviderUnreachable,
        kWalletBalanceCopyTronContractNotConfigured,
        kWalletBalanceCopyTronContractReadFailed,
        kWalletBalanceCopyTronInvalidAddress,
        kWalletBalanceCopyTronProviderError,
      ];
      for (final c in copies) {
        expect(c.length, lessThan(45),
            reason: 'compact enough for a dashboard row: "$c"');
      }
    });
  });



  group('Part C — Monero dashboard card is compact', () {

    test('kWalletBalanceCopyRpcMissingMonero is now the compact chip — '
        '"Scanner not enabled" (was the long "Monero balance requires '
        'wallet scanning. Scanning is not enabled yet." paragraph)',
        () {
      expect(kWalletBalanceCopyRpcMissingMonero, 'Scanner not enabled');
      expect(kWalletBalanceCopyRpcMissingMonero.length, lessThan(30),
          reason: 'the balance-row copy must be short enough for the '
              'single balance line, not a paragraph.');
    });

    test('kWalletBalanceCopyXmrScanner is also the compact chip', () {
      expect(kWalletBalanceCopyXmrScanner, 'Scanner not enabled');
    });

    test('kWalletBalanceCopyMoneroScannerNote is the small explanatory '
        'note that goes under the actions row', () {
      expect(
        kWalletBalanceCopyMoneroScannerNote,
        'Monero balance requires wallet scanning.',
      );
      expect(kWalletBalanceCopyMoneroScannerNote.length, lessThan(60));
    });

    test('rpc_not_configured for Monero renders as the compact chip', () {
      final r = walletBalanceReasonRender(
        reason: 'rpc_not_configured', asset: 'XMR',
        networkKind: WalletNetworkKind.monero,
      );
      expect(r.message, 'Scanner not enabled');
    });

    test('xmr_scanner_not_enabled reason also maps to the compact chip',
        () {
      final r = walletBalanceReasonRender(
        reason: 'xmr_scanner_not_enabled', asset: 'XMR',
        networkKind: WalletNetworkKind.monero,
      );
      expect(r.message, 'Scanner not enabled');
    });

    test('XMR asset card render source shows the small scanner note under '
        'actions, keyed for tests', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');



      expect(
        src.contains("if (asset == 'XMR') ...["),
        isTrue,
        reason: 'the small note branch must be gated on XMR only.',
      );
      expect(
        src.contains("'crypto_wallet_engine_card_xmr_scanner_note'"),
        isTrue,
        reason: 'the XMR scanner note must have a stable widget key '
            'for tests (multi-line Key(...) formatting is fine).',
      );
      expect(
        src.contains('kWalletBalanceCopyMoneroScannerNote'),
        isTrue,
      );
    });

    test('the old long paragraph string is no longer used anywhere in the '
        'source as a balance-row copy', () {
      final src = _readLib('services/crypto_wallet_balance_reason.dart');



      expect(
        src.contains(
          'Monero balance requires wallet scanning. Scanning is not',
        ),
        isFalse,
        reason: 'the old long paragraph must be gone from the balance '
            'copies.',
      );
    });
  });



  group('Part D — Vault balance warning does NOT count XMR', () {

    test('kVaultBalanceSummaryAssets is the closed set — no XMR', () {
      expect(kVaultBalanceSummaryAssets, isNot(contains('XMR')),
          reason: 'XMR scanner-unavailable is a planned limitation, not '
              'a provider failure — it must not inflate the '
              '"N balance unavailable" count.');



      expect(kVaultBalanceSummaryAssets, containsAll(<String>[
        'ETH', 'USDT_ERC20', 'USDC_ERC20', 'SOL', 'USDT_TRC20',
      ]));
    });

    test('_buildPortfolioSummary iterates the closed set constant, not '
        'a locally-inlined list', () {
      final src = _readLib('ui/crypto_wallet_engine_page.dart');
      final start = src.indexOf('Widget _buildPortfolioSummary()');
      expect(start, greaterThan(0));
      final end = (start + 2500 < src.length) ? start + 2500 : src.length;
      final scope = src.substring(start, end);

      expect(scope.contains('kVaultBalanceSummaryAssets'), isTrue,
          reason: 'the summary must iterate the named const so the '
              'XMR exclusion invariant is explicit.');



      expect(
        scope.contains("'XMR'"),
        isFalse,
        reason: 'no inline XMR literal inside the summary loop — the '
            'exclusion must live in the shared const.',
      );
    });

    test('portfolioUnavailableChipLabel stays compact', () {
      expect(portfolioUnavailableChipLabel(1), '1 balance unavailable');
      expect(portfolioUnavailableChipLabel(3), '3 balances unavailable');
    });
  });



  group('Part E — no exchange/trading words in any new copy', () {

    test('every tron/monero copy stays clean', () {
      const banned = ['buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
                      'exchange', 'convert'];
      final all = <String>[
        kWalletBalanceCopyTronApiNotConfigured,
        kWalletBalanceCopyTronApiKeyMissing,
        kWalletBalanceCopyTronApiUnauthorized,
        kWalletBalanceCopyTronRateLimited,
        kWalletBalanceCopyTronProviderUnreachable,
        kWalletBalanceCopyTronContractNotConfigured,
        kWalletBalanceCopyTronContractReadFailed,
        kWalletBalanceCopyTronInvalidAddress,
        kWalletBalanceCopyTronProviderError,
        kWalletBalanceCopyRpcMissingMonero,
        kWalletBalanceCopyMoneroScannerNote,
        kWalletBalanceCopyXmrScanner,
      ];
      for (final c in all) {
        final low = c.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'copy "$c" leaks "$b"');
        }
      }
    });
  });
}
