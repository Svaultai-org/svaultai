


import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/billing_me_diagnostic.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}




List<String> _extractDevLogLabelsIn(String src, {
  required String funcMarker, required String endMarker,
}) {
  final start = src.indexOf(funcMarker);
  if (start < 0) return const [];
  final end = src.indexOf(endMarker, start);
  final scope = end > start ? src.substring(start, end) : src.substring(start);


  final pattern = RegExp(
    r"(?:developer\.log|_logDevBillingMe|_logDevBillingMeStarted|_logDevTiming)"
    r"\(\s*\n?\s*'([^']+)",
    multiLine: true,
  );
  return [
    for (final m in pattern.allMatches(scope))
      (m.group(1) ?? '')
  ];
}


void main() {


  group('Part A — main.dart wires the extended billing_me diagnostic logs',
      () {

    test('_logDevBillingMeStarted helper exists and emits '
        'billing_me_request_started', () {
      final src = _readLib('main.dart');
      expect(src.contains('void _logDevBillingMeStarted('), isTrue,
          reason: '_logDevBillingMeStarted helper must be defined so we can '
              'log the "call is about to begin" event before the network '
              'roundtrip.');
      expect(src.contains('billing_me_request_started'), isTrue,
          reason: 'the request-started log label the user asked for must '
              'be present in main.dart.');
    });

    test('_logDevBillingMeStarted is guarded by kDebugMode', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('void _logDevBillingMeStarted(');
      expect(start, greaterThan(0));
      final scope = src.substring(start, start + 400);
      expect(scope.contains('if (!kDebugMode) return;'), isTrue,
          reason: 'billing_me_request_started log must never fire in '
              'release builds.');
    });

    test('_logDevBillingMe emits billing_me_path, _status, _error_code, '
        '_ms, _parse_ok, _state_after_refresh (closed set)', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('void _logDevBillingMe(');
      expect(start, greaterThan(0),
          reason: '_logDevBillingMe helper must be defined');
      final scope = src.substring(start, start + 800);


      expect(scope.contains('billing_me_path=/billing/me'), isTrue,
          reason: 'billing_me_path label must be present.');
      expect(scope.contains('billing_me_status='), isTrue);
      expect(scope.contains('billing_me_error_code='), isTrue);
      expect(scope.contains('billing_me_ms='), isTrue);
      expect(scope.contains('billing_me_parse_ok='), isTrue,
          reason: 'billing_me_parse_ok label must be present.');
      expect(scope.contains('billing_me_state_after_refresh='), isTrue,
          reason: 'billing_me_state_after_refresh label must be present.');
    });

    test('refreshBilling calls _logDevBillingMeStarted before the network '
        'call', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('Future<void> refreshBilling(');
      expect(start, greaterThan(0));
      final end = src.indexOf('Future<void> retryBilling(', start);
      expect(end, greaterThan(start));
      final scope = src.substring(start, end);


      final startedIdx = scope.indexOf('_logDevBillingMeStarted');
      final getBillingIdx = scope.indexOf('.getBillingMe(');
      expect(startedIdx, greaterThan(0),
          reason: 'refreshBilling must call _logDevBillingMeStarted.');
      expect(getBillingIdx, greaterThan(startedIdx),
          reason: 'the started log must fire BEFORE the network call so we '
              'can see it in DevTools even if the request hangs.');
    });

    test('refreshBilling calls _logDevBillingMe on BOTH success and error '
        'paths with parse_ok and state_after_refresh', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('Future<void> refreshBilling(');
      final end = src.indexOf('Future<void> retryBilling(', start);
      final scope = src.substring(start, end);



      final logCalls = RegExp(r'_logDevBillingMe\(\s*\n?\s*status:')
          .allMatches(scope).length;
      expect(logCalls, greaterThanOrEqualTo(2),
          reason: 'refreshBilling must log on both success and error paths.');


      expect(scope.contains('parseOk:'), isTrue);
      expect(scope.contains('stateAfter:'), isTrue);
    });
  });



  group('Part B — cold-start timeout widened; slow /billing/me does not '
      'false-error at 5s', () {

    test('refreshBilling timeout is 12 seconds (was 5)', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('Future<void> refreshBilling(');
      final end = src.indexOf('Future<void> retryBilling(', start);
      final scope = src.substring(start, end);


      expect(scope.contains('Duration(seconds: 12)'), isTrue,
          reason: 'billing_me timeout must be widened so a cold-start DB '
              'query does not fall off the 5-second cliff and show a '
              '"temporarily unavailable" banner.');
      expect(scope.contains('Duration(seconds: 5)'), isFalse,
          reason: 'the old 5-second timeout must be gone from refreshBilling.');
    });

    test('the timeout copy explains what happened, not raw exception', () {
      final src = _readLib('main.dart');
      final start = src.indexOf('Future<void> refreshBilling(');
      final end = src.indexOf('Future<void> retryBilling(', start);
      final scope = src.substring(start, end);
      expect(
        scope.contains("'Billing check timed out after 12s'"),
        isTrue,
        reason: 'the closed-set timeout message must reflect the new cap.',
      );
    });
  });



  group('Part C — dev-log labels never contain secrets or PII', () {

    test('every log label in refreshBilling is safe (no stripe / customer / '
        'token / email / bearer / card)', () {
      final src = _readLib('main.dart');
      final labels = _extractDevLogLabelsIn(
        src,
        funcMarker: 'Future<void> refreshBilling(',
        endMarker: 'Future<void> retryBilling(',
      );

      expect(labels.isNotEmpty, isTrue,
          reason: 'refreshBilling must emit at least one dev log label.');


      const banned = {
        'stripe', 'customer_id', 'subscription_id',
        'email', '@',
        'card', 'card_number',
        'token', 'apikey', 'api_key',
        'authorization', 'bearer',
        'sk_test', 'sk_live', 'pk_test', 'pk_live',
      };
      for (final label in labels) {
        final low = label.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'label "$label" leaks banned token "$b"');
        }
      }
    });

    test('every log label in _logDevBillingMe / _logDevBillingMeStarted is '
        'safe', () {
      final src = _readLib('main.dart');


      final helpers = [
        'void _logDevBillingMe(',
        'void _logDevBillingMeStarted(',
      ];
      for (final marker in helpers) {
        final start = src.indexOf(marker);
        expect(start, greaterThan(0),
            reason: 'helper $marker must be defined');
        final scope = src.substring(start, start + 800);



        expect(scope.contains('if (!kDebugMode) return;'), isTrue,
            reason: '$marker must be guarded by kDebugMode.');



        const banned = {
          'stripe', 'customer_id', 'subscription_id',
          'card_number',
          'authorization', 'bearer',
          'sk_test', 'sk_live', 'pk_test', 'pk_live',
        };
        for (final b in banned) {
          expect(scope.toLowerCase().contains(b), isFalse,
              reason: '$marker must not literal-mention "$b"');
        }
      }
    });
  });



  group('Part D — closed-set banner copies remain calm and secret-safe', () {

    test('every closed-set copy stays under 120 chars and never leaks '
        'stripe/customer/subscription', () {
      const banned = ['stripe', 'customer_id', 'subscription_id',
                      'sk_test', 'sk_live', 'pk_test', 'pk_live',
                      'card_number', 'authorization', 'bearer'];
      for (final code in kAllBillingMeCodes) {
        final copy = billingBannerCopyForCode(code);
        if (code == kBillingMeCodeOk) {
          expect(copy, '');
          continue;
        }
        expect(copy.length, lessThan(120),
            reason: 'copy for $code too long: $copy');
        final low = copy.toLowerCase();
        for (final b in banned) {
          expect(low.contains(b), isFalse,
              reason: 'copy for $code leaks "$b"');
        }
      }
    });

    test('auth_expired and device_untrusted keep their distinct actionable '
        'copy (not "temporarily unavailable")', () {

      expect(
        billingBannerCopyForCode(kBillingMeCodeAuthExpired)
            .toLowerCase().contains('sign in'),
        isTrue,
        reason: 'auth_expired copy must tell the user to sign in.',
      );
      expect(
        billingBannerCopyForCode(kBillingMeCodeDeviceUntrusted)
            .toLowerCase().contains('device'),
        isTrue,
        reason: 'device_untrusted copy must mention "device".',
      );



      expect(
        billingBannerCopyForCode(kBillingMeCodeAuthExpired),
        isNot(equals('Subscription status is temporarily unavailable.')),
      );
      expect(
        billingBannerCopyForCode(kBillingMeCodeDeviceUntrusted),
        isNot(equals('Subscription status is temporarily unavailable.')),
      );
    });
  });
}
