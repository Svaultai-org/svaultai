


import 'crypto_vault_chat_control.dart';


const String kVaultChatRouterSchemaV1 = 'vault_chat_router_v1';



const String kVcrIntentVaultOverview          = 'vault_overview';
const String kVcrIntentFileSearch             = 'vault_file_search';
const String kVcrIntentDocumentSummary        = 'vault_document_summary';
const String kVcrIntentSecureItemList         = 'vault_secure_item_list';
const String kVcrIntentSecureItemSearch       =
    'vault_secure_item_search';
const String kVcrIntentLoginList              = 'vault_login_list';
const String kVcrIntentLoginSearch            = 'vault_login_search';
const String kVcrIntentLoginDuplicates        = 'vault_login_duplicates';
const String kVcrIntentLoginReveal            = 'vault_login_reveal';
const String kVcrIntentLoginCopy              = 'vault_login_copy';
const String kVcrIntentGeneratedLoginList     =
    'vault_generated_login_list';
const String kVcrIntentGeneratedLoginCreateDraft =
    'vault_generated_login_create_draft';
const String kVcrIntentIdDocumentList         = 'vault_id_document_list';
const String kVcrIntentIdDocumentSearch       =
    'vault_id_document_search';
const String kVcrIntentIdDocumentExpiry       =
    'vault_id_document_expiry';
const String kVcrIntentIdDocumentReveal       =
    'vault_id_document_reveal';
const String kVcrIntentBillingStatus          = 'vault_billing_status';
const String kVcrIntentBillingUpgrade         = 'vault_billing_upgrade';
const String kVcrIntentStorageUsage           = 'vault_storage_usage';
const String kVcrIntentStorageLargest         =
    'vault_storage_largest_files';
const String kVcrIntentActivityRecent         = 'vault_activity_recent';
const String kVcrIntentActivityItemHistory    =
    'vault_activity_item_history';
const String kVcrIntentCrossVaultSearch       = 'vault_cross_vault_search';
const String kVcrIntentCryptoDelegated        = 'vault_crypto_delegated';
const String kVcrIntentFaq                    = 'vault_faq';
const String kVcrIntentRefusalSecretMaterial  =
    'vault_refusal_secret_material';
const String kVcrIntentRefusalExchangeAction  =
    'vault_refusal_exchange_action';
const String kVcrIntentRefusalBypassPin       =
    'vault_refusal_bypass_pin';
const String kVcrIntentRefusalExportAll       =
    'vault_refusal_export_all';
const String kVcrIntentRefusalMassReveal      =
    'vault_refusal_mass_reveal';
const String kVcrIntentRefusalAutoSend        =
    'vault_refusal_auto_send';
const String kVcrIntentUnrecognized           = 'vault_unrecognized';

const Set<String> kAllowedVcrIntents = {
  kVcrIntentVaultOverview,
  kVcrIntentFileSearch, kVcrIntentDocumentSummary,
  kVcrIntentSecureItemList, kVcrIntentSecureItemSearch,
  kVcrIntentLoginList, kVcrIntentLoginSearch,
  kVcrIntentLoginDuplicates, kVcrIntentLoginReveal,
  kVcrIntentLoginCopy,
  kVcrIntentGeneratedLoginList,
  kVcrIntentGeneratedLoginCreateDraft,
  kVcrIntentIdDocumentList, kVcrIntentIdDocumentSearch,
  kVcrIntentIdDocumentExpiry, kVcrIntentIdDocumentReveal,
  kVcrIntentBillingStatus, kVcrIntentBillingUpgrade,
  kVcrIntentStorageUsage, kVcrIntentStorageLargest,
  kVcrIntentActivityRecent, kVcrIntentActivityItemHistory,
  kVcrIntentCrossVaultSearch,
  kVcrIntentCryptoDelegated,
  kVcrIntentFaq,
  kVcrIntentRefusalSecretMaterial,
  kVcrIntentRefusalExchangeAction,
  kVcrIntentRefusalBypassPin,
  kVcrIntentRefusalExportAll,
  kVcrIntentRefusalMassReveal,
  kVcrIntentRefusalAutoSend,
  kVcrIntentUnrecognized,
};



const String kVcrCardVaultOverview        = 'vault_overview_card';
const String kVcrCardFileResult           = 'vault_file_result_card';
const String kVcrCardDocumentResult       = 'vault_document_result_card';
const String kVcrCardSecureItem           = 'vault_secure_item_card';
const String kVcrCardLogin                = 'vault_login_card';
const String kVcrCardGeneratedLogin       = 'vault_generated_login_card';
const String kVcrCardIdDocument           = 'vault_id_document_card';
const String kVcrCardBillingStatus        = 'vault_billing_status_card';
const String kVcrCardStorageUsage         = 'vault_storage_usage_card';
const String kVcrCardVaultActivity        = 'vault_activity_card';
const String kVcrCardCrossVaultSearch     =
    'vault_cross_vault_search_card';
const String kVcrCardConfirmationRequired =
    'vault_confirmation_required_card';
const String kVcrCardRefusal              = 'vault_refusal_card';
const String kVcrCardUnrecognized         = 'vault_unrecognized_card';
const String kVcrCardCryptoDelegated      =
    'vault_crypto_delegated_card';
const String kVcrCardFaq                  = 'vault_faq_card';

const Set<String> kAllowedVcrCards = {
  kVcrCardVaultOverview,
  kVcrCardFileResult, kVcrCardDocumentResult,
  kVcrCardSecureItem, kVcrCardLogin,
  kVcrCardGeneratedLogin, kVcrCardIdDocument,
  kVcrCardBillingStatus, kVcrCardStorageUsage,
  kVcrCardVaultActivity, kVcrCardCrossVaultSearch,
  kVcrCardConfirmationRequired,
  kVcrCardRefusal, kVcrCardUnrecognized,
  kVcrCardCryptoDelegated,
  kVcrCardFaq,
};



class VaultChatResponse {
  final String intent;
  final VaultChatCard card;

  const VaultChatResponse({required this.intent, required this.card});

  factory VaultChatResponse.fromJson(Map<String, dynamic> raw) {
    final rawIntent = (raw['intent'] ?? '').toString();
    final safeIntent = kAllowedVcrIntents.contains(rawIntent)
        ? rawIntent
        : kVcrIntentUnrecognized;
    final cardRaw = raw['card'];
    final card = cardRaw is Map<String, dynamic>
        ? VaultChatCard.fromJson(cardRaw)
        : VaultChatCard._unrecognized();
    return VaultChatResponse(intent: safeIntent, card: card);
  }


  bool get isRefusal =>
      intent == kVcrIntentRefusalSecretMaterial ||
      intent == kVcrIntentRefusalExchangeAction ||
      intent == kVcrIntentRefusalBypassPin ||
      intent == kVcrIntentRefusalExportAll ||
      intent == kVcrIntentRefusalMassReveal ||
      intent == kVcrIntentRefusalAutoSend;

  bool get requiresConfirmation =>
      card.cardType == kVcrCardConfirmationRequired;

  bool get isCryptoDelegated =>
      intent == kVcrIntentCryptoDelegated;


  CryptoVaultChatCard? get delegatedCryptoCard {
    if (!isCryptoDelegated) return null;
    final inner = card._innerCardRaw;
    if (inner == null) return null;
    return CryptoVaultChatCard.fromJson(inner);
  }
}



class VaultChatCard {
  final String cardType;
  final String? refusalReason;
  final String? message;
  final String? action;
  final String? subject;
  final String? view;
  final String? query;
  final bool maskedByDefault;
  final bool liveFetchRequired;


  final bool requiresPinUnlock;
  final bool requiresTrustedDevice;
  final bool requiresLocalSigning;
  final bool requiresExplicitConfirmation;
  final bool canSaveWithoutConfirmation;


  final String? innerIntent;
  final Map<String, dynamic>? _innerCardRaw;




  final Map<String, dynamic>? data;


  final String? faqId;
  final String? faqCategory;
  final String? faqCategoryLabel;
  final String? faqQuestion;
  final String? faqAnswer;
  final List<String> faqRelatedIds;
  final List<Map<String, String>> faqRelatedQuestions;
  final List<String> faqRelatedActions;

  const VaultChatCard({
    required this.cardType,
    this.refusalReason,
    this.message,
    this.action,
    this.subject,
    this.view,
    this.query,
    this.maskedByDefault = true,
    this.liveFetchRequired = false,

    this.requiresPinUnlock = true,
    this.requiresTrustedDevice = true,
    this.requiresLocalSigning = false,
    this.requiresExplicitConfirmation = true,
    this.canSaveWithoutConfirmation = false,
    this.innerIntent,
    Map<String, dynamic>? innerCardRaw,
    this.data,
    this.faqId,
    this.faqCategory,
    this.faqCategoryLabel,
    this.faqQuestion,
    this.faqAnswer,
    this.faqRelatedIds = const <String>[],
    this.faqRelatedQuestions = const <Map<String, String>>[],
    this.faqRelatedActions = const <String>[],
  }) : _innerCardRaw = innerCardRaw;

  factory VaultChatCard._unrecognized() {
    return const VaultChatCard(cardType: kVcrCardUnrecognized);
  }


  bool get isAvailable {
    final d = data;
    if (d == null) return false;
    if (d['available'] is bool) return d['available'] as bool;

    return true;
  }

  String? get unavailableReason {
    final d = data;
    if (d == null) return null;
    final r = d['unavailable_reason'];
    return r?.toString();
  }

  factory VaultChatCard.fromJson(Map<String, dynamic> raw) {
    final rawType = (raw['cardType'] ?? '').toString();
    final safeType = kAllowedVcrCards.contains(rawType)
        ? rawType
        : kVcrCardUnrecognized;
    final innerCard = raw['innerCard'];
    final rawData = raw['data'];


    Map<String, dynamic>? safeData;
    if (rawData is Map<String, dynamic>) {
      safeData = _stripForbiddenKeys(rawData);
    }

    final List<String> relIds = <String>[];
    final rawRelIds = raw['relatedIds'];
    if (rawRelIds is List) {
      for (final e in rawRelIds) {
        if (e is String && e.isNotEmpty) relIds.add(e);
      }
    }
    final List<Map<String, String>> relQs = <Map<String, String>>[];
    final rawRelQs = raw['relatedQuestions'];
    if (rawRelQs is List) {
      for (final e in rawRelQs) {
        if (e is Map) {
          final id = (e['id'] ?? '').toString();
          final q  = (e['question'] ?? '').toString();
          if (id.isNotEmpty && q.isNotEmpty) {
            relQs.add({'id': id, 'question': q});
          }
        }
      }
    }
    final List<String> relActs = <String>[];
    final rawRelActs = raw['relatedActions'];
    if (rawRelActs is List) {
      for (final e in rawRelActs) {
        if (e is String && e.isNotEmpty) relActs.add(e);
      }
    }

    return VaultChatCard(
      cardType:            safeType,
      refusalReason:       raw['refusalReason']?.toString(),
      message:             raw['message']?.toString(),
      action:              raw['action']?.toString(),
      subject:             raw['subject']?.toString(),
      view:                raw['view']?.toString(),
      query:               raw['query']?.toString(),
      maskedByDefault:     raw['maskedByDefault'] != false,
      liveFetchRequired:   raw['liveFetchRequired'] == true,

      requiresPinUnlock:            true,
      requiresTrustedDevice:        true,
      requiresLocalSigning: raw['requiresLocalSigning'] == true,
      requiresExplicitConfirmation: true,

      canSaveWithoutConfirmation: false,
      innerIntent:  raw['innerIntent']?.toString(),
      innerCardRaw: innerCard is Map<String, dynamic>
          ? innerCard
          : null,
      data: safeData,
      faqId:            raw['faqId']?.toString(),
      faqCategory:      raw['category']?.toString(),
      faqCategoryLabel: raw['categoryLabel']?.toString(),
      faqQuestion:      raw['question']?.toString(),
      faqAnswer:        raw['answer']?.toString(),
      faqRelatedIds:        relIds,
      faqRelatedQuestions:  relQs,
      faqRelatedActions:    relActs,
    );
  }
}



const Set<String> kVcrForbiddenDataKeys = <String>{
  'password', 'password_value', 'raw_password', 'plaintext_password',
  'pin', 'pin_hash', 'pinHash',
  'seed', 'seed_phrase', 'seedPhrase', 'seed_hex',
  'mnemonic', 'mnemonic_words',
  'private_key', 'privateKey',
  'view_key', 'private_view_key',
  'spend_key', 'private_spend_key',
  'polyseed',
  'api_key', 'apiKey',
  'auth_token', 'authToken',
  'encrypted_wallet_secret', 'encrypted_secret',
  'stripe_secret_key', 'stripe_secret',

  'id_number', 'idNumber', 'raw_id_number',
  'ssn', 'social_security_number',


  'password_field', 'notes_full', 'card_number_raw',
};


Map<String, dynamic> _stripForbiddenKeys(Map<String, dynamic> raw) {
  final out = <String, dynamic>{};
  for (final entry in raw.entries) {
    final k = entry.key;
    if (kVcrForbiddenDataKeys.contains(k)) continue;
    final v = entry.value;
    if (v is Map<String, dynamic>) {
      out[k] = _stripForbiddenKeys(v);
    } else if (v is Map) {
      out[k] = _stripForbiddenKeys(v.cast<String, dynamic>());
    } else if (v is List) {
      out[k] = _stripForbiddenKeysList(v);
    } else {
      out[k] = v;
    }
  }
  return out;
}

List<dynamic> _stripForbiddenKeysList(List<dynamic> raw) {
  return raw.map((e) {
    if (e is Map<String, dynamic>) {
      return _stripForbiddenKeys(e);
    }
    if (e is Map) {
      return _stripForbiddenKeys(e.cast<String, dynamic>());
    }
    if (e is List) return _stripForbiddenKeysList(e);
    return e;
  }).toList();
}



const String kVcrRefusalCopySecretMaterial =
    'VaultAI never surfaces your seed, mnemonic, private keys, '
    'encrypted wallet secret, auth token, or API key through '
    'chat. If you need to back up sensitive material, use the '
    'existing gated flow (Security page, unlock + confirm).';

const String kVcrRefusalCopyExchangeAction =
    'VaultAI is a non-custodial wallet. It does not buy, sell, '
    'swap, trade, stake, bridge, or exchange assets. You can '
    'receive, hold, and send from your own device.';

const String kVcrRefusalCopyBypassPin =
    'VaultAI does not bypass PIN unlock, trusted-device checks, '
    'or local signing. These gates exist so nothing moves '
    'without your explicit confirmation on your device.';

const String kVcrRefusalCopyExportAll =
    'Exporting your whole vault requires an explicit '
    'confirmation step in the Security page. VaultAI will not '
    'dump your entire vault from a chat message.';

const String kVcrRefusalCopyMassReveal =
    'VaultAI will not reveal every password or every secure '
    'item at once. Open a single item and use the reveal-with-'
    'unlock flow to see its value.';

const String kVcrRefusalCopyAutoSend =
    'VaultAI cannot auto-send crypto. Every send requires a '
    'trusted device, PIN unlock, local signing on your device, '
    'a fee preview where supported, and an explicit '
    'confirmation before broadcast.';
