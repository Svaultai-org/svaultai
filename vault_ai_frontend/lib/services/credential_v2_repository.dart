import 'credential_v2.dart';
import 'credential_v2_api.dart';
import 'credential_v2_qa_diagnostics.dart';
import 'dart:math';

const bool _qaV2Diagnostics =
    bool.fromEnvironment('QA_AUTH_DIAGNOSTICS', defaultValue: false);
void _qaV2Trace(String stage, {String? error}) {
  if (!_qaV2Diagnostics) return;
  qaV2HydrationTrace(stage, error: error);
  final safeError = error == null ? '' : ' error=$error';
  print('[qa-v2-create] $stage$safeError');
}

class CredentialV2LookupIntent {
  final bool listAll;
  final String? service;
  const CredentialV2LookupIntent._({required this.listAll, this.service});
}

class CredentialV2CreateIntent {
  final String? service;
  final String? username;
  final bool explicitlyAnother;
  const CredentialV2CreateIntent({
    this.service,
    this.username,
    this.explicitlyAnother = false,
  });
}

class CredentialV2DeleteIntent {
  final String service;
  const CredentialV2DeleteIntent(this.service);
}

/// Recognizes conversational requests to start a login-creation flow.  This
/// deliberately extracts arbitrary service labels instead of maintaining a
/// list of brands. The caller generates and saves the secret locally.
CredentialV2CreateIntent? parseCredentialV2CreateIntent(String text) {
  var normalized = text.trim().replaceFirst(RegExp(r'[.?!]+$'), '').trim();
  if (normalized.isEmpty) return null;
  final usernameMatch = RegExp(
    r'\s+(?:with|using)\s+(.+?)\s+as\s+(?:the\s+)?(?:username|email)(?:\s+address)?$',
    caseSensitive: false,
  ).firstMatch(normalized);
  final suppliedUsername = usernameMatch?.group(1)?.trim();
  if (usernameMatch != null) {
    normalized = normalized.substring(0, usernameMatch.start).trim();
  }
  final explicitlyAnother =
      RegExp(r'\b(?:another|second|additional)\b', caseSensitive: false)
          .hasMatch(normalized);
  normalized = normalized.replaceAll(
      RegExp(r'\b(?:another|second|additional)\b', caseSensitive: false),
      'new');
  final patterns = <RegExp>[
    RegExp(
      r'^(?:i\s+(?:need|want|would\s+like)|could\s+you\s+(?:make|create|generate))(?:\s+me)?\s+(?:(?:a|an)\s+)?(?:new\s+)?(?:login|credentials?|account)\s+(?:for\s+)?(.+)$',
      caseSensitive: false,
    ),
    RegExp(
      r'^(?:please\s+)?(?:create|generate|make|add|save|set\s*up|give)(?:\s+me)?(?:\s+my)?\s+(?:(?:a|an)\s+)?(?:new\s+)?(.+?)\s+(?:account\s+)?(?:login|logins|credential|credentials|account)(?:\s+for\s+me)?$',
      caseSensitive: false,
    ),
    RegExp(
      r'^(?:please\s+)?(?:create|generate|make|add|save|set\s*up|give)(?:\s+me)?(?:\s+my)?\s+(?:(?:a|an)\s+)?(?:new\s+)?(?:account\s+)?(?:login|logins|credential|credentials|account)\s+(?:for\s+)?(.+)$',
      caseSensitive: false,
    ),
    RegExp(
      r'^(?:please\s+)?(?:create|generate|make|add|save|set\s*up|give)(?:\s+me)?(?:\s+my)?\s+(?:(?:a|an)\s+)?(?:new\s+)?(?:login|logins|credential|credentials|account)$',
      caseSensitive: false,
    ),
  ];
  for (var index = 0; index < patterns.length; index++) {
    final match = patterns[index].firstMatch(normalized);
    if (match == null) continue;
    final service = match.groupCount == 0 ? null : match.group(1)?.trim();
    return CredentialV2CreateIntent(
      service: service == null || service.isEmpty ? null : service,
      username: suppliedUsername == null || suppliedUsername.isEmpty
          ? null
          : suppliedUsername,
      explicitlyAnother: explicitlyAnother,
    );
  }
  return null;
}

CredentialV2DeleteIntent? parseCredentialV2DeleteIntent(String text) {
  final normalized = text.trim().replaceFirst(RegExp(r'[.?!]+$'), '').trim();
  final patterns = <RegExp>[
    RegExp(
      r'^(?:please\s+)?(?:delete|remove|erase|get\s+rid\s+of)(?:\s+my|\s+the)?\s+(.+?)\s+(?:login|credentials?|account)(?:\s+from\s+(?:my\s+)?vault)?$',
      caseSensitive: false,
    ),
    RegExp(
      r'^(?:please\s+)?(?:delete|remove|erase|get\s+rid\s+of)(?:\s+my|\s+the)?\s+(.+?)(?:\s+from\s+(?:my\s+)?vault)$',
      caseSensitive: false,
    ),
  ];
  for (var index = 0; index < patterns.length; index++) {
    final service = patterns[index].firstMatch(normalized)?.group(1)?.trim();
    if (service != null && service.isNotEmpty) {
      // File/media deletion is arbitrated by the local FileV2 route. Do not
      // reinterpret an explicit media noun or filename extension as a login
      // service merely because both actions use "delete/remove" wording.
      // The second pattern has no explicit credential noun (for example,
      // "remove X from my vault"), so media/file vocabulary anywhere in X
      // must be left for FileV2 arbitration. The explicit login pattern can
      // still delete services whose brand happens to contain such a word.
      if (index == 1 &&
          RegExp(
            r'\b(?:file|document|image|photo|picture|video|audio|recording|voice)\b|\.(?:png|jpe?g|gif|webp|heic|pdf|txt|csv|docx?|xlsx?|pptx?|mp3|m4a|wav|ogg|aac|flac|mp4|mov|m4v|webm|avi|mkv)$',
            caseSensitive: false,
          ).hasMatch(service)) {
        return null;
      }
      return CredentialV2DeleteIntent(service);
    }
  }
  return null;
}

CredentialV2Plaintext generateCredentialV2Plaintext(
  String service, {
  Random? random,
  String? username,
}) {
  final rng = random ?? Random.secure();
  final slug = service
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), '')
      .replaceAll(RegExp(r'^\d+'), '');
  final stem = slug.isEmpty ? 'account' : slug;
  final suffix = List<int>.generate(6, (_) => rng.nextInt(10)).join();
  const upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
  const lower = 'abcdefghijkmnopqrstuvwxyz';
  const digits = '23456789';
  const symbols = '!@#%*-_+=';
  const all = '$upper$lower$digits$symbols';
  final required = <String>[
    upper[rng.nextInt(upper.length)],
    lower[rng.nextInt(lower.length)],
    digits[rng.nextInt(digits.length)],
    symbols[rng.nextInt(symbols.length)],
  ];
  required.addAll(List<String>.generate(
    16,
    (_) => all[rng.nextInt(all.length)],
  ));
  required.shuffle(rng);
  return CredentialV2Plaintext(
    service: service.trim(),
    username: username?.trim().isNotEmpty == true
        ? username!.trim()
        : '${stem}_$suffix',
    password: required.join(),
    url: 'https://www.$stem.com',
    notes: 'Generated locally by SVaultAI.',
  );
}

CredentialV2LookupIntent? parseCredentialV2LookupIntent(String text) {
  final normalized = text.trim();
  if (RegExp(
    r'^(?:show|list|open)\s+(?:me\s+)?(?:my\s+)?saved\s+logins?\??$',
    caseSensitive: false,
  ).hasMatch(normalized)) {
    return const CredentialV2LookupIntent._(listAll: true);
  }
  final match = RegExp(
    r'^(?:show|find|open|get)\s+(?:me\s+)?(?:my\s+)?(.+?)\s+(?:saved\s+)?login\??$',
    caseSensitive: false,
  ).firstMatch(normalized);
  final service = match?.group(1)?.trim();
  if (service == null || service.isEmpty) return null;
  return CredentialV2LookupIntent._(listAll: false, service: service);
}

class DecryptedCredentialV2Record {
  final String recordId;
  final CredentialV2Plaintext plaintext;
  final String migrationState;
  final String verificationState;
  const DecryptedCredentialV2Record(
    this.recordId,
    this.plaintext, {
    this.migrationState = 'v2_written',
    this.verificationState = 'not_verified',
  });
}

String _credentialLookupNormalized(String value) => value
    .toLowerCase()
    .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
    .trim()
    .replaceAll(RegExp(r'\s+'), ' ');

/// Match natural user text against services already decrypted in local
/// memory. The vault's own data supplies the vocabulary; service names and
/// sentence templates are deliberately not embedded here.
List<DecryptedCredentialV2Record> matchCredentialV2RecordsForText(
  String text,
  Iterable<DecryptedCredentialV2Record> records,
) {
  final query = _credentialLookupNormalized(text);
  if (query.isEmpty) return const <DecryptedCredentialV2Record>[];
  final available = records.toList(growable: false);
  final exact = available.where((record) =>
      _credentialLookupNormalized(record.plaintext.service) == query);
  if (exact.isNotEmpty) return exact.toList(growable: false);

  final contained = available.where((record) {
    final service = _credentialLookupNormalized(record.plaintext.service);
    return service.length >= 4 && query.contains(service);
  }).toList(growable: false);
  if (contained.isNotEmpty) return contained;

  final queryTokens = query.split(' ').where((token) => token.length >= 4);
  final scored = <({DecryptedCredentialV2Record record, int score})>[];
  for (final record in available) {
    final service = _credentialLookupNormalized(record.plaintext.service);
    if (service.isEmpty) continue;
    final serviceTokens = service.split(' ');
    final score = queryTokens
        .where((queryToken) => serviceTokens.any(
              (serviceToken) =>
                  serviceToken.startsWith(queryToken) ||
                  queryToken.startsWith(serviceToken),
            ))
        .length;
    if (score > 0) scored.add((record: record, score: score));
  }
  if (scored.isEmpty) return const <DecryptedCredentialV2Record>[];
  final best = scored.map((entry) => entry.score).reduce(
        (left, right) => left > right ? left : right,
      );
  return scored
      .where((entry) => entry.score == best)
      .map((entry) => entry.record)
      .toList(growable: false);
}

bool looksLikePrivateCredentialQuery(String text) {
  final tokens = _credentialLookupNormalized(text).split(' ').toSet();
  return tokens.intersection(const {
    'login',
    'logins',
    'password',
    'passwords',
    'credential',
    'credentials',
    'username',
    'usernames',
  }).isNotEmpty;
}

class CredentialV2Repository {
  final CredentialV2Crypto crypto;
  final CredentialV2Api api;

  const CredentialV2Repository({required this.crypto, required this.api});

  Future<void> create({
    required String recordId,
    required CredentialV2Plaintext credential,
    String? serviceForLookup,
    String? migrationOperationId,
  }) async {
    _qaV2Trace('create_call_entered');
    _qaV2Trace('record_id_created');
    try {
      _qaV2Trace('crypto_derive_credential_key_entered');
      _qaV2Trace('crypto_derive_record_key_entered');
      _qaV2Trace('crypto_encrypt_entered');
      final envelope = await crypto.encrypt(
        recordId: recordId,
        plaintext: credential,
        serviceForLookup: serviceForLookup,
      );
      _qaV2Trace('crypto_encrypt_succeeded');
      _qaV2Trace('blind_index_build_entered');
      _qaV2Trace('blind_index_build_succeeded');
      _qaV2Trace('api_put_entered');
      await api.write(envelope, migrationOperationId: migrationOperationId);
      _qaV2Trace('api_put_dispatched');
      _qaV2Trace('api_put_status_ok');
    } on FormatException {
      _qaV2Trace('create_exception', error: 'request_serialization_failed');
      rethrow;
    } on ArgumentError {
      _qaV2Trace('create_exception', error: 'record_id_generation_failed');
      rethrow;
    } catch (_) {
      _qaV2Trace('create_exception', error: 'unexpected_safe_category');
      rethrow;
    }
  }

  Future<CredentialV2Plaintext> reveal(String recordId) async =>
      crypto.decrypt(await api.read(recordId));

  Future<void> edit({
    required String recordId,
    required CredentialV2Plaintext credential,
    String? serviceForLookup,
    String? migrationOperationId,
  }) =>
      create(
        recordId: recordId,
        credential: credential,
        serviceForLookup: serviceForLookup,
        migrationOperationId: migrationOperationId,
      );

  Future<List<String>> listRecordIds({
    String? blindIndexName,
    String? blindIndexToken,
  }) async =>
      (await api.list(
        blindIndexName: blindIndexName,
        blindIndexToken: blindIndexToken,
      ))
          .map((envelope) => envelope.recordId)
          .toList(growable: false);

  Future<List<DecryptedCredentialV2Record>> listDecrypted() async {
    final envelopes = await api.list();
    final records = <DecryptedCredentialV2Record>[];
    for (final envelope in envelopes) {
      final isTarget = envelope.recordId == qaV2TargetRecordId;
      if (_qaV2Diagnostics && isTarget) {
        _qaV2Trace('target_decrypt_entered');
        _qaV2Trace('target_record_key_derivation_entered');
      }
      try {
        final plaintext = await crypto.decrypt(envelope);
        if (_qaV2Diagnostics && isTarget) {
          _qaV2Trace('target_decrypt_succeeded');
          _qaV2Trace('target_plaintext_parse_entered');
          _qaV2Trace('target_plaintext_parse_succeeded');
        }
        records.add(DecryptedCredentialV2Record(
          envelope.recordId,
          plaintext,
          migrationState: envelope.migrationState,
          verificationState: envelope.verificationState,
        ));
        if (_qaV2Diagnostics && isTarget) {
          _qaV2Trace('target_hydrated_record_created');
          _qaV2Trace('target_added_to_result_list');
        }
      } on FormatException {
        if (_qaV2Diagnostics && isTarget) {
          _qaV2Trace('target_decrypt_exception',
              error: 'aes_gcm_decrypt_failed');
        }
      } on Object {
        if (_qaV2Diagnostics && isTarget) {
          _qaV2Trace('target_decrypt_exception',
              error: 'unexpected_safe_category');
        }
        // Authentication/format failure is isolated to this envelope.
      }
    }
    return records;
  }

  Future<List<DecryptedCredentialV2Record>> exactLookup({
    required String field,
    required String value,
  }) async {
    final token = await crypto.blindIndex(field, value);
    final candidates = await api.list(
      blindIndexName: field,
      blindIndexToken: token,
    );
    final clear = <DecryptedCredentialV2Record>[];
    for (final candidate in candidates) {
      clear.add(DecryptedCredentialV2Record(
        candidate.recordId,
        await crypto.decrypt(candidate),
      ));
    }
    if (clear.isNotEmpty || field != 'service') return clear;

    // Migrated CredentialV2 rows can be valid encrypted records while lacking
    // the current service blind index. A blind-index miss is not authoritative:
    // refresh and compare client-decrypted service metadata before not-found.
    final normalized = normalizeExactLookup(value);
    final fresh = await listDecrypted();
    return fresh
        .where((record) =>
            normalizeExactLookup(record.plaintext.service) == normalized)
        .toList(growable: false);
  }

  Future<void> delete(String recordId) => api.delete(recordId);
}
