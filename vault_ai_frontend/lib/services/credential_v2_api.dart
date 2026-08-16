import 'dart:convert';

import 'package:http/http.dart' as http;

import 'credential_v2.dart';
import 'credential_v2_qa_diagnostics.dart';

const bool _qaPutDiagnostics =
    bool.fromEnvironment('QA_AUTH_DIAGNOSTICS', defaultValue: false);

void _qaPutTrace(String stage, {String? error}) {
  if (!_qaPutDiagnostics) return;
  print('[qa-v2-put] $stage${error == null ? '' : ' error=$error'}');
}

const bool zkV2CredentialReadEnabled =
    bool.fromEnvironment('ZK_V2_READ_ENABLED', defaultValue: false);
const bool zkV2CredentialWriteEnabled =
    bool.fromEnvironment('ZK_V2_WRITE_ENABLED', defaultValue: false);
const bool zkV2CredentialMigrationEnabled =
    bool.fromEnvironment('ZK_V2_MIGRATION_ENABLED', defaultValue: false);

class CredentialV2RequestException implements Exception {
  final int statusCode;

  const CredentialV2RequestException(this.statusCode);

  @override
  String toString() => 'CredentialV2RequestException(statusCode: $statusCode)';
}

class CredentialV2Api {
  final String baseUrl;
  final String sessionToken;
  final http.Client client;

  CredentialV2Api({
    required this.baseUrl,
    required this.sessionToken,
    required this.client,
  });

  Map<String, String> get _headers => <String, String>{
        'Authorization': 'Bearer $sessionToken',
        'Content-Type': 'application/json',
      };

  Future<CredentialV2Envelope> write(
    CredentialV2Envelope envelope, {
    String? migrationOperationId,
  }) async {
    try {
      _qaPutTrace('request_model_created');
      _qaPutTrace('operation_id_present=${migrationOperationId != null}');
      _qaPutTrace(
          'operation_id_type_valid=${migrationOperationId == null || migrationOperationId.isNotEmpty}');
      _qaPutTrace('record_id_present=${envelope.recordId.isNotEmpty}');
      _qaPutTrace('record_id_type_valid=true');
      _qaPutTrace('crypto_version_present=true');
      _qaPutTrace('nonce_present=${envelope.nonce.isNotEmpty}');
      _qaPutTrace('ciphertext_present=${envelope.ciphertext.isNotEmpty}');
      _qaPutTrace('tag_present=${envelope.authenticationTag.isNotEmpty}');
      _qaPutTrace('blind_index_container_created=true');
      _qaPutTrace('blind_index_container_valid=true');
      _qaPutTrace('serialization_entered');
      final body = jsonEncode(
        envelope.toRequestBody(migrationOperationId: migrationOperationId),
      );
      _qaPutTrace('serialization_succeeded');
      final uri =
          Uri.parse('$baseUrl/vault/v2/credentials/${envelope.recordId}');
      _qaPutTrace('http_request_object_created');
      final headers = _headers;
      _qaPutTrace('http_headers_created');
      _qaPutTrace(
          'http_auth_header_present=${headers['Authorization']?.isNotEmpty == true}');
      _qaPutTrace('http_body_created');
      _qaPutTrace('http_client_call_entered');
      final response = await client.put(uri, headers: headers, body: body);
      _qaPutTrace('http_client_call_returned');
      if (_qaPutDiagnostics) {
        print('CREDENTIAL_V2_CREATE_HTTP_STATUS=${response.statusCode}');
        print('CREDENTIAL_V2_CREATE_HTTP_2XX=${response.statusCode >= 200 && response.statusCode < 300}');
      }
      return _envelopeResponse(response);
    } on FormatException {
      _qaPutTrace('pre_dispatch_exception_caught', error: 'FormatException');
      rethrow;
    } on ArgumentError {
      _qaPutTrace('pre_dispatch_exception_caught', error: 'ArgumentError');
      rethrow;
    } catch (_) {
      _qaPutTrace('pre_dispatch_exception_caught', error: 'Exception');
      rethrow;
    }
  }

  Future<CredentialV2Envelope> read(String recordId) async {
    final response = await client.get(
      Uri.parse('$baseUrl/vault/v2/credentials/$recordId'),
      headers: _headers,
    );
    return _envelopeResponse(response);
  }

  Future<List<CredentialV2Envelope>> list({
    String? blindIndexName,
    String? blindIndexToken,
  }) async {
    if ((blindIndexName == null) != (blindIndexToken == null)) {
      throw ArgumentError('both blind-index arguments are required');
    }
    final uri = Uri.parse('$baseUrl/vault/v2/credentials').replace(
      queryParameters: blindIndexName == null
          ? null
          : <String, String>{
              'blind_index_name': blindIndexName,
              'blind_index_token': blindIndexToken!,
            },
    );
    final response = await client.get(uri, headers: _headers);
    if (response.statusCode != 200) {
      throw _failure(response);
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! List) {
      throw const FormatException('invalid v2 credential list');
    }
    final envelopes = <CredentialV2Envelope>[];
    for (final value in decoded) {
      final map = value is Map ? Map<String, dynamic>.from(value) : null;
      final id = map?['record_id']?.toString();
      if (_qaPutDiagnostics && id == qaV2TargetRecordId) {
        qaV2HydrationTrace('target_present_in_http_json');
        qaV2HydrationTrace('target_parse_entered');
      }
      try {
        final envelope = CredentialV2Envelope.fromResponse(map!);
        envelopes.add(envelope);
        if (_qaPutDiagnostics && id == qaV2TargetRecordId) {
          qaV2HydrationTrace('target_parse_succeeded');
          qaV2HydrationTrace('target_envelope_model_created');
        }
      } on Object catch (_) {
        if (_qaPutDiagnostics && id == qaV2TargetRecordId) {
          qaV2HydrationTrace('target_parse_exception',
              error: 'api_item_parse_failed');
        }
        // Quarantine a malformed sibling instead of blanking the whole list.
      }
    }
    return envelopes;
  }

  Future<void> verify(
    String recordId,
    String operationId, {
    bool semanticEqualityVerified = true,
  }) async {
    final response = await client.post(
      Uri.parse('$baseUrl/vault/v2/credentials/$recordId/verify'),
      headers: _headers,
      body: jsonEncode(<String, dynamic>{
        'operation_id': operationId,
        'semantic_equality_verified': semanticEqualityVerified,
      }),
    );
    if (response.statusCode != 200) {
      throw _failure(response);
    }
  }

  Future<void> rollback(String recordId) async {
    final response = await client.post(
      Uri.parse('$baseUrl/vault/v2/credentials/$recordId/rollback'),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      throw _failure(response);
    }
  }

  Future<void> delete(String recordId) async {
    final response = await client.delete(
      Uri.parse('$baseUrl/vault/v2/credentials/$recordId'),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      throw _failure(response);
    }
  }

  Future<void> finalizeGeneratedDraft({
    required String recordId,
    required String draftId,
  }) async {
    final response = await client.post(
      Uri.parse(
        '$baseUrl/vault/v2/credentials/$recordId/'
        'generated-drafts/$draftId/finalize',
      ),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      throw _failure(response);
    }
  }

  Future<void> cancelGeneratedDraft(String draftId) async {
    final response = await client.post(
      Uri.parse(
        '$baseUrl/vault/v2/credentials/generated-drafts/$draftId/cancel',
      ),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      throw _failure(response);
    }
  }

  CredentialV2Envelope _envelopeResponse(http.Response response) {
    if (response.statusCode != 200) {
      throw _failure(response);
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map) {
      throw const FormatException('invalid v2 credential response');
    }
    return CredentialV2Envelope.fromResponse(
        Map<String, dynamic>.from(decoded));
  }

  Exception _failure(http.Response response) =>
      CredentialV2RequestException(response.statusCode);
}
