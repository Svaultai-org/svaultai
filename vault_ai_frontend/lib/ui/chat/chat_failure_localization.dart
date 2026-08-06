/// Trusted, offline provider-failure copy for explicitly requested languages.
///
/// These strings never include provider diagnostics.  They are intentionally
/// static so a provider outage cannot turn localization itself into another
/// network request.
const Map<String, String> _friendlyFailureByLanguage = {
  'es':
      'Lo siento, no puedo responder en español en este momento. Podemos continuar en inglés, intentarlo de nuevo en unos minutos o cancelar.',
  'fr':
      'Je suis désolé, je ne peux pas répondre en français pour le moment. Nous pouvons continuer en anglais, réessayer dans quelques minutes ou annuler.',
  'tl':
      'Paumanhin, hindi ako makasagot sa Tagalog sa ngayon. Maaari tayong magpatuloy sa Ingles, subukan muli pagkalipas ng ilang minuto, o kanselahin.',
  'ar':
      'عذرًا، لا يمكنني الرد بالعربية الآن. يمكننا المتابعة بالإنجليزية، أو المحاولة مرة أخرى بعد بضع دقائق، أو الإلغاء.',
  'so':
      'Waan ka xumahay, hadda kuma jawaabi karo Af-Soomaali. Waxaan ku sii wadi karnaa Ingiriisi, mar kale isku day dhowr daqiiqo kadib, ama jooji.',
  'ja': '申し訳ありませんが、現在は日本語で返信できません。英語で続けるか、数分後にもう一度試すか、キャンセルできます。',
  'hi':
      'मुझे खेद है, मैं अभी हिंदी में उत्तर नहीं दे सकता। हम अंग्रेज़ी में जारी रख सकते हैं, कुछ मिनट बाद फिर कोशिश कर सकते हैं, या रद्द कर सकते हैं।',
  'sw':
      'Samahani, siwezi kujibu kwa Kiswahili kwa sasa. Tunaweza kuendelea kwa Kiingereza, kujaribu tena baada ya dakika chache, au kughairi.',
  'fa':
      'متأسفم، در حال حاضر نمی‌توانم به فارسی پاسخ بدهم. می‌توانیم به انگلیسی ادامه دهیم، چند دقیقه دیگر دوباره تلاش کنیم، یا لغو کنیم.',
};

const String unknownLanguageFailure =
    "I'm sorry, I can't reply in the requested language right now. "
    'We can continue in English, you can try again in a moment, or cancel.';

const Map<String, String> _languageAliases = {
  'spanish': 'es',
  'french': 'fr',
  'tagalog': 'tl',
  'filipino': 'tl',
  'arabic': 'ar',
  'somali': 'so',
  'japanese': 'ja',
  'hindi': 'hi',
  'swahili': 'sw',
  'persian': 'fa',
  'farsi': 'fa',
};

String? requestedFailureLanguageCode(String prompt) {
  final normalized = prompt.toLowerCase().replaceAll(RegExp(r'\s+'), ' ');
  for (final entry in _languageAliases.entries) {
    if (RegExp(
      '(?:reply|respond|answer|write|speak|say|explain|tell me|in)'
      r'[^.!?\n]{0,100}\b'
      '${RegExp.escape(entry.key)}'
      r'\b',
    ).hasMatch(normalized)) {
      return entry.value;
    }
  }
  return null;
}

String friendlyChatGenerationFailure(String prompt) {
  final code = requestedFailureLanguageCode(prompt);
  return _friendlyFailureByLanguage[code] ?? unknownLanguageFailure;
}
