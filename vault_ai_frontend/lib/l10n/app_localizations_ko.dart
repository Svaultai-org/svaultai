// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Korean (`ko`).
class AppLocalizationsKo extends AppLocalizations {
  AppLocalizationsKo([String locale = 'ko']) : super(locale);

  @override
  String get appTitle => 'VaultAI';

  @override
  String get commonRetry => '다시 시도';

  @override
  String get commonRefresh => '새로고침';

  @override
  String get commonOpen => '열기';

  @override
  String get commonCancel => '취소';

  @override
  String get commonSave => '저장';

  @override
  String get commonSignOut => '로그아웃';

  @override
  String get commonLoading => '불러오는 중...';

  @override
  String get commonAll => '전체';

  @override
  String get commonView => '보기';

  @override
  String get commonDownload => '다운로드';

  @override
  String get commonAskVaultAI => 'VaultAI 에게 묻기';

  @override
  String get commonClose => '닫기';

  @override
  String get commonDelete => '삭제';

  @override
  String get commonConfirm => '확인';

  @override
  String get commonSignIn => '로그인';

  @override
  String get commonSignUp => '가입';

  @override
  String get commonSearch => '검색';

  @override
  String get commonBack => '뒤로';

  @override
  String get commonNext => '다음';

  @override
  String get commonYes => '예';

  @override
  String get commonNo => '아니오';

  @override
  String get commonError => '오류';

  @override
  String get commonSuccess => '성공';

  @override
  String get commonUnavailable => '사용 불가';

  @override
  String get commonTryAgain => '다시 시도';

  @override
  String get commonContinue => '계속';

  @override
  String get commonApprove => '승인';

  @override
  String get commonReject => '거부';

  @override
  String get commonRevoke => '취소';

  @override
  String get commonReceive => '받기';

  @override
  String get commonReview => '검토';

  @override
  String get commonAnalyze => '분석';

  @override
  String get commonCopy => '복사';

  @override
  String get commonEdit => '편집';

  @override
  String get commonCurrent => '현재';

  @override
  String get commonCopyCode => '코드 복사';

  @override
  String get commonRemove => '제거';

  @override
  String get commonNotYet => '아직 아니오';

  @override
  String get sidebarDashboard => '대시보드';

  @override
  String get sidebarChat => '채팅';

  @override
  String get sidebarFiles => '파일';

  @override
  String get sidebarLogins => '로그인';

  @override
  String get sidebarCryptoVault => 'Crypto Vault';

  @override
  String get sidebarConcierge => '컨시어지';

  @override
  String get sidebarExpiry => '만료';

  @override
  String get sidebarMemory => '메모리';

  @override
  String get sidebarRelationships => '관계';


  @override
  String get sidebarSettings => '설정';

  @override
  String get chatComposerHint => '보관소에 대해 묻거나 파일을 업로드하세요...';

  @override
  String get chatThinking => 'VaultAI 가 생각 중입니다...';

  @override
  String chatThinkingWithName(String name) {
    return '$name 가 생각 중입니다...';
  }

  @override
  String get chatSendButton => '보내기';

  @override
  String get chatSending => '전송 중...';

  @override
  String chatAskAbout(String topic) {
    return '내 $topic 에 대해 더 알려줘';
  }

  @override
  String get chatErrorGeneric => 'VaultAI 가 지금 답할 수 없습니다. 다시 시도하세요.';

  @override
  String get chatRetryButton => '다시 시도';

  @override
  String get chatQuickSavedLogins => '저장된 로그인';

  @override
  String get chatQuickMyFiles => '내 파일';

  @override
  String get chatQuickMyPassport => '내 여권';

  @override
  String get chatQuickWhatCanYouDo => '무엇을 할 수 있나요?';

  @override
  String get chatCardShowRelated => '관련 보기';

  @override
  String get chatCardTopFolders => '주요 폴더';

  @override
  String get chatCardRecentFiles => '최근 파일';

  @override
  String get chatCardSearchDeeper => '깊이 검색';

  @override
  String get chatCardKeepBoth => '둘 다 유지';

  @override
  String get chatCardUpgradeStorage => '저장소 업그레이드';

  @override
  String get unlockToSeeConcierge => '컨시어지 대시보드를 보려면 보관소를 잠금 해제하세요.';

  @override
  String get unlockToSeeExpiry => '만료 타임라인을 보려면 보관소를 잠금 해제하세요.';

  @override
  String get unlockToSeeMemory => '메모리 타임라인을 보려면 보관소를 잠금 해제하세요.';

  @override
  String get unlockToSeeRelationships => '관계 그래프를 보려면 보관소를 잠금 해제하세요.';

  @override
  String get conciergeTitle => '컨시어지';

  @override
  String get conciergeSubtitle => 'VaultAI 가 우선 살펴보길 권하는 항목';

  @override
  String get conciergeLoading => '정보를 모으는 중...';

  @override
  String get conciergeErrorPrefix => '컨시어지 데이터를 불러올 수 없습니다.';

  @override
  String get conciergeCriticalNow => '지금 긴급';

  @override
  String get conciergeComingUp => '곧 다가옴';

  @override
  String get conciergeRecommendations => '추천 항목';

  @override
  String get conciergeTravelReady => '여행 준비 완료';

  @override
  String get conciergeTravelMostly => '거의 준비됨';

  @override
  String get conciergeTravelAttention => '확인 필요';

  @override
  String get conciergeTravelReadyDetail => '여권 > 180일, 비자 > 30일.';

  @override
  String get conciergeTravelMostlyDetail => '여권 또는 비자가 없거나 갱신이 임박했습니다.';

  @override
  String get conciergeTravelAttentionDetail => '갱신이 곧 필요합니다 - 여권과 비자를 확인하세요.';

  @override
  String get conciergeRenewalTimeline => '갱신 타임라인(향후 90일)';

  @override
  String get conciergeTravelReadiness => '여행 준비';

  @override
  String get conciergeAllClear => '모두 이상 없습니다.';

  @override
  String get conciergeAllClearSub =>
      '오늘 급한 일은 없습니다. VaultAI 가 문서를 지켜보며 새로운 사항이 생기면 여기 표시합니다.';

  @override
  String get conciergePostureSecurity => '보안';

  @override
  String get conciergePostureExpiring => '만료';


  @override
  String get conciergePostureScoreHint => '눌러서 보안 센터 보기';

  @override
  String get conciergePostureNoData => '데이터 없음';

  @override
  String get conciergePostureNothingTracked => '아직 추적 중인 항목 없음';

  @override
  String get conciergePostureAllFuture => '모두 여유가 있음';




  @override
  String get conciergePostureScoreNoData => '데이터 없음';

  @override
  String get conciergeAskTravel => '여행 준비가 되었나요?';

  @override
  String get conciergePassport => '여권';

  @override
  String get conciergeVisa => '비자';

  @override
  String get conciergePassportNotOnFile => '등록되지 않음';

  @override
  String get conciergeNoExpiryDate => '만료일 없음';

  @override
  String get conciergeExpired => '만료됨';

  @override
  String get conciergeRenewSoon => '곧 갱신';

  @override
  String get conciergeComfortable => '여유 있음';

  @override
  String get conciergeItem => '건';

  @override
  String get conciergeItems => '건';




  @override
  String get expiryTitle => '만료';

  @override
  String get expirySubtitle => '곧 만료되는 문서 및 의무';

  @override
  String get expiryLoading => '만료 알림을 불러오는 중...';

  @override
  String get expiryErrorPrefix => '만료 알림을 불러올 수 없습니다.';

  @override
  String get expiryEmptyTitle => '모든 갱신을 미리 챙기고 있습니다.';

  @override
  String get expiryEmptySub =>
      '여권, 비자, 보험 증서, 계약서를 업로드하면 VaultAI 가 자동으로 만료일을 추적합니다.';

  @override
  String get expiryNoneInWindow => '이 기간에는 아무것도 없습니다.';

  @override
  String expiryNoneInWindowSub(String window) {
    return '$window 이내에 만료되는 문서가 없습니다. 더 긴 기간을 시도해 보세요.';
  }

  @override
  String get expiryWindow7d => '7일';

  @override
  String get expiryWindow30d => '30일';

  @override
  String get expiryWindow90d => '90일';

  @override
  String get expiryWindowAll => '전체';

  @override
  String get expiryBucketCritical => '긴급';

  @override
  String get expiryBucketWarning => '경고';

  @override
  String get expiryBucketInfo => '안내';

  @override
  String expiryCountCritical(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '긴급 $count건',
    );
    return '$_temp0';
  }

  @override
  String expiryCountWarning(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '경고 $count건',
    );
    return '$_temp0';
  }

  @override
  String expiryDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days일',
    );
    return '$_temp0';
  }

  @override
  String get expiryToday => '오늘';

  @override
  String expiredAgo(int days) {
    return '$days일 전';
  }

  @override
  String get expiryNoDate => '날짜 없음';

  @override
  String get expiryDays => '남음';

  @override
  String get expiryDaysExpires => '만료';

  @override
  String get memoryTitle => '메모리';

  @override
  String get memorySubtitle => 'VaultAI 가 당신에 대해 기억하는 것의 타임라인';

  @override
  String get memoryLoading => '기억을 불러오는 중...';

  @override
  String get memoryErrorPrefix => '메모리 타임라인을 불러올 수 없습니다.';

  @override
  String get memoryEmptyTitle => '아직 기억이 없습니다.';

  @override
  String get memoryEmptySub =>
      'VaultAI 에게 기억할 것을 알려주세요: \'엄마 생일이 2월 14일임을 기억해\'. 종류와 날짜로 그룹화되어 여기에 표시됩니다.';

  @override
  String get memoryNoMatchTitle => '일치하는 항목이 없습니다.';

  @override
  String get memoryNoMatchSub => '필터나 검색을 지워서 모든 기억을 보세요.';

  @override
  String get memorySearchHint => '기억 검색...';

  @override
  String get memoryUndated => '날짜 없음';

  @override
  String get memoryUnnamed => '(이름 없음)';

  @override
  String get memoryTypeIdentity => '신원';

  @override
  String get memoryTypePeople => '사람';

  @override
  String get memoryTypeFamily => '가족';

  @override
  String get memoryTypeBusiness => '비즈니스';

  @override
  String get memoryTypeTravel => '여행';

  @override
  String get memoryTypeProjects => '프로젝트';

  @override
  String get memoryTypeGoals => '목표';

  @override
  String get memoryTypePlaces => '장소';

  @override
  String get memoryTypeDates => '날짜';

  @override
  String get memoryTypeLifeEvent => '인생 이벤트';

  @override
  String get memoryTypePreferences => '선호';

  @override
  String get memoryTypeNote => '메모';

  @override
  String memoryAskAbout(String key) {
    return '$key 에 대해 기억하는 것은?';
  }

  @override
  String get relationshipsTitle => '관계';

  @override
  String get relationshipsSubtitle => '함께 속하는 문서·계정·기억';

  @override
  String get relationshipsLoading => '보관소를 매핑하는 중...';

  @override
  String get relationshipsErrorPrefix => '관계를 불러올 수 없습니다.';

  @override
  String get relationshipsEmptyTitle => '아직 클러스터가 없습니다.';

  @override
  String get relationshipsEmptySub =>
      '여권, 비자, 청구서, 계약서를 업로드하면 VaultAI 가 여행·신원·세금·가족 등으로 문서를 그룹화합니다.';

  @override
  String get relationshipsNoMatchTitle => '일치하는 항목이 없습니다.';

  @override
  String get relationshipsNoMatchSub => '필터나 검색을 지워 보세요.';

  @override
  String get relationshipsSearchHint => '문서·항목·관계 검색...';

  @override
  String get relationshipsTypeTravel => '여행 클러스터';

  @override
  String get relationshipsTypeIdentity => '신원 클러스터';

  @override
  String get relationshipsTypeBusiness => '비즈니스 클러스터';

  @override
  String get relationshipsTypeFinance => '금융 클러스터';

  @override
  String get relationshipsTypeTax => '세금 클러스터';

  @override
  String get relationshipsTypeMedical => '의료 클러스터';

  @override
  String get relationshipsTypeFamily => '가족 클러스터';

  @override
  String get relationshipsTypeSecurity => '보안 클러스터';

  @override
  String get relationshipsTypeMedia => '미디어 클러스터';

  @override
  String get relationshipsTypeInheritance => '상속 클러스터';

  @override
  String get relationshipsEndpointFile => '파일';

  @override
  String get relationshipsEndpointItem => '항목';

  @override
  String relationshipsAskRelated(String label) {
    return '\"$label\" 와 관련된 것은?';
  }

  @override
  String get settingsTitle => '설정';

  @override
  String get settingsSubtitle => '보관소 저장 공간과 구독 플랜을 관리합니다.';

  @override
  String get settingsLanguage => '언어';

  @override
  String get settingsLanguageHint =>
      'VaultAI 가 사용할 언어를 선택하세요. 앱 레이블과 AI 채팅 응답에 영향을 줍니다.';

  @override
  String get settingsLanguageAuto => '자동(시스템)';

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
      '언어 검색 (예: \"Français\", \"French\")';

  @override
  String settingsLanguageAutoResolvedTo(String label) {
    return '시스템: $label';
  }

  @override
  String get settingsLanguageSelected => '선택됨';

  @override
  String settingsLanguagePartialNotice(String name) {
    return 'VaultAI Chat 은 $name 로 응답합니다. 번역이 완료될 때까지 앱 인터페이스는 영어로 표시됩니다.';
  }

  @override
  String get settingsLanguagePopular => '주요 언어';

  @override
  String get settingsLanguageAllLanguages => '모든 언어';

  @override
  String settingsLanguageShowAll(int count) {
    return '모든 언어 표시 ($count개 더)';
  }

  @override
  String get settingsLanguageShowFewer => '간단히 보기';

  @override
  String settingsLanguageNoMatches(String query) {
    return '「$query」와 일치하는 언어가 없습니다';
  }

  @override
  String get settingsCurrentPlan => '현재 플랜';

  @override
  String get settingsLoadingPlan => '플랜 로딩 중…';

  @override
  String get settingsBuyMoreStorage => '저장 공간 구매';

  @override
  String get settingsManageSubscription => '구독 관리';

  @override
  String get settingsDeleteVaultTile => '보관소 삭제';

  @override
  String get settingsDeleteVaultTileHint =>
      '보관소를 영구 삭제합니다. 확인 문구와 PIN 이 필요합니다.';

  @override
  String get securityCenterTitle => '보안 센터';

  @override
  String get devicesTitle => '장치';

  @override
  String get filesTitle => '파일';

  @override
  String get loginsTitle => '로그인';


  @override
  String get dashboardTitle => '대시보드';

  @override
  String get priorityHigh => '높음';

  @override
  String get priorityMedium => '보통';

  @override
  String get priorityLow => '낮음';

  @override
  String get helpCenterTitle => '도움말 및 FAQ';

  @override
  String get helpCenterSubtitle =>
      'VaultAI 에 관한 자주 묻는 질문에 대한 답변입니다. 아래에서 검색하거나 카테고리별로 살펴보세요 — AI 어시스턴트도 동일한 주제에서 답합니다.';

  @override
  String get helpCenterEmpty => '일치하는 도움말이 없습니다';

  @override
  String get helpCenterEmptyBody => '다른 검색어를 시도하거나 카테고리를 선택하세요.';

  @override
  String get helpCenterSupportNote =>
      '실시간 고객 지원은 아직 제공되지 않습니다. 이 도움말 센터를 사용하거나 VaultAI Chat 에 질문하세요.';

  @override
  String get helpContactSupportTitle => '지원팀에 문의';

  @override
  String get helpContactSupportBody =>
      'VaultAI 에 도움이 필요하신가요? 지원팀에 문의하세요.';

  @override
  String helpContactSupportEmailA11yLabel(String email) {
    return '$email 로 VaultAI 지원팀에 이메일 보내기';
  }

  @override
  String helpContactSupportEmailOpenFailed(String email) {
    return '이메일 앱을 열 수 없습니다. 대신 이 주소를 복사하세요: $email';
  }

  @override
  String get helpContactSupportCopyEmailLabel => '이메일 주소 복사';

  @override
  String helpContactSupportCopyEmailA11yLabel(String email) {
    return 'VaultAI 지원 이메일 $email 을(를) 클립보드에 복사';
  }

  @override
  String get helpContactSupportEmailCopied => '이메일이 클립보드에 복사되었습니다';

  @override
  String get helpCenterPublicHint =>
      '공개 도움말 센터를 보고 있습니다. VaultAI 에 질문하고 계정 세부 정보를 보려면 로그인하세요.';

  @override
  String get helpCenterSearchHint => '도움말 검색 (예: \"monero\", \"PIN\")';

  @override
  String get helpCenterClearSearch => '검색 지우기';

  @override
  String get helpCenterSignInToAsk => '로그인하여 VaultAI 에게 질문';

  @override
  String get helpCategoryGettingStarted => '시작하기';

  @override
  String get helpCategorySecurity => '보안';

  @override
  String get helpCategoryFiles => '파일';

  @override
  String get helpCategorySecureItems => '보안 항목';

  @override
  String get helpCategoryIds => '신분증';

  @override
  String get helpCategoryCrypto => 'Crypto Vault';

  @override
  String get helpCategoryBilling => '결제';

  @override
  String get helpCategoryTroubleshooting => '문제 해결';

  @override
  String get deleteVaultTitle => '보관소를 영구 삭제하시겠습니까?';

  @override
  String get deleteVaultBody =>
      '보관소를 삭제하면 파일, 보안 항목, 로그인, 신분증, Crypto Vault 암호화된 지갑 기록, 관련 메타데이터를 포함한 VaultAI 데이터가 영구적으로 삭제됩니다.';

  @override
  String get deleteVaultCryptoWarning =>
      '보관소를 삭제해도 블록체인상의 암호 자산은 이동하거나 삭제되지 않습니다. VaultAI 외부에 지갑을 백업하지 않았다면, 암호화된 지갑 기록의 삭제로 해당 자금에 대한 접근을 잃을 수 있습니다.';

  @override
  String get deleteVaultPhraseInstruction =>
      '확인하려면 문구 DELETE MY VAULT 를 정확히 입력하세요:';

  @override
  String get deleteVaultPhraseMustMatch => '문구가 정확히 일치해야 합니다.';

  @override
  String get deleteVaultPinInstruction => '확인을 위해 PIN 을 입력하세요:';

  @override
  String get deleteVaultPinHint => 'PIN';

  @override
  String get deleteVaultConfirmButton => '보관소 삭제';

  @override
  String get deleteVaultErrorInvalidPin => 'PIN 이 올바르지 않습니다.';

  @override
  String get deleteVaultErrorInvalidPhrase => '확인하려면 정확한 문구를 입력하세요.';

  @override
  String get deleteVaultErrorExpired => '삭제 요청이 만료되었습니다. 다시 시도하세요.';

  @override
  String get deleteVaultErrorNotTrusted => '이 기기는 신뢰되지 않습니다. 먼저 승인하세요.';

  @override
  String get deleteVaultErrorGeneric => '삭제를 완료할 수 없습니다.';

  @override
  String get errorRateLimited => '시도가 너무 많습니다. 몇 분 기다린 후 다시 시도하세요.';

  @override
  String get errorRateLimitedPin => '잘못된 PIN 시도가 너무 많습니다. 나중에 다시 시도하세요.';

  @override
  String errorRateLimitedWait(int seconds) {
    return '시도가 너무 많습니다. $seconds초 기다리세요';
  }

  @override
  String get errorSessionExpired => '세션이 만료되었습니다. 다시 로그인하세요.';

  @override
  String get errorInactivityLocked => '비활성으로 인해 보관소가 잠겼습니다.';

  @override
  String get errorVaultFrozen => '이 보관소는 동결되었습니다.';

  @override
  String get errorDeviceNotTrusted => '이 기기는 신뢰되지 않습니다. 먼저 승인하세요.';

  @override
  String get errorGenericPrefix => '문제가 발생했습니다.';

  @override
  String get errorNetwork => '네트워크 오류. 연결을 확인하고 다시 시도하세요.';

  @override
  String get errorRefreshFailed => '새로고침 실패. 다시 시도하세요.';

  @override
  String get snackDeviceApproved => '기기가 승인되었습니다.';

  @override
  String get snackDeviceRevoked => '기기가 취소되었습니다.';

  @override
  String snackDeviceApproveFailed(String error) {
    return '승인 실패: $error';
  }

  @override
  String snackDeviceRevokeFailed(String error) {
    return '취소 실패: $error';
  }

  @override
  String get snackAddressCopied => '주소가 복사되었습니다';

  @override
  String get snackSendCooldown => '최근 전송 시도가 너무 많습니다. 잠시 기다리세요.';

  @override
  String get storagePageTitle => '저장 공간';

  @override
  String get storageNoDataAvailable => '저장 데이터가 없습니다.';

  @override
  String get storageUsageHeading => '저장 사용량';

  @override
  String get storageAccountHeading => '계정';

  @override
  String get storageFreeTier => '무료 등급';

  @override
  String get storageNeedMoreSpace => '더 많은 공간이 필요하신가요?';

  @override
  String get storageGrandfathered => '이월 저장 공간';

  @override
  String get storageAdditionalPricing => '추가 저장 요금';

  @override
  String get storagePlanLower => '하위 플랜';

  @override
  String get storageCouldNotLoad => '저장 정보를 불러올 수 없습니다';

  @override
  String get storageRefreshNow => '새로고침';

  @override
  String get securityManageDevices => '기기 관리';

  @override
  String get securityAnalyzePasswordsTitle => '비밀번호를 분석할까요?';

  @override
  String get securityEnterVaultPin => '보관소 PIN 을 입력하세요';

  @override
  String get securityAnalyzeButton => '분석';

  @override
  String get securityAnalyzeMore => '더 분석';

  @override
  String get devicePendingRequestSelfApproval => '자체 승인 요청';

  @override
  String get devicePendingFinalize => '완료';

  @override
  String get devicePendingCancelApproval => '승인 취소';

  @override
  String get devicePendingCheckAgain => '다시 확인';

  @override
  String get devicePendingRegisterDevice => '이 기기 등록';

  @override
  String get devicePendingDiagnoseTrust => '신뢰 진단';

  @override
  String get devicePendingCopyDiagnostics => '진단 정보 복사';

  @override
  String get devicePendingDiagnosticsCopied => '진단 정보가 복사되었습니다.';

  @override
  String get cryptoLiteCouldNotLoadRecord => '기록 세부 정보를 불러올 수 없습니다. 다시 시도하세요.';

  @override
  String get cryptoLiteAddressFormatMismatchTitle => '주소 형식이 일치하지 않습니다';

  @override
  String get cryptoLiteSaveAnyway => '그래도 저장';

  @override
  String get cryptoLiteEditMetadata => '메타데이터 편집';

  @override
  String get cryptoLiteEditBackupMetadata => '백업 메타데이터 편집';

  @override
  String get cryptoOpenAsset => '자산 열기';

  @override
  String get cryptoMoneroScannerStatus => 'Monero 스캐너 상태';

  @override
  String get cryptoOpenMonero => 'Monero 열기';

  @override
  String get cryptoSendDraftHeading => '송금 초안';

  @override
  String get cryptoOpenSendFlow => '송금 열기';

  @override
  String get cryptoRetryFailed => '다시 시도';

  @override
  String get cryptoOpenCryptoVault => 'Crypto Vault 열기';

  @override
  String get cryptoCopyAddress => '주소 복사';

  @override
  String get cryptoTransactionsTab => '거래 내역';

  @override
  String get cryptoContinueToPin => 'PIN 으로 계속';

  @override
  String get cryptoCopyDestination => '수신처 복사';

  @override
  String get cryptoSignatureCopied => '서명이 복사되었습니다';

  @override
  String get cryptoCopySignature => '서명 복사';

  @override
  String get cryptoTxIdCopied => '거래 ID 가 복사되었습니다';

  @override
  String get cryptoCopyTxId => '거래 ID 복사';

  @override
  String get vaultCardOverview => '보관소 개요';

  @override
  String get vaultCardOpenVault => '보관소 열기';

  @override
  String get vaultCardDocumentSummary => '문서 요약';

  @override
  String get vaultCardGeneratedLogins => '생성된 로그인';

  @override
  String get vaultCardBilling => '결제';

  @override
  String get vaultCardBrowseAllHelp => '모든 도움말 주제 보기';

  @override
  String get secureItemCopyUsername => '사용자명 복사';

  @override
  String get secureItemCopyValue => '값 복사';

  @override
  String get notificationsTitle => '알림';

  @override
  String get notificationsMarkAllRead => '모두 읽음으로 표시';

  @override
  String get landingHowItWorks => '작동 방식';

  @override
  String get authDontHaveVault => '보관소가 없으신가요? 만들기';

  @override
  String get authAlreadyHaveVault => '이미 보관소가 있으신가요? 로그인';

  @override
  String get authUseAnotherVault => '다른 보관소 사용';

  @override
  String get authLogInAnotherVault => '다른 보관소에 로그인';

  @override
  String get snackDeviceTrusted => '새 기기를 신뢰합니다.';

  @override
  String get confirmEraseTitle => '복구 불가능한 데이터를 지울까요?';

  @override
  String get confirmEraseButton => '지우고 계속';










  @override
  String get filesChooseStorage => '업로드 원본 선택';

  @override
  String get filesUploadFile => '파일 업로드';

  @override
  String get filesUploadPhoto => '사진 업로드';

  @override
  String get filesUploadVideo => '동영상 업로드';

  @override
  String get filesUploadAudio => '오디오 업로드';

  @override
  String get filesUploadFolder => '폴더 업로드';

  @override
  String get filesRecordVoice => '음성 녹음';

  @override
  String get filesRecordVideo => '동영상 녹화';

  @override
  String get deleteVaultSignInRequired => '보관소를 삭제하려면 다시 로그인하세요.';

  @override
  String get deleteVaultSuccess => '보관소가 삭제되었습니다.';

  @override
  String get dashboardActiveVault => '활성 보관소:';
}
