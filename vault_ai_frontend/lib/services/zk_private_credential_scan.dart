/// Bounded credential-file discovery over an ephemeral, locally decrypted
/// private index. This does not perform OCR, transcription, or AI inference.
library;

import 'zk_private_chat.dart';
import 'zk_private_chat_index.dart';

class ZkPrivateCredentialScanResult {
  final List<ZkLocalChatRecord> matches;
  final int readyFilesChecked;
  final int textFilesChecked;
  final int listedFiles;
  final bool incomplete;

  const ZkPrivateCredentialScanResult({
    required this.matches,
    required this.readyFilesChecked,
    required this.textFilesChecked,
    required this.listedFiles,
    required this.incomplete,
  });

  String get summary {
    final found = matches.length;
    final result = found == 0
        ? 'I did not find likely credential-related files.'
        : 'I found $found possible credential-related '
            '${found == 1 ? 'file' : 'files'}.';
    final coverage = 'I checked saved names for $readyFilesChecked ready '
        'private ${readyFilesChecked == 1 ? 'file' : 'files'} and locally '
        'searchable text for $textFilesChecked.';
    final omitted = listedFiles - readyFilesChecked;
    final omittedMessage = omitted > 0
        ? ' $omitted other listed ${omitted == 1 ? 'file was' : 'files were'} '
            'not checked.'
        : '';
    final partial = incomplete || textFilesChecked < readyFilesChecked;
    return '$result $coverage$omittedMessage'
        '${partial ? ' This is a partial scan.' : ''} '
        'I did not run new OCR, audio transcription, video analysis, or AI '
        'inference. Previously saved searchable text, when available, was '
        'checked locally. No file contents or credentials were sent to AI.';
  }
}

class ZkPrivateCredentialScan {
  static final RegExp _scanAction = RegExp(
    r'\b(scan|check|search)\b',
    caseSensitive: false,
  );
  static final RegExp _privateScope = RegExp(
    r'\b(my|vault|saved|stored)\b',
    caseSensitive: false,
  );
  static final RegExp _credentialTarget = RegExp(
    r'\b(credentials?|passwords?|logins?|recovery codes?)\b',
    caseSensitive: false,
  );
  static final RegExp _fileScope = RegExp(
    r'\b(files?|documents?)\b',
    caseSensitive: false,
  );

  static bool isExplicitRequest(String text) =>
      _scanAction.hasMatch(text) &&
      _privateScope.hasMatch(text) &&
      _credentialTarget.hasMatch(text) &&
      (_fileScope.hasMatch(text) ||
          RegExp(r'\bvault\b', caseSensitive: false).hasMatch(text));

  static bool shouldRouteLocally(
    String text, {
    required bool privateChatEnabled,
    required bool signedPrivateChatOffer,
  }) =>
      (privateChatEnabled || signedPrivateChatOffer) && isExplicitRequest(text);

  // Filenames are normalized first so underscores and dashes are word breaks.
  static final RegExp _nameCue = RegExp(
    r'\b(passwords?|passcodes?|credentials?|logins?|recovery|backup codes?|'
    r'2fa|totp|authenticator|api keys?|private keys?|secret keys?|'
    r'seed phrases?)\b',
    caseSensitive: false,
  );
  static final RegExp _contentCue = RegExp(
    r'\b(password|passcode|recovery codes?|backup codes?|2fa|totp|'
    r'authenticator|api key|private key|secret key|seed phrase)\b',
    caseSensitive: false,
  );

  static ZkPrivateCredentialScanResult scan(ZkPrivateChatIndex index) {
    final scored = <(ZkLocalChatRecord, int)>[];
    for (final file in index.files) {
      if (file.kind != ZkLocalChatKind.file) continue;
      final name = file.title.replaceAll(RegExp(r'[_\-.]+'), ' ');
      final nameHit = _nameCue.hasMatch(name);
      final contentHit = _contentCue.hasMatch(file.searchText);
      if (nameHit || contentHit) {
        scored.add((file, (nameHit ? 2 : 0) + (contentHit ? 1 : 0)));
      }
    }
    scored.sort((a, b) {
      final score = b.$2.compareTo(a.$2);
      if (score != 0) return score;
      return a.$1.title.compareTo(b.$1.title);
    });
    final listed = index.totalListedFiles > index.files.length
        ? index.totalListedFiles
        : index.files.length;
    return ZkPrivateCredentialScanResult(
      matches: scored.map((entry) => entry.$1).toList(growable: false),
      readyFilesChecked: index.files.length,
      textFilesChecked: index.contentIndexedFiles,
      listedFiles: listed,
      incomplete: index.incomplete,
    );
  }
}
