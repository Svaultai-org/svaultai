import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

String _readMain() => File('lib/main.dart').readAsStringSync();

void main() {
  group('ZK beneficiary label ciphertext finalize', () {
    test('main.dart declares tryZkFinalizeBeneficiaryLabelCiphertext '
        'as a top-level helper', () {
      final src = _readMain();
      expect(
        src,
        contains(
          'Future<bool> tryZkFinalizeBeneficiaryLabelCiphertext(',
        ),
        reason: 'a top-level helper must exist so any caller can '
                'ciphertext-finalize a beneficiary label',
      );
    });

    test('helper returns TRUE on non-ZK vaults (legacy row already '
        'has the plaintext label)', () {
      final src = _readMain();
      final idx = src.indexOf(
        'Future<bool> tryZkFinalizeBeneficiaryLabelCiphertext(',
      );
      expect(idx, greaterThan(-1));
      // Locate the helper body.
      final bodyStart = src.indexOf('{', idx);
      final bodyEnd = src.indexOf('\n}\n', bodyStart);
      final bodyEndCrlf = src.indexOf('\r\n}\r\n', bodyStart);
      final int end;
      if (bodyEnd == -1) {
        end = bodyEndCrlf;
      } else if (bodyEndCrlf == -1) {
        end = bodyEnd;
      } else {
        end = bodyEnd < bodyEndCrlf ? bodyEnd : bodyEndCrlf;
      }
      final body = src.substring(bodyStart, end);
      expect(
        body,
        contains('if (mvk == null) return true'),
        reason: 'the helper must return true when no active MVK '
                'exists — legacy vaults are already saved by the '
                'upstream /beneficiary/create call',
      );
      expect(
        body,
        contains('/vault/ciphertext/beneficiary-links'),
        reason: 'the helper must POST to the ciphertext endpoint',
      );
      expect(
        body,
        contains('metadataKey()'),
        reason: 'the helper must derive metadataKey from the '
                'active MVK for label encryption',
      );
      expect(
        body,
        contains('aesGcmWrap'),
        reason: 'the helper must AES-GCM-wrap the label plaintext',
      );
      expect(
        body,
        contains('passer_label_ciphertext'),
        reason: 'the POST body must include passer_label_ciphertext',
      );
    });

    test('createBeneficiary call site immediately invokes the ZK '
        'finalize before revealing the pairing code — the pairing '
        'code MUST NOT be shown if the label failed to persist',
        () {
      final src = _readMain();
      final createIdx = src.indexOf('client.createBeneficiary(');
      expect(createIdx, greaterThan(-1),
          reason: 'main.dart must call createBeneficiary');
      // Locate the pairing_code assignment that reveals the code to
      // the user. It must come AFTER the ZK finalize call, not
      // before.
      final relativePairingIdx = RegExp(
        r"pairingCode\s*=\s*result\['pairing_code'\]\?\.toString\(\);",
      ).firstMatch(src.substring(createIdx))?.start;
      final pairingIdx = relativePairingIdx == null
          ? -1
          : createIdx + relativePairingIdx;
      expect(pairingIdx, greaterThan(createIdx),
          reason: 'pairing_code must be assigned AFTER '
                  'createBeneficiary returns');
      final finalizeIdx = src.indexOf(
        'tryZkFinalizeBeneficiaryLabelCiphertext(',
        createIdx,
      );
      expect(finalizeIdx, greaterThan(createIdx),
          reason: 'the ZK finalize call must appear in the same '
                  'try-block as createBeneficiary');
      expect(finalizeIdx, lessThan(pairingIdx),
          reason: 'the ZK finalize must fire BEFORE the pairing '
                  'code is shown to the user — otherwise the user '
                  'could hand out a code for an unlabelled row and '
                  'the beneficiary list would render blank rows');
      final between = src.substring(finalizeIdx, pairingIdx);
      expect(
        between,
        contains('createErr'),
        reason: 'a failed ZK finalize must set createErr and short-'
                'circuit — never silently expose the pairing code',
      );
    });
  });
}
