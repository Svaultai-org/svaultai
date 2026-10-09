import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;

class PasswordExposureResult {
  final int occurrences;
  const PasswordExposureResult(this.occurrences);
  bool get found => occurrences > 0;
}

class PasswordExposureUnavailable implements Exception {
  const PasswordExposureUnavailable();
  @override
  String toString() => 'Password exposure check is unavailable.';
}

abstract interface class PasswordExposureChecker {
  Future<PasswordExposureResult> check(String password);
}

/// Only a five-character SHA-1 prefix leaves this device. SHA-1 is used to
/// address the provider's existing corpus, never for storing passwords.
class PwnedPasswordChecker implements PasswordExposureChecker {
  final http.Client _client;
  final bool _ownsClient;
  final Duration timeout;

  PwnedPasswordChecker(
      {http.Client? client, this.timeout = const Duration(seconds: 12)})
      : _client = client ?? http.Client(),
        _ownsClient = client == null;
  void close() {
    if (_ownsClient) _client.close();
  }

  @override
  Future<PasswordExposureResult> check(String password) async {
    if (password.isEmpty) throw const PasswordExposureUnavailable();
    final digest = sha1.convert(utf8.encode(password)).toString().toUpperCase();
    final prefix = digest.substring(0, 5);
    final suffix = digest.substring(5);
    try {
      final response = await _client.get(
        Uri.https('api.pwnedpasswords.com', '/range/$prefix'),
        headers: const {'Add-Padding': 'true'},
      ).timeout(timeout);
      if (response.statusCode != 200 || response.body.isEmpty) {
        throw const PasswordExposureUnavailable();
      }
      var rows = 0;
      var count = 0;
      for (final line in const LineSplitter().convert(response.body)) {
        if (line.trim().isEmpty) continue;
        final match =
            RegExp(r'^([0-9A-Fa-f]{35}):([0-9]+)$').firstMatch(line.trim());
        if (match == null) throw const PasswordExposureUnavailable();
        final occurrences = int.tryParse(match.group(2)!);
        if (occurrences == null || occurrences < 0) {
          throw const PasswordExposureUnavailable();
        }
        rows++;
        if (match.group(1)!.toUpperCase() == suffix && occurrences > count) {
          count = occurrences;
        }
      }
      if (rows == 0) throw const PasswordExposureUnavailable();
      return PasswordExposureResult(count);
    } catch (_) {
      // Never include the password, hash, provider response or request in an
      // exception message that could reach diagnostics or the interface.
      throw const PasswordExposureUnavailable();
    }
  }
}
