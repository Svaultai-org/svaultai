// Regression tests for the 2026-07-22 fix that surfaces the REAL
// backend code from the inheritance credential save/replace flow
// instead of the hardcoded ``INH-CRED-004`` fallback the frontend
// used to show for every failure mode.
//
// Scope: strictly the two api_client methods
//        (saveInheritanceCredentials + replaceInheritanceCredentials)
// and the shape of the typed exception that carries the code back
// to the caller. No crypto, no backend, no state machine.

library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';


void main() {
  group('InheritanceCredSaveException — shape + fields', () {
    test('carries statusCode + backendCode + backendMessage', () {
      const e = InheritanceCredSaveException(
        statusCode: 409,
        backendCode: 'INH-CRED-005',
        backendMessage: 'Credentials are already saved for this beneficiary.',
      );
      expect(e.statusCode, 409);
      expect(e.backendCode, 'INH-CRED-005');
      expect(e.backendMessage, isNotNull);
    });

    test('null backendCode is preserved (not defaulted to 004)', () {
      const e = InheritanceCredSaveException(statusCode: 502);
      expect(e.backendCode, isNull);
      expect(e.backendMessage, isNull);
      // The whole point of this class: NEVER pretend the failure
      // was INH-CRED-004 when the backend didn't say so.
      expect(e.toString(), isNot(contains('INH-CRED-004')));
    });

    test('toString omits any secret material', () {
      const e = InheritanceCredSaveException(
        statusCode: 409,
        backendCode: 'INH-CRED-007',
        backendMessage: 'This beneficiary already has an active access '
            'request. Cancel it before changing the credentials.',
      );
      final s = e.toString();
      for (final forbidden in const [
        'pin', 'password', 'wrapped_key', 'encrypted_payload',
        'wrapping_ephemeral_pk', 'nonce', 'seed', 'sk', 'mvk',
      ]) {
        expect(s.toLowerCase(), isNot(contains(forbidden.toLowerCase())),
            reason: 'toString must not surface "$forbidden"');
      }
    });

    test('implements Exception', () {
      const e = InheritanceCredSaveException(statusCode: 400);
      expect(e, isA<Exception>());
    });
  });

  group('saveInheritanceCredentials — throws typed exception with '
      'parsed backend detail.code', () {

    // Every FastAPI ``inheritance_http_error`` returns this exact
    // envelope shape: {"detail": {"code": "INH-CRED-XYZ",
    // "message": "..."}}. The api_client parser must lift both
    // fields onto the typed exception.

    Map<String, dynamic> _minValidBody() => const {
          'beneficiary_link_id': 8,
          'crypto_version': 1,
          'encrypted_payload': 'AA',
          'payload_nonce': 'AA',
          'wrapped_key': 'AA',
          'wrapping_ephemeral_pk': 'AA',
          'wrapping_nonce': 'AA',
        };

    Future<Object?> _capture(
        Future<void> Function() action) async {
      try {
        await action();
        return null;
      } catch (e) {
        return e;
      }
    }

    Future<HttpServer> _serve(int status, dynamic body,
        {ContentType? contentType}) async {
      final srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      srv.listen((req) {
        req.response.statusCode = status;
        req.response.headers.contentType =
            contentType ?? ContentType.json;
        req.response.write(body is String ? body : jsonEncode(body));
        req.response.close();
      });
      return srv;
    }

    test('409 INH-CRED-005 already saved → typed exception preserves '
        'code', () async {
      final srv = await _serve(409, {
        'detail': {
          'code': 'INH-CRED-005',
          'message': 'Credentials are already saved for this beneficiary. '
              'Use Update credentials instead.',
        },
      });
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.saveInheritanceCredentials(
              body: _minValidBody(), authToken: 'session-fake');
        });
        expect(caught, isA<InheritanceCredSaveException>());
        final e = caught as InheritanceCredSaveException;
        expect(e.statusCode, 409);
        expect(e.backendCode, 'INH-CRED-005');
        expect(e.backendMessage, contains('already saved'));
      } finally {
        await srv.close(force: true);
      }
    });

    test('400 INH-CRED-004 malformed package → typed exception '
        'preserves the ACTUAL 004 (only when backend really said so)',
        () async {
      final srv = await _serve(400, {
        'detail': {
          'code': 'INH-CRED-004',
          'message': 'The credential package is malformed. Please try again.',
        },
      });
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.saveInheritanceCredentials(
              body: _minValidBody(), authToken: 'session-fake');
        });
        expect(caught, isA<InheritanceCredSaveException>());
        expect(
            (caught as InheritanceCredSaveException).backendCode,
            'INH-CRED-004');
      } finally {
        await srv.close(force: true);
      }
    });

    test('409 INH-CRED-007 access in flight → typed exception preserves '
        'code', () async {
      final srv = await _serve(409, {
        'detail': {
          'code': 'INH-CRED-007',
          'message': 'This beneficiary already has an active access '
              'request. Cancel it before changing the credentials.',
        },
      });
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.saveInheritanceCredentials(
              body: _minValidBody(), authToken: 'session-fake');
        });
        expect(
            (caught as InheritanceCredSaveException).backendCode,
            'INH-CRED-007');
      } finally {
        await srv.close(force: true);
      }
    });

    test('500 with empty body → typed exception with null backendCode '
        '(never fabricated as 004)', () async {
      final srv = await _serve(500, '', contentType: ContentType.text);
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.saveInheritanceCredentials(
              body: _minValidBody(), authToken: 'session-fake');
        });
        expect(caught, isA<InheritanceCredSaveException>());
        final e = caught as InheritanceCredSaveException;
        expect(e.statusCode, 500);
        expect(e.backendCode, isNull,
            reason: 'a body-less 500 must not synthesize a backend code');
      } finally {
        await srv.close(force: true);
      }
    });

    test('502 with garbage HTML body → typed exception with null '
        'backendCode (parser rejects non-JSON gracefully)', () async {
      final srv = await _serve(502, '<html>gateway down</html>',
          contentType: ContentType('text', 'html'));
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.saveInheritanceCredentials(
              body: _minValidBody(), authToken: 'session-fake');
        });
        expect(caught, isA<InheritanceCredSaveException>());
        expect(
            (caught as InheritanceCredSaveException).backendCode, isNull);
      } finally {
        await srv.close(force: true);
      }
    });

    test('replaceInheritanceCredentials mirrors save — 404 INH-CRED-006 '
        'no cred to replace → typed exception with 006', () async {
      final srv = await _serve(404, {
        'detail': {
          'code': 'INH-CRED-006',
          'message': 'No credentials are saved for this beneficiary yet.',
        },
      });
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.replaceInheritanceCredentials(
              body: _minValidBody(), authToken: 'session-fake');
        });
        expect(caught, isA<InheritanceCredSaveException>());
        final e = caught as InheritanceCredSaveException;
        expect(e.statusCode, 404);
        expect(e.backendCode, 'INH-CRED-006');
      } finally {
        await srv.close(force: true);
      }
    });

    test('200 body still returns the decoded map (happy path unchanged)',
        () async {
      final srv = await _serve(200, {
        'beneficiary_link_id': 8,
        'credentials_saved': true,
        'crypto_version': 1,
        'pairing_state': 'credentials_saved',
      });
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final result = await client.saveInheritanceCredentials(
            body: _minValidBody(), authToken: 'session-fake');
        expect(result['credentials_saved'], isTrue);
        expect(result['beneficiary_link_id'], 8);
      } finally {
        await srv.close(force: true);
      }
    });
  });

  group('main.dart _submitInheritanceCredentials — source contract',
      () {
    // The dialog handler must display the returned ``code`` — never
    // the hardcoded pre-2026-07-22 fallback. Locked via source
    // assertion because the handler lives inside a StatefulWidget
    // method deep in main.dart.
    late String src;

    setUpAll(() {
      src = File('lib/main.dart').readAsStringSync();
    });

    test('no hardcoded "Reference: INH-CRED-004" remains in main.dart',
        () {
      expect(
        src.contains('Reference: INH-CRED-004'),
        isFalse,
        reason: 'main.dart must not hardcode "Reference: INH-CRED-004" '
            'for the save-dialog error surface. Use the returned code.',
      );
    });

    test('dialog handler surfaces the returned code via interpolation',
        () {
      // Confirm the button handler references result.code (from the
      // record we now return).
      expect(
        src.contains(r'Reference: ${result.code}'),
        isTrue,
        reason: 'the dialog handler must interpolate the returned '
            'result.code into the reference tag',
      );
    });

    test('_submitInheritanceCredentials returns a record with an '
        '(ok, code) shape', () {
      expect(
        src.contains(
            'Future<({bool ok, String code})> _submitInheritanceCredentials'),
        isTrue,
        reason: 'the save handler must return a record so the caller '
            'can display the real reference tag',
      );
    });

    test('client-side sentinels are all distinct INH-CRED-CLIENT-* '
        'strings (no CLIENT sentinel collides with a backend code)',
        () {
      // Each frontend branch must emit its own sentinel — no branch
      // can be silently mapped to INH-CRED-004 or to another
      // backend-issued INH-CRED-00X.
      for (final sentinel in const [
        'INH-CRED-CLIENT-NO-SESSION',
        'INH-CRED-CLIENT-NO-PUBKEY',
        'INH-CRED-CLIENT-CRYPTO',
        'INH-CRED-CLIENT-NETWORK',
        'INH-CRED-CLIENT-AUTH',
        'INH-CRED-CLIENT-UNKNOWN',
      ]) {
        expect(src.contains(sentinel), isTrue,
            reason: 'client-side sentinel $sentinel must be present '
                'in main.dart _submitInheritanceCredentials');
      }
    });

    test('save handler catches InheritanceCredSaveException specifically',
        () {
      expect(
        src.contains('on InheritanceCredSaveException catch'),
        isTrue,
        reason: 'the save handler must catch the typed exception so '
            'the backend code can be preserved',
      );
    });
  });

  // -------------------------------------------------------------------
  // deleteInheritanceCredentials — typed exception + backend-code
  // interpolation (2026-07-22)
  // -------------------------------------------------------------------
  //
  // Production evidence: the backend rejects a released-link delete
  // with 409 INH-CRED-007 but the UI substituted a hardcoded
  // INH-CRED-006 because the delete path (a) threw a generic Exception
  // that carried the code only in its stringified form, and (b) the
  // catch block hardcoded 'INH-CRED-006' regardless of what the
  // backend actually returned. This group locks the fix: the wire
  // throws the typed exception (mirroring save/replace), and the
  // main.dart handler interpolates ``e.backendCode``.
  group('deleteInheritanceCredentials — typed exception carries '
      'backend code', () {

    Future<Object?> _capture(
        Future<void> Function() action) async {
      try {
        await action();
        return null;
      } catch (e) {
        return e;
      }
    }

    Future<HttpServer> _serve(int status, dynamic body,
        {ContentType? contentType}) async {
      final srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      srv.listen((req) {
        req.response.statusCode = status;
        req.response.headers.contentType =
            contentType ?? ContentType.json;
        req.response.write(body is String ? body : jsonEncode(body));
        req.response.close();
      });
      return srv;
    }

    test('409 INH-CRED-007 (delete during cooldown_active) → typed '
        'exception preserves 007 — NOT INH-CRED-006', () async {
      final srv = await _serve(409, {
        'detail': {
          'code': 'INH-CRED-007',
          'message': 'This beneficiary already has an active access '
              'request. Cancel it before changing the credentials.',
        },
      });
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.deleteInheritanceCredentials(
              linkId: 8, authToken: 'session-fake');
        });
        expect(caught, isA<InheritanceCredSaveException>());
        final e = caught as InheritanceCredSaveException;
        expect(e.statusCode, 409);
        expect(e.backendCode, 'INH-CRED-007',
            reason: 'the delete path must surface the ACTUAL backend '
                'code (INH-CRED-007) instead of substituting the '
                'hardcoded INH-CRED-006 the UI used to display for '
                'every delete failure');
        expect(e.backendMessage, contains('active access'));
      } finally {
        await srv.close(force: true);
      }
    });

    test('404 INH-CRED-006 (no credentials to delete) → typed '
        'exception preserves 006', () async {
      final srv = await _serve(404, {
        'detail': {
          'code': 'INH-CRED-006',
          'message': 'No credentials are saved for this beneficiary yet.',
        },
      });
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.deleteInheritanceCredentials(
              linkId: 8, authToken: 'session-fake');
        });
        expect((caught as InheritanceCredSaveException).backendCode,
            'INH-CRED-006');
      } finally {
        await srv.close(force: true);
      }
    });

    test('500 with empty body → typed exception with null backendCode '
        '(never fabricated as 006)', () async {
      final srv = await _serve(500, '', contentType: ContentType.text);
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final caught = await _capture(() async {
          await client.deleteInheritanceCredentials(
              linkId: 8, authToken: 'session-fake');
        });
        expect(caught, isA<InheritanceCredSaveException>());
        expect((caught as InheritanceCredSaveException).backendCode,
            isNull);
      } finally {
        await srv.close(force: true);
      }
    });

    test('200 body still returns the decoded map (happy path)',
        () async {
      final srv = await _serve(200, {
        'beneficiary_link_id': 8,
        'credentials_saved': false,
        'pairing_state': 'paired_no_credentials',
      });
      try {
        final client = VaultAIClient(
            baseUrl: 'http://${srv.address.host}:${srv.port}');
        final r = await client.deleteInheritanceCredentials(
            linkId: 8, authToken: 'session-fake');
        expect(r['credentials_saved'], isFalse);
        expect(r['pairing_state'], 'paired_no_credentials');
      } finally {
        await srv.close(force: true);
      }
    });
  });

  // -------------------------------------------------------------------
  // main.dart _deleteInheritanceCredentials — source contract
  // -------------------------------------------------------------------
  //
  // The delete-credentials dialog handler MUST NOT hardcode
  // 'INH-CRED-006' in the catch block anymore. This locks the fix
  // structurally so the regression can't come back through a stray
  // copy-paste.
  group('main.dart _deleteInheritanceCredentials — source contract',
      () {
    late String src;

    setUpAll(() {
      src = File('lib/main.dart').readAsStringSync();
    });

    test('no hardcoded "Reference: INH-CRED-006" remains inside a '
        '_showSnack call for the delete path', () {
      // The old failure line looked like:
      //   'Could not delete credentials.\nReference: INH-CRED-006'
      // The fix interpolates the returned backend code instead. It
      // is OK for the SUCCESS path elsewhere to reference
      // INH-CRED-006 in dartdoc — we only forbid the exact snack
      // string used by the delete-failure path.
      expect(
        src.contains(
            "'Could not delete credentials.\\nReference: INH-CRED-006'"),
        isFalse,
        reason: 'the delete-failure snack must not hardcode '
            'Reference: INH-CRED-006 — use the backend code',
      );
    });

    test('delete handler catches InheritanceCredSaveException '
        'and interpolates e.backendCode', () {
      final idx = src.indexOf(
          "Future<void> _deleteInheritanceCredentials(");
      expect(idx, greaterThan(-1),
          reason: '_deleteInheritanceCredentials method not found');
      // The delete handler's method body spans ~80 lines including
      // dialog, try/catch, dedicated typed-exception branch, and a
      // final generic catch. 4000 chars covers it end-to-end.
      final window =
          src.substring(idx, (idx + 4000).clamp(0, src.length));
      expect(
        window.contains('on InheritanceCredSaveException catch'),
        isTrue,
        reason: 'the delete handler must catch the typed exception '
            'so backendCode can be surfaced',
      );
      expect(
        window.contains(r'Reference: $code'),
        isTrue,
        reason: 'the delete-failure snack must interpolate the '
            'derived code (backend or CLIENT-* sentinel)',
      );
    });
  });

  // -------------------------------------------------------------------
  // main.dart _deleteBeneficiary — local-state removal contract
  // -------------------------------------------------------------------
  //
  // Production evidence: /beneficiary/delete returns HTTP 200 but the
  // card lingered in the UI because ``_loadBeneficiaries`` was
  // silently discarded by its generation-counter guard. The fix
  // filters the deleted id out of ``beneficiaries`` before the
  // authoritative refresh. Locked structurally.
  group('main.dart _deleteBeneficiary — local-state removal contract',
      () {
    late String src;

    setUpAll(() {
      src = File('lib/main.dart').readAsStringSync();
    });

    test('_deleteBeneficiary removes the linkId from local '
        'beneficiaries state BEFORE calling _loadBeneficiaries', () {
      final idx = src.indexOf(
          'Future<void> _deleteBeneficiary(int linkId, String label)');
      expect(idx, greaterThan(-1),
          reason: '_deleteBeneficiary method not found');
      final window =
          src.substring(idx, (idx + 3000).clamp(0, src.length));

      final deleteCallAt =
          window.indexOf('client.deleteBeneficiary(');
      final setStateAt = window.indexOf('setState(');
      final loadAt = window.indexOf('_loadBeneficiaries()');
      expect(deleteCallAt, greaterThan(-1),
          reason: 'client.deleteBeneficiary call not found');
      expect(setStateAt, greaterThan(deleteCallAt),
          reason: 'setState must occur AFTER the API 200 (inside '
              'the try {} block, not before)');
      expect(loadAt, greaterThan(setStateAt),
          reason: 'the authoritative refresh must come AFTER the '
              'local filter — otherwise the gen-counter guard can '
              'silently discard the refresh and leave the card '
              'lingering in the UI');
      // The filter can wrap across lines in the source (dart-format
      // will do this for long expressions), so match on the
      // whitespace-collapsed body.
      final collapsed = window.replaceAll(RegExp(r'\s+'), ' ');
      expect(
        collapsed.contains(
            ".where((b) => (b['id'] as num?)?.toInt() != linkId)"),
        isTrue,
        reason: 'the local removal must filter by linkId exactly '
            '(matches the id shape /beneficiary/list-mine returns)',
      );
    });
  });
}
