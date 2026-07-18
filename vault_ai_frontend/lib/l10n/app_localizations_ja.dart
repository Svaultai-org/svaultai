// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Japanese (`ja`).
class AppLocalizationsJa extends AppLocalizations {
  AppLocalizationsJa([String locale = 'ja']) : super(locale);

  @override
  String get appTitle => 'VaultAI';

  @override
  String get commonRetry => '再試行';

  @override
  String get commonRefresh => '更新';

  @override
  String get commonOpen => '開く';

  @override
  String get commonCancel => 'キャンセル';

  @override
  String get commonSave => '保存';

  @override
  String get commonSignOut => 'サインアウト';

  @override
  String get commonLoading => '読み込み中...';

  @override
  String get commonAll => 'すべて';

  @override
  String get commonView => '表示';

  @override
  String get commonDownload => 'ダウンロード';

  @override
  String get commonAskVaultAI => 'VaultAI に聞く';

  @override
  String get commonClose => '閉じる';

  @override
  String get commonDelete => '削除';

  @override
  String get commonConfirm => '確認';

  @override
  String get commonSignIn => 'サインイン';

  @override
  String get commonSignUp => 'サインアップ';

  @override
  String get commonSearch => '検索';

  @override
  String get commonBack => '戻る';

  @override
  String get commonNext => '次へ';

  @override
  String get commonYes => 'はい';

  @override
  String get commonNo => 'いいえ';

  @override
  String get commonError => 'エラー';

  @override
  String get commonSuccess => '完了';

  @override
  String get commonUnavailable => '利用不可';

  @override
  String get commonTryAgain => '再試行';

  @override
  String get commonContinue => '続ける';

  @override
  String get commonApprove => '承認';

  @override
  String get commonReject => '拒否';

  @override
  String get commonRevoke => '取り消し';

  @override
  String get commonReceive => '受け取り';

  @override
  String get commonReview => '確認';

  @override
  String get commonAnalyze => '解析';

  @override
  String get commonCopy => 'コピー';

  @override
  String get commonEdit => '編集';

  @override
  String get commonCurrent => '現在';

  @override
  String get commonCopyCode => 'コードをコピー';

  @override
  String get commonRemove => '削除';

  @override
  String get commonNotYet => 'まだ';

  @override
  String get sidebarDashboard => 'ダッシュボード';

  @override
  String get sidebarChat => 'チャット';

  @override
  String get sidebarFiles => 'ファイル';

  @override
  String get sidebarLogins => 'ログイン';

  @override
  String get sidebarCryptoVault => 'Crypto Vault';

  @override
  String get sidebarConcierge => 'コンシェルジュ';

  @override
  String get sidebarExpiry => '有効期限';

  @override
  String get sidebarMemory => 'メモリ';

  @override
  String get sidebarRelationships => '関連';


  @override
  String get sidebarSettings => '設定';

  @override
  String get chatComposerHint => 'あなたの保管庫について質問するか、ファイルをアップロードしてください...';

  @override
  String get chatThinking => 'VaultAI が考えています...';

  @override
  String chatThinkingWithName(String name) {
    return '$name が考えています...';
  }

  @override
  String get chatSendButton => '送信';

  @override
  String get chatSending => '送信中...';

  @override
  String chatAskAbout(String topic) {
    return '$topic についてもっと教えて';
  }

  @override
  String get chatErrorGeneric => 'VaultAI は今回答できませんでした。もう一度試してください。';

  @override
  String get chatRetryButton => '再試行';

  @override
  String get chatQuickSavedLogins => '保存されたログイン';

  @override
  String get chatQuickMyFiles => 'マイファイル';

  @override
  String get chatQuickMyPassport => '私のパスポート';

  @override
  String get chatQuickWhatCanYouDo => '何ができますか?';

  @override
  String get chatCardShowRelated => '関連を表示';

  @override
  String get chatCardTopFolders => '主要フォルダ';

  @override
  String get chatCardRecentFiles => '最近のファイル';

  @override
  String get chatCardSearchDeeper => '詳細検索';

  @override
  String get chatCardKeepBoth => '両方を保持';

  @override
  String get chatCardUpgradeStorage => 'ストレージをアップグレード';

  @override
  String get unlockToSeeConcierge => 'コンシェルジュを表示するには保管庫を解除してください。';

  @override
  String get unlockToSeeExpiry => '有効期限を表示するには保管庫を解除してください。';

  @override
  String get unlockToSeeMemory => 'メモリタイムラインを表示するには保管庫を解除してください。';

  @override
  String get unlockToSeeRelationships => '関連グラフを表示するには保管庫を解除してください。';

  @override
  String get conciergeTitle => 'コンシェルジュ';

  @override
  String get conciergeSubtitle => 'VaultAI が次に確認すべきと考えるもの';

  @override
  String get conciergeLoading => '情報を集めています...';

  @override
  String get conciergeErrorPrefix => 'コンシェルジュのデータを読み込めませんでした。';

  @override
  String get conciergeCriticalNow => '今すぐ緊急';

  @override
  String get conciergeComingUp => 'もうすぐ';

  @override
  String get conciergeRecommendations => '推奨事項';

  @override
  String get conciergeTravelReady => '渡航準備 OK';

  @override
  String get conciergeTravelMostly => 'ほぼ準備済み';

  @override
  String get conciergeTravelAttention => '要確認';

  @override
  String get conciergeTravelReadyDetail => 'パスポート > 180日、ビザ > 30日。';

  @override
  String get conciergeTravelMostlyDetail => 'パスポートかビザのいずれかが不足、または更新が近い。';

  @override
  String get conciergeTravelAttentionDetail => '更新が必要です - パスポートとビザを確認してください。';

  @override
  String get conciergeRenewalTimeline => '更新タイムライン(今後90日)';

  @override
  String get conciergeTravelReadiness => '渡航準備';

  @override
  String get conciergeAllClear => 'すべて問題ありません。';

  @override
  String get conciergeAllClearSub =>
      '本日急ぎはありません。VaultAI は書類を監視し、新しい事項があればここに表示します。';

  @override
  String get conciergePostureSecurity => 'セキュリティ';

  @override
  String get conciergePostureExpiring => '失効';


  @override
  String get conciergePostureScoreHint => 'タップしてセキュリティセンターを表示';

  @override
  String get conciergePostureNoData => 'データなし';

  @override
  String get conciergePostureNothingTracked => '追跡対象なし';

  @override
  String get conciergePostureAllFuture => 'すべて余裕あり';




  @override
  String get conciergePostureScoreNoData => 'データなし';

  @override
  String get conciergeAskTravel => '渡航準備はできていますか?';

  @override
  String get conciergePassport => 'パスポート';

  @override
  String get conciergeVisa => 'ビザ';

  @override
  String get conciergePassportNotOnFile => '未登録';

  @override
  String get conciergeNoExpiryDate => '有効期限なし';

  @override
  String get conciergeExpired => '期限切れ';

  @override
  String get conciergeRenewSoon => '近く更新';

  @override
  String get conciergeComfortable => '余裕あり';

  @override
  String get conciergeItem => '件';

  @override
  String get conciergeItems => '件';




  @override
  String get expiryTitle => '有効期限';

  @override
  String get expirySubtitle => 'もうすぐ失効する書類と義務';

  @override
  String get expiryLoading => '失効アラートを読み込んでいます...';

  @override
  String get expiryErrorPrefix => '失効アラートを読み込めませんでした。';

  @override
  String get expiryEmptyTitle => 'すべての更新で先手を打っています。';

  @override
  String get expiryEmptySub =>
      'パスポート、ビザ、保険証券、契約書をアップロードすると VaultAI が自動的に有効期限を追跡します。';

  @override
  String get expiryNoneInWindow => 'この期間内にはありません。';

  @override
  String expiryNoneInWindowSub(String window) {
    return '$window 以内に失効する書類はありません。より長い期間をお試しください。';
  }

  @override
  String get expiryWindow7d => '7日';

  @override
  String get expiryWindow30d => '30日';

  @override
  String get expiryWindow90d => '90日';

  @override
  String get expiryWindowAll => 'すべて';

  @override
  String get expiryBucketCritical => '緊急';

  @override
  String get expiryBucketWarning => '警告';

  @override
  String get expiryBucketInfo => '通知';

  @override
  String expiryCountCritical(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '緊急 $count 件',
    );
    return '$_temp0';
  }

  @override
  String expiryCountWarning(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '警告 $count 件',
    );
    return '$_temp0';
  }

  @override
  String expiryDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days日',
    );
    return '$_temp0';
  }

  @override
  String get expiryToday => '本日';

  @override
  String expiredAgo(int days) {
    return '$days日前';
  }

  @override
  String get expiryNoDate => '日付なし';

  @override
  String get expiryDays => '残り';

  @override
  String get expiryDaysExpires => '失効';

  @override
  String get memoryTitle => 'メモリ';

  @override
  String get memorySubtitle => 'VaultAI があなたについて覚えていることのタイムライン';

  @override
  String get memoryLoading => 'あなたの記憶を読み込み中...';

  @override
  String get memoryErrorPrefix => 'メモリタイムラインを読み込めませんでした。';

  @override
  String get memoryEmptyTitle => 'まだ記憶はありません。';

  @override
  String get memoryEmptySub =>
      'VaultAI に覚えてほしいことを伝えてください:「母の誕生日は 2 月 14 日」など。種類と日付でグループ化されてここに表示されます。';

  @override
  String get memoryNoMatchTitle => '一致するものがありません。';

  @override
  String get memoryNoMatchSub => 'フィルターや検索をクリアして全ての記憶を表示してください。';

  @override
  String get memorySearchHint => '記憶を検索...';

  @override
  String get memoryUndated => '日付なし';

  @override
  String get memoryUnnamed => '(無題)';

  @override
  String get memoryTypeIdentity => 'アイデンティティ';

  @override
  String get memoryTypePeople => '人';

  @override
  String get memoryTypeFamily => '家族';

  @override
  String get memoryTypeBusiness => 'ビジネス';

  @override
  String get memoryTypeTravel => '旅行';

  @override
  String get memoryTypeProjects => 'プロジェクト';

  @override
  String get memoryTypeGoals => '目標';

  @override
  String get memoryTypePlaces => '場所';

  @override
  String get memoryTypeDates => '日付';

  @override
  String get memoryTypeLifeEvent => 'ライフイベント';

  @override
  String get memoryTypePreferences => '好み';

  @override
  String get memoryTypeNote => 'メモ';

  @override
  String memoryAskAbout(String key) {
    return '$key について覚えていることは?';
  }

  @override
  String get relationshipsTitle => '関連';

  @override
  String get relationshipsSubtitle => '一緒に属する書類・アカウント・記憶';

  @override
  String get relationshipsLoading => '保管庫をマッピング中...';

  @override
  String get relationshipsErrorPrefix => '関連を読み込めませんでした。';

  @override
  String get relationshipsEmptyTitle => 'まだクラスタはありません。';

  @override
  String get relationshipsEmptySub =>
      'パスポート、ビザ、請求書、契約書をアップロードすると、VaultAI が旅行・アイデンティティ・税金・家族などで書類をグループ化します。';

  @override
  String get relationshipsNoMatchTitle => '一致するものがありません。';

  @override
  String get relationshipsNoMatchSub => 'フィルターや検索をクリアしてください。';

  @override
  String get relationshipsSearchHint => '書類、項目、関連を検索...';

  @override
  String get relationshipsTypeTravel => '旅行クラスタ';

  @override
  String get relationshipsTypeIdentity => 'アイデンティティクラスタ';

  @override
  String get relationshipsTypeBusiness => 'ビジネスクラスタ';

  @override
  String get relationshipsTypeFinance => 'ファイナンスクラスタ';

  @override
  String get relationshipsTypeTax => '税金クラスタ';

  @override
  String get relationshipsTypeMedical => '医療クラスタ';

  @override
  String get relationshipsTypeFamily => '家族クラスタ';

  @override
  String get relationshipsTypeSecurity => 'セキュリティクラスタ';

  @override
  String get relationshipsTypeMedia => 'メディアクラスタ';

  @override
  String get relationshipsTypeInheritance => '継承クラスタ';

  @override
  String get relationshipsEndpointFile => 'ファイル';

  @override
  String get relationshipsEndpointItem => 'アイテム';

  @override
  String relationshipsAskRelated(String label) {
    return '「$label」に関連するものは?';
  }

  @override
  String get settingsTitle => '設定';

  @override
  String get settingsSubtitle => '保管庫のストレージとプランを管理します。';

  @override
  String get settingsLanguage => '言語';

  @override
  String get settingsLanguageHint =>
      'VaultAI が使う言語を選択してください。アプリのラベルと AI チャットの返答に影響します。';

  @override
  String get settingsLanguageAuto => '自動(システム)';

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
  String get settingsLanguageSearchHint => '言語を検索(例:「Français」「French」)';

  @override
  String settingsLanguageAutoResolvedTo(String label) {
    return 'システム: $label';
  }

  @override
  String get settingsLanguageSelected => '選択中';

  @override
  String settingsLanguagePartialNotice(String name) {
    return 'VaultAI Chat は $name で応答します。翻訳作業中のため、アプリ画面は英語のまま表示されます。';
  }

  @override
  String get settingsLanguagePopular => 'よく使う言語';

  @override
  String get settingsLanguageAllLanguages => 'すべての言語';

  @override
  String settingsLanguageShowAll(int count) {
    return 'すべての言語を表示 (他$count件)';
  }

  @override
  String get settingsLanguageShowFewer => '折りたたむ';

  @override
  String settingsLanguageNoMatches(String query) {
    return '「$query」に一致する言語はありません';
  }

  @override
  String get settingsCurrentPlan => '現在のプラン';

  @override
  String get settingsLoadingPlan => 'プランを読み込み中…';

  @override
  String get settingsBuyMoreStorage => 'ストレージを追加購入';

  @override
  String get settingsManageSubscription => 'サブスクリプションを管理';

  @override
  String get settingsDeleteVaultTile => '保管庫を削除';

  @override
  String get settingsDeleteVaultTileHint => '保管庫を完全に削除します。確認フレーズと PIN が必要です。';

  @override
  String get securityCenterTitle => 'セキュリティセンター';

  @override
  String get devicesTitle => 'デバイス';

  @override
  String get filesTitle => 'ファイル';

  @override
  String get loginsTitle => 'ログイン';

  @override
  String get inheritanceTitle => '継承';

  @override
  String get dashboardTitle => 'ダッシュボード';

  @override
  String get priorityHigh => '高';

  @override
  String get priorityMedium => '中';

  @override
  String get priorityLow => '低';

  @override
  String get helpCenterTitle => 'ヘルプ & FAQ';

  @override
  String get helpCenterSubtitle =>
      'VaultAI に関するよくある質問への回答。下で検索するか、カテゴリで閲覧してください。AI アシスタントは同じ内容から回答します。';

  @override
  String get helpCenterEmpty => '該当するヘルプがありません';

  @override
  String get helpCenterEmptyBody => '別の検索語を試すか、カテゴリを選んでください。';

  @override
  String get helpCenterSupportNote =>
      'ライブカスタマーサポートはまだ提供されていません。このヘルプセンターまたは VaultAI Chat をご利用ください。';

  @override
  String get helpContactSupportTitle => 'サポートに問い合わせ';

  @override
  String get helpContactSupportBody =>
      'VaultAI についてサポートが必要ですか?サポートチームにお問い合わせください。';

  @override
  String helpContactSupportEmailA11yLabel(String email) {
    return '$email 宛に VaultAI サポートへメール送信';
  }

  @override
  String helpContactSupportEmailOpenFailed(String email) {
    return 'メールアプリを開けませんでした。代わりにこのアドレスをコピーしてください: $email';
  }

  @override
  String get helpContactSupportCopyEmailLabel => 'メールアドレスをコピー';

  @override
  String helpContactSupportCopyEmailA11yLabel(String email) {
    return 'VaultAI サポートのメールアドレス $email をクリップボードにコピー';
  }

  @override
  String get helpContactSupportEmailCopied =>
      'メールアドレスをクリップボードにコピーしました';

  @override
  String get helpCenterPublicHint =>
      '公開ヘルプセンターを表示しています。VaultAI に質問しアカウント詳細を見るにはサインインしてください。';

  @override
  String get helpCenterSearchHint => 'ヘルプを検索(例:「monero」「PIN」)';

  @override
  String get helpCenterClearSearch => '検索をクリア';

  @override
  String get helpCenterSignInToAsk => 'サインインして VaultAI に質問';

  @override
  String get helpCategoryGettingStarted => 'はじめに';

  @override
  String get helpCategorySecurity => 'セキュリティ';

  @override
  String get helpCategoryFiles => 'ファイル';

  @override
  String get helpCategorySecureItems => 'セキュアアイテム';

  @override
  String get helpCategoryIds => '身分証';

  @override
  String get helpCategoryCrypto => 'Crypto Vault';

  @override
  String get helpCategoryBilling => '請求';

  @override
  String get helpCategoryTroubleshooting => 'トラブルシューティング';

  @override
  String get deleteVaultTitle => '保管庫を完全に削除しますか?';

  @override
  String get deleteVaultBody =>
      '保管庫を削除すると、VaultAI のデータ(ファイル、セキュアアイテム、ログイン、身分証、Crypto Vault の暗号化された記録、関連メタデータ)が完全に削除されます。';

  @override
  String get deleteVaultCryptoWarning =>
      '保管庫の削除はブロックチェーン上の暗号資産を移動・削除しません。VaultAI 外にウォレットのバックアップがない場合、暗号化された記録の削除によりその資金へのアクセスを失う可能性があります。';

  @override
  String get deleteVaultPhraseInstruction =>
      '確認するには、フレーズ DELETE MY VAULT を正確に入力してください:';

  @override
  String get deleteVaultPhraseMustMatch => 'フレーズが正確に一致する必要があります。';

  @override
  String get deleteVaultPinInstruction => '確認のため PIN を入力してください:';

  @override
  String get deleteVaultPinHint => 'PIN';

  @override
  String get deleteVaultConfirmButton => '保管庫を削除';

  @override
  String get deleteVaultErrorInvalidPin => 'PIN が正しくありません。';

  @override
  String get deleteVaultErrorInvalidPhrase => '確認のため正確なフレーズを入力してください。';

  @override
  String get deleteVaultErrorExpired => '削除リクエストが期限切れです。再試行してください。';

  @override
  String get deleteVaultErrorNotTrusted => 'このデバイスは信頼されていません。先に承認してください。';

  @override
  String get deleteVaultErrorGeneric => '削除を完了できませんでした。';

  @override
  String get errorRateLimited => '試行回数が多すぎます。数分待ってから再試行してください。';

  @override
  String get errorRateLimitedPin => 'PIN の誤入力が多すぎます。しばらくしてから再試行してください。';

  @override
  String errorRateLimitedWait(int seconds) {
    return '試行回数が多すぎます。$seconds 秒待ってください';
  }

  @override
  String get errorSessionExpired => 'セッションの期限が切れました。もう一度サインインしてください。';

  @override
  String get errorInactivityLocked => '非アクティブのため保管庫がロックされました。';

  @override
  String get errorVaultFrozen => 'この保管庫は凍結されています。';

  @override
  String get errorDeviceNotTrusted => 'このデバイスは信頼されていません。先に承認してください。';

  @override
  String get errorGenericPrefix => '問題が発生しました。';

  @override
  String get errorNetwork => 'ネットワークエラー。接続を確認して再試行してください。';

  @override
  String get errorRefreshFailed => '更新に失敗しました。再試行してください。';

  @override
  String get snackDeviceApproved => 'デバイスを承認しました。';

  @override
  String get snackDeviceRevoked => 'デバイスを取り消しました。';

  @override
  String snackDeviceApproveFailed(String error) {
    return '承認に失敗: $error';
  }

  @override
  String snackDeviceRevokeFailed(String error) {
    return '取り消しに失敗: $error';
  }

  @override
  String get snackAddressCopied => 'アドレスをコピーしました';

  @override
  String get snackSendCooldown => '最近の送信試行が多すぎます。少し待ってください。';

  @override
  String get storagePageTitle => 'ストレージ';

  @override
  String get storageNoDataAvailable => 'ストレージデータがありません。';

  @override
  String get storageUsageHeading => 'ストレージ使用状況';

  @override
  String get storageAccountHeading => 'アカウント';

  @override
  String get storageFreeTier => '無料プラン';

  @override
  String get storageNeedMoreSpace => '容量が必要ですか?';

  @override
  String get storageGrandfathered => '保持された容量';

  @override
  String get storageAdditionalPricing => '追加容量の価格';

  @override
  String get storagePlanLower => '下位プラン';

  @override
  String get storageCouldNotLoad => 'ストレージを読み込めませんでした';

  @override
  String get storageRefreshNow => '更新';

  @override
  String get securityManageDevices => 'デバイスを管理';

  @override
  String get securityAnalyzePasswordsTitle => 'パスワードを解析しますか?';

  @override
  String get securityEnterVaultPin => '保管庫の PIN を入力';

  @override
  String get securityAnalyzeButton => '解析';

  @override
  String get securityAnalyzeMore => 'さらに解析';

  @override
  String get devicePendingRequestSelfApproval => '自己承認をリクエスト';

  @override
  String get devicePendingFinalize => '完了';

  @override
  String get devicePendingCancelApproval => '承認を取消';

  @override
  String get devicePendingCheckAgain => '再確認';

  @override
  String get devicePendingRegisterDevice => 'このデバイスを登録';

  @override
  String get devicePendingDiagnoseTrust => '信頼を診断';

  @override
  String get devicePendingCopyDiagnostics => '診断をコピー';

  @override
  String get devicePendingDiagnosticsCopied => '診断をコピーしました。';

  @override
  String get cryptoLiteCouldNotLoadRecord => 'レコードの詳細を読み込めませんでした。';

  @override
  String get cryptoLiteAddressFormatMismatchTitle => 'アドレス形式が一致しません';

  @override
  String get cryptoLiteSaveAnyway => 'それでも保存';

  @override
  String get cryptoLiteEditMetadata => 'メタデータを編集';

  @override
  String get cryptoLiteEditBackupMetadata => 'バックアップメタデータを編集';

  @override
  String get cryptoOpenAsset => '資産を開く';

  @override
  String get cryptoMoneroScannerStatus => 'Monero スキャナの状態';

  @override
  String get cryptoOpenMonero => 'Monero を開く';

  @override
  String get cryptoSendDraftHeading => '送信下書き';

  @override
  String get cryptoOpenSendFlow => '送信を開く';

  @override
  String get cryptoRetryFailed => '再試行';

  @override
  String get cryptoOpenCryptoVault => 'Crypto Vault を開く';

  @override
  String get cryptoCopyAddress => 'アドレスをコピー';

  @override
  String get cryptoTransactionsTab => '取引';

  @override
  String get cryptoContinueToPin => 'PIN へ進む';

  @override
  String get cryptoCopyDestination => '宛先をコピー';

  @override
  String get cryptoSignatureCopied => '署名をコピーしました';

  @override
  String get cryptoCopySignature => '署名をコピー';

  @override
  String get cryptoTxIdCopied => '取引 ID をコピーしました';

  @override
  String get cryptoCopyTxId => '取引 ID をコピー';

  @override
  String get vaultCardOverview => '保管庫の概要';

  @override
  String get vaultCardOpenVault => '保管庫を開く';

  @override
  String get vaultCardDocumentSummary => '書類の要約';

  @override
  String get vaultCardGeneratedLogins => '生成されたログイン';

  @override
  String get vaultCardBilling => '請求';

  @override
  String get vaultCardBrowseAllHelp => '全てのヘルプトピックを見る';

  @override
  String get secureItemCopyUsername => 'ユーザー名をコピー';

  @override
  String get secureItemCopyValue => '値をコピー';

  @override
  String get notificationsTitle => '通知';

  @override
  String get notificationsMarkAllRead => 'すべて既読にする';

  @override
  String get landingHowItWorks => '仕組み';

  @override
  String get authDontHaveVault => '保管庫をお持ちでない場合、作成する';

  @override
  String get authAlreadyHaveVault => '既に保管庫をお持ちの場合、サインイン';

  @override
  String get authUseAnotherVault => '別の保管庫を使う';

  @override
  String get authLogInAnotherVault => '別の保管庫にサインイン';

  @override
  String get snackDeviceTrusted => '新しいデバイスを信頼しました。';

  @override
  String get confirmEraseTitle => '復元できないデータを消去しますか?';

  @override
  String get confirmEraseButton => '消去して続行';

  @override
  String inheritanceCancelPendingTransferTitle(String label) {
    return '「$label」への保留中の譲渡を取り消しますか?';
  }

  @override
  String get inheritanceCancelTransfer => '譲渡を取り消す';

  @override
  String inheritanceClaimTitle(String label) {
    return '「$label」を請求';
  }

  @override
  String inheritanceRequestTransferTitle(String label) {
    return '「$label」の譲渡を要求しますか?';
  }

  @override
  String inheritanceRemoveTitle(String label) {
    return '「$label」を削除しますか?';
  }

  @override
  String get inheritanceStartCountdown => '30 日間のカウントダウンを開始';

  @override
  String get inheritanceAddBeneficiary => '受益者を追加';

  @override
  String get inheritanceEnterCode => 'コードを入力';

  @override
  String get inheritanceRequestTransfer => '譲渡を要求';

  @override
  String get filesChooseStorage => 'アップロード元を選択';

  @override
  String get filesUploadFile => 'ファイルをアップロード';

  @override
  String get filesUploadPhoto => '写真をアップロード';

  @override
  String get filesUploadVideo => '動画をアップロード';

  @override
  String get filesUploadAudio => '音声をアップロード';

  @override
  String get filesUploadFolder => 'フォルダをアップロード';

  @override
  String get filesRecordVoice => '音声を録音';

  @override
  String get filesRecordVideo => '動画を録画';

  @override
  String get deleteVaultSignInRequired => '保管庫を削除するには再度サインインしてください。';

  @override
  String get deleteVaultSuccess => '保管庫は削除されました。';

  @override
  String get dashboardActiveVault => 'アクティブな保管庫:';
}
