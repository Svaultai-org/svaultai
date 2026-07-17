// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Chinese (`zh`).
class AppLocalizationsZh extends AppLocalizations {
  AppLocalizationsZh([String locale = 'zh']) : super(locale);

  @override
  String get appTitle => 'VaultAI';

  @override
  String get commonRetry => '重试';

  @override
  String get commonRefresh => '刷新';

  @override
  String get commonOpen => '打开';

  @override
  String get commonCancel => '取消';

  @override
  String get commonSave => '保存';

  @override
  String get commonSignOut => '退出登录';

  @override
  String get commonLoading => '加载中...';

  @override
  String get commonAll => '全部';

  @override
  String get commonView => '查看';

  @override
  String get commonDownload => '下载';

  @override
  String get commonAskVaultAI => '询问 VaultAI';

  @override
  String get commonClose => '关闭';

  @override
  String get commonDelete => '删除';

  @override
  String get commonConfirm => '确认';

  @override
  String get commonSignIn => '登录';

  @override
  String get commonSignUp => '注册';

  @override
  String get commonSearch => '搜索';

  @override
  String get commonBack => '返回';

  @override
  String get commonNext => '下一步';

  @override
  String get commonYes => '是';

  @override
  String get commonNo => '否';

  @override
  String get commonError => '错误';

  @override
  String get commonSuccess => '成功';

  @override
  String get commonUnavailable => '不可用';

  @override
  String get commonTryAgain => '重试';

  @override
  String get commonContinue => '继续';

  @override
  String get commonApprove => '批准';

  @override
  String get commonReject => '拒绝';

  @override
  String get commonRevoke => '撤销';

  @override
  String get commonReceive => '接收';

  @override
  String get commonReview => '查看';

  @override
  String get commonAnalyze => '分析';

  @override
  String get commonCopy => '复制';

  @override
  String get commonEdit => '编辑';

  @override
  String get commonCurrent => '当前';

  @override
  String get commonCopyCode => '复制代码';

  @override
  String get commonRemove => '移除';

  @override
  String get commonNotYet => '尚未';

  @override
  String get sidebarDashboard => '仪表板';

  @override
  String get sidebarChat => '聊天';

  @override
  String get sidebarFiles => '文件';

  @override
  String get sidebarLogins => '登录';

  @override
  String get sidebarCryptoVault => 'Crypto Vault';

  @override
  String get sidebarConcierge => '智能助理';

  @override
  String get sidebarExpiry => '到期';

  @override
  String get sidebarMemory => '记忆';

  @override
  String get sidebarRelationships => '关系';

  @override
  String get sidebarInheritance => '继承';

  @override
  String get sidebarSettings => '设置';

  @override
  String get chatComposerHint => '询问你的保险库或上传文件...';

  @override
  String get chatThinking => 'VaultAI 正在思考...';

  @override
  String chatThinkingWithName(String name) {
    return '$name 正在思考...';
  }

  @override
  String get chatSendButton => '发送';

  @override
  String get chatSending => '发送中...';

  @override
  String chatAskAbout(String topic) {
    return '告诉我更多关于我的$topic';
  }

  @override
  String get chatErrorGeneric => 'VaultAI 暂时无法回答。请重试。';

  @override
  String get chatRetryButton => '重试';

  @override
  String get chatQuickSavedLogins => '已保存的登录';

  @override
  String get chatQuickMyFiles => '我的文件';

  @override
  String get chatQuickMyPassport => '我的护照';

  @override
  String get chatQuickWhatCanYouDo => '你能做什么?';

  @override
  String get chatCardShowRelated => '查看相关';

  @override
  String get chatCardTopFolders => '主要文件夹';

  @override
  String get chatCardRecentFiles => '最近文件';

  @override
  String get chatCardSearchDeeper => '深入搜索';

  @override
  String get chatCardKeepBoth => '两者都保留';

  @override
  String get chatCardUpgradeStorage => '升级存储';

  @override
  String get unlockToSeeConcierge => '解锁保险库以查看智能助理。';

  @override
  String get unlockToSeeExpiry => '解锁保险库以查看到期时间线。';

  @override
  String get unlockToSeeMemory => '解锁保险库以查看记忆时间线。';

  @override
  String get unlockToSeeRelationships => '解锁保险库以查看关系图。';

  @override
  String get conciergeTitle => '智能助理';

  @override
  String get conciergeSubtitle => 'VaultAI 建议你先关注的内容';

  @override
  String get conciergeLoading => '正在收集信息...';

  @override
  String get conciergeErrorPrefix => '无法加载助理数据。';

  @override
  String get conciergeCriticalNow => '当前紧急';

  @override
  String get conciergeComingUp => '即将到来';

  @override
  String get conciergeRecommendations => '推荐';

  @override
  String get conciergeTravelReady => '可以出行';

  @override
  String get conciergeTravelMostly => '基本就绪';

  @override
  String get conciergeTravelAttention => '需要关注';

  @override
  String get conciergeTravelReadyDetail => '护照 > 180天,签证 > 30天。';

  @override
  String get conciergeTravelMostlyDetail => '护照或签证缺失或接近续签。';

  @override
  String get conciergeTravelAttentionDetail => '需要尽快续签 - 请检查护照和签证。';

  @override
  String get conciergeRenewalTimeline => '续签时间线(未来90天)';

  @override
  String get conciergeTravelReadiness => '出行准备';

  @override
  String get conciergeAllClear => '一切顺利。';

  @override
  String get conciergeAllClearSub => '今天没有紧急事项。VaultAI 会关注你的文件,有任何新情况会在此显示。';

  @override
  String get conciergePostureSecurity => '安全';

  @override
  String get conciergePostureExpiring => '即将到期';

  @override
  String get conciergePostureInheritance => '继承';

  @override
  String get conciergePostureScoreHint => '点击查看安全中心';

  @override
  String get conciergePostureNoData => '无数据';

  @override
  String get conciergePostureNothingTracked => '尚未追踪任何内容';

  @override
  String get conciergePostureAllFuture => '全部宽裕';

  @override
  String get conciergePostureFrozen => '保险库已冻结';

  @override
  String get conciergePostureConfigured => '已配置配对';

  @override
  String get conciergePostureUnset => '尚未设置受益人';

  @override
  String get conciergePostureScoreNoData => '无数据';

  @override
  String get conciergeAskTravel => '我可以出行吗?';

  @override
  String get conciergePassport => '护照';

  @override
  String get conciergeVisa => '签证';

  @override
  String get conciergePassportNotOnFile => '未登记';

  @override
  String get conciergeNoExpiryDate => '无到期日';

  @override
  String get conciergeExpired => '已过期';

  @override
  String get conciergeRenewSoon => '尽快续签';

  @override
  String get conciergeComfortable => '宽裕';

  @override
  String get conciergeItem => '项';

  @override
  String get conciergeItems => '项';

  @override
  String get conciergeInheritanceFrozen => '已冻结';

  @override
  String get conciergeInheritanceConfigured => '已配置';

  @override
  String get conciergeInheritanceUnset => '未设置';

  @override
  String get expiryTitle => '到期';

  @override
  String get expirySubtitle => '即将到期的文件和事项';

  @override
  String get expiryLoading => '正在读取到期提醒...';

  @override
  String get expiryErrorPrefix => '无法加载到期提醒。';

  @override
  String get expiryEmptyTitle => '你领先于每一次续签。';

  @override
  String get expiryEmptySub => '上传护照、签证、保单或合同,VaultAI 会自动追踪到期日。';

  @override
  String get expiryNoneInWindow => '此期间内没有内容。';

  @override
  String expiryNoneInWindowSub(String window) {
    return '$window 内没有文件到期。请尝试更长的时间范围。';
  }

  @override
  String get expiryWindow7d => '7天';

  @override
  String get expiryWindow30d => '30天';

  @override
  String get expiryWindow90d => '90天';

  @override
  String get expiryWindowAll => '全部';

  @override
  String get expiryBucketCritical => '紧急';

  @override
  String get expiryBucketWarning => '警告';

  @override
  String get expiryBucketInfo => '提示';

  @override
  String expiryCountCritical(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '紧急 $count 项',
    );
    return '$_temp0';
  }

  @override
  String expiryCountWarning(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '警告 $count 项',
    );
    return '$_temp0';
  }

  @override
  String expiryDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days天',
    );
    return '$_temp0';
  }

  @override
  String get expiryToday => '今天';

  @override
  String expiredAgo(int days) {
    return '$days天前';
  }

  @override
  String get expiryNoDate => '无日期';

  @override
  String get expiryDays => '剩余';

  @override
  String get expiryDaysExpires => '到期';

  @override
  String get memoryTitle => '记忆';

  @override
  String get memorySubtitle => 'VaultAI 关于你生活所记得的时间线';

  @override
  String get memoryLoading => '正在加载你的记忆...';

  @override
  String get memoryErrorPrefix => '无法加载记忆时间线。';

  @override
  String get memoryEmptyTitle => '尚无记忆。';

  @override
  String get memoryEmptySub =>
      '告诉 VaultAI 要记住的事:\"记住妈妈生日是2月14日\"。它们会按类型和日期分组显示在这里。';

  @override
  String get memoryNoMatchTitle => '没有匹配。';

  @override
  String get memoryNoMatchSub => '清除筛选或搜索以查看所有记忆。';

  @override
  String get memorySearchHint => '搜索记忆...';

  @override
  String get memoryUndated => '无日期';

  @override
  String get memoryUnnamed => '(未命名)';

  @override
  String get memoryTypeIdentity => '身份';

  @override
  String get memoryTypePeople => '人物';

  @override
  String get memoryTypeFamily => '家庭';

  @override
  String get memoryTypeBusiness => '业务';

  @override
  String get memoryTypeTravel => '旅行';

  @override
  String get memoryTypeProjects => '项目';

  @override
  String get memoryTypeGoals => '目标';

  @override
  String get memoryTypePlaces => '地点';

  @override
  String get memoryTypeDates => '日期';

  @override
  String get memoryTypeLifeEvent => '人生事件';

  @override
  String get memoryTypePreferences => '偏好';

  @override
  String get memoryTypeNote => '笔记';

  @override
  String memoryAskAbout(String key) {
    return '你记得关于$key的什么?';
  }

  @override
  String get relationshipsTitle => '关系';

  @override
  String get relationshipsSubtitle => '彼此相关的文件、账户和记忆';

  @override
  String get relationshipsLoading => '正在绘制你的保险库...';

  @override
  String get relationshipsErrorPrefix => '无法加载关系。';

  @override
  String get relationshipsEmptyTitle => '尚无聚类。';

  @override
  String get relationshipsEmptySub =>
      '上传护照、签证、发票或合同,VaultAI 会按旅行、身份、税务、家庭等方式将相关文件分组。';

  @override
  String get relationshipsNoMatchTitle => '没有匹配。';

  @override
  String get relationshipsNoMatchSub => '清除筛选或搜索。';

  @override
  String get relationshipsSearchHint => '搜索文件、条目或关系...';

  @override
  String get relationshipsTypeTravel => '旅行聚类';

  @override
  String get relationshipsTypeIdentity => '身份聚类';

  @override
  String get relationshipsTypeBusiness => '业务聚类';

  @override
  String get relationshipsTypeFinance => '金融聚类';

  @override
  String get relationshipsTypeTax => '税务聚类';

  @override
  String get relationshipsTypeMedical => '医疗聚类';

  @override
  String get relationshipsTypeFamily => '家庭聚类';

  @override
  String get relationshipsTypeSecurity => '安全聚类';

  @override
  String get relationshipsTypeMedia => '媒体聚类';

  @override
  String get relationshipsTypeInheritance => '继承聚类';

  @override
  String get relationshipsEndpointFile => '文件';

  @override
  String get relationshipsEndpointItem => '条目';

  @override
  String relationshipsAskRelated(String label) {
    return '什么与\"$label\"相关?';
  }

  @override
  String get settingsTitle => '设置';

  @override
  String get settingsSubtitle => '管理你的保险库存储和订阅计划。';

  @override
  String get settingsLanguage => '语言';

  @override
  String get settingsLanguageHint => '选择 VaultAI 使用的语言。影响应用标签和 AI 聊天回复。';

  @override
  String get settingsLanguageAuto => '自动(系统)';

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
  String get settingsLanguageSearchHint => '搜索语言(例如「Français」「French」)';

  @override
  String settingsLanguageAutoResolvedTo(String label) {
    return '系统:$label';
  }

  @override
  String get settingsLanguageSelected => '已选择';

  @override
  String settingsLanguagePartialNotice(String name) {
    return 'VaultAI Chat 将以 $name 回复。在翻译完成之前,应用界面仍显示为英文。';
  }

  @override
  String get settingsLanguagePopular => '常用';

  @override
  String get settingsLanguageAllLanguages => '所有语言';

  @override
  String settingsLanguageShowAll(int count) {
    return '显示所有语言 (还有 $count 种)';
  }

  @override
  String get settingsLanguageShowFewer => '收起';

  @override
  String settingsLanguageNoMatches(String query) {
    return '没有语言匹配「$query」';
  }

  @override
  String get settingsCurrentPlan => '当前套餐';

  @override
  String get settingsLoadingPlan => '正在加载套餐…';

  @override
  String get settingsBuyMoreStorage => '购买更多存储';

  @override
  String get settingsManageSubscription => '管理订阅';

  @override
  String get settingsDeleteVaultTile => '删除保险库';

  @override
  String get settingsDeleteVaultTileHint => '永久删除你的保险库。需要确认短语和 PIN。';

  @override
  String get securityCenterTitle => '安全中心';

  @override
  String get devicesTitle => '设备';

  @override
  String get filesTitle => '文件';

  @override
  String get loginsTitle => '登录';

  @override
  String get inheritanceTitle => '继承';

  @override
  String get dashboardTitle => '仪表板';

  @override
  String get priorityHigh => '高';

  @override
  String get priorityMedium => '中';

  @override
  String get priorityLow => '低';

  @override
  String get helpCenterTitle => '帮助与常见问题';

  @override
  String get helpCenterSubtitle =>
      '关于 VaultAI 常见问题的答案。在下方搜索或按类别浏览 — AI 助手回答自相同的主题集。';

  @override
  String get helpCenterEmpty => '没有匹配的帮助主题';

  @override
  String get helpCenterEmptyBody => '换一个搜索词,或选择一个类别。';

  @override
  String get helpCenterSupportNote => '尚未提供实时客户支持。请使用此帮助中心或询问 VaultAI Chat。';

  @override
  String get helpCenterPublicHint => '你正在查看公开帮助中心。登录以询问 VaultAI 并查看账户详情。';

  @override
  String get helpCenterSearchHint => '搜索帮助主题(例如「monero」「PIN」)';

  @override
  String get helpCenterClearSearch => '清除搜索';

  @override
  String get helpCenterSignInToAsk => '登录以询问 VaultAI';

  @override
  String get helpCategoryGettingStarted => '入门';

  @override
  String get helpCategorySecurity => '安全';

  @override
  String get helpCategoryFiles => '文件';

  @override
  String get helpCategorySecureItems => '安全项目';

  @override
  String get helpCategoryIds => '身份证件';

  @override
  String get helpCategoryCrypto => 'Crypto Vault';

  @override
  String get helpCategoryBilling => '计费';

  @override
  String get helpCategoryTroubleshooting => '故障排除';

  @override
  String get deleteVaultTitle => '永久删除保险库?';

  @override
  String get deleteVaultBody =>
      '删除保险库将永久删除你的 VaultAI 数据,包括文件、安全项目、登录、身份证件、Crypto Vault 加密钱包记录和相关的元数据。';

  @override
  String get deleteVaultCryptoWarning =>
      '删除你的保险库不会移动或删除区块链上的加密资产。如果你未在 VaultAI 之外备份钱包,删除加密的钱包记录可能导致对这些资金失去访问。';

  @override
  String get deleteVaultPhraseInstruction => '输入 DELETE MY VAULT 这一确切短语以确认:';

  @override
  String get deleteVaultPhraseMustMatch => '短语必须完全匹配。';

  @override
  String get deleteVaultPinInstruction => '输入 PIN 以确认:';

  @override
  String get deleteVaultPinHint => 'PIN';

  @override
  String get deleteVaultConfirmButton => '删除保险库';

  @override
  String get deleteVaultErrorInvalidPin => 'PIN 不正确。';

  @override
  String get deleteVaultErrorInvalidPhrase => '输入完全一致的短语以确认。';

  @override
  String get deleteVaultErrorExpired => '删除请求已过期。请重试。';

  @override
  String get deleteVaultErrorNotTrusted => '此设备不受信任。请先批准。';

  @override
  String get deleteVaultErrorGeneric => '无法完成删除。';

  @override
  String get errorRateLimited => '尝试次数过多。请等几分钟后再试。';

  @override
  String get errorRateLimitedPin => 'PIN 错误次数过多。请稍后再试。';

  @override
  String errorRateLimitedWait(int seconds) {
    return '尝试次数过多。请等待 $seconds 秒';
  }

  @override
  String get errorSessionExpired => '会话已过期。请重新登录。';

  @override
  String get errorInactivityLocked => '因不活动,保险库已锁定。';

  @override
  String get errorVaultFrozen => '此保险库已冻结。';

  @override
  String get errorDeviceNotTrusted => '此设备不受信任。请先批准。';

  @override
  String get errorGenericPrefix => '出了点问题。';

  @override
  String get errorNetwork => '网络错误。请检查连接后重试。';

  @override
  String get errorRefreshFailed => '刷新失败。请重试。';

  @override
  String get snackDeviceApproved => '设备已批准。';

  @override
  String get snackDeviceRevoked => '设备已撤销。';

  @override
  String snackDeviceApproveFailed(String error) {
    return '批准失败:$error';
  }

  @override
  String snackDeviceRevokeFailed(String error) {
    return '撤销失败:$error';
  }

  @override
  String get snackAddressCopied => '地址已复制';

  @override
  String get snackSendCooldown => '最近的发送尝试过多。请稍等再试。';

  @override
  String get storagePageTitle => '存储';

  @override
  String get storageNoDataAvailable => '没有存储数据。';

  @override
  String get storageUsageHeading => '存储使用';

  @override
  String get storageAccountHeading => '账户';

  @override
  String get storageFreeTier => '免费级别';

  @override
  String get storageNeedMoreSpace => '需要更多空间?';

  @override
  String get storageGrandfathered => '保留存储';

  @override
  String get storageAdditionalPricing => '额外存储定价';

  @override
  String get storagePlanLower => '较低套餐';

  @override
  String get storageCouldNotLoad => '无法加载存储';

  @override
  String get storageRefreshNow => '立即刷新';

  @override
  String get securityManageDevices => '管理设备';

  @override
  String get securityAnalyzePasswordsTitle => '分析密码?';

  @override
  String get securityEnterVaultPin => '输入保险库 PIN';

  @override
  String get securityAnalyzeButton => '分析';

  @override
  String get securityAnalyzeMore => '分析更多';

  @override
  String get devicePendingRequestSelfApproval => '请求自我批准';

  @override
  String get devicePendingFinalize => '完成';

  @override
  String get devicePendingCancelApproval => '取消批准';

  @override
  String get devicePendingCheckAgain => '再次检查';

  @override
  String get devicePendingRegisterDevice => '注册此设备';

  @override
  String get devicePendingDiagnoseTrust => '诊断信任';

  @override
  String get devicePendingCopyDiagnostics => '复制诊断';

  @override
  String get devicePendingDiagnosticsCopied => '诊断已复制到剪贴板。';

  @override
  String get cryptoLiteCouldNotLoadRecord => '无法加载记录详情,请重试。';

  @override
  String get cryptoLiteAddressFormatMismatchTitle => '地址格式不匹配';

  @override
  String get cryptoLiteSaveAnyway => '仍然保存';

  @override
  String get cryptoLiteEditMetadata => '编辑元数据';

  @override
  String get cryptoLiteEditBackupMetadata => '编辑备份元数据';

  @override
  String get cryptoOpenAsset => '打开资产';

  @override
  String get cryptoMoneroScannerStatus => 'Monero 扫描器状态';

  @override
  String get cryptoOpenMonero => '打开 Monero';

  @override
  String get cryptoSendDraftHeading => '发送草稿';

  @override
  String get cryptoOpenSendFlow => '打开发送';

  @override
  String get cryptoRetryFailed => '重试';

  @override
  String get cryptoOpenCryptoVault => '打开 Crypto Vault';

  @override
  String get cryptoCopyAddress => '复制地址';

  @override
  String get cryptoTransactionsTab => '交易';

  @override
  String get cryptoContinueToPin => '继续到 PIN';

  @override
  String get cryptoCopyDestination => '复制目标地址';

  @override
  String get cryptoSignatureCopied => '签名已复制';

  @override
  String get cryptoCopySignature => '复制签名';

  @override
  String get cryptoTxIdCopied => '交易 ID 已复制';

  @override
  String get cryptoCopyTxId => '复制交易 ID';

  @override
  String get vaultCardOverview => '保险库概览';

  @override
  String get vaultCardOpenVault => '打开保险库';

  @override
  String get vaultCardDocumentSummary => '文档摘要';

  @override
  String get vaultCardGeneratedLogins => '生成的登录';

  @override
  String get vaultCardBilling => '计费';

  @override
  String get vaultCardBrowseAllHelp => '浏览所有帮助主题';

  @override
  String get secureItemCopyUsername => '复制用户名';

  @override
  String get secureItemCopyValue => '复制值';

  @override
  String get notificationsTitle => '通知';

  @override
  String get notificationsMarkAllRead => '全部标记为已读';

  @override
  String get landingHowItWorks => '工作原理';

  @override
  String get authDontHaveVault => '还没有保险库?创建一个';

  @override
  String get authAlreadyHaveVault => '已有保险库?登录';

  @override
  String get authUseAnotherVault => '使用其他保险库';

  @override
  String get authLogInAnotherVault => '登录另一个保险库';

  @override
  String get snackDeviceTrusted => '已信任新设备。';

  @override
  String get confirmEraseTitle => '抹掉不可恢复的数据?';

  @override
  String get confirmEraseButton => '抹掉并继续';

  @override
  String inheritanceCancelPendingTransferTitle(String label) {
    return '取消向「$label」的待处理转移?';
  }

  @override
  String get inheritanceCancelTransfer => '取消转移';

  @override
  String inheritanceClaimTitle(String label) {
    return '认领「$label」';
  }

  @override
  String inheritanceRequestTransferTitle(String label) {
    return '请求转移「$label」?';
  }

  @override
  String inheritanceRemoveTitle(String label) {
    return '移除「$label」?';
  }

  @override
  String get inheritanceStartCountdown => '开始 30 天倒计时';

  @override
  String get inheritanceAddBeneficiary => '添加受益人';

  @override
  String get inheritanceEnterCode => '输入代码';

  @override
  String get inheritanceRequestTransfer => '请求转移';

  @override
  String get filesChooseStorage => '选择来源';

  @override
  String get filesUploadFile => '上传文件';

  @override
  String get filesUploadPhoto => '上传照片';

  @override
  String get filesUploadVideo => '上传视频';

  @override
  String get filesUploadAudio => '上传音频';

  @override
  String get filesUploadFolder => '上传文件夹';

  @override
  String get filesRecordVoice => '录音';

  @override
  String get filesRecordVideo => '录像';

  @override
  String get deleteVaultSignInRequired => '请重新登录以删除您的保险库。';

  @override
  String get deleteVaultSuccess => '您的保险库已删除。';

  @override
  String get dashboardActiveVault => '活动保险库:';
}
