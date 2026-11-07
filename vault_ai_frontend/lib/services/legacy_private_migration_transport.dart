import 'dart:convert';

import 'package:http/http.dart' as http;

import '../api_client.dart';
import 'legacy_content_migration_stager.dart';

/// The user-initiated private upgrade can stage ciphertext without ever
/// transmitting the PIN used locally to open older content.
class LegacyPrivateMigrationTransport {
  LegacyPrivateMigrationTransport({
    required this.backendBaseUrl,
    required this.sessionToken,
    required this.deviceId,
    required this.accessIsCurrent,
    this.allowRetire = false,
    http.Client? client,
  }) : _client = client ?? http.Client();

  final String backendBaseUrl;
  final String sessionToken;
  final String? deviceId;
  final bool Function() accessIsCurrent;
  final bool allowRetire;
  final http.Client _client;

  Future<MigrationReply> request(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    if (!accessIsCurrent()) throw StateError('Vault session changed');
    if (!_allowedMigrationRoute(method, path, allowRetire: allowRetire)) {
      throw StateError('Unsupported private migration route');
    }
    final uri = Uri.parse('$backendBaseUrl$path');
    final headers = legacyContentMigrationHeaders(
      sessionToken: sessionToken,
      deviceId: deviceId,
    );
    if (_containsPinField(body)) {
      throw StateError('Private migration cannot send a PIN');
    }
    assertPrivateOnlyPinFreeBody(body);
    assertOutboundPinFreeRequest(uri, headers, body: body);
    late final http.Response response;
    switch (method) {
      case 'GET':
        response = await _client.get(uri, headers: headers);
      case 'POST':
        response = await _client.post(
          uri, headers: headers, body: jsonEncode(body),
        );
      case 'PUT':
        response = await _client.put(
          uri, headers: headers, body: jsonEncode(body),
        );
      default:
        throw StateError('Unsupported private migration method');
    }
    if (!accessIsCurrent()) throw StateError('Vault session changed');
    throwIfClientUpgradeRequired(response.statusCode, response.body);
    try {
      return MigrationReply(response.statusCode, jsonDecode(response.body));
    } on FormatException {
      throw const FormatException('Invalid migration response');
    }
  }

  void close() => _client.close();
}

bool _containsPinField(Object? value) {
  if (value is Map) {
    for (final entry in value.entries) {
      final key = entry.key.toString().toLowerCase().replaceAll('-', '_');
      if (key == 'pin' || key.endsWith('_pin') ||
          _containsPinField(entry.value)) {
        return true;
      }
    }
  } else if (value is Iterable) {
    for (final entry in value) {
      if (_containsPinField(entry)) {
        return true;
      }
    }
  }
  return false;
}

bool _allowedMigrationRoute(String method, String path, {
  required bool allowRetire,
}) {
  if (!path.startsWith('/') || path.contains('..') ||
      path.contains('?') || path.contains('#')) {
    return false;
  }
  final stagedRead = RegExp(
    r'^/vault/legacy-ciphertext/migrate/(item-staged|file-staged)/[^/]+$',
  ).hasMatch(path);
  final fileV2Read = RegExp(
    r'^/vault/file-v2/[^/]+/(manifest|chunk/[0-9]+)$',
  ).hasMatch(path);
  if (method == 'GET') {
    return stagedRead || fileV2Read ||
        (allowRetire && path == '/vault/ciphertext/vault-items');
  }
  if (method == 'POST') {
    if (allowRetire && <String>{
      '/vault/legacy-ciphertext/migrate/item-retire',
      '/vault/legacy-ciphertext/migrate/file-retire',
    }.contains(path)) {
      return true;
    }
    return const <String>{
      '/vault/legacy-ciphertext/migrate/item-stage',
      '/vault/legacy-ciphertext/migrate/item-reset-stage',
      '/vault/legacy-ciphertext/migrate/file-reset-stage',
      '/vault/file-v2/manifest',
    }.contains(path);
  }
  if (method == 'PUT') return path == '/vault/file-v2/chunk';
  return false;
}
