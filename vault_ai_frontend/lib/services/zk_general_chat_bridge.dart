/// A narrow PIN-free path for clearly general questions in an older ZK vault.
/// Vault-content and ambiguous follow-up requests stay on local private chat.
library;

import 'zk_private_chat.dart';

typedef SendGeneralTurn = Future<String> Function(
  String prompt,
  List<ZkGeneralChatTurn> history,
);

enum ZkGeneralBridgeRoute { legacy, unavailable, general, privateLocal }

/// The full private bridge keeps an OPAQUE session off legacy chat. The
/// general-only rollout uses legacy chat for private/ambiguous turns until
/// local readers cover them; only clearly general turns change transport.
ZkGeneralBridgeRoute resolveZkGeneralBridgeRoute({
  required bool enabled,
  required bool hasZkHandle,
  required bool hasMvk,
  required bool mvkMatchesVault,
  required bool hasAttachments,
  required String prompt,
  String? vaultName,
  bool preserveLegacyPrivateChat = false,
}) {
  // A general-only rollout changes only clearly general turns. A session
  // without its current OPAQUE key and every private/ambiguous turn continue
  // through the already supported chat path, including attachments.
  if (preserveLegacyPrivateChat &&
      (!hasZkHandle || !hasMvk || !mvkMatchesVault)) {
    return ZkGeneralBridgeRoute.legacy;
  }
  if (!enabled || (!hasZkHandle && !hasMvk)) {
    return ZkGeneralBridgeRoute.legacy;
  }
  if (!hasMvk || !mvkMatchesVault) {
    return ZkGeneralBridgeRoute.unavailable;
  }
  if (!hasAttachments &&
      isClearlyGeneralChatPrompt(prompt, vaultName: vaultName)) {
    return ZkGeneralBridgeRoute.general;
  }
  return preserveLegacyPrivateChat
      ? ZkGeneralBridgeRoute.legacy
      : ZkGeneralBridgeRoute.privateLocal;
}

/// Classification is intentionally stricter than the full private-chat
/// router. A prompt that could refer to the vault or another conversation
/// never enters the general AI request under this transitional feature.
bool isClearlyGeneralChatPrompt(String prompt, {String? vaultName}) {
  final text = prompt.trim();
  if (text.isEmpty || text.length > 4000) return false;
  final privateLabel = vaultName?.trim().toLowerCase();
  if (privateLabel != null &&
      privateLabel.isNotEmpty &&
      text.toLowerCase().contains(privateLabel)) {
    return false;
  }
  if (!RegExp(
    r'^(?:what (?:is|are|does|do)\b|how (?:does|do|is|are)\b|'
    r'why (?:does|do|is|are)\b|explain\b|define\b|'
    r'tell me about\b|(?:could|can) you explain\b)',
    caseSensitive: false,
  ).hasMatch(text)) {
    return false;
  }
  if (RegExp(
    r'\b(?:i|me|my|mine|we|us|our|ours|your|yours|it|that|this|'
    r'these|those|there|here|above|earlier|previous|last|recent|'
    r'first|second|third|fourth|fifth|next|other|another|same|one|ones|'
    r'vault|saved|stored|uploaded|attached|file|document|photo|picture|'
    r'image|video|clip|recording|audio|voice|login|password|pin|passphrase|'
    r'credential|account|secret|code|key|token|wallet|asset|bank|card|'
    r'receipt|passport|address|phone|email|birthday|birth|identity|'
    r'contact|number|date|location|person|people|someone|who|where|which|'
    r'github|recovery)\b|@|https?://|\b\d{4,}\b',
    caseSensitive: false,
  ).hasMatch(text)) {
    return false;
  }
  if (RegExp(r"\b[A-Za-z][A-Za-z'-]*['’]s\b").hasMatch(text)) {
    return false;
  }
  return ZkLocalChatRouter.resolve(
    prompt: text,
    savedItems: const [],
    files: const [],
  ).maySendToGeneralAi;
}

/// Keeps only bounded, successful general turns for one unlocked session.
/// Errors never fall through to a PIN-bearing chat route.
class ZkGeneralChatBridge {
  final SendGeneralTurn sendGeneral;
  final bool Function() accessIsCurrent;
  final String? vaultName;
  final List<ZkGeneralChatTurn> _history = [];

  ZkGeneralChatBridge({
    required this.sendGeneral,
    required this.accessIsCurrent,
    this.vaultName,
  });

  void clear() => _history.clear();

  Future<String> send(String prompt) async {
    if (!isClearlyGeneralChatPrompt(prompt, vaultName: vaultName)) {
      throw StateError('Question needs the private vault chat route');
    }
    if (!accessIsCurrent()) throw StateError('Vault session changed');
    final reply = await sendGeneral(
      prompt,
      List<ZkGeneralChatTurn>.unmodifiable(_history),
    );
    if (!accessIsCurrent()) throw StateError('Vault session changed');
    if (reply.trim().isEmpty) throw const FormatException('Empty chat reply');
    _history.add(ZkGeneralChatTurn(role: 'user', content: prompt));
    _history.add(ZkGeneralChatTurn(role: 'assistant', content: reply));
    while (_history.length > 8) {
      _history.removeRange(0, 2);
    }
    return reply;
  }
}
