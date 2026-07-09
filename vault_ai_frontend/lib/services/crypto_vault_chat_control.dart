


const String kCryptoVaultChatControlSchemaV1 =
    'crypto_vault_chat_control_v1';



const String kCvcIntentShowVault              = 'crypto_vault_show_vault';
const String kCvcIntentBalance                = 'crypto_vault_balance';
const String kCvcIntentReceiveAddress         =
    'crypto_vault_receive_address';
const String kCvcIntentReceiveQr              = 'crypto_vault_receive_qr';
const String kCvcIntentScannerStatus          =
    'crypto_vault_scanner_status';
const String kCvcIntentActivity               = 'crypto_vault_activity';
const String kCvcIntentSendDraft              = 'crypto_vault_send_draft';
const String kCvcIntentClarifyUsdtNetwork     =
    'crypto_vault_clarify_usdt_network';
const String kCvcIntentRefusalSecretMaterial  =
    'crypto_vault_refusal_secret_material';
const String kCvcIntentRefusalExchangeAction  =
    'crypto_vault_refusal_exchange_action';
const String kCvcIntentUnrecognized           =
    'crypto_vault_unrecognized';

const Set<String> kAllowedCvcIntents = {
  kCvcIntentShowVault,
  kCvcIntentBalance,
  kCvcIntentReceiveAddress,
  kCvcIntentReceiveQr,
  kCvcIntentScannerStatus,
  kCvcIntentActivity,
  kCvcIntentSendDraft,
  kCvcIntentClarifyUsdtNetwork,
  kCvcIntentRefusalSecretMaterial,
  kCvcIntentRefusalExchangeAction,
  kCvcIntentUnrecognized,
};



const String kCvcCardShowVault     = 'crypto_vault_show_vault_card';
const String kCvcCardBalance       = 'crypto_vault_balance_card';
const String kCvcCardReceive       = 'crypto_vault_receive_card';
const String kCvcCardReceiveQr     = 'crypto_vault_receive_qr_card';
const String kCvcCardScannerStatus = 'crypto_vault_scanner_status_card';
const String kCvcCardActivity      = 'crypto_vault_activity_card';
const String kCvcCardSendDraft     = 'crypto_vault_send_draft_card';
const String kCvcCardRefusal       = 'crypto_vault_refusal_card';
const String kCvcCardClarify       = 'crypto_vault_clarify_card';
const String kCvcCardUnrecognized  = 'crypto_vault_unrecognized_card';

const Set<String> kAllowedCvcCards = {
  kCvcCardShowVault,
  kCvcCardBalance,
  kCvcCardReceive,
  kCvcCardReceiveQr,
  kCvcCardScannerStatus,
  kCvcCardActivity,
  kCvcCardSendDraft,
  kCvcCardRefusal,
  kCvcCardClarify,
  kCvcCardUnrecognized,
};



const String kCvcRefusalReasonSecretMaterial =
    'secret_material_request';
const String kCvcRefusalReasonExchangeAction =
    'exchange_action_request';



class CryptoVaultChatResponse {
  final String intent;
  final CryptoVaultChatCard card;

  const CryptoVaultChatResponse({
    required this.intent,
    required this.card,
  });

  factory CryptoVaultChatResponse.fromJson(Map<String, dynamic> raw) {
    final rawIntent = (raw['intent'] ?? '').toString();
    final safeIntent = kAllowedCvcIntents.contains(rawIntent)
        ? rawIntent
        : kCvcIntentUnrecognized;
    final cardRaw = raw['card'];
    final card = cardRaw is Map<String, dynamic>
        ? CryptoVaultChatCard.fromJson(cardRaw)
        : CryptoVaultChatCard._unrecognized();
    return CryptoVaultChatResponse(intent: safeIntent, card: card);
  }

  bool get isRefusal =>
      intent == kCvcIntentRefusalSecretMaterial ||
      intent == kCvcIntentRefusalExchangeAction;

  bool get isClarifyUsdt =>
      intent == kCvcIntentClarifyUsdtNetwork;

  bool get isSendDraft => intent == kCvcIntentSendDraft;
}



class CryptoVaultChatCard {
  final String cardType;
  final String? asset;
  final String? amount;
  final String? recipient;
  final String? refusalReason;
  final String? message;
  final List<String>? options;
  final bool liveFetchRequired;


  final bool canBroadcast;
  final bool requiresPinUnlock;
  final bool requiresTrustedDevice;
  final bool requiresLocalSigning;
  final bool requiresExplicitConfirmation;




  final Map<String, dynamic>? data;

  const CryptoVaultChatCard({
    required this.cardType,
    this.asset,
    this.amount,
    this.recipient,
    this.refusalReason,
    this.message,
    this.options,
    this.liveFetchRequired = false,
    this.canBroadcast = false,
    this.requiresPinUnlock = true,
    this.requiresTrustedDevice = true,
    this.requiresLocalSigning = true,
    this.requiresExplicitConfirmation = true,
    this.data,
  });

  factory CryptoVaultChatCard._unrecognized() {
    return const CryptoVaultChatCard(
      cardType: kCvcCardUnrecognized,
    );
  }

  factory CryptoVaultChatCard.fromJson(Map<String, dynamic> raw) {
    final rawType = (raw['cardType'] ?? '').toString();
    final safeType = kAllowedCvcCards.contains(rawType)
        ? rawType
        : kCvcCardUnrecognized;
    final rawOptions = raw['options'];
    final safeOptions = rawOptions is List
        ? rawOptions.map((e) => e.toString()).toList()
        : null;
    final rawData = raw['data'];
    Map<String, dynamic>? safeData;
    if (rawData is Map<String, dynamic>) {
      safeData = _stripForbiddenCryptoKeys(rawData);
    } else if (rawData is Map) {
      safeData = _stripForbiddenCryptoKeys(
        rawData.cast<String, dynamic>(),
      );
    }
    return CryptoVaultChatCard(
      cardType:            safeType,
      asset:               raw['asset']?.toString(),
      amount:              raw['amount']?.toString(),
      recipient:           raw['recipient']?.toString(),
      refusalReason:       raw['refusalReason']?.toString(),
      message:             raw['message']?.toString(),
      options:             safeOptions,
      liveFetchRequired:   raw['liveFetchRequired'] == true,



      canBroadcast:                 false,
      requiresPinUnlock:            true,
      requiresTrustedDevice:        true,
      requiresLocalSigning:         true,
      requiresExplicitConfirmation: true,
      data:                         safeData,
    );
  }
}



const Set<String> kCvcForbiddenDataKeys = <String>{
  'privateKey', 'private_key',
  'privateViewKey', 'private_view_key',
  'privateSpendKey', 'private_spend_key',
  'seed', 'seed_phrase', 'seedPhrase',
  'mnemonic', 'mnemonic_words',
  'polyseed',
  'encryptedWalletSecret', 'encrypted_wallet_secret',
  'encryptedSecret', 'encrypted_secret',
  'authToken', 'auth_token', 'apiKey', 'api_key',
  'stripeSecretKey', 'stripe_secret_key',
  'pin', 'pinHash', 'pin_hash',
  'signedTxHex', 'signed_tx_hex', 'signedRawTransaction',
  'spendKey', 'viewKey',
};


Map<String, dynamic> _stripForbiddenCryptoKeys(
  Map<String, dynamic> raw,
) {
  final out = <String, dynamic>{};
  for (final entry in raw.entries) {
    final k = entry.key;
    if (kCvcForbiddenDataKeys.contains(k)) continue;
    final v = entry.value;
    if (v is Map<String, dynamic>) {
      out[k] = _stripForbiddenCryptoKeys(v);
    } else if (v is Map) {
      out[k] = _stripForbiddenCryptoKeys(
        v.cast<String, dynamic>(),
      );
    } else if (v is List) {
      out[k] = _stripForbiddenCryptoKeysList(v);
    } else {
      out[k] = v;
    }
  }
  return out;
}


List<dynamic> _stripForbiddenCryptoKeysList(List<dynamic> raw) {
  return raw.map((e) {
    if (e is Map<String, dynamic>) {
      return _stripForbiddenCryptoKeys(e);
    }
    if (e is Map) {
      return _stripForbiddenCryptoKeys(e.cast<String, dynamic>());
    }
    if (e is List) return _stripForbiddenCryptoKeysList(e);
    return e;
  }).toList();
}


const String kCvcRefusalCopySecretMaterial =
    'VaultAI never surfaces your seed, mnemonic, private spend key, '
    'private view key, or encrypted wallet secret through chat. If '
    'you need to back up, use the Security page in the Crypto Vault.';

const String kCvcRefusalCopyExchangeAction =
    'VaultAI is a non-custodial wallet. It does not buy, sell, swap, '
    'trade, stake, bridge, or exchange assets. You can receive, '
    'hold, and send from your own device.';

const String kCvcClarifyUsdtCopy =
    'USDT can mean USDT ERC20 (on Ethereum) or USDT TRC20 (on TRON). '
    'Which one do you mean?';

const String kCvcUnrecognizedCopy =
    'That question is not something Crypto Vault chat can answer '
    'yet. Try asking for a balance, a receive address, the Monero '
    'scanner status, or to prepare a send.';
