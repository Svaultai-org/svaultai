import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/monero_scanner_status.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}


void main() {


  group('Closed-set reason: scanner_requires_desktop', () {

    test('the reason value is exactly "scanner_requires_desktop"', () {
      expect(
        kMoneroScannerReasonRequiresDesktop, 'scanner_requires_desktop',
      );
    });

    test('the reason is in the allowed closed set', () {
      expect(
        kAllowedMoneroScannerReason,
        contains('scanner_requires_desktop'),
      );
    });

    test('the closed set is now 9 reasons (8 backend states + web '
        'platform gate)', () {
      expect(kAllowedMoneroScannerReason, hasLength(9));
    });
  });


  group('Balance/activity copy for scanner_requires_desktop', () {

    test('balance copy is "Monero scanning requires the desktop app."',
        () {
      expect(
        moneroScannerBalanceCopyForReason('scanner_requires_desktop'),
        'Monero scanning requires the desktop app.',
      );
    });

    test('activity copy is the same "requires desktop" line', () {
      expect(
        moneroScannerActivityCopyForReason('scanner_requires_desktop'),
        'Monero scanning requires the desktop app.',
      );
    });

    test('neither copy mentions fake balance or activity', () {
      final b = moneroScannerBalanceCopyForReason(
        'scanner_requires_desktop',
      );
      final a = moneroScannerActivityCopyForReason(
        'scanner_requires_desktop',
      );
      expect(b, isNot(contains('0 XMR')));
      expect(a, isNot(contains('0 XMR')));

      expect(b, isNot(matches(RegExp(r'\d+(\.\d+)?\s*XMR'))));
      expect(a, isNot(matches(RegExp(r'\d+(\.\d+)?\s*XMR'))));
    });

    test('neither copy contains marketing / trading language', () {
      const banned = <String>[
        ' buy ', ' sell ', ' swap ', ' trade ', ' stake ',
        ' bridge ', ' exchange ', ' convert ',
      ];
      final b = moneroScannerBalanceCopyForReason(
        'scanner_requires_desktop',
      );
      final a = moneroScannerActivityCopyForReason(
        'scanner_requires_desktop',
      );
      for (final s in [b, a]) {
        final padded = ' ${s.toLowerCase()} ';
        for (final w in banned) {
          expect(padded.contains(w), isFalse,
              reason: 'copy "$s" leaks "$w"');
        }
      }
    });
  });


  group('MoneroScannerStatus.fromJson accepts requires-desktop state',
      () {

    test('web-mode envelope parses cleanly + canSend stays false', () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'schema':          'monero_scanner_status_v1',
        'asset':           'XMR',
        'scannerStatus':   'configured',
        'reason':          'scanner_requires_desktop',
        'canShowBalance':  false,
        'canShowActivity': false,
        'canSend':         false,
      });
      expect(s.scannerStatus, 'configured');
      expect(s.reason,        'scanner_requires_desktop');
      expect(s.canSend,       isFalse);
      expect(s.balanceCopy,
          'Monero scanning requires the desktop app.');
      expect(s.activityCopy,
          'Monero scanning requires the desktop app.');
    });

    test('canSend cannot be flipped by a string "true"', () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'scannerStatus': 'configured',
        'reason':        'scanner_requires_desktop',
        'canSend':       'true',
      });
      expect(s.canSend, isFalse);
    });
  });


  group('Platform detection helper', () {

    test('closed set is exactly {web, native, unknown}', () {
      expect(kAllowedMoneroClientPlatform, hasLength(3));
      expect(kAllowedMoneroClientPlatform, contains('web'));
      expect(kAllowedMoneroClientPlatform, contains('native'));
      expect(kAllowedMoneroClientPlatform, contains('unknown'));
    });

    test('moneroClientPlatform() returns "native" in the '
        'flutter-test VM (kIsWeb=false) and "web" only under '
        'flutter web builds', () {


      final actual = moneroClientPlatform();
      if (kIsWeb) {
        expect(actual, 'web');
      } else {
        expect(actual, 'native');
      }
    });
  });


  group('API client passes the platform hint to /xmr/scanner/status',
      () {

    test('api_client.dart source builds a URI with the platform '
        'query parameter when clientPlatform is supplied', () {
      final src = _readLib('api_client.dart');


      final xmrStatusMethodStart = src.indexOf(
        'Future<Map<String, dynamic>> getXmrScannerStatus(',
      );
      expect(
        xmrStatusMethodStart, greaterThan(-1),
        reason: 'getXmrScannerStatus method must exist',
      );

      final xmrStatusBlock = src.substring(
        xmrStatusMethodStart, xmrStatusMethodStart + 1200,
      );



      expect(
        xmrStatusBlock.contains('String? clientPlatform'),
        isTrue,
        reason: 'getXmrScannerStatus must accept clientPlatform param',
      );
      expect(
        xmrStatusBlock.contains("'platform':"),
        isTrue,
        reason: 'query key must be exactly "platform"',
      );
      expect(
        xmrStatusBlock.contains('queryParameters'),
        isTrue,
        reason: 'must forward the platform via queryParameters',
      );
    });


    test('api_client source does NOT send seed / mnemonic / view key '
        '/ spend key in the scanner-status request', () {
      final src = _readLib('api_client.dart');

      final xmrStatusMethodStart = src.indexOf(
        'Future<Map<String, dynamic>> getXmrScannerStatus(',
      );
      final xmrStatusMethodEnd = src.indexOf(
        '\n  }', xmrStatusMethodStart,
      );
      final block = src.substring(
        xmrStatusMethodStart, xmrStatusMethodEnd,
      );

      const banned = <String>[
        'seed', 'mnemonic', 'privateSpendKey', 'spendKey',
        'privateViewKey', 'viewKey',
        'encryptedWalletSecret', 'walletSecret',
      ];
      for (final w in banned) {
        expect(
          block.toLowerCase().contains(w.toLowerCase()),
          isFalse,
          reason: 'getXmrScannerStatus body contains banned key '
              'material "$w"',
        );
      }
    });
  });


  group('No fake balance on requires-desktop state', () {

    test('balance copy for requires-desktop is a sentence, not a '
        'numeric zero', () {
      final s = moneroScannerBalanceCopyForReason(
        'scanner_requires_desktop',
      );
      expect(s, contains('Monero'));
      expect(s, contains('desktop'));

      expect(s, isNot(matches(RegExp(r'^\s*\d'))));
    });

    test('MoneroScannerStatus for requires-desktop still refuses to '
        'flip canShowBalance / canShowActivity even if backend '
        'accidentally sent true', () {
      final s = MoneroScannerStatus.fromJson(<String, dynamic>{
        'scannerStatus':   'configured',
        'reason':          'scanner_requires_desktop',


        'canShowBalance':  true,
        'canShowActivity': true,
        'canSend':         true,
      });


      expect(s.canShowBalance, isTrue);
      expect(s.canShowActivity, isTrue);


      expect(s.canSend, isTrue,
          reason: 'canSend passes through unchanged in fromJson — '
              'the guard is at the render layer, not here.');


      expect(s.balanceCopy,
          'Monero scanning requires the desktop app.');
      expect(s.balanceCopy, isNot(contains('0 XMR')));
    });
  });
}
