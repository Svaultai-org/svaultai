/// Local-only password health summary for MVK-encrypted saved items.
///
/// No password, hash, decrypted item, or result is sent to the backend.
/// The caller must pass the full server metadata inventory so missing,
/// corrupt, and still-legacy items cannot produce a partial "all clear".
library;

class ZkPasswordAnalysisIncomplete implements Exception {
  const ZkPasswordAnalysisIncomplete();

  @override
  String toString() =>
      'Some saved items still need a private format update before analysis.';
}

class ZkLocalPasswordAnalysis {
  final int analyzedCount;
  final int skippedCount;
  final int weak;
  final int moderate;
  final int strong;
  final int reusedGroups;

  const ZkLocalPasswordAnalysis({
    required this.analyzedCount,
    required this.skippedCount,
    required this.weak,
    required this.moderate,
    required this.strong,
    required this.reusedGroups,
  });

  Map<String, dynamic> toResultMap() => {
        'analyzed_count': analyzedCount,
        'skipped_count': skippedCount,
        'failed_count': 0,
        'weak': weak,
        'moderate': moderate,
        'strong': strong,
        'reused': reusedGroups,
        'has_more': false,
        'next_cursor': null,
      };
}

const _common = <String>[
  'password',
  'qwerty',
  'letmein',
  'iloveyou',
  'admin',
  'welcome',
  'monkey',
  '1234567',
  '123456',
  'abc123',
  'motdepasse',
  'motdepass',
  'contraseña',
  'contrasena',
  'senha',
  'пароль',
  '密码',
  'パスワード',
  '비밀번호',
  'كلمةالمرور',
  'كلمة المرور',
];

const _keyboardWalks = <String>[
  'qwerty',
  'asdfgh',
  'zxcvbn',
  'zxcvbnm',
  'qwertyuiop',
  'asdfghjkl',
  '1qaz',
  '2wsx',
  '3edc',
  '4rfv',
  '5tgb',
  '6yhn',
  '7ujm',
  'qaz',
  'wsx',
  'edc',
  'rfv',
  'tgb',
  'yhn',
  'ujm',
  'azerty',
  'qsdfgh',
  'wxcvbn',
  'azertyuiop',
  'qsdfghjklm',
  '1aq',
  '2zs',
  'aze',
  'qsd',
  'qwertz',
  'yxcvbn',
  'qwertzuiop',
  'yxcvbnm',
  '1qay',
  'qay',
  'aoeu',
  'htns',
  'aoeuidhtns',
  'pyfgcrl',
  'qjkxbm',
  '147',
  '258',
  '369',
  '789',
  '456',
  '1470',
  '2580',
  '159',
  '357',
  '1q2w',
  'qwer',
  'asdf',
  'sdfg',
  'zxcv',
  '13579',
  '1235789',
  'abcdef',
  'abcdefg',
  '1234',
];

int _passwordScore(String password) {
  if (password.isEmpty) return 0;
  final runes = password.runes.toList(growable: false);
  final classes = <String>{};
  final distinct = <int>{};
  for (final rune in runes) {
    distinct.add(rune);
    if (rune >= 65 && rune <= 90) {
      classes.add('upper');
    } else if (rune >= 97 && rune <= 122) {
      classes.add('lower');
    } else if (rune >= 48 && rune <= 57) {
      classes.add('digit');
    } else if (rune > 127 &&
        RegExp(r'\p{L}', unicode: true).hasMatch(String.fromCharCode(rune))) {
      classes.add('other_letter');
    } else {
      classes.add('symbol');
    }
  }
  var score = (runes.length * 2.5).floor().clamp(0, 45) +
      (classes.length * 7).clamp(0, 28) +
      distinct.length.clamp(0, 27);
  final lower = password.toLowerCase();
  if (_common.any(lower.contains)) score -= 30;
  if (_keyboardWalks.any(lower.contains)) score -= 15;
  for (var i = 0; i + 2 < runes.length; i++) {
    if (runes[i] == runes[i + 1] && runes[i] == runes[i + 2]) {
      score -= 10;
      break;
    }
  }
  if (runes.every((rune) => rune >= 48 && rune <= 57)) score -= 20;
  if (runes.length < 6) score -= 30;
  return score.clamp(0, 100);
}

int _itemId(Map<String, dynamic> item) {
  final raw = item['item_id'] ?? item['id'];
  if (raw is int && raw > 0) return raw;
  throw const ZkPasswordAnalysisIncomplete();
}

ZkLocalPasswordAnalysis analyzeZkPasswords({
  required List<Map<String, dynamic>> metadata,
  required List<Map<String, dynamic>> decryptedItems,
}) {
  final expected = <int>{};
  for (final row in metadata) {
    final id = _itemId(row);
    if (!expected.add(id) ||
        row['is_legacy'] != false ||
        row['has_v2_payload'] != true) {
      throw const ZkPasswordAnalysisIncomplete();
    }
  }
  final seen = <int>{};
  final passwordCounts = <String, int>{};
  var skipped = 0;
  var weak = 0;
  var moderate = 0;
  var strong = 0;
  for (final item in decryptedItems) {
    final id = _itemId(item);
    if (!expected.contains(id) ||
        !seen.add(id) ||
        item['storage_engine'] != 'ciphertext') {
      throw const ZkPasswordAnalysisIncomplete();
    }
    final type = item['item_type'];
    if (type is! String || type.isEmpty) {
      throw const ZkPasswordAnalysisIncomplete();
    }
    if (type != 'login' && type != 'credential' && type != 'bank') continue;
    final fields = item['fields'];
    if (fields is! Map) throw const ZkPasswordAnalysisIncomplete();
    final password = fields['password'];
    if (password == null || password == '') {
      skipped++;
      continue;
    }
    if (password is! String) throw const ZkPasswordAnalysisIncomplete();
    passwordCounts.update(password, (count) => count + 1, ifAbsent: () => 1);
    final score = _passwordScore(password);
    if (score < 45) {
      weak++;
    } else if (score < 70) {
      moderate++;
    } else {
      strong++;
    }
  }
  if (seen.length != expected.length) {
    throw const ZkPasswordAnalysisIncomplete();
  }
  return ZkLocalPasswordAnalysis(
    analyzedCount: weak + moderate + strong,
    skippedCount: skipped,
    weak: weak,
    moderate: moderate,
    strong: strong,
    reusedGroups: passwordCounts.values.where((count) => count > 1).length,
  );
}

/// Fetch only the private inventory and MVK-encrypted V2 item surface.
/// The caller checks that the same unlocked vault remains active after each
/// asynchronous step; a changed session never receives a result.
Future<ZkLocalPasswordAnalysis> loadAndAnalyzeZkPasswords({
  required Future<List<Map<String, dynamic>>> Function() fetchMetadata,
  required Future<Map<String, dynamic>> Function() fetchV2Items,
  required bool Function() stillCurrent,
}) async {
  if (!stillCurrent()) throw StateError('Vault session changed');
  final metadata = await fetchMetadata();
  if (!stillCurrent()) throw StateError('Vault session changed');
  final response = await fetchV2Items();
  if (!stillCurrent()) throw StateError('Vault session changed');
  final rawItems = response['items'];
  if (rawItems is! List) throw const ZkPasswordAnalysisIncomplete();
  final items = rawItems.map<Map<String, dynamic>>((raw) {
    if (raw is! Map<String, dynamic>) {
      throw const ZkPasswordAnalysisIncomplete();
    }
    return raw;
  }).toList(growable: false);
  final result = analyzeZkPasswords(
    metadata: metadata,
    decryptedItems: items,
  );
  if (!stillCurrent()) throw StateError('Vault session changed');
  return result;
}
