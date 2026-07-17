// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for French (`fr`).
class AppLocalizationsFr extends AppLocalizations {
  AppLocalizationsFr([String locale = 'fr']) : super(locale);

  @override
  String get appTitle => 'VaultAI';

  @override
  String get commonRetry => 'Réessayer';

  @override
  String get commonRefresh => 'Actualiser';

  @override
  String get commonOpen => 'Ouvrir';

  @override
  String get commonCancel => 'Annuler';

  @override
  String get commonSave => 'Enregistrer';

  @override
  String get commonSignOut => 'Se déconnecter';

  @override
  String get commonLoading => 'Chargement...';

  @override
  String get commonAll => 'Tout';

  @override
  String get commonView => 'Voir';

  @override
  String get commonDownload => 'Télécharger';

  @override
  String get commonAskVaultAI => 'Demander à VaultAI';

  @override
  String get commonClose => 'Fermer';

  @override
  String get commonDelete => 'Supprimer';

  @override
  String get commonConfirm => 'Confirmer';

  @override
  String get commonSignIn => 'Se connecter';

  @override
  String get commonSignUp => 'S\'inscrire';

  @override
  String get commonSearch => 'Rechercher';

  @override
  String get commonBack => 'Retour';

  @override
  String get commonNext => 'Suivant';

  @override
  String get commonYes => 'Oui';

  @override
  String get commonNo => 'Non';

  @override
  String get commonError => 'Erreur';

  @override
  String get commonSuccess => 'Succès';

  @override
  String get commonUnavailable => 'Indisponible';

  @override
  String get commonTryAgain => 'Réessayer';

  @override
  String get commonContinue => 'Continuer';

  @override
  String get commonApprove => 'Approuver';

  @override
  String get commonReject => 'Rejeter';

  @override
  String get commonRevoke => 'Révoquer';

  @override
  String get commonReceive => 'Recevoir';

  @override
  String get commonReview => 'Vérifier';

  @override
  String get commonAnalyze => 'Analyser';

  @override
  String get commonCopy => 'Copier';

  @override
  String get commonEdit => 'Modifier';

  @override
  String get commonCurrent => 'Actuel';

  @override
  String get commonCopyCode => 'Copier le code';

  @override
  String get commonRemove => 'Retirer';

  @override
  String get commonNotYet => 'Pas encore';

  @override
  String get sidebarDashboard => 'Tableau de bord';

  @override
  String get sidebarChat => 'Chat';

  @override
  String get sidebarFiles => 'Fichiers';

  @override
  String get sidebarLogins => 'Identifiants';

  @override
  String get sidebarCryptoVault => 'Crypto Vault';

  @override
  String get sidebarConcierge => 'Concierge';

  @override
  String get sidebarExpiry => 'Expirations';

  @override
  String get sidebarMemory => 'Mémoire';

  @override
  String get sidebarRelationships => 'Relations';

  @override
  String get sidebarInheritance => 'Héritage';

  @override
  String get sidebarSettings => 'Paramètres';

  @override
  String get chatComposerHint =>
      'Posez une question sur votre coffre ou téléversez un fichier...';

  @override
  String get chatThinking => 'VaultAI réfléchit...';

  @override
  String chatThinkingWithName(String name) {
    return '$name réfléchit...';
  }

  @override
  String get chatSendButton => 'Envoyer';

  @override
  String get chatSending => 'Envoi...';

  @override
  String chatAskAbout(String topic) {
    return 'Parle-moi davantage de mon $topic';
  }

  @override
  String get chatErrorGeneric =>
      'VaultAI n\'a pas pu répondre à cela. Réessayez.';

  @override
  String get chatRetryButton => 'Réessayer';

  @override
  String get chatQuickSavedLogins => 'Identifiants enregistrés';

  @override
  String get chatQuickMyFiles => 'Mes fichiers';

  @override
  String get chatQuickMyPassport => 'Mon passeport';

  @override
  String get chatQuickWhatCanYouDo => 'Que peux-tu faire ?';

  @override
  String get chatCardShowRelated => 'Voir les liens';

  @override
  String get chatCardTopFolders => 'Dossiers principaux';

  @override
  String get chatCardRecentFiles => 'Fichiers récents';

  @override
  String get chatCardSearchDeeper => 'Recherche approfondie';

  @override
  String get chatCardKeepBoth => 'Garder les deux';

  @override
  String get chatCardUpgradeStorage => 'Augmenter le stockage';

  @override
  String get unlockToSeeConcierge =>
      'Déverrouille un coffre pour voir le concierge.';

  @override
  String get unlockToSeeExpiry =>
      'Déverrouille un coffre pour voir le calendrier d\'expiration.';

  @override
  String get unlockToSeeMemory =>
      'Déverrouille un coffre pour voir la timeline mémoire.';

  @override
  String get unlockToSeeRelationships =>
      'Déverrouille un coffre pour voir le graphe des relations.';

  @override
  String get conciergeTitle => 'Concierge';

  @override
  String get conciergeSubtitle =>
      'Ce que VaultAI vous suggère de regarder en premier';

  @override
  String get conciergeLoading => 'Collecte des informations...';

  @override
  String get conciergeErrorPrefix =>
      'Impossible de charger les données du concierge.';

  @override
  String get conciergeCriticalNow => 'Critique en ce moment';

  @override
  String get conciergeComingUp => 'À venir';

  @override
  String get conciergeRecommendations => 'Recommandations';

  @override
  String get conciergeTravelReady => 'Prêt à voyager';

  @override
  String get conciergeTravelMostly => 'Presque prêt';

  @override
  String get conciergeTravelAttention => 'À vérifier';

  @override
  String get conciergeTravelReadyDetail =>
      'Passeport > 180 jours, visa > 30 jours.';

  @override
  String get conciergeTravelMostlyDetail =>
      'Passeport ou visa manquant ou bientôt à renouveler.';

  @override
  String get conciergeTravelAttentionDetail =>
      'Renouvellement nécessaire bientôt - vérifiez passeport et visa.';

  @override
  String get conciergeRenewalTimeline =>
      'Calendrier de renouvellement (90 prochains jours)';

  @override
  String get conciergeTravelReadiness => 'Préparation au voyage';

  @override
  String get conciergeAllClear => 'Tout est en ordre.';

  @override
  String get conciergeAllClearSub =>
      'Rien d\'urgent aujourd\'hui. VaultAI surveille vos documents et fera remonter toute nouveauté ici.';

  @override
  String get conciergePostureSecurity => 'Sécurité';

  @override
  String get conciergePostureExpiring => 'Expirations';

  @override
  String get conciergePostureInheritance => 'Héritage';

  @override
  String get conciergePostureScoreHint =>
      'Touchez pour ouvrir le centre de sécurité';

  @override
  String get conciergePostureNoData => 'aucune donnée';

  @override
  String get conciergePostureNothingTracked =>
      'Rien n\'est suivi pour l\'instant';

  @override
  String get conciergePostureAllFuture => 'Tout confortablement futur';

  @override
  String get conciergePostureFrozen => 'Coffre gelé';

  @override
  String get conciergePostureConfigured => 'Jumelage configuré';

  @override
  String get conciergePostureUnset => 'Aucun bénéficiaire';

  @override
  String get conciergePostureScoreNoData => 'aucune donnée';

  @override
  String get conciergeAskTravel => 'Suis-je prêt à voyager ?';

  @override
  String get conciergePassport => 'Passeport';

  @override
  String get conciergeVisa => 'Visa';

  @override
  String get conciergePassportNotOnFile => 'Non enregistré';

  @override
  String get conciergeNoExpiryDate => 'Aucune date d\'expiration';

  @override
  String get conciergeExpired => 'Expiré';

  @override
  String get conciergeRenewSoon => 'À renouveler';

  @override
  String get conciergeComfortable => 'Confortable';

  @override
  String get conciergeItem => 'élément';

  @override
  String get conciergeItems => 'éléments';

  @override
  String get conciergeInheritanceFrozen => 'gelé';

  @override
  String get conciergeInheritanceConfigured => 'configuré';

  @override
  String get conciergeInheritanceUnset => 'non configuré';

  @override
  String get expiryTitle => 'Expirations';

  @override
  String get expirySubtitle => 'Documents et obligations qui expirent bientôt';

  @override
  String get expiryLoading => 'Lecture des alertes d\'expiration...';

  @override
  String get expiryErrorPrefix => 'Impossible de charger les alertes.';

  @override
  String get expiryEmptyTitle =>
      'Vous êtes en avance sur chaque renouvellement.';

  @override
  String get expiryEmptySub =>
      'Téléversez un passeport, visa, police d\'assurance ou contrat et VaultAI suivra son expiration automatiquement.';

  @override
  String get expiryNoneInWindow => 'Rien dans cette période.';

  @override
  String expiryNoneInWindowSub(String window) {
    return 'Aucun document n\'expire dans $window. Essayez une période plus longue.';
  }

  @override
  String get expiryWindow7d => '7 jours';

  @override
  String get expiryWindow30d => '30 jours';

  @override
  String get expiryWindow90d => '90 jours';

  @override
  String get expiryWindowAll => 'Tout';

  @override
  String get expiryBucketCritical => 'Critique';

  @override
  String get expiryBucketWarning => 'Avertissement';

  @override
  String get expiryBucketInfo => 'Information';

  @override
  String expiryCountCritical(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count critiques',
      one: '1 critique',
    );
    return '$_temp0';
  }

  @override
  String expiryCountWarning(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count avertissements',
      one: '1 avertissement',
    );
    return '$_temp0';
  }

  @override
  String expiryDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '${days}j',
      one: '1j',
    );
    return '$_temp0';
  }

  @override
  String get expiryToday => 'Aujourd\'hui';

  @override
  String expiredAgo(int days) {
    return 'il y a ${days}j';
  }

  @override
  String get expiryNoDate => 'sans date';

  @override
  String get expiryDays => 'restant';

  @override
  String get expiryDaysExpires => 'expire';

  @override
  String get memoryTitle => 'Mémoire';

  @override
  String get memorySubtitle =>
      'Une chronologie de ce que VaultAI retient de votre vie';

  @override
  String get memoryLoading => 'Chargement de vos souvenirs...';

  @override
  String get memoryErrorPrefix => 'Impossible de charger la timeline mémoire.';

  @override
  String get memoryEmptyTitle => 'Aucun souvenir pour l\'instant.';

  @override
  String get memoryEmptySub =>
      'Dis à VaultAI quoi retenir : \'retiens que l\'anniversaire de ma mère est le 14 février\'. Tout apparaîtra ici, groupé par type et par date.';

  @override
  String get memoryNoMatchTitle => 'Aucun résultat.';

  @override
  String get memoryNoMatchSub =>
      'Effacez le filtre ou la recherche pour voir tous les souvenirs.';

  @override
  String get memorySearchHint => 'Rechercher dans les souvenirs...';

  @override
  String get memoryUndated => 'Sans date';

  @override
  String get memoryUnnamed => '(sans nom)';

  @override
  String get memoryTypeIdentity => 'Identité';

  @override
  String get memoryTypePeople => 'Personnes';

  @override
  String get memoryTypeFamily => 'Famille';

  @override
  String get memoryTypeBusiness => 'Affaires';

  @override
  String get memoryTypeTravel => 'Voyages';

  @override
  String get memoryTypeProjects => 'Projets';

  @override
  String get memoryTypeGoals => 'Objectifs';

  @override
  String get memoryTypePlaces => 'Lieux';

  @override
  String get memoryTypeDates => 'Dates';

  @override
  String get memoryTypeLifeEvent => 'Événements de vie';

  @override
  String get memoryTypePreferences => 'Préférences';

  @override
  String get memoryTypeNote => 'Notes';

  @override
  String memoryAskAbout(String key) {
    return 'Que sais-tu de $key ?';
  }

  @override
  String get relationshipsTitle => 'Relations';

  @override
  String get relationshipsSubtitle =>
      'Documents, comptes et souvenirs qui vont ensemble';

  @override
  String get relationshipsLoading => 'Cartographie de votre coffre...';

  @override
  String get relationshipsErrorPrefix => 'Impossible de charger les relations.';

  @override
  String get relationshipsEmptyTitle => 'Aucun groupe pour l\'instant.';

  @override
  String get relationshipsEmptySub =>
      'Téléversez un passeport, visa, facture ou contrat et VaultAI commencera à grouper les documents par voyage, identité, fiscalité, famille, etc.';

  @override
  String get relationshipsNoMatchTitle => 'Aucun résultat.';

  @override
  String get relationshipsNoMatchSub => 'Effacez le filtre ou la recherche.';

  @override
  String get relationshipsSearchHint =>
      'Rechercher documents, éléments ou relations...';

  @override
  String get relationshipsTypeTravel => 'Groupe Voyage';

  @override
  String get relationshipsTypeIdentity => 'Groupe Identité';

  @override
  String get relationshipsTypeBusiness => 'Groupe Affaires';

  @override
  String get relationshipsTypeFinance => 'Groupe Finance';

  @override
  String get relationshipsTypeTax => 'Groupe Fiscalité';

  @override
  String get relationshipsTypeMedical => 'Groupe Médical';

  @override
  String get relationshipsTypeFamily => 'Groupe Famille';

  @override
  String get relationshipsTypeSecurity => 'Groupe Sécurité';

  @override
  String get relationshipsTypeMedia => 'Groupe Médias';

  @override
  String get relationshipsTypeInheritance => 'Groupe Héritage';

  @override
  String get relationshipsEndpointFile => 'Fichier';

  @override
  String get relationshipsEndpointItem => 'Élément';

  @override
  String relationshipsAskRelated(String label) {
    return 'Qu\'est-ce qui est lié à « $label » ?';
  }

  @override
  String get settingsTitle => 'Paramètres';

  @override
  String get settingsSubtitle =>
      'Gérez le stockage de votre coffre et votre plan d\'abonnement.';

  @override
  String get settingsLanguage => 'Langue';

  @override
  String get settingsLanguageHint =>
      'Choisissez la langue que VaultAI utilise. Affecte les libellés et les réponses du chat.';

  @override
  String get settingsLanguageAuto => 'Auto (système)';

  @override
  String get settingsLanguageEnglish => 'English';

  @override
  String get settingsLanguageArabic => 'العربية';

  @override
  String get settingsLanguageFrench => 'Français';

  @override
  String get settingsLanguageSpanish => 'Español';

  @override
  String get settingsLanguageJapanese => '日本語';

  @override
  String get settingsLanguageKorean => '한국어';

  @override
  String get settingsLanguageChinese => '中文';

  @override
  String get settingsLanguageSearchHint =>
      'Rechercher une langue (ex. « Français », « French »)';

  @override
  String settingsLanguageAutoResolvedTo(String label) {
    return 'Système : $label';
  }

  @override
  String get settingsLanguageSelected => 'Sélectionné';

  @override
  String settingsLanguagePartialNotice(String name) {
    return 'VaultAI Chat répondra en $name. L\'interface reste en anglais pendant que la traduction est finalisée.';
  }

  @override
  String get settingsLanguagePopular => 'Populaires';

  @override
  String get settingsLanguageAllLanguages => 'Toutes les langues';

  @override
  String settingsLanguageShowAll(int count) {
    return 'Afficher toutes les langues ($count de plus)';
  }

  @override
  String get settingsLanguageShowFewer => 'Afficher moins';

  @override
  String settingsLanguageNoMatches(String query) {
    return 'Aucune langue ne correspond à «$query»';
  }

  @override
  String get settingsCurrentPlan => 'Plan actuel';

  @override
  String get settingsLoadingPlan => 'Chargement du plan…';

  @override
  String get settingsBuyMoreStorage => 'Acheter plus de stockage';

  @override
  String get settingsManageSubscription => 'Gérer l\'abonnement';

  @override
  String get settingsDeleteVaultTile => 'Supprimer le coffre';

  @override
  String get settingsDeleteVaultTileHint =>
      'Supprime définitivement votre coffre. Nécessite la phrase de confirmation et le PIN.';

  @override
  String get securityCenterTitle => 'Centre de sécurité';

  @override
  String get devicesTitle => 'Appareils';

  @override
  String get filesTitle => 'Fichiers';

  @override
  String get loginsTitle => 'Identifiants';

  @override
  String get inheritanceTitle => 'Héritage';

  @override
  String get dashboardTitle => 'Tableau de bord';

  @override
  String get priorityHigh => 'ÉLEVÉ';

  @override
  String get priorityMedium => 'MOYEN';

  @override
  String get priorityLow => 'FAIBLE';

  @override
  String get helpCenterTitle => 'Aide & FAQ';

  @override
  String get helpCenterSubtitle =>
      'Réponses aux questions courantes sur VaultAI. Cherchez ci-dessous ou parcourez par catégorie — l\'assistant IA répond à partir des mêmes sujets.';

  @override
  String get helpCenterEmpty => 'Aucun sujet correspondant';

  @override
  String get helpCenterEmptyBody =>
      'Essayez un autre terme, ou choisissez une catégorie.';

  @override
  String get helpCenterSupportNote =>
      'Le support client en direct n\'est pas encore disponible. Utilisez le centre d\'aide ou demandez à VaultAI Chat.';

  @override
  String get helpCenterPublicHint =>
      'Vous consultez le centre d\'aide public. Connectez-vous pour interroger VaultAI et voir les détails du compte.';

  @override
  String get helpCenterSearchHint =>
      'Rechercher dans l\'aide (ex. « monero », « PIN »)';

  @override
  String get helpCenterClearSearch => 'Effacer la recherche';

  @override
  String get helpCenterSignInToAsk => 'Connectez-vous pour demander à VaultAI';

  @override
  String get helpCategoryGettingStarted => 'Prise en main';

  @override
  String get helpCategorySecurity => 'Sécurité';

  @override
  String get helpCategoryFiles => 'Fichiers';

  @override
  String get helpCategorySecureItems => 'Éléments sécurisés';

  @override
  String get helpCategoryIds => 'Pièces d\'identité';

  @override
  String get helpCategoryCrypto => 'Crypto Vault';

  @override
  String get helpCategoryBilling => 'Facturation';

  @override
  String get helpCategoryTroubleshooting => 'Dépannage';

  @override
  String get deleteVaultTitle => 'Supprimer le coffre définitivement ?';

  @override
  String get deleteVaultBody =>
      'La suppression du coffre supprime définitivement vos données VaultAI, y compris les fichiers, éléments sécurisés, identifiants, pièces d\'identité, enregistrements chiffrés Crypto Vault et métadonnées associées.';

  @override
  String get deleteVaultCryptoWarning =>
      'Supprimer votre coffre ne déplace ni ne supprime les actifs crypto sur la blockchain. Si vous n\'avez pas sauvegardé votre portefeuille hors de VaultAI, la suppression peut entraîner une perte d\'accès à ces fonds.';

  @override
  String get deleteVaultPhraseInstruction =>
      'Tapez la phrase DELETE MY VAULT exactement pour confirmer :';

  @override
  String get deleteVaultPhraseMustMatch =>
      'La phrase doit correspondre exactement.';

  @override
  String get deleteVaultPinInstruction => 'Entrez votre PIN pour confirmer :';

  @override
  String get deleteVaultPinHint => 'PIN';

  @override
  String get deleteVaultConfirmButton => 'Supprimer le coffre';

  @override
  String get deleteVaultErrorInvalidPin => 'PIN incorrect.';

  @override
  String get deleteVaultErrorInvalidPhrase =>
      'Tapez la phrase exacte pour confirmer.';

  @override
  String get deleteVaultErrorExpired =>
      'Demande de suppression expirée. Réessayez.';

  @override
  String get deleteVaultErrorNotTrusted =>
      'Cet appareil n\'est pas approuvé. Approuvez-le d\'abord.';

  @override
  String get deleteVaultErrorGeneric =>
      'La suppression n\'a pas pu être terminée.';

  @override
  String get errorRateLimited =>
      'Trop de tentatives. Patientez quelques minutes puis réessayez.';

  @override
  String get errorRateLimitedPin => 'Trop de PIN erronés. Réessayez plus tard.';

  @override
  String errorRateLimitedWait(int seconds) {
    return 'Trop de tentatives. Attendez ${seconds}s';
  }

  @override
  String get errorSessionExpired => 'Session expirée. Reconnectez-vous.';

  @override
  String get errorInactivityLocked =>
      'Coffre verrouillé pour cause d\'inactivité.';

  @override
  String get errorVaultFrozen => 'Ce coffre est gelé.';

  @override
  String get errorDeviceNotTrusted =>
      'Cet appareil n\'est pas approuvé. Approuvez-le d\'abord.';

  @override
  String get errorGenericPrefix => 'Une erreur est survenue.';

  @override
  String get errorNetwork =>
      'Erreur réseau. Vérifiez votre connexion et réessayez.';

  @override
  String get errorRefreshFailed => 'Actualisation échouée. Réessayez.';

  @override
  String get snackDeviceApproved => 'Appareil approuvé.';

  @override
  String get snackDeviceRevoked => 'Appareil révoqué.';

  @override
  String snackDeviceApproveFailed(String error) {
    return 'Approbation échouée : $error';
  }

  @override
  String snackDeviceRevokeFailed(String error) {
    return 'Révocation échouée : $error';
  }

  @override
  String get snackAddressCopied => 'Adresse copiée';

  @override
  String get snackSendCooldown =>
      'Trop de tentatives d\'envoi récentes. Attendez un instant.';

  @override
  String get storagePageTitle => 'Stockage';

  @override
  String get storageNoDataAvailable => 'Aucune donnée de stockage disponible.';

  @override
  String get storageUsageHeading => 'Utilisation du stockage';

  @override
  String get storageAccountHeading => 'Compte';

  @override
  String get storageFreeTier => 'Palier gratuit';

  @override
  String get storageNeedMoreSpace => 'Besoin de plus d\'espace ?';

  @override
  String get storageGrandfathered => 'Stockage préservé';

  @override
  String get storageAdditionalPricing => 'Tarifs de stockage supplémentaire';

  @override
  String get storagePlanLower => 'Plan inférieur';

  @override
  String get storageCouldNotLoad => 'Impossible de charger le stockage';

  @override
  String get storageRefreshNow => 'Actualiser';

  @override
  String get securityManageDevices => 'Gérer les appareils';

  @override
  String get securityAnalyzePasswordsTitle => 'Analyser les mots de passe ?';

  @override
  String get securityEnterVaultPin => 'Entrez le PIN du coffre';

  @override
  String get securityAnalyzeButton => 'Analyser';

  @override
  String get securityAnalyzeMore => 'Analyser plus';

  @override
  String get devicePendingRequestSelfApproval => 'Demander l\'auto-approbation';

  @override
  String get devicePendingFinalize => 'Finaliser';

  @override
  String get devicePendingCancelApproval => 'Annuler l\'approbation';

  @override
  String get devicePendingCheckAgain => 'Vérifier à nouveau';

  @override
  String get devicePendingRegisterDevice => 'Enregistrer cet appareil';

  @override
  String get devicePendingDiagnoseTrust => 'Diagnostiquer la confiance';

  @override
  String get devicePendingCopyDiagnostics => 'Copier les diagnostics';

  @override
  String get devicePendingDiagnosticsCopied => 'Diagnostics copiés.';

  @override
  String get cryptoLiteCouldNotLoadRecord =>
      'Impossible de charger l\'enregistrement. Réessayez.';

  @override
  String get cryptoLiteAddressFormatMismatchTitle =>
      'Le format d\'adresse ne correspond pas';

  @override
  String get cryptoLiteSaveAnyway => 'Enregistrer quand même';

  @override
  String get cryptoLiteEditMetadata => 'Modifier les métadonnées';

  @override
  String get cryptoLiteEditBackupMetadata =>
      'Modifier les métadonnées de sauvegarde';

  @override
  String get cryptoOpenAsset => 'Ouvrir l\'actif';

  @override
  String get cryptoMoneroScannerStatus => 'État du scanner Monero';

  @override
  String get cryptoOpenMonero => 'Ouvrir Monero';

  @override
  String get cryptoSendDraftHeading => 'Brouillon d\'envoi';

  @override
  String get cryptoOpenSendFlow => 'Ouvrir l\'envoi';

  @override
  String get cryptoRetryFailed => 'Réessayer';

  @override
  String get cryptoOpenCryptoVault => 'Ouvrir Crypto Vault';

  @override
  String get cryptoCopyAddress => 'Copier l\'adresse';

  @override
  String get cryptoTransactionsTab => 'Transactions';

  @override
  String get cryptoContinueToPin => 'Continuer vers le PIN';

  @override
  String get cryptoCopyDestination => 'Copier la destination';

  @override
  String get cryptoSignatureCopied => 'Signature copiée';

  @override
  String get cryptoCopySignature => 'Copier la signature';

  @override
  String get cryptoTxIdCopied => 'ID de transaction copié';

  @override
  String get cryptoCopyTxId => 'Copier l\'ID tx';

  @override
  String get vaultCardOverview => 'Aperçu du coffre';

  @override
  String get vaultCardOpenVault => 'Ouvrir le coffre';

  @override
  String get vaultCardDocumentSummary => 'Résumé du document';

  @override
  String get vaultCardGeneratedLogins => 'Identifiants générés';

  @override
  String get vaultCardBilling => 'Facturation';

  @override
  String get vaultCardBrowseAllHelp => 'Parcourir tous les sujets d\'aide';

  @override
  String get secureItemCopyUsername => 'Copier le nom d\'utilisateur';

  @override
  String get secureItemCopyValue => 'Copier la valeur';

  @override
  String get notificationsTitle => 'Notifications';

  @override
  String get notificationsMarkAllRead => 'Tout marquer comme lu';

  @override
  String get landingHowItWorks => 'Comment ça marche';

  @override
  String get authDontHaveVault => 'Pas encore de coffre ? Créez-en un';

  @override
  String get authAlreadyHaveVault => 'Vous avez déjà un coffre ? Se connecter';

  @override
  String get authUseAnotherVault => 'Utiliser un autre coffre';

  @override
  String get authLogInAnotherVault => 'Se connecter à un autre coffre';

  @override
  String get snackDeviceTrusted => 'Nouvel appareil approuvé.';

  @override
  String get confirmEraseTitle => 'Effacer des données non récupérables ?';

  @override
  String get confirmEraseButton => 'Effacer et continuer';

  @override
  String inheritanceCancelPendingTransferTitle(String label) {
    return 'Annuler le transfert en attente vers « $label » ?';
  }

  @override
  String get inheritanceCancelTransfer => 'Annuler le transfert';

  @override
  String inheritanceClaimTitle(String label) {
    return 'Réclamer « $label »';
  }

  @override
  String inheritanceRequestTransferTitle(String label) {
    return 'Demander le transfert de « $label » ?';
  }

  @override
  String inheritanceRemoveTitle(String label) {
    return 'Retirer « $label » ?';
  }

  @override
  String get inheritanceStartCountdown =>
      'Démarrer le compte à rebours de 30 jours';

  @override
  String get inheritanceAddBeneficiary => 'Ajouter un bénéficiaire';

  @override
  String get inheritanceEnterCode => 'Entrer le code';

  @override
  String get inheritanceRequestTransfer => 'Demander le transfert';

  @override
  String get filesChooseStorage => 'Choisir la source';

  @override
  String get filesUploadFile => 'Téléverser un fichier';

  @override
  String get filesUploadPhoto => 'Téléverser une photo';

  @override
  String get filesUploadVideo => 'Téléverser une vidéo';

  @override
  String get filesUploadAudio => 'Téléverser un audio';

  @override
  String get filesUploadFolder => 'Téléverser un dossier';

  @override
  String get filesRecordVoice => 'Enregistrer la voix';

  @override
  String get filesRecordVideo => 'Enregistrer une vidéo';

  @override
  String get deleteVaultSignInRequired =>
      'Reconnectez-vous pour supprimer votre coffre.';

  @override
  String get deleteVaultSuccess => 'Votre coffre a été supprimé.';

  @override
  String get dashboardActiveVault => 'Coffre actif :';
}
