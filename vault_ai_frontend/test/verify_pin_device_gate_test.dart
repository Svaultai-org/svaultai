import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';


void main() {
  group('DeviceNotTrustedException.fromResponseBody', () {
    test('parses pending-device 403 body and preserves status="pending"', () {
      final body = jsonEncode({
        'detail': {
          'code': 'device_not_trusted',
          'message': 'This device is not trusted yet.',
          'device_id': 'fake-device-id',
          'status': 'pending',
        },
      });

      final exc = DeviceNotTrustedException.fromResponseBody(body);

      expect(exc.status, equals('pending'));
      expect(exc.message, equals('This device is not trusted yet.'));
      expect(exc.deviceId, equals('fake-device-id'));
    });

    test('parses missing-device-id 403 body and preserves status', () {
      final body = jsonEncode({
        'detail': {
          'code': 'missing_device_id',
          'message': 'X-Device-Id header required. Please refresh or update the app.',
          'device_id': null,
          'status': 'missing_device_id',
        },
      });

      final exc = DeviceNotTrustedException.fromResponseBody(body);

      expect(exc.status, equals('missing_device_id'));
      expect(exc.deviceId, isNull);
      expect(
        exc.message,
        contains('X-Device-Id header required'),
      );
    });

    test('parses revoked-device 403 body and preserves status="revoked"', () {
      final body = jsonEncode({
        'detail': {
          'code': 'device_not_trusted',
          'message': 'This device is not trusted yet.',
          'device_id': 'fake-device-id',
          'status': 'revoked',
        },
      });

      final exc = DeviceNotTrustedException.fromResponseBody(body);

      expect(exc.status, equals('revoked'));
    });

    test('falls back to a safe default on malformed JSON', () {
      
      
      final exc = DeviceNotTrustedException.fromResponseBody('not json');

      expect(exc.status, equals('unknown'));
      expect(exc.message, isNotEmpty);
    });

    test('toString includes status (no PII)', () {
      final exc = DeviceNotTrustedException(
        message: 'This device is not trusted yet.',
        status: 'pending',
        deviceId: 'fake-device-id',
      );

      final s = exc.toString();
      expect(s, contains('pending'));
      
      
    });
  });
}
