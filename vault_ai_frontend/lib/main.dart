import 'dart:async';
import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:math';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:crypto/crypto.dart' show sha256;
import 'package:cryptography/cryptography.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart'
    show
        kIsWeb,
        kReleaseMode,
        kDebugMode,
        defaultTargetPlatform,
        TargetPlatform,
        visibleForTesting,
        debugPrint,
        immutable;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_web_plugins/url_strategy.dart' as web_plugins;

import 'route_guard.dart';
import 'services/inheritance_reveal_classify.dart' as inh_classify;
import 'package:http/http.dart' as http;
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'logins_page.dart';
import 'api_client.dart';
import 'chunked_aead.dart';
import 'services/inheritance_credentials.dart' as inh_cred;
import 'services/legacy_adoption.dart' as legacy_adopt;
import 'services/metadata_migration_client.dart' as mmc;
import 'services/native_secure_store.dart';
import 'services/session_termination.dart' as st;
import 'services/opaque_client.dart'
    if (dart.library.io) 'services/opaque_client_native.dart';
import 'services/vault_handle.dart' as vh;
import 'services/zk_active_mvk.dart' as zk_mvk_store;
import 'services/credential_v2.dart';
import 'services/credential_v2_qa_diagnostics.dart';
import 'services/credential_v2_api.dart';
import 'services/credential_v2_migration.dart';
import 'services/credential_v2_repository.dart';
import 'services/zk_active_sk_vault.dart' as zk_sk_store;
import 'services/vault_key_hierarchy.dart' as vk_hier;
import 'services/zk_auth_service.dart';
import 'services/billing_me_diagnostic.dart';
import 'services/upload_queue.dart';
import 'services/attachment_title_binding.dart';
import 'services/native_media_capture.dart';
import 'services/recording_storage.dart';
import 'services/content_hash.dart';
import 'services/vault_local_file_lookup.dart';
import 'services/monero_scanner.dart';
import 'services/monero_wallet.dart';
import 'services/vault_chat_stream_parser.dart' as vcs_parser;
import 'ui/chat/duplicate_dialog.dart';
import 'ui/chat/storage_limit_dialog.dart';
import 'services/folder_picker.dart';
import 'ui/folder_browser/folder_browser.dart';
import 'device_id.dart';
import 'device_pending_page.dart';
import 'devices_page.dart';
import 'security_center_page.dart';
import 'help_center_page.dart' as hc;
import 'privacy_policy_page.dart';
import 'delete_vault_flow.dart';
import 'perf/frontend_cache.dart' as perf_cache;
import 'storage_page.dart';
import 'media_player.dart';
import 'pdf_preview.dart';
import 'file_downloader.dart';
import 'video_recorder.dart';
import 'web_video_recorder_dialog.dart';

import 'ui/theme.dart';
import 'ui/responsive.dart';
import 'ui/chat/ask_brain_handoff.dart';
import 'ui/chat/chat_message_list.dart';
import 'ui/chat/chat_models.dart';
import 'ui/chat/chat_failure_localization.dart';
import 'ui/chat/chat_request_lifecycle.dart';
import 'ui/secure_item_detail.dart';
import 'ui/chat/vault_file_view_messages.dart';

import 'ui/dashboards/concierge_page.dart';
import 'ui/dashboards/expiry_page.dart';

import 'ui/dashboards/memory_page.dart';

import 'services/crypto_chat_live_cache.dart';
import 'services/app_release_controller_scope.dart';
import 'ui/app_release_update_banner.dart';
import 'ui/crypto_vault_locked_card.dart';
import 'ui/crypto_wallet_engine_page.dart';

import 'ui/crypto_wallet_engine_receive_panel.dart';
import 'ui/crypto_wallet_engine_send_panel.dart';
import 'ui/crypto_wallet_engine_sheet_chrome.dart';
import 'ui/chat/crypto_wallet_action_card.dart';

import 'ui/crypto_receive_panel.dart';

import 'l10n/app_localizations.dart';
import 'i18n/language_registry.dart';

// Whether the build was invoked with an explicit
//   --dart-define=BACKEND_BASE_URL=...
// Compile-time constant per Dart's bool.hasEnvironment contract.
const bool _kHasBackendBaseUrlOverride =
    bool.hasEnvironment('BACKEND_BASE_URL');

// Compile-time BACKEND_BASE_URL. If the build passed
//   --dart-define=BACKEND_BASE_URL=https://foo
// this holds "https://foo"; otherwise it holds the documented
// dev-fallback default 'http://localhost:8000'. The presence of
// the defaultValue string here is asserted by
// test/production_deployment_readiness_test.dart (R3) so dev
// builds keep working without --dart-define.
const String _kBackendBaseUrlFromEnv = String.fromEnvironment(
  'BACKEND_BASE_URL',
  defaultValue: 'http://localhost:8000',
);

// Production API host, baked in so a plain
//   flutter build web    --release          (web  release)
//   flutter build appbundle --release       (mobile release)
// cannot ship a build that silently talks to the dev fallback. The
// release-mode guard in main() asserts backendBaseUrl.startsWith(
// 'https://'). Web AND mobile release both hit the same FastAPI host
// today (https://api.svaultai.com); if they ever need to diverge,
// introduce a separate `_kWebProductionBaseUrl` and re-gate on
// `kIsWeb` - do NOT reintroduce a `kIsWeb` gate that leaves web
// release resolving to the localhost fallback, which trips the
// startup HTTPS guard and crashes app.svaultai.com with a black
// screen.
const String _kProductionApiBaseUrl = 'https://api.svaultai.com';

/// Resolves at first access; called from every network path.
///
/// Precedence:
///   1. If the build passed `--dart-define=BACKEND_BASE_URL=...`, use
///      it verbatim (staging / preview / CI overrides).
///   2. Else, on ANY release build (mobile or web), use the
///      production API host `https://api.svaultai.com`. This is the
///      release-safety net enforced by R3 and by the HTTPS guard at
///      the top of `main()`.
///   3. Else, use the compile-time default (dev/debug + local
///      `flutter run` + web without an override).
String get backendBaseUrl {
  if (_kHasBackendBaseUrlOverride) return _kBackendBaseUrlFromEnv;
  if (kReleaseMode) return _kProductionApiBaseUrl;
  return _kBackendBaseUrlFromEnv;
}

const int kVaultStorageLimitBytes = 1024 * 1024 * 1024;

enum BillingLoadState { initial, loading, loaded, error }

const int kChunkedUploadThresholdBytes = int.fromEnvironment(
  'CHUNKED_UPLOAD_THRESHOLD_BYTES',
  defaultValue: 4 * 1024 * 1024,
);

const int kChunkedUploadChunkBytes = int.fromEnvironment(
  'CHUNKED_UPLOAD_CHUNK_BYTES',
  defaultValue: 4 * 1024 * 1024,
);

const bool kCryptoWalletEngineEnabled = bool.fromEnvironment(
  'CRYPTO_WALLET_ENGINE_ENABLED',
  defaultValue: true,
);

const List<String> kAcceptedAudioExtensions = [
  'mp3',
  'm4a',
  'wav',
  'aac',
  'ogg',
];

String generateVoiceRecordingFilename({
  required DateTime now,
  String extension = 'm4a',
}) {
  String two(int n) => n.toString().padLeft(2, '0');
  final date = '${now.year.toString().padLeft(4, '0')}-'
      '${two(now.month)}-${two(now.day)}';
  final time = '${two(now.hour)}-${two(now.minute)}-${two(now.second)}';
  return 'Voice recording - $date $time.$extension';
}

class UploadCancelledException implements Exception {
  const UploadCancelledException();
  @override
  String toString() => 'UploadCancelledException';
}

final GlobalKey<NavigatorState> rootNavigatorKey = GlobalKey<NavigatorState>();

final GlobalKey<ScaffoldMessengerState> rootScaffoldMessengerKey =
    GlobalKey<ScaffoldMessengerState>();

Future<void> openHelpCenter(
  BuildContext context, {
  required hc.HelpCenterMode mode,
}) {
  return Navigator.of(context).push<void>(
    MaterialPageRoute(
      settings: RouteSettings(
        name: mode == hc.HelpCenterMode.public
            ? '/help-and-faq-public'
            : '/help-and-faq',
      ),
      builder: (routeCtx) {
        return Scaffold(
          key: Key(mode == hc.HelpCenterMode.public
              ? 'help_center_route_public'
              : 'help_center_route_signed_in'),
          backgroundColor: const Color(0xFF181818),
          appBar: AppBar(
            backgroundColor: const Color(0xFF181818),
            title: const Text(hc.kHelpCenterTitle),
            leading: IconButton(
              key: const Key('help_center_route_back'),
              icon: const Icon(Icons.arrow_back),
              onPressed: () => Navigator.of(routeCtx).maybePop(),
            ),
          ),
          body: hc.HelpCenterPage(
            mode: mode,
            onRequireSignIn: mode == hc.HelpCenterMode.public
                ? () {
                    Navigator.of(routeCtx).pop();
                    Navigator.of(context).pushNamed('/login');
                  }
                : null,
          ),
        );
      },
    ),
  );
}

String? _guessMimeTypeFromName(String name) {
  final lower = name.toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.webp')) return 'image/webp';
  if (lower.endsWith('.gif')) return 'image/gif';
  if (lower.endsWith('.bmp')) return 'image/bmp';
  if (lower.endsWith('.pdf')) return 'application/pdf';
  if (lower.endsWith('.txt')) return 'text/plain';
  if (lower.endsWith('.csv')) return 'text/csv';
  if (lower.endsWith('.json')) return 'application/json';
  if (lower.endsWith('.mp4')) return 'video/mp4';
  if (lower.endsWith('.mov')) return 'video/quicktime';
  if (lower.endsWith('.webm')) return 'video/webm';
  if (lower.endsWith('.mkv')) return 'video/x-matroska';
  if (lower.endsWith('.avi')) return 'video/x-msvideo';
  if (lower.endsWith('.mp3')) return 'audio/mpeg';
  if (lower.endsWith('.m4a')) return 'audio/mp4';
  if (lower.endsWith('.wav')) return 'audio/wav';
  if (lower.endsWith('.ogg')) return 'audio/ogg';
  if (lower.endsWith('.aac')) return 'audio/aac';
  if (lower.endsWith('.docx')) {
    return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  }
  if (lower.endsWith('.xlsx')) {
    return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  }
  return 'application/octet-stream';
}

bool _isImageMime(String? mime) =>
    (mime ?? '').toLowerCase().startsWith('image/');
bool _isVideoMime(String? mime) =>
    (mime ?? '').toLowerCase().startsWith('video/');
bool _isAudioMime(String? mime) =>
    (mime ?? '').toLowerCase().startsWith('audio/');

bool _isTextPreviewable(String? mime, String filename) {
  final m = (mime ?? '').toLowerCase();
  final lower = filename.toLowerCase();
  return m.startsWith('text/') ||
      m == 'application/json' ||
      lower.endsWith('.txt') ||
      lower.endsWith('.csv') ||
      lower.endsWith('.json');
}

class _BillingLoadingCard extends StatelessWidget {
  final String label;
  const _BillingLoadingCard({required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const SizedBox(
          width: 18,
          height: 18,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: Color(0xFFB4B4B4),
          ),
        ),
        const SizedBox(width: 12),
        Text(
          label,
          style: const TextStyle(
            color: Color(0xFFB4B4B4),
            fontSize: 15,
          ),
        ),
      ],
    );
  }
}

class _BillingErrorCard extends StatelessWidget {
  final VoidCallback onRetry;
  const _BillingErrorCard({required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(
          Icons.cloud_off_outlined,
          color: Color(0xFFEFB66B),
          size: 22,
        ),
        const SizedBox(width: 10),
        const Flexible(
          child: Text(
            'Storage plan unavailable',
            style: TextStyle(
              color: Color(0xFFEFB66B),
              fontSize: 15,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(width: 12),
        TextButton(
          onPressed: onRetry,
          style: TextButton.styleFrom(
            foregroundColor: const Color(0xFFE6E6E6),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            minimumSize: Size.zero,
            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
          child: const Text('Retry'),
        ),
      ],
    );
  }
}

String _formatBytes(int bytes) {
  if (bytes >= 1024 * 1024 * 1024) {
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
  }
  if (bytes >= 1024 * 1024) {
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
  if (bytes >= 1024) {
    return '${(bytes / 1024).toStringAsFixed(1)} KB';
  }
  return '$bytes B';
}

enum _DashboardSection {
  dashboard,
  chat,
  files,
  logins,

  cryptoVault,
  concierge,
  expiry,
  memory,
  inheritance,
  settings,
}

typedef _Msg = ChatMessage;

class ChatAttachmentPanel extends StatelessWidget {
  final int count;

  final Widget Function(BuildContext context, int index) itemBuilder;

  final VoidCallback? onClear;

  final bool isMobile;

  static const double maxHeightDesktop = 240;
  static const double maxHeightMobile = 180;

  const ChatAttachmentPanel({
    super.key,
    required this.count,
    required this.itemBuilder,
    required this.isMobile,
    this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    final maxHeight = isMobile ? maxHeightMobile : maxHeightDesktop;
    return Container(
      margin: EdgeInsets.fromLTRB(isMobile ? 10 : 16, 0, isMobile ? 10 : 16, 0),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF2F2F2F),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ConstrainedBox(
            constraints: BoxConstraints(maxHeight: maxHeight),
            child: Scrollbar(
              child: ListView.builder(
                shrinkWrap: true,
                padding: EdgeInsets.zero,
                itemCount: count,
                itemBuilder: itemBuilder,
              ),
            ),
          ),
          Row(
            children: [
              Expanded(
                child: Text(
                  '$count attachment(s) ready',
                  style:
                      const TextStyle(fontSize: 12, color: Color(0xFFB4B4B4)),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.clear, size: 16),
                onPressed: onClear,
                tooltip: 'Clear attachments',
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _UploadContext {
  final VaultAIClient client;
  final String vaultName;
  final String pin;
  final String authToken;
  final List<int>? keyBytes;
  final String? accompanyingText;
  final bool isBatchUpload;
  final int uploadSafetyCapBytes;

  final String? importId;

  const _UploadContext({
    required this.client,
    required this.vaultName,
    required this.pin,
    required this.authToken,
    required this.keyBytes,
    required this.accompanyingText,
    required this.isBatchUpload,
    required this.uploadSafetyCapBytes,
    this.importId,
  });
}

final Random _attachmentIdRand = Random();

String _newAttachmentId() {
  final t = DateTime.now().microsecondsSinceEpoch;
  final r = _attachmentIdRand.nextInt(1 << 30);
  return 'att_${t}_$r';
}

class _Attachment {
  final String id;
  final String name;
  final String? displayName;
  final String kind;
  final String? mimeType;
  final int size;

  final Future<Uint8List> Function() readBytes;

  final String? relativePath;

  String? importId;

  String? uploadedFileId;
  bool uploaded;

  _Attachment({
    required this.id,
    required this.name,
    required this.kind,
    required this.size,
    required this.readBytes,
    this.displayName,
    this.mimeType,
    this.relativePath,
    this.importId,
    this.uploadedFileId,
    this.uploaded = false,
  });

  _Attachment copy({String? displayName}) {
    return _Attachment(
      id: id,
      name: name,
      displayName: displayName ?? this.displayName,
      kind: kind,
      size: size,
      readBytes: readBytes,
      mimeType: mimeType,
      relativePath: relativePath,
      importId: importId,
      uploadedFileId: uploadedFileId,
      uploaded: uploaded,
    );
  }
}

class _UploadAttachmentsOutcome {
  final List<String> uploadedIds;
  final bool autoNamedAny;

  const _UploadAttachmentsOutcome({
    required this.uploadedIds,
    required this.autoNamedAny,
  });
}

class _OverviewCardData {
  final String title;
  final String value;
  final IconData icon;
  final Color iconColor;
  final Color bgColor;

  const _OverviewCardData({
    required this.title,
    required this.value,
    required this.icon,
    required this.iconColor,
    required this.bgColor,
  });
}

class VaultRecoveryInfo {
  final String? vaultName;
  final int itemCount;
  final int fileCount;

  const VaultRecoveryInfo({
    this.vaultName,
    this.itemCount = 0,
    this.fileCount = 0,
  });

  factory VaultRecoveryInfo.fromMap(Map<String, dynamic>? map) {
    if (map == null) return const VaultRecoveryInfo();
    return VaultRecoveryInfo(
      vaultName: map['vault_name']?.toString(),
      itemCount: (map['item_count'] as num?)?.toInt() ?? 0,
      fileCount: (map['file_count'] as num?)?.toInt() ?? 0,
    );
  }

  bool get isEmpty => itemCount == 0 && fileCount == 0;
}

class _VaultStoredFile {
  final String id;
  final String fileName;
  final String? savedName;
  final String? contentType;
  final String? assetType;
  final int fileSize;
  final bool needsNaming;

  final String? relativePath;

  const _VaultStoredFile({
    required this.id,
    required this.fileName,
    required this.fileSize,
    this.savedName,
    this.contentType,
    this.assetType,
    this.needsNaming = false,
    this.relativePath,
  });

  factory _VaultStoredFile.fromJson(Map<String, dynamic> json) {
    return _VaultStoredFile(
      id: (json['id'] ?? '').toString(),
      fileName: (json['file_name'] ?? 'Unnamed file').toString(),
      savedName: json['saved_name']?.toString(),
      contentType: json['content_type']?.toString(),
      assetType: json['asset_type']?.toString(),
      fileSize: (json['file_size'] as num?)?.toInt() ?? 0,
      needsNaming: json['needs_naming'] == true,
      relativePath: json['relative_path']?.toString(),
    );
  }
}

void vlog(String tag, [Map<String, Object?>? data]) {
  if (kReleaseMode) return;
  final payload = data == null
      ? ''
      : data.entries
          .map((e) => '${e.key}=${_safeVlogValue(tag, e.key, e.value)}')
          .join(' ');

  print('[vault-debug] $tag $payload');
}

String _safeVlogValue(String tag, String key, Object? value) {
  if (value == null) return 'null';
  final lowerKey = key.toLowerCase();
  final lowerTag = tag.toLowerCase();
  final text = value.toString();

  if (lowerKey.contains('vault_id') ||
      lowerKey == 'vaultid' ||
      lowerKey.endsWith('vaultid')) {
    return inheritanceRevealIdFingerprint(text);
  }
  if (lowerKey.contains('vaultname') ||
      lowerKey.contains('vault_name') ||
      lowerKey.contains('username') ||
      lowerKey.contains('display_name') ||
      lowerKey.contains('token') ||
      lowerKey.contains('password') ||
      lowerKey.contains('secret') ||
      lowerKey.contains('ciphertext') ||
      lowerKey == 'body' ||
      lowerKey == 'prompt' ||
      lowerKey == 'query' ||
      (lowerTag.contains('vaultname') &&
          (lowerKey == 'prev' || lowerKey == 'next'))) {
    return '<redacted>';
  }
  if (lowerKey.contains('pin') &&
      lowerKey != 'pin_len' &&
      lowerKey != 'pinattempts') {
    return '<redacted>';
  }
  return text;
}

const bool kQaAuthDiagnosticsEnabled = bool.fromEnvironment(
  'VAULTAI_QA_AUTH_DIAGNOSTICS',
  defaultValue: false,
);

void releaseWebDiagnosticPrint(String message) {
  if (kReleaseMode && !kIsWeb && !kQaAuthDiagnosticsEnabled) return;
  // ignore: avoid_print
  print(message);
}

const bool kAuthTimingDiagnosticsEnabled = bool.fromEnvironment(
  'VAULTAI_AUTH_TIMING_DIAGNOSTICS',
  defaultValue: false,
);

void authTimingDiagnosticPrint(
  String stage,
  Duration elapsed, {
  bool success = true,
  int? httpStatus,
}) {
  if (!kAuthTimingDiagnosticsEnabled) return;
  final statusPart = httpStatus == null ? '' : ' http_status=$httpStatus';
  // ignore: avoid_print
  print(
    '[auth-timing] stage=$stage '
    'elapsed_ms=${elapsed.inMilliseconds} '
    'success=$success$statusPart',
  );
}

const String kAuthDeviceSafeError =
    'Sign in could not be completed on this device. Please try again.';
const String kUnlockDeviceSafeError =
    'Unlock could not be completed on this device. Please try again.';

@visibleForTesting
bool shouldBypassPublicLandingForAuth({
  bool? isWeb,
  TargetPlatform? platform,
}) {
  final web = isWeb ?? kIsWeb;
  final target = platform ?? defaultTargetPlatform;
  return !web && target == TargetPlatform.android;
}

void debugAuthFailureTrace(
  String tag,
  Object error,
  StackTrace stack, {
  String? step,
}) {
  if (!kDebugMode) return;
  final prefix = step == null ? '' : ' step=$step';
  debugPrint('[$tag]$prefix type=${error.runtimeType}');
  debugPrintStack(label: '[$tag] stack', stackTrace: stack);
}

Future<void> main() async {
  if (kReleaseMode && !backendBaseUrl.startsWith('https://')) {
    throw StateError(
      'BACKEND_BASE_URL must use https:// in release builds. '
      'Got "$backendBaseUrl". Rebuild with '
      '--dart-define=BACKEND_BASE_URL=https://your-api.example.com',
    );
  }

  if (kIsWeb) {
    web_plugins.setUrlStrategy(web_plugins.PathUrlStrategy());
  }

  late final AppState appState;
  var appStateReady = false;

  runZonedGuarded(
    () async {
      WidgetsFlutterBinding.ensureInitialized();

      String? webOrigin;
      try {
        if (kIsWeb) {
          webOrigin = Uri.base.origin;
        }
      } catch (_) {
        webOrigin = null;
      }
      vlog('boot', {
        'backendBaseUrl': backendBaseUrl,
        'kIsWeb': kIsWeb,
        'kReleaseMode': kReleaseMode,
        'webOrigin': webOrigin ?? '-',
      });

      // Must run before device-id creation: Keychain survives uninstall, so a
      // fresh install needs to purge stale identity/session records first.
      await NativeSecureStore.purgeIosKeychainAfterReinstallIfNeeded();
      final deviceId = await getOrCreateDeviceId();
      setApiClientDeviceId(deviceId);
      vlog('device-id-set', {
        'len': deviceId.length,
        'first8': deviceId.length >= 8 ? deviceId.substring(0, 8) : deviceId
      });

      appState = AppState();
      appStateReady = true;

      // Register ONE app-wide session-termination handler before
      // hydration so any coded 401 raised inside `hydrate()`'s
      // startup `/auth/me` call routes through this exact flow.
      // Idempotence lives in SessionTermination.instance itself;
      // this handler only knows how to clear state and navigate.
      st.SessionTermination.instance.setHandler((event) async {
        try {
          if (appState.vaultId != null) {
            _VaultCrypto.clearCache(appState.vaultId!);
          }
        } catch (_) {}
        await appState.clearSession(keepLastVaultName: true);
        try {
          rootScaffoldMessengerKey.currentState?.clearSnackBars();
          rootScaffoldMessengerKey.currentState?.showSnackBar(
            SnackBar(content: Text(event.userMessage)),
          );
        } catch (_) {}
        try {
          rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
            appState.lastVaultName != null ? '/unlock' : '/login',
            (_) => false,
          );
        } catch (_) {}
      });
      st.SessionTermination.instance.enablePeerTabListener();

      await appState.hydrate();

      runApp(
        ChangeNotifierProvider.value(
          value: appState,
          child: AppReleaseControllerScope(
            // The release manifest (/release.json) is emitted by
            // scripts/build-web-release.* into build/web/ and served
            // from the SAME origin the web app itself was loaded from,
            // i.e. https://app.svaultai.com — NOT from the FastAPI
            // backend at https://api.svaultai.com. On web we resolve
            // against the current window origin; on mobile/desktop
            // Uri.base.origin is undefined so we keep backendBaseUrl.
            baseUrl: kIsWeb ? Uri.base.origin : backendBaseUrl,
            child: SvaultaiApp(),
          ),
        ),
      );
    },
    (error, stack) {
      if (appStateReady && appState.handleApiException(error)) return;
      FlutterError.reportError(
        FlutterErrorDetails(exception: error, stack: stack),
      );
    },
  );
}

const String _kAppLocaleStorageKeyV1 = 'app_locale';
const String _kAppLocaleStorageKeyV2 = 'app_locale_v2';

class AppState extends ChangeNotifier {
  bool authed = false;

  // Per-file in-flight state. The chat card widgets watch AppState so
  // they can render a spinner + disable the button while a fetch is
  // running, and reject a second tap on the same file. Keeping this on
  // AppState (rather than local widget state) is deliberate — the file
  // list card is rebuilt whenever the chat message list changes, so
  // local state would be lost between rebuilds.
  final Set<String> _viewInFlight = <String>{};
  final Set<String> _downloadInFlight = <String>{};

  bool isFileViewInFlight(String fileId) => _viewInFlight.contains(fileId);
  bool isFileDownloadInFlight(String fileId) =>
      _downloadInFlight.contains(fileId);
  bool isFileBusy(String fileId) =>
      _viewInFlight.contains(fileId) || _downloadInFlight.contains(fileId);

  /// Read-only snapshots of the current in-flight file ids, so
  /// widgets can pass them down without exposing mutable state.
  Set<String> get viewInFlightFileIds =>
      Set<String>.unmodifiable(_viewInFlight);
  Set<String> get downloadInFlightFileIds =>
      Set<String>.unmodifiable(_downloadInFlight);

  /// Returns true if this call registered the lock (i.e. the file was
  /// not already in-flight). A false return means a concurrent tap won
  /// — the caller MUST NOT proceed with the fetch.
  bool beginFileView(String fileId) {
    if (fileId.isEmpty) return false;
    if (_viewInFlight.contains(fileId)) return false;
    _viewInFlight.add(fileId);
    notifyListeners();
    return true;
  }

  void endFileView(String fileId) {
    if (fileId.isEmpty) return;
    if (_viewInFlight.remove(fileId)) notifyListeners();
  }

  bool beginFileDownload(String fileId) {
    if (fileId.isEmpty) return false;
    if (_downloadInFlight.contains(fileId)) return false;
    _downloadInFlight.add(fileId);
    notifyListeners();
    return true;
  }

  void endFileDownload(String fileId) {
    if (fileId.isEmpty) return;
    if (_downloadInFlight.remove(fileId)) notifyListeners();
  }

  void clearAllFileInFlight() {
    if (_viewInFlight.isEmpty && _downloadInFlight.isEmpty) return;
    _viewInFlight.clear();
    _downloadInFlight.clear();
    notifyListeners();
  }

  /// True while a Show more request for the file list is in flight.
  /// Kept as a single boolean because there is only one "current"
  /// paginated file list per chat session — the backend tracks the
  /// offset in its active-entity store.
  bool _showMoreFilesInFlight = false;
  bool get showMoreFilesInFlight => _showMoreFilesInFlight;

  bool beginShowMoreFiles() {
    if (_showMoreFilesInFlight) return false;
    _showMoreFilesInFlight = true;
    notifyListeners();
    return true;
  }

  void endShowMoreFiles() {
    if (!_showMoreFilesInFlight) return;
    _showMoreFilesInFlight = false;
    notifyListeners();
  }

  bool _hydrated = false;
  bool get hydrated => _hydrated;

  Locale? _appLocale;
  Locale? get appLocale => _appLocale;

  static String Function() deviceLanguageCodeResolver =
      _defaultDeviceLanguageCode;

  static String _defaultDeviceLanguageCode() {
    try {
      return WidgetsBinding.instance.platformDispatcher.locale.languageCode;
    } catch (_) {
      return 'en';
    }
  }

  Locale? get shellLocale {
    if (_appLocale == null) return null;
    if (kFullyLocalisedCodes.contains(_appLocale!.languageCode)) {
      return _appLocale;
    }
    return const Locale('en');
  }

  String get effectiveLanguageCode {
    final manual = _appLocale?.languageCode;
    if (manual != null && isSupportedLanguageCode(manual)) {
      return manual;
    }
    String? device;
    try {
      device = deviceLanguageCodeResolver();
    } catch (_) {
      device = null;
    }
    if (device != null && isSupportedLanguageCode(device)) {
      return device;
    }
    return 'en';
  }

  String get chatReplyLanguageCode {
    final manual = _appLocale?.languageCode;
    if (manual != null && isSupportedLanguageCode(manual)) {
      return manual;
    }
    return 'en';
  }

  Future<void> setAppLocale(Locale? value) async {
    if (value != null && !isSupportedLanguageCode(value.languageCode)) {
      return;
    }
    _appLocale = value;
    final sp = await SharedPreferences.getInstance();
    if (value == null) {
      await sp.remove(_kAppLocaleStorageKeyV2);
    } else {
      await sp.setString(_kAppLocaleStorageKeyV2, value.languageCode);
    }
    notifyListeners();
  }

  Future<void> _loadAppLocale() async {
    try {
      final sp = await SharedPreferences.getInstance();

      if (sp.containsKey(_kAppLocaleStorageKeyV1)) {
        await sp.remove(_kAppLocaleStorageKeyV1);
      }

      final tag = sp.getString(_kAppLocaleStorageKeyV2);
      if (tag != null && tag.isNotEmpty) {
        final parts = tag.split('-');
        final loc =
            parts.length == 1 ? Locale(parts[0]) : Locale(parts[0], parts[1]);
        if (isSupportedLanguageCode(loc.languageCode)) {
          _appLocale = loc;
        } else {
          await sp.remove(_kAppLocaleStorageKeyV2);
          _appLocale = null;
        }
      }
    } catch (_) {
      _appLocale = null;
    }
  }

  bool _unlocked = false;

  /// Return true only when the app state carries EVERY component of
  /// a valid unlock context for the current vault:
  ///   * a persisted ``_unlocked`` flag from a successful PIN
  ///     verification or ZK login
  ///   * an authenticated session (``authed == true``)
  ///   * a concrete ``vaultId`` and ``vaultName`` (so we know which
  ///     vault the unlock applies to)
  ///   * a live entry in the process-local key cache for that
  ///     exact (``vaultId``, ``vaultName``) pair (so a subsequent
  ///     chat encrypt can succeed)
  ///
  /// The 2026-07-20 desync had ``_unlocked == true`` while the key
  /// cache had already been cleared (or was keyed under a stale
  /// ``vaultName``): every chat request then tripped
  /// ``InvalidVaultUnlockException`` on the backend but the UI still
  /// showed "unlocked". This getter closes that gap by refusing to
  /// report unlocked when the invariant is violated. Any code that
  /// clears the key cache no longer needs to remember to also flip
  /// ``_unlocked`` — the getter derives the truth.
  bool get unlocked {
    if (!_unlocked) return false;
    if (!authed) return false;
    final vId = vaultId;
    final vName = _vaultName;
    if (vId == null || vName == null) return false;
    if (!_VaultCrypto.hasKeyFor(vaultId: vId, vaultName: vName)) return false;
    return true;
  }

  set unlocked(bool value) {
    if (_unlocked == value) return;
    _unlocked = value;
    if (value) {
      _startInactivityWatch();
    } else {
      _stopInactivityWatch();
    }
  }

  static const Duration _kInactivityTimeout = Duration(minutes: 10);
  Timer? _inactivityTimer;
  DateTime _lastActivityAt = DateTime.now();

  final List<bool Function()> _keepAliveProbes = [];

  final List<void Function()> _shutdownHooks = [];

  String? sessionToken;

  /// One-time inheritance device-enrollment token minted after
  /// credential reveal. When present, the next successful login on
  /// the inherited account should POST it to
  /// ``/inheritance/device/consume`` to trust the current device
  /// without waiting for another approver.
  String? pendingInheritanceDeviceToken;

  String? vaultId;

  /// The human owner's visible name — an optional, human-facing
  /// label for the person who owns this vault (e.g. "Chosen
  /// Abdullahi"). Persisted as ``last_display_name`` through
  /// NativeSecureStore on native builds. Shown in the profile /
  /// account menu.
  ///
  /// This is NOT the vault name and NOT the AI's name — those are
  /// carried by [vaultName]. If missing at render time, UI
  /// surfaces use a neutral human-facing fallback like "Account".
  String? displayName;

  /// Deterministic hidden vault handle (``VLT-XXXX-...``) — the ZK
  /// backend lookup identifier. Populated at signup + login. Used
  /// by unlock-flow re-derivation and by inheritance / crypto-cache
  /// operations that need the stable internal identity. NEVER
  /// shown to the user. Distinct from [vaultName], which is the
  /// product-facing identity.
  String? vaultHandle;

  String? lastVaultName;

  String? _vaultName;
  String? get vaultName => _vaultName;
  set vaultName(String? value) {
    final prev = _vaultName;
    _vaultName = value;
    final currentVaultId = vaultId;

    vlog('appstate.vaultName.set', {
      'prev': prev,
      'next': value,
      'rebind': prev != value,
      'vault_id': currentVaultId,
    });
    if (currentVaultId == null) return;
    if (prev != null && prev != value) {
      vlog('appstate.vaultName.rebind-clears-cache', {
        'vault_id': currentVaultId,
        'prev': prev,
        'next': value,
      });
      _VaultCrypto.clearCache(currentVaultId);
    }
    if (value != null) {
      _VaultCrypto.setActiveVault(vaultId: currentVaultId, vaultName: value);
    }
  }

  int pinAttempts = 0;
  DateTime? lockoutUntil;
  String? lockMessage;

  int loginCount = 0;
  int cardCount = 0;
  int idCount = 0;
  int fileCount = 0;

  int storageUsedBytes = 0;
  int storageLimitBytes = kVaultStorageLimitBytes;

  int storagePendingBytes = 0;

  int billingEffectiveLimitBytes = 0;
  int billingBlockCount = 0;
  int billingPurchasedBytes = 0;
  int billingIncludedBytes = 0;

  BillingLoadState billingLoadState = BillingLoadState.initial;

  String? billingLoadError;

  int _billingRefreshSeq = 0;
  int _billingRefreshLatestApplied = 0;

  bool get isBillingLoaded => billingLoadState == BillingLoadState.loaded;

  bool get isBillingLoading =>
      billingLoadState == BillingLoadState.initial ||
      billingLoadState == BillingLoadState.loading;

  bool get isBillingError => billingLoadState == BillingLoadState.error;

  int get effectiveStorageLimitBytes {
    if (billingEffectiveLimitBytes > 0) return billingEffectiveLimitBytes;
    if (storageLimitBytes > 0) return storageLimitBytes;
    return kVaultStorageLimitBytes;
  }

  String get planLabel {
    if (billingBlockCount > 0 && billingPurchasedBytes > 0) {
      return '${formatBytes(billingPurchasedBytes)} Storage Plan';
    }
    return 'Free Vault Plan';
  }

  /// Crypto Vault is a paid-tier feature. The same rule is applied on
  /// the backend (`user_tier=="upgraded"` in
  /// vault_chat_crypto_data.populate_crypto_delegated_card_data) and on
  /// the destination page (`_buildCryptoVaultSection.isKnownNotUpgraded`).
  /// Chat cards, follow-up dispatch, and the direct route all consult
  /// this getter to keep the entitlement enforcement in one place.
  bool get isCryptoEntitled =>
      billingBlockCount > 0 && billingPurchasedBytes > 0;

  int uploadSafetyCapBytes = 100 * 1024 * 1024;

  VaultRecoveryInfo? recoveryInfo;

  List<Map<String, dynamic>> availableVaults = [];

  List<Map<String, dynamic>> notifications = [];
  int unreadNotificationCount = 0;

  Future<void> refreshNotifications() async {
    final token = sessionToken;
    if (token == null) return;
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.listNotifications(authToken: token);
      final raw = result['notifications'];
      notifications = raw is List
          ? raw
              .whereType<Map>()
              .map((m) => Map<String, dynamic>.from(m))
              .toList()
          : <Map<String, dynamic>>[];
      unreadNotificationCount = (result['unread_count'] as num?)?.toInt() ?? 0;
      notifyListeners();
    } catch (_) {}
  }

  Future<void> markNotificationRead(int? notificationId) async {
    final token = sessionToken;
    if (token == null) return;
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      await client.markNotificationRead(
        notificationId: notificationId,
        authToken: token,
      );
      await refreshNotifications();
    } catch (_) {}
  }

  Future<void> refreshAvailableVaults() async {
    final token = sessionToken;
    if (token == null) return;
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.listMyVaults(authToken: token);
      final raw = result['vaults'];
      if (raw is List) {
        availableVaults = raw
            .whereType<Map>()
            .map((m) => Map<String, dynamic>.from(m))
            .toList();
      } else {
        availableVaults = [];
      }
      notifyListeners();
    } catch (_) {}
  }

  Future<void> requestSwitchVault(
      String newVaultName, BuildContext context) async {
    final currentVaultId = vaultId;
    if (currentVaultId == null) return;
    if (newVaultName == vaultName) return;

    perf_cache.clearCacheOnVaultSwitch(currentVaultId, null);

    _VaultCrypto.clearCache(currentVaultId);
    vaultName = newVaultName;
    unlocked = false;
    pinAttempts = 0;
    lockoutUntil = null;
    notifyListeners();

    if (context.mounted) {
      Navigator.pushNamedAndRemoveUntil(context, '/pin', (route) => false);
    }
  }

  bool handleApiException(Object error) {
    if (error is VaultFrozenException) {
      lockMessage = error.message;
      unlocked = false;
      if (vaultId != null) _VaultCrypto.clearCache(vaultId!);
      notifyListeners();
      rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
        '/vault-frozen',
        (_) => false,
      );
      return true;
    }
    if (error is VaultLockedException) {
      lockMessage = error.message;
      unlocked = false;
      if (vaultId != null) _VaultCrypto.clearCache(vaultId!);
      notifyListeners();
      rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
        '/pin',
        (_) => false,
      );
      return true;
    }

    if (error is InvalidVaultUnlockException) {
      lockMessage = error.message;
      unlocked = false;
      if (vaultId != null) _VaultCrypto.clearCache(vaultId!);
      notifyListeners();
      rootScaffoldMessengerKey.currentState?.clearSnackBars();
      rootScaffoldMessengerKey.currentState?.showSnackBar(
        SnackBar(content: Text(error.message)),
      );
      rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
        '/pin',
        (_) => false,
      );
      return true;
    }
    // 2026-07-22 typed crypto-context mismatch (server 400 "Invalid
    // PIN or corrupted data"). The session and unlock are both
    // intact — the client's ciphertext just did not decrypt under
    // the server's current key. NEVER clear the session, NEVER
    // navigate away, NEVER show "Incorrect PIN". Callers (chat send
    // paths) surface a typed snackbar and preserve the input. If a
    // caller propagates this to the generic error boundary we just
    // return true so no other handler misinterprets it.
    if (error is CryptoContextMismatchException) {
      rootScaffoldMessengerKey.currentState?.clearSnackBars();
      rootScaffoldMessengerKey.currentState?.showSnackBar(
        SnackBar(content: Text(error.message)),
      );
      return true;
    }
    // 2026-07-22 typed 401 invalid_pin. The session is fine; the
    // supplied PIN just didn't match. Do NOT clear the session or
    // navigate; the caller (usually PinGatePage._submit) already
    // surfaces its own PIN-specific error. Returning true here
    // suppresses the generic error boundary — the caller UX owns
    // the message.
    if (error is PinInvalidException) {
      lockMessage = error.message;
      notifyListeners();
      return true;
    }
    // 2026-07-22 (2) REVIEW-GATE FIX. Every 401 the api_client
    // couldn't positively classify as a session-termination code
    // or as invalid_pin arrives here. **HTTP 401 alone is NOT
    // proof that the session expired.** Surface a generic,
    // retryable authorization error and do NOT clear the session.
    // The only paths that may clear the session are the four
    // explicit session-termination codes handled above via
    // [SessionTerminatedException].
    if (error is ApiAuthorizationException) {
      rootScaffoldMessengerKey.currentState?.clearSnackBars();
      rootScaffoldMessengerKey.currentState?.showSnackBar(
        SnackBar(content: Text(error.message)),
      );
      return true;
    }
    if (error is AuthExpiredException) {
      if (!authed && !unlocked) {
        return false;
      }
      lockMessage = error.message;
      unlocked = false;
      authed = false;
      if (vaultId != null) _VaultCrypto.clearCache(vaultId!);

      clearSession(keepLastVaultName: true);
      notifyListeners();
      rootScaffoldMessengerKey.currentState?.showSnackBar(
        SnackBar(content: Text(error.message)),
      );
      rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
        lastVaultName != null ? '/unlock' : '/login',
        (_) => false,
      );
      return true;
    }

    // Coded 401 from the backend's session-revocation layer
    // (Step B.3/B.4). Note: api_client already funnelled the code
    // into SessionTermination.instance.handle() before throwing, so
    // reaching here means the app-registered handler (installed in
    // main()) is doing the actual clearSession + navigation. This
    // branch exists so any caller that catches the exception via
    // handleApiException also returns `true` (handled), and to be
    // idempotent if a stray SessionTerminatedException surfaces
    // outside the api layer.
    if (error is SessionTerminatedException) {
      return true;
    }

    if (error is DeviceNotTrustedException) {
      final activeDeviceId = apiClientDeviceId() ?? '';
      final activeDeviceIdPrefix = activeDeviceId.length >= 8
          ? activeDeviceId.substring(0, 8)
          : activeDeviceId;
      // Single-active-device model (2026-07-20): a device_not_trusted
      // or device_revoked response from any protected endpoint means
      // this browser's session is no longer valid — either it was
      // never trusted in the first place, or a fresh login on another
      // device revoked it. Drop the local session and route straight
      // to the login screen. The legacy /device-pending waiting-period
      // flow is bypassed for normal login.
      vlog('handleApiException.device_not_trusted', {
        'status': error.status,
        'backend_device_id': error.deviceId ?? '-',
        'active_device_id_prefix': activeDeviceIdPrefix,
        'message': error.message,
        'route_target': '/auth',
      });
      clearSession(keepLastVaultName: true);
      notifyListeners();
      rootScaffoldMessengerKey.currentState?.clearSnackBars();
      rootScaffoldMessengerKey.currentState?.showSnackBar(
        SnackBar(content: Text(error.message)),
      );
      rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
        '/auth',
        (_) => false,
      );
      return true;
    }
    return false;
  }

  void resetInactivityTimer() {
    if (!_unlocked) return;
    final now = DateTime.now();
    if (now.difference(_lastActivityAt).inMilliseconds < 1000) return;
    _lastActivityAt = now;
    _inactivityTimer?.cancel();
    _inactivityTimer = Timer(_kInactivityTimeout, _onInactivityExpired);
  }

  void _startInactivityWatch() {
    _lastActivityAt = DateTime.now();
    _inactivityTimer?.cancel();
    _inactivityTimer = Timer(_kInactivityTimeout, _onInactivityExpired);
  }

  void _stopInactivityWatch() {
    _inactivityTimer?.cancel();
    _inactivityTimer = null;
  }

  void registerKeepAliveProbe(bool Function() probe) {
    if (_keepAliveProbes.contains(probe)) return;
    _keepAliveProbes.add(probe);
  }

  void unregisterKeepAliveProbe(bool Function() probe) {
    _keepAliveProbes.remove(probe);
  }

  void registerShutdownHook(void Function() hook) {
    if (_shutdownHooks.contains(hook)) return;
    _shutdownHooks.add(hook);
  }

  void unregisterShutdownHook(void Function() hook) {
    _shutdownHooks.remove(hook);
  }

  bool _hasActiveKeepAlive() {
    for (final probe in _keepAliveProbes) {
      try {
        if (probe()) return true;
      } catch (_) {}
    }
    return false;
  }

  void _runShutdownHooks() {
    for (final hook in [..._shutdownHooks]) {
      try {
        hook();
      } catch (_) {}
    }
  }

  @visibleForTesting
  bool shouldLockOnInactivityExpiry() {
    if (!_unlocked) return false;
    if (_hasActiveKeepAlive()) return false;
    return true;
  }

  void _onInactivityExpired() {
    if (!_unlocked) return;
    if (_hasActiveKeepAlive()) {
      _inactivityTimer?.cancel();
      _inactivityTimer = Timer(_kInactivityTimeout, _onInactivityExpired);
      return;
    }
    lockMessage = 'Vault locked due to inactivity.';
    if (vaultId != null) _VaultCrypto.clearCache(vaultId!);
    unlocked = false;
    notifyListeners();

    final messengerState = rootScaffoldMessengerKey.currentState;
    String localised = 'Vault locked due to inactivity.';
    final ctx = messengerState?.context;
    if (ctx != null) {
      try {
        localised = AppLocalizations.of(ctx).errorInactivityLocked;
      } catch (_) {}
    }
    messengerState?.showSnackBar(
      SnackBar(content: Text(localised)),
    );
    rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
      '/pin',
      (_) => false,
    );
  }

  void applyBackendStats(Map<String, dynamic> stats) {
    loginCount = (stats['login_count'] as num?)?.toInt() ?? loginCount;
    cardCount = (stats['card_count'] as num?)?.toInt() ?? cardCount;
    idCount = (stats['id_count'] as num?)?.toInt() ?? idCount;
    fileCount = (stats['file_count'] as num?)?.toInt() ?? fileCount;
    storageUsedBytes =
        (stats['storage_used_bytes'] as num?)?.toInt() ?? storageUsedBytes;
    storageLimitBytes =
        (stats['storage_limit_bytes'] as num?)?.toInt() ?? storageLimitBytes;
    storagePendingBytes =
        (stats['storage_pending_bytes'] as num?)?.toInt() ?? 0;
    uploadSafetyCapBytes =
        (stats['upload_safety_cap_bytes'] as num?)?.toInt() ??
            uploadSafetyCapBytes;
    notifyListeners();
  }

  Future<void> hydrate() async {
    final sp = await SharedPreferences.getInstance();
    sessionToken = await NativeSecureStore.readString('session_token');
    lastVaultName = await NativeSecureStore.readString('last_vault_name');
    // Restore the friendly identity fields FIRST so any UI that
    // paints before /auth/me returns (or if /auth/me never returns)
    // shows the user's chosen name and their display name rather
    // than an internal identifier.
    //
    // Back-compat: legacy SharedPreferences keys (`last_display_username`,
    // `last_canonical_username`, `last_vault_ai_name`) may still be
    // populated on devices that ran the pre-2026-07-20 build. Read
    // them as a one-time fallback and migrate the values into the
    // new keys.
    final persistedDisplay =
        await NativeSecureStore.readString('last_display_name') ??
            sp.getString('last_display_username');
    if (persistedDisplay != null && persistedDisplay.isNotEmpty) {
      displayName = persistedDisplay;
      await NativeSecureStore.writeString(
        'last_display_name',
        persistedDisplay,
      );
    }
    final persistedName =
        await NativeSecureStore.readString('last_vault_name') ??
            sp.getString('last_canonical_username') ??
            sp.getString('last_vault_ai_name');
    if (persistedName != null && persistedName.isNotEmpty) {
      vaultName = persistedName;
      await NativeSecureStore.writeString('last_vault_name', persistedName);
    }
    // Drop the retired keys once we've migrated their values so
    // subsequent hydrates go straight to the new ones. Best-effort;
    // do not fail hydrate on a remove() error.
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.remove('last_display_username');
      await sp.remove('last_canonical_username');
      await sp.remove('last_vault_ai_name');
    } catch (_) {}
    final persistedHandle =
        await NativeSecureStore.readString('last_vault_handle');
    if (persistedHandle != null && persistedHandle.isNotEmpty) {
      vaultHandle = persistedHandle;
    } else {
      final adoptedHandle = await legacy_adopt.readCachedVaultHandle();
      if (adoptedHandle != null && adoptedHandle.isNotEmpty) {
        vaultHandle = adoptedHandle;
        await NativeSecureStore.writeString(
          'last_vault_handle',
          adoptedHandle,
        );
      }
    }
    await _loadAppLocale();

    if (sessionToken != null && sessionToken!.isNotEmpty) {
      try {
        final client = VaultAIClient(baseUrl: backendBaseUrl);
        final me = await client.authMe(authToken: sessionToken!);
        vaultId = me['vault_id']?.toString();
        // /auth/me returns the SERVER-authoritative vault_name (the
        // user-chosen identity for both the vault and its AI keeper).
        // It may be null on existing ZK accounts whose random-hex
        // placeholder was NULLed by migration 0031 — in that case
        // KEEP whatever hydrate restored from SharedPreferences (the
        // user's typed name is safe on-device) rather than clobber it.
        final rawName = me['vault_name'];
        if (rawName != null) {
          final name = rawName.toString().trim();
          if (name.isNotEmpty) {
            vaultName = name;
            lastVaultName = name;
            await NativeSecureStore.writeString('last_vault_name', name);
          }
        }
        // /auth/me currently returns display_username for legacy
        // vaults (the plaintext DB column) — ZK vaults leave it
        // NULL because the human display name lives in the
        // client-decrypted display_name_ciphertext. Keep the
        // response-key stability but write to the new AppState
        // field name.
        final display = me['display_username']?.toString();
        if (display != null && display.isNotEmpty) {
          displayName = display;
          await NativeSecureStore.writeString('last_display_name', display);
        }
        final handle = me['vault_handle']?.toString().trim();
        if (handle != null && handle.isNotEmpty) {
          vaultHandle = handle;
          await NativeSecureStore.writeString('last_vault_handle', handle);
        }
      } catch (_) {
        sessionToken = null;
        vaultId = null;
        await NativeSecureStore.deleteString('session_token');
      }
    }

    authed = sessionToken != null && vaultId != null;
    _hydrated = true;
    notifyListeners();
  }

  Future<void> setSession({
    required String token,
    required String vaultIdValue,
    required String vaultNameValue,
    String? displayNameValue,
    String? vaultHandleValue,
  }) async {
    // A successful login clears the "terminated" flag so the api
    // layer stops short-circuiting authenticated requests. The
    // generation counter is NOT rewound — any late responses from
    // the pre-termination session still evaluate as stale to any
    // caller comparing generations.
    st.SessionTermination.instance.reset();
    sessionToken = token;
    vaultId = vaultIdValue;
    vaultName = vaultNameValue;
    lastVaultName = vaultNameValue;
    if (vaultHandleValue != null && vaultHandleValue.isNotEmpty) {
      vaultHandle = vaultHandleValue;
      await NativeSecureStore.writeString(
        'last_vault_handle',
        vaultHandleValue,
      );
    }
    if (displayNameValue != null && displayNameValue.isNotEmpty) {
      displayName = displayNameValue;
      // Persist the friendly name so the next launch's hydrate() can
      // paint it BEFORE /auth/me returns (or if it fails).
      await NativeSecureStore.writeString(
        'last_display_name',
        displayNameValue,
      );
    }
    authed = true;
    await NativeSecureStore.writeString('session_token', token);
    await NativeSecureStore.writeString('last_vault_name', vaultNameValue);
    notifyListeners();
  }

  Future<void> clearSession({bool keepLastVaultName = true}) async {
    _runShutdownHooks();

    perf_cache.clearCacheOnLogout();

    try {
      CryptoChatLiveCache.instance.clear();
    } catch (_) {}
    // Clear the process-global active MVK BEFORE nulling session
    // fields. Any downstream write path (crypto send, upload, ZK
    // memory finalize) that races with logout will see current()
    // == null and fall through to legacy plaintext-refuse behavior.
    try {
      zk_mvk_store.ZkActiveMvk.clear();
      zk_sk_store.ZkActiveSkVault.clear();
      CredentialV2QaDiagnostics.clear();
    } catch (_) {}
    // Wipe the _VaultCrypto key cache slot for the vault we are
    // leaving. This drops both the derived key and the cached PIN
    // from process memory. Wiping BEFORE the session is nulled so
    // any concurrent access sees an empty cache rather than a stale
    // (vault_id, vault_name) hit.
    try {
      final leavingVaultId = vaultId;
      final leavingVaultName = vaultName;
      if (leavingVaultId != null && leavingVaultName != null) {
        _VaultCrypto._keyCache.remove(
          _VaultCrypto._ck(leavingVaultId, leavingVaultName),
        );
        _VaultCrypto._pinCache.remove(
          _VaultCrypto._ck(leavingVaultId, leavingVaultName),
        );
        _VaultCrypto._keyOrigin.remove(
          _VaultCrypto._ck(leavingVaultId, leavingVaultName),
        );
      }
      // 2026-07-22: clear the authoritative crypto context too. Any
      // subsequent unlock will install a fresh context; leaving the
      // previous context live across a session boundary is a
      // recipe for the exact TOCTOU class we just eliminated.
      VaultCryptoRegistry.clear(reason: 'clearSession');
    } catch (_) {}
    sessionToken = null;
    vaultId = null;
    vaultName = null;
    vaultHandle = null;
    displayName = null;
    authed = false;
    unlocked = false;
    await NativeSecureStore.deleteString('session_token');
    if (!keepLastVaultName) {
      lastVaultName = null;
      await NativeSecureStore.deleteString('last_vault_name');
      // "Use another vault" — drop everything about the previous
      // account so the /login page starts clean. Preserving these
      // would either pre-fill the wrong vault name or paint the
      // wrong display name during the fresh session's hydrate.
      await NativeSecureStore.deleteString('last_vault_handle');
      await NativeSecureStore.deleteString('last_display_name');
      final sp = await SharedPreferences.getInstance();
      // Legacy keys — retired 2026-07-20 but cleared here too in
      // case a fresh install imported them before hydrate() ran.
      await sp.remove('last_display_username');
      await sp.remove('last_canonical_username');
      await sp.remove('last_vault_ai_name');
    }
    notifyListeners();
  }

  void markUnlocked() {
    unlocked = true;
    pinAttempts = 0;
    lockoutUntil = null;
    notifyListeners();
  }

  Future<LoginResult?> _restoreZkSessionKeysAfterPin({
    required String pin,
    required String expectedVaultId,
    required String vaultNameHint,
    String? vaultHandleHint,
    required String reason,
  }) async {
    final loginId = selectInheritanceRevealLoginIdentifier(
      vaultName: vaultNameHint,
      lastVaultName: lastVaultName,
      vaultHandle: vaultHandleHint ?? vaultHandle,
    );
    if (!loginId.hasIdentifier) {
      inheritanceRevealDiag('${reason}_zk_restore_no_identifier', {
        'expected_vault_fpr': inheritanceRevealIdFingerprint(expectedVaultId),
        'expected_role': 'beneficiary',
      });
      return null;
    }
    inheritanceRevealDiag('${reason}_zk_restore_attempt', {
      'expected_vault_fpr': inheritanceRevealIdFingerprint(expectedVaultId),
      'expected_role': 'beneficiary',
      'id_source': loginId.source,
      'has_vault_handle': loginId.vaultHandle != null,
      'active_sk_present': zk_sk_store.ZkActiveSkVault.current() != null,
      'active_sk_vault_match':
          zk_sk_store.ZkActiveSkVault.currentVaultId() == expectedVaultId,
    });

    String lastStep = 'begin';
    try {
      final zk = ZkAuthService(_zkHttpPost);
      final result = await zk.loginVault(
        vaultName: loginId.vaultName,
        vaultHandle: loginId.vaultHandle,
        pin: pin,
        onStep: (step) => lastStep = step,
      );
      if (result.vaultId != expectedVaultId) {
        inheritanceRevealDiag('${reason}_zk_restore_vault_mismatch', {
          'expected_vault_fpr': inheritanceRevealIdFingerprint(expectedVaultId),
          'actual_vault_fpr': inheritanceRevealIdFingerprint(result.vaultId),
          'expected_role': 'beneficiary',
          'id_source': loginId.source,
        });
        return null;
      }

      final resolvedVaultName = _nonEmptyTrimmed(result.vaultName) ??
          loginId.vaultName ??
          _nonEmptyTrimmed(vaultNameHint) ??
          _nonEmptyTrimmed(vaultName) ??
          _nonEmptyTrimmed(lastVaultName) ??
          _nonEmptyTrimmed(result.displayName) ??
          result.vaultHandle;

      _VaultCrypto
              ._keyCache[_VaultCrypto._ck(result.vaultId, resolvedVaultName)] =
          result.mvk;
      _VaultCrypto
          ._pinCache[_VaultCrypto._ck(result.vaultId, resolvedVaultName)] = pin;
      _VaultCrypto.setActiveVault(
        vaultId: result.vaultId,
        vaultName: resolvedVaultName,
      );
      zk_mvk_store.ZkActiveMvk.set(
        mvk: result.mvk,
        vaultId: result.vaultId,
        vaultHandle: result.vaultHandle,
      );
      zk_sk_store.ZkActiveSkVault.set(
        skVault: result.skVaultPrivate,
        vaultId: result.vaultId,
      );
      inheritanceRevealDiag('${reason}_zk_restore_success', {
        'vault_fpr': inheritanceRevealIdFingerprint(result.vaultId),
        'expected_role': 'beneficiary',
        'id_source': loginId.source,
        'active_sk_present': zk_sk_store.ZkActiveSkVault.current() != null,
        'active_sk_vault_match':
            zk_sk_store.ZkActiveSkVault.currentVaultId() == expectedVaultId,
      });
      return result;
    } on OpaqueAuthenticationFailed catch (e) {
      inheritanceRevealDiag('${reason}_zk_restore_opaque_failed', {
        'stage': e.stage,
        'last_step': lastStep,
        'expected_role': 'beneficiary',
        'id_source': loginId.source,
      });
      return null;
    } catch (e) {
      inheritanceRevealDiag('${reason}_zk_restore_failed', {
        'exception_type': e.runtimeType.toString(),
        'last_step': lastStep,
        'expected_role': 'beneficiary',
        'id_source': loginId.source,
      });
      return null;
    }
  }

  Future<void> wipeOrphanDataAndClear() async {
    final token = sessionToken;
    if (token == null) {
      throw Exception('Session expired. Please sign in again.');
    }
    final client = VaultAIClient(baseUrl: backendBaseUrl);
    await client.wipeOrphanData(authToken: token, confirm: true);
    recoveryInfo = null;
    notifyListeners();
  }

  Future<void> signOut() async {
    final token = sessionToken;
    if (token != null) {
      try {
        await VaultAIClient(baseUrl: backendBaseUrl)
            .authLogout(authToken: token);
      } catch (_) {}
    }
    final currentVaultId = vaultId;
    if (currentVaultId != null) {
      _VaultCrypto.clearCache(currentVaultId);
    }
    await clearSession(keepLastVaultName: true);
  }

  Future<bool> verifyPin(
    String pin, {
    bool restoreZkSessionKeys = false,
  }) async {
    final knownVaultName = vaultName ?? lastVaultName;
    if (knownVaultName == null) return false;

    vlog('pin.verify.start', {
      'vaultName': knownVaultName,
      'vaultNameLen': knownVaultName.length,
      'pinLen': pin.length,
    });

    if (lockoutUntil != null && DateTime.now().isBefore(lockoutUntil!)) {
      throw Exception('Too many attempts. Wait ${_getLockoutSeconds()}s');
    }

    final tTotal0 = DateTime.now();
    int tPrev = tTotal0.millisecondsSinceEpoch;
    int tick() {
      final now = DateTime.now().millisecondsSinceEpoch;
      final delta = now - tPrev;
      tPrev = now;
      return delta;
    }

    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);

      final Map<String, dynamic> loginResult;
      try {
        loginResult = await client.authLogin(
          vaultName: knownVaultName,
          pin: pin,
        );
      } on InvalidCredentialsException catch (e) {
        lockMessage = e.message;
        pinAttempts++;
        vlog('pin.verify.result', {
          'result': 'failure',
          'code': 'invalid_credentials',
        });
        notifyListeners();
        return false;
      }
      vlog('pin.timing.auth_login', {'elapsed_ms': tick()});

      final newToken = loginResult['session_token']?.toString();
      final newVaultId = loginResult['vault_id']?.toString();
      final newVaultName =
          loginResult['vault_name']?.toString() ?? knownVaultName;
      final newDisplay = loginResult['display_username']?.toString();
      final newVaultHandle = loginResult['vault_handle']?.toString();
      if (newToken == null || newToken.isEmpty || newVaultId == null) {
        throw Exception('Login response missing session_token or vault_id');
      }

      var activeToken = newToken;
      var activeVaultId = newVaultId;
      var activeVaultName = newVaultName;
      var activeDisplay = newDisplay;
      var activeVaultHandle = newVaultHandle;
      LoginResult? zkRestore;
      if (restoreZkSessionKeys &&
          newVaultHandle != null &&
          newVaultHandle.isNotEmpty) {
        zkRestore = await _restoreZkSessionKeysAfterPin(
          pin: pin,
          expectedVaultId: newVaultId,
          vaultNameHint: newVaultName,
          vaultHandleHint: newVaultHandle,
          reason: 'verify_pin',
        );
        if (zkRestore != null) {
          activeToken = zkRestore.sessionToken;
          activeVaultId = zkRestore.vaultId;
          activeVaultName =
              _nonEmptyTrimmed(zkRestore.vaultName) ?? newVaultName;
          activeDisplay = zkRestore.displayName;
          activeVaultHandle = zkRestore.vaultHandle;
        }
      } else if (restoreZkSessionKeys) {
        inheritanceRevealDiag('verify_pin_zk_restore_skipped', {
          'expected_vault_fpr': inheritanceRevealIdFingerprint(newVaultId),
          'expected_role': 'beneficiary',
          'has_vault_handle': false,
        });
      }

      await setSession(
        token: activeToken,
        vaultIdValue: activeVaultId,
        vaultNameValue: activeVaultName,
        displayNameValue: activeDisplay,
        vaultHandleValue: activeVaultHandle,
      );

      lockMessage = null;

      final activeDeviceId = apiClientDeviceId() ?? '';
      final activeDeviceIdPrefix = activeDeviceId.length >= 8
          ? activeDeviceId.substring(0, 8)
          : activeDeviceId;
      vlog('pin.verify.result', {
        'result': 'success',
        'vaultName': activeVaultName,
        'next_call': '/vault-meta',
        'device_id_prefix': activeDeviceIdPrefix,
        'device_id_present': activeDeviceId.isNotEmpty,
        'zk_restore': zkRestore != null,
      });

      final vaultMeta = await _API.getVaultMeta(
        vaultName: activeVaultName,
        authToken: activeToken,
      );
      vlog('pin.timing.vault_meta', {'elapsed_ms': tick()});
      vlog('pin.post_verify.vault_meta_ok', {
        'vaultName': activeVaultName,
        'device_id_prefix': activeDeviceIdPrefix,
      });

      final pinSalt = vaultMeta['pin_salt']?.toString();
      if (pinSalt == null || pinSalt.isEmpty) {
        throw Exception('Backend did not return pin salt');
      }
      final iterations =
          (vaultMeta['kdf_iterations'] as num?)?.toInt() ?? 100000;

      // 2026-07-22 crypto-context refactor: derive PBKDF2 AND
      // install the atomic VaultCryptoContext in one guarded
      // operation. Reserves an operation id before the derive and
      // refuses to install if a later reservation superseded us.
      // Both the registry AND the legacy _VaultCrypto caches are
      // updated atomically so no read path sees a half-updated
      // state.
      final _preRotateCtx = await deriveAndInstallCryptoContext(
        vaultId: activeVaultId,
        vaultName: activeVaultName,
        pin: pin,
        pinSaltBase64: pinSalt,
        iterations: iterations,
        source: 'verify_pin',
      );
      if (_preRotateCtx == null) {
        vlog('pin.verify.derive.superseded', {
          'phase': 'initial',
          'vaultName': activeVaultName,
        });
        return false;
      }
      vlog('pin.timing.derive_key', {
        'elapsed_ms': tick(),
        'iterations': iterations,
      });

      // 2026-07-21 (c2f917e first-chat regression fix): the previous
      // shape wrapped the rotate call, a rotated-flag inspection,
      // and the re-derive in ONE try block that silently swallowed
      // every failure. That silently desynced the client key from
      // the DB whenever the server rotated but the flag inspection
      // failed for any reason, and the very first /chat POST then
      // encrypted with the stale key. Server re-derived from the
      // (now-rotated) DB salt, and vault_core.decrypt_message
      // raised "Invalid PIN or corrupted data" -->
      // InvalidVaultUnlockException on the client.
      //
      // New shape (three-part):
      //   * Attempt the rotation. Do NOT silently swallow errors -
      //     log the outcome via vlog. If the rotate call threw the
      //     server transaction rolled back (see
      //     vault_core.py:530-533), so K1 from /vault-meta above is
      //     still valid and no client action is needed.
      //   * REGARDLESS of the rotate outcome, refetch /vault-meta.
      //     That is the authoritative source of the CURRENT DB
      //     salt/iter and closes the "server committed but response
      //     was malformed or lost" window that no flag inspection
      //     can catch.
      //   * If the fresh salt/iter differ from what K1 was derived
      //     from, re-derive K2 and REPLACE the cached key so the
      //     next /chat's server-side re-derive matches.
      Object? _rotateError;
      try {
        await client.rotateVaultKdf(
          vaultName: activeVaultName,
          pin: pin,
          authToken: activeToken,
        );
      } catch (e) {
        _rotateError = e;
      }
      vlog('pin.rotate.attempt', {
        'ok': _rotateError == null,
        if (_rotateError != null)
          'error_type': _rotateError.runtimeType.toString(),
        if (_rotateError != null) 'error': _rotateError.toString(),
      });

      final freshMeta = await _API.getVaultMeta(
        vaultName: activeVaultName,
        authToken: activeToken,
      );
      final freshSalt = freshMeta['pin_salt']?.toString();
      final freshIter =
          (freshMeta['kdf_iterations'] as num?)?.toInt() ?? iterations;
      final saltChanged =
          freshSalt != null && freshSalt.isNotEmpty && freshSalt != pinSalt;
      final iterChanged = freshIter != iterations;
      vlog('pin.rotate.post_meta', {
        'salt_changed': saltChanged,
        'iter_changed': iterChanged,
        'new_iterations': freshIter,
      });
      if (freshSalt != null &&
          freshSalt.isNotEmpty &&
          (saltChanged || iterChanged)) {
        // Authoritative salt/iter differ from what K1 was derived
        // from. Re-derive K2 with the fresh values and install as a
        // new context (bumping the generation). Legacy _VaultCrypto
        // caches are mirrored inside deriveAndInstallCryptoContext.
        final _postRotateCtx = await deriveAndInstallCryptoContext(
          vaultId: activeVaultId,
          vaultName: activeVaultName,
          pin: pin,
          pinSaltBase64: freshSalt,
          iterations: freshIter,
          source: 'verify_pin.post_rotate',
        );
        if (_postRotateCtx == null) {
          vlog('pin.verify.derive.superseded', {
            'phase': 'post_rotate',
            'vaultName': activeVaultName,
          });
          return false;
        }
      }
      vlog('pin.timing.rotate_kdf', {'elapsed_ms': tick()});

      pinAttempts = 0;
      lockoutUntil = null;
      unlocked = true;
      notifyListeners();
      vlog('pin.post_verify.unlocked', {
        'vaultName': activeVaultName,
        'device_id_prefix': activeDeviceIdPrefix,
        'route_target': '/chat',
      });

      _refreshSessionListsBestEffort(this);
      vlog('pin.timing.refresh_fan_queued', {'elapsed_ms': tick()});

      vlog('pin.timing.verify_pin_total', {
        'elapsed_ms': DateTime.now().difference(tTotal0).inMilliseconds,
      });
      return true;
    } on DeviceNotTrustedException catch (e) {
      vlog('pin.verify.result', {
        'result': 'device_not_trusted',
        'status': e.status,
      });
      lockMessage = null;
      rethrow;
    } catch (e) {
      pinAttempts++;
      vlog('pin.verify.result', {
        'result': 'failure',
        'reason': 'exception',
        'error': e.toString(),
      });
      notifyListeners();
      return false;
    }
  }

  /// Apply the authoritative (pin_salt, kdf_iterations) the server
  /// returned in a 409 kdf_generation_stale response body. Re-derives
  /// the cached vault key IN PLACE using the currently-cached PIN and
  /// the fresh salt/iter. No HTTP call — the server already told us
  /// the current values, so this cannot re-race the DB the way a
  /// pre-encrypt GET could (the pre-encrypt-GET approach was rejected
  /// on 2026-07-21 review because a GET+POST is not atomic and a
  /// concurrent rotation between the two can still leave the client
  /// on a stale key).
  ///
  /// Returns true when the re-derive succeeded (the caller may then
  /// prompt the user to re-send their message); false when it could
  /// not (no cached PIN, malformed salt) and the caller must fall
  /// back to forcing PIN re-entry with a specific reason.
  ///
  /// Never mutates the session token, the ``authed`` flag, the
  /// ``unlocked`` flag, or navigation. Purely a crypto-cache
  /// resynchronization step.
  Future<bool> applyFreshKdfMetadata({
    required String pinSaltBase64,
    required int iterations,
  }) async {
    final vId = vaultId;
    final vName = _vaultName;
    if (vId == null || vName == null) return false;
    if (pinSaltBase64.isEmpty || iterations <= 0) return false;
    // Read the PIN from the current authoritative context if there is
    // one — falls back to the legacy _pinCache for pre-refactor
    // ZK-login state where the context was not yet installed.
    final currentCtx = VaultCryptoRegistry.current;
    final String? pin = (currentCtx != null &&
            currentCtx.vaultId == vId &&
            currentCtx.vaultName == vName)
        ? currentCtx.pin
        : _VaultCrypto.cachedPinFor(vaultId: vId, vaultName: vName);
    if (pin == null) {
      vlog('crypto.applyFreshKdfMetadata.no_pin', {});
      return false;
    }
    try {
      // Derive AND install a new atomic context. The install is
      // generation-guarded; if a concurrent derive completes later
      // with a lower generation, it will be refused.
      final newCtx = await deriveAndInstallCryptoContext(
        vaultId: vId,
        vaultName: vName,
        pin: pin,
        pinSaltBase64: pinSaltBase64,
        iterations: iterations,
        source: '409_refresh',
      );
      if (newCtx == null) {
        vlog('crypto.applyFreshKdfMetadata.superseded', {});
        return false;
      }
      vlog('crypto.applyFreshKdfMetadata.rederived', {
        'iterations': iterations,
        'saltLen': pinSaltBase64.length,
        'generation': newCtx.generation,
      });
      return true;
    } catch (e) {
      vlog('crypto.applyFreshKdfMetadata.failed', {'error': e.toString()});
      return false;
    }
  }

  int _getLockoutSeconds() {
    if (lockoutUntil == null) return 0;
    final diff = lockoutUntil!.difference(DateTime.now()).inSeconds;
    return diff < 0 ? 0 : diff;
  }

  Future<bool> hasPin() async {
    final token = sessionToken;
    if (token == null) return false;

    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.getMyVault(
        authToken: token,
      );

      final backendVaultName = result['vault_name']?.toString();
      vlog('pin.hasPin', {
        'currentAppVaultName': vaultName,
        'backendVaultName': backendVaultName,
        'differs': vaultName != null &&
            backendVaultName != null &&
            vaultName != backendVaultName,
        'has_pin': result['has_pin'],
      });
      if (backendVaultName != null && backendVaultName.trim().isNotEmpty) {
        vaultName = backendVaultName.trim();
        lastVaultName = vaultName;
        await NativeSecureStore.writeString('last_vault_name', vaultName!);
      }

      notifyListeners();
      return result['has_pin'] == true;
    } catch (_) {
      return false;
    }
  }

  Future<void> loadVaultName() async {
    final token = sessionToken;
    final localVaultName = lastVaultName;

    if (token == null) {
      if (localVaultName != null && localVaultName.trim().isNotEmpty) {
        vaultName = localVaultName.trim();
      }
      vlog('pin.loadVaultName', {
        'source': 'local_offline',
        'vaultName': vaultName,
      });
      notifyListeners();
      return;
    }

    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.getMyVault(
        authToken: token,
      );

      final hasVault = result['has_vault'] == true;
      final backendVaultName = result['vault_name']?.toString();
      vlog('pin.loadVaultName', {
        'source': 'backend',
        'has_vault': hasVault,
        'currentAppVaultName': vaultName,
        'backendVaultName': backendVaultName,
        'differs': vaultName != null &&
            backendVaultName != null &&
            vaultName != backendVaultName,
      });

      if (hasVault &&
          backendVaultName != null &&
          backendVaultName.trim().isNotEmpty) {
        vaultName = backendVaultName.trim();
        lastVaultName = vaultName;
        await NativeSecureStore.writeString('last_vault_name', vaultName!);
      } else {
        vaultName = null;
      }
    } catch (e) {
      if (localVaultName != null && localVaultName.trim().isNotEmpty) {
        vaultName = localVaultName.trim();
      }
      vlog('pin.loadVaultName', {
        'source': 'local_fallback_after_error',
        'error': e.toString(),
        'vaultName': vaultName,
      });
    }

    notifyListeners();
  }

  Future<void> refreshVaultStats() async {
    final currentVaultName = vaultName;
    final token = sessionToken;
    if (currentVaultName == null || token == null) return;

    final String pin;
    try {
      pin = await _VaultCrypto.currentPinOrThrow();
    } catch (_) {
      return;
    }

    try {
      final stats = await _API.getVaultStats(
        vaultName: currentVaultName,
        pin: pin,
        authToken: token,
      );
      applyBackendStats(stats);
    } catch (_) {}

    await refreshBilling();
  }

  Future<void> refreshBilling() async {
    final token = sessionToken;
    if (token == null) {
      _logDevBillingMeStarted(reason: 'no_session_token', seq: -1);
      return;
    }

    final seq = ++_billingRefreshSeq;

    final hadPriorSuccess = isBillingLoaded;
    if (!hadPriorSuccess) {
      billingLoadState = BillingLoadState.loading;
      billingLoadError = null;
      notifyListeners();
    }

    _logDevBillingMeStarted(reason: 'call', seq: seq);

    final started = DateTime.now();
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);

      final ent = await client.getBillingMe(authToken: token).timeout(
        const Duration(seconds: 12),
        onTimeout: () {
          throw TimeoutException(
            'Billing check timed out after 12s',
            const Duration(seconds: 12),
          );
        },
      );

      _logDevBillingMeShape(ent, seq: seq);

      final parsedOk = ent.isNotEmpty &&
          (ent['included_bytes'] != null ||
              ent['effective_limit_bytes'] != null ||
              ent['status'] != null);

      if (seq < _billingRefreshLatestApplied) {
        _logDevBillingMe(
          status: '200',
          errorCode: 'ok_stale',
          ms: DateTime.now().difference(started).inMilliseconds,
          parseOk: parsedOk,
          stateAfter: 'unchanged_stale_win',
          seq: seq,
        );
        return;
      }
      _billingRefreshLatestApplied = seq;

      billingEffectiveLimitBytes =
          (ent['effective_limit_bytes'] as num?)?.toInt() ??
              billingEffectiveLimitBytes;
      billingBlockCount =
          (ent['block_count'] as num?)?.toInt() ?? billingBlockCount;
      billingPurchasedBytes =
          (ent['purchased_bytes'] as num?)?.toInt() ?? billingPurchasedBytes;
      billingIncludedBytes =
          (ent['included_bytes'] as num?)?.toInt() ?? billingIncludedBytes;

      billingLoadState = BillingLoadState.loaded;
      billingLoadError = null;
      final okMs = DateTime.now().difference(started).inMilliseconds;
      _logDevTiming('crypto_access_check_ms', okMs);
      _logDevBillingMe(
        status: '200',
        errorCode: 'ok',
        ms: okMs,
        parseOk: parsedOk,
        stateAfter: 'loaded',
        seq: seq,
      );
      _logDevBillingMeStateAfterSuccess();
      notifyListeners();
    } catch (e) {
      final errMs = DateTime.now().difference(started).inMilliseconds;
      final classified = classifyBillingMeError(e);
      final safeCopy = billingBannerCopyForCode(classified.errorCode);

      if (seq < _billingRefreshLatestApplied) {
        _logDevBillingMe(
          status: classified.statusLabel,
          errorCode: '${classified.errorCode}_stale',
          ms: errMs,
          parseOk: false,
          stateAfter: 'unchanged_success_holds',
          seq: seq,
        );
        return;
      }
      _billingRefreshLatestApplied = seq;

      String stateAfter;
      if (hadPriorSuccess) {
        billingLoadError = safeCopy;
        stateAfter = 'loaded';
      } else {
        billingLoadState = BillingLoadState.error;
        billingLoadError = safeCopy;
        stateAfter = 'error';
        notifyListeners();
      }
      _logDevTiming('crypto_access_check_ms', errMs, error: true);
      _logDevBillingMe(
        status: classified.statusLabel,
        errorCode: classified.errorCode,
        ms: errMs,
        parseOk: false,
        stateAfter: stateAfter,
        seq: seq,
      );
    }
  }

  void _logDevTiming(String label, int ms, {bool error = false}) {
    if (!kDebugMode) return;

    developer.log('$label=$ms${error ? ' error' : ''}', name: 'CryptoVault');
  }

  void _logDevBillingMe({
    required String status,
    required String errorCode,
    required int ms,
    required bool parseOk,
    required String stateAfter,
    required int seq,
  }) {
    if (!kDebugMode) return;
    developer.log(
      'billing_me_path=/billing/me '
      'billing_me_seq=$seq '
      'billing_me_status=$status '
      'billing_me_error_code=$errorCode '
      'billing_me_ms=$ms '
      'billing_me_parse_ok=$parseOk '
      'billing_me_state_after_refresh=$stateAfter',
      name: 'CryptoVault',
    );
  }

  void _logDevBillingMeStarted({required String reason, required int seq}) {
    if (!kDebugMode) return;
    developer.log(
      'billing_me_request_started '
      'billing_me_path=/billing/me '
      'billing_me_seq=$seq '
      'billing_me_reason=$reason',
      name: 'CryptoVault',
    );
  }

  void _logDevBillingMeShape(Map<String, dynamic> ent, {required int seq}) {
    if (!kDebugMode) return;

    final keys = ent.keys.toList()..sort();
    final billingStateVal = ent['billing_state']?.toString() ?? '<absent>';
    final statusVal = ent['status']?.toString() ?? '<absent>';
    final includedPresent = ent['included_bytes'] != null;
    final effectiveLimitPresent = ent['effective_limit_bytes'] != null;
    final hasActiveSubPresent = ent['has_active_subscription'] != null;
    developer.log(
      'billing_me_shape '
      'billing_me_seq=$seq '
      'body_top_keys=${keys.join(",")} '
      'billing_state=$billingStateVal '
      'status=$statusVal '
      'included_bytes_present=$includedPresent '
      'effective_limit_bytes_present=$effectiveLimitPresent '
      'has_active_subscription_present=$hasActiveSubPresent',
      name: 'CryptoVault',
    );
  }

  void _logDevBillingMeStateAfterSuccess() {
    if (!kDebugMode) return;
    developer.log(
      'billing_me_state_after_success '
      'loaded=${isBillingLoaded} '
      'error=${isBillingError} '
      'load_error_null=${billingLoadError == null} '
      'banner_should_show=${isBillingLoading || isBillingError}',
      name: 'CryptoVault',
    );
  }

  Future<void> retryBilling() => refreshBilling();

  void applyBillingPayload(Map<String, dynamic> ent) {
    billingEffectiveLimitBytes =
        (ent['effective_limit_bytes'] as num?)?.toInt() ??
            billingEffectiveLimitBytes;
    billingBlockCount =
        (ent['block_count'] as num?)?.toInt() ?? billingBlockCount;
    billingPurchasedBytes =
        (ent['purchased_bytes'] as num?)?.toInt() ?? billingPurchasedBytes;
    billingIncludedBytes =
        (ent['included_bytes'] as num?)?.toInt() ?? billingIncludedBytes;
    billingLoadState = BillingLoadState.loaded;
    billingLoadError = null;
    notifyListeners();
  }

  Future<void> signOutEverywhere() async {
    final currentVaultId = vaultId;
    if (currentVaultId != null) {
      _VaultCrypto.clearCache(currentVaultId);
    }
    await signOut();
    pinAttempts = 0;
    lockoutUntil = null;
    recoveryInfo = null;
    availableVaults = [];
    notifications = [];
    unreadNotificationCount = 0;
    billingEffectiveLimitBytes = 0;
    billingBlockCount = 0;
    billingPurchasedBytes = 0;
    billingIncludedBytes = 0;
    billingLoadState = BillingLoadState.initial;
    billingLoadError = null;
    notifyListeners();
  }

  Future<void> handleVaultDeleted() async {
    final deletedVaultId = vaultId;

    if (deletedVaultId != null) {
      try {
        _VaultCrypto.clearCache(deletedVaultId);
      } catch (_) {}
    }

    await clearSession(keepLastVaultName: false);

    pinAttempts = 0;
    lockoutUntil = null;
    storageUsedBytes = 0;
    storageLimitBytes = kVaultStorageLimitBytes;
    storagePendingBytes = 0;
    uploadSafetyCapBytes = 100 * 1024 * 1024;
    billingEffectiveLimitBytes = 0;
    billingBlockCount = 0;
    billingPurchasedBytes = 0;
    billingIncludedBytes = 0;
    billingLoadState = BillingLoadState.initial;
    billingLoadError = null;
    recoveryInfo = null;
    availableVaults = [];
    notifications = [];
    unreadNotificationCount = 0;

    notifyListeners();

    rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
      '/auth',
      (_) => false,
    );

    final messengerState = rootScaffoldMessengerKey.currentState;
    String message = 'Your vault has been deleted.';
    final ctx = messengerState?.context;
    if (ctx != null) {
      try {
        message = AppLocalizations.of(ctx).deleteVaultSuccess;
      } catch (_) {}
    }
    messengerState?.clearSnackBars();
    messengerState?.showSnackBar(
      SnackBar(
        key: const Key('delete_vault_success_snackbar'),
        content: Text(message),
      ),
    );
  }

  Future<void> resetLocalState() async {
    final currentVaultId = vaultId;
    if (currentVaultId != null) {
      _VaultCrypto.clearCache(currentVaultId);
    }

    await clearSession(keepLastVaultName: false);
    pinAttempts = 0;
    lockoutUntil = null;
    storageUsedBytes = 0;
    storageLimitBytes = kVaultStorageLimitBytes;
    storagePendingBytes = 0;
    uploadSafetyCapBytes = 100 * 1024 * 1024;
    billingEffectiveLimitBytes = 0;
    billingBlockCount = 0;
    billingPurchasedBytes = 0;
    billingIncludedBytes = 0;
    billingLoadState = BillingLoadState.initial;
    billingLoadError = null;
    recoveryInfo = null;
    notifyListeners();
  }
}

class _API {
  static final VaultAIClient _client = VaultAIClient(baseUrl: backendBaseUrl);

  static Future<Map<String, dynamic>> getVaultStats({
    required String vaultName,
    required String pin,
    required String authToken,
  }) async {
    return _client.getVaultStats(
      vaultName: vaultName,
      pin: pin,
      authToken: authToken,
    );
  }

  static Future<Map<String, dynamic>> getVaultMeta({
    required String vaultName,
    required String authToken,
  }) async {
    return _client.getVaultMeta(
      vaultName: vaultName,
      authToken: authToken,
    );
  }
}

Locale resolveShellLocale(
  List<Locale>? preferred,
  Iterable<Locale> supported,
) {
  final supportedList = supported.toList(growable: false);
  final english = supportedList.firstWhere(
    (l) => l.languageCode == 'en',
    orElse: () =>
        supportedList.isEmpty ? const Locale('en') : supportedList.first,
  );
  if (preferred == null || preferred.isEmpty) return english;
  for (final want in preferred) {
    for (final s in supportedList) {
      if (s.languageCode == want.languageCode) {
        return s;
      }
    }
  }
  return english;
}

class SvaultaiApp extends StatelessWidget {
  const SvaultaiApp({super.key});

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return MaterialApp(
      navigatorKey: rootNavigatorKey,
      scaffoldMessengerKey: rootScaffoldMessengerKey,
      navigatorObservers: [appRouteObserver],
      builder: (context, child) {
        if (child == null) return const SizedBox.shrink();
        return _ActivityWrapper(child: child);
      },
      debugShowCheckedModeBanner: false,
      title: 'SVaultAI',
      locale: app.shellLocale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      localeListResolutionCallback: resolveShellLocale,
      theme: VaultTheme.dark(),
      routes: {
        '/': (_) => const LandingPage(),
        '/auth': (_) => const LoginPage(),
        '/login': (_) => const LoginPage(),
        '/signup': (_) => const SignupPage(),
        '/unlock': (_) => const UnlockPage(),
        '/pin': (_) => const PinGatePage(),
        '/vault-frozen': (_) => const VaultFrozenPage(),
        '/recover': (_) => const VaultRecoveryPage(),
        '/chat': (_) => const ChatDashboardPage(),
        '/device-pending': (_) => const DevicePendingPage(),
        '/devices': (_) => const DevicesPage(),
        '/security-center': (_) => const SecurityCenterPage(),
        '/storage': (_) => const StoragePage(),
        kVaultAiPrivacyRoute: (_) => const PrivacyPolicyPage(),
      },
      // Native users should arrive at authentication immediately. Keep `/`
      // available for explicit public/marketing navigation, but do not make
      // the promotional landing page the app's startup screen.
      initialRoute: '/login',
    );
  }
}

class _ActivityWrapper extends StatefulWidget {
  final Widget child;
  const _ActivityWrapper({required this.child});

  @override
  State<_ActivityWrapper> createState() => _ActivityWrapperState();
}

class _ActivityWrapperState extends State<_ActivityWrapper> {
  @override
  void initState() {
    super.initState();
    HardwareKeyboard.instance.addHandler(_onKey);
  }

  @override
  void dispose() {
    HardwareKeyboard.instance.removeHandler(_onKey);
    super.dispose();
  }

  bool _onKey(KeyEvent event) {
    if (event is KeyDownEvent) _bump();
    return false;
  }

  void _bump() {
    try {
      context.read<AppState>().resetInactivityTimer();
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      behavior: HitTestBehavior.translucent,
      onPointerDown: (_) => _bump(),
      onPointerSignal: (_) => _bump(),
      child: AppReleaseUpdateBanner(child: widget.child),
    );
  }
}

class TopNavBar extends StatelessWidget implements PreferredSizeWidget {
  final bool showActions;
  final bool isMobile;
  final VoidCallback? onMenuTap;
  final VoidCallback? onCreateTap;
  final bool showMenuButton;

  const TopNavBar({
    super.key,
    this.showActions = true,
    this.isMobile = false,
    this.onMenuTap,
    this.onCreateTap,
    this.showMenuButton = false,
  });

  @override
  Size get preferredSize => const Size.fromHeight(72);

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    // 2026-07-21: the account chip's maxWidth on isMobile used to be
    // a flat 180 which, combined with a 42px shield + 12px gap +
    // menu IconButton + AppBar titleSpacing, consumed enough of the
    // 320-360px viewports that the Flexible-wrapped wordmark laid
    // out at 0 width (long display names amplified this). Tighten
    // the chip cap on the narrowest phones so the wordmark keeps
    // some space to render.
    final screenWidth = MediaQuery.of(context).size.width;
    final double accountChipMaxWidth =
        !isMobile ? 260.0 : (screenWidth < 380 ? 120.0 : 180.0);

    return AppBar(
      toolbarHeight: 72,
      automaticallyImplyLeading: false,
      elevation: 0,
      backgroundColor: const Color(0xFF171717),
      titleSpacing: 14,
      title: Row(
        children: [
          if (showMenuButton)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Semantics(
                container: true,
                identifier: 'top_nav_menu_button',
                button: true,
                child: IconButton(
                  constraints: const BoxConstraints.tightFor(
                    width: 40,
                    height: 40,
                  ),
                  padding: EdgeInsets.zero,
                  visualDensity: VisualDensity.compact,
                  onPressed: onMenuTap,
                  icon: const Icon(Icons.menu_rounded, size: 24),
                ),
              ),
            ),
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: const Color(0xFF10A37F).withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(
                  color: const Color(0xFF10A37F).withValues(alpha: 0.18)),
            ),
            child: const Icon(Icons.shield_rounded,
                color: Color(0xFF10A37F), size: 22),
          ),
          // 2026-07-21 (c2f917e follow-up): on phone-width viewports
          // (< 600 CSS px) hide the wordmark entirely and show only
          // the shield logo. The previous Flexible+ellipsis approach
          // produced "V..." at 320-390px which reads as broken UI.
          // Tablet + desktop (>= 600px) keep the full wordmark.
          if (screenWidth >= 600) ...[
            const SizedBox(width: 12),
            const Flexible(
              child: Text(
                'SVaultAI',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 18,
                  letterSpacing: -0.2,
                ),
              ),
            ),
          ],
        ],
      ),
      actions: !showActions
          ? null
          : [
              if (!app.authed) ...[
                if (!isMobile)
                  TextButton.icon(
                    key: const Key('top_nav_help_and_faq_public'),
                    onPressed: () => openHelpCenter(
                      context,
                      mode: hc.HelpCenterMode.public,
                    ),
                    icon: const Icon(Icons.help_outline, size: 16),
                    label: const Text('Help & FAQ'),
                  ),
                if (!isMobile)
                  Semantics(
                    container: true,
                    identifier: 'auth_landing_sign_in_button',
                    button: true,
                    child: TextButton(
                      key: const Key('auth_landing_sign_in_button'),
                      onPressed: () => Navigator.pushNamed(context, '/login'),
                      child: Text(AppLocalizations.of(context).commonSignIn),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.only(right: 14),
                  child: Semantics(
                    container: true,
                    identifier: 'auth_landing_primary_button',
                    button: true,
                    child: FilledButton(
                      key: const Key('auth_landing_primary_button'),
                      onPressed: () => Navigator.pushNamed(
                        context,
                        isMobile ? '/login' : '/signup',
                      ),
                      child: Text(
                        isMobile
                            ? AppLocalizations.of(context).commonSignIn
                            : AppLocalizations.of(context).commonSignUp,
                      ),
                    ),
                  ),
                ),
              ] else ...[
                if (app.unlocked && onCreateTap != null)
                  Padding(
                    padding: const EdgeInsets.only(right: 10),
                    child: isMobile
                        ? IconButton(
                            key: const Key('top_nav_create_button'),
                            tooltip: 'Create',
                            onPressed: onCreateTap,
                            icon: const Icon(Icons.add_circle_outline),
                          )
                        : FilledButton.icon(
                            key: const Key('top_nav_create_button'),
                            onPressed: onCreateTap,
                            icon: const Icon(Icons.add, size: 18),
                            label: const Text('Create'),
                          ),
                  ),
                if (app.unlocked) const _NotificationBell(),
                Padding(
                  padding: const EdgeInsets.only(right: 16),
                  child: PopupMenuButton<String>(
                    tooltip: 'Account',
                    itemBuilder: (_) => [
                      PopupMenuItem(
                        enabled: false,
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 220),
                          child: Text(
                            app.displayName ?? 'Account',
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ),
                      const PopupMenuDivider(),
                      PopupMenuItem(
                        key: const Key('account_menu_help_and_faq'),
                        value: 'help_and_faq',
                        child: Row(
                          children: [
                            const Icon(Icons.help_outline, size: 16),
                            const SizedBox(width: 8),
                            Text(AppLocalizations.of(context).helpCenterTitle),
                          ],
                        ),
                      ),
                      const PopupMenuDivider(),
                      PopupMenuItem(
                        value: 'sign_out',
                        child: Text(
                          AppLocalizations.of(context).commonSignOut,
                        ),
                      ),
                    ],
                    onSelected: (v) async {
                      if (v == 'help_and_faq') {
                        await openHelpCenter(
                          context,
                          mode: hc.HelpCenterMode.signedIn,
                        );
                        return;
                      }
                      if (v == 'sign_out') {
                        final app = context.read<AppState>();
                        final hadLastVaultName = app.lastVaultName != null;
                        await app.signOutEverywhere();
                        if (context.mounted) {
                          Navigator.pushNamedAndRemoveUntil(
                            context,
                            hadLastVaultName ? '/unlock' : '/login',
                            (_) => false,
                          );
                        }
                      }
                    },
                    child: Container(
                      constraints:
                          BoxConstraints(maxWidth: accountChipMaxWidth),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 14, vertical: 10),
                      decoration: BoxDecoration(
                        color: const Color(0xFF262626),
                        borderRadius: BorderRadius.circular(28),
                        border: Border.all(color: Colors.white10),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.account_circle_outlined,
                              size: 22, color: Color(0xFFB4B4B4)),
                          const SizedBox(width: 8),
                          Flexible(
                            child: Text(
                              app.displayName ?? 'Account',
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                          ),
                          const SizedBox(width: 4),
                          const Icon(Icons.expand_more_rounded, size: 18),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ],
    );
  }
}

/// Client-side mirror of the backend's `_default_asset_type_for_upload`.
///
/// Returns a stable asset_type slug ('image', 'video', 'audio',
/// 'pdf', 'docx', 'spreadsheet', 'id_image', 'file') derived from
/// filename + MIME type. The mapping intentionally mirrors the
/// backend heuristic so that ZK vault clients — which encrypt this
/// value locally and POST the ciphertext to
/// /vault/ciphertext/uploaded-files — produce the same UX as
/// non-ZK vaults where the backend does the mapping.
///
/// Filename-only heuristic: NEVER opens the file body. Safe to run
/// after a chunked upload finalize returns just a file_id.
String inferAssetTypeForUpload({
  required String fileName,
  required String? contentType,
}) {
  final ct = (contentType ?? '').toLowerCase();
  final name = fileName.toLowerCase();

  if (ct.startsWith('image/') ||
      name.endsWith('.jpg') ||
      name.endsWith('.jpeg') ||
      name.endsWith('.png') ||
      name.endsWith('.gif') ||
      name.endsWith('.webp') ||
      name.endsWith('.heic')) {
    // Identity documents that arrive as photos still classify as
    // id_image so the vault UI can group them properly.
    for (final tok in const [
      'passport',
      'driver license',
      'drivers license',
      "driver's license",
      'photo id',
      'id card',
      'identity card',
      'national id',
    ]) {
      if (name.contains(tok)) return 'id_image';
    }
    return 'image';
  }

  if (ct.startsWith('video/') ||
      name.endsWith('.mp4') ||
      name.endsWith('.mov') ||
      name.endsWith('.webm') ||
      name.endsWith('.mkv')) {
    return 'video';
  }

  if (ct.startsWith('audio/') ||
      name.endsWith('.mp3') ||
      name.endsWith('.wav') ||
      name.endsWith('.m4a') ||
      name.endsWith('.ogg') ||
      name.endsWith('.flac')) {
    return 'audio';
  }

  if (name.endsWith('.pdf')) return 'pdf';
  if (name.endsWith('.docx')) return 'docx';
  if (name.endsWith('.xlsx')) return 'spreadsheet';

  return 'file';
}

/// Client-side heuristic for detected_type/detected_service.
/// Returns the pair as (detected_type, detected_service). Both are
/// null if no confident inference can be made from the filename
/// alone. NEVER opens the file body.
({String? detectedType, String? detectedService})
    inferDetectedTypeAndServiceForUpload({
  required String fileName,
}) {
  final name = fileName.toLowerCase();
  String? dt;
  String? ds;
  if (name.contains('passport')) dt = 'passport';
  if (name.contains('driver license') ||
      name.contains('drivers license') ||
      name.contains("driver's license") ||
      name.contains('driver licence')) {
    dt = 'driver_license';
  }
  if (name.contains('id card') ||
      name.contains('identity card') ||
      name.contains('national id')) {
    dt = 'id_card';
  }
  // Filename-based service hints: keep conservative to avoid false
  // positives. The backend runs richer OCR-based detection; when
  // that lands as a client-finalized flow, this heuristic will be
  // superseded.
  for (final entry in const {
    'chase': 'chase',
    'wells fargo': 'wells_fargo',
    'wellsfargo': 'wells_fargo',
    'bank of america': 'bank_of_america',
    'boa': 'bank_of_america',
    'citi': 'citi',
    'amex': 'american_express',
    'american express': 'american_express',
    'paypal': 'paypal',
    'venmo': 'venmo',
    'coinbase': 'coinbase',
    'binance': 'binance',
  }.entries) {
    if (name.contains(entry.key)) {
      ds = entry.value;
      break;
    }
  }
  return (detectedType: dt, detectedService: ds);
}

/// ZK client-finalize of a beneficiary label. Encrypts `label`
/// locally under the active vault's metadataKey and POSTs the
/// ciphertext to /vault/ciphertext/beneficiary-links. Returns true
/// on success, false on any failure (network, crypto, HTTP error).
///
/// Non-ZK vaults (no active MVK): returns true and does nothing,
/// because the label was already persisted in plaintext by the
/// upstream /beneficiary/create call.
Future<bool> tryZkFinalizeBeneficiaryLabelCiphertext({
  required String baseUrl,
  required String authToken,
  required int linkId,
  required String label,
}) async {
  final mvk = zk_mvk_store.ZkActiveMvk.current();
  if (mvk == null) return true; // legacy vault → already persisted
  try {
    final hierarchy = vk_hier.VaultKeyHierarchy(mvk);
    final metaKey = await hierarchy.metadataKey();
    final ct = await vk_hier.aesGcmWrap(metaKey, utf8.encode(label));
    final uri = Uri.parse('$baseUrl/vault/ciphertext/beneficiary-links');
    final resp = await http.post(
      uri,
      headers: <String, String>{
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $authToken',
      },
      body: jsonEncode(<String, dynamic>{
        'link_id': linkId,
        'passer_label_ciphertext': vk_hier.b64urlEncode(ct),
      }),
    );
    return resp.statusCode == 200;
  } catch (_) {
    return false;
  }
}

String? _displayLabelString(Object? value) {
  if (value is! String) return null;
  return value.trim().isEmpty ? null : value;
}

@visibleForTesting
Future<Map<String, dynamic>> resolveOwnerBeneficiaryLabelForDisplay(
  Map<String, dynamic> row, {
  SecretKey? mvk,
}) async {
  final out = Map<String, dynamic>.from(row);
  final plaintext = _displayLabelString(out['label']);
  if (plaintext != null) {
    out['label'] = plaintext;
    return out;
  }

  final encrypted = _displayLabelString(out['passer_label_ciphertext']);
  final activeMvk = mvk ?? zk_mvk_store.ZkActiveMvk.current();
  if (encrypted == null) return out;
  out['has_stored_label'] = true;
  if (activeMvk == null) return out;

  try {
    final hierarchy = vk_hier.VaultKeyHierarchy(activeMvk);
    final metaKey = await hierarchy.metadataKey();
    final labelBytes = await vk_hier.aesGcmUnwrap(
      metaKey,
      vk_hier.b64urlDecode(encrypted),
    );
    final label = utf8.decode(labelBytes);
    if (label.trim().isNotEmpty) {
      out['label'] = label;
    }
  } catch (_) {
    // Corrupt or unavailable owner-only metadata should not break the list.
  }
  return out;
}

/// Best-effort ZK finalize of the inferred metadata for a
/// just-uploaded file. Silent no-op when the vault is not
/// ZK-adopted (legacy vaults get the backend heuristic path). For
/// ZK vaults, encrypts the inferred values under metadataKey and
/// POSTs the ciphertext to /vault/ciphertext/uploaded-files.
///
/// Fail-closed: if the POST fails, the file remains stored with
/// NULL metadata — the correct privacy failure mode. No plaintext
/// fallback ever writes to the DB.
Future<void> tryZkFinalizeInferredUploadMetadataBestEffort({
  required String baseUrl,
  required String authToken,
  required String fileId,
  required String fileName,
  required String? contentType,
}) async {
  if (zk_mvk_store.ZkActiveMvk.current() == null) return;
  try {
    final at = inferAssetTypeForUpload(
      fileName: fileName,
      contentType: contentType,
    );
    final det = inferDetectedTypeAndServiceForUpload(fileName: fileName);
    final client = VaultAIClient(baseUrl: baseUrl);
    await client.tryZkUploadedFileCiphertextUpdate(
      baseUrl: baseUrl,
      authToken: authToken,
      fileId: fileId,
      assetType: at,
      detectedType: det.detectedType,
      detectedService: det.detectedService,
    );
  } catch (_) {
    // Fail-closed: leave the row with NULL metadata rather than
    // silently reverting to plaintext. Correct privacy tradeoff.
  }
}

/// Banner shown near the vault-file search UI when the active vault
/// is ZK-adopted. Semantic content search (embeddings-based) is
/// intentionally unavailable for ZK vaults: the backend refuses to
/// index encrypted content into a vector store on OpenAI's
/// embeddings API, and the client-finalized semantic flow is not
/// yet shipped. This banner tells the user honestly that content
/// search is unavailable — it must NOT imply indexing succeeded.
///
/// Renders as a no-op (SizedBox.shrink) for non-ZK vaults.
class ZkSemanticSearchUnavailableBanner extends StatelessWidget {
  const ZkSemanticSearchUnavailableBanner({super.key});

  @override
  Widget build(BuildContext context) {
    if (zk_mvk_store.ZkActiveMvk.current() == null) {
      return const SizedBox.shrink();
    }
    return Container(
      key: const Key('zk_semantic_search_unavailable_banner'),
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF3B82F6).withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: const Color(0xFF3B82F6).withValues(alpha: 0.35),
        ),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.lock_outline, size: 18, color: Color(0xFF90CAF9)),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              'Semantic content search is unavailable for this '
              'private vault. Your files are encrypted end-to-end, '
              'and SVaultAI cannot read their content to build a '
              'search index. Filename search still works.',
              style: TextStyle(
                color: Color(0xFFCFE2FF),
                fontSize: 12,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Neutral, kind-only fallback rendering for ZK notifications.
///
/// The backend writes `title` and `body` as NULL for ZK/adopted
/// vaults (per the R3 privacy contract — no user-derived text ever
/// hits the DB in readable form). The notification bell UI must
/// still render *something* useful, without reconstructing user
/// text from server-side context. This function maps the neutral
/// `kind` slug to a fixed, generic (title, body) pair that:
///   * tells the user what happened at a categorical level,
///   * never quotes any user data (no vault_name, no device label,
///     no beneficiary label, no filename, no counterparty label),
///   * remains stable across locales' English fallback,
///   * gracefully covers unknown kinds by treating the kind slug as
///     the title in a normalized form.
///
/// File-scope so the mapping is testable in isolation and cannot
/// diverge across UI call sites.
Map<String, String> zkNotificationFallback(String? rawKind) {
  final kind = (rawKind ?? '').trim();
  switch (kind) {
    case 'transfer_requested':
      return const {
        'title': 'Beneficiary transfer requested',
        'body': 'A beneficiary linked to this vault has requested a '
            'transfer. Open the Inheritance page for details.',
      };
    case 'transfer_cancelled':
      return const {
        'title': 'Beneficiary transfer cancelled',
        'body': 'A pending beneficiary transfer for this vault was '
            'cancelled.',
      };
    case 'transfer_completed':
      return const {
        'title': 'Beneficiary transfer completed',
        'body': 'A beneficiary transfer for this vault has '
            'completed. Open the Inheritance page for details.',
      };
    case 'device_approved':
      return const {
        'title': 'Device approved',
        'body': 'A device on this vault was approved. Open the '
            'Devices page to review.',
      };
    case 'device_revoked':
      return const {
        'title': 'Device revoked',
        'body': 'A device on this vault was revoked. Open the '
            'Devices page to review.',
      };
    case 'device_approval_pending':
      return const {
        'title': 'Self-approval started on a new device',
        'body': 'A new device is pending self-approval. Open the '
            'Devices page to review or cancel.',
      };
    case 'device_self_approval_cancelled':
      return const {
        'title': 'Self-approval cancelled',
        'body': 'A device self-approval was cancelled.',
      };
    case 'credential_files':
      return const {
        'title': 'Saved credential files',
        'body': 'Files were added to this vault. Open the Vault to '
            'review.',
      };
    case 'upload':
      return const {
        'title': 'Upload activity',
        'body': 'An upload occurred on this vault.',
      };
    case '':
      return const {
        'title': 'Vault activity',
        'body': 'An update occurred on this vault.',
      };
    default:
      // Unknown / future kinds: normalize the slug so at least the
      // category surfaces without any user text.
      final title = kind
          .replaceAll('_', ' ')
          .split(' ')
          .where((w) => w.isNotEmpty)
          .map((w) => w[0].toUpperCase() + w.substring(1))
          .join(' ');
      return {
        'title': title.isEmpty ? 'Vault activity' : title,
        'body': 'An update of type "$kind" occurred on this vault.',
      };
  }
}

class _NotificationBell extends StatelessWidget {
  const _NotificationBell();

  String _ago(String? iso) {
    if (iso == null) return '';
    try {
      final t = DateTime.parse(iso).toLocal();
      final diff = DateTime.now().difference(t);
      if (diff.inMinutes < 1) return 'just now';
      if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
      if (diff.inHours < 24) return '${diff.inHours} h ago';
      return '${diff.inDays} d ago';
    } catch (_) {
      return '';
    }
  }

  void _openPanel(BuildContext context) async {
    final app = context.read<AppState>();
    await app.refreshNotifications();
    if (!context.mounted) return;

    showDialog(
      context: context,
      builder: (dialogCtx) {
        final screenSize = MediaQuery.of(dialogCtx).size;
        final dialogWidth = (screenSize.width - 32).clamp(240.0, 420.0);
        final listMaxHeight = (screenSize.height - 220).clamp(200.0, 480.0);
        final compact = screenSize.width < 400;
        return AlertDialog(
          backgroundColor: const Color(0xFF2F2F2F),
          insetPadding:
              const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
          contentPadding:
              EdgeInsets.fromLTRB(compact ? 14 : 20, 16, compact ? 14 : 20, 8),
          title: Row(
            children: [
              Expanded(
                child: Text(
                  AppLocalizations.of(dialogCtx).notificationsTitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Consumer<AppState>(
                builder: (_, a, __) => TextButton(
                  onPressed: a.unreadNotificationCount == 0
                      ? null
                      : () => a.markNotificationRead(null),
                  child: Text(
                    AppLocalizations.of(dialogCtx).notificationsMarkAllRead,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
            ],
          ),
          content: SizedBox(
            width: dialogWidth,
            child: Consumer<AppState>(
              builder: (_, a, __) {
                if (a.notifications.isEmpty) {
                  return const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Text(
                      'No notifications yet.',
                      style: TextStyle(color: Color(0xFFB4B4B4)),
                    ),
                  );
                }
                return ConstrainedBox(
                  constraints: BoxConstraints(maxHeight: listMaxHeight),
                  child: ListView.separated(
                    shrinkWrap: true,
                    itemCount: a.notifications.length,
                    separatorBuilder: (_, __) =>
                        const Divider(color: Colors.white10, height: 1),
                    itemBuilder: (_, i) {
                      final n = a.notifications[i];
                      final isUnread = n['read_at'] == null;
                      // ZK notifications: title and body are NULL
                      // (backend refuses to persist user-derived
                      // text). Fall back to a neutral kind-based
                      // label without ever reconstructing user
                      // text server-side. Non-ZK rows still show
                      // their existing title/body verbatim.
                      final rawTitle = (n['title'] ?? '').toString();
                      final rawBody = (n['body'] ?? '').toString();
                      final needsFallback =
                          rawTitle.trim().isEmpty && rawBody.trim().isEmpty;
                      final fallback = needsFallback
                          ? zkNotificationFallback(
                              n['kind']?.toString(),
                            )
                          : const <String, String>{};
                      final displayTitle = rawTitle.trim().isNotEmpty
                          ? rawTitle
                          : (fallback['title'] ?? 'Vault activity');
                      final displayBody = rawBody.trim().isNotEmpty
                          ? rawBody
                          : (fallback['body'] ??
                              'An update occurred on this vault.');
                      return InkWell(
                        onTap: isUnread
                            ? () => a.markNotificationRead(
                                (n['id'] as num?)?.toInt())
                            : null,
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                              vertical: 12, horizontal: 4),
                          color: isUnread
                              ? const Color(0xFF10A37F).withValues(alpha: 0.05)
                              : null,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  if (isUnread)
                                    Container(
                                      width: 8,
                                      height: 8,
                                      margin: const EdgeInsets.only(right: 8),
                                      decoration: const BoxDecoration(
                                        color: Color(0xFF10A37F),
                                        shape: BoxShape.circle,
                                      ),
                                    ),
                                  Expanded(
                                    child: Text(
                                      displayTitle,
                                      style: TextStyle(
                                        fontWeight: isUnread
                                            ? FontWeight.w700
                                            : FontWeight.w500,
                                        fontSize: 14,
                                      ),
                                    ),
                                  ),
                                  Text(
                                    _ago(n['created_at']?.toString()),
                                    style: const TextStyle(
                                        color: Color(0xFF8E8E8E), fontSize: 11),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                displayBody,
                                style: const TextStyle(
                                    color: Color(0xFFB4B4B4),
                                    fontSize: 12,
                                    height: 1.4),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                );
              },
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogCtx),
              child: const Text('Close'),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final unread = app.unreadNotificationCount;
    return Padding(
      padding: const EdgeInsets.only(right: 4),
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          IconButton(
            tooltip: 'Notifications',
            onPressed: () => _openPanel(context),
            icon: const Icon(Icons.notifications_outlined, size: 24),
          ),
          if (unread > 0)
            Positioned(
              right: 6,
              top: 6,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                decoration: BoxDecoration(
                  color: Colors.redAccent,
                  borderRadius: BorderRadius.circular(10),
                ),
                constraints: const BoxConstraints(minWidth: 16, minHeight: 16),
                child: Text(
                  unread > 9 ? '9+' : '$unread',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class LandingPage extends StatefulWidget {
  const LandingPage({super.key});

  @override
  State<LandingPage> createState() => _LandingPageState();
}

class _LandingPageState extends State<LandingPage> with RouteAware {
  bool _publicVisible = false;

  @override
  void initState() {
    super.initState();
    _scheduleGuard('initState');
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();

    final route = ModalRoute.of(context);
    if (route != null) {
      appRouteObserver.subscribe(this, route);
    }
  }

  @override
  void didPopNext() {
    super.didPopNext();
    if (_publicVisible) {
      setState(() {
        _publicVisible = false;
      });
    }
    _scheduleGuard('didPopNext');
  }

  void _scheduleGuard(String source) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final app = context.read<AppState>();

      if (!app.hydrated) {
        debugPrint(
          '[ROUTE-GUARD] landing loaded source=$source '
          'authed=${app.authed} unlocked=${app.unlocked} '
          'hydrated=false dest=null '
          'route=${ModalRoute.of(context)?.settings.name} '
          'redirectFired=false skipReason=not_hydrated',
        );
        return;
      }
      final dest = resolveLandingRedirect(
        authed: app.authed,
        unlocked: app.unlocked,
        lockedRoute: shouldBypassPublicLandingForAuth() ? '/unlock' : '/pin',
      );
      final routeName = ModalRoute.of(context)?.settings.name;
      debugPrint(
        '[ROUTE-GUARD] landing loaded source=$source '
        'authed=${app.authed} unlocked=${app.unlocked} '
        'hydrated=true dest=$dest '
        'route=$routeName '
        'redirectFired=${dest != null}',
      );
      if (dest != null) {
        Navigator.of(context).pushReplacementNamed(dest);
        return;
      }
      if (shouldBypassPublicLandingForAuth()) {
        Navigator.of(context).pushReplacementNamed('/login');
        return;
      }
      if (!_publicVisible) {
        setState(() {
          _publicVisible = true;
        });
      }
    });
  }

  @override
  void dispose() {
    appRouteObserver.unsubscribe(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_publicVisible) {
      return const Scaffold();
    }

    final w = MediaQuery.of(context).size.width;
    final isMobile = w < 900;

    return Scaffold(
      appBar: TopNavBar(isMobile: w < 760),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1100),
          child: Padding(
            padding: EdgeInsets.symmetric(
                horizontal: isMobile ? 18 : 28, vertical: isMobile ? 18 : 30),
            child: isMobile
                ? const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [_HeroText(), SizedBox(height: 20), _HeroCard()],
                  )
                : const Row(
                    children: [
                      Expanded(child: _HeroText()),
                      SizedBox(width: 40),
                      Expanded(child: _HeroCard())
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

class _HeroText extends StatelessWidget {
  const _HeroText();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Your private AI vault.',
          style: Theme.of(context)
              .textTheme
              .headlineMedium
              ?.copyWith(fontWeight: FontWeight.w800, height: 1.1),
        ),
        const SizedBox(height: 14),
        const Text(
          'SVaultAI helps you save logins, IDs, cards, files, photos, and notes, then retrieve them naturally in chat.',
          style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 16, height: 1.6),
        ),
        const SizedBox(height: 22),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            FilledButton(
              onPressed: () => Navigator.pushNamed(context, '/signup'),
              child: Text(AppLocalizations.of(context).commonSignUp),
            ),
            OutlinedButton(
              onPressed: () => Navigator.pushNamed(context, '/login'),
              child: Text(AppLocalizations.of(context).commonSignIn),
            ),
          ],
        ),
      ],
    );
  }
}

class _HeroCard extends StatelessWidget {
  const _HeroCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        color: const Color(0xFF2F2F2F),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.lock_outline, size: 42, color: Color(0xFF10A37F)),
          const SizedBox(height: 12),
          Text(
            AppLocalizations.of(context).landingHowItWorks,
            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18),
          ),
          const SizedBox(height: 10),
          const Text(
            '1. Pick a vault name and a PIN — that is your account\n2. Returning users: enter your PIN to unlock\n3. Save secrets or upload files\n4. Ask your vault anything',
            textAlign: TextAlign.center,
            style: TextStyle(color: Color(0xFFB4B4B4), height: 1.6),
          ),
        ],
      ),
    );
  }
}

Future<void> _registerDeviceBestEffort(String authToken) async {
  try {
    final id = currentDeviceId() ?? await getOrCreateDeviceId();
    await VaultAIClient(baseUrl: backendBaseUrl).registerDevice(
      authToken: authToken,
      deviceId: id,
      label: currentDeviceLabel(),
    );
  } catch (_) {}
}

void _refreshSessionListsBestEffort(AppState app) {
  unawaited(() async {
    try {
      await app.refreshAvailableVaults();
    } catch (_) {}
    try {
      await app.refreshNotifications();
    } catch (_) {}
  }());
}

/// Decide whether a failed consume call should keep the pending
/// token around for a later login attempt.
///
/// Only ``INH-DEV-004`` (the caller's current session is not the
/// inherited owner) means "we may still succeed on a subsequent
/// login to a different account". Every other error — expired,
/// replayed, wrong device, revoked release, missing session — makes
/// the token permanently useless, so we clear it and let the user
/// go through the reveal → authorize flow again if they need to.
///
/// Exposed as a top-level function for unit tests.
bool shouldPreservePendingInheritanceToken(String errorText) {
  return errorText.contains('INH-DEV-004');
}

@visibleForTesting
enum InheritanceRevealLocalKeyStatus {
  ready,
  invalidPin,
  missingLocalKey,
}

@visibleForTesting
class InheritanceRevealLocalKeyResult {
  final InheritanceRevealLocalKeyStatus status;
  final SecretKey? skVault;
  final String reason;

  const InheritanceRevealLocalKeyResult._(
    this.status,
    this.skVault,
    this.reason,
  );

  const InheritanceRevealLocalKeyResult.ready(
    SecretKey skVault, {
    String reason = 'ready',
  }) : this._(InheritanceRevealLocalKeyStatus.ready, skVault, reason);

  const InheritanceRevealLocalKeyResult.invalidPin({
    String reason = 'invalid_pin',
  }) : this._(InheritanceRevealLocalKeyStatus.invalidPin, null, reason);

  const InheritanceRevealLocalKeyResult.missingLocalKey({
    String reason = 'missing_local_key',
  }) : this._(InheritanceRevealLocalKeyStatus.missingLocalKey, null, reason);
}

typedef InheritanceCachedPinCheck = Future<bool?> Function(String pin);
typedef InheritanceUnlockWithPin = Future<bool> Function(String pin);
typedef InheritanceSkReader = SecretKey? Function();
typedef InheritanceSkVaultIdReader = String? Function();
typedef InheritanceSkRehydrate = Future<SecretKey?> Function(String pin);

@visibleForTesting
class InheritanceRevealLoginIdentifier {
  final String? vaultName;
  final String? vaultHandle;
  final String source;

  const InheritanceRevealLoginIdentifier({
    required this.vaultName,
    required this.vaultHandle,
    required this.source,
  });

  bool get hasIdentifier =>
      (vaultName != null && vaultName!.isNotEmpty) ||
      (vaultHandle != null && vaultHandle!.isNotEmpty);
}

String? _nonEmptyTrimmed(String? value) {
  final trimmed = value?.trim();
  return trimmed == null || trimmed.isEmpty ? null : trimmed;
}

String inheritanceRevealIdFingerprint(String? value) {
  final trimmed = _nonEmptyTrimmed(value);
  if (trimmed == null) return '-';
  return _fp12(Uint8List.fromList(utf8.encode(trimmed)));
}

void inheritanceRevealDiag(String branch, [Map<String, Object?>? data]) {
  final payload = data == null
      ? ''
      : data.entries.map((e) => '${e.key}=${e.value}').join(' ');
  // Values passed here must be closed-set branch names, booleans,
  // or short one-way fingerprints only. Never pass PINs, keys,
  // tokens, ciphertext, or decrypted values.
  releaseWebDiagnosticPrint(
    '[inheritance-reveal-diag] branch=$branch $payload',
  );
}

@visibleForTesting
InheritanceRevealLoginIdentifier selectInheritanceRevealLoginIdentifier({
  required String? vaultName,
  required String? lastVaultName,
  required String? vaultHandle,
}) {
  final handle = _nonEmptyTrimmed(vaultHandle);
  if (handle != null) {
    return InheritanceRevealLoginIdentifier(
      vaultName: null,
      vaultHandle: handle,
      source: 'stored_vault_handle',
    );
  }

  final name = _nonEmptyTrimmed(vaultName) ?? _nonEmptyTrimmed(lastVaultName);
  if (name == null) {
    return const InheritanceRevealLoginIdentifier(
      vaultName: null,
      vaultHandle: null,
      source: 'none',
    );
  }
  if (vh.isValidVaultHandleDisplay(name)) {
    return InheritanceRevealLoginIdentifier(
      vaultName: null,
      vaultHandle: name,
      source: 'name_is_vault_handle',
    );
  }
  return InheritanceRevealLoginIdentifier(
    vaultName: name,
    vaultHandle: null,
    source: vaultName != null && vaultName.trim().isNotEmpty
        ? 'vault_name'
        : 'last_vault_name',
  );
}

@visibleForTesting
Future<InheritanceRevealLocalKeyResult> resolveInheritanceRevealLocalKey({
  required String vaultId,
  required String pin,
  required InheritanceCachedPinCheck cachedPinMatches,
  required InheritanceUnlockWithPin unlockWithPin,
  required InheritanceSkReader currentSk,
  required InheritanceSkVaultIdReader currentSkVaultId,
  required InheritanceSkRehydrate rehydrateSkWithPin,
}) async {
  SecretKey? usableCurrentSk() {
    final sk = currentSk();
    if (sk == null) return null;
    if (currentSkVaultId() != vaultId) return null;
    return sk;
  }

  final cachedMatch = await cachedPinMatches(pin);
  if (cachedMatch == false) {
    return const InheritanceRevealLocalKeyResult.invalidPin(
      reason: 'cached_pin_mismatch',
    );
  }
  if (cachedMatch == null) {
    final unlocked = await unlockWithPin(pin);
    if (!unlocked) {
      return const InheritanceRevealLocalKeyResult.invalidPin(
        reason: 'pin_unlock_rejected',
      );
    }
  }

  final active = usableCurrentSk();
  if (active != null) {
    return InheritanceRevealLocalKeyResult.ready(
      active,
      reason: 'active_sk_ready',
    );
  }

  final rehydrated = await rehydrateSkWithPin(pin);
  if (rehydrated != null) {
    return InheritanceRevealLocalKeyResult.ready(
      rehydrated,
      reason: 'rehydrated_sk_ready',
    );
  }
  final afterRehydrate = usableCurrentSk();
  if (afterRehydrate != null) {
    return InheritanceRevealLocalKeyResult.ready(
      afterRehydrate,
      reason: 'active_sk_ready_after_rehydrate',
    );
  }
  return const InheritanceRevealLocalKeyResult.missingLocalKey(
    reason: 'missing_sk_after_rehydrate',
  );
}

/// Best-effort consume of any pending inheritance device-enrollment
/// token immediately after a successful login. If the token matches
/// the account the caller just logged in to (and the current device),
/// the backend flips the device row to ``trusted`` and returns 200 —
/// no second manual step is required.
///
/// If no token is pending (the vast majority of logins), this is a
/// silent no-op so normal login behaviour is unchanged for every
/// non-inheritance user.
Future<void> _autoConsumeInheritanceTokenIfPresent(
  String authToken,
  AppState app,
) async {
  final token = app.pendingInheritanceDeviceToken;
  if (token == null || token.isEmpty) return;
  try {
    await VaultAIClient(baseUrl: backendBaseUrl)
        .consumeInheritanceDeviceAuthorization(
      token: token,
      authToken: authToken,
    );
    // Success: this device is trusted on the inherited account
    // and the one-time token is now consumed server-side. Clear it
    // so a re-login doesn't try to replay.
    app.pendingInheritanceDeviceToken = null;
    _notifyNewDeviceTrustedIfNeeded(true);
  } catch (e) {
    final msg = e.toString();
    if (shouldPreservePendingInheritanceToken(msg)) {
      // Wrong account — the caller might log in as the inherited
      // owner on the next attempt.
      vlog('inheritance.consume.wrong_account', const {});
      return;
    }
    vlog('inheritance.consume.exhausted', {'error': msg});
    app.pendingInheritanceDeviceToken = null;
  }
}

void _notifyNewDeviceTrustedIfNeeded(bool flag) {
  if (!flag) return;
  final messenger = rootScaffoldMessengerKey.currentState;
  if (messenger == null) return;

  final ctx = messenger.context;
  String label = 'New device trusted.';
  try {
    label = AppLocalizations.of(ctx).snackDeviceTrusted;
  } catch (_) {}
  messenger.clearSnackBars();
  messenger.showSnackBar(
    SnackBar(
      content: Text(label),
      behavior: SnackBarBehavior.floating,
    ),
  );
}

Widget _authErrorBox(String text) {
  return Container(
    width: double.infinity,
    margin: const EdgeInsets.only(top: 10),
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(
      color: Colors.red.withValues(alpha: 0.10),
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: Colors.red.withValues(alpha: 0.25)),
    ),
    child: Text(text, style: const TextStyle(color: Colors.redAccent)),
  );
}

Future<Map<String, dynamic>> _zkHttpPost(
  String path,
  Map<String, dynamic> body, {
  String? bearerToken,
}) async {
  final uri = Uri.parse('$backendBaseUrl$path');
  final headers = <String, String>{'Content-Type': 'application/json'};
  final deviceId = apiClientDeviceId();
  if (deviceId != null && deviceId.isNotEmpty) {
    headers['X-Device-Id'] = deviceId;
  }
  if (bearerToken != null && bearerToken.isNotEmpty) {
    headers['Authorization'] = 'Bearer $bearerToken';
  }
  final requestBody = Map<String, dynamic>.from(body);
  if (path == '/auth/zk-login-finalize' &&
      deviceId != null &&
      deviceId.isNotEmpty) {
    requestBody.putIfAbsent('device_id', () => deviceId);
  }
  final response = await http.post(
    uri,
    headers: headers,
    body: jsonEncode(requestBody),
  );
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw Exception(
      'ZK POST $path failed ${response.statusCode}: ${response.body}',
    );
  }
  final decoded = jsonDecode(response.body);
  if (decoded is! Map<String, dynamic>) {
    throw Exception('ZK POST $path returned non-object body');
  }
  return decoded;
}

Future<Map<String, dynamic>> _zkHttpGet(
  String path, {
  String? bearerToken,
}) async {
  final uri = Uri.parse('$backendBaseUrl$path');
  final headers = <String, String>{};
  if (bearerToken != null && bearerToken.isNotEmpty) {
    headers['Authorization'] = 'Bearer $bearerToken';
  }
  final response = await http.get(uri, headers: headers);
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw Exception(
      'ZK GET $path failed ${response.statusCode}: ${response.body}',
    );
  }
  final decoded = jsonDecode(response.body);
  if (decoded is! Map<String, dynamic>) {
    return <String, dynamic>{};
  }
  return decoded;
}

/// Fire-and-forget lazy metadata migration triggered after unlock.
///
/// 2026-07-22 (2) — CORRECTED after the crypto-context refactor.
/// The prior version read the MVK from `_VaultCrypto._keyCache` and
/// re-published it to `ZkActiveMvk`. That is now WRONG: the
/// atomic-context refactor's legacy-mirror step overwrites the
/// _keyCache slot with the PBKDF2 vault key (so `/chat` decrypt
/// works), so reading _keyCache here would publish the PBKDF2 key
/// as if it were the MVK — silently corrupting every downstream ZK
/// metadata encrypt.
///
/// New source of truth for MVK: [ZkActiveMvk.current] — populated
/// EXPLICITLY at each ZK login/signup site right after OPAQUE
/// unwrap. This helper only publishes when a live MVK is already
/// visible (i.e. the caller went through a ZK path); legacy vaults
/// have no MVK and this helper safely no-ops for them.
void _scheduleMetadataMigration({required AppState app}) {
  final token = app.sessionToken;
  final vaultName = app.vaultName;
  final vaultId = app.vaultId;
  if (token == null || vaultName == null || vaultId == null) return;
  // Read the MVK from the authoritative ZK-metadata store. Legacy
  // vaults leave this null; the migration is a no-op there.
  final mvk = zk_mvk_store.ZkActiveMvk.current();
  if (mvk == null) return;

  unawaited(mmc.runMetadataMigrationBestEffort(
    mvk: mvk,
    sessionToken: token,
    post: _zkHttpPost,
    get: _zkHttpGet,
  ));
}

/// Best-effort transparent adoption after successful legacy unlock.
/// A failure never breaks the user's session. Returns true if the
/// widget already navigated to the save screen (caller must skip its
/// own navigation), false otherwise.
Future<bool> _tryLegacyAdoptionBestEffort({
  required BuildContext context,
  required AppState app,
  required String pin,
}) async {
  final token = app.sessionToken;
  final vaultName = app.vaultName;
  final vaultId = app.vaultId;
  if (token == null || vaultName == null || vaultId == null) return false;
  if (!_VaultCrypto.hasKeyFor(vaultId: vaultId, vaultName: vaultName)) {
    return false;
  }

  try {
    final SecretKey? legacyKey =
        _VaultCrypto._keyCache[_VaultCrypto._ck(vaultId, vaultName)];
    if (legacyKey == null) return false;

    final result = await legacy_adopt.tryAdoptLegacyVault(
      legacyDisplayName: app.displayName ?? vaultName,
      pin: pin,
      legacyVaultKey: legacyKey,
      sessionToken: token,
      post: _zkHttpPost,
      get: _zkHttpGet,
    );

    if (result.adopted && result.newVaultHandle != null) {
      app.vaultHandle = result.newVaultHandle;
      try {
        await NativeSecureStore.writeString(
          'last_vault_handle',
          result.newVaultHandle!,
        );
      } catch (_) {}
      if (!context.mounted) return true;
      // Adoption completes silently and the user lands in /chat. The
      // internal vault handle is stored via legacy_adoption for
      // subsequent ZK login, but the user never sees it — SVaultAI's
      // user-facing credentials are username + PIN only.
      Navigator.of(context).pushReplacementNamed('/chat');
      return true;
    }
    return false;
  } catch (_) {
    // Adoption failure is non-fatal: legacy unlock succeeded and the
    // user's session is intact. The next unlock will retry.
    return false;
  }
}

Future<bool> _deriveKeyAndUnlock({
  required AppState app,
  required String pin,
}) async {
  final vaultName = app.vaultName;
  final vaultId = app.vaultId;
  final token = app.sessionToken;
  if (vaultName == null || vaultId == null || token == null) return false;

  final vaultMeta = await _API.getVaultMeta(
    vaultName: vaultName,
    authToken: token,
  );
  final pinSalt = vaultMeta['pin_salt']?.toString();
  if (pinSalt == null || pinSalt.isEmpty) {
    throw Exception('Backend did not return pin salt');
  }
  final iterations = (vaultMeta['kdf_iterations'] as num?)?.toInt() ?? 100000;

  final _unlockCtx = await deriveAndInstallCryptoContext(
    vaultId: vaultId,
    vaultName: vaultName,
    pin: pin,
    pinSaltBase64: pinSalt,
    iterations: iterations,
    source: 'legacy_unlock',
  );
  if (_unlockCtx == null) {
    vlog('unlock.derive.superseded', {'vaultName': vaultName});
    return false;
  }
  app.markUnlocked();

  _refreshSessionListsBestEffort(app);
  _scheduleMetadataMigration(app: app);
  return true;
}

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> with RouteAware {
  final vaultNameCtrl = TextEditingController();
  final pinCtrl = TextEditingController();
  bool loading = false;
  String? err;
  bool _isZkHandleInput = false;

  bool _showForm = false;

  @override
  void initState() {
    super.initState();
    _scheduleGuard('initState');
    _autofillCachedHandle();
    vaultNameCtrl.addListener(_maybeMarkZkHandle);
  }

  void _maybeMarkZkHandle() {
    final zk = vh.isValidVaultHandleDisplay(vaultNameCtrl.text.trim());
    if (zk != _isZkHandleInput) {
      setState(() => _isZkHandleInput = zk);
    }
  }

  Future<void> _autofillCachedHandle() async {
    // Prefer the persisted vault name (last_vault_name) — that's
    // what the user actually types to sign in. Fall back to the
    // cached VLT handle only if we don't have a vault name yet
    // (e.g. an adopted-legacy account whose signup happened before
    // we started persisting it). We never overwrite whatever the
    // user has already started typing.
    //
    // Back-compat: read the legacy pre-2026-07-20 keys
    // (last_canonical_username / last_display_username) if the new
    // key isn't populated yet — hydrate() migrates them into the
    // new key on next launch.
    try {
      final sp = await SharedPreferences.getInstance();
      final persistedName =
          await NativeSecureStore.readString('last_vault_name') ??
              sp.getString('last_canonical_username') ??
              sp.getString('last_display_username');
      if (!mounted) return;
      if (persistedName != null &&
          persistedName.isNotEmpty &&
          vaultNameCtrl.text.isEmpty) {
        vaultNameCtrl.text = persistedName;
        _maybeMarkZkHandle();
        return;
      }
      final cached = await legacy_adopt.readCachedVaultHandle();
      if (!mounted) return;
      if (cached != null && cached.isNotEmpty && vaultNameCtrl.text.isEmpty) {
        vaultNameCtrl.text = cached;
        _maybeMarkZkHandle();
      }
    } catch (_) {}
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route != null) {
      appRouteObserver.subscribe(this, route);
    }
  }

  @override
  void didPopNext() {
    super.didPopNext();
    if (_showForm) setState(() => _showForm = false);
    _scheduleGuard('didPopNext');
  }

  void _scheduleGuard(String source) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final app = context.read<AppState>();
      if (!app.hydrated) return;

      final dest = resolveLandingRedirect(
        authed: app.authed,
        unlocked: app.unlocked,
        lockedRoute: shouldBypassPublicLandingForAuth() ? '/unlock' : '/pin',
      );
      debugPrint(
        '[ROUTE-GUARD] login loaded source=$source '
        'authed=${app.authed} unlocked=${app.unlocked} '
        'hydrated=true dest=$dest '
        'redirectFired=${dest != null}',
      );
      if (dest != null) {
        Navigator.of(context).pushReplacementNamed(dest);
        return;
      }

      if (app.lastVaultName != null && app.lastVaultName!.isNotEmpty) {
        Navigator.of(context).pushReplacementNamed('/unlock');
        return;
      }
      if (!_showForm) setState(() => _showForm = true);
    });
  }

  @override
  void dispose() {
    appRouteObserver.unsubscribe(this);
    super.dispose();
  }

  Future<void> _submit() async {
    final vaultName = vaultNameCtrl.text.trim();
    final pin = pinCtrl.text.trim();
    if (vaultName.isEmpty) {
      setState(() => err = 'Enter your vault name.');
      return;
    }
    final digitsOnly = RegExp(r'^\d+$');
    if (!digitsOnly.hasMatch(pin)) {
      setState(() => err = 'PIN can only contain digits.');
      return;
    }
    if (pin.length < 6) {
      setState(() => err = 'PIN must be at least 6 digits.');
      return;
    }
    if (pin.length > 64) {
      setState(() => err = 'PIN must be 64 digits or fewer.');
      return;
    }
    setState(() {
      loading = true;
      err = null;
    });

    final authTiming = Stopwatch()..start();
    void pageTiming(
      String stage, {
      bool success = true,
      int? httpStatus,
    }) {
      authTimingDiagnosticPrint(
        stage,
        authTiming.elapsed,
        success: success,
        httpStatus: httpStatus,
      );
    }

    pageTiming('submit_entry');
    final app = context.read<AppState>();

    // Post-2026-07-19 primary login path: derive the vault_handle
    // from the entered username and hit /auth/zk-login-init.
    // A legacy VLT-XXXX handle typed by an adopted user is also
    // accepted — routed via the handle branch of loginVault.
    // If the ZK lookup 401s (unknown handle), fall through to the
    // pre-ZK legacy /auth/login below for true-legacy accounts.
    final bool entryIsHandle = vh.isValidVaultHandleDisplay(vaultName);

    // Preflight: verify the entered identifier is derivable BEFORE
    // touching the network. Any exception (InvalidUsername from a
    // malformed input, a bang-null somewhere in the derivation
    // chain) is turned into a controlled error message — never a
    // raw "Null check operator used on a null value" leaks to the
    // user. This also produces a diagnostic vlog line so a future
    // regression can be pinpointed from production logs.
    try {
      if (entryIsHandle) {
        vh.vaultHandleFromDisplay(vaultName);
      } else {
        vh.deriveVaultHandleFromUsername(vaultName);
      }
      vlog('login.preflight.ok', {
        'entry_type': entryIsHandle ? 'handle' : 'username',
        'identifier_len': vaultName.length,
        'pin_len': pin.length,
        'auth_path': 'zk_first_then_legacy_fallback',
      });
    } on vh.InvalidUsername catch (e) {
      releaseWebDiagnosticPrint('[zk-login-diag] '
          'last_step=preflight type=InvalidUsername reason=${e.message}');
      vlog('login.preflight.invalid_username', {'reason': e.message});
      setState(() {
        err = 'Please enter your username.';
        loading = false;
      });
      return;
    } on vh.InvalidVaultHandle catch (e) {
      releaseWebDiagnosticPrint('[zk-login-diag] '
          'last_step=preflight type=InvalidVaultHandle reason=${e.message}');
      vlog('login.preflight.invalid_handle', {'reason': e.message});
      setState(() {
        err = 'Please enter your username.';
        loading = false;
      });
      return;
    } catch (e, stack) {
      final typeName = e.runtimeType.toString();
      final msg = e.toString();
      final head = msg.length > 120 ? msg.substring(0, 120) : msg;
      releaseWebDiagnosticPrint('[zk-login-diag] '
          'last_step=preflight type=$typeName head=$head');
      debugAuthFailureTrace('zk-login-diag', e, stack, step: 'preflight');
      vlog('login.preflight.derivation_failed',
          {'error_type': typeName, 'error': msg});
      setState(() {
        err = kAuthDeviceSafeError;
        loading = false;
      });
      return;
    }

    // Step tracker for post-preflight diagnostics.
    //
    // The pre-2026-07-21 build surfaced "Login failed. Please try
    // again." with no clue WHICH step in the ZK login pipeline
    // threw. When the operator sees no /auth/zk-login-init request
    // hit the backend, the failure is by definition before the first
    // POST — the step recorded here is the last one that COMPLETED,
    // so the failing step is (recorded + 1) in the pipeline order.
    //
    // Steps emitted by ZkAuthService.loginVault:
    //   begin, opaque_ready, derive_handle, handle_encoded,
    //   opaque_start_login, post_login_init,   <-- first HTTP
    //   opaque_finish_login, post_login_finalize, decode_response,
    //   unwrap_mvk, unwrap_display_name.
    // The LoginPage's OWN post-loginVault steps use the ``page_``
    // prefix so operators can distinguish page-side from service-side.
    String loginLastStep = 'submit_entry';
    bool zkLoginNotFound = false;
    {
      try {
        releaseWebDiagnosticPrint('[zk-login-step] page/submit_entry '
            'entry_type=${entryIsHandle ? "handle" : "username"} '
            'identifier_len=${vaultName.length} pin_len=${pin.length}');
        vlog('login.zk.attempt', {
          'entry_type': entryIsHandle ? 'handle' : 'username',
        });
        await OpaqueClient.ready();
        loginLastStep = 'page_opaque_ready';
        final zk = ZkAuthService(_zkHttpPost);
        final loginResult = await zk.loginVault(
          vaultName: entryIsHandle ? null : vaultName,
          vaultHandle: entryIsHandle ? vaultName : null,
          pin: pin,
          onStep: (s) => loginLastStep = s,
        );
        loginLastStep = 'page_zk_login_returned';
        // Product-name resolution priority: server-authoritative
        // (backfilled vault_name) > user-typed (when entry was a
        // vault name) > displayName (legacy fallback). Never the
        // VLT handle.
        final resolvedVaultName = loginResult.vaultName ??
            (entryIsHandle ? loginResult.displayName : vaultName);
        await app.setSession(
          token: loginResult.sessionToken,
          vaultIdValue: loginResult.vaultId,
          vaultNameValue: resolvedVaultName,
          vaultHandleValue: loginResult.vaultHandle,
          displayNameValue: loginResult.displayName,
        );
        pageTiming('secure_store_complete');
        await _registerDeviceBestEffort(loginResult.sessionToken);
        await _autoConsumeInheritanceTokenIfPresent(
          loginResult.sessionToken,
          app,
        );
        // 2026-07-22 crypto-context refactor. The MVK unwrapped by
        // OPAQUE is preserved in the legacy _keyCache slot for the
        // ZK metadata surface (ZkActiveMvk publish below reads it).
        // But it is NOT the vault key /chat's server-side decrypt
        // uses: /chat derives PBKDF2(pin, vaults.pin_salt,
        // vaults.kdf_iterations) from the current DB row. For
        // ZK-adopted vaults rotated after adoption, MVK != current
        // PBKDF2 key — that divergence was the production
        // first-chat-fail symptom (LoginPage path).
        //
        // Fix: install the atomic VaultCryptoContext with the
        // FRESHLY-DERIVED PBKDF2 key from current /vault-meta.
        // /chat now reads exclusively from VaultCryptoRegistry.
        _VaultCrypto._keyCache[
                _VaultCrypto._ck(loginResult.vaultId, resolvedVaultName)] =
            loginResult.mvk;
        _VaultCrypto._pinCache[
            _VaultCrypto._ck(loginResult.vaultId, resolvedVaultName)] = pin;
        _VaultCrypto.setActiveVault(
          vaultId: loginResult.vaultId,
          vaultName: resolvedVaultName,
        );
        // Publish MVK to the ZK metadata surface BEFORE the PBKDF2
        // derive-and-install below mirrors the vault key into
        // _keyCache (overwriting the MVK slot). ZkActiveMvk is the
        // authoritative source for MVK downstream (see
        // _scheduleMetadataMigration).
        zk_mvk_store.ZkActiveMvk.set(
          mvk: loginResult.mvk,
          vaultId: loginResult.vaultId,
          vaultHandle: loginResult.vaultHandle,
        );
        try {
          final _zkLoginMeta = await _API.getVaultMeta(
            vaultName: resolvedVaultName,
            authToken: loginResult.sessionToken,
          );
          final _zkLoginSalt = _zkLoginMeta['pin_salt']?.toString();
          final _zkLoginIter =
              (_zkLoginMeta['kdf_iterations'] as num?)?.toInt();
          if (_zkLoginSalt != null &&
              _zkLoginSalt.isNotEmpty &&
              _zkLoginIter != null) {
            final _zkLoginCtx = await deriveAndInstallCryptoContext(
              vaultId: loginResult.vaultId,
              vaultName: resolvedVaultName,
              pin: pin,
              pinSaltBase64: _zkLoginSalt,
              iterations: _zkLoginIter,
              source: 'zk_login',
            );
            if (_zkLoginCtx == null) {
              vlog('login.zk.derive.superseded', {
                'vaultName': resolvedVaultName,
              });
            }
            pageTiming('vault_pbkdf2_complete');
          } else {
            vlog('login.zk.meta_missing_fields', {
              'has_salt': _zkLoginSalt != null,
              'has_iter': _zkLoginIter != null,
            });
          }
        } catch (e) {
          vlog('login.zk.pbkdf2_derive_failed', {
            'error': e.toString(),
            'vaultName': resolvedVaultName,
          });
        }
        // Cache the X25519 private key so the inheritance credential
        // reveal path can decrypt without another OPAQUE round-trip.
        // Cleared on logout / vault switch.
        zk_sk_store.ZkActiveSkVault.set(
          skVault: loginResult.skVaultPrivate,
          vaultId: loginResult.vaultId,
        );
        inheritanceRevealDiag('normal_login_zk_success', {
          'vault_fpr': inheritanceRevealIdFingerprint(loginResult.vaultId),
          'has_vault_handle': loginResult.vaultHandle.isNotEmpty,
          'active_sk_present': zk_sk_store.ZkActiveSkVault.current() != null,
          'active_sk_vault_match':
              zk_sk_store.ZkActiveSkVault.currentVaultId() ==
                  loginResult.vaultId,
        });
        app.markUnlocked();
        _refreshSessionListsBestEffort(app);
        pageTiming('session_hydrated');
        // Both post-login side-effects below can throw independently
        // of the authenticated session. If either raises, the user
        // is ALREADY authenticated — we must not surface a raw
        // exception ("Null check operator used on a null value") as
        // if the login itself failed. Swallow-and-log so the user
        // still lands on /chat.
        try {
          _scheduleMetadataMigration(app: app);
        } catch (e) {
          vlog('login.post_login_side_effect_failed',
              {'step': 'schedule_metadata_migration', 'error': e.toString()});
        }
        try {
          await NativeSecureStore.writeString(
            legacy_adopt.prefsVaultHandleKey,
            loginResult.vaultHandle,
          );
        } catch (_) {}
        if (!mounted) return;
        pageTiming('authenticated_route_visible');
        Navigator.pushReplacementNamed(context, '/chat');
        return;
      } on OpaqueUnavailable catch (e, stack) {
        releaseWebDiagnosticPrint('[zk-login-diag] '
            'last_step=$loginLastStep type=OpaqueUnavailable reason=${e.reason}');
        debugAuthFailureTrace('zk-login-diag', e, stack, step: loginLastStep);
        if (!mounted) return;
        setState(() {
          err = kAuthDeviceSafeError;
          loading = false;
        });
        return;
      } on OpaqueAuthenticationFailed catch (e) {
        // Wrong PIN — @serenity-kit/opaque returned undefined from
        // client.finishLogin, meaning the OPAQUE handshake could not
        // be completed against the stored registration record. Fail
        // closed on the ZK side; the legacy /auth/login fallback
        // MUST NOT run (an OPAQUE auth failure is a definitive
        // "wrong PIN" — retrying against the plaintext-verifier path
        // would produce the same result and just leak timing info).
        releaseWebDiagnosticPrint('[zk-login-diag] '
            'last_step=$loginLastStep type=OpaqueAuthenticationFailed stage=${e.stage}');
        vlog('login.zk.opaque_auth_failed', {'stage': e.stage});
        if (!mounted) return;
        setState(() {
          err = 'Wrong username or PIN.';
          loading = false;
        });
        return;
      } on RateLimitedException catch (e) {
        if (!mounted) return;
        setState(() {
          err = e.message;
          loading = false;
        });
        return;
      } catch (e, stack) {
        if (app.handleApiException(e)) return;
        final msg = e.toString();
        final typeName = e.runtimeType.toString();
        final head = msg.length > 120 ? msg.substring(0, 120) : msg;
        // Unconditional console log — fires in release builds too so
        // an operator can grep the browser DevTools console for
        // "[zk-login-diag]" without a debug build. No PIN, token,
        // ciphertext or handle bytes are printed.
        releaseWebDiagnosticPrint('[zk-login-diag] '
            'last_step=$loginLastStep type=$typeName head=$head');
        // First line of the stack — the top frame usually names the
        // exact file+line that threw, which is the fastest way to
        // identify a bang null in a minified web build.
        final stackLines = stack.toString().split('\n');
        final topFrame = stackLines.isNotEmpty ? stackLines.first : '';
        releaseWebDiagnosticPrint('[zk-login-diag] top_frame=$topFrame');

        vlog('login.zk.failed', {
          'error_type': typeName,
          'last_step': loginLastStep,
          'error_head': head,
        });
        // Two ZK failure modes:
        //   * 401 "vault_handle or PIN is incorrect" — either the
        //     account is pre-ZK (no vault_handle row) OR the PIN is
        //     wrong. Only in the first case is the legacy fallback
        //     safe. We can't tell the difference from the error
        //     alone, so we let the fallback run; it will 401 again
        //     with the correct "Wrong username or PIN" copy for the
        //     pre-ZK-but-wrong-PIN case.
        //   * anything else — hard error. Surface a controlled copy
        //     that ALSO carries the diagnostic step + exception
        //     class so an operator or user reading production logs
        //     can identify the failing step. Truncated to remain
        //     free of PIN/ciphertext/handle bytes.
        final looksLikeAuth401 = msg.contains('HTTP 401') ||
            msg.contains('failed 401') ||
            msg.contains('vault_handle or PIN is incorrect');
        if (looksLikeAuth401) {
          zkLoginNotFound = true;
        } else {
          if (!mounted) return;
          debugAuthFailureTrace('zk-login-diag', e, stack, step: loginLastStep);
          setState(() {
            err = kAuthDeviceSafeError;
            loading = false;
          });
          return;
        }
      }
    }

    // A typed VLT- handle never falls back to legacy — a wrong PIN
    // must fail closed on the ZK side.
    if (entryIsHandle && zkLoginNotFound) {
      if (!mounted) return;
      setState(() {
        err = 'Wrong username or PIN.';
        loading = false;
      });
      return;
    }

    // Legacy path — vault_name + PIN. Reserved for un-adopted vaults
    // that predate the ZK rollout.
    vlog('login.legacy.attempt', {
      'reason': entryIsHandle ? 'handle_not_zk' : 'username_not_zk',
    });
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.authLogin(vaultName: vaultName, pin: pin);
      final token = result['session_token']?.toString() ?? '';
      final vaultId = result['vault_id']?.toString() ?? '';
      final outName = result['vault_name']?.toString() ?? vaultName;
      final display = result['display_username']?.toString();
      final vaultHandle = result['vault_handle']?.toString();
      final newDeviceTrusted = result['new_device_trusted'] == true;
      if (token.isEmpty || vaultId.isEmpty) {
        throw Exception('Login response missing session_token / vault_id');
      }
      await app.setSession(
        token: token,
        vaultIdValue: vaultId,
        vaultNameValue: outName,
        displayNameValue: display,
        vaultHandleValue: vaultHandle,
      );
      pageTiming('secure_store_complete');
      inheritanceRevealDiag('normal_login_legacy_success', {
        'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
        'has_vault_handle':
            vaultHandle != null && vaultHandle.trim().isNotEmpty,
        'active_sk_present': zk_sk_store.ZkActiveSkVault.current() != null,
        'active_sk_vault_match':
            zk_sk_store.ZkActiveSkVault.currentVaultId() == vaultId,
      });
      await _registerDeviceBestEffort(token);
      await _autoConsumeInheritanceTokenIfPresent(token, app);
      await _deriveKeyAndUnlock(app: app, pin: pin);
      pageTiming('key_unwrap_complete');
      if (!mounted) return;
      _notifyNewDeviceTrustedIfNeeded(newDeviceTrusted);
      final adoptedNav = await _tryLegacyAdoptionBestEffort(
        context: context,
        app: app,
        pin: pin,
      );
      if (!mounted) return;
      if (!adoptedNav) {
        pageTiming('authenticated_route_visible');
        Navigator.pushReplacementNamed(context, '/chat');
      }
    } on InvalidCredentialsException catch (e) {
      if (!mounted) return;
      setState(() {
        err = e.message;
        loading = false;
      });
    } on RateLimitedException catch (e) {
      if (!mounted) return;
      setState(() {
        err = e.message;
        loading = false;
      });
    } on VaultFrozenException {
      if (!mounted) return;
      Navigator.pushReplacementNamed(context, '/vault-frozen');
    } on VaultLockedException catch (e) {
      if (!mounted) return;
      setState(() {
        err = e.message;
        loading = false;
      });
    } catch (e, stack) {
      if (app.handleApiException(e)) return;
      if (!mounted) return;
      final typeName = e.runtimeType.toString();
      final msg = e.toString();
      final head = msg.length > 120 ? msg.substring(0, 120) : msg;
      releaseWebDiagnosticPrint('[zk-login-diag] '
          'last_step=legacy_fallback type=$typeName head=$head');
      debugAuthFailureTrace('zk-login-diag', e, stack, step: 'legacy_fallback');
      vlog('login.legacy.failed', {'error_type': typeName});
      setState(() {
        // Controlled copy — never the raw Dart exception. The old
        // "Null check operator used on a null value" from the pre-
        // 2026-07-20 build reached this branch when a bang deeper
        // in the login pipeline blew up.
        err = kAuthDeviceSafeError;
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_showForm) return const Scaffold();
    final w = MediaQuery.of(context).size.width;
    final isMobile = w < 760;
    return Scaffold(
      appBar: TopNavBar(isMobile: isMobile),
      body: Center(
        child: SizedBox(
          width: w < 420 ? w - 24 : 390,
          child: Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: const Color(0xFF2F2F2F),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Sign in to your vault',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 22),
                ),
                const SizedBox(height: 10),
                const Text(
                  'Enter your vault name and PIN. Vault names are unique across SVaultAI.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Color(0xFFB4B4B4)),
                ),
                const SizedBox(height: 14),
                Semantics(
                  container: true,
                  identifier: 'auth_vault_name_field',
                  textField: true,
                  child: TextField(
                    key: const Key('auth_vault_name_field'),
                    controller: vaultNameCtrl,
                    autocorrect: false,
                    enabled: !loading,
                    decoration: const InputDecoration(labelText: 'Vault name'),
                  ),
                ),
                const SizedBox(height: 10),
                Semantics(
                  container: true,
                  identifier: 'auth_pin_field',
                  textField: true,
                  child: TextField(
                    key: const Key('auth_pin_field'),
                    controller: pinCtrl,
                    keyboardType: TextInputType.number,
                    obscureText: true,
                    maxLength: 64,
                    enabled: !loading,
                    decoration: const InputDecoration(
                      counterText: '',
                      labelText: 'PIN',
                      helperText: 'Enter your 6–64 digit PIN.',
                    ),
                    onSubmitted: loading ? null : (_) => _submit(),
                  ),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: Semantics(
                    container: true,
                    identifier: 'auth_sign_in_button',
                    button: true,
                    child: FilledButton(
                      key: const Key('auth_sign_in_button'),
                      onPressed: loading ? null : _submit,
                      child: Text(loading ? 'Signing in…' : 'Sign in'),
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                TextButton(
                  onPressed: loading
                      ? null
                      : () =>
                          Navigator.pushReplacementNamed(context, '/signup'),
                  child: Text(
                    AppLocalizations.of(context).authDontHaveVault,
                  ),
                ),
                TextButton.icon(
                  key: const Key('login_form_help_and_faq'),
                  onPressed: loading
                      ? null
                      : () => openHelpCenter(
                            context,
                            mode: hc.HelpCenterMode.public,
                          ),
                  icon: const Icon(Icons.help_outline, size: 16),
                  label: const Text('Help & FAQ'),
                ),
                if (err != null) _authErrorBox(err!),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class SignupPage extends StatefulWidget {
  const SignupPage({super.key});

  @override
  State<SignupPage> createState() => _SignupPageState();
}

class _SignupPageState extends State<SignupPage> {
  final vaultNameCtrl = TextEditingController();
  final displayNameCtrl = TextEditingController();
  final pinCtrl = TextEditingController();
  final confirmPinCtrl = TextEditingController();
  bool acknowledged = false;
  bool loading = false;
  String? err;
  String? vaultNameErr;

  static const int _minPinLength = 6;
  static const int _maxPinLength = 64;

  Future<void> _submit() async {
    final vaultName = vaultNameCtrl.text.trim();
    final displayName = displayNameCtrl.text.trim();
    final pin = pinCtrl.text.trim();
    final confirm = confirmPinCtrl.text.trim();

    setState(() {
      err = null;
      vaultNameErr = null;
    });

    if (vaultName.isEmpty) {
      setState(() => vaultNameErr = 'Pick a vault name.');
      return;
    }
    final digitsOnly = RegExp(r'^\d+$');
    if (!digitsOnly.hasMatch(pin)) {
      setState(() => err = 'PIN can only contain digits.');
      return;
    }
    if (pin.length < _minPinLength) {
      setState(() => err = 'PIN must be at least 6 digits.');
      return;
    }
    if (pin.length > _maxPinLength) {
      setState(() => err = 'PIN must be 64 digits or fewer.');
      return;
    }
    if (pin != confirm) {
      setState(() => err = 'PINs do not match.');
      return;
    }
    if (!acknowledged) {
      setState(() => err =
          'Please confirm you understand SVaultAI cannot recover your vault.');
      return;
    }

    setState(() => loading = true);
    final app = context.read<AppState>();

    // ZK signup path: mints a fresh Vault Handle, runs OPAQUE
    // registration, wraps a random MVK. The user's chosen
    // display_username (or vault_name) is encrypted client-side and
    // never sent to the server as plaintext.
    try {
      await OpaqueClient.ready();

      // Identity contract (2026-07-20 corrected):
      //   vaultName    = user-chosen identity used both for signing
      //                  into the vault AND as the vault AI's name.
      //                  ONE string with ONE meaning. Preserved
      //                  as-typed for UI + prompt injection; used
      //                  as the sole authentication input.
      //   displayName  = optional human owner's visible name.
      //                  Rendered in the profile menu only. Never
      //                  substituted for vaultName anywhere.
      final displayNameForEncrypt =
          displayName.isEmpty ? vaultName : displayName;

      final zk = ZkAuthService(_zkHttpPost);
      final result = await zk.registerVault(
        // The vaultName the user typed drives BOTH the deterministic
        // lookup derivation (SHA-256 for username_lookup_v1 sent to
        // server) AND the server-side plaintext vault_name column
        // (needed authoritatively for LLM prompt injection). See the
        // 2026-07-20 privacy clarification: vault_name is
        // product-facing server-visible metadata, not a private
        // credential.
        vaultName: vaultName,
        displayName: displayNameForEncrypt,
        pin: pin,
      );

      await app.setSession(
        token: result.sessionToken,
        vaultIdValue: result.vaultId,
        // vaultNameValue is the USER-CHOSEN name — the same string
        // the user typed. Never the VLT handle, never a random hex.
        vaultNameValue: vaultName,
        vaultHandleValue: result.vaultHandle,
        // Optional display name — only when the user set it
        // explicitly.
        displayNameValue: displayName.isEmpty ? null : displayName,
      );
      await _registerDeviceBestEffort(result.sessionToken);
      await _autoConsumeInheritanceTokenIfPresent(
        result.sessionToken,
        app,
      );
      // Crypto cache key MUST match what the ``unlocked`` invariant
      // getter reads at [main.dart:908]:
      //     _VaultCrypto.hasKeyFor(vaultId: vId, vaultName: vName)
      // where ``vName`` is ``AppState._vaultName`` (populated with
      // the user-typed vault name via setSession above). Before the
      // ed825aa unification, this line stored the entry under
      // ``result.vaultHandle`` (the VLT-... identifier) which no
      // longer matches — that mismatch produced the "signup
      // succeeds → redirect back to PIN" symptom because
      // ``unlocked`` returned false immediately.
      _VaultCrypto._keyCache[_VaultCrypto._ck(result.vaultId, vaultName)] =
          result.mvk;
      _VaultCrypto._pinCache[_VaultCrypto._ck(result.vaultId, vaultName)] = pin;
      _VaultCrypto.setActiveVault(
        vaultId: result.vaultId,
        vaultName: vaultName,
      );
      // Publish MVK explicitly before the PBKDF2 mirror overwrites
      // _keyCache — see the LoginPage ZK path.
      zk_mvk_store.ZkActiveMvk.set(
        mvk: result.mvk,
        vaultId: result.vaultId,
        vaultHandle: result.vaultHandle,
      );
      // 2026-07-22 crypto-context refactor. Fresh ZK signup writes
      // a random MVK; the server's /chat handler derives PBKDF2 from
      // the vault's pin_salt/kdf_iterations (set at signup). We
      // install the atomic VaultCryptoContext from that DB state so
      // /chat encrypt uses the same key the server will derive.
      // See LoginPage ZK path for the full incident context.
      try {
        final _zkSignupMeta = await _API.getVaultMeta(
          vaultName: vaultName,
          authToken: result.sessionToken,
        );
        final _zkSignupSalt = _zkSignupMeta['pin_salt']?.toString();
        final _zkSignupIter =
            (_zkSignupMeta['kdf_iterations'] as num?)?.toInt();
        if (_zkSignupSalt != null &&
            _zkSignupSalt.isNotEmpty &&
            _zkSignupIter != null) {
          final _zkSignupCtx = await deriveAndInstallCryptoContext(
            vaultId: result.vaultId,
            vaultName: vaultName,
            pin: pin,
            pinSaltBase64: _zkSignupSalt,
            iterations: _zkSignupIter,
            source: 'zk_signup',
          );
          if (_zkSignupCtx == null) {
            vlog('signup.zk.derive.superseded', {'vaultName': vaultName});
          }
        } else {
          vlog('signup.zk.meta_missing_fields', {
            'has_salt': _zkSignupSalt != null,
            'has_iter': _zkSignupIter != null,
          });
        }
      } catch (e) {
        vlog('signup.zk.pbkdf2_derive_failed', {
          'error': e.toString(),
          'vaultName': vaultName,
        });
      }
      app.markUnlocked();
      _refreshSessionListsBestEffort(app);

      if (!mounted) return;
      // Successful ZK registration enters the app directly. The
      // internal vault handle is persisted client-side by
      // ``ZkAuthService`` for the next ZK login, but never shown to
      // the user — the only user-visible credentials are the
      // username and PIN they just chose.
      Navigator.of(context).pushReplacementNamed('/chat');
      return;
    } on OpaqueUnavailable catch (e) {
      // If WASM did not load (rare), inform the user and stop —
      // silently falling back to legacy signup would produce a
      // plaintext-vault-name row that the user cannot log into via
      // their new bundle later. Better to fail loudly.
      if (!mounted) return;
      setState(() {
        err = 'Secure signup module failed to load: ${e.reason}';
        loading = false;
      });
      return;
    } on RateLimitedException catch (e) {
      if (!mounted) return;
      setState(() {
        err = e.message;
        loading = false;
      });
      return;
    } catch (e) {
      // Classify the failure so the user never sees a raw
      // "ZK POST /auth/zk-register-finalize failed 409: {...}"
      // string. The _zkHttpPost helper throws:
      //   Exception('ZK POST <path> failed <status>: <body>')
      // Match the two operationally meaningful cases and map them
      // to friendly copy; anything else stays generic.
      if (app.handleApiException(e)) return;
      final msg = e.toString();
      releaseWebDiagnosticPrint('[zk-signup-diag] error_type=${e.runtimeType} '
          'head=${msg.length > 120 ? msg.substring(0, 120) : msg}');
      String friendly;
      if (msg.contains('failed 409') || msg.contains('HTTP 409')) {
        // Duplicate username — the backend's canonical copy is
        // "Username already taken. Please choose another." but the
        // raw exception also carries the URL and status. Show only
        // the friendly form.
        friendly = 'That username is already taken. Please choose another.';
      } else if (msg.contains('failed 429') || msg.contains('HTTP 429')) {
        friendly = 'Too many attempts. Please wait and try again.';
      } else {
        friendly = 'Signup failed. Please try again.';
      }
      if (!mounted) return;
      setState(() {
        err = friendly;
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.of(context).size.width;
    final isMobile = w < 760;
    return Scaffold(
      appBar: TopNavBar(isMobile: isMobile),
      body: Center(
        child: SizedBox(
          width: w < 480 ? w - 24 : 440,
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(vertical: 18),
            child: Container(
              padding: const EdgeInsets.all(22),
              decoration: BoxDecoration(
                color: const Color(0xFF2F2F2F),
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: Colors.white10),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'Create your vault',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontWeight: FontWeight.w800, fontSize: 22),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Pick a unique vault name and a PIN. Together they are your account.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Color(0xFFB4B4B4)),
                  ),
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFA726).withValues(alpha: 0.10),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: const Color(0xFFFFA726).withValues(alpha: 0.45),
                      ),
                    ),
                    child: const Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(Icons.warning_amber_rounded,
                            color: Color(0xFFFFA726), size: 22),
                        SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            'If you forget your vault name or PIN, SVaultAI '
                            'cannot recover your vault.',
                            style: TextStyle(
                              color: Color(0xFFFFE0B2),
                              fontSize: 13,
                              height: 1.4,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: vaultNameCtrl,
                    autocorrect: false,
                    enabled: !loading,
                    decoration: InputDecoration(
                      labelText: 'Vault name',
                      hintText: 'e.g. Alexa, Atlas, Mira',
                      errorText: vaultNameErr,
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: displayNameCtrl,
                    enabled: !loading,
                    decoration: const InputDecoration(
                      labelText: 'Display name (optional)',
                      hintText: 'Shown in your welcome header',
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: pinCtrl,
                    keyboardType: TextInputType.number,
                    obscureText: true,
                    maxLength: _maxPinLength,
                    enabled: !loading,
                    decoration: const InputDecoration(
                      counterText: '',
                      labelText: 'PIN (6–64 digits)',
                      helperText: 'Create a 6–64 digit PIN.',
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: confirmPinCtrl,
                    keyboardType: TextInputType.number,
                    obscureText: true,
                    maxLength: _maxPinLength,
                    enabled: !loading,
                    decoration: const InputDecoration(
                      counterText: '',
                      labelText: 'Confirm PIN',
                    ),
                    onSubmitted: loading ? null : (_) => _submit(),
                  ),
                  const SizedBox(height: 10),
                  InkWell(
                    onTap: loading
                        ? null
                        : () => setState(() => acknowledged = !acknowledged),
                    borderRadius: BorderRadius.circular(8),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Checkbox(
                            value: acknowledged,
                            onChanged: loading
                                ? null
                                : (v) =>
                                    setState(() => acknowledged = v ?? false),
                          ),
                          const Expanded(
                            child: Padding(
                              padding: EdgeInsets.only(top: 12),
                              child: Text(
                                'I understand and accept this risk.',
                                style: TextStyle(
                                  color: Color(0xFFE0E0E0),
                                  fontSize: 13,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: loading ? null : _submit,
                      child: Text(loading ? 'Creating…' : 'Create vault'),
                    ),
                  ),
                  TextButton(
                    onPressed: loading
                        ? null
                        : () =>
                            Navigator.pushReplacementNamed(context, '/login'),
                    child: Text(
                      AppLocalizations.of(context).authAlreadyHaveVault,
                    ),
                  ),
                  if (err != null) _authErrorBox(err!),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class UnlockPage extends StatefulWidget {
  const UnlockPage({super.key});

  @override
  State<UnlockPage> createState() => _UnlockPageState();
}

class _UnlockPageState extends State<UnlockPage> {
  final pinCtrl = TextEditingController();
  bool loading = false;
  String? err;

  Future<void> _submit() async {
    final app = context.read<AppState>();
    final name = app.lastVaultName;
    // Cache invariants: to run the ZK unlock path we need either the
    // last used vault_handle (VLT-... display) OR the last used
    // vault_name (legacy). A stale / partially-cleared cache — for
    // example `lastVaultName` present but `last_display_username`
    // wiped — would send us to /unlock with no way to look up the
    // account. Route the user through full /login instead of
    // attempting an unlock that would 100% miss.
    if (name == null || name.isEmpty) {
      releaseWebDiagnosticPrint(
        '[zk-unlock-diag] cache_incomplete=lastVaultName_missing',
      );
      Navigator.pushReplacementNamed(context, '/login');
      return;
    }
    final pin = pinCtrl.text.trim();
    final digitsOnly = RegExp(r'^\d+$');
    if (!digitsOnly.hasMatch(pin)) {
      setState(() => err = 'PIN can only contain digits.');
      return;
    }
    if (pin.length < 6) {
      setState(() => err = 'PIN must be at least 6 digits.');
      return;
    }
    if (pin.length > 64) {
      setState(() => err = 'PIN must be 64 digits or fewer.');
      return;
    }
    setState(() {
      loading = true;
      err = null;
    });

    final authTiming = Stopwatch()..start();
    void pageTiming(
      String stage, {
      bool success = true,
      int? httpStatus,
    }) {
      authTimingDiagnosticPrint(
        stage,
        authTiming.elapsed,
        success: success,
        httpStatus: httpStatus,
      );
    }

    pageTiming('submit_entry');
    // Under the corrected identity model (ed825aa), lastVaultName
    // holds the USER-TYPED vault name — the same string used for
    // both signing in and as the vault AI's name. Only sessions
    // predating that migration might carry a VLT-... handle in
    // this slot (via the SharedPreferences fallback chain in
    // hydrate). Route accordingly: user-typed name → ZK vault-
    // name path; literal VLT handle → ZK handle path. Legacy
    // /auth/login is a last-resort fallback for unadopted pre-ZK
    // accounts (the ZK path 401's on those because no vault_handle
    // row exists for the derived bytes).
    final entryIsVltHandle = vh.isValidVaultHandleDisplay(name);
    String unlockLastStep = 'submit_entry';
    bool zkLoginNotFound = false;
    {
      try {
        releaseWebDiagnosticPrint('[zk-unlock-step] page/submit_entry '
            'entry_type=${entryIsVltHandle ? "handle" : "name"}');
        await OpaqueClient.ready();
        unlockLastStep = 'page_opaque_ready';
        final zk = ZkAuthService(_zkHttpPost);
        final loginResult = await zk.loginVault(
          vaultName: entryIsVltHandle ? null : name,
          vaultHandle: entryIsVltHandle ? name : null,
          pin: pin,
          onStep: (s) => unlockLastStep = s,
        );
        unlockLastStep = 'page_zk_login_returned';
        // Preferred: server-authoritative vault_name from the
        // finalize response. If null (e.g. an existing account
        // whose column hasn't been backfilled yet), use the
        // typed name when the entry was a vault name, or the
        // client-side app.vaultName / decrypted displayName when
        // the entry was a VLT handle. Never the VLT handle
        // itself.
        final resolvedVaultName = loginResult.vaultName ??
            (entryIsVltHandle
                ? (app.vaultName ?? loginResult.displayName)
                : name);
        await app.setSession(
          token: loginResult.sessionToken,
          vaultIdValue: loginResult.vaultId,
          vaultNameValue: resolvedVaultName,
          vaultHandleValue: loginResult.vaultHandle,
          displayNameValue: loginResult.displayName,
        );
        pageTiming('secure_store_complete');
        await _registerDeviceBestEffort(loginResult.sessionToken);
        await _autoConsumeInheritanceTokenIfPresent(
          loginResult.sessionToken,
          app,
        );
        // 2026-07-22 crypto-context refactor. Preserve MVK in
        // _keyCache for the ZK metadata surface, but install the
        // freshly-derived PBKDF2 VaultCryptoContext for /chat. See
        // the LoginPage ZK path above for the full incident context.
        _VaultCrypto._keyCache[
                _VaultCrypto._ck(loginResult.vaultId, resolvedVaultName)] =
            loginResult.mvk;
        _VaultCrypto._pinCache[
            _VaultCrypto._ck(loginResult.vaultId, resolvedVaultName)] = pin;
        _VaultCrypto.setActiveVault(
          vaultId: loginResult.vaultId,
          vaultName: resolvedVaultName,
        );
        // Publish MVK explicitly before the PBKDF2 mirror overwrites
        // _keyCache — see the LoginPage ZK path above.
        zk_mvk_store.ZkActiveMvk.set(
          mvk: loginResult.mvk,
          vaultId: loginResult.vaultId,
          vaultHandle: loginResult.vaultHandle,
        );
        try {
          final _zkUnlockMeta = await _API.getVaultMeta(
            vaultName: resolvedVaultName,
            authToken: loginResult.sessionToken,
          );
          final _zkUnlockSalt = _zkUnlockMeta['pin_salt']?.toString();
          final _zkUnlockIter =
              (_zkUnlockMeta['kdf_iterations'] as num?)?.toInt();
          if (_zkUnlockSalt != null &&
              _zkUnlockSalt.isNotEmpty &&
              _zkUnlockIter != null) {
            final _zkUnlockCtx = await deriveAndInstallCryptoContext(
              vaultId: loginResult.vaultId,
              vaultName: resolvedVaultName,
              pin: pin,
              pinSaltBase64: _zkUnlockSalt,
              iterations: _zkUnlockIter,
              source: 'zk_unlock',
            );
            if (_zkUnlockCtx == null) {
              vlog('unlock.zk.derive.superseded', {
                'vaultName': resolvedVaultName,
              });
            }
            pageTiming('vault_pbkdf2_complete');
          } else {
            vlog('unlock.zk.meta_missing_fields', {
              'has_salt': _zkUnlockSalt != null,
              'has_iter': _zkUnlockIter != null,
            });
          }
        } catch (e) {
          vlog('unlock.zk.pbkdf2_derive_failed', {
            'error': e.toString(),
            'vaultName': resolvedVaultName,
          });
        }
        // Cache the X25519 private key so the inheritance credential
        // reveal path can decrypt without another OPAQUE round-trip.
        // Cleared on logout / vault switch.
        zk_sk_store.ZkActiveSkVault.set(
          skVault: loginResult.skVaultPrivate,
          vaultId: loginResult.vaultId,
        );
        inheritanceRevealDiag('normal_unlock_zk_success', {
          'vault_fpr': inheritanceRevealIdFingerprint(loginResult.vaultId),
          'has_vault_handle': loginResult.vaultHandle.isNotEmpty,
          'active_sk_present': zk_sk_store.ZkActiveSkVault.current() != null,
          'active_sk_vault_match':
              zk_sk_store.ZkActiveSkVault.currentVaultId() ==
                  loginResult.vaultId,
        });
        app.markUnlocked();
        _refreshSessionListsBestEffort(app);
        pageTiming('session_hydrated');
        // Post-login side-effects are best-effort; a failure here
        // must not surface as a raw Dart exception (the old
        // "Null check operator used on a null value" symptom).
        try {
          _scheduleMetadataMigration(app: app);
        } catch (e) {
          vlog('unlock.post_login_side_effect_failed',
              {'step': 'schedule_metadata_migration', 'error': e.toString()});
        }
        if (!mounted) return;
        pageTiming('authenticated_route_visible');
        Navigator.pushReplacementNamed(context, '/chat');
        return;
      } on OpaqueUnavailable catch (e, stack) {
        releaseWebDiagnosticPrint('[zk-unlock-diag] '
            'last_step=$unlockLastStep type=OpaqueUnavailable reason=${e.reason}');
        debugAuthFailureTrace('zk-unlock-diag', e, stack, step: unlockLastStep);
        if (!mounted) return;
        setState(() {
          err = kUnlockDeviceSafeError;
          loading = false;
        });
        return;
      } on OpaqueAuthenticationFailed catch (e) {
        // Same wrong-PIN classification as LoginPage — see the
        // matching catch there for the rationale.
        releaseWebDiagnosticPrint('[zk-unlock-diag] '
            'last_step=$unlockLastStep type=OpaqueAuthenticationFailed stage=${e.stage}');
        vlog('unlock.zk.opaque_auth_failed', {'stage': e.stage});
        if (!mounted) return;
        setState(() {
          err = 'Wrong username or PIN.';
          loading = false;
        });
        return;
      } catch (e, stack) {
        if (app.handleApiException(e)) return;
        final typeName = e.runtimeType.toString();
        final msg = e.toString();
        final head = msg.length > 120 ? msg.substring(0, 120) : msg;
        releaseWebDiagnosticPrint('[zk-unlock-diag] '
            'last_step=$unlockLastStep type=$typeName head=$head');
        debugAuthFailureTrace('zk-unlock-diag', e, stack, step: unlockLastStep);
        vlog('unlock.zk.failed', {
          'error_type': typeName,
          'last_step': unlockLastStep,
        });
        // 2026-07-20: mirror the LoginPage classifier so unadopted
        // legacy accounts can still unlock. A 401 at zk-login-init
        // means either "account not in ZK" (legacy) or "wrong PIN"
        // (ZK). We can't tell from the error alone; let the legacy
        // fallback run when the entry is NOT a VLT handle. A wrong
        // PIN on a real ZK account raises OpaqueAuthenticationFailed
        // (caught above) so we never falsely fall through for that
        // case.
        final looksLikeAuth401 = msg.contains('HTTP 401') ||
            msg.contains('failed 401') ||
            msg.contains('Wrong username or PIN');
        if (looksLikeAuth401 && !entryIsVltHandle) {
          zkLoginNotFound = true;
        } else {
          if (!mounted) return;
          setState(() {
            err = kUnlockDeviceSafeError;
            loading = false;
          });
          return;
        }
      }
    }

    // A typed VLT handle never falls back to legacy — a wrong PIN
    // there must fail closed on the ZK side.
    if (entryIsVltHandle && zkLoginNotFound) {
      if (!mounted) return;
      setState(() {
        err = 'Wrong username or PIN.';
        loading = false;
      });
      return;
    }

    // Legacy /auth/login fallback — reserved for un-adopted vaults
    // that predate the ZK rollout (no vault_handle row exists for
    // their derived bytes, so the ZK path 401's; the plaintext
    // pin_verifier still works).
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.authLogin(vaultName: name, pin: pin);
      final token = result['session_token']?.toString() ?? '';
      final vaultId = result['vault_id']?.toString() ?? '';
      final outName = result['vault_name']?.toString() ?? name;
      final display = result['display_username']?.toString();
      final vaultHandle = result['vault_handle']?.toString();
      final newDeviceTrusted = result['new_device_trusted'] == true;
      if (token.isEmpty || vaultId.isEmpty) {
        throw Exception('Login response missing session_token / vault_id');
      }
      await app.setSession(
        token: token,
        vaultIdValue: vaultId,
        vaultNameValue: outName,
        displayNameValue: display,
        vaultHandleValue: vaultHandle,
      );
      pageTiming('secure_store_complete');
      inheritanceRevealDiag('normal_unlock_legacy_success', {
        'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
        'has_vault_handle':
            vaultHandle != null && vaultHandle.trim().isNotEmpty,
        'active_sk_present': zk_sk_store.ZkActiveSkVault.current() != null,
        'active_sk_vault_match':
            zk_sk_store.ZkActiveSkVault.currentVaultId() == vaultId,
      });
      await _registerDeviceBestEffort(token);
      await _autoConsumeInheritanceTokenIfPresent(token, app);
      await _deriveKeyAndUnlock(app: app, pin: pin);
      pageTiming('key_unwrap_complete');
      if (!mounted) return;
      _notifyNewDeviceTrustedIfNeeded(newDeviceTrusted);
      final adoptedNav = await _tryLegacyAdoptionBestEffort(
        context: context,
        app: app,
        pin: pin,
      );
      if (!mounted) return;
      if (!adoptedNav) {
        pageTiming('authenticated_route_visible');
        Navigator.pushReplacementNamed(context, '/chat');
      }
    } on InvalidCredentialsException catch (e) {
      if (!mounted) return;
      setState(() {
        err = e.message;
        loading = false;
      });
    } on RateLimitedException catch (e) {
      if (!mounted) return;
      setState(() {
        err = e.message;
        loading = false;
      });
    } on VaultFrozenException {
      if (!mounted) return;
      Navigator.pushReplacementNamed(context, '/vault-frozen');
    } on VaultLockedException catch (e) {
      if (!mounted) return;
      setState(() {
        err = e.message;
        loading = false;
      });
    } catch (e, stack) {
      if (app.handleApiException(e)) return;
      final typeName = e.runtimeType.toString();
      final msg = e.toString();
      final head = msg.length > 120 ? msg.substring(0, 120) : msg;
      releaseWebDiagnosticPrint('[zk-unlock-diag] '
          'last_step=legacy_fallback type=$typeName head=$head');
      debugAuthFailureTrace('zk-unlock-diag', e, stack,
          step: 'legacy_fallback');
      vlog('unlock.legacy.failed', {'error_type': typeName});
      if (!mounted) return;
      setState(() {
        err = kUnlockDeviceSafeError;
        loading = false;
      });
    }
  }

  Future<void> _useAnotherVault() async {
    final app = context.read<AppState>();
    await app.clearSession(keepLastVaultName: false);
    if (!mounted) return;
    Navigator.pushReplacementNamed(context, '/login');
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();

    if (app.lastVaultName == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) Navigator.pushReplacementNamed(context, '/login');
      });
      return const Scaffold();
    }
    final w = MediaQuery.of(context).size.width;
    final isMobile = w < 760;
    return Scaffold(
      appBar: TopNavBar(isMobile: isMobile),
      body: Center(
        child: SizedBox(
          width: w < 420 ? w - 24 : 390,
          child: Container(
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
              color: const Color(0xFF2F2F2F),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Welcome back',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 22,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Enter your 6–64 digit PIN.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Color(0xFFB4B4B4)),
                ),
                const SizedBox(height: 14),
                Semantics(
                  container: true,
                  identifier: 'auth_unlock_pin_field',
                  textField: true,
                  child: TextField(
                    key: const Key('auth_unlock_pin_field'),
                    controller: pinCtrl,
                    keyboardType: TextInputType.number,
                    obscureText: true,
                    autofocus: true,
                    maxLength: 64,
                    enabled: !loading,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 22, letterSpacing: 10),
                    decoration: const InputDecoration(
                      counterText: '',
                      hintText: '••••••',
                    ),
                    onSubmitted: loading ? null : (_) => _submit(),
                  ),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: Semantics(
                    container: true,
                    identifier: 'auth_unlock_button',
                    button: true,
                    child: FilledButton(
                      key: const Key('auth_unlock_button'),
                      onPressed: loading ? null : _submit,
                      child: Text(loading ? 'Unlocking…' : 'Unlock'),
                    ),
                  ),
                ),
                TextButton(
                  onPressed: loading ? null : _useAnotherVault,
                  child: Text(
                    AppLocalizations.of(context).authUseAnotherVault,
                  ),
                ),
                if (err != null) _authErrorBox(err!),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class PinGatePage extends StatefulWidget {
  const PinGatePage({super.key});

  @override
  State<PinGatePage> createState() => _PinGatePageState();
}

class _PinGatePageState extends State<PinGatePage> {
  final pinController = TextEditingController();
  String? err;

  bool? creating;

  bool _submitting = false;

  bool _acknowledgedNoRecovery = false;

  static const int _minPinLengthCreate = 6;
  static const int _minPinLengthUnlock = 6;
  static const int _maxPinLength = 64;

  @override
  void initState() {
    super.initState();
    _decide();
  }

  Future<void> _decide() async {
    vlog('pin.mode.loading');
    final app = context.read<AppState>();
    final token = app.sessionToken;

    if (token == null) {
      if (mounted) {
        Navigator.pushReplacementNamed(
          context,
          app.lastVaultName != null ? '/unlock' : '/login',
        );
      }
      return;
    }

    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.getMyVault(authToken: token);

      final hasVault = result['has_vault'] == true;
      final isOrphaned = result['is_orphaned'] == true;
      final mustReset = result['must_reset'] == true;
      final backendVaultName = result['vault_name']?.toString();

      vlog('pin.mode.backend', {
        'has_vault': hasVault,
        'vault_name': backendVaultName,
        'is_orphaned': isOrphaned,
        'must_reset': mustReset,
      });

      if (isOrphaned) {
        app.recoveryInfo = VaultRecoveryInfo.fromMap(
          result['orphan_data'] is Map<String, dynamic>
              ? result['orphan_data'] as Map<String, dynamic>
              : null,
        );
        if (!mounted) return;
        Navigator.pushReplacementNamed(context, '/recover');
        return;
      }

      if (mustReset) {
        if (!mounted) return;
        Navigator.pushReplacementNamed(context, '/vault-frozen');
        return;
      }

      app.recoveryInfo = null;

      if (hasVault &&
          backendVaultName != null &&
          backendVaultName.trim().isNotEmpty) {
        app.vaultName = backendVaultName.trim();
        app.lastVaultName = backendVaultName.trim();
        await NativeSecureStore.writeString(
          'last_vault_name',
          backendVaultName.trim(),
        );
      }

      if (mounted) {
        setState(() {
          creating = false;
        });
      }
    } catch (e) {
      if (app.handleApiException(e)) return;
      vlog('pin.mode.final', {
        'mode': 'enter',
        'reason': 'getMyVault_error',
        'error': e.toString(),
      });
      if (mounted) {
        setState(() => creating = false);
      }
    }
  }

  String get _pin => pinController.text.trim();

  Future<void> _useAnotherVault() async {
    if (_submitting) return;
    final app = context.read<AppState>();
    await app.clearSession(keepLastVaultName: false);
    if (!mounted) return;
    Navigator.pushReplacementNamed(context, '/login');
  }

  Future<void> _submit() async {
    if (_submitting) return;

    final mode = creating;
    if (mode == null) return;
    final pin = _pin;
    final minLen = _minPinLengthUnlock;
    final digitsOnly = RegExp(r'^\d+$');
    if (!digitsOnly.hasMatch(pin)) {
      setState(() {
        err = 'PIN can only contain digits.';
      });
      return;
    }
    if (pin.length < minLen) {
      setState(() {
        err = 'PIN must be at least 6 digits.';
      });
      return;
    }
    if (pin.length > _maxPinLength) {
      setState(() {
        err = 'PIN must be 64 digits or fewer.';
      });
      return;
    }

    setState(() {
      _submitting = true;
      err = null;
    });

    final submitStartedAt = DateTime.now();
    final app = context.read<AppState>();
    try {
      final ok = await app.verifyPin(_pin);
      if (!ok) {
        setState(() {
          err = app.lockMessage ?? 'Incorrect PIN. Try again.';
        });
        return;
      }

      if (!mounted) return;
      vlog('pin.timing.post_pin_navigate', {
        'mode': 'unlock',
        'elapsed_ms': DateTime.now().difference(submitStartedAt).inMilliseconds,
        'route': '/chat',
      });
      Navigator.pushReplacementNamed(context, '/chat');
    } catch (e) {
      if (app.handleApiException(e)) return;
      setState(() => err = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.of(context).size.width;
    final isMobile = w < 760;

    final mode = creating;
    if (mode == null) {
      return Scaffold(
        appBar: TopNavBar(showActions: false, isMobile: isMobile),
        body: Center(
          child: SizedBox(
            width: w < 420 ? w - 24 : 390,
            child: Container(
              padding: const EdgeInsets.all(22),
              decoration: BoxDecoration(
                color: const Color(0xFF2F2F2F),
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: Colors.white10),
              ),
              child: const Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    height: 28,
                    width: 28,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  SizedBox(height: 14),
                  Text(
                    'Checking your vault...',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }
    final title = mode ? 'Create your PIN' : 'Enter your PIN';

    return Scaffold(
      appBar: TopNavBar(showActions: false, isMobile: isMobile),
      body: Center(
        child: SizedBox(
          width: w < 420 ? w - 24 : 390,
          child: Container(
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
              color: const Color(0xFF2F2F2F),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(title,
                    style: const TextStyle(
                        fontSize: 24, fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                Text(
                  mode
                      ? 'Create a 6–64 digit PIN.'
                      : 'Enter your 6–64 digit PIN.',
                  style:
                      const TextStyle(color: Color(0xFFB4B4B4), fontSize: 12),
                ),
                const SizedBox(height: 16),
                if (mode) ...[
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFA726).withValues(alpha: 0.10),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: const Color(0xFFFFA726).withValues(alpha: 0.45),
                      ),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(
                          Icons.warning_amber_rounded,
                          color: Color(0xFFFFA726),
                          size: 22,
                        ),
                        const SizedBox(width: 10),
                        const Expanded(
                          child: Text(
                            'SVaultAI cannot reset, recover, view, or '
                            'bypass your PIN.\n'
                            'If you forget it, your vault may become '
                            'permanently inaccessible.',
                            style: TextStyle(
                              color: Color(0xFFFFE0B2),
                              fontSize: 13,
                              height: 1.4,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  InkWell(
                    onTap: _submitting
                        ? null
                        : () => setState(() {
                              _acknowledgedNoRecovery =
                                  !_acknowledgedNoRecovery;
                            }),
                    borderRadius: BorderRadius.circular(8),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Checkbox(
                            value: _acknowledgedNoRecovery,
                            onChanged: _submitting
                                ? null
                                : (v) => setState(() {
                                      _acknowledgedNoRecovery = v ?? false;
                                    }),
                          ),
                          const Expanded(
                            child: Padding(
                              padding: EdgeInsets.only(top: 12),
                              child: Text(
                                'I understand that SVaultAI cannot '
                                'recover my PIN.',
                                style: TextStyle(
                                  color: Color(0xFFE0E0E0),
                                  fontSize: 13,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                ] else ...[
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFF262626),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: const Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          Icons.info_outline,
                          color: Color(0xFFB4B4B4),
                          size: 18,
                        ),
                        SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Remember: SVaultAI cannot recover forgotten PINs.',
                            style: TextStyle(
                              color: Color(0xFFB4B4B4),
                              fontSize: 12,
                              height: 1.4,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                TextField(
                  key: const Key('pin_gate_pin_field'),
                  controller: pinController,
                  keyboardType: TextInputType.number,
                  obscureText: true,
                  maxLength: _maxPinLength,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 22, letterSpacing: 10),
                  decoration: const InputDecoration(
                    counterText: '',
                    hintText: '••••••',
                  ),
                  enabled: !_submitting,
                  onSubmitted: _submitting ? null : (_) => _submit(),
                ),
                const SizedBox(height: 10),
                if (err != null)
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red.withValues(alpha: 0.10),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(err!,
                        style: const TextStyle(color: Colors.redAccent)),
                  ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    key: const Key('pin_gate_submit_button'),
                    onPressed:
                        (_submitting || (mode && !_acknowledgedNoRecovery))
                            ? null
                            : _submit,
                    child: _submitting
                        ? const SizedBox(
                            height: 18,
                            width: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Text(mode ? 'Create PIN' : 'Unlock'),
                  ),
                ),
                if (!mode)
                  const Padding(
                    padding: EdgeInsets.only(top: 12),
                    child: Text(
                      'Returning users only need their PIN to get back into their vault.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 12),
                    ),
                  ),
                if (!mode)
                  TextButton(
                    onPressed: _submitting ? null : _useAnotherVault,
                    child: Text(
                      AppLocalizations.of(context).authLogInAnotherVault,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class VaultFrozenPage extends StatelessWidget {
  const VaultFrozenPage({super.key});

  Future<void> _signOut(BuildContext context) async {
    final app = context.read<AppState>();
    await app.signOutEverywhere();
    if (!context.mounted) return;
    Navigator.pushNamedAndRemoveUntil(context, '/', (route) => false);
  }

  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.of(context).size.width;
    final isMobile = w < 760;

    return Scaffold(
      appBar: TopNavBar(showActions: false, isMobile: isMobile),
      body: Center(
        child: SizedBox(
          width: w < 480 ? w - 24 : 460,
          child: Container(
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
              color: const Color(0xFF2F2F2F),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: const [
                    Icon(Icons.ac_unit, color: Colors.amber, size: 28),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Vault frozen',
                        style: TextStyle(
                            fontSize: 22, fontWeight: FontWeight.w800),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                const Text(
                  'This vault has been frozen because an inheritance transfer '
                  'completed. Its contents have already been moved to the '
                  'beneficiary\'s account, and the original vault can no '
                  'longer be unlocked.',
                  style: TextStyle(
                      color: Color(0xFFECECEC), fontSize: 14, height: 1.5),
                ),
                const SizedBox(height: 20),
                OutlinedButton.icon(
                  onPressed: () => _signOut(context),
                  icon: const Icon(Icons.logout),
                  label: Text(AppLocalizations.of(context).commonSignOut),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class VaultRecoveryPage extends StatefulWidget {
  const VaultRecoveryPage({super.key});

  @override
  State<VaultRecoveryPage> createState() => _VaultRecoveryPageState();
}

class _VaultRecoveryPageState extends State<VaultRecoveryPage> {
  bool _wiping = false;
  String? _err;

  Future<void> _confirmAndWipe(BuildContext context) async {
    final app = context.read<AppState>();
    final info = app.recoveryInfo;
    if (info == null) {
      Navigator.pushReplacementNamed(context, '/pin');
      return;
    }

    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) {
        return AlertDialog(
          backgroundColor: const Color(0xFF2F2F2F),
          title: Text(
            AppLocalizations.of(dialogCtx).confirmEraseTitle,
          ),
          content: Text(
            'This permanently removes ${info.itemCount} encrypted login(s) '
            'and ${info.fileCount} encrypted file(s) that can no longer be unlocked '
            'because the recovery key for the previous vault was lost.\n\n'
            'This cannot be undone.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogCtx, false),
              child: Text(AppLocalizations.of(dialogCtx).commonCancel),
            ),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
              onPressed: () => Navigator.pop(dialogCtx, true),
              child: Text(
                AppLocalizations.of(dialogCtx).confirmEraseButton,
              ),
            ),
          ],
        );
      },
    );

    if (ok != true) return;

    setState(() {
      _wiping = true;
      _err = null;
    });

    try {
      await app.wipeOrphanDataAndClear();
      if (!context.mounted) return;
      Navigator.pushReplacementNamed(context, '/pin');
    } catch (e) {
      if (app.handleApiException(e)) return;
      if (!mounted) return;
      setState(() {
        _err = e.toString().replaceFirst('Exception: ', '');
      });
    } finally {
      if (mounted) setState(() => _wiping = false);
    }
  }

  Future<void> _signOut(BuildContext context) async {
    final app = context.read<AppState>();
    await app.signOutEverywhere();
    if (!context.mounted) return;
    Navigator.pushNamedAndRemoveUntil(context, '/', (route) => false);
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final info = app.recoveryInfo ?? const VaultRecoveryInfo();
    final w = MediaQuery.of(context).size.width;
    final isMobile = w < 760;

    return Scaffold(
      appBar: TopNavBar(showActions: false, isMobile: isMobile),
      body: Center(
        child: SizedBox(
          width: w < 480 ? w - 24 : 460,
          child: Container(
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
              color: const Color(0xFF2F2F2F),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: const [
                    Icon(Icons.warning_amber_rounded,
                        color: Colors.amber, size: 28),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Vault recovery required',
                        style: TextStyle(
                            fontSize: 22, fontWeight: FontWeight.w800),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Text(
                  info.vaultName != null && info.vaultName!.isNotEmpty
                      ? 'We found encrypted data tied to your account from a previous '
                          'vault ("${info.vaultName}"), but the vault profile that held '
                          'the recovery key is missing.'
                      : 'We found encrypted data tied to your account, but the vault '
                          'profile that held the recovery key is missing.',
                  style: const TextStyle(
                      color: Color(0xFFECECEC), fontSize: 14, height: 1.5),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Without that key, the old data cannot be decrypted by anyone, '
                  'including you. To protect your account, SVaultAI will not let a '
                  'new vault be created on top of it. You must erase the unrecoverable '
                  'data before starting fresh.',
                  style: TextStyle(
                      color: Color(0xFFB4B4B4), fontSize: 13, height: 1.5),
                ),
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.black26,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Unrecoverable logins: ${info.itemCount}',
                          style: const TextStyle(fontSize: 13)),
                      const SizedBox(height: 4),
                      Text('Unrecoverable files: ${info.fileCount}',
                          style: const TextStyle(fontSize: 13)),
                    ],
                  ),
                ),
                if (_err != null) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red.withValues(alpha: 0.10),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(_err!,
                        style: const TextStyle(color: Colors.redAccent)),
                  ),
                ],
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: _wiping ? null : () => _confirmAndWipe(context),
                  style:
                      FilledButton.styleFrom(backgroundColor: Colors.redAccent),
                  icon: _wiping
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white),
                        )
                      : const Icon(Icons.delete_forever_outlined),
                  label: Text(_wiping ? 'Erasing…' : 'Erase and start over'),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _wiping ? null : () => _signOut(context),
                  icon: const Icon(Icons.logout),
                  label: Text(AppLocalizations.of(context).commonSignOut),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class ChatDashboardPage extends StatefulWidget {
  const ChatDashboardPage({super.key});

  @override
  State<ChatDashboardPage> createState() => _ChatDashboardPageState();
}

class _CreateChoiceTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _CreateChoiceTile({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap,
      leading: Icon(icon),
      title: Text(title),
      subtitle: Text(subtitle),
      trailing: const Icon(Icons.chevron_right),
    );
  }
}

class MemoryProposalStripResult {
  final String strippedBuffer;
  final String? jsonPayload;
  const MemoryProposalStripResult({
    required this.strippedBuffer,
    required this.jsonPayload,
  });
}

const String kMemoryProposalOpen = '<<VAULTAI_MEMORY_PROPOSAL>>';
const String kMemoryProposalClose = '<<END>>';

/// Scan `buffer` for the `<<VAULTAI_MEMORY_PROPOSAL>>{json}<<END>>`
/// sentinel. If a full sentinel is found, returns the JSON payload
/// and a buffer with the sentinel + one trailing blank line
/// removed. If only the opening marker is present (mid-chunk), the
/// buffer is truncated at the marker to keep the sentinel out of
/// user view until the closing marker arrives. If `alreadyFinalized`
/// is true, `jsonPayload` is returned as null even when the full
/// sentinel is present, so the caller does not re-fire the finalize
/// call — but the buffer is still stripped so repeated observations
/// across SSE chunks do not leak the sentinel.
///
/// File-scope function (not a method) so the sentinel-strip logic
/// can be tested in isolation without a widget harness.
MemoryProposalStripResult extractAndStripMemoryProposal({
  required String buffer,
  required bool alreadyFinalized,
}) {
  final openIdx = buffer.indexOf(kMemoryProposalOpen);
  if (openIdx < 0) {
    return MemoryProposalStripResult(
      strippedBuffer: buffer,
      jsonPayload: null,
    );
  }
  final closeIdx = buffer.indexOf(
    kMemoryProposalClose,
    openIdx + kMemoryProposalOpen.length,
  );
  if (closeIdx < 0) {
    return MemoryProposalStripResult(
      strippedBuffer: buffer.substring(0, openIdx),
      jsonPayload: null,
    );
  }
  final jsonStart = openIdx + kMemoryProposalOpen.length;
  final jsonPayload = buffer.substring(jsonStart, closeIdx);
  final afterClose = closeIdx + kMemoryProposalClose.length;
  final tail =
      buffer.substring(afterClose).replaceFirst(RegExp(r'^\r?\n\r?\n'), '');
  final strippedBuffer = buffer.substring(0, openIdx) + tail;
  return MemoryProposalStripResult(
    strippedBuffer: strippedBuffer,
    jsonPayload: alreadyFinalized ? null : jsonPayload,
  );
}

class _ChatDashboardPageState extends State<ChatDashboardPage> {
  final http.Client _credentialV2HttpClient = http.Client();
  final Map<String, String> _credentialV2MigrationOperationIds = {};
  bool _cryptoBillingBannerDismissed = false;
  BillingLoadState? _cryptoBillingBannerLastState;

  void _openSecureItemView(String service, String itemType) {
    final safeTitle = service.trim();
    setState(() {
      selectedSection = _DashboardSection.chat;
    });
    if (safeTitle.isEmpty) {
      _sendQuickPrompt('show me');
    } else {
      _sendQuickPrompt('show me $safeTitle');
    }
  }

  CredentialV2Repository? _credentialV2Repository(AppState app) {
    if (!zkV2CredentialReadEnabled) return null;
    final token = app.sessionToken;
    final mvk = zk_mvk_store.ZkActiveMvk.current();
    final vaultId = app.vaultId;
    if (token == null ||
        mvk == null ||
        vaultId == null ||
        zk_mvk_store.ZkActiveMvk.currentVaultId() != vaultId) {
      return null;
    }
    return CredentialV2Repository(
      crypto: CredentialV2Crypto(vk_hier.VaultKeyHierarchy(mvk)),
      api: CredentialV2Api(
        baseUrl: backendBaseUrl,
        sessionToken: token,
        client: _credentialV2HttpClient,
      ),
    );
  }

  String _newCredentialV2RecordId() {
    final random = Random.secure();
    final suffix = base64Url
        .encode(List<int>.generate(12, (_) => random.nextInt(256)))
        .replaceAll('=', '');
    return 'cred-${DateTime.now().microsecondsSinceEpoch}-$suffix';
  }

  String _newCredentialV2OperationId() {
    final bytes = List<int>.generate(16, (_) => Random.secure().nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final hex = bytes.map((value) => value.toRadixString(16).padLeft(2, '0'));
    final value = hex.join();
    return '${value.substring(0, 8)}-${value.substring(8, 12)}-'
        '${value.substring(12, 16)}-${value.substring(16, 20)}-'
        '${value.substring(20)}';
  }

  String _credentialV2MigrationKey(VaultLoginItem item) =>
      '${item.itemType}\u0000${item.service.trim().toLowerCase()}';

  String _credentialV2MigrationRecordId(AppState app, VaultLoginItem item) {
    final material = '${app.vaultId}|${item.itemType}|'
        '${item.service.trim().toLowerCase()}';
    return 'migrated-${sha256.convert(utf8.encode(material))}';
  }

  Future<void> _migrateCredentialV2(VaultLoginItem item) async {
    if (!zkV2CredentialMigrationEnabled ||
        item.cryptoVersion != 'legacy_v1' ||
        !isLoginLikeType(item.itemType)) {
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Migrate this login to credential v2?'),
        content: Text(
          'QA only: migrate exactly ${item.service}. The legacy record is '
          'retained for rollback. This does not run during login.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('credential_v2_migrate_confirm'),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Migrate this item'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final app = context.read<AppState>();
    final repository = _credentialV2Repository(app);
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    if (repository == null || token == null || vaultName == null) {
      _showSnack('Unlock this QA vault again before migration.');
      return;
    }
    final key = _credentialV2MigrationKey(item);
    final operationId = _credentialV2MigrationOperationIds.putIfAbsent(
      key,
      _newCredentialV2OperationId,
    );
    final recordId = _credentialV2MigrationRecordId(app, item);
    final migrator = CredentialV2Migrator(
      crypto: repository.crypto,
      api: repository.api,
    );
    try {
      await migrator.migrateOne(
        recordId: recordId,
        operationId: operationId,
        serviceForLookup: item.service,
        decryptLegacyLocally: () async {
          final pin = await _VaultCrypto.currentPinOrThrow();
          final response =
              await VaultAIClient(baseUrl: backendBaseUrl).getVaultSecureItem(
            vaultName: vaultName,
            service: item.service,
            itemType: item.itemType,
            pin: pin,
            authToken: token,
          );
          final rawFields = response['fields'];
          final fields = rawFields is Map
              ? Map<String, dynamic>.from(rawFields)
              : <String, dynamic>{};
          return CredentialV2Plaintext(
            service: response['service']?.toString() ?? item.service,
            username: fields['username']?.toString() ?? '',
            password: fields['password']?.toString() ?? '',
            url: fields['url']?.toString(),
            notes: response['notes']?.toString() ?? fields['note']?.toString(),
          );
        },
      );
      _credentialV2MigrationOperationIds.remove(key);
      _showSnack('Credential v2 migration verified; legacy retained.');
      await _loadVaultLogins();
    } catch (_) {
      _showSnack('Migration paused safely. Retry reuses the same operation.');
    }
  }

  Future<void> _rollbackCredentialV2(VaultLoginItem item) async {
    if (!zkV2CredentialMigrationEnabled ||
        item.cryptoVersion != credentialV2CryptoVersion ||
        item.recordId == null) {
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Rollback this v2 migration?'),
        content: Text(
          'QA only: hide the v2 envelope for ${item.service} and return to '
          'the retained legacy record.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('credential_v2_rollback_confirm'),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Rollback this item'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    if (!mounted) return;
    final repository = _credentialV2Repository(context.read<AppState>());
    if (repository == null) return;
    try {
      await CredentialV2Migrator(
        crypto: repository.crypto,
        api: repository.api,
      ).rollbackOne(item.recordId!);
      _showSnack('Credential v2 rolled back; retained legacy is active.');
      await _loadVaultLogins();
    } catch (_) {
      _showSnack('Rollback was not available for this item.');
    }
  }

  Future<void> _openCredentialV2Editor(
    VaultLoginItem? item, {
    bool createMode = false,
  }) async {
    final app = context.read<AppState>();
    if (!zkV2CredentialWriteEnabled) {
      _showSnack('Credential v2 writing is disabled.');
      return;
    }
    final repository = _credentialV2Repository(app);
    if (repository == null) {
      _showSnack('Unlock this QA vault again to use credential v2.');
      return;
    }
    CredentialV2Plaintext? existing;
    bool? qaEditPrefillEquality;
    if (item != null) {
      final recordId = item.recordId;
      if (recordId == null) return;
      try {
        existing = await repository.reveal(recordId);
        qaEditPrefillEquality = CredentialV2QaDiagnostics.matches(
          recordId,
          existing,
        );
      } catch (_) {
        _showSnack(
            'Could not decrypt this credential. No legacy fallback was used.');
        return;
      }
    }
    if (!mounted) return;
    final initial = existing == null
        ? <String, String>{}
        : <String, String>{
            'username': existing.username,
            'password': existing.password,
            if (existing.url != null) 'url': existing.url!,
            if (existing.notes != null) 'note': existing.notes!,
          };
    await showSecureItemEditDialog(
      context,
      title: existing?.service ?? '',
      itemType: 'login',
      dialogTitle: createMode
          ? 'New login'
          : credentialV2QaDiagnosticsEnabled && qaEditPrefillEquality != null
              ? qaEditPrefillEquality
                  ? 'QA edit prefill equality: PASS'
                  : 'QA edit prefill equality: FAIL'
              : null,
      initialFields: initial,
      onSave: ({
        required String oldTitle,
        required String itemType,
        required String newTitle,
        required Map<String, String> fields,
      }) async {
        try {
          final recordId = item?.recordId ?? _newCredentialV2RecordId();
          final credential = CredentialV2Plaintext(
            service: newTitle,
            username: fields['username'] ?? '',
            password: fields['password'] ?? '',
            url: fields['url'],
            notes: fields['note'],
            totpSecret: existing?.totpSecret,
            customFields: existing?.customFields ?? const {},
          );
          if (item == null) {
            await repository.create(
              recordId: recordId,
              credential: credential,
              serviceForLookup: newTitle,
            );
          } else {
            await repository.edit(
              recordId: recordId,
              credential: credential,
              serviceForLookup: newTitle,
            );
          }
          CredentialV2QaDiagnostics.remember(recordId, credential);
          _showSnack(item == null ? 'Login saved' : 'Updated login');
          unawaited(_loadVaultLogins());
          if (mounted && item == null) {
            setState(() => selectedSection = _DashboardSection.logins);
          }
          return true;
        } catch (_) {
          _showSnack('Could not save this credential.');
          return false;
        }
      },
    );
  }

  Future<void> _revealCredentialV2(VaultLoginItem item) async {
    final repository = _credentialV2Repository(context.read<AppState>());
    if (repository == null || item.recordId == null) return;
    try {
      final value = await repository.reveal(item.recordId!);
      final equality = CredentialV2QaDiagnostics.matches(
        item.recordId!,
        value,
      );
      await _showCredentialV2Plaintext(value, qaEquality: equality);
    } catch (_) {
      _showSnack(
          'Could not decrypt this credential. No legacy fallback was used.');
    }
  }

  Future<void> _showCredentialV2Plaintext(CredentialV2Plaintext value,
      {bool? qaEquality, CredentialV2QaComparison? qaComparison}) async {
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(value.service),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SelectableText([
              'Username: ${value.username}',
              'Password: ${value.password}',
              if (value.url?.isNotEmpty == true) 'URL: ${value.url}',
              if (value.notes?.isNotEmpty == true) 'Note: ${value.notes}',
              ...value.customFields.entries.map((e) => '${e.key}: ${e.value}'),
            ].join('\n')),
            if (credentialV2QaDiagnosticsEnabled && qaEquality != null)
              Text(
                qaEquality
                    ? 'QA credential plaintext equality: PASS'
                    : 'QA credential plaintext equality: FAIL',
              ),
            if (credentialV2QaDiagnosticsEnabled && qaComparison != null) ...[
              Text('USERNAME_MATCH=${qaComparison.username ? 'PASS' : 'FAIL'}'),
              Text('PASSWORD_MATCH=${qaComparison.password ? 'PASS' : 'FAIL'}'),
              Text('URL_MATCH=${qaComparison.url ? 'PASS' : 'FAIL'}'),
              Text('NOTES_MATCH=${qaComparison.notes ? 'PASS' : 'FAIL'}'),
              Text('TOTP_MATCH=${qaComparison.totp ? 'PASS' : 'FAIL'}'),
              Text(
                'CUSTOM_FIELDS_MATCH=${qaComparison.customFields ? 'PASS' : 'FAIL'}',
              ),
              Text('SERVICE_MATCH=${qaComparison.service ? 'PASS' : 'FAIL'}'),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  Future<bool> _tryLocalCredentialV2LookupReply(
    String text,
    AppState app,
  ) async {
    if (!zkV2CredentialReadEnabled || attachments.isNotEmpty) return false;
    final intent = parseCredentialV2LookupIntent(text);
    if (intent == null) return false;
    if (intent.listAll) {
      input.clear();
      setState(() => selectedSection = _DashboardSection.logins);
      unawaited(_loadVaultLogins());
      return true;
    }
    final service = intent.service!;
    final repository = _credentialV2Repository(app);
    if (repository == null) return false;
    input.clear();
    try {
      final matches = await repository.exactLookup(
        field: 'service',
        value: service,
      );
      if (matches.isEmpty) {
        _appendAssistantMessage('No matching saved login was found.');
        return true;
      }
      if (matches.length == 1) {
        final match = matches.single;
        final comparison = CredentialV2QaDiagnostics.compare(
          match.recordId,
          match.plaintext,
        );
        await _showCredentialV2Plaintext(
          match.plaintext,
          qaEquality: comparison?.all,
          qaComparison: comparison,
        );
        return true;
      }
      if (!mounted) return true;
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Choose a login'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: matches
                .map((record) => ListTile(
                      title: Text(record.plaintext.service),
                      subtitle: Text(record.plaintext.username),
                      onTap: () {
                        Navigator.pop(ctx);
                        final comparison = CredentialV2QaDiagnostics.compare(
                          record.recordId,
                          record.plaintext,
                        );
                        unawaited(
                          _showCredentialV2Plaintext(
                            record.plaintext,
                            qaEquality: comparison?.all,
                            qaComparison: comparison,
                          ),
                        );
                      },
                    ))
                .toList(growable: false),
          ),
        ),
      );
    } catch (_) {
      _appendAssistantMessage(
        'Could not open that saved login. No legacy fallback was used.',
      );
    }
    return true;
  }

  Future<void> _deleteCredentialV2(VaultLoginItem item) async {
    final repository = _credentialV2Repository(context.read<AppState>());
    if (repository == null || item.recordId == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete login?'),
        content: Text('Delete ${item.service}?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Delete')),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await repository.delete(item.recordId!);
      CredentialV2QaDiagnostics.forget(item.recordId!);
      unawaited(_loadVaultLogins());
      _showSnack('Login deleted');
    } catch (_) {
      _showSnack('Could not delete this credential.');
    }
  }

  Future<void> _showCreateMenu() async {
    final app = context.read<AppState>();
    if (!app.authed || !app.unlocked) {
      _showSnack('Unlock your vault first.');
      return;
    }
    final choice = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      constraints: const BoxConstraints(maxWidth: 520),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 18),
          child: Column(
            key: const Key('vault_create_menu'),
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Create',
                style: Theme.of(ctx).textTheme.titleLarge,
              ),
              const SizedBox(height: 8),
              _CreateChoiceTile(
                key: const Key('create_choice_login'),
                icon: Icons.key_outlined,
                title: 'Login',
                subtitle: 'Credentials and access details',
                onTap: () => Navigator.pop(ctx, 'login'),
              ),
              _CreateChoiceTile(
                key: const Key('create_choice_file'),
                icon: Icons.upload_file_outlined,
                title: 'File',
                subtitle: 'Documents, images, videos, and uploads',
                onTap: () => Navigator.pop(ctx, 'file'),
              ),
              _CreateChoiceTile(
                key: const Key('create_choice_memory'),
                icon: Icons.auto_stories_outlined,
                title: 'Memory',
                subtitle: 'Notes, facts, keys, Wi-Fi details, and more',
                onTap: () => Navigator.pop(ctx, 'memory'),
              ),
              const SizedBox(height: 8),
              TextButton(
                key: const Key('create_menu_cancel'),
                onPressed: () => Navigator.pop(ctx),
                child: Text(AppLocalizations.of(ctx).commonCancel),
              ),
            ],
          ),
        ),
      ),
    );
    if (!mounted || choice == null) return;
    switch (choice) {
      case 'login':
        await _openSecureItemEditDialog('', 'login', createMode: true);
        break;
      case 'file':
        await _pickFile();
        break;
      case 'memory':
        await _openCreateMemoryDialog();
        break;
    }
  }

  Future<void> _openCreateMemoryDialog() async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    if (token == null || vaultName == null || vaultName.isEmpty) {
      _showSnack('Session expired.');
      return;
    }
    final data = await showMemoryEditorDialog(context);
    if (data == null) return;
    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      await client.createMemory(
        authToken: token,
        vaultName: vaultName,
        pin: pin,
        data: data,
      );
      if (!mounted) return;
      _showSnack('Memory saved');
      setState(() => selectedSection = _DashboardSection.memory);
      unawaited(app.refreshVaultStats());
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack('Could not save memory: $e');
    }
  }

  Future<void> _openSecureItemEditDialog(String service, String itemType,
      {Map<String, String>? initialFields, bool createMode = false}) async {
    final app = context.read<AppState>();

    if (createMode &&
        isSecureItemLoginLike(itemType) &&
        zkV2CredentialWriteEnabled) {
      await _openCredentialV2Editor(null, createMode: true);
      return;
    }

    Map<String, String> resolved = initialFields ?? const {};
    if (resolved.isEmpty) {
      final token = app.sessionToken;
      if (token != null && app.vaultName != null) {
        try {
          final pin = await _VaultCrypto.currentPinOrThrow();
          final client = VaultAIClient(baseUrl: backendBaseUrl);
          final fetched = await client.getVaultSecureItem(
            vaultName: app.vaultName!,
            service: service,
            itemType: itemType,
            pin: pin,
            authToken: token,
          );
          final raw = fetched['fields'];
          if (raw is Map) {
            resolved = <String, String>{
              for (final e in raw.entries)
                if (e.value is String) e.key.toString(): e.value as String,
            };
          }
        } catch (e) {
          if (app.handleApiException(e)) return;

          _showSnack('Could not load saved values; you can still edit.');
        }
      }
    }
    if (!mounted) return;
    await showSecureItemEditDialog(
      context,
      title: service,
      itemType: itemType,
      dialogTitle: createMode
          ? 'New ${kSecureItemTypeLabelsForDetail[itemType] ?? 'saved item'}'
          : null,
      initialFields: resolved,
      onSave: ({
        required String oldTitle,
        required String itemType,
        required String newTitle,
        required Map<String, String> fields,
      }) async {
        final token = app.sessionToken;
        if (token == null || app.vaultName == null) {
          _showSnack('Session expired.');
          return false;
        }
        try {
          final pin = await _VaultCrypto.currentPinOrThrow();
          final client = VaultAIClient(baseUrl: backendBaseUrl);
          final oldServiceForRequest =
              oldTitle.trim().isEmpty ? newTitle : oldTitle;
          await client.updateVaultSecureItem(
            vaultName: app.vaultName!,
            oldService: oldServiceForRequest,
            itemType: itemType,
            newService: newTitle == oldServiceForRequest ? null : newTitle,
            fields: fields.isEmpty ? null : fields,
            pin: pin,
            authToken: token,
          );

          final isLogin = itemType == 'login' || itemType == 'credential';
          _showSnack(createMode
              ? (isLogin ? 'Login saved' : 'Saved item')
              : (isLogin ? 'Updated login' : 'Updated saved item'));
          unawaited(_loadVaultLogins());
          unawaited(app.refreshVaultStats());
          if (createMode && isLogin) {
            setState(() => selectedSection = _DashboardSection.logins);
          }
          return true;
        } catch (e) {
          if (app.handleApiException(e)) return false;
          _showSnack('Could not update saved item: $e');
          return false;
        }
      },
    );
  }

  bool _isCryptoItemType(String itemType) {
    switch (itemType) {
      case 'crypto_wallet_address':
      case 'crypto_seed_phrase':
      case 'crypto_private_key':
      case 'crypto_recovery_phrase':
      case 'crypto_note':
      case 'crypto_transaction_note':
      case 'crypto_exchange_note':
      case 'crypto_hardware_wallet_note':
        return true;
      default:
        return false;
    }
  }

  String _copyFieldKeyForCryptoType(String itemType) {
    switch (itemType) {
      case 'crypto_wallet_address':
        return 'wallet_address';
      case 'crypto_seed_phrase':
        return 'seed_phrase';
      case 'crypto_private_key':
        return 'private_key';
      case 'crypto_recovery_phrase':
        return 'recovery_phrase';
      case 'crypto_note':
        return 'crypto_note';
      case 'crypto_transaction_note':
        return 'transaction_note';
      case 'crypto_exchange_note':
        return 'exchange_note';
      case 'crypto_hardware_wallet_note':
        return 'hardware_wallet_note';
      default:
        return '';
    }
  }

  Future<void> _copyCryptoValueToClipboard(
      String service, String itemType) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    if (token == null || vaultName == null) {
      _showSnack('Session expired.');
      return;
    }
    final fieldKey = _copyFieldKeyForCryptoType(itemType);
    if (fieldKey.isEmpty) {
      _showSnack("Can't copy this record type.");
      return;
    }
    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final fetched = await client.getVaultSecureItem(
        vaultName: vaultName,
        service: service,
        itemType: itemType,
        pin: pin,
        authToken: token,
      );
      final raw = fetched['fields'];
      String? value;
      if (raw is Map && raw[fieldKey] is String) {
        value = raw[fieldKey] as String;
      }
      if (value == null || value.isEmpty) {
        _showSnack("Couldn't copy — value not found.");
        return;
      }
      await Clipboard.setData(ClipboardData(text: value));
      _showSnack('Copied to clipboard');
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack('Could not copy value.');
    }
  }

  Future<void> _openCryptoReceivePanel(String service, String itemType) async {
    if (itemType != 'crypto_wallet_address') {
      _showSnack("Receive QR is available only for saved wallet addresses.");
      return;
    }
    final app = context.read<AppState>();
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    if (token == null || vaultName == null) {
      _showSnack('Session expired.');
      return;
    }
    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final fetched = await client.getVaultSecureItem(
        vaultName: vaultName,
        service: service,
        itemType: itemType,
        pin: pin,
        authToken: token,
      );
      final raw = fetched['fields'];
      String? address;
      String? network;
      if (raw is Map) {
        if (raw['wallet_address'] is String) {
          address = raw['wallet_address'] as String;
        }
        if (raw['network'] is String) {
          network = raw['network'] as String;
        }
      }
      if (address == null || address.isEmpty) {
        _showSnack("Couldn't open Receive — saved address not found.");
        return;
      }
      if (!mounted) return;
      await showReceivePanelDialog(
        context,
        title: service.isNotEmpty ? service : 'Crypto wallet',
        address: address,
        network: network,
        onCopy: (a) async {
          await Clipboard.setData(ClipboardData(text: a));
          _showSnack('Address copied');
        },
      );
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack('Could not open Receive panel.');
    }
  }

  Future<void> _startSecureItemDeleteConfirmation(
      String service, String itemType) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    final activeVaultId = app.vaultId;
    if (token == null || vaultName == null) {
      _showSnack('Session expired.');
      return;
    }
    if (!app.unlocked) {
      _showSnack('Your vault is locked. Please enter your PIN again.');
      return;
    }
    if (activeVaultId == null ||
        !_VaultCrypto.hasKeyFor(vaultId: activeVaultId, vaultName: vaultName)) {
      app.handleApiException(const InvalidVaultUnlockException());
      return;
    }

    final safeService =
        service.trim().isEmpty ? 'this saved item' : service.trim();
    final isLogin = itemType == 'login' || itemType == 'credential';
    final visibleBubble = isLogin
        ? 'Delete $safeService login from my vault'
        : (service.trim().isEmpty
            ? 'Delete this saved item from my vault'
            : 'Delete $safeService from my vault');
    final sentinel = '__delete_item:$itemType:$safeService';

    setState(() {
      selectedSection = _DashboardSection.chat;
      sending = true;
      thinking = true;
      msgs.add(_Msg('user', visibleBubble));
    });
    _scrollToBottom();

    final client = VaultAIClient(baseUrl: backendBaseUrl);
    try {
      // Snapshot the crypto context ONCE; use it for both encrypt
      // and declared metadata. See _send() for the incident-context
      // rationale — the delete-sentinel path was subject to the
      // exact same race.
      final ctxSnapshot = VaultCryptoRegistry.current;
      if (ctxSnapshot == null ||
          ctxSnapshot.vaultId != activeVaultId ||
          ctxSnapshot.vaultName != vaultName) {
        vlog('delete_sentinel.no_context', {
          'has_ctx': ctxSnapshot != null,
        });
        setState(() {
          sending = false;
          thinking = false;
          if (msgs.isNotEmpty && msgs.last.role == 'user') {
            msgs.removeLast();
          }
        });
        rootScaffoldMessengerKey.currentState?.showSnackBar(
          const SnackBar(
            content: Text(
              'Vault crypto state is out of sync. Please tap Delete '
              'again.',
            ),
          ),
        );
        return;
      }
      final pin = ctxSnapshot.pin;
      final encryptedMessage = await encryptWithContext(
        plaintext: sentinel,
        context: ctxSnapshot,
      );
      int? assistantIndex;
      String buffer = '';
      bool memoryProposalFinalized = false;

      final stream = client.chatStream(
        encryptedMessage: encryptedMessage,
        vaultName: vaultName,
        pin: pin,
        authToken: token,
        uploadedFileIds: const <String>[],
        appLocale: context.read<AppState>().chatReplyLanguageCode,
        kdfSaltUsed: ctxSnapshot.saltBase64,
        kdfIterationsUsed: ctxSnapshot.iterations,
      );
      try {
        await for (final encryptedChunk in stream) {
          try {
            final decryptedChunk = await _VaultCrypto.decrypt(encryptedChunk);
            if (!mounted) return;
            buffer += decryptedChunk;

            // ZK memory-proposal sentinel: strip it BEFORE any
            // downstream parse/render and fire the ciphertext-first
            // finalize exactly once. See _send() for the full policy.
            final _stripped = extractAndStripMemoryProposal(
              buffer: buffer,
              alreadyFinalized: memoryProposalFinalized,
            );
            buffer = _stripped.strippedBuffer;
            if (_stripped.jsonPayload != null && !memoryProposalFinalized) {
              memoryProposalFinalized = true;
              unawaited(_finalizeMemoryProposalBestEffort(
                jsonPayload: _stripped.jsonPayload!,
                authToken: token,
              ));
            }

            // dart format off
            final structuredNow = _tryParseAssistantStructuredMessage(buffer);
            final _Msg replacement = structuredNow ?? _Msg('assistant', buffer);
            // dart format on
            setState(() {
              if (assistantIndex == null) {
                msgs.add(replacement);
                assistantIndex = msgs.length - 1;
                thinking = false;
              } else {
                msgs[assistantIndex!] = replacement;
              }
            });
            _scrollToBottom();
          } catch (e) {
            if (app.handleApiException(e)) return;
            if (!mounted) return;
            setState(() {
              thinking = false;
              if (assistantIndex == null) {
                msgs.add(_Msg('assistant', 'Decrypt error: $e'));
                assistantIndex = msgs.length - 1;
              } else {
                msgs[assistantIndex!] = _Msg('assistant', 'Decrypt error: $e');
              }
            });
          }
        }
      } catch (err) {
        // 2026-07-22 crypto-context mismatch (server 400) — same
        // policy as _send: preserve session, snackbar, no navigate.
        if (err is CryptoContextMismatchException) {
          if (!mounted) return;
          setState(() {
            thinking = false;
            sending = false;
            if (msgs.isNotEmpty && msgs.last.role == 'user') {
              msgs.removeLast();
            }
          });
          rootScaffoldMessengerKey.currentState?.clearSnackBars();
          rootScaffoldMessengerKey.currentState?.showSnackBar(
            SnackBar(content: Text(err.message)),
          );
          return;
        }
        // 2026-07-21 KDF-generation-stale: identical policy to _send.
        // Re-derive from response salt/iter, drop the just-added
        // user bubble, show snackbar, do NOT force PIN, do NOT
        // auto-retry. The user tapped "Delete X"; if the underlying
        // request 409'd they just tap the delete-confirmation button
        // again.
        if (err is KdfGenerationStaleException) {
          bool rederived = false;
          final freshSalt = err.currentPinSalt;
          final freshIter = err.currentKdfIterations;
          if (freshSalt != null &&
              freshSalt.isNotEmpty &&
              freshIter != null &&
              freshIter > 0) {
            rederived = await app.applyFreshKdfMetadata(
              pinSaltBase64: freshSalt,
              iterations: freshIter,
            );
          }
          if (!mounted) return;
          setState(() {
            thinking = false;
            sending = false;
            if (msgs.isNotEmpty && msgs.last.role == 'user') {
              msgs.removeLast();
            }
          });
          rootScaffoldMessengerKey.currentState?.clearSnackBars();
          if (rederived) {
            rootScaffoldMessengerKey.currentState?.showSnackBar(
              SnackBar(content: Text(err.message)),
            );
          } else {
            rootScaffoldMessengerKey.currentState?.showSnackBar(
              const SnackBar(
                content: Text(
                  'The vault was updated. Please enter your PIN '
                  'again to continue.',
                ),
              ),
            );
            rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
              '/pin',
              (_) => false,
            );
          }
          return;
        }
        // Route InvalidVaultUnlockException / VaultLockedException /
        // SessionTerminatedException / DeviceNotTrustedException
        // through the AppState handler so the vault re-locks, the
        // key cache is cleared, and the user lands on the correct
        // recovery screen. Without this, the SSE stream's outer
        // catch would paint the raw exception ("Error:
        // InvalidVaultUnlockException(message: ...)") straight into
        // the assistant bubble AND leave app.unlocked=true — the
        // 2026-07-20 dashboard-says-unlocked/chat-says-expired
        // desync symptom.
        if (app.handleApiException(err)) return;
        if (!mounted) return;
        setState(() {
          thinking = false;
          if (assistantIndex == null) {
            msgs.add(_Msg('assistant', 'Error: $err'));
            assistantIndex = msgs.length - 1;
          } else {
            msgs[assistantIndex!] = _Msg('assistant', 'Error: $err');
          }
        });
      }

      if (assistantIndex != null && buffer.isNotEmpty) {
        final structured = _tryParseAssistantStructuredMessage(buffer);
        if (structured != null && mounted) {
          setState(() => msgs[assistantIndex!] = structured);
        }
      }
      if (mounted && thinking) setState(() => thinking = false);
      await app.refreshVaultStats();
      await _loadVaultLogins();
    } catch (e) {
      if (app.handleApiException(e)) return;
      if (!mounted) return;
      setState(() {
        thinking = false;
        msgs.add(_Msg('assistant', 'Could not start delete: $e'));
      });
    } finally {
      if (mounted) setState(() => sending = false);
    }
  }

  final input = TextEditingController();
  bool _composerSubmitStarting = false;
  final List<_Msg> msgs = <_Msg>[];
  final List<_Attachment> attachments = [];
  final ScrollController _scrollController = ScrollController();
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();

  bool sending = false;
  bool thinking = false;
  final ChatRequestCoordinator _chatRequests = ChatRequestCoordinator();
  StreamIterator<String>? _activeChatIterator;
  String? _activeChatRequestId;
  final Set<String> _cancelledChatRequestIds = <String>{};

  Future<void> _cancelActiveChatRequest() async {
    final requestId = _activeChatRequestId;
    if (requestId == null) return;
    _chatRequests.cancel(requestId);
    _cancelledChatRequestIds.add(requestId);
    final iterator = _activeChatIterator;
    _activeChatIterator = null;
    _activeChatRequestId = null;
    await iterator?.cancel();
    if (!mounted) return;
    setState(() {
      final assistantIndex = msgs.indexWhere(
        (message) => message.requestId == requestId && message.isAssistant,
      );
      if (assistantIndex >= 0) {
        msgs[assistantIndex] = _Msg('assistant', 'Cancelled.')
            .withCorrelationFrom(msgs[assistantIndex]);
      }
      thinking = false;
      sending = false;
    });
  }

  bool loadingFiles = false;
  bool loadingLogins = false;

  bool hasLoadedSecureItems = false;
  String? secureItemsError;

  final stt.SpeechToText _speech = stt.SpeechToText();
  bool _speechAvailable = false;
  bool _speechInitialized = false;
  bool _isListening = false;
  String _preMicText = '';

  final AudioRecorder _audioRecorder = AudioRecorder();
  bool _isRecording = false;
  // Legacy inline-banner state remains false on the web. Web recording now
  // lives entirely inside WebVideoRecorderDialog.
  bool _isVideoRecording = false;
  String? _videoPreviewViewType;
  String? _audioRecordingName;

  final VideoRecorder _videoRecorder = VideoRecorder();

  late final NativeMediaCaptureService _nativeMediaCapture;
  late final RecordingStorage _recordingStorage;

  late final UploadQueueController _uploadQueue;

  _UploadContext? _currentUploadContext;

  late final FolderPickerService _folderPicker;

  bool Function()? _uploadKeepAliveProbe;
  void Function()? _uploadShutdownHook;
  bool _wasUploadQueueBusy = false;

  List<_VaultStoredFile> vaultFiles = [];

  String? activeDeepScanJobId;
  String? activeDeepScanIntent;
  String? activeDeepScanQuery;
  String? activeDeepScanStatus;
  GlobalKey? activeDeepScanCardKey;

  bool isDeepScanActive({
    required String intent,
    required String normalizedQuery,
  }) {
    if (activeDeepScanJobId == null) return false;
    if (activeDeepScanStatus != 'scanning') return false;
    if (activeDeepScanIntent != intent) return false;
    if (activeDeepScanQuery != normalizedQuery) return false;
    return true;
  }

  String normalizeDeepScanQuery(String? query) {
    if (query == null || query.isEmpty) return '';
    return query.toLowerCase().trim().split(RegExp(r'\s+')).join(' ');
  }

  String _currentFolderPath = '';
  FolderTreeData? _folderTreeData;
  String _folderSearchQuery = '';
  List<VaultLoginItem> vaultLogins = [];

  _DashboardSection selectedSection = _DashboardSection.chat;
  final CryptoWalletMainnetSendApprovalSession _chatMainnetSendApprovalSession =
      CryptoWalletMainnetSendApprovalSession();

  List<Map<String, dynamic>> beneficiaries = [];
  List<Map<String, dynamic>> inheritances = [];
  bool loadingBeneficiaries = false;
  bool loadingInheritances = false;
  bool _inheritanceLoadedOnce = false;

  // Monotonic generation counter for _loadBeneficiaries. 2026-07-22:
  // ``_loadBeneficiaries`` is called from ~10 UI sites (dialog
  // dismissals, refresh buttons, post-mutation reloads). On iOS
  // Safari an in-flight fetch that is superseded by a newer call —
  // or by a page teardown — surfaces as ``ClientException: Load
  // failed`` from package:http. That aborted request is unrelated
  // to the newer 200 the backend records; showing it as a toast
  // misleads the operator. We record the generation at entry and
  // only apply results / show errors when it still matches, so a
  // stale invocation is silently discarded.
  int _loadBeneficiariesGen = 0;

  Future<void> _loadBeneficiaries() async {
    final myGen = ++_loadBeneficiariesGen;
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null || app.vaultName == null) return;

    setState(() => loadingBeneficiaries = true);
    // Per-invocation correlation id sent on the wire so an
    // operator can align nginx access-log entries with the
    // client-diagnostic log line. Never used for auth. Bounded
    // by the api_client to 64 chars.
    final clientRequestId =
        'lm-${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}-'
        '${myGen.toRadixString(36)}';
    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.listBeneficiaries(
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
        clientRequestId: clientRequestId,
      );
      // Discard results from a superseded invocation. A newer
      // _loadBeneficiaries has already started; its result is
      // what should populate the panel.
      if (!mounted || myGen != _loadBeneficiariesGen) return;
      final raw = result['beneficiaries'];
      final resolved = raw is List
          ? await Future.wait(raw
              .whereType<Map>()
              .map((m) => resolveOwnerBeneficiaryLabelForDisplay(
                    Map<String, dynamic>.from(m),
                  )))
          : <Map<String, dynamic>>[];
      if (!mounted || myGen != _loadBeneficiariesGen) return;
      setState(() {
        beneficiaries = resolved;
      });
    } catch (e) {
      // Skip stale errors — a newer invocation is in flight or
      // already resolved.
      if (myGen != _loadBeneficiariesGen) {
        vlog('inheritance.list_mine.stale', {
          'gen': myGen,
          'current_gen': _loadBeneficiariesGen,
          'exception_type': e.runtimeType.toString(),
        });
        // Fire-and-forget diagnostic (safe fields only).
        unawaited(VaultAIClient(baseUrl: backendBaseUrl)
            .postInheritanceClientDiagnostic(
          authToken: token,
          body: {
            'area': 'beneficiary_list',
            'reference_code': 'INH-LIST-MINE-STALE',
            'client_request_id': clientRequestId,
            'exception_type': e.runtimeType.toString(),
            'category': 'stale',
          },
        ));
        return;
      }
      if (app.handleApiException(e)) return;
      // Distinguish network-level aborts (iOS Safari "Load
      // failed" ClientException, browser cancellations) from
      // real backend errors. A network abort is informational
      // — a subsequent refresh will populate the panel — and
      // must not toast the user with a scary "ClientException"
      // string. Real errors (auth, backend-side exceptions
      // that surfaced with a body) still toast.
      if (_looksLikeNetworkAbort(e)) {
        vlog('inheritance.list_mine.network_abort', {
          'exception_type': e.runtimeType.toString(),
          'client_request_id': clientRequestId,
        });
        unawaited(VaultAIClient(baseUrl: backendBaseUrl)
            .postInheritanceClientDiagnostic(
          authToken: token,
          body: {
            'area': 'beneficiary_list',
            'reference_code': 'INH-LIST-MINE-ABORT',
            'client_request_id': clientRequestId,
            'exception_type': e.runtimeType.toString(),
            'category': 'network_abort',
          },
        ));
        return;
      }
      _showSnack('Could not load beneficiaries: $e');
    } finally {
      // Only clear the loading spinner if we're still the latest
      // invocation. Otherwise the newer invocation is in charge
      // of the spinner state.
      if (mounted && myGen == _loadBeneficiariesGen) {
        setState(() => loadingBeneficiaries = false);
      }
    }
  }

  // Recognises the browser fetch-level failures that
  // ``package:http`` surfaces as `ClientException`. On iOS Safari
  // these carry the message "Load failed"; other browsers use
  // "Failed to fetch" / "aborted" / "cancelled". None of these
  // are backend errors — the request either was aborted client-
  // side (page navigation, superseded refresh, `AbortController`)
  // or failed at the network layer before a status code was
  // returned. Treat as informational: log via the diagnostic
  // endpoint and let the next refresh populate the panel.
  bool _looksLikeNetworkAbort(Object e) {
    final s = e.toString().toLowerCase();
    return s.contains('clientexception') ||
        s.contains('load failed') ||
        s.contains('failed to fetch') ||
        s.contains('aborted') ||
        s.contains('cancelled') ||
        s.contains('canceled') ||
        s.contains('network is offline') ||
        s.contains('network request failed');
  }

  Future<void> _loadInheritances() async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null || app.vaultName == null) return;

    setState(() => loadingInheritances = true);
    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.listInheritances(
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
      );
      final raw = result['inheritances'];
      if (!mounted) return;
      setState(() {
        inheritances = raw is List
            ? raw
                .whereType<Map>()
                .map((m) => Map<String, dynamic>.from(m))
                .toList()
            : <Map<String, dynamic>>[];
      });
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack('Could not load inheritances: $e');
    } finally {
      if (mounted) setState(() => loadingInheritances = false);
    }
  }

  Future<void> _showAddBeneficiaryDialog() async {
    final labelCtrl = TextEditingController();
    final formKey = GlobalKey<FormState>();
    String? pairingCode;
    String? createErr;
    bool creating = false;

    await showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogCtx) {
        return StatefulBuilder(
          builder: (ctx, setLocal) {
            return AlertDialog(
              backgroundColor: const Color(0xFF2F2F2F),
              title: Text(
                pairingCode == null
                    ? AppLocalizations.of(dialogCtx).inheritanceAddBeneficiary
                    : 'Pairing code',
              ),
              content: pairingCode == null
                  ? Form(
                      key: formKey,
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          const Text(
                            'Give this beneficiary a label only you will see, '
                            'like "Son - John". You\'ll get a one-time code to '
                            'share with them out-of-band.',
                            style: TextStyle(
                                color: Color(0xFFB4B4B4), fontSize: 13),
                          ),
                          const SizedBox(height: 12),
                          TextFormField(
                            controller: labelCtrl,
                            maxLength: 60,
                            decoration: const InputDecoration(
                              counterText: '',
                              hintText: 'Label (e.g. Son - John)',
                            ),
                            validator: (v) => (v == null || v.trim().isEmpty)
                                ? 'Required'
                                : null,
                          ),
                          if (createErr != null) ...[
                            const SizedBox(height: 10),
                            Text(createErr!,
                                style:
                                    const TextStyle(color: Colors.redAccent)),
                          ],
                        ],
                      ),
                    )
                  : Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text(
                          'Share this code with your beneficiary out-of-band '
                          '(Signal, in person, paper). It works once and '
                          'expires in 60 minutes.',
                          style:
                              TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
                        ),
                        const SizedBox(height: 14),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              vertical: 14, horizontal: 12),
                          decoration: BoxDecoration(
                            color:
                                const Color(0xFF10A37F).withValues(alpha: 0.10),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: SelectableText(
                            pairingCode!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 2,
                              color: Color(0xFF10A37F),
                            ),
                          ),
                        ),
                      ],
                    ),
              actions: pairingCode == null
                  ? [
                      TextButton(
                        onPressed:
                            creating ? null : () => Navigator.pop(dialogCtx),
                        child: Text(AppLocalizations.of(context).commonCancel),
                      ),
                      FilledButton.icon(
                        onPressed: creating
                            ? null
                            : () async {
                                if (formKey.currentState?.validate() != true)
                                  return;
                                final app = context.read<AppState>();
                                final token = app.sessionToken;
                                if (token == null || app.vaultName == null) {
                                  setLocal(
                                      () => createErr = 'Session expired.');
                                  return;
                                }
                                setLocal(() {
                                  creating = true;
                                  createErr = null;
                                });
                                try {
                                  final pin =
                                      await _VaultCrypto.currentPinOrThrow();
                                  final client =
                                      VaultAIClient(baseUrl: backendBaseUrl);
                                  final labelText = labelCtrl.text.trim();
                                  final result = await client.createBeneficiary(
                                    vaultName: app.vaultName!,
                                    pin: pin,
                                    label: labelText,
                                    authToken: token,
                                  );
                                  // ZK client-finalize: for ZK vaults,
                                  // /beneficiary/create wrote
                                  // passer_label = NULL. Encrypt the
                                  // label locally under metadataKey
                                  // and POST the ciphertext to
                                  // /vault/ciphertext/beneficiary-links
                                  // BEFORE surfacing the pairing code.
                                  // If the finalize fails, do NOT
                                  // silently claim success — refuse
                                  // to hand out the pairing code with
                                  // an unlabelled row (the beneficiary
                                  // list would be unreadable). Show
                                  // the error and let the user retry.
                                  if (zk_mvk_store.ZkActiveMvk.current() !=
                                      null) {
                                    final linkId =
                                        (result['link_id'] as num?)?.toInt();
                                    if (linkId == null) {
                                      setLocal(() {
                                        createErr = 'Could not finalize the '
                                            'label: missing link_id in '
                                            'the create response.';
                                        creating = false;
                                      });
                                      return;
                                    }
                                    final ok =
                                        await tryZkFinalizeBeneficiaryLabelCiphertext(
                                      baseUrl: backendBaseUrl,
                                      authToken: token,
                                      linkId: linkId,
                                      label: labelText,
                                    );
                                    if (!ok) {
                                      // Full detail is captured by
                                      // the network log inside
                                      // tryZkFinalizeBeneficiaryLabelCiphertext;
                                      // surface only a safe reference
                                      // to the user so we never leak
                                      // an SQL trace or an internal
                                      // field name.
                                      setLocal(() {
                                        createErr = 'Could not generate the '
                                            'pairing code. Please try '
                                            'again.\nReference: '
                                            'INH-PAIR-004';
                                        creating = false;
                                      });
                                      return;
                                    }
                                  }
                                  // dart format off
                                  setLocal(() {
                                    pairingCode =
                                        result['pairing_code']?.toString();
                                    creating = false;
                                  });
                                  // dart format on
                                  await _loadBeneficiaries();
                                } catch (e) {
                                  if (app.handleApiException(e)) return;
                                  // Log the raw exception for support;
                                  // show the safe reference to the
                                  // user so no stack / SQL text leaks.
                                  vlog('inheritance.pair.create.failed', {
                                    'error': e.toString(),
                                  });
                                  setLocal(() {
                                    createErr = 'Could not generate the '
                                        'pairing code. Please try '
                                        'again.\nReference: '
                                        'INH-PAIR-001';
                                    creating = false;
                                  });
                                }
                              },
                        icon: creating
                            ? const SizedBox(
                                width: 14,
                                height: 14,
                                child: CircularProgressIndicator(
                                    strokeWidth: 2, color: Colors.white),
                              )
                            : const Icon(Icons.qr_code_2),
                        label: Text(creating ? 'Generating…' : 'Generate code'),
                      ),
                    ]
                  : [
                      FilledButton.icon(
                        onPressed: () {
                          Clipboard.setData(ClipboardData(text: pairingCode!));
                          _showSnack('Copied to clipboard');
                        },
                        icon: const Icon(Icons.copy_all_outlined),
                        label: Text(
                          AppLocalizations.of(dialogCtx).commonCopyCode,
                        ),
                      ),
                      OutlinedButton(
                        onPressed: () => Navigator.pop(dialogCtx),
                        child: const Text('Done'),
                      ),
                    ],
            );
          },
        );
      },
    );
  }

  Future<void> _showEnterPairingCodeDialog() async {
    final codeCtrl = TextEditingController();
    String? linkErr;
    String? linkedLabel;
    bool linking = false;

    await showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogCtx) {
        return StatefulBuilder(
          builder: (ctx, setLocal) {
            return AlertDialog(
              backgroundColor: const Color(0xFF2F2F2F),
              title: Text(
                  linkedLabel == null ? 'Enter inheritance code' : 'Linked!'),
              content: linkedLabel == null
                  ? Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text(
                          'Type the pairing code your benefactor gave you. '
                          'Once linked, you\'ll be able to request transfer '
                          'whenever you need to.',
                          style:
                              TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: codeCtrl,
                          autocorrect: false,
                          textCapitalization: TextCapitalization.characters,
                          decoration: const InputDecoration(
                            hintText: 'XXX-XXXX-XXXX',
                          ),
                        ),
                        if (linkErr != null) ...[
                          const SizedBox(height: 10),
                          Text(linkErr!,
                              style: const TextStyle(color: Colors.redAccent)),
                        ],
                      ],
                    )
                  : Text(
                      'You are now linked as a beneficiary of "$linkedLabel". '
                      'You can request transfer from the Inheritance page at any time.',
                      style: const TextStyle(
                          color: Color(0xFFECECEC), fontSize: 13),
                    ),
              actions: linkedLabel == null
                  ? [
                      TextButton(
                        onPressed:
                            linking ? null : () => Navigator.pop(dialogCtx),
                        child: Text(AppLocalizations.of(context).commonCancel),
                      ),
                      FilledButton.icon(
                        onPressed: linking
                            ? null
                            : () async {
                                final code = codeCtrl.text.trim();
                                if (code.isEmpty) {
                                  setLocal(() => linkErr = 'Enter the code.');
                                  return;
                                }
                                final app = context.read<AppState>();
                                final token = app.sessionToken;
                                if (token == null || app.vaultName == null) {
                                  setLocal(() => linkErr = 'Session expired.');
                                  return;
                                }
                                setLocal(() {
                                  linking = true;
                                  linkErr = null;
                                });
                                try {
                                  final pin =
                                      await _VaultCrypto.currentPinOrThrow();
                                  final client =
                                      VaultAIClient(baseUrl: backendBaseUrl);
                                  final result = await client.linkBeneficiary(
                                    vaultName: app.vaultName!,
                                    pin: pin,
                                    pairingCode: code,
                                    authToken: token,
                                  );
                                  setLocal(() {
                                    linkedLabel =
                                        result['passer_label']?.toString() ??
                                            'vault';
                                    linking = false;
                                  });
                                  await _loadInheritances();
                                } catch (e) {
                                  if (app.handleApiException(e)) return;
                                  setLocal(() {
                                    linkErr = e
                                        .toString()
                                        .replaceFirst('Exception: ', '');
                                    linking = false;
                                  });
                                }
                              },
                        icon: linking
                            ? const SizedBox(
                                width: 14,
                                height: 14,
                                child: CircularProgressIndicator(
                                    strokeWidth: 2, color: Colors.white),
                              )
                            : const Icon(Icons.link),
                        label: Text(linking ? 'Linking…' : 'Link to vault'),
                      ),
                    ]
                  : [
                      FilledButton(
                        onPressed: () => Navigator.pop(dialogCtx),
                        child: const Text('Done'),
                      ),
                    ],
            );
          },
        );
      },
    );
  }

  Future<void> _cancelTransfer(int linkId, String label) async {
    final app = context.read<AppState>();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text(
          AppLocalizations.of(dialogCtx)
              .inheritanceCancelPendingTransferTitle(label),
        ),
        content: const Text(
          // 2026-07-23: SVaultAI does not email — the cancel notify
          // fires via _create_notification (in-app only).
          'The 30-day countdown will be cleared. The beneficiary will '
          'be notified inside SVaultAI. They can request again later.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogCtx, false),
              child: const Text('Keep')),
          FilledButton(
            onPressed: () => Navigator.pop(dialogCtx, true),
            child: Text(
              AppLocalizations.of(dialogCtx).inheritanceCancelTransfer,
            ),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    final token = app.sessionToken;
    if (token == null || app.vaultName == null) return;

    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      await client.cancelTransfer(
        linkId: linkId,
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
      );
      _showSnack('Transfer cancelled');
      await _loadBeneficiaries();
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack('Could not cancel transfer: $e');
    }
  }

  Future<void> _claimInheritance(int linkId, String label) async {
    final inheritedNameCtrl = TextEditingController(text: '$label (inherited)');
    String? err;
    bool claiming = false;

    await showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogCtx) {
        return StatefulBuilder(
          builder: (ctx, setLocal) {
            return AlertDialog(
              backgroundColor: const Color(0xFF2F2F2F),
              title: Text(
                AppLocalizations.of(dialogCtx).inheritanceClaimTitle(label),
              ),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'A new vault will be created on your account containing '
                    'all of the inherited data, encrypted under your PIN. '
                    'The original vault is then frozen for 90 days.',
                    style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: inheritedNameCtrl,
                    maxLength: 60,
                    decoration: const InputDecoration(
                      counterText: '',
                      hintText: 'Name for the inherited vault',
                    ),
                  ),
                  if (err != null) ...[
                    const SizedBox(height: 10),
                    Text(err!, style: const TextStyle(color: Colors.redAccent)),
                  ],
                ],
              ),
              actions: [
                TextButton(
                  onPressed: claiming ? null : () => Navigator.pop(dialogCtx),
                  child: Text(AppLocalizations.of(dialogCtx).commonCancel),
                ),
                FilledButton.icon(
                  onPressed: claiming
                      ? null
                      : () async {
                          final newName = inheritedNameCtrl.text.trim();
                          if (newName.isEmpty) {
                            setLocal(
                                () => err = 'Pick a name for the new vault.');
                            return;
                          }
                          final app = context.read<AppState>();
                          final token = app.sessionToken;
                          if (token == null || app.vaultName == null) {
                            setLocal(() => err = 'Session expired.');
                            return;
                          }
                          setLocal(() {
                            claiming = true;
                            err = null;
                          });
                          try {
                            final pin = await _VaultCrypto.currentPinOrThrow();
                            final client =
                                VaultAIClient(baseUrl: backendBaseUrl);
                            final result = await client.claimTransfer(
                              linkId: linkId,
                              vaultName: app.vaultName!,
                              pin: pin,
                              inheritedVaultName: newName,
                              authToken: token,
                            );
                            final inheritedName =
                                result['inherited_vault_name']?.toString() ??
                                    newName;
                            if (!context.mounted) return;
                            Navigator.pop(dialogCtx);
                            _showSnack(
                                'Claimed! New vault "$inheritedName" is available in your vault list.');
                            await _loadInheritances();
                            await app.refreshAvailableVaults();
                          } catch (e) {
                            if (app.handleApiException(e)) return;
                            setLocal(() {
                              err =
                                  e.toString().replaceFirst('Exception: ', '');
                              claiming = false;
                            });
                          }
                        },
                  icon: claiming
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white),
                        )
                      : const Icon(Icons.move_to_inbox),
                  label: Text(claiming ? 'Claiming…' : 'Claim'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  Future<void> _requestTransfer(int linkId, String label) async {
    final app = context.read<AppState>();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text(
          AppLocalizations.of(dialogCtx).inheritanceRequestTransferTitle(label),
        ),
        content: const Text(
          // 2026-07-23: text corrected against the actual backend
          // state machine. SVaultAI does not email — it notifies
          // owners in-app. The post-countdown behavior is NOT
          // automatic release: the beneficiary must call
          // /inheritance/access/claim → /credentials/retrieve to
          // move the escrow to 'released'. See
          // inheritance_release_routes.py::claim_access.
          'A 30-day countdown will start. The vault owner will be '
          'notified inside SVaultAI and can approve or reject the '
          'request during that period. If the owner does not respond '
          'before the countdown ends, you\'ll be able to claim the '
          'credentials and open the inherited login on your account.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogCtx, false),
            child: Text(AppLocalizations.of(dialogCtx).commonNotYet),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogCtx, true),
            child: Text(
              AppLocalizations.of(dialogCtx).inheritanceStartCountdown,
            ),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    final token = app.sessionToken;
    if (token == null || app.vaultName == null) return;

    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      await client.requestTransfer(
        linkId: linkId,
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
      );
      _showSnack('Transfer requested — owner has been notified');
      await _loadInheritances();
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack('Could not request transfer: $e');
    }
  }

  String _formatCountdown(String? isoExecutesAt) {
    if (isoExecutesAt == null) return '';
    try {
      final executes = DateTime.parse(isoExecutesAt).toLocal();
      final remaining = executes.difference(DateTime.now());
      if (remaining.isNegative) return 'Ready to claim';
      final days = remaining.inDays;
      final hours = remaining.inHours % 24;
      if (days >= 1)
        return '$days day${days == 1 ? '' : 's'}, $hours hr remaining';
      final minutes = remaining.inMinutes % 60;
      return '${remaining.inHours} hr $minutes min remaining';
    } catch (_) {
      return '';
    }
  }

  Future<void> _deleteBeneficiary(int linkId, String label) async {
    final app = context.read<AppState>();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text(
          AppLocalizations.of(dialogCtx).inheritanceRemoveTitle(label),
        ),
        content: const Text(
          'They will no longer be able to inherit this vault. They can be re-added later with a new code.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogCtx, false),
            child: Text(AppLocalizations.of(dialogCtx).commonCancel),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
            onPressed: () => Navigator.pop(dialogCtx, true),
            child: Text(AppLocalizations.of(dialogCtx).commonRemove),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    final token = app.sessionToken;
    if (token == null || app.vaultName == null) return;

    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      await client.deleteBeneficiary(
        linkId: linkId,
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
      );
      // 2026-07-22: synchronously remove the deleted card from local
      // state BEFORE the authoritative refresh. The refresh path
      // (``_loadBeneficiaries``) is gated by a generation counter
      // that can silently discard the reload when a concurrent
      // panel refresh is in flight — without this local removal the
      // card lingered in the UI even though the backend deletion
      // succeeded (POST /beneficiary/delete → 200). See
      // test/inheritance_delete_beneficiary_refresh_2026_07_22_test.dart.
      if (mounted) {
        setState(() {
          beneficiaries = beneficiaries
              .where((b) => (b['id'] as num?)?.toInt() != linkId)
              .toList();
        });
      }
      _showSnack('Removed $label');
      await _loadBeneficiaries();
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack('Could not remove beneficiary: $e');
    }
  }

// ---------------------------------------------------------------------
// Inheritance credential escrow — owner side (Phase 1).
//
// Encrypts {version, username, pin, created_at} client-side against
// the beneficiary's stored X25519 public key and POSTs only the
// wrapped bytes to /inheritance/credentials/{save,replace,delete}.
// The username field is autofilled from the authenticated vault
// name to reduce typos; the owner can still edit it.
// ---------------------------------------------------------------------

  String _shortDateFromIso(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    try {
      final dt = DateTime.parse(iso).toLocal();
      // "Jan 3" style — locale-neutral short date without a year.
      const months = [
        'Jan',
        'Feb',
        'Mar',
        'Apr',
        'May',
        'Jun',
        'Jul',
        'Aug',
        'Sep',
        'Oct',
        'Nov',
        'Dec',
      ];
      return '${months[dt.month - 1]} ${dt.day}';
    } catch (_) {
      return iso;
    }
  }

  Future<void> _showInheritanceCredentialsDialog({
    required int linkId,
    required String beneficiaryLabel,
    required bool isUpdate,
  }) async {
    final app = context.read<AppState>();
    final autofilledUsername = app.vaultName ?? '';
    final usernameCtrl = TextEditingController(text: autofilledUsername);
    final pinCtrl = TextEditingController();
    final formKey = GlobalKey<FormState>();
    bool saving = false;
    String? errRef;

    await showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogCtx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF2F2F2F),
          title: Text(
            isUpdate
                ? 'Update credentials for $beneficiaryLabel'
                : 'Credentials to inherit',
          ),
          content: SingleChildScrollView(
            child: Form(
              key: formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                    'These are the SVaultAI login credentials this '
                    'beneficiary will inherit. SVaultAI can never read '
                    'them — they are encrypted on this device and '
                    'released only after your approval or the 30-day '
                    'cooldown.',
                    style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'SVaultAI username',
                    style: TextStyle(fontSize: 12, color: Color(0xFFB4B4B4)),
                  ),
                  TextFormField(
                    key: const Key('inheritance_cred_username_field'),
                    controller: usernameCtrl,
                    autofillHints: const [AutofillHints.username],
                    decoration: const InputDecoration(
                      hintText: 'Autofilled from your account',
                      isDense: true,
                    ),
                    validator: (v) => (v == null || v.trim().isEmpty)
                        ? 'Username is required'
                        : null,
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'SVaultAI PIN',
                    style: TextStyle(fontSize: 12, color: Color(0xFFB4B4B4)),
                  ),
                  TextFormField(
                    key: const Key('inheritance_cred_pin_field'),
                    controller: pinCtrl,
                    obscureText: true,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      hintText: 'Enter the PIN to escrow',
                      isDense: true,
                    ),
                    validator: (v) {
                      final s = (v ?? '').trim();
                      if (s.isEmpty) return 'PIN is required';
                      if (s.length < 4) return 'PIN is too short';
                      return null;
                    },
                  ),
                  if (errRef != null) ...[
                    const SizedBox(height: 10),
                    Text(
                      errRef!,
                      style: const TextStyle(
                          color: Color(0xFFE57373), fontSize: 12),
                    ),
                  ],
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: saving ? null : () => Navigator.pop(dialogCtx, false),
              child: const Text('Cancel'),
            ),
            FilledButton.icon(
              key: const Key('inheritance_cred_save_button'),
              onPressed: saving
                  ? null
                  : () async {
                      if (!(formKey.currentState?.validate() ?? false)) {
                        return;
                      }
                      setLocal(() {
                        saving = true;
                        errRef = null;
                      });
                      final result = await _submitInheritanceCredentials(
                        linkId: linkId,
                        username: usernameCtrl.text.trim(),
                        pin: pinCtrl.text.trim(),
                        isUpdate: isUpdate,
                      );
                      if (result.ok) {
                        // Wipe the plaintext from the widget's memory
                        // as soon as we no longer need it.
                        usernameCtrl.text = '';
                        pinCtrl.text = '';
                        if (dialogCtx.mounted) {
                          Navigator.pop(dialogCtx, true);
                        }
                      } else {
                        // 2026-07-22: surface the ACTUAL failure code
                        // (backend detail.code when the request
                        // reached the backend, or a distinct
                        // INH-CRED-CLIENT-* sentinel when it
                        // failed before that). Never hardcode
                        // INH-CRED-004 anymore — that string was
                        // masking every non-shape failure mode.
                        setLocal(() {
                          saving = false;
                          errRef = 'Could not save credentials. Please try '
                              'again.\nReference: ${result.code}';
                        });
                      }
                    },
              icon: saving
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.lock_outline),
              label: Text(saving ? 'Saving…' : 'Save securely'),
            ),
          ],
        ),
      ),
    );

    // Best-effort clear of the controllers after the dialog closes.
    usernameCtrl.dispose();
    pinCtrl.dispose();
    await _loadBeneficiaries();
  }

  /// Owner-side "Save securely" handler. Returns a record so the
  /// dialog can surface the ACTUAL failure reference tag rather
  /// than the pre-2026-07-22 hardcoded ``INH-CRED-004`` fallback:
  ///
  ///   * ``ok = true``  → save succeeded; ``code`` is unused
  ///   * ``ok = false`` → save failed; ``code`` is the reference to
  ///                      display, one of:
  ///                        - the backend's ``detail.code``
  ///                          (``INH-CRED-005``, ``INH-CRED-006``,
  ///                          ``INH-CRED-007``, ``INH-CRED-001``,
  ///                          ``INH-CRED-002``, ``INH-CRED-003``,
  ///                          ``INH-CRED-004``, ``INH-CRED-401``, …)
  ///                          when the failure came from the
  ///                          backend and carried a parsable detail;
  ///                        - a ``INH-CRED-CLIENT-*`` sentinel when
  ///                          the failure was purely client-side and
  ///                          the request never left the device.
  ///
  /// The user-facing wording is set by the caller; this method only
  /// PRESERVES and RETURNS the code — no crypto, backend validation,
  /// or state-machine change.
  Future<({bool ok, String code})> _submitInheritanceCredentials({
    required int linkId,
    required String username,
    required String pin,
    required bool isUpdate,
  }) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) {
      vlog('inheritance.cred.save.no_session', {'link_id': linkId});
      return (ok: false, code: 'INH-CRED-CLIENT-NO-SESSION');
    }
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);

      // 1. Fetch the beneficiary's X25519 public key.
      final pkResp = await client.getInheritanceBeneficiaryPubKey(
        linkId: linkId,
        authToken: token,
      );
      final pkB64 = pkResp['pk_vault_public_b64url']?.toString();
      if (pkB64 == null || pkB64.isEmpty) {
        vlog('inheritance.cred.save.no_pk', {'link_id': linkId});
        return (ok: false, code: 'INH-CRED-CLIENT-NO-PUBKEY');
      }
      // Base64url decode with padding forgiveness.
      final padded = pkB64 + '=' * ((4 - pkB64.length % 4) % 4);
      final pk = base64Url.decode(padded);

      // 2. Encrypt the credential package client-side.
      final pkg = await inh_cred.encryptInheritanceCredentials(
        username: username,
        pin: pin,
        beneficiaryPkVaultPublic: pk,
      );

      // 3. POST wrapped material.
      final body = pkg.toRequestBody(beneficiaryLinkId: linkId);
      if (isUpdate) {
        await client.replaceInheritanceCredentials(
            body: body, authToken: token);
      } else {
        await client.saveInheritanceCredentials(body: body, authToken: token);
      }
      _showSnack(isUpdate ? 'Credentials updated' : 'Credentials saved');
      return (ok: true, code: '');
    } on InheritanceCredSaveException catch (e) {
      // Backend-side failure that carried a parseable INH-CRED-* code.
      vlog('inheritance.cred.save.backend_error', {
        'link_id': linkId,
        'status': e.statusCode,
        'backend_code': e.backendCode,
      });
      if (app.handleApiException(e)) {
        return (ok: false, code: 'INH-CRED-CLIENT-AUTH');
      }
      return (
        ok: false,
        code: e.backendCode ?? 'INH-CRED-CLIENT-UNKNOWN',
      );
    } on FormatException catch (e) {
      // Malformed base64 from the pubkey response, or a bad JSON
      // body decode. Purely client-side.
      vlog('inheritance.cred.save.client_format_error', {
        'link_id': linkId,
        'error': e.toString(),
      });
      return (ok: false, code: 'INH-CRED-CLIENT-CRYPTO');
    } on ArgumentError catch (e) {
      // Thrown by encryptInheritanceCredentials when the decoded
      // beneficiary pubkey is not 32 bytes, or by the cryptography
      // package for a key/seed length mismatch. Client-side only.
      vlog('inheritance.cred.save.client_argument_error', {
        'link_id': linkId,
        'error': e.toString(),
      });
      return (ok: false, code: 'INH-CRED-CLIENT-CRYPTO');
    } on StateError catch (e) {
      // Post-decrypt / post-encrypt structural failure in the
      // cryptography package. Client-side only.
      vlog('inheritance.cred.save.client_state_error', {
        'link_id': linkId,
        'error': e.toString(),
      });
      return (ok: false, code: 'INH-CRED-CLIENT-CRYPTO');
    } catch (e) {
      // Network aborts, timeouts, TLS failures, DNS errors — all
      // travel as ClientException / SocketException from
      // package:http and never carry a backend code.
      final s = e.toString().toLowerCase();
      final isNetwork = s.contains('clientexception') ||
          s.contains('socketexception') ||
          s.contains('load failed') ||
          s.contains('failed to fetch') ||
          s.contains('aborted') ||
          s.contains('cancelled') ||
          s.contains('canceled') ||
          s.contains('network is offline') ||
          s.contains('network request failed');
      vlog('inheritance.cred.save.failed', {
        'link_id': linkId,
        'error': e.toString(),
        'network_abort': isNetwork,
      });
      if (app.handleApiException(e)) {
        return (ok: false, code: 'INH-CRED-CLIENT-AUTH');
      }
      return (
        ok: false,
        code: isNetwork ? 'INH-CRED-CLIENT-NETWORK' : 'INH-CRED-CLIENT-UNKNOWN',
      );
    }
  }

  Future<void> _deleteInheritanceCredentials({
    required int linkId,
    required String beneficiaryLabel,
  }) async {
    final app = context.read<AppState>();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text(
          'Delete credentials for $beneficiaryLabel?',
        ),
        content: const Text(
          'The encrypted username and PIN will be permanently removed. '
          'They can be re-added later.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogCtx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
            onPressed: () => Navigator.pop(dialogCtx, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final token = app.sessionToken;
    if (token == null) return;
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      await client.deleteInheritanceCredentials(
        linkId: linkId,
        authToken: token,
      );
      _showSnack('Credentials deleted');
      await _loadBeneficiaries();
    } on InheritanceCredSaveException catch (e) {
      // 2026-07-22: surface the ACTUAL backend code (e.g.
      // INH-CRED-007 when the caller tried to delete a link that is
      // mid-cooldown) instead of the hardcoded INH-CRED-006 the UI
      // used to show for every failure mode.
      vlog('inheritance.cred.delete.failed', {
        'link_id': linkId,
        'status': e.statusCode,
        'backend_code': e.backendCode,
      });
      if (app.handleApiException(e)) return;
      final code = (e.backendCode == null || e.backendCode!.isEmpty)
          ? 'INH-CRED-CLIENT-UNKNOWN'
          : e.backendCode!;
      _showSnack(
        'Could not delete credentials.\nReference: $code',
      );
    } catch (e) {
      vlog('inheritance.cred.delete.failed', {'error': e.toString()});
      if (app.handleApiException(e)) return;
      _showSnack(
        'Could not delete credentials.\nReference: INH-CRED-CLIENT-UNKNOWN',
      );
    }
  }

  String _beneficiaryStateLabel({
    required String pairingState,
    required bool credentialsSaved,
    required String legacyStatus,
  }) {
    switch (pairingState) {
      case 'credentials_saved':
        return 'Credentials secured';
      case 'cooldown_active':
        return 'Access requested';
      case 'claimable':
        return 'Access available';
      case 'approved':
        return 'Access approved';
      case 'released':
        return 'Access granted';
      case 'needs_reencryption':
        return 'Owner update required';
      case 'revoked':
        return 'Revoked';
      case 'rejected':
        return 'Request rejected';
      case 'paired_no_credentials':
        if (legacyStatus == 'transfer_pending') return 'Transfer pending';
        if (legacyStatus == 'linked') return 'Linked';
        return 'Waiting for credentials';
    }
    return legacyStatus.isEmpty ? 'Linked' : legacyStatus;
  }

  Color _beneficiaryStateColor(String pairingState) {
    switch (pairingState) {
      case 'released':
      case 'approved':
      case 'claimable':
        return const Color(0xFF10A37F);
      case 'cooldown_active':
      case 'needs_reencryption':
        return Colors.orange;
      case 'revoked':
      case 'rejected':
        return Colors.redAccent;
      default:
        return const Color(0xFFB4B4B4);
    }
  }

  bool _constantTimeStringEquals(String a, String b) {
    if (a.length != b.length) return false;
    int diff = 0;
    for (int i = 0; i < a.length; i++) {
      diff |= a.codeUnitAt(i) ^ b.codeUnitAt(i);
    }
    return diff == 0;
  }

// ---------------------------------------------------------------------
// Phase 2 — release-flow helpers (approve / reject / request /
// cancel / claim / reveal).
//
// Each helper wraps a single API call, refreshes the two dashboard
// lists, and surfaces safe operator-readable messages. The reveal
// helper additionally requires a local PIN reauth before showing
// plaintext credentials on screen.
// ---------------------------------------------------------------------

  Future<void> _ownerApproveInheritance({
    required int linkId,
    required String beneficiaryLabel,
  }) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dCtx) => AlertDialog(
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text('Approve $beneficiaryLabel?'),
        content: const Text(
          'Approving will permanently release the saved SVaultAI '
          'username and PIN to this beneficiary. This cannot be '
          'undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dCtx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dCtx, true),
            child: const Text('Approve now'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await VaultAIClient(baseUrl: backendBaseUrl)
          .approveInheritanceAccess(linkId: linkId, authToken: token);
      _showSnack('Approved $beneficiaryLabel');
      await _loadBeneficiaries();
    } catch (e) {
      vlog('inheritance.access.approve.failed', {'error': e.toString()});
      if (app.handleApiException(e)) return;
      _showSnack(
        'Could not approve the request.\nReference: INH-ACCESS-005',
      );
    }
  }

  Future<void> _ownerRejectInheritance({
    required int linkId,
    required String beneficiaryLabel,
  }) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dCtx) => AlertDialog(
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text('Reject request from $beneficiaryLabel?'),
        content: const Text(
          'The saved credentials remain safe. The beneficiary can '
          'request access again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dCtx, false),
            child: const Text('Keep pending'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
            onPressed: () => Navigator.pop(dCtx, true),
            child: const Text('Reject'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await VaultAIClient(baseUrl: backendBaseUrl)
          .rejectInheritanceAccess(linkId: linkId, authToken: token);
      _showSnack('Rejected request');
      await _loadBeneficiaries();
    } catch (e) {
      vlog('inheritance.access.reject.failed', {'error': e.toString()});
      if (app.handleApiException(e)) return;
      _showSnack(
        'Could not reject the request.\nReference: INH-ACCESS-005',
      );
    }
  }

  Future<void> _beneficiaryRequestAccess({
    required int linkId,
    required String passerLabel,
  }) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dCtx) => AlertDialog(
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text('Request access to $passerLabel?'),
        content: const Text(
          'The owner will be notified and can approve or reject. '
          'Without a response, access becomes available after 30 '
          'days.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dCtx, false),
            child: const Text('Cancel'),
          ),
          FilledButton.icon(
            icon: const Icon(Icons.lock_outline),
            onPressed: () => Navigator.pop(dCtx, true),
            label: const Text('Request access'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await VaultAIClient(baseUrl: backendBaseUrl)
          .requestInheritanceAccess(linkId: linkId, authToken: token);
      _showSnack('Access requested');
      await _loadInheritances();
    } catch (e) {
      vlog('inheritance.access.request.failed', {'error': e.toString()});
      if (app.handleApiException(e)) return;
      _showSnack(
        'Could not request access.\nReference: INH-ACCESS-003',
      );
    }
  }

  Future<void> _beneficiaryCancelAccess({
    required int linkId,
    required String passerLabel,
  }) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) return;
    try {
      await VaultAIClient(baseUrl: backendBaseUrl)
          .cancelInheritanceAccess(linkId: linkId, authToken: token);
      _showSnack('Request cancelled');
      await _loadInheritances();
    } catch (e) {
      vlog('inheritance.access.cancel.failed', {'error': e.toString()});
      if (app.handleApiException(e)) return;
      _showSnack('Could not cancel.\nReference: INH-ACCESS-005');
    }
  }

  Future<void> _beneficiaryClaimAccess({
    required int linkId,
    required String passerLabel,
  }) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) return;
    try {
      await VaultAIClient(baseUrl: backendBaseUrl)
          .claimInheritanceAccess(linkId: linkId, authToken: token);
      await _loadInheritances();
      // Straight into reveal after successful claim.
      await _beneficiaryRevealCredentials(
        linkId: linkId,
        passerLabel: passerLabel,
      );
    } catch (e) {
      vlog('inheritance.access.claim.failed', {'error': e.toString()});
      if (app.handleApiException(e)) return;
      _showSnack(
        'Could not claim yet — check the countdown.'
        '\nReference: INH-CLAIM-001',
      );
    }
  }

  Future<void> _beneficiaryRevealCredentials({
    required int linkId,
    required String passerLabel,
  }) async {
    // 1. Require the beneficiary's own PIN before showing anything.
    final pin = await _promptForReauthPin(title: 'Reveal $passerLabel');
    if (pin == null) return;
    final app = context.read<AppState>();
    if (app.sessionToken == null) return;
    final vaultId = app.vaultId;
    if (vaultId == null || vaultId.isEmpty) {
      _showSnack('Session expired. Please sign in again.');
      return;
    }
    inheritanceRevealDiag('local_key_begin', {
      'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
      'active_sk_present': zk_sk_store.ZkActiveSkVault.current() != null,
      'active_sk_vault_match':
          zk_sk_store.ZkActiveSkVault.currentVaultId() == vaultId,
      'has_vault_name': _nonEmptyTrimmed(app.vaultName) != null,
      'has_last_vault_name': _nonEmptyTrimmed(app.lastVaultName) != null,
      'has_vault_handle': _nonEmptyTrimmed(app.vaultHandle) != null,
    });

    // Resolve the beneficiary's local X25519 key before fetching the
    // encrypted package. Wrong PINs and missing/corrupt local keys
    // fail closed without asking the backend for ciphertext.
    InheritanceRevealLocalKeyResult localKey;
    try {
      localKey = await resolveInheritanceRevealLocalKey(
        vaultId: vaultId,
        pin: pin,
        cachedPinMatches: _inheritanceCachedPinMatches,
        unlockWithPin: (candidatePin) => app.verifyPin(
          candidatePin,
          restoreZkSessionKeys: true,
        ),
        currentSk: () => _activeInheritanceSkForVault(vaultId),
        currentSkVaultId: zk_sk_store.ZkActiveSkVault.currentVaultId,
        rehydrateSkWithPin: (candidatePin) => _rehydrateInheritanceSkVault(
          app: app,
          expectedVaultId: vaultId,
          pin: candidatePin,
        ),
      );
    } catch (e) {
      if (app.handleApiException(e)) return;
      inheritanceRevealDiag('local_key_exception', {
        'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
        'exception_type': e.runtimeType.toString(),
      });
      vlog('inheritance.reveal.local_key_failed', {
        'exception_type': e.runtimeType.toString(),
      });
      _showSnack(
        'Could not unlock inherited credentials on this device. '
        'Enter your PIN again to continue.',
      );
      return;
    }
    inheritanceRevealDiag('local_key_result', {
      'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
      'status': localKey.status.name,
      'reason': localKey.reason,
    });
    switch (localKey.status) {
      case InheritanceRevealLocalKeyStatus.invalidPin:
        _showSnack('PIN did not match. Try again.');
        return;
      case InheritanceRevealLocalKeyStatus.missingLocalKey:
        ZkRepairResult? repair;
        try {
          repair = await _repairInheritanceZkAfterPin(
            app: app,
            vaultId: vaultId,
            pin: pin,
          );
        } catch (e) {
          if (app.handleApiException(e)) return;
          inheritanceRevealDiag('repair_exception', {
            'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
            'exception_type': e.runtimeType.toString(),
          });
        }
        if (repair == null) {
          _showSnack(
            'Could not restore this device\'s inheritance key. '
            'Unlock this beneficiary vault with your PIN, then try Reveal again.',
          );
          return;
        }
        if (repair.requiresOwnerReencryption) {
          _showSnack(
            'This device could not recover the old inheritance key. '
            'I repaired this beneficiary vault with a new key, but the owner '
            'must update the saved credentials before you can reveal them.',
          );
          await _loadInheritances();
          await _loadBeneficiaries();
          return;
        }
        localKey = InheritanceRevealLocalKeyResult.ready(
          repair.skVaultPrivate,
          reason: 'repair_preserved_sk_ready',
        );
        break;
      case InheritanceRevealLocalKeyStatus.ready:
        break;
    }

    if (localKey.skVault != null &&
        (localKey.reason == 'active_sk_ready' ||
            localKey.reason == 'active_sk_ready_after_rehydrate')) {
      try {
        final repair = await _repairInheritanceZkAfterPin(
          app: app,
          vaultId: vaultId,
          pin: pin,
          existingSkVault: localKey.skVault,
        );
        if (repair != null && repair.preservedExistingKey) {
          localKey = InheritanceRevealLocalKeyResult.ready(
            repair.skVaultPrivate,
            reason: 'repair_preserved_existing_sk',
          );
        }
      } catch (e) {
        inheritanceRevealDiag('repair_preserve_failed_non_blocking', {
          'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
          'exception_type': e.runtimeType.toString(),
        });
      }
    }

    // 2. Load the wrapped package.
    final token = app.sessionToken;
    if (token == null) return;
    Map<String, dynamic> pkg;
    try {
      pkg = await VaultAIClient(baseUrl: backendBaseUrl)
          .retrieveInheritanceCredentials(
        linkId: linkId,
        authToken: token,
      );
    } catch (e) {
      vlog('inheritance.reveal.retrieve_failed', {'error': e.toString()});
      if (app.handleApiException(e)) return;
      _showSnack(
        'Could not fetch credentials.\nReference: INH-RETRIEVE-001',
      );
      return;
    }

    // 3. Stage-complete decrypt.
    //
    // 2026-07-23: reveal now runs entirely inside
    // ``revealInheritanceCredentialsStaged``. Every one of the nine
    // decrypt stages is separately wrapped so any failure surfaces
    // as ``InheritanceRevealStageException(stage: <NAME>)``. The
    // defensive outer catch below guarantees that ANYTHING that
    // escapes gets a stage of ``UNSTAGED_UNKNOWN`` — the operator
    // will never see ``stage=None`` again.
    inh_cred.DecryptedInheritanceCredentials? decrypted;
    Object? stagedError;
    StackTrace? stagedStack;
    try {
      decrypted = await inh_cred.revealInheritanceCredentialsStaged(
        beneficiarySkVault: localKey.skVault!,
        rawPackage: pkg,
      );
    } catch (e, st) {
      // Anything that isn't already staged (should be nothing) gets
      // wrapped as UNSTAGED_UNKNOWN. If we ever see this stage in
      // production logs it means the wrapper has a hole to fix.
      if (e is inh_cred.InheritanceRevealStageException) {
        stagedError = e;
      } else {
        stagedError = inh_cred.InheritanceRevealStageException(
          stage: inh_cred.kRevealStageUnstagedUnknown,
          cause: e,
          causeStackTrace: st,
        );
      }
      stagedStack = st;
    }

    if (stagedError != null) {
      final ref = inh_classify.classifyRevealException(stagedError);
      final safeLens = inh_classify.safeLengthsFromRawPkg(pkg);
      final category = inh_classify.revealCategoryFor(ref);
      vlog('inheritance.reveal.decrypt_failed', {
        'ref': ref,
        // 2026-07-23: stage is guaranteed non-null. If the staged
        // wrapper somehow missed a code path, we surface the
        // ``kRevealStageUnstagedUnknown`` sentinel — never
        // ``stage=None``.
        'stage': inh_classify.revealStageOf(stagedError) ??
            inh_cred.kRevealStageUnstagedUnknown,
        'link_id': linkId,
        'exception_type': stagedError.runtimeType.toString(),
      });
      unawaited(VaultAIClient(baseUrl: backendBaseUrl)
          .postInheritanceClientDiagnostic(
        authToken: token,
        body: {
          'area': 'reveal',
          'reference_code': ref,
          'stage': inh_classify.revealStageOf(stagedError) ??
              inh_cred.kRevealStageUnstagedUnknown,
          'link_id': linkId,
          'exception_type': stagedError.runtimeType.toString(),
          'category': category,
          'crypto_version': safeLens['crypto_version'],
          'encrypted_payload_len': safeLens['encrypted_payload_len'],
          'payload_nonce_len': safeLens['payload_nonce_len'],
          'wrapped_key_len': safeLens['wrapped_key_len'],
          'wrapping_ephemeral_pk_len': safeLens['wrapping_ephemeral_pk_len'],
          'wrapping_nonce_len': safeLens['wrapping_nonce_len'],
          'active_sk_present': true,
          // sk_len is 32 for every ZK-adopted account (X25519 seed).
          // We report the SPEC value here rather than re-extracting
          // the sk bytes just to measure them — the LOAD_SECRET_KEY
          // stage already length-checks the actual seed.
          'active_sk_len': inh_cred.kExpectedSkVaultLen,
          // Expected wire lengths per crypto_version=1 so the
          // operator can compare actual vs expected inline.
          ...inh_classify.expectedLengthsForCryptoVersionOne(),
        },
      ));
      // stagedStack is captured for local `flutter run` debugging
      // only. It never leaves the device — stack traces on Web
      // include minified symbol names but can still identify user
      // code paths, so nothing is wired to the diagnostic body
      // beyond the safe fields above.
      // ignore: unnecessary_null_comparison
      final _ = stagedStack;
      _showSnack(
        '${inh_classify.userMessageForReveal(ref)}\n'
        'Reference: $ref',
      );
      return;
    }

    if (!mounted) return;
    await _showRevealedCredentialsDialog(
      passerLabel: passerLabel,
      username: decrypted!.username,
      pin: decrypted.pin,
      linkId: linkId,
      token: token,
    );
    await _loadInheritances();
  }

  Future<bool?> _inheritanceCachedPinMatches(String pin) async {
    try {
      final cached = await _VaultCrypto.currentPinOrThrow();
      final matches =
          cached.length == pin.length && _constantTimeStringEquals(cached, pin);
      inheritanceRevealDiag(matches ? 'pin_cache_match' : 'pin_cache_mismatch');
      return matches;
    } catch (_) {
      inheritanceRevealDiag('pin_cache_absent');
      return null;
    }
  }

  SecretKey? _activeInheritanceSkForVault(String vaultId) {
    if (zk_sk_store.ZkActiveSkVault.currentVaultId() != vaultId) {
      return null;
    }
    return zk_sk_store.ZkActiveSkVault.current();
  }

  Future<SecretKey> _inheritanceRepairMvkFor({
    required String vaultId,
  }) async {
    final activeMvk = zk_mvk_store.ZkActiveMvk.current();
    if (activeMvk != null &&
        zk_mvk_store.ZkActiveMvk.currentVaultId() == vaultId) {
      return activeMvk;
    }
    final activeContext = VaultCryptoRegistry.current;
    if (activeContext != null && activeContext.vaultId == vaultId) {
      return activeContext.key;
    }
    if (_VaultCrypto._activeVaultId == vaultId) {
      return _VaultCrypto._requireActiveKey();
    }
    throw const InvalidVaultUnlockException();
  }

  Future<ZkRepairResult?> _repairInheritanceZkAfterPin({
    required AppState app,
    required String vaultId,
    required String pin,
    SecretKey? existingSkVault,
  }) async {
    final pinVerified = await app.verifyPin(
      pin,
      restoreZkSessionKeys: false,
    );
    if (!pinVerified) {
      inheritanceRevealDiag('repair_pin_rejected', {
        'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
      });
      return null;
    }
    final token = app.sessionToken;
    final handle = _nonEmptyTrimmed(app.vaultHandle);
    if (token == null || token.isEmpty || handle == null) {
      inheritanceRevealDiag('repair_missing_session_or_handle', {
        'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
        'has_token': token != null && token.isNotEmpty,
        'has_vault_handle': handle != null,
      });
      return null;
    }
    final mvk = await _inheritanceRepairMvkFor(vaultId: vaultId);
    final display = _nonEmptyTrimmed(app.displayName) ??
        _nonEmptyTrimmed(app.vaultName) ??
        _nonEmptyTrimmed(app.lastVaultName) ??
        'SVaultAI';
    final repair = await ZkAuthService(_zkHttpPost).repairVaultOpaqueRecord(
      vaultHandle: handle,
      pin: pin,
      mvk: mvk,
      displayName: display,
      currentSessionToken: token,
      existingSkVaultPrivate: existingSkVault,
    );
    if (repair.vaultId != vaultId) {
      inheritanceRevealDiag('repair_vault_mismatch', {
        'expected_vault_fpr': inheritanceRevealIdFingerprint(vaultId),
        'actual_vault_fpr': inheritanceRevealIdFingerprint(repair.vaultId),
      });
      return null;
    }
    zk_mvk_store.ZkActiveMvk.set(
      mvk: repair.mvk,
      vaultId: repair.vaultId,
      vaultHandle: repair.vaultHandle,
    );
    zk_sk_store.ZkActiveSkVault.set(
      skVault: repair.skVaultPrivate,
      vaultId: repair.vaultId,
    );
    inheritanceRevealDiag('repair_success', {
      'vault_fpr': inheritanceRevealIdFingerprint(vaultId),
      'branch': repair.branch,
      'requires_owner_reencryption': repair.requiresOwnerReencryption,
      'reencryption_required_count': repair.reencryptionRequiredCount,
    });
    return repair;
  }

  Future<SecretKey?> _rehydrateInheritanceSkVault({
    required AppState app,
    required String expectedVaultId,
    required String pin,
  }) async {
    final cachedAdoptedHandle = await legacy_adopt.readCachedVaultHandle();
    final loginId = selectInheritanceRevealLoginIdentifier(
      vaultName: app.vaultName,
      lastVaultName: app.lastVaultName,
      vaultHandle: _nonEmptyTrimmed(app.vaultHandle) ?? cachedAdoptedHandle,
    );
    if (!loginId.hasIdentifier) {
      inheritanceRevealDiag('rehydrate_no_identifier', {
        'expected_vault_fpr': inheritanceRevealIdFingerprint(expectedVaultId),
        'expected_role': 'beneficiary',
      });
      return null;
    }
    inheritanceRevealDiag('rehydrate_attempt', {
      'expected_vault_fpr': inheritanceRevealIdFingerprint(expectedVaultId),
      'expected_role': 'beneficiary',
      'id_source': loginId.source,
      'uses_handle': loginId.vaultHandle != null,
      'uses_name': loginId.vaultName != null,
    });

    String lastStep = 'begin';
    try {
      final zk = ZkAuthService(_zkHttpPost);
      final loginResult = await zk.loginVault(
        vaultName: loginId.vaultName,
        vaultHandle: loginId.vaultHandle,
        pin: pin,
        onStep: (step) => lastStep = step,
      );
      if (loginResult.vaultId != expectedVaultId) {
        inheritanceRevealDiag('rehydrate_vault_mismatch', {
          'expected_vault_fpr': inheritanceRevealIdFingerprint(expectedVaultId),
          'actual_vault_fpr':
              inheritanceRevealIdFingerprint(loginResult.vaultId),
          'expected_role': 'beneficiary',
          'id_source': loginId.source,
        });
        vlog('inheritance.reveal.rehydrate_vault_mismatch', {
          'expected_vault_fpr': inheritanceRevealIdFingerprint(expectedVaultId),
          'actual_vault_fpr':
              inheritanceRevealIdFingerprint(loginResult.vaultId),
        });
        return null;
      }

      final resolvedVaultName = _nonEmptyTrimmed(loginResult.vaultName) ??
          loginId.vaultName ??
          _nonEmptyTrimmed(app.vaultName) ??
          _nonEmptyTrimmed(app.lastVaultName) ??
          _nonEmptyTrimmed(loginResult.displayName) ??
          loginResult.vaultHandle;

      await app.setSession(
        token: loginResult.sessionToken,
        vaultIdValue: loginResult.vaultId,
        vaultNameValue: resolvedVaultName,
        vaultHandleValue: loginResult.vaultHandle,
        displayNameValue: loginResult.displayName,
      );
      await _registerDeviceBestEffort(loginResult.sessionToken);
      await _autoConsumeInheritanceTokenIfPresent(
        loginResult.sessionToken,
        app,
      );

      _VaultCrypto._keyCache[
              _VaultCrypto._ck(loginResult.vaultId, resolvedVaultName)] =
          loginResult.mvk;
      _VaultCrypto._pinCache[
          _VaultCrypto._ck(loginResult.vaultId, resolvedVaultName)] = pin;
      _VaultCrypto.setActiveVault(
        vaultId: loginResult.vaultId,
        vaultName: resolvedVaultName,
      );
      zk_mvk_store.ZkActiveMvk.set(
        mvk: loginResult.mvk,
        vaultId: loginResult.vaultId,
        vaultHandle: loginResult.vaultHandle,
      );
      zk_sk_store.ZkActiveSkVault.set(
        skVault: loginResult.skVaultPrivate,
        vaultId: loginResult.vaultId,
      );

      try {
        final vaultMeta = await _API.getVaultMeta(
          vaultName: resolvedVaultName,
          authToken: loginResult.sessionToken,
        );
        final pinSalt = vaultMeta['pin_salt']?.toString();
        final iterations = (vaultMeta['kdf_iterations'] as num?)?.toInt();
        if (pinSalt != null && pinSalt.isNotEmpty && iterations != null) {
          await deriveAndInstallCryptoContext(
            vaultId: loginResult.vaultId,
            vaultName: resolvedVaultName,
            pin: pin,
            pinSaltBase64: pinSalt,
            iterations: iterations,
            source: 'inheritance_reveal_reauth',
          );
        }
      } catch (e) {
        vlog('inheritance.reveal.rehydrate_pbkdf2_failed', {
          'exception_type': e.runtimeType.toString(),
        });
      }

      app.markUnlocked();
      inheritanceRevealDiag('rehydrate_success', {
        'vault_fpr': inheritanceRevealIdFingerprint(loginResult.vaultId),
        'expected_role': 'beneficiary',
        'id_source': loginId.source,
        'active_sk_present': zk_sk_store.ZkActiveSkVault.current() != null,
        'active_sk_vault_match':
            zk_sk_store.ZkActiveSkVault.currentVaultId() == expectedVaultId,
      });
      return loginResult.skVaultPrivate;
    } on OpaqueAuthenticationFailed catch (e) {
      inheritanceRevealDiag('rehydrate_opaque_failed', {
        'stage': e.stage,
        'last_step': lastStep,
        'expected_role': 'beneficiary',
        'id_source': loginId.source,
      });
      vlog('inheritance.reveal.rehydrate_opaque_failed', {
        'stage': e.stage,
        'last_step': lastStep,
      });
      return null;
    } catch (e) {
      inheritanceRevealDiag('rehydrate_failed', {
        'exception_type': e.runtimeType.toString(),
        'last_step': lastStep,
        'expected_role': 'beneficiary',
        'id_source': loginId.source,
      });
      vlog('inheritance.reveal.rehydrate_failed', {
        'exception_type': e.runtimeType.toString(),
        'last_step': lastStep,
      });
      return null;
    }
  }

  Future<String?> _promptForReauthPin({required String title}) async {
    final ctrl = TextEditingController();
    final formKey = GlobalKey<FormState>();
    final result = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (dCtx) => AlertDialog(
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text(title),
        content: Form(
          key: formKey,
          child: TextFormField(
            key: const Key('inheritance_reveal_reauth_pin_field'),
            controller: ctrl,
            obscureText: true,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              hintText: 'Enter your SVaultAI PIN',
              isDense: true,
            ),
            validator: (v) =>
                (v == null || v.trim().length < 4) ? 'PIN is too short' : null,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dCtx, null),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (!(formKey.currentState?.validate() ?? false)) return;
              Navigator.pop(dCtx, ctrl.text.trim());
            },
            child: const Text('Continue'),
          ),
        ],
      ),
    );
    ctrl.dispose();
    return result;
  }

  Future<void> _showRevealedCredentialsDialog({
    required String passerLabel,
    required String username,
    required String pin,
    required int linkId,
    required String token,
  }) async {
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dCtx) => AlertDialog(
        key: const Key('inheritance_revealed_dialog'),
        backgroundColor: const Color(0xFF2F2F2F),
        title: Text('Inherited SVaultAI login: $passerLabel'),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'These credentials provide access to the owner\'s '
                'original SVaultAI account. Keep them private.',
                style: TextStyle(
                  color: Color(0xFFFFA726),
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                'Username',
                style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 12),
              ),
              SelectableText(
                username,
                key: const Key('inheritance_revealed_username'),
                style: const TextStyle(fontSize: 16),
              ),
              const SizedBox(height: 12),
              const Text(
                'PIN',
                style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 12),
              ),
              SelectableText(
                pin,
                key: const Key('inheritance_revealed_pin'),
                style: const TextStyle(fontSize: 16, fontFeatures: [
                  FontFeature.tabularFigures(),
                ]),
              ),
              const SizedBox(height: 14),
              const Text(
                'Clipboard contents may be accessible to other apps. '
                'Copy carefully.',
                style: TextStyle(color: Color(0xFFB4B4B4), fontSize: 11),
              ),
            ],
          ),
        ),
        actions: [
          OutlinedButton.icon(
            key: const Key('inheritance_revealed_copy_username'),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: username));
              _showSnack('Username copied');
            },
            icon: const Icon(Icons.copy, size: 18),
            label: const Text('Copy username'),
          ),
          OutlinedButton.icon(
            key: const Key('inheritance_revealed_copy_pin'),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: pin));
              _showSnack('PIN copied');
            },
            icon: const Icon(Icons.copy, size: 18),
            label: const Text('Copy PIN'),
          ),
          FilledButton.icon(
            key: const Key('inheritance_revealed_continue'),
            onPressed: () async {
              Navigator.pop(dCtx);
              await _beneficiaryContinueToInheritedAccount(
                linkId: linkId,
                authToken: token,
              );
            },
            icon: const Icon(Icons.login),
            label: const Text('Continue to inherited account'),
          ),
        ],
      ),
    );
    // Best-effort: clear the clipboard after 60 s. Not all platforms
    // honor this; log it and move on. We intentionally do NOT claim
    // 100% clipboard clearing.
    Future.delayed(const Duration(seconds: 60), () async {
      try {
        await Clipboard.setData(const ClipboardData(text: ''));
      } catch (_) {}
    });
  }

  Future<void> _beneficiaryContinueToInheritedAccount({
    required int linkId,
    required String authToken,
  }) async {
    // Fire a one-time inheritance-scoped device enrollment token so
    // the very next login on the inherited account can convert this
    // device from pending → trusted automatically. The token is
    // held in ``AppState.pendingInheritanceDeviceToken`` and consumed
    // by ``_autoConsumeInheritanceTokenIfPresent`` immediately after
    // the next successful login (see the register+consume pair at
    // every login site).
    try {
      final resp = await VaultAIClient(baseUrl: backendBaseUrl)
          .authorizeInheritanceDevice(
        linkId: linkId,
        authToken: authToken,
      );
      final token = resp['token']?.toString();
      if (token != null && token.isNotEmpty) {
        final app = context.read<AppState>();
        app.pendingInheritanceDeviceToken = token;
      }
    } catch (e) {
      vlog('inheritance.device.authorize.failed', {'error': e.toString()});
    }
    _showSnack(
      'Sign in with the inherited username and PIN — this device '
      'will be enrolled automatically.',
    );
  }

  Widget _buildInheritanceSection(bool isMobile) {
    if (!_inheritanceLoadedOnce) {
      _inheritanceLoadedOnce = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _loadBeneficiaries();
        _loadInheritances();
      });
    }

    String statusLabel(Map<String, dynamic> row) {
      final status = (row['status'] ?? '').toString();
      switch (status) {
        case 'pairing_pending':
          return 'Awaiting beneficiary';
        case 'linked':
          return 'Linked';
        case 'transfer_pending':
          return 'Transfer pending (30-day countdown)';
        case 'transferred':
          return 'Transferred';
        case 'cancelled':
          return 'Cancelled';
        default:
          return status;
      }
    }

    Color statusColor(String status) {
      switch (status) {
        case 'pairing_pending':
          return Colors.amber;
        case 'linked':
          return const Color(0xFF10A37F);
        case 'transfer_pending':
          return Colors.orange;
        case 'transferred':
          return Colors.blueAccent;
        default:
          return const Color(0xFFB4B4B4);
      }
    }

    final _vrInh = VaultResponsive.of(context);
    return SingleChildScrollView(
      padding: EdgeInsets.all(_vrInh.pageHorizontalPadding),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                padding: EdgeInsets.all(_vrInh.isMobile ? 16 : 24),
                decoration: BoxDecoration(
                  color: const Color(0xFF2F2F2F),
                  borderRadius:
                      BorderRadius.circular(_vrInh.isMobile ? 18 : 24),
                  border: Border.all(color: Colors.white10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(AppLocalizations.of(context).inheritanceTitle,
                        style: TextStyle(
                          fontSize: _vrInh.headingXlSize,
                          fontWeight: FontWeight.w800,
                        )),
                    SizedBox(height: _vrInh.isMobile ? 6 : 8),
                    Text(
                      'Designate who can inherit this vault if you can no longer access '
                      'it, and view vaults you\'re set up to inherit.',
                      style: TextStyle(
                        color: const Color(0xFFB4B4B4),
                        fontSize: _vrInh.isMobile ? 13 : 15,
                        height: 1.5,
                      ),
                    ),
                    if (context.watch<AppState>().availableVaults.length >
                        1) ...[
                      SizedBox(height: _vrInh.isMobile ? 10 : 14),
                      _VaultSwitcher(),
                    ],
                  ],
                ),
              ),
              SizedBox(height: _vrInh.sectionSpacing),
              Container(
                padding: EdgeInsets.all(_vrInh.cardInsetPadding),
                decoration: BoxDecoration(
                  color: const Color(0xFF2A2A2A),
                  borderRadius:
                      BorderRadius.circular(_vrInh.isMobile ? 16 : 20),
                  border: Border.all(color: Colors.white10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    ResponsiveActionBar(
                      heading: const Text(
                        'People I\'ve added',
                        style: TextStyle(
                            fontSize: 18, fontWeight: FontWeight.w700),
                      ),
                      actions: [
                        OutlinedButton.icon(
                          key: const Key('inheritance_refresh_button'),
                          onPressed: _loadBeneficiaries,
                          icon: const Icon(Icons.refresh, size: 18),
                          label: Text(
                            AppLocalizations.of(context).commonRefresh,
                          ),
                        ),
                        FilledButton.icon(
                          key: const Key('inheritance_add_beneficiary_button'),
                          onPressed: _showAddBeneficiaryDialog,
                          icon: const Icon(Icons.person_add_alt_1, size: 18),
                          label: Text(
                            AppLocalizations.of(context)
                                .inheritanceAddBeneficiary,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    if (loadingBeneficiaries)
                      const Center(
                          child: Padding(
                        padding: EdgeInsets.all(20),
                        child: CircularProgressIndicator(),
                      ))
                    else if (beneficiaries.isEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Text(
                          'No beneficiaries yet. Click "Add beneficiary" to generate a pairing code.',
                          style:
                              TextStyle(color: Color(0xFFB4B4B4), fontSize: 14),
                        ),
                      )
                    else
                      ...beneficiaries.map((b) {
                        final hasStoredLabel = b['has_stored_label'] == true;
                        final label = (b['label'] ??
                                (hasStoredLabel
                                    ? 'Encrypted label unavailable'
                                    : 'Unnamed'))
                            .toString();
                        final status = (b['status'] ?? '').toString();
                        final id = (b['id'] as num?)?.toInt() ?? 0;
                        final executesAt =
                            b['transfer_executes_at']?.toString();
                        final isTransferPending = status == 'transfer_pending';
                        final isLinked = b['is_linked'] == true;
                        final credentialsSaved = b['credentials_saved'] == true;
                        final credentialUpdatedAt =
                            b['credential_updated_at']?.toString();
                        // Phase 2 release-flow state — authoritative
                        // source is beneficiary_links.pairing_state
                        // from the server. The legacy transfer flow
                        // is hidden once the new escrow has produced
                        // any release-flow signal.
                        final pairingState =
                            (b['pairing_state'] ?? 'paired_no_credentials')
                                .toString();
                        final needsReencryption =
                            pairingState == 'needs_reencryption';
                        final cooldownEndsAt =
                            b['cooldown_ends_at']?.toString();
                        final accessRequested =
                            pairingState == 'cooldown_active' ||
                                pairingState == 'claimable';
                        final approved = pairingState == 'approved';
                        final released = pairingState == 'released';
                        final hideLegacyTransfer = credentialsSaved ||
                            accessRequested ||
                            approved ||
                            released;
                        return Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: isTransferPending
                                ? Colors.orange.withValues(alpha: 0.08)
                                : const Color(0xFF222222),
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(
                                color: isTransferPending
                                    ? Colors.orange
                                    : Colors.white10),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(label,
                                            style: const TextStyle(
                                                fontSize: 15,
                                                fontWeight: FontWeight.w700)),
                                        const SizedBox(height: 4),
                                        Text(
                                          statusLabel(b),
                                          style: TextStyle(
                                              color: statusColor(status),
                                              fontSize: 12),
                                        ),
                                        if (isTransferPending &&
                                            executesAt != null) ...[
                                          const SizedBox(height: 2),
                                          Text(
                                            _formatCountdown(executesAt),
                                            style: const TextStyle(
                                                color: Colors.orange,
                                                fontSize: 11),
                                          ),
                                        ],
                                      ],
                                    ),
                                  ),
                                  if (isTransferPending && !hideLegacyTransfer)
                                    FilledButton.icon(
                                      onPressed: () =>
                                          _cancelTransfer(id, label),
                                      style: FilledButton.styleFrom(
                                          backgroundColor: Colors.orange),
                                      icon: const Icon(Icons.cancel_outlined,
                                          size: 18),
                                      label: Text(
                                        AppLocalizations.of(context)
                                            .inheritanceCancelTransfer,
                                      ),
                                    ),
                                  IconButton(
                                    tooltip: 'Remove',
                                    onPressed: () =>
                                        _deleteBeneficiary(id, label),
                                    icon: const Icon(Icons.delete_outline,
                                        color: Colors.redAccent),
                                  ),
                                ],
                              ),
                              if (isLinked) ...[
                                const SizedBox(height: 10),
                                Container(
                                  key: Key('inheritance_credentials_row_$id'),
                                  padding: const EdgeInsets.all(10),
                                  decoration: BoxDecoration(
                                    color: const Color(0xFF1E1E1E),
                                    borderRadius: BorderRadius.circular(10),
                                    border: Border.all(color: Colors.white10),
                                  ),
                                  child: Wrap(
                                    spacing: 8,
                                    runSpacing: 6,
                                    crossAxisAlignment:
                                        WrapCrossAlignment.center,
                                    children: [
                                      Row(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          Icon(
                                            needsReencryption
                                                ? Icons.warning_amber_outlined
                                                : credentialsSaved
                                                    ? Icons.lock_outline
                                                    : Icons.lock_open_outlined,
                                            size: 16,
                                            color: needsReencryption
                                                ? Colors.orange
                                                : credentialsSaved
                                                    ? const Color(0xFF66BB6A)
                                                    : const Color(0xFFB4B4B4),
                                          ),
                                          const SizedBox(width: 6),
                                          Text(
                                            needsReencryption
                                                ? 'Inheritance credentials: Needs update'
                                                : credentialsSaved
                                                    ? 'Inheritance credentials: Saved'
                                                    : 'Inheritance credentials: Not saved',
                                            style: TextStyle(
                                              color: needsReencryption
                                                  ? Colors.orange
                                                  : credentialsSaved
                                                      ? const Color(0xFF66BB6A)
                                                      : const Color(0xFFB4B4B4),
                                              fontSize: 12,
                                            ),
                                          ),
                                          if (credentialsSaved &&
                                              credentialUpdatedAt != null &&
                                              credentialUpdatedAt
                                                  .isNotEmpty) ...[
                                            const SizedBox(width: 6),
                                            Text(
                                              '• Updated ${_shortDateFromIso(credentialUpdatedAt)}',
                                              style: const TextStyle(
                                                color: Color(0xFF8A8A8A),
                                                fontSize: 11,
                                              ),
                                            ),
                                          ],
                                        ],
                                      ),
                                      if (!credentialsSaved)
                                        FilledButton.icon(
                                          key: Key(
                                              'inheritance_add_credentials_$id'),
                                          onPressed: () =>
                                              _showInheritanceCredentialsDialog(
                                            linkId: id,
                                            beneficiaryLabel: label,
                                            isUpdate: false,
                                          ),
                                          icon: const Icon(
                                              Icons.add_moderator_outlined,
                                              size: 18),
                                          label: const Text('Add credentials'),
                                        )
                                      else ...[
                                        OutlinedButton.icon(
                                          key: Key(
                                              'inheritance_update_credentials_$id'),
                                          onPressed: () =>
                                              _showInheritanceCredentialsDialog(
                                            linkId: id,
                                            beneficiaryLabel: label,
                                            isUpdate: true,
                                          ),
                                          icon: const Icon(Icons.edit_outlined,
                                              size: 18),
                                          label: Text(needsReencryption
                                              ? 'Re-save credentials'
                                              : 'Update credentials'),
                                        ),
                                        OutlinedButton.icon(
                                          key: Key(
                                              'inheritance_delete_credentials_$id'),
                                          onPressed: () =>
                                              _deleteInheritanceCredentials(
                                            linkId: id,
                                            beneficiaryLabel: label,
                                          ),
                                          icon: const Icon(
                                              Icons.lock_open_outlined,
                                              size: 18,
                                              color: Colors.redAccent),
                                          label: const Text(
                                            'Delete credentials',
                                            style: TextStyle(
                                                color: Colors.redAccent),
                                          ),
                                        ),
                                      ],
                                    ],
                                  ),
                                ),
                                // Phase 2: owner-side release actions.
                                if (accessRequested) ...[
                                  const SizedBox(height: 10),
                                  Container(
                                    key: Key(
                                        'inheritance_owner_release_row_$id'),
                                    padding: const EdgeInsets.all(10),
                                    decoration: BoxDecoration(
                                      color: const Color(0xFF2A211E),
                                      borderRadius: BorderRadius.circular(10),
                                      border: Border.all(
                                          color: Colors.orange
                                              .withValues(alpha: 0.4)),
                                    ),
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        const Text(
                                          'Access requested',
                                          style: TextStyle(
                                            color: Color(0xFFFFA726),
                                            fontWeight: FontWeight.w700,
                                            fontSize: 13,
                                          ),
                                        ),
                                        if (cooldownEndsAt != null) ...[
                                          const SizedBox(height: 2),
                                          Text(
                                            'Available automatically in '
                                            '${_formatCountdown(cooldownEndsAt)}',
                                            style: const TextStyle(
                                              color: Color(0xFFB4B4B4),
                                              fontSize: 12,
                                            ),
                                          ),
                                        ],
                                        const SizedBox(height: 8),
                                        Wrap(
                                          spacing: 8,
                                          runSpacing: 6,
                                          children: [
                                            FilledButton.icon(
                                              key: Key(
                                                  'inheritance_owner_approve_$id'),
                                              onPressed: () =>
                                                  _ownerApproveInheritance(
                                                linkId: id,
                                                beneficiaryLabel: label,
                                              ),
                                              icon: const Icon(Icons.check,
                                                  size: 18),
                                              label: const Text('Approve now'),
                                            ),
                                            OutlinedButton.icon(
                                              key: Key(
                                                  'inheritance_owner_reject_$id'),
                                              onPressed: () =>
                                                  _ownerRejectInheritance(
                                                linkId: id,
                                                beneficiaryLabel: label,
                                              ),
                                              icon: const Icon(Icons.close,
                                                  size: 18,
                                                  color: Colors.redAccent),
                                              label: const Text(
                                                'Reject request',
                                                style: TextStyle(
                                                    color: Colors.redAccent),
                                              ),
                                            ),
                                          ],
                                        ),
                                      ],
                                    ),
                                  ),
                                ] else if (approved || released) ...[
                                  const SizedBox(height: 8),
                                  Text(
                                    released
                                        ? 'Access released'
                                        : 'Access approved',
                                    key: Key(
                                        'inheritance_owner_release_state_$id'),
                                    style: const TextStyle(
                                      color: Color(0xFF66BB6A),
                                      fontSize: 12,
                                    ),
                                  ),
                                ],
                              ],
                            ],
                          ),
                        );
                      }),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              Container(
                padding: EdgeInsets.all(_vrInh.cardInsetPadding),
                decoration: BoxDecoration(
                  color: const Color(0xFF2A2A2A),
                  borderRadius:
                      BorderRadius.circular(_vrInh.isMobile ? 16 : 20),
                  border: Border.all(color: Colors.white10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Same responsive pattern as "People I've added" above.
                    // On < 600dp the heading renders full-width and the
                    // buttons wrap below, so "Vaults I'll inherit" never gets
                    // squeezed into a one-char-per-line column.
                    ResponsiveActionBar(
                      heading: const Text(
                        'Vaults I\'ll inherit',
                        key: Key('inheritance_vaults_ill_inherit_heading'),
                        style: TextStyle(
                            fontSize: 18, fontWeight: FontWeight.w700),
                      ),
                      actions: [
                        OutlinedButton.icon(
                          key: const Key(
                              'inheritance_refresh_inheritances_button'),
                          onPressed: _loadInheritances,
                          icon: const Icon(Icons.refresh, size: 18),
                          label: Text(
                            AppLocalizations.of(context).commonRefresh,
                          ),
                        ),
                        FilledButton.icon(
                          key: const Key('inheritance_enter_code_button'),
                          onPressed: _showEnterPairingCodeDialog,
                          icon: const Icon(Icons.vpn_key),
                          label: Text(
                            AppLocalizations.of(context).inheritanceEnterCode,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    if (loadingInheritances)
                      const Center(
                          child: Padding(
                        padding: EdgeInsets.all(20),
                        child: CircularProgressIndicator(),
                      ))
                    else if (inheritances.isEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Text(
                          'No inheritances. Use "Enter code" if someone shared a pairing code with you.',
                          style:
                              TextStyle(color: Color(0xFFB4B4B4), fontSize: 14),
                        ),
                      )
                    else
                      ...inheritances.map((i) {
                        // 2026-07-23: prefer the passer_label the owner
                        // originally typed. For ZK-created pairings
                        // that column is NULL on the server (the
                        // plaintext is encrypted under the OWNER's
                        // metadataKey and the beneficiary cannot
                        // decrypt it), so fall back to the owner's
                        // chosen vault_name. Only render 'Unknown'
                        // when the backend genuinely has no usable
                        // identity for either field.
                        final label = (i['passer_label'] ??
                                i['owner_vault_name'] ??
                                'Unknown')
                            .toString();
                        final status = (i['status'] ?? '').toString();
                        final id = (i['id'] as num?)?.toInt() ?? 0;
                        final executesAt =
                            i['transfer_executes_at']?.toString();
                        final isLinked = status == 'linked';
                        final isPending = status == 'transfer_pending';
                        final readyToClaim = isPending &&
                            executesAt != null &&
                            DateTime.tryParse(executesAt)
                                    ?.isBefore(DateTime.now()) ==
                                true;

                        // Phase 2 escrow-flow state — authoritative
                        // source is the server's ``pairing_state``.
                        final pairingState =
                            (i['pairing_state'] ?? 'paired_no_credentials')
                                .toString();
                        final needsReencryption =
                            pairingState == 'needs_reencryption';
                        final credentialsSaved = i['credentials_saved'] == true;
                        final cooldownEndsAt =
                            i['cooldown_ends_at']?.toString();
                        final showRequest = credentialsSaved &&
                            pairingState == 'credentials_saved';
                        final showCancel = pairingState == 'cooldown_active';
                        final showClaim = pairingState == 'claimable' ||
                            (pairingState == 'cooldown_active' &&
                                cooldownEndsAt != null &&
                                (DateTime.tryParse(cooldownEndsAt)
                                        ?.isBefore(DateTime.now()) ==
                                    true));
                        final showReveal = pairingState == 'approved' ||
                            pairingState == 'released';
                        final showLegacyLinked = isLinked &&
                            !credentialsSaved &&
                            pairingState == 'paired_no_credentials';

                        return Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: showReveal
                                ? const Color(0xFF10A37F)
                                    .withValues(alpha: 0.08)
                                : (showClaim || readyToClaim)
                                    ? const Color(0xFF10A37F)
                                        .withValues(alpha: 0.08)
                                    : (showCancel || isPending)
                                        ? Colors.orange.withValues(alpha: 0.06)
                                        : const Color(0xFF222222),
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(
                                color: showReveal
                                    ? const Color(0xFF10A37F)
                                    : (showClaim || readyToClaim)
                                        ? const Color(0xFF10A37F)
                                        : (showCancel || isPending)
                                            ? Colors.orange
                                            : Colors.white10),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(label,
                                            style: const TextStyle(
                                                fontSize: 15,
                                                fontWeight: FontWeight.w700)),
                                        const SizedBox(height: 4),
                                        Text(
                                          _beneficiaryStateLabel(
                                            pairingState: pairingState,
                                            credentialsSaved: credentialsSaved,
                                            legacyStatus: status,
                                          ),
                                          style: TextStyle(
                                              color: _beneficiaryStateColor(
                                                  pairingState),
                                              fontSize: 12),
                                        ),
                                        if (showCancel &&
                                            cooldownEndsAt != null) ...[
                                          const SizedBox(height: 2),
                                          Text(
                                            'Available in ${_formatCountdown(cooldownEndsAt)}',
                                            style: const TextStyle(
                                                color: Color(0xFFB4B4B4),
                                                fontSize: 11),
                                          ),
                                        ] else if (needsReencryption) ...[
                                          const SizedBox(height: 2),
                                          const Text(
                                            'The owner needs to update these credentials for your repaired vault key.',
                                            style: TextStyle(
                                                color: Color(0xFFB4B4B4),
                                                fontSize: 11),
                                          ),
                                        ] else if (isPending &&
                                            executesAt != null &&
                                            !showCancel) ...[
                                          const SizedBox(height: 2),
                                          Text(
                                            _formatCountdown(executesAt),
                                            style: TextStyle(
                                                color: readyToClaim
                                                    ? const Color(0xFF10A37F)
                                                    : Colors.orange,
                                                fontSize: 11),
                                          ),
                                        ],
                                      ],
                                    ),
                                  ),
                                  if (showRequest)
                                    FilledButton.icon(
                                      key: Key(
                                          'inheritance_beneficiary_request_$id'),
                                      onPressed: () =>
                                          _beneficiaryRequestAccess(
                                        linkId: id,
                                        passerLabel: label,
                                      ),
                                      icon: const Icon(Icons.lock_outline,
                                          size: 18),
                                      label: const Text('Request access'),
                                    ),
                                  if (showCancel)
                                    OutlinedButton.icon(
                                      key: Key(
                                          'inheritance_beneficiary_cancel_$id'),
                                      onPressed: () => _beneficiaryCancelAccess(
                                        linkId: id,
                                        passerLabel: label,
                                      ),
                                      icon: const Icon(Icons.cancel_outlined,
                                          size: 18),
                                      label: const Text('Cancel request'),
                                    ),
                                  if (showClaim && !showReveal)
                                    FilledButton.icon(
                                      key: Key(
                                          'inheritance_beneficiary_claim_$id'),
                                      onPressed: () => _beneficiaryClaimAccess(
                                        linkId: id,
                                        passerLabel: label,
                                      ),
                                      icon: const Icon(Icons.download_done,
                                          size: 18),
                                      label: const Text('Claim and reveal'),
                                    ),
                                  if (showReveal)
                                    FilledButton.icon(
                                      key: Key(
                                          'inheritance_beneficiary_reveal_$id'),
                                      onPressed: () =>
                                          _beneficiaryRevealCredentials(
                                        linkId: id,
                                        passerLabel: label,
                                      ),
                                      icon: const Icon(Icons.visibility,
                                          size: 18),
                                      label: const Text(
                                          'Reveal login credentials'),
                                    ),
                                  if (showLegacyLinked)
                                    FilledButton.icon(
                                      onPressed: () =>
                                          _requestTransfer(id, label),
                                      icon:
                                          const Icon(Icons.av_timer, size: 18),
                                      label: Text(
                                        AppLocalizations.of(context)
                                            .inheritanceRequestTransfer,
                                      ),
                                    ),
                                  if (readyToClaim &&
                                      !credentialsSaved &&
                                      pairingState == 'paired_no_credentials')
                                    FilledButton.icon(
                                      onPressed: () =>
                                          _claimInheritance(id, label),
                                      icon: const Icon(Icons.move_to_inbox,
                                          size: 18),
                                      label: const Text('Claim'),
                                    ),
                                ],
                              ),
                            ],
                          ),
                        );
                      }),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSettingsSection(bool isMobile) {
    final app = context.watch<AppState>();
    final l = AppLocalizations.of(context);
    final used = app.storageUsedBytes;

    final limit = app.effectiveStorageLimitBytes;
    final progress = limit == 0 ? 0.0 : min(1.0, used / limit);

    return SingleChildScrollView(
      padding: EdgeInsets.all(isMobile ? 12 : 20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: Container(
            width: double.infinity,
            padding: EdgeInsets.all(
                MediaQuery.of(context).size.width < 600 ? 16 : 24),
            decoration: BoxDecoration(
              color: const Color(0xFF2F2F2F),
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l.settingsTitle,
                  style: TextStyle(
                      fontSize: vrHeadline(context),
                      fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 10),
                Text(
                  l.settingsSubtitle,
                  style: const TextStyle(
                    color: Color(0xFFB4B4B4),
                    fontSize: 15,
                    height: 1.6,
                  ),
                ),
                const SizedBox(height: 24),
                const LanguageCard(),
                const SizedBox(height: 24),

                const Text(
                  'Current plan',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 10),
                Container(
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    color: const Color(0xFF262626),
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: Colors.white10),
                  ),
                  child: Builder(builder: (_) {
                    if (app.isBillingLoading) {
                      return const _BillingLoadingCard(label: 'Loading plan…');
                    }
                    if (app.isBillingError) {
                      return _BillingErrorCard(
                        onRetry: () => app.retryBilling(),
                      );
                    }
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          app.planLabel,
                          style: const TextStyle(
                              fontSize: 20, fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          '${formatBytes(used)} used of ${formatBytes(limit)}',
                          style: const TextStyle(color: Color(0xFFB4B4B4)),
                        ),
                        if (app.storagePendingBytes > 0) ...[
                          const SizedBox(height: 4),
                          Text(
                            '${_formatBytes(app.storagePendingBytes)} pending '
                            '(in-flight uploads)',
                            style: const TextStyle(
                              color: Color(0xFF888888),
                              fontSize: 13,
                            ),
                          ),
                        ],
                        const SizedBox(height: 12),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(999),
                          child: LinearProgressIndicator(
                            value: progress,
                            minHeight: 10,
                          ),
                        ),
                      ],
                    );
                  }),
                ),

                const SizedBox(height: 16),

                InkWell(
                  onTap: () => Navigator.pushNamed(context, '/security-center'),
                  borderRadius: BorderRadius.circular(18),
                  child: Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: const Color(0xFF262626),
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.shield_outlined,
                            color: Color(0xFFB4B4B4)),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                AppLocalizations.of(context)
                                    .securityCenterTitle,
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              const SizedBox(height: 2),
                              const Text(
                                'Overall vault health and recommendations',
                                style: TextStyle(
                                    fontSize: 13, color: Color(0xFFB4B4B4)),
                              ),
                            ],
                          ),
                        ),
                        const Icon(Icons.chevron_right,
                            color: Color(0xFFB4B4B4)),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),

                InkWell(
                  onTap: () => Navigator.pushNamed(context, '/storage'),
                  borderRadius: BorderRadius.circular(18),
                  child: Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: const Color(0xFF262626),
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.cloud_outlined,
                            color: Color(0xFFB4B4B4)),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                AppLocalizations.of(context).storagePageTitle,
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              const SizedBox(height: 2),
                              const Text(
                                'Usage, free tier, and additional pricing',
                                style: TextStyle(
                                    fontSize: 13, color: Color(0xFFB4B4B4)),
                              ),
                            ],
                          ),
                        ),
                        const Icon(Icons.chevron_right,
                            color: Color(0xFFB4B4B4)),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),

                InkWell(
                  onTap: () => Navigator.pushNamed(context, '/devices'),
                  borderRadius: BorderRadius.circular(18),
                  child: Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: const Color(0xFF262626),
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Row(
                      children: const [
                        Icon(Icons.devices_other, color: Color(0xFFB4B4B4)),
                        SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Devices',
                                style: TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              SizedBox(height: 2),
                              Text(
                                'Approve new devices, revoke devices you '
                                'no longer use.',
                                style: TextStyle(
                                    color: Color(0xFFB4B4B4), fontSize: 13),
                              ),
                            ],
                          ),
                        ),
                        Icon(Icons.chevron_right, color: Color(0xFFB4B4B4)),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),

                InkWell(
                  key: const Key('settings_help_and_faq_tile'),
                  onTap: () => openHelpCenter(
                    context,
                    mode: hc.HelpCenterMode.signedIn,
                  ),
                  borderRadius: BorderRadius.circular(18),
                  child: Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: const Color(0xFF262626),
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Row(
                      children: const [
                        Icon(Icons.help_outline, color: Color(0xFFB4B4B4)),
                        SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Help & FAQ',
                                style: TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              SizedBox(height: 2),
                              Text(
                                'Answers about SVaultAI, Crypto Vault, '
                                'Monero, billing, and support.',
                                style: TextStyle(
                                  color: Color(0xFFB4B4B4),
                                  fontSize: 13,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Icon(Icons.chevron_right, color: Color(0xFFB4B4B4)),
                      ],
                    ),
                  ),
                ),

                const SizedBox(height: 12),

                InkWell(
                  key: const Key('settings_privacy_policy_tile'),
                  onTap: () => Navigator.pushNamed(
                    context,
                    kVaultAiPrivacyRoute,
                  ),
                  borderRadius: BorderRadius.circular(18),
                  child: Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: const Color(0xFF262626),
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Row(
                      children: const [
                        Icon(Icons.privacy_tip_outlined,
                            color: Color(0xFFB4B4B4)),
                        SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Privacy Policy',
                                style: TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              SizedBox(height: 2),
                              Text(
                                'How SVaultAI handles account, '
                                'vault, inheritance, wallet, and device data.',
                                style: TextStyle(
                                  color: Color(0xFFB4B4B4),
                                  fontSize: 13,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Icon(Icons.chevron_right, color: Color(0xFFB4B4B4)),
                      ],
                    ),
                  ),
                ),

                const SizedBox(height: 24),

                // Buy-More-Storage promotional card is WEB-ONLY.
                // Rationale: App Store 3.1.1 + Google Play Payments
                // Policy require in-app digital-goods purchases to use
                // StoreKit / Play Billing. Mobile users still upgrade
                // via the web at app.svaultai.com; hiding this
                // promotional entry point keeps the mobile store
                // submission compliant without touching web behavior.
                if (kIsWeb) ...[
                  InkWell(
                    onTap: () => Navigator.pushNamed(
                      context,
                      '/storage',
                      arguments: const {'autoOpenPicker': true},
                    ),
                    borderRadius: BorderRadius.circular(18),
                    child: Container(
                      padding: const EdgeInsets.all(18),
                      decoration: BoxDecoration(
                        color: const Color(0xFF10A37F).withValues(alpha: 0.10),
                        borderRadius: BorderRadius.circular(18),
                        border: Border.all(
                          color:
                              const Color(0xFF10A37F).withValues(alpha: 0.30),
                        ),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: const [
                              Icon(Icons.cloud_upload_outlined,
                                  color: Color(0xFF10A37F)),
                              SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      'Buy More Storage',
                                      style: TextStyle(
                                        fontSize: 18,
                                        fontWeight: FontWeight.w800,
                                      ),
                                    ),
                                    SizedBox(height: 4),
                                    Text(
                                      'Add storage in 50 GB blocks. Your '
                                      'limit updates automatically after '
                                      'payment.',
                                      style: TextStyle(
                                        color: Color(0xFFB4B4B4),
                                        height: 1.45,
                                        fontSize: 13,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 14),
                          Align(
                            alignment: Alignment.centerRight,
                            child: ElevatedButton.icon(
                              onPressed: () => Navigator.pushNamed(
                                context,
                                '/storage',
                                arguments: const {'autoOpenPicker': true},
                              ),
                              icon: const Icon(Icons.add, size: 18),
                              label: Text(
                                AppLocalizations.of(context).filesChooseStorage,
                              ),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: const Color(0xFF10A37F),
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 18,
                                  vertical: 12,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                ],

                _DeleteVaultSettingsTile(),

                const SizedBox(height: 24),

                CryptoVaultLockedCard(
                  tier: !app.isBillingLoaded
                      ? kTierLoadingLabel
                      : ((app.billingBlockCount > 0 &&
                              app.billingPurchasedBytes > 0)
                          ? kTierUpgradedLabel
                          : kTierFreeLabel),
                  onOpenCryptoVault: () {
                    setState(
                        () => selectedSection = _DashboardSection.cryptoVault);
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  void initState() {
    super.initState();
    final initialChatTiming = Stopwatch()..start();
    _uploadQueue = UploadQueueController(
      action: _runUploadAction,
      maxConcurrency: 3,
      maxAttempts: 3,
      onDuplicate: _resolveUploadDuplicate,
      onNameConflict: _resolveNameConflict,
      onStorageLimitHit: _onStorageLimitHit,
    );
    _uploadQueue.addListener(_onUploadQueueChanged);
    _folderPicker = createFolderPickerService();
    _nativeMediaCapture = createNativeMediaCaptureService();
    _recordingStorage = createRecordingStorage();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final app = context.read<AppState>();

      _uploadKeepAliveProbe ??= () => _uploadQueue.isBusy;
      _uploadShutdownHook ??= () => _uploadQueue.cancelAll();
      app.registerKeepAliveProbe(_uploadKeepAliveProbe!);
      app.registerShutdownHook(_uploadShutdownHook!);

      if (!app.unlocked || app.vaultName == null) {
        if (!mounted) return;
        Navigator.pushReplacementNamed(context, '/pin');
        return;
      }

      if (mounted) {
        setState(() {
          msgs.add(
            _Msg(
              'assistant',
              'Your vault is unlocked 🔓\n\n'
                  'This is your private place for the important things you '
                  'may need later — documents, photos, videos, audio, IDs, '
                  'credentials, receipts, device details, notes, and '
                  'personal records.\n\n'
                  'Ask me to find something, save something, organize '
                  'what\'s inside, or help you understand what you\'ve '
                  'stored.',
            ),
          );
        });
        authTimingDiagnosticPrint(
          'initial_chat_visible',
          initialChatTiming.elapsed,
        );
      }
      await app.refreshVaultStats();
      await _loadVaultFiles();
      await _loadVaultLogins();
      authTimingDiagnosticPrint(
        'initial_vault_data_loaded',
        initialChatTiming.elapsed,
      );
    });
  }

  Future<bool> _initSpeech() async {
    try {
      final ok = await _speech.initialize(
        onError: (_) {
          if (mounted) setState(() => _isListening = false);
        },
        onStatus: (_) {
          if (mounted) {
            setState(() => _isListening = _speech.isListening);
          }
        },
      );
      if (mounted) {
        setState(() {
          _speechInitialized = true;
          _speechAvailable = ok;
        });
      }
      return ok;
    } catch (_) {
      if (mounted) {
        setState(() {
          _speechInitialized = true;
          _speechAvailable = false;
        });
      }
      return false;
    }
  }

  Future<void> _toggleListening() async {
    if (sending) return;
    if (!_speechInitialized) {
      final allowed = await _ensureMicrophonePermission(
        'Microphone permission is needed for voice input.',
      );
      if (!allowed) return;
      await _initSpeech();
    }
    if (!_speechAvailable) {
      _showSnack(
        'Voice input is unavailable or microphone permission was denied.',
      );
      return;
    }

    if (_isListening) {
      await _speech.stop();
      if (mounted) setState(() => _isListening = false);
      return;
    }

    _preMicText = input.text;
    if (mounted) setState(() => _isListening = true);

    await _speech.listen(
      onResult: (result) {
        if (!mounted) return;
        final transcript = result.recognizedWords;
        final combined =
            _preMicText.isEmpty ? transcript : '$_preMicText $transcript';
        setState(() {
          input.text = combined;
          input.selection = TextSelection.collapsed(offset: combined.length);
        });
      },
      listenFor: const Duration(minutes: 1),
      pauseFor: const Duration(seconds: 4),
    );
  }

  Future<void> _toggleRecording() async {
    if (sending) return;

    if (_isListening) {
      _showSnack('Stop voice input before recording audio.');
      return;
    }

    if (_isRecording) {
      await _stopAudioRecording();
      return;
    }

    if (!await _ensureMicrophonePermission(
      'Microphone permission is needed to record voice.',
    )) {
      return;
    }

    bool granted;
    try {
      granted = await _audioRecorder.hasPermission();
    } catch (_) {
      granted = false;
    }
    if (!granted) {
      _showPermissionSnack(
        'Microphone permission was denied or unavailable.',
      );
      return;
    }

    try {
      final recordingName = generateVoiceRecordingFilename(
        now: DateTime.now(),
      );
      final recordingPath = await _recordingStorage.audioPath(recordingName);
      await _audioRecorder.start(
        const RecordConfig(encoder: AudioEncoder.aacLc),
        path: recordingPath,
      );
      if (mounted) {
        setState(() {
          _isRecording = true;
          _audioRecordingName = recordingName;
        });
      }
    } catch (_) {
      _audioRecordingName = null;
      _showSnack('Could not start recording.');
    }
  }

  Future<void> _stopAudioRecording() async {
    String? path;
    try {
      path = await _audioRecorder.stop();
    } catch (_) {}
    final recordedName = _audioRecordingName ??
        generateVoiceRecordingFilename(now: DateTime.now());
    if (mounted) {
      setState(() {
        _isRecording = false;
        _audioRecordingName = null;
      });
    } else {
      _audioRecordingName = null;
    }

    if (path == null || path.isEmpty) return;

    Uint8List bytes;
    try {
      bytes = await _recordingStorage.readAndMaybeDelete(path);
    } catch (_) {
      _showSnack('Could not read the recording.');
      return;
    }

    if (bytes.isEmpty) {
      _showSnack('Recording is empty.');
      return;
    }

    final sizeError = _checkUploadSize(bytes.length);
    if (sizeError != null) {
      _showSnack(sizeError);
      return;
    }

    if (!mounted) return;
    final recordedBytes = bytes;
    setState(() {
      attachments.add(
        _Attachment(
          id: _newAttachmentId(),
          name: recordedName,
          kind: 'audio',
          readBytes: () async => recordedBytes,
          size: recordedBytes.length,
          mimeType: 'audio/mp4',
        ),
      );
    });
  }

  Future<void> _toggleVideoRecording() async {
    if (sending) return;

    if (kIsWeb) {
      await _openWebVideoRecorder();
      return;
    }

    if (!kIsWeb && _nativeMediaCapture.isSupported) {
      await _captureNativeVideo();
      return;
    }
    _showSnack('Video recording is unavailable on this device.');
  }

  Future<void> _openWebVideoRecorder() async {
    if (_isRecording) {
      _showSnack('Stop audio recording before recording video.');
      return;
    }
    if (_isListening) {
      _showSnack('Stop voice input before recording video.');
      return;
    }
    final recording = await showDialog<WebVideoRecording>(
      context: context,
      useRootNavigator: false,
      barrierDismissible: false,
      builder: (_) => WebVideoRecorderDialog(recorder: _videoRecorder),
    );
    if (!mounted || recording == null) return;
    final sizeError = _checkUploadSize(recording.bytes.length);
    if (sizeError != null) {
      _showSnack(sizeError);
      return;
    }
    final recordedBytes = recording.bytes;
    setState(() {
      attachments.add(_Attachment(
        id: _newAttachmentId(),
        name: 'video_${DateTime.now().millisecondsSinceEpoch}.webm',
        kind: 'video',
        readBytes: () async => recordedBytes,
        size: recordedBytes.length,
        mimeType: recording.mimeType,
      ));
    });
  }

  // Compatibility cleanup for the retired inline web recorder banner. The
  // dedicated WebVideoRecorderDialog owns all current web close/discard UI.
  Future<void> _cancelVideoRecordingWithConfirmation() async {
    if (!_isVideoRecording) return;
    _videoRecorder.cancel();
    if (!mounted) return;
    setState(() {
      _isVideoRecording = false;
      _videoPreviewViewType = null;
    });
  }

  Future<void> _captureNativePhoto() async {
    if (sending) return;
    if (!await _ensureCameraPermission(
      'Camera permission is needed to take a photo.',
    )) {
      return;
    }
    CapturedMedia? captured;
    try {
      captured = await _nativeMediaCapture.capturePhoto();
    } catch (_) {
      _showSnack('Could not take a photo.');
      return;
    }
    if (captured == null) return;
    _ingestCapturedMedia(captured);
  }

  Future<void> _captureNativeVideo() async {
    if (sending) return;
    if (_isRecording) {
      _showSnack('Stop audio recording before recording video.');
      return;
    }
    if (_isListening) {
      _showSnack('Stop voice input before recording video.');
      return;
    }
    if (!await _ensureCameraAndMicrophonePermission(
      'Camera and microphone permissions are needed to record video.',
    )) {
      return;
    }

    CapturedMedia? captured;
    try {
      captured = await _nativeMediaCapture.captureVideo();
    } catch (_) {
      _showSnack('Could not record a video.');
      return;
    }
    if (captured == null) return;
    _ingestCapturedMedia(captured);
  }

  void _ingestCapturedMedia(CapturedMedia captured) {
    final sizeError = _checkUploadSize(captured.bytes.length);
    if (sizeError != null) {
      _showSnack(sizeError);
      return;
    }
    final capturedBytes = captured.bytes;
    if (!mounted) return;
    setState(() {
      attachments.add(
        _Attachment(
          id: _newAttachmentId(),
          name: captured.name,
          kind: captured.kind,
          readBytes: () async => capturedBytes,
          size: capturedBytes.length,
          mimeType: captured.mimeType,
        ),
      );
    });
  }

  Future<bool> _ensureMicrophonePermission(String message) async {
    if (kIsWeb) return true;
    try {
      final status = await Permission.microphone.request();
      if (status.isGranted || status.isLimited) return true;
    } catch (_) {
      _showPermissionSnack(message);
      return false;
    }
    _showPermissionSnack(message);
    return false;
  }

  Future<bool> _ensureCameraPermission(String message) async {
    if (kIsWeb) return true;
    try {
      final status = await Permission.camera.request();
      if (status.isGranted || status.isLimited) return true;
    } catch (_) {
      _showPermissionSnack(message);
      return false;
    }
    _showPermissionSnack(message);
    return false;
  }

  Future<bool> _ensureCameraAndMicrophonePermission(String message) async {
    if (kIsWeb) return true;
    final cameraOk = await _ensureCameraPermission(message);
    if (!cameraOk) return false;
    return _ensureMicrophonePermission(message);
  }

  void _showPermissionSnack(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(text),
        action: SnackBarAction(
          label: 'Settings',
          onPressed: openAppSettings,
        ),
      ),
    );
  }

  Widget _buildRecordingBanner() {
    final viewType = _videoPreviewViewType;

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A1A),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: Colors.redAccent.withValues(alpha: 0.35),
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (kIsWeb && viewType != null)
            AspectRatio(
              aspectRatio: 16 / 9,
              child: HtmlElementView(viewType: viewType),
            ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            color: Colors.redAccent.withValues(alpha: 0.12),
            child: Row(
              children: [
                const Icon(
                  Icons.fiber_manual_record,
                  color: Colors.redAccent,
                  size: 14,
                ),
                const SizedBox(width: 8),
                const Text(
                  'Recording video...',
                  style: TextStyle(
                    color: Colors.redAccent,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const Spacer(),
                IconButton(
                  key: const Key('video_recording_close_button'),
                  tooltip: 'Cancel recording',
                  onPressed: _cancelVideoRecordingWithConfirmation,
                  icon: const Icon(Icons.close, color: Colors.white70),
                ),
                TextButton.icon(
                  onPressed: _toggleVideoRecording,
                  icon: const Icon(Icons.stop, color: Colors.redAccent),
                  label: const Text(
                    'Stop',
                    style: TextStyle(color: Colors.redAccent),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildImportPanel() {
    final q = _uploadQueue;
    final total = q.totalCount;
    if (total == 0) return const SizedBox.shrink();

    final uploaded = q.uploadedCount;
    final failed = q.failedCount;
    final pauseSec = q.pauseRemaining?.inSeconds;
    final isBusy = q.isBusy;
    final aggregateProgress = total == 0 ? 0.0 : uploaded / total;

    String headerText;
    if (isBusy) {
      headerText = 'Uploading $uploaded of $total files'
          '${failed > 0 ? ' • $failed failed' : ''}';
    } else if (failed > 0) {
      headerText = 'Imported $uploaded of $total • $failed failed';
    } else {
      headerText = 'Imported $uploaded of $total files';
    }

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A1A),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white24),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                failed > 0 && !isBusy
                    ? Icons.error_outline
                    : Icons.cloud_upload_outlined,
                size: 16,
                color:
                    failed > 0 && !isBusy ? Colors.redAccent : Colors.white70,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  headerText,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (failed > 0)
                TextButton.icon(
                  onPressed: _uploadQueue.retryAllFailed,
                  icon: const Icon(Icons.refresh, size: 14),
                  label: Text(
                    AppLocalizations.of(context).cryptoRetryFailed,
                    style: const TextStyle(fontSize: 12),
                  ),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    minimumSize: const Size(0, 28),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
              if (isBusy)
                TextButton.icon(
                  onPressed: _cancelActiveUploads,
                  icon: const Icon(Icons.close,
                      size: 14, color: Colors.redAccent),
                  label: const Text(
                    'Cancel',
                    style: TextStyle(color: Colors.redAccent, fontSize: 12),
                  ),
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    minimumSize: const Size(0, 28),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                )
              else if (total > 0)
                IconButton(
                  icon: const Icon(Icons.close, size: 16),
                  tooltip: 'Dismiss',
                  onPressed: _uploadQueue.reset,
                  visualDensity: VisualDensity.compact,
                ),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: aggregateProgress,
              minHeight: 5,
              backgroundColor: Colors.white12,
            ),
          ),
          if (pauseSec != null) ...[
            const SizedBox(height: 6),
            Text(
              'Rate-limited. Resuming in ${pauseSec}s…',
              style: const TextStyle(
                color: Color(0xFFFFB74D),
                fontSize: 11,
              ),
            ),
          ],
          const SizedBox(height: 8),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 200),
            child: Scrollbar(
              child: ListView.builder(
                shrinkWrap: true,
                itemCount: q.jobs.length,
                itemBuilder: (context, i) => _buildImportJobRow(q.jobs[i]),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildImportJobRow(UploadJob j) {
    IconData icon;
    Color color;
    String label;
    switch (j.status) {
      case UploadJobStatus.pending:
        icon = Icons.schedule;
        color = Colors.white54;
        label = 'pending';
        break;
      case UploadJobStatus.reading:
        icon = Icons.cloud_sync;
        color = Colors.white70;
        label = 'reading…';
        break;
      case UploadJobStatus.uploading:
        icon = Icons.upload;
        color = const Color(0xFF10A37F);
        final pct = (j.progress * 100).clamp(0, 100).toStringAsFixed(0);
        label = 'uploading $pct%';
        break;
      case UploadJobStatus.uploaded:
        icon = Icons.check_circle;
        color = const Color(0xFF10A37F);
        label = 'uploaded';
        break;
      case UploadJobStatus.failed:
        icon = Icons.error_outline;
        color = Colors.redAccent;
        label = j.errorMessage ?? 'failed';
        break;
      case UploadJobStatus.retrying:
        icon = Icons.refresh;
        color = const Color(0xFFFFB74D);
        label = 'retrying (attempt ${j.attempts})';
        break;
      case UploadJobStatus.cancelled:
        icon = Icons.cancel;
        color = Colors.white38;
        label = 'cancelled';
        break;
      case UploadJobStatus.skippedDuplicate:
        icon = Icons.content_copy_outlined;
        color = const Color(0xFFFBBF24);
        label = 'already in vault';
        break;
      case UploadJobStatus.stoppedForStorage:
        icon = Icons.cloud_off_outlined;
        color = const Color(0xFFFBBF24);
        label = 'not enough storage';
        break;
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  j.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white, fontSize: 12),
                ),
                Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: color, fontSize: 11),
                ),
              ],
            ),
          ),
          if (j.status == UploadJobStatus.failed)
            IconButton(
              icon: const Icon(Icons.refresh, size: 14),
              tooltip: 'Retry',
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 24, minHeight: 24),
              onPressed: () => _uploadQueue.retry(j.id),
            ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _credentialV2HttpClient.close();
    _chatMainnetSendApprovalSession.clear();
    final activeRequestId = _activeChatRequestId;
    if (activeRequestId != null) {
      _chatRequests.cancel(activeRequestId);
      _cancelledChatRequestIds.add(activeRequestId);
    }
    unawaited(_activeChatIterator?.cancel());
    _activeChatIterator = null;
    _activeChatRequestId = null;
    if (_speech.isListening) {
      _speech.cancel();
    }
    if (_isRecording) {
      _audioRecorder.stop();
    }
    _audioRecorder.dispose();
    if (_isVideoRecording || _videoPreviewViewType != null) {
      _videoRecorder.cancel();
    }
    _videoRecorder.dispose();

    try {
      final app = context.read<AppState>();
      if (_uploadKeepAliveProbe != null) {
        app.unregisterKeepAliveProbe(_uploadKeepAliveProbe!);
      }
      if (_uploadShutdownHook != null) {
        app.unregisterShutdownHook(_uploadShutdownHook!);
      }
    } catch (_) {}
    _uploadQueue.removeListener(_onUploadQueueChanged);
    _uploadQueue.dispose();
    input.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _onUploadQueueChanged() {
    if (mounted) setState(() {});
    final nowBusy = _uploadQueue.isBusy;
    if (_wasUploadQueueBusy && !nowBusy && mounted) {
      try {
        final app = context.read<AppState>();
        app.resetInactivityTimer();
      } catch (_) {}
    }
    _wasUploadQueueBusy = nowBusy;
  }

  Future<DuplicateUploadDecision?> _resolveUploadDuplicate(
    UploadJob job,
    Map<String, dynamic> detail,
  ) async {
    if (_currentUploadContext?.isBatchUpload == true) {
      return DuplicateUploadDecision.skip;
    }
    if (!mounted) {
      return DuplicateUploadDecision.skip;
    }
    final parsed = DuplicateFoundDetail.fromJson(detail);
    final choice = await DuplicateUploadDialog.show(
      context,
      detail: parsed,
    );
    switch (choice) {
      case DuplicateDialogChoice.keepBoth:
        return DuplicateUploadDecision.keepBoth;
      case DuplicateDialogChoice.skip:
      case DuplicateDialogChoice.cancel:
        if (mounted) {
          _showSnack(
            'Skipped duplicate file already in your vault.',
          );
        }
        return DuplicateUploadDecision.skip;
    }
  }

  void _onStorageLimitHit(StorageLimitDuringUploadException error) {
    if (!mounted) return;
    _showSnack('Import stopped — not enough storage.');
  }

  Future<NameConflictDecision?> _resolveNameConflict(
    UploadJob job,
    Map<String, dynamic> detail,
  ) async {
    if (_currentUploadContext?.isBatchUpload == true) {
      return NameConflictDecision.cancel;
    }
    if (!mounted) return NameConflictDecision.cancel;
    final parsed = NameConflictDetail.fromJson(detail);
    final choice = await NameConflictDialog.show(
      context,
      detail: parsed,
    );
    switch (choice) {
      case NameConflictDialogChoice.keepBoth:
        return NameConflictDecision.keepBoth;
      case NameConflictDialogChoice.cancel:
      case NameConflictDialogChoice.replace:
        return NameConflictDecision.cancel;
    }
  }

  Future<UploadResult> _runUploadAction(
    UploadJob job,
    Uint8List bytes,
    void Function(double progress) reportProgress,
  ) async {
    final ctx = _currentUploadContext;
    if (ctx == null) {
      throw StateError(
        'Upload queue invoked without _currentUploadContext — '
        '_uploadAttachments must set the context before enqueueing.',
      );
    }

    final preferChunked = bytes.length >= kChunkedUploadThresholdBytes;

    final contentSha256 = computeContentSha256(bytes);

    final duplicateAction =
        job.duplicateAction ?? (ctx.isBatchUpload ? 'skip' : 'prompt');

    Map<String, dynamic> result;
    try {
      if (preferChunked) {
        try {
          result = await _chunkedUpload(
            client: ctx.client,
            vaultName: ctx.vaultName,
            pin: ctx.pin,
            authToken: ctx.authToken,
            keyBytes: ctx.keyBytes!,
            filename: job.name,
            mimeType: job.mimeType,
            bytes: bytes,
            onProgress: reportProgress,
            isBatchUpload: ctx.isBatchUpload,
            relativePath: job.relativePath,
            importId: job.importId,
            contentSha256: contentSha256,
          );
        } on ChunkedUploadNotAvailableException {
          if (bytes.length > ctx.uploadSafetyCapBytes) {
            throw Exception(
              'Large uploads are not enabled yet on this server. '
              'This file is ${_formatBytes(bytes.length)} and the '
              'temporary single-upload safety cap is '
              '${_formatBytes(ctx.uploadSafetyCapBytes)}.',
            );
          }
          result = await ctx.client.uploadVaultFile(
            vaultName: ctx.vaultName,
            pin: ctx.pin,
            authToken: ctx.authToken,
            filename: job.name,
            fileBytes: bytes,
            contentType: job.mimeType,
            accompanyingText: ctx.accompanyingText,
            isBatchUpload: ctx.isBatchUpload,
            relativePath: job.relativePath,
            importId: job.importId,
            contentSha256: contentSha256,
            duplicateAction: duplicateAction,
          );
        }
      } else {
        result = await ctx.client.uploadVaultFile(
          vaultName: ctx.vaultName,
          pin: ctx.pin,
          authToken: ctx.authToken,
          filename: job.name,
          fileBytes: bytes,
          contentType: job.mimeType,
          accompanyingText: ctx.accompanyingText,
          isBatchUpload: ctx.isBatchUpload,
          relativePath: job.relativePath,
          importId: job.importId,
          contentSha256: contentSha256,
          duplicateAction: duplicateAction,
        );
      }
    } on DuplicateFoundUploadException catch (e) {
      throw DuplicateUploadDecisionRequired(e.detail);
    } on NameConflictUploadException catch (e) {
      throw NameConflictDecisionRequired(e.detail);
    } on StorageLimitExceededException catch (e) {
      throw StorageLimitDuringUploadException(
        message: e.message,
        usedBytes: e.usedBytes,
        limitBytes: e.limitBytes,
      );
    } on RateLimitedException catch (e) {
      final pauseSec = e.resetInSeconds ?? 30;
      throw TransientUploadException(
        'Server rate-limited the upload (retrying in ${pauseSec}s)',
        pauseFor: Duration(seconds: pauseSec),
      );
    }

    final status = result['status']?.toString();
    if (status == 'skipped_duplicate') {
      final existingId = result['duplicate_of_file_id']?.toString() ?? '';
      return UploadResult(
        fileId: existingId,
        skippedDuplicate: true,
        message: result['message']?.toString(),
        existingRelativePath: result['existing_relative_path']?.toString(),
      );
    }

    final fileId = result['file_id']?.toString();
    if (fileId == null || fileId.isEmpty) {
      throw Exception('Upload succeeded but no file_id was returned.');
    }

    final requestedDisplayName = job.displayName?.trim();
    var displayNameCommitted = false;
    String? displayNameWarning;
    if (requestedDisplayName != null && requestedDisplayName.isNotEmpty) {
      try {
        await ctx.client.nameVaultFile(
          vaultName: ctx.vaultName,
          fileId: fileId,
          savedName: requestedDisplayName,
          pin: ctx.pin,
          authToken: ctx.authToken,
        );
        displayNameCommitted = true;
      } catch (_) {
        displayNameWarning = 'Saved the file, but I could not save its title. '
            'Rename it from Files.';
      }
    }

    // ZK client-finalize of server-inferred document metadata.
    // For ZK vaults the backend INSERTs uploaded_files rows with
    // detected_type / detected_service / asset_type = NULL. We
    // reconstruct these fields locally from the filename + MIME
    // type, encrypt under metadataKey, and POST the ciphertext to
    // /vault/ciphertext/uploaded-files. Fire-and-forget: an
    // upload succeeds even if the metadata finalize fails
    // (fail-closed — no plaintext fallback).
    unawaited(tryZkFinalizeInferredUploadMetadataBestEffort(
      baseUrl: backendBaseUrl,
      authToken: ctx.authToken,
      fileId: fileId,
      fileName: job.name,
      contentType: job.mimeType,
    ));

    return UploadResult(
      fileId: fileId,
      autoNamed: result['auto_named'] == true || displayNameCommitted,
      message: displayNameWarning ??
          (displayNameCommitted
              ? 'Saved "$requestedDisplayName".'
              : result['message']?.toString()),
      renamed: result['renamed'] == true,
      originalSavedName: result['original_saved_name']?.toString(),
    );
  }

  UploadJob? _findQueueJob(String attachmentId) {
    for (final j in _uploadQueue.jobs) {
      if (j.id == attachmentId) return j;
    }
    return null;
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent + 120,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  Future<void> _loadVaultLogins() async {
    final app = context.read<AppState>();
    final token = app.sessionToken;

    if (token == null || app.vaultName == null) return;

    setState(() {
      loadingLogins = true;

      secureItemsError = null;
    });

    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);

      final result = await client.listVaultSecureItems(
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
      );
      final rawItems = result['items'];
      final parsed = <VaultLoginItem>[];

      if (rawItems is List) {
        for (final item in rawItems) {
          if (item is Map<String, dynamic>) {
            parsed.add(VaultLoginItem.fromJson(item));
          } else if (item is Map) {
            parsed
                .add(VaultLoginItem.fromJson(Map<String, dynamic>.from(item)));
          }
        }
      }

      final v2Repository = _credentialV2Repository(app);
      if (v2Repository != null) {
        final v2Records = await v2Repository.listDecrypted();
        parsed.addAll(v2Records.map((record) => VaultLoginItem(
              service: record.plaintext.service,
              itemType: 'login',
              recordId: record.recordId,
              cryptoVersion: credentialV2CryptoVersion,
              migrationState: record.migrationState,
              verificationState: record.verificationState,
            )));
      }

      if (!mounted) return;
      setState(() {
        vaultLogins = parsed;
        hasLoadedSecureItems = true;
        secureItemsError = null;
      });
    } catch (e) {
      if (app.handleApiException(e)) return;

      if (mounted) {
        setState(() {
          hasLoadedSecureItems = true;
          secureItemsError = e.toString();
        });
      }
      _showSnack('Could not load secure items: $e');
    } finally {
      if (mounted) {
        setState(() {
          loadingLogins = false;
        });
      }
    }
  }

  Future<void> _loadVaultFiles() async {
    final app = context.read<AppState>();
    final token = app.sessionToken;

    if (token == null || app.vaultId == null || app.vaultName == null) return;

    setState(() {
      loadingFiles = true;
    });

    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.listVaultFiles(
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
      );

      final rawFiles = result['files'];
      final parsed = <_VaultStoredFile>[];

      if (rawFiles is List) {
        for (final item in rawFiles) {
          if (item is Map<String, dynamic>) {
            parsed.add(_VaultStoredFile.fromJson(item));
          } else if (item is Map) {
            parsed.add(
                _VaultStoredFile.fromJson(Map<String, dynamic>.from(item)));
          }
        }
      }

      if (!mounted) return;
      setState(() {
        vaultFiles = parsed;
      });
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack('Could not load files: $e');
    } finally {
      if (mounted) {
        setState(() {
          loadingFiles = false;
        });
      }
    }

    await _loadFolderTree();
  }

  Future<void> _loadFolderTree() async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) return;

    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final response = await client.listFolder(
        authToken: token,
        path: _currentFolderPath.isEmpty ? null : _currentFolderPath,
      );
      if (!mounted) return;
      setState(() {
        _folderTreeData = FolderTreeData.fromJson(response);
      });
    } catch (e) {
      if (kDebugMode) {
        debugPrint('listFolder failed: $e');
      }
    }
  }

  void _navigateToFolder(String path) {
    if (_currentFolderPath == path) return;
    setState(() {
      _currentFolderPath = path;

      _folderSearchQuery = '';
    });

    _loadFolderTree();
  }

  Widget _buildAttachmentPlusMenu() {
    final maxMenuHeight = math.max(
      260.0,
      math.min(420.0, MediaQuery.of(context).size.height - 180.0),
    );
    final supportsNativeCapture = !kIsWeb && _nativeMediaCapture.isSupported;
    final supportsVideoRecording = kIsWeb || supportsNativeCapture;
    final supportsFolderUpload = _folderPicker.isSupported;

    return Semantics(
      container: true,
      identifier: 'attachment_menu_button',
      button: true,
      child: PopupMenuButton<String>(
        key: const Key('attachment_menu_button'),
        tooltip: 'Add attachment',
        icon: const Icon(Icons.add_circle_outline),
        constraints: BoxConstraints(
          minWidth: 260,
          maxWidth: 320,
          maxHeight: maxMenuHeight,
        ),
        enabled: !sending,
        onSelected: (value) async {
          try {
            switch (value) {
              case 'file':
                await _pickFile();
                break;
              case 'take_photo':
                await _captureNativePhoto();
                break;
              case 'photo':
                await _pickImage();
                break;
              case 'video':
                await _pickVideo();
                break;
              case 'audio':
                await _pickAudio();
                break;
              case 'folder':
                await _pickFolder();
                break;
              case 'voice':
                await _toggleRecording();
                break;
              case 'record_video':
                await _toggleVideoRecording();
                break;
            }
          } catch (_) {
            _showSnack('Could not open that attachment action.');
          }
        },
        itemBuilder: (context) => [
          PopupMenuItem(
            key: const Key('attachment_menu_upload_file'),
            value: 'file',
            child: Semantics(
              container: true,
              identifier: 'attachment_menu_upload_file',
              button: true,
              child: ListTile(
                dense: true,
                leading: const Icon(Icons.attach_file),
                title: Text(AppLocalizations.of(context).filesUploadFile),
              ),
            ),
          ),
          if (supportsNativeCapture)
            PopupMenuItem(
              key: const Key('attachment_menu_take_photo'),
              value: 'take_photo',
              child: Semantics(
                container: true,
                identifier: 'attachment_menu_take_photo',
                button: true,
                child: ListTile(
                  dense: true,
                  leading: Icon(Icons.add_a_photo_outlined),
                  title: Text('Take photo'),
                ),
              ),
            ),
          PopupMenuItem(
            key: const Key('attachment_menu_upload_photo'),
            value: 'photo',
            child: Semantics(
              container: true,
              identifier: 'attachment_menu_upload_photo',
              button: true,
              child: ListTile(
                dense: true,
                leading: const Icon(Icons.image),
                title: Text(AppLocalizations.of(context).filesUploadPhoto),
              ),
            ),
          ),
          PopupMenuItem(
            key: const Key('attachment_menu_upload_video'),
            value: 'video',
            child: Semantics(
              container: true,
              identifier: 'attachment_menu_upload_video',
              button: true,
              child: ListTile(
                dense: true,
                leading: const Icon(Icons.videocam_outlined),
                title: Text(AppLocalizations.of(context).filesUploadVideo),
              ),
            ),
          ),
          PopupMenuItem(
            key: const Key('attachment_menu_upload_audio'),
            value: 'audio',
            child: Semantics(
              container: true,
              identifier: 'attachment_menu_upload_audio',
              button: true,
              child: ListTile(
                dense: true,
                leading: const Icon(Icons.audiotrack),
                title: Text(AppLocalizations.of(context).filesUploadAudio),
              ),
            ),
          ),
          if (supportsFolderUpload)
            PopupMenuItem(
              key: const Key('attachment_menu_upload_folder'),
              value: 'folder',
              child: Semantics(
                container: true,
                identifier: 'attachment_menu_upload_folder',
                button: true,
                child: ListTile(
                  dense: true,
                  leading: const Icon(Icons.folder_open),
                  title: Text(AppLocalizations.of(context).filesUploadFolder),
                ),
              ),
            ),
          const PopupMenuDivider(),
          PopupMenuItem(
            key: const Key('attachment_menu_record_voice'),
            value: 'voice',
            child: Semantics(
              container: true,
              identifier: 'attachment_menu_record_voice',
              button: true,
              child: ListTile(
                dense: true,
                leading: const Icon(Icons.mic_none),
                title: Text(AppLocalizations.of(context).filesRecordVoice),
              ),
            ),
          ),
          if (supportsVideoRecording)
            PopupMenuItem(
              key: const Key('attachment_menu_record_video'),
              value: 'record_video',
              child: Semantics(
                container: true,
                identifier: 'attachment_menu_record_video',
                button: true,
                child: ListTile(
                  dense: true,
                  leading: const Icon(Icons.videocam),
                  title: Text(AppLocalizations.of(context).filesRecordVideo),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _pickFile() async {
    final result = await FilePicker.platform.pickFiles(
      withData: false,
      withReadStream: true,
      allowMultiple: true,
      type: FileType.any,
    );

    if (result == null || result.files.isEmpty) return;
    _ingestPickedFiles(result.files, kind: 'file');
  }

  Future<void> _pickImage() async {
    final result = await FilePicker.platform.pickFiles(
      withData: false,
      withReadStream: true,
      allowMultiple: true,
      type: FileType.image,
    );
    if (result == null || result.files.isEmpty) return;
    _ingestPickedFiles(result.files, kind: 'image');
  }

  Future<void> _pickVideo() async {
    final result = await FilePicker.platform.pickFiles(
      withData: false,
      withReadStream: true,
      allowMultiple: true,
      type: FileType.video,
    );
    if (result == null || result.files.isEmpty) return;
    _ingestPickedFiles(result.files, kind: 'video');
  }

  Future<void> _pickAudio() async {
    final result = await FilePicker.platform.pickFiles(
      withData: false,
      withReadStream: true,
      allowMultiple: true,
      type: FileType.custom,
      allowedExtensions: kAcceptedAudioExtensions,
    );
    if (result == null || result.files.isEmpty) return;
    _ingestPickedFiles(result.files, kind: 'audio');
  }

  Future<void> _pickFolder() async {
    if (!_folderPicker.isSupported) {
      _showSnack(_folderPicker.unsupportedReason);
      return;
    }

    FolderPickResult? result;
    try {
      result = await _folderPicker.pickFolder();
    } catch (e) {
      _showSnack('Could not open the folder picker: $e');
      return;
    }
    if (result == null) return;
    if (result.files.isEmpty) {
      _showSnack('No readable files inside that folder.');
      return;
    }

    _ingestPickedFolderFiles(result);
  }

  void _ingestPickedFolderFiles(FolderPickResult result) {
    final accepted = <_Attachment>[];
    final skippedReasons = <String>[...result.skipped];

    for (final f in result.files) {
      final sizeError = _checkUploadSize(f.size);
      if (sizeError != null) {
        skippedReasons.add('${f.relativePath}: $sizeError');
        continue;
      }

      accepted.add(_Attachment(
        id: _newAttachmentId(),
        name: f.name,
        kind: 'file',
        readBytes: f.readBytes,
        size: f.size,
        mimeType: f.mimeType ?? _guessMimeTypeFromName(f.name),
        relativePath: f.relativePath,
      ));
    }

    if (accepted.isNotEmpty) {
      setState(() => attachments.addAll(accepted));
      final rootName =
          result.rootFolderName.isEmpty ? 'folder' : result.rootFolderName;
      _showSnack(
        'Queued ${accepted.length} file'
        '${accepted.length == 1 ? '' : 's'} from $rootName.',
      );
    }
    if (skippedReasons.isNotEmpty) {
      _showSnack(
        'Skipped ${skippedReasons.length} file'
        '${skippedReasons.length == 1 ? '' : 's'}: '
        '${skippedReasons.take(2).join(' · ')}'
        '${skippedReasons.length > 2 ? ' (+${skippedReasons.length - 2} more)' : ''}',
      );
    }
  }

  void _ingestPickedFiles(List<PlatformFile> files, {required String kind}) {
    final accepted = <_Attachment>[];
    final skippedReasons = <String>[];
    for (final f in files) {
      if (f.readStream == null && f.bytes == null) {
        skippedReasons.add('${f.name}: unreadable');
        continue;
      }
      final sizeError = _checkUploadSize(f.size);
      if (sizeError != null) {
        skippedReasons.add('${f.name}: $sizeError');
        continue;
      }

      final pf = f;
      accepted.add(_Attachment(
        id: _newAttachmentId(),
        name: f.name,
        kind: kind,
        readBytes: () => readPlatformFileBytes(pf),
        size: f.size,
        mimeType: _guessMimeTypeFromName(f.name),
      ));
    }
    if (accepted.isNotEmpty) {
      setState(() => attachments.addAll(accepted));
    }
    if (skippedReasons.isNotEmpty) {
      _showSnack(
        'Skipped ${skippedReasons.length} file${skippedReasons.length == 1 ? '' : 's'}: '
        '${skippedReasons.take(2).join(' · ')}'
        '${skippedReasons.length > 2 ? ' (+${skippedReasons.length - 2} more)' : ''}',
      );
    }
  }

  void _clearAttachments() {
    setState(() => attachments.clear());
  }

  String? _checkUploadSize(int sizeBytes) {
    final app = context.read<AppState>();
    final cap = app.uploadSafetyCapBytes;

    if (app.isBillingLoaded) {
      final limit = app.effectiveStorageLimitBytes;
      final remaining = (limit - app.storageUsedBytes).clamp(0, limit);

      if (sizeBytes > remaining) {
        return 'Not enough vault storage left. You have '
            '${formatBytes(remaining)} remaining; this file is '
            '${formatBytes(sizeBytes)}.';
      }
    }

    if (sizeBytes < kChunkedUploadThresholdBytes && sizeBytes > cap) {
      return 'This file is ${_formatBytes(sizeBytes)}. The current '
          'single-upload safety cap is ${_formatBytes(cap)} — '
          'a temporary backend limit, not your vault storage quota.';
    }
    return null;
  }

  void _showSnack(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  void _appendAssistantMessage(String text) {
    if (!mounted) return;
    setState(() {
      msgs.add(_Msg('assistant', text));
    });
    _scrollToBottom();
  }

  /// Encrypt the parsed memory proposal locally under the active
  /// MVK-derived `memoryKey`, compute `memory_lookup_hash` via the
  /// derived `memoryLookupKey`, and POST to the ciphertext-first
  /// AI-memory endpoint. Fail-closed on any exception: no user-
  /// visible error, no fallback plaintext write. The chat reply
  /// already tells the user the memory was saved; a silent finalize
  /// failure is the correct privacy failure mode (nothing saved),
  /// and the user can re-issue the "remember this" instruction on
  /// the next turn.
  Future<void> _finalizeMemoryProposalBestEffort({
    required String jsonPayload,
    required String authToken,
  }) async {
    try {
      final decoded = jsonDecode(jsonPayload);
      if (decoded is! Map) return;
      final mt = decoded['memory_type'];
      final mk = decoded['memory_key'];
      final mv = decoded['memory_value'];
      final md = decoded['memory_event_date'];
      if (mt is! String || mt.isEmpty) return;
      if (mk is! String || mk.isEmpty) return;
      if (mv is! String || mv.isEmpty) return;
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      await client.tryZkFinalizeMemoryProposal(
        baseUrl: backendBaseUrl,
        authToken: authToken,
        memoryType: mt,
        memoryKey: mk,
        memoryValue: mv,
        memoryEventDate: md is String && md.isNotEmpty ? md : null,
      );
    } catch (_) {
      // Fail privacy-safe: never surface the parsed plaintext memory
      // in an error banner. Silent no-op = memory not saved =
      // correct ZK failure mode.
    }
  }

  void _askBrainAboutFile(_VaultStoredFile file) {
    if (!mounted) return;

    final handoff = buildAskBrainHandoff(
      fileId: file.id,
      fileName: file.fileName,
      savedName: file.savedName,
      mimeType: file.contentType,
      assetType: file.assetType,
      relativePath: file.relativePath,
      sizeBytes: file.fileSize,
    );

    setState(() {
      selectedSection = _DashboardSection.chat;

      input.clear();
      attachments.clear();
      msgs.addAll(handoff);
    });
    _scrollToBottom();
  }

  Future<void> _previewLocalAttachment(_Attachment attachment) async {
    await showDialog(
      context: context,
      useRootNavigator: false,
      builder: (dCtx) => AlertDialog(
        title: Text(attachment.name),
        content: Text(
          'Type: ${attachment.mimeType ?? 'unknown'}\n'
          'Size: ${_formatBytes(attachment.size)}\n\n'
          'Preview opens after the file is saved to your vault.',
        ),
        actions: [
          TextButton(
              key: const Key('attachment_preview_dialog_close'),
              onPressed: () => Navigator.pop(dCtx),
              child: const Text('Close')),
        ],
      ),
    );
  }

  Future<Map<String, dynamic>> _chunkedUpload({
    required VaultAIClient client,
    required String vaultName,
    required String pin,
    required String authToken,
    required List<int> keyBytes,
    required String filename,
    required String? mimeType,
    required Uint8List bytes,
    required void Function(double progress) onProgress,
    bool isBatchUpload = false,
    String? relativePath,
    String? importId,
    String? contentSha256,
  }) async {
    final init = await client.initChunkedUpload(
      vaultName: vaultName,
      pin: pin,
      authToken: authToken,
      filename: filename,
      contentType: mimeType,
      totalBytes: bytes.length,
      chunkSize: kChunkedUploadChunkBytes,
      isBatchUpload: isBatchUpload,
      relativePath: relativePath,
      importId: importId,
      contentSha256: contentSha256,
    );

    final fileId = init['file_id'] as String;
    final uploadToken = init['upload_token'] as String;
    final chunkSize = (init['chunk_size'] as num).toInt();
    final chunkCount = (init['chunk_count'] as num).toInt();

    try {
      for (var i = 0; i < chunkCount; i++) {
        final start = i * chunkSize;
        final end = (i == chunkCount - 1) ? bytes.length : start + chunkSize;
        final slice = bytes.sublist(start, end);

        final frame = await encryptChunk(
          plaintext: slice,
          key: keyBytes,
          chunkIndex: i,
        );

        await client.uploadChunk(
          authToken: authToken,
          fileId: fileId,
          chunkIndex: i,
          uploadToken: uploadToken,
          chunkFrameBytes: frame,
        );
        onProgress((i + 1) / chunkCount);
      }

      final fin = await client.finalizeChunkedUpload(
        authToken: authToken,
        vaultName: vaultName,
        pin: pin,
        fileId: fileId,
      );

      return {
        'status': 'uploaded',
        'file_id': fileId,
        'filename': filename,
        'content_type': mimeType,
        'size': (fin['file_size'] as num?)?.toInt() ?? bytes.length,
        'message': 'Uploaded $filename.',
      };
    } catch (e) {
      try {
        await client.abortChunkedUpload(
          authToken: authToken,
          vaultName: vaultName,
          pin: pin,
          fileId: fileId,
        );
      } catch (_) {}
      rethrow;
    }
  }

  void _cancelActiveUploads() {
    if (!mounted) return;
    if (!_uploadQueue.isBusy) return;

    final ctx = _currentUploadContext;
    if (ctx?.importId != null) {
      ctx!.client
          .cancelImport(
            vaultName: ctx.vaultName,
            pin: ctx.pin,
            authToken: ctx.authToken,
            importId: ctx.importId!,
          )
          .catchError((_) => <String, dynamic>{});
    }
    _uploadQueue.cancelAll();
    _showSnack('Upload cancelled.');
  }

  Future<_UploadAttachmentsOutcome> _uploadAttachments({
    required VaultAIClient client,
    required String vaultName,
    required String pin,
    required String authToken,
    required List<_Attachment> pendingAttachments,
    String? accompanyingText,
  }) async {
    final preUploadedIds = <String>[];
    final freshAttachments = <_Attachment>[];
    for (final a in pendingAttachments) {
      if (a.uploaded && a.uploadedFileId != null) {
        preUploadedIds.add(a.uploadedFileId!);
      } else {
        freshAttachments.add(a);
      }
    }

    if (freshAttachments.isEmpty) {
      return _UploadAttachmentsOutcome(
        uploadedIds: preUploadedIds,
        autoNamedAny: false,
      );
    }

    final app = context.read<AppState>();
    final hasAccompanyingText =
        accompanyingText != null && accompanyingText.isNotEmpty;
    final freshCount = freshAttachments.length;
    final isMultiFileBatch = freshCount >= 2;

    List<int>? keyBytes;
    final needsChunked =
        freshAttachments.any((a) => a.size >= kChunkedUploadThresholdBytes);
    if (needsChunked) {
      keyBytes = await _VaultCrypto.currentKeyBytesOrThrow();
    }

    final hasFolderContext =
        freshAttachments.any((a) => a.relativePath != null);
    final shouldCreateBatch = isMultiFileBatch || hasFolderContext;
    String? importId;
    if (shouldCreateBatch) {
      String? rootFolderName;
      for (final a in freshAttachments) {
        if (a.relativePath == null) continue;
        final firstSeg = a.relativePath!.split('/').first;
        if (firstSeg.isNotEmpty) {
          rootFolderName = firstSeg;
          break;
        }
      }
      final totalBytesPlanned =
          freshAttachments.fold<int>(0, (acc, a) => acc + a.size);

      try {
        final batch = await client.startImport(
          vaultName: vaultName,
          pin: pin,
          authToken: authToken,
          rootFolderName: rootFolderName,
          totalFiles: freshAttachments.length,
          totalBytesPlanned: totalBytesPlanned,
        );
        importId = batch['import_id']?.toString();
      } on StorageLimitExceededException catch (e) {
        _showSnack(e.message);
        return _UploadAttachmentsOutcome(
          uploadedIds: preUploadedIds,
          autoNamedAny: false,
        );
      } catch (e) {
        if (kDebugMode) {
          debugPrint('startImport failed; proceeding without batch: $e');
        }
      }
    }

    for (final a in freshAttachments) {
      a.importId = importId;
    }

    _currentUploadContext = _UploadContext(
      client: client,
      vaultName: vaultName,
      pin: pin,
      authToken: authToken,
      keyBytes: keyBytes,
      accompanyingText: accompanyingText,
      isBatchUpload: isMultiFileBatch,
      uploadSafetyCapBytes: app.uploadSafetyCapBytes,
      importId: importId,
    );

    final jobs = [
      for (final a in freshAttachments)
        UploadJob(
          id: a.id,
          name: a.name,
          displayName: a.displayName,
          kind: a.kind,
          size: a.size,
          mimeType: a.mimeType,
          relativePath: a.relativePath,
          importId: a.importId,
          readBytes: a.readBytes,
        ),
    ];

    try {
      _uploadQueue.enqueueAll(jobs);
      await _uploadQueue.waitForIdle();
    } finally {
      _currentUploadContext = null;
    }

    if (importId != null) {
      final cancelledByUser = _uploadQueue.jobs.any(
        (j) => j.status == UploadJobStatus.cancelled,
      );
      if (!cancelledByUser) {
        try {
          await client.completeImport(
            vaultName: vaultName,
            pin: pin,
            authToken: authToken,
            importId: importId,
            failedCountDelta: _uploadQueue.failedCount,
          );
        } catch (e) {
          if (kDebugMode) {
            debugPrint('completeImport failed: $e');
          }
        }
      }
    }

    final uploadedIds = <String>[...preUploadedIds];
    var autoNamedAny = false;
    int multiFileSavedCount = 0;

    for (final a in freshAttachments) {
      final job = _findQueueJob(a.id);
      if (job == null) continue;
      if (job.status != UploadJobStatus.uploaded ||
          job.uploadedFileId == null) {
        if (job.status == UploadJobStatus.failed) {
          _showSnack(
            'Upload failed: ${a.name}. Open the import panel to retry.',
          );
        }
        continue;
      }

      a.uploaded = true;
      a.uploadedFileId = job.uploadedFileId;
      uploadedIds.add(job.uploadedFileId!);

      final res = job.lastResult;
      final autoNamed = res?.autoNamed ?? false;
      final message = res?.message;

      if (isMultiFileBatch) {
        multiFileSavedCount += 1;
      } else if (message != null && message.isNotEmpty) {
        final shouldDisplay = autoNamed || !hasAccompanyingText;
        if (shouldDisplay) {
          _appendAssistantMessage(message);
        }
      }

      if (autoNamed) {
        autoNamedAny = true;
      }
    }

    if (isMultiFileBatch &&
        !hasAccompanyingText &&
        (multiFileSavedCount > 0 ||
            _uploadQueue.skippedDuplicateCount > 0 ||
            _uploadQueue.renamedCount > 0 ||
            _uploadQueue.failedCount > 0)) {
      _appendAssistantMessage(
        formatImportSummary(
          savedCount: multiFileSavedCount,
          renamedCount: _uploadQueue.renamedCount,
          skippedDuplicateCount: _uploadQueue.skippedDuplicateCount,
          failedCount: _uploadQueue.failedCount,
        ),
      );
    }

    if (!_uploadQueue.hasFailures) {
      _uploadQueue.clearTerminal();
    }

    return _UploadAttachmentsOutcome(
      uploadedIds: uploadedIds,
      autoNamedAny: autoNamedAny,
    );
  }

  _Msg? _tryParseAssistantStructuredMessage(String text) {
    if (kDebugMode) {
      debugPrint(
        '[chat_bubble_parse] enter '
        'buffer_len=${text.length} '
        'first_char=${text.isEmpty ? "(empty)" : text[0]} '
        'last_char=${text.isEmpty ? "(empty)" : text[text.length - 1]}',
      );
    }
    final maybeCard = vcs_parser.parseVaultChatCardMessage(text);
    if (maybeCard != null) {
      return maybeCard;
    }

    final trimmed = text.trim();
    if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) return null;

    try {
      final decodedRaw = jsonDecode(trimmed);
      if (decodedRaw is! Map) return null;

      final Map<String, dynamic> decoded = decodedRaw is Map<String, dynamic>
          ? decodedRaw
          : decodedRaw.map<String, dynamic>(
              (k, v) => MapEntry(k.toString(), v),
            );
      final type = decoded['type']?.toString();
      if (type == 'vault_file' || type == 'vault_image') {
        final payload = <String, dynamic>{};
        final relativePath = decoded['relative_path']?.toString();
        if (relativePath != null && relativePath.isNotEmpty) {
          payload['relative_path'] = relativePath;
        }
        final assetType = decoded['asset_type']?.toString();
        if (assetType != null && assetType.isNotEmpty) {
          payload['asset_type'] = assetType;
        }
        // The backend's active-entity follow-up dispatcher can attach
        // a pending_action (open/view/download) so the frontend
        // triggers the corresponding UI immediately on receipt — the
        // user asked "download it" and expects a download to start,
        // not another card to click through.
        final pending = decoded['pending_action']?.toString();
        if (pending != null && pending.isNotEmpty) {
          payload['pending_action'] = pending;
        }
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? 'Here is your file.',
          kind: 'vault_file',
          fileId: decoded['file_id']?.toString(),
          fileName: decoded['file_name']?.toString(),
          mimeType: decoded['content_type']?.toString(),
          payload: payload.isEmpty ? null : payload,
        );
      }
      if (type == 'vault_file_list') {
        final filesRaw = decoded['files'];
        final files = filesRaw is List
            ? filesRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final payload = <String, dynamic>{
          'files': files,
        };
        final title = decoded['title']?.toString();
        if (title != null && title.isNotEmpty) {
          payload['title'] = title;
        }
        final requestedName = decoded['requested_name']?.toString();
        if (requestedName != null && requestedName.isNotEmpty) {
          payload['requested_name'] = requestedName;
        }
        if (decoded['count'] is int) {
          payload['count'] = decoded['count'];
        }
        if (decoded['total_count'] is int) {
          payload['total_count'] = decoded['total_count'];
        }
        if (decoded['more_count'] is int) {
          payload['more_count'] = decoded['more_count'];
        }
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'vault_file_list',
          payload: payload,
        );
      }
      if (type == 'vault_inventory') {
        final payload = <String, dynamic>{
          if (decoded['total_files'] is int)
            'total_files': decoded['total_files'],
          if (decoded['total_bytes'] is int)
            'total_bytes': decoded['total_bytes'],
          if (decoded['folder_count'] is int)
            'folder_count': decoded['folder_count'],
          'top_folders': (decoded['top_folders'] is List)
              ? (decoded['top_folders'] as List)
                  .whereType<Map>()
                  .map((m) => m.cast<String, dynamic>())
                  .toList()
              : const <Map<String, dynamic>>[],
          'type_counts': (decoded['type_counts'] is Map)
              ? (decoded['type_counts'] as Map).cast<String, dynamic>()
              : const <String, dynamic>{},
          'recent_files': (decoded['recent_files'] is List)
              ? (decoded['recent_files'] as List)
                  .whereType<Map>()
                  .map((m) => m.cast<String, dynamic>())
                  .toList()
              : const <Map<String, dynamic>>[],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'vault_inventory',
          payload: payload,
        );
      }
      if (type == 'travel_readiness') {
        final payload = <String, dynamic>{
          'confidence': decoded['confidence']?.toString() ?? 'blocked',
          'found': (decoded['found'] is List)
              ? (decoded['found'] as List).whereType<String>().toList()
              : const <String>[],
          'missing': (decoded['missing'] is List)
              ? (decoded['missing'] as List).whereType<String>().toList()
              : const <String>[],
          'expired': (decoded['expired'] is List)
              ? (decoded['expired'] as List)
                  .whereType<Map>()
                  .map((m) => m.cast<String, dynamic>())
                  .toList()
              : const <Map<String, dynamic>>[],
          'expiring_soon': (decoded['expiring_soon'] is List)
              ? (decoded['expiring_soon'] as List)
                  .whereType<Map>()
                  .map((m) => m.cast<String, dynamic>())
                  .toList()
              : const <Map<String, dynamic>>[],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'travel_readiness',
          payload: payload,
        );
      }
      if (type == 'credential_files') {
        final filesRaw = decoded['files'];
        final files = filesRaw is List
            ? filesRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final sectionsRaw = decoded['sections'];
        final sections = sectionsRaw is Map
            ? sectionsRaw.cast<String, dynamic>()
            : const <String, dynamic>{};
        final actionsRaw = decoded['actions'];
        final actions = actionsRaw is List
            ? actionsRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final payload = <String, dynamic>{
          'files': files,
          'sections': sections,
          'actions': actions,
          if (decoded['has_content_matches'] is bool)
            'has_content_matches': decoded['has_content_matches'],
          if (decoded['count'] is int) 'count': decoded['count'],
          if (decoded['scanned_count'] is int)
            'scanned_count': decoded['scanned_count'],
          if (decoded['not_scanned_count'] is int)
            'not_scanned_count': decoded['not_scanned_count'],
          if (decoded['is_partial'] is bool)
            'is_partial': decoded['is_partial'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'credential_files',
          payload: payload,
        );
      }
      if (type == 'deep_answer_progress') {
        final progress = (decoded['progress'] is Map)
            ? (decoded['progress'] as Map).cast<String, dynamic>()
            : const <String, dynamic>{};
        final payload = <String, dynamic>{
          if (decoded['job_id'] is String) 'job_id': decoded['job_id'],
          if (decoded['intent'] is String) 'intent': decoded['intent'],
          if (decoded['status'] is String) 'status': decoded['status'],
          'progress': progress,
          if (decoded['results'] is Map)
            'results': (decoded['results'] as Map).cast<String, dynamic>(),
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'deep_answer_progress',
          payload: payload,
        );
      }
      if (type == 'credential_extraction_review') {
        final recordsRaw = decoded['records'];
        final records = recordsRaw is List
            ? recordsRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final fileRaw = decoded['file'];
        final fileMap = fileRaw is Map
            ? fileRaw.cast<String, dynamic>()
            : const <String, dynamic>{};
        final payload = <String, dynamic>{
          'records': records,
          'file': fileMap,
          if (decoded['count'] is int) 'count': decoded['count'],
          if (decoded['text_available'] is bool)
            'text_available': decoded['text_available'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'credential_extraction_review',
          payload: payload,
        );
      }
      if (type == 'file_disambiguation') {
        final filesRaw = decoded['files'];
        final files = filesRaw is List
            ? filesRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final payload = <String, dynamic>{
          'files': files,
          'title': decoded['title']?.toString() ?? 'Which file do you mean?',
          if (decoded['context_kind'] is String)
            'context_kind': decoded['context_kind'],
          if (decoded['count'] is int) 'count': decoded['count'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'file_disambiguation',
          payload: payload,
        );
      }
      if (type == 'vault_brain_answer') {
        final evidenceRaw = decoded['evidence'];
        final evidence = evidenceRaw is List
            ? evidenceRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final coverageRaw = decoded['coverage'];
        final coverage = coverageRaw is Map
            ? coverageRaw.cast<String, dynamic>()
            : const <String, dynamic>{};
        final payload = <String, dynamic>{
          'evidence': evidence,
          'coverage': coverage,
          if (decoded['intent'] is String) 'intent': decoded['intent'],
          if (decoded['no_evidence'] is bool)
            'no_evidence': decoded['no_evidence'],
          if (decoded['coverage_note'] is String)
            'coverage_note': decoded['coverage_note'],
          if (decoded['retrieval_mode'] is String)
            'retrieval_mode': decoded['retrieval_mode'],
          if (decoded['breadth'] is String) 'breadth': decoded['breadth'],
          if (decoded['continuation_available'] is bool)
            'continuation_available': decoded['continuation_available'],
          if (decoded['count'] is int) 'count': decoded['count'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'vault_brain_answer',
          payload: payload,
        );
      }
      if (type == 'secure_item_results') {
        final itemsRaw = decoded['items'];
        final items = itemsRaw is List
            ? itemsRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final payload = <String, dynamic>{
          'items': items,
          if (decoded['count'] is int) 'count': decoded['count'],
          if (decoded['reveal'] is bool) 'reveal': decoded['reveal'],
          if (decoded['display_mode'] is String)
            'display_mode': decoded['display_mode'],
          if (decoded['category_filter'] is String)
            'category_filter': decoded['category_filter'],
          if (decoded['schema_version'] is String)
            'schema_version': decoded['schema_version'],
          if (decoded['copy_version'] is String)
            'copy_version': decoded['copy_version'],
          if (decoded['message'] is String) 'message': decoded['message'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'secure_item_results',
          payload: payload,
        );
      }
      if (type == 'vault_chat_card') {
        final intent = decoded['intent']?.toString() ?? '';
        final cardRaw = decoded['card'];
        final card = cardRaw is Map
            ? cardRaw.cast<String, dynamic>()
            : const <String, dynamic>{};
        final schema = decoded['schema']?.toString() ?? '';
        final payload = <String, dynamic>{
          'intent': intent,
          'card': card,
          if (schema.isNotEmpty) 'schema': schema,
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'vault_chat_card',
          payload: payload,
        );
      }
      if (type == 'crypto_wallet_action') {
        final payload = <String, dynamic>{
          'intent': decoded['intent']?.toString() ?? '',
          if (decoded['asset'] is String) 'asset': decoded['asset'],
          if (decoded['network'] is String) 'network': decoded['network'],
          if (decoded['amount'] is String) 'amount': decoded['amount'],
          if (decoded['amountUnit'] is String)
            'amountUnit': decoded['amountUnit'],
          if (decoded['destinationAddress'] is String)
            'destinationAddress': decoded['destinationAddress'],
          if (decoded['blockedReason'] is String)
            'blockedReason': decoded['blockedReason'],
          if (decoded['engineEnabled'] is bool)
            'engineEnabled': decoded['engineEnabled'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'crypto_wallet_action',
          payload: payload,
        );
      }
      if (type == 'file_search_results') {
        final resultsRaw = decoded['results'];
        final results = resultsRaw is List
            ? resultsRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];

        final schemaVersion = (decoded['schema_version'] as String?)?.trim();
        final copyVersion = (decoded['copy_version'] as String?)?.trim();
        if (kDebugMode) {
          print(
            '[file_search_results] '
            'schema_version=${schemaVersion ?? "(missing)"} '
            'copy_version=${copyVersion ?? "(missing)"} '
            'is_complete=${decoded['is_complete']} '
            'count=${decoded['count']}',
          );
        }
        final payload = <String, dynamic>{
          'results': results,
          if (decoded['query'] is String) 'query': decoded['query'],
          if (decoded['count'] is int) 'count': decoded['count'],
          if (decoded['pending_count'] is int)
            'pending_count': decoded['pending_count'],
          if (decoded['is_complete'] is bool)
            'is_complete': decoded['is_complete'],
          if (decoded['incomplete_reason'] is String)
            'incomplete_reason': decoded['incomplete_reason'],
          if (decoded['query_kind'] is String)
            'query_kind': decoded['query_kind'],
          if (decoded['weak_hits_dropped'] is int)
            'weak_hits_dropped': decoded['weak_hits_dropped'],
          if (schemaVersion != null && schemaVersion.isNotEmpty)
            'schema_version': schemaVersion,
          if (copyVersion != null && copyVersion.isNotEmpty)
            'copy_version': copyVersion,
          if (decoded['requested_person_name'] is String)
            'requested_person_name': decoded['requested_person_name'],
          if (decoded['candidate_id_docs_count'] is int)
            'candidate_id_docs_count': decoded['candidate_id_docs_count'],
          if (decoded['name_mismatch_count'] is int)
            'name_mismatch_count': decoded['name_mismatch_count'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'file_search_results',
          payload: payload,
        );
      }
      if (type == 'related_files_graph') {
        final relsRaw = decoded['relationships'];
        final relationships = relsRaw is List
            ? relsRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final anchorRaw = decoded['anchor'];
        final anchor = anchorRaw is Map<String, dynamic>
            ? anchorRaw
            : (anchorRaw is Map
                ? anchorRaw.cast<String, dynamic>()
                : const <String, dynamic>{});
        final payload = <String, dynamic>{
          'anchor': anchor,
          'relationships': relationships,
          if (decoded['count'] is int) 'count': decoded['count'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'related_files_graph',
          payload: payload,
        );
      }
      if (type == 'vault_relationship_clusters') {
        final clustersRaw = decoded['clusters'];
        final clusters = clustersRaw is List
            ? clustersRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final payload = <String, dynamic>{
          'clusters': clusters,
          if (decoded['count'] is int) 'count': decoded['count'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'vault_relationship_clusters',
          payload: payload,
        );
      }
      if (type == 'related_files') {
        final resultsRaw = decoded['results'];
        final results = resultsRaw is List
            ? resultsRaw
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList()
            : const <Map<String, dynamic>>[];
        final anchorRaw = decoded['anchor'];
        final anchor = anchorRaw is Map
            ? anchorRaw.cast<String, dynamic>()
            : const <String, dynamic>{};
        final payload = <String, dynamic>{
          'anchor': anchor,
          'results': results,
          if (decoded['count'] is int) 'count': decoded['count'],
        };
        return _Msg(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: 'related_files',
          payload: payload,
        );
      }

      final fallbackMessage = decoded['message']?.toString();
      if (type != null &&
          fallbackMessage != null &&
          fallbackMessage.isNotEmpty) {
        return _Msg('assistant', fallbackMessage);
      }

      if (type != null && type.isNotEmpty) {
        if (kDebugMode) {
          print(
            '[structured_message_parse] recognised envelope type '
            '"$type" but no matching renderer or fallback message. '
            'Displaying safe fallback so user never sees raw JSON.',
          );
        }
        return _Msg(
          'assistant',
          'I received a response but I can\'t render it here yet. '
              'Please make sure the app is up to date.',
        );
      }
    } catch (_) {}

    if (trimmed.length > 20 &&
        (trimmed.contains('"schema"') ||
            trimmed.contains('"cardType"') ||
            trimmed.contains('"type"'))) {
      if (kDebugMode) {
        print(
          '[structured_message_parse] JSON-shaped payload with no '
          'recognised type; showing safe fallback.',
        );
      }
      return _Msg(
        'assistant',
        'I received a response but I can\'t display it. '
            'Please try again.',
      );
    }

    return null;
  }

  Future<({Uint8List bytes, String? contentType, String fileName})>
      _fetchVaultFile({
    required VaultAIClient client,
    required String vaultName,
    required String pin,
    required String authToken,
    required String fileId,
    required String fallbackFileName,
    required String? fallbackMime,
  }) async {
    Map<String, dynamic>? manifest;
    try {
      manifest = await client.getDownloadManifest(
        authToken: authToken,
        vaultName: vaultName,
        pin: pin,
        fileId: fileId,
      );
    } catch (e) {
      final raw = e.toString().toLowerCase();
      final looksLikeMissingRoute =
          raw.contains('404') || raw.contains('not found');
      if (!looksLikeMissingRoute) rethrow;
      manifest = null;
    }

    if (manifest == null) {
      final payload = await client.downloadVaultFile(
        vaultName: vaultName,
        fileId: fileId,
        pin: pin,
        authToken: authToken,
      );
      final bytes = client.decodeDownloadedFileBytes(payload);
      return (
        bytes: bytes,
        contentType: fallbackMime,
        fileName: fallbackFileName,
      );
    }

    final mode = manifest['storage_mode']?.toString() ?? 'inline';
    final fileName = manifest['file_name']?.toString() ?? fallbackFileName;
    final mime = manifest['content_type']?.toString() ?? fallbackMime;

    if (mode == 'inline') {
      final payload = await client.downloadVaultFile(
        vaultName: vaultName,
        fileId: fileId,
        pin: pin,
        authToken: authToken,
      );
      final bytes = client.decodeDownloadedFileBytes(payload);
      return (bytes: bytes, contentType: mime, fileName: fileName);
    }

    if (mode != 'chunks') {
      throw Exception('Unsupported storage_mode from backend: $mode');
    }

    final keyBytes = await _VaultCrypto.currentKeyBytesOrThrow();
    final chunkCount = (manifest['chunk_count'] as num).toInt();
    final fileSize = (manifest['file_size'] as num).toInt();
    final downloadToken = manifest['download_token'] as String;

    final out = Uint8List(fileSize);
    var offset = 0;
    for (var i = 0; i < chunkCount; i++) {
      final frame = await client.downloadChunk(
        authToken: authToken,
        fileId: fileId,
        chunkIndex: i,
        downloadToken: downloadToken,
      );
      final plain = await decryptChunk(
        frame: frame,
        key: keyBytes,
        chunkIndex: i,
      );
      out.setRange(offset, offset + plain.length, plain);
      offset += plain.length;
    }
    if (offset != fileSize) {
      throw Exception(
        'Chunked download size mismatch (got $offset bytes, expected $fileSize).',
      );
    }
    return (bytes: out, contentType: mime, fileName: fileName);
  }

  Future<Map<String, dynamic>?> _fetchRelatedFilesEnvelope(
    String fileId,
  ) async {
    if (fileId.trim().isEmpty) return null;
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null || app.vaultId == null) {
      throw Exception('Session expired.');
    }
    final pin = await _VaultCrypto.currentPinOrThrow();
    final client = VaultAIClient(baseUrl: backendBaseUrl);
    return await client.fetchRelatedFiles(
      fileId: fileId,
      pin: pin,
      authToken: token,
    );
  }

  Future<void> _showRelatedFilesForFile(String fileId) async {
    if (fileId.trim().isEmpty) {
      _showSnack('Missing file information.');
      return;
    }
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null || app.vaultId == null) {
      _showSnack('Session expired.');
      return;
    }

    setState(() {
      msgs.add(_Msg('user', 'Show related files'));
    });
    _scrollToBottom();

    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final envelope = await client.fetchRelatedFiles(
        fileId: fileId,
        pin: pin,
        authToken: token,
      );

      if (!mounted) return;

      final anchorRaw = envelope['anchor'];
      final anchor = anchorRaw is Map
          ? anchorRaw.cast<String, dynamic>()
          : const <String, dynamic>{};
      final relsRaw = envelope['relationships'];
      final relationships = relsRaw is List
          ? relsRaw
              .whereType<Map>()
              .map((m) => m.cast<String, dynamic>())
              .toList()
          : const <Map<String, dynamic>>[];
      final message = (envelope['message'] as String?) ?? '';

      setState(() {
        msgs.add(_Msg(
          'assistant',
          message,
          kind: ChatMessage.kRelatedFilesGraph,
          payload: {
            'anchor': anchor,
            'relationships': relationships,
            'count': relationships.length,
          },
        ));
      });
      _scrollToBottom();
    } catch (e) {
      if (!mounted) return;
      _showSnack('Failed to load related files: $e');
    }
  }

  void _handleScanRemaining(ChatMessage credentialMsg) {
    unawaited(_kickOffDeepAnswerScan(credentialMsg));
  }

  Future<void> _kickOffDeepAnswerScan(ChatMessage credentialMsg) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null || app.vaultId == null) {
      _showSnack('Session expired. Sign in again to run a deep scan.');
      return;
    }
    final String pin;
    try {
      pin = await _VaultCrypto.currentPinOrThrow();
    } catch (_) {
      _showSnack(
        'Vault is locked. Unlock to scan the remaining files.',
      );
      return;
    }

    const intent = 'search_files_for_credentials';
    final normalizedQuery = normalizeDeepScanQuery('');

    if (isDeepScanActive(
      intent: intent,
      normalizedQuery: normalizedQuery,
    )) {
      _focusActiveDeepScanCard();
      return;
    }

    Map<String, dynamic> snapshot;
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      snapshot = await client.startDeepAnswer(
        pin: pin,
        authToken: token,
        intent: intent,
        query: '',
      );
    } catch (e) {
      if (!mounted) return;
      _showSnack('Failed to start deep scan: $e');
      return;
    }

    if (!mounted) return;

    final returnedJobId = (snapshot['job_id'] as String?) ?? '';
    final returnedStatus = (snapshot['status'] as String?) ?? 'scanning';

    if (returnedJobId.isNotEmpty && activeDeepScanJobId == returnedJobId) {
      _focusActiveDeepScanCard();
      return;
    }

    setState(() {
      _markPriorCredentialCardsStale();

      activeDeepScanJobId = returnedJobId.isNotEmpty ? returnedJobId : null;
      activeDeepScanIntent = intent;
      activeDeepScanQuery = normalizedQuery;
      activeDeepScanStatus = returnedStatus;
      activeDeepScanCardKey = GlobalKey();

      msgs.add(_Msg(
        'assistant',
        'Let me check your vault properly. '
            "I'll read the files before giving the result.",
        kind: ChatMessage.kDeepAnswerProgress,
        payload: snapshot,
      ));
    });
    _scrollToBottom();

    if (returnedStatus == 'ready') {
      _promoteDeepAnswerResult(snapshot);
    }
  }

  void _focusActiveDeepScanCard() {
    if (!mounted) return;
    _scrollToBottom();
    _showSnack('Scan is already running.');
  }

  void _markPriorCredentialCardsStale() {
    for (var i = 0; i < msgs.length; i++) {
      final m = msgs[i];
      if (m.kind != ChatMessage.kCredentialFiles) continue;
      final payload = m.payload;
      if (payload == null) continue;
      if (payload['stale'] == true) continue;
      final newPayload = <String, dynamic>{
        ...payload,
        'stale': true,
      };
      msgs[i] = _Msg(
        m.role,
        m.text,
        kind: m.kind,
        payload: newPayload,
        fileId: m.fileId,
        fileName: m.fileName,
        mimeType: m.mimeType,
      );
    }
  }

  Future<Map<String, dynamic>?> _pollDeepAnswerJob(String jobId) async {
    if (!mounted) return null;
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null || app.vaultId == null) return null;
    final String pin;
    try {
      pin = await _VaultCrypto.currentPinOrThrow();
    } catch (_) {
      return null;
    }
    Map<String, dynamic>? snap;
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      snap = await client.pollDeepAnswerJob(
        pin: pin,
        authToken: token,
        jobId: jobId,
      );
    } catch (_) {
      return null;
    }

    if (mounted && activeDeepScanJobId == jobId) {
      final newStatus = (snap['status'] as String?) ?? 'scanning';
      if (newStatus != activeDeepScanStatus) {
        scheduleMicrotask(() {
          if (!mounted) return;
          if (activeDeepScanJobId != jobId) return;
          setState(() {
            activeDeepScanStatus = newStatus;
            if (newStatus == 'failed') {
              activeDeepScanJobId = null;
              activeDeepScanIntent = null;
              activeDeepScanQuery = null;
            }
          });
        });
      }
    }
    return snap;
  }

  void _promoteDeepAnswerResult(Map<String, dynamic> snapshot) {
    if (!mounted) return;

    final status = (snapshot['status'] as String?) ?? '';
    if (status != 'ready') return;

    final results = snapshot['results'];
    if (results is! Map) return;
    final envelopeRaw = (results)['envelope'];
    if (envelopeRaw is! Map) return;
    final envelope = envelopeRaw.cast<String, dynamic>();
    final envelopeType = (envelope['type'] as String?) ?? '';
    if (envelopeType != 'credential_files') return;

    final envScanned = (envelope['scanned_count'] is int)
        ? envelope['scanned_count'] as int
        : 0;
    final envNotScanned = (envelope['not_scanned_count'] is int)
        ? envelope['not_scanned_count'] as int
        : 0;
    final envTotal = envScanned + envNotScanned;
    if (envTotal > 0 && envScanned == 0) {
      return;
    }

    final snapJobId = (snapshot['job_id'] as String?) ?? '';
    if (snapJobId.isNotEmpty) {
      final already = msgs.any((m) =>
          m.kind == ChatMessage.kCredentialFiles &&
          (m.payload?['deep_answer_job_id'] as String?) == snapJobId);
      if (already) return;
    }

    final filesRaw = envelope['files'];
    final files = filesRaw is List
        ? filesRaw
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final sectionsRaw = envelope['sections'];
    final sections = sectionsRaw is Map
        ? sectionsRaw.cast<String, dynamic>()
        : const <String, dynamic>{};
    final actionsRaw = envelope['actions'];
    final actions = actionsRaw is List
        ? actionsRaw
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    final payload = <String, dynamic>{
      'files': files,
      'sections': sections,
      'actions': actions,
      if (envelope['has_content_matches'] is bool)
        'has_content_matches': envelope['has_content_matches'],
      if (envelope['count'] is int) 'count': envelope['count'],
      if (envelope['scanned_count'] is int)
        'scanned_count': envelope['scanned_count'],
      if (envelope['not_scanned_count'] is int)
        'not_scanned_count': envelope['not_scanned_count'],
      if (envelope['is_partial'] is bool) 'is_partial': envelope['is_partial'],
      if (snapJobId.isNotEmpty) 'deep_answer_job_id': snapJobId,
    };
    setState(() {
      if (activeDeepScanJobId == snapJobId) {
        activeDeepScanJobId = null;
        activeDeepScanIntent = null;
        activeDeepScanQuery = null;
        activeDeepScanStatus = null;
        activeDeepScanCardKey = null;
      }
      msgs.add(_Msg(
        'assistant',
        (envelope['message'] as String?) ?? '',
        kind: ChatMessage.kCredentialFiles,
        payload: payload,
      ));
    });
    _scrollToBottom();
  }

  Future<void> _openVaultFileCard(_Msg msg) async {
    if (msg.fileId == null || msg.fileName == null) {
      _showSnack('Missing file information.');
      return;
    }

    final app = context.read<AppState>();
    // Per-file double-tap guard. beginFileView returns false if a
    // view fetch is already running for this file id — the second
    // tap becomes a no-op instead of firing another decrypt.
    if (!app.beginFileView(msg.fileId!)) return;
    // Remember which file the user just picked so a follow-up
    // "download it" / "delete it" targets THIS file, not whichever
    // one shares a filename.
    _rememberTappedFile(msg.fileId!);

    final token = app.sessionToken;
    if (token == null || app.vaultId == null || app.vaultName == null) {
      app.endFileView(msg.fileId!);
      _showSnack('Session expired.');
      return;
    }

    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);

      final fetched = await _fetchVaultFile(
        client: client,
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
        fileId: msg.fileId!,
        fallbackFileName: msg.fileName!,
        fallbackMime: msg.mimeType,
      );

      if (!mounted) return;
      final bytes = fetched.bytes;
      final mime = fetched.contentType;

      if (_isImageMime(mime)) {
        if (!mounted) return;
        await showDialog(
          context: context,
          useRootNavigator: false,
          builder: (dCtx) {
            final s = MediaQuery.of(dCtx).size;
            final w = (s.width - 32).clamp(240.0, 900.0);
            final h = (s.height - 120).clamp(200.0, 900.0);
            return Dialog(
              backgroundColor: Colors.black,
              insetPadding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
              child: ConstrainedBox(
                constraints: BoxConstraints(maxWidth: w, maxHeight: h),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    AppBar(
                      automaticallyImplyLeading: false,
                      backgroundColor: Colors.black,
                      title: Text(
                        msg.fileName!,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      actions: [
                        IconButton(
                          key: const Key('image_viewer_dialog_close'),
                          onPressed: () => Navigator.pop(dCtx),
                          icon: const Icon(Icons.close),
                        ),
                      ],
                    ),
                    Flexible(
                      child: InteractiveViewer(
                        child: Image.memory(bytes, fit: BoxFit.contain),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
        return;
      }

      if (_isVideoMime(mime)) {
        if (!mounted) return;
        await _openMediaDialog(
          fileName: msg.fileName!,
          bytes: bytes,
          mimeType: mime,
          isVideo: true,
        );
        return;
      }

      if (_isAudioMime(mime)) {
        if (!mounted) return;
        await _openMediaDialog(
          fileName: msg.fileName!,
          bytes: bytes,
          mimeType: mime,
          isVideo: false,
        );
        return;
      }

      if (_isTextPreviewable(mime, msg.fileName!)) {
        final text = utf8.decode(bytes, allowMalformed: true);
        if (!mounted) return;
        await showDialog(
          context: context,
          useRootNavigator: false,
          builder: (dCtx) {
            final s = MediaQuery.of(dCtx).size;
            final w = (s.width - 32).clamp(240.0, 600.0);
            final h = (s.height - 200).clamp(200.0, 500.0);
            return AlertDialog(
              insetPadding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
              title: Text(
                msg.fileName!,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              content: SizedBox(
                width: w,
                height: h,
                child: SingleChildScrollView(child: SelectableText(text)),
              ),
              actions: [
                TextButton(
                    key: const Key('text_viewer_dialog_close'),
                    onPressed: () => Navigator.pop(dCtx),
                    child: const Text('Close')),
              ],
            );
          },
        );
        return;
      }

      if ((mime ?? '').toLowerCase() == 'application/pdf') {
        if (!mounted) return;
        await _openPdfPreviewDialog(
          fileName: msg.fileName!,
          bytes: bytes,
        );
        return;
      }

      if (!mounted) return;
      await _showUnsupportedPreviewDialog(
        fileName: msg.fileName!,
        bytes: bytes,
        mimeType: mime,
      );
    } catch (e) {
      if (app.handleApiException(e)) return;

      _showSnack(friendlyVaultFileOpenError(e));
    } finally {
      // Always release the per-file lock — including when the fetch
      // threw before opening a dialog. Otherwise the button stays
      // stuck in the loading state.
      app.endFileView(msg.fileId!);
    }
  }

  /// Auto-trigger the backend-supplied pending action on a freshly
  /// received vault_file card. Only fires once per message — we use
  /// the payload's own `pending_action` flag which is cleared after
  /// dispatch so a rebuild does not re-fire the action.
  void _maybeTriggerPendingFileAction(_Msg msg) {
    if (msg.kind != 'vault_file') return;
    final payload = msg.payload;
    if (payload == null) return;
    final action = payload['pending_action']?.toString();
    if (action == null || action.isEmpty) return;
    // Clear so any subsequent rebuild does not re-dispatch.
    payload.remove('pending_action');
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (action == 'download') {
        _downloadVaultFileCard(msg);
      } else if (action == 'open' || action == 'view' || action == 'show') {
        _openVaultFileCard(msg);
      }
    });
  }

  /// Download the file bytes and hand them to the browser as a real
  /// file save. Distinct from `_openVaultFileCard`: no viewer dialog,
  /// no `HtmlElementView`, no `Image.memory` — just `_fetchVaultFile`
  /// then `FileDownloader().downloadBytes(...)` with the original
  /// filename + MIME preserved. Per-file lock guards against double
  /// taps.
  Future<void> _downloadVaultFileCard(_Msg msg) async {
    if (msg.fileId == null || msg.fileName == null) {
      _showSnack('Missing file information.');
      return;
    }
    final app = context.read<AppState>();
    if (!app.beginFileDownload(msg.fileId!)) return;
    _rememberTappedFile(msg.fileId!);
    final token = app.sessionToken;
    if (token == null || app.vaultId == null || app.vaultName == null) {
      app.endFileDownload(msg.fileId!);
      _showSnack('Session expired.');
      return;
    }
    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final fetched = await _fetchVaultFile(
        client: client,
        vaultName: app.vaultName!,
        pin: pin,
        authToken: token,
        fileId: msg.fileId!,
        fallbackFileName: msg.fileName!,
        fallbackMime: msg.mimeType,
      );
      if (!mounted) return;
      final ok = FileDownloader().downloadBytes(
        bytes: fetched.bytes,
        fileName:
            fetched.fileName.isNotEmpty ? fetched.fileName : msg.fileName!,
        mimeType: fetched.contentType ?? msg.mimeType,
      );
      if (!mounted) return;
      _showSnack(ok
          ? 'Download started: ${msg.fileName}'
          : 'Download failed. Try again.');
    } catch (e) {
      if (app.handleApiException(e)) return;
      _showSnack(friendlyVaultFileOpenError(e));
    } finally {
      app.endFileDownload(msg.fileId!);
    }
  }

  Future<void> _showUnsupportedPreviewDialog({
    required String fileName,
    required Uint8List bytes,
    required String? mimeType,
  }) async {
    await showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(fileName),
        content: Text(
          '${unsupportedPreviewMessage(mimeType: mimeType)}\n\n'
          'Size: ${_formatBytes(bytes.length)}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Close'),
          ),
          FilledButton.icon(
            onPressed: () {
              if (!kIsWeb) {
                _showSnack(
                  'Saving from the desktop app is not supported '
                  'yet. Use the web version to download this file.',
                );
                return;
              }
              final ok = FileDownloader().downloadBytes(
                bytes: bytes,
                fileName: fileName,
                mimeType: mimeType,
              );
              if (!ok && mounted) {
                _showSnack(
                  'Could not start the download. Check your '
                  'browser settings and try again.',
                );
              }
            },
            icon: const Icon(Icons.download_outlined),
            label: Text(AppLocalizations.of(context).commonDownload),
          ),
        ],
      ),
    );
  }

  Future<void> _openPdfPreviewDialog({
    required String fileName,
    required Uint8List bytes,
  }) async {
    final previewer = VaultPdfPreviewer();
    final canPreview = previewer.available && kIsWeb;
    if (!canPreview) {
      await _showPdfPreviewFailureDialog(
        fileName: fileName,
        bytes: bytes,
      );
      return;
    }
    final viewType = 'vault-pdf-${DateTime.now().microsecondsSinceEpoch}';
    final registered = previewer.register(
      viewType: viewType,
      bytes: bytes,
    );
    if (!registered) {
      previewer.dispose();
      await _showPdfPreviewFailureDialog(
        fileName: fileName,
        bytes: bytes,
      );
      return;
    }

    await showDialog(
      context: context,
      builder: (ctx) {
        final size = MediaQuery.of(ctx).size;
        return Dialog(
          insetPadding: const EdgeInsets.symmetric(
            horizontal: 24,
            vertical: 32,
          ),
          backgroundColor: const Color(0xFF1A1A1A),
          child: SizedBox(
            width: size.width * 0.9,
            height: size.height * 0.9,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                AppBar(
                  automaticallyImplyLeading: false,
                  backgroundColor: const Color(0xFF1A1A1A),
                  title: Text(fileName),
                  actions: [
                    IconButton(
                      tooltip: 'Download',
                      onPressed: () {
                        if (!kIsWeb) {
                          _showSnack(
                            'Saving from the desktop app is not '
                            'supported yet. Use the web version to '
                            'download this file.',
                          );
                          return;
                        }
                        final ok = FileDownloader().downloadBytes(
                          bytes: bytes,
                          fileName: fileName,
                          mimeType: 'application/pdf',
                        );
                        if (!ok && mounted) {
                          _showSnack(
                            'Could not start the download. Check '
                            'your browser settings and try again.',
                          );
                        }
                      },
                      icon: const Icon(Icons.download_outlined),
                    ),
                    IconButton(
                      tooltip: 'Close',
                      onPressed: () => Navigator.pop(ctx),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
                Expanded(
                  child: HtmlElementView(viewType: viewType),
                ),
              ],
            ),
          ),
        );
      },
    );
    previewer.dispose();
  }

  Future<void> _showPdfPreviewFailureDialog({
    required String fileName,
    required Uint8List bytes,
  }) async {
    await showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(fileName),
        content: Text(
          '${pdfPreviewFailedMessage()}\n\n'
          'Size: ${_formatBytes(bytes.length)}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Close'),
          ),
          FilledButton.icon(
            onPressed: () {
              if (!kIsWeb) {
                _showSnack(
                  'Saving from the desktop app is not supported '
                  'yet. Use the web version to download this file.',
                );
                return;
              }
              final ok = FileDownloader().downloadBytes(
                bytes: bytes,
                fileName: fileName,
                mimeType: 'application/pdf',
              );
              if (!ok && mounted) {
                _showSnack(
                  'Could not start the download. Check your '
                  'browser settings and try again.',
                );
              }
            },
            icon: const Icon(Icons.download_outlined),
            label: Text(AppLocalizations.of(context).commonDownload),
          ),
        ],
      ),
    );
  }

  Future<void> _openMediaDialog({
    required String fileName,
    required Uint8List bytes,
    required String? mimeType,
    required bool isVideo,
  }) async {
    if (!kIsWeb) {
      await _openMediaMetadataDialog(
        fileName: fileName,
        bytes: bytes,
        mimeType: mimeType,
        isVideo: isVideo,
        reason: 'In-app playback is currently web-only.',
      );
      return;
    }

    if (!MediaPlayer.canPlay(mimeType: mimeType, isVideo: isVideo)) {
      await _openMediaMetadataDialog(
        fileName: fileName,
        bytes: bytes,
        mimeType: mimeType,
        isVideo: isVideo,
        reason:
            'This browser does not report playback support for ${mimeType ?? 'this format'}.',
      );
      return;
    }

    final player = MediaPlayer();
    final viewType =
        'vault-media-${isVideo ? 'video' : 'audio'}-${DateTime.now().microsecondsSinceEpoch}';
    final registered = player.register(
      viewType: viewType,
      bytes: bytes,
      mimeType: mimeType,
      isVideo: isVideo,
    );
    if (!registered) {
      player.dispose();
      await _openMediaMetadataDialog(
        fileName: fileName,
        bytes: bytes,
        mimeType: mimeType,
        isVideo: isVideo,
        reason: 'Could not prepare in-app playback for this file.',
      );
      return;
    }

    try {
      if (!mounted) return;
      await showDialog(
        context: context,
        useRootNavigator: false,
        builder: (dCtx) {
          final s = MediaQuery.of(dCtx).size;
          final w = (s.width - 32).clamp(240.0, 480.0);
          final maxH = (s.height - 200).clamp(120.0, 400.0);
          final videoH = isVideo ? maxH.clamp(160.0, 320.0) : 80.0;
          return AlertDialog(
            insetPadding:
                const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
            title: Text(
              fileName,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            content: SizedBox(
              width: w,
              height: videoH,
              child: Stack(
                children: [
                  Positioned.fill(
                    child: HtmlElementView(viewType: viewType),
                  ),
                  Positioned(
                    left: 0,
                    right: 0,
                    bottom: 0,
                    child: ValueListenableBuilder<String?>(
                      valueListenable: player.errorNotifier,
                      builder: (_, err, __) {
                        if (err == null) return const SizedBox.shrink();
                        return Container(
                          key: const Key('media_video_dialog_error_banner'),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 12, vertical: 8),
                          color: const Color(0xCC000000),
                          child: Row(
                            children: [
                              const Icon(Icons.error_outline,
                                  color: Color(0xFFFFB4A2), size: 18),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  err,
                                  style: const TextStyle(
                                      color: Color(0xFFFFB4A2), fontSize: 13),
                                ),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                key: const Key('media_video_dialog_close'),
                // Close pops THIS dialog only. Using dCtx (the dialog's
                // BuildContext) — not the ChatDashboardPage's context —
                // guarantees the popped route is the DialogRoute even if
                // the tree ever nests navigators. Without useRootNavigator
                // + this fix, on some browsers/Flutter web configurations
                // the HtmlElementView video element's blob-URL revocation
                // in `finally { player.dispose(); }` fires a MediaError
                // right as the Flutter shell is between routes — a stray
                // reload then puts the user back on /pin.
                onPressed: () => Navigator.pop(dCtx),
                child: const Text('Close'),
              ),
            ],
          );
        },
      );
    } finally {
      // Defer the blob-URL revocation to the frame AFTER the dialog is
      // dismissed and the HtmlElementView has been removed from the
      // DOM. Doing this in the same microtask as the pop occasionally
      // fires a `MediaError` on Chromium — which on Flutter web is
      // observable as an unhandled `error` event that reloads the
      // shell. This scheduleMicrotask → Future.delayed pattern lets
      // the platform-view detach first.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        Future<void>.delayed(const Duration(milliseconds: 100), () {
          try {
            player.dispose();
          } catch (_) {}
        });
      });
    }
  }

  Future<void> _openMediaMetadataDialog({
    required String fileName,
    required Uint8List bytes,
    required String? mimeType,
    required bool isVideo,
    required String reason,
  }) async {
    if (!mounted) return;
    final kind = isVideo ? 'Video' : 'Audio';
    await showDialog(
      context: context,
      useRootNavigator: false,
      builder: (dCtx) => AlertDialog(
        title: Text(fileName),
        content: Text(
          '$kind decrypted in memory.\n\n'
          'Type: ${mimeType ?? (isVideo ? 'video' : 'audio')}\n'
          'Size: ${_formatBytes(bytes.length)}\n\n'
          '$reason The file stays encrypted at rest and was decrypted only '
          'for this view.',
        ),
        actions: [
          TextButton(
            key: const Key('media_metadata_dialog_close'),
            onPressed: () => Navigator.pop(dCtx),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  String? _mainnetNetworkForAsset(String asset) {
    switch (asset) {
      case 'ETH':
      case 'USDT_ERC20':
      case 'USDC_ERC20':
        return 'ethereum_mainnet';
      case 'SOL':
        return 'solana_mainnet';
      case 'USDT_TRC20':
        return 'tron_mainnet';
      default:
        return null;
    }
  }

  Map<String, dynamic> _unavailableBalance(String reason) => {
        'balanceStatus': 'unavailable',
        'reason': reason,
        'availableAmount': null,
      };

  Future<Map<String, dynamic>> _fetchCryptoBalanceForChatCard({
    required String asset,
    required String address,
  }) async {
    if (asset.isEmpty || address.isEmpty) {
      return _unavailableBalance('missing_input');
    }
    if (asset == 'XMR') {
      return _unavailableBalance('scanner_gated');
    }
    final network = _mainnetNetworkForAsset(asset);
    if (network == null) {
      return _unavailableBalance('unsupported_asset');
    }
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) {
      return _unavailableBalance('not_authenticated');
    }
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.getCryptoWalletBalanceNetwork(
        network: network,
        asset: asset,
        authToken: token,
        address: address,
      );
      return result;
    } catch (e) {
      return _unavailableBalance('network_error');
    }
  }

  Map<String, dynamic> _unavailableActivity(String reason) => {
        'activityStatus': 'unavailable',
        'reason': reason,
        'transactions': const <dynamic>[],
      };

  Future<Map<String, dynamic>> _fetchCryptoActivityForChatCard({
    required String asset,
    required String address,
    int limit = 10,
  }) async {
    if (asset.isEmpty) return _unavailableActivity('missing_input');
    if (asset == 'XMR') {
      return _unavailableActivity('scanner_gated');
    }
    final network = _mainnetNetworkForAsset(asset);
    if (network == null) {
      return _unavailableActivity('unsupported_asset');
    }
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null) {
      return _unavailableActivity('not_authenticated');
    }
    try {
      final client = VaultAIClient(baseUrl: backendBaseUrl);
      final result = await client.listCryptoWalletTransactionsNetwork(
        network: network,
        asset: asset,
        authToken: token,
        limit: limit,
      );
      return result;
    } catch (e) {
      return _unavailableActivity('network_error');
    }
  }

  Future<void> _sendQuickPrompt(String text) async {
    setState(() {
      selectedSection = _DashboardSection.chat;
      input.text = text;
    });
    await Future.delayed(const Duration(milliseconds: 50));
    await _send();
  }

  /// Dispatcher for structured card actions surfaced through the
  /// chat bubble → chat message list plumbing. Actions carry a
  /// (msg, action, data) tuple. Today we route:
  ///   * select_login_by_id — the user tapped a specific login row
  ///     in the list. We display a natural chat prompt AND set
  ///     `_nextSelectionHint` so the backend gets the row's stable
  ///     id via /chat body — the id never appears in visible prose.
  ///   * choose_login — legacy chooser-card path (title only).
  ///     Retained for backwards compatibility; also sends a natural
  ///     prompt without a hint.
  Future<void> _handleChatCardAction(
    _Msg msg,
    String action,
    Map<String, dynamic>? data,
  ) async {
    if (action == 'select_login_by_id') {
      final id = (data?['id'] as String?)?.trim() ?? '';
      final title = (data?['title'] as String?)?.trim() ?? '';
      if (id.isEmpty) return;
      _nextSelectionHint = {
        'kind': 'login',
        'id': id,
      };
      final prompt =
          title.isEmpty ? 'Show my selected login' : 'Show my $title login';
      _sendQuickPrompt(prompt);
      return;
    }
    if (action == 'choose_login') {
      final title = (data?['query'] as String?)?.trim() ?? '';
      if (title.isEmpty) return;
      _sendQuickPrompt('Show my $title login');
      return;
    }
    if (action == 'select_file_by_id') {
      final id = (data?['id'] as String?)?.trim() ?? '';
      final title = (data?['title'] as String?)?.trim() ?? '';
      if (id.isEmpty) return;
      _nextSelectionHint = {
        'kind': 'file',
        'id': id,
      };
      final prompt =
          title.isEmpty ? 'Show my selected file' : 'Show my $title file';
      _sendQuickPrompt(prompt);
      return;
    }
    // 2026-08-01 generated-login draft Save / Cancel from the card
    // button row. Both re-enter the /chat endpoint as a natural-
    // language message the backend state machine already knows how
    // to consume:
    //   "save it"  -> state machine calls consume_draft(...) +
    //                  save_secret_tool(...) — persists the draft.
    //   "cancel"   -> state machine ACTION_CANCEL branch — clears
    //                  the pending draft + the active entity pin.
    if (action == 'generated_login_save') {
      final draftId = (data?['draft_id'] as String?)?.trim() ?? '';
      final service = (data?['service'] as String?)?.trim() ?? '';
      if (zkV2CredentialWriteEnabled && draftId.isNotEmpty) {
        final repository = _credentialV2Repository(context.read<AppState>());
        final username = data?['username']?.toString() ?? '';
        final password = data?['password']?.toString() ?? '';
        if (repository == null ||
            service.isEmpty ||
            username.isEmpty ||
            password.isEmpty) {
          _showSnack('This generated login cannot be saved securely yet.');
          return;
        }
        final recordDigest = sha256.convert(utf8.encode(draftId)).toString();
        final recordId = 'generated-${recordDigest.substring(0, 32)}';
        final credential = CredentialV2Plaintext(
          service: service,
          username: username,
          password: password,
          url: data?['url']?.toString(),
          notes: data?['notes']?.toString(),
        );
        try {
          await repository.create(
            recordId: recordId,
            credential: credential,
            serviceForLookup: service,
          );
          final readBack = await repository.reveal(recordId);
          if (!readBack.semanticallyEquals(credential)) {
            throw StateError('generated credential verification failed');
          }
          CredentialV2QaDiagnostics.remember(recordId, credential);
          await repository.api.finalizeGeneratedDraft(
            recordId: recordId,
            draftId: draftId,
          );
          _appendAssistantMessage('Saved your ${service.trim()} login.');
          unawaited(_loadVaultLogins());
        } catch (_) {
          _showSnack(
              'Could not securely save this generated login. Retry is safe.');
          rethrow;
        }
        return;
      }
      if (draftId.isNotEmpty) {
        _nextSelectionHint = {
          'kind': 'generated_login_draft',
          'id': draftId,
          if (service.isNotEmpty) 'service': service,
        };
      }
      _sendQuickPrompt('save it');
      return;
    }
    if (action == 'generated_login_cancel') {
      final draftId = (data?['draft_id'] as String?)?.trim() ?? '';
      final service = (data?['service'] as String?)?.trim() ?? '';
      if (zkV2CredentialWriteEnabled && draftId.isNotEmpty) {
        final repository = _credentialV2Repository(context.read<AppState>());
        if (repository == null) {
          _showSnack('Could not cancel this generated login.');
          return;
        }
        try {
          await repository.api.cancelGeneratedDraft(draftId);
          _appendAssistantMessage('Generated login cancelled.');
        } catch (_) {
          _showSnack('Could not cancel this generated login.');
          rethrow;
        }
        return;
      }
      if (draftId.isNotEmpty) {
        _nextSelectionHint = {
          'kind': 'generated_login_draft',
          'id': draftId,
          if (service.isNotEmpty) 'service': service,
        };
      }
      _sendQuickPrompt('cancel');
      return;
    }
    if (action == 'memory_proposal_save') {
      final payload =
          data == null ? <String, dynamic>{} : Map<String, dynamic>.from(data);
      await _saveMemoryProposalFromCard(payload);
      return;
    }
    if (action == 'memory_proposal_cancel') {
      _appendAssistantMessage('Memory proposal cancelled.');
      return;
    }
  }

  Future<void> _saveMemoryProposalFromCard(
    Map<String, dynamic> payload,
  ) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    if (token == null || vaultName == null || vaultName.isEmpty) {
      _showSnack('Session expired. Please sign in again.');
      throw StateError('memory_save_session_unavailable');
    }
    try {
      final pin = await _VaultCrypto.currentPinOrThrow();
      final result = await VaultAIClient(baseUrl: backendBaseUrl).createMemory(
        authToken: token,
        vaultName: vaultName,
        pin: pin,
        data: payload,
      );
      final message = (result['message'] as String?)?.trim();
      _appendAssistantMessage(
        message == null || message.isEmpty ? 'Memory saved.' : message,
      );
      _showSnack('Memory saved');
    } on InvalidVaultUnlockException {
      _showSnack('Your vault is locked. Please enter your PIN again.');
      throw StateError('memory_save_vault_locked');
    } catch (e) {
      _showSnack('Could not save memory.');
      throw StateError('memory_save_failed');
    }
  }

  /// One-shot selection hint attached to the NEXT chat POST. Cleared
  /// after send. The hint is a structured field on the /chat body —
  /// it never appears in the user-visible chat prose.
  Map<String, String>? _nextSelectionHint;

  /// The last file id the user opened/downloaded via a direct card
  /// tap (i.e. without a chat prompt in between). Set from
  /// `_openVaultFileCard` and `_downloadVaultFileCard` so the next
  /// chat message ("download it", "delete it", "rename it") targets
  /// the file the user just touched, even for files that share a
  /// filename. Cleared when consumed as a hint, or when a chat
  /// response resets the active entity.
  String? _lastTappedFileId;

  void _rememberTappedFile(String fileId) {
    if (fileId.isEmpty) return;
    _lastTappedFileId = fileId;
    // If no explicit hint is already queued, use the tapped file as
    // the default. An explicit row tap that already staged a hint
    // wins (staged hints are always fresher).
    _nextSelectionHint ??= {'kind': 'file', 'id': fileId};
  }

  /// Backend re-emits the paginated file-list envelope when the user
  /// says "show more". This helper acquires the per-session lock,
  /// emits the prompt, and releases the lock on completion — so
  /// rapid taps of Show more become a single request.
  Future<void> _requestMoreFiles() async {
    final app = context.read<AppState>();
    if (!app.beginShowMoreFiles()) return;
    try {
      await _sendQuickPrompt('show more');
    } finally {
      app.endShowMoreFiles();
    }
  }

  void _handleCryptoWalletChatAction(CryptoWalletActionRequest request) {
    if (request.blockedReason != null && request.blockedReason!.isNotEmpty) {
      return;
    }
    final asset = (request.asset ?? 'ETH').toUpperCase();

    if (selectedSection != _DashboardSection.cryptoVault) {
      setState(() {
        selectedSection = _DashboardSection.cryptoVault;
      });
    }

    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      switch (request.intent) {
        case kCryptoWalletActionIntentSendDraft:
          await _openSendPanelFromChat(asset, request);
          break;
        case kCryptoWalletActionIntentReceiveAddress:
        case kCryptoWalletActionIntentReceiveQr:
          _openReceivePanelFromChat(asset);
          break;
        default:
          break;
      }
    });
  }

  void _openReceivePanelFromChat(String asset) {
    final app = context.read<AppState>();
    final authToken = app.sessionToken;
    final hasVaultKey = app.vaultId != null &&
        app.vaultName != null &&
        _VaultCrypto.hasKeyFor(
          vaultId: app.vaultId!,
          vaultName: app.vaultName!,
        );
    if (authToken == null || !hasVaultKey) {
      _showSnack(
        'Unlock your vault with your PIN before opening the wallet '
        'receive panel.',
      );
      return;
    }
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetCtx) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.of(sheetCtx).size.height * 0.85,
          ),
          child: SingleChildScrollView(
            child: CryptoWalletEngineReceivePanel(
              key: Key('chat_receive_panel_$asset'),
              authToken: authToken,
              client: VaultAIClient(baseUrl: backendBaseUrl),
              encryptForVault: (plaintext) => _VaultCrypto.encrypt(plaintext),
              isVaultKeyAvailable: () => hasVaultKey,
              asset: asset,
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _openSendPanelFromChat(
    String asset,
    CryptoWalletActionRequest request,
  ) async {
    final app = context.read<AppState>();
    final authToken = app.sessionToken;
    final hasVaultKey = app.vaultId != null &&
        app.vaultName != null &&
        _VaultCrypto.hasKeyFor(
          vaultId: app.vaultId!,
          vaultName: app.vaultName!,
        );
    if (authToken == null || !hasVaultKey) {
      _showSnack(
        'Unlock your vault with your PIN before opening the wallet '
        'send panel.',
      );
      return;
    }

    String? fromAddress;
    try {
      final body =
          await VaultAIClient(baseUrl: backendBaseUrl).getCryptoWalletReceive(
        asset: 'ETH',
        authToken: authToken,
      );
      final status = (body['wallet_engine'] ?? '').toString();
      if (status == 'receive_ready') {
        final raw = body['publicAddress'];
        if (raw is String && raw.isNotEmpty) fromAddress = raw;
      }
    } catch (_) {
      fromAddress = null;
    }
    if (fromAddress == null || fromAddress.isEmpty) {
      _showSnack(
        'Create your Ethereum Sepolia wallet first. Open the ETH '
        'card and tap Receive.',
      );
      return;
    }
    final resolvedFromAddress = fromAddress;
    if (!mounted) return;
    // 2026-07-13: migrate the chat structured-action send sheet onto
    // `showCryptoWalletSheet` so it inherits the shared chrome (drag
    // handle, close X, escape-to-close) and lets
    // `WalletSendScaffold` manage the sticky Review button + keyboard
    // padding. Previously this used a bare `showModalBottomSheet`
    // with a `ConstrainedBox`, so the chat-triggered send sheet
    // lacked a visible close control.
    final shortAsset = switch (asset) {
      'USDT_ERC20' => 'USDT',
      'USDC_ERC20' => 'USDC',
      _ => asset,
    };
    showCryptoWalletSheet<void>(
      context: context,
      title: 'Send $shortAsset',
      sheetKey: 'chat_send_sheet',
      bodyOwnsLayout: true,
      child: CryptoWalletEngineSendPanel(
        key: Key('chat_send_panel_$asset'),
        authToken: authToken,
        fromAddress: resolvedFromAddress,
        client: VaultAIClient(baseUrl: backendBaseUrl),
        decryptForVault: (ciphertext) => _VaultCrypto.decrypt(ciphertext),
        isVaultKeyAvailable: () => hasVaultKey,
        verifyPin: (pin) async {
          final cachedPin = _VaultCrypto.cachedPinFor(
            vaultId: app.vaultId ?? '',
            vaultName: app.vaultName ?? '',
          );
          if (cachedPin == null) return false;
          return cachedPin == pin;
        },
        asset: asset,
        prefilledDestination: request.destinationAddress,
        prefilledAmount: request.amount,
        mainnetApprovalSession: _chatMainnetSendApprovalSession,
      ),
    ).whenComplete(_chatMainnetSendApprovalSession.clear);
  }

  /// Regex covering the ACCOUNT-USERNAME intent set — questions
  /// specifically about the human login identifier the user typed
  /// at signup. Anchored + case-insensitive so casual chat and
  /// AI-side identity questions do NOT match
  /// and fall through cleanly to the LLM with the corrected
  /// identity context.
  ///
  /// Deliberately excludes "vault name" and "which vault am I in"
  /// — both are ambiguous with the vault-AI identity concept and
  /// belong on the LLM path so the AI can answer specifically
  /// using its persistent identity profile. Only unambiguous
  /// login-identifier phrasings are intercepted here.
  static final RegExp _accountUsernameQueryRe = RegExp(
    r"^\s*(?:"
    r"what(?:'s|s|\s+is)?\s+(?:my\s+)?(?:username|account\s*name|login\s*name)"
    r"|what\s+username\s+did\s+i\s+register"
    r")\s*[.?!]?\s*$",
    caseSensitive: false,
  );

  /// Return true iff [text] matches the ACCOUNT-USERNAME intent
  /// (specifically the login identifier — not the vault AI name)
  /// AND we produced a direct reply from local state. Never hits
  /// the LLM path, never sends the raw canonical username to the
  /// backend, never surfaces the VLT handle / UUID / exception.
  ///
  /// AI-side identity questions are NOT intercepted here — they
  /// fall through to the LLM which answers using the server-
  /// injected vault-AI identity context.
  bool _tryDirectAccountUsernameReply(String text, AppState app) {
    if (!_accountUsernameQueryRe.hasMatch(text)) return false;
    final canonical = app.vaultName;
    final nickname = app.displayName;
    final String reply;
    if (canonical != null && canonical.isNotEmpty) {
      reply = 'Your username is $canonical.';
    } else if (nickname != null && nickname.isNotEmpty) {
      // Fallback for legacy accounts where the canonical username
      // was never captured on this device. Deliberately labels the
      // string as a nickname so we do NOT mislead the user into
      // treating the display name as their login identifier.
      reply = 'You haven\'t saved your username on this device. '
          'Your nickname here is $nickname.';
    } else {
      reply = 'You haven\'t saved your username on this device yet. '
          'Enter it on the sign-in screen.';
    }
    if (!mounted) return true;
    setState(() {
      msgs.add(_Msg('user', text));
      msgs.add(_Msg('assistant', reply));
    });
    _scrollToBottom();
    return true;
  }

  Future<bool> _tryLocalVaultFileLookupReply(String text) async {
    if (attachments.isNotEmpty) return false;
    final query = extractLocalFileLookupQuery(text);
    if (query == null) return false;

    if (vaultFiles.isEmpty && !loadingFiles) {
      await _loadVaultFiles();
    }
    if (!mounted) return true;

    final match = resolveLocalVaultFileLookup(
      query: query,
      files: vaultFiles.map((file) => VaultLocalFileLookupEntry(
            id: file.id,
            fileName: file.fileName,
            savedName: file.savedName,
            mimeType: file.contentType,
            assetType: file.assetType,
            relativePath: file.relativePath,
            sizeBytes: file.fileSize,
          )),
    );
    if (match == null) return false;

    final file = match.entry;
    final label = file.displayName;
    final savedName = (file.savedName ?? '').trim();
    final relativePath = (file.relativePath ?? '').trim();
    final assetType = (file.assetType ?? '').trim();
    final payload = <String, dynamic>{
      if (savedName.isNotEmpty) 'saved_name': savedName,
      if (relativePath.isNotEmpty) 'relative_path': relativePath,
      if (assetType.isNotEmpty) 'asset_type': assetType,
      if (file.sizeBytes > 0) 'size_bytes': file.sizeBytes,
    };

    setState(() {
      selectedSection = _DashboardSection.chat;
      _nextSelectionHint = {'kind': 'file', 'id': file.id};
      input.clear();
      msgs.add(_Msg('user', text));
      msgs.add(_Msg(
        'assistant',
        'Here is "$label" from your vault.',
        kind: ChatMessage.kVaultFile,
        fileId: file.id,
        fileName: file.fileName,
        mimeType: file.mimeType,
        payload: payload.isEmpty ? null : payload,
      ));
    });
    _scrollToBottom();
    return true;
  }

  Future<void> _send() async {
    final text = input.text.trim();
    if ((text.isEmpty && attachments.isEmpty) || sending) return;

    final app = context.read<AppState>();
    final token = app.sessionToken;

    if (token == null) {
      _appendAssistantMessage('Session expired. Please sign in again.');
      return;
    }

    final authToken = token;
    final vaultName = app.vaultName;
    final activeVaultId = app.vaultId;

    vlog('chat.preSend', {
      'vault_id': activeVaultId,
      'vaultName': vaultName,
      'unlocked': app.unlocked,
      'authTokenLen': authToken.length,
      'hasKeyForRequested': activeVaultId != null && vaultName != null
          ? _VaultCrypto.hasKeyFor(vaultId: activeVaultId, vaultName: vaultName)
          : false,
      'cryptoSnapshot': _VaultCrypto.debugSnapshot(),
    });

    if (!app.unlocked || vaultName == null) {
      _appendAssistantMessage(
          'Your vault is locked. Please enter your PIN again.');
      return;
    }

    if (activeVaultId == null ||
        !_VaultCrypto.hasKeyFor(vaultId: activeVaultId, vaultName: vaultName)) {
      vlog('chat.preSend.GUARD_TRIPPED', {
        'reason': activeVaultId == null
            ? 'no vault_id'
            : 'no key for (vault_id,vaultName)',
        'vault_id': activeVaultId,
        'vaultName': vaultName,
      });
      app.handleApiException(const InvalidVaultUnlockException());
      return;
    }

    // Deterministic ACCOUNT-USERNAME intent (login identifier only).
    // "What is my username" / "What's my account name" / "What
    // username did I register" is answered directly from
    // authenticated local state, without hitting the LLM path
    // (which would echo the VLT-* handle or return document
    // noise) and without sending the raw canonical username to
    // the backend. Never surfaces a raw exception, VLT handle,
    // UUID, or display name as the login identifier.
    //
    // AI-side identity questions deliberately do NOT match this
    // regex — they fall through to the LLM path where the server-
    // injected vault-AI identity context answers with the
    // persistent AI keeper's name and role.
    if (attachments.isEmpty && _tryDirectAccountUsernameReply(text, app)) {
      input.clear();
      return;
    }

    if (await _tryLocalCredentialV2LookupReply(text, app)) {
      return;
    }

    if (await _tryLocalVaultFileLookupReply(text)) {
      return;
    }

    setState(() {
      selectedSection = _DashboardSection.chat;
    });

    final client = VaultAIClient(baseUrl: backendBaseUrl);
    final replyLanguageCode = app.chatReplyLanguageCode;
    final rawPendingAttachments = attachments.map((a) => a.copy()).toList();
    final attachmentTitle = attachmentTitleFromComposerText(
      text,
      attachmentCount: rawPendingAttachments.length,
    );
    final pendingAttachments = attachmentTitle == null
        ? rawPendingAttachments
        : [
            for (var i = 0; i < rawPendingAttachments.length; i++)
              i == 0
                  ? rawPendingAttachments[i].copy(displayName: attachmentTitle)
                  : rawPendingAttachments[i],
          ];

    if (pendingAttachments.isNotEmpty) {
      final plannedBytes =
          pendingAttachments.fold<int>(0, (acc, a) => acc + a.size);
      final usedBytes = app.storageUsedBytes;
      final limitBytes = app.effectiveStorageLimitBytes;
      final availableBytes =
          (limitBytes - usedBytes) < 0 ? 0 : (limitBytes - usedBytes);
      if (plannedBytes > availableBytes) {
        String? folderName;
        for (final a in pendingAttachments) {
          final firstSlash = a.name.indexOf('/');
          if (firstSlash > 0) {
            folderName = a.name.substring(0, firstSlash);
            break;
          }
        }
        final choice = await NotEnoughStorageDialog.show(
          context,
          plannedBytes: plannedBytes,
          availableBytes: availableBytes,
          folderName: folderName,
        );
        if (!mounted) return;
        if (choice == StorageLimitDialogChoice.upgrade) {
          Navigator.pushNamed(context, '/storage');
        }

        return;
      }
    }

    final attachmentSummaries = pendingAttachments
        .map((a) => ChatAttachmentSummary(
              name: a.displayName ?? a.name,
              kind: a.kind,
              mimeType: a.mimeType,
              size: a.size,
            ))
        .toList(growable: false);
    final chatTicket = _chatRequests.begin();
    final chatRequestId = chatTicket.requestId;
    final userMessageId = chatTicket.userMessageId;
    final assistantMessageId = chatTicket.assistantMessageId;

    setState(() {
      sending = true;
      msgs.add(_Msg(
        'user',
        text,
        messageId: userMessageId,
        requestId: chatRequestId,
        attachments: attachmentSummaries.isEmpty ? null : attachmentSummaries,
      ));
      input.clear();
      attachments.clear();
    });
    _scrollToBottom();

    var uploadedFileIds = <String>[];
    final hadAttachments = pendingAttachments.isNotEmpty;
    var uploadCommitted = false;

    try {
      final pin = await _VaultCrypto.currentPinOrThrow();

      final uploadOutcome = await _uploadAttachments(
        client: client,
        vaultName: vaultName,
        pin: pin,
        authToken: authToken,
        pendingAttachments: pendingAttachments,
        accompanyingText: attachmentTitle == null ? text : null,
      );
      uploadedFileIds = uploadOutcome.uploadedIds;
      uploadCommitted = uploadedFileIds.isNotEmpty;

      if (hadAttachments) {
        await app.refreshVaultStats();
        await _loadVaultFiles();
        await _loadVaultLogins();
      }

      if (text.isEmpty && uploadedFileIds.isNotEmpty) {
        if (!mounted) return;
        _chatRequests.complete(chatRequestId);
        setState(() {
          sending = false;
        });
        return;
      }

      if (hadAttachments && attachmentTitle != null) {
        if (!mounted) return;
        _chatRequests.complete(chatRequestId);
        setState(() {
          sending = false;
        });
        return;
      }

      if (uploadOutcome.autoNamedAny) {
        if (!mounted) return;
        _chatRequests.complete(chatRequestId);
        setState(() {
          sending = false;
        });
        return;
      }

      setState(() {
        thinking = true;
        msgs.add(_Msg(
          'assistant',
          '',
          messageId: assistantMessageId,
          requestId: chatRequestId,
          replyToMessageId: userMessageId,
        ));
      });
      _scrollToBottom();
      final int assistantIndex = msgs.indexWhere(
        (message) => message.messageId == assistantMessageId,
      );
      if (assistantIndex < 0) {
        throw StateError('correlated assistant placeholder missing');
      }
      String buffer = '';
      // Per-send ZK memory-proposal state. The backend emits the
      // sentinel exactly once per turn, but SSE decoding may deliver
      // it across chunks — track whether we've already fired the
      // client finalize so we do not double-POST if the sentinel is
      // re-observed after buffer growth.
      bool memoryProposalFinalized = false;

      // 2026-07-22 atomic crypto context snapshot. This is the ONE
      // place the /chat send path samples the vault's key + KDF
      // metadata, and BOTH values come from the same immutable
      // VaultCryptoContext object. NEVER read the key and metadata
      // from separate getters — that produced the production
      // "encrypted with MVK, declared PBKDF2 metadata" ciphertext
      // whose server-side decrypt failed and mis-signed-out the
      // user. NEVER await between capturing the snapshot and
      // finishing the encrypt+request-build unless the SAME
      // snapshot object is retained.
      final ctxSnapshot = VaultCryptoRegistry.current;
      if (ctxSnapshot == null ||
          ctxSnapshot.vaultId != activeVaultId ||
          ctxSnapshot.vaultName != vaultName) {
        // No live context for the caller's vault. Do NOT force PIN
        // (that would be the pre-2026-07-22 silent-sign-out bug).
        // Surface a clear typed error and preserve the input; the
        // route guard will guide the user to /pin only when the
        // session itself is missing.
        vlog('chat.preSend.no_context', {
          'has_ctx': ctxSnapshot != null,
          'ctx_vault_id': ctxSnapshot?.vaultId,
          'ctx_vault_name': ctxSnapshot?.vaultName,
          'active_vault_id': activeVaultId,
          'active_vault_name': vaultName,
        });
        setState(() {
          sending = false;
          thinking = false;
          msgs.removeWhere((message) => message.requestId == chatRequestId);
          input.text = text;
          input.selection = TextSelection.collapsed(offset: text.length);
        });
        rootScaffoldMessengerKey.currentState?.clearSnackBars();
        rootScaffoldMessengerKey.currentState?.showSnackBar(
          const SnackBar(
            content: Text(
              'Vault crypto state is out of sync. Please tap send '
              'again.',
            ),
          ),
        );
        return;
      }
      final keyFp = await cryptoFingerprintForKey(ctxSnapshot.key);
      final saltFp = cryptoFingerprintForSaltBase64(ctxSnapshot.saltBase64);
      final encryptedMessage = await encryptWithContext(
        plaintext: text,
        context: ctxSnapshot,
      );
      vlog('chat.body.diag', {
        'chat_request_id': chatRequestId,
        'vault_id': ctxSnapshot.vaultId,
        'context_generation': ctxSnapshot.generation,
        'key_fp12': keyFp,
        'salt_fp12_sent': saltFp,
        'iterations_sent': ctxSnapshot.iterations,
        'kdf_fields_present': true,
        'encrypted_length': encryptedMessage.length,
      });

      final hintForThisSend = _nextSelectionHint;
      _nextSelectionHint = null;
      // The kdf metadata sent to the server MUST be the same fields
      // from the same ctxSnapshot the encryption used above — no
      // separate lookups. This is the atomicity contract the
      // production incident traced back to.
      final stream = client.chatStream(
        encryptedMessage: encryptedMessage,
        vaultName: vaultName,
        pin: pin,
        authToken: authToken,
        requestId: chatRequestId,
        uploadedFileIds: uploadedFileIds,
        appLocale: replyLanguageCode,
        selectionHint: hintForThisSend,
        kdfSaltUsed: ctxSnapshot.saltBase64,
        kdfIterationsUsed: ctxSnapshot.iterations,
      );
      final streamIterator = StreamIterator<String>(stream);
      _activeChatIterator = streamIterator;
      _activeChatRequestId = chatRequestId;

      try {
        while (await streamIterator.moveNext()) {
          if (!_chatRequests.acceptsEvents(chatRequestId)) break;
          final encryptedChunk = streamIterator.current;
          try {
            final decryptedChunk = await _VaultCrypto.decrypt(encryptedChunk);
            if (!mounted || !_chatRequests.acceptsEvents(chatRequestId)) {
              break;
            }
            buffer += decryptedChunk;

            // ZK memory-proposal sentinel: the backend emits
            // <<VAULTAI_MEMORY_PROPOSAL>>{json}<<END>> at the head
            // of the reply for ZK vaults. Strip it from the visible
            // buffer BEFORE any downstream parse/render, and fire
            // the client-side finalize (encrypt under memoryKey,
            // compute memory_lookup_hash, POST to
            // /vault/ciphertext/vault-ai-memory) exactly once. If
            // finalize fails (network drop, tab close, crypto
            // error) the memory is not saved — the correct ZK
            // failure mode. No plaintext ever hits the DB.
            final stripped = extractAndStripMemoryProposal(
              buffer: buffer,
              alreadyFinalized: memoryProposalFinalized,
            );
            buffer = stripped.strippedBuffer;
            if (stripped.jsonPayload != null && !memoryProposalFinalized) {
              memoryProposalFinalized = true;
              unawaited(_finalizeMemoryProposalBestEffort(
                jsonPayload: stripped.jsonPayload!,
                authToken: authToken,
              ));
            }

            // dart format off
            final structuredNow = _tryParseAssistantStructuredMessage(buffer);
            final _Msg replacement =
                (structuredNow ?? _Msg('assistant', buffer))
                    .withCorrelationFrom(msgs[assistantIndex]);
            // dart format on
            setState(() {
              msgs[assistantIndex] = replacement;
              thinking = false;
            });
            _scrollToBottom();
          } catch (e) {
            if (app.handleApiException(e)) return;
            if (!mounted) return;
            setState(() {
              thinking = false;
              msgs[assistantIndex] = _Msg(
                'assistant',
                friendlyChatGenerationFailure(text),
              ).withCorrelationFrom(msgs[assistantIndex]);
            });
          }
        }
      } catch (err) {
        // 2026-07-22: server 400 "Invalid PIN or corrupted data" is
        // NOT a session-expired condition and NOT an incorrect PIN
        // — it's a client-side crypto-context mismatch. Preserve
        // the user's input, drop the just-added user bubble, show
        // a typed snackbar, and keep everything else unchanged.
        // The atomic VaultCryptoContext + snapshot-once contract
        // above should prevent this from ever happening for a
        // modern client; if it does, we recover gracefully rather
        // than sign the user out.
        if (err is CryptoContextMismatchException) {
          if (!mounted) return;
          setState(() {
            thinking = false;
            sending = false;
            msgs.removeWhere((message) => message.requestId == chatRequestId);
            input.text = text;
            input.selection = TextSelection.collapsed(offset: text.length);
          });
          rootScaffoldMessengerKey.currentState?.clearSnackBars();
          rootScaffoldMessengerKey.currentState?.showSnackBar(
            SnackBar(content: Text(err.message)),
          );
          return;
        }
        // 2026-07-21: 409 kdf_generation_stale is a specific,
        // recoverable state — the client's declared (salt, iter)
        // did not match the server's current DB (something rotated
        // between our unlock and this send). Re-derive the key from
        // the fresh values in the response body, put the user's
        // text back in the input so they can send again, and show
        // a clear snackbar. NEVER force PIN re-entry for this
        // exception (the session is intact) and NEVER auto-retry
        // the send (would double-post the user's message).
        if (err is KdfGenerationStaleException) {
          bool rederived = false;
          final freshSalt = err.currentPinSalt;
          final freshIter = err.currentKdfIterations;
          if (freshSalt != null &&
              freshSalt.isNotEmpty &&
              freshIter != null &&
              freshIter > 0) {
            rederived = await app.applyFreshKdfMetadata(
              pinSaltBase64: freshSalt,
              iterations: freshIter,
            );
          }
          if (!mounted) return;
          setState(() {
            thinking = false;
            sending = false;
            // Drop the just-added user message (send failed) so the
            // chat log doesn't imply the message was received.
            msgs.removeWhere((message) => message.requestId == chatRequestId);
            // Put the text back in the input so the user can just
            // tap send again — no retyping.
            input.text = text;
            input.selection = TextSelection.collapsed(offset: text.length);
          });
          rootScaffoldMessengerKey.currentState?.clearSnackBars();
          if (rederived) {
            rootScaffoldMessengerKey.currentState?.showSnackBar(
              SnackBar(content: Text(err.message)),
            );
          } else {
            // Could not re-derive locally (no cached PIN, or the
            // server did not include current_pin_salt). Force a
            // fresh PIN entry with a specific, non-generic reason —
            // this is NOT the pre-2026-07-21 "unlock session
            // expired" silent bounce; the user has a clear
            // explanation.
            rootScaffoldMessengerKey.currentState?.showSnackBar(
              const SnackBar(
                content: Text(
                  'The vault was updated. Please enter your PIN '
                  'again to continue.',
                ),
              ),
            );
            rootNavigatorKey.currentState?.pushNamedAndRemoveUntil(
              '/pin',
              (_) => false,
            );
          }
          return;
        }
        // Route InvalidVaultUnlockException / VaultLockedException /
        // SessionTerminatedException / DeviceNotTrustedException
        // through the AppState handler so the vault re-locks, the
        // key cache is cleared, and the user lands on the correct
        // recovery screen. Without this, the SSE stream's outer
        // catch would paint the raw exception ("Error:
        // InvalidVaultUnlockException(message: ...)") straight into
        // the assistant bubble AND leave app.unlocked=true — the
        // 2026-07-20 dashboard-says-unlocked/chat-says-expired
        // desync symptom.
        if (app.handleApiException(err)) return;
        if (!mounted) return;
        setState(() {
          thinking = false;
          msgs[assistantIndex] = _Msg(
            'assistant',
            friendlyChatGenerationFailure(text),
          ).withCorrelationFrom(msgs[assistantIndex]);
        });
      } finally {
        await streamIterator.cancel();
        if (_activeChatRequestId == chatRequestId) {
          _activeChatIterator = null;
          _activeChatRequestId = null;
        }
      }

      if (_cancelledChatRequestIds.remove(chatRequestId)) return;
      _chatRequests.complete(chatRequestId);

      if (buffer.isNotEmpty) {
        final structured = _tryParseAssistantStructuredMessage(buffer);
        if (structured != null && mounted) {
          setState(() {
            msgs[assistantIndex] =
                structured.withCorrelationFrom(msgs[assistantIndex]);
          });
          // "download it" / "open it" / "view it" pronoun follow-ups
          // arrive as a vault_file card with pending_action set. Fire
          // the corresponding UI action once, on the next frame, so
          // the user's instruction actually completes without another
          // tap.
          _maybeTriggerPendingFileAction(structured);
        }
      }

      if (mounted && thinking) {
        setState(() => thinking = false);
      }

      unawaited(app.refreshVaultStats());
      unawaited(_loadVaultFiles());
      unawaited(_loadVaultLogins());

      if (!mounted) return;
      setState(() {
        sending = false;
      });
    } catch (e) {
      if (app.handleApiException(e)) return;
      if (!mounted) return;

      if (e is UploadCancelledException) {
        _chatRequests.cancel(chatRequestId);
        setState(() {
          thinking = false;
          sending = false;
        });
        return;
      }
      _chatRequests.complete(chatRequestId);
      setState(() {
        thinking = false;
        final failure = _Msg(
          'assistant',
          uploadCommitted && hadAttachments
              ? 'Your file was saved. I could not complete the optional '
                  'follow-up.'
              : friendlyChatGenerationFailure(text),
          messageId: assistantMessageId,
          requestId: chatRequestId,
          replyToMessageId: userMessageId,
        );
        final existing = msgs.indexWhere(
          (message) => message.messageId == assistantMessageId,
        );
        if (existing >= 0) {
          msgs[existing] = failure;
        } else {
          msgs.add(failure);
        }
        sending = false;
      });
      _scrollToBottom();
    }
  }

  Widget _buildAttachmentPanel(bool isMobile) {
    if (attachments.isEmpty) return const SizedBox.shrink();
    return ChatAttachmentPanel(
      isMobile: isMobile,
      count: attachments.length,
      itemBuilder: (context, index) => _buildAttachmentRow(attachments[index]),
      onClear: sending ? null : _clearAttachments,
    );
  }

  Widget _buildAttachmentRow(_Attachment a) {
    final IconData icon;
    switch (a.kind) {
      case 'image':
        icon = Icons.image;
        break;
      case 'video':
        icon = Icons.videocam_outlined;
        break;
      case 'audio':
        icon = Icons.audiotrack;
        break;
      default:
        icon = Icons.insert_drive_file;
    }
    return InkWell(
      onTap: () => _previewLocalAttachment(a),
      borderRadius: BorderRadius.circular(12),
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.03),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white10),
        ),
        child: Row(
          children: [
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: const Color(0xFF10A37F).withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(icon),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    a.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 13,
                        color: Colors.white,
                        fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${a.kind} • ${_formatBytes(a.size)}',
                    style:
                        const TextStyle(fontSize: 11, color: Color(0xFFB4B4B4)),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            const Icon(Icons.info_outline, size: 18),
          ],
        ),
      ),
    );
  }

  bool get _composerIsComposing {
    final composing = input.value.composing;
    return composing.isValid && !composing.isCollapsed;
  }

  Future<void> _submitComposer() async {
    if (_composerSubmitStarting || sending || _composerIsComposing) return;
    if (input.text.trim().isEmpty && attachments.isEmpty) return;
    _composerSubmitStarting = true;
    try {
      await _send();
    } finally {
      _composerSubmitStarting = false;
    }
  }

  Widget _buildComposer(bool isMobile) {
    final vr = VaultResponsive.of(context);

    final canSend =
        !sending && (input.text.trim().isNotEmpty || attachments.isNotEmpty);

    Widget _attachmentIcon() => SizedBox(
          key: const Key('composer_attachment_button'),
          width: vr.composerIconButtonSize,
          height: vr.composerIconButtonSize,
          child: _buildAttachmentPlusMenu(),
        );

    Widget _micIcon() => SizedBox(
          key: const Key('composer_mic_button'),
          width: vr.composerIconButtonSize,
          height: vr.composerIconButtonSize,
          child: IconButton(
            padding: EdgeInsets.zero,
            iconSize: vr.isMobile ? 20 : 22,
            icon: Icon(_isListening ? Icons.mic : Icons.mic_none),
            color: _isListening ? const Color(0xFF10A37F) : null,
            tooltip: _isListening ? 'Stop listening' : 'Speak',
            onPressed: sending ? null : _toggleListening,
          ),
        );

    Widget _recordingStopIcon() => SizedBox(
          key: const Key('composer_stop_recording_button'),
          width: vr.composerIconButtonSize,
          height: vr.composerIconButtonSize,
          child: IconButton(
            padding: EdgeInsets.zero,
            iconSize: vr.isMobile ? 20 : 22,
            icon: const Icon(Icons.stop_circle),
            color: Colors.redAccent,
            tooltip: 'Stop recording',
            onPressed: sending
                ? null
                : (_isVideoRecording
                    ? _toggleVideoRecording
                    : _toggleRecording),
          ),
        );

    Widget _sendButton() {
      final size = vr.composerSendButtonSize;
      final iconColor = canSend ? Colors.white : Colors.white54;
      return Semantics(
        button: true,
        identifier: 'composer_send_button',
        label: sending
            ? 'Cancel response'
            : AppLocalizations.of(context).chatSendButton,
        child: Material(
          key: const Key('composer_send_button'),
          color: canSend ? const Color(0xFF10A37F) : const Color(0xFF3A3F47),
          shape: const CircleBorder(),
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: sending
                ? _cancelActiveChatRequest
                : (canSend ? _submitComposer : null),
            child: SizedBox(
              width: size,
              height: size,
              child: Icon(
                sending ? Icons.close_rounded : Icons.arrow_upward_rounded,
                size: vr.isMobile ? 18 : 20,
                color: iconColor,
              ),
            ),
          ),
        ),
      );
    }

    final editableTextField = TextField(
      key: const Key('chat_composer_field'),
      controller: input,
      enabled: !sending,
      decoration: InputDecoration(
        hintText: isMobile
            ? 'Ask SVaultAI…'
            : AppLocalizations.of(context).chatComposerHint,
        border: InputBorder.none,
        enabledBorder: InputBorder.none,
        focusedBorder: InputBorder.none,
        isDense: true,
        contentPadding: EdgeInsets.symmetric(
          horizontal: 4,
          vertical: isMobile ? 8 : 10,
        ),
      ),
      minLines: vr.composerMinLines,
      maxLines: vr.composerMaxLines,
      textInputAction:
          isMobile ? TextInputAction.send : TextInputAction.newline,
      keyboardType: TextInputType.multiline,
      onSubmitted: canSend ? (_) => _submitComposer() : null,
      onChanged: (_) {
        setState(() {});
      },
    );

    final textField = Semantics(
      container: true,
      identifier: 'chat_composer_field',
      textField: true,
      // Desktop/web policy: Enter and Ctrl+Enter send. Shift+Enter and
      // Alt+Enter stay unbound so EditableText inserts a newline. The
      // synchronous latch blocks key-repeat duplicates; composing IME text
      // is never submitted.
      child: isMobile
          ? editableTextField
          : CallbackShortcuts(
              bindings: <ShortcutActivator, VoidCallback>{
                const SingleActivator(LogicalKeyboardKey.enter): () =>
                    unawaited(_submitComposer()),
                const SingleActivator(
                  LogicalKeyboardKey.enter,
                  control: true,
                ): () => unawaited(_submitComposer()),
              },
              child: editableTextField,
            ),
    );

    return SafeArea(
      top: false,
      bottom: true,
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          isMobile ? 10 : 16,
          6,
          isMobile ? 10 : 16,
          isMobile ? 6 : 12,
        ),
        child: Container(
          padding: EdgeInsets.symmetric(
            horizontal: vr.composerHorizontalPadding,
            vertical: vr.composerVerticalPadding,
          ),
          decoration: BoxDecoration(
            color: const Color(0xFF2F2F2F),
            borderRadius: BorderRadius.circular(isMobile ? 22 : 20),
            border: Border.all(color: Colors.white10),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              _attachmentIcon(),
              if (_isRecording || _isVideoRecording) _recordingStopIcon(),
              _micIcon(),
              const SizedBox(width: 4),
              Expanded(child: textField),
              const SizedBox(width: 6),
              _sendButton(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildChatView(bool isMobile) {
    final app = context.watch<AppState>();
    return CallbackShortcuts(
      bindings: <ShortcutActivator, VoidCallback>{
        const SingleActivator(LogicalKeyboardKey.escape): () =>
            unawaited(_cancelVideoRecordingWithConfirmation()),
      },
      child: Column(
        children: [
          Expanded(
            child: ChatMessageList(
              key: const Key('chat_message_list'),
              messages: msgs,
              thinking: thinking,

              streaming:
                  sending && msgs.isNotEmpty && msgs.last.role == 'assistant',
              isMobile: isMobile,
              padding: EdgeInsets.symmetric(
                horizontal: isMobile ? 8 : 16,
                vertical: isMobile ? 8 : 12,
              ),
              scrollController: _scrollController,
              // Typing indicator identity: the user-chosen vault
              // name (``AppState._vaultName``), which is the vault's
              // own identity — the same string the user typed to
              // sign into the vault and the same string the LLM is
              // instructed to identify as. It is a per-vault value
              // (e.g. "Brain", "My Safe", "Family Vault"), NOT a
              // hardcoded global constant.
              //
              // 2026-07-22 fix: the previous binding was
              // ``vaultName: app.displayName`` — that field is the
              // human owner's display label (e.g. "Chosen"), not
              // the vault's identity, and produced the incident
              // "Chosen is thinking..." for a user named Chosen.
              // Never re-bind this parameter to app.displayName or
              // to a hardcoded literal; the vault-name registry
              // pattern (AppState.setSession populates
              // ``_vaultName`` from the authenticated backend
              // vault_name and clears it on sign-out) is the single
              // source of truth per-session.
              vaultName: app.vaultName,
              // Per-file in-flight state, watched from AppState so the
              // whole chat rebuilds when any file starts / finishes a
              // view or download. Individual cards render their own
              // spinner / disabled buttons based on set membership.
              viewInFlightFileIds: app.viewInFlightFileIds,
              downloadInFlightFileIds: app.downloadInFlightFileIds,
              onOpenVaultFile: (msg) => _openVaultFileCard(msg),
              onDownloadVaultFile: (msg) => _downloadVaultFileCard(msg),
              onShowMoreFiles: () => _requestMoreFiles(),
              isShowMoreFilesInFlight: app.showMoreFilesInFlight,
              onCardAction: _handleChatCardAction,
              onShowRelated: _showRelatedFilesForFile,
              onLoadRelated: _fetchRelatedFilesEnvelope,
              onScanRemaining: _handleScanRemaining,
              onDeepAnswerPoll: _pollDeepAnswerJob,
              onDeepAnswerReady: _promoteDeepAnswerResult,
              isDeepScanActive: ({
                required String intent,
                required String normalizedQuery,
              }) =>
                  isDeepScanActive(
                intent: intent,
                normalizedQuery: normalizedQuery,
              ),

              onSecureItemView: (itemId, title, itemType) {
                final safeTitle = title.trim();
                _sendQuickPrompt(
                    safeTitle.isEmpty ? 'show me' : 'show me $safeTitle');
              },

              onSecureItemReveal: null,
              onSecureItemCopyUsername: (username) {
                Clipboard.setData(ClipboardData(text: username));
                _showSnack('Username copied');
              },
              onSecureItemCopyValue: (value) {
                Clipboard.setData(ClipboardData(text: value));
                _showSnack('Value copied');
              },
              onSecureItemEdit: (title, itemType) {
                _openSecureItemEditDialog(title, itemType);
              },
              onSecureItemDelete: (title, itemType) {
                _startSecureItemDeleteConfirmation(title, itemType);
              },

              onCryptoWalletAction: _handleCryptoWalletChatAction,

              onOpenVault: () {
                if (mounted) {
                  setState(() => selectedSection = _DashboardSection.dashboard);
                }
              },
              onOpenAssetDetail: (asset) {
                if (!mounted) return;
                setState(() => selectedSection = _DashboardSection.cryptoVault);
              },
              onOpenSendFlow: () {
                if (!mounted) return;
                setState(() => selectedSection = _DashboardSection.cryptoVault);
              },
              onOpenSecurityPage: () {
                if (!mounted) return;
                setState(() => selectedSection = _DashboardSection.settings);
              },
              onOpenBillingPage: () {
                if (!mounted) return;
                setState(() => selectedSection = _DashboardSection.settings);
              },
              onOpenStoragePage: () {
                if (!mounted) return;
                setState(() => selectedSection = _DashboardSection.files);
              },
              onOpenVaultItem: (category, id) {
                if (!mounted) return;
                switch (category) {
                  case 'login':
                  case 'generated_login':
                  case 'id_document':
                  case 'secure_item':
                    setState(() => selectedSection = _DashboardSection.logins);
                    break;
                  case 'crypto':
                    setState(
                        () => selectedSection = _DashboardSection.cryptoVault);
                    break;
                  case 'file':
                  case 'document':
                    setState(() => selectedSection = _DashboardSection.files);
                    break;
                  case 'activity':
                    setState(
                        () => selectedSection = _DashboardSection.dashboard);
                    break;
                  default:
                    setState(
                        () => selectedSection = _DashboardSection.dashboard);
                }
              },
              onSearchVault: (query) {
                _sendQuickPrompt('search my vault for $query');
              },

              onFetchCryptoBalance: ({
                required String asset,
                required String address,
              }) async {
                return _fetchCryptoBalanceForChatCard(
                  asset: asset,
                  address: address,
                );
              },
              onFetchCryptoActivity: ({
                required String asset,
                required String address,
                int limit = 10,
              }) async {
                return _fetchCryptoActivityForChatCard(
                  asset: asset,
                  address: address,
                  limit: limit,
                );
              },

              cryptoCache: CryptoChatLiveCache.instance,

              cryptoEntitled: context.watch<AppState>().isCryptoEntitled,
              onOpenCryptoUpgrade: () {
                if (!mounted) return;
                setState(() => selectedSection = _DashboardSection.settings);
              },
            ),
          ),
          if (_isVideoRecording) _buildRecordingBanner(),
          _buildImportPanel(),
          _buildAttachmentPanel(isMobile),
          _buildComposer(isMobile),
        ],
      ),
    );
  }

  Widget _buildFilesSection(bool isMobile) {
    if (loadingFiles) {
      return const Center(
        child: CircularProgressIndicator(),
      );
    }

    if (vaultFiles.isEmpty) {
      return SingleChildScrollView(
        padding: EdgeInsets.all(isMobile ? 12 : 20),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1000),
            child: Container(
              width: double.infinity,
              padding: EdgeInsets.all(
                  MediaQuery.of(context).size.width < 600 ? 16 : 24),
              decoration: BoxDecoration(
                color: const Color(0xFF2F2F2F),
                borderRadius: BorderRadius.circular(24),
                border: Border.all(color: Colors.white10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    AppLocalizations.of(context).filesTitle,
                    style: TextStyle(
                        fontSize: vrHeadline(context),
                        fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'No files uploaded yet. Upload images, PDFs, spreadsheets, and documents from chat.',
                    style: TextStyle(
                      color: Color(0xFFB4B4B4),
                      fontSize: 15,
                      height: 1.6,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return SingleChildScrollView(
      padding: EdgeInsets.all(isMobile ? 12 : 20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: Semantics(
            container: true,
            identifier: 'files_list',
            child: Column(
              key: const Key('files_list'),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: double.infinity,
                  padding: EdgeInsets.all(
                      MediaQuery.of(context).size.width < 600 ? 16 : 24),
                  decoration: BoxDecoration(
                    color: const Color(0xFF2F2F2F),
                    borderRadius: BorderRadius.circular(24),
                    border: Border.all(color: Colors.white10),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              AppLocalizations.of(context).filesTitle,
                              style: TextStyle(
                                  fontSize: vrHeadline(context),
                                  fontWeight: FontWeight.w800),
                            ),
                            const SizedBox(height: 8),
                            const Text(
                              'Open and manage files saved in your vault.',
                              style: TextStyle(
                                color: Color(0xFFB4B4B4),
                                fontSize: 15,
                              ),
                            ),
                          ],
                        ),
                      ),
                      OutlinedButton.icon(
                        key: const Key('files_refresh_button'),
                        onPressed: _loadVaultFiles,
                        icon: const Icon(Icons.refresh),
                        label: Text(
                          AppLocalizations.of(context).commonRefresh,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                const ZkSemanticSearchUnavailableBanner(),
                if (_folderTreeData != null)
                  FolderBrowser(
                    treeData: _folderTreeData!,
                    isMobile: isMobile,
                    searchQuery: _folderSearchQuery,
                    onSearchChanged: (q) {
                      setState(() {
                        _folderSearchQuery = q;
                      });
                    },
                    onNavigateToPath: _navigateToFolder,
                    fileItemBuilder: (json) => _buildVaultFileCard(
                      _VaultStoredFile.fromJson(json),
                    ),
                  )
                else
                  ...vaultFiles.map(_buildVaultFileCard),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildVaultFileCard(_VaultStoredFile file) {
    final label = file.savedName != null && file.savedName!.trim().isNotEmpty
        ? file.savedName!
        : file.fileName;

    final subtitleParts = <String>[
      if (file.assetType != null && file.assetType!.isNotEmpty) file.assetType!,
      _formatBytes(file.fileSize),
      if (file.needsNaming) 'needs naming',
      if (file.relativePath != null && file.relativePath!.isNotEmpty)
        file.relativePath!,
    ];

    return Semantics(
      container: true,
      identifier: 'files_file_card_${file.id}',
      child: Container(
        key: ValueKey('files_file_card_${file.id}'),
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFF2A2A2A),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: Colors.white10),
        ),
        child: Row(
          children: [
            Container(
              width: 54,
              height: 54,
              decoration: BoxDecoration(
                color: const Color(0xFF10A37F).withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Icon(
                () {
                  if (_isVideoMime(file.contentType) ||
                      file.assetType == 'video') {
                    return Icons.videocam_outlined;
                  }
                  if (_isAudioMime(file.contentType) ||
                      file.assetType == 'audio') {
                    return Icons.audiotrack;
                  }
                  if (_isImageMime(file.contentType) ||
                      file.assetType == 'image') {
                    return Icons.image_outlined;
                  }
                  return Icons.insert_drive_file_outlined;
                }(),
                color: const Color(0xFF10A37F),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    // 2026-07-21 c2f917e follow-up: never surface
                    // vault_name in normal UI. Use display_name; fall
                    // back to the neutral 'Vault' literal.
                    'Hidden for privacy. Ask ${context.read<AppState>().displayName?.trim().isNotEmpty == true ? context.read<AppState>().displayName!.trim() : 'Vault'} in chat to retrieve this file.',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: Color(0xFFB4B4B4),
                      fontSize: 13,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    subtitleParts.join(' • '),
                    style: const TextStyle(
                      color: Color(0xFF8E8E8E),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Semantics(
              container: true,
              identifier: 'files_file_ask_${file.id}',
              button: true,
              child: Tooltip(
                message:
                    context.read<AppState>().displayName?.trim().isNotEmpty ==
                            true
                        ? 'Ask ${context.read<AppState>().displayName!.trim()}'
                        : 'Ask Vault',
                child: IconButton(
                  key: ValueKey('files_file_ask_${file.id}'),
                  onPressed: () => _askBrainAboutFile(file),
                  icon: const Icon(Icons.smart_toy_outlined),
                  color: const Color(0xFF10A37F),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDashboardHome(bool isMobile) {
    final app = context.watch<AppState>();
    final used = app.storageUsedBytes;

    final limit = app.effectiveStorageLimitBytes;
    final progress = limit == 0 ? 0.0 : min(1.0, used / limit);

    final cards = [
      _OverviewCardData(
        title: 'Logins',
        value: app.loginCount.toString(),
        icon: Icons.lock_outline,
        iconColor: const Color(0xFF10A37F),
        bgColor: const Color(0xFF10A37F).withValues(alpha: 0.12),
      ),
      _OverviewCardData(
        title: 'Files',
        value: app.fileCount.toString(),
        icon: Icons.folder_open_outlined,
        iconColor: Colors.purpleAccent,
        bgColor: Colors.purple.withValues(alpha: 0.12),
      ),
    ];

    return SingleChildScrollView(
      padding: EdgeInsets.all(isMobile ? 12 : 20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1180),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: double.infinity,
                padding: EdgeInsets.all(isMobile ? 20 : 28),
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [
                      Color(0xFF2A2A2A),
                      Color(0xFF232323),
                    ],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(28),
                  border: Border.all(color: Colors.white10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: const Color(0xFF10A37F).withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: const Text(
                        'Vault overview',
                        style: TextStyle(
                          color: Color(0xFF10A37F),
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      // 2026-07-21 (c2f917e regression fix): greet
                      // using the user's chosen display_name. The
                      // vault_name is the login and AI identity —
                      // it must NOT be the visible greeting label.
                      // Neutral fallback when displayName is absent.
                      () {
                        final name = app.displayName?.trim() ?? '';
                        if (name.isEmpty) return 'Welcome to your vault';
                        return 'Welcome, $name';
                      }(),
                      style: TextStyle(
                        fontSize: isMobile ? 28 : 40,
                        fontWeight: FontWeight.w800,
                        height: 1.02,
                        letterSpacing: -0.8,
                      ),
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      'Ask naturally, upload documents, and retrieve private information from one secure workspace.',
                      style: TextStyle(
                        color: Color(0xFFB4B4B4),
                        fontSize: 15,
                        height: 1.5,
                      ),
                    ),
                    const SizedBox(height: 22),
                    Builder(builder: (_) {
                      if (app.isBillingLoading) {
                        return const _BillingLoadingCard(
                          label: 'Loading storage usage…',
                        );
                      }
                      if (app.isBillingError) {
                        return _BillingErrorCard(
                          onRetry: () => app.retryBilling(),
                        );
                      }
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          ClipRRect(
                            borderRadius: BorderRadius.circular(999),
                            child: LinearProgressIndicator(
                              value: progress,
                              minHeight: 10,
                            ),
                          ),
                          const SizedBox(height: 10),
                          Text(
                            '${formatBytes(used)} used of ${formatBytes(limit)}',
                            style: const TextStyle(
                              color: Color(0xFFA3A3A3),
                              fontSize: 13,
                            ),
                          ),
                        ],
                      );
                    }),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              const Padding(
                padding: EdgeInsets.only(left: 4, bottom: 10),
                child: Text(
                  'Your vault stats',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
              ),
              GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: cards.length,
                gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: isMobile ? 1 : 2,
                  crossAxisSpacing: 16,
                  mainAxisSpacing: 16,
                  childAspectRatio: isMobile ? 3.0 : 2.8,
                ),
                itemBuilder: (_, i) => _OverviewCard(data: cards[i]),
              ),
              const SizedBox(height: 22),
              const Padding(
                padding: EdgeInsets.only(left: 4, bottom: 10),
                child: Text(
                  'Quick actions',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
              ),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  OutlinedButton.icon(
                    onPressed: () => _sendQuickPrompt('Show my saved logins'),
                    icon: const Icon(Icons.lock_outline, size: 18),
                    label: Text(
                      AppLocalizations.of(context).chatQuickSavedLogins,
                    ),
                  ),
                  OutlinedButton.icon(
                    onPressed: () => _sendQuickPrompt('What files do I have?'),
                    icon: const Icon(Icons.folder_open_outlined, size: 18),
                    label: Text(
                      AppLocalizations.of(context).chatQuickMyFiles,
                    ),
                  ),
                  OutlinedButton.icon(
                    onPressed: () => _sendQuickPrompt('Show my passport'),
                    icon: const Icon(Icons.badge_outlined, size: 18),
                    label: Text(
                      AppLocalizations.of(context).chatQuickMyPassport,
                    ),
                  ),
                  OutlinedButton.icon(
                    onPressed: () =>
                        _sendQuickPrompt('Describe your capabilities'),
                    icon: const Icon(Icons.auto_awesome_outlined, size: 18),
                    label: Text(
                      AppLocalizations.of(context).chatQuickWhatCanYouDo,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSidebar() {
    final app = context.watch<AppState>();

    Widget tile(
      _DashboardSection section,
      IconData icon,
      String label, {
      bool compact = false,
      double verticalPadding = 14,
    }) {
      final selected = selectedSection == section;
      final horizontalPad = compact ? 10.0 : 14.0;
      final iconSize = compact ? 18.0 : 20.0;
      final labelFont = compact ? 13.5 : 14.0;
      final radius = compact ? 12.0 : 16.0;
      final marginBottom = compact ? 4.0 : 8.0;

      return Semantics(
        container: true,
        identifier: 'sidebar_section_${section.name}',
        button: true,
        selected: selected,
        child: InkWell(
          key: ValueKey('sidebar_section_${section.name}'),
          onTap: () {
            setState(() => selectedSection = section);
            Navigator.of(context).maybePop();
          },
          borderRadius: BorderRadius.circular(radius),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            margin: EdgeInsets.only(bottom: marginBottom),
            padding: EdgeInsets.symmetric(
              horizontal: horizontalPad,
              vertical: verticalPadding,
            ),
            decoration: BoxDecoration(
              color: selected
                  ? const Color(0xFF10A37F).withValues(alpha: 0.14)
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(radius),
              border: Border.all(
                color: selected
                    ? const Color(0xFF10A37F).withValues(alpha: 0.35)
                    : Colors.white10,
              ),
            ),
            child: Row(
              children: [
                Icon(
                  icon,
                  size: iconSize,
                  color: selected
                      ? const Color(0xFF10A37F)
                      : const Color(0xFF9CA3AF),
                ),
                SizedBox(width: compact ? 10 : 12),
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      color: selected ? Colors.white : const Color(0xFFC7C7C7),
                      fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                      fontSize: labelFont,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final _vr = VaultResponsive.of(context);
    final _drawerHeaderFontSize = _vr.isMobile ? 18.0 : 22.0;
    final _drawerHeaderPadding = _vr.drawerHeaderPadding;
    final _drawerBodyPadding = _vr.drawerBodyPadding;
    final _drawerTileVpad = _vr.isMobile ? 6.0 : 8.0;
    return Drawer(
      backgroundColor: const Color(0xFF212121),
      width: _vr.drawerWidth,
      child: SafeArea(
        bottom: true,
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            _drawerBodyPadding,
            _drawerBodyPadding,
            _drawerBodyPadding,
            _drawerBodyPadding + math.max(0, _vr.bottomSafeInset),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: double.infinity,
                padding: EdgeInsets.all(_drawerHeaderPadding),
                decoration: BoxDecoration(
                  color: const Color(0xFF2F2F2F),
                  borderRadius: BorderRadius.circular(_vr.isMobile ? 14 : 18),
                  border: Border.all(color: Colors.white10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      // Drawer header (2026-07-21 c2f917e follow-up):
                      // display the user-facing display_name only.
                      // The internal vault_name is the login/AI
                      // identity — never a normal-UI label. Falls back
                      // to the neutral 'Vault' literal when the row
                      // has no display_name captured.
                      () {
                        final name = app.displayName?.trim() ?? '';
                        return name.isEmpty ? 'Vault' : name;
                      }(),
                      style: TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: _drawerHeaderFontSize,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              SizedBox(height: _vr.isMobile ? 8 : 14),
              Expanded(
                child: ListView(
                  key: const Key('vault_drawer_menu_list'),
                  padding: EdgeInsets.only(
                    bottom: math.max(0, _vr.bottomSafeInset),
                  ),
                  children: [
                    tile(_DashboardSection.dashboard, Icons.dashboard_outlined,
                        AppLocalizations.of(context).sidebarDashboard,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(_DashboardSection.chat, Icons.chat_bubble_outline,
                        AppLocalizations.of(context).sidebarChat,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(_DashboardSection.files, Icons.folder_open_outlined,
                        AppLocalizations.of(context).sidebarFiles,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(_DashboardSection.logins, Icons.lock_outline,
                        AppLocalizations.of(context).sidebarLogins,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(
                        _DashboardSection.cryptoVault,
                        Icons.account_balance_wallet_outlined,
                        AppLocalizations.of(context).sidebarCryptoVault,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(
                        _DashboardSection.concierge,
                        Icons.auto_awesome_outlined,
                        AppLocalizations.of(context).sidebarConcierge,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(_DashboardSection.expiry, Icons.event_busy_outlined,
                        AppLocalizations.of(context).sidebarExpiry,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(_DashboardSection.memory, Icons.auto_stories_outlined,
                        AppLocalizations.of(context).sidebarMemory,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(_DashboardSection.inheritance, Icons.diversity_3,
                        AppLocalizations.of(context).sidebarInheritance,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    tile(_DashboardSection.settings, Icons.settings_outlined,
                        AppLocalizations.of(context).sidebarSettings,
                        compact: _vr.isMobile,
                        verticalPadding: _drawerTileVpad),
                    SizedBox(
                      key: const Key('vault_drawer_menu_tail_sentinel'),
                      height: 8,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBody(bool isMobile) {
    switch (selectedSection) {
      case _DashboardSection.dashboard:
        return _buildDashboardHome(isMobile);
      case _DashboardSection.chat:
        return _buildChatView(isMobile);
      case _DashboardSection.files:
        return _buildFilesSection(isMobile);

      case _DashboardSection.logins:
        // 2026-07-21 c2f917e follow-up: LoginsPage vaultLabel is a
        // user-visible header string ("Your Vault" / display_name).
        // Never surface the internal vault_name here.
        final vaultDisplayName =
            context.read<AppState>().displayName?.trim().isNotEmpty == true
                ? context.read<AppState>().displayName!.trim()
                : 'Vault';

        if (!hasLoadedSecureItems &&
            !loadingLogins &&
            secureItemsError == null) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) _loadVaultLogins();
          });
        }

        return LoginsPage(
          isLoading: loadingLogins,
          hasLoaded: hasLoadedSecureItems,
          error: secureItemsError,
          logins: vaultLogins,
          vaultLabel: vaultDisplayName,
          onRefresh: _loadVaultLogins,
          onAskVault: (service) async {
            await _sendQuickPrompt('Show my $service login');
          },
          onView: (service, itemType) {
            _openSecureItemView(service, itemType);
          },
          onEdit: (service, itemType) {
            _openSecureItemEditDialog(service, itemType);
          },
          onDelete: (service, itemType) {
            _startSecureItemDeleteConfirmation(service, itemType);
          },
          onViewItem: (item) {
            if (item.cryptoVersion == credentialV2CryptoVersion) {
              unawaited(_revealCredentialV2(item));
            } else {
              _openSecureItemView(item.service, item.itemType);
            }
          },
          onEditItem: (item) {
            if (item.cryptoVersion == credentialV2CryptoVersion) {
              unawaited(_openCredentialV2Editor(item));
            } else {
              unawaited(_openSecureItemEditDialog(item.service, item.itemType));
            }
          },
          onDeleteItem: (item) {
            if (item.cryptoVersion == credentialV2CryptoVersion) {
              unawaited(_deleteCredentialV2(item));
            } else {
              _startSecureItemDeleteConfirmation(item.service, item.itemType);
            }
          },
          onMigrateItem: zkV2CredentialMigrationEnabled
              ? (item) {
                  if (item.cryptoVersion == 'legacy_v1' &&
                      isLoginLikeType(item.itemType)) {
                    unawaited(_migrateCredentialV2(item));
                  }
                }
              : null,
          onRollbackItem: zkV2CredentialMigrationEnabled
              ? (item) {
                  if (isCredentialV2RollbackEligible(item)) {
                    unawaited(_rollbackCredentialV2(item));
                  }
                }
              : null,
        );

      case _DashboardSection.cryptoVault:
        return _buildCryptoVaultSection(isMobile);

      case _DashboardSection.concierge:
        return _buildConciergeSection(isMobile);

      case _DashboardSection.expiry:
        return _buildExpirySection(isMobile);

      case _DashboardSection.memory:
        return _buildMemorySection(isMobile);

      case _DashboardSection.inheritance:
        return _buildInheritanceSection(isMobile);

      case _DashboardSection.settings:
        return _buildSettingsSection(isMobile);
    }
  }

  Widget _buildCryptoVaultSection(bool isMobile) {
    final app = context.watch<AppState>();

    final billingLoaded = app.isBillingLoaded;
    final billingErrored = app.isBillingError;
    final billingLoading = app.isBillingLoading;

    if (_cryptoBillingBannerLastState != app.billingLoadState) {
      _cryptoBillingBannerLastState = app.billingLoadState;
      _cryptoBillingBannerDismissed = false;
    }

    final isKnownNotUpgraded = billingLoaded &&
        !(app.billingBlockCount > 0 && app.billingPurchasedBytes > 0);

    Widget content;
    if (isKnownNotUpgraded) {
      content = SingleChildScrollView(
        padding: EdgeInsets.all(isMobile ? 12 : 20),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  AppLocalizations.of(context).sidebarCryptoVault,
                  key: const Key('crypto_vault_page_heading'),
                  style: TextStyle(
                    fontSize: vrHeadline(context),
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 24),
                const CryptoVaultLockedCard(
                  key: Key('crypto_vault_page_card'),
                ),
              ],
            ),
          ),
        ),
      );
    } else {
      content = _buildCryptoVaultEngineContent(app, isMobile);
    }

    final showBanner =
        (billingLoading || billingErrored) && !_cryptoBillingBannerDismissed;

    if (showBanner) {
      return Stack(
        key: const Key('crypto_vault_page'),
        children: [
          Positioned.fill(child: content),
          Positioned(
            top: 8,
            left: 8,
            right: 8,
            child: Align(
              alignment: Alignment.topRight,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: _CryptoVaultBillingStatusBanner(
                  errored: billingErrored,
                  onRetry: () {
                    setState(() {
                      _cryptoBillingBannerDismissed = false;
                    });
                    app.retryBilling();
                  },
                  onDismiss: () {
                    setState(() {
                      _cryptoBillingBannerDismissed = true;
                    });
                  },
                ),
              ),
            ),
          ),
        ],
      );
    }

    return KeyedSubtree(
      key: const Key('crypto_vault_page'),
      child: content,
    );
  }

  Widget _buildCryptoVaultEngineContent(AppState app, bool isMobile) {
    final authToken = app.sessionToken;
    final hasVaultKey = app.vaultId != null &&
        app.vaultName != null &&
        _VaultCrypto.hasKeyFor(
          vaultId: app.vaultId!,
          vaultName: app.vaultName!,
        );

    if (kCryptoWalletEngineEnabled) {
      return Builder(
        builder: (engineCtx) => CryptoWalletEnginePage(
          key: const Key('crypto_wallet_engine_page_root'),
          onSendChatPrompt: (prompt) {
            setState(() => selectedSection = _DashboardSection.chat);
            _sendQuickPrompt(prompt);
          },
          authToken: authToken,
          apiClient: VaultAIClient(baseUrl: backendBaseUrl),
          encryptForVault: (plaintext) => _VaultCrypto.encrypt(plaintext),
          isVaultKeyAvailable: () => hasVaultKey,
          decryptForVault: (ciphertext) => _VaultCrypto.decrypt(ciphertext),
          verifyPin: (pin) async {
            final cachedPin = _VaultCrypto.cachedPinFor(
              vaultId: app.vaultId ?? '',
              vaultName: app.vaultName ?? '',
            );
            if (cachedPin == null) return false;
            return cachedPin == pin;
          },
          // 2026-07-13 fix: was calling the legacy
          // /crypto/wallet/{asset}/receive endpoint which queries
          // service='ETH'. The mainnet ETH wallet is persisted with
          // service='ETH:ethereum_mainnet' (see backend
          // _service_key_for_network), so the legacy call returned
          // no_account even when the wallet existed and had a live
          // balance — the exact "No Ethereum wallet exists yet" bug
          // the user hit on Send. Balance and Receive already use
          // the network-scoped endpoint, so switching Send to the
          // same endpoint aligns all three paths on one source of
          // truth. For ERC20 tokens (USDT_ERC20/USDC_ERC20) the
          // asset is still 'ETH' because the parent Ethereum wallet
          // signs and pays gas for the ERC20 transfer — the token
          // itself is not a separate wallet.
          loadFromAddress: (network) async {
            try {
              final body = await VaultAIClient(baseUrl: backendBaseUrl)
                  .getCryptoWalletReceiveNetwork(
                network: network,
                asset: 'ETH',
                authToken: authToken ?? '',
              );
              final status = (body['wallet_engine'] ?? '').toString();
              if (status != 'receive_ready') return null;
              final addr = body['publicAddress'];
              if (addr is String && addr.isNotEmpty) return addr;
              return null;
            } catch (_) {
              return null;
            }
          },
          moneroWalletAdapter: RealMoneroWalletAdapter(),
          moneroScannerAdapter: const NullMoneroScannerAdapter(),
        ),
      );
    }

    return SingleChildScrollView(
      key: const Key('crypto_vault_engine_disabled_page'),
      padding: EdgeInsets.all(isMobile ? 12 : 20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'SVaultAI Crypto Wallet',
                key: const Key('crypto_vault_engine_disabled_heading'),
                style: TextStyle(
                  fontSize: vrHeadline(context),
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 12),
              const Text(
                'Wallet engine is disabled in this build.',
                key: Key('crypto_vault_engine_disabled_body'),
                style: TextStyle(color: Colors.black54, fontSize: 14),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildConciergeSection(bool isMobile) {
    final app = context.watch<AppState>();
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    if (token == null || vaultName == null || vaultName.isEmpty) {
      return Center(
        child: Padding(
          padding:
              EdgeInsets.all(MediaQuery.of(context).size.width < 600 ? 16 : 24),
          child: Text(
            AppLocalizations.of(context).unlockToSeeConcierge,
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    return ConciergePage(
      client: VaultAIClient(baseUrl: backendBaseUrl),
      authToken: token,
      vaultName: vaultName,
      isMobile: isMobile,
      onAskVaultAI: (prompt) async {
        setState(() => selectedSection = _DashboardSection.chat);
        await _sendQuickPrompt(prompt);
      },
      onOpenSecurityCenter: () =>
          Navigator.pushNamed(context, '/security-center'),
      onOpenExpiry: () => setState(
        () => selectedSection = _DashboardSection.expiry,
      ),
      onOpenInheritance: () => setState(
        () => selectedSection = _DashboardSection.inheritance,
      ),
    );
  }

  Widget _buildExpirySection(bool isMobile) {
    final app = context.watch<AppState>();
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    if (token == null || vaultName == null || vaultName.isEmpty) {
      return Center(
        child: Padding(
          padding:
              EdgeInsets.all(MediaQuery.of(context).size.width < 600 ? 16 : 24),
          child: Text(
            AppLocalizations.of(context).unlockToSeeExpiry,
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    return ExpiryPage(
      client: VaultAIClient(baseUrl: backendBaseUrl),
      authToken: token,
      vaultName: vaultName,
      isMobile: isMobile,
      onAskVaultAI: (prompt) async {
        setState(() => selectedSection = _DashboardSection.chat);
        await _sendQuickPrompt(prompt);
      },
    );
  }

  Widget _buildMemorySection(bool isMobile) {
    final app = context.watch<AppState>();
    final token = app.sessionToken;
    final vaultName = app.vaultName;
    if (token == null || vaultName == null || vaultName.isEmpty) {
      return Center(
        child: Padding(
          padding:
              EdgeInsets.all(MediaQuery.of(context).size.width < 600 ? 16 : 24),
          child: Text(
            AppLocalizations.of(context).unlockToSeeMemory,
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    return MemoryPage(
      client: VaultAIClient(baseUrl: backendBaseUrl),
      authToken: token,
      vaultName: vaultName,
      isMobile: isMobile,
      pinProvider: _VaultCrypto.currentPinOrThrow,
      onAskVaultAI: (prompt) async {
        setState(() => selectedSection = _DashboardSection.chat);
        await _sendQuickPrompt(prompt);
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (_, constraints) {
        final isMobile = constraints.maxWidth < 980;

        return Scaffold(
          key: _scaffoldKey,
          drawer: _buildSidebar(),
          appBar: TopNavBar(
            isMobile: isMobile,
            showMenuButton: true,
            onMenuTap: () => _scaffoldKey.currentState?.openDrawer(),
            onCreateTap: _showCreateMenu,
          ),
          body: _buildBody(isMobile),
        );
      },
    );
  }
}

class _DeleteVaultSettingsTile extends StatelessWidget {
  const _DeleteVaultSettingsTile();

  Future<void> _handleTap(BuildContext context) async {
    final app = context.read<AppState>();
    final token = app.sessionToken;
    if (token == null || token.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            AppLocalizations.of(context).deleteVaultSignInRequired,
          ),
        ),
      );
      return;
    }
    final client = VaultAIClient(baseUrl: backendBaseUrl);
    final deleted = await showDeleteVaultDialog(
      context,
      client: client,
      authToken: token,
      onDeleted: () {},
    );

    if (deleted) {
      await app.handleVaultDeleted();
    }
  }

  @override
  Widget build(BuildContext context) {
    const dangerColor = Color(0xFFE0605C);
    return InkWell(
      key: const Key('settings_delete_vault_tile'),
      onTap: () => _handleTap(context),
      borderRadius: BorderRadius.circular(18),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: dangerColor.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(
            color: dangerColor.withValues(alpha: 0.30),
          ),
        ),
        child: Row(
          children: const [
            Icon(Icons.delete_forever_outlined, color: dangerColor),
            SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Delete vault',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: dangerColor,
                    ),
                  ),
                  SizedBox(height: 2),
                  Text(
                    'Permanently delete your SVaultAI vault. This '
                    'cannot be undone. Trusted device + PIN + exact '
                    'phrase required.',
                    style: TextStyle(
                      color: Color(0xFFB4B4B4),
                      fontSize: 13,
                    ),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: dangerColor),
          ],
        ),
      ),
    );
  }
}

// Exposed to widget tests via @visibleForTesting so the a11y +
// viewport-overflow suite in test/language_card_viewport_2026_07_17_test.dart
// can mount the card in isolation. Not part of the app's public API
// beyond that annotation.
@visibleForTesting
class LanguageCard extends StatefulWidget {
  const LanguageCard({super.key});

  @override
  State<LanguageCard> createState() => _LanguageCardState();
}

class _LanguageCardState extends State<LanguageCard> {
  final TextEditingController _searchCtrl = TextEditingController();
  String _query = '';
  bool _expanded = false;
  bool _appliedInitialExpansion = false;

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  // If the user's currently-selected locale is not in the Popular
  // shortlist, auto-expand the "All languages" section on the
  // first build so the selection is always visible without the
  // user having to discover the toggle. Fires once per mount;
  // subsequent user interactions with the toggle are respected.
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_appliedInitialExpansion) return;
    _appliedInitialExpansion = true;
    final current = context.read<AppState>().appLocale;
    if (current != null && !_isPopular(current.languageCode)) {
      _expanded = true;
    }
  }

  bool _isPopular(String code) {
    for (final l in kPopularLanguages) {
      if (l.code == code) return true;
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final app = context.watch<AppState>();
    final current = app.appLocale;
    final systemLocale = WidgetsBinding.instance.platformDispatcher.locale;
    final systemMatch = findLanguageByCode(systemLocale.languageCode);
    final systemResolvedLabel =
        systemMatch?.nativeName ?? systemLocale.languageCode.toUpperCase();

    final visibleLangs = kSupportedLanguages
        .where((info) => info.matchesQuery(_query))
        .toList(growable: false);

    LanguageInfo? currentInfo;
    if (current != null) {
      currentInfo = findLanguageByCode(current.languageCode);
    }

    return Container(
      key: const Key('settings_language_card'),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.language, size: 18, color: Color(0xFFB4B4B4)),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  l.settingsLanguage,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            l.settingsLanguageHint,
            style: const TextStyle(
              color: Color(0xFFB4B4B4),
              fontSize: 13,
              height: 1.5,
            ),
          ),
          const SizedBox(height: 14),

          InkWell(
            key: const Key('settings_language_auto'),
            onTap: () => app.setAppLocale(null),
            borderRadius: BorderRadius.circular(12),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: current == null
                    ? const Color(0xFF10A37F).withValues(alpha: 0.18)
                    : const Color(0xFF2A2A2A),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: current == null
                      ? const Color(0xFF10A37F).withValues(alpha: 0.45)
                      : Colors.white12,
                ),
              ),
              child: Row(
                children: [
                  const Icon(Icons.autorenew,
                      size: 16, color: Color(0xFF10A37F)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          l.settingsLanguageAuto,
                          style: TextStyle(
                            color: current == null
                                ? Colors.white
                                : const Color(0xFFC7C7C7),
                            fontWeight: current == null
                                ? FontWeight.w700
                                : FontWeight.w500,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          l.settingsLanguageAutoResolvedTo(systemResolvedLabel),
                          style: const TextStyle(
                            color: Color(0xFF8E8E8E),
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (current == null)
                    const Icon(Icons.check, size: 16, color: Color(0xFF10A37F)),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),

          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            decoration: BoxDecoration(
              color: const Color(0xFF1F1F1F),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.white12),
            ),
            child: Row(
              children: [
                const Icon(Icons.search, size: 16, color: Color(0xFF8E8E8E)),
                const SizedBox(width: 6),
                Expanded(
                  child: TextField(
                    key: const Key('settings_language_search'),
                    controller: _searchCtrl,
                    onChanged: (v) => setState(() => _query = v),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                    ),
                    decoration: InputDecoration(
                      isCollapsed: true,
                      contentPadding: const EdgeInsets.symmetric(vertical: 10),
                      hintText: l.settingsLanguageSearchHint,
                      hintStyle: const TextStyle(
                          color: Color(0xFF8E8E8E), fontSize: 12),
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                    ),
                  ),
                ),
                if (_query.isNotEmpty)
                  IconButton(
                    key: const Key('settings_language_search_clear'),
                    icon: const Icon(Icons.close,
                        size: 14, color: Color(0xFF8E8E8E)),
                    onPressed: () {
                      _searchCtrl.clear();
                      setState(() => _query = '');
                    },
                  ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // 2026-07-17 UX redesign — replace the wall of chips with a
          // sectioned selectable list (iOS/Android Settings pattern).
          // Non-search state: a small Popular list + a "Show all
          // languages" toggle. Search state: a flat filtered list
          // with no section headers, matching the ChatGPT / Notion
          // search-clears-the-navigation UX.
          if (_query.trim().isNotEmpty) ...[
            if (visibleLangs.isEmpty)
              Padding(
                key: const Key('settings_language_no_matches'),
                padding: const EdgeInsets.symmetric(vertical: 18),
                child: Center(
                  child: Text(
                    l.settingsLanguageNoMatches(_query.trim()),
                    style: const TextStyle(
                      color: Color(0xFF8E8E8E),
                      fontSize: 13,
                    ),
                  ),
                ),
              )
            else
              Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final info in visibleLangs)
                    _LanguageListRow(
                      info: info,
                      selected:
                          current != null && current.languageCode == info.code,
                      onTap: () => app.setAppLocale(Locale(info.code)),
                    ),
                ],
              ),
          ] else ...[
            _LanguageSectionHeader(label: l.settingsLanguagePopular),
            const SizedBox(height: 4),
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final info in kPopularLanguages)
                  _LanguageListRow(
                    info: info,
                    selected:
                        current != null && current.languageCode == info.code,
                    onTap: () => app.setAppLocale(Locale(info.code)),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            InkWell(
              key: const Key('settings_language_show_all'),
              onTap: () => setState(() => _expanded = !_expanded),
              borderRadius: BorderRadius.circular(10),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                constraints: const BoxConstraints(minHeight: 44),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.02),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white12),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        _expanded
                            ? l.settingsLanguageShowFewer
                            : l.settingsLanguageShowAll(
                                kSupportedLanguages.length -
                                    kPopularLanguages.length),
                        style: const TextStyle(
                          color: Color(0xFFC7C7C7),
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    AnimatedRotation(
                      duration: const Duration(milliseconds: 180),
                      turns: _expanded ? 0.5 : 0.0,
                      child: const Icon(
                        Icons.keyboard_arrow_down,
                        size: 20,
                        color: Color(0xFFC7C7C7),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            ClipRect(
              child: AnimatedSize(
                duration: const Duration(milliseconds: 180),
                curve: Curves.easeInOut,
                alignment: Alignment.topCenter,
                child: _expanded
                    ? Column(
                        key: const Key('settings_language_all_expanded'),
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          const SizedBox(height: 10),
                          _LanguageSectionHeader(
                              label: l.settingsLanguageAllLanguages),
                          const SizedBox(height: 4),
                          for (final info in kSupportedLanguages)
                            if (!_isPopular(info.code))
                              _LanguageListRow(
                                info: info,
                                selected: current != null &&
                                    current.languageCode == info.code,
                                onTap: () =>
                                    app.setAppLocale(Locale(info.code)),
                              ),
                        ],
                      )
                    : const SizedBox(width: double.infinity),
              ),
            ),
          ],

          if (currentInfo != null && !currentInfo.fullyLocalised) ...[
            const SizedBox(height: 12),
            Container(
              key: const Key('settings_language_partial_notice'),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFFE0A83E).withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: const Color(0xFFE0A83E).withValues(alpha: 0.28),
                ),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.info_outline,
                      size: 14, color: Color(0xFFE0A83E)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      l.settingsLanguagePartialNotice(currentInfo.englishName),
                      style: const TextStyle(
                        color: Color(0xFFE0A83E),
                        fontSize: 12,
                        height: 1.4,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// Small uppercase caption used above the Popular / All-Languages
// groups on the Language card. Matches the iOS/Android Settings
// language-picker treatment (dim, wide-tracked, uppercase).
class _LanguageSectionHeader extends StatelessWidget {
  final String label;
  const _LanguageSectionHeader({required this.label});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 2, bottom: 2, left: 4),
      child: Text(
        label,
        style: const TextStyle(
          color: Color(0xFF8E8E8E),
          fontSize: 11,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.7,
        ),
      ),
    );
  }
}

// Full-width selectable language row. Replaces the previous chip
// treatment so the list scales to arbitrarily many languages
// without stretching the Settings page and keeps the 48-pt tap
// target iOS accessibility guidelines call for.
class _LanguageListRow extends StatelessWidget {
  final LanguageInfo info;
  final bool selected;
  final VoidCallback onTap;

  const _LanguageListRow({
    required this.info,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final showEnglish = info.englishName != info.nativeName;
    return Semantics(
      button: true,
      selected: selected,
      label: showEnglish
          ? '${info.nativeName}, ${info.englishName}'
          : info.nativeName,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Material(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(10),
          child: InkWell(
            key: Key('settings_language_row_${info.code}'),
            onTap: onTap,
            borderRadius: BorderRadius.circular(10),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              curve: Curves.easeOut,
              constraints: const BoxConstraints(minHeight: 48),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: selected
                    ? const Color(0xFF10A37F).withValues(alpha: 0.16)
                    : Colors.transparent,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: selected
                      ? const Color(0xFF10A37F).withValues(alpha: 0.45)
                      : Colors.white10,
                ),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          info.nativeName,
                          style: TextStyle(
                            color: selected
                                ? Colors.white
                                : const Color(0xFFEAEAEA),
                            fontSize: 14,
                            fontWeight:
                                selected ? FontWeight.w700 : FontWeight.w500,
                            height: 1.2,
                          ),
                        ),
                        if (showEnglish) ...[
                          const SizedBox(height: 2),
                          Text(
                            info.englishName,
                            style: const TextStyle(
                              color: Color(0xFF8E8E8E),
                              fontSize: 11,
                              height: 1.2,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  if (selected)
                    const Padding(
                      padding: EdgeInsets.only(left: 10),
                      child: Icon(
                        Icons.check,
                        size: 18,
                        color: Color(0xFF10A37F),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _OverviewCard extends StatelessWidget {
  final _OverviewCardData data;

  const _OverviewCard({required this.data});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF262626),
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        children: [
          Container(
            width: 62,
            height: 62,
            decoration: BoxDecoration(
              color: data.bgColor,
              borderRadius: BorderRadius.circular(18),
            ),
            child: Icon(
              data.icon,
              color: data.iconColor,
              size: 30,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  data.title,
                  style: const TextStyle(
                    color: Color(0xFFA3A3A3),
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  data.value,
                  style: TextStyle(
                    fontSize: vrMetric(context),
                    fontWeight: FontWeight.w800,
                    height: 1,
                    color: Colors.white,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _VaultSwitcher extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final vaults = app.availableVaults;
    final current = app.vaultName;
    if (vaults.length <= 1 || current == null) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF2A2A2A),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        children: [
          const Icon(Icons.swap_horiz, size: 18, color: Color(0xFFB4B4B4)),
          const SizedBox(width: 8),
          Text(
            AppLocalizations.of(context).dashboardActiveVault,
            style: const TextStyle(color: Color(0xFFB4B4B4), fontSize: 13),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: DropdownButton<String>(
              value: current,
              isExpanded: true,
              underline: const SizedBox.shrink(),
              dropdownColor: const Color(0xFF2F2F2F),
              items: vaults.map((v) {
                final name = (v['vault_name'] ?? '').toString();
                final inheritedFrom = v['inherited_from_label']?.toString();
                final label = inheritedFrom == null
                    ? name
                    : '$name  (inherited from $inheritedFrom)';
                return DropdownMenuItem<String>(
                  value: name,
                  child: Text(label, overflow: TextOverflow.ellipsis),
                );
              }).toList(),
              onChanged: (newName) {
                if (newName == null || newName == current) return;
                app.requestSwitchVault(newName, context);
              },
            ),
          ),
        ],
      ),
    );
  }
}

/// Origin snapshot for a cached crypto key: the exact (pin_salt,
/// kdf_iterations) pair the current [SecretKey] was derived from.
///
/// LEGACY — kept for back-compat with pre-2026-07-22 call sites.
/// New code MUST use [VaultCryptoContext] via [VaultCryptoRegistry].
class _KeyOrigin {
  final String saltBase64;
  final int iterations;
  const _KeyOrigin({required this.saltBase64, required this.iterations});
}

/// Immutable snapshot of the vault's crypto state at a specific
/// generation. Every derive/rotation/refresh atomically REPLACES the
/// whole object via [VaultCryptoRegistry.install]. Never mutate any
/// field, never construct one without going through the registry.
///
/// The 2026-07-22 production incident (see f8210d6 deployment
/// aftermath): the pre-fix code stored the key in one map
/// (`_keyCache`) and its (salt, iter) origin in another
/// (`_keyOrigin`), updated by different code paths at different
/// times. The three ZK login/signup paths wrote MVK into `_keyCache`
/// without touching `_keyOrigin` at all. On the /chat send path,
/// `_send()` read the origin first (returning null for the ZK
/// slot), then read the key (returning the MVK), producing a
/// ciphertext-encrypted-with-MVK that was declared as PBKDF2 salt.
/// Server matched the metadata, derived PBKDF2 K, tried to decrypt
/// MVK-ciphertext → 400 "Invalid PIN or corrupted data" → client
/// signed the user out and later showed "Incorrect PIN". Root cause
/// was that the key and its metadata were NEVER an atomic unit.
///
/// This class is that atomic unit. There is exactly one live
/// [VaultCryptoRegistry._current] per session; every writer replaces
/// the whole object under a monotonically-increasing generation
/// guard so a stale async completion cannot clobber newer state.
///
/// **/chat contract**: every send path MUST snapshot the whole
/// context ONCE with `VaultCryptoRegistry.current`, then use the
/// same snapshot for both `context.key` (encryption) and
/// `context.saltBase64` / `context.iterations` (declared metadata).
/// No await may sit between the snapshot capture and constructing
/// the request unless the same immutable snapshot is retained.
@immutable
class VaultCryptoContext {
  final String vaultId;
  final String vaultName;
  final SecretKey key;
  final String pin;
  final String saltBase64;
  final int iterations;
  final int generation;
  final String source;

  const VaultCryptoContext({
    required this.vaultId,
    required this.vaultName,
    required this.key,
    required this.pin,
    required this.saltBase64,
    required this.iterations,
    required this.generation,
    required this.source,
  });
}

/// Non-secret fingerprints for the diagnostic log. First 12 hex
/// chars of SHA-256(bytes) — enough to distinguish keys / salts in
/// production logs without exposing any secret material.
Future<String> cryptoFingerprintForKey(SecretKey key) async {
  try {
    final bytes = await key.extractBytes();
    return _fp12(Uint8List.fromList(bytes));
  } catch (_) {
    return 'unavailable';
  }
}

String cryptoFingerprintForSaltBase64(String saltBase64) {
  try {
    final raw = base64Decode(saltBase64);
    return _fp12(raw);
  } catch (_) {
    return 'unavailable';
  }
}

String _fp12(Uint8List bytes) {
  final digest = sha256.convert(bytes);
  final hex = digest.toString();
  return hex.length >= 12 ? hex.substring(0, 12) : hex;
}

/// Registry of the vault's authoritative [VaultCryptoContext].
///
/// Every writer (unlock, verifyPin, ZK login, ZK signup, session
/// restore, rotation, 409-refresh, etc.) MUST:
///
///   1. Reserve an operation id via [nextOperationId] BEFORE any
///      async work.
///   2. Perform its async derivation.
///   3. Construct a [VaultCryptoContext] with
///      `generation: nextGeneration()`.
///   4. Call [install]. The install is refused if the operation id
///      was superseded by a later reservation, and it is refused if
///      the constructed generation is not strictly greater than the
///      currently-installed generation. Both guards must pass — the
///      operation id catches "started earlier but finishing later",
///      the generation catches "wrote directly without reserving."
///
/// The registry has NO getters that expose the key or PIN by pointer
/// — the only way to obtain them is via a full context snapshot,
/// which guarantees the caller can never end up with a key from one
/// generation and metadata from another.
class VaultCryptoRegistry {
  static VaultCryptoContext? _current;
  static int _generationSeq = 0;
  static int _operationSeq = 0;

  static VaultCryptoContext? get current => _current;

  /// Reserve an operation id for an in-flight derivation. The id is
  /// checked at [install] time; a later reservation invalidates the
  /// earlier one so a stale async completion cannot overwrite newer
  /// state.
  static int nextOperationId() {
    return ++_operationSeq;
  }

  /// Return the current sequence peak. install() will refuse a
  /// write whose operationId is not equal to this peak (i.e. some
  /// later reservation has taken over).
  static int currentOperationPeak() => _operationSeq;

  /// Allocate the next generation number for a new context. Called
  /// AFTER the async derivation completes, right before install.
  static int nextGeneration() {
    return ++_generationSeq;
  }

  /// Install a new context atomically. Returns true on success, false
  /// when refused (stale operation id, non-monotonic generation, or
  /// mismatched vault). NEVER partially updates state on refusal.
  static bool install({
    required int operationId,
    required VaultCryptoContext context,
  }) {
    if (operationId != _operationSeq) {
      vlog('crypto.context.install.stale', {
        'reason': 'operation_id_superseded',
        'op_id': operationId,
        'peak': _operationSeq,
        'source': context.source,
      });
      return false;
    }
    final current = _current;
    if (current != null && context.generation <= current.generation) {
      vlog('crypto.context.install.stale', {
        'reason': 'generation_not_greater',
        'ctx_gen': context.generation,
        'current_gen': current.generation,
        'source': context.source,
      });
      return false;
    }
    _current = context;
    // Diagnostic log — fingerprints only, never key bytes / salt bytes
    // / pin. Fingerprint call is fire-and-forget so it never blocks
    // the install path.
    unawaited(cryptoFingerprintForKey(context.key).then((keyFp) {
      vlog('crypto.context.installed', {
        'vault_id': context.vaultId,
        'vault_name': context.vaultName,
        'generation': context.generation,
        'prev_generation': current?.generation,
        'op_id': operationId,
        'source': context.source,
        'iterations': context.iterations,
        'key_fp12': keyFp,
        'salt_fp12': cryptoFingerprintForSaltBase64(context.saltBase64),
      });
    }));
    return true;
  }

  /// Clear the context — session end / vault switch / explicit
  /// invalidation. Also resets the generation counter for the next
  /// unlock cycle so the numbers stay small in logs.
  static void clear({String? reason}) {
    final prev = _current;
    _current = null;
    _generationSeq = 0;
    _operationSeq = 0;
    if (prev != null) {
      vlog('crypto.context.cleared', {
        'reason': reason ?? 'unspecified',
        'prev_generation': prev.generation,
        'prev_vault_id': prev.vaultId,
      });
    }
  }

  /// For diagnostics only.
  static Map<String, Object?> debugSnapshot() {
    final c = _current;
    return {
      'has_current': c != null,
      'vault_id': c?.vaultId,
      'vault_name': c?.vaultName,
      'generation': c?.generation,
      'iterations': c?.iterations,
      'operation_peak': _operationSeq,
      'source': c?.source,
    };
  }
}

/// PBKDF2-derive a key AND install the atomic context in one guarded
/// operation. Used by every unlock/rotate/refresh path.
///
/// - Reserves an operation id BEFORE the derive.
/// - Runs PBKDF2 (the expensive step).
/// - Constructs a [VaultCryptoContext] with a fresh generation.
/// - Installs via [VaultCryptoRegistry.install]. If the install is
///   refused (a later reservation superseded us), the returned
///   context is null and the caller MUST NOT proceed as if the key
///   were live.
///
/// Also mirrors the derived key into the legacy `_VaultCrypto`
/// caches so any code path that still reads `_keyCache` / `_pinCache`
/// / `_keyOrigin` sees a consistent view. New code should read from
/// [VaultCryptoRegistry.current] exclusively.
Future<VaultCryptoContext?> deriveAndInstallCryptoContext({
  required String vaultId,
  required String vaultName,
  required String pin,
  required String pinSaltBase64,
  required int iterations,
  required String source,
}) async {
  final opId = VaultCryptoRegistry.nextOperationId();

  final secretKey = await _deriveVaultPbkdf2Key(
    pin: pin,
    pinSaltBase64: pinSaltBase64,
    iterations: iterations,
  );

  final gen = VaultCryptoRegistry.nextGeneration();
  final context = VaultCryptoContext(
    vaultId: vaultId,
    vaultName: vaultName,
    key: secretKey,
    pin: pin,
    saltBase64: pinSaltBase64,
    iterations: iterations,
    generation: gen,
    source: source,
  );

  final ok = VaultCryptoRegistry.install(
    operationId: opId,
    context: context,
  );
  if (!ok) {
    // Superseded — do NOT mirror into legacy caches (would clobber a
    // newer install's mirror below).
    return null;
  }

  // Legacy mirror — keep the old caches in lock-step with the
  // registry so no read path is left dangling. Deliberately after
  // the install success check so a stale derive never overwrites
  // the newer install's mirror.
  final k = _VaultCrypto._ck(vaultId, vaultName);
  _VaultCrypto._keyCache[k] = secretKey;
  _VaultCrypto._pinCache[k] = pin;
  _VaultCrypto._keyOrigin[k] = _KeyOrigin(
    saltBase64: pinSaltBase64,
    iterations: iterations,
  );
  _VaultCrypto._activeVaultId = vaultId;
  _VaultCrypto._activeVaultName = vaultName;

  return context;
}

Future<SecretKey> _deriveVaultPbkdf2Key({
  required String pin,
  required String pinSaltBase64,
  required int iterations,
}) async {
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    final keyBytes = await OpaqueClient.pbkdf2HmacSha256(
      password: pin,
      saltBase64: pinSaltBase64,
      iterations: iterations,
    );
    if (keyBytes.length != 32) {
      vlog('crypto.pbkdf2.native_bad_length', {'length': keyBytes.length});
      throw StateError('Native PBKDF2 returned an invalid key length.');
    }
    return SecretKey(keyBytes);
  }

  final algorithm = Pbkdf2(
    macAlgorithm: Hmac.sha256(),
    iterations: iterations,
    bits: 256,
  );
  return algorithm.deriveKey(
    secretKey: SecretKey(utf8.encode(pin)),
    nonce: base64Decode(pinSaltBase64),
  );
}

/// Encrypt [plaintext] using [context.key] atomically. No implicit
/// registry lookups. The caller passes the context snapshot they
/// intend to declare in the request body, and this function uses
/// EXACTLY that key. This is what enforces the "key and metadata
/// come from the same context" contract at the crypto boundary.
Future<String> encryptWithContext({
  required String plaintext,
  required VaultCryptoContext context,
}) async {
  final algorithm = AesGcm.with256bits();
  final nonce = algorithm.newNonce();
  final secretBox = await algorithm.encrypt(
    utf8.encode(plaintext),
    secretKey: context.key,
    nonce: nonce,
  );
  final combined = <int>[
    ...nonce,
    ...secretBox.cipherText,
    ...secretBox.mac.bytes,
  ];
  return base64.encode(combined);
}

class _VaultCrypto {
  static final Map<String, SecretKey> _keyCache = {};
  static final Map<String, String> _pinCache = {};
  static final Map<String, _KeyOrigin> _keyOrigin = {};

  static String? _activeVaultId;
  static String? _activeVaultName;

  static String _ck(String vaultId, String vaultName) => '$vaultId|$vaultName';

  /// Return the (salt, iterations) that the currently-cached key for
  /// (vaultId, vaultName) was derived from, or ``null`` if no key is
  /// cached for that slot. Used by `AppState.resyncCryptoKeyIfDrifted`
  /// to decide whether the cache is authoritative or needs a fresh
  /// PBKDF2 pass against the server's current DB state.
  static _KeyOrigin? originFor({
    required String vaultId,
    required String vaultName,
  }) {
    return _keyOrigin[_ck(vaultId, vaultName)];
  }

  static void setActiveVault({
    required String vaultId,
    required String vaultName,
  }) {
    _activeVaultId = vaultId;
    _activeVaultName = vaultName;
    vlog('crypto.setActiveVault', {
      'vault_id': vaultId,
      'vaultName': vaultName,
      'hasKeyForThisSlot': _keyCache.containsKey(_ck(vaultId, vaultName)),
      'keyCacheSize': _keyCache.length,
    });
  }

  static bool hasKeyFor({
    required String vaultId,
    required String vaultName,
  }) {
    return _keyCache.containsKey(_ck(vaultId, vaultName));
  }

  static Future<void> deriveAndCacheKey({
    required String pin,
    required String vaultId,
    required String vaultName,
    required String pinSaltBase64,
    required int iterations,
  }) async {
    final algorithm = Pbkdf2(
      macAlgorithm: Hmac.sha256(),
      iterations: iterations,
      bits: 256,
    );

    final secretKey = await algorithm.deriveKey(
      secretKey: SecretKey(utf8.encode(pin)),
      nonce: base64Decode(pinSaltBase64),
    );

    final k = _ck(vaultId, vaultName);
    _keyCache[k] = secretKey;
    _pinCache[k] = pin;
    _keyOrigin[k] = _KeyOrigin(
      saltBase64: pinSaltBase64,
      iterations: iterations,
    );
    _activeVaultId = vaultId;
    _activeVaultName = vaultName;
    vlog('crypto.deriveAndCacheKey.stored', {
      'vault_id': vaultId,
      'vaultName': vaultName,
      'iterations': iterations,
      'saltLen': pinSaltBase64.length,
      'keyCacheSize': _keyCache.length,
    });
  }

  static SecretKey _requireActiveKey() {
    final id = _activeVaultId;
    final v = _activeVaultName;
    if (id == null || v == null) {
      throw const InvalidVaultUnlockException();
    }
    final key = _keyCache[_ck(id, v)];
    if (key == null) {
      throw const InvalidVaultUnlockException();
    }
    return key;
  }

  static Future<String> encrypt(String plaintext) async {
    final key = _requireActiveKey();
    final algorithm = AesGcm.with256bits();
    final nonce = algorithm.newNonce();
    final secretBox = await algorithm.encrypt(
      utf8.encode(plaintext),
      secretKey: key,
      nonce: nonce,
    );

    final combined = <int>[
      ...nonce,
      ...secretBox.cipherText,
      ...secretBox.mac.bytes
    ];
    return base64.encode(combined);
  }

  static Future<String> decrypt(String encryptedB64) async {
    final key = _requireActiveKey();

    final combined = base64.decode(encryptedB64);
    if (combined.length < 28) {
      throw Exception('Invalid encrypted payload');
    }

    final nonce = combined.sublist(0, 12);
    final ciphertext = combined.sublist(12, combined.length - 16);
    final mac = combined.sublist(combined.length - 16);

    final algorithm = AesGcm.with256bits();
    final secretBox = SecretBox(ciphertext, nonce: nonce, mac: Mac(mac));
    final plaintext = await algorithm.decrypt(secretBox, secretKey: key);
    return utf8.decode(plaintext);
  }

  static Future<String> currentPinOrThrow() async {
    final id = _activeVaultId;
    final v = _activeVaultName;
    if (id == null || v == null) {
      throw const InvalidVaultUnlockException();
    }
    final pin = _pinCache[_ck(id, v)];
    if (pin == null) {
      throw const InvalidVaultUnlockException();
    }
    return pin;
  }

  static String? cachedPinFor({
    required String vaultId,
    required String vaultName,
  }) {
    if (vaultId.isEmpty || vaultName.isEmpty) return null;
    return _pinCache[_ck(vaultId, vaultName)];
  }

  static Future<List<int>> currentKeyBytesOrThrow() async {
    return _requireActiveKey().extractBytes();
  }

  static void clearCache(String vaultId) {
    final prefix = '$vaultId|';
    final before = _keyCache.length;
    _keyCache.removeWhere((k, _) => k.startsWith(prefix));
    _pinCache.removeWhere((k, _) => k.startsWith(prefix));
    _keyOrigin.removeWhere((k, _) => k.startsWith(prefix));
    final wasActive = _activeVaultId == vaultId;
    if (wasActive) {
      _activeVaultId = null;
      _activeVaultName = null;
    }
    // 2026-07-22: keep the authoritative VaultCryptoContext in
    // lock-step with the legacy cache. If the leaving vault was
    // the active one, clear the registry too.
    if (VaultCryptoRegistry.current?.vaultId == vaultId) {
      VaultCryptoRegistry.clear(reason: 'clearCache');
    }
    vlog('crypto.clearCache', {
      'vault_id': vaultId,
      'removed': before - _keyCache.length,
      'remaining': _keyCache.length,
      'clearedActive': wasActive,
    });
  }

  static Map<String, Object?> debugSnapshot() {
    return {
      'activeVaultId': _activeVaultId,
      'activeVaultName': _activeVaultName,
      'keyCacheSize': _keyCache.length,
      'pinCacheSize': _pinCache.length,
      'activeHasKey': _activeVaultId != null &&
          _activeVaultName != null &&
          _keyCache.containsKey(_ck(_activeVaultId!, _activeVaultName!)),
    };
  }
}

class _CryptoVaultBillingStatusBanner extends StatelessWidget {
  final bool errored;
  final VoidCallback onRetry;
  final VoidCallback? onDismiss;
  const _CryptoVaultBillingStatusBanner({
    super.key,
    required this.errored,
    required this.onRetry,
    this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    final label = errored
        ? 'Subscription status is temporarily unavailable.'
        : 'Checking subscription status…';
    return Material(
      color: Colors.transparent,
      child: Container(
        key: const Key('crypto_vault_billing_status_banner'),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: const Color(0xFF1E1E1E).withOpacity(0.96),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0x33FFFFFF)),
          boxShadow: const [
            BoxShadow(
              color: Color(0x40000000),
              blurRadius: 8,
              offset: Offset(0, 2),
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              errored ? Icons.cloud_off_outlined : Icons.hourglass_top_outlined,
              key: Key(errored
                  ? 'crypto_vault_billing_banner_error_icon'
                  : 'crypto_vault_billing_banner_loading_icon'),
              color: const Color(0xFFEFB66B),
              size: 16,
            ),
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                label,
                key: const Key('crypto_vault_billing_banner_message'),
                style: const TextStyle(
                  color: Color(0xFFDDDDDD),
                  fontSize: 12,
                ),
                overflow: TextOverflow.ellipsis,
                maxLines: 1,
              ),
            ),
            if (errored) ...[
              const SizedBox(width: 8),
              TextButton(
                key: const Key('crypto_vault_access_error_retry_button'),
                onPressed: onRetry,
                style: TextButton.styleFrom(
                  foregroundColor: const Color(0xFFE6E6E6),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  minimumSize: Size.zero,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  textStyle: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                child: const Text('Retry'),
              ),
            ],
            if (onDismiss != null) ...[
              const SizedBox(width: 4),
              IconButton(
                key: const Key('crypto_vault_billing_banner_dismiss_button'),
                tooltip: 'Dismiss',
                onPressed: onDismiss,
                iconSize: 14,
                padding: EdgeInsets.zero,
                visualDensity: VisualDensity.compact,
                constraints: const BoxConstraints.tightFor(
                  width: 22,
                  height: 22,
                ),
                icon: const Icon(
                  Icons.close_rounded,
                  color: Color(0xFFB4B4B4),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
