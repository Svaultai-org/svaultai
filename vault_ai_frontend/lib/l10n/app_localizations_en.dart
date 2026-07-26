// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'VaultAI';

  @override
  String get commonRetry => 'Retry';

  @override
  String get commonRefresh => 'Refresh';

  @override
  String get commonOpen => 'Open';

  @override
  String get commonCancel => 'Cancel';

  @override
  String get commonSave => 'Save';

  @override
  String get commonSignOut => 'Sign out';

  @override
  String get commonLoading => 'Loading...';

  @override
  String get commonAll => 'All';

  @override
  String get commonView => 'View';

  @override
  String get commonDownload => 'Download';

  @override
  String get commonAskVaultAI => 'Ask VaultAI';

  @override
  String get commonClose => 'Close';

  @override
  String get commonDelete => 'Delete';

  @override
  String get commonConfirm => 'Confirm';

  @override
  String get commonSignIn => 'Sign in';

  @override
  String get commonSignUp => 'Sign up';

  @override
  String get commonSearch => 'Search';

  @override
  String get commonBack => 'Back';

  @override
  String get commonNext => 'Next';

  @override
  String get commonYes => 'Yes';

  @override
  String get commonNo => 'No';

  @override
  String get commonError => 'Error';

  @override
  String get commonSuccess => 'Success';

  @override
  String get commonUnavailable => 'Unavailable';

  @override
  String get commonTryAgain => 'Try again';

  @override
  String get commonContinue => 'Continue';

  @override
  String get commonApprove => 'Approve';

  @override
  String get commonReject => 'Reject';

  @override
  String get commonRevoke => 'Revoke';

  @override
  String get commonReceive => 'Receive';

  @override
  String get commonReview => 'Review';

  @override
  String get commonAnalyze => 'Analyze';

  @override
  String get commonCopy => 'Copy';

  @override
  String get commonEdit => 'Edit';

  @override
  String get commonCurrent => 'Current';

  @override
  String get commonCopyCode => 'Copy code';

  @override
  String get commonRemove => 'Remove';

  @override
  String get commonNotYet => 'Not yet';

  @override
  String get sidebarDashboard => 'Dashboard';

  @override
  String get sidebarChat => 'Chat';

  @override
  String get sidebarFiles => 'Files';

  @override
  String get sidebarLogins => 'Logins';

  @override
  String get sidebarCryptoVault => 'Crypto Vault';

  @override
  String get sidebarConcierge => 'Concierge';

  @override
  String get sidebarExpiry => 'Expiry';

  @override
  String get sidebarMemory => 'Memory';

  @override
  String get sidebarInheritance => 'Inheritance';

  @override
  String get sidebarSettings => 'Settings';

  @override
  String get chatComposerHint => 'Ask about your vault or upload a file...';

  @override
  String get chatThinking => 'VaultAI is thinking...';

  @override
  String chatThinkingWithName(String name) {
    return '$name is thinking...';
  }

  @override
  String get chatSendButton => 'Send';

  @override
  String get chatSending => 'Sending...';

  @override
  String chatAskAbout(String topic) {
    return 'Tell me more about my $topic';
  }

  @override
  String get chatErrorGeneric =>
      'VaultAI could not answer that just now. Try again.';

  @override
  String get chatRetryButton => 'Retry';

  @override
  String get chatQuickSavedLogins => 'Saved logins';

  @override
  String get chatQuickMyFiles => 'My files';

  @override
  String get chatQuickMyPassport => 'My passport';

  @override
  String get chatQuickWhatCanYouDo => 'What can you do?';

  @override
  String get chatCardShowRelated => 'Show related';

  @override
  String get chatCardTopFolders => 'Top folders';

  @override
  String get chatCardRecentFiles => 'Recent files';

  @override
  String get chatCardSearchDeeper => 'Search deeper';

  @override
  String get chatCardKeepBoth => 'Keep both';

  @override
  String get chatCardUpgradeStorage => 'Upgrade storage';

  @override
  String get unlockToSeeConcierge =>
      'Unlock a vault to see your concierge dashboard.';

  @override
  String get unlockToSeeExpiry => 'Unlock a vault to see your expiry timeline.';

  @override
  String get unlockToSeeMemory => 'Unlock a vault to see your memory timeline.';

  @override
  String get conciergeTitle => 'Concierge';

  @override
  String get conciergeSubtitle => 'What VaultAI thinks you should look at next';

  @override
  String get conciergeLoading => 'Gathering intelligence...';

  @override
  String get conciergeErrorPrefix => 'Could not load concierge data.';

  @override
  String get conciergeCriticalNow => 'Critical right now';

  @override
  String get conciergeComingUp => 'Coming up';

  @override
  String get conciergeRecommendations => 'Recommendations';

  @override
  String get conciergeTravelReady => 'Travel-ready';

  @override
  String get conciergeTravelMostly => 'Mostly ready';

  @override
  String get conciergeTravelAttention => 'Needs attention';

  @override
  String get conciergeTravelReadyDetail =>
      'Passport > 180 days, visa > 30 days.';

  @override
  String get conciergeTravelMostlyDetail =>
      'One of passport / visa is missing or close to renewal.';

  @override
  String get conciergeTravelAttentionDetail =>
      'Renewal needed soon - check passport and visa.';

  @override
  String get conciergeRenewalTimeline => 'Renewal timeline (next 90 days)';

  @override
  String get conciergeTravelReadiness => 'Travel readiness';

  @override
  String get conciergeAllClear => 'All clear.';

  @override
  String get conciergeAllClearSub =>
      'Nothing urgent today. VaultAI is watching your documents and will surface anything new here.';

  @override
  String get conciergePostureSecurity => 'Security';

  @override
  String get conciergePostureExpiring => 'Expiring';

  @override
  String get conciergePostureInheritance => 'Inheritance';

  @override
  String get conciergePostureScoreHint => 'Tap to view security center';

  @override
  String get conciergePostureNoData => 'no data';

  @override
  String get conciergePostureNothingTracked => 'Nothing tracked yet';

  @override
  String get conciergePostureAllFuture => 'All comfortably future';

  @override
  String get conciergePostureFrozen => 'Vault is frozen';

  @override
  String get conciergePostureConfigured => 'Pairing configured';

  @override
  String get conciergePostureUnset => 'No beneficiary yet';

  @override
  String get conciergePostureScoreNoData => 'no data';

  @override
  String get conciergeAskTravel => 'Am I travel-ready?';

  @override
  String get conciergePassport => 'Passport';

  @override
  String get conciergeVisa => 'Visa';

  @override
  String get conciergePassportNotOnFile => 'Not on file';

  @override
  String get conciergeNoExpiryDate => 'No expiry date';

  @override
  String get conciergeExpired => 'Expired';

  @override
  String get conciergeRenewSoon => 'Renew soon';

  @override
  String get conciergeComfortable => 'Comfortable';

  @override
  String get conciergeItem => 'item';

  @override
  String get conciergeItems => 'items';

  @override
  String get conciergeInheritanceFrozen => 'frozen';

  @override
  String get conciergeInheritanceConfigured => 'configured';

  @override
  String get conciergeInheritanceUnset => 'unset';

  @override
  String get expiryTitle => 'Expiry';

  @override
  String get expirySubtitle => 'Documents and obligations expiring soon';

  @override
  String get expiryLoading => 'Reading expiry alerts...';

  @override
  String get expiryErrorPrefix => 'Could not load expiry alerts.';

  @override
  String get expiryEmptyTitle => 'You\'re fully ahead of every renewal.';

  @override
  String get expiryEmptySub =>
      'Upload a passport, visa, insurance policy, or contract and VaultAI will track its expiry automatically.';

  @override
  String get expiryNoneInWindow => 'Nothing in this window.';

  @override
  String expiryNoneInWindowSub(String window) {
    return 'No documents expire within $window. Try a longer window.';
  }

  @override
  String get expiryWindow7d => '7 days';

  @override
  String get expiryWindow30d => '30 days';

  @override
  String get expiryWindow90d => '90 days';

  @override
  String get expiryWindowAll => 'All';

  @override
  String get expiryBucketCritical => 'Critical';

  @override
  String get expiryBucketWarning => 'Warning';

  @override
  String get expiryBucketInfo => 'Heads-up';

  @override
  String expiryCountCritical(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count critical',
      one: '1 critical',
    );
    return '$_temp0';
  }

  @override
  String expiryCountWarning(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count warning',
      one: '1 warning',
    );
    return '$_temp0';
  }

  @override
  String expiryDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '${days}d',
      one: '1d',
    );
    return '$_temp0';
  }

  @override
  String get expiryToday => 'Today';

  @override
  String expiredAgo(int days) {
    return '${days}d ago';
  }

  @override
  String get expiryNoDate => 'no date';

  @override
  String get expiryDays => 'left';

  @override
  String get expiryDaysExpires => 'expires';

  @override
  String get memoryTitle => 'Memory';

  @override
  String get memorySubtitle =>
      'A timeline of what VaultAI remembers about your life';

  @override
  String get memoryLoading => 'Loading your memories...';

  @override
  String get memoryErrorPrefix => 'Could not load memory timeline.';

  @override
  String get memoryEmptyTitle => 'No memories yet.';

  @override
  String get memoryEmptySub =>
      'Tell VaultAI things to remember: \'remember my mom\'s birthday is Feb 14\', \'remember I started learning Spanish in 2024\'. They will show up here grouped by type and date.';

  @override
  String get memoryNoMatchTitle => 'Nothing matches.';

  @override
  String get memoryNoMatchSub =>
      'Try clearing the filter or search to see all memories.';

  @override
  String get memorySearchHint => 'Search memories...';

  @override
  String get memoryUndated => 'Undated';

  @override
  String get memoryUnnamed => '(unnamed)';

  @override
  String get memoryTypeIdentity => 'Identity';

  @override
  String get memoryTypePeople => 'People';

  @override
  String get memoryTypeFamily => 'Family';

  @override
  String get memoryTypeBusiness => 'Business';

  @override
  String get memoryTypeTravel => 'Travel';

  @override
  String get memoryTypeProjects => 'Projects';

  @override
  String get memoryTypeGoals => 'Goals';

  @override
  String get memoryTypePlaces => 'Places';

  @override
  String get memoryTypeDates => 'Dates';

  @override
  String get memoryTypeLifeEvent => 'Life events';

  @override
  String get memoryTypePreferences => 'Preferences';

  @override
  String get memoryTypeNote => 'Notes';

  @override
  String memoryAskAbout(String key) {
    return 'What do you remember about $key?';
  }

  @override
  String get settingsTitle => 'Settings';

  @override
  String get settingsSubtitle =>
      'Manage your vault storage and subscription plan.';

  @override
  String get settingsLanguage => 'Language';

  @override
  String get settingsLanguageHint =>
      'Choose how VaultAI talks to you. Affects this app\'s labels and AI chat replies.';

  @override
  String get settingsLanguageAuto => 'Auto (system)';

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
      'Search languages (e.g. \"Français\", \"French\")';

  @override
  String settingsLanguageAutoResolvedTo(String label) {
    return 'System: $label';
  }

  @override
  String get settingsLanguageSelected => 'Selected';

  @override
  String settingsLanguagePartialNotice(String name) {
    return 'VaultAI Chat will reply in $name. The app interface is still shown in English while translation is in progress.';
  }

  @override
  String get settingsLanguagePopular => 'Popular';

  @override
  String get settingsLanguageAllLanguages => 'All languages';

  @override
  String settingsLanguageShowAll(int count) {
    return 'Show all languages ($count more)';
  }

  @override
  String get settingsLanguageShowFewer => 'Show fewer';

  @override
  String settingsLanguageNoMatches(String query) {
    return 'No languages match \"$query\"';
  }

  @override
  String get settingsCurrentPlan => 'Current plan';

  @override
  String get settingsLoadingPlan => 'Loading plan…';

  @override
  String get settingsBuyMoreStorage => 'Buy More Storage';

  @override
  String get settingsManageSubscription => 'Manage Subscription';

  @override
  String get settingsDeleteVaultTile => 'Delete vault';

  @override
  String get settingsDeleteVaultTileHint =>
      'Permanently deletes your vault. Requires confirmation phrase and PIN.';

  @override
  String get securityCenterTitle => 'Security Center';

  @override
  String get devicesTitle => 'Devices';

  @override
  String get filesTitle => 'Files';

  @override
  String get loginsTitle => 'Logins';

  @override
  String get inheritanceTitle => 'Inheritance';

  @override
  String get dashboardTitle => 'Dashboard';

  @override
  String get priorityHigh => 'HIGH';

  @override
  String get priorityMedium => 'MEDIUM';

  @override
  String get priorityLow => 'LOW';

  @override
  String get helpCenterTitle => 'Help & FAQ';

  @override
  String get helpCenterSubtitle =>
      'Answers to common questions about VaultAI. Search below or browse by category — the AI assistant answers from the same set of topics.';

  @override
  String get helpCenterEmpty => 'No matching help topics';

  @override
  String get helpCenterEmptyBody =>
      'Try a different search term, or pick a category chip.';

  @override
  String get helpCenterSupportNote =>
      'Live customer support is not available yet. Use this Help Center or ask VaultAI Chat for help.';

  @override
  String get helpContactSupportTitle => 'Contact Support';

  @override
  String get helpContactSupportBody =>
      'Need help with VaultAI? Contact our support team.';

  @override
  String helpContactSupportEmailA11yLabel(String email) {
    return 'Email VaultAI support at $email';
  }

  @override
  String helpContactSupportEmailOpenFailed(String email) {
    return 'Couldn\'t open your email app. Copy this address instead: $email';
  }

  @override
  String get helpContactSupportCopyEmailLabel => 'Copy email address';

  @override
  String helpContactSupportCopyEmailA11yLabel(String email) {
    return 'Copy VaultAI support email $email to clipboard';
  }

  @override
  String get helpContactSupportEmailCopied => 'Email copied to clipboard';

  @override
  String get helpCenterPublicHint =>
      'You\'re viewing the public Help Center. Sign in to ask VaultAI and see account details.';

  @override
  String get helpCenterSearchHint =>
      'Search help topics (e.g. \"monero\", \"PIN\")';

  @override
  String get helpCenterClearSearch => 'Clear search';

  @override
  String get helpCenterSignInToAsk => 'Sign in to ask VaultAI';

  @override
  String get helpCategoryGettingStarted => 'Getting started';

  @override
  String get helpCategorySecurity => 'Security';

  @override
  String get helpCategoryFiles => 'Files';

  @override
  String get helpCategorySecureItems => 'Secure items';

  @override
  String get helpCategoryIds => 'IDs';

  @override
  String get helpCategoryCrypto => 'Crypto Vault';

  @override
  String get helpCategoryBilling => 'Billing';

  @override
  String get helpCategoryTroubleshooting => 'Troubleshooting';

  @override
  String get deleteVaultTitle => 'Delete vault permanently?';

  @override
  String get deleteVaultBody =>
      'Deleting your vault permanently deletes your VaultAI vault data, including files, secure items, logins, ID documents, Crypto Vault encrypted wallet records, and related vault metadata.';

  @override
  String get deleteVaultCryptoWarning =>
      'Deleting your vault does not move or delete crypto assets on the blockchain. If you have not backed up your wallet outside VaultAI, deleting your encrypted wallet records may cause loss of access to those funds.';

  @override
  String get deleteVaultPhraseInstruction =>
      'Type the phrase DELETE MY VAULT exactly to confirm:';

  @override
  String get deleteVaultPhraseMustMatch => 'Phrase must match exactly.';

  @override
  String get deleteVaultPinInstruction => 'Enter your PIN to confirm:';

  @override
  String get deleteVaultPinHint => 'PIN';

  @override
  String get deleteVaultConfirmButton => 'Delete vault';

  @override
  String get deleteVaultErrorInvalidPin => 'PIN is incorrect.';

  @override
  String get deleteVaultErrorInvalidPhrase =>
      'Type the exact phrase to confirm.';

  @override
  String get deleteVaultErrorExpired => 'Delete request expired. Try again.';

  @override
  String get deleteVaultErrorNotTrusted =>
      'This device is not trusted. Approve it first.';

  @override
  String get deleteVaultErrorGeneric => 'Deletion could not be completed.';

  @override
  String get errorRateLimited =>
      'Too many attempts. Please wait a few minutes and try again.';

  @override
  String get errorRateLimitedPin =>
      'Too many wrong PIN attempts. Try again later.';

  @override
  String errorRateLimitedWait(int seconds) {
    return 'Too many attempts. Wait ${seconds}s';
  }

  @override
  String get errorSessionExpired => 'Session expired. Sign in again.';

  @override
  String get errorInactivityLocked => 'Vault locked due to inactivity.';

  @override
  String get errorVaultFrozen => 'This vault has been frozen.';

  @override
  String get errorDeviceNotTrusted =>
      'This device is not trusted. Approve it first.';

  @override
  String get errorGenericPrefix => 'Something went wrong.';

  @override
  String get errorNetwork =>
      'Network error. Check your connection and try again.';

  @override
  String get errorRefreshFailed => 'Refresh failed. Try again.';

  @override
  String get snackDeviceApproved => 'Device approved.';

  @override
  String get snackDeviceRevoked => 'Device revoked.';

  @override
  String snackDeviceApproveFailed(String error) {
    return 'Approve failed: $error';
  }

  @override
  String snackDeviceRevokeFailed(String error) {
    return 'Revoke failed: $error';
  }

  @override
  String get snackAddressCopied => 'Address copied';

  @override
  String get snackSendCooldown =>
      'Too many recent send attempts. Wait a moment and try again.';

  @override
  String get storagePageTitle => 'Storage';

  @override
  String get storageNoDataAvailable => 'No storage data available.';

  @override
  String get storageUsageHeading => 'Storage Usage';

  @override
  String get storageAccountHeading => 'Account';

  @override
  String get storageFreeTier => 'Free Tier';

  @override
  String get storageNeedMoreSpace => 'Need more space?';

  @override
  String get storageGrandfathered => 'Grandfathered storage';

  @override
  String get storageAdditionalPricing => 'Additional storage pricing';

  @override
  String get storagePlanLower => 'Lower plan';

  @override
  String get storageCouldNotLoad => 'Could not load storage';

  @override
  String get storageRefreshNow => 'Refresh now';

  @override
  String get securityManageDevices => 'Manage devices';

  @override
  String get securityAnalyzePasswordsTitle => 'Analyze passwords?';

  @override
  String get securityEnterVaultPin => 'Enter vault PIN';

  @override
  String get securityAnalyzeButton => 'Analyze';

  @override
  String get securityAnalyzeMore => 'Analyze more';

  @override
  String get devicePendingRequestSelfApproval => 'Request self-approval';

  @override
  String get devicePendingFinalize => 'Finalize';

  @override
  String get devicePendingCancelApproval => 'Cancel approval';

  @override
  String get devicePendingCheckAgain => 'Check again';

  @override
  String get devicePendingRegisterDevice => 'Register this device';

  @override
  String get devicePendingDiagnoseTrust => 'Diagnose trust';

  @override
  String get devicePendingCopyDiagnostics => 'Copy diagnostics';

  @override
  String get devicePendingDiagnosticsCopied =>
      'Diagnostics copied to clipboard.';

  @override
  String get cryptoLiteCouldNotLoadRecord =>
      'Could not load record detail. Try again.';

  @override
  String get cryptoLiteAddressFormatMismatchTitle =>
      'Address format does not match';

  @override
  String get cryptoLiteSaveAnyway => 'Save anyway';

  @override
  String get cryptoLiteEditMetadata => 'Edit metadata';

  @override
  String get cryptoLiteEditBackupMetadata => 'Edit backup metadata';

  @override
  String get cryptoOpenAsset => 'Open asset';

  @override
  String get cryptoMoneroScannerStatus => 'Monero scanner status';

  @override
  String get cryptoOpenMonero => 'Open Monero';

  @override
  String get cryptoSendDraftHeading => 'Send draft';

  @override
  String get cryptoOpenSendFlow => 'Open send flow';

  @override
  String get cryptoRetryFailed => 'Retry failed';

  @override
  String get cryptoOpenCryptoVault => 'Open Crypto Vault';

  @override
  String get cryptoCopyAddress => 'Copy address';

  @override
  String get cryptoTransactionsTab => 'Transactions';

  @override
  String get cryptoContinueToPin => 'Continue to PIN';

  @override
  String get cryptoCopyDestination => 'Copy destination';

  @override
  String get cryptoSignatureCopied => 'Signature copied to clipboard';

  @override
  String get cryptoCopySignature => 'Copy signature';

  @override
  String get cryptoTxIdCopied => 'Transaction id copied to clipboard';

  @override
  String get cryptoCopyTxId => 'Copy txID';

  @override
  String get vaultCardOverview => 'Vault overview';

  @override
  String get vaultCardOpenVault => 'Open vault';

  @override
  String get vaultCardDocumentSummary => 'Document summary';

  @override
  String get vaultCardGeneratedLogins => 'Generated logins';

  @override
  String get vaultCardBilling => 'Billing';

  @override
  String get vaultCardBrowseAllHelp => 'Browse all help topics';

  @override
  String get secureItemCopyUsername => 'Copy username';

  @override
  String get secureItemCopyValue => 'Copy value';

  @override
  String get notificationsTitle => 'Notifications';

  @override
  String get notificationsMarkAllRead => 'Mark all read';

  @override
  String get landingHowItWorks => 'How it works';

  @override
  String get authDontHaveVault => 'Don\'t have a vault? Create one';

  @override
  String get authAlreadyHaveVault => 'Already have a vault? Sign in';

  @override
  String get authUseAnotherVault => 'Use another vault';

  @override
  String get authLogInAnotherVault => 'Log in to another vault';

  @override
  String get snackDeviceTrusted => 'New device trusted.';

  @override
  String get confirmEraseTitle => 'Erase unrecoverable data?';

  @override
  String get confirmEraseButton => 'Erase and continue';

  @override
  String inheritanceCancelPendingTransferTitle(String label) {
    return 'Cancel pending transfer to \"$label\"?';
  }

  @override
  String get inheritanceCancelTransfer => 'Cancel transfer';

  @override
  String inheritanceClaimTitle(String label) {
    return 'Claim \"$label\"';
  }

  @override
  String inheritanceRequestTransferTitle(String label) {
    return 'Request transfer of \"$label\"?';
  }

  @override
  String inheritanceRemoveTitle(String label) {
    return 'Remove \"$label\"?';
  }

  @override
  String get inheritanceStartCountdown => 'Start 30-day countdown';

  @override
  String get inheritanceAddBeneficiary => 'Add beneficiary';

  @override
  String get inheritanceEnterCode => 'Enter code';

  @override
  String get inheritanceRequestTransfer => 'Request transfer';

  @override
  String get filesChooseStorage => 'Choose Storage';

  @override
  String get filesUploadFile => 'Upload file';

  @override
  String get filesUploadPhoto => 'Upload photo';

  @override
  String get filesUploadVideo => 'Upload video';

  @override
  String get filesUploadAudio => 'Upload audio';

  @override
  String get filesUploadFolder => 'Upload folder';

  @override
  String get filesRecordVoice => 'Record voice';

  @override
  String get filesRecordVideo => 'Record video';

  @override
  String get deleteVaultSignInRequired =>
      'Please sign in again to delete your vault.';

  @override
  String get deleteVaultSuccess => 'Your vault has been deleted.';

  @override
  String get dashboardActiveVault => 'Active vault:';
}
