import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';


String? extractMessageForTest(String body) {
  String detail = body.trim();
  try {
    final decoded = jsonDecode(body);
    if (decoded is Map<String, dynamic>) {
      final rawDetail = decoded['detail'];
      if (rawDetail is Map && rawDetail['message'] != null) {
        detail = rawDetail['message'].toString();
      } else if (rawDetail != null) {
        detail = rawDetail.toString();
      } else if (decoded['message'] != null) {
        detail = decoded['message'].toString();
      }
    }
  } catch (_) {}
  return detail;
}

void main() {
  test('structured 4xx detail Map surfaces detail.message only', () {
    final body = jsonEncode({
      'detail': {
        'code': 'missing_chunks',
        'message': 'Cannot finalize: 2 chunk(s) missing.',
        'missing_chunks': [3, 7],
        'missing_count': 2,
      },
    });

    final extracted = extractMessageForTest(body)!;
    expect(extracted, equals('Cannot finalize: 2 chunk(s) missing.'));
    expect(extracted.contains('missing_chunks'), isFalse,
        reason: 'must not leak the raw Map repr to the user');
    expect(extracted.contains('code'), isFalse,
        reason: 'must not leak the internal code to the user');
  });

  test('vault_quota_exceeded structured body', () {
    final body = jsonEncode({
      'detail': {
        'code': 'vault_quota_exceeded',
        'message': 'Vault storage limit exceeded. Used 950 MB of 1024 MB.',
        'storage_used_bytes': 996147200,
        'storage_limit_bytes': 1073741824,
        'requested_bytes': 209715200,
      },
    });

    final extracted = extractMessageForTest(body)!;
    expect(extracted, equals('Vault storage limit exceeded. Used 950 MB of 1024 MB.'));
    expect(extracted.contains('storage_used_bytes'), isFalse);
  });

  test('upload_safety_cap_exceeded structured body', () {
    final body = jsonEncode({
      'detail': {
        'code': 'upload_safety_cap_exceeded',
        'message':
            'This file is 150 MB. The current single-upload safety cap is '
            '100 MB - a temporary backend limit, not your vault storage quota.',
        'max_upload_bytes': 104857600,
      },
    });

    final extracted = extractMessageForTest(body)!;
    expect(extracted.startsWith('This file is 150 MB.'), isTrue);
    expect(extracted.contains('max_upload_bytes'), isFalse);
  });

  test('flat string detail still works (backward compat)', () {
    final body = jsonEncode({'detail': 'File not found'});
    expect(extractMessageForTest(body), equals('File not found'));
  });

  test('top-level message fallback when no detail', () {
    final body = jsonEncode({'message': 'Some other error'});
    expect(extractMessageForTest(body), equals('Some other error'));
  });

  test('non-JSON body returns the raw body trimmed', () {
    final body = '   plain text error   ';
    expect(extractMessageForTest(body), equals('plain text error'));
  });

  test('Map detail without message falls back to stringification', () {
    final body = jsonEncode({'detail': {'foo': 'bar'}});
    
    
    final out = extractMessageForTest(body)!;
    expect(out.contains('foo'), isTrue);
  });
}
