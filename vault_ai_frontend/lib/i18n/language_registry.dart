// Canonical list of languages VaultAI supports across the UI and
// VaultAI Chat. This is the single source of truth for:
//
//   * the Settings language selector (native + English names,
//     search index, RTL flag)
//   * what locale codes we pass to VaultAI Chat backend so the AI
//     replies in the right language even when the app shell is
//     not yet fully translated
//   * which locales AppState.setAppLocale accepts
//
// The seven "fully localised" languages have complete .arb files
// under lib/l10n/. The other seventeen have their native names
// listed here so the user can select them; the chat backend then
// replies in that language while the app shell shows English as
// an honest fallback (see `LanguageInfo.fullyLocalised`).

import 'package:flutter/material.dart';


class LanguageInfo {
  final String code;
  final String nativeName;
  final String englishName;

  final bool fullyLocalised;

  final bool rtl;

  final List<String> aliases;

  const LanguageInfo({
    required this.code,
    required this.nativeName,
    required this.englishName,
    required this.fullyLocalised,
    required this.rtl,
    this.aliases = const <String>[],
  });

  Locale get locale => Locale(code);


  bool matchesQuery(String q) {
    if (q.isEmpty) return true;
    final n = q.trim().toLowerCase();
    if (code.toLowerCase().contains(n)) return true;
    if (englishName.toLowerCase().contains(n)) return true;
    if (nativeName.toLowerCase().contains(n)) return true;
    for (final a in aliases) {
      if (a.toLowerCase().contains(n)) return true;
    }
    return false;
  }
}


const List<LanguageInfo> kSupportedLanguages = <LanguageInfo>[

  LanguageInfo(
    code: 'en',
    nativeName: 'English',
    englishName: 'English',
    fullyLocalised: true,
    rtl: false,
  ),
  LanguageInfo(
    code: 'ar',
    nativeName: 'العربية',
    englishName: 'Arabic',
    fullyLocalised: true,
    rtl: true,
    aliases: <String>['arabic', 'arabe', 'ar'],
  ),
  LanguageInfo(
    code: 'fr',
    nativeName: 'Français',
    englishName: 'French',
    fullyLocalised: true,
    rtl: false,
    aliases: <String>['francais', 'french'],
  ),
  LanguageInfo(
    code: 'es',
    nativeName: 'Español',
    englishName: 'Spanish',
    fullyLocalised: true,
    rtl: false,
    aliases: <String>['espanol', 'spanish', 'castellano'],
  ),
  LanguageInfo(
    code: 'ja',
    nativeName: '日本語',
    englishName: 'Japanese',
    fullyLocalised: true,
    rtl: false,
    aliases: <String>['japanese', 'nihongo', 'ja'],
  ),
  LanguageInfo(
    code: 'ko',
    nativeName: '한국어',
    englishName: 'Korean',
    fullyLocalised: true,
    rtl: false,
    aliases: <String>['korean', 'hangul', 'ko'],
  ),
  LanguageInfo(
    code: 'zh',
    nativeName: '中文',
    englishName: 'Chinese',
    fullyLocalised: true,
    rtl: false,
    aliases: <String>['chinese', 'mandarin', 'simplified'],
  ),


  LanguageInfo(
    code: 'pt',
    nativeName: 'Português',
    englishName: 'Portuguese',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['portugues', 'portuguese', 'brasileiro'],
  ),
  LanguageInfo(
    code: 'de',
    nativeName: 'Deutsch',
    englishName: 'German',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['german', 'deutsch', 'de'],
  ),
  LanguageInfo(
    code: 'it',
    nativeName: 'Italiano',
    englishName: 'Italian',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['italian', 'italiano'],
  ),
  LanguageInfo(
    code: 'hi',
    nativeName: 'हिन्दी',
    englishName: 'Hindi',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['hindi'],
  ),
  LanguageInfo(
    code: 'ur',
    nativeName: 'اردو',
    englishName: 'Urdu',
    fullyLocalised: false,
    rtl: true,
    aliases: <String>['urdu'],
  ),
  LanguageInfo(
    code: 'bn',
    nativeName: 'বাংলা',
    englishName: 'Bengali',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['bengali', 'bangla'],
  ),
  LanguageInfo(
    code: 'ru',
    nativeName: 'Русский',
    englishName: 'Russian',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['russian'],
  ),
  LanguageInfo(
    code: 'tr',
    nativeName: 'Türkçe',
    englishName: 'Turkish',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['turkish', 'turkce'],
  ),
  LanguageInfo(
    code: 'id',
    nativeName: 'Bahasa Indonesia',
    englishName: 'Indonesian',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['indonesian', 'bahasa'],
  ),
  LanguageInfo(
    code: 'vi',
    nativeName: 'Tiếng Việt',
    englishName: 'Vietnamese',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['vietnamese', 'tiengviet'],
  ),
  LanguageInfo(
    code: 'th',
    nativeName: 'ไทย',
    englishName: 'Thai',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['thai'],
  ),
  LanguageInfo(
    code: 'sw',
    nativeName: 'Kiswahili',
    englishName: 'Swahili',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['swahili', 'kiswahili'],
  ),
  LanguageInfo(
    code: 'ha',
    nativeName: 'Hausa',
    englishName: 'Hausa',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['hausa'],
  ),
  LanguageInfo(
    code: 'yo',
    nativeName: 'Yorùbá',
    englishName: 'Yoruba',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['yoruba'],
  ),
  LanguageInfo(
    code: 'ig',
    nativeName: 'Igbo',
    englishName: 'Igbo',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['igbo'],
  ),
  LanguageInfo(
    code: 'so',
    nativeName: 'Soomaali',
    englishName: 'Somali',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['somali', 'soomaali'],
  ),
  LanguageInfo(
    code: 'am',
    nativeName: 'አማርኛ',
    englishName: 'Amharic',
    fullyLocalised: false,
    rtl: false,
    aliases: <String>['amharic'],
  ),
];



const Set<String> kFullyLocalisedCodes = <String>{
  'en', 'ar', 'fr', 'es', 'ja', 'ko', 'zh',
};



const Set<String> kRtlLanguageCodes = <String>{
  'ar', 'ur',
};


LanguageInfo? findLanguageByCode(String? code) {
  if (code == null || code.isEmpty) return null;
  final normalised = code.toLowerCase().split('-').first;
  for (final l in kSupportedLanguages) {
    if (l.code == normalised) return l;
  }
  return null;
}


bool isSupportedLanguageCode(String? code) =>
    findLanguageByCode(code) != null;


bool isFullyLocalised(String? code) {
  final info = findLanguageByCode(code);
  return info != null && info.fullyLocalised;
}


bool isRtlLanguage(String? code) {
  final info = findLanguageByCode(code);
  return info != null && info.rtl;
}
