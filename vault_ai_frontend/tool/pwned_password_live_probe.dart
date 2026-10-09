// QA-only public-provider probe. It accepts no arguments or private passwords,
// uses no account/session/API key, and never logs a hash or provider response.
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:vault_ai_frontend/services/pwned_password_check.dart';

const _sample = 'password';
const _webOrigin = 'https://app.svaultai.com';

class _OriginObservingClient extends http.BaseClient {
  final http.Client _delegate = http.Client();
  int? observedStatus;
  String? observedAllowedOrigin;
  String? observedAllowedHeaders;
  String? observedAllowedMethods;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    request.headers['Origin'] = _webOrigin;
    final response = await _delegate.send(request);
    observedStatus = response.statusCode;
    observedAllowedOrigin = response.headers['access-control-allow-origin'];
    observedAllowedHeaders = response.headers['access-control-allow-headers'];
    observedAllowedMethods = response.headers['access-control-allow-methods'];
    return response;
  }

  @override
  void close() => _delegate.close();
}

bool _originAllowed(String? value) => value == '*' || value == _webOrigin;

Future<void> main() async {
  final client = _OriginObservingClient();
  final checker = PwnedPasswordChecker(client: client);
  final prefix = sha1.convert(utf8.encode(_sample)).toString().substring(0, 5);
  final uri =
      Uri.https('api.pwnedpasswords.com', '/range/${prefix.toUpperCase()}');
  final report = <String, Object?>{
    'probe': 'public_synthetic_password_only',
    'checkedAtUtc': DateTime.now().toUtc().toIso8601String(),
    'actualChecker': 'PwnedPasswordChecker',
    'browserExecuted': false,
    'providerRequiresApiKey': false,
  };
  try {
    final result = await checker.check(_sample);
    report.addAll({
      'providerStatus': 'available',
      'getHttpStatus': client.observedStatus,
      'getCorsAllowsWebOrigin': _originAllowed(client.observedAllowedOrigin),
      'getAccessControlAllowOrigin': client.observedAllowedOrigin,
      'publicSampleFound': result.found,
      'publicSampleOccurrences': result.occurrences,
    });
    if (!result.found) exitCode = 1;
  } on PasswordExposureUnavailable {
    report['providerStatus'] = 'unavailable';
    exitCode = 1;
  }
  try {
    final request = http.Request('OPTIONS', uri)
      ..headers.addAll({
        'Origin': _webOrigin,
        'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'add-padding',
      });
    final response =
        await client.send(request).timeout(const Duration(seconds: 12));
    await response.stream.drain<void>().timeout(const Duration(seconds: 12));
    final allowedHeaders = client.observedAllowedHeaders ?? '';
    final acceptsPadding = allowedHeaders
            .toLowerCase()
            .split(',')
            .map((v) => v.trim())
            .contains('add-padding') ||
        allowedHeaders == '*';
    final allowedMethods = client.observedAllowedMethods ?? '';
    final acceptsGet = allowedMethods
            .toUpperCase()
            .split(',')
            .map((v) => v.trim())
            .contains('GET') ||
        allowedMethods == '*';
    final success = response.statusCode >= 200 &&
        response.statusCode < 300 &&
        _originAllowed(client.observedAllowedOrigin) &&
        acceptsPadding &&
        acceptsGet;
    report.addAll({
      'preflightHttpStatus': response.statusCode,
      'preflightAllowsWebOrigin': _originAllowed(client.observedAllowedOrigin),
      'preflightAccessControlAllowOrigin': client.observedAllowedOrigin,
      'preflightAllowsAddPadding': acceptsPadding,
      'preflightAllowsGet': acceptsGet,
      'corsHeaderProbePassed': success,
      'limitation':
          'Checks live CORS headers; does not execute browser enforcement.',
    });
    if (!success) exitCode = 1;
  } catch (_) {
    report['corsHeaderProbePassed'] = false;
    report['preflightStatus'] = 'unavailable';
    exitCode = 1;
  } finally {
    checker.close();
    client.close();
  }
  stdout.writeln(jsonEncode(report));
}
