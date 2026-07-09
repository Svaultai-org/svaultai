import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kReleaseMode;
import 'package:http/http.dart' as http;


void _vlog(String tag, [Map<String, Object?>? data]) {
  if (kReleaseMode) return;
  final payload = data == null
      ? ''
      : data.entries.map((e) => '${e.key}=${e.value}').join(' ');
  
  print('[vault-debug] $tag $payload');
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
          final orphanMap = orphan is Map<String, dynamic> ? orphan : const <String, dynamic>{};
          return OrphanDataException(
            message: (detail['message'] ?? 'Orphan data detected').toString(),
            vaultName: orphanMap['vault_name']?.toString(),
            itemCount: (orphanMap['item_count'] as num?)?.toInt() ?? 0,
            fileCount: (orphanMap['file_count'] as num?)?.toInt() ?? 0,
          );
        }
      }
    } catch (_) {
      
    }
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
  String toString() =>
      'StorageLimitExceededException(message: $message, '
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
  String toString() =>
      'NameConflictUploadException(existing=$existingFileId)';
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
    this.message = 'Too many attempts. Please wait a few minutes and try again.',
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


class InvalidVaultUnlockException implements Exception {
  final String message;
  const InvalidVaultUnlockException({
    this.message =
        'Your vault unlock session expired or no longer matches this vault. Please enter your PIN again.',
  });
  @override
  String toString() => 'InvalidVaultUnlockException(message: $message)';
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
            message: (detail['message'] ?? 'This device is not trusted.').toString(),
            deviceId: detail['device_id']?.toString(),
            status: (detail['status'] ?? 'unknown').toString(),
          );
        }
      }
    } catch (_) {
      
    }
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
      'baseUrl':                baseUrl,
      'url':                    uri.toString(),
      'body_len':               body.length,
      'vault_name_len':         vaultName.length,
      'pin_len':                pin.length,
      'has_display_username':   displayUsername != null
                                && displayUsername.isNotEmpty,
      'acknowledged':           acknowledgedIrrecoverable,
      'x_device_id_present':    headers.containsKey('X-Device-Id'),
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
        'baseUrl':         baseUrl,
        'url':             uri.toString(),
        'error_type':      e.runtimeType.toString(),
        'error':           e.toString(),
        'stack_first_line': st.toString().split('\n').firstWhere(
                              (_) => true, orElse: () => '-',
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
      'baseUrl':              baseUrl,
      'url':                  uri.toString(),
      'body_len':             body.length,
      'vault_name_len':       vaultName.length,
      'pin_len':              pin.length,
      'x_device_id_present':  headers.containsKey('X-Device-Id'),
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
        'baseUrl':         baseUrl,
        'url':             uri.toString(),
        'error_type':      e.runtimeType.toString(),
        'error':           e.toString(),
        'stack_first_line': st.toString().split('\n').firstWhere(
                              (_) => true, orElse: () => '-',
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
        throw VaultFrozenException(message: message.isEmpty ? 'Vault frozen' : message);
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
      if (cancelUrl != null)  'cancel_url':  cancelUrl,
    });

    
    _vlog('billing.checkout_session.preflight', {
      'baseUrl':              baseUrl,
      'url':                  uri.toString(),
      'block_count':          blockCount,
      'body_len':             body.length,
      'auth_token_present':   authToken.isNotEmpty,
      'auth_token_len':       authToken.length,
      'x_device_id_present':  headers.containsKey('X-Device-Id'),
      'has_success_url':      successUrl != null,
      'has_cancel_url':       cancelUrl != null,
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
        'baseUrl':         baseUrl,
        'url':             uri.toString(),
        'error_type':      e.runtimeType.toString(),
        'error':           e.toString(),
        'stack_first_line': st.toString().split('\n').firstWhere(
                              (_) => true, orElse: () => '-',
                            ),
      });
      rethrow;
    }

    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Checkout session failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid checkout-session response format');
    }
    return decoded;
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

  
  Future<Map<String, dynamic>> getRelationshipList({
    required String authToken,
    required String vaultName,
    String? relationType,
    int limit = 500,
  }) async {
    final uri = Uri.parse('$baseUrl/relationships/list');
    final body = <String, dynamic>{
      'vault_name': vaultName,
      'limit': limit,
    };
    if (relationType != null && relationType.isNotEmpty) {
      body['relation_type'] = relationType;
    }
    final headers = _defaultHeaders(authToken: authToken, json: true);
    _vlogRequest('relationships.list', uri, headers);
    final response = await _runWithNetLog(
      'relationships.list',
      uri,
      () => http.post(uri, headers: headers, body: jsonEncode(body)),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Relationships failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid relationships response format');
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
    List<String>? uploadedFileIds,
    String? appLocale,
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
        RegExp(r'[^a-zA-Z0-9\-]'), '',
      );
      if (safe.isNotEmpty && safe.length <= 16) {
        headers['X-App-Locale'] = safe;
      }
    }

    request.headers.addAll(headers);
    _vlogRequest('chat.stream', uri, headers);
    _vlog('chat.body', {
      'vault_name': vaultName,
      'encrypted_message_len': encryptedMessage.length,
      'pin_present': pin.isNotEmpty,
      'uploaded_file_count': (uploadedFileIds ?? const <String>[]).length,
      'app_locale_present': appLocale != null && appLocale.isNotEmpty,
    });

    request.body = jsonEncode({
      'encrypted_message': encryptedMessage,
      'vault_name': vaultName,
      'pin': pin,
      'uploaded_file_ids': uploadedFileIds ?? <String>[],
      if (appLocale != null && appLocale.isNotEmpty)
        'app_locale': appLocale,
    });

    final response = await request.send();
    _vlog('chat.response', {
      'status': response.statusCode,
      'content_type': response.headers['content-type'] ?? '-',
    });

    if (response.statusCode != 200) {
      final errorBody = await response.stream.bytesToString();
      
      
      _vlog('chat.error', {
        'status': response.statusCode,
        'body':   errorBody,
      });
      _throwIfAuthExpired(response.statusCode, errorBody);
      _throwIfDeviceNotTrusted(response.statusCode, errorBody);
      _throwIfLockOrFrozen(response.statusCode, errorBody);
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
        'endpoint':        uri.toString(),
        'authToken_empty': authToken.isEmpty,
        'authToken_len':   authToken.length,
        'body':            response.body,
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
        'stack_first_line':
            st.toString().split('\n').firstWhere((_) => true, orElse: () => '-'),
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
      if (resumeJobId != null && resumeJobId.isNotEmpty)
        'job_id': resumeJobId,
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
    final uri = Uri.parse(
      '$baseUrl/vault-meta'
      '?vault_name=${Uri.encodeQueryComponent(vaultName)}',
);

    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    );

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
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/beneficiary/list-mine'),
      headers: _defaultHeaders(authToken: authToken, json: true),
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
    throw const AuthExpiredException();
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
          if (code == 'device_not_trusted' || code == 'missing_device_id') {
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
    
    
    String? message;
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final d = decoded['detail'];
        if (d is String && d.isNotEmpty) message = d;
      }
    } catch (_) {
      
    }
    if (message != null && message.contains('Invalid PIN or corrupted data')) {
      throw const InvalidVaultUnlockException();
    }
    throw const InvalidVaultUnlockException();
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
        'service':    service,
        'item_type':  itemType,
        'pin':        pin,
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
    final uri = Uri.parse('$baseUrl/crypto/save-wallet-profile');
    final body = <String, dynamic>{
      'pin':           pin,
      'asset':         asset,
      'walletLabel':   walletLabel,
      'publicAddress': publicAddress,
    };
    if (network != null && network.isNotEmpty) body['network'] = network;
    if (note    != null && note.isNotEmpty)    body['note']    = note;
    if (title   != null && title.isNotEmpty)   body['title']   = title;

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
    required bool   warningConfirmed,
    String? asset,
    String? network,
    String? note,
    String? title,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/save-sensitive-backup');
    final body = <String, dynamic>{
      'pin':              pin,
      'walletLabel':      walletLabel,
      'secretType':       secretType,
      'secretValue':      secretValue,
      'warningConfirmed': warningConfirmed,
    };
    if (asset   != null && asset.isNotEmpty)   body['asset']   = asset;
    if (network != null && network.isNotEmpty) body['network'] = network;
    if (note    != null && note.isNotEmpty)    body['note']    = note;
    if (title   != null && title.isNotEmpty)   body['title']   = title;

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
    final uri = Uri.parse('$baseUrl/crypto/save-note');
    final body = <String, dynamic>{
      'pin':      pin,
      'title':    title,
      'note':     note,
      'noteType': noteType,
    };
    if (asset       != null && asset.isNotEmpty)       body['asset']       = asset;
    if (network     != null && network.isNotEmpty)     body['network']     = network;
    if (walletLabel != null && walletLabel.isNotEmpty) body['walletLabel'] = walletLabel;
    if (txHash      != null && txHash.isNotEmpty)      body['txHash']      = txHash;
    if (amountText  != null && amountText.isNotEmpty)  body['amountText']  = amountText;
    if (dateText    != null && dateText.isNotEmpty)    body['dateText']    = dateText;

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
    final uri = Uri.parse(
      '$baseUrl/crypto/reveal-sensitive-backup',
    );
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'pin':       pin,
        'service':   service,
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

    return decoded;
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
      if (importId != null && importId.isNotEmpty)
        'import_id': importId,
    };

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
  final uri = Uri.parse('$baseUrl/update-secure-item');
  final body = <String, dynamic>{
    'vault_name':  vaultName,
    'old_service': oldService,
    'item_type':   itemType,
    'pin':         pin,
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
      'service':    service,
      'item_type':  itemType,
      'pin':        pin,
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
    } catch (_) {
      
    }

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
        'walletLabel':           walletLabel,
        'publicAddress':         publicAddress,
        'network':               network,
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

  
  Future<Map<String, dynamic>> createCryptoWalletSendDraft({
    required String asset,
    required String authToken,
    required String fromAddress,
    required String destinationAddress,
    required String amountEth,
  }) async {
    final uri = Uri.parse('$baseUrl/crypto/wallet/$asset/send/draft');
    final response = await http.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'fromAddress':        fromAddress,
        'destinationAddress': destinationAddress,
        'amountEth':          amountEth,
      }),
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
      'walletLabel':           walletLabel,
      'publicAddress':         publicAddress,
      'network':               network,
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
  }) async {
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/send/draft',
    );
    final body = <String, dynamic>{
      'fromAddress':        fromAddress,
      'destinationAddress': destinationAddress,
    };
    if (amountEth != null) body['amountEth'] = amountEth;
    if (amountSol != null) body['amountSol'] = amountSol;
    if (amountUsdt != null) body['amountUsdt'] = amountUsdt;
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

  
  Future<Map<String, dynamic>>
      broadcastCryptoWalletSignedTransactionNetwork({
    required String network,
    required String asset,
    required String authToken,
    required Object signedTransaction,
    String? idempotencyKey,
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
    final uri = Uri.parse('$baseUrl/crypto/wallet/features');
    final response = await http.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
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
}
