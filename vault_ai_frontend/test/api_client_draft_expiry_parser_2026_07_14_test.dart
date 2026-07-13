// 2026-07-14 (Round 9) API-client parser regression for
// `getCryptoWalletDraftExpiryNetwork`.
//
// The SOL / TRON send panels' pre-sign and pre-broadcast fail-
// closed checks depend on this parser NEVER converting an
// unexpected / malformed / non-200 backend envelope into an
// `expired: false` allow. This test file drives the parser
// against the exact envelope shapes the Round-9 backend endpoint
// emits (see `_get_solana_draft_expiry` / `_get_tron_draft_expiry`
// in routes/crypto_wallet_routes.py) plus every documented failure
// mode.
//
// Failure surface exercised:
//   * HTTP 200 with `expired: false`             → returns map
//   * HTTP 200 with `expired: true`              → returns map
//   * HTTP 200 with `expired: null`              → returns map
//   * HTTP 401                                   → throws
//   * HTTP 403                                   → throws
//   * HTTP 404                                   → throws
//   * HTTP 422                                   → throws
//   * HTTP 500                                   → throws
//   * HTTP 200 with body that isn't a JSON map   → throws
//   * HTTP 200 with body that isn't valid JSON   → throws
//   * HTTP 200 with empty body                   → throws
//
// The panels then convert "map returned but expired != false"
// into a fail-closed block — see the panel-level Round-9
// `strict-bool-only` unit tests below for that half of the
// contract.

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:vault_ai_frontend/api_client.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel')
      .readAsStringSync()
      .replaceAll('\r\n', '\n');
}


VaultAIClient _mk() => const VaultAIClient(baseUrl: 'http://mock');


Future<T> _withMockClient<T>(
  MockClient mock,
  Future<T> Function() body,
) {
  return http.runWithClient(body, () => mock);
}


void main() {
  group('Round 9 — API client draft-expiry parser fail-closed', () {
    test('HTTP 200 + expired:false → returns full map', () async {
      final mock = MockClient((req) async {
        expect(
          req.url.toString(),
          contains('/crypto/wallet/network/solana_mainnet/draft/'),
        );
        expect(req.url.toString(), endsWith('/expiry'));
        return http.Response(
          jsonEncode({
            'expired': false,
            'network': 'solana_mainnet',
            'currentBlockHeight': 999,
            'lastValidBlockHeight': 1000,
            'reason': 'still_valid',
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });
      final result = await _withMockClient(mock, () async {
        return _mk().getCryptoWalletDraftExpiryNetwork(
          network: 'solana_mainnet',
          draftId: 'expiry-parser-valid-abcd12345',
          authToken: 't',
        );
      });
      expect(result['expired'], false);
      expect(result['reason'], 'still_valid');
      expect(result['currentBlockHeight'], 999);
      expect(result['lastValidBlockHeight'], 1000);
    });

    test('HTTP 200 + expired:true → returns full map', () async {
      final mock = MockClient((req) async {
        return http.Response(
          jsonEncode({
            'expired': true,
            'network': 'solana_mainnet',
            'reason': 'blockheight_exceeded',
          }),
          200,
        );
      });
      final result = await _withMockClient(mock, () async {
        return _mk().getCryptoWalletDraftExpiryNetwork(
          network: 'solana_mainnet',
          draftId: 'expiry-parser-expired-abcd1234',
          authToken: 't',
        );
      });
      expect(result['expired'], true);
      expect(result['reason'], 'blockheight_exceeded');
    });

    test('HTTP 200 + expired:null → returns full map (parser MUST '
         'not translate to false)', () async {
      final mock = MockClient((req) async {
        return http.Response(
          jsonEncode({
            'expired': null,
            'network': 'solana_mainnet',
            'reason': 'rpc_unreachable',
          }),
          200,
        );
      });
      final result = await _withMockClient(mock, () async {
        return _mk().getCryptoWalletDraftExpiryNetwork(
          network: 'solana_mainnet',
          draftId: 'expiry-parser-nullexp-abcd1234',
          authToken: 't',
        );
      });
      expect(result.containsKey('expired'), true);
      expect(result['expired'], null);
      // The caller distinguishes null from missing via the strict
      // `expired is bool` check in the panel; this test proves the
      // parser preserves null rather than turning it into false.
    });

    test('HTTP 401 → throws (parser MUST NOT swallow to '
         'expired:false)', () async {
      final mock = MockClient((req) async {
        return http.Response(
          jsonEncode({'detail': 'session_expired'}),
          401,
        );
      });
      final threw = await _withMockClient(mock, () async {
        try {
          await _mk().getCryptoWalletDraftExpiryNetwork(
            network: 'solana_mainnet',
            draftId: 'expiry-parser-401-abcd1234ef',
            authToken: 't',
          );
          return false;
        } catch (_) {
          return true;
        }
      });
      expect(threw, true);
    });

    test('HTTP 403 → throws', () async {
      final mock = MockClient((req) async {
        return http.Response(
          jsonEncode({
            'detail': {
              'code': 'crypto_vault_upgrade_required',
              'message': 'Crypto Vault is not included in the current plan.',
            },
          }),
          403,
        );
      });
      final threw = await _withMockClient(mock, () async {
        try {
          await _mk().getCryptoWalletDraftExpiryNetwork(
            network: 'solana_mainnet',
            draftId: 'expiry-parser-403-abcd1234ef',
            authToken: 't',
          );
          return false;
        } catch (_) {
          return true;
        }
      });
      expect(threw, true);
    });

    test('HTTP 404 → throws', () async {
      final mock = MockClient((req) async {
        return http.Response('not found', 404);
      });
      final threw = await _withMockClient(mock, () async {
        try {
          await _mk().getCryptoWalletDraftExpiryNetwork(
            network: 'solana_mainnet',
            draftId: 'expiry-parser-404-abcd1234ef',
            authToken: 't',
          );
          return false;
        } catch (_) {
          return true;
        }
      });
      expect(threw, true);
    });

    test('HTTP 422 (invalid draft_id) → throws', () async {
      final mock = MockClient((req) async {
        return http.Response(
          jsonEncode({
            'detail': {
              'wallet_engine': 'invalid_draft_id',
              'message': 'The draft_id must be 16-64 chars.',
            },
          }),
          422,
        );
      });
      final threw = await _withMockClient(mock, () async {
        try {
          await _mk().getCryptoWalletDraftExpiryNetwork(
            network: 'solana_mainnet',
            draftId: 'expiry-parser-422-abcd1234ef',
            authToken: 't',
          );
          return false;
        } catch (_) {
          return true;
        }
      });
      expect(threw, true);
    });

    test('HTTP 500 → throws', () async {
      final mock = MockClient((req) async {
        return http.Response('server_error', 500);
      });
      final threw = await _withMockClient(mock, () async {
        try {
          await _mk().getCryptoWalletDraftExpiryNetwork(
            network: 'solana_mainnet',
            draftId: 'expiry-parser-500-abcd1234ef',
            authToken: 't',
          );
          return false;
        } catch (_) {
          return true;
        }
      });
      expect(threw, true);
    });

    test('HTTP 200 with non-map JSON (list body) → throws',
        () async {
      final mock = MockClient((req) async {
        return http.Response('[1,2,3]', 200);
      });
      final threw = await _withMockClient(mock, () async {
        try {
          await _mk().getCryptoWalletDraftExpiryNetwork(
            network: 'solana_mainnet',
            draftId: 'expiry-parser-list-abcd1234ef',
            authToken: 't',
          );
          return false;
        } catch (_) {
          return true;
        }
      });
      expect(threw, true);
    });

    test('HTTP 200 with malformed JSON → throws', () async {
      final mock = MockClient((req) async {
        return http.Response('{not valid json', 200);
      });
      final threw = await _withMockClient(mock, () async {
        try {
          await _mk().getCryptoWalletDraftExpiryNetwork(
            network: 'solana_mainnet',
            draftId: 'expiry-parser-badjson-abcd12345',
            authToken: 't',
          );
          return false;
        } catch (_) {
          return true;
        }
      });
      expect(threw, true);
    });

    test('HTTP 200 with empty body → throws', () async {
      final mock = MockClient((req) async {
        return http.Response('', 200);
      });
      final threw = await _withMockClient(mock, () async {
        try {
          await _mk().getCryptoWalletDraftExpiryNetwork(
            network: 'solana_mainnet',
            draftId: 'expiry-parser-empty-abcd1234ef',
            authToken: 't',
          );
          return false;
        } catch (_) {
          return true;
        }
      });
      expect(threw, true);
    });

    test('TRON envelope shape flows through parser identically',
        () async {
      final mock = MockClient((req) async {
        expect(
          req.url.toString(),
          contains('/crypto/wallet/network/tron_mainnet/draft/'),
        );
        return http.Response(
          jsonEncode({
            'expired': false,
            'network': 'tron_mainnet',
            'nowMs': 1600000000000,
            'expirationMs': 1600000030000,
            'reason': 'still_valid',
          }),
          200,
        );
      });
      final result = await _withMockClient(mock, () async {
        return _mk().getCryptoWalletDraftExpiryNetwork(
          network: 'tron_mainnet',
          draftId: 'expiry-parser-tron-abcd1234ef',
          authToken: 't',
        );
      });
      expect(result['expired'], false);
      expect(result['expirationMs'], 1600000030000);
    });
  });

  group('Round 9 — panel-side strict-bool-only fail-closed rule', () {
    // These are source-level assertions proving the SOL and TRON
    // panel's `_verifyDraftExpiryFailClosed` only allows the flow
    // to continue when `expired` is the canonical Dart `bool`
    // literal `false`. Any other shape — string 'false', numeric
    // 0, null, missing key — MUST return the expired error.

    String _defScope(String path) {
      final src = _readLib(path);
      final defIdx = src.indexOf(
        'Future<String?> _verifyDraftExpiryFailClosed',
      );
      expect(defIdx, greaterThan(-1),
          reason: 'Definition not found in $path');
      // Grab everything from the definition to the next `\n}` at the
      // top level. We can safely bound with the next occurrence of
      // '\n  void ' / '\n  Future<' / '\n  //' section header — but
      // 3000 chars is plenty for this small helper.
      final scope = src.substring(defIdx,
          (defIdx + 3000).clamp(0, src.length));
      // Trim to the end of the first standalone `  }` line (function
      // body closer at 2-space indent).
      final endMatch =
          RegExp(r'\n  \}\n').firstMatch(scope);
      return endMatch != null
          ? scope.substring(0, endMatch.start)
          : scope;
    }

    test('SOL panel: verify uses `expired is bool` narrow-check',
        () {
      final scope = _defScope(
        'ui/crypto_wallet_engine_solana_send_panel.dart',
      );
      expect(scope.contains('expired is bool'), true,
          reason:
              'SOL panel must narrow with `expired is bool` so '
              'only real `false` proceeds.');
      expect(scope.contains('expired == false'), true,
          reason:
              'SOL panel must require `expired == false` after '
              'the type check.');
      // Fall-through tail: after the strict-bool branch, the only
      // remaining path returns the expired-error sentinel.
      expect(
          scope.contains('kSolanaSendDraftExpiredError'),
          true,
          reason:
              'SOL panel must return the draft-expired error '
              'sentinel as the fall-through tail.');
    });

    test('TRON panel: verify uses `expired is bool` narrow-check',
        () {
      final scope = _defScope(
        'ui/crypto_wallet_engine_tron_send_panel.dart',
      );
      expect(scope.contains('expired is bool'), true);
      expect(scope.contains('expired == false'), true);
      expect(scope.contains('kTronSendDraftExpiredError'), true);
    });

    test('SOL panel: definition body has exactly one `return null;` '
         '(the strict-bool allow path)', () {
      final scope = _defScope(
        'ui/crypto_wallet_engine_solana_send_panel.dart',
      );
      final returnNullCount =
          RegExp(r'return null;').allMatches(scope).length;
      expect(returnNullCount, 1,
          reason:
              'Only one `return null;` should exist in the SOL '
              'expiry check; it is the strict-bool allow path.');
    });

    test('TRON panel: definition body has exactly one '
         '`return null;` (the strict-bool allow path)', () {
      final scope = _defScope(
        'ui/crypto_wallet_engine_tron_send_panel.dart',
      );
      final returnNullCount =
          RegExp(r'return null;').allMatches(scope).length;
      expect(returnNullCount, 1);
    });
  });
}
