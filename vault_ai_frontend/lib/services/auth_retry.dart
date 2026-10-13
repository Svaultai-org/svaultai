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
