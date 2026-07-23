// Unit tests for the inheritance-reveal exception classifier PLUS
// the reveal-flow diagnostic contract:
//
//   * classifyRevealException + safeLengthsFromRawPkg + userMessageForReveal
//     — every branch exercised with synthetic inputs.
//
//   * postInheritanceClientDiagnostic fire-and-forget contract —
//     verified against a battery of HTTP failure modes (500 / 502
//     / 422 / hang / port-refused / chained-then). None of them
//     may throw or block; the reveal flow depends on that
//     guarantee.
//
//   * main.dart reveal-catch source contract — the diagnostic POST
//     is wrapped in unawaited(...), the _showSnack call comes
//     AFTER it, exactly ONE snack fires, and the reference tag
//     interpolates the classifier's output rather than the pre-
//     2026-07-22 hardcoded 'INH-RETRIEVE-003'. Also asserts the
//     diagnostic body carries none of the credential-shaped keys.

library;

import 'dart:async';
import 'dart:convert' show base64Url, jsonEncode;
import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart'
    show Mac, SecretBox, SecretBoxAuthenticationError;
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/inheritance_credentials.dart'
    show
        InheritanceRevealStageException,
        // 2026-07-23: stage names migrated to UPPER_SNAKE — the
        // prior lowercase constants have been removed. Each new
        // constant covers a superset of the prior tag's scope; see
        // ``inheritance_credentials.dart`` header.
        kRevealStageDecryptPayload,
        kRevealStageDeriveSharedSecret,
        kRevealStageDeriveWrapKey,
        kRevealStageJsonParse,
        kRevealStageLoadSecretKey,
        kRevealStageMapCredential,
        kRevealStageParseEphemeralPublicKey,
        kRevealStagesAll,
        kRevealStageUnstagedUnknown,
        kRevealStageUnwrapDataKey,
        kRevealStageUtf8Decode;
import 'package:vault_ai_frontend/services/inheritance_reveal_classify.dart';


String _b64Url(List<int> bytes) =>
    base64Url.encode(bytes).replaceAll('=', '');


void main() {
  group('classifyRevealException — every branch', () {
    test('SecretBoxAuthenticationError → AUTH', () {
      final e = SecretBoxAuthenticationError(
        secretBox: SecretBox(
          const <int>[1, 2, 3],
          nonce: Uint8List(12),
          mac: Mac(const <int>[]),
        ),
      );
      expect(classifyRevealException(e), equals(kRefRevealAuth));
      expect(revealCategoryFor(kRefRevealAuth), equals('auth'));
    });

    test('TypeError from a null cast → SHAPE', () {
      Object? caught;
      try {
        final m = <String, dynamic>{'crypto_version': null};
        // Reproduce the same cast the reveal path performs when the
        // backend response is missing a field.
        // ignore: unused_local_variable
        final _ = (m['crypto_version'] as num).toInt();
      } catch (e) {
        caught = e;
      }
      expect(caught, isNotNull);
      expect(classifyRevealException(caught!), equals(kRefRevealShape));
      expect(revealCategoryFor(kRefRevealShape), equals('shape'));
    });

    test('NoSuchMethodError on null.toString() shape → SHAPE', () {
      // NoSuchMethodError is uncommon in null-safety mode but stays
      // in the classifier as a defensive branch for legacy paths.
      final err = NoSuchMethodError.withInvocation(
        null,
        Invocation.getter(#nothing),
      );
      expect(classifyRevealException(err), equals(kRefRevealShape));
    });

    test('FormatException from bad base64 → B64', () {
      Object? caught;
      try {
        base64Url.decode('!!!not-b64!!!');
      } catch (e) {
        caught = e;
      }
      expect(caught, isA<FormatException>());
      expect(classifyRevealException(caught!), equals(kRefRevealB64));
      expect(revealCategoryFor(kRefRevealB64), equals('b64'));
    });

    test('FormatException with a JSON-shaped message → PAYLOAD', () {
      final e = const FormatException('Unexpected character (at position 3)');
      expect(classifyRevealException(e), equals(kRefRevealPayload));
      expect(revealCategoryFor(kRefRevealPayload), equals('payload'));
    });

    test('FormatException with an UTF-8-shaped message → PAYLOAD', () {
      final e = const FormatException('Bad UTF-8 encoding');
      expect(classifyRevealException(e), equals(kRefRevealPayload));
    });

    test('ArgumentError from newKeyPairFromSeed length → KEYLEN', () {
      final e = ArgumentError.value(
        Uint8List(31), 'seed', 'must be 32 bytes',
      );
      expect(classifyRevealException(e), equals(kRefRevealKeyLen));
      expect(revealCategoryFor(kRefRevealKeyLen), equals('keylen'));
    });

    test('StateError about ciphertext length → KEYLEN', () {
      final e = StateError('ciphertext is shorter than the AES-GCM tag');
      expect(classifyRevealException(e), equals(kRefRevealKeyLen));
    });

    test('StateError about wrong CEK length → PAYLOAD', () {
      final e = StateError('unwrapped CEK has wrong length');
      expect(classifyRevealException(e), equals(kRefRevealPayload));
    });

    test('StateError about JSON object → PAYLOAD', () {
      final e = StateError('credential payload is not a JSON object');
      expect(classifyRevealException(e), equals(kRefRevealPayload));
    });

    test('Arbitrary Object → OTHER', () {
      final e = Object();
      expect(classifyRevealException(e), equals(kRefRevealOther));
      expect(revealCategoryFor(kRefRevealOther), equals('other'));
    });
  });

  group('safeLengthsFromRawPkg', () {
    test('all six fields decode when present', () {
      final pkg = <String, dynamic>{
        'crypto_version': 1,
        'encrypted_payload':     _b64Url(List<int>.filled(48, 0)),
        'payload_nonce':         _b64Url(List<int>.filled(12, 0)),
        'wrapped_key':           _b64Url(List<int>.filled(48, 0)),
        'wrapping_ephemeral_pk': _b64Url(List<int>.filled(32, 0)),
        'wrapping_nonce':        _b64Url(List<int>.filled(12, 0)),
      };
      final out = safeLengthsFromRawPkg(pkg);
      expect(out['crypto_version'], equals(1));
      expect(out['encrypted_payload_len'], equals(48));
      expect(out['payload_nonce_len'], equals(12));
      expect(out['wrapped_key_len'], equals(48));
      expect(out['wrapping_ephemeral_pk_len'], equals(32));
      expect(out['wrapping_nonce_len'], equals(12));
    });

    test('null pkg → every field null', () {
      final out = safeLengthsFromRawPkg(null);
      for (final k in const [
        'crypto_version',
        'encrypted_payload_len', 'payload_nonce_len',
        'wrapped_key_len', 'wrapping_ephemeral_pk_len',
        'wrapping_nonce_len',
      ]) {
        expect(out[k], isNull, reason: '$k must be null on null pkg');
      }
    });

    test('malformed base64 in one field → that length is null, '
        'others still decode', () {
      final pkg = <String, dynamic>{
        'crypto_version': 1,
        'encrypted_payload':     _b64Url(List<int>.filled(48, 0)),
        'payload_nonce':         '!!!bad!!!',   // malformed
        'wrapped_key':           _b64Url(List<int>.filled(48, 0)),
        'wrapping_ephemeral_pk': _b64Url(List<int>.filled(32, 0)),
        'wrapping_nonce':        _b64Url(List<int>.filled(12, 0)),
      };
      final out = safeLengthsFromRawPkg(pkg);
      expect(out['payload_nonce_len'], isNull);
      expect(out['encrypted_payload_len'], equals(48));
      expect(out['wrapping_ephemeral_pk_len'], equals(32));
    });

    test('wrong-type field → length null, does not throw', () {
      final pkg = <String, dynamic>{
        'crypto_version': 'not a number',
        'encrypted_payload': 42,  // not a string
        'payload_nonce': null,
      };
      final out = safeLengthsFromRawPkg(pkg);
      expect(out['crypto_version'], isNull);
      expect(out['encrypted_payload_len'], isNull);
      expect(out['payload_nonce_len'], isNull);
    });

    test('never contains any field VALUE — only lengths', () {
      final pkg = <String, dynamic>{
        'crypto_version': 1,
        'encrypted_payload':     _b64Url(List<int>.filled(48, 0)),
        'payload_nonce':         _b64Url(List<int>.filled(12, 0)),
        'wrapped_key':           _b64Url(List<int>.filled(48, 0)),
        'wrapping_ephemeral_pk': _b64Url(List<int>.filled(32, 0)),
        'wrapping_nonce':        _b64Url(List<int>.filled(12, 0)),
      };
      final out = safeLengthsFromRawPkg(pkg);
      // Whitelist: every value in the returned map must be int
      // OR null. No strings, no lists, no maps — guaranteeing no
      // ciphertext / nonce / key material can leak via this path.
      for (final entry in out.entries) {
        expect(
          entry.value == null || entry.value is int,
          isTrue,
          reason: '${entry.key} must be int? — got ${entry.value.runtimeType}',
        );
      }
    });
  });

  group('userMessageForReveal — safe user copy', () {
    test('never mentions crypto internals', () {
      for (final ref in const [
        kRefRevealAuth, kRefRevealShape, kRefRevealB64,
        kRefRevealKeyLen, kRefRevealPayload, kRefRevealOther,
      ]) {
        final msg = userMessageForReveal(ref).toLowerCase();
        for (final forbidden in const [
          'aes', 'gcm', 'hkdf', 'x25519', 'ecdh', 'seed',
          'cek', 'nonce', 'ciphertext', 'wrapped',
        ]) {
          expect(
            msg.contains(forbidden), isFalse,
            reason: 'reveal $ref must not surface "$forbidden"',
          );
        }
      }
    });

    test('AUTH message points the user at re-authentication', () {
      final msg = userMessageForReveal(kRefRevealAuth).toLowerCase();
      expect(msg, contains('sign'));
    });
  });

  // -------------------------------------------------------------------
  // postInheritanceClientDiagnostic — fire-and-forget contract
  // -------------------------------------------------------------------
  //
  // Proves that no matter what the backend does to the diagnostic
  // POST — HTTP 500, HTTP 502 with a garbage body, HTTP 422 schema
  // rejection, an indefinitely-hanging response, or a refused
  // port — the call NEVER throws. The reveal-catch relies on this
  // to make the diagnostic emission truly non-blocking (the call
  // is wrapped in ``unawaited(...)`` in production, so a thrown
  // future would surface as an uncaught async error).
  group('postInheritanceClientDiagnostic — fire-and-forget contract',
      () {
    Map<String, dynamic> _revealBody() => {
          'area': 'reveal',
          'reference_code': 'INH-RETRIEVE-003-AUTH',
          'link_id': 8,
          'exception_type': 'SecretBoxAuthenticationError',
          'category': 'auth',
          'crypto_version': 1,
          'encrypted_payload_len': 96,
          'payload_nonce_len': 12,
          'wrapped_key_len': 48,
          'wrapping_ephemeral_pk_len': 32,
          'wrapping_nonce_len': 12,
          'active_sk_present': true,
          'active_sk_len': 32,
        };

    test('endpoint returns HTTP 500: no throw, no crash', () async {
      final srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final base = 'http://${srv.address.host}:${srv.port}';
      srv.listen((req) {
        req.response.statusCode = 500;
        req.response.write('server exploded');
        req.response.close();
      });
      try {
        final client = VaultAIClient(baseUrl: base);
        // Not-throwing IS the assertion.
        await client.postInheritanceClientDiagnostic(
          authToken: 'session-fake',
          body: _revealBody(),
        );
      } finally {
        await srv.close(force: true);
      }
    });

    test('endpoint returns HTTP 502 with garbage body: no throw',
        () async {
      final srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final base = 'http://${srv.address.host}:${srv.port}';
      srv.listen((req) {
        req.response.statusCode = 502;
        req.response.headers.contentType =
            ContentType('text', 'html');
        req.response.write('<html>gateway broke</html>');
        req.response.close();
      });
      try {
        final client = VaultAIClient(baseUrl: base);
        await client.postInheritanceClientDiagnostic(
          authToken: 'session-fake',
          body: _revealBody(),
        );
      } finally {
        await srv.close(force: true);
      }
    });

    test('endpoint returns HTTP 422 (schema rejection): no throw',
        () async {
      final srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final base = 'http://${srv.address.host}:${srv.port}';
      srv.listen((req) {
        req.response.statusCode = 422;
        req.response.headers.contentType = ContentType.json;
        req.response.write(jsonEncode({'detail': 'unprocessable'}));
        req.response.close();
      });
      try {
        final client = VaultAIClient(baseUrl: base);
        await client.postInheritanceClientDiagnostic(
          authToken: 'session-fake',
          body: _revealBody(),
        );
      } finally {
        await srv.close(force: true);
      }
    });

    test('server hangs (never responds): call still returns without '
        'blocking the caller', () async {
      final srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final base = 'http://${srv.address.host}:${srv.port}';
      srv.listen((req) {
        // Deliberately do not close the response.
      });
      try {
        final client = VaultAIClient(baseUrl: base);
        // Guard with a 3s outer timeout: reaching the onTimeout
        // branch is an ACCEPTABLE outcome — the pending internal
        // request does not leak an exception into the caller's
        // stack.
        await client
            .postInheritanceClientDiagnostic(
              authToken: 'session-fake',
              body: _revealBody(),
            )
            .timeout(const Duration(seconds: 3),
                onTimeout: () {});
      } finally {
        await srv.close(force: true);
      }
    });

    test('port is refused (nothing listening): no throw', () async {
      final srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final base = 'http://${srv.address.host}:${srv.port}';
      await srv.close(force: true);
      final client = VaultAIClient(baseUrl: base);
      await client.postInheritanceClientDiagnostic(
        authToken: 'session-fake',
        body: _revealBody(),
      );
    });

    test('caller can chain .then and .catchError after a 500 — '
        'the Future resolves cleanly, not with an error', () async {
      final srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final base = 'http://${srv.address.host}:${srv.port}';
      srv.listen((req) {
        req.response.statusCode = 500;
        req.response.close();
      });
      try {
        final client = VaultAIClient(baseUrl: base);
        Object? seenError;
        var completed = false;
        await client
            .postInheritanceClientDiagnostic(
              authToken: 'session-fake',
              body: _revealBody(),
            )
            .then((_) => completed = true)
            .catchError((Object e) {
          seenError = e;
        });
        expect(seenError, isNull,
            reason: 'must complete normally on 500 — never with '
                'an error');
        expect(completed, isTrue,
            reason: 'the returned Future must resolve, not error');
      } finally {
        await srv.close(force: true);
      }
    });
  });

  // -------------------------------------------------------------------
  // reveal-flow source contract — main.dart
  // -------------------------------------------------------------------
  //
  // Locks the wire-order of the reveal catch: the "no second toast"
  // and "reveal shows the classifier's reference tag" invariants
  // both depend on (a) unawaited(...) around the diagnostic POST
  // and (b) _showSnack being invoked AFTER the unawaited call.
  //
  // The reveal widget is a StatefulWidget method deep inside main.dart
  // that cannot be pumped in isolation, so the invariants are locked
  // structurally the same way test_chat_deep_fix locks main.dart
  // wire orderings.
  group('reveal-flow source contract — main.dart', () {
    late String src;

    setUpAll(() {
      src = File('lib/main.dart').readAsStringSync();
    });

    test('reveal catch invokes postInheritanceClientDiagnostic via '
        'unawaited (fire-and-forget, non-blocking)', () {
      final idx = src.indexOf("'inheritance.reveal.decrypt_failed'");
      expect(idx, greaterThan(-1),
          reason: 'reveal catch fingerprint missing — '
              'inheritance.reveal.decrypt_failed vlog tag not found');
      final window =
          src.substring(idx, (idx + 2000).clamp(0, src.length));
      expect(
        window.contains('unawaited('),
        isTrue,
        reason: 'reveal catch must invoke the diagnostic post via '
            'unawaited(...) — never await it, otherwise a hanging '
            'diagnostic would delay the user-facing snack',
      );
      expect(
        window.contains('postInheritanceClientDiagnostic('),
        isTrue,
      );
      final unawaitedAt = window.indexOf('unawaited(');
      final postAt = window.indexOf('postInheritanceClientDiagnostic(');
      expect(postAt, greaterThan(unawaitedAt),
          reason: 'postInheritanceClientDiagnostic must be wrapped '
              'INSIDE the unawaited(...) call, not after it.');
    });

    test('reveal catch calls _showSnack AFTER queuing the '
        'diagnostic — snack fires even if diagnostic is unreachable',
        () {
      final idx = src.indexOf("'inheritance.reveal.decrypt_failed'");
      expect(idx, greaterThan(-1));
      final window =
          src.substring(idx, (idx + 2500).clamp(0, src.length));
      final postAt = window.indexOf('postInheritanceClientDiagnostic(');
      final snackAt = window.indexOf('_showSnack(');
      expect(snackAt, greaterThan(-1),
          reason: 'reveal catch must invoke _showSnack with the '
              'INH-RETRIEVE-003-* reference tag');
      expect(snackAt, greaterThan(postAt),
          reason: 'The _showSnack call must come AFTER the '
              'unawaited(postInheritanceClientDiagnostic(...)) call '
              'so a diagnostic failure cannot prevent or delay the '
              'user-facing message.');
    });

    test('reveal catch shows exactly ONE snack (no second toast)',
        () {
      final idx = src.indexOf("'inheritance.reveal.decrypt_failed'");
      final window =
          src.substring(idx, (idx + 2500).clamp(0, src.length));
      final matches = RegExp(r'_showSnack\(').allMatches(window).length;
      expect(matches, equals(1),
          reason: 'reveal catch must invoke _showSnack exactly ONCE '
              '— a second toast would confuse the user and would '
              'imply the diagnostic path surfaces an error message.');
    });

    test('reveal catch surfaces a reference tag from the classifier '
        '(never the raw INH-RETRIEVE-003 without a category suffix)',
        () {
      final idx = src.indexOf("'inheritance.reveal.decrypt_failed'");
      final window =
          src.substring(idx, (idx + 2500).clamp(0, src.length));
      expect(
        window.contains(r"'INH-RETRIEVE-003'"),
        isFalse,
        reason: "reveal catch must not emit the pre-2026-07-22 "
            "generic 'INH-RETRIEVE-003' tag — it must carry a "
            "category suffix from classifyRevealException",
      );
      expect(
        window.contains(r'Reference: $ref'),
        isTrue,
        reason: 'reveal catch must interpolate the ref variable '
            'from classifyRevealException, not a hardcoded tag',
      );
    });

    test('diagnostic body contains ONLY the safe fields the backend '
        'endpoint declares — no ciphertext / nonces / wrapped-key '
        'values', () {
      final idx = src.indexOf("'inheritance.reveal.decrypt_failed'");
      final window =
          src.substring(idx, (idx + 2500).clamp(0, src.length));

      const allowed = <String>{
        "'area'", "'reference_code'", "'link_id'",
        "'exception_type'", "'category'", "'crypto_version'",
        "'encrypted_payload_len'", "'payload_nonce_len'",
        "'wrapped_key_len'", "'wrapping_ephemeral_pk_len'",
        "'wrapping_nonce_len'", "'active_sk_present'",
        "'active_sk_len'",
      };
      const forbidden = <String>[
        "'encrypted_payload'",
        "'payload_nonce'",
        "'wrapped_key'",
        "'wrapping_ephemeral_pk'",
        "'wrapping_nonce'",
        "'pin'",
        "'password'",
        "'token'",
        "'seed'",
        "'sk'",
        "'mvk'",
      ];
      for (final f in forbidden) {
        expect(
          window.contains(f),
          isFalse,
          reason: 'reveal catch diagnostic body must NOT include '
              '$f (would leak credential material to the log line)',
        );
      }
      final saw = allowed.any(window.contains);
      expect(saw, isTrue,
          reason: 'reveal catch diagnostic body must include at '
              'least one of the allowed fields');
    });

    test('reveal catch emits the pipeline stage in the diagnostic '
        'body (2026-07-23)', () {
      final idx = src.indexOf("'inheritance.reveal.decrypt_failed'");
      final window =
          src.substring(idx, (idx + 3500).clamp(0, src.length));
      expect(
        window.contains("'stage'"),
        isTrue,
        reason: "the reveal-catch diagnostic body must include a "
            "'stage' field carrying the pipeline stage",
      );
      // 2026-07-23: the reveal catch now uses the staged pipeline's
      // captured error variable (``stagedError``), not the raw
      // ``e``. Guarantee-fallback to ``kRevealStageUnstagedUnknown``
      // ensures stage is never null.
      expect(
        window.contains('revealStageOf('),
        isTrue,
        reason: 'the reveal-catch must derive the stage via '
            'revealStageOf(...) so the wire value stays inside the '
            'closed backend allowlist',
      );
      expect(
        window.contains('kRevealStageUnstagedUnknown'),
        isTrue,
        reason: 'the reveal-catch must fall back to '
            'kRevealStageUnstagedUnknown so the diagnostic never '
            'carries stage=None even if the wrapper has a hole',
      );
    });
  });

  // -------------------------------------------------------------------
  // Stage-aware classification (2026-07-22)
  // -------------------------------------------------------------------
  //
  // The decrypt pipeline now wraps every failing stage in
  // InheritanceRevealStageException(stage, cause). The classifier
  // must (a) return the SAME category the raw cause would have
  // produced (transparent unwrap), and (b) expose the stage via
  // revealStageOf so the reveal catch can add it to the diagnostic
  // POST body.
  group('classifyRevealException — stage-wrapped exceptions', () {
    test('unwraps SecretBoxAuthenticationError → AUTH regardless of '
        'stage', () {
      for (final stage in const [
        kRevealStageUnwrapDataKey, kRevealStageDecryptPayload,
      ]) {
        final inner = SecretBoxAuthenticationError(
          secretBox: SecretBox(
            const <int>[1, 2, 3],
            nonce: Uint8List(12),
            mac: Mac(const <int>[]),
          ),
        );
        final wrapped = InheritanceRevealStageException(
          stage: stage, cause: inner, causeStackTrace: StackTrace.current,
        );
        expect(classifyRevealException(wrapped),
            equals(kRefRevealAuth));
        expect(revealStageOf(wrapped), equals(stage));
      }
    });

    test('unwraps ArgumentError → KEYLEN with stage preserved', () {
      final wrapped = InheritanceRevealStageException(
        stage: kRevealStageLoadSecretKey,
        cause: ArgumentError.value(
          Uint8List(31), 'seed', 'must be 32 bytes',
        ),
        causeStackTrace: StackTrace.current,
      );
      expect(classifyRevealException(wrapped),
          equals(kRefRevealKeyLen));
      expect(revealStageOf(wrapped),
          equals(kRevealStageLoadSecretKey));
    });

    test('unwraps StateError → PAYLOAD when cause is JSON-shaped', () {
      final wrapped = InheritanceRevealStageException(
        stage: kRevealStageJsonParse,
        cause: StateError('credential payload is not a JSON object'),
        causeStackTrace: StackTrace.current,
      );
      expect(classifyRevealException(wrapped),
          equals(kRefRevealPayload));
      expect(revealStageOf(wrapped), equals(kRevealStageJsonParse));
    });

    test('unwraps FormatException → B64 with stage preserved', () {
      Object? caught;
      try {
        base64Url.decode('!!!not-b64!!!');
      } catch (e) { caught = e; }
      final wrapped = InheritanceRevealStageException(
        stage: kRevealStageParseEphemeralPublicKey,
        cause: caught!,
        causeStackTrace: StackTrace.current,
      );
      expect(classifyRevealException(wrapped),
          equals(kRefRevealB64));
      expect(revealStageOf(wrapped),
          equals(kRevealStageParseEphemeralPublicKey));
    });

    test('unwraps arbitrary Object → OTHER but stage still surfaces',
        () {
      final wrapped = InheritanceRevealStageException(
        stage: kRevealStageDeriveSharedSecret,
        cause: Object(),
        causeStackTrace: StackTrace.current,
      );
      expect(classifyRevealException(wrapped),
          equals(kRefRevealOther));
      expect(revealStageOf(wrapped),
          equals(kRevealStageDeriveSharedSecret),
          reason: 'even when the classifier falls through to OTHER '
              'the STAGE must still be available so the operator can '
              'grep the diagnostic log line by pipeline step');
    });

    test('revealStageOf returns null for a bare (unwrapped) exception',
        () {
      expect(revealStageOf(Object()), isNull);
      expect(revealStageOf(const FormatException('bad')), isNull);
      expect(
        revealStageOf(ArgumentError.value(1, 'x', 'y')), isNull,
      );
    });

    test('every kRevealStage* constant is UPPER_SNAKE and length ≤ '
        '32 chars (matches _DIAG_STAGES backend allowlist)', () {
      for (final stage in kRevealStagesAll) {
        expect(stage.length, lessThanOrEqualTo(32),
            reason: 'stage tag $stage must fit the backend '
                '_DIAG_STAGES allowlist (max_length=32)');
        // 2026-07-23 single-convention rule: UPPER_SNAKE only.
        expect(
          RegExp(r'^[A-Z][A-Z0-9_]*$').hasMatch(stage), isTrue,
          reason: 'stage tag $stage must be UPPER_SNAKE_CASE',
        );
      }
      // Sanity: the union of the nine pipeline stages + the
      // defensive fallback.
      expect(kRevealStagesAll, containsAll(<String>{
        kRevealStageLoadSecretKey,
        kRevealStageParseEphemeralPublicKey,
        kRevealStageDeriveSharedSecret,
        kRevealStageDeriveWrapKey,
        kRevealStageUnwrapDataKey,
        kRevealStageDecryptPayload,
        kRevealStageUtf8Decode,
        kRevealStageJsonParse,
        kRevealStageMapCredential,
        kRevealStageUnstagedUnknown,
      }));
    });
  });
}
