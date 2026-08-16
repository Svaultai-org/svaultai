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
  final CredentialV2RequestedField requestedField;
  const CredentialV2LookupIntent._({
    required this.listAll,
    this.service,
    this.requestedField = CredentialV2RequestedField.summary,
  });
}

enum CredentialV2RequestedField { summary, username, password }

String credentialV2LookupReply(
  String service,
  CredentialV2RequestedField requestedField,
) =>
    switch (requestedField) {
      CredentialV2RequestedField.username =>
        'Here is the saved username for your $service login.',
      CredentialV2RequestedField.password =>
        'I found your $service login. Use Reveal password to view it.',
      CredentialV2RequestedField.summary => 'Here is your $service login.',
    };

class CredentialV2CreateIntent {
  final String? service;
  final String? username;
  final String? password;
  final bool explicitlyAnother;
  const CredentialV2CreateIntent({
    this.service,
    this.username,
    this.password,
    this.explicitlyAnother = false,
  });

  bool get hasSuppliedValues =>
      username?.isNotEmpty == true || password?.isNotEmpty == true;
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

  String cleanValue(String? value) => (value ?? '')
      .trim()
      .replaceFirst(RegExp(r'^["\x27`]'), '')
      .replaceFirst(RegExp(r'["\x27`,;]+$'), '');

  CredentialV2CreateIntent? supplied(
    RegExp pattern, {
    required int serviceGroup,
    required int usernameGroup,
    required int passwordGroup,
  }) {
    final match = pattern.firstMatch(normalized);
    if (match == null) return null;
    final service = cleanValue(match.group(serviceGroup));
    final username = cleanValue(match.group(usernameGroup));
    final password = cleanValue(match.group(passwordGroup));
    if (service.isEmpty || username.isEmpty || password.isEmpty) return null;
    return CredentialV2CreateIntent(
      service: service,
      username: username,
      password: password,
    );
  }

  // Credential assertions are creation data even without a leading "save".
  // These anchored shapes keep arbitrary service labels data-driven while
  // ensuring the two explicitly labelled values are never regenerated.
  final suppliedIntent = supplied(
        RegExp(
          r'^username\s+(\S+)\s+(?:and\s+)?(?:password|pass|pwd)\s+(\S+)\s+is\s+my\s+(.+?)\s+login$',
          caseSensitive: false,
        ),
        serviceGroup: 3,
        usernameGroup: 1,
        passwordGroup: 2,
      ) ??
      supplied(
        RegExp(
          r'^my\s+(.+?)\s+username\s+is\s+(\S+)\s+(?:and\s+)?(?:password|pass|pwd)\s+is\s+(\S+)$',
          caseSensitive: false,
        ),
        serviceGroup: 1,
        usernameGroup: 2,
        passwordGroup: 3,
      ) ??
      supplied(
        RegExp(
          r'^(?:save\s+)?(?:my\s+)?(.+?)\s+(?:login\s+)?(?:username|user)\s+(?:is\s+)?(\S+)\s+(?:and\s+)?(?:password|pass|pwd)\s+(?:is\s+)?(\S+)$',
          caseSensitive: false,
        ),
        serviceGroup: 1,
        usernameGroup: 2,
        passwordGroup: 3,
      ) ??
      supplied(
        RegExp(
          r'^(?:save\s+)?(?:my\s+)?(.+?)\s+login\s+is\s+(\S+)\s*(?:/|and)\s*(\S+)$',
          caseSensitive: false,
        ),
        serviceGroup: 1,
        usernameGroup: 2,
        passwordGroup: 3,
      ) ??
      supplied(
        RegExp(
          r'^save\s+(?:my\s+)?(.+?)\s+login\s+(\S+)\s+(?:and\s+)?(?:password|pass|pwd)\s+(\S+)$',
          caseSensitive: false,
        ),
        serviceGroup: 1,
        usernameGroup: 2,
        passwordGroup: 3,
      );
  if (suppliedIntent != null) return suppliedIntent;
  final usernameMatch = RegExp(
    r'\s+(?:with|using)\s+(.+?)\s+as\s+(?:the\s+)?(?:username|email)(?:\s+address)?$',
    caseSensitive: false,
  ).firstMatch(normalized);
  final suppliedUsername = usernameMatch?.group(1)?.trim();
  if (usernameMatch != null) {
    normalized = normalized.substring(0, usernameMatch.start).trim();
  }
  // "Give me my Facebook login" is a possessive retrieval request. Keep
  // "give me a/new Facebook login" available to the creation flow.
  if (RegExp(
    r'^(?:please\s+)?give(?:\s+me)?\s+my\s+.+?\s+(?:login|logins|credential|credentials|account)$',
    caseSensitive: false,
  ).hasMatch(normalized)) {
    return null;
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
  String? password,
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
  final suppliedPassword = password?.trim();
  return CredentialV2Plaintext(
    service: service.trim(),
    username: username?.trim().isNotEmpty == true
        ? username!.trim()
        : '${stem}_$suffix',
    password: suppliedPassword?.isNotEmpty == true
        ? suppliedPassword!
        : required.join(),
    url: 'https://www.$stem.com',
    notes: 'Generated locally by SVaultAI.',
  );
}

CredentialV2LookupIntent? parseCredentialV2LookupIntent(String text) {
  var normalized = text
      .trim()
      .replaceAll('\u2019', "'")
      .replaceAll(RegExp(r'[.?!,:;]+$'), '')
      .trim()
      .replaceAll(RegExp(r'\s+'), ' ');
  if (normalized.isEmpty ||
      parseCredentialV2CreateIntent(normalized) != null ||
      parseCredentialV2DeleteIntent(normalized) != null) {
    return null;
  }
  if (RegExp(
    r'^(?:(?:please\s+)?(?:show|list|open|get|find)(?:\s+me)?|what\s+are)\s+(?:my\s+)?(?:saved\s+)?(?:logins?|credentials?)$',
    caseSensitive: false,
  ).hasMatch(normalized)) {
    return const CredentialV2LookupIntent._(listAll: true);
  }

  // Preserve the service while removing only anchored conversational
  // wrappers. A credential noun or requested field is still required below,
  // so a general question such as "what is facebook" remains Brain-owned.
  normalized = normalized.replaceFirst(
    RegExp(
      r"^(?:(?:please\s+)?(?:can|could|would)\s+you\s+(?:show|find|get|open|tell)(?:\s+me)?|(?:please\s+)?(?:show|find|get|open|give|tell)(?:\s+me)?|what\s+is|what's|what\s+are|what(?=\s+(?:username|password)\b)|which|where\s+is|do\s+i\s+have)\s+",
      caseSensitive: false,
    ),
    '',
  );
  normalized = normalized
      .replaceFirst(
        RegExp(r'^(?:(?:a|an|the|my)\s+)+', caseSensitive: false),
        '',
      )
      .trim();

  CredentialV2LookupIntent? intentFor(
    String? rawService, {
    CredentialV2RequestedField field = CredentialV2RequestedField.summary,
  }) {
    final service = rawService
        ?.replaceFirst(
          RegExp(r'^(?:(?:a|an|the|my)\s+)+', caseSensitive: false),
          '',
        )
        .trim();
    if (service == null || service.isEmpty) return null;
    return CredentialV2LookupIntent._(
      listAll: false,
      service: service,
      requestedField: field,
    );
  }

  // Field-first phrasing: "what username did I save for Facebook" and
  // "the password for my Facebook login".
  var match = RegExp(
    r'^(username|password)\s+(?:did\s+i\s+(?:save|store|use)\s+for|(?:saved\s+)?for|of)\s+(.+?)(?:\s+(?:saved\s+)?(?:login|logins|credential|credentials|account)(?:\s+details?)?)?$',
    caseSensitive: false,
  ).firstMatch(normalized);
  if (match != null) {
    return intentFor(
      match.group(2),
      field: match.group(1)!.toLowerCase() == 'password'
          ? CredentialV2RequestedField.password
          : CredentialV2RequestedField.username,
    );
  }

  // Service-first field phrasing: "my Facebook username/password".
  match = RegExp(
    r'^(.+?)\s+(username|password)$',
    caseSensitive: false,
  ).firstMatch(normalized);
  if (match != null) {
    return intentFor(
      match.group(1),
      field: match.group(2)!.toLowerCase() == 'password'
          ? CredentialV2RequestedField.password
          : CredentialV2RequestedField.username,
    );
  }

  // Credential-shaped shorthand and conversational requests. The anchored
  // suffix supplies the item type; arbitrary service names remain data-driven.
  match = RegExp(
    r'^(.+?)\s+(?:saved\s+)?(?:login|logins|credential|credentials|account)(?:\s+details?)?$',
    caseSensitive: false,
  ).firstMatch(normalized);
  return intentFor(match?.group(1));
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

/// Resolve a parsed service without weakening exact identifiers. Exact labels
/// win; ordinary word-based services may then match a more-specific label
/// (for example Facebook -> Facebook Personal and Facebook Business). A
/// single one-edit typo is accepted only for an unambiguous alphabetic service.
List<DecryptedCredentialV2Record> matchCredentialV2RecordsForService(
  String service,
  Iterable<DecryptedCredentialV2Record> records,
) =>
    matchCredentialServiceCandidates(
      service,
      records,
      (record) => record.plaintext.service,
    );

List<T> matchCredentialServiceCandidates<T>(
  String service,
  Iterable<T> records,
  String Function(T record) serviceOf,
) {
  final query = _credentialLookupNormalized(service);
  if (query.isEmpty) return <T>[];
  final available = records.toList(growable: false);
  final exact = available
      .where(
          (record) => _credentialLookupNormalized(serviceOf(record)) == query)
      .toList(growable: false);
  if (exact.isNotEmpty) return exact;

  // Generated/synthetic identifiers are intentionally exact-only. This keeps
  // a deleted qa-nova-9315 request from resolving to an unrelated Nova46880.
  if (RegExp(r'[0-9]').hasMatch(query)) {
    return <T>[];
  }

  final queryTokens = query.split(' ').where((token) => token.isNotEmpty);
  final contained = available.where((record) {
    final candidate = _credentialLookupNormalized(serviceOf(record));
    final candidateTokens = candidate.split(' ').toSet();
    return queryTokens.every(candidateTokens.contains);
  }).toList(growable: false);
  if (contained.isNotEmpty) return contained;

  if (!RegExp(r'^[a-z ]+$').hasMatch(query)) {
    return <T>[];
  }
  final typoMatches = available.where((record) {
    final candidate = _credentialLookupNormalized(serviceOf(record));
    return RegExp(r'^[a-z ]+$').hasMatch(candidate) &&
        _isAtMostOneEditApart(query, candidate);
  }).toList(growable: false);
  return typoMatches.length == 1 ? typoMatches : <T>[];
}

bool _isAtMostOneEditApart(String left, String right) {
  if (left == right) return true;
  if ((left.length - right.length).abs() > 1) return false;
  if (left.length == right.length) {
    var differences = 0;
    for (var index = 0; index < left.length; index++) {
      if (left.codeUnitAt(index) != right.codeUnitAt(index) &&
          ++differences > 1) {
        return false;
      }
    }
    return true;
  }
  final shorter = left.length < right.length ? left : right;
  final longer = left.length < right.length ? right : left;
  var shortIndex = 0;
  var longIndex = 0;
  var edits = 0;
  while (shortIndex < shorter.length && longIndex < longer.length) {
    if (shorter.codeUnitAt(shortIndex) == longer.codeUnitAt(longIndex)) {
      shortIndex++;
      longIndex++;
      continue;
    }
    if (++edits > 1) return false;
    longIndex++;
  }
  return true;
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

/// Returns whether a message belongs to the local credential lookup route.
///
/// Creation requests contain credential vocabulary too, but when local v2
/// writes are disabled they must fall through to the backend draft workflow.
/// Treating them as broad lookups would consume the message after an inventory
/// read and incorrectly report that no saved login exists.
bool shouldAttemptCredentialV2Lookup(String text) {
  if (parseCredentialV2CreateIntent(text) != null) return false;
  return parseCredentialV2LookupIntent(text) != null ||
      looksLikePrivateCredentialQuery(text);
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

  Future<List<DecryptedCredentialV2Record>> naturalServiceLookup(
    String service,
  ) async {
    final exact = await exactLookup(field: 'service', value: service);
    if (exact.isNotEmpty) return exact;
    return matchCredentialV2RecordsForService(
      service,
      await listDecrypted(),
    );
  }

  Future<void> delete(String recordId) => api.delete(recordId);
}
