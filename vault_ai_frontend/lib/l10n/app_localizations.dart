import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_ar.dart';
import 'app_localizations_en.dart';
import 'app_localizations_es.dart';
import 'app_localizations_fr.dart';
import 'app_localizations_ja.dart';
import 'app_localizations_ko.dart';
import 'app_localizations_zh.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
      : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
    delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
  ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('ar'),
    Locale('en'),
    Locale('es'),
    Locale('fr'),
    Locale('ja'),
    Locale('ko'),
    Locale('zh')
  ];

  /// App title shown in MaterialApp + dialogs
  ///
  /// In en, this message translates to:
  /// **'VaultAI'**
  String get appTitle;

  /// No description provided for @commonRetry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get commonRetry;

  /// No description provided for @commonRefresh.
  ///
  /// In en, this message translates to:
  /// **'Refresh'**
  String get commonRefresh;

  /// No description provided for @commonOpen.
  ///
  /// In en, this message translates to:
  /// **'Open'**
  String get commonOpen;

  /// No description provided for @commonCancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get commonCancel;

  /// No description provided for @commonSave.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get commonSave;

  /// No description provided for @commonSignOut.
  ///
  /// In en, this message translates to:
  /// **'Sign out'**
  String get commonSignOut;

  /// No description provided for @commonLoading.
  ///
  /// In en, this message translates to:
  /// **'Loading...'**
  String get commonLoading;

  /// No description provided for @commonAll.
  ///
  /// In en, this message translates to:
  /// **'All'**
  String get commonAll;

  /// No description provided for @commonView.
  ///
  /// In en, this message translates to:
  /// **'View'**
  String get commonView;

  /// No description provided for @commonDownload.
  ///
  /// In en, this message translates to:
  /// **'Download'**
  String get commonDownload;

  /// No description provided for @commonAskVaultAI.
  ///
  /// In en, this message translates to:
  /// **'Ask VaultAI'**
  String get commonAskVaultAI;

  /// No description provided for @commonClose.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get commonClose;

  /// No description provided for @commonDelete.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get commonDelete;

  /// No description provided for @commonConfirm.
  ///
  /// In en, this message translates to:
  /// **'Confirm'**
  String get commonConfirm;

  /// No description provided for @commonSignIn.
  ///
  /// In en, this message translates to:
  /// **'Sign in'**
  String get commonSignIn;

  /// No description provided for @commonSignUp.
  ///
  /// In en, this message translates to:
  /// **'Sign up'**
  String get commonSignUp;

  /// No description provided for @commonSearch.
  ///
  /// In en, this message translates to:
  /// **'Search'**
  String get commonSearch;

  /// No description provided for @commonBack.
  ///
  /// In en, this message translates to:
  /// **'Back'**
  String get commonBack;

  /// No description provided for @commonNext.
  ///
  /// In en, this message translates to:
  /// **'Next'**
  String get commonNext;

  /// No description provided for @commonYes.
  ///
  /// In en, this message translates to:
  /// **'Yes'**
  String get commonYes;

  /// No description provided for @commonNo.
  ///
  /// In en, this message translates to:
  /// **'No'**
  String get commonNo;

  /// No description provided for @commonError.
  ///
  /// In en, this message translates to:
  /// **'Error'**
  String get commonError;

  /// No description provided for @commonSuccess.
  ///
  /// In en, this message translates to:
  /// **'Success'**
  String get commonSuccess;

  /// No description provided for @commonUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Unavailable'**
  String get commonUnavailable;

  /// No description provided for @commonTryAgain.
  ///
  /// In en, this message translates to:
  /// **'Try again'**
  String get commonTryAgain;

  /// No description provided for @commonContinue.
  ///
  /// In en, this message translates to:
  /// **'Continue'**
  String get commonContinue;

  /// No description provided for @commonApprove.
  ///
  /// In en, this message translates to:
  /// **'Approve'**
  String get commonApprove;

  /// No description provided for @commonReject.
  ///
  /// In en, this message translates to:
  /// **'Reject'**
  String get commonReject;

  /// No description provided for @commonRevoke.
  ///
  /// In en, this message translates to:
  /// **'Revoke'**
  String get commonRevoke;

  /// No description provided for @commonReceive.
  ///
  /// In en, this message translates to:
  /// **'Receive'**
  String get commonReceive;

  /// No description provided for @commonReview.
  ///
  /// In en, this message translates to:
  /// **'Review'**
  String get commonReview;

  /// No description provided for @commonAnalyze.
  ///
  /// In en, this message translates to:
  /// **'Analyze'**
  String get commonAnalyze;

  /// No description provided for @commonCopy.
  ///
  /// In en, this message translates to:
  /// **'Copy'**
  String get commonCopy;

  /// No description provided for @commonEdit.
  ///
  /// In en, this message translates to:
  /// **'Edit'**
  String get commonEdit;

  /// No description provided for @commonCurrent.
  ///
  /// In en, this message translates to:
  /// **'Current'**
  String get commonCurrent;

  /// No description provided for @commonCopyCode.
  ///
  /// In en, this message translates to:
  /// **'Copy code'**
  String get commonCopyCode;

  /// No description provided for @commonRemove.
  ///
  /// In en, this message translates to:
  /// **'Remove'**
  String get commonRemove;

  /// No description provided for @commonNotYet.
  ///
  /// In en, this message translates to:
  /// **'Not yet'**
  String get commonNotYet;

  /// No description provided for @sidebarDashboard.
  ///
  /// In en, this message translates to:
  /// **'Dashboard'**
  String get sidebarDashboard;

  /// No description provided for @sidebarChat.
  ///
  /// In en, this message translates to:
  /// **'Chat'**
  String get sidebarChat;

  /// No description provided for @sidebarFiles.
  ///
  /// In en, this message translates to:
  /// **'Files'**
  String get sidebarFiles;

  /// No description provided for @sidebarLogins.
  ///
  /// In en, this message translates to:
  /// **'Logins'**
  String get sidebarLogins;

  /// No description provided for @sidebarCryptoVault.
  ///
  /// In en, this message translates to:
  /// **'Crypto Vault'**
  String get sidebarCryptoVault;

  /// No description provided for @sidebarConcierge.
  ///
  /// In en, this message translates to:
  /// **'Concierge'**
  String get sidebarConcierge;

  /// No description provided for @sidebarExpiry.
  ///
  /// In en, this message translates to:
  /// **'Expiry'**
  String get sidebarExpiry;

  /// No description provided for @sidebarMemory.
  ///
  /// In en, this message translates to:
  /// **'Memory'**
  String get sidebarMemory;

  /// No description provided for @sidebarRelationships.
  ///
  /// In en, this message translates to:
  /// **'Relationships'**
  String get sidebarRelationships;

  /// No description provided for @sidebarInheritance.
  ///
  /// In en, this message translates to:
  /// **'Inheritance'**
  String get sidebarInheritance;

  /// No description provided for @sidebarSettings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get sidebarSettings;

  /// No description provided for @chatComposerHint.
  ///
  /// In en, this message translates to:
  /// **'Ask about your vault or upload a file...'**
  String get chatComposerHint;

  /// No description provided for @chatThinking.
  ///
  /// In en, this message translates to:
  /// **'VaultAI is thinking...'**
  String get chatThinking;

  /// Typing indicator personalized with the active vault name
  ///
  /// In en, this message translates to:
  /// **'{name} is thinking...'**
  String chatThinkingWithName(String name);

  /// No description provided for @chatSendButton.
  ///
  /// In en, this message translates to:
  /// **'Send'**
  String get chatSendButton;

  /// No description provided for @chatSending.
  ///
  /// In en, this message translates to:
  /// **'Sending...'**
  String get chatSending;

  /// Quick prompt template
  ///
  /// In en, this message translates to:
  /// **'Tell me more about my {topic}'**
  String chatAskAbout(String topic);

  /// No description provided for @chatErrorGeneric.
  ///
  /// In en, this message translates to:
  /// **'VaultAI could not answer that just now. Try again.'**
  String get chatErrorGeneric;

  /// No description provided for @chatRetryButton.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get chatRetryButton;

  /// No description provided for @chatQuickSavedLogins.
  ///
  /// In en, this message translates to:
  /// **'Saved logins'**
  String get chatQuickSavedLogins;

  /// No description provided for @chatQuickMyFiles.
  ///
  /// In en, this message translates to:
  /// **'My files'**
  String get chatQuickMyFiles;

  /// No description provided for @chatQuickMyPassport.
  ///
  /// In en, this message translates to:
  /// **'My passport'**
  String get chatQuickMyPassport;

  /// No description provided for @chatQuickWhatCanYouDo.
  ///
  /// In en, this message translates to:
  /// **'What can you do?'**
  String get chatQuickWhatCanYouDo;

  /// No description provided for @chatCardShowRelated.
  ///
  /// In en, this message translates to:
  /// **'Show related'**
  String get chatCardShowRelated;

  /// No description provided for @chatCardTopFolders.
  ///
  /// In en, this message translates to:
  /// **'Top folders'**
  String get chatCardTopFolders;

  /// No description provided for @chatCardRecentFiles.
  ///
  /// In en, this message translates to:
  /// **'Recent files'**
  String get chatCardRecentFiles;

  /// No description provided for @chatCardSearchDeeper.
  ///
  /// In en, this message translates to:
  /// **'Search deeper'**
  String get chatCardSearchDeeper;

  /// No description provided for @chatCardKeepBoth.
  ///
  /// In en, this message translates to:
  /// **'Keep both'**
  String get chatCardKeepBoth;

  /// No description provided for @chatCardUpgradeStorage.
  ///
  /// In en, this message translates to:
  /// **'Upgrade storage'**
  String get chatCardUpgradeStorage;

  /// No description provided for @unlockToSeeConcierge.
  ///
  /// In en, this message translates to:
  /// **'Unlock a vault to see your concierge dashboard.'**
  String get unlockToSeeConcierge;

  /// No description provided for @unlockToSeeExpiry.
  ///
  /// In en, this message translates to:
  /// **'Unlock a vault to see your expiry timeline.'**
  String get unlockToSeeExpiry;

  /// No description provided for @unlockToSeeMemory.
  ///
  /// In en, this message translates to:
  /// **'Unlock a vault to see your memory timeline.'**
  String get unlockToSeeMemory;

  /// No description provided for @unlockToSeeRelationships.
  ///
  /// In en, this message translates to:
  /// **'Unlock a vault to see your relationship graph.'**
  String get unlockToSeeRelationships;

  /// No description provided for @conciergeTitle.
  ///
  /// In en, this message translates to:
  /// **'Concierge'**
  String get conciergeTitle;

  /// No description provided for @conciergeSubtitle.
  ///
  /// In en, this message translates to:
  /// **'What VaultAI thinks you should look at next'**
  String get conciergeSubtitle;

  /// No description provided for @conciergeLoading.
  ///
  /// In en, this message translates to:
  /// **'Gathering intelligence...'**
  String get conciergeLoading;

  /// No description provided for @conciergeErrorPrefix.
  ///
  /// In en, this message translates to:
  /// **'Could not load concierge data.'**
  String get conciergeErrorPrefix;

  /// No description provided for @conciergeCriticalNow.
  ///
  /// In en, this message translates to:
  /// **'Critical right now'**
  String get conciergeCriticalNow;

  /// No description provided for @conciergeComingUp.
  ///
  /// In en, this message translates to:
  /// **'Coming up'**
  String get conciergeComingUp;

  /// No description provided for @conciergeRecommendations.
  ///
  /// In en, this message translates to:
  /// **'Recommendations'**
  String get conciergeRecommendations;

  /// No description provided for @conciergeTravelReady.
  ///
  /// In en, this message translates to:
  /// **'Travel-ready'**
  String get conciergeTravelReady;

  /// No description provided for @conciergeTravelMostly.
  ///
  /// In en, this message translates to:
  /// **'Mostly ready'**
  String get conciergeTravelMostly;

  /// No description provided for @conciergeTravelAttention.
  ///
  /// In en, this message translates to:
  /// **'Needs attention'**
  String get conciergeTravelAttention;

  /// No description provided for @conciergeTravelReadyDetail.
  ///
  /// In en, this message translates to:
  /// **'Passport > 180 days, visa > 30 days.'**
  String get conciergeTravelReadyDetail;

  /// No description provided for @conciergeTravelMostlyDetail.
  ///
  /// In en, this message translates to:
  /// **'One of passport / visa is missing or close to renewal.'**
  String get conciergeTravelMostlyDetail;

  /// No description provided for @conciergeTravelAttentionDetail.
  ///
  /// In en, this message translates to:
  /// **'Renewal needed soon - check passport and visa.'**
  String get conciergeTravelAttentionDetail;

  /// No description provided for @conciergeRenewalTimeline.
  ///
  /// In en, this message translates to:
  /// **'Renewal timeline (next 90 days)'**
  String get conciergeRenewalTimeline;

  /// No description provided for @conciergeTravelReadiness.
  ///
  /// In en, this message translates to:
  /// **'Travel readiness'**
  String get conciergeTravelReadiness;

  /// No description provided for @conciergeAllClear.
  ///
  /// In en, this message translates to:
  /// **'All clear.'**
  String get conciergeAllClear;

  /// No description provided for @conciergeAllClearSub.
  ///
  /// In en, this message translates to:
  /// **'Nothing urgent today. VaultAI is watching your documents and will surface anything new here.'**
  String get conciergeAllClearSub;

  /// No description provided for @conciergePostureSecurity.
  ///
  /// In en, this message translates to:
  /// **'Security'**
  String get conciergePostureSecurity;

  /// No description provided for @conciergePostureExpiring.
  ///
  /// In en, this message translates to:
  /// **'Expiring'**
  String get conciergePostureExpiring;

  /// No description provided for @conciergePostureInheritance.
  ///
  /// In en, this message translates to:
  /// **'Inheritance'**
  String get conciergePostureInheritance;

  /// No description provided for @conciergePostureScoreHint.
  ///
  /// In en, this message translates to:
  /// **'Tap to view security center'**
  String get conciergePostureScoreHint;

  /// No description provided for @conciergePostureNoData.
  ///
  /// In en, this message translates to:
  /// **'no data'**
  String get conciergePostureNoData;

  /// No description provided for @conciergePostureNothingTracked.
  ///
  /// In en, this message translates to:
  /// **'Nothing tracked yet'**
  String get conciergePostureNothingTracked;

  /// No description provided for @conciergePostureAllFuture.
  ///
  /// In en, this message translates to:
  /// **'All comfortably future'**
  String get conciergePostureAllFuture;

  /// No description provided for @conciergePostureFrozen.
  ///
  /// In en, this message translates to:
  /// **'Vault is frozen'**
  String get conciergePostureFrozen;

  /// No description provided for @conciergePostureConfigured.
  ///
  /// In en, this message translates to:
  /// **'Pairing configured'**
  String get conciergePostureConfigured;

  /// No description provided for @conciergePostureUnset.
  ///
  /// In en, this message translates to:
  /// **'No beneficiary yet'**
  String get conciergePostureUnset;

  /// No description provided for @conciergePostureScoreNoData.
  ///
  /// In en, this message translates to:
  /// **'no data'**
  String get conciergePostureScoreNoData;

  /// No description provided for @conciergeAskTravel.
  ///
  /// In en, this message translates to:
  /// **'Am I travel-ready?'**
  String get conciergeAskTravel;

  /// No description provided for @conciergePassport.
  ///
  /// In en, this message translates to:
  /// **'Passport'**
  String get conciergePassport;

  /// No description provided for @conciergeVisa.
  ///
  /// In en, this message translates to:
  /// **'Visa'**
  String get conciergeVisa;

  /// No description provided for @conciergePassportNotOnFile.
  ///
  /// In en, this message translates to:
  /// **'Not on file'**
  String get conciergePassportNotOnFile;

  /// No description provided for @conciergeNoExpiryDate.
  ///
  /// In en, this message translates to:
  /// **'No expiry date'**
  String get conciergeNoExpiryDate;

  /// No description provided for @conciergeExpired.
  ///
  /// In en, this message translates to:
  /// **'Expired'**
  String get conciergeExpired;

  /// No description provided for @conciergeRenewSoon.
  ///
  /// In en, this message translates to:
  /// **'Renew soon'**
  String get conciergeRenewSoon;

  /// No description provided for @conciergeComfortable.
  ///
  /// In en, this message translates to:
  /// **'Comfortable'**
  String get conciergeComfortable;

  /// No description provided for @conciergeItem.
  ///
  /// In en, this message translates to:
  /// **'item'**
  String get conciergeItem;

  /// No description provided for @conciergeItems.
  ///
  /// In en, this message translates to:
  /// **'items'**
  String get conciergeItems;

  /// No description provided for @conciergeInheritanceFrozen.
  ///
  /// In en, this message translates to:
  /// **'frozen'**
  String get conciergeInheritanceFrozen;

  /// No description provided for @conciergeInheritanceConfigured.
  ///
  /// In en, this message translates to:
  /// **'configured'**
  String get conciergeInheritanceConfigured;

  /// No description provided for @conciergeInheritanceUnset.
  ///
  /// In en, this message translates to:
  /// **'unset'**
  String get conciergeInheritanceUnset;

  /// No description provided for @expiryTitle.
  ///
  /// In en, this message translates to:
  /// **'Expiry'**
  String get expiryTitle;

  /// No description provided for @expirySubtitle.
  ///
  /// In en, this message translates to:
  /// **'Documents and obligations expiring soon'**
  String get expirySubtitle;

  /// No description provided for @expiryLoading.
  ///
  /// In en, this message translates to:
  /// **'Reading expiry alerts...'**
  String get expiryLoading;

  /// No description provided for @expiryErrorPrefix.
  ///
  /// In en, this message translates to:
  /// **'Could not load expiry alerts.'**
  String get expiryErrorPrefix;

  /// No description provided for @expiryEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'You\'re fully ahead of every renewal.'**
  String get expiryEmptyTitle;

  /// No description provided for @expiryEmptySub.
  ///
  /// In en, this message translates to:
  /// **'Upload a passport, visa, insurance policy, or contract and VaultAI will track its expiry automatically.'**
  String get expiryEmptySub;

  /// No description provided for @expiryNoneInWindow.
  ///
  /// In en, this message translates to:
  /// **'Nothing in this window.'**
  String get expiryNoneInWindow;

  /// No description provided for @expiryNoneInWindowSub.
  ///
  /// In en, this message translates to:
  /// **'No documents expire within {window}. Try a longer window.'**
  String expiryNoneInWindowSub(String window);

  /// No description provided for @expiryWindow7d.
  ///
  /// In en, this message translates to:
  /// **'7 days'**
  String get expiryWindow7d;

  /// No description provided for @expiryWindow30d.
  ///
  /// In en, this message translates to:
  /// **'30 days'**
  String get expiryWindow30d;

  /// No description provided for @expiryWindow90d.
  ///
  /// In en, this message translates to:
  /// **'90 days'**
  String get expiryWindow90d;

  /// No description provided for @expiryWindowAll.
  ///
  /// In en, this message translates to:
  /// **'All'**
  String get expiryWindowAll;

  /// No description provided for @expiryBucketCritical.
  ///
  /// In en, this message translates to:
  /// **'Critical'**
  String get expiryBucketCritical;

  /// No description provided for @expiryBucketWarning.
  ///
  /// In en, this message translates to:
  /// **'Warning'**
  String get expiryBucketWarning;

  /// No description provided for @expiryBucketInfo.
  ///
  /// In en, this message translates to:
  /// **'Heads-up'**
  String get expiryBucketInfo;

  /// No description provided for @expiryCountCritical.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 critical} other{{count} critical}}'**
  String expiryCountCritical(int count);

  /// No description provided for @expiryCountWarning.
  ///
  /// In en, this message translates to:
  /// **'{count, plural, =1{1 warning} other{{count} warning}}'**
  String expiryCountWarning(int count);

  /// No description provided for @expiryDaysLeft.
  ///
  /// In en, this message translates to:
  /// **'{days, plural, =1{1d} other{{days}d}}'**
  String expiryDaysLeft(int days);

  /// No description provided for @expiryToday.
  ///
  /// In en, this message translates to:
  /// **'Today'**
  String get expiryToday;

  /// No description provided for @expiredAgo.
  ///
  /// In en, this message translates to:
  /// **'{days}d ago'**
  String expiredAgo(int days);

  /// No description provided for @expiryNoDate.
  ///
  /// In en, this message translates to:
  /// **'no date'**
  String get expiryNoDate;

  /// No description provided for @expiryDays.
  ///
  /// In en, this message translates to:
  /// **'left'**
  String get expiryDays;

  /// No description provided for @expiryDaysExpires.
  ///
  /// In en, this message translates to:
  /// **'expires'**
  String get expiryDaysExpires;

  /// No description provided for @memoryTitle.
  ///
  /// In en, this message translates to:
  /// **'Memory'**
  String get memoryTitle;

  /// No description provided for @memorySubtitle.
  ///
  /// In en, this message translates to:
  /// **'A timeline of what VaultAI remembers about your life'**
  String get memorySubtitle;

  /// No description provided for @memoryLoading.
  ///
  /// In en, this message translates to:
  /// **'Loading your memories...'**
  String get memoryLoading;

  /// No description provided for @memoryErrorPrefix.
  ///
  /// In en, this message translates to:
  /// **'Could not load memory timeline.'**
  String get memoryErrorPrefix;

  /// No description provided for @memoryEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No memories yet.'**
  String get memoryEmptyTitle;

  /// No description provided for @memoryEmptySub.
  ///
  /// In en, this message translates to:
  /// **'Tell VaultAI things to remember: \'remember my mom\'s birthday is Feb 14\', \'remember I started learning Spanish in 2024\'. They will show up here grouped by type and date.'**
  String get memoryEmptySub;

  /// No description provided for @memoryNoMatchTitle.
  ///
  /// In en, this message translates to:
  /// **'Nothing matches.'**
  String get memoryNoMatchTitle;

  /// No description provided for @memoryNoMatchSub.
  ///
  /// In en, this message translates to:
  /// **'Try clearing the filter or search to see all memories.'**
  String get memoryNoMatchSub;

  /// No description provided for @memorySearchHint.
  ///
  /// In en, this message translates to:
  /// **'Search memories...'**
  String get memorySearchHint;

  /// No description provided for @memoryUndated.
  ///
  /// In en, this message translates to:
  /// **'Undated'**
  String get memoryUndated;

  /// No description provided for @memoryUnnamed.
  ///
  /// In en, this message translates to:
  /// **'(unnamed)'**
  String get memoryUnnamed;

  /// No description provided for @memoryTypeIdentity.
  ///
  /// In en, this message translates to:
  /// **'Identity'**
  String get memoryTypeIdentity;

  /// No description provided for @memoryTypePeople.
  ///
  /// In en, this message translates to:
  /// **'People'**
  String get memoryTypePeople;

  /// No description provided for @memoryTypeFamily.
  ///
  /// In en, this message translates to:
  /// **'Family'**
  String get memoryTypeFamily;

  /// No description provided for @memoryTypeBusiness.
  ///
  /// In en, this message translates to:
  /// **'Business'**
  String get memoryTypeBusiness;

  /// No description provided for @memoryTypeTravel.
  ///
  /// In en, this message translates to:
  /// **'Travel'**
  String get memoryTypeTravel;

  /// No description provided for @memoryTypeProjects.
  ///
  /// In en, this message translates to:
  /// **'Projects'**
  String get memoryTypeProjects;

  /// No description provided for @memoryTypeGoals.
  ///
  /// In en, this message translates to:
  /// **'Goals'**
  String get memoryTypeGoals;

  /// No description provided for @memoryTypePlaces.
  ///
  /// In en, this message translates to:
  /// **'Places'**
  String get memoryTypePlaces;

  /// No description provided for @memoryTypeDates.
  ///
  /// In en, this message translates to:
  /// **'Dates'**
  String get memoryTypeDates;

  /// No description provided for @memoryTypeLifeEvent.
  ///
  /// In en, this message translates to:
  /// **'Life events'**
  String get memoryTypeLifeEvent;

  /// No description provided for @memoryTypePreferences.
  ///
  /// In en, this message translates to:
  /// **'Preferences'**
  String get memoryTypePreferences;

  /// No description provided for @memoryTypeNote.
  ///
  /// In en, this message translates to:
  /// **'Notes'**
  String get memoryTypeNote;

  /// No description provided for @memoryAskAbout.
  ///
  /// In en, this message translates to:
  /// **'What do you remember about {key}?'**
  String memoryAskAbout(String key);

  /// No description provided for @relationshipsTitle.
  ///
  /// In en, this message translates to:
  /// **'Relationships'**
  String get relationshipsTitle;

  /// No description provided for @relationshipsSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Documents, accounts, and memories that belong together'**
  String get relationshipsSubtitle;

  /// No description provided for @relationshipsLoading.
  ///
  /// In en, this message translates to:
  /// **'Mapping your vault...'**
  String get relationshipsLoading;

  /// No description provided for @relationshipsErrorPrefix.
  ///
  /// In en, this message translates to:
  /// **'Could not load relationships.'**
  String get relationshipsErrorPrefix;

  /// No description provided for @relationshipsEmptyTitle.
  ///
  /// In en, this message translates to:
  /// **'No clusters yet.'**
  String get relationshipsEmptyTitle;

  /// No description provided for @relationshipsEmptySub.
  ///
  /// In en, this message translates to:
  /// **'Upload a passport, visa, invoice, or contract and VaultAI will start grouping documents that belong together by travel, identity, tax, family, and more.'**
  String get relationshipsEmptySub;

  /// No description provided for @relationshipsNoMatchTitle.
  ///
  /// In en, this message translates to:
  /// **'Nothing matches.'**
  String get relationshipsNoMatchTitle;

  /// No description provided for @relationshipsNoMatchSub.
  ///
  /// In en, this message translates to:
  /// **'Try clearing the filter or search.'**
  String get relationshipsNoMatchSub;

  /// No description provided for @relationshipsSearchHint.
  ///
  /// In en, this message translates to:
  /// **'Search documents, items, or relations...'**
  String get relationshipsSearchHint;

  /// No description provided for @relationshipsTypeTravel.
  ///
  /// In en, this message translates to:
  /// **'Travel cluster'**
  String get relationshipsTypeTravel;

  /// No description provided for @relationshipsTypeIdentity.
  ///
  /// In en, this message translates to:
  /// **'Identity cluster'**
  String get relationshipsTypeIdentity;

  /// No description provided for @relationshipsTypeBusiness.
  ///
  /// In en, this message translates to:
  /// **'Business cluster'**
  String get relationshipsTypeBusiness;

  /// No description provided for @relationshipsTypeFinance.
  ///
  /// In en, this message translates to:
  /// **'Finance cluster'**
  String get relationshipsTypeFinance;

  /// No description provided for @relationshipsTypeTax.
  ///
  /// In en, this message translates to:
  /// **'Tax cluster'**
  String get relationshipsTypeTax;

  /// No description provided for @relationshipsTypeMedical.
  ///
  /// In en, this message translates to:
  /// **'Medical cluster'**
  String get relationshipsTypeMedical;

  /// No description provided for @relationshipsTypeFamily.
  ///
  /// In en, this message translates to:
  /// **'Family cluster'**
  String get relationshipsTypeFamily;

  /// No description provided for @relationshipsTypeSecurity.
  ///
  /// In en, this message translates to:
  /// **'Security cluster'**
  String get relationshipsTypeSecurity;

  /// No description provided for @relationshipsTypeMedia.
  ///
  /// In en, this message translates to:
  /// **'Media cluster'**
  String get relationshipsTypeMedia;

  /// No description provided for @relationshipsTypeInheritance.
  ///
  /// In en, this message translates to:
  /// **'Inheritance cluster'**
  String get relationshipsTypeInheritance;

  /// No description provided for @relationshipsEndpointFile.
  ///
  /// In en, this message translates to:
  /// **'File'**
  String get relationshipsEndpointFile;

  /// No description provided for @relationshipsEndpointItem.
  ///
  /// In en, this message translates to:
  /// **'Item'**
  String get relationshipsEndpointItem;

  /// No description provided for @relationshipsAskRelated.
  ///
  /// In en, this message translates to:
  /// **'What is related to \"{label}\"?'**
  String relationshipsAskRelated(String label);

  /// No description provided for @settingsTitle.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get settingsTitle;

  /// No description provided for @settingsSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Manage your vault storage and subscription plan.'**
  String get settingsSubtitle;

  /// No description provided for @settingsLanguage.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get settingsLanguage;

  /// No description provided for @settingsLanguageHint.
  ///
  /// In en, this message translates to:
  /// **'Choose how VaultAI talks to you. Affects this app\'s labels and AI chat replies.'**
  String get settingsLanguageHint;

  /// No description provided for @settingsLanguageAuto.
  ///
  /// In en, this message translates to:
  /// **'Auto (system)'**
  String get settingsLanguageAuto;

  /// No description provided for @settingsLanguageEnglish.
  ///
  /// In en, this message translates to:
  /// **'English'**
  String get settingsLanguageEnglish;

  /// No description provided for @settingsLanguageArabic.
  ///
  /// In en, this message translates to:
  /// **'العربية'**
  String get settingsLanguageArabic;

  /// No description provided for @settingsLanguageFrench.
  ///
  /// In en, this message translates to:
  /// **'Français'**
  String get settingsLanguageFrench;

  /// No description provided for @settingsLanguageSpanish.
  ///
  /// In en, this message translates to:
  /// **'Español'**
  String get settingsLanguageSpanish;

  /// No description provided for @settingsLanguageJapanese.
  ///
  /// In en, this message translates to:
  /// **'日本語'**
  String get settingsLanguageJapanese;

  /// No description provided for @settingsLanguageKorean.
  ///
  /// In en, this message translates to:
  /// **'한국어'**
  String get settingsLanguageKorean;

  /// No description provided for @settingsLanguageChinese.
  ///
  /// In en, this message translates to:
  /// **'中文'**
  String get settingsLanguageChinese;

  /// No description provided for @settingsLanguageSearchHint.
  ///
  /// In en, this message translates to:
  /// **'Search languages (e.g. \"Français\", \"French\")'**
  String get settingsLanguageSearchHint;

  /// No description provided for @settingsLanguageAutoResolvedTo.
  ///
  /// In en, this message translates to:
  /// **'System: {label}'**
  String settingsLanguageAutoResolvedTo(String label);

  /// No description provided for @settingsLanguageSelected.
  ///
  /// In en, this message translates to:
  /// **'Selected'**
  String get settingsLanguageSelected;

  /// No description provided for @settingsLanguagePartialNotice.
  ///
  /// In en, this message translates to:
  /// **'VaultAI Chat will reply in {name}. The app interface is still shown in English while translation is in progress.'**
  String settingsLanguagePartialNotice(String name);

  /// No description provided for @settingsLanguagePopular.
  ///
  /// In en, this message translates to:
  /// **'Popular'**
  String get settingsLanguagePopular;

  /// No description provided for @settingsLanguageAllLanguages.
  ///
  /// In en, this message translates to:
  /// **'All languages'**
  String get settingsLanguageAllLanguages;

  /// No description provided for @settingsLanguageShowAll.
  ///
  /// In en, this message translates to:
  /// **'Show all languages ({count} more)'**
  String settingsLanguageShowAll(int count);

  /// No description provided for @settingsLanguageShowFewer.
  ///
  /// In en, this message translates to:
  /// **'Show fewer'**
  String get settingsLanguageShowFewer;

  /// No description provided for @settingsLanguageNoMatches.
  ///
  /// In en, this message translates to:
  /// **'No languages match \"{query}\"'**
  String settingsLanguageNoMatches(String query);

  /// No description provided for @settingsCurrentPlan.
  ///
  /// In en, this message translates to:
  /// **'Current plan'**
  String get settingsCurrentPlan;

  /// No description provided for @settingsLoadingPlan.
  ///
  /// In en, this message translates to:
  /// **'Loading plan…'**
  String get settingsLoadingPlan;

  /// No description provided for @settingsBuyMoreStorage.
  ///
  /// In en, this message translates to:
  /// **'Buy More Storage'**
  String get settingsBuyMoreStorage;

  /// No description provided for @settingsManageSubscription.
  ///
  /// In en, this message translates to:
  /// **'Manage Subscription'**
  String get settingsManageSubscription;

  /// No description provided for @settingsDeleteVaultTile.
  ///
  /// In en, this message translates to:
  /// **'Delete vault'**
  String get settingsDeleteVaultTile;

  /// No description provided for @settingsDeleteVaultTileHint.
  ///
  /// In en, this message translates to:
  /// **'Permanently deletes your vault. Requires confirmation phrase and PIN.'**
  String get settingsDeleteVaultTileHint;

  /// No description provided for @securityCenterTitle.
  ///
  /// In en, this message translates to:
  /// **'Security Center'**
  String get securityCenterTitle;

  /// No description provided for @devicesTitle.
  ///
  /// In en, this message translates to:
  /// **'Devices'**
  String get devicesTitle;

  /// No description provided for @filesTitle.
  ///
  /// In en, this message translates to:
  /// **'Files'**
  String get filesTitle;

  /// No description provided for @loginsTitle.
  ///
  /// In en, this message translates to:
  /// **'Logins'**
  String get loginsTitle;

  /// No description provided for @inheritanceTitle.
  ///
  /// In en, this message translates to:
  /// **'Inheritance'**
  String get inheritanceTitle;

  /// No description provided for @dashboardTitle.
  ///
  /// In en, this message translates to:
  /// **'Dashboard'**
  String get dashboardTitle;

  /// No description provided for @priorityHigh.
  ///
  /// In en, this message translates to:
  /// **'HIGH'**
  String get priorityHigh;

  /// No description provided for @priorityMedium.
  ///
  /// In en, this message translates to:
  /// **'MEDIUM'**
  String get priorityMedium;

  /// No description provided for @priorityLow.
  ///
  /// In en, this message translates to:
  /// **'LOW'**
  String get priorityLow;

  /// No description provided for @helpCenterTitle.
  ///
  /// In en, this message translates to:
  /// **'Help & FAQ'**
  String get helpCenterTitle;

  /// No description provided for @helpCenterSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Answers to common questions about VaultAI. Search below or browse by category — the AI assistant answers from the same set of topics.'**
  String get helpCenterSubtitle;

  /// No description provided for @helpCenterEmpty.
  ///
  /// In en, this message translates to:
  /// **'No matching help topics'**
  String get helpCenterEmpty;

  /// No description provided for @helpCenterEmptyBody.
  ///
  /// In en, this message translates to:
  /// **'Try a different search term, or pick a category chip.'**
  String get helpCenterEmptyBody;

  /// No description provided for @helpCenterSupportNote.
  ///
  /// In en, this message translates to:
  /// **'Live customer support is not available yet. Use this Help Center or ask VaultAI Chat for help.'**
  String get helpCenterSupportNote;

  /// No description provided for @helpContactSupportTitle.
  ///
  /// In en, this message translates to:
  /// **'Contact Support'**
  String get helpContactSupportTitle;

  /// No description provided for @helpContactSupportBody.
  ///
  /// In en, this message translates to:
  /// **'Need help with VaultAI? Contact our support team.'**
  String get helpContactSupportBody;

  /// No description provided for @helpContactSupportEmailA11yLabel.
  ///
  /// In en, this message translates to:
  /// **'Email VaultAI support at {email}'**
  String helpContactSupportEmailA11yLabel(String email);

  /// No description provided for @helpContactSupportEmailOpenFailed.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t open your email app. Copy this address instead: {email}'**
  String helpContactSupportEmailOpenFailed(String email);

  /// No description provided for @helpContactSupportCopyEmailLabel.
  ///
  /// In en, this message translates to:
  /// **'Copy email address'**
  String get helpContactSupportCopyEmailLabel;

  /// No description provided for @helpContactSupportCopyEmailA11yLabel.
  ///
  /// In en, this message translates to:
  /// **'Copy VaultAI support email {email} to clipboard'**
  String helpContactSupportCopyEmailA11yLabel(String email);

  /// No description provided for @helpContactSupportEmailCopied.
  ///
  /// In en, this message translates to:
  /// **'Email copied to clipboard'**
  String get helpContactSupportEmailCopied;

  /// No description provided for @helpCenterPublicHint.
  ///
  /// In en, this message translates to:
  /// **'You\'re viewing the public Help Center. Sign in to ask VaultAI and see account details.'**
  String get helpCenterPublicHint;

  /// No description provided for @helpCenterSearchHint.
  ///
  /// In en, this message translates to:
  /// **'Search help topics (e.g. \"monero\", \"PIN\")'**
  String get helpCenterSearchHint;

  /// No description provided for @helpCenterClearSearch.
  ///
  /// In en, this message translates to:
  /// **'Clear search'**
  String get helpCenterClearSearch;

  /// No description provided for @helpCenterSignInToAsk.
  ///
  /// In en, this message translates to:
  /// **'Sign in to ask VaultAI'**
  String get helpCenterSignInToAsk;

  /// No description provided for @helpCategoryGettingStarted.
  ///
  /// In en, this message translates to:
  /// **'Getting started'**
  String get helpCategoryGettingStarted;

  /// No description provided for @helpCategorySecurity.
  ///
  /// In en, this message translates to:
  /// **'Security'**
  String get helpCategorySecurity;

  /// No description provided for @helpCategoryFiles.
  ///
  /// In en, this message translates to:
  /// **'Files'**
  String get helpCategoryFiles;

  /// No description provided for @helpCategorySecureItems.
  ///
  /// In en, this message translates to:
  /// **'Secure items'**
  String get helpCategorySecureItems;

  /// No description provided for @helpCategoryIds.
  ///
  /// In en, this message translates to:
  /// **'IDs'**
  String get helpCategoryIds;

  /// No description provided for @helpCategoryCrypto.
  ///
  /// In en, this message translates to:
  /// **'Crypto Vault'**
  String get helpCategoryCrypto;

  /// No description provided for @helpCategoryBilling.
  ///
  /// In en, this message translates to:
  /// **'Billing'**
  String get helpCategoryBilling;

  /// No description provided for @helpCategoryTroubleshooting.
  ///
  /// In en, this message translates to:
  /// **'Troubleshooting'**
  String get helpCategoryTroubleshooting;

  /// No description provided for @deleteVaultTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete vault permanently?'**
  String get deleteVaultTitle;

  /// No description provided for @deleteVaultBody.
  ///
  /// In en, this message translates to:
  /// **'Deleting your vault permanently deletes your VaultAI vault data, including files, secure items, logins, ID documents, Crypto Vault encrypted wallet records, and related vault metadata.'**
  String get deleteVaultBody;

  /// No description provided for @deleteVaultCryptoWarning.
  ///
  /// In en, this message translates to:
  /// **'Deleting your vault does not move or delete crypto assets on the blockchain. If you have not backed up your wallet outside VaultAI, deleting your encrypted wallet records may cause loss of access to those funds.'**
  String get deleteVaultCryptoWarning;

  /// No description provided for @deleteVaultPhraseInstruction.
  ///
  /// In en, this message translates to:
  /// **'Type the phrase DELETE MY VAULT exactly to confirm:'**
  String get deleteVaultPhraseInstruction;

  /// No description provided for @deleteVaultPhraseMustMatch.
  ///
  /// In en, this message translates to:
  /// **'Phrase must match exactly.'**
  String get deleteVaultPhraseMustMatch;

  /// No description provided for @deleteVaultPinInstruction.
  ///
  /// In en, this message translates to:
  /// **'Enter your PIN to confirm:'**
  String get deleteVaultPinInstruction;

  /// No description provided for @deleteVaultPinHint.
  ///
  /// In en, this message translates to:
  /// **'PIN'**
  String get deleteVaultPinHint;

  /// No description provided for @deleteVaultConfirmButton.
  ///
  /// In en, this message translates to:
  /// **'Delete vault'**
  String get deleteVaultConfirmButton;

  /// No description provided for @deleteVaultErrorInvalidPin.
  ///
  /// In en, this message translates to:
  /// **'PIN is incorrect.'**
  String get deleteVaultErrorInvalidPin;

  /// No description provided for @deleteVaultErrorInvalidPhrase.
  ///
  /// In en, this message translates to:
  /// **'Type the exact phrase to confirm.'**
  String get deleteVaultErrorInvalidPhrase;

  /// No description provided for @deleteVaultErrorExpired.
  ///
  /// In en, this message translates to:
  /// **'Delete request expired. Try again.'**
  String get deleteVaultErrorExpired;

  /// No description provided for @deleteVaultErrorNotTrusted.
  ///
  /// In en, this message translates to:
  /// **'This device is not trusted. Approve it first.'**
  String get deleteVaultErrorNotTrusted;

  /// No description provided for @deleteVaultErrorGeneric.
  ///
  /// In en, this message translates to:
  /// **'Deletion could not be completed.'**
  String get deleteVaultErrorGeneric;

  /// No description provided for @errorRateLimited.
  ///
  /// In en, this message translates to:
  /// **'Too many attempts. Please wait a few minutes and try again.'**
  String get errorRateLimited;

  /// No description provided for @errorRateLimitedPin.
  ///
  /// In en, this message translates to:
  /// **'Too many wrong PIN attempts. Try again later.'**
  String get errorRateLimitedPin;

  /// No description provided for @errorRateLimitedWait.
  ///
  /// In en, this message translates to:
  /// **'Too many attempts. Wait {seconds}s'**
  String errorRateLimitedWait(int seconds);

  /// No description provided for @errorSessionExpired.
  ///
  /// In en, this message translates to:
  /// **'Session expired. Sign in again.'**
  String get errorSessionExpired;

  /// No description provided for @errorInactivityLocked.
  ///
  /// In en, this message translates to:
  /// **'Vault locked due to inactivity.'**
  String get errorInactivityLocked;

  /// No description provided for @errorVaultFrozen.
  ///
  /// In en, this message translates to:
  /// **'This vault has been frozen.'**
  String get errorVaultFrozen;

  /// No description provided for @errorDeviceNotTrusted.
  ///
  /// In en, this message translates to:
  /// **'This device is not trusted. Approve it first.'**
  String get errorDeviceNotTrusted;

  /// No description provided for @errorGenericPrefix.
  ///
  /// In en, this message translates to:
  /// **'Something went wrong.'**
  String get errorGenericPrefix;

  /// No description provided for @errorNetwork.
  ///
  /// In en, this message translates to:
  /// **'Network error. Check your connection and try again.'**
  String get errorNetwork;

  /// No description provided for @errorRefreshFailed.
  ///
  /// In en, this message translates to:
  /// **'Refresh failed. Try again.'**
  String get errorRefreshFailed;

  /// No description provided for @snackDeviceApproved.
  ///
  /// In en, this message translates to:
  /// **'Device approved.'**
  String get snackDeviceApproved;

  /// No description provided for @snackDeviceRevoked.
  ///
  /// In en, this message translates to:
  /// **'Device revoked.'**
  String get snackDeviceRevoked;

  /// No description provided for @snackDeviceApproveFailed.
  ///
  /// In en, this message translates to:
  /// **'Approve failed: {error}'**
  String snackDeviceApproveFailed(String error);

  /// No description provided for @snackDeviceRevokeFailed.
  ///
  /// In en, this message translates to:
  /// **'Revoke failed: {error}'**
  String snackDeviceRevokeFailed(String error);

  /// No description provided for @snackAddressCopied.
  ///
  /// In en, this message translates to:
  /// **'Address copied'**
  String get snackAddressCopied;

  /// No description provided for @snackSendCooldown.
  ///
  /// In en, this message translates to:
  /// **'Too many recent send attempts. Wait a moment and try again.'**
  String get snackSendCooldown;

  /// No description provided for @storagePageTitle.
  ///
  /// In en, this message translates to:
  /// **'Storage'**
  String get storagePageTitle;

  /// No description provided for @storageNoDataAvailable.
  ///
  /// In en, this message translates to:
  /// **'No storage data available.'**
  String get storageNoDataAvailable;

  /// No description provided for @storageUsageHeading.
  ///
  /// In en, this message translates to:
  /// **'Storage Usage'**
  String get storageUsageHeading;

  /// No description provided for @storageAccountHeading.
  ///
  /// In en, this message translates to:
  /// **'Account'**
  String get storageAccountHeading;

  /// No description provided for @storageFreeTier.
  ///
  /// In en, this message translates to:
  /// **'Free Tier'**
  String get storageFreeTier;

  /// No description provided for @storageNeedMoreSpace.
  ///
  /// In en, this message translates to:
  /// **'Need more space?'**
  String get storageNeedMoreSpace;

  /// No description provided for @storageGrandfathered.
  ///
  /// In en, this message translates to:
  /// **'Grandfathered storage'**
  String get storageGrandfathered;

  /// No description provided for @storageAdditionalPricing.
  ///
  /// In en, this message translates to:
  /// **'Additional storage pricing'**
  String get storageAdditionalPricing;

  /// No description provided for @storagePlanLower.
  ///
  /// In en, this message translates to:
  /// **'Lower plan'**
  String get storagePlanLower;

  /// No description provided for @storageCouldNotLoad.
  ///
  /// In en, this message translates to:
  /// **'Could not load storage'**
  String get storageCouldNotLoad;

  /// No description provided for @storageRefreshNow.
  ///
  /// In en, this message translates to:
  /// **'Refresh now'**
  String get storageRefreshNow;

  /// No description provided for @securityManageDevices.
  ///
  /// In en, this message translates to:
  /// **'Manage devices'**
  String get securityManageDevices;

  /// No description provided for @securityAnalyzePasswordsTitle.
  ///
  /// In en, this message translates to:
  /// **'Analyze passwords?'**
  String get securityAnalyzePasswordsTitle;

  /// No description provided for @securityEnterVaultPin.
  ///
  /// In en, this message translates to:
  /// **'Enter vault PIN'**
  String get securityEnterVaultPin;

  /// No description provided for @securityAnalyzeButton.
  ///
  /// In en, this message translates to:
  /// **'Analyze'**
  String get securityAnalyzeButton;

  /// No description provided for @securityAnalyzeMore.
  ///
  /// In en, this message translates to:
  /// **'Analyze more'**
  String get securityAnalyzeMore;

  /// No description provided for @devicePendingRequestSelfApproval.
  ///
  /// In en, this message translates to:
  /// **'Request self-approval'**
  String get devicePendingRequestSelfApproval;

  /// No description provided for @devicePendingFinalize.
  ///
  /// In en, this message translates to:
  /// **'Finalize'**
  String get devicePendingFinalize;

  /// No description provided for @devicePendingCancelApproval.
  ///
  /// In en, this message translates to:
  /// **'Cancel approval'**
  String get devicePendingCancelApproval;

  /// No description provided for @devicePendingCheckAgain.
  ///
  /// In en, this message translates to:
  /// **'Check again'**
  String get devicePendingCheckAgain;

  /// No description provided for @devicePendingRegisterDevice.
  ///
  /// In en, this message translates to:
  /// **'Register this device'**
  String get devicePendingRegisterDevice;

  /// No description provided for @devicePendingDiagnoseTrust.
  ///
  /// In en, this message translates to:
  /// **'Diagnose trust'**
  String get devicePendingDiagnoseTrust;

  /// No description provided for @devicePendingCopyDiagnostics.
  ///
  /// In en, this message translates to:
  /// **'Copy diagnostics'**
  String get devicePendingCopyDiagnostics;

  /// No description provided for @devicePendingDiagnosticsCopied.
  ///
  /// In en, this message translates to:
  /// **'Diagnostics copied to clipboard.'**
  String get devicePendingDiagnosticsCopied;

  /// No description provided for @cryptoLiteCouldNotLoadRecord.
  ///
  /// In en, this message translates to:
  /// **'Could not load record detail. Try again.'**
  String get cryptoLiteCouldNotLoadRecord;

  /// No description provided for @cryptoLiteAddressFormatMismatchTitle.
  ///
  /// In en, this message translates to:
  /// **'Address format does not match'**
  String get cryptoLiteAddressFormatMismatchTitle;

  /// No description provided for @cryptoLiteSaveAnyway.
  ///
  /// In en, this message translates to:
  /// **'Save anyway'**
  String get cryptoLiteSaveAnyway;

  /// No description provided for @cryptoLiteEditMetadata.
  ///
  /// In en, this message translates to:
  /// **'Edit metadata'**
  String get cryptoLiteEditMetadata;

  /// No description provided for @cryptoLiteEditBackupMetadata.
  ///
  /// In en, this message translates to:
  /// **'Edit backup metadata'**
  String get cryptoLiteEditBackupMetadata;

  /// No description provided for @cryptoOpenAsset.
  ///
  /// In en, this message translates to:
  /// **'Open asset'**
  String get cryptoOpenAsset;

  /// No description provided for @cryptoMoneroScannerStatus.
  ///
  /// In en, this message translates to:
  /// **'Monero scanner status'**
  String get cryptoMoneroScannerStatus;

  /// No description provided for @cryptoOpenMonero.
  ///
  /// In en, this message translates to:
  /// **'Open Monero'**
  String get cryptoOpenMonero;

  /// No description provided for @cryptoSendDraftHeading.
  ///
  /// In en, this message translates to:
  /// **'Send draft'**
  String get cryptoSendDraftHeading;

  /// No description provided for @cryptoOpenSendFlow.
  ///
  /// In en, this message translates to:
  /// **'Open send flow'**
  String get cryptoOpenSendFlow;

  /// No description provided for @cryptoRetryFailed.
  ///
  /// In en, this message translates to:
  /// **'Retry failed'**
  String get cryptoRetryFailed;

  /// No description provided for @cryptoOpenCryptoVault.
  ///
  /// In en, this message translates to:
  /// **'Open Crypto Vault'**
  String get cryptoOpenCryptoVault;

  /// No description provided for @cryptoCopyAddress.
  ///
  /// In en, this message translates to:
  /// **'Copy address'**
  String get cryptoCopyAddress;

  /// No description provided for @cryptoTransactionsTab.
  ///
  /// In en, this message translates to:
  /// **'Transactions'**
  String get cryptoTransactionsTab;

  /// No description provided for @cryptoContinueToPin.
  ///
  /// In en, this message translates to:
  /// **'Continue to PIN'**
  String get cryptoContinueToPin;

  /// No description provided for @cryptoCopyDestination.
  ///
  /// In en, this message translates to:
  /// **'Copy destination'**
  String get cryptoCopyDestination;

  /// No description provided for @cryptoSignatureCopied.
  ///
  /// In en, this message translates to:
  /// **'Signature copied to clipboard'**
  String get cryptoSignatureCopied;

  /// No description provided for @cryptoCopySignature.
  ///
  /// In en, this message translates to:
  /// **'Copy signature'**
  String get cryptoCopySignature;

  /// No description provided for @cryptoTxIdCopied.
  ///
  /// In en, this message translates to:
  /// **'Transaction id copied to clipboard'**
  String get cryptoTxIdCopied;

  /// No description provided for @cryptoCopyTxId.
  ///
  /// In en, this message translates to:
  /// **'Copy txID'**
  String get cryptoCopyTxId;

  /// No description provided for @vaultCardOverview.
  ///
  /// In en, this message translates to:
  /// **'Vault overview'**
  String get vaultCardOverview;

  /// No description provided for @vaultCardOpenVault.
  ///
  /// In en, this message translates to:
  /// **'Open vault'**
  String get vaultCardOpenVault;

  /// No description provided for @vaultCardDocumentSummary.
  ///
  /// In en, this message translates to:
  /// **'Document summary'**
  String get vaultCardDocumentSummary;

  /// No description provided for @vaultCardGeneratedLogins.
  ///
  /// In en, this message translates to:
  /// **'Generated logins'**
  String get vaultCardGeneratedLogins;

  /// No description provided for @vaultCardBilling.
  ///
  /// In en, this message translates to:
  /// **'Billing'**
  String get vaultCardBilling;

  /// No description provided for @vaultCardBrowseAllHelp.
  ///
  /// In en, this message translates to:
  /// **'Browse all help topics'**
  String get vaultCardBrowseAllHelp;

  /// No description provided for @secureItemCopyUsername.
  ///
  /// In en, this message translates to:
  /// **'Copy username'**
  String get secureItemCopyUsername;

  /// No description provided for @secureItemCopyValue.
  ///
  /// In en, this message translates to:
  /// **'Copy value'**
  String get secureItemCopyValue;

  /// No description provided for @notificationsTitle.
  ///
  /// In en, this message translates to:
  /// **'Notifications'**
  String get notificationsTitle;

  /// No description provided for @notificationsMarkAllRead.
  ///
  /// In en, this message translates to:
  /// **'Mark all read'**
  String get notificationsMarkAllRead;

  /// No description provided for @landingHowItWorks.
  ///
  /// In en, this message translates to:
  /// **'How it works'**
  String get landingHowItWorks;

  /// No description provided for @authDontHaveVault.
  ///
  /// In en, this message translates to:
  /// **'Don\'t have a vault? Create one'**
  String get authDontHaveVault;

  /// No description provided for @authAlreadyHaveVault.
  ///
  /// In en, this message translates to:
  /// **'Already have a vault? Sign in'**
  String get authAlreadyHaveVault;

  /// No description provided for @authUseAnotherVault.
  ///
  /// In en, this message translates to:
  /// **'Use another vault'**
  String get authUseAnotherVault;

  /// No description provided for @authLogInAnotherVault.
  ///
  /// In en, this message translates to:
  /// **'Log in to another vault'**
  String get authLogInAnotherVault;

  /// No description provided for @snackDeviceTrusted.
  ///
  /// In en, this message translates to:
  /// **'New device trusted.'**
  String get snackDeviceTrusted;

  /// No description provided for @confirmEraseTitle.
  ///
  /// In en, this message translates to:
  /// **'Erase unrecoverable data?'**
  String get confirmEraseTitle;

  /// No description provided for @confirmEraseButton.
  ///
  /// In en, this message translates to:
  /// **'Erase and continue'**
  String get confirmEraseButton;

  /// No description provided for @inheritanceCancelPendingTransferTitle.
  ///
  /// In en, this message translates to:
  /// **'Cancel pending transfer to \"{label}\"?'**
  String inheritanceCancelPendingTransferTitle(String label);

  /// No description provided for @inheritanceCancelTransfer.
  ///
  /// In en, this message translates to:
  /// **'Cancel transfer'**
  String get inheritanceCancelTransfer;

  /// No description provided for @inheritanceClaimTitle.
  ///
  /// In en, this message translates to:
  /// **'Claim \"{label}\"'**
  String inheritanceClaimTitle(String label);

  /// No description provided for @inheritanceRequestTransferTitle.
  ///
  /// In en, this message translates to:
  /// **'Request transfer of \"{label}\"?'**
  String inheritanceRequestTransferTitle(String label);

  /// No description provided for @inheritanceRemoveTitle.
  ///
  /// In en, this message translates to:
  /// **'Remove \"{label}\"?'**
  String inheritanceRemoveTitle(String label);

  /// No description provided for @inheritanceStartCountdown.
  ///
  /// In en, this message translates to:
  /// **'Start 30-day countdown'**
  String get inheritanceStartCountdown;

  /// No description provided for @inheritanceAddBeneficiary.
  ///
  /// In en, this message translates to:
  /// **'Add beneficiary'**
  String get inheritanceAddBeneficiary;

  /// No description provided for @inheritanceEnterCode.
  ///
  /// In en, this message translates to:
  /// **'Enter code'**
  String get inheritanceEnterCode;

  /// No description provided for @inheritanceRequestTransfer.
  ///
  /// In en, this message translates to:
  /// **'Request transfer'**
  String get inheritanceRequestTransfer;

  /// No description provided for @filesChooseStorage.
  ///
  /// In en, this message translates to:
  /// **'Choose Storage'**
  String get filesChooseStorage;

  /// No description provided for @filesUploadFile.
  ///
  /// In en, this message translates to:
  /// **'Upload file'**
  String get filesUploadFile;

  /// No description provided for @filesUploadPhoto.
  ///
  /// In en, this message translates to:
  /// **'Upload photo'**
  String get filesUploadPhoto;

  /// No description provided for @filesUploadVideo.
  ///
  /// In en, this message translates to:
  /// **'Upload video'**
  String get filesUploadVideo;

  /// No description provided for @filesUploadAudio.
  ///
  /// In en, this message translates to:
  /// **'Upload audio'**
  String get filesUploadAudio;

  /// No description provided for @filesUploadFolder.
  ///
  /// In en, this message translates to:
  /// **'Upload folder'**
  String get filesUploadFolder;

  /// No description provided for @filesRecordVoice.
  ///
  /// In en, this message translates to:
  /// **'Record voice'**
  String get filesRecordVoice;

  /// No description provided for @filesRecordVideo.
  ///
  /// In en, this message translates to:
  /// **'Record video'**
  String get filesRecordVideo;

  /// No description provided for @deleteVaultSignInRequired.
  ///
  /// In en, this message translates to:
  /// **'Please sign in again to delete your vault.'**
  String get deleteVaultSignInRequired;

  /// No description provided for @deleteVaultSuccess.
  ///
  /// In en, this message translates to:
  /// **'Your vault has been deleted.'**
  String get deleteVaultSuccess;

  /// No description provided for @dashboardActiveVault.
  ///
  /// In en, this message translates to:
  /// **'Active vault:'**
  String get dashboardActiveVault;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) => <String>[
        'ar',
        'en',
        'es',
        'fr',
        'ja',
        'ko',
        'zh'
      ].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'ar':
      return AppLocalizationsAr();
    case 'en':
      return AppLocalizationsEn();
    case 'es':
      return AppLocalizationsEs();
    case 'fr':
      return AppLocalizationsFr();
    case 'ja':
      return AppLocalizationsJa();
    case 'ko':
      return AppLocalizationsKo();
    case 'zh':
      return AppLocalizationsZh();
  }

  throw FlutterError(
      'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
      'an issue with the localizations generation tool. Please file an issue '
      'on GitHub with a reproducible sample app and the gen-l10n configuration '
      'that was used.');
}
