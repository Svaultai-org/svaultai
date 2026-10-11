import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/google_play_verification.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;

const _client = VaultAIClient(baseUrl: 'https://api.example.invalid');
const _product = 'svaultai_storage_50gb';
const _privateToken = 'private-purchase-token';

Map<String, dynamic> _verified([Map<String, dynamic> fields = const {}]) => {
      'verified': true,
      'provider': 'google_play',
      'product_id': _product,
      'status': 'active',
      'acknowledged': true,
      'transition': 'none_to_active',
      ...fields,
    };

Map<String, dynamic> _reconciled([Map<String, dynamic> fields = const {}]) => {
      'reconciled': true,
      'provider': 'google_play',
      'status': 'none',
      'has_active_subscription': false,
      'current_purchase_count': 0,
      'reconciled_count': 0,
      'cleared_pending': true,
      ...fields,
    };

Future<Map<String, dynamic>> _verifyWith(http.Client mock,
        {String productId = _product,
        String purchaseToken = _privateToken,
        bool Function()? responseIsCurrent}) =>
    http.runWithClient(
      () => _client.verifyGooglePlayStoragePurchase(
        authToken: 'test-session',
        purchaseToken: purchaseToken,
        productId: productId,
        responseIsCurrent: responseIsCurrent,
      ),
      () => mock,
    );

Future<Map<String, dynamic>> _reconcileWith(http.Client mock,
        {List<String> tokens = const [], bool Function()? responseIsCurrent}) =>
    http.runWithClient(
      () => _client.reconcileGooglePlayStoragePurchases(
        authToken: 'test-session',
        purchaseTokens: tokens,
        responseIsCurrent: responseIsCurrent,
      ),
      () => mock,
    );

typedef _GuardedBillingCall = Future<Map<String, dynamic>> Function(
    http.Client mock, bool Function()? responseIsCurrent);

final _guardedCalls = <String, _GuardedBillingCall>{
  'verification': (mock, guard) => _verifyWith(mock, responseIsCurrent: guard),
  'reconciliation': (mock, guard) =>
      _reconcileWith(mock, responseIsCurrent: guard),
  'providers': (mock, guard) => http.runWithClient(
        () => _client.getGooglePlayBillingProviders(
            authToken: 'test-session', responseIsCurrent: guard),
        () => mock,
      ),
  'billing state': (mock, guard) => http.runWithClient(
        () => _client.getGooglePlayBillingMe(
            authToken: 'test-session', responseIsCurrent: guard),
        () => mock,
      ),
};

Matcher _staleSessionFailure() => isA<GooglePlayPurchaseVerificationException>()
    .having((e) => e.statusCode, 'stale context HTTP status', 403)
    .having((e) => e.code, 'stale context code', 'google_play_context_changed')
    .having((e) => e.isTransient, 'stale context never retries', isFalse);

Matcher _safeFailure(
        String code) =>
    isA<GooglePlayPurchaseVerificationException>()
        .having((e) => e.statusCode, 'HTTP status', 200)
        .having((e) => e.code, 'stable code', code)
        .having(
            (e) => e.isTransient, 'does not retry malformed success', isFalse);

void main() {
  String? previousDeviceId;
  setUp(() {
    st.SessionTermination.instance.resetForTests();
    previousDeviceId = apiClientDeviceId();
    setApiClientDeviceId('test-billing-device');
  });
  tearDown(() {
    setApiClientDeviceId(previousDeviceId ?? '');
    st.SessionTermination.instance.resetForTests();
  });

  test('provider catalog returns the server Google account binding and tiers',
      () async {
    final catalog = {
      'google_play': {
        'account_token': 'opaque-google-account-binding',
        'base_plan_id': 'monthly-auto',
        'product_ids': googlePlayStorageProductIdAllowlist.toList(),
        'products': [
          {
            'product_id': _product,
            'base_plan_id': 'monthly-auto',
            'billing_period': 'P1M',
            'tier_rank': 1,
            'display_capacity': '50 GB',
            'storage_entitlement_bytes': 53687091200,
            'quantity': 1,
          },
        ],
      },
      'apple': {'app_account_token': 'opaque-apple-binding'},
    };
    final mock = MockClient((request) async {
      expect(request.method, 'GET');
      expect(request.url.path, '/billing/providers');
      expect(request.url.query, isEmpty);
      expect(request.headers['Authorization'], 'Bearer test-session');
      expect(request.headers['X-Device-Id'], 'test-billing-device');
      return http.Response(jsonEncode(catalog), 200);
    });
    expect(
      await http.runWithClient(
        () => _client.getBillingProviders(authToken: 'test-session'),
        () => mock,
      ),
      catalog,
    );
  });

  test('verification posts only the token and product to the trusted route',
      () async {
    final expected = _verified();
    final mock = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/billing/google-play/verify');
      expect(request.url.query, isEmpty);
      expect(request.headers['Authorization'], 'Bearer test-session');
      expect(request.headers['X-Device-Id'], 'test-billing-device');
      expect(request.headers['Content-Type'], 'application/json');
      expect(jsonDecode(request.body), {
        'purchase_token': _privateToken,
        'product_id': _product,
      });
      return http.Response(jsonEncode(expected), 200);
    });
    expect(await _verifyWith(mock), expected);
  });

  test('a deferred downgrade keeps the authoritative current product',
      () async {
    final mock = MockClient((request) async {
      expect(jsonDecode(request.body)['product_id'], _product);
      return http.Response(
        jsonEncode(_verified({
          'product_id': 'svaultai_storage_1tb',
          'transition': 'unchanged',
        })),
        200,
      );
    });
    final result = await _verifyWith(mock);
    expect(result['product_id'], 'svaultai_storage_1tb');
  });

  test('pending verification retains the server acknowledgement state',
      () async {
    final expected = _verified({
      'status': 'pending',
      'acknowledged': false,
      'transition': 'none_to_pending',
      'current_period_end': null,
    });
    expect(
      await _verifyWith(
          MockClient((_) async => http.Response(jsonEncode(expected), 200))),
      expected,
    );
  });

  test('verification canonicalizes only the documented expiry field', () async {
    final mock = MockClient((_) async => http.Response(
          jsonEncode(_verified({
            'current_period_end': '2026-11-10T12:00:00+00:00',
            'purchase_token': _privateToken,
            'signed_transaction': 'private-receipt',
            'debug': 'private-backend-payload',
          })),
          200,
        ));
    final result = await _verifyWith(mock);
    expect(result['current_period_end'], '2026-11-10T12:00:00.000Z');
    expect(result.toString(), isNot(contains('private')));
    expect(result.containsKey('purchase_token'), isFalse);
  });

  for (final body in ['{}', '{"verified":false}', '{"verified":"true"}']) {
    test('verification rejects unconfirmed HTTP 200: $body', () async {
      await expectLater(
        _verifyWith(MockClient((_) async => http.Response(body, 200))),
        throwsA(_safeFailure('unconfirmed_verification')),
      );
    });
  }
  for (final body in ['not-json', '[]', 'null', 'true']) {
    test('verification rejects malformed HTTP 200: $body', () async {
      await expectLater(
        _verifyWith(MockClient((_) async => http.Response(body, 200))),
        throwsA(_safeFailure('invalid_verification_response')),
      );
    });
  }
  final invalidVerifications = <String, Map<String, dynamic>>{
    'wrong provider': _verified({'provider': 'apple'}),
    'unknown product': _verified({'product_id': 'another_store_product'}),
    'missing product': _verified()..remove('product_id'),
    'unknown status': _verified({'status': 'private-status'}),
    'missing status': _verified()..remove('status'),
    'missing acknowledgement': _verified()..remove('acknowledged'),
    'string acknowledgement': _verified({'acknowledged': 'true'}),
    'missing transition': _verified()..remove('transition'),
    'unknown transition': _verified({'transition': 'private-transition'}),
    'malformed expiry': _verified({'current_period_end': _privateToken}),
  };
  for (final entry in invalidVerifications.entries) {
    test('verification rejects ${entry.key}', () async {
      await expectLater(
        _verifyWith(MockClient(
            (_) async => http.Response(jsonEncode(entry.value), 200))),
        throwsA(_safeFailure('invalid_verification_response')),
      );
    });
  }

  test('reconciliation posts an empty authoritative device query', () async {
    final expected = _reconciled();
    final mock = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/billing/google-play/reconcile');
      expect(request.url.query, isEmpty);
      expect(request.headers['Authorization'], 'Bearer test-session');
      expect(request.headers['X-Device-Id'], 'test-billing-device');
      expect(request.headers['Content-Type'], 'application/json');
      expect(jsonDecode(request.body), {'purchase_tokens': []});
      return http.Response(jsonEncode(expected), 200);
    });
    expect(await _reconcileWith(mock), expected);
  });

  test('reconciliation preserves tokens and validates distinct current count',
      () async {
    const tokens = [_privateToken, ' second-private-token ', _privateToken];
    final expected = _reconciled({
      'status': 'in_grace',
      'has_active_subscription': true,
      'current_purchase_count': 2,
      'reconciled_count': 3,
      'cleared_pending': false,
    });
    final mock = MockClient((request) async {
      expect(jsonDecode(request.body), {'purchase_tokens': tokens});
      return http.Response(jsonEncode(expected), 200);
    });
    expect(await _reconcileWith(mock, tokens: tokens), expected);
  });

  test('reconciliation accepts normalized delinquency without active storage',
      () async {
    final expected = _reconciled({'status': 'past_due'});
    expect(
      await _reconcileWith(
          MockClient((_) async => http.Response(jsonEncode(expected), 200))),
      expected,
    );
  });

  final invalidReconciliations = <String, String>{
    'unconfirmed': jsonEncode(_reconciled({'reconciled': false})),
    'wrong provider': jsonEncode(_reconciled({'provider': 'apple'})),
    'unknown status': jsonEncode(_reconciled({'status': 'private-status'})),
    'inconsistent active state':
        jsonEncode(_reconciled({'has_active_subscription': true})),
    'string active state':
        jsonEncode(_reconciled({'has_active_subscription': 'false'})),
    'wrong current count':
        jsonEncode(_reconciled({'current_purchase_count': 1})),
    'noninteger count': jsonEncode(_reconciled({'reconciled_count': 1.5})),
    'negative count': jsonEncode(_reconciled({'reconciled_count': -1})),
    'missing cleared pending':
        jsonEncode(_reconciled()..remove('cleared_pending')),
    'string cleared pending':
        jsonEncode(_reconciled({'cleared_pending': 'true'})),
    'nonobject': '[]',
    'nonjson': 'private-invalid-json',
  };
  for (final entry in invalidReconciliations.entries) {
    test('reconciliation rejects ${entry.key}', () async {
      await expectLater(
        _reconcileWith(
            MockClient((_) async => http.Response(entry.value, 200))),
        throwsA(_safeFailure(entry.key == 'unconfirmed'
            ? 'unconfirmed_reconciliation'
            : 'invalid_reconciliation_response')),
      );
    });
  }

  test('reconciliation strips unexpected private response fields', () async {
    final mock = MockClient((_) async => http.Response(
          jsonEncode(_reconciled({
            'purchase_tokens': [_privateToken]
          })),
          200,
        ));
    expect((await _reconcileWith(mock)).toString(), isNot(contains('private')));
  });

  for (final entry in <String, int>{
    'google_play_verification_unavailable': 503,
    'google_play_billing_not_configured': 503,
    'purchase_already_bound': 409,
    'active_storage_billing_owner': 409,
    'google_play_replacement_required': 409,
    'google_play_purchase_superseded': 409,
    'google_play_purchase_invalid': 400,
  }.entries) {
    test('${entry.key} is a safe terminal provider failure', () async {
      final mock = MockClient((_) async => http.Response(
            jsonEncode({
              'detail': {'code': entry.key, 'message': _privateToken},
            }),
            entry.value,
          ));
      await expectLater(
        _verifyWith(mock),
        throwsA(isA<GooglePlayPurchaseVerificationException>()
            .having((e) => e.code, 'code', entry.key)
            .having((e) => e.statusCode, 'HTTP status', entry.value)
            .having((e) => e.isTransient, 'no retry', isFalse)
            .having((e) => '${e.toString()} ${e.userMessage}',
                'no private payload', isNot(contains('private')))),
      );
      expect(
        GooglePlayPurchaseVerificationException(
                code: entry.key, statusCode: 503)
            .isTransient,
        isFalse,
      );
    });
  }

  for (final status in [404, 429, 500, 502, 503]) {
    test('HTTP $status retries only server failures and keeps payload private',
        () async {
      final mock = MockClient((_) async => http.Response(
            jsonEncode({
              'detail': {'code': _privateToken, 'message': 'private-debug'},
            }),
            status,
          ));
      await expectLater(
        _verifyWith(mock),
        throwsA(isA<GooglePlayPurchaseVerificationException>()
            .having((e) => e.code, 'unknown codes hidden', isNull)
            .having((e) => e.isTransient, 'retry', status >= 500)
            .having((e) => e.toString(), 'private payload',
                isNot(contains('private')))),
      );
    });
  }

  test('explicit transient verification failures remain retryable', () async {
    final mock = MockClient((_) async => http.Response(
          jsonEncode({
            'detail': {'code': 'google_play_verification_retry'},
          }),
          503,
        ));
    await expectLater(
      _reconcileWith(mock),
      throwsA(isA<GooglePlayPurchaseVerificationException>()
          .having((e) => e.code, 'code', 'google_play_verification_retry')
          .having((e) => e.isTransient, 'server retry', isTrue)),
    );
  });

  for (final error in [
    http.ClientException('private-network-debug $_privateToken'),
    TimeoutException('private-timeout-debug $_privateToken'),
  ]) {
    test('${error.runtimeType} is safe and retryable', () async {
      final prints = <String>[];
      await runZoned(
        () async => expectLater(
          _verifyWith(MockClient((_) async => throw error)),
          throwsA(isA<GooglePlayPurchaseVerificationException>()
              .having((e) => e.isTransient, 'network retry', isTrue)
              .having((e) => '${e.toString()} ${e.userMessage}',
                  'private payload', isNot(contains('private')))),
        ),
        zoneSpecification: ZoneSpecification(
          print: (_, __, ___, line) => prints.add(line),
        ),
      );
      expect(prints.join('\n'), isNot(contains('private')));
    });
  }

  test('response logs omit private reason phrases and response bodies',
      () async {
    final prints = <String>[];
    await runZoned(
      () async => _verifyWith(MockClient((_) async => http.Response(
            jsonEncode(_verified({'purchase_token': _privateToken})),
            200,
            reasonPhrase: _privateToken,
          ))),
      zoneSpecification: ZoneSpecification(
        print: (_, __, ___, line) => prints.add(line),
      ),
    );
    expect(prints.join('\n'), isNot(contains('private')));
  });

  test('unexpected transport failures are safe and not retryable', () async {
    await expectLater(
      _verifyWith(MockClient((_) async => throw StateError(_privateToken))),
      throwsA(isA<GooglePlayPurchaseVerificationException>()
          .having((e) => e.code, 'code', 'google_play_request_failed')
          .having((e) => e.isTransient, 'not network', isFalse)
          .having((e) => e.toString(), 'private payload',
              isNot(contains('private')))),
    );
  });

  test('uncoded authorization retains the existing client classification',
      () async {
    await expectLater(
      _verifyWith(MockClient((_) async =>
          http.Response(jsonEncode({'detail': _privateToken}), 401))),
      throwsA(isA<ApiAuthorizationException>()),
    );
    expect(st.SessionTermination.instance.isTerminated, isFalse);
  });

  test('coded session expiry retains the existing termination machinery',
      () async {
    await expectLater(
      _reconcileWith(MockClient((_) async => http.Response(
            jsonEncode({
              'detail': {'code': 'session_expired', 'message': _privateToken},
            }),
            401,
          ))),
      throwsA(isA<SessionTerminatedException>()
          .having((e) => e.code, 'code', st.SessionTerminationCode.expired)),
    );
    expect(st.SessionTermination.instance.isTerminated, isTrue);
  });

  test('device rejection retains its typed classification without backend text',
      () async {
    await expectLater(
      _verifyWith(MockClient((_) async => http.Response(
            jsonEncode({
              'detail': {
                'code': 'device_not_trusted',
                'message': _privateToken,
                'device_id': _privateToken,
                'status': _privateToken,
              },
            }),
            403,
          ))),
      throwsA(isA<DeviceNotTrustedException>().having((e) => e.toString(),
          'no private backend text', isNot(contains('private')))),
    );
  });

  test('invalid local purchase payloads do not reach the server', () async {
    var requests = 0;
    final mock = MockClient((_) async {
      requests++;
      return http.Response('{}', 200);
    });
    await expectLater(_verifyWith(mock, purchaseToken: ' '), throwsException);
    await expectLater(
        _verifyWith(mock, productId: 'unknown-product'), throwsException);
    await expectLater(
        _reconcileWith(mock, tokens: List.filled(21, _privateToken)),
        throwsException);
    await expectLater(_reconcileWith(mock, tokens: ['']), throwsException);
    expect(requests, 0);
  });

  for (final entry in _guardedCalls.entries) {
    test('${entry.key} rejects a stale session before sending', () async {
      var requests = 0;
      final mock = MockClient((_) async {
        requests++;
        return http.Response('{}', 200);
      });
      await expectLater(
        entry.value(mock, () => false),
        throwsA(_staleSessionFailure()),
      );
      expect(requests, 0);
      expect(st.SessionTermination.instance.isTerminated, isFalse);
    });

    test(
        '${entry.key} discards a late coded 401 before global session handling',
        () async {
      var current = true;
      var terminationCalls = 0;
      st.SessionTermination.instance
          .setHandler((_) async => terminationCalls++);
      final started = Completer<void>();
      final response = Completer<http.Response>();
      final mock = MockClient((_) async {
        started.complete();
        return response.future;
      });
      final expectation = expectLater(
        entry.value(mock, () => current),
        throwsA(_staleSessionFailure()),
      );
      await started.future;
      current = false;
      // A successful sign-in has reset the global termination flag while the
      // old vault request is still waiting for its server response.
      st.SessionTermination.instance.reset();
      final generation = st.SessionTermination.instance.generation;
      response.complete(http.Response(
        jsonEncode({
          'detail': {'code': 'session_revoked', 'message': _privateToken},
        }),
        401,
      ));
      await expectation;
      expect(terminationCalls, 0);
      expect(st.SessionTermination.instance.generation, generation);
      expect(st.SessionTermination.instance.isTerminated, isFalse);
    });

    test('${entry.key} discards a late successful response', () async {
      var current = true;
      final started = Completer<void>();
      final response = Completer<http.Response>();
      final mock = MockClient((_) async {
        started.complete();
        return response.future;
      });
      final expectation = expectLater(
        entry.value(mock, () => current),
        throwsA(_staleSessionFailure()),
      );
      await started.future;
      current = false;
      response.complete(http.Response(jsonEncode(_verified()), 200));
      await expectation;
      expect(st.SessionTermination.instance.isTerminated, isFalse);
    });

    for (final error in [
      http.ClientException(_privateToken),
      TimeoutException(_privateToken),
      StateError(_privateToken),
    ]) {
      test('${entry.key} discards a stale ${error.runtimeType}', () async {
        var current = true;
        final started = Completer<void>();
        final response = Completer<http.Response>();
        final mock = MockClient((_) async {
          started.complete();
          return response.future;
        });
        final expectation = expectLater(
          entry.value(mock, () => current),
          throwsA(_staleSessionFailure()),
        );
        await started.future;
        current = false;
        response.completeError(error);
        await expectation;
        expect(st.SessionTermination.instance.isTerminated, isFalse);
      });
    }
  }

  for (final entry in {
    'providers': '/billing/providers',
    'billing state': '/billing/me',
  }.entries) {
    test('Google ${entry.key} uses the existing authenticated GET contract',
        () async {
      final expected = {'server_state': true};
      final mock = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, entry.value);
        expect(request.url.query, isEmpty);
        expect(request.headers['Authorization'], 'Bearer test-session');
        expect(request.headers['X-Device-Id'], 'test-billing-device');
        expect(request.body, isEmpty);
        return http.Response(jsonEncode(expected), 200);
      });
      expect(await _guardedCalls[entry.key]!(mock, () => true), expected);
    });

    for (final body in ['[]', 'private-invalid-json']) {
      test('Google ${entry.key} safely rejects malformed response $body',
          () async {
        await expectLater(
          _guardedCalls[entry.key]!(
              MockClient((_) async => http.Response(body, 200)), () => true),
          throwsA(_safeFailure(entry.key == 'providers'
              ? 'invalid_google_play_providers_response'
              : 'invalid_google_play_billing_response')),
        );
      });
    }
  }
}
