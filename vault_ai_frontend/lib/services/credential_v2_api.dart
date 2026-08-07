import 'dart:convert';

import 'package:http/http.dart' as http;

import 'credential_v2.dart';

const bool zkV2CredentialReadEnabled =
    bool.fromEnvironment('ZK_V2_READ_ENABLED', defaultValue: false);
const bool zkV2CredentialWriteEnabled =
    bool.fromEnvironment('ZK_V2_WRITE_ENABLED', defaultValue: false);
const bool zkV2CredentialMigrationEnabled =
    bool.fromEnvironment('ZK_V2_MIGRATION_ENABLED', defaultValue: false);

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
    final response = await client.put(
      Uri.parse('$baseUrl/vault/v2/credentials/${envelope.recordId}'),
      headers: _headers,
      body: jsonEncode(
        envelope.toRequestBody(migrationOperationId: migrationOperationId),
      ),
    );
    return _envelopeResponse(response);
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
    return decoded
        .map((value) => CredentialV2Envelope.fromResponse(
              Map<String, dynamic>.from(value as Map),
            ))
        .toList(growable: false);
  }

  Future<void> verify(String recordId, String operationId) async {
    final response = await client.post(
      Uri.parse('$baseUrl/vault/v2/credentials/$recordId/verify'),
      headers: _headers,
      body: jsonEncode(<String, dynamic>{
        'operation_id': operationId,
        'semantic_equality_verified': true,
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
      Exception('Credential v2 request failed (${response.statusCode})');
}
