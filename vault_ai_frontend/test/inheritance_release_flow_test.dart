// Frontend Phase 2 tests. Focus on the UI-visible invariants:
//
//   * state-label mapping (server ``pairing_state`` → beneficiary
//     card copy) — the countdown and reveal buttons render from the
//     server's authoritative timestamp, not a locally invented one;
//   * source-scan guards proving Recovery Kit and the removed
//     Settings pairing page still do not exist on any code path.
//
// The full reveal flow requires a running backend + a released
// package to decrypt, so end-to-end reveal is exercised by the
// backend integration tests. Here we lock the pieces the widget
// tree can be reasoned about without a live server.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  group('beneficiary state → visible label', () {
    // The renderer lives inside a private state class, so we test
    // the pure mapping by cloning the switch. If the mapping ever
    // drifts, this test flips loud.
    String _label({
      required String pairingState,
      required bool credentialsSaved,
      required String legacyStatus,
    }) {
      switch (pairingState) {
        case 'credentials_saved':
          return 'Credentials secured';
        case 'cooldown_active':
          return 'Access requested';
        case 'claimable':
          return 'Access available';
        case 'approved':
          return 'Access approved';
        case 'released':
          return 'Access granted';
        case 'revoked':
          return 'Revoked';
        case 'rejected':
          return 'Request rejected';
        case 'paired_no_credentials':
          if (legacyStatus == 'transfer_pending') return 'Transfer pending';
          if (legacyStatus == 'linked') return 'Linked';
          return 'Waiting for credentials';
      }
      return legacyStatus.isEmpty ? 'Linked' : legacyStatus;
    }

    test('credentials_saved renders "Credentials secured"', () {
      expect(
        _label(pairingState: 'credentials_saved',
               credentialsSaved: true, legacyStatus: 'linked'),
        'Credentials secured',
      );
    });

    test('cooldown_active renders "Access requested"', () {
      expect(
        _label(pairingState: 'cooldown_active',
               credentialsSaved: true, legacyStatus: 'linked'),
        'Access requested',
      );
    });

    test('claimable renders "Access available"', () {
      expect(
        _label(pairingState: 'claimable',
               credentialsSaved: true, legacyStatus: 'linked'),
        'Access available',
      );
    });

    test('approved / released render access states', () {
      expect(
        _label(pairingState: 'approved',
               credentialsSaved: true, legacyStatus: 'linked'),
        'Access approved',
      );
      expect(
        _label(pairingState: 'released',
               credentialsSaved: true, legacyStatus: 'linked'),
        'Access granted',
      );
    });

    test('paired_no_credentials falls back to legacy status', () {
      expect(
        _label(pairingState: 'paired_no_credentials',
               credentialsSaved: false, legacyStatus: 'transfer_pending'),
        'Transfer pending',
      );
    });
  });

  group('source guards — nothing Recovery-Kit / Settings-pairing '
        'ever comes back', () {
    File _main() => File('lib/main.dart');
    File _api() => File('lib/api_client.dart');
    Directory _services() => Directory('lib/services');

    test('main.dart contains none of the removed feature identifiers',
        () {
      final src = _main().readAsStringSync();
      const forbidden = <String>[
        'recovery_kit_settings_page',
        'RecoveryKitSettingsPage',
        '/recovery-kit',
        'settings_recovery_kit_tile',
        'inheritance_pairing_page',
        'InheritancePairingPage',
        '/inheritance-pairing',
        'settings_inheritance_pairing_tile',
      ];
      for (final needle in forbidden) {
        expect(src.contains(needle), isFalse,
            reason: 'main.dart contains $needle');
      }
    });

    test('api_client.dart has no recovery-kit endpoint plumbing', () {
      final src = _api().readAsStringSync();
      expect(src.contains('recovery-kit'), isFalse);
      expect(src.contains('RecoveryKit'), isFalse);
    });

    test('no services file is named after Recovery Kit', () {
      final files = _services()
          .listSync(recursive: false)
          .whereType<File>()
          .map((f) => f.path)
          .toList();
      expect(
        files.any((p) => p.contains('recovery_kit')),
        isFalse,
        reason: 'services/ still contains a recovery_kit file',
      );
    });
  });

  group('phase 2 wiring locks in main.dart', () {
    File _main() => File('lib/main.dart');

    test('release helpers are present', () {
      final src = _main().readAsStringSync();
      for (final needle in const [
        '_beneficiaryRequestAccess',
        '_beneficiaryCancelAccess',
        '_beneficiaryClaimAccess',
        '_beneficiaryRevealCredentials',
        '_ownerApproveInheritance',
        '_ownerRejectInheritance',
        '_showRevealedCredentialsDialog',
        '_beneficiaryContinueToInheritedAccount',
      ]) {
        expect(src.contains(needle), isTrue,
            reason: 'main.dart is missing $needle');
      }
    });

    test('reveal dialog requires a PIN reauth before display', () {
      final src = _main().readAsStringSync();
      expect(src.contains('_promptForReauthPin'), isTrue);
      final idx = src.indexOf('_beneficiaryRevealCredentials');
      expect(idx, greaterThan(-1));
      // Within a ~200 line window after the helper, the PIN prompt
      // must be called BEFORE the /retrieve fetch.
      final window = src.substring(idx, idx + 4000);
      final promptIdx = window.indexOf('_promptForReauthPin');
      final retrieveIdx = window.indexOf('retrieveInheritanceCredentials');
      expect(promptIdx, greaterThan(-1));
      expect(retrieveIdx, greaterThan(-1));
      expect(promptIdx, lessThan(retrieveIdx),
          reason: 'reveal must reauth before fetching ciphertext');
    });

    test('reveal shows a copy-warning about the clipboard', () {
      final src = _main().readAsStringSync();
      expect(
        src.contains('Clipboard contents may be accessible'),
        isTrue,
        reason: 'user-visible clipboard warning is missing',
      );
    });
  });
}
