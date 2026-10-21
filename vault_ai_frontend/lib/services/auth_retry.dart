import 'dart:convert';

/// A failed authentication request with an explicit, bounded retry delay.
/// No response body, identifier, PIN or URL is retained in the exception.
class AuthRetryException implements Exception {
  final int retryAfterSeconds;

  const AuthRetryException._(this.retryAfterSeconds);

  factory AuthRetryException.fromResponse({
    required String responseBody,
    String? retryAfter,
  }) {
    int? seconds = _seconds(retryAfter);
    if (seconds == null) {
      try {
        final body = jsonDecode(responseBody);
        final detail = body is Map ? body['detail'] : null;
        if (detail is Map) seconds = _seconds(detail['reset_in_seconds']);
      } catch (_) {
        // A malformed error is still an explicit retryable throttle, never
        // evidence of a wrong PIN, an absent account, or an expired session.
      }
    }
    return AuthRetryException._(seconds ?? 60);
  }

  String get message => authRetryMessage(retryAfterSeconds);

  @override
  String toString() => message;
}

/// The server deliberately withheld authentication because its security
/// dependency was unavailable. This is distinct from an exhausted retry
/// budget, and never implies that the entered credentials were wrong.
class AuthServiceUnavailableException implements Exception {
  const AuthServiceUnavailableException();

  static const String message =
      'Sign-in is temporarily unavailable. Please try again shortly.';
  static const String signupMessage =
      'Vault creation is temporarily unavailable. Please try again shortly.';

  @override
  String toString() => message;
}

bool isAuthServiceUnavailableResponse(String responseBody) {
  try {
    final body = jsonDecode(responseBody);
    if (body is! Map) return false;
    final detail = body['detail'];
    return detail is Map && detail['code'] == 'auth_temporarily_unavailable';
  } catch (_) {
    return false;
  }
}

String authRetryMessage(int? seconds) =>
    'Too many attempts. Try again in ${(seconds ?? 60).clamp(1, 86400)} seconds.';

int? _seconds(Object? raw) {
  final int? seconds;
  if (raw is int) {
    seconds = raw;
  } else if (raw is String && RegExp(r'^[0-9]{1,6}$').hasMatch(raw)) {
    seconds = int.tryParse(raw);
  } else {
    return null;
  }
  if (seconds == null) return null;
  return seconds.clamp(1, 86400);
}
