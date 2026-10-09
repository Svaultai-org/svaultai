import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'pwned_password_check.dart';
import 'vault_key_hierarchy.dart';
import 'zk_active_mvk.dart';

const conciergeConsentVersion = '2026-10-09';

class ConciergeAccessExpired implements Exception {
  const ConciergeAccessExpired();
  @override
  String toString() => 'Unlock your vault to continue.';
}

class ConciergeUnavailable implements Exception {
  final String code;
  const ConciergeUnavailable([this.code = 'unavailable']);
  @override
  String toString() => 'Concierge check is unavailable.';
}

/// Main supplies a lease bound to its current unlocked key/session identity.
/// It must become permanently stale after lock, logout or account switch.
class ConciergeAccessLease {
  final bool Function() _isCurrent;
  const ConciergeAccessLease({required bool Function() isCurrent})
      : _isCurrent = isCurrent;
  bool get isCurrent => _isCurrent();
  void assertCurrent() {
    if (!isCurrent) throw const ConciergeAccessExpired();
  }
}

class ConciergeLoginRecord {
  final String id;
  final String title;
  final String itemType;
  final String? password;
  final String? email;
  final String? settingsUrl;
  const ConciergeLoginRecord(
      {required this.id,
      required this.title,
      this.itemType = 'login',
      this.password,
      this.email,
      this.settingsUrl});
  @override
  String toString() => 'ConciergeLoginRecord(redacted)';
}

String? canonicalConciergeEmail(String? value) {
  final email = value?.trim().toLowerCase();
  if (email == null ||
      email.length > 254 ||
      !RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(email)) {
    return null;
  }
  return email;
}

class ConciergeInventory {
  final List<ConciergeLoginRecord> logins;
  final int unreadableRecords;
  const ConciergeInventory(this.logins, {this.unreadableRecords = 0});
}

class ConciergeEditableLogin {
  final String id;
  final String title;
  final String itemType;
  final Map<String, dynamic> payload;
  Map<String, dynamic> get fields =>
      Map<String, dynamic>.from(payload['fields']);
  const ConciergeEditableLogin(
      {required this.id,
      required this.title,
      required this.itemType,
      required this.payload});
  @override
  String toString() => 'ConciergeEditableLogin(redacted)';
}

/// Reads only client-encrypted records. Never falls back to the legacy
/// PIN/server-decryption endpoints. State is a dedicated opaque backend blob,
/// not a saved-login entry, with optimistic concurrency protection.
class ConciergeVaultRepository {
  final String baseUrl;
  final String authToken;
  final String vaultId;
  final String deviceId;
  final http.Client _client;
  final bool _ownsClient;
  int? _stateRevision;
  ConciergeVaultRepository(
      {required this.baseUrl,
      required this.authToken,
      required this.vaultId,
      required this.deviceId,
      http.Client? client})
      : _client = client ?? http.Client(),
        _ownsClient = client == null;
  Map<String, String> get _headers => {
        'Authorization': 'Bearer $authToken',
        'X-Device-Id': deviceId,
        'Content-Type': 'application/json'
      };
  void close() {
    if (_ownsClient) _client.close();
  }

  Future<http.Response> _request(
      ConciergeAccessLease access, String method, String path,
      [Map<String, dynamic>? body]) async {
    access.assertCurrent();
    if (deviceId.isEmpty) throw const ConciergeUnavailable('device_missing');
    try {
      final uri = Uri.parse('$baseUrl$path');
      final response = await (method == 'GET'
              ? _client.get(uri, headers: _headers)
              : method == 'POST'
                  ? _client.post(uri, headers: _headers, body: jsonEncode(body))
                  : _client.put(uri, headers: _headers, body: jsonEncode(body)))
          .timeout(const Duration(seconds: 12));
      access.assertCurrent();
      return response;
    } on ConciergeAccessExpired {
      rethrow;
    } catch (_) {
      throw const ConciergeUnavailable();
    }
  }

  Future<ConciergeInventory> loadLogins(ConciergeAccessLease access) async {
    try {
      return await _loadLogins(access);
    } on ConciergeAccessExpired {
      rethrow;
    } catch (_) {
      throw const ConciergeUnavailable('inventory_unavailable');
    }
  }

  Future<ConciergeInventory> _loadLogins(ConciergeAccessLease access) async {
    final mvk = ZkActiveMvk.current();
    if (mvk == null || ZkActiveMvk.currentVaultId() != vaultId) {
      throw const ConciergeAccessExpired();
    }
    final response =
        await _request(access, 'GET', '/vault/ciphertext/vault-items');
    if (response.statusCode != 200) throw const ConciergeUnavailable();
    final decoded = jsonDecode(response.body);
    if (decoded is! List) throw const ConciergeUnavailable();
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    access.assertCurrent();
    if (!identical(mvk, ZkActiveMvk.current()) ||
        ZkActiveMvk.currentVaultId() != vaultId) {
      throw const ConciergeAccessExpired();
    }
    final records = <ConciergeLoginRecord>[];
    var unreadable = 0;
    for (final row in decoded) {
      access.assertCurrent();
      try {
        if (row is! Map) throw const FormatException();
        Future<String> field(String name) async => utf8
            .decode(await aesGcmUnwrap(key, b64urlDecode(row[name] as String)));
        final type = await field('item_type_ciphertext');
        if (type != 'login' && type != 'credential') continue;
        final title = await field('service_ciphertext');
        final payload = jsonDecode(await field('payload_ciphertext'));
        if (payload is! Map || payload['fields'] is! Map) {
          throw const FormatException();
        }
        final fields = payload['fields'] as Map;
        records.add(ConciergeLoginRecord(
            id: '${row['item_id']}',
            title: title,
            itemType: type,
            password: fields['password'] is String ? fields['password'] : null,
            email: canonicalConciergeEmail(
                    fields['email'] is String ? fields['email'] : null) ??
                canonicalConciergeEmail(
                    fields['username'] is String ? fields['username'] : null),
            settingsUrl: fields['url'] is String ? fields['url'] : null));
      } catch (_) {
        unreadable++;
      }
    }
    access.assertCurrent();
    if (!identical(mvk, ZkActiveMvk.current()) ||
        ZkActiveMvk.currentVaultId() != vaultId) {
      throw const ConciergeAccessExpired();
    }
    return ConciergeInventory(records, unreadableRecords: unreadable);
  }

  Future<ConciergeEditableLogin> loadLoginForEdit(
      String id, ConciergeAccessLease access) async {
    try {
      access.assertCurrent();
      if (!RegExp(r'^[1-9][0-9]{0,15}$').hasMatch(id)) {
        throw const ConciergeUnavailable('unsupported_login_id');
      }
      final mvk = ZkActiveMvk.current();
      if (mvk == null || ZkActiveMvk.currentVaultId() != vaultId) {
        throw const ConciergeAccessExpired();
      }
      final response =
          await _request(access, 'GET', '/vault/ciphertext/vault-items');
      if (response.statusCode != 200) throw const ConciergeUnavailable();
      final rows = jsonDecode(response.body);
      if (rows is! List) throw const ConciergeUnavailable();
      final matches = rows
          .whereType<Map>()
          .where((row) => '${row['item_id']}' == id)
          .toList();
      if (matches.length != 1) {
        throw const ConciergeUnavailable('login_not_found');
      }
      final row = matches.single;
      final key = await VaultKeyHierarchy(mvk).metadataKey();
      Future<String> field(String name) async => utf8
          .decode(await aesGcmUnwrap(key, b64urlDecode(row[name] as String)));
      final type = await field('item_type_ciphertext');
      final title = await field('service_ciphertext');
      final payload = jsonDecode(await field('payload_ciphertext'));
      access.assertCurrent();
      if (!identical(mvk, ZkActiveMvk.current()) ||
          ZkActiveMvk.currentVaultId() != vaultId) {
        throw const ConciergeAccessExpired();
      }
      if ((type != 'login' && type != 'credential') ||
          payload is! Map ||
          payload['fields'] is! Map) {
        throw const ConciergeUnavailable('login_type_changed');
      }
      return ConciergeEditableLogin(
          id: id,
          title: title,
          itemType: type,
          payload: Map<String, dynamic>.from(payload));
    } on ConciergeAccessExpired {
      rethrow;
    } on ConciergeUnavailable {
      rethrow;
    } catch (_) {
      throw const ConciergeUnavailable('login_unreadable');
    }
  }

  Future<void> updateLoginById(String id, String newTitle,
      Map<String, dynamic> fields, ConciergeAccessLease access,
      {required String expectedItemType}) async {
    try {
      // Read again immediately before encryption. Preserve unrelated payload,
      // notes and fields, and never create a row if this ID was deleted.
      final original = await loadLoginForEdit(id, access);
      if (original.itemType != expectedItemType || newTitle.trim().isEmpty) {
        throw const ConciergeUnavailable('login_type_changed');
      }
      final mvk = ZkActiveMvk.current();
      if (mvk == null || ZkActiveMvk.currentVaultId() != vaultId) {
        throw const ConciergeAccessExpired();
      }
      final key = await VaultKeyHierarchy(mvk).metadataKey();
      Future<String> encrypted(Object value) async =>
          b64urlEncode(await aesGcmWrap(
              key, utf8.encode(value is String ? value : jsonEncode(value))));
      final body = <String, dynamic>{
        'item_id': int.parse(id),
        'item_type_ciphertext': await encrypted(original.itemType),
        'service_ciphertext': await encrypted(newTitle.trim()),
        'payload_ciphertext': await encrypted({
          ...original.payload,
          'fields': {...original.fields, ...fields}
        })
      };
      access.assertCurrent();
      if (!identical(mvk, ZkActiveMvk.current()) ||
          ZkActiveMvk.currentVaultId() != vaultId) {
        throw const ConciergeAccessExpired();
      }
      final response =
          await _request(access, 'POST', '/vault/ciphertext/vault-items', body);
      if (response.statusCode != 200) {
        throw const ConciergeUnavailable('login_update_unavailable');
      }
      final saved = jsonDecode(response.body);
      if (saved is! Map ||
          '${saved['item_id']}' != id ||
          saved['created'] != false) {
        throw const ConciergeUnavailable('login_update_unconfirmed');
      }
    } on ConciergeAccessExpired {
      rethrow;
    } on ConciergeUnavailable {
      rethrow;
    } catch (_) {
      throw const ConciergeUnavailable('login_update_unavailable');
    }
  }

  Future<Map<String, dynamic>?> readEncryptedState(
      ConciergeAccessLease access) async {
    try {
      return await _readEncryptedState(access);
    } on ConciergeAccessExpired {
      rethrow;
    } catch (_) {
      throw const ConciergeUnavailable('state_unreadable');
    }
  }

  Future<Map<String, dynamic>?> _readEncryptedState(
      ConciergeAccessLease access) async {
    _stateRevision = null;
    final mvk = ZkActiveMvk.current();
    if (mvk == null || ZkActiveMvk.currentVaultId() != vaultId) {
      throw const ConciergeAccessExpired();
    }
    final response = await _request(access, 'GET', '/concierge/state');
    if (response.statusCode != 200) {
      throw const ConciergeUnavailable('state_unavailable');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map || decoded['revision'] is! int) {
      throw const ConciergeUnavailable();
    }
    final ciphertext = decoded['ciphertext'];
    if (ciphertext == null) {
      _stateRevision = decoded['revision'];
      return null;
    }
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    final payload = jsonDecode(utf8
        .decode(await aesGcmUnwrap(key, b64urlDecode(ciphertext as String))));
    access.assertCurrent();
    if (!identical(mvk, ZkActiveMvk.current()) ||
        ZkActiveMvk.currentVaultId() != vaultId ||
        payload is! Map ||
        payload['purpose'] != 'vaultai.concierge.state.v1' ||
        payload['vault_id'] != vaultId ||
        payload['data'] is! Map) {
      throw const ConciergeUnavailable('state_unreadable');
    }
    _stateRevision = decoded['revision'];
    return Map<String, dynamic>.from(payload['data']);
  }

  Future<void> writeEncryptedState(
      Map<String, dynamic> data, ConciergeAccessLease access) async {
    final mvk = ZkActiveMvk.current();
    if (mvk == null || ZkActiveMvk.currentVaultId() != vaultId) {
      throw const ConciergeAccessExpired();
    }
    if (_stateRevision == null) {
      throw const ConciergeUnavailable('state_not_loaded');
    }
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    final envelope = await aesGcmWrap(
        key,
        utf8.encode(jsonEncode({
          'purpose': 'vaultai.concierge.state.v1',
          'vault_id': vaultId,
          'data': data
        })));
    access.assertCurrent();
    if (!identical(mvk, ZkActiveMvk.current()) ||
        ZkActiveMvk.currentVaultId() != vaultId) {
      throw const ConciergeAccessExpired();
    }
    final response = await _request(access, 'PUT', '/concierge/state', {
      'ciphertext': b64urlEncode(envelope),
      'envelope_version': 'v1',
      'expected_revision': _stateRevision
    });
    if (response.statusCode == 409) {
      throw const ConciergeUnavailable('state_conflict');
    }
    if (response.statusCode != 200) {
      throw const ConciergeUnavailable('state_unavailable');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map || decoded['revision'] is! int) {
      throw const ConciergeUnavailable();
    }
    _stateRevision = decoded['revision'];
  }
}

class ConciergeProviderCapabilities {
  final String providerMode;
  final bool emailRange;
  final bool emailMonitoring;
  final bool stealerLogs;
  final Set<String> verifiedEmailDomains;
  final String emailRangeStatus;
  final String emailMonitoringStatus;
  final String stealerStatus;
  const ConciergeProviderCapabilities(
      {this.providerMode = 'unknown',
      this.emailRange = false,
      this.emailMonitoring = false,
      this.stealerLogs = false,
      this.verifiedEmailDomains = const {},
      this.emailRangeStatus = 'not_configured',
      this.emailMonitoringStatus = 'not_configured',
      this.stealerStatus = 'not_configured'});

  // Only an explicit release policy may hide planned-deferred tools. A real
  // provider outage, or an older response without this policy, stays visible.
  bool get emailDeferred =>
      providerMode == 'free' &&
      emailRangeStatus == 'deferred' &&
      emailMonitoringStatus == 'deferred' &&
      stealerStatus == 'deferred';
}

class ConciergeEmailExposure {
  final List<Map<String, dynamic>> breaches;
  final List<String> stealerDomains;
  const ConciergeEmailExposure(
      {this.breaches = const [], this.stealerDomains = const []});
}

abstract interface class ConciergeExposureProvider {
  Future<ConciergeProviderCapabilities> capabilities(
      ConciergeAccessLease access);
  Future<ConciergeEmailExposure> checkEmail(
      String email, ConciergeAccessLease access);
  Future<Map<String, dynamic>> createMonitor(String email, String sourceId,
      {required bool stealerLogs, required ConciergeAccessLease access});
  Future<List<Map<String, dynamic>>> monitors(ConciergeAccessLease access);
  Future<void> deleteMonitor(String id, ConciergeAccessLease access);
}

class ConciergeBackendProvider implements ConciergeExposureProvider {
  final String baseUrl;
  final String authToken;
  final String deviceId;
  final http.Client _client;
  final bool _ownsClient;
  ConciergeBackendProvider(
      {required this.baseUrl,
      required this.authToken,
      required this.deviceId,
      http.Client? client})
      : _client = client ?? http.Client(),
        _ownsClient = client == null;
  void close() {
    if (_ownsClient) _client.close();
  }

  Future<Map<String, dynamic>> _call(
      String method, String path, ConciergeAccessLease access,
      [Map<String, dynamic>? body]) async {
    access.assertCurrent();
    if (deviceId.isEmpty) throw const ConciergeUnavailable('device_missing');
    try {
      final uri = Uri.parse('$baseUrl$path');
      final headers = {
        'Authorization': 'Bearer $authToken',
        'X-Device-Id': deviceId,
        'Content-Type': 'application/json'
      };
      final response = await (method == 'POST'
              ? _client.post(uri, headers: headers, body: jsonEncode(body))
              : method == 'DELETE'
                  ? _client.delete(uri, headers: headers)
                  : _client.get(uri, headers: headers))
          .timeout(const Duration(seconds: 60));
      access.assertCurrent();
      if (method == 'DELETE' && response.statusCode == 404) {
        final absent = jsonDecode(response.body);
        if (absent is Map &&
            absent['detail'] is Map &&
            (absent['detail'] as Map)['code'] == 'monitor_not_found') {
          return {};
        }
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final error = jsonDecode(response.body);
        if (error is Map &&
            error['detail'] is Map &&
            (error['detail'] as Map)['code'] == 'provider_deferred' &&
            (error['detail'] as Map)['status'] == 'deferred') {
          throw const ConciergeUnavailable('provider_deferred');
        }
        throw const ConciergeUnavailable();
      }
      if (method == 'DELETE' && response.statusCode == 204) return {};
      final decoded = jsonDecode(response.body);
      if (decoded is! Map) throw const ConciergeUnavailable();
      return Map<String, dynamic>.from(decoded);
    } on ConciergeAccessExpired {
      rethrow;
    } on ConciergeUnavailable {
      rethrow;
    } catch (_) {
      throw const ConciergeUnavailable();
    }
  }

  @override
  Future<ConciergeProviderCapabilities> capabilities(
      ConciergeAccessLease access) async {
    final result = await _call('GET', '/concierge/capabilities', access);
    String status(String key) {
      if (result[key] is Map && (result[key] as Map)['status'] == 'deferred') {
        return 'deferred';
      }
      if (result['enabled'] != true) return 'disabled';
      if (result[key] is! Map) return 'unavailable';
      final value = (result[key] as Map)['status'];
      return const {
        'available',
        'conditional',
        'disabled',
        'not_configured',
        'deferred',
        'unavailable',
        'unsupported_plan',
        'unsupported_domain',
        'rate_limited'
      }.contains(value)
          ? value as String
          : 'unavailable';
    }

    final stealer = result['stealer_logs'] is Map
        ? result['stealer_logs'] as Map
        : const {};
    final domains = stealer['verified_email_domains'];
    return ConciergeProviderCapabilities(
        providerMode: const {'free', 'hibp'}.contains(result['provider_mode'])
            ? result['provider_mode'] as String
            : 'unknown',
        emailRange: status('email_range') == 'available',
        emailMonitoring: status('email_monitoring') == 'available',
        stealerLogs:
            const {'available', 'conditional'}.contains(status('stealer_logs')),
        emailRangeStatus: status('email_range'),
        emailMonitoringStatus: status('email_monitoring'),
        stealerStatus: status('stealer_logs'),
        verifiedEmailDomains: (domains is List
            ? domains.whereType<String>().map((e) => e.toLowerCase()).toSet()
            : <String>{}));
  }

  @override
  Future<ConciergeEmailExposure> checkEmail(
      String email, ConciergeAccessLease access) async {
    final canonical = canonicalConciergeEmail(email);
    if (canonical == null) throw const ConciergeUnavailable();
    final digest =
        sha1.convert(utf8.encode(canonical)).toString().toUpperCase();
    final result = await _call('POST', '/concierge/email-range', access, {
      'prefix': digest.substring(0, 6),
      'consent_version': conciergeConsentVersion,
      'prefix_disclosure_consent': true
    });
    if (result['status'] != 'checked' || result['rows'] is! List) {
      throw const ConciergeUnavailable();
    }
    final names = <String>{};
    for (final row in result['rows'] as List) {
      if (row is! Map ||
          row['hashSuffix'] is! String ||
          row['websites'] is! List ||
          !RegExp(r'^[A-Fa-f0-9]{34}$').hasMatch(row['hashSuffix'])) {
        throw const ConciergeUnavailable();
      }
      if ('${row['hashSuffix']}'.toUpperCase() == digest.substring(6)) {
        names.addAll((row['websites'] as List).whereType<String>());
      }
    }
    // No range rows or hashes are retained or returned to the controller.
    final breaches = <Map<String, dynamic>>[];
    for (final name in names) {
      if (!RegExp(r'^[A-Za-z0-9._-]{1,128}$').hasMatch(name)) {
        throw const ConciergeUnavailable();
      }
      final details = await _call(
          'GET', '/concierge/breaches/${Uri.encodeComponent(name)}', access);
      if (details['status'] != 'checked' || details['breach'] is! Map) {
        throw const ConciergeUnavailable();
      }
      breaches.add(Map<String, dynamic>.from(details['breach']));
    }
    return ConciergeEmailExposure(breaches: breaches);
  }

  @override
  Future<Map<String, dynamic>> createMonitor(String email, String sourceId,
          {required bool stealerLogs,
          required ConciergeAccessLease access}) async =>
      _call('POST', '/concierge/monitors', access, {
        'email': email,
        'source_item_id': sourceId,
        'consent_version': conciergeConsentVersion,
        'email_disclosure_consent': true,
        'background': true,
        'stealer_logs': stealerLogs,
        'stealer_disclosure_consent': stealerLogs
      });
  @override
  Future<List<Map<String, dynamic>>> monitors(
      ConciergeAccessLease access) async {
    final result = await _call('GET', '/concierge/monitors', access);
    if (result['monitors'] is! List) throw const ConciergeUnavailable();
    return (result['monitors'] as List)
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
  }

  @override
  Future<void> deleteMonitor(String id, ConciergeAccessLease access) async {
    if (!RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(id)) {
      throw const ConciergeUnavailable();
    }
    await _call('DELETE', '/concierge/monitors/$id', access);
  }
}

class ConciergeExposureBindings {
  final Listenable? accessChanges;
  final ConciergeAccessLease Function() captureAccess;
  final Future<ConciergeInventory> Function(ConciergeAccessLease access)
      loadLogins;
  final Future<Map<String, dynamic>?> Function(ConciergeAccessLease access)
      readEncryptedState;
  final Future<void> Function(
          Map<String, dynamic> data, ConciergeAccessLease access)
      writeEncryptedState;
  final ConciergeExposureProvider provider;
  final PasswordExposureChecker passwordChecker;
  final void Function(String loginId, String title, String itemType)?
      onUpdateLogin;
  const ConciergeExposureBindings(
      {this.accessChanges,
      required this.captureAccess,
      required this.loadLogins,
      required this.readEncryptedState,
      required this.writeEncryptedState,
      required this.provider,
      required this.passwordChecker,
      this.onUpdateLogin});
}

class ConciergeConsent {
  final bool enabled;
  final bool checkOnUnlock;
  final Set<String> approvedEmails;
  final bool backgroundEmails;
  final bool stealerLogs;
  const ConciergeConsent(
      {this.enabled = false,
      this.checkOnUnlock = false,
      this.approvedEmails = const {},
      this.backgroundEmails = false,
      this.stealerLogs = false});
  Map<String, dynamic> toJson() => {
        'enabled': enabled,
        'check_on_unlock': checkOnUnlock,
        'approved_emails': approvedEmails.toList(),
        'background_emails': backgroundEmails,
        'stealer_logs': stealerLogs,
        'version': conciergeConsentVersion
      };
  factory ConciergeConsent.fromJson(Map value) {
    if (value['version'] != conciergeConsentVersion) {
      return const ConciergeConsent();
    }
    return ConciergeConsent(
        enabled: value['enabled'] == true,
        checkOnUnlock: value['check_on_unlock'] == true,
        approvedEmails: (value['approved_emails'] is List
            ? (value['approved_emails'] as List)
                .whereType<String>()
                .map(canonicalConciergeEmail)
                .whereType<String>()
                .toSet()
            : <String>{}),
        backgroundEmails: value['background_emails'] == true,
        stealerLogs: value['stealer_logs'] == true);
  }
}

class ConciergeFinding {
  final String loginId;
  final String title;
  final String itemType;
  final String kind;
  final int count;
  final String? detail;
  final DateTime? checkedAt;
  final bool stale;
  const ConciergeFinding(
      {required this.loginId,
      required this.title,
      required this.kind,
      this.itemType = 'login',
      this.count = 0,
      this.detail,
      this.checkedAt,
      this.stale = false});
  ConciergeFinding asStale() => ConciergeFinding(
      loginId: loginId,
      title: title,
      kind: kind,
      itemType: itemType,
      count: count,
      detail: detail,
      checkedAt: checkedAt,
      stale: true);
  Map<String, dynamic> toJson() => {
        'login_id': loginId,
        'title': title,
        'item_type': itemType,
        'kind': kind,
        'count': count,
        'checked_at': checkedAt?.toUtc().toIso8601String(),
        'stale': stale,
        if (detail != null) 'detail': detail
      };
  factory ConciergeFinding.fromJson(Map value) => ConciergeFinding(
      loginId: '${value['login_id'] ?? ''}',
      title: '${value['title'] ?? 'Saved login'}',
      itemType: '${value['item_type'] ?? 'login'}',
      kind: '${value['kind'] ?? 'unknown'}',
      count: (value['count'] as num?)?.toInt() ?? 0,
      detail: value['detail'] is String ? value['detail'] : null,
      checkedAt: value['checked_at'] is String
          ? DateTime.tryParse(value['checked_at'])
          : null,
      stale: value['stale'] == true);
}

class ConciergeExposureController extends ChangeNotifier {
  final ConciergeExposureBindings bindings;
  final DateTime Function() clock;
  ConciergeConsent consent = const ConciergeConsent();
  ConciergeProviderCapabilities capabilities =
      const ConciergeProviderCapabilities();
  List<ConciergeFinding> findings = [];
  List<Map<String, dynamic>> monitorRows = [];
  Map<String, String> _monitorIds = {};
  Set<String> _pendingRevocations = {};
  DateTime? lastAttemptAt;
  DateTime? lastPasswordCheckAt;
  DateTime? lastEmailCheckAt;
  String passwordStatus = 'not_checked';
  String emailStatus = 'not_checked';
  String? issue;
  bool loading = false;
  bool checking = false;
  bool stateReady = false;
  bool _disposed = false;
  int checkedPasswords = 0;
  int unavailablePasswords = 0;
  int unreadableRecords = 0;
  int _run = 0;
  bool _revocationUnknown = false;
  ConciergeExposureController(this.bindings, {DateTime Function()? clock})
      : clock = clock ?? DateTime.now;
  bool get revocationPending =>
      _pendingRevocations.isNotEmpty || _revocationUnknown;
  bool get hasBackgroundAuthorization =>
      consent.backgroundEmails || _monitorIds.isNotEmpty || revocationPending;
  bool get hasPastEmailCoverage =>
      lastEmailCheckAt != null || findings.any(_isEmailFinding);
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  void _assert(ConciergeAccessLease access, int run) {
    access.assertCurrent();
    if (_disposed || _run != run) throw const ConciergeAccessExpired();
  }

  void lock() {
    _run++;
    findings = [];
    monitorRows = [];
    _monitorIds = {};
    _pendingRevocations = {};
    _revocationUnknown = false;
    consent = const ConciergeConsent();
    loading = checking = false;
    stateReady = false;
    issue = null;
    passwordStatus = emailStatus = 'locked';
    _notify();
  }

  @override
  void dispose() {
    _disposed = true;
    _run++;
    super.dispose();
  }

  Map<String, dynamic> _state() => {
        'schema': 1,
        'consent': consent.toJson(),
        'findings': findings.map((e) => e.toJson()).toList(),
        'monitor_ids': _monitorIds,
        'pending_revocations': _pendingRevocations.toList(),
        'revocation_unknown': _revocationUnknown,
        'password_status': passwordStatus,
        'email_status': emailStatus,
        'last_attempt_at': lastAttemptAt?.toUtc().toIso8601String(),
        'last_password_check_at':
            lastPasswordCheckAt?.toUtc().toIso8601String(),
        'last_email_check_at': lastEmailCheckAt?.toUtc().toIso8601String(),
        'checked_passwords': checkedPasswords,
        'unavailable_passwords': unavailablePasswords,
        'unreadable_records': unreadableRecords
      };
  Future<void> _persist(ConciergeAccessLease access, int run) async {
    _assert(access, run);
    try {
      await bindings.writeEncryptedState(_state(), access);
      _assert(access, run);
    } on ConciergeAccessExpired {
      rethrow;
    } catch (_) {
      issue =
          'Results or preferences could not be saved. Refresh before trying again.';
    }
  }

  bool _isMonitorFinding(ConciergeFinding finding) =>
      finding.kind == 'email_monitor_breach' ||
      finding.kind == 'stealer_domain';

  bool _isEmailFinding(ConciergeFinding finding) =>
      finding.kind == 'email_breach' || _isMonitorFinding(finding);

  List<ConciergeFinding> _monitorFindings(
      List<Map<String, dynamic>> rows, ConciergeInventory inventory) {
    final result = <ConciergeFinding>[];
    for (final row in rows) {
      final successful = row['successful_at'] is String
          ? DateTime.tryParse(row['successful_at'])
          : null;
      final stale = row['status'] == 'unavailable';
      final selectedEmails = _monitorIds.entries
          .where((entry) =>
              entry.value == '${row['id']}' &&
              consent.approvedEmails.contains(entry.key))
          .map((entry) => entry.key)
          .toSet();
      // One authorized monitor belongs to one email; show that known exposure
      // against every currently eligible saved login using this same email.
      // Do not invent a link if the server's ownership anchor no longer exists.
      if (!inventory.logins.any((login) =>
          login.id == '${row['source_item_id']}' &&
          selectedEmails.contains(login.email))) {
        continue;
      }
      final linked = inventory.logins
          .where((login) => selectedEmails.contains(login.email));
      for (final login in linked) {
        for (final breach
            in (row['breaches'] is List ? row['breaches'] as List : const [])
                .whereType<Map>()) {
          result.add(ConciergeFinding(
              loginId: login.id,
              title: login.title,
              itemType: login.itemType,
              kind: 'email_monitor_breach',
              detail: '${breach['title'] ?? breach['name'] ?? 'Known breach'}',
              checkedAt: successful,
              stale: stale));
        }
        for (final domain in (row['stealer_domains'] is List
                ? row['stealer_domains'] as List
                : const [])
            .whereType<String>()) {
          result.add(ConciergeFinding(
              loginId: login.id,
              title: login.title,
              itemType: login.itemType,
              kind: 'stealer_domain',
              detail: domain,
              checkedAt: successful,
              stale: stale));
        }
      }
    }
    return result;
  }

  Future<void> _refreshMonitors(ConciergeInventory inventory,
      ConciergeAccessLease access, int run) async {
    final rows = await bindings.provider.monitors(access);
    _assert(access, run);
    monitorRows =
        rows.where((r) => _monitorIds.containsValue('${r['id']}')).toList();
    findings = [
      ...findings.where((f) => !_isMonitorFinding(f)),
      ..._monitorFindings(monitorRows, inventory)
    ];
  }

  Future<void> hydrate() async {
    final access = bindings.captureAccess();
    final run = ++_run;
    loading = true;
    _notify();
    try {
      _assert(access, run);
      final state = await bindings.readEncryptedState(access);
      _assert(access, run);
      stateReady = true;
      if (state != null && state['schema'] == 1) {
        consent = ConciergeConsent.fromJson(
            state['consent'] is Map ? state['consent'] : {});
        findings =
            (state['findings'] is List ? state['findings'] as List : const [])
                .whereType<Map>()
                .map(ConciergeFinding.fromJson)
                .toList();
        _monitorIds = state['monitor_ids'] is Map
            ? (state['monitor_ids'] as Map).map((k, v) => MapEntry('$k', '$v'))
            : {};
        _pendingRevocations = (state['pending_revocations'] is List
                ? state['pending_revocations'] as List
                : const [])
            .whereType<String>()
            .toSet();
        _revocationUnknown = state['revocation_unknown'] == true;
        DateTime? date(String key) =>
            state[key] is String ? DateTime.tryParse(state[key]) : null;
        lastAttemptAt = date('last_attempt_at');
        lastPasswordCheckAt = date('last_password_check_at');
        lastEmailCheckAt = date('last_email_check_at');
        passwordStatus = '${state['password_status'] ?? 'not_checked'}';
        emailStatus = '${state['email_status'] ?? 'not_checked'}';
        checkedPasswords = (state['checked_passwords'] as num?)?.toInt() ?? 0;
        unavailablePasswords =
            (state['unavailable_passwords'] as num?)?.toInt() ?? 0;
        unreadableRecords = (state['unreadable_records'] as num?)?.toInt() ?? 0;
      }
      try {
        capabilities = await bindings.provider.capabilities(access);
        _assert(access, run);
      } on ConciergeAccessExpired {
        rethrow;
      } catch (_) {
        capabilities = const ConciergeProviderCapabilities(
            emailRangeStatus: 'unavailable',
            emailMonitoringStatus: 'unavailable',
            stealerStatus: 'unavailable');
      }
      if (!capabilities.emailRange) emailStatus = _providerEmailStatus();
      if (consent.enabled &&
          consent.backgroundEmails &&
          _monitorIds.isNotEmpty) {
        try {
          final inventory = await bindings.loadLogins(access);
          _assert(access, run);
          await _refreshMonitors(inventory, access, run);
          _assert(access, run);
        } on ConciergeAccessExpired {
          rethrow;
        } catch (_) {
          findings = findings
              .map((f) => _isMonitorFinding(f) ? f.asStale() : f)
              .toList();
          issue =
              'Background monitoring status is unavailable. Earlier results may be out of date.';
        }
      }
      if (capabilities.emailDeferred) {
        findings =
            findings.map((f) => _isEmailFinding(f) ? f.asStale() : f).toList();
      }
      if (consent.enabled &&
          consent.checkOnUnlock &&
          (lastPasswordCheckAt == null ||
              clock().difference(lastPasswordCheckAt!).inHours >= 24)) {
        loading = false;
        _notify();
        await checkNow();
        return;
      }
    } on ConciergeAccessExpired {
      if (_run == run && !_disposed) lock();
    } catch (_) {
      stateReady = false;
      issue =
          'Saved check settings are unavailable. No checks have been enabled.';
    } finally {
      if (_run == run && !_disposed) {
        loading = false;
        _notify();
      }
    }
  }

  Future<List<ConciergeLoginRecord>> emailChoices() async {
    final access = bindings.captureAccess();
    access.assertCurrent();
    final inventory = await bindings.loadLogins(access);
    access.assertCurrent();
    return inventory.logins.where((e) => e.email != null).toList();
  }

  String _providerEmailStatus() => switch (capabilities.emailRangeStatus) {
        'deferred' => 'deferred',
        'not_configured' => 'provider_not_configured',
        'disabled' => 'provider_disabled',
        'unsupported_plan' => 'provider_plan_unavailable',
        _ => 'unavailable',
      };

  Future<void> configure(ConciergeConsent next) async {
    if (checking || loading || !stateReady) return;
    final access = bindings.captureAccess();
    final run = ++_run;
    loading = true;
    issue = null;
    _notify();
    try {
      _assert(access, run);
      final previous = consent;
      consent = next;
      if (!next.enabled || !next.backgroundEmails) {
        // Discover all owned monitors, including one created just before a
        // lost response/state conflict. Withdrawal must not depend solely on
        // the local encrypted mapping being complete.
        try {
          final rows = await bindings.provider.monitors(access);
          _assert(access, run);
          _pendingRevocations
              .addAll(rows.map((e) => e['id']).whereType<String>());
          _revocationUnknown = false;
        } on ConciergeAccessExpired {
          rethrow;
        } catch (_) {
          _revocationUnknown = _revocationUnknown ||
              previous.backgroundEmails ||
              _monitorIds.isNotEmpty;
        }
      }
      // Revocation is local immediately; failed server deletion is displayed
      // honestly and retained for retry, not described as completed.
      for (final entry in _monitorIds.entries.toList()) {
        if (!next.enabled ||
            !next.backgroundEmails ||
            !next.approvedEmails.contains(entry.key) ||
            previous.stealerLogs != next.stealerLogs) {
          _pendingRevocations.add(entry.value);
          _monitorIds.remove(entry.key);
        }
      }
      for (final id in _pendingRevocations.toList()) {
        try {
          await bindings.provider.deleteMonitor(id, access);
          _assert(access, run);
          _pendingRevocations.remove(id);
        } on ConciergeAccessExpired {
          rethrow;
        } catch (_) {
          issue =
              'Background consent withdrawal is pending. Reconnect and retry.';
        }
      }
      if (_revocationUnknown) {
        issue =
            'Background consent withdrawal is pending. Reconnect and retry.';
      }
      if (next.enabled &&
          next.backgroundEmails &&
          capabilities.emailMonitoring &&
          !revocationPending) {
        final inventory = await bindings.loadLogins(access);
        _assert(access, run);
        for (final email in next.approvedEmails) {
          if (_monitorIds.containsKey(email)) continue;
          final matching =
              inventory.logins.where((e) => e.email == email).toList();
          if (matching.isEmpty) continue;
          final supportedStealer = next.stealerLogs &&
              capabilities.stealerLogs &&
              capabilities.verifiedEmailDomains.contains(email.split('@').last);
          final result = await bindings.provider.createMonitor(
              email, matching.first.id,
              stealerLogs: supportedStealer, access: access);
          _assert(access, run);
          final monitor =
              result['monitor'] is Map ? result['monitor'] as Map : result;
          if (monitor['id'] is! String) throw const ConciergeUnavailable();
          _monitorIds[email] = monitor['id'];
        }
      }
      if (!next.enabled) {
        findings = [];
        monitorRows = [];
        passwordStatus = emailStatus = 'off';
      } else {
        findings = capabilities.emailDeferred
            ? findings.where(_isEmailFinding).map((f) => f.asStale()).toList()
            : [];
        passwordStatus = 'not_checked';
        emailStatus =
            capabilities.emailRange ? 'not_checked' : _providerEmailStatus();
      }
      await _persist(access, run);
    } on ConciergeAccessExpired {
      if (_run == run && !_disposed) lock();
    } catch (_) {
      issue =
          'Consent settings could not be fully applied. Review the status and retry.';
    } finally {
      if (_run == run && !_disposed) {
        loading = false;
        _notify();
      }
    }
  }

  Future<void> retryRevocation() => configure(consent);

  Future<void> withdrawBackgroundConsent() => configure(ConciergeConsent(
      enabled: consent.enabled,
      checkOnUnlock: consent.checkOnUnlock,
      approvedEmails: consent.approvedEmails));

  Future<void> checkNow() async {
    if (checking || loading || !consent.enabled || !stateReady) return;
    final access = bindings.captureAccess();
    final run = ++_run;
    checking = true;
    issue = null;
    lastAttemptAt = clock().toUtc();
    _notify();
    try {
      _assert(access, run);
      final inventory = await bindings.loadLogins(access);
      _assert(access, run);
      final next = <ConciergeFinding>[];
      final byPassword = <String, List<ConciergeLoginRecord>>{};
      for (final login in inventory.logins) {
        final pw = login.password;
        if (pw != null && pw.isNotEmpty) {
          byPassword.putIfAbsent(pw, () => []).add(login);
        }
      }
      var checked = 0;
      var unavailable = 0;
      for (final entry in byPassword.entries) {
        _assert(access, run);
        final pw = entry.key;
        for (final login in entry.value) {
          if (entry.value.length > 1) {
            next.add(ConciergeFinding(
                loginId: login.id,
                title: login.title,
                itemType: login.itemType,
                kind: 'reused',
                count: entry.value.length,
                checkedAt: clock().toUtc()));
          }
          if (pw.length < 12 ||
              RegExp(r'^\d+$').hasMatch(pw) ||
              const ['password', 'qwerty', 'letmein', '123456']
                  .any((p) => pw.toLowerCase().contains(p))) {
            next.add(ConciergeFinding(
                loginId: login.id,
                title: login.title,
                itemType: login.itemType,
                kind: 'weak',
                checkedAt: clock().toUtc()));
          }
        }
        try {
          final result = await bindings.passwordChecker.check(pw);
          _assert(access, run);
          checked += entry.value.length;
          if (result.found) {
            for (final login in entry.value) {
              next.add(ConciergeFinding(
                  loginId: login.id,
                  title: login.title,
                  itemType: login.itemType,
                  kind: 'pwned',
                  count: result.occurrences,
                  checkedAt: clock().toUtc()));
            }
          }
        } on ConciergeAccessExpired {
          rethrow;
        } catch (_) {
          unavailable += entry.value.length;
          next.addAll(findings
              .where((f) =>
                  f.kind == 'pwned' &&
                  entry.value.any((e) => e.id == f.loginId))
              .map((f) => f.asStale()));
        }
      }
      _assert(access, run);
      var emailsChecked = 0;
      var emailsFailed = 0;
      final eligibleEmails = inventory.logins
          .map((e) => e.email)
          .whereType<String>()
          .where(consent.approvedEmails.contains)
          .toSet();
      if (capabilities.emailRange) {
        for (final email in eligibleEmails) {
          try {
            final result = await bindings.provider.checkEmail(email, access);
            _assert(access, run);
            emailsChecked++;
            for (final login
                in inventory.logins.where((e) => e.email == email)) {
              for (final breach in result.breaches) {
                next.add(ConciergeFinding(
                    loginId: login.id,
                    title: login.title,
                    itemType: login.itemType,
                    kind: 'email_breach',
                    checkedAt: clock().toUtc(),
                    detail:
                        '${breach['title'] ?? breach['name'] ?? 'Known breach'}'));
              }
            }
          } on ConciergeAccessExpired {
            rethrow;
          } catch (_) {
            emailsFailed++;
            next.addAll(findings
                .where((f) =>
                    f.kind == 'email_breach' &&
                    inventory.logins
                        .any((e) => e.id == f.loginId && e.email == email))
                .map((f) => f.asStale()));
          }
        }
      } else if (capabilities.emailDeferred) {
        // Keep prior coverage honest without querying the deferred provider.
        // Deleted or no-longer-eligible login IDs must not reappear as results.
        next.addAll(findings
            .where((f) =>
                f.kind == 'email_breach' &&
                inventory.logins.any((login) => login.id == f.loginId))
            .map((f) => f.asStale()));
      }
      if (_monitorIds.isNotEmpty || revocationPending) {
        try {
          final rows = await bindings.provider.monitors(access);
          _assert(access, run);
          monitorRows = rows
              .where((r) => _monitorIds.containsValue('${r['id']}'))
              .toList();
          next.addAll(_monitorFindings(monitorRows, inventory));
        } on ConciergeAccessExpired {
          rethrow;
        } catch (_) {
          next.addAll(
              findings.where(_isMonitorFinding).map((f) => f.asStale()));
          monitorRows = monitorRows
              .map((row) => {...row, 'status': 'unavailable'})
              .toList();
          issue =
              'Background monitoring status is unavailable. Earlier results may be out of date.';
        }
      }
      _assert(access, run);
      findings = capabilities.emailDeferred
          ? next.map((f) => _isEmailFinding(f) ? f.asStale() : f).toList()
          : next;
      checkedPasswords = checked;
      unavailablePasswords = unavailable;
      unreadableRecords = inventory.unreadableRecords;
      passwordStatus = unavailable > 0 || unreadableRecords > 0
          ? 'partial'
          : checked == 0
              ? 'no_eligible_passwords'
              : 'checked';
      emailStatus = !capabilities.emailRange
          ? _providerEmailStatus()
          : emailsFailed > 0
              ? 'unavailable'
              : emailsChecked == 0
                  ? 'not_selected'
                  : 'checked';
      if (checked > 0 && unavailable == 0 && unreadableRecords == 0) {
        lastPasswordCheckAt = clock().toUtc();
      }
      if (emailsChecked > 0 && emailsFailed == 0) {
        lastEmailCheckAt = clock().toUtc();
      }
      await _persist(access, run);
    } on ConciergeAccessExpired {
      if (_run == run && !_disposed) lock();
    } catch (_) {
      issue = 'The check could not finish. No clean result has been confirmed.';
      passwordStatus = 'unavailable';
    } finally {
      if (_run == run && !_disposed) {
        checking = false;
        _notify();
      }
    }
  }
}
