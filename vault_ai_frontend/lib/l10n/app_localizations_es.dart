// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Spanish Castilian (`es`).
class AppLocalizationsEs extends AppLocalizations {
  AppLocalizationsEs([String locale = 'es']) : super(locale);

  @override
  String get appTitle => 'VaultAI';

  @override
  String get commonRetry => 'Reintentar';

  @override
  String get commonRefresh => 'Actualizar';

  @override
  String get commonOpen => 'Abrir';

  @override
  String get commonCancel => 'Cancelar';

  @override
  String get commonSave => 'Guardar';

  @override
  String get commonSignOut => 'Cerrar sesión';

  @override
  String get commonLoading => 'Cargando...';

  @override
  String get commonAll => 'Todo';

  @override
  String get commonView => 'Ver';

  @override
  String get commonDownload => 'Descargar';

  @override
  String get commonAskVaultAI => 'Preguntar a VaultAI';

  @override
  String get commonClose => 'Cerrar';

  @override
  String get commonDelete => 'Eliminar';

  @override
  String get commonConfirm => 'Confirmar';

  @override
  String get commonSignIn => 'Iniciar sesión';

  @override
  String get commonSignUp => 'Registrarse';

  @override
  String get commonSearch => 'Buscar';

  @override
  String get commonBack => 'Atrás';

  @override
  String get commonNext => 'Siguiente';

  @override
  String get commonYes => 'Sí';

  @override
  String get commonNo => 'No';

  @override
  String get commonError => 'Error';

  @override
  String get commonSuccess => 'Éxito';

  @override
  String get commonUnavailable => 'No disponible';

  @override
  String get commonTryAgain => 'Reintentar';

  @override
  String get commonContinue => 'Continuar';

  @override
  String get commonApprove => 'Aprobar';

  @override
  String get commonReject => 'Rechazar';

  @override
  String get commonRevoke => 'Revocar';

  @override
  String get commonReceive => 'Recibir';

  @override
  String get commonReview => 'Revisar';

  @override
  String get commonAnalyze => 'Analizar';

  @override
  String get commonCopy => 'Copiar';

  @override
  String get commonEdit => 'Editar';

  @override
  String get commonCurrent => 'Actual';

  @override
  String get commonCopyCode => 'Copiar código';

  @override
  String get commonRemove => 'Quitar';

  @override
  String get commonNotYet => 'Todavía no';

  @override
  String get sidebarDashboard => 'Panel';

  @override
  String get sidebarChat => 'Chat';

  @override
  String get sidebarFiles => 'Archivos';

  @override
  String get sidebarLogins => 'Accesos';

  @override
  String get sidebarCryptoVault => 'Crypto Vault';

  @override
  String get sidebarConcierge => 'Asistente';

  @override
  String get sidebarExpiry => 'Vencimientos';

  @override
  String get sidebarMemory => 'Memoria';

  @override
  String get sidebarRelationships => 'Relaciones';

  @override
  String get sidebarInheritance => 'Herencia';

  @override
  String get sidebarSettings => 'Ajustes';

  @override
  String get chatComposerHint =>
      'Pregunta sobre tu bóveda o sube un archivo...';

  @override
  String get chatThinking => 'VaultAI está pensando...';

  @override
  String chatThinkingWithName(String name) {
    return '$name está pensando...';
  }

  @override
  String get chatSendButton => 'Enviar';

  @override
  String get chatSending => 'Enviando...';

  @override
  String chatAskAbout(String topic) {
    return 'Cuéntame más sobre mi $topic';
  }

  @override
  String get chatErrorGeneric =>
      'VaultAI no pudo responder ahora. Inténtalo de nuevo.';

  @override
  String get chatRetryButton => 'Reintentar';

  @override
  String get chatQuickSavedLogins => 'Accesos guardados';

  @override
  String get chatQuickMyFiles => 'Mis archivos';

  @override
  String get chatQuickMyPassport => 'Mi pasaporte';

  @override
  String get chatQuickWhatCanYouDo => '¿Qué puedes hacer?';

  @override
  String get chatCardShowRelated => 'Ver relacionados';

  @override
  String get chatCardTopFolders => 'Carpetas principales';

  @override
  String get chatCardRecentFiles => 'Archivos recientes';

  @override
  String get chatCardSearchDeeper => 'Buscar más profundo';

  @override
  String get chatCardKeepBoth => 'Conservar ambos';

  @override
  String get chatCardUpgradeStorage => 'Ampliar almacenamiento';

  @override
  String get unlockToSeeConcierge =>
      'Desbloquea una bóveda para ver tu asistente.';

  @override
  String get unlockToSeeExpiry =>
      'Desbloquea una bóveda para ver tus vencimientos.';

  @override
  String get unlockToSeeMemory =>
      'Desbloquea una bóveda para ver tu línea de memoria.';

  @override
  String get unlockToSeeRelationships =>
      'Desbloquea una bóveda para ver el gráfico de relaciones.';

  @override
  String get conciergeTitle => 'Asistente';

  @override
  String get conciergeSubtitle => 'Lo que VaultAI te sugiere mirar primero';

  @override
  String get conciergeLoading => 'Reuniendo información...';

  @override
  String get conciergeErrorPrefix =>
      'No se pudieron cargar los datos del asistente.';

  @override
  String get conciergeCriticalNow => 'Crítico ahora mismo';

  @override
  String get conciergeComingUp => 'Próximamente';

  @override
  String get conciergeRecommendations => 'Recomendaciones';

  @override
  String get conciergeTravelReady => 'Listo para viajar';

  @override
  String get conciergeTravelMostly => 'Casi listo';

  @override
  String get conciergeTravelAttention => 'Requiere atención';

  @override
  String get conciergeTravelReadyDetail =>
      'Pasaporte > 180 días, visa > 30 días.';

  @override
  String get conciergeTravelMostlyDetail =>
      'Falta pasaporte o visa, o están cerca de renovar.';

  @override
  String get conciergeTravelAttentionDetail =>
      'Renovación necesaria pronto - revisa pasaporte y visa.';

  @override
  String get conciergeRenewalTimeline =>
      'Cronograma de renovación (próximos 90 días)';

  @override
  String get conciergeTravelReadiness => 'Preparación para viajar';

  @override
  String get conciergeAllClear => 'Todo en orden.';

  @override
  String get conciergeAllClearSub =>
      'Nada urgente hoy. VaultAI vigila tus documentos y aparecerá aquí cualquier novedad.';

  @override
  String get conciergePostureSecurity => 'Seguridad';

  @override
  String get conciergePostureExpiring => 'Vencen';

  @override
  String get conciergePostureInheritance => 'Herencia';

  @override
  String get conciergePostureScoreHint =>
      'Toca para ver el centro de seguridad';

  @override
  String get conciergePostureNoData => 'sin datos';

  @override
  String get conciergePostureNothingTracked => 'Nada en seguimiento aún';

  @override
  String get conciergePostureAllFuture => 'Todo cómodamente futuro';

  @override
  String get conciergePostureFrozen => 'Bóveda congelada';

  @override
  String get conciergePostureConfigured => 'Emparejamiento configurado';

  @override
  String get conciergePostureUnset => 'Sin beneficiario aún';

  @override
  String get conciergePostureScoreNoData => 'sin datos';

  @override
  String get conciergeAskTravel => '¿Estoy listo para viajar?';

  @override
  String get conciergePassport => 'Pasaporte';

  @override
  String get conciergeVisa => 'Visa';

  @override
  String get conciergePassportNotOnFile => 'No registrado';

  @override
  String get conciergeNoExpiryDate => 'Sin fecha de vencimiento';

  @override
  String get conciergeExpired => 'Vencido';

  @override
  String get conciergeRenewSoon => 'Renovar pronto';

  @override
  String get conciergeComfortable => 'Cómodo';

  @override
  String get conciergeItem => 'elemento';

  @override
  String get conciergeItems => 'elementos';

  @override
  String get conciergeInheritanceFrozen => 'congelado';

  @override
  String get conciergeInheritanceConfigured => 'configurado';

  @override
  String get conciergeInheritanceUnset => 'sin configurar';

  @override
  String get expiryTitle => 'Vencimientos';

  @override
  String get expirySubtitle => 'Documentos y obligaciones que vencen pronto';

  @override
  String get expiryLoading => 'Leyendo alertas de vencimiento...';

  @override
  String get expiryErrorPrefix => 'No se pudieron cargar las alertas.';

  @override
  String get expiryEmptyTitle => 'Vas por delante de cada renovación.';

  @override
  String get expiryEmptySub =>
      'Sube pasaporte, visa, póliza o contrato y VaultAI hará seguimiento automático.';

  @override
  String get expiryNoneInWindow => 'Nada en este rango.';

  @override
  String expiryNoneInWindowSub(String window) {
    return 'No hay vencimientos en $window. Prueba un rango mayor.';
  }

  @override
  String get expiryWindow7d => '7 días';

  @override
  String get expiryWindow30d => '30 días';

  @override
  String get expiryWindow90d => '90 días';

  @override
  String get expiryWindowAll => 'Todo';

  @override
  String get expiryBucketCritical => 'Crítico';

  @override
  String get expiryBucketWarning => 'Aviso';

  @override
  String get expiryBucketInfo => 'Información';

  @override
  String expiryCountCritical(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count críticos',
      one: '1 crítico',
    );
    return '$_temp0';
  }

  @override
  String expiryCountWarning(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count avisos',
      one: '1 aviso',
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
  String get expiryToday => 'Hoy';

  @override
  String expiredAgo(int days) {
    return 'hace ${days}d';
  }

  @override
  String get expiryNoDate => 'sin fecha';

  @override
  String get expiryDays => 'restantes';

  @override
  String get expiryDaysExpires => 'vence';

  @override
  String get memoryTitle => 'Memoria';

  @override
  String get memorySubtitle =>
      'Una cronología de lo que VaultAI recuerda de tu vida';

  @override
  String get memoryLoading => 'Cargando tus recuerdos...';

  @override
  String get memoryErrorPrefix => 'No se pudo cargar la memoria.';

  @override
  String get memoryEmptyTitle => 'Sin recuerdos todavía.';

  @override
  String get memoryEmptySub =>
      'Dile a VaultAI qué recordar: \'recuerda que el cumpleaños de mi mamá es el 14 de febrero\'. Aparecerá aquí agrupado por tipo y fecha.';

  @override
  String get memoryNoMatchTitle => 'Sin resultados.';

  @override
  String get memoryNoMatchSub =>
      'Borra el filtro o la búsqueda para ver todos los recuerdos.';

  @override
  String get memorySearchHint => 'Buscar recuerdos...';

  @override
  String get memoryUndated => 'Sin fecha';

  @override
  String get memoryUnnamed => '(sin nombre)';

  @override
  String get memoryTypeIdentity => 'Identidad';

  @override
  String get memoryTypePeople => 'Personas';

  @override
  String get memoryTypeFamily => 'Familia';

  @override
  String get memoryTypeBusiness => 'Negocios';

  @override
  String get memoryTypeTravel => 'Viajes';

  @override
  String get memoryTypeProjects => 'Proyectos';

  @override
  String get memoryTypeGoals => 'Metas';

  @override
  String get memoryTypePlaces => 'Lugares';

  @override
  String get memoryTypeDates => 'Fechas';

  @override
  String get memoryTypeLifeEvent => 'Eventos de vida';

  @override
  String get memoryTypePreferences => 'Preferencias';

  @override
  String get memoryTypeNote => 'Notas';

  @override
  String memoryAskAbout(String key) {
    return '¿Qué sabes sobre $key?';
  }

  @override
  String get relationshipsTitle => 'Relaciones';

  @override
  String get relationshipsSubtitle =>
      'Documentos, cuentas y recuerdos que van juntos';

  @override
  String get relationshipsLoading => 'Mapeando tu bóveda...';

  @override
  String get relationshipsErrorPrefix =>
      'No se pudieron cargar las relaciones.';

  @override
  String get relationshipsEmptyTitle => 'Sin agrupaciones aún.';

  @override
  String get relationshipsEmptySub =>
      'Sube un pasaporte, visa, factura o contrato y VaultAI empezará a agrupar documentos por viaje, identidad, impuestos, familia y más.';

  @override
  String get relationshipsNoMatchTitle => 'Sin resultados.';

  @override
  String get relationshipsNoMatchSub => 'Borra el filtro o la búsqueda.';

  @override
  String get relationshipsSearchHint =>
      'Buscar documentos, elementos o relaciones...';

  @override
  String get relationshipsTypeTravel => 'Grupo de viajes';

  @override
  String get relationshipsTypeIdentity => 'Grupo de identidad';

  @override
  String get relationshipsTypeBusiness => 'Grupo de negocios';

  @override
  String get relationshipsTypeFinance => 'Grupo financiero';

  @override
  String get relationshipsTypeTax => 'Grupo de impuestos';

  @override
  String get relationshipsTypeMedical => 'Grupo médico';

  @override
  String get relationshipsTypeFamily => 'Grupo familiar';

  @override
  String get relationshipsTypeSecurity => 'Grupo de seguridad';

  @override
  String get relationshipsTypeMedia => 'Grupo de medios';

  @override
  String get relationshipsTypeInheritance => 'Grupo de herencia';

  @override
  String get relationshipsEndpointFile => 'Archivo';

  @override
  String get relationshipsEndpointItem => 'Elemento';

  @override
  String relationshipsAskRelated(String label) {
    return '¿Qué se relaciona con «$label»?';
  }

  @override
  String get settingsTitle => 'Ajustes';

  @override
  String get settingsSubtitle =>
      'Gestiona el almacenamiento de tu bóveda y tu plan.';

  @override
  String get settingsLanguage => 'Idioma';

  @override
  String get settingsLanguageHint =>
      'Elige el idioma de VaultAI. Afecta las etiquetas y las respuestas del chat.';

  @override
  String get settingsLanguageAuto => 'Auto (sistema)';

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
      'Buscar idioma (p. ej. «Français», «French»)';

  @override
  String settingsLanguageAutoResolvedTo(String label) {
    return 'Sistema: $label';
  }

  @override
  String get settingsLanguageSelected => 'Seleccionado';

  @override
  String settingsLanguagePartialNotice(String name) {
    return 'VaultAI Chat responderá en $name. La interfaz sigue en inglés mientras se completa la traducción.';
  }

  @override
  String get settingsLanguagePopular => 'Populares';

  @override
  String get settingsLanguageAllLanguages => 'Todos los idiomas';

  @override
  String settingsLanguageShowAll(int count) {
    return 'Mostrar todos los idiomas ($count más)';
  }

  @override
  String get settingsLanguageShowFewer => 'Mostrar menos';

  @override
  String settingsLanguageNoMatches(String query) {
    return 'Ningún idioma coincide con «$query»';
  }

  @override
  String get settingsCurrentPlan => 'Plan actual';

  @override
  String get settingsLoadingPlan => 'Cargando plan…';

  @override
  String get settingsBuyMoreStorage => 'Comprar más almacenamiento';

  @override
  String get settingsManageSubscription => 'Gestionar suscripción';

  @override
  String get settingsDeleteVaultTile => 'Eliminar bóveda';

  @override
  String get settingsDeleteVaultTileHint =>
      'Elimina tu bóveda permanentemente. Requiere frase de confirmación y PIN.';

  @override
  String get securityCenterTitle => 'Centro de seguridad';

  @override
  String get devicesTitle => 'Dispositivos';

  @override
  String get filesTitle => 'Archivos';

  @override
  String get loginsTitle => 'Accesos';

  @override
  String get inheritanceTitle => 'Herencia';

  @override
  String get dashboardTitle => 'Panel';

  @override
  String get priorityHigh => 'ALTA';

  @override
  String get priorityMedium => 'MEDIA';

  @override
  String get priorityLow => 'BAJA';

  @override
  String get helpCenterTitle => 'Ayuda y FAQ';

  @override
  String get helpCenterSubtitle =>
      'Respuestas a preguntas comunes sobre VaultAI. Busca abajo o navega por categoría — el asistente IA responde desde el mismo conjunto de temas.';

  @override
  String get helpCenterEmpty => 'Sin temas coincidentes';

  @override
  String get helpCenterEmptyBody =>
      'Prueba con otro término o elige una categoría.';

  @override
  String get helpCenterSupportNote =>
      'El soporte al cliente en vivo aún no está disponible. Usa el centro de ayuda o pregunta a VaultAI Chat.';

  @override
  String get helpCenterPublicHint =>
      'Estás viendo el centro de ayuda público. Inicia sesión para preguntar a VaultAI y ver detalles de la cuenta.';

  @override
  String get helpCenterSearchHint => 'Buscar en ayuda (p. ej. «monero», «PIN»)';

  @override
  String get helpCenterClearSearch => 'Limpiar búsqueda';

  @override
  String get helpCenterSignInToAsk => 'Inicia sesión para preguntar a VaultAI';

  @override
  String get helpCategoryGettingStarted => 'Primeros pasos';

  @override
  String get helpCategorySecurity => 'Seguridad';

  @override
  String get helpCategoryFiles => 'Archivos';

  @override
  String get helpCategorySecureItems => 'Elementos seguros';

  @override
  String get helpCategoryIds => 'Documentos de identidad';

  @override
  String get helpCategoryCrypto => 'Crypto Vault';

  @override
  String get helpCategoryBilling => 'Facturación';

  @override
  String get helpCategoryTroubleshooting => 'Resolución de problemas';

  @override
  String get deleteVaultTitle => '¿Eliminar la bóveda permanentemente?';

  @override
  String get deleteVaultBody =>
      'Eliminar tu bóveda borra permanentemente tus datos de VaultAI, incluidos archivos, elementos seguros, accesos, documentos de identidad, registros cifrados de Crypto Vault y metadatos asociados.';

  @override
  String get deleteVaultCryptoWarning =>
      'Eliminar la bóveda no mueve ni elimina activos crypto en la blockchain. Si no has hecho copia de seguridad de tu billetera fuera de VaultAI, eliminar los registros cifrados puede causar pérdida de acceso a esos fondos.';

  @override
  String get deleteVaultPhraseInstruction =>
      'Escribe la frase DELETE MY VAULT exactamente para confirmar:';

  @override
  String get deleteVaultPhraseMustMatch =>
      'La frase debe coincidir exactamente.';

  @override
  String get deleteVaultPinInstruction => 'Ingresa tu PIN para confirmar:';

  @override
  String get deleteVaultPinHint => 'PIN';

  @override
  String get deleteVaultConfirmButton => 'Eliminar bóveda';

  @override
  String get deleteVaultErrorInvalidPin => 'PIN incorrecto.';

  @override
  String get deleteVaultErrorInvalidPhrase =>
      'Escribe la frase exacta para confirmar.';

  @override
  String get deleteVaultErrorExpired =>
      'Solicitud de eliminación caducada. Inténtalo de nuevo.';

  @override
  String get deleteVaultErrorNotTrusted =>
      'Este dispositivo no es de confianza. Apruébalo primero.';

  @override
  String get deleteVaultErrorGeneric => 'No se pudo completar la eliminación.';

  @override
  String get errorRateLimited =>
      'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.';

  @override
  String get errorRateLimitedPin =>
      'Demasiados PIN incorrectos. Inténtalo más tarde.';

  @override
  String errorRateLimitedWait(int seconds) {
    return 'Demasiados intentos. Espera ${seconds}s';
  }

  @override
  String get errorSessionExpired => 'Sesión expirada. Inicia sesión de nuevo.';

  @override
  String get errorInactivityLocked => 'Bóveda bloqueada por inactividad.';

  @override
  String get errorVaultFrozen => 'Esta bóveda está congelada.';

  @override
  String get errorDeviceNotTrusted =>
      'Este dispositivo no es de confianza. Apruébalo primero.';

  @override
  String get errorGenericPrefix => 'Algo salió mal.';

  @override
  String get errorNetwork =>
      'Error de red. Verifica tu conexión e inténtalo de nuevo.';

  @override
  String get errorRefreshFailed =>
      'Falló la actualización. Inténtalo de nuevo.';

  @override
  String get snackDeviceApproved => 'Dispositivo aprobado.';

  @override
  String get snackDeviceRevoked => 'Dispositivo revocado.';

  @override
  String snackDeviceApproveFailed(String error) {
    return 'Falló la aprobación: $error';
  }

  @override
  String snackDeviceRevokeFailed(String error) {
    return 'Falló la revocación: $error';
  }

  @override
  String get snackAddressCopied => 'Dirección copiada';

  @override
  String get snackSendCooldown =>
      'Demasiados intentos de envío recientes. Espera un momento.';

  @override
  String get storagePageTitle => 'Almacenamiento';

  @override
  String get storageNoDataAvailable => 'Sin datos de almacenamiento.';

  @override
  String get storageUsageHeading => 'Uso de almacenamiento';

  @override
  String get storageAccountHeading => 'Cuenta';

  @override
  String get storageFreeTier => 'Nivel gratuito';

  @override
  String get storageNeedMoreSpace => '¿Necesitas más espacio?';

  @override
  String get storageGrandfathered => 'Almacenamiento preservado';

  @override
  String get storageAdditionalPricing => 'Precios de almacenamiento adicional';

  @override
  String get storagePlanLower => 'Plan inferior';

  @override
  String get storageCouldNotLoad => 'No se pudo cargar el almacenamiento';

  @override
  String get storageRefreshNow => 'Actualizar';

  @override
  String get securityManageDevices => 'Gestionar dispositivos';

  @override
  String get securityAnalyzePasswordsTitle => '¿Analizar contraseñas?';

  @override
  String get securityEnterVaultPin => 'Ingresa el PIN de la bóveda';

  @override
  String get securityAnalyzeButton => 'Analizar';

  @override
  String get securityAnalyzeMore => 'Analizar más';

  @override
  String get devicePendingRequestSelfApproval => 'Solicitar autoaprobación';

  @override
  String get devicePendingFinalize => 'Finalizar';

  @override
  String get devicePendingCancelApproval => 'Cancelar aprobación';

  @override
  String get devicePendingCheckAgain => 'Comprobar de nuevo';

  @override
  String get devicePendingRegisterDevice => 'Registrar este dispositivo';

  @override
  String get devicePendingDiagnoseTrust => 'Diagnosticar confianza';

  @override
  String get devicePendingCopyDiagnostics => 'Copiar diagnósticos';

  @override
  String get devicePendingDiagnosticsCopied => 'Diagnósticos copiados.';

  @override
  String get cryptoLiteCouldNotLoadRecord =>
      'No se pudo cargar el registro. Inténtalo de nuevo.';

  @override
  String get cryptoLiteAddressFormatMismatchTitle =>
      'El formato de dirección no coincide';

  @override
  String get cryptoLiteSaveAnyway => 'Guardar de todos modos';

  @override
  String get cryptoLiteEditMetadata => 'Editar metadatos';

  @override
  String get cryptoLiteEditBackupMetadata => 'Editar metadatos de copia';

  @override
  String get cryptoOpenAsset => 'Abrir activo';

  @override
  String get cryptoMoneroScannerStatus => 'Estado del escáner Monero';

  @override
  String get cryptoOpenMonero => 'Abrir Monero';

  @override
  String get cryptoSendDraftHeading => 'Borrador de envío';

  @override
  String get cryptoOpenSendFlow => 'Abrir envío';

  @override
  String get cryptoRetryFailed => 'Reintentar';

  @override
  String get cryptoOpenCryptoVault => 'Abrir Crypto Vault';

  @override
  String get cryptoCopyAddress => 'Copiar dirección';

  @override
  String get cryptoTransactionsTab => 'Transacciones';

  @override
  String get cryptoContinueToPin => 'Continuar al PIN';

  @override
  String get cryptoCopyDestination => 'Copiar destino';

  @override
  String get cryptoSignatureCopied => 'Firma copiada';

  @override
  String get cryptoCopySignature => 'Copiar firma';

  @override
  String get cryptoTxIdCopied => 'ID de transacción copiado';

  @override
  String get cryptoCopyTxId => 'Copiar ID tx';

  @override
  String get vaultCardOverview => 'Resumen de la bóveda';

  @override
  String get vaultCardOpenVault => 'Abrir bóveda';

  @override
  String get vaultCardDocumentSummary => 'Resumen del documento';

  @override
  String get vaultCardGeneratedLogins => 'Accesos generados';

  @override
  String get vaultCardBilling => 'Facturación';

  @override
  String get vaultCardBrowseAllHelp => 'Explorar todos los temas de ayuda';

  @override
  String get secureItemCopyUsername => 'Copiar usuario';

  @override
  String get secureItemCopyValue => 'Copiar valor';

  @override
  String get notificationsTitle => 'Notificaciones';

  @override
  String get notificationsMarkAllRead => 'Marcar todo como leído';

  @override
  String get landingHowItWorks => 'Cómo funciona';

  @override
  String get authDontHaveVault => '¿No tienes bóveda? Crea una';

  @override
  String get authAlreadyHaveVault => '¿Ya tienes bóveda? Inicia sesión';

  @override
  String get authUseAnotherVault => 'Usar otra bóveda';

  @override
  String get authLogInAnotherVault => 'Iniciar sesión en otra bóveda';

  @override
  String get snackDeviceTrusted => 'Nuevo dispositivo aprobado.';

  @override
  String get confirmEraseTitle => '¿Borrar datos irrecuperables?';

  @override
  String get confirmEraseButton => 'Borrar y continuar';

  @override
  String inheritanceCancelPendingTransferTitle(String label) {
    return '¿Cancelar la transferencia pendiente a «$label»?';
  }

  @override
  String get inheritanceCancelTransfer => 'Cancelar transferencia';

  @override
  String inheritanceClaimTitle(String label) {
    return 'Reclamar «$label»';
  }

  @override
  String inheritanceRequestTransferTitle(String label) {
    return '¿Solicitar transferencia de «$label»?';
  }

  @override
  String inheritanceRemoveTitle(String label) {
    return '¿Quitar «$label»?';
  }

  @override
  String get inheritanceStartCountdown => 'Iniciar cuenta regresiva de 30 días';

  @override
  String get inheritanceAddBeneficiary => 'Agregar beneficiario';

  @override
  String get inheritanceEnterCode => 'Ingresar código';

  @override
  String get inheritanceRequestTransfer => 'Solicitar transferencia';

  @override
  String get filesChooseStorage => 'Elegir origen';

  @override
  String get filesUploadFile => 'Subir archivo';

  @override
  String get filesUploadPhoto => 'Subir foto';

  @override
  String get filesUploadVideo => 'Subir video';

  @override
  String get filesUploadAudio => 'Subir audio';

  @override
  String get filesUploadFolder => 'Subir carpeta';

  @override
  String get filesRecordVoice => 'Grabar voz';

  @override
  String get filesRecordVideo => 'Grabar video';

  @override
  String get deleteVaultSignInRequired =>
      'Vuelve a iniciar sesión para eliminar tu bóveda.';

  @override
  String get deleteVaultSuccess => 'Tu bóveda ha sido eliminada.';

  @override
  String get dashboardActiveVault => 'Bóveda activa:';
}
