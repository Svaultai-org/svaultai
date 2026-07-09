import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/monero_scanner_status.dart';
import 'package:vault_ai_frontend/ui/crypto_wallet_engine_page.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {
  group('Monero scanner status — closed-set enums', () {

    test('scanner status set is exactly six values', () {
      expect(kAllowedMoneroScannerStatus, hasLength(6));
      expect(kAllowedMoneroScannerStatus, contains('disabled'));
      expect(kAllowedMoneroScannerStatus, contains('not_configured'));
      expect(kAllowedMoneroScannerStatus, contains('configured'));
      expect(kAllowedMoneroScannerStatus, contains('syncing'));
      expect(kAllowedMoneroScannerStatus, contains('ready'));
      expect(kAllowedMoneroScannerStatus, contains('error'));
    });

    test('scanner reason set is exactly nine values (7 backend '
        'states + client_local + web platform gate)', () {
      expect(kAllowedMoneroScannerReason, hasLength(9));
      expect(kAllowedMoneroScannerReason, contains('scanner_not_enabled'));
      expect(kAllowedMoneroScannerReason, contains('scanner_not_configured'));
      expect(kAllowedMoneroScannerReason, contains('view_key_not_available'));
      expect(kAllowedMoneroScannerReason, contains('scanner_unreachable'));
      expect(kAllowedMoneroScannerReason, contains('scanner_syncing'));
      expect(kAllowedMoneroScannerReason, contains('scanner_ready'));
      expect(kAllowedMoneroScannerReason, contains('scanner_error'));
      expect(kAllowedMoneroScannerReason,
          contains('local_scanner_available'));
      expect(kAllowedMoneroScannerReason,
          contains('scanner_requires_desktop'));
    });
  });


  group('Balance copy mapping per reason', () {

    test('scanner_not_enabled → "Scanner not enabled"', () {
      expect(
        moneroScannerBalanceCopyForReason('scanner_not_enabled'),
        'Scanner not enabled',
      );
    });

    test('scanner_not_configured → "Scanner not configured"', () {
      expect(
        moneroScannerBalanceCopyForReason('scanner_not_configured'),
        'Scanner not configured',
      );
    });

    test('view_key_not_available → "View-only scanning not available"',
        () {
      expect(
        moneroScannerBalanceCopyForReason('view_key_not_available'),
        'View-only scanning not available',
      );
    });

    test('scanner_unreachable → "Scanner temporarily unavailable"', () {
      expect(
        moneroScannerBalanceCopyForReason('scanner_unreachable'),
        'Scanner temporarily unavailable',
      );
    });

    test('scanner_syncing → "Scanner syncing"', () {
      expect(
        moneroScannerBalanceCopyForReason('scanner_syncing'),
        'Scanner syncing',
      );
    });

    test('scanner_ready with no real balance still says '
        '"Balance unavailable"', () {
      expect(
        moneroScannerBalanceCopyForReason('scanner_ready'),
        'Balance unavailable',
      );
    });

    test('unknown/null reason falls back to "Scanner not enabled"',
        () {
      expect(
        moneroScannerBalanceCopyForReason(null),
        'Scanner not enabled',
      );
      expect(
        moneroScannerBalanceCopyForReason('weird_reason'),
        'Scanner not enabled',
      );
    });
  });


  group('Activity copy mapping per reason', () {

    test('scanner_not_enabled → "Monero activity requires wallet '
        'scanning."', () {
      expect(
        moneroScannerActivityCopyForReason('scanner_not_enabled'),
        'Monero activity requires wallet scanning.',
      );
    });

    test('scanner_not_configured → "Monero scanner is not configured."',
        () {
      expect(
        moneroScannerActivityCopyForReason('scanner_not_configured'),
        'Monero scanner is not configured.',
      );
    });

    test('scanner_syncing → "Monero scanner is syncing."', () {
      expect(
        moneroScannerActivityCopyForReason('scanner_syncing'),
        'Monero scanner is syncing.',
      );
    });

    test('scanner_unreachable → "Monero scanner is temporarily '
        'unavailable."', () {
      expect(
        moneroScannerActivityCopyForReason('scanner_unreachable'),
        'Monero scanner is temporarily unavailable.',
      );
    });

    test('scanner_ready with empty result → "No activity yet."', () {
      expect(
        moneroScannerActivityCopyForReason('scanner_ready'),
        'No activity yet.',
      );
    });
  });


  group('Dashboard XMR default copy is exactly what the spec asks for',
      () {

    test('default dashboard balance row copy is "Scanner not enabled"',
        () {
      expect(
        kMoneroDashboardBalanceCopyDefault,
        'Scanner not enabled',
      );
    });

    test('dashboard scanner note is exactly the spec sentence', () {
      expect(
        kMoneroDashboardScannerNoteCopyDefault,
        'Monero balance requires wallet scanning.',
      );
    });

    test('dashboard activity chip is "Scanner not enabled"', () {
      expect(
        kMoneroDashboardActivityChipCopyDefault,
        'Scanner not enabled',
      );
    });
  });


  group('MoneroScannerStatus.fromJson', () {

    test('parses a real-shaped disabled response', () {
      final status = MoneroScannerStatus.fromJson(<String, dynamic>{
        'schema':          'monero_scanner_status_v1',
        'asset':           'XMR',
        'scannerStatus':   'disabled',
        'reason':          'scanner_not_enabled',
        'canShowBalance':  false,
        'canShowActivity': false,
        'canSend':         false,
      });
      expect(status.scannerStatus, 'disabled');
      expect(status.reason, 'scanner_not_enabled');
      expect(status.canShowBalance,  isFalse);
      expect(status.canShowActivity, isFalse);
      expect(status.canSend, isFalse);
      expect(status.balanceCopy,  'Scanner not enabled');
      expect(status.activityCopy,
          'Monero activity requires wallet scanning.');
      expect(status.sendVisible, isFalse);
    });

    test('parses server_view_only + view_key_not_available', () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'scannerStatus':   'configured',
        'reason':          'view_key_not_available',
        'canShowBalance':  false,
        'canShowActivity': false,
        'canSend':         false,
      });
      expect(s.scannerStatus, 'configured');
      expect(s.reason,        'view_key_not_available');
      expect(s.balanceCopy,   'View-only scanning not available');
      expect(s.canSend,       isFalse);
    });

    test('coerces an unknown status to disabled (never crashes UI)',
        () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'scannerStatus': 'something_new',
        'reason':        'strange_reason',
      });
      expect(s.scannerStatus, 'disabled');
      expect(s.reason,        'scanner_not_enabled');
      expect(s.canSend,       isFalse);
    });

    test('canSend is NEVER true just because the backend said so — '
        'it must be an explicit true boolean, not a truthy string',
        () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'scannerStatus': 'ready',
        'reason':        'scanner_ready',
        'canSend':       'true',
      });
      expect(s.canSend, isFalse,
          reason: 'string "true" must not silently enable sends');
    });
  });


  group('Part E — XMR is excluded from the provider-failure chip', () {

    test('kVaultBalanceSummaryAssets does NOT contain XMR', () {
      expect(kVaultBalanceSummaryAssets, isNot(contains('XMR')));
    });

    test('XMR scanner-not-enabled reason has no ETH/SOL/TRON-style '
        'RPC failure vocabulary', () {

      const banned = <String>[
        'rpc_error', 'provider_error', 'provider_unreachable',
        'rate_limited', 'api_key_missing',
      ];
      for (final r in kAllowedMoneroScannerReason) {
        for (final b in banned) {
          expect(r, isNot(equals(b)),
              reason: 'XMR reason must not overload ETH/SOL/TRON '
                  'provider-failure keys');
        }
      }
    });
  });


  group('Send hidden on dashboard for XMR — kAssetsWithLiveSend '
      'excludes XMR', () {

    test('kAssetsWithLiveSend does not contain XMR', () {
      expect(kAssetsWithLiveSend, isNot(contains('XMR')));
    });
  });


  group('Safe copy — no exchange/trading language, no "coming soon"',
      () {

    test('every balance and activity copy string is safe', () {
      const banned = <String>[
        'buy', 'sell', 'swap', 'trade', 'stake', 'bridge',
        'exchange', 'convert', 'coming soon',
      ];
      final strings = <String>[
        kMoneroScannerBalanceCopyNotEnabled,
        kMoneroScannerBalanceCopyNotConfigured,
        kMoneroScannerBalanceCopyViewKeyMissing,
        kMoneroScannerBalanceCopyUnreachable,
        kMoneroScannerBalanceCopySyncing,
        kMoneroScannerBalanceCopyReady,
        kMoneroScannerBalanceCopyError,
        kMoneroScannerActivityCopyNotEnabled,
        kMoneroScannerActivityCopyNotConfigured,
        kMoneroScannerActivityCopyViewKeyMissing,
        kMoneroScannerActivityCopyUnreachable,
        kMoneroScannerActivityCopySyncing,
        kMoneroScannerActivityCopyReady,
        kMoneroScannerActivityCopyError,
        kMoneroDashboardBalanceCopyDefault,
        kMoneroDashboardScannerNoteCopyDefault,
        kMoneroDashboardActivityChipCopyDefault,
      ];
      for (final s in strings) {
        final low = s.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'XMR copy "$s" leaks "$b"');
        }
      }
    });


    test('the service module source itself has no exchange language',
        () {
      final src = _readLib('services/monero_scanner_status.dart')
          .toLowerCase();

      final withoutHeader = src.substring(src.indexOf('const string'));
      const banned = <String>[
        ' buy ', ' sell ', ' swap ', ' trade ', ' stake ',
        ' bridge ', ' exchange ', ' convert ', 'coming soon',
      ];
      for (final b in banned) {
        expect(withoutHeader.contains(b), isFalse,
            reason: 'monero_scanner_status.dart leaks "$b"');
      }
    });
  });


  group('Never fake 0 XMR', () {

    test('no balance copy renders "0 XMR"', () {
      for (final r in kAllowedMoneroScannerReason) {
        final c = moneroScannerBalanceCopyForReason(r);
        expect(c.contains('0 XMR'), isFalse,
            reason: 'reason "$r" fabricates "0 XMR"');
        expect(c.contains('0.0 XMR'), isFalse);
      }
    });

    test('MoneroScannerStatus.balanceCopy for scanner_ready must not '
        'be a numeric zero display', () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'scannerStatus': 'ready',
        'reason':        'scanner_ready',
      });

      expect(s.balanceCopy, 'Balance unavailable');
      expect(s.balanceCopy.contains('0'), isFalse);
    });
  });
}
