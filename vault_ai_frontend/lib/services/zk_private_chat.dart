/// PIN-free chat routing for locally unlocked ZK vaults.
///
/// Locally decrypted titles, annotations and bounded text content may be
/// searched in memory. Decrypted vault content, vault keys and PINs are never
/// copied into the general AI request body.
/// The caller must pass a `general` result to the general-chat API and render
/// local results in the vault UI without a network request.
library;

enum ZkLocalChatKind { savedItem, file }

enum ZkLocalMediaKind { photo, video, audio, document, other }

enum ZkLocalChatDisposition {
  general,
  found,
  ambiguous,
  related,
  notFound,
  needsPrivateIndex,
  unsupportedAction,
}

class ZkLocalChatRecord {
  final ZkLocalChatKind kind;
  final String id;
  final String title;
  final String searchText;
  final String? mimeType;
  final ZkLocalMediaKind mediaKind;

  const ZkLocalChatRecord({
    required this.kind,
    required this.id,
    required this.title,
    this.searchText = '',
    this.mimeType,
    this.mediaKind = ZkLocalMediaKind.other,
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
    r'\b(file|document|photo|picture|image|video|clip|recording|audio|voice|login|password|credential|code)\b',
    caseSensitive: false,
  );
  static final RegExp _mediaCue = RegExp(
    r'\b(photo|picture|image|video|clip|recording|audio|voice)\b',
    caseSensitive: false,
  );
  static final RegExp _photoCue = RegExp(
    r'\b(photo|picture|image|screenshot)\b',
    caseSensitive: false,
  );
  static final RegExp _videoCue = RegExp(
    r'\b(video|clip|movie)\b',
    caseSensitive: false,
  );
  static final RegExp _audioCue = RegExp(
    r'\b(audio|voice|recording|sound)\b',
    caseSensitive: false,
  );
  static final RegExp _mutationCue = RegExp(
    r'\b(save|remember|store|upload|delete|remove|rename|change|edit|share)\b',
    caseSensitive: false,
  );
  static final RegExp _followUp = RegExp(
    r'^(?:please\s+)?(?:show|open|view|play|display|where\s+is)\s+(?:me\s+)?(?:it|that|this|the\s+one)\??$',
    caseSensitive: false,
  );
  static final RegExp _contextReference = RegExp(
    r'\b(it|its|that|this|these|those|one|ones|same)\b',
    caseSensitive: false,
  );
  static final RegExp _relatedCue = RegExp(
    r'\b(related|similar)\s+(?:files?|photos?|pictures?|documents?|ones?)\b|\bmore\s+like\s+(?:this|that|it)\b',
    caseSensitive: false,
  );
  static final RegExp _ordinalFollowUp = RegExp(
    r'\b(first|second|third|fourth|fifth|last)\s+(?:one|file|photo|picture|document|result)\b',
    caseSensitive: false,
  );

  /// A reference after a private turn stays in the local vault flow. Its
  /// meaning may depend on the prior private result, even without "my vault".
  static bool referencesPreviousPrivateResult(String prompt) =>
      _contextReference.hasMatch(prompt) ||
      _relatedCue.hasMatch(prompt) ||
      _ordinalFollowUp.hasMatch(prompt);
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
    'picture',
    'photo',
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
    'voice',
    'audio',
    'clip',
    'what',
    'where',
    'with',
  };

  static String _normalizeTerm(String term) {
    if (term.endsWith('ies') && term.length > 4) {
      return '${term.substring(0, term.length - 3)}y';
    }
    if (term.endsWith('s') && !term.endsWith('ss') && term.length > 3) {
      return term.substring(0, term.length - 1);
    }
    return term;
  }

  static Set<String> _terms(String text) => _word
      .allMatches(text.toLowerCase())
      .map((match) => _normalizeTerm(match.group(0)!))
      .where((term) => term.length > 1 && !_stop.contains(term))
      .toSet();

  static ZkLocalMediaKind? _requestedMedia(String query) {
    if (_videoCue.hasMatch(query)) return ZkLocalMediaKind.video;
    if (_photoCue.hasMatch(query)) return ZkLocalMediaKind.photo;
    if (_audioCue.hasMatch(query)) return ZkLocalMediaKind.audio;
    return null;
  }

  static ZkLocalChatResult resolve({
    required String prompt,
    required List<ZkLocalChatRecord> savedItems,
    required List<ZkLocalChatRecord> files,
    ZkLocalChatRecord? previousSelection,
    List<ZkLocalChatRecord> previousMatches = const [],
    bool forcePrivate = false,
  }) {
    final query = prompt.trim();
    final records = [...savedItems, ...files];
    final ordinal = _ordinalFollowUp.firstMatch(query);
    if (ordinal != null) {
      final candidates = previousMatches
          .where(
            (candidate) => records.any(
              (record) =>
                  record.kind == candidate.kind && record.id == candidate.id,
            ),
          )
          .toList();
      final word = ordinal.group(1)!.toLowerCase();
      final at = word == 'last'
          ? candidates.length - 1
          : const {
              'first': 0,
              'second': 1,
              'third': 2,
              'fourth': 3,
              'fifth': 4,
            }[word]!;
      if (at < 0 || at >= candidates.length) {
        return const ZkLocalChatResult(ZkLocalChatDisposition.notFound);
      }
      return ZkLocalChatResult(
        ZkLocalChatDisposition.found,
        matches: [candidates[at]],
        selection: candidates[at],
      );
    }
    if (_relatedCue.hasMatch(query)) {
      final previous = previousSelection;
      if (previous == null ||
          previous.kind != ZkLocalChatKind.file ||
          !files.any((file) => file.id == previous.id)) {
        return const ZkLocalChatResult(ZkLocalChatDisposition.notFound);
      }
      return ZkLocalChatResult(
        ZkLocalChatDisposition.related,
        matches: ZkLocalFileRelations.related(previous, files),
        selection: previous,
      );
    }
    if (_followUp.hasMatch(query)) {
      final previous = previousSelection;
      if (previous == null ||
          !records.any(
            (record) =>
                record.kind == previous.kind && record.id == previous.id,
          )) {
        return const ZkLocalChatResult(ZkLocalChatDisposition.notFound);
      }
      return ZkLocalChatResult(
        ZkLocalChatDisposition.found,
        matches: [previous],
        selection: previous,
      );
    }
    final hasMy = _myCue.hasMatch(query);
    final hasAsset = _assetCue.hasMatch(query);
    final hasLookup = _lookupCue.hasMatch(query);
    final isHowTo = query.toLowerCase().startsWith('how ');
    if (_mutationCue.hasMatch(query) && !isHowTo) {
      return const ZkLocalChatResult(ZkLocalChatDisposition.unsupportedAction);
    }
    final isPrivate =
        forcePrivate ||
        _privateCue.hasMatch(query) ||
        (hasLookup && (hasMy || hasAsset)) ||
        (hasMy && !isHowTo);
    if (!isPrivate) {
      return const ZkLocalChatResult(ZkLocalChatDisposition.general);
    }

    final queryTerms = _terms(query);
    final mediaKind = _requestedMedia(query);
    final scored = <(ZkLocalChatRecord, int)>[];
    for (final record in [...savedItems, ...files]) {
      if (mediaKind != null && record.mediaKind != mediaKind) continue;
      final titleScore = _terms(record.title).intersection(queryTerms).length;
      final contentScore = _terms(
        record.searchText,
      ).intersection(queryTerms).length;
      final score = titleScore * 4 + contentScore * 2;
      if (score > 0 || (queryTerms.isEmpty && mediaKind != null)) {
        scored.add((record, score));
      }
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

/// Conservative local title matches. These are not semantic relationships or
/// media-content matches; callers must describe them as similar saved names.
class ZkLocalFileRelations {
  static final RegExp _words = RegExp(r'[a-z0-9]{4,}');
  static const _ignored = <String>{
    'file',
    'photo',
    'image',
    'video',
    'audio',
    'document',
    'copy',
    'final',
    'jpeg',
    'webp',
    'heic',
    'm4a',
    'mp4',
  };

  static Set<String> _titleTerms(String title) => _words
      .allMatches(title.toLowerCase())
      .map((match) => match.group(0)!)
      .where((word) => !_ignored.contains(word))
      .toSet();

  static List<ZkLocalChatRecord> related(
    ZkLocalChatRecord anchor,
    List<ZkLocalChatRecord> files,
  ) {
    if (anchor.kind != ZkLocalChatKind.file) return const [];
    final anchorTerms = _titleTerms(anchor.title);
    if (anchorTerms.isEmpty) return const [];
    final scored = <(ZkLocalChatRecord, int)>[];
    for (final file in files) {
      if (file.id == anchor.id || file.kind != ZkLocalChatKind.file) continue;
      final count = anchorTerms.intersection(_titleTerms(file.title)).length;
      if (count > 0) scored.add((file, count));
    }
    scored.sort((a, b) {
      final byScore = b.$2.compareTo(a.$2);
      return byScore != 0 ? byScore : a.$1.title.compareTo(b.$1.title);
    });
    return scored.take(6).map((entry) => entry.$1).toList();
  }

  static Map<String, dynamic> envelope({
    required ZkLocalChatRecord anchor,
    required List<ZkLocalChatRecord> matches,
    required bool incomplete,
  }) {
    if (anchor.kind != ZkLocalChatKind.file) {
      throw ArgumentError('Related-file anchor must be a file');
    }
    return <String, dynamic>{
      'anchor': <String, dynamic>{
        'file_id': anchor.id,
        'file_name': anchor.title,
        'mime_type': anchor.mimeType ?? '',
      },
      'relationships': <Map<String, dynamic>>[
        for (final file in matches)
          <String, dynamic>{
            'file': <String, dynamic>{
              'file_id': file.id,
              'file_name': file.title,
              'mime_type': file.mimeType ?? '',
              'zk_private_chat_v2': true,
            },
            'relationship_type': 'similar_saved_name',
            'confidence_label': 'weak',
            'reasons': <String>['Similar saved name'],
          },
      ],
      'message': matches.isEmpty
          ? 'No files with similar saved names were found locally.'
          : 'These files have similar saved names. Their contents were not compared.',
      'is_complete': !incomplete,
    };
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
