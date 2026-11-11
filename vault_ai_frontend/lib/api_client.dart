import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kReleaseMode;
import 'package:cryptography/cryptography.dart' show SecretKey, Sha256;
import 'package:http/http.dart' as http;

import 'logins_page.dart' show isSystemHiddenItemType;
import 'services/asset_catalog.dart' show parseAssetBaseUnits;
import 'services/auth_retry.dart';
import 'services/memory_title_identity.dart';
import 'services/saved_file_rename.dart';
import 'services/session_termination.dart' as st;
import 'services/zk_pin_free_item_read_session.dart';
import 'services/zk_pin_free_file_session.dart';
import 'services/zk_proof_token_guard.dart';
import 'services/zk_auth_service.dart' show kSignedBeneficiaryClientEnabled;
import 'services/saved_item_mutation_feedback.dart';
export 'services/saved_item_mutation_feedback.dart'
    show SavedItemUpdateRequiredException, savedItemUpdateRequiredMessage;
import 'services/vault_handle.dart' as vault_handle;
import 'services/vault_key_hierarchy.dart' as vault_key_hierarchy;
import 'services/zk_active_mvk.dart' as zk_mvk_store;
import 'services/zk_private_chat.dart' as zk_private_chat;
import 'services/zk_general_chat_bridge.dart' as zk_general_bridge;
import 'services/file_v2_reader.dart';
import 'services/file_v2_renamer.dart';
import 'services/file_v2_writer.dart';
import 'services/inheritance_v2_file_stream_transfer.dart';
import 'services/inheritance_v2_file_stage.dart' show inheritedTargetFileId;
import 'services/inheritance_v2_file_batch_transfer.dart';
import 'services/inheritance_mvk_v2.dart' show decryptInheritanceMvk;
import 'services/linked_inheritance_v2_stage.dart' as linked_inh_stage;
import 'services/linked_inheritance_v2_keycheck.dart' as linked_inh_keycheck;
import 'services/linked_inheritance_v2_release_readback.dart'
    as linked_inh_release;
import 'services/linked_inheritance_v2_readback_proof.dart'
    as linked_inh_proof;
import 'services/linked_inheritance_v2_item_import.dart'
    as linked_inh_items;
import 'services/linked_inheritance_v2_legacy_item_import.dart'
    as linked_inh_legacy_items;
import 'services/linked_inheritance_v2_mixed_item_import.dart'
    as linked_inh_mixed_items;
import 'services/linked_inheritance_v2_memory_import.dart'
    as linked_inh_memory;
import 'services/zk_active_sk_vault.dart' as zk_sk_store;
import 'services/private_content_pin_guard.dart' as private_content_guard;

// Only builds with the MVK V2 file reader advertise this capability. The
// server uses it to avoid handing V2 file owners to an incompatible client.
const bool kFileV2ReaderCapability = bool.fromEnvironment(
  'VAULTAI_ENABLE_FILE_V2_UI_READ',
  defaultValue: false,
);

// Paired with the server's separate active-copy gate. Off until the owner
// device can read and mutate prepared older Memory records end to end.
const bool kEnableLegacyMemoryV2ActiveRead = bool.fromEnvironment(
  'VAULTAI_ENABLE_LEGACY_MEMORY_V2_ACTIVE_READ',
  defaultValue: false,
);

// After the coordinated ZK file cutover, legacy file endpoints must never
// receive a PIN from an unlocked MVK vault. Legacy-only vaults still use
// these endpoints; the V2 and ciphertext migration routes do not call them.
const bool kRequirePinFreeZkFiles = bool.fromEnvironment(
  'VAULTAI_ENABLE_ZK_FILE_PIN_FREE_ONLY',
  defaultValue: false,
);

/// A newer or older device changed files after this session's list offer.
/// The caller must obtain a new offer; retrying the same bearer cannot fix it.
class ZkLegacyFileListChangedException implements Exception {
  const ZkLegacyFileListChangedException();

  @override
  String toString() => 'Files changed. Sign in once to refresh access.';
}

bool _memoryGenerationConflict(String body) {
  try {
    final decoded = jsonDecode(body);
    return decoded is Map &&
        (decoded['detail'] == 'memory_inventory_changed' ||
            decoded['detail'] == 'memory_inventory_generation_required');
  } catch (_) {
    return false;
  }
}

// The private-only unlock build cannot use inheritance routes that require
// the server to derive a content key from a raw PIN. The OPAQUE-proof
// beneficiary actions use separate methods and remain available.
const bool kEnableZkPrivateOnlyUnlock = bool.fromEnvironment(
  'VAULTAI_ENABLE_ZK_PRIVATE_ONLY_UNLOCK',
  defaultValue: false,
);

void requireLegacyBeneficiaryPinActionAllowed({String? vaultHandle}) {
  if (kEnableZkPrivateOnlyUnlock &&
      (vaultHandle?.isNotEmpty == true ||
          zk_mvk_store.ZkActiveMvk.current() != null)) {
    throw StateError('Private inheritance setup is not available yet.');
  }
}

void _rejectBeneficiaryPin(String authToken, String? pin) {
  if (pin != null &&
      (kSignedBeneficiaryClientEnabled ||
          (_signedOfferBits(authToken) & 64) != 0)) {
    throw StateError('Private inheritance action needs a one-time proof.');
  }
}

bool _beneficiaryProofRouteRequired(String authToken) =>
    kEnableZkPrivateOnlyUnlock || kSignedBeneficiaryClientEnabled ||
    (_signedOfferBits(authToken) & 64) != 0;

void _rejectLegacyFilePinForActiveZk() {
  if (kRequirePinFreeZkFiles && zk_mvk_store.ZkActiveMvk.current() != null) {
    throw StateError('Private file needs migration before this action.');
  }
}

void _rejectOfferedLegacyFileDownload(String authToken) {
  if (signedFileDownloadOfferedForToken(authToken) ||
      ZkPinFreeFileSession.instance.downloadOfferedForToken(authToken)) {
    throw StateError('This file uses the private download route.');
  }
}

void _rejectOfferedLegacyFileCreate(String authToken) {
  if (signedFileCreateOfferedForToken(authToken)) {
    throw StateError('This file uses the private upload route.');
  }
}

// Coordinated rollout with VAULTAI_ZK_METADATA_INVENTORY_ENABLED on the API.
// A missing keyless route must fail closed instead of sending a ZK PIN.
const bool kEnableKeylessSavedItemRead = bool.fromEnvironment(
  'VAULTAI_ENABLE_KEYLESS_SAVED_ITEM_READ',
  defaultValue: false,
);

// Requires a staged, locally verified legacy ciphertext replacement route.
// The old source remains active until a fresh OPAQUE proof promotes it.
const bool kEnableKeylessLegacySavedItemEdit = bool.fromEnvironment(
  'VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_EDIT',
  defaultValue: false,
) && kEnableKeylessSavedItemRead;

const bool kEnableKeylessLegacySavedItemRename = bool.fromEnvironment(
  'VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_RENAME',
  defaultValue: false,
) && kEnableKeylessLegacySavedItemEdit;

const bool kEnableKeylessLegacySavedItemDelete = bool.fromEnvironment(
  'VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_DELETE',
  defaultValue: false,
) && kEnableKeylessSavedItemRead;

// A narrow ZK index cutover. Legacy item details still use their existing
// reader, while list/search preflights can use the trusted metadata inventory.
// Coordinate with VAULTAI_ZK_METADATA_INVENTORY_ENABLED on the API.
const bool kEnableZkPinFreeSavedItemIndex = bool.fromEnvironment(
  'VAULTAI_ENABLE_ZK_PIN_FREE_SAVED_ITEM_INDEX',
  defaultValue: false,
);

// Enable only alongside the trusted-session metadata inventory. A ZK write
// must never use a PIN-bearing list or mutation route for its preflight.
const bool kEnableKeylessSavedItemWrite = bool.fromEnvironment(
  'VAULTAI_ENABLE_KEYLESS_SAVED_ITEM_WRITE',
  defaultValue: false,
);

const bool kPrivateOnlyTransportRejectPin = bool.fromEnvironment(
  'VAULTAI_ENABLE_ZK_PRIVATE_ONLY_UNLOCK',
  defaultValue: false,
);

// This marker additionally scopes an OPAQUE session after unlock. The strict
// build-wide transport fence below also rejects PIN requests before sign-in;
// a legacy-only account needs a separate recovery path, not a raw-PIN escape.
class PrivateZkPinTransportSession {
  static int? _sessionEpoch;
  static String? _sessionFingerprint;

  static void bind(String sessionToken) {
    if (!kPrivateOnlyTransportRejectPin) return;
    final scope = st.SessionTermination.instance.captureRequest(sessionToken);
    if (!st.SessionTermination.instance.isCurrentRequest(scope)) {
      throw StateError('Private vault session changed.');
    }
    _sessionEpoch = scope.sessionEpoch;
    _sessionFingerprint = scope.sessionFingerprint;
  }

  static void clear() {
    _sessionEpoch = null;
    _sessionFingerprint = null;
  }

  static bool get active =>
      kPrivateOnlyTransportRejectPin &&
      _sessionFingerprint != null &&
      _sessionEpoch == st.SessionTermination.instance.sessionEpoch &&
      st.SessionTermination.instance.hasBoundSession &&
      !st.SessionTermination.instance.isTerminated;
}

bool _isRawPinFieldName(Object? name) {
  final normalized = name.toString().toLowerCase().replaceAll('-', '_');
  return normalized == 'pin' || normalized.endsWith('_pin');
}

bool _containsRawPinField(Object? value) {
  if (value is Map) {
    for (final entry in value.entries) {
      // A multipart protocol metadata field may itself contain JSON. Other
      // string values can be user content (for example a chat prompt about a
      // JSON document) and must not be mistaken for a request PIN field.
      if (entry.key.toString().toLowerCase() == 'metadata' &&
          entry.value is String) {
        try {
          if (_containsRawPinField(jsonDecode(entry.value as String))) {
            return true;
          }
        } on FormatException {
          // Treat a non-JSON metadata value as ordinary text.
        }
      }
      if (_isRawPinFieldName(entry.key) ||
          _containsRawPinField(entry.value)) {
        return true;
      }
    }
  } else if (value is Iterable) {
    for (final entry in value) {
      if (_containsRawPinField(entry)) return true;
    }
  }
  return false;
}

bool _requestBodyContainsPin(Object? body, {Map<String, String>? headers}) {
  Object? parsed = body;
  if (body is List<int>) {
    // The caller may omit or mislabel Content-Type. A byte-encoded JSON PIN
    // must still be rejected before the HTTP client sends any bytes. Multipart
    // file content is handled separately by inspecting only its form fields.
    try {
      parsed = utf8.decode(body);
    } on FormatException {
      return false;
    }
  }
  final textBody = parsed;
  if (textBody is String) {
    try {
      parsed = jsonDecode(textBody);
    } on FormatException {
      try {
        return Uri.splitQueryString(textBody).keys.any(_isRawPinFieldName);
      } on FormatException {
        return RegExp(r'(^|[?&])pin=', caseSensitive: false)
            .hasMatch(textBody);
      }
    }
  }
  return _containsRawPinField(parsed);
}

bool _requestMetadataContainsPin(Uri uri, Map<String, String>? headers) {
  if (uri.queryParametersAll.keys.any(_isRawPinFieldName)) return true;
  return headers?.keys.any(_isRawPinFieldName) ?? false;
}

/// Catch PIN requests throughout a strict build before transport, including
/// before OPAQUE sign-in and after a vault session changes.
void assertPrivateOnlyPinFreeBody(Object? body) {
  if (!kPrivateOnlyTransportRejectPin || body == null) return;
  if (_requestBodyContainsPin(body)) {
    throw StateError('Raw PIN requests are unavailable in private mode.');
  }
}

/// One outbound boundary for ordinary, streamed and multipart API requests.
/// The private-only fence is opt-in at build time while the default build
/// retains legacy access during migration.
/// Signed offers additionally fence their own old routes in ordinary builds.
void assertOutboundPinFreeRequest(
  Uri uri,
  Map<String, String>? headers, {
  Object? body,
}) {
  // The private key can become active after a legacy chat/deep-answer method
  // selected its route. Recheck the session at the last outbound boundary;
  // those old endpoints decrypt on the server and cannot use a local MVK.
  final path = uri.path.replaceFirst(RegExp(r'/+$'), '');
  if ((path == '/chat' &&
          private_content_guard.blocksZkLegacyContentRoute()) ||
      ((path == '/vault-analysis/deep-answer' ||
              RegExp(r'^/vault-analysis/deep-answer/[^/]+/poll$')
                  .hasMatch(path)) &&
          private_content_guard.blocksZkDeepAnswerPinRoute())) {
    throw StateError('This session uses private local chat.');
  }
  // A vault can acquire its private unlock key while the delete dialog is
  // open. Recheck at the outbound boundary, after the request was selected.
  if (uri.path == '/vault/delete/confirm' &&
      zk_mvk_store.ZkActiveMvk.current() != null &&
      (_requestMetadataContainsPin(uri, headers) ||
          _requestBodyContainsPin(body, headers: headers))) {
    throw StateError('Private vault deletion requires an OPAQUE proof.');
  }
  // Keep the old analyzer fenced if a vault adopts OPAQUE after the screen
  // collected credentials but before the request reaches transport.
  if (uri.path == '/security-center/analyze-passwords' &&
      zk_mvk_store.ZkActiveMvk.current() != null &&
      (_requestMetadataContainsPin(uri, headers) ||
          _requestBodyContainsPin(body, headers: headers))) {
    throw StateError('Use local password analysis for this vault.');
  }
  if (kPrivateOnlyTransportRejectPin &&
      (_requestMetadataContainsPin(uri, headers) ||
          _requestBodyContainsPin(body, headers: headers))) {
    throw StateError('Raw PIN requests are unavailable in private mode.');
  }
  assertOfferedReadPinFreeRequest(uri, headers, body: body);
}

/// Unknown streamed request bodies cannot be inspected before transmission.
/// Files in multipart requests are user content; inspect fields, not bytes.
void assertOutboundPinFreeBaseRequest(http.BaseRequest request) {
  final Object? body;
  if (request is http.Request) {
    body = request.body;
  } else if (request is http.MultipartRequest) {
    body = request.fields;
  } else {
    if (kPrivateOnlyTransportRejectPin) {
      throw StateError('Uninspectable private request body.');
    }
    body = null;
  }
  assertOutboundPinFreeRequest(request.url, request.headers, body: body);
}

Future<http.StreamedResponse> _sendCheckedBaseRequest(
  http.BaseRequest request,
  http.Client? client,
) {
  assertOutboundPinFreeBaseRequest(request);
  return client?.send(request) ?? request.send();
}

/// Use the same outbound PIN boundary for the few direct HTTP calls outside
/// VaultAIClient. The optional client supports an in-memory transport test.
Future<http.Response> sendPinCheckedHttp(
  String method,
  Uri uri, {
  Map<String, String>? headers,
  Object? body,
  http.Client? client,
}) {
  assertOutboundPinFreeRequest(uri, headers, body: body);
  switch (method) {
    case 'GET':
      if (body != null) throw StateError('GET body is unavailable');
      return client?.get(uri, headers: headers) ?? http.get(uri, headers: headers);
    case 'POST':
      return client?.post(uri, headers: headers, body: body) ??
          http.post(uri, headers: headers, body: body);
    case 'PUT':
      return client?.put(uri, headers: headers, body: body) ??
          http.put(uri, headers: headers, body: body);
    default:
      throw StateError('Unsupported private request method');
  }
}

int _signedOfferBits(String token) {
  try {
    final wire = base64Url.decode(base64Url.normalize(token));
    if (wire.length == 48 || wire.isEmpty) return 0;
    if (wire[0] == 3) {
      if (wire.length != 50 || (wire[1] & ~255) != 0) return 255;
      return wire[1];
    }
    if (wire[0] == 4) {
      if (wire.length != 51) return 4095;
      final offers = (wire[1] << 8) | wire[2];
      if ((offers & ~4095) != 0 || offers <= 255 ||
          ((offers & 512) != 0 && (offers & 7) != 7) ||
          ((offers & 2048) != 0 && (offers & 1) == 0)) {
        return 4095;
      }
      return offers;
    }
    return 0;
  } on FormatException {
    return 0;
  }
}

bool signedPrivateChatOfferedForToken(String token) =>
    (_signedOfferBits(token) & 512) != 0;

bool signedPasswordAnalysisOfferedForToken(String token) =>
    (_signedOfferBits(token) & 16) != 0;

bool signedFileListOfferedForToken(String token) =>
    (_signedOfferBits(token) & 2) != 0;

bool signedFileDownloadOfferedForToken(String token) =>
    (_signedOfferBits(token) & 4) != 0;

bool signedFileCreateOfferedForToken(String token) =>
    (_signedOfferBits(token) & 8) != 0;

bool signedFileMutationOfferedForToken(String token) =>
    (_signedOfferBits(token) & 32) != 0;

bool signedAuthDeviceOfferedForToken(String token) =>
    (_signedOfferBits(token) & 128) != 0;

bool signedImportOfferedForToken(String token) =>
    (_signedOfferBits(token) & 256) != 0;

bool signedSavedItemMutationOfferedForToken(String token) =>
    (_signedOfferBits(token) & 2048) != 0;

/// An authenticated OPAQUE offer replaces specific older routes for the life
/// of that bearer. Reject those paths before transport, including requests
/// whose body omitted the PIN but could still contain the raw vault name.
/// Upload-token continuation paths are separate PIN-free contracts.
void assertOfferedReadPinFreeRequest(
  Uri uri,
  Map<String, String>? headers, {
  Object? body,
}) {
  final authorization = headers?['Authorization'] ?? headers?['authorization'];
  if (authorization == null || !authorization.startsWith('Bearer ')) return;
  final token = authorization.substring(7);
  if (token.isEmpty) return;
  final signedOffers = _signedOfferBits(token);
  // FastAPI can redirect a trailing slash while preserving the POST body.
  final path = uri.path.replaceFirst(RegExp(r'/+$'), '');
  if ((signedOffers & 1) != 0 &&
      (const <String>{
        '/vault-analysis/coverage',
        '/vault-analysis/drain-text-extraction',
        '/vault-analysis/backfill-chunked-text-extraction',
        '/vault-analysis/backfill-archive-signals',
      }.contains(path) ||
          RegExp(r'^/vault/file/[^/]+/text$').hasMatch(path))) {
    throw StateError('This older analysis route is unavailable in private mode.');
  }
  if (signedAuthDeviceOfferedForToken(token) &&
      const <String>{
        '/get-or-create-vault-meta', '/verify-pin', '/rotate-vault-kdf',
        '/vault-stats', '/devices/request-self-approval',
        '/devices/finalize-self-approval', '/vault/delete/confirm',
      }.contains(path)) {
    throw StateError('This action uses the private vault route.');
  }
  if ((signedOffers & 256) != 0 &&
      (path == '/imports/start' ||
       RegExp(r'^/imports/[^/]+/(cancel|complete)$').hasMatch(path))) {
    throw StateError('This import action uses the private vault route.');
  }
  if ((signedOffers & 2048) != 0 &&
      (path == '/update-secure-item' || path == '/delete-secure-item')) {
    throw StateError('This saved-item action uses the private vault route.');
  }
  if ((signedOffers & 32) != 0 &&
      (path == '/name-file' || path == '/manage/file' ||
          path == '/manage/file/delete' || path == '/delete-file')) {
    throw StateError('This file action uses the private vault route.');
  }
  final fileSession = ZkPinFreeFileSession.instance;
  final itemSession = ZkPinFreeItemReadSession.instance;
  final offered = switch (path) {
    '/list-files' =>
      (signedOffers & 2) != 0 || fileSession.listOfferedForToken(token),
    '/download-file' || '/download-file/manifest' =>
      (signedOffers & 4) != 0 || fileSession.downloadOfferedForToken(token),
    '/list-secure-items' || '/get-secure-item' ||
    '/list-login-names' || '/get-login' || '/login-count' ||
    '/manage/list-login-names' || '/manage/list-secure-items' ||
    '/manage/logins-full' =>
      (signedOffers & 1) != 0 || itemSession.wasOfferedForToken(token),
    '/chat' || '/vault-analysis/deep-answer' =>
      (signedOffers & 512) != 0,
    _ when RegExp(r'^/vault-analysis/deep-answer/[^/]+/(poll|debug)$')
        .hasMatch(path) => (signedOffers & 512) != 0,
    _ when RegExp(r'^/files/[^/]+/related$').hasMatch(path) =>
      (signedOffers & 518) != 0 || fileSession.listOfferedForToken(token) ||
          fileSession.downloadOfferedForToken(token),
    '/upload-file' || '/upload-file/init' ||
    '/upload-file/finalize' || '/upload-file/abort' ||
    '/upload-file/chunk' || '/upload-file/finalize-token' ||
    '/upload-file/abort-token' =>
      (signedOffers & 8) != 0,
    '/security-center/analyze-passwords' => (signedOffers & 16) != 0,
    '/memory/list' || '/memory/create' || '/memory/update' ||
    '/memory/delete' => (signedOffers & 1024) != 0,
    '/beneficiary/create' || '/beneficiary/link' ||
    '/beneficiary/list-mine' || '/beneficiary/list-inheritances' ||
    '/beneficiary/request-transfer' ||
    '/beneficiary/cancel-transfer' || '/beneficiary/claim-transfer' ||
    '/beneficiary/delete' => (signedOffers & 64) != 0,
    _ => false,
  };
  if (!offered) return;
  // These three continuation paths authenticate with an upload token. Every
  // other path above is the retired PIN contract and must not be sent at all.
  if (path != '/upload-file/chunk' &&
      path != '/upload-file/finalize-token' &&
      path != '/upload-file/abort-token') {
    throw StateError('This action uses the private vault route.');
  }
  if (_requestBodyContainsPin(body, headers: headers) ||
      _requestMetadataContainsPin(uri, headers)) {
    throw StateError('This upload uses the private vault route.');
  }
}

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
  final text = value.toString();
  if (value is Map) {
    return '{${value.entries.map((entry) {
      final nestedKey = entry.key.toString();
      return '$nestedKey: ${_safeVlogValue(tag, nestedKey, entry.value)}';
    }).join(', ')}}';
  }
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
      lowerKey.contains('error') ||
      lowerKey.contains('exception') ||
      lowerKey.contains('stack') ||
      lowerKey == 'body' ||
      lowerKey == 'response_body' ||
      lowerKey == 'errorbody' ||
      lowerKey == 'prompt' ||
      lowerKey == 'query' ||
      lowerKey == 'message') {
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

class SavedItemConflictException implements Exception {
  final bool duplicate;
  const SavedItemConflictException({this.duplicate = false});
  @override
  String toString() => duplicate
      ? 'A saved item already uses this title. Choose a different title or edit it.'
      : 'More than one saved item has this title. Select the specific item from Logins.';
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

/// An older app cannot enter the coordinated private-only server mode. Keep
/// the current session intact so the owner can update this app first.
class ClientUpgradeRequiredException implements Exception {
  static const message = 'Update SVaultAI to continue with private access.';
  const ClientUpgradeRequiredException();

  @override
  String toString() => message;
}

bool isClientUpgradeRequiredResponse(int statusCode, String body) {
  if (statusCode != 426) return false;
  try {
    final decoded = jsonDecode(body);
    final detail = decoded is Map ? decoded['detail'] : null;
    return detail is Map && detail['code'] == 'client_upgrade_required';
  } on FormatException {
    return false;
  }
}

void throwIfClientUpgradeRequired(int statusCode, String body) {
  if (isClientUpgradeRequiredResponse(statusCode, body)) {
    throw const ClientUpgradeRequiredException();
  }
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
  final st.SessionRequestScope? requestScope;
  final bool handledBySessionCore;
  const SessionTerminatedException({
    required this.code,
    required this.message,
    this.requestScope,
    this.handledBySessionCore = false,
  });
  @override
  String toString() => 'SessionTerminatedException(code: $code)';
}

/// A previous request is obsolete, not evidence that the current login died.
class StaleSessionResponseException implements Exception {
  const StaleSessionResponseException();
  @override
  String toString() => 'StaleSessionResponseException([redacted])';
}

enum SessionValidity { valid, terminated, indeterminate }

/// A local header snapshot keeps its request epoch out of the wire format.
class _SessionHeaders extends MapBase<String, String> {
  _SessionHeaders(this._values, this.scope);
  final Map<String, String> _values;
  final st.SessionRequestScope scope;
  @override
  String? operator [](Object? key) => _values[key];
  @override
  void operator []=(String key, String value) => _values[key] = value;
  @override
  Iterable<String> get keys => _values.keys;
  @override
  void clear() => _values.clear();
  @override
  String? remove(Object? key) => _values.remove(key);
}

st.SessionRequestScope? _requestScopeFor(Map<String, String>? headers) {
  if (headers is _SessionHeaders) return headers.scope;
  final authorization = headers?['Authorization'];
  if (authorization == null || !authorization.startsWith('Bearer ')) {
    return null;
  }
  return st.SessionTermination.instance
      .captureRequest(authorization.substring(7));
}

void _assertCurrentRequest(st.SessionRequestScope? scope) {
  if (scope != null && !st.SessionTermination.instance.canUseRequest(scope)) {
    throw const StaleSessionResponseException();
  }
}

void _checkSessionResponse(
    int statusCode, String body, st.SessionRequestScope? scope) {
  _assertCurrentRequest(scope);
  throwIfClientUpgradeRequired(statusCode, body);
  if (scope == null) return;
  if (statusCode == 403) {
    try {
      final decoded = jsonDecode(body);
      final detail = decoded is Map ? decoded['detail'] : null;
      final code = detail is Map ? detail['code'] : null;
      if (code == 'device_not_trusted' ||
          code == 'missing_device_id' ||
          code == 'device_revoked') {
        throw DeviceNotTrustedException.fromResponseBody(body,
            requestScope: scope);
      }
    } on DeviceNotTrustedException {
      rethrow;
    } on FormatException {
      // An unclassified 403 cannot prove session termination.
    }
    return;
  }
  if (statusCode != 401) return;
  final code = VaultAIClient._extractSessionTerminationCode(body);
  if (code == null) return;
  final service = st.SessionTermination.instance;
  final handled = service.isCurrentRequest(scope);
  if (handled) {
    // The service starts its guarded cleanup synchronously. Never initiate a
    // second cleanup from a delayed UI error boundary after a newer login.
    unawaited(service
        .handle(code, request: scope)
        .then<void>((_) {}, onError: (Object _, StackTrace __) {}));
  }
  throw SessionTerminatedException(
    code: code,
    message: st.userMessageFor(code),
    requestScope: scope,
    handledBySessionCore: handled,
  );
}

/// Stateless request boundary: no concurrent request state on VaultAIClient.
/// Each invocation captures its own token/epoch and rejects stale responses,
/// including successes, before existing endpoint-specific decoding runs.
class _SessionBoundHttp {
  const _SessionBoundHttp(
      {http.Client? client, void Function()? beforeResponse})
      : _client = client,
        _beforeResponse = beforeResponse;

  final http.Client? _client;
  final void Function()? _beforeResponse;

  Future<http.Response> _send(Uri url, Map<String, String>? headers,
      Future<http.Response> Function() send, {Object? body}) async {
    assertOutboundPinFreeRequest(url, headers, body: body);
    final scope = _requestScopeFor(headers);
    _assertCurrentRequest(scope);
    final response = await send();
    // A stricter private-operation lease can change while the bearer remains
    // current. Preserve its existing rejection before global auth side effects.
    _beforeResponse?.call();
    _checkSessionResponse(response.statusCode, response.body, scope);
    return response;
  }

  Future<http.Response> get(Uri url, {Map<String, String>? headers}) => _send(
      url, headers,
      () =>
          _client?.get(url, headers: headers) ??
          http.get(url, headers: headers));

  Future<http.Response> post(Uri url,
          {Map<String, String>? headers, Object? body, Encoding? encoding}) =>
      _send(
          url, headers,
          () =>
              _client?.post(url,
                  headers: headers, body: body, encoding: encoding) ??
              http.post(url, headers: headers, body: body, encoding: encoding),
          body: body);

  Future<http.Response> put(Uri url,
          {Map<String, String>? headers, Object? body, Encoding? encoding}) =>
      _send(
          url, headers,
          () =>
              _client?.put(url,
                  headers: headers, body: body, encoding: encoding) ??
              http.put(url, headers: headers, body: body, encoding: encoding),
          body: body);

  Future<http.Response> patch(Uri url,
          {Map<String, String>? headers, Object? body, Encoding? encoding}) =>
      _send(
          url, headers,
          () =>
              _client?.patch(url,
                  headers: headers, body: body, encoding: encoding) ??
              http.patch(url,
                  headers: headers, body: body, encoding: encoding),
          body: body);

  Future<http.Response> delete(Uri url,
          {Map<String, String>? headers, Object? body, Encoding? encoding}) =>
      _send(
          url, headers,
          () =>
              _client?.delete(url,
                  headers: headers, body: body, encoding: encoding) ??
              http.delete(url,
                  headers: headers, body: body, encoding: encoding),
          body: body);
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

class MemorySaveReadbackException implements Exception {
  const MemorySaveReadbackException();

  @override
  String toString() =>
      'Memory may have been saved. Open Memory to check before retrying.';
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
  if (kPrivateOnlyTransportRejectPin) {
    throw StateError('Older PIN-based chat is unavailable in private mode.');
  }
  return <String, dynamic>{
    'encrypted_message': encryptedMessage,
    'vault_name': '',
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
  final st.SessionRequestScope? requestScope;

  const DeviceNotTrustedException({
    required this.message,
    this.deviceId,
    this.status = 'unknown',
    this.requestScope,
  });

  factory DeviceNotTrustedException.fromResponseBody(String body,
      {st.SessionRequestScope? requestScope}) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        final detail = decoded['detail'];
        if (detail is Map) {
          return DeviceNotTrustedException(
            requestScope: requestScope,
            message:
                (detail['message'] ?? 'This device is not trusted.').toString(),
            deviceId: detail['device_id']?.toString(),
            status: (detail['status'] ?? 'unknown').toString(),
          );
        }
      }
    } catch (_) {}
    return DeviceNotTrustedException(
      requestScope: requestScope,
      message: 'This device is not trusted.',
    );
  }

  @override
  String toString() => 'DeviceNotTrustedException([redacted])';
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
  final http.Client? _httpClient;
  final Future<Map<String, dynamic>> Function(int itemId)? legacyZkItemReader;
  final Future<Map<String, dynamic>> Function({
    required int itemId,
    required String itemType,
    required String oldService,
    String? newService,
    Map<String, dynamic>? fields,
  })? legacyZkItemUpdater;
  final Future<void> Function({
    required int itemId,
    required String itemType,
    required String service,
  })? legacyZkItemDeleter;

  /// Captured key/session lease used only by the new registered-asset client.
  /// Existing clients omit this and retain their normal request behavior.
  final bool Function()? walletResponseIsCurrent;
  // A remembered session is checked before the vault UI is available. Never
  // let a stalled auth/me request block startup indefinitely.
  final Duration authMeTimeout;

  const VaultAIClient({
    required this.baseUrl,
    this.walletResponseIsCurrent,
    this.authMeTimeout = const Duration(seconds: 12),
    this.legacyZkItemReader,
    this.legacyZkItemUpdater,
    this.legacyZkItemDeleter,
    http.Client? httpClient,
  }) : _httpClient = httpClient;

  _SessionBoundHttp get _sessionHttp => _SessionBoundHttp(client: _httpClient);
  _SessionBoundHttp _sessionHttpWithGuard(void Function()? beforeResponse) =>
      _SessionBoundHttp(client: _httpClient, beforeResponse: beforeResponse);
  _SessionBoundHttp get _walletHttp =>
      _sessionHttpWithGuard(_assertWalletResponseCurrent);

  void _assertWalletResponseCurrent() {
    if (walletResponseIsCurrent != null && !walletResponseIsCurrent!()) {
      throw StateError('Asset wallet access changed');
    }
  }

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
        handledBySessionCore: true,
      );
    }
    final headers = <String, String>{};

    if (kFileV2ReaderCapability) {
      headers['X-SVaultAI-File-V2-Reader'] = '1';
    }

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

    return authToken == null || authToken.isEmpty
        ? headers
        : _SessionHeaders(
            headers, st.SessionTermination.instance.captureRequest(authToken));
  }

  Future<Map<String, dynamic>> authLogin({
    required String vaultName,
    required String pin,
  }) async {
    if (kPrivateOnlyTransportRejectPin) {
      throw StateError('Legacy PIN sign-in is unavailable in private mode.');
    }
    final uri = Uri.parse('$baseUrl/auth/login');
    final headers = _defaultHeaders(json: true);
    final body = jsonEncode({
      'username_lookup': vault_handle.vaultHandleB64Url(
        vault_handle.deriveUsernameLookupV1(vaultName),
      ),
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
        () => _sessionHttp.post(uri, headers: headers, body: body),
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
    if (response.statusCode == 503 &&
        isAuthServiceUnavailableResponse(response.body)) {
      throw const AuthServiceUnavailableException();
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
      () => _sessionHttp
          .get(uri, headers: _defaultHeaders(authToken: authToken))
          .timeout(authMeTimeout),
    );
    _throwIfAuthExpired(response.statusCode, response.body);
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

  /// Read-only probe of the existing /auth/me contract. No accounts or data
  /// are created. Offline/uncoded authorization failures remain indeterminate.
  Future<SessionValidity> checkSessionValidity(
      {required String authToken}) async {
    final service = st.SessionTermination.instance;
    final scope = service.captureRequest(authToken);
    try {
      await authMe(authToken: authToken);
      return service.isCurrentRequest(scope)
          ? SessionValidity.valid
          : SessionValidity.indeterminate;
    } on SessionTerminatedException catch (error) {
      // A replacement login already won this race; do not label it terminated.
      if (!service.wasTerminatedRequest(scope)) {
        return SessionValidity.indeterminate;
      }
      return error.handledBySessionCore
          ? SessionValidity.terminated
          : SessionValidity.indeterminate;
    } catch (_) {
      return SessionValidity.indeterminate;
    }
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
    // The readable vault name is local-only. Keep this compatibility method
    // for call sites that update local state, but never transmit the value.
    if (authToken.isEmpty) throw const AuthExpiredException();
    final local = vaultName?.trim();
    return local == null || local.isEmpty ? null : local;
  }

  Future<void> authLogout({required String authToken}) async {
    if (authToken.isEmpty) return;
    final uri = Uri.parse('$baseUrl/auth/logout');
    // Sign-out clears the local session first. The regular bound transport
    // correctly rejects that retired token, so send this one revocation
    // request directly to its fixed logout route with the captured token.
    // No other endpoint can use this unbound path.
    final headers = _defaultHeaders()..['Authorization'] = 'Bearer $authToken';
    assertOutboundPinFreeRequest(uri, headers);
    final response = await _runWithNetLog(
      'auth.logout',
      uri,
      () => _httpClient?.post(uri, headers: headers) ??
          http.post(uri, headers: headers),
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
      () =>
          _sessionHttp.get(uri, headers: _defaultHeaders(authToken: authToken)),
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
      () => _sessionHttp.post(uri,
          headers: _defaultHeaders(authToken: authToken)),
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
    String? pin,
    String? zkProofToken,
    required String confirmationPhrase,
  }) async {
    if (pin != null || zkProofToken == null || zkProofToken.isEmpty) {
      throw StateError('Private vault deletion requires an OPAQUE proof.');
    }
    rejectPinShapedZkProof(zkProofToken);
    final uri = Uri.parse('$baseUrl/vault/delete/confirm-proof');
    final body = jsonEncode({
      'request_token': requestToken,
      'zk_proof_token': zkProofToken,
      'confirmation_phrase': confirmationPhrase,
    });
    final response = await _runWithNetLog(
      'vault.delete.confirm',
      uri,
      () => _sessionHttp.post(
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
    final response = await _sessionHttp.post(
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
      () => _sessionHttp.get(uri, headers: headers),
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
    final response = await _sessionHttp.get(
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

  Future<Map<String, dynamic>> getBillingMe({
    required String authToken,
  }) async {
    final uri = Uri.parse('$baseUrl/billing/me');
    final headers = _defaultHeaders(authToken: authToken);
    _vlogRequest('billing.me', uri, headers);
    final response = await _runWithNetLog(
      'billing.me',
      uri,
      () => _sessionHttp.get(uri, headers: headers),
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
    final headers = _defaultHeaders(authToken: authToken);
    _vlogRequest('billing.providers', uri, headers);
    final response = await _runWithNetLog(
      'billing.providers',
      uri,
      () => _sessionHttp.get(uri, headers: headers),
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
      throw Exception('Invalid billing providers response format');
    }
    return decoded;
  }

  /// Sends StoreKit 2's signed transaction JWS to the backend. Storage is
  /// granted only after Apple signature, bundle, environment, product, expiry,
  /// and app-account binding checks pass server-side.
  Future<Map<String, dynamic>> verifyAppleStoragePurchase({
    required String authToken,
    required String signedTransaction,
  }) async {
    final uri = Uri.parse('$baseUrl/billing/apple/verify-transaction');
    final headers = _defaultHeaders(authToken: authToken, json: true);
    _vlogRequest('billing.apple.verify', uri, headers);
    final response = await _runWithNetLog(
      'billing.apple.verify',
      uri,
      () => _sessionHttp.post(
        uri,
        headers: headers,
        body: jsonEncode({'signed_transaction': signedTransaction}),
      ),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'App Store purchase verification failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid App Store verification response format');
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
      () => _sessionHttp.get(uri, headers: headers),
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
      'vault_name': '',
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
      () => _sessionHttp.post(uri, headers: headers, body: jsonEncode(body)),
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
      'vault_name': '',
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
      () => _sessionHttp.post(uri, headers: headers, body: jsonEncode(body)),
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

  Future<Map<String, dynamic>> analyzePasswords({
    required String authToken,
    required String vaultName,
    required String pin,
    int? cursor,
    int? limit,
  }) async {
    // The local analyzer handles OPAQUE vaults. Keep this old public method
    // as a fail-closed compatibility stub so no caller can revive the
    // server-side analyzer by holding a legacy bearer or losing the MVK.
    throw StateError('Use local password analysis for this vault.');
  }

  Future<Map<String, dynamic>> approveDevice({
    required String authToken,
    required String deviceId,
  }) async {
    final uri = Uri.parse('$baseUrl/devices/approve');
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.post(
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

  Future<Map<String, dynamic>> postPendingDeviceOpaque(
    String path,
    Map<String, dynamic> body, {
    required String authToken,
  }) async {
    if (path != '/auth/zk-pending-verify-init' &&
        path != '/auth/zk-pending-verify-finalize') {
      throw ArgumentError.value(path, 'path', 'Not a pending-device proof path');
    }
    final response = await _sessionHttp.post(
      Uri.parse('$baseUrl$path'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Pending-device verification failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid pending-device verification response');
    }
    return decoded;
  }

  Map<String, dynamic> _pinOrZkProofBody({
    String? pin,
    String? zkProofToken,
  }) {
    if ((pin == null) == (zkProofToken == null) ||
        (pin != null && pin.isEmpty) ||
        (zkProofToken != null && zkProofToken.isEmpty)) {
      throw ArgumentError('Exactly one credential is required');
    }
    return zkProofToken != null
        ? {'zk_proof_token': zkProofToken}
        : {'pin': pin};
  }

  Future<Map<String, dynamic>> requestSelfApproval({
    required String authToken,
    String vaultName = '',
    String? pin,
    String? zkProofToken,
  }) async {
    final proofOnly = zkProofToken != null || kEnableZkPrivateOnlyUnlock ||
        signedAuthDeviceOfferedForToken(authToken) ||
        zk_mvk_store.ZkActiveMvk.current() != null;
    if (proofOnly &&
        (pin != null || zkProofToken == null || zkProofToken.isEmpty)) {
      throw StateError('Private device approval requires an OPAQUE proof.');
    }
    final uri = Uri.parse(proofOnly
        ? '$baseUrl/devices/request-self-approval-proof'
        : '$baseUrl/devices/request-self-approval');
    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(_pinOrZkProofBody(
        pin: pin,
        zkProofToken: zkProofToken,
      )),
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
    String vaultName = '',
    String? pin,
    String? zkProofToken,
  }) async {
    final proofOnly = zkProofToken != null || kEnableZkPrivateOnlyUnlock ||
        signedAuthDeviceOfferedForToken(authToken) ||
        zk_mvk_store.ZkActiveMvk.current() != null;
    if (proofOnly &&
        (pin != null || zkProofToken == null || zkProofToken.isEmpty)) {
      throw StateError('Private device approval requires an OPAQUE proof.');
    }
    final uri = Uri.parse(proofOnly
        ? '$baseUrl/devices/finalize-self-approval-proof'
        : '$baseUrl/devices/finalize-self-approval');
    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(_pinOrZkProofBody(
        pin: pin,
        zkProofToken: zkProofToken,
      )),
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
    final response = await _sessionHttp.post(
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

  /// Separate PIN-free general chat. Call only after the local ZK router
  /// returns `general`; vault records and private lookup results stay local.
  Future<String> zkGeneralChat({
    required String authToken,
    required String message,
    required String vaultName,
    List<zk_private_chat.ZkGeneralChatTurn> history = const [],
    void Function()? accessGuard,
  }) async {
    accessGuard?.call();
    // This endpoint sees plaintext. Reject private prompts again at transport
    // so another caller cannot bypass the UI router and disclose vault text.
    // Assistant turns are not user-authored and may contain a private local
    // reply supplied by a caller. Never serialize them to general AI.
    if (history.any((turn) =>
        turn.role != 'user' && turn.role != 'assistant')) {
      throw StateError('Invalid general chat history');
    }
    final safeUserHistory = history
        .where((turn) => turn.role == 'user')
        .toList(growable: false);
    if (vaultName.trim().isEmpty ||
        !zk_general_bridge.isClearlyGeneralChatPrompt(
            message, vaultName: vaultName) ||
        safeUserHistory.any((turn) =>
            !zk_general_bridge.isClearlyGeneralChatPrompt(
                turn.content, vaultName: vaultName))) {
      throw StateError('Question needs the private vault chat route');
    }
    final uri = Uri.parse('$baseUrl/chat/zk/general');
    final body = zk_private_chat.buildZkGeneralChatBody(
      message: message,
      history: safeUserHistory,
    );
    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    accessGuard?.call();
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'General chat failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    accessGuard?.call();
    if (decoded is! Map<String, dynamic> ||
        decoded['mode'] != 'general' ||
        decoded['reply'] is! String ||
        (decoded['reply'] as String).trim().isEmpty) {
      throw const FormatException('Invalid general chat response');
    }
    return (decoded['reply'] as String).trim();
  }

  /// Read only the ciphertext endpoints needed by the ephemeral private
  /// search index. No PIN, MVK, private query text, or decrypted content is
  /// included in these requests.
  Future<Object?> zkPrivateChatCiphertextGet({
    required String authToken,
    required String path,
    void Function()? accessGuard,
  }) async {
    final filePath = RegExp(
      r'^/vault/file-v2/[^/?#]+/(?:manifest|chunk/[0-9]+)$',
    );
    if (path != '/vault/ciphertext/vault-items' &&
        path != '/vault/file-v2' &&
        !filePath.hasMatch(path)) {
      throw ArgumentError.value(path, 'path', 'Unsupported private search route');
    }
    accessGuard?.call();
    final response = await _sessionHttpWithGuard(accessGuard).get(
      Uri.parse('$baseUrl$path'),
      headers: _defaultHeaders(authToken: authToken),
    );
    accessGuard?.call();
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwIfLockOrFrozen(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Private search failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body);
  }

  Stream<String> chatStream({
    required String encryptedMessage,
    required String vaultName,
    required String pin,
    required String authToken,
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
    if (kPrivateOnlyTransportRejectPin ||
        signedPrivateChatOfferedForToken(authToken)) {
      throw StateError('This session uses private chat.');
    }
    final uri = Uri.parse('$baseUrl/chat');

    final requestScope =
        st.SessionTermination.instance.captureRequest(authToken);
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
    _vlogRequest('chat.stream', uri, headers);
    _vlog('chat.body', {
      'vault_name': '',
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

    _assertCurrentRequest(requestScope);
    final response = await _sendCheckedBaseRequest(request, _httpClient);
    _assertCurrentRequest(requestScope);
    _vlog('chat.response', {
      'status': response.statusCode,
      'content_type': response.headers['content-type'] ?? '-',
    });

    if (response.statusCode != 200) {
      final errorBody = await response.stream.bytesToString();
      _checkSessionResponse(response.statusCode, errorBody, requestScope);

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
      _assertCurrentRequest(requestScope);
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

    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'username_lookup': vault_handle.vaultHandleB64Url(
          vault_handle.deriveUsernameLookupV1(vaultName),
        ),
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

    final response = await _sessionHttp.get(
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

  Future<Map<String, dynamic>> startDeepAnswer({
    required String pin,
    required String authToken,
    String? vaultHandle,
    String intent = 'search_files_for_credentials',
    String query = '',
    String? resumeJobId,
  }) async {
    if (kPrivateOnlyTransportRejectPin ||
        signedPrivateChatOfferedForToken(authToken) ||
        private_content_guard.blocksZkDeepAnswerPinRoute(
        vaultHandle: vaultHandle)) {
      throw const private_content_guard.PrivateContentSearchUnavailable(
        private_content_guard.deepScanPrivateMessage,
      );
    }
    final uri = Uri.parse('$baseUrl/vault-analysis/deep-answer');
    final headers = _defaultHeaders(authToken: authToken, json: true);
    final body = jsonEncode({
      'pin': pin,
      'intent': intent,
      'query': query,
      if (resumeJobId != null && resumeJobId.isNotEmpty) 'job_id': resumeJobId,
    });
    final response = await _sessionHttp.post(uri, headers: headers, body: body);
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
    String? vaultHandle,
  }) async {
    if (kPrivateOnlyTransportRejectPin ||
        signedPrivateChatOfferedForToken(authToken) ||
        private_content_guard.blocksZkDeepAnswerPinRoute(
        vaultHandle: vaultHandle)) {
      throw const private_content_guard.PrivateContentSearchUnavailable(
        private_content_guard.deepScanPrivateMessage,
      );
    }
    final uri = Uri.parse(
      '$baseUrl/vault-analysis/deep-answer/$jobId/poll',
    );
    final headers = _defaultHeaders(authToken: authToken, json: true);
    final body = jsonEncode({'pin': pin});
    final response = await _sessionHttp.post(uri, headers: headers, body: body);
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
      '?vault_name=',
    );

    final response = await _sessionHttp.get(uri, headers: headers);

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

  Future<Map<String, dynamic>> createBeneficiary({
    required String vaultName,
    required String pin,
    required String label,
    required String authToken,
  }) async {
    _rejectBeneficiaryPin(authToken, pin);
    requireLegacyBeneficiaryPinActionAllowed();
    final response = await _sessionHttp.post(
      Uri.parse('$baseUrl/beneficiary/create'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': '',
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

  Future<Map<String, dynamic>> createZkBeneficiary({
    required String passerLabelCiphertext,
    required String zkProofToken,
    required String authToken,
    void Function()? accessGuard,
  }) async {
    accessGuard?.call();
    final response = await _sessionHttpWithGuard(accessGuard).post(
      Uri.parse('$baseUrl/beneficiary/zk-create'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'passer_label_ciphertext': passerLabelCiphertext,
        'zk_proof_token': zkProofToken,
      }),
    );
    accessGuard?.call();
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Create beneficiary failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// Resolve only the pairing protocol of an unused code. This transitional,
  /// authenticated lookup lets an OPAQUE vault with existing old links choose
  /// the V2 proof-only linker for new invitations while preserving old codes.
  Future<String> beneficiaryPairingProtocol({
    required String pairingCode,
    required String authToken,
    void Function()? accessGuard,
  }) async {
    accessGuard?.call();
    final response = await _sessionHttpWithGuard(accessGuard).post(
      Uri.parse('$baseUrl/beneficiary/pairing-protocol'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({'pairing_code': pairingCode}),
    );
    accessGuard?.call();
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw StateError('Pairing code check is unavailable.');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> ||
        !const {'private', 'legacy', 'unknown'}
            .contains(decoded['protocol'])) {
      throw const FormatException('Invalid pairing code check');
    }
    return decoded['protocol'] as String;
  }

  Future<Map<String, dynamic>> linkZkBeneficiary({
    required String pairingCode,
    required String zkProofToken,
    required String authToken,
    void Function()? accessGuard,
  }) async {
    accessGuard?.call();
    final response = await _sessionHttpWithGuard(accessGuard).post(
      Uri.parse('$baseUrl/beneficiary/zk-link'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'pairing_code': pairingCode,
        'zk_proof_token': zkProofToken,
      }),
    );
    accessGuard?.call();
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Link beneficiary failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getReleasedInheritanceV2VaultItems({
    required int linkId,
    required String authToken,
  }) async {
    if (linkId <= 0) throw ArgumentError('Invalid inheritance link');
    final response = await _sessionHttp.get(
      Uri.parse('$baseUrl/inheritance/v2/$linkId/vault-items'),
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Inherited private items unavailable',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Invalid inheritance export');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> linkBeneficiary({
    required String vaultName,
    required String pin,
    required String pairingCode,
    required String authToken,
  }) async {
    _rejectBeneficiaryPin(authToken, pin);
    requireLegacyBeneficiaryPinActionAllowed();
    final response = await _sessionHttp.post(
      Uri.parse('$baseUrl/beneficiary/link'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': '',
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
    String? pin,
    String? zkProofToken,
    required String authToken,
    // 2026-07-22: optional client-generated request id. When set,
    // sent as X-Client-Request-Id so the ClientException-vs-200
    // distinction visible in nginx access logs can be correlated
    // with the specific failed invocation on the device. NOT used
    // for auth, NOT logged if unset. Bounded to 64 chars.
    String? clientRequestId,
  }) async {
    _rejectBeneficiaryPin(authToken, pin);
    if (_beneficiaryProofRouteRequired(authToken) &&
        (pin != null || zkProofToken == null || zkProofToken.isEmpty)) {
      throw StateError('Private inheritance access requires an OPAQUE proof.');
    }
    final headers = _defaultHeaders(authToken: authToken, json: true);
    if (clientRequestId != null && clientRequestId.isNotEmpty) {
      final cri = clientRequestId.length > 64
          ? clientRequestId.substring(0, 64)
          : clientRequestId;
      headers['X-Client-Request-Id'] = cri;
    }
    final response = await _sessionHttp.post(
      Uri.parse(_beneficiaryProofRouteRequired(authToken)
          ? '$baseUrl/beneficiary/proof/list-mine'
          : '$baseUrl/beneficiary/list-mine'),
      headers: headers,
      body: jsonEncode(_pinOrZkProofBody(
        pin: pin,
        zkProofToken: zkProofToken,
      )),
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
      await _sessionHttp.post(
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
    String? pin,
    String? zkProofToken,
    required String authToken,
  }) async {
    _rejectBeneficiaryPin(authToken, pin);
    if (_beneficiaryProofRouteRequired(authToken) &&
        (pin != null || zkProofToken == null || zkProofToken.isEmpty)) {
      throw StateError('Private inheritance access requires an OPAQUE proof.');
    }
    final response = await _sessionHttp.post(
      Uri.parse(_beneficiaryProofRouteRequired(authToken)
          ? '$baseUrl/beneficiary/proof/list-inheritances'
          : '$baseUrl/beneficiary/list-inheritances'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(_pinOrZkProofBody(
        pin: pin,
        zkProofToken: zkProofToken,
      )),
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
    _rejectBeneficiaryPin(authToken, pin);
    requireLegacyBeneficiaryPinActionAllowed();
    final response = await _sessionHttp.post(
      Uri.parse('$baseUrl/beneficiary/claim-transfer'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'link_id': linkId,
        'vault_name': '',
        'pin': pin,
        'inherited_username_lookup': vault_handle.vaultHandleB64Url(
          vault_handle.deriveUsernameLookupV1(
            inheritedVaultName != null && inheritedVaultName.isNotEmpty
                ? inheritedVaultName
                : 'Inherited vault',
          ),
        ),
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
    final response = await _sessionHttp.get(
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
    String? pin,
    String? zkProofToken,
    required String authToken,
  }) async {
    // This endpoint starts the older clone flow. A private beneficiary cannot
    // complete that claim without sending a PIN and decrypting on the server.
    if (kEnableZkPrivateOnlyUnlock || kSignedBeneficiaryClientEnabled ||
        (_signedOfferBits(authToken) & 64) != 0) {
      throw StateError('Older inheritance transfer is unavailable with private access.');
    }
    requireLegacyBeneficiaryPinActionAllowed();
    _rejectBeneficiaryPin(authToken, pin);
    final response = await _sessionHttp.post(
      Uri.parse('$baseUrl/beneficiary/request-transfer'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'link_id': linkId,
        ..._pinOrZkProofBody(pin: pin, zkProofToken: zkProofToken),
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
    String? pin,
    String? zkProofToken,
    required String authToken,
  }) async {
    _rejectBeneficiaryPin(authToken, pin);
    if (_beneficiaryProofRouteRequired(authToken) &&
        (pin != null || zkProofToken == null || zkProofToken.isEmpty)) {
      throw StateError('Private inheritance access requires an OPAQUE proof.');
    }
    final response = await _sessionHttp.post(
      Uri.parse(_beneficiaryProofRouteRequired(authToken)
          ? '$baseUrl/beneficiary/proof/cancel-transfer'
          : '$baseUrl/beneficiary/cancel-transfer'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'link_id': linkId,
        ..._pinOrZkProofBody(pin: pin, zkProofToken: zkProofToken),
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
    String? pin,
    String? zkProofToken,
    required String authToken,
  }) async {
    _rejectBeneficiaryPin(authToken, pin);
    if (_beneficiaryProofRouteRequired(authToken) &&
        (pin != null || zkProofToken == null || zkProofToken.isEmpty)) {
      throw StateError('Private inheritance access requires an OPAQUE proof.');
    }
    final response = await _sessionHttp.post(
      Uri.parse(_beneficiaryProofRouteRequired(authToken)
          ? '$baseUrl/beneficiary/proof/delete'
          : '$baseUrl/beneficiary/delete'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'link_id': linkId,
        if (!_beneficiaryProofRouteRequired(authToken)) 'vault_name': '',
        ..._pinOrZkProofBody(pin: pin, zkProofToken: zkProofToken),
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
    final response = await _sessionHttp.get(
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
    final response = await _sessionHttp.get(
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

  /// Stage a PIN-free owner MVK envelope beside an unchanged linked old link.
  /// The caller supplies a separately confirmed beneficiary fingerprint and
  /// a fresh local OPAQUE action proof. This does not switch the old link.
  Future<linked_inh_stage.StagedLinkedInheritanceV2>
      stageLinkedOldInheritanceV2({
    required String authToken,
    required int linkId,
    required String ownerVaultId,
    required SecretKey ownerMvk,
    SecretKey? ownerLegacyKey,
    required String confirmedBeneficiaryFingerprint,
    required String zkProofToken,
    int? expectedStageRevision,
    bool Function()? responseIsCurrent,
  }) async {
    void checkAccess() {
      _requireSavedItemKey(ownerMvk);
      if (zk_mvk_store.ZkActiveMvk.currentVaultId() != ownerVaultId ||
          !identical(zk_mvk_store.ZkActiveMvk.current(), ownerMvk) ||
          responseIsCurrent?.call() == false) {
        throw StateError('Private inheritance access changed');
      }
    }

    Future<Map<String, dynamic>> request(
      String method,
      String path, [
      Map<String, dynamic>? body,
    ]) async {
      checkAccess();
      final uri = Uri.parse('$baseUrl$path');
      final headers = _defaultHeaders(
        authToken: authToken,
        json: method == 'POST',
      );
      final transport = _sessionHttpWithGuard(checkAccess);
      final response = method == 'POST'
          ? await transport.post(uri, headers: headers, body: jsonEncode(body))
          : await transport.get(uri, headers: headers);
      checkAccess();
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw StateError('Private inheritance stage unavailable');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid private inheritance response');
      }
      return decoded;
    }

    checkAccess();
    return linked_inh_stage.stageLinkedOldInheritanceV2(
      linkId: linkId,
      ownerVaultId: ownerVaultId,
      ownerMvk: ownerMvk,
      ownerLegacyKey: ownerLegacyKey,
      confirmedBeneficiaryFingerprint: confirmedBeneficiaryFingerprint,
      zkProofToken: zkProofToken,
      expectedStageRevision: expectedStageRevision,
      fetchPubkey: (id) => getInheritanceBeneficiaryPubKey(
        linkId: id,
        authToken: authToken,
      ),
      stage: (body) => request(
        'POST',
        '/inheritance/old-link-v2/stage',
        body,
      ),
      readback: (id) => request(
        'GET',
        '/inheritance/old-link-v2/$id/readback',
      ),
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  /// Check beneficiary key possession using a random challenge. The owner
  /// package stays private and the old link remains authoritative.
  Future<linked_inh_keycheck.LinkedBeneficiaryKeyCheck>
      verifyLinkedOldInheritanceBeneficiaryKey({
    required String authToken,
    required int linkId,
    required String beneficiaryVaultId,
    required SecretKey beneficiaryPrivateKey,
    required String zkProofToken,
    bool Function()? responseIsCurrent,
  }) async {
    const enabled = bool.fromEnvironment(
      'VAULTAI_ENABLE_LINKED_INHERITANCE_KEYCHECK',
      defaultValue: false,
    );
    if (!enabled) {
      throw StateError('Linked inheritance key check is unavailable');
    }
    void checkAccess() {
      if (zk_sk_store.ZkActiveSkVault.currentVaultId() !=
              beneficiaryVaultId ||
          !identical(zk_sk_store.ZkActiveSkVault.current(),
              beneficiaryPrivateKey) ||
          responseIsCurrent?.call() == false) {
        throw StateError('Beneficiary vault access changed');
      }
    }

    Future<Map<String, dynamic>> request(String path,
        [Map<String, dynamic>? body]) async {
      checkAccess();
      final response = await _sessionHttpWithGuard(checkAccess).post(
        Uri.parse('$baseUrl$path'),
        headers: _defaultHeaders(authToken: authToken, json: true),
        body: jsonEncode(body ?? <String, dynamic>{}),
      );
      checkAccess();
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw StateError('Beneficiary key check unavailable');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid beneficiary key check response');
      }
      return decoded;
    }

    checkAccess();
    return linked_inh_keycheck.verifyLinkedBeneficiaryKey(
      linkId: linkId,
      beneficiaryPrivateKey: beneficiaryPrivateKey,
      zkProofToken: zkProofToken,
      fetchChallenge: (id) => request(
        '/inheritance/old-link-v2/$id/beneficiary-challenge',
      ),
      submitResponse: (body) => request(
        '/inheritance/old-link-v2/beneficiary-keycheck', body,
      ),
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  /// Read a linked old-link V2 package only after the server's existing
  /// approval/cooldown state releases it. The old package remains available.
  Future<linked_inh_release.ReleasedLinkedInheritanceV2>
      readReleasedLinkedOldInheritanceV2({
    required String authToken,
    required int linkId,
    required String beneficiaryVaultId,
    required SecretKey beneficiaryPrivateKey,
    bool Function()? responseIsCurrent,
  }) async {
    const enabled = bool.fromEnvironment(
      'VAULTAI_ENABLE_LINKED_INHERITANCE_RELEASE_READBACK',
      defaultValue: false,
    );
    if (!enabled) {
      throw StateError('Linked inheritance release is unavailable');
    }
    void checkAccess() {
      if (zk_sk_store.ZkActiveSkVault.currentVaultId() !=
              beneficiaryVaultId ||
          !identical(zk_sk_store.ZkActiveSkVault.current(),
              beneficiaryPrivateKey) ||
          responseIsCurrent?.call() == false) {
        throw StateError('Beneficiary vault access changed');
      }
    }

    checkAccess();
    return linked_inh_release.readReleasedLinkedInheritanceV2(
      linkId: linkId,
      beneficiaryPrivateKey: beneficiaryPrivateKey,
      fetchReleased: (id) async {
        checkAccess();
        final response = await _sessionHttpWithGuard(checkAccess).post(
          Uri.parse(
            '$baseUrl/inheritance/old-link-v2/$id/released-package',
          ),
          headers: _defaultHeaders(authToken: authToken),
        );
        checkAccess();
        if (response.statusCode != 200) {
          _throwIfAuthExpired(response.statusCode, response.body);
          _throwIfDeviceNotTrusted(response.statusCode, response.body);
          throw StateError('Released inheritance package unavailable');
        }
        final decoded = jsonDecode(response.body);
        if (decoded is! Map<String, dynamic>) {
          throw const FormatException('Invalid inheritance package response');
        }
        return decoded;
      },
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  /// Register a public proof verifier derived locally from the owner MVK.
  /// The old linked package and release state remain unchanged.
  Future<linked_inh_proof.LinkedReadbackVerifier>
      registerLinkedOldInheritanceReadbackVerifier({
    required String authToken,
    required linked_inh_stage.StagedLinkedInheritanceV2 staged,
    required String ownerVaultId,
    required SecretKey ownerMvk,
    required String zkProofToken,
    bool Function()? responseIsCurrent,
  }) async {
    const enabled = bool.fromEnvironment(
      'VAULTAI_ENABLE_LINKED_INHERITANCE_READBACK_PROOF',
      defaultValue: false,
    );
    if (!enabled) {
      throw StateError('Linked inheritance readback proof is unavailable');
    }
    void checkAccess() {
      _requireSavedItemKey(ownerMvk);
      if (zk_mvk_store.ZkActiveMvk.currentVaultId() != ownerVaultId ||
          !identical(zk_mvk_store.ZkActiveMvk.current(), ownerMvk) ||
          responseIsCurrent?.call() == false) {
        throw StateError('Owner vault access changed');
      }
    }

    Future<Map<String, dynamic>> request(
      String method, String path, [Map<String, dynamic>? body]
    ) async {
      checkAccess();
      final transport = _sessionHttpWithGuard(checkAccess);
      final uri = Uri.parse('$baseUrl$path');
      final response = method == 'POST'
          ? await transport.post(
              uri,
              headers: _defaultHeaders(authToken: authToken, json: true),
              body: jsonEncode(body ?? <String, dynamic>{}),
            )
          : await transport.get(
              uri, headers: _defaultHeaders(authToken: authToken),
            );
      checkAccess();
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw StateError('Owner readback verifier unavailable');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid readback verifier response');
      }
      return decoded;
    }

    checkAccess();
    return linked_inh_proof.registerLinkedReadbackVerifier(
      staged: staged,
      ownerVaultId: ownerVaultId,
      ownerMvk: ownerMvk,
      zkProofToken: zkProofToken,
      fetchReadback: (id) => request(
        'GET', '/inheritance/old-link-v2/$id/readback',
      ),
      submitVerifier: (body) => request(
        'POST', '/inheritance/old-link-v2/readback-verifier', body,
      ),
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  /// Prove local owner-MVK decryption after the existing release gate opens.
  /// The proof body contains only a challenge signature, never the MVK.
  Future<linked_inh_proof.LinkedReadbackReceipt>
      proveReleasedLinkedOldInheritanceReadback({
    required String authToken,
    required int linkId,
    required String beneficiaryVaultId,
    required SecretKey beneficiaryPrivateKey,
    required String zkProofToken,
    bool Function()? responseIsCurrent,
  }) async {
    const enabled = bool.fromEnvironment(
      'VAULTAI_ENABLE_LINKED_INHERITANCE_READBACK_PROOF',
      defaultValue: false,
    );
    if (!enabled) {
      throw StateError('Linked inheritance readback proof is unavailable');
    }
    void checkAccess() {
      if (zk_sk_store.ZkActiveSkVault.currentVaultId() !=
              beneficiaryVaultId ||
          !identical(zk_sk_store.ZkActiveSkVault.current(),
              beneficiaryPrivateKey) ||
          responseIsCurrent?.call() == false) {
        throw StateError('Beneficiary vault access changed');
      }
    }

    Future<Map<String, dynamic>> post(
      String path, [Map<String, dynamic>? body]
    ) async {
      checkAccess();
      final response = await _sessionHttpWithGuard(checkAccess).post(
        Uri.parse('$baseUrl$path'),
        headers: _defaultHeaders(authToken: authToken, json: true),
        body: jsonEncode(body ?? <String, dynamic>{}),
      );
      checkAccess();
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw StateError('Beneficiary readback proof unavailable');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid beneficiary readback response');
      }
      return decoded;
    }

    checkAccess();
    final released = await readReleasedLinkedOldInheritanceV2(
      authToken: authToken,
      linkId: linkId,
      beneficiaryVaultId: beneficiaryVaultId,
      beneficiaryPrivateKey: beneficiaryPrivateKey,
      responseIsCurrent: responseIsCurrent,
    );
    checkAccess();
    return linked_inh_proof.proveLinkedReadback(
      released: released,
      beneficiaryVaultId: beneficiaryVaultId,
      zkProofToken: zkProofToken,
      fetchChallenge: (id) => post(
        '/inheritance/old-link-v2/$id/readback-challenge',
      ),
      submitProof: (body) => post(
        '/inheritance/old-link-v2/readback-proof', body,
      ),
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  /// Copy only encrypted saved items after a verified old-link V2 readback.
  /// The server checks the release, receipt, and source inventory on every
  /// destination write; the client re-reads and decrypts every copied item.
  Future<linked_inh_items.LinkedV2SavedItemImport>
      importLinkedOldInheritanceV2SavedItems({
    required String authToken,
    required String beneficiaryVaultId,
    required SecretKey beneficiaryMvk,
    required linked_inh_release.ReleasedLinkedInheritanceV2 released,
    required linked_inh_proof.LinkedReadbackReceipt readbackReceipt,
    bool Function()? responseIsCurrent,
  }) async {
    const enabled = bool.fromEnvironment(
      'VAULTAI_ENABLE_LINKED_INHERITANCE_ITEM_IMPORT',
      defaultValue: false,
    );
    if (!enabled) {
      throw StateError('Linked inheritance item import is unavailable');
    }
    void checkAccess() {
      _requireSavedItemKey(beneficiaryMvk);
      if (zk_mvk_store.ZkActiveMvk.currentVaultId() !=
              beneficiaryVaultId ||
          !identical(zk_mvk_store.ZkActiveMvk.current(), beneficiaryMvk) ||
          responseIsCurrent?.call() == false) {
        throw StateError('Beneficiary vault access changed');
      }
    }

    Future<Map<String, dynamic>> request(
      String method, Uri uri, [Map<String, dynamic>? body]
    ) async {
      checkAccess();
      final transport = _sessionHttpWithGuard(checkAccess);
      final response = method == 'POST'
          ? await transport.post(
              uri,
              headers: _defaultHeaders(authToken: authToken, json: true),
              body: jsonEncode(body ?? <String, dynamic>{}),
            )
          : await transport.get(
              uri, headers: _defaultHeaders(authToken: authToken),
            );
      checkAccess();
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw StateError('Inherited saved-item copy unavailable');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid inherited item response');
      }
      return decoded;
    }

    checkAccess();
    return linked_inh_items.importLinkedV2SavedItems(
      released: released,
      readbackReceipt: readbackReceipt,
      beneficiaryVaultId: beneficiaryVaultId,
      beneficiaryMvk: beneficiaryMvk,
      fetchExport: (id) => request(
        'GET', Uri.parse('$baseUrl/inheritance/old-link-v2/$id/vault-items'),
      ),
      copyItem: (body) => request(
        'POST', Uri.parse('$baseUrl/inheritance/old-link-v2/item-copy'), body,
      ),
      readbackCopies: (id, digest) => request(
        'GET', Uri.parse('$baseUrl/inheritance/old-link-v2/$id/item-copies')
            .replace(queryParameters: {'source_inventory_sha256': digest}),
      ),
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  /// Copy older saved-item ciphertext after release. The beneficiary device
  /// decrypts with the released old key and encrypts under its own MVK; no
  /// PIN, old key, or plaintext saved-item payload is posted to the server.
  Future<linked_inh_legacy_items.LinkedV2LegacySavedItemImport>
      importLinkedOldInheritanceV2LegacySavedItems({
    required String authToken,
    required String beneficiaryVaultId,
    required SecretKey beneficiaryMvk,
    required linked_inh_release.ReleasedLinkedInheritanceV2 released,
    required linked_inh_proof.LinkedReadbackReceipt readbackReceipt,
    bool Function()? responseIsCurrent,
  }) async {
    const enabled = bool.fromEnvironment(
      'VAULTAI_ENABLE_LINKED_INHERITANCE_LEGACY_ITEM_IMPORT',
      defaultValue: false,
    );
    if (!enabled) {
      throw StateError('Linked legacy item import is unavailable');
    }
    void checkAccess() {
      _requireSavedItemKey(beneficiaryMvk);
      if (zk_mvk_store.ZkActiveMvk.currentVaultId() !=
              beneficiaryVaultId ||
          !identical(zk_mvk_store.ZkActiveMvk.current(), beneficiaryMvk) ||
          responseIsCurrent?.call() == false) {
        throw StateError('Beneficiary vault access changed');
      }
    }

    Future<Map<String, dynamic>> request(
      String method, Uri uri, [Map<String, dynamic>? body]
    ) async {
      checkAccess();
      final transport = _sessionHttpWithGuard(checkAccess);
      final response = method == 'POST'
          ? await transport.post(
              uri,
              headers: _defaultHeaders(authToken: authToken, json: true),
              body: jsonEncode(body ?? <String, dynamic>{}),
            )
          : await transport.get(
              uri, headers: _defaultHeaders(authToken: authToken),
            );
      checkAccess();
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw StateError('Inherited legacy item copy unavailable');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid inherited legacy item response');
      }
      return decoded;
    }

    checkAccess();
    return linked_inh_legacy_items.importReleasedLinkedLegacyItems(
      released: released,
      readbackReceipt: readbackReceipt,
      beneficiaryVaultId: beneficiaryVaultId,
      beneficiaryMvk: beneficiaryMvk,
      fetchExport: (id) => request(
        'GET', Uri.parse(
          '$baseUrl/inheritance/old-link-v2/$id/legacy-vault-items',
        ),
      ),
      copyItem: (body) => request(
        'POST', Uri.parse('$baseUrl/inheritance/old-link-v2/legacy-item-copy'),
        body,
      ),
      readbackCopies: (id, digest) => request(
        'GET', Uri.parse('$baseUrl/inheritance/old-link-v2/$id/legacy-item-copies')
            .replace(queryParameters: {'source_inventory_sha256': digest}),
      ),
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  /// Copy the complete mixed saved-item inventory after release. The owner
  /// keys and decrypted content stay on the beneficiary device.
  Future<linked_inh_mixed_items.LinkedV2MixedSavedItemImport>
      importLinkedOldInheritanceV2MixedSavedItems({
    required String authToken,
    required String beneficiaryVaultId,
    required SecretKey beneficiaryMvk,
    required linked_inh_release.ReleasedLinkedInheritanceV2 released,
    required linked_inh_proof.LinkedReadbackReceipt readbackReceipt,
    bool Function()? responseIsCurrent,
  }) async {
    const enabled = bool.fromEnvironment(
      'VAULTAI_ENABLE_LINKED_INHERITANCE_MIXED_ITEM_IMPORT',
      defaultValue: false,
    );
    if (!enabled) {
      throw StateError('Mixed inheritance item import is unavailable');
    }
    void checkAccess() {
      _requireSavedItemKey(beneficiaryMvk);
      if (zk_mvk_store.ZkActiveMvk.currentVaultId() !=
              beneficiaryVaultId ||
          !identical(zk_mvk_store.ZkActiveMvk.current(), beneficiaryMvk) ||
          responseIsCurrent?.call() == false) {
        throw StateError('Beneficiary vault access changed');
      }
    }

    Future<Map<String, dynamic>> request(
      String method, Uri uri, [Map<String, dynamic>? body]
    ) async {
      checkAccess();
      final transport = _sessionHttpWithGuard(checkAccess);
      final response = method == 'POST'
          ? await transport.post(
              uri,
              headers: _defaultHeaders(authToken: authToken, json: true),
              body: jsonEncode(body ?? <String, dynamic>{}),
            )
          : await transport.get(
              uri, headers: _defaultHeaders(authToken: authToken),
            );
      checkAccess();
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw StateError('Mixed inheritance item copy unavailable');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid mixed inheritance response');
      }
      return decoded;
    }

    checkAccess();
    return linked_inh_mixed_items.importReleasedLinkedMixedSavedItems(
      released: released,
      readbackReceipt: readbackReceipt,
      beneficiaryVaultId: beneficiaryVaultId,
      beneficiaryMvk: beneficiaryMvk,
      fetchExport: (id) => request(
        'GET', Uri.parse(
          '$baseUrl/inheritance/old-link-v2/$id/mixed-vault-items',
        ),
      ),
      copyItem: (body) => request(
        'POST', Uri.parse('$baseUrl/inheritance/old-link-v2/mixed-item-copy'),
        body,
      ),
      readbackCopies: (id, digest) => request(
        'GET', Uri.parse('$baseUrl/inheritance/old-link-v2/$id/mixed-item-copies')
            .replace(queryParameters: {'source_inventory_sha256': digest}),
      ),
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  /// Copy only Memory after a released old-link V2 readback receipt. A fresh
  /// OPAQUE proof is requested for every destination write; source and
  /// destination ciphertext are verified by the beneficiary device.
  Future<linked_inh_memory.LinkedV2MemoryImport>
      importLinkedOldInheritanceV2Memories({
    required String authToken,
    required String beneficiaryVaultId,
    required SecretKey beneficiaryMvk,
    required linked_inh_release.ReleasedLinkedInheritanceV2 released,
    required linked_inh_proof.LinkedReadbackReceipt readbackReceipt,
    required Future<String> Function() freshZkProof,
    bool Function()? responseIsCurrent,
  }) async {
    const enabled = bool.fromEnvironment(
      'VAULTAI_ENABLE_LINKED_INHERITANCE_MEMORY_IMPORT',
      defaultValue: false,
    );
    if (!enabled || !kEnableLegacyMemoryV2ActiveRead) {
      throw StateError('Linked inheritance Memory import is unavailable');
    }
    void checkAccess() {
      _requireSavedItemKey(beneficiaryMvk);
      if (zk_mvk_store.ZkActiveMvk.currentVaultId() != beneficiaryVaultId ||
          responseIsCurrent?.call() == false) {
        throw StateError('Beneficiary vault access changed');
      }
    }

    Future<Map<String, dynamic>> request(
      String method, Uri uri, [Map<String, dynamic>? body]
    ) async {
      checkAccess();
      final transport = _sessionHttpWithGuard(checkAccess);
      final response = method == 'POST'
          ? await transport.post(
              uri,
              headers: _defaultHeaders(authToken: authToken, json: true),
              body: jsonEncode(body ?? <String, dynamic>{}),
            )
          : await transport.get(
              uri, headers: _defaultHeaders(authToken: authToken),
            );
      checkAccess();
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw StateError('Inherited Memory copy unavailable');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid inherited Memory response');
      }
      return decoded;
    }

    checkAccess();
    return linked_inh_memory.importLinkedV2Memories(
      released: released,
      readbackReceipt: readbackReceipt,
      beneficiaryVaultId: beneficiaryVaultId,
      beneficiaryMvk: beneficiaryMvk,
      fetchExport: (id) => request(
        'GET', Uri.parse('$baseUrl/inheritance/old-link-v2/$id/vault-memories'),
      ),
      copyMemory: (body) => request(
        'POST', Uri.parse('$baseUrl/inheritance/old-link-v2/memory-copy'), body,
      ),
      readbackCopies: (id, digest) => request(
        'GET', Uri.parse('$baseUrl/inheritance/old-link-v2/$id/memory-copies')
            .replace(queryParameters: {'source_inventory_sha256': digest}),
      ),
      fetchBeneficiaryInventory: () async {
        checkAccess();
        final inventory = await listZkMemories(authToken: authToken, limit: 0);
        checkAccess();
        return inventory;
      },
      freshZkProof: () async {
        checkAccess();
        final proof = rejectPinShapedZkProof(await freshZkProof());
        checkAccess();
        return proof;
      },
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
    );
  }

  Future<Map<String, dynamic>> saveInheritanceCredentials({
    required Map<String, dynamic> body,
    required String authToken,
  }) async {
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.post(
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
    String? zkProofToken,
  }) async {
    final response = await _sessionHttp.post(
      Uri.parse('$baseUrl/inheritance/credentials/delete'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'beneficiary_link_id': linkId,
        if (zkProofToken != null) 'zk_proof_token': zkProofToken,
      }),
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
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.get(
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
    final response = await _sessionHttp.get(
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
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.post(
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

  Future<Map<String, dynamic>> wipeOrphanData({
    required String authToken,
    bool confirm = true,
  }) async {
    final uri = Uri.parse('$baseUrl/wipe-orphan-data');

    final response = await _sessionHttp.post(
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

  Future<Map<String, dynamic>> listVaultSecureItems({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    final itemRead = ZkPinFreeItemReadSession.instance;
    final sessionPinFreeRead = itemRead.activeForToken(authToken);
    if (itemRead.wasOfferedForToken(authToken) &&
        (!sessionPinFreeRead || mvk == null)) {
      throw StateError('Vault encryption key is unavailable');
    }
    _requirePrivateSavedItemIdentity(authToken, mvk);
    if (mvk != null) {
      final ciphertext = await _listZkVaultItems(authToken: authToken);
      _requirePrivateSavedItemIdentity(authToken, mvk);
      // The coordinated keyless build and authenticated read offers use the
      // trusted metadata route. A missing route cannot retry the old list.
      final legacy = (kEnableKeylessSavedItemRead || sessionPinFreeRead ||
              kEnableZkPinFreeSavedItemIndex)
          ? await _listZkItemMetadata(authToken: authToken, mvk: mvk)
          : await _listLegacyVaultSecureItems(
              vaultName: vaultName,
              pin: pin,
              authToken: authToken,
              beforeResponse: () => _requireSavedItemKey(mvk),
            );
      _requirePrivateSavedItemIdentity(authToken, mvk);
      final combined = <Map<String, dynamic>>[];
      final seen = <String>{};
      for (final raw in (ciphertext['items'] as List? ?? const [])) {
        if (raw is! Map) continue;
        final item = Map<String, dynamic>.from(raw);
        final service = '${item['service'] ?? ''}'.trim();
        if (service.isEmpty) continue;
        final id = '${item['id'] ?? ''}';
        if (id.isNotEmpty) seen.add(id);
        item['storage_engine'] = 'ciphertext';
        combined.add(item);
      }
      for (final raw in (legacy['items'] as List? ?? const [])) {
        if (raw is! Map) continue;
        final item = Map<String, dynamic>.from(raw);
        final service = '${item['service'] ?? ''}'.trim();
        if (service.isEmpty) continue;
        final id = '${item['id'] ?? ''}';
        if (id.isEmpty || seen.add(id)) {
          item['storage_engine'] = 'legacy_compatibility';
          combined.add(item);
        }
      }
      _requirePrivateSavedItemIdentity(authToken, mvk);
      return <String, dynamic>{
        'items': combined,
        'engine': 'ciphertext_with_legacy_compatibility',
      };
    }
    return _listLegacyVaultSecureItems(
      vaultName: vaultName,
      pin: pin,
      authToken: authToken,
    );
  }

  Future<Map<String, dynamic>> _listZkItemMetadata({
    required String authToken,
    required SecretKey mvk,
  }) async {
    final metadataKey =
        await vault_key_hierarchy.VaultKeyHierarchy(mvk).metadataKey();
    final items = <Map<String, dynamic>>[];
    final records = await listZkItemMetadataRaw(authToken: authToken);
    _requireSavedItemKey(mvk);
    for (final raw in records) {
      if (raw['is_legacy'] != true) continue;
      Future<String> label(String cipherField, String plainField) async {
        final encrypted = raw[cipherField];
        if (encrypted is String && encrypted.isNotEmpty) {
          return utf8.decode(await vault_key_hierarchy.aesGcmUnwrap(
            metadataKey,
            vault_key_hierarchy.b64urlDecode(encrypted),
          ));
        }
        final plain = raw[plainField];
        if (plain is String && plain.isNotEmpty) return plain;
        throw const FormatException('Saved-item label is unavailable');
      }

      final type = await label('item_type_ciphertext', 'item_type');
      if (isSystemHiddenItemType(type)) continue;
      final service = await label('service_ciphertext', 'service');
      if (type.trim().isEmpty || service.trim().isEmpty) {
        throw const FormatException('Empty saved-item metadata');
      }
      items.add(<String, dynamic>{
        'id': raw['item_id'],
        'item_type': type,
        'service': service,
        'created_at': raw['created_at'],
        'storage_engine': 'legacy_compatibility',
      });
    }
    _requireSavedItemKey(mvk);
    return <String, dynamic>{'items': items, 'engine': 'zk_metadata'};
  }

  /// Strict trusted-session inventory for completeness checks. No PIN or
  /// saved-item value ciphertext is sent or returned by this route.
  Future<List<Map<String, dynamic>>> listZkItemMetadataRaw({
    required String authToken,
    int? maxRecords,
  }) async {
    if (maxRecords != null && maxRecords < 1) {
      throw ArgumentError.value(maxRecords, 'maxRecords');
    }
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    final records = <Map<String, dynamic>>[];
    var afterId = 0;
    for (var page = 0; page < 1000; page++) {
      _requireSavedItemKey(mvk);
      final uri = Uri.parse('$baseUrl/vault/items/metadata').replace(
        queryParameters: <String, String>{
          'after_item_id': '$afterId',
          'limit': '100',
        },
      );
      final response = await _sessionHttpWithGuard(
        () => _requireSavedItemKey(mvk),
      ).get(uri, headers: _defaultHeaders(authToken: authToken));
      _requireSavedItemKey(mvk);
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw Exception(_formatBackendError(
          prefix: 'List saved-item metadata failed',
          statusCode: response.statusCode,
          responseBody: response.body,
        ));
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic> ||
          decoded['records'] is! List ||
          decoded['has_more'] is! bool) {
        throw const FormatException('Invalid saved-item metadata inventory');
      }
      for (final raw in decoded['records'] as List) {
        if (raw is! Map<String, dynamic> || raw['item_id'] is! int) {
          throw const FormatException('Invalid saved-item metadata record');
        }
        records.add(raw);
        if (maxRecords != null && records.length > maxRecords) {
          throw const FormatException('Saved-item metadata exceeds safe limit');
        }
      }
      final hasMore = decoded['has_more'] as bool;
      if (!hasMore) {
        _requireSavedItemKey(mvk);
        return records;
      }
      final next = decoded['next_after_item_id'];
      if (next is! int || next <= afterId) {
        throw const FormatException(
            'Saved-item metadata cursor did not advance');
      }
      afterId = next;
    }
    throw StateError('Saved-item inventory exceeded page limit');
  }

  Future<Map<String, dynamic>> _listLegacyVaultSecureItems({
    required String vaultName,
    required String pin,
    required String authToken,
    void Function()? beforeResponse,
  }) async {
    if ((kEnableKeylessSavedItemRead &&
            zk_mvk_store.ZkActiveMvk.current() != null) ||
        ZkPinFreeItemReadSession.instance.wasOfferedForToken(authToken) ||
        ZkPinFreeItemReadSession.instance.privateVaultForToken(authToken)) {
      throw StateError('This vault uses the private saved-item list.');
    }
    final uri = Uri.parse('$baseUrl/list-secure-items');

    final response = await _sessionHttpWithGuard(beforeResponse).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': '',
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

  Future<Map<String, dynamic>> _listZkVaultItems({
    required String authToken,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-items');
    final response =
        await _sessionHttpWithGuard(() => _requireSavedItemKey(mvk)).get(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    );
    _requireSavedItemKey(mvk);
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'List secure items failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! List) {
      throw Exception('Invalid ciphertext secure-items response format');
    }
    final metaKey =
        await vault_key_hierarchy.VaultKeyHierarchy(mvk).metadataKey();
    Future<String> decryptRequired(Object? encoded) async {
      if (encoded is! String || encoded.isEmpty) {
        throw const FormatException('Missing encrypted saved-item field');
      }
      final plaintext = await vault_key_hierarchy.aesGcmUnwrap(
        metaKey,
        vault_key_hierarchy.b64urlDecode(encoded),
      );
      return utf8.decode(plaintext);
    }

    final items = <Map<String, dynamic>>[];
    for (final raw in decoded) {
      if (raw is! Map) continue;
      try {
        final type = await decryptRequired(raw['item_type_ciphertext']);
        final service = await decryptRequired(raw['service_ciphertext']);
        final payloadText = await decryptRequired(raw['payload_ciphertext']);
        final payloadDecoded = jsonDecode(payloadText);
        final payload = payloadDecoded is Map
            ? Map<String, dynamic>.from(payloadDecoded)
            : <String, dynamic>{};
        final rawFields = payload['fields'];
        items.add(<String, dynamic>{
          'id': raw['item_id'],
          'service': service,
          'item_type': type,
          'fields': rawFields is Map
              ? Map<String, dynamic>.from(rawFields)
              : <String, dynamic>{},
          'notes': payload['notes'],
          'draft_id': payload['draft_id'],
          'zk_payload': payload,
          'zk_service_ciphertext': raw['service_ciphertext'],
          'title_indexed': raw['title_indexed'] == true,
          'title_revision': raw['title_revision'],
          'storage_engine': 'ciphertext',
          'created_at': raw['created_at'],
        });
      } catch (_) {
        // A single corrupt envelope must not hide other saved items.
      }
    }
    _requireSavedItemKey(mvk);
    return <String, dynamic>{'items': items, 'engine': 'ciphertext'};
  }

  /// Strict MVK-only saved-item reader. Never calls the legacy PIN routes.
  Future<Map<String, dynamic>> listZkVaultItemsOnly({
    required String authToken,
  }) => _listZkVaultItems(authToken: authToken);

  /// Read only an MVK-decrypted V2 row. A legacy metadata row or a corrupt
  /// envelope cannot trigger the PIN-bearing detail route or legacy reader.
  Future<Map<String, dynamic>> getZkVaultSecureItemOnly({
    required String authToken,
    required String service,
    required String itemType,
    String? itemId,
  }) async {
    if (!kEnableKeylessSavedItemRead) {
      throw StateError('Private saved-item reading is unavailable');
    }
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    final selectedId = itemId == null ? null : int.tryParse(itemId);
    if (itemId != null && (selectedId == null || selectedId <= 0)) {
      throw StateError('Saved-item identity is unavailable');
    }
    final listed = await _listZkVaultItems(authToken: authToken);
    _requireSavedItemKey(mvk);
    final matches = (listed['items'] as List? ?? const [])
        .whereType<Map>()
        .where((row) => selectedId != null
            ? row['id'] == selectedId
            : '${row['item_type']}'.toLowerCase() ==
                    itemType.toLowerCase() &&
                _savedItemTitleIdentity('${row['service']}') ==
                    _savedItemTitleIdentity(service))
        .toList();
    if (matches.length != 1 ||
        '${matches.single['item_type']}'.toLowerCase() !=
            itemType.toLowerCase() ||
        _savedItemTitleIdentity('${matches.single['service']}') !=
            _savedItemTitleIdentity(service)) {
      throw StateError('This saved item is unavailable or needs migration');
    }
    _requireSavedItemKey(mvk);
    return Map<String, dynamic>.from(matches.single);
  }

  /// Delete only a selected V2 row after a fresh MVK-only identity check.
  Future<Map<String, dynamic>> deleteZkVaultSecureItemOnly({
    required String authToken,
    required String service,
    required String itemType,
    String? itemId,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    final selected = await getZkVaultSecureItemOnly(
      authToken: authToken,
      service: service,
      itemType: itemType,
      itemId: itemId,
    );
    _requireSavedItemKey(mvk);
    final selectedId = selected['id'];
    if (selectedId is! int || selectedId <= 0) {
      throw const FormatException('Invalid private saved-item identity');
    }
    final response = await _sessionHttpWithGuard(
      () => _requireSavedItemKey(mvk),
    ).delete(
      Uri.parse('$baseUrl/vault/ciphertext/vault-items/$selectedId'),
      headers: _defaultHeaders(authToken: authToken),
    );
    _requireSavedItemKey(mvk);
    if (response.statusCode != 200) {
      throwIfSavedItemUpdateRequired(response.statusCode, response.body);
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Could not delete saved item',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> ||
        decoded['item_id'] != selectedId ||
        decoded['status'] != 'deleted') {
      throw const FormatException('Invalid private saved-item deletion result');
    }
    return decoded;
  }

  /// Strict MVK-only create/edit path. Metadata covers every legacy and V2
  /// title so a new ciphertext item cannot silently duplicate an older item.
  /// An edit requires a selected V2 item ID; legacy rows remain untouched.
  Future<Map<String, dynamic>> saveZkVaultSecureItem({
    required String authToken,
    required String itemType,
    required String service,
    required Map<String, dynamic> fields,
    int? itemId,
    String? expectedOldService,
  }) async {
    if (!kEnableKeylessSavedItemWrite || !kEnableKeylessSavedItemRead) {
      throw StateError('Private saved-item writing is not enabled');
    }
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    final type = itemType.trim();
    final title = service.trim();
    if (type.isEmpty || title.isEmpty ||
        (itemId == null) != (expectedOldService == null) ||
        (itemId != null && (itemId <= 0 ||
            expectedOldService!.trim().isEmpty))) {
      throw ArgumentError('A saved-item type, title and selected edit ID are required');
    }

    // The V2 list may omit a corrupt envelope. Compare it to the complete
    // metadata inventory before writing, rather than interpreting omission as
    // an available title or as a missing edit target.
    final metadata = await listZkItemMetadataRaw(authToken: authToken);
    final listed = await _listZkVaultItems(authToken: authToken);
    _requireSavedItemKey(mvk);
    final v2ById = <int, Map<String, dynamic>>{};
    for (final raw in (listed['items'] as List? ?? const [])) {
      if (raw is! Map || raw['id'] is! int ||
          v2ById.containsKey(raw['id'] as int)) {
        throw const FormatException('Invalid private saved-item inventory');
      }
      v2ById[raw['id'] as int] = Map<String, dynamic>.from(raw);
    }
    final metadataKey = await vault_key_hierarchy.VaultKeyHierarchy(mvk)
        .metadataKey();
    Future<String> label(Map<String, dynamic> row,
        String encryptedField, String plainField) async {
      final encrypted = row[encryptedField];
      if (encrypted is String && encrypted.isNotEmpty) {
        return utf8.decode(await vault_key_hierarchy.aesGcmUnwrap(
          metadataKey, vault_key_hierarchy.b64urlDecode(encrypted),
        ));
      }
      final plain = row[plainField];
      if (row['is_legacy'] == true && plain is String && plain.isNotEmpty) {
        return plain;
      }
      throw const FormatException('Saved-item label is unavailable');
    }
    final normalizedType = type.toLowerCase();
    final normalizedTitle = _savedItemTitleIdentity(title);
    final resolved = <({int id, String type, String title, bool legacy})>[];
    final metadataIds = <int>{};
    for (final row in metadata) {
      final id = row['item_id'];
      if (id is! int || id <= 0 || !metadataIds.add(id)) {
        throw const FormatException('Invalid saved-item metadata inventory');
      }
      final legacy = row['is_legacy'] == true;
      final hasV2 = row['has_v2_payload'] == true;
      if (!legacy && (!hasV2 || !v2ById.containsKey(id))) {
        throw const FormatException('Private saved-item inventory is incomplete');
      }
      final rowType = await label(row, 'item_type_ciphertext', 'item_type');
      final rowTitle = await label(row, 'service_ciphertext', 'service');
      if (rowType.trim().isEmpty || rowTitle.trim().isEmpty) {
        throw const FormatException('Empty saved-item metadata');
      }
      resolved.add((id: id, type: rowType, title: rowTitle, legacy: legacy));
    }
    if (v2ById.keys.any((id) => !metadataIds.contains(id))) {
      throw const FormatException('Private saved-item metadata is incomplete');
    }
    _requireSavedItemKey(mvk);

    final sameTitle = resolved.where((row) =>
        row.id != itemId && row.type.toLowerCase() == normalizedType &&
        _savedItemTitleIdentity(row.title) == normalizedTitle);
    if (sameTitle.isNotEmpty) {
      throw const SavedItemConflictException(duplicate: true);
    }
    // Existing V2 rows predate the server's keyed unique index. Claim each
    // other row with an exact ciphertext/revision comparison before a write.
    // The selected edit row is updated atomically below, which also permits
    // repairing a preexisting duplicate by renaming that selected row.
    for (final entry in v2ById.entries) {
      if (entry.key == itemId || entry.value['title_indexed'] == true) continue;
      final revision = entry.value['title_revision'];
      final serviceCt = entry.value['zk_service_ciphertext'];
      if (revision is! int || revision < 0 ||
          serviceCt is! String || serviceCt.isEmpty) {
        throw const FormatException('Private saved-item title index is unavailable');
      }
      await _claimZkSavedItemTitleIndex(
        authToken: authToken,
        mvk: mvk,
        itemId: entry.key,
        itemType: '${entry.value['item_type']}',
        service: '${entry.value['service']}',
        expectedServiceCiphertext: serviceCt,
        expectedRevision: revision,
      );
    }
    final selectedRevision = itemId == null
        ? null : v2ById[itemId]?['title_revision'];
    if (itemId != null &&
        (selectedRevision is! int || selectedRevision < 0)) {
      throw const FormatException('Private saved-item revision is unavailable');
    }
    Map<String, dynamic> payload = <String, dynamic>{};
    if (itemId != null) {
      final selected = resolved.where((row) => row.id == itemId).toList();
      if (selected.length != 1 || selected.single.legacy ||
          selected.single.type.toLowerCase() != normalizedType ||
          _savedItemTitleIdentity(selected.single.title) !=
              _savedItemTitleIdentity(expectedOldService!)) {
        throw StateError('Selected private saved item changed');
      }
      final rawPayload = v2ById[itemId]?['zk_payload'];
      if (rawPayload is! Map) {
        throw const FormatException('Private saved-item content is unavailable');
      }
      payload = Map<String, dynamic>.from(rawPayload);
    }
    payload['fields'] = Map<String, dynamic>.from(fields);
    _requireSavedItemKey(mvk);
    final written = await tryZkVaultItemCiphertextUpsert(
      baseUrl: baseUrl,
      authToken: authToken,
      existingItemId: itemId,
      expectedTitleRevision: selectedRevision as int?,
      itemType: type,
      service: title,
      payload: payload,
    );
    _requireSavedItemKey(mvk);
    final writtenId = written?['item_id'];
    if (writtenId is! int || writtenId <= 0 ||
        writtenId != (itemId ?? writtenId) ||
        written?['created'] != (itemId == null)) {
      throw const FormatException('Private saved-item acknowledgement is invalid');
    }
    final readback = await _listZkVaultItems(authToken: authToken);
    _requireSavedItemKey(mvk);
    final matches = (readback['items'] as List? ?? const [])
        .whereType<Map>()
        .where((row) => row['id'] == writtenId)
        .toList();
    if (matches.length != 1 || matches.single['item_type'] != type ||
        matches.single['service'] != title ||
        matches.single['title_indexed'] != true ||
        matches.single['title_revision'] !=
            (itemId == null ? 0 : (selectedRevision as int) + 1) ||
        jsonEncode(matches.single['zk_payload']) != jsonEncode(payload)) {
      throw const FormatException('Private saved-item readback did not match');
    }
    return written!;
  }

  Future<Map<String, dynamic>> getVaultSecureItem({
    required String vaultName,
    required String service,
    required String itemType,
    required String pin,
    required String authToken,
    String? itemId,
  }) async {
    final itemRead = ZkPinFreeItemReadSession.instance;
    final sessionPinFreeRead = itemRead.activeForToken(authToken);
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (itemRead.wasOfferedForToken(authToken) &&
        (!sessionPinFreeRead || mvk == null)) {
      throw StateError('Vault encryption key is unavailable');
    }
    _requirePrivateSavedItemIdentity(authToken, mvk);
    if (mvk != null) {
      final item = await _resolveSavedItem(
        vaultName: vaultName,
        pin: pin,
        authToken: authToken,
        service: service,
        itemType: itemType,
        itemId: itemId,
      );
      _requireSavedItemKey(mvk);
      _requirePrivateSavedItemIdentity(authToken, mvk);
      if (item?['storage_engine'] == 'ciphertext') return item!;
      if (kEnableKeylessSavedItemRead || sessionPinFreeRead) {
        if (item?['storage_engine'] != 'legacy_compatibility') {
          throw StateError('Saved item not found');
        }
        final exactId = item?['id'];
        final reader = legacyZkItemReader;
        if (exactId is! int || exactId <= 0 || reader == null) {
          throw StateError('Private saved-item reader is unavailable');
        }
        final detail = await reader(exactId);
        _requireSavedItemKey(mvk);
        _requirePrivateSavedItemIdentity(authToken, mvk);
        if (detail['id'] != exactId ||
            detail['item_type'] != item?['item_type'] ||
            detail['service'] != item?['service']) {
          throw const FormatException('Saved-item identity changed');
        }
        return detail;
      }
      // Until the coordinated cutover is enabled, older builds retain their
      // legacy item detail path for sessions without a private read offer.
      itemId = item?['id']?.toString() ?? itemId;
    }
    if (itemRead.wasOfferedForToken(authToken) ||
        itemRead.privateVaultForToken(authToken)) {
      throw StateError('This vault uses the private saved-item reader.');
    }
    final uri = Uri.parse('$baseUrl/get-secure-item');

    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': '',
        'service': service,
        'item_type': itemType,
        'pin': pin,
        if (itemId != null) 'item_id': itemId,
      }),
    );

    if (response.statusCode != 200) {
      if (response.statusCode == 409) throw const SavedItemConflictException();
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

  Future<Map<String, dynamic>?> _resolveSavedItem({
    required String vaultName,
    required String pin,
    required String authToken,
    required String service,
    required String itemType,
    String? itemId,
    bool creating = false,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    final listed = await listVaultSecureItems(
      vaultName: vaultName,
      pin: pin,
      authToken: authToken,
    );
    _requireSavedItemKey(mvk);
    final matches = (listed['items'] as List? ?? const [])
        .whereType<Map>()
        .where((row) => itemId != null
            ? '${row['id']}' == itemId && '${row['item_type']}' == itemType
            : '${row['item_type']}'.toLowerCase() == itemType.toLowerCase() &&
                _savedItemTitleIdentity('${row['service']}') ==
                    _savedItemTitleIdentity(service))
        .map((row) => Map<String, dynamic>.from(row))
        .toList();
    if (matches.length > 1)
      throw SavedItemConflictException(duplicate: creating);
    if (itemId != null && matches.isEmpty)
      throw StateError('Saved item not found');
    return matches.isEmpty ? null : matches.single;
  }

  String _savedItemTitleIdentity(String value) =>
      value.trim().replaceAll(RegExp(r'\s+'), ' ').toLowerCase();

  Future<String> _savedItemTitleLookupHash(
      SecretKey mvk, String itemType, String service) async {
    final subkey = await vault_key_hierarchy.VaultKeyHierarchy(mvk)
        .savedItemTitleLookupKey();
    final canonical = '${itemType.trim().toLowerCase()}\u0000'
        '${_savedItemTitleIdentity(service)}';
    return vault_key_hierarchy.b64urlEncode(
      await vault_key_hierarchy.keyedLookupHash(
        subkey, utf8.encode(canonical),
      ),
    );
  }

  void _throwSavedItemTitleConflict(int status, String body) {
    if (status != 409) return;
    try {
      final decoded = jsonDecode(body);
      final detail = decoded is Map ? decoded['detail'] : null;
      final code = detail is Map ? detail['code'] : detail;
      if (code == 'saved_item_title_conflict') {
        throw const SavedItemConflictException(duplicate: true);
      }
      if (code == 'saved_item_revision_stale' ||
          code == 'saved_item_title_index_changed') {
        throw StateError('Saved item changed. Refresh and try again.');
      }
    } on SavedItemConflictException {
      rethrow;
    } on StateError {
      rethrow;
    } catch (_) {}
  }

  Future<int> _claimZkSavedItemTitleIndex({
    required String authToken,
    required SecretKey mvk,
    required int itemId,
    required String itemType,
    required String service,
    required String expectedServiceCiphertext,
    required int expectedRevision,
  }) async {
    _requireSavedItemKey(mvk);
    final lookup = await _savedItemTitleLookupHash(mvk, itemType, service);
    final uri = Uri.parse(
        '$baseUrl/vault/ciphertext/vault-items/$itemId/title-index');
    final response = await _sessionHttpWithGuard(
      () => _requireSavedItemKey(mvk),
    ).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(<String, Object>{
        'title_lookup_hash': lookup,
        'expected_title_revision': expectedRevision,
        'expected_service_ciphertext': expectedServiceCiphertext,
      }),
    );
    _requireSavedItemKey(mvk);
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      _throwSavedItemTitleConflict(response.statusCode, response.body);
      throw StateError('Private saved-item title index is unavailable');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> ||
        decoded['item_id'] != itemId || decoded['indexed'] != true ||
        decoded['title_revision'] is! int ||
        (decoded['title_revision'] as int) < expectedRevision) {
      throw const FormatException('Invalid private saved-item title index');
    }
    return decoded['title_revision'] as int;
  }

  void _requireSavedItemKey(Object? expected) {
    if (expected == null ||
        !identical(expected, zk_mvk_store.ZkActiveMvk.current())) {
      throw StateError('Vault encryption key changed. Unlock and try again.');
    }
  }

  void _requirePrivateSavedItemIdentity(String authToken, Object? expected) {
    final itemRead = ZkPinFreeItemReadSession.instance;
    if (!itemRead.privateVaultForToken(authToken)) return;
    _requireSavedItemKey(expected);
    if (!itemRead.privateVaultKeyMatchesForToken(
      authToken,
      vaultId: zk_mvk_store.ZkActiveMvk.currentVaultId(),
      vaultHandle: zk_mvk_store.ZkActiveMvk.currentVaultHandle(),
    )) {
      throw StateError('Vault encryption key belongs to another vault.');
    }
  }

  void _requireSavedItemMutationIdentity(String authToken, Object? expected) {
    final itemRead = ZkPinFreeItemReadSession.instance;
    if (itemRead.wasOfferedForToken(authToken) &&
        (!itemRead.activeForToken(authToken) || expected == null)) {
      throw StateError('Private saved-item access needs a fresh vault unlock.');
    }
    if (signedSavedItemMutationOfferedForToken(authToken) &&
        !itemRead.privateVaultForToken(authToken)) {
      throw StateError('Private saved-item mutation session is unavailable.');
    }
    _requirePrivateSavedItemIdentity(authToken, expected);
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
    _rejectOfferedLegacyFileCreate(authToken);
    _rejectLegacyFilePinForActiveZk();
    final uri = Uri.parse('$baseUrl/upload-file');

    final requestScope =
        st.SessionTermination.instance.captureRequest(authToken);
    final request = http.MultipartRequest('POST', uri);
    request.headers.addAll(
      _defaultHeaders(authToken: authToken),
    );

    request.fields['vault_name'] = '';
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

    _assertCurrentRequest(requestScope);
    final response = await _sendCheckedBaseRequest(request, _httpClient);
    _assertCurrentRequest(requestScope);
    final responseBody = await response.stream.bytesToString();
    _checkSessionResponse(response.statusCode, responseBody, requestScope);

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
    final response = await _sessionHttp.get(
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

  Map<String, dynamic> _importAuthBody({
    required String? pin,
    required bool zkSessionOnly,
  }) {
    if (zkSessionOnly) {
      if (pin != null) {
        throw ArgumentError('Private import must omit the PIN.');
      }
      return const <String, dynamic>{};
    }
    if (pin == null || pin.isEmpty) {
      throw ArgumentError('Legacy import requires a PIN.');
    }
    return <String, dynamic>{'pin': pin};
  }

  Future<Map<String, dynamic>> startImport({
    required String vaultName,
    required String? pin,
    required String authToken,
    bool zkSessionOnly = false,
    String? rootFolderName,
    int totalFiles = 0,
    int totalBytesPlanned = 0,
  }) async {
    final offeredImport = signedImportOfferedForToken(authToken);
    if (offeredImport && (!zkSessionOnly || pin != null)) {
      throw StateError('Signed import requires the PIN-free session route.');
    }
    if (kEnableZkPrivateOnlyUnlock && !zkSessionOnly) {
      throw StateError('Private import requires an OPAQUE session.');
    }
    final uri = Uri.parse(zkSessionOnly
        ? '$baseUrl/imports/session/start' : '$baseUrl/imports/start');
    if (zkSessionOnly && rootFolderName != null) {
      throw ArgumentError('Private import cannot send a folder name.');
    }
    final body = <String, dynamic>{
      if (!zkSessionOnly) 'vault_name': '',
      ..._importAuthBody(pin: pin, zkSessionOnly: zkSessionOnly),
      'total_files': totalFiles,
      'total_bytes_planned': totalBytesPlanned,
      if (rootFolderName != null && rootFolderName.isNotEmpty)
        'root_folder_name': rootFolderName,
    };

    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.get(
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
    required String? pin,
    required String authToken,
    required String importId,
    bool zkSessionOnly = false,
  }) async {
    final offeredImport = signedImportOfferedForToken(authToken);
    if (offeredImport && (!zkSessionOnly || pin != null)) {
      throw StateError('Signed import requires the PIN-free session route.');
    }
    if (kEnableZkPrivateOnlyUnlock && !zkSessionOnly) {
      throw StateError('Private import requires an OPAQUE session.');
    }
    final uri = Uri.parse(zkSessionOnly
        ? '$baseUrl/imports/session/$importId/cancel'
        : '$baseUrl/imports/$importId/cancel');
    final body = <String, dynamic>{
      if (!zkSessionOnly) 'vault_name': '',
      ..._importAuthBody(pin: pin, zkSessionOnly: zkSessionOnly),
    };

    final response = await _sessionHttp.post(
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
    required String? pin,
    required String authToken,
    required String importId,
    bool zkSessionOnly = false,
    int failedCountDelta = 0,
    int skippedDuplicateCountDelta = 0,
  }) async {
    final offeredImport = signedImportOfferedForToken(authToken);
    if (offeredImport && (!zkSessionOnly || pin != null)) {
      throw StateError('Signed import requires the PIN-free session route.');
    }
    if (kEnableZkPrivateOnlyUnlock && !zkSessionOnly) {
      throw StateError('Private import requires an OPAQUE session.');
    }
    final uri = Uri.parse(zkSessionOnly
        ? '$baseUrl/imports/session/$importId/complete'
        : '$baseUrl/imports/$importId/complete');
    final body = <String, dynamic>{
      if (!zkSessionOnly) 'vault_name': '',
      ..._importAuthBody(pin: pin, zkSessionOnly: zkSessionOnly),
      'failed_count_delta': failedCountDelta,
      'skipped_duplicate_count_delta': skippedDuplicateCountDelta,
    };

    final response = await _sessionHttp.post(
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
    String? pin,
    required String authToken,
    bool requireCiphertext = false,
    bool Function()? responseIsCurrent,
  }) async {
    if (requireCiphertext) {
      final error = savedFileNameValidationError(savedName);
      if (error != null) throw SavedFileRenameValidationException(error);
    }
    // ZK ciphertext-first fast path. Encrypts saved_name under the
    // vault's metadata subkey and POSTs to
    // /vault/ciphertext/uploaded-files so no readable saved_name
    // touches persistent server storage for an adopted vault.
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    void checkAccess() {
      if (responseIsCurrent?.call() == false ||
          mvk == null ||
          !identical(zk_mvk_store.ZkActiveMvk.current(), mvk)) {
        throw StateError('File rename access changed. Unlock and try again.');
      }
    }

    checkAccess();
    if (mvk != null) {
      final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(mvk);
      final metaKey = await hierarchy.metadataKey();
      final savedNameCt = await vault_key_hierarchy.aesGcmWrap(
        metaKey,
        utf8.encode(
            requireCiphertext ? normalizeSavedFileName(savedName) : savedName),
      );
      checkAccess();
      final zkUri = Uri.parse('$baseUrl/vault/ciphertext/uploaded-files');
      final zkResp = await _sessionHttpWithGuard(checkAccess).post(
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
      checkAccess();
      if (zkResp.statusCode != 200) {
        throw Exception(
          'ZK ciphertext saved_name write failed '
          '(${zkResp.statusCode})',
        );
      }
      final decoded = jsonDecode(zkResp.body);
      if (decoded is Map<String, dynamic>) {
        if (requireCiphertext &&
            (decoded['file_id'] != fileId ||
                decoded['updated_columns'] is! List ||
                (decoded['updated_columns'] as List).length != 1 ||
                !(decoded['updated_columns'] as List)
                    .contains('saved_name_ciphertext'))) {
          throw StateError('File name commit could not be verified.');
        }
        return decoded;
      }
      throw Exception('Invalid /vault/ciphertext/uploaded-files response');
    }
    // The legacy-only account needs a separate migration client. Never
    // revive its PIN-bearing rename route when the private key is absent.
    throw StateError('Unlock your encrypted vault before renaming a file.');
  }

  Future<Map<String, dynamic>> listVaultFiles({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    // A signed bearer remains authoritative if the local offer marker was
    // lost, so do not fall back to the older PIN request in that case.
    if (signedFileListOfferedForToken(authToken) ||
        ZkPinFreeFileSession.instance.listOfferedForToken(authToken)) {
      if (zk_mvk_store.ZkActiveMvk.current() == null) {
        throw StateError('Vault encryption key is unavailable');
      }
      final result = await listZkVaultFilesWithRetiredV2(
        authToken: authToken, requireLegacyComplete: true,
      );
      final files = (result['files'] as List).cast<Map<String, dynamic>>();
      files.sort((a, b) {
        final aTime = DateTime.tryParse('${a['created_at']}');
        final bTime = DateTime.tryParse('${b['created_at']}');
        return (bTime ?? DateTime.fromMillisecondsSinceEpoch(0))
            .compareTo(aTime ?? DateTime.fromMillisecondsSinceEpoch(0));
      });
      return result;
    }
    _rejectLegacyFilePinForActiveZk();
    final uri = Uri.parse('$baseUrl/list-files');

    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': '',
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

  /// Session-only ZK file inventory. The server returns encrypted labels and
  /// structural fields, never inline file ciphertext or a PIN-derived key.
  Future<Map<String, dynamic>> listZkFileMetadata({
    required String authToken,
    bool requireLegacyComplete = false,
    int maxPages = 1000,
  }) async {
    if (maxPages < 1 || maxPages > 1000) {
      throw ArgumentError.value(maxPages, 'maxPages', 'Must be 1–1000');
    }
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    final files = <Map<String, dynamic>>[];
    final seen = <String>{};
    var after = '';
    for (var page = 0; page < maxPages; page++) {
      _requireSavedItemKey(mvk);
      final uri = Uri.parse(
        '$baseUrl/vault/files/metadata?after_file_id=${Uri.encodeQueryComponent(after)}&limit=100${requireLegacyComplete ? '&require_legacy_complete=true' : ''}',
      );
      final response = await _sessionHttpWithGuard(
        () => _requireSavedItemKey(mvk),
      ).get(uri, headers: _defaultHeaders(authToken: authToken));
      _requireSavedItemKey(mvk);
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        if (requireLegacyComplete && response.statusCode == 409) {
          try {
            final error = jsonDecode(response.body);
            if (error is Map<String, dynamic> &&
                error['detail'] == 'legacy_file_list_changed') {
              throw const ZkLegacyFileListChangedException();
            }
          } on ZkLegacyFileListChangedException {
            rethrow;
          } catch (_) {
            // Unknown conflict is reported normally below.
          }
        }
        throw StateError(
            'ZK file inventory unavailable (${response.statusCode})');
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic> ||
          decoded['records'] is! List ||
          decoded['has_more'] is! bool) {
        throw const FormatException('Invalid ZK file inventory');
      }
      for (final raw in decoded['records'] as List) {
        if (raw is! Map<String, dynamic> ||
            raw['file_id'] is! String ||
            (raw['file_id'] as String).isEmpty ||
            !seen.add(raw['file_id'] as String)) {
          throw const FormatException('Invalid ZK file inventory entry');
        }
        files.add(<String, dynamic>{
          ...raw,
          'id': raw['file_id'],
          'v2_retired': raw['lifecycle_state'] == 'legacy_migration_retired' &&
              raw['verification_state'] == 'client_verified',
          'v2_ready': raw['lifecycle_state'] == 'client_v2_ready' &&
              raw['verification_state'] == 'client_verified',
          'needs_naming': raw['needs_naming'] == true,
        });
      }
      if (decoded['has_more'] == false) {
        final result = <String, dynamic>{'files': files};
        await _decryptUploadedFileMetadataForActiveZkVault(result);
        _requireSavedItemKey(mvk);
        return result;
      }
      // Private search needs a bounded snapshot, while the file UI continues
      // to request the complete inventory by default. Never call a truncated
      // search result complete.
      if (page + 1 == maxPages && maxPages < 1000) {
        final result = <String, dynamic>{
          'files': files,
          'truncated': true,
        };
        await _decryptUploadedFileMetadataForActiveZkVault(result);
        _requireSavedItemKey(mvk);
        return result;
      }
      final next = decoded['next_after_file_id'];
      if (next is! String || next.isEmpty || next == after) {
        throw const FormatException('ZK file inventory did not advance');
      }
      after = next;
    }
    throw StateError('ZK file inventory exceeded page limit');
  }

  FileV2Reader _fileV2Reader({required String authToken}) {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    return FileV2Reader(
      mvk: mvk,
      get: (path) async {
        _requireSavedItemKey(mvk);
        final response = await _sessionHttpWithGuard(
          () => _requireSavedItemKey(mvk),
        ).get(
          Uri.parse('$baseUrl$path'),
          headers: _defaultHeaders(authToken: authToken),
        );
        _requireSavedItemKey(mvk);
        if (response.statusCode != 200) {
          _throwIfAuthExpired(response.statusCode, response.body);
          _throwIfDeviceNotTrusted(response.statusCode, response.body);
          throw FileV2ReadException(response.statusCode);
        }
        final decoded = jsonDecode(response.body);
        if (decoded is! Map<String, dynamic>) {
          throw const FormatException('Invalid V2 file response');
        }
        return decoded;
      },
    );
  }

  /// Transfer a released owner's V2 file one chunk at a time. The owner key
  /// and clear bytes stay on this device; only beneficiary-MVK ciphertext is
  /// sent to the existing V2 upload routes. A fresh beneficiary OPAQUE proof
  /// is obtained after readback, just before publication. The server's
  /// inheritance export gate is separately default-off, so this is not a
  /// user-visible flow yet.
  Future<Map<String, dynamic>> transferInheritedV2File({
    required String authToken,
    required int linkId,
    required String sourceFileId,
    required Future<String> Function() freshBeneficiaryProof,
    required SecretKey beneficiaryPrivateKey,
    required SecretKey beneficiaryMvk,
    required Map<String, dynamic> releasedPackage,
    bool Function()? responseIsCurrent,
    void Function(double progress)? onProgress,
  }) async {
    final beneficiaryVaultId = zk_mvk_store.ZkActiveMvk.currentVaultId();
    if (beneficiaryVaultId == null || beneficiaryVaultId.isEmpty) {
      throw StateError('Beneficiary vault is unavailable');
    }
    void checkAccess() {
      _requireSavedItemKey(beneficiaryMvk);
      if (zk_mvk_store.ZkActiveMvk.currentVaultId() != beneficiaryVaultId) {
        throw StateError('Beneficiary vault changed');
      }
      if (responseIsCurrent?.call() == false) {
        throw StateError('Private inheritance access changed');
      }
    }

    Future<Map<String, dynamic>?> request(
      String method,
      String path,
      Map<String, Object>? body, {
      required bool allowMissing,
    }) async {
      checkAccess();
      final uri = Uri.parse('$baseUrl$path');
      final headers = _defaultHeaders(
        authToken: authToken,
        json: method != 'GET',
      );
      final transport = _sessionHttpWithGuard(checkAccess);
      final response = switch (method) {
        'GET' => await transport.get(uri, headers: headers),
        'POST' => await transport.post(
            uri,
            headers: headers,
            body: jsonEncode(body),
          ),
        'PUT' => await transport.put(
            uri,
            headers: headers,
            body: jsonEncode(body),
          ),
        _ => throw const FormatException('Invalid private transfer request'),
      };
      checkAccess();
      if (allowMissing && response.statusCode == 404) return null;
      if (response.statusCode == 413) {
        throw _parseStorageLimitException(response.body);
      }
      if (response.statusCode == 429) {
        throw _rateLimitedFromBody(response.body);
      }
      if (response.statusCode == 409) {
        try {
          final error = jsonDecode(response.body);
          if (error is Map<String, dynamic> &&
              error['detail'] == 'inherited_source_changed') {
            throw const InheritedV2SourceChangedException();
          }
        } on InheritedV2SourceChangedException {
          rethrow;
        } catch (_) {
          // Preserve the ordinary V2 error below for unrelated conflicts.
        }
      }
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw FileV2ReadException(response.statusCode);
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid private transfer response');
      }
      return decoded;
    }

    checkAccess();
    return transferReleasedV2FileStreamed(
      linkId: linkId,
      sourceFileId: sourceFileId,
      beneficiaryVaultId: beneficiaryVaultId,
      freshBeneficiaryProof: freshBeneficiaryProof,
      beneficiaryPrivateKey: beneficiaryPrivateKey,
      beneficiaryMvk: beneficiaryMvk,
      releasedPackage: releasedPackage,
      fetchSource: (path) async => (await request(
        'GET',
        path,
        null,
        allowMissing: false,
      ))!,
      requestTarget: (method, path, body) => request(
        method,
        path,
        body,
        allowMissing: method == 'GET',
      ),
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
      onProgress: onProgress,
    );
  }

  /// Copy a bounded, released V2 file inventory into this vault. Each file
  /// uses the existing streamed copy and its own fresh OPAQUE publication
  /// proof. A second inventory read detects added, removed or renamed files;
  /// this is a copy result, not a whole-vault inheritance claim.
  Future<ReleasedV2FileBatchResult> transferInheritedV2Files({
    required String authToken,
    required int linkId,
    required Future<String> Function() freshBeneficiaryProof,
    required SecretKey beneficiaryPrivateKey,
    required SecretKey beneficiaryMvk,
    required Map<String, dynamic> releasedPackage,
    required bool Function() responseIsCurrent,
    void Function(int completed, int total)? onFileProgress,
  }) async {
    void checkAccess() {
      _requireSavedItemKey(beneficiaryMvk);
      if (!responseIsCurrent()) {
        throw StateError('Private inheritance access changed');
      }
    }

    checkAccess();
    final package = await decryptInheritanceMvk(
      expectedLinkId: linkId,
      beneficiaryPrivateKey: beneficiaryPrivateKey,
      rawPackage: releasedPackage,
    );
    checkAccess();
    return copyReleasedV2FileInventory(
      linkId: linkId,
      ownerVaultId: package.ownerVaultId,
      accessIsCurrent: () {
        try {
          checkAccess();
          return true;
        } catch (_) {
          return false;
        }
      },
      fetchPage: (after) async {
        checkAccess();
        final uri = Uri.parse('$baseUrl/inheritance/v2/$linkId/files')
            .replace(queryParameters: {
          'after_file_id': after,
          'limit': '100',
        });
        final response = await _sessionHttpWithGuard(checkAccess).get(
          uri,
          headers: _defaultHeaders(authToken: authToken),
        );
        checkAccess();
        if (response.statusCode != 200) {
          _throwIfAuthExpired(response.statusCode, response.body);
          _throwIfDeviceNotTrusted(response.statusCode, response.body);
          throw FileV2ReadException(response.statusCode);
        }
        final decoded = jsonDecode(response.body);
        if (decoded is! Map<String, dynamic>) {
          throw const FormatException('Invalid inherited file inventory');
        }
        return decoded;
      },
      copyFile: (sourceId) => transferInheritedV2File(
        authToken: authToken,
        linkId: linkId,
        sourceFileId: sourceId,
        freshBeneficiaryProof: freshBeneficiaryProof,
        beneficiaryPrivateKey: beneficiaryPrivateKey,
        beneficiaryMvk: beneficiaryMvk,
        releasedPackage: releasedPackage,
        responseIsCurrent: responseIsCurrent,
      ),
      expectedTargetFileId: (sourceId) => inheritedTargetFileId(
        linkId: linkId,
        ownerVaultId: package.ownerVaultId,
        sourceFileId: sourceId,
        beneficiaryMvk: beneficiaryMvk,
      ),
      onFileProgress: onFileProgress,
    );
  }

  /// Idempotently stage one prepared MVK file, verify every server byte on
  /// this client, then publish it. No PIN, filename, MIME, or plaintext bytes
  /// are included in any request. The caller retains `prepared` on retry.
  Future<Map<String, dynamic>> uploadNewV2File({
    required String authToken,
    required PreparedNewFileV2 prepared,
    required Uint8List originalBytes,
    required SecretKey mvk,
    String duplicateAction = 'prompt',
    bool Function()? responseIsCurrent,
    void Function(double progress)? onProgress,
  }) async {
    if (!<String>{'prompt', 'skip', 'keep_both'}.contains(duplicateAction) ||
        (prepared.contentToken == null) != prepared.nameTokens.isEmpty ||
        (prepared.contentToken == null) != (prepared.sourceSha256 == null) ||
        originalBytes.length != prepared.totalBytes ||
        (prepared.chunkCiphertexts.isNotEmpty &&
            prepared.chunkCiphertexts.length != prepared.chunkCount) ||
        !identical(mvk, zk_mvk_store.ZkActiveMvk.current())) {
      throw StateError('Private upload access changed');
    }
    void checkAccess() {
      _requireSavedItemKey(mvk);
      if (responseIsCurrent?.call() == false) {
        throw StateError('Private upload access changed');
      }
    }
    if (prepared.sourceSha256 != null) {
      checkAccess();
      final currentDigest = vault_key_hierarchy.b64urlEncode(
        (await Sha256().hash(originalBytes)).bytes,
      );
      checkAccess();
      if (currentDigest != prepared.sourceSha256) {
        throw StateError('Private upload source changed after preparation');
      }
    }
    Future<Map<String, dynamic>?> getOptional(String path) async {
      checkAccess();
      final response = await _sessionHttpWithGuard(checkAccess).get(
        Uri.parse('$baseUrl$path'),
        headers: _defaultHeaders(authToken: authToken),
      );
      checkAccess();
      if (response.statusCode == 404) return null;
      if (response.statusCode == 429) {
        throw _rateLimitedFromBody(response.body);
      }
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw FileV2ReadException(response.statusCode);
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid private upload readback');
      }
      return decoded;
    }
    Future<void> discardConflictingStage() async {
      checkAccess();
      final response = await _sessionHttpWithGuard(checkAccess).delete(
        Uri.parse('$baseUrl/vault/file-v2/${Uri.encodeComponent(prepared.fileId)}'),
        headers: _defaultHeaders(authToken: authToken),
      );
      checkAccess();
      if (response.statusCode == 404) return;
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw FileV2ReadException(response.statusCode);
      }
      final result = jsonDecode(response.body);
      if (result is! Map<String, dynamic> ||
          result['file_id'] != prepared.fileId ||
          result['deleted'] != true) {
        throw const FormatException('Private file stage cleanup failed');
      }
    }
    Future<Map<String, dynamic>> mutate(
      String method, String path, Map<String, Object> body,
    ) async {
      checkAccess();
      final uri = Uri.parse('$baseUrl$path');
      final headers = _defaultHeaders(authToken: authToken, json: true);
      final encoded = jsonEncode(body);
      final transport = _sessionHttpWithGuard(checkAccess);
      final response = method == 'PUT'
          ? await transport.put(uri, headers: headers, body: encoded)
          : await transport.post(uri, headers: headers, body: encoded);
      checkAccess();
      if (response.statusCode == 413) {
        throw _parseStorageLimitException(response.body);
      }
      if (response.statusCode == 429) {
        throw _rateLimitedFromBody(response.body);
      }
      if (response.statusCode == 409 && path.endsWith('/publish-new')) {
        Map<String, dynamic>? detail;
        try {
          final decoded = jsonDecode(response.body);
          if (decoded is Map<String, dynamic> &&
              decoded['detail'] is Map<String, dynamic>) {
            detail = decoded['detail'] as Map<String, dynamic>;
          }
        } catch (_) {
          // An unrelated malformed 409 takes the ordinary error path.
        }
        final code = detail?['code'];
        if (code == 'duplicate_found' || code == 'name_conflict') {
          // A rejected stage is invisible and uncharged. Remove it before
          // offering a different name or a duplicate decision; never rebind
          // its immutable encrypted manifest to a new name.
          await discardConflictingStage();
          if (code == 'duplicate_found') {
            throw DuplicateFoundUploadException(detail!);
          }
          throw NameConflictUploadException(detail!);
        }
      }
      if (response.statusCode != 200) {
        _throwIfAuthExpired(response.statusCode, response.body);
        _throwIfDeviceNotTrusted(response.statusCode, response.body);
        throw FileV2ReadException(response.statusCode);
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Invalid private upload acknowledgement');
      }
      return decoded;
    }

    final encodedId = Uri.encodeComponent(prepared.fileId);
    final manifestPath = '/vault/file-v2/$encodedId/manifest';
    final existingManifest = await getOptional(manifestPath);
    if (existingManifest == null) {
      await mutate('POST', '/vault/file-v2/manifest',
          prepared.toManifestBody());
    } else if (existingManifest['file_id'] != prepared.fileId ||
        existingManifest['manifest_ciphertext'] !=
            prepared.manifestCiphertext ||
        existingManifest['total_bytes'] != prepared.totalBytes ||
        existingManifest['chunk_size'] != prepared.chunkSize ||
        existingManifest['chunk_count'] != prepared.chunkCount) {
      throw const FormatException('Private file upload differs from server');
    }
    final writer = FileV2Writer(mvk);
    final deferredChunks = prepared.chunkCiphertexts.isEmpty &&
        prepared.chunkCount > 0;
    final contentKey = deferredChunks
        ? await vault_key_hierarchy.VaultKeyHierarchy(mvk).fileContentKey()
        : null;
    for (var index = 0; index < prepared.chunkCount; index++) {
      checkAccess();
      final chunkPath = '/vault/file-v2/$encodedId/chunk/$index';
      final existing = await getOptional(chunkPath);
      if (existing == null) {
        final start = index * prepared.chunkSize;
        final end = math.min(start + prepared.chunkSize, originalBytes.length);
        final ciphertext = deferredChunks
            ? vault_key_hierarchy.b64urlEncode(
                await vault_key_hierarchy.aesGcmWrap(
                  contentKey!, originalBytes.sublist(start, end),
                ),
              )
            : prepared.chunkCiphertexts[index];
        checkAccess();
        await mutate('PUT', '/vault/file-v2/chunk', <String, Object>{
          'file_id': prepared.fileId,
          'chunk_index': index,
          'ciphertext': ciphertext,
        });
      } else if (existing['file_id'] != prepared.fileId ||
          existing['chunk_index'] != index ||
          existing['ciphertext'] is! String) {
        throw const FormatException('Private file chunk differs from server');
      } else if (!deferredChunks) {
        if (existing['ciphertext'] != prepared.chunkCiphertexts[index]) {
          throw const FormatException('Private file chunk differs from server');
        }
      } else {
        final start = index * prepared.chunkSize;
        final end = math.min(start + prepared.chunkSize, originalBytes.length);
        final clear = await vault_key_hierarchy.aesGcmUnwrap(
          contentKey!,
          vault_key_hierarchy.b64urlDecode(existing['ciphertext'] as String),
        );
        checkAccess();
        if (clear.length != end - start) {
          throw const FormatException('Private file chunk differs from source');
        }
        for (var j = 0; j < clear.length; j++) {
          if (clear[j] != originalBytes[start + j]) {
            throw const FormatException('Private file chunk differs from source');
          }
        }
      }
      onProgress?.call(0.8 * (index + 1) / prepared.chunkCount);
    }
    final verified = await writer.verifyReadback(
      prepared: prepared,
      originalBytes: originalBytes,
      get: (path) async {
        final value = await getOptional(path);
        if (value == null) {
          throw const FormatException('Private file readback is incomplete');
        }
        if (path == manifestPath &&
            value['manifest_ciphertext'] != prepared.manifestCiphertext) {
          throw const FormatException('Private file metadata changed');
        }
        return value;
      },
    );
    checkAccess();
    if (!verified) {
      throw const FormatException('Private file readback did not match');
    }
    onProgress?.call(0.95);
    final published = await mutate('POST',
        '/vault/file-v2/$encodedId/publish-new',
        <String, Object>{
          'confirm': true,
          if (prepared.contentToken != null) ...<String, Object>{
            'content_token': prepared.contentToken!,
            'name_tokens': prepared.nameTokens,
            'duplicate_action': duplicateAction,
          },
        });
    if (published['file_id'] == prepared.fileId &&
        published['status'] == 'skipped_duplicate' &&
        duplicateAction == 'skip' &&
        published['duplicate_of_file_id'] is String &&
        (published['duplicate_of_file_id'] as String).isNotEmpty) {
      return published;
    }
    if (published['file_id'] != prepared.fileId ||
        !<String>{'published', 'already_published'}
            .contains(published['status'])) {
      throw const FormatException('Invalid private file publish result');
    }
    final ready = await getOptional(manifestPath);
    if (ready == null ||
        ready['lifecycle_state'] != 'client_v2_ready' ||
        ready['verification_state'] != 'client_verified' ||
        ready['manifest_ciphertext'] != prepared.manifestCiphertext) {
      throw const FormatException('Private file publish state is unavailable');
    }
    onProgress?.call(1);
    return published;
  }

  Future<List<Map<String, dynamic>>> listRetiredV2Files({
    required String authToken,
  }) async {
    final listed = await _fileV2Reader(authToken: authToken).list(
      retiredOnly: true,
    );
    return <Map<String, dynamic>>[
      for (final file in listed)
        <String, dynamic>{
          'id': file.fileId,
          'file_name': file.fileName ?? file.displayName,
          'saved_name': file.savedName,
          'content_type': file.contentType,
          'asset_type': file.assetType,
          'file_size': file.totalBytes,
          'relative_path': file.relativePath,
          'needs_naming': false,
          'v2_retired': true,
        },
    ];
  }

  Future<List<Map<String, dynamic>>> listReadyV2Files({
    required String authToken,
  }) async {
    final listed = await _fileV2Reader(authToken: authToken).list(
      readyOnly: true,
    );
    return <Map<String, dynamic>>[
      for (final file in listed)
        <String, dynamic>{
          'id': file.fileId,
          'file_name': file.fileName ?? file.displayName,
          'saved_name': file.savedName,
          'content_type': file.contentType,
          'asset_type': file.assetType,
          'file_size': file.totalBytes,
          'relative_path': file.relativePath,
          'needs_naming': false,
          'v2_retired': file.retired,
          'v2_ready': file.readyForUse && !file.retired,
        },
    ];
  }

  Future<Map<String, dynamic>> listZkVaultFilesWithRetiredV2({
    required String authToken,
    bool requireLegacyComplete = false,
  }) async {
    // Metadata and V2 manifests are separate reads. A concurrent publish or
    // delete can make the first pair disagree; take one fresh pair before
    // reporting an unavailable copy. Never drop a still-marked ready file.
    for (var attempt = 0; attempt < 2; attempt++) {
      final inventory = await listZkFileMetadata(
        authToken: authToken,
        requireLegacyComplete: requireLegacyComplete,
      );
      final files = (inventory['files'] as List)
          .map((row) => Map<String, dynamic>.from(row as Map))
          .toList();
      // Older vaults can receive a signed list offer before any V2 copy
      // exists. Their metadata inventory is complete already.
      if (!files.any((row) =>
          row['v2_retired'] == true || row['v2_ready'] == true)) {
        return <String, dynamic>{'files': files};
      }
      final List<Map<String, dynamic>> ready;
      try {
        ready = await listReadyV2Files(authToken: authToken);
      } on FileV2ReadException catch (error) {
        // A listed manifest can disappear during a concurrent deletion.
        if (attempt == 0 && error.statusCode == 404) continue;
        rethrow;
      } on FormatException catch (error) {
        // The list can say ready just before the manifest changes state.
        // Other malformed or undecryptable manifests must fail immediately.
        if (attempt == 0 && error.message == 'V2 file is not ready for use') {
          continue;
        }
        rethrow;
      }
      final byId = <String, Map<String, dynamic>>{};
      for (final row in ready) {
        final id = row['id'] as String;
        if (byId.containsKey(id)) {
          throw const FormatException('Duplicate ready V2 file');
        }
        byId[id] = row;
      }
      final merged = <Map<String, dynamic>>[];
      var changed = false;
      for (final row in files) {
        final id = row['id'] as String;
        final v2 = byId.remove(id);
        final expectedV2 =
            row['v2_retired'] == true || row['v2_ready'] == true;
        if (expectedV2 &&
            (v2 == null ||
                row['v2_retired'] != v2['v2_retired'] ||
                row['v2_ready'] != v2['v2_ready'] ||
                row['file_size'] != v2['file_size'])) {
          changed = true;
          break;
        }
        merged.add(v2 == null ? row : <String, dynamic>{...row, ...v2});
      }
      if (changed) {
        if (attempt == 0) continue;
        throw const FormatException('Private file inventory changed');
      }
      merged.addAll(byId.values);
      return <String, dynamic>{'files': merged};
    }
    throw StateError('Private file inventory retry exhausted');
  }

  Future<bool> isRetiredV2File({
    required String authToken,
    required String fileId,
  }) async {
    if (fileId.isEmpty) return false;
    final response = await _fileV2Reader(authToken: authToken).get(
      '/vault/file-v2',
    );
    final files = response['files'];
    if (files is! List) {
      throw const FormatException('Invalid V2 file list');
    }
    for (final raw in files) {
      if (raw is! Map || raw['file_id'] != fileId) continue;
      return raw['lifecycle_state'] == 'legacy_migration_retired' &&
          raw['verification_state'] == 'client_verified';
    }
    return false;
  }

  Future<bool> isAvailableV2File({
    required String authToken,
    required String fileId,
    bool allowDisabledRoute = false,
  }) async {
    if (fileId.isEmpty) return false;
    final Map<String, dynamic> response;
    try {
      response = await _fileV2Reader(authToken: authToken).get(
        '/vault/file-v2',
      );
    } on FileV2ReadException catch (error) {
      // A signed legacy download can still open an older inline file when
      // file-v2 is disabled. Other errors, and every V2-required read, fail.
      if (allowDisabledRoute && error.statusCode == 404) return false;
      rethrow;
    }
    final files = response['files'];
    if (files is! List) throw const FormatException('Invalid V2 file list');
    for (final raw in files) {
      if (raw is! Map || raw['file_id'] != fileId) continue;
      return raw['verification_state'] == 'client_verified' &&
          <String>{'legacy_migration_retired', 'client_v2_ready'}
              .contains(raw['lifecycle_state']);
    }
    return false;
  }

  Future<bool> isNewReadyV2File({
    required String authToken,
    required String fileId,
  }) async {
    final response = await _fileV2Reader(authToken: authToken).get(
      '/vault/file-v2',
    );
    final files = response['files'];
    if (files is! List) throw const FormatException('Invalid V2 file list');
    return files.whereType<Map>().any((raw) =>
        raw['file_id'] == fileId &&
        raw['lifecycle_state'] == 'client_v2_ready' &&
        raw['verification_state'] == 'client_verified');
  }

  Future<FileV2Download> downloadRetiredV2File({
    required String authToken,
    required String fileId,
  }) async {
    return _fileV2Reader(authToken: authToken).download(
      fileId,
      requireRetired: true,
    );
  }

  Future<FileV2Download> downloadAvailableV2File({
    required String authToken,
    required String fileId,
    int maxBytes = FileV2Reader.maxDownloadBytes,
  }) => _fileV2Reader(authToken: authToken).download(
        fileId,
        requireReady: true,
        maxBytes: maxBytes,
      );

  Future<FileV2Manifest> renameAvailableV2File({
    required String authToken,
    required String fileId,
    required String savedName,
    required String zkProofToken,
    bool Function()? responseIsCurrent,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    void checkAccess() {
      if (!identical(mvk, zk_mvk_store.ZkActiveMvk.current()) ||
          responseIsCurrent?.call() == false) {
        throw StateError('File rename access changed. Select it again.');
      }
    }

    checkAccess();
    final reader = _fileV2Reader(authToken: authToken);
    final renamer = FileV2Renamer(
      mvk: mvk,
      get: (path) async {
        checkAccess();
        final value = await reader.get(path);
        checkAccess();
        return value;
      },
      post: (path, body) async {
        checkAccess();
        final response = await _sessionHttpWithGuard(checkAccess).post(
          Uri.parse('$baseUrl$path'),
          headers: _defaultHeaders(authToken: authToken, json: true),
          body: jsonEncode(body),
        );
        checkAccess();
        if (response.statusCode != 200) {
          _throwIfAuthExpired(response.statusCode, response.body);
          _throwIfDeviceNotTrusted(response.statusCode, response.body);
          throw FileV2ReadException(response.statusCode);
        }
        final decoded = jsonDecode(response.body);
        if (decoded is! Map<String, dynamic>) {
          throw const FormatException('Invalid private file rename response');
        }
        return decoded;
      },
    );
    final renamed = await renamer.rename(
      fileId: fileId, savedName: savedName, zkProofToken: zkProofToken,
    );
    checkAccess();
    return renamed;
  }

  Future<Map<String, dynamic>> deleteRetiredV2File({
    required String authToken,
    required String fileId,
    required String zkProofToken,
    bool Function()? responseIsCurrent,
  }) async {
    if (zkProofToken.isEmpty || fileId.isEmpty) {
      throw const FormatException('V2 file delete proof is missing');
    }
    void checkAccess() {
      if (responseIsCurrent?.call() == false) {
        throw StateError('File deletion access changed. Select it again.');
      }
    }

    checkAccess();
    final uri = Uri.parse(
      '$baseUrl/vault/file-v2/${Uri.encodeComponent(fileId)}/delete-confirm',
    );
    final response = await _sessionHttpWithGuard(checkAccess).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(<String, dynamic>{
        'zk_proof_token': zkProofToken,
        'confirm': true,
      }),
    );
    checkAccess();
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw FileV2ReadException(response.statusCode);
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> ||
        decoded['file_id'] != fileId ||
        decoded['deleted'] != true) {
      throw const FormatException('Invalid V2 file delete response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> deleteNewV2File({
    required String authToken,
    required String fileId,
    required String zkProofToken,
    bool Function()? responseIsCurrent,
  }) async {
    if (zkProofToken.isEmpty || fileId.isEmpty) {
      throw const FormatException('V2 file delete proof is missing');
    }
    void checkAccess() {
      if (responseIsCurrent?.call() == false) {
        throw StateError('File deletion access changed. Select it again.');
      }
    }
    checkAccess();
    final uri = Uri.parse(
      '$baseUrl/vault/file-v2/${Uri.encodeComponent(fileId)}/delete-new',
    );
    final response = await _sessionHttpWithGuard(checkAccess).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(<String, dynamic>{
        'zk_proof_token': zkProofToken,
        'confirm': true,
      }),
    );
    checkAccess();
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw FileV2ReadException(response.statusCode);
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> ||
        decoded['file_id'] != fileId || decoded['deleted'] != true) {
      throw const FormatException('Invalid V2 file delete response');
    }
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

  Future<Map<String, dynamic>> getSessionVaultStats({
    required String authToken,
  }) async {
    final response = await _sessionHttp.get(
      Uri.parse('$baseUrl/vault-stats/session'),
      headers: _defaultHeaders(authToken: authToken),
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

  Future<Map<String, dynamic>> getZkVaultStats({
    required String authToken,
  }) async {
    final response = await _sessionHttp.get(
      Uri.parse('$baseUrl/vault-stats/zk'),
      headers: _defaultHeaders(authToken: authToken),
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
    _rejectOfferedLegacyFileDownload(authToken);
    _rejectLegacyFilePinForActiveZk();
    final uri = Uri.parse('$baseUrl/download-file');

    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': '',
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
    _rejectOfferedLegacyFileCreate(authToken);
    _rejectLegacyFilePinForActiveZk();
    final uri = Uri.parse('$baseUrl/upload-file/init');
    final body = <String, dynamic>{
      'vault_name': '',
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

    final response = await _sessionHttp.post(
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

    final requestScope =
        st.SessionTermination.instance.captureRequest(authToken);
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

    _assertCurrentRequest(requestScope);
    final response = await _sendCheckedBaseRequest(request, _httpClient);
    _assertCurrentRequest(requestScope);
    final responseBody = await response.stream.bytesToString();
    _checkSessionResponse(response.statusCode, responseBody, requestScope);

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
    required String uploadToken,
    required String fileId,
  }) async {
    if (fileId.isEmpty || fileId.length > 128 ||
        uploadToken.length < 32 || uploadToken.length > 1024) {
      throw const FormatException('Invalid pending upload identity');
    }
    final uri = Uri.parse('$baseUrl/upload-file/finalize-token');

    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'file_id': fileId,
        'upload_token': uploadToken,
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
    required String uploadToken,
    required String fileId,
  }) async {
    if (fileId.isEmpty || fileId.length > 128 ||
        uploadToken.length < 32 || uploadToken.length > 1024) {
      throw const FormatException('Invalid pending upload identity');
    }
    final uri = Uri.parse('$baseUrl/upload-file/abort-token');

    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'file_id': fileId,
        'upload_token': uploadToken,
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

  /// Proof-bound token for encrypted older chunks; no PIN or plaintext name.
  Future<Map<String, dynamic>> getZkLegacyChunkedManifest({
    required String authToken,
    required String fileId,
    required String zkProofToken,
    void Function()? accessGuard,
  }) async {
    if (fileId.isEmpty || fileId.length > 128) {
      throw const FormatException('Invalid older file identity');
    }
    rejectPinShapedZkProof(zkProofToken);
    accessGuard?.call();
    final response = await _sessionHttpWithGuard(accessGuard).post(
      Uri.parse('$baseUrl/vault/legacy-file/chunked/manifest'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(<String, String>{
        'file_id': fileId,
        'zk_proof_token': zkProofToken,
      }),
    );
    accessGuard?.call();
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw StateError('Older file download unavailable (${response.statusCode})');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic> ||
        decoded['file_id'] != fileId ||
        decoded['storage_mode'] != 'chunked' ||
        decoded['file_size'] is! int ||
        decoded['chunk_size'] is! int ||
        decoded['chunk_count'] is! int ||
        decoded['download_token'] is! String ||
        (decoded['download_token'] as String).isEmpty) {
      throw const FormatException('Invalid older chunked-file manifest');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getDownloadManifest({
    required String authToken,
    required String vaultName,
    required String pin,
    required String fileId,
  }) async {
    _rejectOfferedLegacyFileDownload(authToken);
    _rejectLegacyFilePinForActiveZk();
    final uri = Uri.parse('$baseUrl/download-file/manifest');

    final response = await _sessionHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': '',
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

    final response = await _sessionHttp.post(
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

  Future<Map<String, dynamic>> updateVaultSecureItem({
    required String vaultName,
    required String oldService,
    required String itemType,
    required String pin,
    required String authToken,
    String? newService,
    Map<String, dynamic>? fields,
    String? itemId,
    bool createOnly = false,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    _requireSavedItemMutationIdentity(authToken, mvk);
    // ZK ciphertext-first fast path. When an unlocked MVK is active
    // (i.e. this is a ZK/adopted vault), the item is written to
    // /vault/ciphertext/vault-items instead of /update-secure-item —
    // no readable item_type / service / payload leaves the client.
    if (mvk != null) {
      int? existingItemId;
      final existing = await _resolveSavedItem(
        vaultName: vaultName,
        pin: pin,
        authToken: authToken,
        service: createOnly ? (newService ?? oldService) : oldService,
        itemType: itemType,
        itemId: createOnly ? null : itemId,
        creating: createOnly,
      );
      _requireSavedItemKey(mvk);
      _requireSavedItemMutationIdentity(authToken, mvk);
      if (createOnly && existing != null) {
        throw const SavedItemConflictException(duplicate: true);
      }
      final useCiphertext = createOnly ||
          existing == null ||
          existing['storage_engine'] == 'ciphertext';
      if (!createOnly) itemId = existing?['id']?.toString() ?? itemId;
      if (useCiphertext) {
        existingItemId = createOnly ? null : int.tryParse(itemId ?? '');
        final zkResp = await tryZkVaultItemCiphertextUpsert(
          baseUrl: baseUrl,
          authToken: authToken,
          existingItemId: existingItemId,
          itemType: itemType,
          service: (newService != null && newService.trim().isNotEmpty)
              ? newService.trim()
              : oldService,
          payload: <String, dynamic>{
            'old_service': oldService,
            if (!createOnly && existing?['draft_id'] is String)
              'draft_id': existing!['draft_id'],
            if (newService != null && newService.trim().isNotEmpty)
              'new_service': newService.trim(),
            if (fields != null) 'fields': fields,
          },
        );
        _requireSavedItemMutationIdentity(authToken, mvk);
        if (zkResp != null) return zkResp;
        // The MVK vanished during the request. Never send the supplied PIN to
        // the legacy route as a fallback from a ZK operation.
        throw StateError('Vault encryption key changed. Unlock and try again.');
      }
      if (kEnableKeylessLegacySavedItemEdit &&
          existing['storage_engine'] == 'legacy_compatibility') {
        final exactId = int.tryParse(itemId ?? '');
        final updater = legacyZkItemUpdater;
        if (exactId == null || exactId <= 0 || updater == null ||
            existing['service'] != oldService) {
          throw StateError('Private saved-item editor is unavailable');
        }
        final updated = await updater(
          itemId: exactId,
          itemType: itemType,
          oldService: oldService,
          newService: newService,
          fields: fields,
        );
        _requireSavedItemMutationIdentity(authToken, mvk);
        return updated;
      }
      throw StateError(
          'Legacy saved-item editing is unavailable until migration.');
    }

    // A current client cannot turn a missing OPAQUE key into a raw-PIN edit.
    // Legacy-only recovery requires a separate, explicit migration build.
    throw StateError('Unlock your vault before editing a saved item.');
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
    final privateReadback = PrivateZkPinTransportSession.active;
    final memoryGeneration = st.SessionTermination.instance.generation;
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
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
      utf8.encode(memoryKey.trim().toLowerCase()),
    );
    final recordCanonical = <String>[
      memoryType,
      memoryKey.trim().toLowerCase(),
      memoryValue.trim().toLowerCase(),
    ].join('\u0000');
    final recordHash = await vault_key_hierarchy.keyedLookupHash(
      memoryLookup,
      utf8.encode(recordCanonical),
    );
    final resolvedMemoryId =
        'memory-${vault_key_hierarchy.b64urlEncode(recordHash)}';
    final memoryInventoryGeneration = await _checkMemoryTitleAvailable(
      authToken: authToken,
      title: memoryKey,
      editingMemoryId: privateReadback ? resolvedMemoryId : null,
    );

    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-ai-memory');
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    final resp = await _sessionHttpWithGuard(
        () => _assertMemoryAccessCurrent(mvk, memoryGeneration)).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(<String, dynamic>{
        'memory_id': resolvedMemoryId,
        'memory_type': memoryType,
        'memory_lookup_hash': vault_key_hierarchy.b64urlEncode(lookupHash),
        'payload_ciphertext': vault_key_hierarchy.b64urlEncode(payloadCt),
        if (memoryInventoryGeneration != null)
          'expected_memory_generation': memoryInventoryGeneration,
      }),
    );
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    if (resp.statusCode == 409) {
      if (_memoryGenerationConflict(resp.body)) {
        throw const MemoryInventoryIncompleteException();
      }
      throw const MemoryTitleConflictException();
    }
    if (resp.statusCode != 200) return false;
    if (privateReadback) {
      try {
        await _verifyZkMemoryReadback(
          authToken: authToken,
          mvk: mvk,
          memoryGeneration: memoryGeneration,
          memoryId: resolvedMemoryId,
          memoryType: memoryType,
          lookupHash: vault_key_hierarchy.b64urlEncode(lookupHash),
          expectedPayloadJson: payloadJson,
        );
      } on AuthExpiredException {
        rethrow;
      } on SessionTerminatedException {
        rethrow;
      } on DeviceNotTrustedException {
        rethrow;
      } catch (_) {
        throw const MemorySaveReadbackException();
      }
    }
    return true;
  }

  Future<String> _readMemoryInventoryGeneration({
    required String authToken,
    required Object mvk,
    required int sessionGeneration,
  }) async {
    final uri = Uri.parse('$baseUrl/vault/memory/legacy-copy/generation');
    final response = await _sessionHttpWithGuard(
            () => _assertMemoryAccessCurrent(mvk, sessionGeneration))
        .get(uri, headers: _defaultHeaders(authToken: authToken))
        .timeout(const Duration(seconds: 12));
    _assertMemoryAccessCurrent(mvk, sessionGeneration);
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Memory inventory check failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final body = jsonDecode(response.body);
    final generation = body is Map ? body['generation'] : null;
    if (generation is! String ||
        !RegExp(r'^(0|[1-9][0-9]{0,18})$').hasMatch(generation)) {
      throw const FormatException('Invalid Memory inventory generation');
    }
    return generation;
  }

  /// Fetches opaque ZK memory envelopes and decrypts them only on the client.
  Future<Map<String, dynamic>> listZkMemories({
    required String authToken,
    int limit = 200,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    final memoryGeneration = st.SessionTermination.instance.generation;
    final inventoryGeneration = kEnableLegacyMemoryV2ActiveRead
        ? await _readMemoryInventoryGeneration(
            authToken: authToken,
            mvk: mvk,
            sessionGeneration: memoryGeneration,
          )
        : null;
    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-ai-memory');
    final response = await _sessionHttpWithGuard(
            () => _assertMemoryAccessCurrent(mvk, memoryGeneration))
        .get(
          uri,
          headers: <String, String>{
            ..._defaultHeaders(authToken: authToken),
            'Cache-Control': 'no-cache, no-store',
            'Pragma': 'no-cache',
            if (kEnableLegacyMemoryV2ActiveRead)
              'X-SVaultAI-Memory-Active-Copy': '1',
          },
        )
        .timeout(const Duration(seconds: 12));
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
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
    if (decoded is! List) {
      throw Exception('Invalid memory list response format');
    }
    final prepared = <Map<String, dynamic>>[];
    var sourceUnavailable = 0;
    if (kEnableLegacyMemoryV2ActiveRead) {
      const pageSize = 20;
      var cursor = 0;
      var processed = 0;
      var encodedBytes = 0;
      final seen = <int>{};
      while (true) {
        final uri = Uri.parse('$baseUrl/vault/memory/legacy-copy/list')
            .replace(queryParameters: <String, String>{
          'after_memory_id': '$cursor', 'limit': '$pageSize',
        });
        final preparedResponse = await _sessionHttpWithGuard(
                () => _assertMemoryAccessCurrent(mvk, memoryGeneration))
            .get(uri, headers: _defaultHeaders(authToken: authToken))
            .timeout(const Duration(seconds: 12));
        _assertMemoryAccessCurrent(mvk, memoryGeneration);
        if (preparedResponse.statusCode != 200) {
          _throwIfAuthExpired(preparedResponse.statusCode,
              preparedResponse.body);
          _throwIfDeviceNotTrusted(
              preparedResponse.statusCode, preparedResponse.body);
          throw Exception(_formatBackendError(
            prefix: 'Older Memory list failed',
            statusCode: preparedResponse.statusCode,
            responseBody: preparedResponse.body,
          ));
        }
        final body = jsonDecode(preparedResponse.body);
        if (body is! Map || body['copies'] is! List ||
            body['unavailable_count'] is! int ||
            body['next_after_memory_id'] is! int ||
            body['has_more'] is! bool) {
          throw const FormatException('Invalid older Memory list');
        }
        final batch = body['copies'] as List;
        final unavailable = body['unavailable_count'] as int;
        final next = body['next_after_memory_id'] as int;
        final hasMore = body['has_more'] as bool;
        final batchCount = batch.length + unavailable;
        if (unavailable < 0 || batchCount > pageSize ||
            (batchCount > 0 && next <= cursor) ||
            (batchCount == 0 && next != cursor) ||
            (hasMore && batchCount != pageSize)) {
          throw const FormatException('Invalid older Memory page');
        }
        processed += batchCount;
        if (processed > 5000) {
          throw const FormatException('Too many older Memories');
        }
        sourceUnavailable += unavailable;
        for (final raw in batch) {
          if (raw is! Map) {
            throw const FormatException('Invalid older Memory copy');
          }
          final copy = Map<String, dynamic>.from(raw);
          final id = copy['legacy_memory_id'];
          final envelope = copy['payload_ciphertext'];
          if (id is! int || id <= cursor || id > next || !seen.add(id) ||
              envelope is! String || envelope.isEmpty) {
            throw const FormatException('Invalid older Memory copy');
          }
          encodedBytes += envelope.length;
          if (encodedBytes > 64 * 1024 * 1024) {
            throw const FormatException('Older Memory list is too large');
          }
          prepared.add(copy);
        }
        cursor = next;
        if (!hasMore) break;
      }
    }
    if (inventoryGeneration != null &&
        inventoryGeneration != await _readMemoryInventoryGeneration(
          authToken: authToken,
          mvk: mvk,
          sessionGeneration: memoryGeneration,
        )) {
      throw const MemoryInventoryIncompleteException();
    }
    final memoryKey =
        await vault_key_hierarchy.VaultKeyHierarchy(mvk).memoryKey();
    final items = <Map<String, dynamic>>[];
    final counts = <String, int>{};
    var unavailableCount = sourceUnavailable;
    // A write preflight must see all records, not just the dashboard's cap.
    final combined = <dynamic>[...decoded, ...prepared];
    final selected = limit <= 0 ? combined : combined.take(limit);
    for (final raw in selected) {
      if (raw is! Map) continue;
      final envelope = raw['payload_ciphertext'];
      if (envelope is! String || envelope.isEmpty) {
        unavailableCount++;
        continue;
      }
      try {
        final plaintext = await vault_key_hierarchy.aesGcmUnwrap(
          memoryKey,
          vault_key_hierarchy.b64urlDecode(envelope),
        );
        _assertMemoryAccessCurrent(mvk, memoryGeneration);
        final payload = jsonDecode(utf8.decode(plaintext));
        if (payload is! Map) {
          unavailableCount++;
          continue;
        }
        final type =
            '${raw['memory_type'] ?? payload['memory_type'] ?? 'note'}';
        items.add(<String, dynamic>{
          ...Map<String, dynamic>.from(payload),
          'id': raw['memory_record_id'] ?? raw['memory_id'],
          'memory_type': type,
          'created_at': raw['created_at'],
          'updated_at': raw['updated_at'],
          if (raw['legacy_memory_id'] is int)
            'legacy_memory_id': raw['legacy_memory_id'],
          if (raw['source_snapshot'] is String)
            'source_snapshot': raw['source_snapshot'],
        });
        counts[type] = (counts[type] ?? 0) + 1;
      } catch (_) {
        _assertMemoryAccessCurrent(mvk, memoryGeneration);
        // One corrupt/legacy envelope must not hide the user's other memories.
        unavailableCount++;
      }
    }
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    return <String, dynamic>{
      'items': items,
      'counts': counts,
      'engine': 'ciphertext',
      'unavailable_count': unavailableCount,
      if (inventoryGeneration != null) 'generation': inventoryGeneration,
    };
  }

  Future<String?> _checkMemoryTitleAvailable({
    required String authToken,
    required String title,
    String? editingMemoryId,
  }) async {
    final inventory = await listZkMemories(authToken: authToken, limit: 0);
    // Older-client edits invalidate the prepared copy. An unavailable row may
    // contain this title, so a private V2 write must not guess that it is free.
    if (kEnableLegacyMemoryV2ActiveRead &&
        (inventory['unavailable_count'] is! int ||
            (inventory['unavailable_count'] as int) != 0)) {
      throw const MemoryInventoryIncompleteException();
    }
    final rows = ((inventory['items'] as List?) ?? const [])
        .whereType<Map>()
        .map((row) => Map<String, dynamic>.from(row));
    if (memoryTitleConflicts(
      title: title,
      memories: rows,
      editingMemoryId: editingMemoryId,
    )) {
      throw const MemoryTitleConflictException();
    }
    if (!kEnableLegacyMemoryV2ActiveRead) return null;
    final generation = inventory['generation'];
    if (generation is! String) {
      throw const MemoryInventoryIncompleteException();
    }
    return generation;
  }

  void _assertMemoryAccessCurrent(Object mvk, int generation) {
    if (!identical(zk_mvk_store.ZkActiveMvk.current(), mvk) ||
        st.SessionTermination.instance.generation != generation ||
        st.SessionTermination.instance.isTerminated) {
      throw StateError(
          'Vault memory access changed. Unlock again to continue.');
    }
  }

  Future<void> deleteZkMemory({
    required String authToken,
    required String memoryId,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/vault/ciphertext/vault-ai-memory/'
      '${Uri.encodeComponent(memoryId)}',
    );
    final response = await _sessionHttp.delete(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Memory delete failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
  }

  Future<void> upsertZkMemory({
    required String authToken,
    required Map<String, dynamic> data,
    String? memoryId,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) throw StateError('Vault encryption key is unavailable');
    final privateReadback = PrivateZkPinTransportSession.active;
    final memoryGeneration = st.SessionTermination.instance.generation;
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    final hierarchy = vault_key_hierarchy.VaultKeyHierarchy(mvk);
    final memoryKey = await hierarchy.memoryKey();
    final lookupKey = await hierarchy.memoryLookupKey();
    final lookupText = '${data['title'] ?? data['memory_key'] ?? 'memory'}';
    final envelope = await vault_key_hierarchy.aesGcmWrap(
      memoryKey,
      utf8.encode(jsonEncode(data)),
    );
    final lookupHash = await vault_key_hierarchy.keyedLookupHash(
      lookupKey,
      utf8.encode(lookupText.trim().toLowerCase()),
    );
    final recordCanonical = <String>[
      '${data['memory_type'] ?? 'note'}',
      lookupText.trim().toLowerCase(),
      '${data['value'] ?? data['memory_value'] ?? ''}'.trim().toLowerCase(),
    ].join('\u0000');
    final recordHash = await vault_key_hierarchy.keyedLookupHash(
      lookupKey,
      utf8.encode(recordCanonical),
    );
    final resolvedMemoryId =
        memoryId ?? 'memory-${vault_key_hierarchy.b64urlEncode(recordHash)}';
    final memoryInventoryGeneration = await _checkMemoryTitleAvailable(
      authToken: authToken,
      title: lookupText,
      editingMemoryId: memoryId ?? (privateReadback ? resolvedMemoryId : null),
    );
    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-ai-memory');
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    final response = await _sessionHttpWithGuard(
        () => _assertMemoryAccessCurrent(mvk, memoryGeneration)).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(<String, dynamic>{
        'memory_id': resolvedMemoryId,
        'memory_type': '${data['memory_type'] ?? 'note'}',
        'memory_lookup_hash': vault_key_hierarchy.b64urlEncode(lookupHash),
        'payload_ciphertext': vault_key_hierarchy.b64urlEncode(envelope),
        'replace_existing': memoryId != null,
        if (memoryInventoryGeneration != null)
          'expected_memory_generation': memoryInventoryGeneration,
      }),
    );
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    if (response.statusCode == 409) {
      if (_memoryGenerationConflict(response.body)) {
        throw const MemoryInventoryIncompleteException();
      }
      throw const MemoryTitleConflictException();
    }
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Memory save failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    if (privateReadback) {
      try {
        await _verifyZkMemoryReadback(
          authToken: authToken,
          mvk: mvk,
          memoryGeneration: memoryGeneration,
          memoryId: resolvedMemoryId,
          memoryType: '${data['memory_type'] ?? 'note'}',
          lookupHash: vault_key_hierarchy.b64urlEncode(lookupHash),
          expectedPayloadJson: jsonEncode(data),
        );
      } on AuthExpiredException {
        rethrow;
      } on SessionTerminatedException {
        rethrow;
      } on DeviceNotTrustedException {
        rethrow;
      } catch (_) {
        throw const MemorySaveReadbackException();
      }
    }
  }

  Future<void> _verifyZkMemoryReadback({
    required String authToken,
    required SecretKey mvk,
    required int memoryGeneration,
    required String memoryId,
    required String memoryType,
    required String lookupHash,
    required String expectedPayloadJson,
  }) async {
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-ai-memory')
        .replace(queryParameters: {'memory_lookup_hash': lookupHash});
    final response = await _sessionHttpWithGuard(
      () => _assertMemoryAccessCurrent(mvk, memoryGeneration),
    ).get(
      uri,
      headers: _defaultHeaders(authToken: authToken),
    ).timeout(const Duration(seconds: 12));
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw StateError('Memory save could not be verified. Refresh Memory.');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! List) {
      throw StateError('Memory save could not be verified. Refresh Memory.');
    }
    final matches = decoded.whereType<Map>().where((row) =>
        row['memory_id'] == memoryId &&
        row['memory_type'] == memoryType &&
        row['memory_lookup_hash'] == lookupHash).toList();
    if (matches.length != 1 ||
        matches.single['payload_ciphertext'] is! String) {
      throw StateError('Memory save could not be verified. Refresh Memory.');
    }
    final memoryKey = await vault_key_hierarchy.VaultKeyHierarchy(mvk)
        .memoryKey();
    final plaintext = await vault_key_hierarchy.aesGcmUnwrap(
      memoryKey,
      vault_key_hierarchy.b64urlDecode(
        matches.single['payload_ciphertext'] as String,
      ),
    );
    _assertMemoryAccessCurrent(mvk, memoryGeneration);
    if (utf8.decode(plaintext) != expectedPayloadJson) {
      throw StateError('Memory save could not be verified. Refresh Memory.');
    }
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
    final resp = await _sessionHttp.post(
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
    int? expectedTitleRevision,
    required String itemType,
    required String service,
    required Map<String, dynamic> payload,
  }) async {
    if (existingItemId != null && existingItemId <= 0) {
      throw ArgumentError('A saved-item edit requires a valid existing ID');
    }
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) {
      _requireSavedItemMutationIdentity(authToken, null);
      return null;
    }
    void checkMutationKey() {
      _requireSavedItemKey(mvk);
      _requireSavedItemMutationIdentity(authToken, mvk);
    }
    checkMutationKey();
    final indexedWrite =
        kEnableKeylessSavedItemWrite && kEnableKeylessSavedItemRead;
    int? titleRevision = expectedTitleRevision;
    if (indexedWrite && existingItemId != null && titleRevision == null) {
      final current = await _listZkVaultItems(authToken: authToken);
      checkMutationKey();
      final rows = (current['items'] as List? ?? const [])
          .whereType<Map>()
          .where((row) => row['id'] == existingItemId)
          .toList();
      if (rows.length != 1 || rows.single['title_revision'] is! int) {
        throw StateError('Private saved-item revision is unavailable');
      }
      titleRevision = rows.single['title_revision'] as int;
    }
    final titleLookup = indexedWrite
        ? await _savedItemTitleLookupHash(mvk, itemType, service) : null;
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
    checkMutationKey();
    final body = <String, dynamic>{
      if (existingItemId != null) 'item_id': existingItemId,
      'mutation_intent': existingItemId == null ? 'create' : 'edit',
      if (titleLookup != null) 'title_lookup_hash': titleLookup,
      if (indexedWrite && existingItemId != null)
        'expected_title_revision': titleRevision,
      'item_type_ciphertext': vault_key_hierarchy.b64urlEncode(itCt),
      'service_ciphertext': vault_key_hierarchy.b64urlEncode(svcCt),
      'payload_ciphertext': vault_key_hierarchy.b64urlEncode(pyCt),
    };
    final uri = Uri.parse('$baseUrl/vault/ciphertext/vault-items');
    final resp = await _sessionHttpWithGuard(checkMutationKey).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    checkMutationKey();
    if (resp.statusCode != 200) {
      // Fail closed for ZK — a broken ciphertext write must NOT
      // silently fall back to plaintext.
      throwIfSavedItemUpdateRequired(resp.statusCode, resp.body);
      _throwIfAuthExpired(resp.statusCode, resp.body);
      _throwIfDeviceNotTrusted(resp.statusCode, resp.body);
      _throwSavedItemTitleConflict(resp.statusCode, resp.body);
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

  /// Persist a generated-login draft on the same client-encrypted path used
  /// by the Logins dashboard, then consume the server's transient draft.
  /// Credential values are never sent to the finalize endpoint.
  Future<Map<String, dynamic>> saveGeneratedLoginDraftCiphertext({
    required String authToken,
    required String pin,
    required String draftId,
    required String service,
    required Map<String, dynamic> fields,
  }) async {
    final safeDraftId = draftId.trim();
    final safeService = service.trim();
    if (safeDraftId.isEmpty || safeService.isEmpty || fields.isEmpty) {
      throw ArgumentError('Generated login draft is incomplete');
    }
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    if (mvk == null) {
      throw StateError('Vault encryption key is unavailable');
    }

    // Only the same encrypted draft identity is an idempotent retry.
    final current = await _listZkVaultItems(authToken: authToken);
    int? existingItemId;
    var savedService = safeService;
    for (final raw in (current['items'] as List? ?? const [])) {
      if (raw is! Map) continue;
      final type = '${raw['item_type'] ?? ''}'.trim().toLowerCase();
      if ((type == 'login' || type == 'credential') &&
          raw['draft_id'] == safeDraftId) {
        existingItemId = (raw['id'] as num?)?.toInt();
        savedService = '${raw['service'] ?? safeService}';
        break;
      }
    }
    if (existingItemId == null) {
      final legacy = (kEnableKeylessSavedItemRead ||
              ZkPinFreeItemReadSession.instance.activeForToken(authToken) ||
              kEnableZkPinFreeSavedItemIndex)
          ? await _listZkItemMetadata(authToken: authToken, mvk: mvk)
          : await _listLegacyVaultSecureItems(
              vaultName: '',
              pin: pin,
              authToken: authToken,
              beforeResponse: () => _requireSavedItemKey(mvk),
            );
      final rows = [
        ...(current['items'] as List? ?? const []),
        ...(legacy['items'] as List? ?? const []),
      ];
      if (rows.whereType<Map>().any((row) =>
          const {'login', 'credential'}
              .contains('${row['item_type']}'.toLowerCase()) &&
          _savedItemTitleIdentity('${row['service']}') ==
              _savedItemTitleIdentity(safeService))) {
        throw const SavedItemConflictException(duplicate: true);
      }
    }

    _requireSavedItemKey(mvk);
    final saved = existingItemId != null
        ? <String, dynamic>{'item_id': existingItemId, 'created': false}
        : await tryZkVaultItemCiphertextUpsert(
            baseUrl: baseUrl,
            authToken: authToken,
            existingItemId: existingItemId,
            itemType: 'login',
            service: safeService,
            payload: <String, dynamic>{
              'fields': Map<String, dynamic>.from(fields),
              'source': 'generated_login_draft',
              'draft_id': safeDraftId,
            },
          );
    final itemId = (saved?['item_id'] as num?)?.toInt();
    if (itemId == null) {
      throw StateError('Generated login could not be encrypted');
    }

    final finalizeUri = Uri.parse(
      '$baseUrl/vault/ciphertext/vault-items/generated-drafts/finalize',
    );
    _requireSavedItemKey(mvk);
    final finalized = await _sessionHttp.post(
      finalizeUri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(<String, dynamic>{
        'item_id': itemId,
        'draft_id': safeDraftId,
      }),
    );
    if (finalized.statusCode != 200) {
      _throwIfAuthExpired(finalized.statusCode, finalized.body);
      _throwIfDeviceNotTrusted(finalized.statusCode, finalized.body);
      throw Exception(_formatBackendError(
        prefix: 'Generated login finalize failed',
        statusCode: finalized.statusCode,
        responseBody: finalized.body,
      ));
    }
    return <String, dynamic>{
      ...saved!,
      'service': savedService,
      'item_type': 'login',
    };
  }

  Future<Map<String, dynamic>> deleteVaultSecureItem({
    required String vaultName,
    required String service,
    required String itemType,
    required String pin,
    required String authToken,
    String? itemId,
  }) async {
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    _requireSavedItemMutationIdentity(authToken, mvk);
    if (mvk != null) {
      final existing = await _resolveSavedItem(
        vaultName: vaultName,
        pin: pin,
        authToken: authToken,
        service: service,
        itemType: itemType,
        itemId: itemId,
      );
      _requireSavedItemKey(mvk);
      _requireSavedItemMutationIdentity(authToken, mvk);
      itemId = existing?['id']?.toString() ?? itemId;
      if (existing?['storage_engine'] == 'ciphertext' && itemId != null) {
        final uri = Uri.parse(
          '$baseUrl/vault/ciphertext/vault-items/$itemId',
        );
        final response = await _sessionHttpWithGuard(
          () {
            _requireSavedItemKey(mvk);
            _requireSavedItemMutationIdentity(authToken, mvk);
          },
        ).delete(
          uri,
          headers: _defaultHeaders(authToken: authToken),
        );
        _requireSavedItemKey(mvk);
        _requireSavedItemMutationIdentity(authToken, mvk);
        if (response.statusCode != 200) {
          _throwIfAuthExpired(response.statusCode, response.body);
          _throwIfDeviceNotTrusted(response.statusCode, response.body);
          throw Exception(_formatBackendError(
            prefix: 'Could not delete saved item',
            statusCode: response.statusCode,
            responseBody: response.body,
          ));
        }
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      if ((kEnableKeylessLegacySavedItemDelete ||
              signedSavedItemMutationOfferedForToken(authToken)) &&
          existing?['storage_engine'] == 'legacy_compatibility') {
        final exactId = int.tryParse(itemId ?? '');
        final deleter = legacyZkItemDeleter;
        if (exactId == null || exactId <= 0 || deleter == null ||
            existing?['id'] != exactId ||
            existing?['item_type'] != itemType ||
            existing?['service'] != service) {
          throw StateError('Private saved-item deletion is unavailable');
        }
        await deleter(
          itemId: exactId,
          itemType: itemType,
          service: service,
        );
        _requireSavedItemKey(mvk);
        _requireSavedItemMutationIdentity(authToken, mvk);
        return <String, dynamic>{'status': 'deleted', 'item_id': exactId};
      }
      // No ciphertext row matched. A ZK operation must not fall through to
      // the legacy PIN-bearing delete endpoint.
      throw StateError(
          'Legacy saved-item deletion is unavailable until migration.');
    }
    // Never retry a saved-item delete with a PIN after a key/session loss.
    throw StateError('Unlock your vault before deleting a saved item.');
  }

  Future<Map<String, dynamic>> deleteVaultFile({
    required String vaultName,
    required String fileId,
    String? pin,
    String? zkProofToken,
    required String authToken,
    bool Function()? responseIsCurrent,
  }) async {
    void checkAccess() {
      if (responseIsCurrent?.call() == false) {
        throw StateError(
            'File deletion access changed. Select the file again.');
      }
    }

    checkAccess();
    final mutationOffered = signedFileMutationOfferedForToken(authToken);
    if (mutationOffered && zkProofToken == null) {
      throw StateError('Private file deletion needs vault verification.');
    }
    final uri = Uri.parse(mutationOffered
        ? '$baseUrl/manage/file/delete-proof'
        : '$baseUrl/manage/file/delete');

    final response = await _sessionHttpWithGuard(checkAccess).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'vault_name': '',
        'file_id': fileId,
        ..._pinOrZkProofBody(pin: pin, zkProofToken: zkProofToken),
      }),
    );

    // Reject a stale response before coded auth errors can terminate a newer
    // session. The absent optional lease preserves existing callers.
    if (responseIsCurrent?.call() == false) {
      throw StateError('File deletion access changed. Select the file again.');
    }
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
    String? vaultHandle,
  }) async {
    if (kPrivateOnlyTransportRejectPin ||
        signedPrivateChatOfferedForToken(authToken) ||
        signedFileListOfferedForToken(authToken) ||
        signedFileDownloadOfferedForToken(authToken) ||
        ZkPinFreeFileSession.instance.listOfferedForToken(authToken) ||
        ZkPinFreeFileSession.instance.downloadOfferedForToken(authToken) ||
        private_content_guard.blocksZkRelatedFilesPinRoute(
        vaultHandle: vaultHandle)) {
      throw const private_content_guard.PrivateContentSearchUnavailable(
        private_content_guard.relatedFilesPrivateMessage,
      );
    }
    final uri = Uri.parse('$baseUrl/files/$fileId/related');
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.get(
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
    final response = await _sessionHttp.get(
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
    final response = await _sessionHttp.get(
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
    final response = await _sessionHttp.get(
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

  /// Wallet V2 migration transport. The service performs MVK wrapping and
  /// exact readback locally; this boundary accepts only ciphertext metadata
  /// and a one-time OPAQUE proof, never a PIN or plaintext wallet secret.
  Future<Map<String, dynamic>> walletV2MigrationPost({
    required String authToken,
    required String path,
    required Map<String, dynamic> body,
  }) async {
    const stage = '/vault/wallet-v2/migrate/stage';
    const retire = '/vault/wallet-v2/migrate/retire';
    final allowed = path == stage
        ? const <String>{
            'legacy_item_id', 'source_snapshot', 'wallet_record_id', 'chain',
            'network', 'asset', 'public_address', 'wallet_label',
            'payload_ciphertext', 'envelope_version',
          }
        : path == retire
            ? const <String>{
                'legacy_item_id', 'wallet_record_id', 'source_snapshot',
                'readback_receipt', 'zk_proof_token',
                'client_verified_exact_bytes',
              }
            : null;
    if (allowed == null || body.keys.toSet().difference(allowed).isNotEmpty ||
        !body.keys.toSet().containsAll(allowed)) {
      throw StateError('Invalid wallet migration request');
    }
    final response = await _sessionHttp.post(
      Uri.parse('$baseUrl$path'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Wallet migration failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Invalid wallet migration response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> walletV2Read({
    required String authToken,
    required String path,
  }) async {
    if (!RegExp(r'^/vault/wallet-v2/[A-Za-z0-9_-]{16,128}$')
        .hasMatch(path)) {
      throw StateError('Invalid wallet V2 read path');
    }
    final response = await _sessionHttp.get(
      Uri.parse('$baseUrl$path'),
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Wallet V2 read failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Invalid wallet V2 response');
    }
    return decoded;
  }

  /// New-wallet V2 transport. A newly generated wallet is staged first;
  /// only an exact local readback may publish it for Receive and Send.
  Future<Map<String, dynamic>> walletV2NewPost({
    required String authToken,
    required String path,
    required Map<String, dynamic> body,
  }) async {
    const stage = '/vault/wallet-v2';
    final publish = RegExp(
      r'^/vault/wallet-v2/[A-Za-z0-9_-]{16,128}/publish-new$',
    );
    final allowed = path == stage
        ? const <String>{
            'wallet_record_id', 'chain', 'network', 'asset',
            'public_address', 'wallet_label', 'payload_ciphertext',
            'envelope_version', 'migration_state',
          }
        : publish.hasMatch(path)
            ? const <String>{
                'readback_receipt', 'client_verified_exact_bytes',
              }
            : null;
    if (allowed == null ||
        body.keys.toSet().difference(allowed).isNotEmpty ||
        !body.keys.toSet().containsAll(allowed) ||
        (path == stage && body['migration_state'] != 'migration_pending')) {
      throw StateError('Invalid wallet V2 request');
    }
    final response = await _sessionHttp.post(
      Uri.parse('$baseUrl$path'),
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Wallet V2 request failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Invalid wallet V2 response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> walletV2List({
    required String authToken,
  }) async {
    final response = await _sessionHttp.get(
      Uri.parse('$baseUrl/vault/wallet-v2'),
      headers: _defaultHeaders(authToken: authToken),
    );
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception(_formatBackendError(
        prefix: 'Wallet V2 list failed',
        statusCode: response.statusCode,
        responseBody: response.body,
      ));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Invalid wallet V2 list response');
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
  }) =>
      _postCryptoOutgoingHistoryCiphertext(
        authToken: authToken,
        network: network,
        signatureLookupHash: signatureLookupHash,
        outcomePayloadCiphertext: outcomePayloadCiphertext,
      );

  /// Only the new PAXG flow opts into the captured wallet-response lease.
  /// Legacy history persistence keeps its existing dispatch semantics.
  Future<Map<String, dynamic>> postCryptoWalletPaxgOutgoingHistoryCiphertext({
    required String authToken,
    required String signatureLookupHash,
    required String outcomePayloadCiphertext,
  }) =>
      _postCryptoOutgoingHistoryCiphertext(
        authToken: authToken,
        network: 'mainnet',
        signatureLookupHash: signatureLookupHash,
        outcomePayloadCiphertext: outcomePayloadCiphertext,
        scopedPaxg: true,
      );

  /// KAG uses the same captured private-operation lease as PAXG.
  Future<Map<String, dynamic>> postCryptoWalletKagOutgoingHistoryCiphertext({
    required String authToken,
    required String signatureLookupHash,
    required String outcomePayloadCiphertext,
  }) =>
      _postCryptoOutgoingHistoryCiphertext(
        authToken: authToken,
        network: 'mainnet',
        signatureLookupHash: signatureLookupHash,
        outcomePayloadCiphertext: outcomePayloadCiphertext,
        scopedPaxg: true,
      );

  Future<Map<String, dynamic>> _postCryptoOutgoingHistoryCiphertext({
    required String authToken,
    required String network,
    required String signatureLookupHash,
    required String outcomePayloadCiphertext,
    bool scopedPaxg = false,
  }) async {
    if (scopedPaxg) _assertWalletResponseCurrent();
    final uri = Uri.parse('$baseUrl/vault/ciphertext/crypto-history');
    final response = await (scopedPaxg ? _walletHttp : _sessionHttp).post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'network': network,
        'signature_lookup_hash': signatureLookupHash,
        'outcome_payload_ciphertext': outcomePayloadCiphertext,
      }),
    );
    if (scopedPaxg) _assertWalletResponseCurrent();
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
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.get(
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
    _assertWalletResponseCurrent();
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/receive',
    );
    final response = await _walletHttp.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    _assertWalletResponseCurrent();
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
    _assertWalletResponseCurrent();
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
    final response = await _walletHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    _assertWalletResponseCurrent();
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
    _assertWalletResponseCurrent();
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/balance?address=$address',
    );
    final response = await _walletHttp.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    _assertWalletResponseCurrent();
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
    _assertWalletResponseCurrent();
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/transactions?limit=$limit',
    );
    final response = await _walletHttp.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    _assertWalletResponseCurrent();
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
    final response = await _sessionHttp.get(
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
    final response = await _sessionHttp.get(
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
    _assertWalletResponseCurrent();
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
    final response = await _walletHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    _assertWalletResponseCurrent();
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
    _assertWalletResponseCurrent();
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
    final response = await _walletHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode(body),
    );
    _assertWalletResponseCurrent();
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
    _assertWalletResponseCurrent();
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/encrypted-secret',
    );
    final response = await _walletHttp.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    _assertWalletResponseCurrent();
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

  Future<Map<String, dynamic>> getCryptoWalletAssetCatalog({
    required String authToken,
    bool Function()? responseIsCurrent,
  }) async {
    void checkAccess() {
      if (responseIsCurrent?.call() == false) {
        throw StateError('Asset catalog access changed');
      }
    }

    final uri = Uri.parse('$baseUrl/crypto/wallet/asset-catalog').replace(
      queryParameters: {'_': DateTime.now().millisecondsSinceEpoch.toString()},
    );
    final headers = _defaultHeaders(authToken: authToken, json: false);
    headers['Cache-Control'] = 'no-cache, no-store';
    final response =
        await _sessionHttpWithGuard(checkAccess).get(uri, headers: headers);
    if (responseIsCurrent != null && !responseIsCurrent()) {
      throw StateError('Asset catalog access changed');
    }
    if (response.statusCode != 200) {
      _throwIfAuthExpired(response.statusCode, response.body);
      _throwIfDeviceNotTrusted(response.statusCode, response.body);
      throw Exception('Asset catalog is unavailable');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw Exception('Invalid asset catalog response');
    }
    return decoded;
  }

  Future<Map<String, dynamic>> getCryptoWalletFeatures({
    required String authToken,
    bool Function()? responseIsCurrent,
  }) async {
    void checkAccess() {
      if (responseIsCurrent?.call() == false) {
        throw StateError('Asset availability access changed');
      }
    }

    final uri = Uri.parse('$baseUrl/crypto/wallet/features').replace(
      queryParameters: <String, String>{
        '_': DateTime.now().millisecondsSinceEpoch.toString(),
      },
    );
    final headers = _defaultHeaders(authToken: authToken, json: false);
    headers['Cache-Control'] = 'no-cache, no-store';
    headers['Pragma'] = 'no-cache';
    final response = await _sessionHttpWithGuard(checkAccess).get(
      uri,
      headers: headers,
    );
    if (responseIsCurrent != null && !responseIsCurrent()) {
      throw StateError('Asset availability access changed');
    }
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
    final response = await _sessionHttp.get(uri, headers: headers);
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
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.post(
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
    final response = await _sessionHttp.get(
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
    final response = await _sessionHttp.get(uri, headers: headers);
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
    _assertWalletResponseCurrent();
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/$asset/transaction/$txHash',
    );
    final response = await _walletHttp.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    _assertWalletResponseCurrent();
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
    _assertWalletResponseCurrent();
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/outgoing/history',
    );
    final response = await _walletHttp.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    _assertWalletResponseCurrent();
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
  }) =>
      _postCryptoWalletSendFeeEstimateNetwork(
        network: network,
        fromAddress: fromAddress,
        destinationAddress: destinationAddress,
        asset: asset,
        authToken: authToken,
      );

  /// PAXG gas simulation must use the exact reviewed 18-decimal token debit.
  /// This closed helper cannot select another chain or an arbitrary contract;
  /// existing cryptocurrency fee-estimate requests retain their old payload.
  Future<Map<String, dynamic>> postCryptoWalletPaxgSendFeeEstimateNetwork({
    required String fromAddress,
    required String destinationAddress,
    required String amountEth,
    required String authToken,
  }) {
    if (parseAssetBaseUnits(amountEth, 18) <= BigInt.zero) {
      throw const FormatException('Invalid PAXG amount');
    }
    return _postCryptoWalletSendFeeEstimateNetwork(
      network: 'ethereum_mainnet',
      fromAddress: fromAddress,
      destinationAddress: destinationAddress,
      asset: 'PAXG_ERC20',
      amountEth: amountEth,
      authToken: authToken,
    );
  }

  /// Closed issuer-verified Ethereum KAG fee quote. Exact debit is mandatory;
  /// neither a different chain nor an arbitrary silver contract is accepted.
  Future<Map<String, dynamic>> postCryptoWalletKagSendFeeEstimateNetwork({
    required String fromAddress,
    required String destinationAddress,
    required String amountEth,
    required String authToken,
  }) {
    if (parseAssetBaseUnits(amountEth, 18) <= BigInt.zero) {
      throw const FormatException('Invalid KAG amount');
    }
    return _postCryptoWalletSendFeeEstimateNetwork(
      network: 'ethereum_mainnet',
      fromAddress: fromAddress,
      destinationAddress: destinationAddress,
      asset: 'KAG_ERC20',
      amountEth: amountEth,
      authToken: authToken,
    );
  }

  Future<Map<String, dynamic>> _postCryptoWalletSendFeeEstimateNetwork({
    required String network,
    required String fromAddress,
    required String destinationAddress,
    required String asset,
    required String authToken,
    String? amountEth,
  }) async {
    _assertWalletResponseCurrent();
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/send/fee_estimate',
    );
    final response = await _walletHttp.post(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: true),
      body: jsonEncode({
        'fromAddress': fromAddress,
        'destinationAddress': destinationAddress,
        'asset': asset,
        if (amountEth != null) 'amountEth': amountEth,
      }),
    );
    _assertWalletResponseCurrent();
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
    _assertWalletResponseCurrent();
    final uri = Uri.parse(
      '$baseUrl/crypto/wallet/network/$network/draft/$draftId/expiry',
    );
    final response = await _walletHttp.get(
      uri,
      headers: _defaultHeaders(authToken: authToken, json: false),
    );
    _assertWalletResponseCurrent();
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
}
