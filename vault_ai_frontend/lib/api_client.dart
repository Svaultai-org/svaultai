import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kReleaseMode;
import 'package:http/http.dart' as http;

import 'services/session_termination.dart' as st;
import 'services/vault_key_hierarchy.dart' as vault_key_hierarchy;
import 'services/wallet_backup_v2_repository.dart';
import 'services/zk_active_mvk.dart' as zk_mvk_store;

void _vlog(String tag, [Map<String, Object?>? data]) {
  if (kReleaseMode) return;
  final payload = data == null
      ? ''
      : data.entries
          .map((e) => '${e.key}=${_safeVlogValue(tag, e.key, e.value)}')
          .join(' ');

  print('[vault-debug] $tag $payload');
}

String _safeVlogValue(String tag, String key, Object? value) {
  if (value == null) return 'null';
  final lowerKey = key.toLowerCase();
  final lowerTag = tag.toLowerCase();
  final text = value.toString();
  if (lowerKey == 'url') {
    return _safeUrlForLog(text);
  }
  if (lowerKey.contains('vault_name') ||
      lowerKey.contains('vaultname') ||
      lowerKey.contains('username') ||
      lowerKey.contains('display_name') ||
      lowerKey.contains('token') ||
      lowerKey.contains('authorization') ||
      lowerKey.contains('password') ||
      lowerKey.contains('secret') ||
      lowerKey.contains('ciphertext') ||
      lowerKey.contains('credential') ||
      lowerKey == 'body' ||
      lowerKey == 'response_body' ||
      lowerKey == 'errorbody' ||
      lowerKey == 'prompt' ||
      lowerKey == 'query' ||
      lowerKey == 'message' ||
      (lowerTag.contains('chat') && lowerKey.contains('error'))) {
    return '<redacted>';
  }
  if (lowerKey.contains('pin') &&
      lowerKey != 'pin_len' &&
      lowerKey != 'pinlen' &&
      lowerKey != 'pin_present') {
    return '<redacted>';
  }
  return text;
}

String _safeUrlForLog(String raw) {
  try {
    final uri = Uri.parse(raw);
    final queryKeys = uri.queryParameters.keys.toList()..sort();
    final query = queryKeys.isEmpty ? '' : '?${queryKeys.join('&')}';
    return uri.replace(query: '').toString() + query;
  } catch (_) {
    return '<redacted-url>';
  }
}

void _vlogRequest(String label, Uri uri, Map<String, String> headers) {
  _vlog('http.request', {
    'label': label,
    'url': uri.toString(),
    'auth_present': headers.containsKey('Authorization'),
    'x_device_id_present': headers.containsKey('X-Device-Id'),
    'content_type': headers['Content-Type'] ?? '-',
    'accept': headers['Accept'] ?? '-',
  });
}

Future<http.Response> _runWithNetLog(
  String label,
  Uri uri,
  Future<http.Response> Function() send,
) async {
  try {
    final response = await send();
    _vlog('http.response', {
      'label': label,
      'url': uri.toString(),
      'status': response.statusCode,
      'reason': response.reasonPhrase ?? '-',
      'body_len': response.body.length,
    });
    return response;
  } catch (e, st) {
    _vlog('http.network_error', {
      'label': label,
      'url': uri.toString(),
      'error_type': e.runtimeType.toString(),
      'error': e.toString(),
      'stack_first_line':
          st.toString().split('\n').firstWhere((_) => true, orElse: () => '-'),
    });
    rethrow;
  }
}

/// A checkout failure whose string representation is safe to display.
///
/// Stripe response details and backend diagnostics must never cross this UI
/// boundary. [code] is retained only for known product flows such as the
/// supported lower-plan dialog.
class BillingCheckoutException implements Exception {
  final String code;
  final String message;

  const BillingCheckoutException({
    required this.code,
    required this.message,
  });

  @override
  String toString() => message;
}

class OrphanDataException implements Exception {
  final String message;
  final String? vaultName;
  final int itemCount;
  final int fileCount;

  const OrphanDataException({
    required this.message,
    this.vaultName,
    this.itemCount = 0,
    this.fileCount = 0,
  });

  factory OrphanDataException.fromResponseBody(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'];
        if (detail is Map<String, dynamic>) {
          final orphan = detail['orphan_data'];
          final orphanMap = orphan is Map<String, dynamic>
              ? orphan
              : const <String, dynamic>{};
          return OrphanDataException(
            message: (detail['message'] ?? 'Orphan data detected').toString(),
            vaultName: orphanMap['vault_name']?.toString(),
            itemCount: (orphanMap['item_count'] as num?)?.toInt() ?? 0,
            fileCount: (orphanMap['file_count'] as num?)?.toInt() ?? 0,
          );
        }
      }
    } catch (_) {}
    return const OrphanDataException(message: 'Orphan data detected');
  }

  @override
  String toString() =>
      'OrphanDataException(message: $message, vaultName: $vaultName, items: $itemCount, files: $fileCount)';
}

class VaultFrozenException implements Exception {
  final String message;
  const VaultFrozenException({required this.message});
  @override
  String toString() => 'VaultFrozenException(message: $message)';
}

class VaultLockedException implements Exception {
  final String message;
  final String? lockedUntil;
  final int? attemptsLeft;
  const VaultLockedException({
    required this.message,
    this.lockedUntil,
    this.attemptsLeft,
  });
  @override
  String toString() =>
      'VaultLockedException(message: $message, lockedUntil: $lockedUntil)';
}

class VaultNameTakenException implements Exception {
  final String message;
  const VaultNameTakenException({
    this.message = 'That vault name is already taken.',
  });
  @override
  String toString() => 'VaultNameTakenException(message: $message)';
}

/// Thrown by ``saveInheritanceCredentials`` / ``replaceInheritanceCredentials``
/// when the backend responds with a non-200 that is NOT one of the
/// generic auth / device / lock exceptions the API client already
/// classifies (those still throw ``AuthExpiredException`` /
/// ``VaultLockedException`` / etc. first).
///
/// Preserves the backend's ``detail.code`` (e.g. ``INH-CRED-005``,
/// ``INH-CRED-006``, ``INH-CRED-007``) so the UI can surface the
/// real reference tag instead of the pre-2026-07-22 hardcoded
/// ``INH-CRED-004`` fallback that hid every non-shape failure.
class InheritanceCredSaveException implements Exception {
  final int statusCode;

  /// The backend's stable ``detail.code`` string, or null when the
  /// response body could not be parsed as the expected shape.
  final String? backendCode;

  /// The backend's user-safe ``detail.message`` (already scrubbed
  /// of internals by ``inheritance_http_error``).
  final String? backendMessage;

  const InheritanceCredSaveException({
    required this.statusCode,
    this.backendCode,
    this.backendMessage,
  });

  @override
  String toString() => 'InheritanceCredSaveException(statusCode: $statusCode, '
      'backendCode: $backendCode, backendMessage: $backendMessage)';
}

class InvalidCredentialsException implements Exception {
  final String message;
  const InvalidCredentialsException({
    this.message = 'Vault name or PIN is incorrect',
  });
  @override
  String toString() => 'InvalidCredentialsException(message: $message)';
}

class StorageLimitExceededException implements Exception {
  final String message;
  final int? usedBytes;
  final int? limitBytes;
  final int? projectedBytes;

  const StorageLimitExceededException({
    required this.message,
    this.usedBytes,
    this.limitBytes,
    this.projectedBytes,
  });

  @override
  String toString() => 'StorageLimitExceededException(message: $message, '
      'used: $usedBytes, limit: $limitBytes, '
      'projected: $projectedBytes)';
}

class DuplicateFoundUploadException implements Exception {
  final Map<String, dynamic> detail;
  const DuplicateFoundUploadException(this.detail);

  String? get existingFileId => detail['existing_file_id'] as String?;

  String get message =>
      (detail['message'] as String?) ?? 'This file already exists.';

  @override
  String toString() =>
      'DuplicateFoundUploadException(existing=$existingFileId)';
}

class NameConflictUploadException implements Exception {
  final Map<String, dynamic> detail;
  const NameConflictUploadException(this.detail);

  String? get existingFileId => detail['existing_file_id'] as String?;

  String get message =>
      (detail['message'] as String?) ??
      'A file with this name already exists in this folder, but the '
          'content is different.';

  @override
  String toString() => 'NameConflictUploadException(existing=$existingFileId)';
}

class ImportBatchTerminalException implements Exception {
  final String message;
  final String? status;
  const ImportBatchTerminalException({
    required this.message,
    this.status,
  });
  @override
  String toString() =>
      'ImportBatchTerminalException(message: $message, status: $status)';
}

class RateLimitedException implements Exception {
  final String message;
  final int? resetInSeconds;
  const RateLimitedException({
    this.message =
        'Too many attempts. Please wait a few minutes and try again.',
    this.resetInSeconds,
  });
  @override
  String toString() =>
      'RateLimitedException(message: $message, resetInSeconds: $resetInSeconds)';
}

class AuthExpiredException implements Exception {
  final String message;
  const AuthExpiredException({
    this.message = 'Session expired. Please sign in again.',
  });
  @override
  String toString() => 'AuthExpiredException(message: $message)';
}

/// Coded 401 from the backend's session-revocation layer (Step B.3).
///
/// Raised only when `detail.code` is one of the four session codes:
/// `session_superseded`, `session_expired`, `session_revoked`, or
/// `invalid_session`. The message is the fixed user-facing string
/// from [st.userMessageFor]; the raw backend body is NOT surfaced
/// so token ids, hashes, or vault ids never reach the UI or logs.
class SessionTerminatedException implements Exception {
  final st.SessionTerminationCode code;
  final String message;
  const SessionTerminatedException({
    required this.code,
    required this.message,
  });
  @override
  String toString() => 'SessionTerminatedException(code: $code)';
}

class InvalidVaultUnlockException implements Exception {
  final String message;
  const InvalidVaultUnlockException({
    this.message =
        'Your vault unlock session expired or no longer matches this vault. Please enter your PIN again.',
  });
  @override
  String toString() => 'InvalidVaultUnlockException(message: $message)';
}

/// Client-declared protocol version for encrypted-request endpoints.
///
/// Sent inside the request body (never a header). The backend uses
/// this — not the diagnostic X-App-Release header — to decide
/// whether the KDF-generation fields are mandatory. See
/// `vault_kdf_generation.client_requires_kdf_fields`.
///
/// 2 = requires kdf_salt_used AND kdf_iterations_used on every
/// encrypted request.
const int kCryptoProtocolVersion = 2;

/// Pure function that builds the JSON map sent as the /chat request
/// body. Exposed at top level so tests can call it directly with a
/// null-origin scenario (the pre-fix ZK-path shape) and prove the
/// KDF fields are absent — the concrete evidence the review gate
/// asked for. Never touches HTTP, sessions, crypto state, or
/// singletons; every input is a parameter.
Map<String, dynamic> buildChatRequestBody({
  required String encryptedMessage,
  required String vaultName,
  required String pin,
  List<String>? uploadedFileIds,
  String? appLocale,
  Map<String, String>? selectionHint,
  String? kdfSaltUsed,
  int? kdfIterationsUsed,
}) {
  return <String, dynamic>{
    'encrypted_message': encryptedMessage,
    'vault_name': vaultName,
    'pin': pin,
    'uploaded_file_ids': uploadedFileIds ?? const <String>[],
    // Client-declared protocol version. Backend uses THIS (not a
    // header) to gate whether the KDF fields are mandatory.
    'crypto_protocol_version': kCryptoProtocolVersion,
    if (appLocale != null && appLocale.isNotEmpty) 'app_locale': appLocale,
    if (selectionHint != null && selectionHint.isNotEmpty)
      'selection_hint': selectionHint,
    if (kdfSaltUsed != null && kdfSaltUsed.isNotEmpty)
      'kdf_salt_used': kdfSaltUsed,
    if (kdfIterationsUsed != null) 'kdf_iterations_used': kdfIterationsUsed,
  };
}

/// Server returned 400 "Invalid PIN or corrupted data" from
/// [vault_core.decrypt_message]. Semantically DISTINCT from
/// [InvalidVaultUnlockException] — the session and unlock are
/// intact, the client's ciphertext just did not decrypt under the
/// server's derived key. The correct recovery is to re-derive the
/// crypto context (freshly from /vault-meta) and ask the user to
/// tap send again. NEVER map this to session-expired sign-out or
/// "Incorrect PIN" — those were the confusing 2026-07-22 production
/// UX symptoms.
class CryptoContextMismatchException implements Exception {
  final String message;
  const CryptoContextMismatchException({
    this.message = 'Vault crypto state is out of sync. Please tap send again.',
  });
  @override
  String toString() => 'CryptoContextMismatchException(message: $message)';
}

/// Server returned 401 `invalid_pin` from [verify_vault_pin]. The
/// user's PIN did NOT match the stored verifier. This is a
/// PIN-specific error and MUST NOT be conflated with session
/// termination — the session is still valid; only the supplied
/// PIN was wrong. UI should surface a PIN-specific message and
/// remain on whatever screen it is (usually /pin).
class PinInvalidException implements Exception {
  final String message;
  final int? attemptsLeft;
  const PinInvalidException({
    this.message = 'Incorrect PIN.',
    this.attemptsLeft,
  });
  @override
  String toString() =>
      'PinInvalidException(attemptsLeft: $attemptsLeft, message: $message)';
}

/// Any 401 the api_client cannot positively classify as a session
/// termination (one of the four coded session termination codes) or
/// as an `invalid_pin` PIN failure. **HTTP 401 alone is NOT proof
/// that the session expired** — this exception says exactly that:
/// "the server rejected the request on authorization grounds, but
/// nothing about that response proves the session died." Handlers
/// MUST NOT clear the session on this type; only the four explicit
/// codes may do that. The correct UX is a generic retryable
/// authorization error.
class ApiAuthorizationException implements Exception {
  final String message;
  final int statusCode;
  const ApiAuthorizationException({
    this.message = 'Request was rejected on authorization grounds.',
    this.statusCode = 401,
  });
  @override
  String toString() =>
      'ApiAuthorizationException(status: $statusCode, message: $message)';
}

/// Server returned 409 kdf_generation_stale — the client's declared
/// (pin_salt, kdf_iterations) did not match the vault row's current
/// values. Something rotated the DB under this session (a second
/// tab's /rotate-vault-kdf, a maintenance path, a browser cache that
/// served us a stale /vault-meta before we derived) so the client
/// key does not match what the server will derive. The response
/// body carries the authoritative CURRENT (pin_salt, kdf_iterations)
/// so the client can re-derive locally without another HTTP
/// round-trip and prompt the user to send again. NEVER surface as
/// "unlock session expired" — the session is fine, the KEY just
/// needs to be re-derived from the fresh salt.
class KdfGenerationStaleException implements Exception {
  final String? currentPinSalt;
  final int? currentKdfIterations;
  final String message;
  const KdfGenerationStaleException({
    required this.currentPinSalt,
    required this.currentKdfIterations,
    this.message =
        'The vault was updated in another tab or window. Please tap send again.',
  });

  factory KdfGenerationStaleException.fromResponseBody(String body) {
    String? salt;
    int? iter;
    String? msg;
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'];
        if (detail is Map) {
          salt = detail['current_pin_salt']?.toString();
          final rawIter = detail['current_kdf_iterations'];
          if (rawIter is int) {
            iter = rawIter;
          } else if (rawIter is num) {
            iter = rawIter.toInt();
          }
          final rawMsg = detail['message'];
          if (rawMsg is String && rawMsg.isNotEmpty) msg = rawMsg;
        }
      }
    } catch (_) {}
    return KdfGenerationStaleException(
      currentPinSalt: salt,
      currentKdfIterations: iter,
      message: msg ??
          'The vault was updated in another tab or window. '
              'Please tap send again.',
    );
  }

  @override
  String toString() =>
      'KdfGenerationStaleException(hasSalt: ${currentPinSalt != null}, '
      'iter: $currentKdfIterations)';
}

class ChunkedUploadNotAvailableException implements Exception {
  final String message;
  const ChunkedUploadNotAvailableException({
    this.message = 'Chunked uploads are not enabled on this server.',
  });
  @override
  String toString() => 'ChunkedUploadNotAvailableException(message: $message)';
}

class DeviceNotTrustedException implements Exception {
  final String message;
  final String? deviceId;

  final String status;

  const DeviceNotTrustedException({
    required this.message,
    this.deviceId,
    this.status = 'unknown',
  });

  factory DeviceNotTrustedException.fromResponseBody(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'];
        if (detail is Map) {
          return DeviceNotTrustedException(
            message:
                (detail['message'] ?? 'This device is not trusted.').toString(),
            deviceId: detail['device_id']?.toString(),
            status: (detail['status'] ?? 'unknown').toString(),
          );
        }
      }
    } catch (_) {}
    return const DeviceNotTrustedException(
      message: 'This device is not trusted.',
    );
  }

  @override
  String toString() =>
      'DeviceNotTrustedException(status: $status, message: $message)';
}

String? _apiClientDeviceId;
void setApiClientDeviceId(String id) {
  _apiClientDeviceId = id;

  final prefix = id.length <= 8 ? id : id.substring(0, 8);
  _vlog('device-id.setApiClient', {'id_prefix': prefix, 'len': id.length});
}

String? apiClientDeviceId() => _apiClientDeviceId;

class VaultAIClient {
  final String baseUrl;

  const VaultAIClient({required this.baseUrl});

  Map<String, String> _defaultHeaders({
    String? authToken,
    bool json = false,
    bool sse = false,
  }) {
    // Fail fast if a caller tries to attach a bearer after local
    // termination — no wire hit, no accidental retry with a token
    // the backend has already revoked. Public (unauthenticated)
    // calls remain usable.
    if (authToken != null &&
        authToken.isNotEmpty &&
        st.SessionTermination.instance.isTerminated) {
      throw const SessionTerminatedException(
        code: st.SessionTerminationCode.invalid,
        message: 'Your session is no longer valid. Sign in again.',
      );
    }
    final headers = <String, String>{};

    if (json) {
      headers['Content-Type'] = 'application/json';
    }

    if (sse) {
      headers['Accept'] = 'text/event-stream';
    }

    if (authToken != null && authToken.isNotEmpty) {
      headers['Authorization'] = 'Bearer $authToken';
    }

    final did = _apiClientDeviceId;
    if (did != null && did.isNotEmpty) {
      headers['X-Device-Id'] = did;
    }

    // 2026-07-22 modern-client identification. The build script
    // bakes the full 40-char commit SHA into main.dart.js via
    // --dart-define=APP_RELEASE=<sha>. Sending it on every request
    // lets the backend distinguish modern clients (which MUST
    // declare kdf_salt_used / kdf_iterations_used) from older
    // builds (which stay on the legacy pass-through). See
    // vault_kdf_generation.is_modern_client.
    const _appRelease =
        String.fromEnvironment('APP_RELEASE', defaultValue: 'dev');
    if (_appRelease.isNotEmpty && _appRelease != 'dev') {
      headers['X-App-Release'] = _appRelease;
    }

    return headers;
  }

  Future<Map<String, dynamic>> authSignup({
    required String vaultName,
    required String pin,
    required String confirmPin,
    String? displayUsername,
    required bool acknowledgedIrrecoverable,
  }) async {
    final uri = Uri.parse('$baseUrl/auth/signup');
    final headers = _defaultHeaders(json: true);
    final body = jsonEncode({
      'vault_name': vaultName,
      'pin': pin,
      'confirm_pin': confirmPin,
      if (displayUsername != null && displayUsername.isNotEmpty)
        'display_username': displayUsername,
      'acknowledged_irrecoverable': acknowledgedIrrecoverable,
    });

    _vlog('auth.signup.preflight', {
      'baseUrl': baseUrl,
      'url': uri.toString(),
      'body_len': body.length,
      'vault_name_len': vaultName.length,
      'pin_len': pin.length,
      'has_display_username':
          displayUsername != null && displayUsername.isNotEmpty,
      'acknowledged': acknowledgedIrrecoverable,
      'x_device_id_present': headers.containsKey('X-Device-Id'),
    });
    _vlogRequest('auth.signup', uri, headers);

    final http.Response response;
    try {
      response = await _runWithNetLog(
        'auth.signup',
        uri,
        () => http.post(uri, headers: headers, body: body),
      );
    } catch (e, st) {
      _vlog('auth.signup.network_failure', {
        'baseUrl': baseUrl,
        'url': uri.toString(),
        'error_type': e.runtimeType.toString(),
        'error': e.toString(),
        'stack_first_line': st.toString().split('\n').firstWhere(
              (_) => true,
              orElse: () => '-',
            ),
      });
      rethrow;
    }
    if (response.statusCode == 409) {
      String message = 'That vault name is already taken.';
      try {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          final detail = decoded['detail'];
          if (detail is Map<String, dynamic> && detail['message'] is String) {
            message = detail['message'] as String;
          }
        }
      } catch (_) {}
      throw VaultNameTakenException(message: message);
    }
    if (response.statusCode == 429) {
      throw _rateLimitedFromBody(response.body);
    }
    if (response.statusCode != 201 && response.statusCode != 200) {
      throw Exception(_formatBackendError(
        prefix: 'Signup failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid signup response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> authLogin({
    required String vaultName,
    required String pin,
  }) async {
    final uri = Uri.parse('$baseUrl/auth/login');
    final headers = _defaultHeaders(json: true);
    final body = jsonEncode({
      'vault_name': vaultName,
      'pin': pin,
    });

    _vlog('auth.login.preflight', {
      'baseUrl': baseUrl,
      'url': uri.toString(),
      'body_len': body.length,
      'vault_name_len': vaultName.length,
      'pin_len': pin.length,
      'x_device_id_present': headers.containsKey('X-Device-Id'),
    });
    _vlogRequest('auth.login', uri, headers);

    final http.Response response;
    try {
      response = await _runWithNetLog(
        'auth.login',
        uri,
        () => http.post(uri, headers: headers, body: body),
      );
    } catch (e, st) {
      _vlog('auth.login.network_failure', {
        'baseUrl': baseUrl,
        'url': uri.toString(),
        'error_type': e.runtimeType.toString(),
        'error': e.toString(),
        'stack_first_line': st.toString().split('\n').firstWhere(
              (_) => true,
              orElse: () => '-',
            ),
      });
      rethrow;
    }
    if (response.statusCode == 401) {
      throw const InvalidCredentialsException();
    }
    if (response.statusCode == 429) {
      throw _rateLimitedFromBody(response.body);
    }
    if (response.statusCode == 423) {
      String code = '';
      String message = '';
      String? lockedUntil;
      try {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          final detail = decoded['detail'];
          if (detail is Map<String, dynamic>) {
            code = (detail['code'] ?? '').toString();
            message = (detail['message'] ?? '').toString();
            lockedUntil = detail['locked_until']?.toString();
          }
        }
      } catch (_) {}
      if (code == 'vault_frozen') {
        throw VaultFrozenException(
            message: message.isEmpty ? 'Vault frozen' : message);
      }
      throw VaultLockedException(
        message: message.isEmpty ? 'Vault is temporarily locked' : message,
        lockedUntil: lockedUntil,
      );
    }
    if (response.statusCode != 200) {
      throw Exception(_formatBackendError(
        prefix: 'Login failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid login response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> authMe({required String authToken}) async {
    final uri = Uri.parse('$baseUrl/auth/me');
    final response = await _runWithNetLog(
      'auth.me',
      uri,
      () => http.get(uri, headers: _defaultHeaders(authToken: authToken)),
    );
    if (response.statusCode == 401) {
      throw const AuthExpiredException();
    }
    if (response.statusCode != 200) {
      throw Exception(_formatBackendError(
        prefix: 'auth/me failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid /auth/me response format');
    }
    return decoded;
  }

  /// Set (or clear, when [vaultName] is null) the caller's
  /// user-chosen vault name via ``PATCH /vault/name``.
  ///
  /// ``vault_name`` is the user-chosen identity for both signing
  /// into the vault AND for the vault AI's name — one string, one
  /// concept. The value the server persists is the returned
  /// ``vault_name`` field, AFTER server-side normalization
  /// (trim + whitespace-collapse + length cap 1..60 + reject
  /// control chars). Callers should update ``AppState.vaultName``
  /// and the persisted ``last_vault_name`` from what the server
  /// returned, not from what they originally submitted.
  ///
  /// 409 is surfaced as an [Exception] with the endpoint's
  /// "That vault name is already in use." message — vault_name
  /// is UNIQUE, so two accounts cannot share the same non-NULL
  /// value.
  Future<String?> setVaultName({
    required String authToken,
    required String? vaultName,
  }) async {
    final uri = Uri.parse('$baseUrl/vault/name');
    final response = await _runWithNetLog(
      'vault.name.set',
      uri,
      () => http.patch(
        uri,
        headers: _defaultHeaders(authToken: authToken),
        body: jsonEncode({'vault_name': vaultName}),
      ),
    );
    if (response.statusCode == 401) {
      throw const AuthExpiredException();
    }
    if (response.statusCode != 200) {
      throw Exception(_formatBackendError(
        prefix: 'vault/name failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid /vault/name response format');
    }
    final stored = decoded['vault_name'];
    return stored is String && stored.isNotEmpty ? stored : null;
  }

  Future<void> authLogout({required String authToken}) async {
    final uri = Uri.parse('$baseUrl/auth/logout');
    final response = await _runWithNetLog(
      'auth.logout',
      uri,
      () => http.post(uri, headers: _defaultHeaders(authToken: authToken)),
    );
    if (response.statusCode != 204 && response.statusCode != 200) {
      if (response.statusCode != 401) {
        throw Exception(_formatBackendError(
          prefix: 'Logout failed',
          statusCode: response.statusCode,
          responseBody: response.body,
        ));
      }
    }
  }

  Future<Map<String, dynamic>> getDeleteStatus({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/vault/delete/status');
    final response = await _runWithNetLog(
      'vault.delete.status',
      uri,
      () => http.get(uri, headers: _defaultHeaders(authToken: authToken)),
    );
    _throwIfAuthExpired(response.statusCode, response.body);
    _throwIfDeviceNotTrusted(response.statusCode, response.body);
    if (response.statusCode != 200) {
      throw Exception(_formatBackendError(
        prefix: 'Delete status failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Delete status: unexpected response shape');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> requestDeleteVault({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/vault/delete/request');
    final response = await _runWithNetLog(
      'vault.delete.request',
      uri,
      () => http.post(uri, headers: _defaultHeaders(authToken: authToken)),
    );
    _throwIfAuthExpired(response.statusCode, response.body);
    _throwIfDeviceNotTrusted(response.statusCode, response.body);
    if (response.statusCode != 200) {
      throw Exception(_formatBackendError(
        prefix: 'Delete request failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Delete request: unexpected response shape');
    }
    return decoded;
  }

  Future<void> confirmDeleteVault({
    required String authToken,
    required String requestToken,
    required String pin,
    required String confirmationPhrase,
  }) async {
    final uri = Uri.parse('$baseUrl/vault/delete/confirm');
    final body = jsonEncode({
      'request_token': requestToken,
      'pin': pin,
      'confirmation_phrase': confirmationPhrase,
    });
    final response = await _runWithNetLog(
      'vault.delete.confirm',
      uri,
      () => http.post(
        uri,
        headers: _defaultHeaders(authToken: authToken, json: true),
        body: body,
      ),
    );
    _throwIfAuthExpired(response.statusCode, response.body);
    _throwIfDeviceNotTrusted(response.statusCode, response.body);
    if (response.statusCode == 204 || response.statusCode == 200) {
      return;
    }
    throw Exception(_formatBackendError(
      prefix: 'Delete confirmation failed',
      statusCode: response.statusCode,
      responseBody: response.body,
    ));
  }

  Future<Map<String, dynamic>> registerDevice({
    required String authToken,
    required String deviceId,
    required String label,
    String? userAgentBrand,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/register');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'device_id': deviceId,
        'label': label,
        if (userAgentBrand != null && userAgentBrand.isNotEmpty)
          'user_agent_brand': userAgentBrand,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);

      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Register device failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid register-device response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> diagnoseTrust({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/diagnose-trust');
    final headers = _defaultHeaders(authToken: authToken);
    _vlogRequest('devices.diagnose_trust', uri, headers);
    final response = await _runWithNetLog(
      'devices.diagnose_trust',
      uri,
      () => http.get(uri, headers: headers),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Diagnose trust failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid diagnose-trust response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> listDevices({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/me');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List devices failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid list-devices response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> createStripeCheckoutSession({
    required String authToken,
    required int blockCount,
    String? successUrl,
    String? cancelUrl,
  }) async {
    final uri = Uri.parse('$baseUrl/billing/checkout-session');
    final headers = _defaultHeaders(authToken: authToken, json: true);
    final body = jsonEncode({
      'block_count': blockCount,
      if (successUrl != null) 'success_url': successUrl,
      if (cancelUrl != null) 'cancel_url': cancelUrl,
    });

    _vlog('billing.checkout_session.preflight', {
      'baseUrl': baseUrl,
      'url': uri.toString(),
      'block_count': blockCount,
      'body_len': body.length,
      'auth_token_present': authToken.isNotEmpty,
      'auth_token_len': authToken.length,
      'x_device_id_present': headers.containsKey('X-Device-Id'),
      'has_success_url': successUrl != null,
      'has_cancel_url': cancelUrl != null,
    });
    _vlogRequest('billing.checkout_session', uri, headers);

    final http.Response response;
    try {
      response = await _runWithNetLog(
        'billing.checkout_session',
        uri,
        () => http.post(uri, headers: headers, body: body),
      );
    } catch (e, st) {
      _vlog('billing.checkout_session.network_failure', {
        'baseUrl': baseUrl,
        'url': uri.toString(),
        'error_type': e.runtimeType.toString(),
        'error': e.toString(),
        'stack_first_line': st.toString().split('\n').firstWhere(
              (_) => true,
              orElse: () => '-',
            ),
      });
      rethrow;
    }

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw _safeBillingCheckoutError(response.body);
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid checkout-session response format');
    }
    return decoded;
  }

  BillingCheckoutException _safeBillingCheckoutError(String responseBody) {
    const fallback = "We couldn't start checkout. Please try again.";
    var code = 'checkout_failed';
    var message = fallback;

    try {
      final decoded = jsonDecode(responseBody);
      final detail = decoded is Map<String, dynamic> ? decoded['detail'] : null;
      if (detail is Map) {
        final parsedCode = detail['code']?.toString() ?? '';
        code = parsedCode.isEmpty ? code : parsedCode;

        // These are product-policy messages authored by SVaultAI. All
        // Stripe/configuration/internal failures deliberately use fallback.
        const safeProductCodes = {
          'no_change',
          'downgrade_not_supported',
          'enterprise_required',
        };
        if (safeProductCodes.contains(parsedCode)) {
          final parsedMessage = detail['message']?.toString().trim() ?? '';
          if (parsedMessage.isNotEmpty) message = parsedMessage;
        }
      }
    } catch (_) {
      // Malformed and non-JSON responses use the same safe fallback.
    }

    return BillingCheckoutException(code: code, message: message);
  }

  Future<Map<String, dynamic>> createStripePortalSession({
    required String authToken,
    String? returnUrl,
  }) async {
    final uri = Uri.parse('$baseUrl/billing/portal-session');
    final headers = _defaultHeaders(authToken: authToken, json: true);
    final body = jsonEncode({
      if (returnUrl != null) 'return_url': returnUrl,
    });
    _vlogRequest('billing.portal_session', uri, headers);
    final response = await _runWithNetLog(
      'billing.portal_session',
      uri,
      () => http.post(uri, headers: headers, body: body),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Portal session failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid portal-session response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getBillingMe({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/billing/me');
    final headers = _defaultHeaders(authToken: authToken);
    _vlogRequest('billing.me', uri, headers);
    final response = await _runWithNetLog(
      'billing.me',
      uri,
      () => http.get(uri, headers: headers),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Billing state failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid billing response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getBillingProviders({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/billing/providers');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Billing providers failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid billing-providers response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> verifyGooglePlayPurchase({
    required String authToken,
    required String productId,
    required String purchaseToken,
  }) async {
    final uri = Uri.parse('$baseUrl/billing/google-play/verify');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'product_id': productId,
        'purchase_token': purchaseToken,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Google Play verification failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid Google Play verification response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getSecurityCenterSummary({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/security-center/summary');
    final headers = _defaultHeaders(authToken: authToken);
    _vlogRequest('security_center.summary', uri, headers);
    final response = await _runWithNetLog(
      'security_center.summary',
      uri,
      () => http.get(uri, headers: headers),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Security Center summary failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid security-center response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getActiveExpiryAlerts({
    required String authToken,
    required String vaultName,
    String? expiryFilter,
    int limit = 100,
  }) async {
    final uri = Uri.parse('$baseUrl/expiry/active');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'limit': limit,
    };
    if (expiryFilter != null && expiryFilter.isNotEmpty) {
      body['expiry_filter'] = expiryFilter;
    }
    final headers = _defaultHeaders(authToken: authToken, json: true);
    _vlogRequest('expiry.active', uri, headers);
    final response = await _runWithNetLog(
      'expiry.active',
      uri,
      () => http.post(uri, headers: headers, body: jsonEncode(body)),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Expiry status failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid expiry response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getMemoryTimeline({
    required String authToken,
    required String vaultName,
    String? memoryType,
    int limit = 200,
  }) async {
    final uri = Uri.parse('$baseUrl/memory/timeline');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'limit': limit,
    };
    if (memoryType != null && memoryType.isNotEmpty) {
      body['memory_type'] = memoryType;
    }
    final headers = _defaultHeaders(authToken: authToken, json: true);
    _vlogRequest('memory.timeline', uri, headers);
    final response = await _runWithNetLog(
      'memory.timeline',
      uri,
      () => http.post(uri, headers: headers, body: jsonEncode(body)),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Memory timeline failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid memory timeline response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> listMemories({
    required String authToken,
    required String vaultName,
    required String pin,
    String? query,
    String? memoryType,
    int limit = 200,
  }) async {
    final uri = Uri.parse('$baseUrl/memory/list');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'pin': pin,
      'limit': limit,
      if (query != null && query.isNotEmpty) 'query': query,
      if (memoryType != null && memoryType.isNotEmpty)
        'memory_type': memoryType,
    };
    final headers = _defaultHeaders(authToken: authToken, json: true);
    _vlogRequest('memory.list', uri, headers);
    final response = await _runWithNetLog(
      'memory.list',
      uri,
      () => http.post(uri, headers: headers, body: jsonEncode(body)),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Memory list failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid memory list response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> createMemory({
    required String authToken,
    required String vaultName,
    required String pin,
    required Map<String, dynamic> data,
  }) async {
    return _postMemoryMutation(
      label: 'memory.create',
      path: '/memory/create',
      authToken: authToken,
      body: <String, dynamic>{
        ...data,
        'vault_name': vaultName,
        'pin': pin,
      },
      prefix: 'Memory save failed',
    );
  }

  Future<Map<String, dynamic>> updateMemory({
    required String authToken,
    required String vaultName,
    required String pin,
    required int id,
    required Map<String, dynamic> data,
  }) async {
    return _postMemoryMutation(
      label: 'memory.update',
      path: '/memory/update',
      authToken: authToken,
      body: <String, dynamic>{
        ...data,
        'id': id,
        'vault_name': vaultName,
        'pin': pin,
      },
      prefix: 'Memory update failed',
    );
  }

  Future<Map<String, dynamic>> deleteMemory({
    required String authToken,
    required String vaultName,
    required String pin,
    required int id,
  }) async {
    return _postMemoryMutation(
      label: 'memory.delete',
      path: '/memory/delete',
      authToken: authToken,
      body: <String, dynamic>{
        'id': id,
        'vault_name': vaultName,
        'pin': pin,
      },
      prefix: 'Memory delete failed',
    );
  }

  Future<Map<String, dynamic>> _postMemoryMutation({
    required String label,
    required String path,
    required String authToken,
    required Map<String, dynamic> body,
    required String prefix,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final headers = _defaultHeaders(authToken: authToken, json: true);
    _vlogRequest(label, uri, headers);
    final response = await _runWithNetLog(
      label,
      uri,
      () => http.post(uri, headers: headers, body: jsonEncode(body)),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: prefix,
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid memory response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> analyzePasswords({
    required String authToken,
    required String vaultName,
    required String pin,
    int? cursor,
    int? limit,
  }) async {
    final uri = Uri.parse('$baseUrl/security-center/analyze-passwords');
    final body = jsonEncode({
      'vault_name': vaultName,
      'pin': pin,
      if (cursor != null) 'cursor': cursor,
      if (limit != null) 'limit': limit,
    });
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: body,
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Analyze passwords failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid analyze-passwords response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> approveDevice({
    required String authToken,
    required String deviceId,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/approve');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'device_id': deviceId}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Approve device failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid approve response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> revokeDevice({
    required String authToken,
    required String deviceId,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/revoke');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'device_id': deviceId}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Revoke device failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid revoke response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> requestSelfApproval({
    required String authToken,
    required String vaultName,
    required String pin,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/request-self-approval');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'vault_name': vaultName, 'pin': pin}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Request self-approval failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid request-self-approval response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> finalizeSelfApproval({
    required String authToken,
    required String vaultName,
    required String pin,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/finalize-self-approval');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'vault_name': vaultName, 'pin': pin}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Finalize self-approval failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid finalize-self-approval response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> cancelSelfApproval({
    required String authToken,
    String? deviceId,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/cancel-self-approval');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        if (deviceId != null && deviceId.isNotEmpty) 'device_id': deviceId,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Cancel self-approval failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid cancel-self-approval response format');
    }
    return decoded;
  }

  Stream<String> chatStream({
    required String encryptedMessage,
    required String vaultName,
    required String pin,
    required String authToken,
    String? requestId,
    List<String>? uploadedFileIds,
    String? appLocale,
    Map<String, String>? selectionHint,
    // 2026-07-21 concurrency-safety fields. The client declares
    // the exact (pin_salt, kdf_iterations) it derived the vault
    // key against; the server compares these to the current DB row
    // BEFORE decryption and returns 409 kdf_generation_stale with
    // fresh salt+iter on mismatch (see vault_kdf_generation.py).
    // Optional so a request path that has no origin recorded (rare
    // — legacy code that stamped the cache directly without going
    // through deriveAndCacheKey) still works via the server's
    // legacy behavior of deriving with the current DB state.
    String? kdfSaltUsed,
    int? kdfIterationsUsed,
  }) async* {
    final uri = Uri.parse('$baseUrl/chat');

    final request = http.Request('POST', uri);
    final headers = _defaultHeaders(
      authToken: authToken,
      json: true,
      sse: true,
    );

    if (appLocale != null && appLocale.isNotEmpty) {
      final safe = appLocale.replaceAll(
        RegExp(r'[^a-zA-Z0-9\-]'),
        '',
      );
      if (safe.isNotEmpty && safe.length <= 16) {
        headers['X-App-Locale'] = safe;
      }
    }

    request.headers.addAll(headers);
    final safeRequestId = (requestId ?? '').replaceAll(
      RegExp(r'[^a-zA-Z0-9_.:-]'),
      '',
    );
    if (safeRequestId.isNotEmpty && safeRequestId.length <= 64) {
      request.headers['X-Chat-Request-Id'] = safeRequestId;
    }
    _vlogRequest('chat.stream', uri, headers);
    _vlog('chat.body', {
      'vault_name': vaultName,
      'encrypted_message_len': encryptedMessage.length,
      'pin_present': pin.isNotEmpty,
      'uploaded_file_count': (uploadedFileIds ?? const <String>[]).length,
      'app_locale_present': appLocale != null && appLocale.isNotEmpty,
    });

    request.body = jsonEncode(buildChatRequestBody(
      encryptedMessage: encryptedMessage,
      vaultName: vaultName,
      pin: pin,
      uploadedFileIds: uploadedFileIds,
      appLocale: appLocale,
      selectionHint: selectionHint,
      kdfSaltUsed: kdfSaltUsed,
      kdfIterationsUsed: kdfIterationsUsed,
    ));

    final response = await request.send();
    _vlog('chat.response', {
      'status': response.statusCode,
      'content_type': response.headers['content-type'] ?? '-',
    });

    if (response.statusCode != 200) {
      final errorBody = await response.stream.bytesToString();

      _vlog('chat.error', {
        'status': response.statusCode,
        'body': errorBody,
      });
      _throwIfAuthExpired(response.statusCode, errorBody);
      _throwIfDeviceNotTrusted(response.statusCode, errorBody);
      _throwIfLockOrFrozen(response.statusCode, errorBody);
      // 2026-07-21: 409 kdf_generation_stale MUST throw its
      // typed exception BEFORE the generic 400 InvalidVaultUnlock
      // check — a stale-generation request is a specific,
      // recoverable state (client re-derives from response salt +
      // user taps send), NOT a session-expired condition.
      _throwIfKdfGenerationStale(response.statusCode, errorBody);
      _throwIfInvalidVaultUnlock(response.statusCode, errorBody);
      throw Exception(_formatBackendError(
        prefix: 'Chat failed',
        statusCode: response.statusCode,
        responseBody: errorBody,
      ));
    }

    final lineStream =
        response.stream.transform(utf8.decoder).transform(const LineSplitter());

    await for (final line in lineStream) {
      final cleaned = _cleanSseLine(line);
      if (cleaned != null && cleaned.isNotEmpty) {
        yield cleaned;
      }
    }
  }

  Future<Map<String, dynamic>> checkVaultNameAvailable({
    required String vaultName,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/vault-name-available');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Vault name check failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid response format from backend');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> getMyVault({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/my-vault');

    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    );

    if (response.statusCode == 401) {
      _vlog('http.client_401', {
        'endpoint': uri.toString(),
        'authToken_empty': authToken.isEmpty,
        'authToken_len': authToken.length,
        'body': response.body,
      });
    }

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get my vault failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid my-vault response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> verifyPin({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/verify-pin');
    final headers = _defaultHeaders(authToken: authToken, json: true);

    _vlog('pin.verify.request', {
      'baseUrl': baseUrl,
      'url': uri.toString(),
      'vaultName': vaultName,
      'vaultNameLen': vaultName.length,
      'pinLen': pin.length,
      'auth_present': headers.containsKey('Authorization'),
      'x_device_id_present': headers.containsKey('X-Device-Id'),
    });

    final http.Response response;
    try {
      response = await http.post(
        uri,
        headers: headers,
        body: jsonEncode({
          'vault_name': vaultName,
          'pin': pin,
        }),
      );
    } catch (e, st) {
      _vlog('pin.verify.network_error', {
        'baseUrl': baseUrl,
        'url': uri.toString(),
        'error_type': e.runtimeType.toString(),
        'error': e.toString(),
        'stack_first_line': st
            .toString()
            .split('\n')
            .firstWhere((_) => true, orElse: () => '-'),
      });
      rethrow;
    }

    _vlog('pin.verify.response', {
      'baseUrl': baseUrl,
      'url': uri.toString(),
      'status': response.statusCode,
      'reason_phrase': response.reasonPhrase ?? '-',
      'body': response.body,
      'body_len': response.body.length,
    });

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Verify PIN failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid verify PIN response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> startDeepAnswer({
    required String pin,
    required String authToken,
    String intent = 'search_files_for_credentials',
    String query = '',
    String? resumeJobId,
  }) async {
    final uri = Uri.parse('$baseUrl/vault-analysis/deep-answer');
    final headers = _defaultHeaders(authToken: authToken, json: true);
    final body = jsonEncode({
      'pin': pin,
      'intent': intent,
      'query': query,
      if (resumeJobId != null && resumeJobId.isNotEmpty) 'job_id': resumeJobId,
    });
    final response = await http.post(uri, headers: headers, body: body);
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Deep Answer start failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid deep-answer start response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> pollDeepAnswerJob({
    required String pin,
    required String authToken,
    required String jobId,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/vault-analysis/deep-answer/$jobId/poll',
    );
    final headers = _defaultHeaders(authToken: authToken, json: true);
    final body = jsonEncode({'pin': pin});
    final response = await http.post(uri, headers: headers, body: body);
    if (response.statusCode == 404) {
      throw Exception('deep_answer_job_not_found');
    }
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Deep Answer poll failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid deep-answer poll response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getVaultMeta({
    required String vaultName,
    required String authToken,
  }) async {
    // 2026-07-21 cache-poisoning hardening for the "first chat forces
    // PIN" production incident. /vault-meta is authoritative for the
    // (pin_salt, kdf_iterations) the client derives the vault key
    // against; any cached response served after a server-side
    // rotation would leave the client on a stale salt and trip the
    // decrypt-side generic 400. The server-side fix (add /vault-meta
    // to SENSITIVE_PATH_PREFIXES in security_headers.py) already
    // pins the response as no-store, and the request-side pragmas
    // below defend against browser-heuristic caching + shared
    // caches that ignored the response header. Never send from a
    // cached copy.
    final headers = _defaultHeaders(authToken: authToken);
    headers['Cache-Control'] = 'no-cache, no-store';
    headers['Pragma'] = 'no-cache';

    final uri = Uri.parse(
      '$baseUrl/vault-meta'
      '?vault_name=${Uri.encodeQueryComponent(vaultName)}',
    );

    final response = await http.get(uri, headers: headers);

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get vault meta failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid vault meta response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> getOrCreateVaultMeta({
    required String vaultName,
    required String authToken,
    required String pin,
    bool acknowledgeOrphanWipe = false,
  }) async {
    final uri = Uri.parse('$baseUrl/get-or-create-vault-meta');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
        'acknowledge_orphan_wipe': acknowledgeOrphanWipe,
      }),
    );

    if (response.statusCode == 409 && _isOrphanConflict(response.body)) {
      throw OrphanDataException.fromResponseBody(response.body);
    }

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get/Create vault meta failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid vault meta response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> createBeneficiary({
    required String vaultName,
    required String pin,
    required String label,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/create'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
        'label': label,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Create beneficiary failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> linkBeneficiary({
    required String vaultName,
    required String pin,
    required String pairingCode,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/link'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
        'pairing_code': pairingCode,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Link beneficiary failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> listBeneficiaries({
    required String vaultName,
    required String pin,
    required String authToken,
    // 2026-07-22: optional client-generated request id. When set,
    // sent as X-Client-Request-Id so the ClientException-vs-200
    // distinction visible in nginx access logs can be correlated
    // with the specific failed invocation on the device. NOT used
    // for auth, NOT logged if unset. Bounded to 64 chars.
    String? clientRequestId,
  }) async {
    final headers = _defaultHeaders(authToken: authToken, json: true);
    if (clientRequestId != null && clientRequestId.isNotEmpty) {
      final cri = clientRequestId.length > 64
          ? clientRequestId.substring(0, 64)
          : clientRequestId;
      headers['X-Client-Request-Id'] = cri;
    }
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/list-mine'),
      headers: headers,
      body: jsonEncode({'vault_name': vaultName, 'pin': pin}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List beneficiaries failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// Best-effort ingest of a safe client-side diagnostic for an
  /// inheritance-scoped failure. NO ciphertext, NO wrapped-key
  /// contents, NO nonces, NO tokens, NO PINs may appear in
  /// ``body`` — the backend endpoint's Pydantic model rejects any
  /// field that isn't in its allowlist (see
  /// ``routes/inheritance_credential_routes.py::ClientDiagnosticRequest``).
  ///
  /// Fire-and-forget: a failure to POST the diagnostic never
  /// surfaces to the caller. The reveal / list-mine catch blocks
  /// depend on this to keep the UI-visible reference tag stable
  /// even when the network round-trip for the diagnostic itself
  /// fails.
  Future<void> postInheritanceClientDiagnostic({
    required Map<String, dynamic> body,
    required String authToken,
  }) async {
    try {
      await http.post(
        Uri.parse('$baseUrl/inheritance/client-diagnostic'),
        headers: _defaultHeaders(authToken: authToken, json: true),
        body: jsonEncode(body),
      );
    } catch (_) {
      // Intentionally swallowed. Diagnostic emission must never
      // itself become an error the user sees.
    }
  }

  Future<Map<String, dynamic>> listInheritances({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/list-inheritances'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'vault_name': vaultName, 'pin': pin}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List inheritances failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> claimTransfer({
    required int linkId,
    required String vaultName,
    required String pin,
    String? inheritedVaultName,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/claim-transfer'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'link_id': linkId,
        'vault_name': vaultName,
        'pin': pin,
        if (inheritedVaultName != null && inheritedVaultName.isNotEmpty)
          'inherited_vault_name': inheritedVaultName,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Claim transfer failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> listMyVaults({
    required String authToken,
  }) async {
    final response = await http.get(
      Uri.parse('$baseUrl/list-my-vaults'),
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List vaults failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> requestTransfer({
    required int linkId,
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/request-transfer'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'link_id': linkId,
        'vault_name': vaultName,
        'pin': pin,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Request transfer failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> cancelTransfer({
    required int linkId,
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/cancel-transfer'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'link_id': linkId,
        'vault_name': vaultName,
        'pin': pin,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Cancel transfer failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> deleteBeneficiary({
    required int linkId,
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/delete'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'link_id': linkId,
        'vault_name': vaultName,
        'pin': pin,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Delete beneficiary failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> listNotifications({
    required String authToken,
  }) async {
    final response = await http.get(
      Uri.parse('$baseUrl/notifications'),
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List notifications failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  // ------------------------------------------------------------------
  // Inheritance credential escrow (Phase 1).
  //
  // All five endpoints require a session bearer token. The server
  // never sees decrypted credential material.
  // ------------------------------------------------------------------

  Future<Map<String, dynamic>> getInheritanceBeneficiaryPubKey({
    required int linkId,
    required String authToken,
  }) async {
    final response = await http.get(
      Uri.parse('$baseUrl/inheritance/beneficiary/$linkId/pubkey'),
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get beneficiary pubkey failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> saveInheritanceCredentials({
    required Map<String, dynamic> body,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/inheritance/credentials/save'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      final detail = _parseInheritanceBackendDetail(response.body);
      throw InheritanceCredSaveException(
        statusCode: response.statusCode,
        backendCode: detail.$1,
        backendMessage: detail.$2,
      );
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> replaceInheritanceCredentials({
    required Map<String, dynamic> body,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/inheritance/credentials/replace'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      final detail = _parseInheritanceBackendDetail(response.body);
      throw InheritanceCredSaveException(
        statusCode: response.statusCode,
        backendCode: detail.$1,
        backendMessage: detail.$2,
      );
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// Extract ``(detail.code, detail.message)`` from the standard
  /// FastAPI error envelope produced by ``inheritance_http_error``:
  ///   ``{"detail": {"code": "INH-CRED-006", "message": "..."}}``
  /// Returns ``(null, null)`` when the body is not that shape.
  /// Scoped to the inheritance credential save/replace path — other
  /// endpoints keep their existing ``_formatBackendError``-based
  /// generic ``Exception`` throw, unchanged.
  (String?, String?) _parseInheritanceBackendDetail(String responseBody) {
    try {
      final decoded = jsonDecode(responseBody);
      if (decoded is Map<String, dynamic>) {
        final rawDetail = decoded['detail'];
        if (rawDetail is Map<String, dynamic>) {
          final code = rawDetail['code'];
          final msg = rawDetail['message'];
          return (
            code is String ? code : null,
            msg is String ? msg : null,
          );
        }
      }
    } catch (_) {}
    return (null, null);
  }

  Future<Map<String, dynamic>> deleteInheritanceCredentials({
    required int linkId,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/inheritance/credentials/delete'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'beneficiary_link_id': linkId}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      // 2026-07-22: mirror the save/replace path — surface the
      // backend's ``detail.code`` on the typed exception so the UI
      // can display the ACTUAL reference (e.g. INH-CRED-007 when
      // the caller tried to delete during cooldown_active) instead
      // of the hardcoded INH-CRED-006 the delete UI used to show
      // for every failure mode. The exception name reads "Save"
      // for historical reasons but now covers save/replace/delete
      // uniformly.
      final detail = _parseInheritanceBackendDetail(response.body);
      throw InheritanceCredSaveException(
        statusCode: response.statusCode,
        backendCode: detail.$1,
        backendMessage: detail.$2,
      );
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  // ------------------------------------------------------------------
  // Inheritance release flow (Phase 2).
  //
  // All endpoints require a session token; state transitions are
  // authoritative on the server. The server never returns decrypted
  // credential bytes — the beneficiary decrypts locally.
  // ------------------------------------------------------------------

  Future<Map<String, dynamic>> _inhReleasePost({
    required String path,
    required int linkId,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl$path'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'beneficiary_link_id': linkId}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Inheritance $path failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> requestInheritanceAccess({
    required int linkId,
    required String authToken,
  }) =>
      _inhReleasePost(
          path: '/inheritance/access/request',
          linkId: linkId,
          authToken: authToken);

  Future<Map<String, dynamic>> cancelInheritanceAccess({
    required int linkId,
    required String authToken,
  }) =>
      _inhReleasePost(
          path: '/inheritance/access/cancel',
          linkId: linkId,
          authToken: authToken);

  Future<Map<String, dynamic>> approveInheritanceAccess({
    required int linkId,
    required String authToken,
  }) =>
      _inhReleasePost(
          path: '/inheritance/access/approve',
          linkId: linkId,
          authToken: authToken);

  Future<Map<String, dynamic>> rejectInheritanceAccess({
    required int linkId,
    required String authToken,
  }) =>
      _inhReleasePost(
          path: '/inheritance/access/reject',
          linkId: linkId,
          authToken: authToken);

  Future<Map<String, dynamic>> claimInheritanceAccess({
    required int linkId,
    required String authToken,
  }) =>
      _inhReleasePost(
          path: '/inheritance/access/claim',
          linkId: linkId,
          authToken: authToken);

  Future<Map<String, dynamic>> getInheritanceAccessStatus({
    required int linkId,
    required String authToken,
  }) async {
    final response = await http.get(
      Uri.parse('$baseUrl/inheritance/access/status?link_id=$linkId'),
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Inheritance status failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> retrieveInheritanceCredentials({
    required int linkId,
    required String authToken,
  }) async {
    final response = await http.get(
      Uri.parse('$baseUrl/inheritance/credentials/retrieve?link_id=$linkId'),
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Retrieve inheritance credentials failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> authorizeInheritanceDevice({
    required int linkId,
    required String authToken,
  }) =>
      _inhReleasePost(
          path: '/inheritance/device/authorize',
          linkId: linkId,
          authToken: authToken);

  Future<Map<String, dynamic>> consumeInheritanceDeviceAuthorization({
    required String token,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/inheritance/device/consume'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'token': token}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Consume inheritance device authorization failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> markNotificationRead({
    int? notificationId,
    required String authToken,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/notifications/mark-read'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        if (notificationId != null) 'notification_id': notificationId,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Mark notification read failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> rotateVaultKdf({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/rotate-vault-kdf');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Rotate vault KDF failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid rotate vault KDF response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> wipeOrphanData({
    required String authToken,
    bool confirm = true,
  }) async {
    final uri = Uri.parse('$baseUrl/wipe-orphan-data');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'confirm': confirm}),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Wipe orphan data failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid wipe response format');
    }

    return decoded;
  }

  void _throwIfAuthExpired(int statusCode, String body) {
    if (statusCode != 401) return;
    // If the backend supplied a coded 401 (Step B.3), classify it
    // and throw the code-carrying exception. The api_client never
    // decides what user message to render — that's the
    // application's job — but it does canonicalise the code so
    // upper layers do not have to re-parse detail.
    final code = _extractSessionTerminationCode(body);
    if (code != null) {
      final exc = SessionTerminatedException(
        code: code,
        message: st.userMessageFor(code),
      );
      // Route through the singleton so a coded 401 always feeds the
      // central termination flow, even on paths that call the api
      // helper without going through the app's error boundary
      // (e.g. background pollers, SSE reconnect loops).
      // ignore: discarded_futures
      st.SessionTermination.instance.handle(code);
      throw exc;
    }
    // 2026-07-22: `invalid_pin` is NOT a session-termination code
    // — the session is valid; the caller's supplied PIN just
    // didn't match. Convert to the typed [PinInvalidException] so
    // the app's error boundary does NOT clear the session or
    // navigate to sign-in. The pre-fix code fell through to a
    // generic AuthExpiredException here, which is exactly what
    // signed the user out on the production /chat 401 that had
    // detail.code=invalid_pin.
    final invalidPin = _extractInvalidPinException(body);
    if (invalidPin != null) {
      throw invalidPin;
    }
    // 2026-07-22 (2) — REVIEW-GATE FIX. HTTP 401 alone is NOT
    // proof that the session died. Only the four explicit
    // session-termination codes above cause sign-out. Every other
    // 401 becomes a typed [ApiAuthorizationException] that
    // handleApiException surfaces as a generic retryable
    // authorization error — never clearing the session.
    //
    // The pre-review-gate behavior threw AuthExpiredException here,
    // which handleApiException converted into a full clearSession
    // + navigate-to-/unlock. That's exactly what signed the user
    // out on 401s that had no session-termination code (and it's
    // what let the /chat invalid_pin 401 masquerade as a session
    // expiry before the invalid_pin carve-out landed).
    throw ApiAuthorizationException(
      message: 'Request was rejected on authorization grounds.',
      statusCode: statusCode,
    );
  }

  /// Parse a 401 body of the shape
  /// `{"detail": {"code": "invalid_pin", "message": "...",
  ///              "attempts_left": <int>}}`.
  static PinInvalidException? _extractInvalidPinException(String body) {
    if (body.isEmpty) return null;
    try {
      final decoded = jsonDecode(body);
      if (decoded is! Map) return null;
      final detail = decoded['detail'];
      if (detail is! Map) return null;
      if (detail['code']?.toString() != 'invalid_pin') return null;
      int? attempts;
      final rawAttempts = detail['attempts_left'];
      if (rawAttempts is int) {
        attempts = rawAttempts;
      } else if (rawAttempts is num) {
        attempts = rawAttempts.toInt();
      }
      final msg = detail['message']?.toString() ?? 'Incorrect PIN.';
      return PinInvalidException(message: msg, attemptsLeft: attempts);
    } catch (_) {
      return null;
    }
  }

  /// Parse a FastAPI 401 body of the shape
  /// `{"detail": {"code": "<one_of_four>", "message": "..."}}`.
  /// Returns null if the body doesn't decode to that exact shape or
  /// the code isn't one of the four session codes. Never throws.
  static st.SessionTerminationCode? _extractSessionTerminationCode(
      String body) {
    if (body.isEmpty) return null;
    try {
      final decoded = jsonDecode(body);
      if (decoded is! Map) return null;
      final detail = decoded['detail'];
      if (detail is! Map) return null;
      final raw = detail['code'];
      if (raw is! String) return null;
      return st.parseSessionTerminationCode(raw);
    } catch (_) {
      return null;
    }
  }

  RateLimitedException _rateLimitedFromBody(String body) {
    int? resetIn;
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'];
        if (detail is Map<String, dynamic>) {
          final raw = detail['reset_in_seconds'];
          if (raw is num) resetIn = raw.toInt();
        }
      }
    } catch (_) {}
    return RateLimitedException(resetInSeconds: resetIn);
  }

  void _throwIfDeviceNotTrusted(int statusCode, String body) {
    if (statusCode != 403) return;
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final d = decoded['detail'];
        if (d is Map) {
          final code = d['code']?.toString();
          if (code == 'device_not_trusted' ||
              code == 'missing_device_id' ||
              code == 'device_revoked') {
            throw DeviceNotTrustedException.fromResponseBody(body);
          }
        }
      }
    } catch (e) {
      if (e is DeviceNotTrustedException) rethrow;
    }
  }

  void _throwIfInvalidVaultUnlock(int statusCode, String body) {
    if (statusCode != 400) return;
    if (!body.contains('Invalid PIN or corrupted data')) return;
    // 2026-07-22: what looks like "invalid unlock" is really a
    // crypto-context mismatch — the server derived a valid key
    // from the current DB (verify_pin_ok in the log), but the
    // client-supplied ciphertext did not decrypt under it. The
    // session and unlock are both fine; only the CIPHERTEXT is
    // out of sync with the server's derived key. Never map this
    // to sign-out or "Incorrect PIN" — see
    // [CryptoContextMismatchException] for the correct recovery.
    throw const CryptoContextMismatchException();
  }

  /// Server declared the client's (pin_salt, kdf_iterations) stale.
  /// Convert the 409 into a typed exception that carries the fresh
  /// salt/iter so the caller can re-derive without another HTTP
  /// round-trip. Semantically DISTINCT from
  /// `InvalidVaultUnlockException`: the session is intact, only the
  /// KDF version drifted. Callers MUST NOT force a re-PIN on this
  /// exception and MUST NOT auto-retry the request (per the 2026-
  /// 07-21 hardening review).
  void _throwIfKdfGenerationStale(int statusCode, String body) {
    if (statusCode != 409) return;
    if (!body.contains('kdf_generation_stale')) return;
    throw KdfGenerationStaleException.fromResponseBody(body);
  }

  void _throwIfLockOrFrozen(int statusCode, String body) {
    if (statusCode != 423) return;
    Map<String, dynamic>? detail;
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final d = decoded['detail'];
        if (d is Map<String, dynamic>) detail = d;
      }
    } catch (_) {
      return;
    }
    if (detail == null) return;
    final code = detail['code']?.toString();
    final message = (detail['message']?.toString() ?? '').trim();
    if (code == 'vault_frozen') {
      throw VaultFrozenException(
        message: message.isEmpty ? 'This vault has been frozen.' : message,
      );
    }
    if (code == 'pin_locked') {
      throw VaultLockedException(
        message: message.isEmpty
            ? 'Too many wrong PIN attempts. Try again later.'
            : message,
        lockedUntil: detail['locked_until']?.toString(),
        attemptsLeft: (detail['attempts_left'] as num?)?.toInt(),
      );
    }
  }

  bool _isOrphanConflict(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'];
        if (detail is Map<String, dynamic>) {
          return detail['code'] == 'orphan_data_exists';
        }
      }
    } catch (_) {}
    return false;
  }

  Future<Map<String, dynamic>> listVaultLogins({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/list-login-names');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List logins failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid list logins response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> listVaultSecureItems({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/list-secure-items');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List secure items failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid list secure items response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> getVaultSecureItem({
    required String vaultName,
    required String service,
    required String itemType,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/get-secure-item');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'service': service,
        'item_type': itemType,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get secure item failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid get secure item response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> saveCryptoWalletProfile({
    required String pin,
    required String authToken,
    required String asset,
    required String walletLabel,
    required String publicAddress,
    String? network,
    String? note,
    String? title,
  }) async {
    if (zk_mvk_store.ZkActiveMvk.current() != null) {
      final zkResp = await tryZkVaultItemCiphertextUpsert(
        baseUrl: baseUrl,
        authToken: authToken,
        itemType: 'wallet_account',
        service: 'crypto:$asset',
        payload: <String, dynamic>{
          'asset': asset,
          'walletLabel': walletLabel,
          'publicAddress': publicAddress,
          if (network != null && network.isNotEmpty) 'network': network,
          if (note != null && note.isNotEmpty) 'note': note,
          if (title != null && title.isNotEmpty) 'title': title,
        },
      );
      if (zkResp != null) return zkResp;
    }
    final uri = Uri.parse('$baseUrl/crypto/save-wallet-profile');
    final body = <String, dynamic>{
      'pin': pin,
      'asset': asset,
      'walletLabel': walletLabel,
      'publicAddress': publicAddress,
    };
    if (network != null && network.isNotEmpty) body['network'] = network;
    if (note != null && note.isNotEmpty) body['note'] = note;
    if (title != null && title.isNotEmpty) body['title'] = title;

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Save crypto wallet failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid save crypto wallet response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> saveCryptoSensitiveBackup({
    required String pin,
    required String authToken,
    required String walletLabel,
    required String secretType,
    required String secretValue,
    required bool warningConfirmed,
    String? asset,
    String? network,
    String? note,
    String? title,
  }) async {
    const walletBackupV2WriteEnabled = bool.fromEnvironment(
        'WALLET_BACKUP_V2_WRITE_ENABLED',
        defaultValue: false);
    if (walletBackupV2WriteEnabled) {
      final repository =
          WalletBackupV2Repository.current(api: this, authToken: authToken);
      if (repository == null) {
        throw StateError('wallet_backup_v2_requires_active_mvk');
      }
      final backupRecordId = await repository.create(
          secretType: secretType, secretPlaintext: secretValue);
      return <String, dynamic>{
        'status': 'saved',
        'schema': 'wallet_backup_v2',
        'backup_record_id': backupRecordId,
        'category': secretType,
      };
    }
    if (zk_mvk_store.ZkActiveMvk.current() != null) {
      final zkResp = await tryZkVaultItemCiphertextUpsert(
        baseUrl: baseUrl,
        authToken: authToken,
        itemType: 'crypto_sensitive_backup',
        service: 'crypto:${asset ?? "unknown"}',
        payload: <String, dynamic>{
          'walletLabel': walletLabel,
          'secretType': secretType,
          'secretValue': secretValue,
          'warningConfirmed': warningConfirmed,
          if (asset != null && asset.isNotEmpty) 'asset': asset,
          if (network != null && network.isNotEmpty) 'network': network,
          if (note != null && note.isNotEmpty) 'note': note,
          if (title != null && title.isNotEmpty) 'title': title,
        },
      );
      if (zkResp != null) return zkResp;
    }
    final uri = Uri.parse('$baseUrl/crypto/save-sensitive-backup');
    final body = <String, dynamic>{
      'pin': pin,
      'walletLabel': walletLabel,
      'secretType': secretType,
      'secretValue': secretValue,
      'warningConfirmed': warningConfirmed,
    };
    if (asset != null && asset.isNotEmpty) body['asset'] = asset;
    if (network != null && network.isNotEmpty) body['network'] = network;
    if (note != null && note.isNotEmpty) body['note'] = note;
    if (title != null && title.isNotEmpty) body['title'] = title;

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Save crypto sensitive backup failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid save crypto backup response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> saveCryptoNote({
    required String pin,
    required String authToken,
    required String title,
    required String note,
    required String noteType,
    String? asset,
    String? network,
    String? walletLabel,
    String? txHash,
    String? amountText,
    String? dateText,
  }) async {
    if (zk_mvk_store.ZkActiveMvk.current() != null) {
      final zkResp = await tryZkVaultItemCiphertextUpsert(
        baseUrl: baseUrl,
        authToken: authToken,
        itemType: 'crypto_note',
        service: 'crypto:${asset ?? "note"}',
        payload: <String, dynamic>{
          'title': title,
          'note': note,
          'noteType': noteType,
          if (asset != null && asset.isNotEmpty) 'asset': asset,
          if (network != null && network.isNotEmpty) 'network': network,
          if (walletLabel != null && walletLabel.isNotEmpty)
            'walletLabel': walletLabel,
          if (txHash != null && txHash.isNotEmpty) 'txHash': txHash,
          if (amountText != null && amountText.isNotEmpty)
            'amountText': amountText,
          if (dateText != null && dateText.isNotEmpty) 'dateText': dateText,
        },
      );
      if (zkResp != null) return zkResp;
    }
    final uri = Uri.parse('$baseUrl/crypto/save-note');
    final body = <String, dynamic>{
      'pin': pin,
      'title': title,
      'note': note,
      'noteType': noteType,
    };
    if (asset != null && asset.isNotEmpty) body['asset'] = asset;
    if (network != null && network.isNotEmpty) body['network'] = network;
    if (walletLabel != null && walletLabel.isNotEmpty)
      body['walletLabel'] = walletLabel;
    if (txHash != null && txHash.isNotEmpty) body['txHash'] = txHash;
    if (amountText != null && amountText.isNotEmpty)
      body['amountText'] = amountText;
    if (dateText != null && dateText.isNotEmpty) body['dateText'] = dateText;

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Save crypto note failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid save crypto note response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> revealCryptoSensitiveBackup({
    required String pin,
    required String authToken,
    required String service,
    required String itemType,
  }) async {
    const walletBackupV2ReadEnabled = bool.fromEnvironment(
        'WALLET_BACKUP_V2_READ_ENABLED',
        defaultValue: false);
    if (walletBackupV2ReadEnabled) {
      final repository =
          WalletBackupV2Repository.current(api: this, authToken: authToken);
      if (repository == null) {
        throw StateError('wallet_backup_v2_requires_active_mvk');
      }
      // In V2 the service field carries only the opaque record identity.
      // A malformed V2 envelope throws locally and never falls back to V1.
      final envelope = await repository.read(service);
      final secretValue = await repository.decrypt(envelope);
      return <String, dynamic>{
        'status': 'ok',
        'schema': 'wallet_backup_v2',
        'secretType': envelope.secretType,
        'secretValue': secretValue,
      };
    }
    final uri = Uri.parse(
      '$baseUrl/crypto/reveal-sensitive-backup',
    );
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'pin': pin,
        'service': service,
        'item_type': itemType,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);

      throw Exception(_formatBackendError(
        prefix: 'Reveal sensitive backup failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid reveal sensitive backup response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> uploadVaultFile({
    required String vaultName,
    required String pin,
    required String authToken,
    required String filename,
    required Uint8List fileBytes,
    String? contentType,
    String? accompanyingText,
    bool isBatchUpload = false,
    String? relativePath,
    String? importId,
    String? contentSha256,
    String? duplicateAction,
  }) async {
    final uri = Uri.parse('$baseUrl/upload-file');

    final request = http.MultipartRequest('POST', uri);
    request.headers.addAll(
      _defaultHeaders(authToken: authToken),
    );

    request.fields['vault_name'] = vaultName;
    request.fields['pin'] = pin;

    if (contentType != null && contentType.isNotEmpty) {
      request.fields['content_type'] = contentType;
    }
    if (isBatchUpload) {
      request.fields['is_batch_upload'] = 'true';
    }
    if (relativePath != null && relativePath.isNotEmpty) {
      request.fields['relative_path'] = relativePath;
    }
    if (importId != null && importId.isNotEmpty) {
      request.fields['import_id'] = importId;
    }
    if (contentSha256 != null && contentSha256.isNotEmpty) {
      request.fields['content_sha256'] = contentSha256;
    }
    if (duplicateAction != null && duplicateAction.isNotEmpty) {
      request.fields['duplicate_action'] = duplicateAction;
    }

    // ZK ciphertext-first mode. Encrypt filename + content_type
    // BEFORE the multipart POST and add them as form fields. The
    // server INSERTs the row with legacy readable columns NULL
    // from the initial write — no cleanup dependency.
    final inlineMvk = zk_mvk_store.ZkActiveMvk.current();
    if (inlineMvk != null) {
      final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(inlineMvk);
      final metaKey = await hierarchy.metadataKey();
      final fnCt = await vault_key_hierarchy.aesGcmWrap(
        metaKey,
        utf8.encode(filename),
      );
      request.fields['filename_ciphertext'] =
          vault_key_hierarchy.b64urlEncode(fnCt);
      if (contentType != null && contentType.isNotEmpty) {
        final ctCt = await vault_key_hierarchy.aesGcmWrap(
          metaKey,
          utf8.encode(contentType),
        );
        request.fields['content_type_ciphertext'] =
            vault_key_hierarchy.b64urlEncode(ctCt);
      }
    }

    if (accompanyingText != null && accompanyingText.isNotEmpty) {
      request.fields['accompanying_text'] = accompanyingText;
    }

    request.files.add(
      http.MultipartFile.fromBytes(
        'file',
        fileBytes,
        filename: filename,
      ),
    );

    final response = await request.send();
    final responseBody = await response.stream.bytesToString();

    if (response.statusCode == 413) {
      throw _parseStorageLimitException(responseBody);
    }

    if (response.statusCode == 409) {
      Map<String, dynamic>? body;
      try {
        final decoded = jsonDecode(responseBody);
        if (decoded is Map<String, dynamic>) body = decoded;
      } catch (_) {}
      final detail = body?['detail'];
      if (detail is Map<String, dynamic>) {
        final code = detail['code'] as String?;
        if (code == 'duplicate_found') {
          throw DuplicateFoundUploadException(detail);
        }
        if (code == 'name_conflict') {
          throw NameConflictUploadException(detail);
        }
      }

      throw Exception(_formatBackendError(
        prefix: 'File upload failed',
        statusCode: response.statusCode,
        responseBody: responseBody,
      ));
    }

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, responseBody);
      _throwIfDeviceNotTrusted(response.statusCode, responseBody);
      _throwIfLockOrFrozen(response.statusCode, responseBody);
      throw Exception(_formatBackendError(
        prefix: 'File upload failed',
        statusCode: response.statusCode,
        responseBody: responseBody,
      ));
    }

    final decoded = jsonDecode(responseBody);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid upload response format from backend');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> listFolder({
    required String authToken,
    String? path,
  }) async {
    final qs = (path != null && path.isNotEmpty)
        ? '?path=${Uri.encodeQueryComponent(path)}'
        : '';
    final uri = Uri.parse('$baseUrl/folders$qs');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List folder failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid /folders response format');
    }
    await _decryptUploadedFileMetadataForActiveZkVault(decoded);
    return decoded;
  }

  Future<Map<String, dynamic>> startImport({
    required String vaultName,
    required String pin,
    required String authToken,
    String? rootFolderName,
    int totalFiles = 0,
    int totalBytesPlanned = 0,
  }) async {
    final uri = Uri.parse('$baseUrl/imports/start');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'pin': pin,
      'total_files': totalFiles,
      'total_bytes_planned': totalBytesPlanned,
      if (rootFolderName != null && rootFolderName.isNotEmpty)
        'root_folder_name': rootFolderName,
    };

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );

    if (response.statusCode == 413) {
      throw _parseStorageLimitException(response.body);
    }
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Start import failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid /imports/start response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getImport({
    required String authToken,
    required String importId,
  }) async {
    final uri = Uri.parse('$baseUrl/imports/$importId');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get import failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid /imports/{id} response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> cancelImport({
    required String vaultName,
    required String pin,
    required String authToken,
    required String importId,
  }) async {
    final uri = Uri.parse('$baseUrl/imports/$importId/cancel');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'pin': pin,
    };

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Cancel import failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid /imports/{id}/cancel response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> completeImport({
    required String vaultName,
    required String pin,
    required String authToken,
    required String importId,
    int failedCountDelta = 0,
    int skippedDuplicateCountDelta = 0,
  }) async {
    final uri = Uri.parse('$baseUrl/imports/$importId/complete');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'pin': pin,
      'failed_count_delta': failedCountDelta,
      'skipped_duplicate_count_delta': skippedDuplicateCountDelta,
    };

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Complete import failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid /imports/{id}/complete response format');
    }
    return decoded;
  }

  StorageLimitExceededException _parseStorageLimitException(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'];
        if (detail is Map<String, dynamic>) {
          return StorageLimitExceededException(
            message: detail['message']?.toString() ??
                'Not enough vault storage for this import.',
            usedBytes: (detail['used_bytes'] as num?)?.toInt(),
            limitBytes: (detail['limit_bytes'] as num?)?.toInt(),
            projectedBytes: (detail['projected_bytes'] as num?)?.toInt(),
          );
        }
      }
    } catch (_) {}
    return const StorageLimitExceededException(
      message: 'Not enough vault storage for this import.',
    );
  }

  Future<Map<String, dynamic>> nameVaultFile({
    required String vaultName,
    required String fileId,
    required String savedName,
    required String pin,
    required String authToken,
  }) async {
    // ZK ciphertext-first fast path. Encrypts saved_name under the
    // vault's metadata subkey and POSTs to
    // /vault/ciphertext/uploaded-files so no readable saved_name
    // touches persistent server storage for an adopted vault.
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk != null) {
      final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(mvk);
      final metaKey = await hierarchy.metadataKey();
      final savedNameCt = await vault_key_hierarchy.aesGcmWrap(
        metaKey,
        utf8.encode(savedName),
      );
      final zkUri = Uri.parse('$baseUrl/vault/ciphertext/uploaded-files');
      final zkResp = await http.post(
        zkUri,
        headers: <String, String>{
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $authToken',
        },
        body: jsonEncode(<String, dynamic>{
          'file_id': fileId,
          'saved_name_ciphertext':
              vault_key_hierarchy.b64urlEncode(savedNameCt),
        }),
      );
      if (zkResp.statusCode != 200) {
        throw Exception(
          'ZK ciphertext saved_name write failed '
          '(${zkResp.statusCode})',
        );
      }
      final decoded = jsonDecode(zkResp.body);
      if (decoded is Map<String, dynamic>) return decoded;
      throw Exception('Invalid /vault/ciphertext/uploaded-files response');
    }
    final uri = Uri.parse('$baseUrl/name-file');

    final request = http.MultipartRequest('POST', uri);
    request.headers.addAll(
      _defaultHeaders(authToken: authToken),
    );

    request.fields['vault_name'] = vaultName;
    request.fields['file_id'] = fileId;
    request.fields['saved_name'] = savedName;
    request.fields['pin'] = pin;

    final response = await request.send();
    final responseBody = await response.stream.bytesToString();

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, responseBody);
      _throwIfDeviceNotTrusted(response.statusCode, responseBody);
      _throwIfLockOrFrozen(response.statusCode, responseBody);
      throw Exception(_formatBackendError(
        prefix: 'Name file failed',
        statusCode: response.statusCode,
        responseBody: responseBody,
      ));
    }

    final decoded = jsonDecode(responseBody);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid name file response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> listVaultFiles({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/list-files');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List files failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid list files response format');
    }

    await _decryptUploadedFileMetadataForActiveZkVault(decoded);
    return decoded;
  }

  Future<void> _decryptUploadedFileMetadataForActiveZkVault(
    Map<String, dynamic> decoded,
  ) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) return;
    final files = decoded['files'];
    if (files is! List) return;
    final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(mvk);
    final metaKey = await hierarchy.metadataKey();

    Future<String?> decryptField(Object? value) async {
      if (value is! String || value.isEmpty) return null;
      try {
        final plaintext = await vault_key_hierarchy.aesGcmUnwrap(
          metaKey,
          vault_key_hierarchy.b64urlDecode(value),
        );
        return utf8.decode(plaintext);
      } catch (_) {
        return null;
      }
    }

    for (var i = 0; i < files.length; i++) {
      final item = files[i];
      if (item is! Map) continue;
      final map =
          item is Map<String, dynamic> ? item : Map<String, dynamic>.from(item);
      if (!identical(map, item)) {
        files[i] = map;
      }
      Future<void> fill(String plain, String encrypted) async {
        final decrypted = await decryptField(map[encrypted]);
        if (decrypted != null && decrypted.trim().isNotEmpty) {
          map[plain] = decrypted;
        }
      }

      await fill('file_name', 'file_name_ciphertext');
      await fill('saved_name', 'saved_name_ciphertext');
      if ((map['saved_name']?.toString().trim().isNotEmpty ?? false) &&
          map['saved_name_ciphertext'] is String) {
        map['needs_naming'] = false;
      }
      await fill('content_type', 'content_type_ciphertext');
      await fill('detected_type', 'detected_type_ciphertext');
      await fill('detected_service', 'detected_service_ciphertext');
      await fill('asset_type', 'asset_type_ciphertext');
    }
  }

  Future<Map<String, dynamic>> getVaultStats({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/vault-stats');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Vault stats failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid vault stats response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> downloadVaultFile({
    required String vaultName,
    required String fileId,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/download-file');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'file_id': fileId,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Download file failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid download file response format');
    }

    return decoded;
  }

  Future<Map<String, dynamic>> initChunkedUpload({
    required String vaultName,
    required String pin,
    required String authToken,
    required String filename,
    required String? contentType,
    required int totalBytes,
    required int chunkSize,
    String? contentSha256,
    bool isBatchUpload = false,
    String? relativePath,
    String? importId,
  }) async {
    final uri = Uri.parse('$baseUrl/upload-file/init');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'pin': pin,
      'filename': filename,
      'content_type': contentType,
      'total_bytes': totalBytes,
      'chunk_size': chunkSize,
      if (contentSha256 != null) 'content_sha256': contentSha256,
      if (isBatchUpload) 'is_batch_upload': true,
      if (relativePath != null && relativePath.isNotEmpty)
        'relative_path': relativePath,
      if (importId != null && importId.isNotEmpty) 'import_id': importId,
    };

    // ZK ciphertext-first mode: encrypt filename + content_type
    // BEFORE the initial request. The backend INSERTs the row with
    // the *_ciphertext columns populated and the legacy plaintext
    // columns as NULL from the start. No transient plaintext
    // persistence, no post-write cleanup needed.
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk != null) {
      final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(mvk);
      final metaKey = await hierarchy.metadataKey();
      final fnCt = await vault_key_hierarchy.aesGcmWrap(
        metaKey,
        utf8.encode(filename),
      );
      body['filename_ciphertext'] = vault_key_hierarchy.b64urlEncode(fnCt);
      if (contentType != null && contentType.isNotEmpty) {
        final ctCt = await vault_key_hierarchy.aesGcmWrap(
          metaKey,
          utf8.encode(contentType),
        );
        body['content_type_ciphertext'] =
            vault_key_hierarchy.b64urlEncode(ctCt);
      }
    }

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );

    if (response.statusCode == 404) {
      throw const ChunkedUploadNotAvailableException();
    }
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Init chunked upload failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid init response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> uploadChunk({
    required String authToken,
    required String fileId,
    required int chunkIndex,
    required String uploadToken,
    required Uint8List chunkFrameBytes,
  }) async {
    final uri = Uri.parse('$baseUrl/upload-file/chunk');

    final request = http.MultipartRequest('POST', uri);
    request.headers.addAll(_defaultHeaders(authToken: authToken));
    request.fields['file_id'] = fileId;
    request.fields['chunk_index'] = chunkIndex.toString();
    request.fields['upload_token'] = uploadToken;
    request.files.add(http.MultipartFile.fromBytes(
      'chunk',
      chunkFrameBytes,
      filename: 'chunk_$chunkIndex.bin',
    ));

    final response = await request.send();
    final responseBody = await response.stream.bytesToString();

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, responseBody);
      _throwIfDeviceNotTrusted(response.statusCode, responseBody);
      _throwIfLockOrFrozen(response.statusCode, responseBody);
      throw Exception(_formatBackendError(
        prefix: 'Upload chunk failed',
        statusCode: response.statusCode,
        responseBody: responseBody,
      ));
    }

    final decoded = jsonDecode(responseBody);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid upload-chunk response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> finalizeChunkedUpload({
    required String authToken,
    required String vaultName,
    required String pin,
    required String fileId,
  }) async {
    final uri = Uri.parse('$baseUrl/upload-file/finalize');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
        'file_id': fileId,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Finalize chunked upload failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid finalize response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> abortChunkedUpload({
    required String authToken,
    required String vaultName,
    required String pin,
    required String fileId,
  }) async {
    final uri = Uri.parse('$baseUrl/upload-file/abort');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
        'file_id': fileId,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Abort chunked upload failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid abort response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getDownloadManifest({
    required String authToken,
    required String vaultName,
    required String pin,
    required String fileId,
  }) async {
    final uri = Uri.parse('$baseUrl/download-file/manifest');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
        'file_id': fileId,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get download manifest failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid manifest response format');
    }
    return decoded;
  }

  Future<Uint8List> downloadChunk({
    required String authToken,
    required String fileId,
    required int chunkIndex,
    required String downloadToken,
  }) async {
    final uri = Uri.parse('$baseUrl/download-file/chunk');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'file_id': fileId,
        'chunk_index': chunkIndex,
        'download_token': downloadToken,
      }),
    );

    if (response.statusCode != 200) {
      final body = utf8.decode(response.bodyBytes, allowMalformed: true);
      _throwIfAuthExpired(response.statusCode, body);
      _throwIfDeviceNotTrusted(response.statusCode, body);
      _throwIfLockOrFrozen(response.statusCode, body);
      throw Exception(_formatBackendError(
        prefix: 'Download chunk failed',
        statusCode: response.statusCode,
        responseBody: body,
      ));
    }

    return response.bodyBytes;
  }

  Future<Map<String, dynamic>> listFullLogins({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/manage/logins-full');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List full logins failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateLogin({
    required String vaultName,
    required String pin,
    required String oldService,
    required String newService,
    String? username,
    String? email,
    String? password,
    String? pinValue,
    String? note,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/manage/login');

    final response = await http.patch(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'pin': pin,
        'old_service': oldService,
        'new_service': newService,
        'username': username,
        'email': email,
        'password': password,
        'pin_value': pinValue,
        'note': note,
      }..removeWhere((key, value) => value == null)),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Update login failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> deleteLogin({
    required String vaultName,
    required String service,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/manage/login/delete');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'service': service,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Delete login failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateVaultSecureItem({
    required String vaultName,
    required String oldService,
    required String itemType,
    required String pin,
    required String authToken,
    String? newService,
    Map<String, dynamic>? fields,
  }) async {
    // ZK ciphertext-first fast path. When an unlocked MVK is active
    // (i.e. this is a ZK/adopted vault), the item is written to
    // /vault/ciphertext/vault-items instead of /update-secure-item —
    // no readable item_type / service / payload leaves the client.
    if (zk_mvk_store.ZkActiveMvk.current() != null) {
      final zkResp = await tryZkVaultItemCiphertextUpsert(
        baseUrl: baseUrl,
        authToken: authToken,
        itemType: itemType,
        service: (newService != null && newService.trim().isNotEmpty)
            ? newService.trim()
            : oldService,
        payload: <String, dynamic>{
          'old_service': oldService,
          if (newService != null && newService.trim().isNotEmpty)
            'new_service': newService.trim(),
          if (fields != null) 'fields': fields,
        },
      );
      if (zkResp != null) {
        return zkResp;
      }
    }

    final uri = Uri.parse('$baseUrl/update-secure-item');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'old_service': oldService,
      'item_type': itemType,
      'pin': pin,
    };
    if (newService != null && newService.trim().isNotEmpty) {
      body['new_service'] = newService.trim();
    }
    if (fields != null && fields.isNotEmpty) {
      body['fields'] = fields;
    }

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Could not update saved item',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// ZK ciphertext-first vault-item upsert helper. Called by
  /// updateVaultSecureItem / saveCryptoWalletProfile / etc when an
  /// unlocked MVK is available. Encrypts item_type + service + full
  /// payload JSON under the vault's metadata subkey and POSTs to
  /// /vault/ciphertext/vault-items. Returns null when no MVK is
  /// active (caller falls through to legacy plaintext endpoint).
  ///
  /// This function is intentionally file-scope (not a method on
  /// VaultAIClient) so it can be reused by any write path that
  /// converges on a `(item_type, service, payload_json)` triple.
  /// ZK ciphertext-first AI-memory finalize.
  ///
  /// Called by the chat SSE handler when the backend emits a
  /// `<<VAULTAI_MEMORY_PROPOSAL>>{json}<<END>>` sentinel. Derives
  /// `memoryKey` + `memoryLookupKey` from the active MVK, encrypts
  /// the full memory proposal payload, computes the keyed lookup
  /// hash locally, and POSTs to /vault/ciphertext/vault-ai-memory.
  /// The backend accepts only ciphertext + hash; the user's memory
  /// key/value never touches server storage in readable form.
  ///
  /// Returns true iff the finalize POST succeeded. False (with the
  /// exception swallowed by the caller) means the memory was NOT
  /// saved — correct privacy tradeoff on network/crypto failure.
  Future<bool> tryZkFinalizeMemoryProposal({
    required String baseUrl,
    required String authToken,
    required String memoryType,
    required String memoryKey,
    required String memoryValue,
    String? memoryEventDate,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) return false;
    final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(mvk);
    final memoryK = await hierarchy.memoryKey();
    final memoryLookup = await hierarchy.memoryLookupKey();

    final payloadJson = jsonEncode(<String, dynamic>{
      'memory_key': memoryKey,
      'memory_value': memoryValue,
      if (memoryEventDate != null && memoryEventDate.isNotEmpty)
        'memory_event_date': memoryEventDate,
    });
    final payloadCt = await vault_key_hierarchy.aesGcmWrap(
      memoryK,
      utf8.encode(payloadJson),
    );
    final lookupHash = await vault_key_hierarchy.keyedLookupHash(
      memoryLookup,
      utf8.encode(memoryKey),
    );

    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-ai-memory');
    final resp = await http.post(
      uri,
      headers: <String, String>{
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $authToken',
      },
      body: jsonEncode(<String, dynamic>{
        'memory_type': memoryType,
        'memory_lookup_hash': vault_key_hierarchy.b64urlEncode(lookupHash),
        'payload_ciphertext': vault_key_hierarchy.b64urlEncode(payloadCt),
      }),
    );
    return resp.statusCode == 200;
  }

  /// Reads only opaque MEMORY_V2 envelopes. Plaintext memory columns are
  /// never requested; callers must decrypt locally with the active MVK.
  Future<List<Map<String, dynamic>>> listZkMemoryEnvelopes({
    required String baseUrl,
    required String authToken,
    String? lookupHash,
  }) async {
    final query = lookupHash == null
        ? ''
        : '?memory_lookup_hash=${Uri.encodeQueryComponent(lookupHash)}';
    final resp = await http.get(
      Uri.parse('$baseUrl/vault/ciphertext/vault-ai-memory$query'),
      headers: <String, String>{'Authorization': 'Bearer $authToken'},
    );
    if (resp.statusCode != 200) {
      throw Exception('memory_v2_read_failed');
    }
    final decoded = jsonDecode(resp.body);
    if (decoded is! List)
      throw const FormatException('memory_v2_invalid_response');
    return decoded
        .whereType<Map>()
        .map((row) => Map<String, dynamic>.from(row))
        .toList(growable: false);
  }

  Future<void> writeZkMemoryEnvelope({
    required String baseUrl,
    required String authToken,
    required String memoryId,
    required String memoryType,
    required String payloadCiphertext,
    required String lookupHash,
  }) async {
    const qa = bool.fromEnvironment(
      'QA_CHAT_PRIVACY_DIAGNOSTICS',
      defaultValue: false,
    );
    if (qa) _vlog('QA_MEMORY_API_STAGE=method_body_entered', const {});
    if (qa) _vlog('QA_MEMORY_API_STAGE=base_url_ready', const {});
    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-ai-memory');
    if (qa) _vlog('QA_MEMORY_API_STAGE=uri_parse_succeeded', const {});
    final headers = <String, String>{
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $authToken'
    };
    final body = jsonEncode(<String, dynamic>{
      'memory_type': memoryType,
      'memory_lookup_hash': lookupHash,
      'payload_ciphertext': payloadCiphertext,
      'memory_id': memoryId,
    });
    if (qa) _vlog('QA_MEMORY_API_STAGE=body_build_succeeded', const {});
    if (qa) _vlog('QA_MEMORY_API_STAGE=auth_ready', const {});
    try {
      if (qa) _vlog('QA_MEMORY_API_STAGE=http_client_ready', const {});
      if (qa) _vlog('QA_MEMORY_API_STAGE=http_call_entered', const {});
      final resp = await http.post(uri, headers: headers, body: body);
      if (qa) _vlog('QA_MEMORY_API_STAGE=http_call_returned', const {});
      if (qa) _vlog('QA_MEMORY_API_STAGE=response_status_present', const {});
      if (qa) {
        _vlog('MEMORY_V2_WRITE_HTTP_STATUS=${resp.statusCode}', const {});
        _vlog(
          'MEMORY_V2_WRITE_HTTP_2XX=${resp.statusCode >= 200 && resp.statusCode < 300}',
          const {},
        );
      }
      if (resp.statusCode != 200) {
        // Status-only diagnostics are safe: never log the encrypted request,
        // response body, lookup hash, token, or memory identifier.
        _vlog('memory-v2.write.response', {
          'status': resp.statusCode,
          'reason': resp.reasonPhrase ?? '-',
        });
        if (qa) {
          _vlog(
            'MEMORY_V2_WRITE_SAFE_ERROR_CATEGORY=${resp.statusCode == 401 ? 'unauthorized' : resp.statusCode == 403 ? 'forbidden' : resp.statusCode == 404 ? 'route_or_feature_disabled' : resp.statusCode == 409 ? 'duplicate_or_state_conflict' : resp.statusCode == 422 ? 'request_model_validation' : resp.statusCode >= 500 ? 'backend_server_error' : 'validation_error'}',
            const {},
          );
        }
        throw Exception('memory_v2_write_failed_status_${resp.statusCode}');
      }
      return;
    } catch (e) {
      if (qa) {
        _vlog('QA_MEMORY_WRITE_EXCEPTION_TYPE=${e.runtimeType}', const {});
      }
      rethrow;
    }
  }

  Future<void> deleteZkMemoryEnvelope({
    required String baseUrl,
    required String authToken,
    required String memoryId,
  }) async {
    final resp = await http.delete(
      Uri.parse('$baseUrl/vault/ciphertext/vault-ai-memory/$memoryId'),
      headers: <String, String>{'Authorization': 'Bearer $authToken'},
    );
    if (resp.statusCode != 200) throw Exception('memory_v2_delete_failed');
  }

  /// ZK ciphertext-first uploaded_files metadata write. Called right
  /// after an upload path returns a file_id; encrypts every readable
  /// metadata field under the vault's metadata subkey and POSTs the
  /// ciphertext to /vault/ciphertext/uploaded-files. That endpoint
  /// writes the ciphertext columns AND NULLs the corresponding legacy
  /// plaintext columns atomically. Fails-closed on ZK path.
  Future<void> tryZkUploadedFileCiphertextUpdate({
    required String baseUrl,
    required String authToken,
    required String fileId,
    String? fileName,
    String? savedName,
    String? contentType,
    String? detectedType,
    String? detectedService,
    String? assetType,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) return;
    final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(mvk);
    final metaKey = await hierarchy.metadataKey();
    Future<String?> ct(String? plaintext) async {
      if (plaintext == null || plaintext.isEmpty) return null;
      final bytes = await vault_key_hierarchy.aesGcmWrap(
        metaKey,
        utf8.encode(plaintext),
      );
      return vault_key_hierarchy.b64urlEncode(bytes);
    }

    final body = <String, dynamic>{'file_id': fileId};
    final fnCt = await ct(fileName);
    if (fnCt != null) body['file_name_ciphertext'] = fnCt;
    final snCt = await ct(savedName);
    if (snCt != null) body['saved_name_ciphertext'] = snCt;
    final ctypeCt = await ct(contentType);
    if (ctypeCt != null) body['content_type_ciphertext'] = ctypeCt;
    final dtCt = await ct(detectedType);
    if (dtCt != null) body['detected_type_ciphertext'] = dtCt;
    final dsCt = await ct(detectedService);
    if (dsCt != null) body['detected_service_ciphertext'] = dsCt;
    final atCt = await ct(assetType);
    if (atCt != null) body['asset_type_ciphertext'] = atCt;
    if (body.length == 1) return; // nothing to encrypt
    final uri = Uri.parse('$baseUrl/vault/ciphertext/uploaded-files');
    final resp = await http.post(
      uri,
      headers: <String, String>{
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $authToken',
      },
      body: jsonEncode(body),
    );
    if (resp.statusCode != 200) {
      throw Exception(
        'ZK ciphertext uploaded_files metadata write failed '
        '(${resp.statusCode})',
      );
    }
  }

  Future<Map<String, dynamic>?> tryZkVaultItemCiphertextUpsert({
    required String baseUrl,
    required String authToken,
    int? existingItemId,
    required String itemType,
    required String service,
    required Map<String, dynamic> payload,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) return null;
    final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(mvk);
    final metaKey = await hierarchy.metadataKey();
    final itCt = await vault_key_hierarchy.aesGcmWrap(
      metaKey,
      utf8.encode(itemType),
    );
    final svcCt = await vault_key_hierarchy.aesGcmWrap(
      metaKey,
      utf8.encode(service),
    );
    final pyCt = await vault_key_hierarchy.aesGcmWrap(
      metaKey,
      utf8.encode(jsonEncode(payload)),
    );
    final body = <String, dynamic>{
      if (existingItemId != null) 'item_id': existingItemId,
      'item_type_ciphertext': vault_key_hierarchy.b64urlEncode(itCt),
      'service_ciphertext': vault_key_hierarchy.b64urlEncode(svcCt),
      'payload_ciphertext': vault_key_hierarchy.b64urlEncode(pyCt),
    };
    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-items');
    final resp = await http.post(
      uri,
      headers: <String, String>{
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $authToken',
      },
      body: jsonEncode(body),
    );
    if (resp.statusCode != 200) {
      // Fail closed for ZK — a broken ciphertext write must NOT
      // silently fall back to plaintext.
      throw Exception(
        'ZK ciphertext vault-item write failed (${resp.statusCode})',
      );
    }
    final decoded = jsonDecode(resp.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid /vault/ciphertext/vault-items response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> deleteVaultSecureItem({
    required String vaultName,
    required String service,
    required String itemType,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/delete-secure-item');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'service': service,
        'item_type': itemType,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Could not delete saved item',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateVaultFileName({
    required String vaultName,
    required String fileId,
    required String savedName,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/manage/file');

    final response = await http.patch(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'file_id': fileId,
        'saved_name': savedName,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Update file failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> deleteVaultFile({
    required String vaultName,
    required String fileId,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/manage/file/delete');

    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': vaultName,
        'file_id': fileId,
        'pin': pin,
      }),
    );

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Delete file failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Uint8List decodeDownloadedFileBytes(Map<String, dynamic> payload) {
    final base64Data = payload['base64_data'];
    if (base64Data == null || base64Data.toString().isEmpty) {
      throw Exception('Missing base64_data in download response');
    }

    return base64Decode(base64Data.toString());
  }

  String? _cleanSseLine(String rawLine) {
    final line = rawLine.trim();

    if (line.isEmpty) {
      return null;
    }

    if (line.startsWith('data:')) {
      return line.substring(5).trim();
    }

    return null;
  }

  String _formatBackendError({
    required String prefix,
    required int statusCode,
    required String responseBody,
  }) {
    String detail = responseBody.trim();

    try {
      final decoded = jsonDecode(responseBody);
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

    if (detail.isEmpty) {
      return '$prefix: $statusCode';
    }

    return '$prefix: $statusCode - $detail';
  }

  Future<Map<String, dynamic>> fetchRelatedFiles({
    required String fileId,
    required String pin,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/files/$fileId/related');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'pin': pin}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Show related files failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid related-files response format');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> createCryptoWalletAccount({
    required String asset,
    required String authToken,
    required String walletLabel,
    required String publicAddress,
    required String network,
    required String encryptedWalletSecret,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/$asset/create');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'walletLabel': walletLabel,
        'publicAddress': publicAddress,
        'network': network,
        'encryptedWalletSecret': encryptedWalletSecret,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Create wallet account failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid create wallet account response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletAccount({
    required String asset,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/$asset');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get wallet account failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid wallet account response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletReceive({
    required String asset,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/$asset/receive');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get receive payload failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid receive payload response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletBalance({
    required String asset,
    required String authToken,
    required String address,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/$asset/balance?address=$address',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get balance failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid balance response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecret({
    required String asset,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/$asset/encrypted-secret');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get encrypted secret failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid encrypted secret response');
    }
    return decoded;
  }

  /// ZK ciphertext-first outgoing-history persistence. Fire-and-
  /// forget from the panel; a failure never blocks the send-success
  /// UI.
  Future<Map<String, dynamic>> postCryptoOutgoingHistoryCiphertext({
    required String authToken,
    required String network,
    required String signatureLookupHash,
    required String outcomePayloadCiphertext,
  }) async {
    final uri = Uri.parse('$baseUrl/vault/ciphertext/crypto-history');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'network': network,
        'signature_lookup_hash': signatureLookupHash,
        'outcome_payload_ciphertext': outcomePayloadCiphertext,
      }),
    );
    if (response.statusCode != 200) {
      throw Exception(_formatBackendError(
        prefix: 'Crypto history ciphertext-write failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid crypto history response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> createCryptoWalletSendDraft({
    required String asset,
    required String authToken,
    required String fromAddress,
    required String destinationAddress,
    required String amountEth,
    // ZK ciphertext-first mode. When both fields are supplied the
    // backend persists an opaque draft (no readable sender /
    // destination / value / fee / asset columns). The plaintext
    // address / amount fields above are still transmitted so the
    // server can compute gas / nonce / RPC-side validation but are
    // NOT persisted.
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/$asset/send/draft');
    final body = <String, dynamic>{
      'fromAddress': fromAddress,
      'destinationAddress': destinationAddress,
      'amountEth': amountEth,
    };
    if (draftPayloadCiphertext != null) {
      body['draftPayloadCiphertext'] = draftPayloadCiphertext;
    }
    if (senderAddressLookupHash != null) {
      body['senderAddressLookupHash'] = senderAddressLookupHash;
    }
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Create send draft failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid send draft response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransaction({
    required String asset,
    required String authToken,
    required String signedTransaction,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/$asset/send/broadcast');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'signedTransaction': signedTransaction,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Broadcast transaction failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid broadcast response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletTransactionStatus({
    required String asset,
    required String txHash,
    required String authToken,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/$asset/transaction/$txHash',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get transaction status failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid transaction status response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/receive',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get receive payload failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid receive payload response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> createCryptoWalletAccountNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String walletLabel,
    required String publicAddress,
    required String encryptedWalletSecret,
    int? restoreHeight,
    String? scannerMode,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/create',
    );
    final body = <String, dynamic>{
      'walletLabel': walletLabel,
      'publicAddress': publicAddress,
      'network': network,
      'encryptedWalletSecret': encryptedWalletSecret,
    };
    if (restoreHeight != null) {
      body['restoreHeight'] = restoreHeight;
    }
    if (scannerMode != null) {
      body['scannerMode'] = scannerMode;
    }
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Create wallet account failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid create wallet account response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/balance?address=$address',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get balance failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid balance response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> listCryptoWalletTransactionsNetwork({
    required String network,
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/transactions?limit=$limit',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get transaction history failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid transaction history response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> listCryptoWalletTransactions({
    required String asset,
    required String authToken,
    int limit = 20,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/$asset/transactions?limit=$limit',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get transaction history failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid transaction history response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> listCryptoWalletAccounts({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/accounts');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List wallet accounts failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid wallet accounts response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> createCryptoWalletSendDraftNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String fromAddress,
    required String destinationAddress,
    String? amountEth,
    String? amountSol,
    String? amountUsdt,
    // ZK ciphertext-first mode; see the twin on the single-asset
    // sibling method above.
    String? draftPayloadCiphertext,
    String? senderAddressLookupHash,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/send/draft',
    );
    final body = <String, dynamic>{
      'fromAddress': fromAddress,
      'destinationAddress': destinationAddress,
    };
    if (amountEth != null) body['amountEth'] = amountEth;
    if (amountSol != null) body['amountSol'] = amountSol;
    if (amountUsdt != null) body['amountUsdt'] = amountUsdt;
    if (draftPayloadCiphertext != null) {
      body['draftPayloadCiphertext'] = draftPayloadCiphertext;
    }
    if (senderAddressLookupHash != null) {
      body['senderAddressLookupHash'] = senderAddressLookupHash;
    }
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Create send draft failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid send draft response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
    String? draftId,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/send/broadcast',
    );
    final body = <String, dynamic>{
      'signedTransaction': signedTransaction,
    };
    if (idempotencyKey != null && idempotencyKey.isNotEmpty) {
      body['idempotencyKey'] = idempotencyKey;
    }
    if (draftId != null && draftId.isNotEmpty) {
      body['draftId'] = draftId;
    }
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Broadcast transaction failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid broadcast response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletEncryptedSecretNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/encrypted-secret',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get encrypted secret failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid encrypted secret response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/features').replace(
      queryParameters: <String, String>{
        '_': DateTime.now().millisecondsSinceEpoch.toString(),
      },
    );
    final headers = _defaultHeaders(authToken: authToken, json: false);
    headers['Cache-Control'] = 'no-cache, no-store';
    headers['Pragma'] = 'no-cache';
    final response = await http.get(
      uri,
      headers: headers,
    );
    _vlog('crypto_wallet.features.response', {
      'status': response.statusCode,
    });
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get wallet features failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid features response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletDiagnosis({
    required String authToken,
    String? adminToken,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/diagnosis');
    final headers = _defaultHeaders(authToken: authToken, json: false);
    if (adminToken != null && adminToken.isNotEmpty) {
      headers['X-Crypto-Health-Admin-Token'] = adminToken;
    }
    final response = await http.get(uri, headers: headers);
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get wallet diagnosis failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid diagnosis response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> classifyVaultChat({
    required String message,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/vault/chat/classify');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken),
      body: jsonEncode({'message': message}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Classify vault chat failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid classify response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> classifyCryptoVaultChat({
    required String message,
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/vault/chat/classify');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken),
      body: jsonEncode({'message': message}),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Classify Crypto Vault chat failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid classify response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getXmrScannerStatus({
    required String authToken,
    String? clientPlatform,
  }) async {
    final base = Uri.parse('$baseUrl/crypto/wallet/xmr/scanner/status');
    final uri = clientPlatform != null && clientPlatform.isNotEmpty
        ? base.replace(queryParameters: {'platform': clientPlatform})
        : base;
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get XMR scanner status failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid XMR scanner status response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletHealth({
    required String authToken,
    String? adminToken,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/health');
    final headers = _defaultHeaders(authToken: authToken, json: false);
    if (adminToken != null && adminToken.isNotEmpty) {
      headers['X-Crypto-Health-Admin-Token'] = adminToken;
    }
    final response = await http.get(uri, headers: headers);
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get wallet health failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid health response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletTransactionStatusNetwork({
    required String network,
    required String asset,
    required String txHash,
    required String authToken,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/transaction/$txHash',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get transaction status failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid transaction status response');
    }
    return decoded;
  }

  // 2026-07-13 (durability slice): vault-scoped durable outgoing
  // history. The backend response never includes claim tokens or
  // internal lock fields — only the projection of consumed drafts
  // that Activity needs to render (and the local tx hash the client
  // uses to fetch chain-observed status separately).
  Future<Map<String, dynamic>> getCryptoWalletOutgoingHistoryNetwork({
    required String network,
    required String authToken,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/outgoing/history',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get outgoing history failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid outgoing history response');
    }
    return decoded;
  }

  // 2026-07-14 (Round 8 hardening): authoritative pre-sign +
  // pre-broadcast draft-expiry verification.
  //
  // Response shape:
  //   {
  //     "expired": true | false | null,
  //     "network": "solana_mainnet" | "tron_mainnet" | ...,
  //     "reason": "...",
  //     // SOL: "currentBlockHeight", "lastValidBlockHeight"
  //     // TRON: "nowMs", "expirationMs"
  //   }
  //
  // `expired == null` means the authoritative chain observation
  // could not be fetched (RPC unavailable). The caller MUST treat
  // null as a block signal — never as "not expired".
  // 2026-07-14 (Round 10 — Max UX): fee-estimate endpoint used by
  // the Send-form Max button so users do NOT have to enter an
  // amount + tap Review before Max can populate the field.
  //
  // Request:
  //   POST /crypto/wallet/network/{network}/send/fee_estimate
  //   body: { fromAddress, destinationAddress, asset }
  //
  // Success shape (ETH / SOL — TRC-20 does not use this endpoint):
  //   {
  //     "status": "fee_estimate_ready",
  //     "network": "ethereum_mainnet" | "solana_mainnet",
  //     "asset": "ETH" | "USDT_ERC20" | "USDC_ERC20" | "SOL",
  //     "authorizedMaxFeeBaseUnits": "21000000000000",   // wei/lamports
  //     "feeSource": "eth_estimateGas_x_gasPrice" | "sol_getFeeForMessage",
  //   }
  //
  // Failure shape:
  //   {
  //     "status": "fee_estimate_unavailable",
  //     "reason": "rpc_error" | "invalid_destination_address" | ...
  //     "message": optional user-facing string,
  //   }
  //
  // Anything other than exactly `status: "fee_estimate_ready"` +
  // parseable `authorizedMaxFeeBaseUnits` MUST be treated as a
  // "Max temporarily unavailable" fail-closed state by the caller.
  Future<Map<String, dynamic>> postCryptoWalletSendFeeEstimateNetwork({
    required String network,
    required String fromAddress,
    required String destinationAddress,
    required String asset,
    required String authToken,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/send/fee_estimate',
    );
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'fromAddress': fromAddress,
        'destinationAddress': destinationAddress,
        'asset': asset,
      }),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Fee estimate failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid fee estimate response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletDraftExpiryNetwork({
    required String network,
    required String draftId,
    required String authToken,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/draft/$draftId/expiry',
    );
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Get draft expiry failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid draft expiry response');
    }
    return decoded;
  }

  Future<void> createFileV2Manifest(
      {required String authToken,
      required String fileId,
      required Uint8List manifestCiphertext,
      required int totalBytes,
      required int chunkSize,
      required int chunkCount}) async {
    final r = await http.post(Uri.parse('$baseUrl/vault/file-v2/manifest'),
        headers: _defaultHeaders(authToken: authToken, json: true),
        body: jsonEncode({
          'file_id': fileId,
          'crypto_version': 'client_mvk_v2',
          'manifest_ciphertext':
              vault_key_hierarchy.b64urlEncode(manifestCiphertext),
          'total_bytes': totalBytes,
          'chunk_size': chunkSize,
          'chunk_count': chunkCount,
        }));
    if (r.statusCode != 200) throw Exception('file_v2_manifest_failed');
  }

  Future<void> putFileV2Chunk(
      {required String authToken,
      required String fileId,
      required int chunkIndex,
      required Uint8List ciphertext}) async {
    final r = await http.put(Uri.parse('$baseUrl/vault/file-v2/chunk'),
        headers: _defaultHeaders(authToken: authToken, json: true),
        body: jsonEncode({
          'file_id': fileId,
          'chunk_index': chunkIndex,
          'ciphertext': vault_key_hierarchy.b64urlEncode(ciphertext),
        }));
    if (r.statusCode != 200) throw Exception('file_v2_chunk_failed');
  }

  Future<Map<String, dynamic>> listFileV2({required String authToken}) async {
    final r = await http.get(Uri.parse('$baseUrl/vault/file-v2'),
        headers: _defaultHeaders(authToken: authToken));
    _vlog('file-v2.list.response', {
      'status': r.statusCode,
      'reason': r.reasonPhrase ?? '-',
      'body_len': r.bodyBytes.length,
    });
    if (r.statusCode != 200) throw Exception('file_v2_list_failed');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getFileV2Manifest(
      {required String authToken, required String fileId}) async {
    final r = await http.get(
        Uri.parse('$baseUrl/vault/file-v2/$fileId/manifest'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('file_v2_manifest_read_failed');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Uint8List> getFileV2Chunk(
      {required String authToken,
      required String fileId,
      required int chunkIndex}) async {
    final r = await http.get(
        Uri.parse('$baseUrl/vault/file-v2/$fileId/chunk/$chunkIndex'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('file_v2_chunk_read_failed');
    final m = jsonDecode(r.body) as Map<String, dynamic>;
    return vault_key_hierarchy.b64urlDecode(m['ciphertext'] as String);
  }

  Future<void> deleteFileV2(
      {required String authToken, required String fileId}) async {
    final r = await http.delete(Uri.parse('$baseUrl/vault/file-v2/$fileId'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('file_v2_delete_failed');
  }

  Future<void> createWalletBackupV2({
    required String authToken,
    required String backupRecordId,
    required String secretType,
    required Uint8List payloadCiphertext,
  }) async {
    final r = await http.post(Uri.parse('$baseUrl/vault/wallet-backup-v2'),
        headers: _defaultHeaders(authToken: authToken, json: true),
        body: jsonEncode({
          'backup_record_id': backupRecordId,
          'secret_type': secretType,
          'payload_ciphertext':
              vault_key_hierarchy.b64urlEncode(payloadCiphertext),
          'envelope_version': 'client_mvk_v2',
        }));
    if (r.statusCode != 200) throw Exception('wallet_backup_v2_create_failed');
  }

  Future<List<Map<String, dynamic>>> listWalletBackupV2(
      {required String authToken}) async {
    final r = await http.get(Uri.parse('$baseUrl/vault/wallet-backup-v2'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('wallet_backup_v2_list_failed');
    final body = jsonDecode(r.body) as Map<String, dynamic>;
    return (body['backups'] as List<dynamic>).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> readWalletBackupV2({
    required String authToken,
    required String backupRecordId,
  }) async {
    final r = await http.get(
        Uri.parse('$baseUrl/vault/wallet-backup-v2/$backupRecordId'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('wallet_backup_v2_read_failed');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> deleteWalletBackupV2({
    required String authToken,
    required String backupRecordId,
  }) async {
    final r = await http.delete(
        Uri.parse('$baseUrl/vault/wallet-backup-v2/$backupRecordId'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('wallet_backup_v2_delete_failed');
  }

  Future<void> createWalletV2(
      {required String authToken,
      required String walletRecordId,
      required String chain,
      required String network,
      required String asset,
      required String publicAddress,
      required String walletLabel,
      required Uint8List payloadCiphertext,
      String migrationState = 'v2_verified'}) async {
    final r = await http.post(Uri.parse('$baseUrl/vault/wallet-v2'),
        headers: _defaultHeaders(authToken: authToken, json: true),
        body: jsonEncode({
          'wallet_record_id': walletRecordId,
          'chain': chain,
          'network': network,
          'asset': asset,
          'public_address': publicAddress,
          'wallet_label': walletLabel,
          'payload_ciphertext':
              vault_key_hierarchy.b64urlEncode(payloadCiphertext),
          'envelope_version': 'v2',
          'migration_state': migrationState
        }));
    if (r.statusCode != 200) throw Exception('wallet_v2_create_failed');
  }

  Future<List<Map<String, dynamic>>> listWalletV2(
      {required String authToken}) async {
    final r = await http.get(Uri.parse('$baseUrl/vault/wallet-v2'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('wallet_v2_list_failed');
    return ((jsonDecode(r.body) as Map<String, dynamic>)['wallets'] as List)
        .cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> readWalletV2(
      {required String authToken, required String walletRecordId}) async {
    final r = await http.get(
        Uri.parse('$baseUrl/vault/wallet-v2/$walletRecordId'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('wallet_v2_read_failed');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> deleteWalletV2(
      {required String authToken, required String walletRecordId}) async {
    final r = await http.delete(
        Uri.parse('$baseUrl/vault/wallet-v2/$walletRecordId'),
        headers: _defaultHeaders(authToken: authToken));
    if (r.statusCode != 200) throw Exception('wallet_v2_delete_failed');
  }
}
