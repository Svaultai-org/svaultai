// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Arabic (`ar`).
class AppLocalizationsAr extends AppLocalizations {
  AppLocalizationsAr([String locale = 'ar']) : super(locale);

  @override
  String get appTitle => 'VaultAI';

  @override
  String get commonRetry => 'إعادة المحاولة';

  @override
  String get commonRefresh => 'تحديث';

  @override
  String get commonOpen => 'فتح';

  @override
  String get commonCancel => 'إلغاء';

  @override
  String get commonSave => 'حفظ';

  @override
  String get commonSignOut => 'تسجيل الخروج';

  @override
  String get commonLoading => 'جارٍ التحميل...';

  @override
  String get commonAll => 'الكل';

  @override
  String get commonView => 'عرض';

  @override
  String get commonDownload => 'تنزيل';

  @override
  String get commonAskVaultAI => 'اسأل VaultAI';

  @override
  String get commonClose => 'إغلاق';

  @override
  String get commonDelete => 'حذف';

  @override
  String get commonConfirm => 'تأكيد';

  @override
  String get commonSignIn => 'تسجيل الدخول';

  @override
  String get commonSignUp => 'إنشاء حساب';

  @override
  String get commonSearch => 'بحث';

  @override
  String get commonBack => 'رجوع';

  @override
  String get commonNext => 'التالي';

  @override
  String get commonYes => 'نعم';

  @override
  String get commonNo => 'لا';

  @override
  String get commonError => 'خطأ';

  @override
  String get commonSuccess => 'تم';

  @override
  String get commonUnavailable => 'غير متاح';

  @override
  String get commonTryAgain => 'حاول مرة أخرى';

  @override
  String get commonContinue => 'متابعة';

  @override
  String get commonApprove => 'موافقة';

  @override
  String get commonReject => 'رفض';

  @override
  String get commonRevoke => 'إلغاء الوصول';

  @override
  String get commonReceive => 'استلام';

  @override
  String get commonReview => 'مراجعة';

  @override
  String get commonAnalyze => 'تحليل';

  @override
  String get commonCopy => 'نسخ';

  @override
  String get commonEdit => 'تعديل';

  @override
  String get commonCurrent => 'الحالي';

  @override
  String get commonCopyCode => 'نسخ الرمز';

  @override
  String get commonRemove => 'إزالة';

  @override
  String get commonNotYet => 'ليس بعد';

  @override
  String get sidebarDashboard => 'لوحة التحكم';

  @override
  String get sidebarChat => 'المحادثة';

  @override
  String get sidebarFiles => 'الملفات';

  @override
  String get sidebarLogins => 'تسجيلات الدخول';

  @override
  String get sidebarCryptoVault => 'Crypto Vault';

  @override
  String get sidebarConcierge => 'المساعد الذكي';

  @override
  String get sidebarExpiry => 'تواريخ الانتهاء';

  @override
  String get sidebarMemory => 'الذاكرة';

  @override
  String get sidebarRelationships => 'العلاقات';


  @override
  String get sidebarSettings => 'الإعدادات';

  @override
  String get chatComposerHint => 'اسأل عن خزينتك أو ارفع ملفًا...';

  @override
  String get chatThinking => 'VaultAI يفكر...';

  @override
  String chatThinkingWithName(String name) {
    return '$name يفكر...';
  }

  @override
  String get chatSendButton => 'إرسال';

  @override
  String get chatSending => 'جارٍ الإرسال...';

  @override
  String chatAskAbout(String topic) {
    return 'أخبرني المزيد عن $topic';
  }

  @override
  String get chatErrorGeneric => 'تعذّر على VaultAI الرد الآن. حاول مرة أخرى.';

  @override
  String get chatRetryButton => 'إعادة المحاولة';

  @override
  String get chatQuickSavedLogins => 'تسجيلات الدخول المحفوظة';

  @override
  String get chatQuickMyFiles => 'ملفاتي';

  @override
  String get chatQuickMyPassport => 'جواز سفري';

  @override
  String get chatQuickWhatCanYouDo => 'ماذا يمكنك أن تفعل؟';

  @override
  String get chatCardShowRelated => 'عرض المرتبطات';

  @override
  String get chatCardTopFolders => 'المجلدات الأبرز';

  @override
  String get chatCardRecentFiles => 'الملفات الأخيرة';

  @override
  String get chatCardSearchDeeper => 'بحث أعمق';

  @override
  String get chatCardKeepBoth => 'احتفظ بكليهما';

  @override
  String get chatCardUpgradeStorage => 'ترقية التخزين';

  @override
  String get unlockToSeeConcierge => 'افتح خزينة لعرض لوحة المساعد.';

  @override
  String get unlockToSeeExpiry =>
      'افتح خزينة لعرض الجدول الزمني لانتهاء الصلاحية.';

  @override
  String get unlockToSeeMemory => 'افتح خزينة لعرض الجدول الزمني للذاكرة.';

  @override
  String get unlockToSeeRelationships => 'افتح خزينة لعرض شبكة العلاقات.';

  @override
  String get conciergeTitle => 'المساعد الذكي';

  @override
  String get conciergeSubtitle => 'ما يقترحه VaultAI أن تنظر إليه الآن';

  @override
  String get conciergeLoading => 'جارٍ جمع المعلومات...';

  @override
  String get conciergeErrorPrefix => 'تعذّر تحميل بيانات المساعد.';

  @override
  String get conciergeCriticalNow => 'حالات حرجة الآن';

  @override
  String get conciergeComingUp => 'قادم قريبًا';

  @override
  String get conciergeRecommendations => 'التوصيات';

  @override
  String get conciergeTravelReady => 'جاهز للسفر';

  @override
  String get conciergeTravelMostly => 'جاهز إلى حد كبير';

  @override
  String get conciergeTravelAttention => 'يحتاج إلى انتباه';

  @override
  String get conciergeTravelReadyDetail =>
      'جواز السفر > 180 يومًا، التأشيرة > 30 يومًا.';

  @override
  String get conciergeTravelMostlyDetail =>
      'أحد جواز السفر أو التأشيرة مفقود أو قريب من التجديد.';

  @override
  String get conciergeTravelAttentionDetail =>
      'يلزم التجديد قريبًا - راجع جواز السفر والتأشيرة.';

  @override
  String get conciergeRenewalTimeline =>
      'الجدول الزمني للتجديد (90 يومًا القادمة)';

  @override
  String get conciergeTravelReadiness => 'جاهزية السفر';

  @override
  String get conciergeAllClear => 'كل شيء على ما يرام.';

  @override
  String get conciergeAllClearSub =>
      'لا شيء عاجل اليوم. VaultAI يراقب مستنداتك وسيظهر أي جديد هنا.';

  @override
  String get conciergePostureSecurity => 'الأمان';

  @override
  String get conciergePostureExpiring => 'ينتهي';


  @override
  String get conciergePostureScoreHint => 'اضغط لعرض مركز الأمان';

  @override
  String get conciergePostureNoData => 'لا توجد بيانات';

  @override
  String get conciergePostureNothingTracked => 'لا شيء يُتابع بعد';

  @override
  String get conciergePostureAllFuture => 'كل شيء بعيد بصورة مريحة';




  @override
  String get conciergePostureScoreNoData => 'لا توجد بيانات';

  @override
  String get conciergeAskTravel => 'هل أنا جاهز للسفر؟';

  @override
  String get conciergePassport => 'جواز السفر';

  @override
  String get conciergeVisa => 'التأشيرة';

  @override
  String get conciergePassportNotOnFile => 'غير موجود';

  @override
  String get conciergeNoExpiryDate => 'لا يوجد تاريخ انتهاء';

  @override
  String get conciergeExpired => 'منتهي';

  @override
  String get conciergeRenewSoon => 'جدّد قريبًا';

  @override
  String get conciergeComfortable => 'مريح';

  @override
  String get conciergeItem => 'عنصر';

  @override
  String get conciergeItems => 'عناصر';




  @override
  String get expiryTitle => 'تواريخ الانتهاء';

  @override
  String get expirySubtitle =>
      'المستندات والالتزامات التي تنتهي صلاحيتها قريبًا';

  @override
  String get expiryLoading => 'جارٍ قراءة تنبيهات الانتهاء...';

  @override
  String get expiryErrorPrefix => 'تعذّر تحميل تنبيهات الانتهاء.';

  @override
  String get expiryEmptyTitle => 'أنت متقدّم على كل تجديد.';

  @override
  String get expiryEmptySub =>
      'ارفع جواز سفر، تأشيرة، بوليصة تأمين، أو عقدًا وسيتتبع VaultAI تاريخ انتهائها تلقائيًا.';

  @override
  String get expiryNoneInWindow => 'لا شيء في هذه الفترة.';

  @override
  String expiryNoneInWindowSub(String window) {
    return 'لا تنتهي مستندات خلال $window. جرّب فترة أطول.';
  }

  @override
  String get expiryWindow7d => '7 أيام';

  @override
  String get expiryWindow30d => '30 يومًا';

  @override
  String get expiryWindow90d => '90 يومًا';

  @override
  String get expiryWindowAll => 'الكل';

  @override
  String get expiryBucketCritical => 'حرج';

  @override
  String get expiryBucketWarning => 'تحذير';

  @override
  String get expiryBucketInfo => 'تنبيه';

  @override
  String expiryCountCritical(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count حالة حرجة',
      one: 'حالة حرجة واحدة',
    );
    return '$_temp0';
  }

  @override
  String expiryCountWarning(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count تحذير',
      one: 'تحذير واحد',
    );
    return '$_temp0';
  }

  @override
  String expiryDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days ي',
      one: '١ ي',
    );
    return '$_temp0';
  }

  @override
  String get expiryToday => 'اليوم';

  @override
  String expiredAgo(int days) {
    return 'منذ $days ي';
  }

  @override
  String get expiryNoDate => 'بدون تاريخ';

  @override
  String get expiryDays => 'متبقّ';

  @override
  String get expiryDaysExpires => 'ينتهي';

  @override
  String get memoryTitle => 'الذاكرة';

  @override
  String get memorySubtitle => 'جدول زمني لما يتذكّره VaultAI عن حياتك';

  @override
  String get memoryLoading => 'جارٍ تحميل ذكرياتك...';

  @override
  String get memoryErrorPrefix => 'تعذّر تحميل الجدول الزمني للذاكرة.';

  @override
  String get memoryEmptyTitle => 'لا توجد ذكريات بعد.';

  @override
  String get memoryEmptySub =>
      'أخبر VaultAI بأشياء ليتذكّرها: \'تذكّر أن عيد ميلاد أمي 14 فبراير\'. ستظهر هنا مجمّعة حسب النوع والتاريخ.';

  @override
  String get memoryNoMatchTitle => 'لا توجد نتائج.';

  @override
  String get memoryNoMatchSub => 'جرّب مسح الفلتر أو البحث لعرض كل الذكريات.';

  @override
  String get memorySearchHint => 'ابحث في الذكريات...';

  @override
  String get memoryUndated => 'بدون تاريخ';

  @override
  String get memoryUnnamed => '(بدون اسم)';

  @override
  String get memoryTypeIdentity => 'الهوية';

  @override
  String get memoryTypePeople => 'الأشخاص';

  @override
  String get memoryTypeFamily => 'العائلة';

  @override
  String get memoryTypeBusiness => 'الأعمال';

  @override
  String get memoryTypeTravel => 'السفر';

  @override
  String get memoryTypeProjects => 'المشاريع';

  @override
  String get memoryTypeGoals => 'الأهداف';

  @override
  String get memoryTypePlaces => 'الأماكن';

  @override
  String get memoryTypeDates => 'التواريخ';

  @override
  String get memoryTypeLifeEvent => 'أحداث الحياة';

  @override
  String get memoryTypePreferences => 'التفضيلات';

  @override
  String get memoryTypeNote => 'ملاحظات';

  @override
  String memoryAskAbout(String key) {
    return 'ماذا تتذكر عن $key؟';
  }

  @override
  String get relationshipsTitle => 'العلاقات';

  @override
  String get relationshipsSubtitle =>
      'المستندات والحسابات والذكريات التي تنتمي معًا';

  @override
  String get relationshipsLoading => 'جارٍ رسم خريطة خزينتك...';

  @override
  String get relationshipsErrorPrefix => 'تعذّر تحميل العلاقات.';

  @override
  String get relationshipsEmptyTitle => 'لا توجد مجموعات بعد.';

  @override
  String get relationshipsEmptySub =>
      'ارفع جواز سفر، تأشيرة، فاتورة، أو عقدًا وسيبدأ VaultAI بتجميع المستندات التي تنتمي معًا حسب السفر والهوية والضرائب والعائلة وغيرها.';

  @override
  String get relationshipsNoMatchTitle => 'لا توجد نتائج.';

  @override
  String get relationshipsNoMatchSub => 'جرّب مسح الفلتر أو البحث.';

  @override
  String get relationshipsSearchHint =>
      'ابحث في المستندات أو العناصر أو العلاقات...';

  @override
  String get relationshipsTypeTravel => 'مجموعة السفر';

  @override
  String get relationshipsTypeIdentity => 'مجموعة الهوية';

  @override
  String get relationshipsTypeBusiness => 'مجموعة الأعمال';

  @override
  String get relationshipsTypeFinance => 'مجموعة المالية';

  @override
  String get relationshipsTypeTax => 'مجموعة الضرائب';

  @override
  String get relationshipsTypeMedical => 'مجموعة طبية';

  @override
  String get relationshipsTypeFamily => 'مجموعة العائلة';

  @override
  String get relationshipsTypeSecurity => 'مجموعة الأمان';

  @override
  String get relationshipsTypeMedia => 'مجموعة الوسائط';

  @override
  String get relationshipsTypeInheritance => 'مجموعة الميراث';

  @override
  String get relationshipsEndpointFile => 'ملف';

  @override
  String get relationshipsEndpointItem => 'عنصر';

  @override
  String relationshipsAskRelated(String label) {
    return 'ما المرتبط بـ \"$label\"؟';
  }

  @override
  String get settingsTitle => 'الإعدادات';

  @override
  String get settingsSubtitle => 'إدارة تخزين الخزينة وخطة الاشتراك.';

  @override
  String get settingsLanguage => 'اللغة';

  @override
  String get settingsLanguageHint =>
      'اختر كيف يخاطبك VaultAI. يؤثر على تسميات التطبيق وردود المحادثة.';

  @override
  String get settingsLanguageAuto => 'تلقائي (النظام)';

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
      'ابحث عن اللغة (مثل \"Français\", \"French\")';

  @override
  String settingsLanguageAutoResolvedTo(String label) {
    return 'النظام: $label';
  }

  @override
  String get settingsLanguageSelected => 'مختارة';

  @override
  String settingsLanguagePartialNotice(String name) {
    return 'سيرد VaultAI Chat بلغة $name. لا تزال واجهة التطبيق تعرض بالإنجليزية بينما يجري إتمام الترجمة.';
  }

  @override
  String get settingsLanguagePopular => 'الشائعة';

  @override
  String get settingsLanguageAllLanguages => 'جميع اللغات';

  @override
  String settingsLanguageShowAll(int count) {
    return 'عرض جميع اللغات ($count أخرى)';
  }

  @override
  String get settingsLanguageShowFewer => 'عرض أقل';

  @override
  String settingsLanguageNoMatches(String query) {
    return 'لا توجد لغات مطابقة لـ \"$query\"';
  }

  @override
  String get settingsCurrentPlan => 'الخطة الحالية';

  @override
  String get settingsLoadingPlan => 'جارٍ تحميل الخطة…';

  @override
  String get settingsBuyMoreStorage => 'شراء مساحة تخزين إضافية';

  @override
  String get settingsManageSubscription => 'إدارة الاشتراك';

  @override
  String get settingsDeleteVaultTile => 'حذف الخزينة';

  @override
  String get settingsDeleteVaultTileHint =>
      'يحذف خزينتك نهائيًا. يتطلب عبارة تأكيد ورمز PIN.';

  @override
  String get securityCenterTitle => 'مركز الأمان';

  @override
  String get devicesTitle => 'الأجهزة';

  @override
  String get filesTitle => 'الملفات';

  @override
  String get loginsTitle => 'تسجيلات الدخول';


  @override
  String get dashboardTitle => 'لوحة التحكم';

  @override
  String get priorityHigh => 'عالٍ';

  @override
  String get priorityMedium => 'متوسط';

  @override
  String get priorityLow => 'منخفض';

  @override
  String get helpCenterTitle => 'المساعدة والأسئلة الشائعة';

  @override
  String get helpCenterSubtitle =>
      'إجابات على الأسئلة الشائعة حول VaultAI. ابحث أدناه أو تصفّح حسب الفئة — يجيب المساعد الذكي من المجموعة نفسها.';

  @override
  String get helpCenterEmpty => 'لا توجد نتائج مطابقة';

  @override
  String get helpCenterEmptyBody =>
      'جرّب كلمة بحث مختلفة، أو اختر إحدى الفئات.';

  @override
  String get helpCenterSupportNote =>
      'الدعم البشري المباشر غير متاح بعد. استخدم مركز المساعدة أو اسأل VaultAI Chat.';

  @override
  String get helpContactSupportTitle => 'التواصل مع الدعم';

  @override
  String get helpContactSupportBody =>
      'هل تحتاج مساعدة في VaultAI؟ تواصل مع فريق الدعم.';

  @override
  String helpContactSupportEmailA11yLabel(String email) {
    return 'أرسل بريدًا إلى دعم VaultAI على $email';
  }

  @override
  String helpContactSupportEmailOpenFailed(String email) {
    return 'تعذّر فتح تطبيق البريد. انسخ هذا العنوان بدلًا من ذلك: $email';
  }

  @override
  String get helpContactSupportCopyEmailLabel => 'نسخ عنوان البريد';

  @override
  String helpContactSupportCopyEmailA11yLabel(String email) {
    return 'نسخ بريد دعم VaultAI $email إلى الحافظة';
  }

  @override
  String get helpContactSupportEmailCopied => 'تم نسخ البريد إلى الحافظة';

  @override
  String get helpCenterPublicHint =>
      'أنت في مركز المساعدة العام. سجّل الدخول لسؤال VaultAI ورؤية تفاصيل الحساب.';

  @override
  String get helpCenterSearchHint =>
      'ابحث في مواضيع المساعدة (مثل \"monero\", \"PIN\")';

  @override
  String get helpCenterClearSearch => 'مسح البحث';

  @override
  String get helpCenterSignInToAsk => 'سجّل الدخول لسؤال VaultAI';

  @override
  String get helpCategoryGettingStarted => 'البدء';

  @override
  String get helpCategorySecurity => 'الأمان';

  @override
  String get helpCategoryFiles => 'الملفات';

  @override
  String get helpCategorySecureItems => 'العناصر الآمنة';

  @override
  String get helpCategoryIds => 'الهويات';

  @override
  String get helpCategoryCrypto => 'Crypto Vault';

  @override
  String get helpCategoryBilling => 'الفوترة';

  @override
  String get helpCategoryTroubleshooting => 'استكشاف الأخطاء';

  @override
  String get deleteVaultTitle => 'حذف الخزينة نهائيًا؟';

  @override
  String get deleteVaultBody =>
      'سيحذف حذف الخزينة نهائيًا بيانات VaultAI الخاصة بك، بما في ذلك الملفات، والعناصر الآمنة، وتسجيلات الدخول، ومستندات الهوية، وسجلات محفظة Crypto Vault المشفّرة، والبيانات المرتبطة بالخزينة.';

  @override
  String get deleteVaultCryptoWarning =>
      'حذف خزينتك لا يُحرّك ولا يحذف أصول العملات المشفّرة على البلوكشين. إذا لم تحتفظ بنسخة احتياطية من محفظتك خارج VaultAI، فقد يؤدي حذف سجلات المحفظة المشفّرة إلى فقدان الوصول إلى تلك الأموال.';

  @override
  String get deleteVaultPhraseInstruction =>
      'اكتب عبارة DELETE MY VAULT كما هي للتأكيد:';

  @override
  String get deleteVaultPhraseMustMatch => 'يجب أن تطابق العبارة تمامًا.';

  @override
  String get deleteVaultPinInstruction => 'أدخل رمز PIN للتأكيد:';

  @override
  String get deleteVaultPinHint => 'PIN';

  @override
  String get deleteVaultConfirmButton => 'حذف الخزينة';

  @override
  String get deleteVaultErrorInvalidPin => 'رمز PIN غير صحيح.';

  @override
  String get deleteVaultErrorInvalidPhrase => 'اكتب العبارة كما هي للتأكيد.';

  @override
  String get deleteVaultErrorExpired =>
      'انتهت صلاحية طلب الحذف. حاول مرة أخرى.';

  @override
  String get deleteVaultErrorNotTrusted =>
      'هذا الجهاز غير موثوق. وافق عليه أولًا.';

  @override
  String get deleteVaultErrorGeneric => 'تعذّر إتمام الحذف.';

  @override
  String get errorRateLimited =>
      'محاولات كثيرة. انتظر بضع دقائق ثم حاول مرة أخرى.';

  @override
  String get errorRateLimitedPin => 'محاولات PIN خاطئة كثيرة. حاول لاحقًا.';

  @override
  String errorRateLimitedWait(int seconds) {
    return 'محاولات كثيرة. انتظر $seconds ثانية';
  }

  @override
  String get errorSessionExpired => 'انتهت الجلسة. سجّل الدخول مرة أخرى.';

  @override
  String get errorInactivityLocked => 'قُفلت الخزينة بسبب عدم النشاط.';

  @override
  String get errorVaultFrozen => 'هذه الخزينة مجمّدة.';

  @override
  String get errorDeviceNotTrusted => 'هذا الجهاز غير موثوق. وافق عليه أولًا.';

  @override
  String get errorGenericPrefix => 'حدث خطأ ما.';

  @override
  String get errorNetwork => 'خطأ في الشبكة. تحقق من الاتصال وحاول مرة أخرى.';

  @override
  String get errorRefreshFailed => 'فشل التحديث. حاول مرة أخرى.';

  @override
  String get snackDeviceApproved => 'تمت الموافقة على الجهاز.';

  @override
  String get snackDeviceRevoked => 'تم إلغاء الجهاز.';

  @override
  String snackDeviceApproveFailed(String error) {
    return 'فشلت الموافقة: $error';
  }

  @override
  String snackDeviceRevokeFailed(String error) {
    return 'فشل الإلغاء: $error';
  }

  @override
  String get snackAddressCopied => 'تم نسخ العنوان';

  @override
  String get snackSendCooldown =>
      'محاولات إرسال حديثة كثيرة. انتظر لحظة ثم حاول.';

  @override
  String get storagePageTitle => 'التخزين';

  @override
  String get storageNoDataAvailable => 'لا توجد بيانات تخزين.';

  @override
  String get storageUsageHeading => 'استخدام التخزين';

  @override
  String get storageAccountHeading => 'الحساب';

  @override
  String get storageFreeTier => 'الطبقة المجانية';

  @override
  String get storageNeedMoreSpace => 'تحتاج مساحة إضافية؟';

  @override
  String get storageGrandfathered => 'تخزين مُثبَّت';

  @override
  String get storageAdditionalPricing => 'أسعار التخزين الإضافي';

  @override
  String get storagePlanLower => 'خطة أقل';

  @override
  String get storageCouldNotLoad => 'تعذّر تحميل التخزين';

  @override
  String get storageRefreshNow => 'تحديث الآن';

  @override
  String get securityManageDevices => 'إدارة الأجهزة';

  @override
  String get securityAnalyzePasswordsTitle => 'تحليل كلمات المرور؟';

  @override
  String get securityEnterVaultPin => 'أدخل رمز PIN للخزينة';

  @override
  String get securityAnalyzeButton => 'تحليل';

  @override
  String get securityAnalyzeMore => 'تحليل المزيد';

  @override
  String get devicePendingRequestSelfApproval => 'طلب موافقة ذاتية';

  @override
  String get devicePendingFinalize => 'إنهاء';

  @override
  String get devicePendingCancelApproval => 'إلغاء الموافقة';

  @override
  String get devicePendingCheckAgain => 'تحقّق مرة أخرى';

  @override
  String get devicePendingRegisterDevice => 'تسجيل هذا الجهاز';

  @override
  String get devicePendingDiagnoseTrust => 'تشخيص الثقة';

  @override
  String get devicePendingCopyDiagnostics => 'نسخ التشخيصات';

  @override
  String get devicePendingDiagnosticsCopied => 'تم نسخ التشخيصات.';

  @override
  String get cryptoLiteCouldNotLoadRecord =>
      'تعذّر تحميل تفاصيل السجل. حاول مرة أخرى.';

  @override
  String get cryptoLiteAddressFormatMismatchTitle => 'تنسيق العنوان لا يتطابق';

  @override
  String get cryptoLiteSaveAnyway => 'احفظ على أي حال';

  @override
  String get cryptoLiteEditMetadata => 'تعديل البيانات الوصفية';

  @override
  String get cryptoLiteEditBackupMetadata => 'تعديل بيانات النسخة الاحتياطية';

  @override
  String get cryptoOpenAsset => 'فتح الأصل';

  @override
  String get cryptoMoneroScannerStatus => 'حالة ماسح Monero';

  @override
  String get cryptoOpenMonero => 'فتح Monero';

  @override
  String get cryptoSendDraftHeading => 'مسودة الإرسال';

  @override
  String get cryptoOpenSendFlow => 'فتح مسار الإرسال';

  @override
  String get cryptoRetryFailed => 'أعد المحاولة';

  @override
  String get cryptoOpenCryptoVault => 'فتح Crypto Vault';

  @override
  String get cryptoCopyAddress => 'نسخ العنوان';

  @override
  String get cryptoTransactionsTab => 'المعاملات';

  @override
  String get cryptoContinueToPin => 'متابعة إلى PIN';

  @override
  String get cryptoCopyDestination => 'نسخ الوجهة';

  @override
  String get cryptoSignatureCopied => 'تم نسخ التوقيع';

  @override
  String get cryptoCopySignature => 'نسخ التوقيع';

  @override
  String get cryptoTxIdCopied => 'تم نسخ معرّف المعاملة';

  @override
  String get cryptoCopyTxId => 'نسخ معرّف المعاملة';

  @override
  String get vaultCardOverview => 'نظرة عامة على الخزينة';

  @override
  String get vaultCardOpenVault => 'فتح الخزينة';

  @override
  String get vaultCardDocumentSummary => 'ملخّص المستند';

  @override
  String get vaultCardGeneratedLogins => 'تسجيلات الدخول المُولَّدة';

  @override
  String get vaultCardBilling => 'الفوترة';

  @override
  String get vaultCardBrowseAllHelp => 'تصفّح كل مواضيع المساعدة';

  @override
  String get secureItemCopyUsername => 'نسخ اسم المستخدم';

  @override
  String get secureItemCopyValue => 'نسخ القيمة';

  @override
  String get notificationsTitle => 'الإشعارات';

  @override
  String get notificationsMarkAllRead => 'وضع علامة مقروء على الكل';

  @override
  String get landingHowItWorks => 'كيف يعمل';

  @override
  String get authDontHaveVault => 'ليس لديك خزينة؟ أنشئ واحدة';

  @override
  String get authAlreadyHaveVault => 'لديك خزينة بالفعل؟ سجّل الدخول';

  @override
  String get authUseAnotherVault => 'استخدم خزينة أخرى';

  @override
  String get authLogInAnotherVault => 'تسجيل الدخول إلى خزينة أخرى';

  @override
  String get snackDeviceTrusted => 'تم توثيق الجهاز الجديد.';

  @override
  String get confirmEraseTitle => 'مسح بيانات لا يمكن استردادها؟';

  @override
  String get confirmEraseButton => 'امسح وتابع';










  @override
  String get filesChooseStorage => 'اختر مصدر الملف';

  @override
  String get filesUploadFile => 'رفع ملف';

  @override
  String get filesUploadPhoto => 'رفع صورة';

  @override
  String get filesUploadVideo => 'رفع فيديو';

  @override
  String get filesUploadAudio => 'رفع صوت';

  @override
  String get filesUploadFolder => 'رفع مجلد';

  @override
  String get filesRecordVoice => 'تسجيل صوت';

  @override
  String get filesRecordVideo => 'تسجيل فيديو';

  @override
  String get deleteVaultSignInRequired =>
      'الرجاء تسجيل الدخول مرة أخرى لحذف خزينتك.';

  @override
  String get deleteVaultSuccess => 'تم حذف خزينتك.';

  @override
  String get dashboardActiveVault => 'الخزينة النشطة:';
}
