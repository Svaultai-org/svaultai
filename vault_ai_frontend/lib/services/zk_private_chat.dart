/// PIN-free chat routing for locally unlocked ZK vaults.
///
/// Only display titles are searched here. Decrypted secrets, file bytes,
/// vault keys and PINs are never copied into the general AI request body.
/// The caller must pass a `general` result to the general-chat API and render
/// local results in the vault UI without a network request.
library;

enum ZkLocalChatKind { savedItem, file }

enum ZkLocalChatDisposition {
  general,
  found,
  ambiguous,
  notFound,
  needsPrivateIndex,
}

class ZkLocalChatRecord {
  final ZkLocalChatKind kind;
  final String id;
  final String title;

  const ZkLocalChatRecord({
    required this.kind,
    required this.id,
    required this.title,
  });
}

class ZkLocalChatResult {
  final ZkLocalChatDisposition disposition;
  final List<ZkLocalChatRecord> matches;
  final ZkLocalChatRecord? selection;

  const ZkLocalChatResult(
    this.disposition, {
    this.matches = const [],
    this.selection,
  });

  bool get maySendToGeneralAi => disposition == ZkLocalChatDisposition.general;
}

class ZkChatDispatchResult {
  final ZkLocalChatResult local;
  final String? generalReply;

  const ZkChatDispatchResult({required this.local, this.generalReply});
}

class ZkLocalChatRouter {
  static final RegExp _word = RegExp(r'[a-z0-9]+');
  static final RegExp _privateCue = RegExp(
    r'\b(vault|saved|stored|uploaded)\b',
    caseSensitive: false,
  );
  static final RegExp _myCue = RegExp(r'\b(my|mine)\b', caseSensitive: false);
  static final RegExp _lookupCue = RegExp(
    r'\b(find|show|open|locate|retrieve|search|where)\b',
    caseSensitive: false,
  );
  static final RegExp _assetCue = RegExp(
    r'\b(file|document|photo|image|video|recording|audio|login|password|credential|code)\b',
    caseSensitive: false,
  );
  static final RegExp _mediaCue = RegExp(
    r'\b(photo|image|video|recording|audio)\b',
    caseSensitive: false,
  );
  static final RegExp _followUp = RegExp(
    r'^(?:please\s+)?(?:show|open|view|play|display|where\s+is)\s+(?:me\s+)?(?:it|that|this|the\s+one)\??$',
    caseSensitive: false,
  );
  static const Set<String> _stop = {
    'a',
    'an',
    'and',
    'at',
    'by',
    'file',
    'find',
    'for',
    'from',
    'i',
    'image',
    'in',
    'is',
    'it',
    'locate',
    'login',
    'me',
    'my',
    'of',
    'on',
    'open',
    'or',
    'please',
    'recording',
    'retrieve',
    'search',
    'show',
    'the',
    'this',
    'to',
    'vault',
    'video',
    'what',
    'where',
    'with',
  };

  static Set<String> _terms(String text) => _word
      .allMatches(text.toLowerCase())
      .map((match) => match.group(0)!)
      .where((term) => term.length > 1 && !_stop.contains(term))
      .toSet();

  static ZkLocalChatResult resolve({
    required String prompt,
    required List<ZkLocalChatRecord> savedItems,
    required List<ZkLocalChatRecord> files,
    ZkLocalChatRecord? previousSelection,
  }) {
    final query = prompt.trim();
    if (_followUp.hasMatch(query)) {
      if (previousSelection == null) {
        return const ZkLocalChatResult(ZkLocalChatDisposition.notFound);
      }
      return ZkLocalChatResult(
        ZkLocalChatDisposition.found,
        matches: [previousSelection],
        selection: previousSelection,
      );
    }
    final hasMy = _myCue.hasMatch(query);
    final hasAsset = _assetCue.hasMatch(query);
    final hasLookup = _lookupCue.hasMatch(query);
    final isHowTo = query.toLowerCase().startsWith('how ');
    final isPrivate = _privateCue.hasMatch(query) ||
        (hasLookup && (hasMy || hasAsset)) ||
        (hasMy && hasAsset && !isHowTo);
    if (!isPrivate) {
      return const ZkLocalChatResult(ZkLocalChatDisposition.general);
    }

    final queryTerms = _terms(query);
    final scored = <(ZkLocalChatRecord, int)>[];
    for (final record in [...savedItems, ...files]) {
      final score = _terms(record.title).intersection(queryTerms).length;
      if (score > 0) scored.add((record, score));
    }
    scored.sort((a, b) => b.$2.compareTo(a.$2));
    if (scored.isEmpty) {
      return ZkLocalChatResult(
        _mediaCue.hasMatch(query)
            ? ZkLocalChatDisposition.needsPrivateIndex
            : ZkLocalChatDisposition.notFound,
      );
    }
    final topScore = scored.first.$2;
    final top = scored
        .where((entry) => entry.$2 == topScore)
        .map((entry) => entry.$1)
        .toList(growable: false);
    if (top.length > 1) {
      return ZkLocalChatResult(ZkLocalChatDisposition.ambiguous, matches: top);
    }
    return ZkLocalChatResult(
      ZkLocalChatDisposition.found,
      matches: top,
      selection: top.single,
    );
  }

  /// A private lookup never invokes [sendGeneral]. The caller renders the
  /// local record id with its own vault UI; only general turns use the API.
  static Future<ZkChatDispatchResult> dispatch({
    required String prompt,
    required List<ZkLocalChatRecord> savedItems,
    required List<ZkLocalChatRecord> files,
    required Future<String> Function(String) sendGeneral,
    ZkLocalChatRecord? previousSelection,
  }) async {
    final local = resolve(
      prompt: prompt,
      savedItems: savedItems,
      files: files,
      previousSelection: previousSelection,
    );
    if (!local.maySendToGeneralAi) {
      return ZkChatDispatchResult(local: local);
    }
    final reply = await sendGeneral(prompt);
    return ZkChatDispatchResult(local: local, generalReply: reply);
  }
}

class ZkGeneralChatTurn {
  final String role;
  final String content;

  const ZkGeneralChatTurn({required this.role, required this.content});
}

Map<String, dynamic> buildZkGeneralChatBody({
  required String message,
  List<ZkGeneralChatTurn> history = const [],
}) {
  if (message.trim().isEmpty || message.length > 4000 || history.length > 12) {
    throw ArgumentError('General chat message or history exceeds its limit');
  }
  return <String, dynamic>{
    'message': message,
    'history': [
      for (final turn in history)
        if ((turn.role == 'user' || turn.role == 'assistant') &&
            turn.content.trim().isNotEmpty &&
            turn.content.length <= 4000)
          <String, String>{'role': turn.role, 'content': turn.content}
        else
          throw ArgumentError('Invalid general chat history turn'),
    ],
  };
}
