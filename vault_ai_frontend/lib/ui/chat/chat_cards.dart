import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import '../../l10n/app_localizations.dart';
import '../primitives.dart';
import '../tokens.dart';
import 'chat_models.dart';

bool _vaultAiDeepScanDebugUiEnabled = false;
bool isDeepScanDebugUiEnabled() => _vaultAiDeepScanDebugUiEnabled;
void setDeepScanDebugUiEnabled(bool enabled) {
  _vaultAiDeepScanDebugUiEnabled = enabled;
}

bool _isImageMime(String? mime) =>
    (mime ?? '').toLowerCase().startsWith('image/');
bool _isVideoMime(String? mime) =>
    (mime ?? '').toLowerCase().startsWith('video/');
bool _isAudioMime(String? mime) =>
    (mime ?? '').toLowerCase().startsWith('audio/');

IconData _iconForMime(String? mime) {
  if (_isImageMime(mime)) return Icons.image_outlined;
  if (_isVideoMime(mime)) return Icons.movie_outlined;
  if (_isAudioMime(mime)) return Icons.audiotrack;
  final m = (mime ?? '').toLowerCase();
  if (m == 'application/pdf') return Icons.picture_as_pdf_outlined;
  return Icons.insert_drive_file_outlined;
}

const List<String> _kForbiddenEmptyStatePhrases = <String>[
  'no matches yet',
  "i'm still analyzing your vault",
  'still analyzing your vault',
  'ask again in a moment',
  'try again in a moment',
];

bool _containsForbiddenEmptyStateCopy(String text) {
  final low = text.toLowerCase();
  for (final phrase in _kForbiddenEmptyStatePhrases) {
    if (low.contains(phrase)) return true;
  }
  return false;
}

String _sanitizeStaleEmptyStateText({
  required String original,
  required bool isComplete,
  required int count,
  required bool isStrictIdPhoto,
  String? requestedPersonName,
}) {
  if (!_containsForbiddenEmptyStateCopy(original)) {
    return original;
  }
  if (kDebugMode) {
    print(
      '[file_search_results] sanitized_stale_copy '
      'is_complete=$isComplete count=$count '
      'is_strict=$isStrictIdPhoto',
    );
  }
  if (!isComplete) {
    return 'Search incomplete. I checked what I could, but the '
        'search hit its limit.';
  }
  if (count == 0) {
    final person = (requestedPersonName ?? '').trim();
    if (isStrictIdPhoto) {
      if (person.isNotEmpty) {
        return "I couldn't find an ID photo for $person.";
      }
      return 'No matching ID photo found.';
    }
    if (person.isNotEmpty) {
      return "I couldn't find any files matching $person.";
    }
    return 'No matching files found in your vault.';
  }

  return '';
}

class VaultFileCard extends StatelessWidget {
  final ChatMessage msg;
  final VoidCallback? onOpen;
  final VoidCallback? onDownload;

  /// True while `onOpen` is fetching + decrypting bytes. When true the
  /// View button shows a spinner + "Opening…" and does NOT re-fire on
  /// tap. Set by AppState.isFileViewInFlight and threaded down from
  /// ChatMessageList.
  final bool isViewInFlight;

  /// True while `onDownload` is fetching + decrypting bytes. When true
  /// the Download button shows a spinner + "Downloading…".
  final bool isDownloadInFlight;

  final void Function(String fileId)? onShowRelated;

  const VaultFileCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onDownload,
    this.isViewInFlight = false,
    this.isDownloadInFlight = false,
    this.onShowRelated,
  });

  @override
  Widget build(BuildContext context) {
    final mime = msg.mimeType ?? '';
    final p = msg.payload ?? const <String, dynamic>{};
    final assetType = (p['asset_type'] as String?)?.trim();
    final size = p['size_bytes'] is int ? p['size_bytes'] as int : null;
    final savedName = (p['saved_name'] as String?)?.trim();

    final relativePath = (p['relative_path'] as String?)?.trim();
    final tags = (p['tags'] is List)
        ? (p['tags'] as List).whereType<String>().toList()
        : const <String>[];

    final title = (savedName != null && savedName.isNotEmpty)
        ? savedName
        : (msg.fileName ?? 'Vault file');

    final subtitleParts = <String>[
      if (assetType != null && assetType.isNotEmpty) assetType,
      if (mime.isNotEmpty) mime,
      if (size != null) _formatBytes(size),
    ];

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (msg.text.trim().isNotEmpty) ...[
            Text(msg.text, style: VaultText.body),
            const SizedBox(height: VaultSpacing.md),
          ],
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              IconBadge(
                icon: _iconForMime(mime),
                color: VaultColors.accent,
                size: 48,
                radius: VaultRadius.md,
              ),
              const SizedBox(width: VaultSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: VaultText.subtitle,
                    ),
                    if (relativePath != null && relativePath.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Row(
                        children: [
                          const Icon(
                            Icons.folder_outlined,
                            size: 12,
                            color: VaultColors.textTertiary,
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: Text(
                              relativePath,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: VaultText.caption,
                            ),
                          ),
                        ],
                      ),
                    ],
                    if (subtitleParts.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        subtitleParts.join(' / '),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: VaultText.caption,
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          if (tags.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Wrap(
              spacing: VaultSpacing.xs + 2,
              runSpacing: VaultSpacing.xs,
              children: tags.map((t) => MetaPill(label: t)).toList(),
            ),
          ],
          const SizedBox(height: VaultSpacing.lg),
          Wrap(
            spacing: VaultSpacing.sm,
            runSpacing: VaultSpacing.sm,
            children: [
              // Disable BOTH buttons while either action is in flight
              // for this file — a user should not be able to start a
              // download mid-view or fire a second view.
              Semantics(
                container: true,
                identifier: 'vault_file_card_view_btn',
                button: true,
                child: FilledButton.icon(
                  key: const Key('vault_file_card_view_btn'),
                  onPressed:
                      (isViewInFlight || isDownloadInFlight) ? null : onOpen,
                  icon: isViewInFlight
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                          ),
                        )
                      : const Icon(Icons.visibility_outlined, size: 18),
                  label: Text(
                    isViewInFlight
                        ? 'Opening…'
                        : AppLocalizations.of(context).commonView,
                  ),
                ),
              ),
              Semantics(
                container: true,
                identifier: 'vault_file_card_download_btn',
                button: true,
                child: OutlinedButton.icon(
                  key: const Key('vault_file_card_download_btn'),
                  onPressed: (isViewInFlight || isDownloadInFlight)
                      ? null
                      : (onDownload ?? onOpen),
                  icon: isDownloadInFlight
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                          ),
                        )
                      : const Icon(Icons.file_download_outlined, size: 18),
                  label: Text(
                    isDownloadInFlight
                        ? 'Downloading…'
                        : AppLocalizations.of(context).commonDownload,
                  ),
                ),
              ),
              if (onShowRelated != null && (msg.fileId ?? '').isNotEmpty)
                OutlinedButton.icon(
                  key: const Key('vault_file_card_show_related_btn'),
                  onPressed: (isViewInFlight || isDownloadInFlight)
                      ? null
                      : () => onShowRelated!(msg.fileId!),
                  icon: const Icon(
                    Icons.account_tree_outlined,
                    size: 18,
                  ),
                  label: Text(
                    AppLocalizations.of(context).chatCardShowRelated,
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  String _formatBytes(int bytes) {
    if (bytes >= 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
    }
    if (bytes >= 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    if (bytes >= 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '$bytes B';
  }
}

String _formatBytes(int bytes) {
  if (bytes >= 1024 * 1024 * 1024) {
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
  }
  if (bytes >= 1024 * 1024) {
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
  if (bytes >= 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '$bytes B';
}

class VaultFileListCard extends StatefulWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;

  /// Distinct callback for the Download row action. If null the
  /// Download button is not shown. Kept separate so the row cannot
  /// silently accept `onOpen` when a caller forgets to wire download.
  final void Function(ChatMessage fileMsg)? onDownload;

  final Future<Map<String, dynamic>?> Function(String fileId)? onLoadRelated;

  final void Function(String fileId)? onShowRelated;

  /// Set of file ids currently being fetched for View. Rows check
  /// membership to render a spinner and reject repeat taps.
  final Set<String> viewInFlight;

  /// Set of file ids currently being fetched for Download.
  final Set<String> downloadInFlight;

  /// Callback for the Show more button (real pagination, not a "refine
  /// your search" text hint). The parent should re-issue the chat
  /// prompt "show more" — the backend re-emits the same file-list
  /// envelope sliced at the next offset, so no duplicate rows appear.
  final VoidCallback? onShowMore;

  /// True while a Show more request is in flight for this card. Used
  /// to disable the button + render a spinner. Kept per-card so
  /// multiple stale file-list cards in scroll history do not race.
  final bool isShowMoreInFlight;

  static const int maxRows = 25;

  static const double maxListHeight = 380;

  const VaultFileListCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onDownload,
    this.onLoadRelated,
    this.onShowRelated,
    this.viewInFlight = const <String>{},
    this.downloadInFlight = const <String>{},
    this.onShowMore,
    this.isShowMoreInFlight = false,
  });

  @override
  State<VaultFileListCard> createState() => _VaultFileListCardState();

  static ChatMessage _toFileMessage(
    Map<String, dynamic> raw,
    ChatMessage list,
  ) {
    final relativePath = (raw['relative_path'] as String?)?.trim();
    final savedName = (raw['saved_name'] as String?)?.trim();
    final assetType = (raw['asset_type'] as String?)?.trim();
    final size = raw['size_bytes'];
    final payload = <String, dynamic>{
      if (relativePath != null && relativePath.isNotEmpty)
        'relative_path': relativePath,
      if (savedName != null && savedName.isNotEmpty) 'saved_name': savedName,
      if (assetType != null && assetType.isNotEmpty) 'asset_type': assetType,
      if (size is int) 'size_bytes': size,
    };
    return ChatMessage(
      'assistant',
      '',
      kind: ChatMessage.kVaultFile,
      fileId: (raw['file_id'] as String?),
      fileName: (raw['file_name'] as String?),
      mimeType: (raw['mime_type'] as String?),
      payload: payload.isEmpty ? null : payload,
      createdAt: list.createdAt,
    );
  }
}

class _VaultFileListCardState extends State<VaultFileListCard> {
  String? _expandedFileId;

  @override
  Widget build(BuildContext context) {
    final msg = widget.msg;
    final p = msg.payload ?? const <String, dynamic>{};
    final title = (p['title'] as String?)?.trim();
    final requestedName = (p['requested_name'] as String?)?.trim();
    final rawFiles = (p['files'] is List)
        ? (p['files'] as List).whereType<Map>().toList()
        : const <Map>[];

    final totalCount =
        p['total_count'] is int ? p['total_count'] as int : rawFiles.length;
    final shownCount = rawFiles.length > VaultFileListCard.maxRows
        ? VaultFileListCard.maxRows
        : rawFiles.length;
    final moreCount = p['more_count'] is int
        ? (p['more_count'] as int)
        : (totalCount - shownCount).clamp(0, 1 << 30);

    final files = rawFiles.take(shownCount).toList();

    final headerTitle = (title != null && title.isNotEmpty)
        ? title
        : (requestedName != null && requestedName.isNotEmpty
            ? 'Files named "$requestedName"'
            : 'Matching files');
    final headerSubtitle = totalCount == 1 ? '1 file' : '$totalCount files';

    final onOpen = widget.onOpen;
    final onLoadRelated = widget.onLoadRelated;
    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.folder_copy_outlined,
            iconColor: VaultColors.accent,
            title: headerTitle,
            subtitle: headerSubtitle,
          ),
          if (msg.text.trim().isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Text(msg.text, style: VaultText.body),
          ],
          if (files.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            ConstrainedBox(
              constraints: const BoxConstraints(
                maxHeight: VaultFileListCard.maxListHeight,
              ),
              child: Scrollbar(
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: files.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: VaultSpacing.sm),
                  itemBuilder: (context, i) {
                    final raw = files[i].cast<String, dynamic>();
                    final fid = (raw['file_id'] as String?) ?? '';
                    final canExpand = onLoadRelated != null && fid.isNotEmpty;
                    final isExpanded = canExpand && _expandedFileId == fid;
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _VaultFileListRow(
                          file: raw,
                          onOpen: () => onOpen?.call(
                            VaultFileListCard._toFileMessage(raw, msg),
                          ),
                          onDownload: widget.onDownload == null
                              ? null
                              : () => widget.onDownload!.call(
                                    VaultFileListCard._toFileMessage(raw, msg),
                                  ),
                          isViewInFlight: widget.viewInFlight.contains(fid),
                          isDownloadInFlight:
                              widget.downloadInFlight.contains(fid),
                          onShowRelated: canExpand
                              ? () => setState(() {
                                    _expandedFileId = isExpanded ? null : fid;
                                  })
                              : null,
                        ),
                        if (isExpanded)
                          _InlineRelatedSection(
                            fileId: fid,
                            parentMsg: msg,
                            onLoadRelated: onLoadRelated,
                            onOpen: onOpen,
                            onShowFullGraph: widget.onShowRelated,
                            onCollapse: () => setState(
                              () => _expandedFileId = null,
                            ),
                          ),
                      ],
                    );
                  },
                ),
              ),
            ),
          ],
          // Real pagination. When the backend indicates has_more, we
          // render a tappable Show more button that re-issues the
          // chat prompt "show more". While the request is in-flight
          // the button collapses to a spinner and can't fire again.
          if (_hasMoreForCurrentEnvelope(p) ||
              (moreCount > 0 && widget.onShowMore == null)) ...[
            const SizedBox(height: VaultSpacing.md),
            if (widget.onShowMore != null)
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  key: const Key('vault_file_list_show_more_btn'),
                  onPressed:
                      widget.isShowMoreInFlight ? null : widget.onShowMore,
                  icon: widget.isShowMoreInFlight
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                          ),
                        )
                      : const Icon(Icons.expand_more, size: 18),
                  label: Text(
                    widget.isShowMoreInFlight
                        ? 'Loading…'
                        : (moreCount > 0
                            ? 'Show more ($moreCount remaining)'
                            : 'Show more'),
                  ),
                ),
              )
            else
              Text(
                '+$moreCount more — say "show more" to see the next page.',
                style: VaultText.caption,
              ),
          ],
        ],
      ),
    );
  }

  /// Prefer the backend's explicit `has_more` flag over deriving it
  /// from `more_count`. Older envelopes without the flag fall back to
  /// the caller's `moreCount > 0` check.
  bool _hasMoreForCurrentEnvelope(Map<String, dynamic> p) {
    final flag = p['has_more'];
    if (flag is bool) return flag;
    final more = p['more_count'];
    return more is int && more > 0;
  }
}

class _VaultFileListRow extends StatelessWidget {
  final Map<String, dynamic> file;
  final VoidCallback? onOpen;
  final VoidCallback? onDownload;
  final bool isViewInFlight;
  final bool isDownloadInFlight;

  final VoidCallback? onShowRelated;

  const _VaultFileListRow({
    required this.file,
    this.onOpen,
    this.onDownload,
    this.isViewInFlight = false,
    this.isDownloadInFlight = false,
    this.onShowRelated,
  });

  @override
  Widget build(BuildContext context) {
    final fileName = (file['file_name'] as String?) ?? 'file';
    final savedName = (file['saved_name'] as String?)?.trim();
    final relativePath = (file['relative_path'] as String?)?.trim();
    final mime = (file['mime_type'] as String?) ?? '';
    final size = file['size_bytes'] is int ? file['size_bytes'] as int : null;

    final title =
        (savedName != null && savedName.isNotEmpty) ? savedName : fileName;

    final busy = isViewInFlight || isDownloadInFlight;
    final fileId = (file['file_id'] as String?) ?? '';
    return InkWell(
      key: Key('vault_file_list_row_$fileId'),
      onTap: busy ? null : onOpen,
      borderRadius: BorderRadius.circular(VaultRadius.md),
      child: Container(
        padding: const EdgeInsets.all(VaultSpacing.md),
        decoration: BoxDecoration(
          color: VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.md),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            IconBadge(
              icon: _iconForMime(mime),
              color: VaultColors.accent,
              size: 36,
              radius: VaultRadius.sm,
            ),
            const SizedBox(width: VaultSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: VaultText.subtitle.copyWith(fontSize: 15),
                  ),
                  if (relativePath != null && relativePath.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        const Icon(
                          Icons.folder_outlined,
                          size: 12,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            relativePath,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption,
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (mime.isNotEmpty || size != null) ...[
                    const SizedBox(height: 2),
                    Builder(builder: (_) {
                      // Prefer the backend-supplied size_display so
                      // the row always shows a human-readable size
                      // even if a client formatter drifts.
                      final serverSize =
                          (file['size_display'] as String?)?.trim();
                      final sizeStr =
                          (serverSize != null && serverSize.isNotEmpty)
                              ? serverSize
                              : (size != null ? _formatBytes(size) : null);
                      final uploaded = (file['uploaded_at'] as String?)?.trim();
                      final parts = <String>[
                        if (mime.isNotEmpty) mime,
                        if (sizeStr != null) sizeStr,
                        if (uploaded != null && uploaded.isNotEmpty)
                          'uploaded ${_shortDate(uploaded)}',
                      ];
                      if (parts.isEmpty) {
                        return const SizedBox.shrink();
                      }
                      return Text(
                        parts.join(' / '),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: VaultText.caption,
                      );
                    }),
                  ],
                ],
              ),
            ),
            const SizedBox(width: VaultSpacing.sm),
            // Per-row loading indicator: while the fetch runs the
            // row's action buttons collapse to a spinner so the user
            // sees progress AND cannot fire a second fetch.
            if (busy)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 8),
                child: SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              )
            else ...[
              Semantics(
                container: true,
                identifier: 'vault_file_list_row_view',
                button: true,
                child: IconButton(
                  key: Key('vault_file_list_row_view_$fileId'),
                  tooltip: AppLocalizations.of(context).commonView,
                  onPressed: onOpen,
                  icon: const Icon(
                    Icons.open_in_new,
                    size: 18,
                    color: VaultColors.accentBright,
                  ),
                ),
              ),
              if (onDownload != null)
                Semantics(
                  container: true,
                  identifier: 'vault_file_list_row_download',
                  button: true,
                  child: IconButton(
                    key: Key('vault_file_list_row_download_$fileId'),
                    tooltip: AppLocalizations.of(context).commonDownload,
                    onPressed: onDownload,
                    visualDensity: VisualDensity.compact,
                    icon: const Icon(
                      Icons.file_download_outlined,
                      size: 18,
                      color: VaultColors.accentBright,
                    ),
                  ),
                ),
              if (onShowRelated != null)
                IconButton(
                  key: Key('vault_file_list_row_related_$fileId'),
                  tooltip: AppLocalizations.of(context).chatCardShowRelated,
                  onPressed: onShowRelated,
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(
                    Icons.account_tree_outlined,
                    size: 18,
                    color: VaultColors.accentBright,
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }

  static String _shortDate(String iso) {
    // Best-effort short-date rendering. Falls back to first 10 chars
    // (YYYY-MM-DD prefix of an ISO string) if parsing fails — avoids
    // an exception on partial or non-standard values.
    try {
      final dt = DateTime.parse(iso).toLocal();
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
      return '${months[dt.month - 1]} ${dt.day}, ${dt.year}';
    } catch (_) {
      return iso.length >= 10 ? iso.substring(0, 10) : iso;
    }
  }
}

class MemoryCard extends StatelessWidget {
  final ChatMessage msg;
  const MemoryCard({super.key, required this.msg});

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final items = (p['items'] is List)
        ? (p['items'] as List).whereType<Map>().toList()
        : const <Map>[];
    final title = (p['title'] as String?) ?? 'Memory';
    final subtitle = p['subtitle'] as String?;

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CardHeader(
            icon: Icons.auto_awesome_outlined,
            iconColor: VaultColors.accentBright,
            title: title,
            subtitle: subtitle,
          ),
          if (msg.text.trim().isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Text(msg.text, style: VaultText.body),
          ],
          if (items.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            ...List.generate(items.length, (i) {
              final m = items[i].cast<String, dynamic>();
              return Padding(
                padding: EdgeInsets.only(
                  bottom: i == items.length - 1 ? 0 : VaultSpacing.sm,
                ),
                child: _MemoryItemRow(item: m),
              );
            }),
          ],
        ],
      ),
    );
  }
}

class _MemoryItemRow extends StatelessWidget {
  final Map<String, dynamic> item;
  const _MemoryItemRow({required this.item});

  @override
  Widget build(BuildContext context) {
    final type = (item['memory_type'] as String?) ?? '';
    final key = (item['memory_key'] as String?) ?? '';
    final preview = (item['value_preview'] as String?) ?? '';
    final eventDate = (item['event_date'] as String?) ?? '';
    final lang = (item['language'] as String?) ?? '';

    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  key.isNotEmpty ? key : '(no key)',
                  style: VaultText.subtitle.copyWith(fontSize: 15),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (type.isNotEmpty) MetaPill(label: type),
            ],
          ),
          if (preview.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(preview, style: VaultText.caption, maxLines: 2),
          ],
          if (eventDate.isNotEmpty || lang.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.sm),
            Wrap(
              spacing: VaultSpacing.xs + 2,
              runSpacing: VaultSpacing.xs,
              children: [
                if (eventDate.isNotEmpty)
                  MetaPill(label: eventDate, icon: Icons.event_outlined),
                if (lang.isNotEmpty)
                  MetaPill(label: lang.toUpperCase(), icon: Icons.language),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class RelationshipCard extends StatelessWidget {
  final ChatMessage msg;
  const RelationshipCard({super.key, required this.msg});

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final relType = (p['relation_type'] as String?) ?? '';
    final anchor = (p['anchor_label'] as String?) ?? '';
    final nodes = (p['nodes'] is List)
        ? (p['nodes'] as List).whereType<Map>().toList()
        : const <Map>[];
    final count = p['count'] is int ? p['count'] as int : nodes.length;

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CardHeader(
            icon: Icons.hub_outlined,
            iconColor: VaultColors.severityInfo,
            title: anchor.isNotEmpty ? anchor : 'Related items',
            subtitle: _humanRelType(relType),
            trailing: count > 0
                ? MetaPill(label: '$count', icon: Icons.density_medium)
                : null,
          ),
          if (msg.text.trim().isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Text(msg.text, style: VaultText.body),
          ],
          if (nodes.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Wrap(
              spacing: VaultSpacing.sm,
              runSpacing: VaultSpacing.sm,
              children: nodes
                  .map(
                      (n) => _RelationshipNode(node: n.cast<String, dynamic>()))
                  .toList(),
            ),
          ],
        ],
      ),
    );
  }

  String _humanRelType(String t) {
    if (t.isEmpty) return '';
    switch (t) {
      case 'travel_related':
        return 'Travel cluster';
      case 'identity_related':
        return 'Identity cluster';
      case 'business_related':
        return 'Business cluster';
      case 'finance_related':
        return 'Finance cluster';
      case 'tax_related':
        return 'Tax cluster';
      case 'medical_related':
        return 'Medical cluster';
      case 'family_related':
        return 'Family cluster';
      case 'security_related':
        return 'Security cluster';
      case 'media_related':
        return 'Media cluster';
      case 'inheritance_related':
        return 'Inheritance cluster';
      default:
        return t.replaceAll('_', ' ');
    }
  }
}

class _RelationshipNode extends StatelessWidget {
  final Map<String, dynamic> node;
  const _RelationshipNode({required this.node});

  @override
  Widget build(BuildContext context) {
    final label = (node['label'] as String?) ?? '';
    final iconHint = (node['icon'] as String?) ?? '';
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: VaultSpacing.md,
        vertical: VaultSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(_iconForHint(iconHint),
              size: 14, color: VaultColors.accentBright),
          const SizedBox(width: VaultSpacing.sm),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 220),
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: VaultText.bodySm,
            ),
          ),
        ],
      ),
    );
  }

  IconData _iconForHint(String hint) {
    switch (hint) {
      case 'passport':
        return Icons.book_outlined;
      case 'visa':
        return Icons.flight_takeoff;
      case 'id_card':
        return Icons.badge_outlined;
      case 'driver_license':
        return Icons.directions_car_outlined;
      case 'invoice':
        return Icons.receipt_long_outlined;
      case 'receipt':
        return Icons.receipt_outlined;
      case 'contract':
        return Icons.handshake_outlined;
      case 'agreement':
        return Icons.description_outlined;
      case 'medical':
        return Icons.medical_information_outlined;
      case 'tax':
        return Icons.account_balance_outlined;
      case 'business':
        return Icons.business_center_outlined;
      case 'insurance':
        return Icons.shield_outlined;
      case 'memory':
        return Icons.auto_awesome_outlined;
      case 'travel':
        return Icons.flight;
      case 'family':
        return Icons.people_outline;
      default:
        return Icons.circle_outlined;
    }
  }
}

class ConciergeCard extends StatelessWidget {
  final ChatMessage msg;
  final void Function(String action, Map<String, dynamic>? data)? onAction;

  const ConciergeCard({super.key, required this.msg, this.onAction});

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final severity = (p['severity'] as String?) ?? 'info';
    final title = (p['title'] as String?) ?? 'Concierge';
    final reason = (p['reason'] as String?) ?? '';
    final iconHint = (p['icon'] as String?) ?? '';
    final actions = (p['actions'] is List)
        ? (p['actions'] as List).whereType<Map>().toList()
        : const <Map>[];

    final accentColor = VaultColors.forSeverity(severity);

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      accentSide: BorderSide(color: accentColor, width: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              IconBadge(
                icon: _iconForHint(iconHint),
                color: accentColor,
                size: 40,
              ),
              const SizedBox(width: VaultSpacing.md),
              Expanded(
                child: Text(title, style: VaultText.subtitle),
              ),
              SeverityChip(level: severity, label: _severityLabel(severity)),
            ],
          ),
          if (reason.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Text(reason, style: VaultText.body),
          ],
          if (msg.text.trim().isNotEmpty && msg.text.trim() != reason) ...[
            const SizedBox(height: VaultSpacing.sm),
            Text(msg.text, style: VaultText.bodySm),
          ],
          if (actions.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.lg),
            Wrap(
              spacing: VaultSpacing.sm,
              runSpacing: VaultSpacing.sm,
              children: actions.map((a) {
                final m = a.cast<String, dynamic>();
                final label = (m['label'] as String?) ?? 'Open';
                final action = (m['action'] as String?) ?? '';
                final data = m['data'] is Map
                    ? (m['data'] as Map).cast<String, dynamic>()
                    : null;
                return FilledButton(
                  onPressed: () => onAction?.call(action, data),
                  style: FilledButton.styleFrom(
                    backgroundColor: accentColor,
                  ),
                  child: Text(label),
                );
              }).toList(),
            ),
          ],
        ],
      ),
    );
  }

  IconData _iconForHint(String hint) {
    switch (hint) {
      case 'travel':
        return Icons.flight_takeoff;
      case 'tax':
        return Icons.account_balance_outlined;
      case 'inheritance':
        return Icons.family_restroom_outlined;
      case 'security':
        return Icons.shield_outlined;
      case 'identity':
        return Icons.badge_outlined;
      case 'finance':
        return Icons.payments_outlined;
      case 'medical':
        return Icons.medical_services_outlined;
      default:
        return Icons.lightbulb_outline;
    }
  }

  String _severityLabel(String s) {
    switch (s.toLowerCase()) {
      case 'critical':
        return 'CRITICAL';
      case 'warning':
        return 'WARNING';
      case 'info':
        return 'INFO';
      case 'ok':
        return 'OK';
      default:
        return s.toUpperCase();
    }
  }
}

class ExpiryCard extends StatelessWidget {
  final ChatMessage msg;
  final void Function(String action, Map<String, dynamic>? data)? onAction;

  const ExpiryCard({super.key, required this.msg, this.onAction});

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final items = (p['items'] is List)
        ? (p['items'] as List).whereType<Map>().toList()
        : const <Map>[];
    final summary = p['summary'] as String?;

    final worst = _worstSeverity(items);
    final accentColor = VaultColors.forSeverity(worst);

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      accentSide: BorderSide(color: accentColor, width: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CardHeader(
            icon: Icons.event_busy_outlined,
            iconColor: accentColor,
            title: 'Expiry status',
            subtitle: summary ?? '${items.length} item(s) tracked',
          ),
          if (msg.text.trim().isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Text(msg.text, style: VaultText.body),
          ],
          if (items.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            ...List.generate(items.length, (i) {
              final m = items[i].cast<String, dynamic>();
              return Padding(
                padding: EdgeInsets.only(
                  bottom: i == items.length - 1 ? 0 : VaultSpacing.sm,
                ),
                child: _ExpiryRow(item: m),
              );
            }),
          ],
        ],
      ),
    );
  }

  String _worstSeverity(List<Map> items) {
    const order = ['critical', 'warning', 'info', 'ok'];
    String worst = 'info';
    int worstIdx = order.indexOf(worst);
    for (final it in items) {
      final s = ((it['severity'] as String?) ?? 'info').toLowerCase();
      final idx = order.indexOf(s);
      if (idx >= 0 && idx < worstIdx) {
        worst = s;
        worstIdx = idx;
      }
    }
    return worst;
  }
}

class _ExpiryRow extends StatelessWidget {
  final Map<String, dynamic> item;
  const _ExpiryRow({required this.item});

  @override
  Widget build(BuildContext context) {
    final docLabel = (item['doc_label'] as String?) ?? '';
    final phrase = (item['phrase'] as String?) ?? '';
    final date = (item['expiry_date'] as String?) ?? '';
    final daysUntil =
        item['days_until'] is int ? item['days_until'] as int : null;
    final severity = ((item['severity'] as String?) ?? 'info').toLowerCase();
    final type = (item['expiry_type'] as String?) ?? '';

    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          IconBadge(
            icon: _iconForType(type),
            color: VaultColors.forSeverity(severity),
            size: 36,
            radius: VaultRadius.sm,
          ),
          const SizedBox(width: VaultSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  docLabel.isNotEmpty
                      ? docLabel
                      : (type.isNotEmpty ? type : 'Document'),
                  style: VaultText.subtitle.copyWith(fontSize: 15),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (phrase.isNotEmpty || date.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    phrase.isNotEmpty ? phrase : date,
                    style: VaultText.caption,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: VaultSpacing.sm),
          SeverityChip(
            level: severity,
            label: daysUntil != null
                ? _daysLabel(daysUntil)
                : severity.toUpperCase(),
          ),
        ],
      ),
    );
  }

  IconData _iconForType(String t) {
    switch (t) {
      case 'passport':
        return Icons.book_outlined;
      case 'visa':
        return Icons.flight_takeoff;
      case 'id_card':
        return Icons.badge_outlined;
      case 'driver_license':
        return Icons.directions_car_outlined;
      case 'insurance':
        return Icons.shield_outlined;
      case 'tax':
        return Icons.account_balance_outlined;
      case 'contract':
        return Icons.handshake_outlined;
      case 'subscription':
        return Icons.autorenew;
      case 'inheritance':
        return Icons.family_restroom_outlined;
      default:
        return Icons.event_outlined;
    }
  }

  String _daysLabel(int days) {
    if (days < 0) return '${-days}d ago';
    if (days == 0) return 'Today';
    if (days == 1) return '1 day';
    return '${days}d';
  }
}

const Map<String, IconData> _kTypeBucketIcons = <String, IconData>{
  'PDFs': Icons.picture_as_pdf_outlined,
  'Images': Icons.image_outlined,
  'Videos': Icons.movie_outlined,
  'Audio': Icons.audiotrack,
  'Documents': Icons.description_outlined,
  'Spreadsheets': Icons.table_chart_outlined,
  'Archives': Icons.folder_zip_outlined,
  'Scripts': Icons.code,
};

const Map<String, IconData> _kTravelDocIcons = <String, IconData>{
  'passport': Icons.book_outlined,
  'visa': Icons.flight_takeoff,
  'boarding_pass': Icons.airplane_ticket_outlined,
  'ticket': Icons.confirmation_number_outlined,
  'hotel_itinerary': Icons.hotel_outlined,
};

String _prettyTravelDocType(String code) {
  switch (code) {
    case 'passport':
      return 'Passport';
    case 'visa':
      return 'Visa';
    case 'boarding_pass':
      return 'Boarding pass';
    case 'ticket':
      return 'Ticket';
    case 'hotel_itinerary':
      return 'Hotel itinerary';
    default:
      return code
          .split('_')
          .map((p) => p.isEmpty ? p : p[0].toUpperCase() + p.substring(1))
          .join(' ');
  }
}

class VaultInventoryCard extends StatefulWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;
  final void Function(ChatMessage fileMsg)? onDownload;
  final Set<String> viewInFlight;
  final Set<String> downloadInFlight;

  final Future<Map<String, dynamic>?> Function(String fileId)? onLoadRelated;

  final void Function(String fileId)? onShowRelated;

  static const int maxRecentRows = 10;

  static const int maxFolderRows = 8;

  static const double maxRecentListHeight = 240;

  const VaultInventoryCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onDownload,
    this.viewInFlight = const <String>{},
    this.downloadInFlight = const <String>{},
    this.onLoadRelated,
    this.onShowRelated,
  });

  @override
  State<VaultInventoryCard> createState() => _VaultInventoryCardState();
}

class _VaultInventoryCardState extends State<VaultInventoryCard> {
  String? _expandedFileId;

  @override
  Widget build(BuildContext context) {
    final msg = widget.msg;
    final onOpen = widget.onOpen;
    final onLoadRelated = widget.onLoadRelated;
    final p = msg.payload ?? const <String, dynamic>{};
    final totalFiles = p['total_files'] is int ? p['total_files'] as int : 0;
    final totalBytes = p['total_bytes'] is int ? p['total_bytes'] as int : 0;
    final folderCount = p['folder_count'] is int ? p['folder_count'] as int : 0;

    final folders = (p['top_folders'] is List)
        ? (p['top_folders'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final typeCounts = (p['type_counts'] is Map)
        ? (p['type_counts'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final recent = (p['recent_files'] is List)
        ? (p['recent_files'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    final isEmpty = totalFiles == 0 && folders.isEmpty && recent.isEmpty;

    if (isEmpty) {
      return VaultCard(
        padding: const EdgeInsets.all(VaultSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            CardHeader(
              icon: Icons.dashboard_customize_outlined,
              iconColor: VaultColors.accent,
              title: 'Vault overview',
              subtitle: 'Empty vault',
            ),
            const SizedBox(height: VaultSpacing.md),
            Text(
              msg.text.trim().isNotEmpty
                  ? msg.text
                  : "I don't see any uploaded files in your vault yet.",
              style: VaultText.body,
            ),
          ],
        ),
      );
    }

    final shownFolders = folders.length > VaultInventoryCard.maxFolderRows
        ? folders.take(VaultInventoryCard.maxFolderRows).toList()
        : folders;
    final shownRecent = recent.length > VaultInventoryCard.maxRecentRows
        ? recent.take(VaultInventoryCard.maxRecentRows).toList()
        : recent;

    final headline = _buildHeadline(
      totalFiles: totalFiles,
      folderCount: folderCount,
      totalBytes: totalBytes,
    );

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.dashboard_customize_outlined,
            iconColor: VaultColors.accent,
            title: 'Vault overview',
            subtitle: headline,
            trailing: totalFiles > 0
                ? MetaPill(
                    label: '$totalFiles file${totalFiles == 1 ? '' : 's'}',
                    icon: Icons.inventory_2_outlined,
                  )
                : null,
          ),
          if (typeCounts.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            _TypeBreakdownRow(typeCounts: typeCounts),
          ],
          if (shownFolders.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.lg),
            Text(
              AppLocalizations.of(context).chatCardTopFolders,
              style: VaultText.subtitle.copyWith(fontSize: 14),
            ),
            const SizedBox(height: VaultSpacing.sm),
            for (final f in shownFolders)
              Padding(
                padding: const EdgeInsets.only(bottom: VaultSpacing.xs + 2),
                child: _FolderSummaryRow(folder: f),
              ),
          ],
          if (shownRecent.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.lg),
            Text(
              AppLocalizations.of(context).chatCardRecentFiles,
              style: VaultText.subtitle.copyWith(fontSize: 14),
            ),
            const SizedBox(height: VaultSpacing.sm),
            ConstrainedBox(
              constraints: const BoxConstraints(
                maxHeight: VaultInventoryCard.maxRecentListHeight,
              ),
              child: Scrollbar(
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: shownRecent.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: VaultSpacing.xs + 2),
                  itemBuilder: (context, i) {
                    final raw = shownRecent[i];
                    final fid = (raw['file_id'] as String?) ?? '';
                    final canExpand = onLoadRelated != null && fid.isNotEmpty;
                    final isExpanded = canExpand && _expandedFileId == fid;
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _VaultFileListRow(
                          file: raw,
                          onOpen: () => onOpen?.call(
                            VaultFileListCard._toFileMessage(raw, msg),
                          ),
                          onDownload: widget.onDownload == null
                              ? null
                              : () => widget.onDownload!.call(
                                    VaultFileListCard._toFileMessage(raw, msg),
                                  ),
                          isViewInFlight: widget.viewInFlight.contains(fid),
                          isDownloadInFlight:
                              widget.downloadInFlight.contains(fid),
                          onShowRelated: canExpand
                              ? () => setState(() {
                                    _expandedFileId = isExpanded ? null : fid;
                                  })
                              : null,
                        ),
                        if (isExpanded)
                          _InlineRelatedSection(
                            fileId: fid,
                            parentMsg: msg,
                            onLoadRelated: onLoadRelated,
                            onOpen: onOpen,
                            onShowFullGraph: widget.onShowRelated,
                            onCollapse: () => setState(
                              () => _expandedFileId = null,
                            ),
                          ),
                      ],
                    );
                  },
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  String _buildHeadline({
    required int totalFiles,
    required int folderCount,
    required int totalBytes,
  }) {
    final folderPart = folderCount > 0
        ? ' across $folderCount folder${folderCount == 1 ? '' : 's'}'
        : '';
    final sizePart = totalBytes > 0 ? ' · ${_formatBytes(totalBytes)}' : '';
    return 'Your vault has $totalFiles file'
        '${totalFiles == 1 ? '' : 's'}$folderPart$sizePart.';
  }
}

class _TypeBreakdownRow extends StatelessWidget {
  final Map<String, dynamic> typeCounts;
  const _TypeBreakdownRow({required this.typeCounts});

  static const List<String> _kDisplayOrder = [
    'PDFs',
    'Images',
    'Videos',
    'Audio',
    'Documents',
    'Spreadsheets',
    'Archives',
    'Scripts',
  ];

  @override
  Widget build(BuildContext context) {
    final pills = <Widget>[];
    for (final label in _kDisplayOrder) {
      final v = typeCounts[label];
      final count = v is int ? v : (v is num ? v.toInt() : 0);
      if (count <= 0) continue;
      pills.add(MetaPill(
        label: '$count $label',
        icon: _kTypeBucketIcons[label] ?? Icons.insert_drive_file_outlined,
      ));
    }
    if (pills.isEmpty) return const SizedBox.shrink();
    return Wrap(
      spacing: VaultSpacing.xs + 2,
      runSpacing: VaultSpacing.xs,
      children: pills,
    );
  }
}

class _FolderSummaryRow extends StatelessWidget {
  final Map<String, dynamic> folder;
  const _FolderSummaryRow({required this.folder});

  @override
  Widget build(BuildContext context) {
    final name = (folder['name'] as String?) ?? 'Folder';
    final fileCount =
        folder['file_count'] is int ? folder['file_count'] as int : 0;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: VaultSpacing.md,
        vertical: VaultSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.folder_outlined,
            size: 18,
            color: VaultColors.accentBright,
          ),
          const SizedBox(width: VaultSpacing.sm),
          Expanded(
            child: Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: VaultText.body.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
          const SizedBox(width: VaultSpacing.sm),
          Text(
            '$fileCount file${fileCount == 1 ? '' : 's'}',
            style: VaultText.caption,
          ),
        ],
      ),
    );
  }
}

class TravelReadinessCard extends StatelessWidget {
  final ChatMessage msg;
  const TravelReadinessCard({super.key, required this.msg});

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final confidence = (p['confidence'] as String?)?.toLowerCase() ?? 'blocked';
    final found = (p['found'] is List)
        ? (p['found'] as List).whereType<String>().toList()
        : const <String>[];
    final missing = (p['missing'] is List)
        ? (p['missing'] as List).whereType<String>().toList()
        : const <String>[];
    final expired = (p['expired'] is List)
        ? (p['expired'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final expiringSoon = (p['expiring_soon'] is List)
        ? (p['expiring_soon'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    final hasAnyTravelData =
        found.isNotEmpty || expired.isNotEmpty || expiringSoon.isNotEmpty;

    if (!hasAnyTravelData && missing.isEmpty) {
      return VaultCard(
        padding: const EdgeInsets.all(VaultSpacing.lg),
        accentSide: const BorderSide(
          color: VaultColors.severityWarn,
          width: 3,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            CardHeader(
              icon: Icons.luggage_outlined,
              iconColor: VaultColors.severityWarn,
              title: 'Travel readiness',
              subtitle: 'No travel documents found',
            ),
            const SizedBox(height: VaultSpacing.md),
            Text(
              msg.text.trim().isNotEmpty
                  ? msg.text
                  : "Upload a passport, visa, or boarding pass to start a "
                      "travel readiness check.",
              style: VaultText.body,
            ),
          ],
        ),
      );
    }

    final severityLevel = _severityForConfidence(confidence);
    final accentColor = VaultColors.forSeverity(severityLevel);

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      accentSide: BorderSide(color: accentColor, width: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.luggage_outlined,
            iconColor: accentColor,
            title: 'Travel readiness',
            subtitle: _statusSubtitle(confidence),
            trailing: SeverityChip(
              level: severityLevel,
              label: _statusLabel(confidence),
            ),
          ),
          if (found.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            _ReadinessSection(
              title: 'Found',
              icon: Icons.check_circle_outline,
              accent: VaultColors.severityOk,
              items: [
                for (final dt in found)
                  _ReadinessLine(
                    icon: _kTravelDocIcons[dt] ?? Icons.description_outlined,
                    label: _prettyTravelDocType(dt),
                  ),
              ],
            ),
          ],
          if (expired.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            _ReadinessSection(
              title: 'Expired',
              icon: Icons.error_outline,
              accent: VaultColors.severityCrit,
              items: [
                for (final e in expired)
                  _ReadinessLine(
                    icon: _kTravelDocIcons[(e['doc_type'] as String?) ?? ''] ??
                        Icons.description_outlined,
                    label: _expiredLabel(e),
                  ),
              ],
            ),
          ],
          if (expiringSoon.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            _ReadinessSection(
              title: 'Expiring soon',
              icon: Icons.schedule,
              accent: VaultColors.severityWarn,
              items: [
                for (final e in expiringSoon)
                  _ReadinessLine(
                    icon: _kTravelDocIcons[(e['doc_type'] as String?) ?? ''] ??
                        Icons.description_outlined,
                    label: _expiringSoonLabel(e),
                  ),
              ],
            ),
          ],
          if (missing.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            _ReadinessSection(
              title: 'Missing',
              icon: Icons.help_outline,
              accent: VaultColors.severityWarn,
              items: [
                for (final dt in missing)
                  _ReadinessLine(
                    icon: _kTravelDocIcons[dt] ?? Icons.description_outlined,
                    label: _prettyTravelDocType(dt),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  String _severityForConfidence(String c) {
    switch (c) {
      case 'ready':
        return 'ok';
      case 'partial':
        return 'warning';
      case 'blocked':
        return 'critical';
      default:
        return 'info';
    }
  }

  String _statusLabel(String c) {
    switch (c) {
      case 'ready':
        return 'READY';
      case 'partial':
        return 'PARTIAL';
      case 'blocked':
        return 'BLOCKED';
      default:
        return c.toUpperCase();
    }
  }

  String _statusSubtitle(String c) {
    switch (c) {
      case 'ready':
        return "You're travel-ready.";
      case 'partial':
        return 'Some items are missing or expiring.';
      case 'blocked':
        return 'Blockers found.';
      default:
        return '';
    }
  }

  String _expiredLabel(Map<String, dynamic> e) {
    final docType = (e['doc_type'] as String?) ?? '';
    final label = (e['label'] as String?) ?? '';
    final days = e['days_overdue'];
    final base = label.isNotEmpty
        ? '${_prettyTravelDocType(docType)} ($label)'
        : _prettyTravelDocType(docType);
    if (days is int) return '$base — expired ${days}d ago';
    return '$base — expired';
  }

  String _expiringSoonLabel(Map<String, dynamic> e) {
    final docType = (e['doc_type'] as String?) ?? '';
    final label = (e['label'] as String?) ?? '';
    final days = e['days_until'];
    final base = label.isNotEmpty
        ? '${_prettyTravelDocType(docType)} ($label)'
        : _prettyTravelDocType(docType);
    if (days is int) return '$base — ${days}d';
    return base;
  }
}

class _ReadinessSection extends StatelessWidget {
  final String title;
  final IconData icon;
  final Color accent;
  final List<_ReadinessLine> items;

  const _ReadinessSection({
    required this.title,
    required this.icon,
    required this.accent,
    required this.items,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: accent.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: accent),
              const SizedBox(width: VaultSpacing.sm),
              Text(
                title,
                style: VaultText.subtitle.copyWith(
                  fontSize: 14,
                  color: accent,
                ),
              ),
            ],
          ),
          const SizedBox(height: VaultSpacing.sm),
          for (int i = 0; i < items.length; i++)
            Padding(
              padding: EdgeInsets.only(
                bottom: i == items.length - 1 ? 0 : 4,
              ),
              child: Row(
                children: [
                  Icon(items[i].icon,
                      size: 14, color: VaultColors.textSecondary),
                  const SizedBox(width: VaultSpacing.sm),
                  Expanded(
                    child: Text(
                      items[i].label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: VaultText.body,
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

class _ReadinessLine {
  final IconData icon;
  final String label;
  const _ReadinessLine({required this.icon, required this.label});
}

class CredentialFileSearchCard extends StatefulWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;

  final Future<Map<String, dynamic>?> Function(String fileId)? onLoadRelated;

  final void Function(String fileId)? onShowRelated;

  final void Function()? onScanRemaining;

  final bool Function({
    required String intent,
    required String normalizedQuery,
  })? isDeepScanActive;

  static const int maxRows = 25;
  static const double maxListHeight = 360;

  const CredentialFileSearchCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onLoadRelated,
    this.onShowRelated,
    this.onScanRemaining,
    this.isDeepScanActive,
  });

  @override
  State<CredentialFileSearchCard> createState() =>
      _CredentialFileSearchCardState();
}

class _CredentialFileSearchCardState extends State<CredentialFileSearchCard> {
  String? _expandedFileId;

  bool _scanRequested = false;

  static const String _kIntent = 'search_files_for_credentials';
  static const String _kNormalizedQuery = '';

  bool _hostKnowsScanActive() {
    final predicate = widget.isDeepScanActive;
    if (predicate == null) return false;
    return predicate(
      intent: _kIntent,
      normalizedQuery: _kNormalizedQuery,
    );
  }

  @override
  Widget build(BuildContext context) {
    final msg = widget.msg;
    final onOpen = widget.onOpen;
    final onLoadRelated = widget.onLoadRelated;
    final p = msg.payload ?? const <String, dynamic>{};

    final allFiles = (p['files'] is List)
        ? (p['files'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    final verifiedFiles = allFiles.where((f) {
      final tier = (f['tier'] as String?)?.toLowerCase();
      if (tier != null && tier != 'confirmed' && tier.isNotEmpty) {
        return false;
      }
      final conf = (f['confidence'] as String?)?.toLowerCase();
      if (conf != null && conf != 'strong' && conf.isNotEmpty) {
        return false;
      }
      return true;
    }).toList();

    final actions = (p['actions'] is List)
        ? (p['actions'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final notScanned =
        p['not_scanned_count'] is int ? p['not_scanned_count'] as int : 0;
    final scannedCount =
        p['scanned_count'] is int ? p['scanned_count'] as int : 0;

    final isPartial = p['is_partial'] == true || notScanned > 0;

    final isStale = p['stale'] == true;
    final hostScanIsActive = _hostKnowsScanActive();
    if (isStale && hostScanIsActive) {
      if (isDeepScanDebugUiEnabled()) {
        return _OlderResultsPlaceholder();
      }
      return const SizedBox.shrink();
    }
    final scanAction = actions.firstWhere(
      (a) => a['type'] == 'scan_remaining',
      orElse: () => const <String, dynamic>{},
    );

    Widget wrapStale(Widget child) {
      if (!isStale) return child;
      return Opacity(
        opacity: 0.55,
        child: Stack(
          children: [
            child,
            Positioned.fill(
              child: IgnorePointer(
                child: Container(
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(VaultRadius.lg),
                    border: Border.all(
                      color: VaultColors.severityWarn.withValues(alpha: 0.45),
                      width: 1,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      );
    }

    Widget staleBanner() {
      if (!isStale) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.only(bottom: VaultSpacing.md),
        child: _HonestyHint(
          icon: Icons.history_outlined,
          text: 'Older results — a fresh scan is running. These rows '
              'reflect a previous check; the new answer will replace '
              'them once the scan finishes.',
        ),
      );
    }

    if (verifiedFiles.isEmpty) {
      final emptyHeadline = scannedCount > 0
          ? "I didn't find any files with saved credentials."
          : "I didn't find any uploaded files with saved credential "
              'records. Saved logins live separately — ask "show my '
              'saved logins" to see those.';
      return wrapStale(VaultCard(
        padding: const EdgeInsets.all(VaultSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (isDeepScanDebugUiEnabled()) staleBanner(),
            CardHeader(
              icon: Icons.search_off_outlined,
              iconColor: VaultColors.textSecondary,
              title: 'No credential files found',
              subtitle: 'Saved logins live separately',
            ),
            const SizedBox(height: VaultSpacing.md),
            Text(
              msg.text.trim().isNotEmpty ? msg.text : emptyHeadline,
              style: VaultText.body,
            ),
            if (isDeepScanDebugUiEnabled() && notScanned > 0) ...[
              const SizedBox(height: VaultSpacing.md),
              _NotScannedFooter(count: notScanned),
              if (scanAction.isNotEmpty) ...[
                const SizedBox(height: VaultSpacing.sm),
                _ScanRemainingButton(
                  fileCount: notScanned,
                  scanRequested: _scanRequested,
                  hostKnowsActive: _hostKnowsScanActive(),
                  onTap: () {
                    if (_scanRequested) return;
                    if (_hostKnowsScanActive()) return;
                    setState(() => _scanRequested = true);
                    widget.onScanRemaining?.call();
                  },
                ),
              ],
            ],
          ],
        ),
      ));
    }

    final n = verifiedFiles.length;
    final headline = n == 1
        ? 'I found 1 file with saved credentials.'
        : 'I found $n files with saved credentials.';
    final subtitle = n == 1 ? '1 file' : '$n files';

    return wrapStale(VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (isDeepScanDebugUiEnabled()) staleBanner(),
          CardHeader(
            icon: Icons.verified_outlined,
            iconColor: VaultColors.severityOk,
            title: headline,
            subtitle: subtitle,
          ),
          const SizedBox(height: VaultSpacing.md),
          ConstrainedBox(
            constraints: const BoxConstraints(
              maxHeight: CredentialFileSearchCard.maxListHeight,
            ),
            child: Scrollbar(
              child: SingleChildScrollView(
                child: _renderRows(
                  verifiedFiles,
                  msg: msg,
                  onOpen: onOpen,
                  onLoadRelated: onLoadRelated,
                ),
              ),
            ),
          ),
          if (isDeepScanDebugUiEnabled() && notScanned > 0) ...[
            const SizedBox(height: VaultSpacing.md),
            _NotScannedFooter(count: notScanned),
            if (scanAction.isNotEmpty) ...[
              const SizedBox(height: VaultSpacing.sm),
              _ScanRemainingButton(
                fileCount: notScanned,
                scanRequested: _scanRequested,
                hostKnowsActive: _hostKnowsScanActive(),
                onTap: () {
                  if (_scanRequested) return;
                  if (_hostKnowsScanActive()) return;
                  setState(() => _scanRequested = true);
                  widget.onScanRemaining?.call();
                },
              ),
            ],
          ],
        ],
      ),
    ));
  }

  Widget _renderRows(
    List<Map<String, dynamic>> rows, {
    required ChatMessage msg,
    required void Function(ChatMessage)? onOpen,
    required Future<Map<String, dynamic>?> Function(String)? onLoadRelated,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (int i = 0; i < rows.length; i++) ...[
          if (i > 0) const SizedBox(height: VaultSpacing.sm),
          Builder(builder: (context) {
            final raw = rows[i];
            final fid = (raw['file_id'] as String?) ?? '';
            final canExpand = onLoadRelated != null && fid.isNotEmpty;
            final isExpanded = canExpand && _expandedFileId == fid;
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                _CredentialFileRow(
                  file: raw,
                  onOpen: () => onOpen?.call(
                    VaultFileListCard._toFileMessage(raw, msg),
                  ),
                  onShowRelated: canExpand
                      ? () => setState(() {
                            _expandedFileId = isExpanded ? null : fid;
                          })
                      : null,
                ),
                if (isExpanded)
                  _InlineRelatedSection(
                    fileId: fid,
                    parentMsg: msg,
                    onLoadRelated: onLoadRelated,
                    onOpen: onOpen,
                    onShowFullGraph: widget.onShowRelated,
                    onCollapse: () => setState(
                      () => _expandedFileId = null,
                    ),
                  ),
              ],
            );
          }),
        ],
      ],
    );
  }
}

class _HonestyHint extends StatelessWidget {
  final IconData icon;
  final String text;
  const _HonestyHint({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.sm + 2),
      decoration: BoxDecoration(
        color: VaultColors.severityWarnSoft,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(
          color: VaultColors.severityWarn.withValues(alpha: 0.30),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 14, color: VaultColors.severityWarn),
          const SizedBox(width: VaultSpacing.sm),
          Expanded(child: Text(text, style: VaultText.caption)),
        ],
      ),
    );
  }
}

class _OlderResultsPlaceholder extends StatelessWidget {
  const _OlderResultsPlaceholder();

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: 0.7,
      child: Container(
        padding: const EdgeInsets.all(VaultSpacing.md),
        decoration: BoxDecoration(
          color: VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.md),
          border: Border.all(
            color: VaultColors.textTertiary.withValues(alpha: 0.30),
          ),
        ),
        child: Row(
          children: const [
            Icon(
              Icons.history_outlined,
              size: 14,
              color: VaultColors.textTertiary,
            ),
            SizedBox(width: VaultSpacing.sm),
            Expanded(
              child: Text(
                'Older results hidden — a fresh scan is running. '
                "I'll replace them with the new answer when the "
                'scan finishes.',
                style: VaultText.caption,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ScanRemainingButton extends StatelessWidget {
  final int fileCount;
  final bool scanRequested;
  final bool hostKnowsActive;
  final VoidCallback onTap;
  const _ScanRemainingButton({
    required this.fileCount,
    required this.scanRequested,
    required this.onTap,
    this.hostKnowsActive = false,
  });

  @override
  Widget build(BuildContext context) {
    final disabled = scanRequested || hostKnowsActive;
    final String label;
    if (hostKnowsActive) {
      label = 'Scanning…';
    } else if (scanRequested) {
      label = 'Scan started — analysis running in background';
    } else {
      label = 'Scan remaining files ($fileCount)';
    }
    return SizedBox(
      width: double.infinity,
      child: OutlinedButton.icon(
        onPressed: disabled ? null : onTap,
        icon: Icon(
          disabled ? Icons.hourglass_top_outlined : Icons.play_circle_outline,
          size: 16,
        ),
        label: Text(label),
      ),
    );
  }
}

class _NotScannedFooter extends StatelessWidget {
  final int count;
  const _NotScannedFooter({required this.count});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.severityWarnSoft,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(
          color: VaultColors.severityWarn.withValues(alpha: 0.30),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.info_outline,
            size: 14,
            color: VaultColors.severityWarn,
          ),
          const SizedBox(width: VaultSpacing.sm),
          Expanded(
            child: Text(
              count == 1
                  ? 'Some files could not be scanned because text '
                      'extraction is not available yet (1 file).'
                  : 'Some files could not be scanned because text '
                      'extraction is not available yet ($count files).',
              style: VaultText.caption,
            ),
          ),
        ],
      ),
    );
  }
}

class _CredentialFileRow extends StatelessWidget {
  final Map<String, dynamic> file;
  final VoidCallback? onOpen;

  final VoidCallback? onShowRelated;

  const _CredentialFileRow({
    required this.file,
    this.onOpen,
    this.onShowRelated,
  });

  @override
  Widget build(BuildContext context) {
    final fileName = (file['file_name'] as String?) ?? 'file';
    final savedName = (file['saved_name'] as String?)?.trim();
    final relativePath = (file['relative_path'] as String?)?.trim();
    final mime = (file['mime_type'] as String?) ?? '';
    final passwordPresent = file['password_present'] == true;
    final safeServiceNames = (file['safe_service_names'] is List)
        ? (file['safe_service_names'] as List)
            .whereType<String>()
            .where((s) => s.trim().isNotEmpty)
            .take(3)
            .toList()
        : const <String>[];

    final recordCount =
        (file['record_count'] is int) ? file['record_count'] as int : 0;
    final evidenceLabel =
        ((file['evidence_source_label'] as String?) ?? '').trim();
    final duplicatePaths = (file['duplicate_paths'] is List)
        ? (file['duplicate_paths'] as List)
            .whereType<String>()
            .where((s) => s.trim().isNotEmpty)
            .toList()
        : const <String>[];

    final title =
        (savedName != null && savedName.isNotEmpty) ? savedName : fileName;

    return InkWell(
      onTap: onOpen,
      borderRadius: BorderRadius.circular(VaultRadius.md),
      child: Container(
        padding: const EdgeInsets.all(VaultSpacing.md),
        decoration: BoxDecoration(
          color: VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.md),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            IconBadge(
              icon: _iconForMime(mime),
              color: VaultColors.severityInfo,
              size: 36,
              radius: VaultRadius.sm,
            ),
            const SizedBox(width: VaultSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: VaultText.subtitle.copyWith(fontSize: 15),
                  ),
                  if (relativePath != null && relativePath.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        const Icon(
                          Icons.folder_outlined,
                          size: 12,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            relativePath,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption,
                          ),
                        ),
                      ],
                    ),
                  ],
                  const SizedBox(height: VaultSpacing.xs + 2),
                  Wrap(
                    spacing: VaultSpacing.xs + 2,
                    runSpacing: VaultSpacing.xs,
                    children: [
                      if (recordCount > 0)
                        MetaPill(
                          label: recordCount == 1
                              ? '1 record'
                              : '$recordCount records',
                          icon: Icons.fact_check_outlined,
                          tint: VaultColors.severityOk,
                        ),
                      if (evidenceLabel.isNotEmpty)
                        MetaPill(
                          label: 'evidence: $evidenceLabel',
                          icon: Icons.find_in_page_outlined,
                          tint: VaultColors.severityInfo,
                        ),
                      if (passwordPresent)
                        const MetaPill(
                          label: 'password present',
                          icon: Icons.key_outlined,
                          tint: VaultColors.severityOk,
                        ),
                      if (duplicatePaths.isNotEmpty)
                        MetaPill(
                          label: duplicatePaths.length == 1
                              ? 'same file found in 2 folders'
                              : 'same file found in ${duplicatePaths.length + 1} folders',
                          icon: Icons.file_copy_outlined,
                          tint: VaultColors.severityInfo,
                        ),
                      for (final s in safeServiceNames)
                        MetaPill(
                          label: s,
                          icon: Icons.business_outlined,
                          tint: VaultColors.accentBright,
                        ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: VaultSpacing.sm),
            IconButton(
              tooltip: AppLocalizations.of(context).commonOpen,
              onPressed: onOpen,
              icon: const Icon(
                Icons.open_in_new,
                size: 18,
                color: VaultColors.accentBright,
              ),
            ),
            if (onShowRelated != null)
              IconButton(
                tooltip: AppLocalizations.of(context).chatCardShowRelated,
                onPressed: onShowRelated,
                visualDensity: VisualDensity.compact,
                icon: const Icon(
                  Icons.account_tree_outlined,
                  size: 18,
                  color: VaultColors.accentBright,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class CredentialExtractionReviewCard extends StatefulWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;
  final FutureOr<void> Function(
    String action,
    Map<String, dynamic>? data,
  )? onAction;

  static const int maxRows = 200;
  static const double maxListHeight = 520;

  const CredentialExtractionReviewCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onAction,
  });

  @override
  State<CredentialExtractionReviewCard> createState() =>
      _CredentialExtractionReviewCardState();
}

class _CredentialExtractionReviewCardState
    extends State<CredentialExtractionReviewCard> {
  final Set<String> _selected = <String>{};
  final Set<String> _handled = <String>{};
  final Set<String> _ignored = <String>{};
  final Set<String> _busy = <String>{};
  final Set<String> _revealed = <String>{};

  List<Map<String, dynamic>> get _records {
    final p = widget.msg.payload ?? const <String, dynamic>{};
    return (p['records'] is List)
        ? (p['records'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .take(CredentialExtractionReviewCard.maxRows)
            .toList(growable: false)
        : const <Map<String, dynamic>>[];
  }

  String _candidateId(Map<String, dynamic> record, int index) =>
      (record['candidate_id']?.toString().trim().isNotEmpty ?? false)
          ? record['candidate_id'].toString().trim()
          : 'candidate-${index + 1}';

  @override
  void initState() {
    super.initState();
    for (var i = 0; i < _records.length; i++) {
      _selected.add(_candidateId(_records[i], i));
    }
  }

  Future<void> _submit(
    String action,
    List<String> ids, {
    Map<String, dynamic>? overrides,
  }) async {
    final callback = widget.onAction;
    if (callback == null || ids.any((id) => id.startsWith('candidate-'))) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('This review action is unavailable.')),
      );
      return;
    }
    setState(() => _busy.addAll(ids));
    try {
      await callback(action, <String, dynamic>{
        'candidate_ids': ids,
        if (overrides != null && overrides.isNotEmpty)
          'overrides': overrides,
      });
      if (!mounted) return;
      setState(() {
        _busy.removeAll(ids);
        _handled.addAll(ids);
        _selected.removeAll(ids);
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _busy.removeAll(ids));
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Could not complete that credential review action.'),
        ),
      );
    }
  }

  Future<void> _editAndSave(
    Map<String, dynamic> record,
    String candidateId,
  ) async {
    final fields = (record['fields'] is Map)
        ? (record['fields'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final service = TextEditingController(
      text: record['service']?.toString() ?? '',
    );
    final username = TextEditingController(
      text: fields['username']?.toString() ??
          record['username']?.toString() ??
          '',
    );
    final email = TextEditingController(
      text: fields['email']?.toString() ?? record['email']?.toString() ?? '',
    );
    final userId = TextEditingController(
      text: fields['user_id']?.toString() ?? '',
    );
    final loginId = TextEditingController(
      text: fields['login_id']?.toString() ?? '',
    );
    final accountId = TextEditingController(
      text: fields['account_id']?.toString() ?? '',
    );
    final website = TextEditingController(
      text: fields['url']?.toString() ?? record['website']?.toString() ?? '',
    );
    final replacementPassword = TextEditingController();
    final pin = TextEditingController(text: fields['pin']?.toString() ?? '');
    final accountNumber = TextEditingController(
      text: fields['account_number']?.toString() ?? '',
    );
    final secureIdentifier = TextEditingController(
      text: fields['secure_identifier']?.toString() ?? '',
    );
    final accessCode = TextEditingController(
      text: fields['access_code']?.toString() ?? '',
    );
    final secureValue = TextEditingController(
      text: fields['secure_value']?.toString() ?? '',
    );
    final notes = TextEditingController(
      text: fields['note']?.toString() ?? '',
    );
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Edit credential before saving'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                key: const Key('credential_extraction_edit_service'),
                controller: service,
                decoration: const InputDecoration(labelText: 'Service'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_username'),
                controller: username,
                decoration: const InputDecoration(labelText: 'Username'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_email'),
                controller: email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Email'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_user_id'),
                controller: userId,
                decoration: const InputDecoration(labelText: 'User ID'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_login_id'),
                controller: loginId,
                decoration: const InputDecoration(labelText: 'Login ID'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_account_id'),
                controller: accountId,
                decoration: const InputDecoration(labelText: 'Account ID'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_website'),
                controller: website,
                decoration: const InputDecoration(labelText: 'Website'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_password'),
                controller: replacementPassword,
                obscureText: true,
                enableSuggestions: false,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'Replacement password (optional)',
                  helperText: 'Leave blank to keep the extracted password.',
                ),
              ),
              TextField(
                key: const Key('credential_extraction_edit_pin'),
                controller: pin,
                obscureText: true,
                enableSuggestions: false,
                autocorrect: false,
                decoration: const InputDecoration(labelText: 'PIN'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_account_number'),
                controller: accountNumber,
                decoration: const InputDecoration(labelText: 'Account number'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_secure_identifier'),
                controller: secureIdentifier,
                decoration:
                    const InputDecoration(labelText: 'Secure identifier'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_access_code'),
                controller: accessCode,
                obscureText: true,
                enableSuggestions: false,
                autocorrect: false,
                decoration: const InputDecoration(labelText: 'Access code'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_secure_value'),
                controller: secureValue,
                decoration: const InputDecoration(labelText: 'Secure value'),
              ),
              TextField(
                key: const Key('credential_extraction_edit_notes'),
                controller: notes,
                maxLines: 2,
                decoration: const InputDecoration(labelText: 'Notes'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('credential_extraction_edit_save'),
            onPressed: () {
              final cleanService = service.text.trim();
              if (cleanService.isEmpty) return;
              Navigator.of(dialogContext).pop(<String, dynamic>{
                'service': cleanService,
                'username': username.text.trim(),
                'email': email.text.trim(),
                'user_id': userId.text.trim(),
                'login_id': loginId.text.trim(),
                'account_id': accountId.text.trim(),
                'website': website.text.trim(),
                'notes': notes.text.trim(),
                'pin': pin.text,
                'account_number': accountNumber.text,
                'secure_identifier': secureIdentifier.text,
                'access_code': accessCode.text,
                'secure_value': secureValue.text,
                if (replacementPassword.text.isNotEmpty)
                  'password': replacementPassword.text,
              });
            },
            child: const Text('Save changes'),
          ),
        ],
      ),
    );
    await Future<void>.delayed(const Duration(milliseconds: 250));
    service.dispose();
    username.dispose();
    email.dispose();
    userId.dispose();
    loginId.dispose();
    accountId.dispose();
    website.dispose();
    replacementPassword.dispose();
    pin.dispose();
    accountNumber.dispose();
    secureIdentifier.dispose();
    accessCode.dispose();
    secureValue.dispose();
    notes.dispose();
    if (result == null || !mounted) return;
    await _submit(
      'credential_extraction_edit_and_save',
      <String>[candidateId],
      overrides: <String, dynamic>{candidateId: result},
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.msg.payload ?? const <String, dynamic>{};
    final records = _records;
    final analysisCounts = (p['analysis_counts'] is Map)
        ? (p['analysis_counts'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final fileMap = (p['file'] is Map)
        ? (p['file'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final textAvailable = p['text_available'] == true;
    final fileLabel = (fileMap['saved_name'] is String &&
            (fileMap['saved_name'] as String).trim().isNotEmpty)
        ? (fileMap['saved_name'] as String).trim()
        : ((fileMap['file_name'] as String?)?.trim() ?? 'the selected file');

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.fact_check_outlined,
            iconColor: VaultColors.accent,
            title: 'Review extracted secure records',
            subtitle: fileLabel,
            trailing: const MetaPill(
              label: 'review only',
              icon: Icons.lock_outline,
            ),
          ),
          const SizedBox(height: VaultSpacing.md),
          if (widget.msg.text.trim().isNotEmpty)
            Text(widget.msg.text, style: VaultText.body),
          const SizedBox(height: VaultSpacing.md),
          _HonestyHint(
            icon: Icons.shield_outlined,
            text: 'Nothing is saved until you confirm. Sensitive values are '
                'hidden by default; use the eye control to reveal the exact '
                'value extracted from the document.',
          ),
          if (analysisCounts.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.sm),
            Text(
              'Pages: ${analysisCounts['text_extraction_page_count'] ?? 0}/'
              '${analysisCounts['pdf_page_count'] ?? 0}  •  '
              'Candidates: ${analysisCounts['normalized_record_count'] ?? records.length}',
              key: const Key('credential_extraction_analysis_counts'),
              style: VaultText.caption,
            ),
          ],
          if (!textAvailable) ...[
            const SizedBox(height: VaultSpacing.md),
            _HonestyHint(
              icon: Icons.info_outline,
              text: "I don't have the file's text yet. Run vault "
                  'analysis to extract it, then ask again.',
            ),
          ],
          if (records.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            ConstrainedBox(
              constraints: const BoxConstraints(
                maxHeight: CredentialExtractionReviewCard.maxListHeight,
              ),
              child: Scrollbar(
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: records.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: VaultSpacing.sm),
                  itemBuilder: (context, i) {
                    final record = records[i];
                    final candidateId = _candidateId(record, i);
                    return _ExtractionReviewRow(
                      record: record,
                      selected: _selected.contains(candidateId),
                      handled: _handled.contains(candidateId),
                      ignored: _ignored.contains(candidateId),
                      busy: _busy.contains(candidateId),
                      revealed: _revealed.contains(candidateId),
                      onSelected: (value) => setState(() {
                        if (value) {
                          _selected.add(candidateId);
                        } else {
                          _selected.remove(candidateId);
                        }
                      }),
                      onSave: () => _submit(
                        'credential_extraction_save',
                        <String>[candidateId],
                      ),
                      onEdit: () => _editAndSave(record, candidateId),
                      onIgnore: () => setState(() {
                        _ignored.add(candidateId);
                        _selected.remove(candidateId);
                      }),
                      onReveal: () => setState(() {
                        if (_revealed.contains(candidateId)) {
                          _revealed.remove(candidateId);
                        } else {
                          _revealed.add(candidateId);
                        }
                      }),
                    );
                  },
                ),
              ),
            ),
            const SizedBox(height: VaultSpacing.md),
            Wrap(
              spacing: VaultSpacing.sm,
              runSpacing: VaultSpacing.sm,
              children: [
                FilledButton.icon(
                  key: const Key('credential_extraction_save_selected'),
                  onPressed: _selected.isEmpty || _busy.isNotEmpty
                      ? null
                      : () => _submit(
                            'credential_extraction_save_selected',
                            _selected.toList(growable: false),
                          ),
                  icon: const Icon(Icons.save_outlined),
                  label: Text('Save selected (${_selected.length})'),
                ),
                OutlinedButton.icon(
                  key: const Key('credential_extraction_ignore_all'),
                  onPressed: _busy.isNotEmpty
                      ? null
                      : () async {
                          final callback = widget.onAction;
                          if (callback != null) {
                            await callback(
                              'credential_extraction_cancel',
                              const <String, dynamic>{},
                            );
                          }
                          if (!mounted) return;
                          setState(() {
                            for (var i = 0; i < records.length; i++) {
                              _ignored.add(_candidateId(records[i], i));
                            }
                            _selected.clear();
                          });
                        },
                  icon: const Icon(Icons.cancel_outlined),
                  label: const Text('Ignore all'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _ExtractionReviewRow extends StatelessWidget {
  final Map<String, dynamic> record;
  final bool selected;
  final bool handled;
  final bool ignored;
  final bool busy;
  final bool revealed;
  final ValueChanged<bool> onSelected;
  final VoidCallback onSave;
  final VoidCallback onEdit;
  final VoidCallback onIgnore;
  final VoidCallback onReveal;

  const _ExtractionReviewRow({
    required this.record,
    required this.selected,
    required this.handled,
    required this.ignored,
    required this.busy,
    required this.revealed,
    required this.onSelected,
    required this.onSave,
    required this.onEdit,
    required this.onIgnore,
    required this.onReveal,
  });

  @override
  Widget build(BuildContext context) {
    final service = (record['service'] as String?)?.trim();
    final fields = (record['fields'] is Map)
        ? (record['fields'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final recordType =
        (record['record_type'] as String?)?.trim().toUpperCase() ??
            'SECURE RECORD';
    final passwordPresent = record['password_present'] == true;
    final pinPresent = record['pin_present'] == true;
    final notePresent = record['note_present'] == true;
    final website =
        (fields['url'] ?? record['website'])?.toString().trim();
    final sourceContext = (record['source_context'] as String?)?.trim();
    const fieldLabels = <String, String>{
      'username': 'Username',
      'email': 'Email',
      'user_id': 'User ID',
      'login_id': 'Login ID',
      'account_id': 'Account ID',
      'url': 'Website or URL',
      'password': 'Password',
      'pin': 'PIN',
      'account_number': 'Account number',
      'secure_identifier': 'Secure identifier',
      'access_code': 'Access code',
      'secure_value': 'Secure value',
      'value': 'Secure value',
      'notes': 'Note',
      'note': 'Note',
    };
    const publicFieldNames = <String>{
      'username',
      'email',
      'user_id',
      'login_id',
      'account_id',
    };
    String labelFor(String name) => fieldLabels[name] ?? name
        .split('_')
        .where((part) => part.isNotEmpty)
        .map((part) => '${part[0].toUpperCase()}${part.substring(1)}')
        .join(' ');
    final identifierFields = <MapEntry<String, String>>[
      for (final entry in fields.entries)
        if (publicFieldNames.contains(entry.key) &&
            (entry.value?.toString() ?? '').isNotEmpty)
          MapEntry(labelFor(entry.key), entry.value.toString()),
    ];
    final sensitiveFields = <MapEntry<String, String>>[
      for (final entry in fields.entries)
        if (!publicFieldNames.contains(entry.key) &&
            entry.key != 'url' &&
            (entry.value?.toString() ?? '').isNotEmpty)
          MapEntry(labelFor(entry.key), entry.value.toString()),
    ];

    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Checkbox(
                key: ValueKey(
                  'credential_extraction_select_${record['candidate_id']}',
                ),
                value: selected,
                onChanged: handled || ignored || busy
                    ? null
                    : (value) => onSelected(value ?? false),
              ),
              const Icon(
                Icons.business_outlined,
                size: 14,
                color: VaultColors.accentBright,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  service?.isNotEmpty == true ? service! : 'unnamed service',
                  style: VaultText.subtitle.copyWith(fontSize: 14),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          MetaPill(
            label: recordType.replaceAll('_', ' ').toLowerCase(),
            icon: Icons.security_outlined,
            tint: VaultColors.severityInfo,
          ),
          if (identifierFields.isNotEmpty) ...[
            const SizedBox(height: 4),
            for (final entry in identifierFields)
              Text(
                '${entry.key}: ${entry.value}',
                style: VaultText.caption,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
          ],
          if (website != null && website.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text('Website: $website', style: VaultText.caption),
          ],
          if (sourceContext != null && sourceContext.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              'Source: $sourceContext',
              style: VaultText.caption.copyWith(
                color: VaultColors.textTertiary,
              ),
            ),
          ],
          if (sensitiveFields.isNotEmpty) ...[
            const SizedBox(height: 4),
            if (revealed)
              ...sensitiveFields.map(
                (entry) => SelectableText(
                  '${entry.key}: ${entry.value}',
                  key: ValueKey(
                    'credential_extraction_revealed_${record['candidate_id']}_${entry.key}',
                  ),
                  style: VaultText.body,
                ),
              )
            else
              ...sensitiveFields.map(
                (entry) => Text(
                  '${entry.key}: ••••••••••',
                  key: entry.key == 'Password'
                      ? const Key('credential_extraction_masked_password')
                      : null,
                ),
              ),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                key: ValueKey(
                  'credential_extraction_reveal_${record['candidate_id']}',
                ),
                onPressed: busy ? null : onReveal,
                icon: Icon(
                  revealed ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                ),
                label: Text(
                  revealed ? 'Hide extracted values' : 'Show extracted values',
                ),
              ),
            ),
          ],
          const SizedBox(height: VaultSpacing.xs + 2),
          Wrap(
            spacing: VaultSpacing.xs + 2,
            runSpacing: VaultSpacing.xs,
            children: [
              MetaPill(
                label: passwordPresent ? 'password present' : 'no password',
                icon: passwordPresent
                    ? Icons.key_outlined
                    : Icons.key_off_outlined,
                tint: passwordPresent
                    ? VaultColors.severityOk
                    : VaultColors.textTertiary,
              ),
              if (pinPresent)
                const MetaPill(
                  label: 'PIN present',
                  icon: Icons.pin_outlined,
                  tint: VaultColors.severityInfo,
                ),
              if (notePresent)
                const MetaPill(
                  label: 'note present',
                  icon: Icons.sticky_note_2_outlined,
                  tint: VaultColors.severityInfo,
                ),
            ],
          ),
          const SizedBox(height: VaultSpacing.sm),
          if (handled)
            const MetaPill(
              label: 'handled',
              icon: Icons.check_circle_outline,
              tint: VaultColors.severityOk,
            )
          else if (ignored)
            const MetaPill(
              label: 'ignored',
              icon: Icons.remove_circle_outline,
              tint: VaultColors.textTertiary,
            )
          else
            Wrap(
              spacing: VaultSpacing.xs,
              children: [
                TextButton.icon(
                  key: ValueKey(
                    'credential_extraction_save_${record['candidate_id']}',
                  ),
                  onPressed: busy ? null : onSave,
                  icon: busy
                      ? const SizedBox.square(
                          dimension: 14,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.save_outlined),
                  label: const Text('Save'),
                ),
                TextButton.icon(
                  key: ValueKey(
                    'credential_extraction_edit_${record['candidate_id']}',
                  ),
                  onPressed: busy ? null : onEdit,
                  icon: const Icon(Icons.edit_outlined),
                  label: const Text('Edit'),
                ),
                TextButton.icon(
                  key: ValueKey(
                    'credential_extraction_ignore_${record['candidate_id']}',
                  ),
                  onPressed: busy ? null : onIgnore,
                  icon: const Icon(Icons.remove_circle_outline),
                  label: const Text('Ignore'),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

class DeepAnswerProgressCard extends StatefulWidget {
  final ChatMessage msg;

  final Future<Map<String, dynamic>?> Function(String jobId)? onPoll;

  final void Function(Map<String, dynamic> snapshot)? onReady;

  final Duration pollInterval;

  const DeepAnswerProgressCard({
    super.key,
    required this.msg,
    this.onPoll,
    this.onReady,
    this.pollInterval = const Duration(milliseconds: 1500),
  });

  @override
  State<DeepAnswerProgressCard> createState() => _DeepAnswerProgressCardState();
}

class _DeepAnswerProgressCardState extends State<DeepAnswerProgressCard> {
  Map<String, dynamic>? _snapshot;
  Timer? _timer;
  bool _terminal = false;

  int _lastScanned = 0;
  int _stalledTicks = 0;
  static const int _stalledThreshold = 3;

  @override
  void initState() {
    super.initState();
    _snapshot = widget.msg.payload != null
        ? Map<String, dynamic>.from(widget.msg.payload!)
        : <String, dynamic>{};
    _lastScanned = _readScanned(_snapshot);
    final status = (_snapshot?['status'] as String?) ?? 'scanning';
    if (status == 'ready' || status == 'failed') {
      _terminal = true;
      if (status == 'ready') {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          widget.onReady?.call(_snapshot ?? const <String, dynamic>{});
        });
      }
    } else {
      _scheduleNextPoll();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _scheduleNextPoll() {
    _timer?.cancel();
    if (_terminal) return;
    _timer = Timer(widget.pollInterval, _runPoll);
  }

  int _readScanned(Map<String, dynamic>? snap) {
    final progress = (snap?['progress'] is Map)
        ? (snap!['progress'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final coverage = (progress['coverage'] is Map)
        ? (progress['coverage'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    return (coverage['scanned'] is int) ? coverage['scanned'] as int : 0;
  }

  Future<void> _runPoll() async {
    if (!mounted || _terminal) return;
    final jobId = _snapshot?['job_id'] as String?;
    final onPoll = widget.onPoll;
    if (jobId == null || jobId.isEmpty || onPoll == null) {
      _terminal = true;
      return;
    }
    Map<String, dynamic>? fresh;
    try {
      fresh = await onPoll(jobId);
    } catch (_) {
      _scheduleNextPoll();
      return;
    }
    if (!mounted) return;
    if (fresh == null) {
      _terminal = true;
      return;
    }
    final freshScanned = _readScanned(fresh);
    if (freshScanned > _lastScanned) {
      _lastScanned = freshScanned;
      _stalledTicks = 0;
    } else {
      _stalledTicks++;
    }
    setState(() => _snapshot = fresh);
    final newStatus = (fresh['status'] as String?) ?? 'scanning';
    if (newStatus == 'ready' || newStatus == 'failed') {
      _terminal = true;
      if (newStatus == 'ready') {
        widget.onReady?.call(fresh);
      }
      return;
    }
    _scheduleNextPoll();
  }

  @override
  Widget build(BuildContext context) {
    final snap = _snapshot ?? const <String, dynamic>{};
    final status = (snap['status'] as String?) ?? 'scanning';
    final progress = (snap['progress'] is Map)
        ? (snap['progress'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final coverage = (progress['coverage'] is Map)
        ? (progress['coverage'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final stageLabel = (progress['stage_label'] as String?) ?? '';
    final total = (coverage['total'] is int) ? coverage['total'] as int : 0;
    final scanned =
        (coverage['scanned'] is int) ? coverage['scanned'] as int : 0;
    final pending =
        (coverage['pending'] is int) ? coverage['pending'] as int : 0;
    final processing =
        (coverage['processing'] is int) ? coverage['processing'] as int : 0;
    final unsupported =
        (coverage['unsupported'] is int) ? coverage['unsupported'] as int : 0;
    final failed = (coverage['failed'] is int) ? coverage['failed'] as int : 0;
    final fractionDenom = total > 0 ? total : 1;
    final fraction = (scanned / fractionDenom).clamp(0.0, 1.0).toDouble();
    final remaining = pending + processing;

    final isFailedRaw = status == 'failed';
    final isReadyRaw = status == 'ready';

    final isLyingAboutCompletion = isReadyRaw && total > 0 && scanned == 0;
    final isReady = isReadyRaw && !isLyingAboutCompletion;
    final isFailed = isFailedRaw || isLyingAboutCompletion;

    final backendBlockerReason =
        (progress['blocker_reason'] as String?)?.trim() ?? '';
    final stalled = !isReady &&
        !isFailed &&
        (backendBlockerReason.isNotEmpty || _stalledTicks >= _stalledThreshold);

    if (!isDeepScanDebugUiEnabled()) {
      if (isReady) {
        return const SizedBox.shrink();
      }
      if (isFailed || stalled) {
        return _SimpleAssistantBubble(
          text: "I couldn't finish checking the vault because file "
              'analysis is not moving. Try running vault analysis '
              'or check the backend workers.',
        );
      }
      final headline = widget.msg.text.trim().isNotEmpty
          ? widget.msg.text
          : 'Let me check your vault properly. '
              "I'll read the files before giving the result.";
      return _SimpleAssistantBubble(
        text: headline,
        showTypingPulse: true,
      );
    }

    final isPreparing = !isReady && !isFailed && scanned == 0 && remaining > 0;
    final subtitle = isFailed
        ? "Scan didn't finish"
        : isReady
            ? 'Scan complete'
            : isPreparing
                ? 'Preparing scan…'
                : total > 0
                    ? '$scanned of $total files read'
                    : 'Getting ready…';

    final headlineMessage = widget.msg.text.trim().isNotEmpty
        ? widget.msg.text
        : (isReady
            ? 'Preparing your results.'
            : isFailed
                ? "I couldn't finish the scan."
                : isPreparing
                    ? "I'm preparing to scan your vault. "
                        'This takes a moment for the first read.'
                    : "I'm reading through your vault so I can answer "
                        'accurately.');

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: isFailed
                ? Icons.error_outline
                : isReady
                    ? Icons.check_circle_outline
                    : Icons.travel_explore_outlined,
            iconColor: isFailed
                ? VaultColors.severityWarn
                : isReady
                    ? VaultColors.severityOk
                    : VaultColors.accent,
            title: 'Scanning your vault',
            subtitle: subtitle,
          ),
          const SizedBox(height: VaultSpacing.md),
          Text(headlineMessage, style: VaultText.body),
          const SizedBox(height: VaultSpacing.md),
          if (!isReady && !isFailed && total > 0) ...[
            LinearProgressIndicator(
              value: isPreparing ? null : fraction,
              minHeight: 6,
              backgroundColor: VaultColors.surfaceMuted,
              valueColor: const AlwaysStoppedAnimation<Color>(
                VaultColors.accentBright,
              ),
            ),
            const SizedBox(height: VaultSpacing.sm),
          ],
          Wrap(
            spacing: VaultSpacing.xs + 2,
            runSpacing: VaultSpacing.xs,
            children: [
              MetaPill(
                label: isPreparing
                    ? 'Preparing…'
                    : total > 0
                        ? '$scanned of $total checked'
                        : 'Counting files…',
                icon: Icons.fact_check_outlined,
                tint: VaultColors.severityOk,
              ),
              if (remaining > 0 && !isPreparing)
                MetaPill(
                  label: '$remaining to go',
                  icon: Icons.hourglass_bottom_outlined,
                  tint: VaultColors.severityInfo,
                ),
              if (unsupported > 0)
                MetaPill(
                  label: '$unsupported can’t be read',
                  icon: Icons.block_outlined,
                  tint: VaultColors.textTertiary,
                ),
              if (failed > 0)
                MetaPill(
                  label: '$failed had errors',
                  icon: Icons.error_outline,
                  tint: VaultColors.severityWarn,
                ),
              if (stageLabel.isNotEmpty && !isReady && !isFailed)
                MetaPill(
                  label: stageLabel,
                  icon: Icons.auto_awesome_outlined,
                  tint: VaultColors.accentBright,
                ),
            ],
          ),
          if (stalled) ...[
            const SizedBox(height: VaultSpacing.md),
            _HonestyHint(
              icon: Icons.info_outline,
              text: scanned == 0
                  ? "I'm preparing the scan. No files have been "
                      'processed yet.'
                  : "I'm still preparing the scan. Some files may "
                      'need text extraction or OCR before I can check '
                      'them.',
            ),
          ],
          if (isFailed) ...[
            const SizedBox(height: VaultSpacing.md),
            _HonestyHint(
              icon: Icons.error_outline,
              text: "I couldn't finish reading your vault. Try the "
                  'question again, or run vault analysis from settings.',
            ),
          ],
        ],
      ),
    );
  }
}

class _SimpleAssistantBubble extends StatelessWidget {
  final String text;
  final bool showTypingPulse;

  const _SimpleAssistantBubble({
    required this.text,
    this.showTypingPulse = false,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.all(VaultSpacing.md),
          decoration: BoxDecoration(
            color: VaultColors.bubbleAssistant,
            borderRadius: BorderRadius.circular(VaultRadius.lg),
            border: Border.all(color: VaultColors.borderSubtle),
          ),
          child: Text(text, style: VaultText.body),
        ),
        if (showTypingPulse) ...[
          const SizedBox(height: VaultSpacing.xs),
          const _ScanTypingDots(),
        ],
      ],
    );
  }
}

class _ScanTypingDots extends StatefulWidget {
  const _ScanTypingDots();

  @override
  State<_ScanTypingDots> createState() => _ScanTypingDotsState();
}

class _ScanTypingDotsState extends State<_ScanTypingDots>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (context, _) {
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: VaultSpacing.sm),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (int i = 0; i < 3; i++) ...[
                if (i > 0) const SizedBox(width: 4),
                Opacity(
                  opacity: 0.30 + 0.70 * _dotPhase(_ctrl.value, i / 3.0),
                  child: Container(
                    width: 5,
                    height: 5,
                    decoration: const BoxDecoration(
                      color: VaultColors.textTertiary,
                      shape: BoxShape.circle,
                    ),
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  double _dotPhase(double t, double offset) {
    final phase = (t - offset) % 1.0;
    final norm = phase < 0 ? phase + 1.0 : phase;

    if (norm < 0.25) return norm / 0.25;
    if (norm < 0.5) return 1.0 - (norm - 0.25) / 0.25;
    return 0.0;
  }
}

class RelatedFilesCard extends StatelessWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;

  static const int maxRows = 12;
  static const double maxListHeight = 360;

  const RelatedFilesCard({super.key, required this.msg, this.onOpen});

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final anchor = (p['anchor'] is Map)
        ? (p['anchor'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final results = (p['results'] is List)
        ? (p['results'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    final anchorLabel =
        (anchor['saved_name'] as String?)?.trim().isNotEmpty == true
            ? (anchor['saved_name'] as String).trim()
            : ((anchor['file_name'] as String?)?.trim() ?? 'this file');

    if (results.isEmpty) {
      return VaultCard(
        padding: const EdgeInsets.all(VaultSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            CardHeader(
              icon: Icons.hub_outlined,
              iconColor: VaultColors.textSecondary,
              title: 'No clearly related files',
              subtitle: 'Anchor: $anchorLabel',
            ),
            const SizedBox(height: VaultSpacing.md),
            Text(
              msg.text.trim().isNotEmpty
                  ? msg.text
                  : "I couldn't find any clearly related files for "
                      "$anchorLabel.",
              style: VaultText.body,
            ),
          ],
        ),
      );
    }

    final shown =
        results.length > maxRows ? results.take(maxRows).toList() : results;
    final allWeak = shown.every((r) =>
        ((r['confidence'] as String?) ?? 'weak').toLowerCase() == 'weak');

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.hub_outlined,
            iconColor: VaultColors.accent,
            title: 'Related to $anchorLabel',
            subtitle:
                '${results.length} match${results.length == 1 ? '' : 'es'}'
                '${allWeak ? ' · weak only' : ''}',
          ),
          if (allWeak) ...[
            const SizedBox(height: VaultSpacing.md),
            Container(
              padding: const EdgeInsets.all(VaultSpacing.md),
              decoration: BoxDecoration(
                color: VaultColors.severityWarnSoft,
                borderRadius: BorderRadius.circular(VaultRadius.md),
                border: Border.all(
                  color: VaultColors.severityWarn.withValues(alpha: 0.35),
                ),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: const [
                  Icon(
                    Icons.warning_amber_outlined,
                    size: 16,
                    color: VaultColors.severityWarn,
                  ),
                  SizedBox(width: VaultSpacing.sm),
                  Expanded(
                    child: Text(
                      "I'm not sure they're actually related — treat these "
                      "as weak matches.",
                      style: VaultText.bodySm,
                    ),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: VaultSpacing.md),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: maxListHeight),
            child: Scrollbar(
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: shown.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: VaultSpacing.sm),
                itemBuilder: (context, i) {
                  final raw = shown[i];
                  return _RelatedFileRow(
                    file: raw,
                    onOpen: () => onOpen?.call(
                      VaultFileListCard._toFileMessage(raw, msg),
                    ),
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _RelatedFileRow extends StatelessWidget {
  final Map<String, dynamic> file;
  final VoidCallback? onOpen;

  const _RelatedFileRow({required this.file, this.onOpen});

  @override
  Widget build(BuildContext context) {
    final fileName = (file['file_name'] as String?) ?? 'file';
    final savedName = (file['saved_name'] as String?)?.trim();
    final relativePath = (file['relative_path'] as String?)?.trim();
    final confidence =
        ((file['confidence'] as String?) ?? 'weak').toLowerCase();
    final reasons = (file['reasons'] is List)
        ? (file['reasons'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    final title =
        (savedName != null && savedName.isNotEmpty) ? savedName : fileName;

    final mime = (file['mime_type'] as String?) ?? '';
    final reasonsLine = reasons
        .map((r) => (r['label'] as String?) ?? '')
        .where((s) => s.isNotEmpty)
        .join(' · ');

    return InkWell(
      onTap: onOpen,
      borderRadius: BorderRadius.circular(VaultRadius.md),
      child: Container(
        padding: const EdgeInsets.all(VaultSpacing.md),
        decoration: BoxDecoration(
          color: VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.md),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            IconBadge(
              icon: _iconForMime(mime),
              color: VaultColors.accent,
              size: 36,
              radius: VaultRadius.sm,
            ),
            const SizedBox(width: VaultSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: VaultText.subtitle.copyWith(fontSize: 15),
                        ),
                      ),
                      const SizedBox(width: VaultSpacing.sm),
                      _ConfidenceBadge(confidence: confidence),
                    ],
                  ),
                  if (relativePath != null && relativePath.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        const Icon(
                          Icons.folder_outlined,
                          size: 12,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            relativePath,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption,
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (reasonsLine.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      reasonsLine,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: VaultText.caption,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ConfidenceBadge extends StatelessWidget {
  final String confidence;
  const _ConfidenceBadge({required this.confidence});

  @override
  Widget build(BuildContext context) {
    String level;
    String label;
    switch (confidence) {
      case 'strong':
        level = 'ok';
        label = 'STRONG';
        break;
      case 'medium':
        level = 'info';
        label = 'MEDIUM';
        break;
      case 'weak':
      default:
        level = 'warning';
        label = 'WEAK';
        break;
    }
    return SeverityChip(level: level, label: label);
  }
}

class FileDisambiguationCard extends StatelessWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;

  static const int maxRows = 50;

  static const double maxListHeight = 360;

  const FileDisambiguationCard({
    super.key,
    required this.msg,
    this.onOpen,
  });

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final title = (p['title'] as String?)?.trim();
    final files = (p['files'] is List)
        ? (p['files'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    if (files.isEmpty) {
      return VaultCard(
        padding: const EdgeInsets.all(VaultSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            CardHeader(
              icon: Icons.help_outline,
              iconColor: VaultColors.textSecondary,
              title: title?.isNotEmpty == true
                  ? title!
                  : 'Which file do you mean?',
              subtitle: 'No candidates available',
            ),
            if (msg.text.trim().isNotEmpty) ...[
              const SizedBox(height: VaultSpacing.md),
              Text(msg.text, style: VaultText.body),
            ],
          ],
        ),
      );
    }

    final shown = files.length > maxRows ? files.take(maxRows).toList() : files;

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.help_outline,
            iconColor: VaultColors.severityInfo,
            title:
                title?.isNotEmpty == true ? title! : 'Which file do you mean?',
            subtitle:
                '${files.length} candidate${files.length == 1 ? '' : 's'}',
          ),
          if (msg.text.trim().isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.sm),
            Text(
              _headlineOnly(msg.text),
              style: VaultText.body,
            ),
          ],
          const SizedBox(height: VaultSpacing.md),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: maxListHeight),
            child: Scrollbar(
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: shown.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: VaultSpacing.sm),
                itemBuilder: (context, i) {
                  final raw = shown[i];
                  return _FileDisambiguationRow(
                    file: raw,
                    index: i + 1,
                    onOpen: () => onOpen?.call(
                      VaultFileListCard._toFileMessage(raw, msg),
                    ),
                  );
                },
              ),
            ),
          ),
          const SizedBox(height: VaultSpacing.md),
          Row(
            children: const [
              Icon(
                Icons.touch_app_outlined,
                size: 14,
                color: VaultColors.textTertiary,
              ),
              SizedBox(width: VaultSpacing.xs + 2),
              Expanded(
                child: Text(
                  'Tap a row to open that file. Or type "the first one" / "#2".',
                  style: VaultText.caption,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static String _headlineOnly(String message) {
    final lines = message.trim().split('\n');
    final headlineLines = <String>[];
    for (final line in lines) {
      if (RegExp(r'^\s*\d+\.\s+').hasMatch(line)) break;
      headlineLines.add(line);
    }
    return headlineLines.join('\n').trim();
  }
}

class _FileDisambiguationRow extends StatelessWidget {
  final Map<String, dynamic> file;
  final int index;
  final VoidCallback? onOpen;

  const _FileDisambiguationRow({
    required this.file,
    required this.index,
    this.onOpen,
  });

  @override
  Widget build(BuildContext context) {
    final fileName = (file['file_name'] as String?) ?? 'file';
    final savedName = (file['saved_name'] as String?)?.trim();
    final relativePath = (file['relative_path'] as String?)?.trim();
    final mime = (file['mime_type'] as String?) ?? '';
    final confidence = ((file['confidence'] as String?) ?? '').toLowerCase();
    final reasons = (file['reasons'] is List)
        ? (file['reasons'] as List).whereType<String>().toList()
        : const <String>[];

    final isBestMatch = file['best_match'] == true;
    final isMostlyCredentials = file['mostly_credentials'] == true;

    final purposeLabel = (file['purpose_label'] as String?)?.trim();

    final title =
        (savedName != null && savedName.isNotEmpty) ? savedName : fileName;

    final bestMatchReason =
        (isBestMatch && purposeLabel != null && purposeLabel.isNotEmpty)
            ? 'Best match because most of the document appears to be '
                '$purposeLabel.'
            : null;
    final reasonsLine =
        reasons.map((r) => r.trim()).where((s) => s.isNotEmpty).join(' · ');

    final borderColor =
        isBestMatch ? VaultColors.accentBright : VaultColors.borderSubtle;
    final bgColor =
        isBestMatch ? VaultColors.accentSoft : VaultColors.surfaceMuted;

    return InkWell(
      onTap: onOpen,
      borderRadius: BorderRadius.circular(VaultRadius.md),
      child: Container(
        padding: const EdgeInsets.all(VaultSpacing.md),
        decoration: BoxDecoration(
          color: bgColor,
          borderRadius: BorderRadius.circular(VaultRadius.md),
          border: Border.all(color: borderColor),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 28,
              height: 28,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: VaultColors.accentSoft,
                borderRadius: BorderRadius.circular(VaultRadius.sm),
              ),
              child: Text(
                '$index',
                style: VaultText.subtitle.copyWith(
                  fontSize: 14,
                  color: VaultColors.accentBright,
                ),
              ),
            ),
            const SizedBox(width: VaultSpacing.md),
            IconBadge(
              icon: _iconForMime(mime),
              color: VaultColors.severityInfo,
              size: 36,
              radius: VaultRadius.sm,
            ),
            const SizedBox(width: VaultSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: VaultText.subtitle.copyWith(fontSize: 15),
                        ),
                      ),
                      if (isBestMatch) ...[
                        const SizedBox(width: VaultSpacing.sm),
                        const SeverityChip(level: 'ok', label: 'BEST MATCH'),
                      ],
                      if (confidence.isNotEmpty) ...[
                        const SizedBox(width: VaultSpacing.sm),
                        _ConfidenceBadge(confidence: confidence),
                      ],
                    ],
                  ),
                  if (bestMatchReason != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      bestMatchReason,
                      style: VaultText.caption.copyWith(
                        fontStyle: FontStyle.italic,
                        color: VaultColors.accentBright,
                      ),
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ] else if (isMostlyCredentials && !isBestMatch) ...[
                    const SizedBox(height: 4),
                    Text(
                      'Appears to be mostly a credential list',
                      style: VaultText.caption.copyWith(
                        fontStyle: FontStyle.italic,
                      ),
                    ),
                  ],
                  if (relativePath != null && relativePath.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        const Icon(
                          Icons.folder_outlined,
                          size: 12,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            relativePath,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption,
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (reasonsLine.isNotEmpty && bestMatchReason == null) ...[
                    const SizedBox(height: 4),
                    Text(
                      reasonsLine,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: VaultText.caption,
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: VaultSpacing.sm),
            IconButton(
              tooltip: AppLocalizations.of(context).commonOpen,
              onPressed: onOpen,
              icon: const Icon(
                Icons.open_in_new,
                size: 18,
                color: VaultColors.accentBright,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class FileSearchResultsCard extends StatefulWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;

  static const int maxRows = 100;

  static const double maxListHeight = 420;

  final Future<Map<String, dynamic>?> Function(String fileId)? onLoadRelated;

  final void Function(String fileId)? onShowRelated;

  const FileSearchResultsCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onLoadRelated,
    this.onShowRelated,
  });

  @override
  State<FileSearchResultsCard> createState() => _FileSearchResultsCardState();
}

class _FileSearchResultsCardState extends State<FileSearchResultsCard> {
  String? _expandedFileId;

  @override
  Widget build(BuildContext context) {
    final msg = widget.msg;
    final onOpen = widget.onOpen;
    final onLoadRelated = widget.onLoadRelated;
    final p = msg.payload ?? const <String, dynamic>{};
    final query = (p['query'] as String?)?.trim() ?? '';
    final pendingCount =
        (p['pending_count'] is int) ? p['pending_count'] as int : 0;
    final files = (p['results'] is List)
        ? (p['results'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    final queryKind = ((p['query_kind'] as String?) ?? '').toLowerCase().trim();
    final isStrictIdPhoto = queryKind == 'id_photo_visual';

    final title = isStrictIdPhoto
        ? 'ID photo results'
        : (query.isNotEmpty ? 'Search results for "$query"' : 'Search results');

    final isComplete =
        p['is_complete'] is bool ? p['is_complete'] as bool : true;
    String emptySubtitle;
    if (isComplete) {
      emptySubtitle = 'No matches found';
    } else {
      emptySubtitle = 'Search incomplete';
    }
    final nonEmptySubtitle = isComplete
        ? '${files.length} match${files.length == 1 ? '' : 'es'}'
        : 'Partial results · ${files.length} match'
            '${files.length == 1 ? '' : 'es'} so far';

    final requestedPersonName = (p['requested_person_name'] as String?)?.trim();
    final displayText = _sanitizeStaleEmptyStateText(
      original: msg.text,
      isComplete: isComplete,
      count: files.length,
      isStrictIdPhoto: isStrictIdPhoto,
      requestedPersonName: requestedPersonName,
    );

    if (files.isEmpty) {
      return VaultCard(
        padding: const EdgeInsets.all(VaultSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            CardHeader(
              icon: Icons.search_outlined,
              iconColor: VaultColors.textSecondary,
              title: title,
              subtitle: emptySubtitle,
            ),
            if (displayText.trim().isNotEmpty) ...[
              const SizedBox(height: VaultSpacing.md),
              Text(displayText, style: VaultText.body),
            ],
            if (pendingCount > 0) ...[
              const SizedBox(height: VaultSpacing.md),
              _PendingAnalysisStrip(pendingCount: pendingCount),
            ],
          ],
        ),
      );
    }

    final shown = files.length > FileSearchResultsCard.maxRows
        ? files.take(FileSearchResultsCard.maxRows).toList()
        : files;

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.search_outlined,
            iconColor: VaultColors.accentBright,
            title: title,
            subtitle: nonEmptySubtitle,
          ),
          if (pendingCount > 0) ...[
            const SizedBox(height: VaultSpacing.md),
            _PendingAnalysisStrip(pendingCount: pendingCount),
          ],
          const SizedBox(height: VaultSpacing.md),
          ConstrainedBox(
            constraints: const BoxConstraints(
              maxHeight: FileSearchResultsCard.maxListHeight,
            ),
            child: Scrollbar(
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: shown.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: VaultSpacing.sm),
                itemBuilder: (context, i) {
                  final raw = shown[i];
                  final fid = (raw['file_id'] as String?) ?? '';
                  final canExpand = onLoadRelated != null && fid.isNotEmpty;
                  final isExpanded = canExpand && _expandedFileId == fid;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _FileSearchResultRow(
                        file: raw,
                        onOpen: () => onOpen?.call(
                          VaultFileListCard._toFileMessage(raw, msg),
                        ),
                        onShowRelated: canExpand
                            ? () => setState(() {
                                  _expandedFileId = isExpanded ? null : fid;
                                })
                            : null,
                      ),
                      if (isExpanded)
                        _InlineRelatedSection(
                          fileId: fid,
                          parentMsg: msg,
                          onLoadRelated: onLoadRelated,
                          onOpen: onOpen,
                          onShowFullGraph: widget.onShowRelated,
                          onCollapse: () => setState(
                            () => _expandedFileId = null,
                          ),
                        ),
                    ],
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PendingAnalysisStrip extends StatelessWidget {
  final int pendingCount;
  const _PendingAnalysisStrip({required this.pendingCount});

  @override
  Widget build(BuildContext context) {
    final n = pendingCount;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: VaultSpacing.md,
        vertical: VaultSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.sm),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.hourglass_empty,
            size: 14,
            color: VaultColors.textTertiary,
          ),
          const SizedBox(width: VaultSpacing.xs + 2),
          Expanded(
            child: Text(
              '$n file${n == 1 ? '' : 's'} still being analyzed â€” '
              'more matches may appear once that finishes.',
              style: VaultText.caption,
            ),
          ),
        ],
      ),
    );
  }
}

class _FileSearchResultRow extends StatefulWidget {
  final Map<String, dynamic> file;
  final VoidCallback? onOpen;

  final VoidCallback? onShowRelated;

  const _FileSearchResultRow({
    required this.file,
    this.onOpen,
    this.onShowRelated,
  });

  @override
  State<_FileSearchResultRow> createState() => _FileSearchResultRowState();
}

class _FileSearchResultRowState extends State<_FileSearchResultRow> {
  bool _innerExpanded = false;

  @override
  Widget build(BuildContext context) {
    final file = widget.file;
    final onOpen = widget.onOpen;
    final fileName = (file['file_name'] as String?) ?? 'file';
    final savedName = (file['saved_name'] as String?)?.trim();
    final relativePath = (file['relative_path'] as String?)?.trim();
    final mime = (file['mime_type'] as String?) ?? '';
    final matchType =
        ((file['match_type'] as String?) ?? '').toLowerCase().trim();
    final matchReason = (file['match_reason'] as String?)?.trim() ?? '';
    final matchConfidence =
        ((file['match_confidence'] as String?) ?? 'weak').toLowerCase().trim();
    final purposeLabel = (file['purpose_label'] as String?)?.trim();

    final isArchiveMatch = file['is_archive_match'] == true;

    final thumbnailBase64 = (file['thumbnail_base64'] as String?)?.trim();
    final documentType =
        ((file['document_type'] as String?) ?? '').toLowerCase().trim();
    final matchedName = (file['matched_name'] as String?)?.trim();
    final fileKind =
        ((file['file_kind'] as String?) ?? '').toLowerCase().trim();

    final detailsRaw = file['archive_match_details'];
    final archiveDetails = detailsRaw is Map<String, dynamic>
        ? detailsRaw
        : (detailsRaw is Map ? detailsRaw.cast<String, dynamic>() : null);
    final innerMatchesRaw = archiveDetails?['inner_matches'];
    final innerMatches = innerMatchesRaw is List
        ? innerMatchesRaw
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final totalInnerRaw = archiveDetails?['total_inner_matches'];
    final totalInner =
        totalInnerRaw is int ? totalInnerRaw : innerMatches.length;
    final hasInnerMatches = isArchiveMatch && innerMatches.isNotEmpty;

    final title =
        (savedName != null && savedName.isNotEmpty) ? savedName : fileName;

    return InkWell(
      onTap: onOpen,
      borderRadius: BorderRadius.circular(VaultRadius.md),
      child: Container(
        padding: const EdgeInsets.all(VaultSpacing.md),
        decoration: BoxDecoration(
          color: VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.md),
          border: Border.all(color: VaultColors.borderSubtle),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _ResultLeadingThumb(
              thumbnailBase64: thumbnailBase64,
              fallbackIcon: _iconForMime(mime),
              fileKind: fileKind,
            ),
            const SizedBox(width: VaultSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: VaultText.subtitle.copyWith(fontSize: 15),
                        ),
                      ),
                      const SizedBox(width: VaultSpacing.sm),
                      _ConfidenceBadge(confidence: matchConfidence),
                    ],
                  ),
                  if (documentType.isNotEmpty && documentType != 'unknown') ...[
                    const SizedBox(height: 4),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: _DocumentTypeChip(documentType: documentType),
                    ),
                  ],
                  if (matchedName != null && matchedName.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        const Icon(
                          Icons.person_outline,
                          size: 12,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            matchedName,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption,
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (relativePath != null && relativePath.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        const Icon(
                          Icons.folder_outlined,
                          size: 12,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            relativePath,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption,
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (purposeLabel != null && purposeLabel.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        const Icon(
                          Icons.assignment_outlined,
                          size: 12,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            purposeLabel,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption.copyWith(
                              fontStyle: FontStyle.italic,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (matchReason.isNotEmpty || matchType.isNotEmpty) ...[
                    const SizedBox(height: VaultSpacing.xs + 2),
                    Wrap(
                      spacing: VaultSpacing.xs + 2,
                      runSpacing: VaultSpacing.xs,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        if (isArchiveMatch) const _ArchiveContentChip(),
                        if (matchType.isNotEmpty)
                          _MatchTypeChip(matchType: matchType),
                        if (matchReason.isNotEmpty)
                          ConstrainedBox(
                            constraints: const BoxConstraints(
                              maxWidth: 360,
                            ),
                            child: Text(
                              matchReason,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: VaultText.caption,
                            ),
                          ),
                      ],
                    ),
                  ],
                  if (hasInnerMatches) ...[
                    const SizedBox(height: VaultSpacing.xs + 2),
                    _InnerMatchesToggle(
                      expanded: _innerExpanded,
                      totalInner: totalInner,
                      onTap: () {
                        setState(() {
                          _innerExpanded = !_innerExpanded;
                        });
                      },
                    ),
                    if (_innerExpanded) ...[
                      const SizedBox(height: VaultSpacing.xs + 2),
                      _InnerMatchesList(inner: innerMatches),
                    ],
                  ],
                ],
              ),
            ),
            const SizedBox(width: VaultSpacing.sm),
            IconButton(
              tooltip: AppLocalizations.of(context).commonOpen,
              onPressed: onOpen,
              icon: const Icon(
                Icons.open_in_new,
                size: 18,
                color: VaultColors.accentBright,
              ),
            ),
            if (widget.onShowRelated != null)
              IconButton(
                tooltip: AppLocalizations.of(context).chatCardShowRelated,
                onPressed: widget.onShowRelated,
                visualDensity: VisualDensity.compact,
                icon: const Icon(
                  Icons.account_tree_outlined,
                  size: 18,
                  color: VaultColors.accentBright,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _ResultLeadingThumb extends StatelessWidget {
  final String? thumbnailBase64;
  final IconData fallbackIcon;
  final String fileKind;

  const _ResultLeadingThumb({
    required this.thumbnailBase64,
    required this.fallbackIcon,
    required this.fileKind,
  });

  static const double _size = 56;

  @override
  Widget build(BuildContext context) {
    final b64 = thumbnailBase64;
    if (b64 != null && b64.isNotEmpty) {
      Uint8List? bytes;
      try {
        bytes = base64Decode(b64);
      } catch (_) {
        bytes = null;
      }
      if (bytes != null && bytes.isNotEmpty) {
        return ClipRRect(
          borderRadius: BorderRadius.circular(VaultRadius.sm),
          child: Container(
            width: _size,
            height: _size,
            color: VaultColors.surfaceMuted,
            child: Image.memory(
              bytes,
              fit: BoxFit.cover,
              width: _size,
              height: _size,
              gaplessPlayback: true,
              filterQuality: FilterQuality.medium,
              errorBuilder: (_, __, ___) => _IconFallback(
                icon: fallbackIcon,
                fileKind: fileKind,
              ),
            ),
          ),
        );
      }
    }
    return _IconFallback(icon: fallbackIcon, fileKind: fileKind);
  }
}

class _IconFallback extends StatelessWidget {
  final IconData icon;
  final String fileKind;
  const _IconFallback({required this.icon, required this.fileKind});

  @override
  Widget build(BuildContext context) {
    return IconBadge(
      icon: icon,
      color: fileKind == 'pdf'
          ? VaultColors.severityCrit
          : VaultColors.severityInfo,
      size: 56,
      radius: VaultRadius.sm,
    );
  }
}

class _DocumentTypeChip extends StatelessWidget {
  final String documentType;
  const _DocumentTypeChip({required this.documentType});

  @override
  Widget build(BuildContext context) {
    final label = _humanLabel(documentType);
    final icon = _iconFor(documentType);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: VaultSpacing.sm,
        vertical: 2,
      ),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.sm),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: VaultColors.accentBright),
          const SizedBox(width: 4),
          Text(
            label,
            style: VaultText.caption.copyWith(
              color: VaultColors.accentBright,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  static String _humanLabel(String code) {
    switch (code) {
      case 'driver_license':
        return 'Driver license';
      case 'passport':
        return 'Passport';
      case 'id_photo':
        return 'ID photo';
      default:
        return code
            .split('_')
            .map((p) => p.isEmpty ? p : p[0].toUpperCase() + p.substring(1))
            .join(' ');
    }
  }

  static IconData _iconFor(String code) {
    switch (code) {
      case 'driver_license':
        return Icons.directions_car_outlined;
      case 'passport':
        return Icons.book_outlined;
      case 'id_photo':
        return Icons.badge_outlined;
      default:
        return Icons.description_outlined;
    }
  }
}

class _ArchiveContentChip extends StatelessWidget {
  const _ArchiveContentChip();

  @override
  Widget build(BuildContext context) {
    return const SeverityChip(
      level: 'info',
      label: 'ARCHIVE CONTENT',
      icon: Icons.folder_zip_outlined,
    );
  }
}

class _InnerMatchesToggle extends StatelessWidget {
  final bool expanded;
  final int totalInner;
  final VoidCallback? onTap;

  const _InnerMatchesToggle({
    required this.expanded,
    required this.totalInner,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final label =
        expanded ? 'Hide inner matches' : 'Show inner matches ($totalInner)';
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(VaultRadius.sm),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.xs + 2,
          vertical: VaultSpacing.xs,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              expanded ? Icons.expand_less : Icons.expand_more,
              size: 16,
              color: VaultColors.accentBright,
            ),
            const SizedBox(width: 4),
            Text(
              label,
              style: VaultText.caption.copyWith(
                color: VaultColors.accentBright,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _InnerMatchesList extends StatelessWidget {
  final List<Map<String, dynamic>> inner;

  static const int maxRows = 20;

  const _InnerMatchesList({required this.inner});

  @override
  Widget build(BuildContext context) {
    final shown = inner.length > maxRows ? inner.take(maxRows).toList() : inner;
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.sm),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.sm),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          for (final m in shown) ...[
            _InnerMatchRow(entry: m),
            if (m != shown.last)
              const Divider(
                height: VaultSpacing.sm + 4,
                thickness: 0.5,
                color: VaultColors.borderSubtle,
              ),
          ],
        ],
      ),
    );
  }
}

class _InnerMatchRow extends StatelessWidget {
  final Map<String, dynamic> entry;

  const _InnerMatchRow({required this.entry});

  @override
  Widget build(BuildContext context) {
    final path = (entry['path'] as String?)?.trim() ?? '';
    final reason = (entry['reason'] as String?)?.trim() ?? '';
    final kind = ((entry['kind'] as String?) ?? '').toLowerCase().trim();

    if (path.isEmpty) {
      return const SizedBox.shrink();
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          _iconForKind(kind),
          size: 14,
          color: VaultColors.textTertiary,
        ),
        const SizedBox(width: 6),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                path,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: VaultText.caption.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              if (reason.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(
                  reason,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: VaultText.caption,
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  IconData _iconForKind(String kind) {
    switch (kind) {
      case 'credentials':
        return Icons.password_outlined;
      case 'code':
        return Icons.code;
      case 'entity':
        return Icons.label_outlined;
      case 'topic':
        return Icons.topic_outlined;
      default:
        return Icons.description_outlined;
    }
  }
}

class _MatchTypeChip extends StatelessWidget {
  final String matchType;
  const _MatchTypeChip({required this.matchType});

  @override
  Widget build(BuildContext context) {
    final type = matchType.toLowerCase();
    String level;
    switch (type) {
      case 'purpose':
      case 'category':
      case 'entity':
        level = 'ok';
        break;
      case 'topic':
      case 'term':
      case 'date':
      case 'summary':
      case 'preview':
      case 'content':
        level = 'info';
        break;
      case 'folder':
      case 'filename':
      default:
        level = 'warning';
        break;
    }
    return SeverityChip(
      level: level,
      label: type.toUpperCase(),
    );
  }
}

class RelatedFilesGraphCard extends StatefulWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;

  final Future<Map<String, dynamic>?> Function(String fileId)? onLoadRelated;

  final void Function(String fileId)? onShowRelated;

  static const int maxRows = 100;

  static const double maxListHeight = 460;

  const RelatedFilesGraphCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onLoadRelated,
    this.onShowRelated,
  });

  @override
  State<RelatedFilesGraphCard> createState() => _RelatedFilesGraphCardState();
}

class _RelatedFilesGraphCardState extends State<RelatedFilesGraphCard> {
  String? _expandedFileId;

  @override
  Widget build(BuildContext context) {
    final msg = widget.msg;
    final onOpen = widget.onOpen;
    final onLoadRelated = widget.onLoadRelated;
    final p = msg.payload ?? const <String, dynamic>{};
    final anchorRaw = p['anchor'];
    final anchor = anchorRaw is Map<String, dynamic>
        ? anchorRaw
        : (anchorRaw is Map
            ? anchorRaw.cast<String, dynamic>()
            : const <String, dynamic>{});
    final relsRaw = p['relationships'];
    final relationships = relsRaw is List
        ? relsRaw
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];

    final anchorTitle = _anchorTitle(anchor);
    final headerTitle = 'Related to "$anchorTitle"';
    final headerSubtitle = relationships.isEmpty
        ? 'No related files'
        : '${relationships.length} related';

    if (relationships.isEmpty) {
      return VaultCard(
        padding: const EdgeInsets.all(VaultSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            CardHeader(
              icon: Icons.account_tree_outlined,
              iconColor: VaultColors.textSecondary,
              title: headerTitle,
              subtitle: headerSubtitle,
            ),
            const SizedBox(height: VaultSpacing.md),
            _RelatedAnchorRow(anchor: anchor),
            if (msg.text.trim().isNotEmpty) ...[
              const SizedBox(height: VaultSpacing.md),
              Text(msg.text, style: VaultText.body),
            ],
          ],
        ),
      );
    }

    final shown = relationships.length > RelatedFilesGraphCard.maxRows
        ? relationships.take(RelatedFilesGraphCard.maxRows).toList()
        : relationships;

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.account_tree_outlined,
            iconColor: VaultColors.accentBright,
            title: headerTitle,
            subtitle: headerSubtitle,
          ),
          const SizedBox(height: VaultSpacing.md),
          _RelatedAnchorRow(anchor: anchor),
          const SizedBox(height: VaultSpacing.md),
          ConstrainedBox(
            constraints: const BoxConstraints(
              maxHeight: RelatedFilesGraphCard.maxListHeight,
            ),
            child: Scrollbar(
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: shown.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: VaultSpacing.sm),
                itemBuilder: (context, i) {
                  final raw = shown[i];
                  final fileRaw = raw['file'];
                  final fileMap = fileRaw is Map<String, dynamic>
                      ? fileRaw
                      : (fileRaw is Map
                          ? fileRaw.cast<String, dynamic>()
                          : null);
                  final fid = (fileMap?['file_id'] as String?) ?? '';
                  final canExpand = onLoadRelated != null && fid.isNotEmpty;
                  final isExpanded = canExpand && _expandedFileId == fid;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _RelatedGraphFileRow(
                        entry: raw,
                        onOpen: () {
                          if (fileMap == null) return;
                          onOpen?.call(
                            VaultFileListCard._toFileMessage(
                              fileMap,
                              msg,
                            ),
                          );
                        },
                        onShowRelated: canExpand
                            ? () => setState(() {
                                  _expandedFileId = isExpanded ? null : fid;
                                })
                            : null,
                      ),
                      if (isExpanded)
                        _InlineRelatedSection(
                          fileId: fid,
                          parentMsg: msg,
                          onLoadRelated: onLoadRelated,
                          onOpen: onOpen,
                          onShowFullGraph: widget.onShowRelated,
                          onCollapse: () => setState(
                            () => _expandedFileId = null,
                          ),
                        ),
                    ],
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _anchorTitle(Map<String, dynamic> anchor) {
    final saved = (anchor['saved_name'] as String?)?.trim();
    if (saved != null && saved.isNotEmpty) return saved;
    final name = (anchor['file_name'] as String?)?.trim();
    if (name != null && name.isNotEmpty) return name;
    return 'this file';
  }
}

class _RelatedAnchorRow extends StatelessWidget {
  final Map<String, dynamic> anchor;
  const _RelatedAnchorRow({required this.anchor});

  @override
  Widget build(BuildContext context) {
    final saved = (anchor['saved_name'] as String?)?.trim();
    final name = (saved != null && saved.isNotEmpty)
        ? saved
        : ((anchor['file_name'] as String?)?.trim() ?? 'this file');
    final relativePath = (anchor['relative_path'] as String?)?.trim();
    final mime = (anchor['mime_type'] as String?) ?? '';

    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          IconBadge(
            icon: _iconForMime(mime),
            color: VaultColors.severityInfo,
            size: 36,
            radius: VaultRadius.sm,
          ),
          const SizedBox(width: VaultSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: VaultText.subtitle.copyWith(fontSize: 15),
                ),
                if (relativePath != null && relativePath.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      const Icon(
                        Icons.folder_outlined,
                        size: 12,
                        color: VaultColors.textTertiary,
                      ),
                      const SizedBox(width: 4),
                      Expanded(
                        child: Text(
                          relativePath,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: VaultText.caption,
                        ),
                      ),
                    ],
                  ),
                ],
                const SizedBox(height: 4),
                Text(
                  'Anchor file',
                  style: VaultText.caption.copyWith(
                    fontStyle: FontStyle.italic,
                    color: VaultColors.textTertiary,
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

class _RelatedGraphFileRow extends StatelessWidget {
  final Map<String, dynamic> entry;
  final VoidCallback? onOpen;

  final VoidCallback? onShowRelated;

  const _RelatedGraphFileRow({
    required this.entry,
    this.onOpen,
    this.onShowRelated,
  });

  @override
  Widget build(BuildContext context) {
    final fileRaw = entry['file'];
    final file = fileRaw is Map<String, dynamic>
        ? fileRaw
        : (fileRaw is Map
            ? fileRaw.cast<String, dynamic>()
            : const <String, dynamic>{});
    final fileName = (file['file_name'] as String?) ?? 'file';
    final savedName = (file['saved_name'] as String?)?.trim();
    final relativePath = (file['relative_path'] as String?)?.trim();
    final mime = (file['mime_type'] as String?) ?? '';
    final title =
        (savedName != null && savedName.isNotEmpty) ? savedName : fileName;

    final relationshipType =
        ((entry['relationship_type'] as String?) ?? '').toLowerCase().trim();
    final confidenceLabel =
        ((entry['confidence_label'] as String?) ?? 'weak').toLowerCase().trim();
    final reasonsRaw = entry['reasons'];
    final reasons = reasonsRaw is List
        ? reasonsRaw
            .whereType<String>()
            .map((s) => s.trim())
            .where((s) => s.isNotEmpty)
            .toList()
        : const <String>[];

    return InkWell(
      onTap: onOpen,
      borderRadius: BorderRadius.circular(VaultRadius.md),
      child: Container(
        padding: const EdgeInsets.all(VaultSpacing.md),
        decoration: BoxDecoration(
          color: VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.md),
          border: Border.all(color: VaultColors.borderSubtle),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            IconBadge(
              icon: _iconForMime(mime),
              color: VaultColors.severityInfo,
              size: 36,
              radius: VaultRadius.sm,
            ),
            const SizedBox(width: VaultSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: VaultText.subtitle.copyWith(fontSize: 15),
                        ),
                      ),
                      const SizedBox(width: VaultSpacing.sm),
                      _ConfidenceBadge(confidence: confidenceLabel),
                    ],
                  ),
                  if (relativePath != null && relativePath.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        const Icon(
                          Icons.folder_outlined,
                          size: 12,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            relativePath,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption,
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (relationshipType.isNotEmpty) ...[
                    const SizedBox(height: VaultSpacing.xs + 2),
                    Wrap(
                      spacing: VaultSpacing.xs + 2,
                      runSpacing: VaultSpacing.xs,
                      children: [
                        _RelationshipTypeChip(
                          relationshipType: relationshipType,
                        ),
                      ],
                    ),
                  ],
                  if (reasons.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    for (final r in reasons.take(3))
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Padding(
                              padding: EdgeInsets.only(top: 4, right: 4),
                              child: Icon(
                                Icons.chevron_right,
                                size: 12,
                                color: VaultColors.textTertiary,
                              ),
                            ),
                            Expanded(
                              child: Text(
                                r,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: VaultText.caption,
                              ),
                            ),
                          ],
                        ),
                      ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: VaultSpacing.sm),
            IconButton(
              tooltip: AppLocalizations.of(context).commonOpen,
              onPressed: onOpen,
              icon: const Icon(
                Icons.open_in_new,
                size: 18,
                color: VaultColors.accentBright,
              ),
            ),
            if (onShowRelated != null)
              IconButton(
                tooltip: AppLocalizations.of(context).chatCardShowRelated,
                onPressed: onShowRelated,
                visualDensity: VisualDensity.compact,
                icon: const Icon(
                  Icons.account_tree_outlined,
                  size: 18,
                  color: VaultColors.accentBright,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _RelationshipTypeChip extends StatelessWidget {
  final String relationshipType;
  const _RelationshipTypeChip({required this.relationshipType});

  @override
  Widget build(BuildContext context) {
    final type = relationshipType.toLowerCase();
    String level;
    switch (type) {
      case 'duplicate':
      case 'front_back_pair':
      case 'near_duplicate':
      case 'same_person':
        level = 'ok';
        break;
      case 'same_trip':
      case 'same_financial_account':
      case 'same_company':
      case 'supporting_document':
      case 'archive_contains_signal':
      case 'same_document_family':
      case 'semantic_related':
        level = 'info';
        break;
      case 'same_folder':
      case 'same_import_batch':
      default:
        level = 'warning';
        break;
    }
    return SeverityChip(
      level: level,
      label: type.toUpperCase().replaceAll('_', ' '),
    );
  }
}

const int _kInlineRelatedMaxRows = 6;

class _InlineRelatedSection extends StatefulWidget {
  final String fileId;
  final ChatMessage parentMsg;
  final Future<Map<String, dynamic>?> Function(String fileId) onLoadRelated;
  final void Function(ChatMessage fileMsg)? onOpen;
  final VoidCallback onCollapse;

  final void Function(String fileId)? onShowFullGraph;

  const _InlineRelatedSection({
    required this.fileId,
    required this.parentMsg,
    required this.onLoadRelated,
    required this.onCollapse,
    this.onOpen,
    this.onShowFullGraph,
  });

  @override
  State<_InlineRelatedSection> createState() => _InlineRelatedSectionState();
}

class _InlineRelatedSectionState extends State<_InlineRelatedSection> {
  bool _loading = true;
  Map<String, dynamic>? _envelope;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(_InlineRelatedSection old) {
    super.didUpdateWidget(old);
    if (old.fileId != widget.fileId) {
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _envelope = null;
      _error = null;
    });
    try {
      final env = await widget.onLoadRelated(widget.fileId);
      if (!mounted) return;
      setState(() {
        _envelope = env;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = "Couldn't load related files right now.";
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final Widget inner;
    if (_loading) {
      inner = const _InlineLoadingRow();
    } else if (_error != null) {
      inner = _InlineErrorRow(message: _error!, onRetry: _load);
    } else {
      final envelope = _envelope ?? const <String, dynamic>{};
      final relsRaw = envelope['relationships'];
      final relationships = relsRaw is List
          ? relsRaw
              .whereType<Map>()
              .map((m) => m.cast<String, dynamic>())
              .toList()
          : const <Map<String, dynamic>>[];
      if (relationships.isEmpty) {
        inner = const _InlineEmptyRow();
      } else {
        final shown = relationships.length > _kInlineRelatedMaxRows
            ? relationships.take(_kInlineRelatedMaxRows).toList()
            : relationships;
        final hiddenCount = relationships.length - shown.length;
        inner = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final r in shown)
              Padding(
                padding: const EdgeInsets.only(top: VaultSpacing.xs),
                child: _InlineRelatedRow(
                  entry: r,
                  parentMsg: widget.parentMsg,
                  onOpen: widget.onOpen,
                ),
              ),
            if (hiddenCount > 0)
              _InlineMoreFooter(
                hiddenCount: hiddenCount,
                onShowFullGraph: widget.onShowFullGraph == null
                    ? null
                    : () => widget.onShowFullGraph!(widget.fileId),
              ),
          ],
        );
      }
    }

    return Padding(
      padding: const EdgeInsets.only(
        top: VaultSpacing.xs + 2,
        bottom: VaultSpacing.xs + 2,
        left: VaultSpacing.lg,
      ),
      child: Container(
        padding: const EdgeInsets.all(VaultSpacing.sm + 2),
        decoration: BoxDecoration(
          color: VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.md),
          border: Border.all(color: VaultColors.borderSubtle),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Icon(
                  Icons.account_tree_outlined,
                  size: 14,
                  color: VaultColors.accentBright,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'Related to this file',
                    style: VaultText.caption.copyWith(
                      fontWeight: FontWeight.w600,
                      color: VaultColors.accentBright,
                    ),
                  ),
                ),
                InkWell(
                  onTap: widget.onCollapse,
                  borderRadius: BorderRadius.circular(VaultRadius.sm),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: VaultSpacing.xs + 2,
                      vertical: 2,
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.expand_less,
                          size: 14,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 2),
                        Text(
                          'Hide related',
                          style: VaultText.caption,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: VaultSpacing.xs + 2),
            inner,
          ],
        ),
      ),
    );
  }
}

class _InlineLoadingRow extends StatelessWidget {
  const _InlineLoadingRow();

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const SizedBox(
          width: 14,
          height: 14,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: VaultColors.accentBright,
          ),
        ),
        const SizedBox(width: VaultSpacing.sm),
        Text(
          'Loading related files…',
          style: VaultText.caption,
        ),
      ],
    );
  }
}

class _InlineEmptyRow extends StatelessWidget {
  const _InlineEmptyRow();

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(
          Icons.search_off_outlined,
          size: 14,
          color: VaultColors.textTertiary,
        ),
        const SizedBox(width: VaultSpacing.xs + 2),
        Expanded(
          child: Text(
            "I don't see strong related files for this yet.",
            style: VaultText.caption,
          ),
        ),
      ],
    );
  }
}

class _InlineErrorRow extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _InlineErrorRow({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        const Icon(
          Icons.error_outline,
          size: 14,
          color: VaultColors.severityWarn,
        ),
        const SizedBox(width: VaultSpacing.xs + 2),
        Expanded(
          child: Text(message, style: VaultText.caption),
        ),
        TextButton.icon(
          onPressed: onRetry,
          icon: const Icon(Icons.refresh, size: 14),
          label: const Text('Retry'),
          style: TextButton.styleFrom(
            minimumSize: const Size(0, 28),
            padding: const EdgeInsets.symmetric(
              horizontal: VaultSpacing.sm,
            ),
            visualDensity: VisualDensity.compact,
          ),
        ),
      ],
    );
  }
}

class _InlineRelatedRow extends StatelessWidget {
  final Map<String, dynamic> entry;
  final ChatMessage parentMsg;
  final void Function(ChatMessage fileMsg)? onOpen;

  const _InlineRelatedRow({
    required this.entry,
    required this.parentMsg,
    this.onOpen,
  });

  @override
  Widget build(BuildContext context) {
    final fileRaw = entry['file'];
    final file = fileRaw is Map<String, dynamic>
        ? fileRaw
        : (fileRaw is Map
            ? fileRaw.cast<String, dynamic>()
            : const <String, dynamic>{});
    final fileName = (file['file_name'] as String?) ?? 'file';
    final savedName = (file['saved_name'] as String?)?.trim();
    final relativePath = (file['relative_path'] as String?)?.trim();
    final mime = (file['mime_type'] as String?) ?? '';
    final title =
        (savedName != null && savedName.isNotEmpty) ? savedName : fileName;

    final relationshipType =
        ((entry['relationship_type'] as String?) ?? '').toLowerCase().trim();
    final confidenceLabel =
        ((entry['confidence_label'] as String?) ?? 'weak').toLowerCase().trim();
    final reasonsRaw = entry['reasons'];
    final reasons = reasonsRaw is List
        ? reasonsRaw
            .whereType<String>()
            .map((s) => s.trim())
            .where((s) => s.isNotEmpty)
            .toList()
        : const <String>[];

    void tapOpen() {
      if (file.isEmpty || onOpen == null) return;
      onOpen!.call(VaultFileListCard._toFileMessage(file, parentMsg));
    }

    return InkWell(
      onTap: tapOpen,
      borderRadius: BorderRadius.circular(VaultRadius.sm),
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.sm + 2,
          vertical: VaultSpacing.xs + 2,
        ),
        decoration: BoxDecoration(
          color: VaultColors.surface,
          borderRadius: BorderRadius.circular(VaultRadius.sm),
          border: Border.all(color: VaultColors.borderSubtle),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            IconBadge(
              icon: _iconForMime(mime),
              color: VaultColors.severityInfo,
              size: 28,
              radius: VaultRadius.sm,
            ),
            const SizedBox(width: VaultSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: VaultText.subtitle.copyWith(fontSize: 13),
                        ),
                      ),
                      const SizedBox(width: VaultSpacing.xs + 2),
                      _ConfidenceBadge(confidence: confidenceLabel),
                    ],
                  ),
                  if (relativePath != null && relativePath.isNotEmpty) ...[
                    const SizedBox(height: 1),
                    Row(
                      children: [
                        const Icon(
                          Icons.folder_outlined,
                          size: 10,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 3),
                        Expanded(
                          child: Text(
                            relativePath,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption.copyWith(fontSize: 11),
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (relationshipType.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Wrap(
                      spacing: VaultSpacing.xs + 2,
                      runSpacing: VaultSpacing.xs,
                      children: [
                        _RelationshipTypeChip(
                          relationshipType: relationshipType,
                        ),
                      ],
                    ),
                  ],
                  if (reasons.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(
                      '› ${reasons.first}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: VaultText.caption.copyWith(fontSize: 11),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: VaultSpacing.xs + 2),
            IconButton(
              tooltip: AppLocalizations.of(context).commonOpen,
              onPressed: tapOpen,
              visualDensity: VisualDensity.compact,
              icon: const Icon(
                Icons.open_in_new,
                size: 16,
                color: VaultColors.accentBright,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _InlineMoreFooter extends StatelessWidget {
  final int hiddenCount;
  final VoidCallback? onShowFullGraph;

  const _InlineMoreFooter({
    required this.hiddenCount,
    this.onShowFullGraph,
  });

  @override
  Widget build(BuildContext context) {
    if (onShowFullGraph == null) {
      return Padding(
        padding: const EdgeInsets.only(top: VaultSpacing.sm),
        child: Text(
          '+$hiddenCount more — open the file to see the full graph.',
          style: VaultText.caption,
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(top: VaultSpacing.sm),
      child: InkWell(
        onTap: onShowFullGraph,
        borderRadius: BorderRadius.circular(VaultRadius.sm),
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: VaultSpacing.xs + 2,
            vertical: 2,
          ),
          child: Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                '+$hiddenCount more — ',
                style: VaultText.caption,
              ),
              Text(
                'View full graph',
                style: VaultText.caption.copyWith(
                  color: VaultColors.accentBright,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(width: 4),
              const Icon(
                Icons.open_in_new,
                size: 12,
                color: VaultColors.accentBright,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class VaultRelationshipClustersCard extends StatelessWidget {
  final ChatMessage msg;

  final void Function(ChatMessage fileMsg)? onOpen;

  final void Function(String fileId)? onShowRelated;

  static const int maxClusters = 100;

  static const double maxListHeight = 520;

  const VaultRelationshipClustersCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onShowRelated,
  });

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final clustersRaw = p['clusters'];
    final clusters = clustersRaw is List
        ? clustersRaw
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final headerSubtitle = clusters.isEmpty
        ? 'No connected groups yet'
        : '${clusters.length} group${clusters.length == 1 ? '' : 's'}';

    if (clusters.isEmpty) {
      return VaultCard(
        padding: const EdgeInsets.all(VaultSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            CardHeader(
              icon: Icons.hub_outlined,
              iconColor: VaultColors.textSecondary,
              title: 'Connected groups in your vault',
              subtitle: headerSubtitle,
            ),
            if (msg.text.trim().isNotEmpty) ...[
              const SizedBox(height: VaultSpacing.md),
              Text(msg.text, style: VaultText.body),
            ],
          ],
        ),
      );
    }

    final shown = clusters.length > maxClusters
        ? clusters.take(maxClusters).toList()
        : clusters;

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: Icons.hub_outlined,
            iconColor: VaultColors.accentBright,
            title: 'Connected groups in your vault',
            subtitle: headerSubtitle,
          ),
          if (msg.text.trim().isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Text(msg.text, style: VaultText.body),
          ],
          const SizedBox(height: VaultSpacing.md),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: maxListHeight),
            child: Scrollbar(
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: shown.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: VaultSpacing.md),
                itemBuilder: (context, i) {
                  final c = shown[i];
                  return _VaultClusterRow(
                    cluster: c,
                    parentMsg: msg,
                    onOpen: onOpen,
                    onShowRelated: onShowRelated,
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _VaultClusterRow extends StatefulWidget {
  final Map<String, dynamic> cluster;
  final ChatMessage parentMsg;
  final void Function(ChatMessage fileMsg)? onOpen;
  final void Function(String fileId)? onShowRelated;

  static const int previewFiles = 5;

  static const int detailFilesCap = 50;

  const _VaultClusterRow({
    required this.cluster,
    required this.parentMsg,
    this.onOpen,
    this.onShowRelated,
  });

  @override
  State<_VaultClusterRow> createState() => _VaultClusterRowState();
}

class _VaultClusterRowState extends State<_VaultClusterRow> {
  bool _isExpanded = false;

  @override
  Widget build(BuildContext context) {
    final cluster = widget.cluster;
    final onOpen = widget.onOpen;
    final onShowRelated = widget.onShowRelated;
    final parentMsg = widget.parentMsg;

    final title = (cluster['title'] as String?)?.trim() ?? 'Connected group';
    final clusterType =
        ((cluster['cluster_type'] as String?) ?? '').toLowerCase().trim();
    final confidence =
        ((cluster['confidence'] as String?) ?? 'weak').toLowerCase().trim();
    final fileCount =
        cluster['file_count'] is int ? cluster['file_count'] as int : 0;
    final reasonsRaw = cluster['main_reasons'];
    final reasons = reasonsRaw is List
        ? reasonsRaw
            .whereType<String>()
            .map((s) => s.trim())
            .where((s) => s.isNotEmpty)
            .toList()
        : const <String>[];
    final filesRaw = cluster['representative_files'];
    final files = filesRaw is List
        ? filesRaw
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final cappedFiles = files.length > _VaultClusterRow.detailFilesCap
        ? files.take(_VaultClusterRow.detailFilesCap).toList()
        : files;
    final hasDetailToggle = cappedFiles.length > _VaultClusterRow.previewFiles;
    final shownFiles = _isExpanded
        ? cappedFiles
        : (cappedFiles.length > _VaultClusterRow.previewFiles
            ? cappedFiles.take(_VaultClusterRow.previewFiles).toList()
            : cappedFiles);
    final hiddenCount = cappedFiles.length - shownFiles.length;

    final trueOverflow = fileCount - cappedFiles.length;
    final warningsRaw = cluster['warnings'];
    final warnings = warningsRaw is List
        ? warningsRaw
            .whereType<String>()
            .map((s) => s.trim())
            .where((s) => s.isNotEmpty)
            .toList()
        : const <String>[];

    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
        border: Border.all(color: VaultColors.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              IconBadge(
                icon: _iconForClusterType(clusterType),
                color: VaultColors.accentBright,
                size: 32,
                radius: VaultRadius.sm,
              ),
              const SizedBox(width: VaultSpacing.sm),
              Expanded(
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: VaultText.subtitle.copyWith(fontSize: 15),
                ),
              ),
              const SizedBox(width: VaultSpacing.xs + 2),
              _ConfidenceBadge(confidence: confidence),
            ],
          ),
          const SizedBox(height: VaultSpacing.xs + 2),
          Wrap(
            spacing: VaultSpacing.xs + 2,
            runSpacing: VaultSpacing.xs,
            children: [
              if (clusterType.isNotEmpty)
                _ClusterTypeChip(clusterType: clusterType),
              MetaPill(
                label: '$fileCount file${fileCount == 1 ? '' : 's'}',
                icon: Icons.insert_drive_file_outlined,
              ),
            ],
          ),
          if (reasons.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.xs + 2),
            for (final r in reasons.take(3))
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(top: 4, right: 4),
                      child: Icon(
                        Icons.chevron_right,
                        size: 12,
                        color: VaultColors.textTertiary,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        r,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: VaultText.caption,
                      ),
                    ),
                  ],
                ),
              ),
          ],
          if (shownFiles.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.sm),
            for (final raw in shownFiles)
              Padding(
                padding: const EdgeInsets.only(bottom: VaultSpacing.xs),
                child: _ClusterFileRow(
                  file: raw,
                  parentMsg: parentMsg,
                  onOpen: onOpen,
                  onShowRelated: onShowRelated,
                ),
              ),
          ],
          if (hasDetailToggle)
            Padding(
              padding: const EdgeInsets.only(top: VaultSpacing.xs),
              child: _ViewClusterToggle(
                expanded: _isExpanded,
                hiddenCount: _isExpanded ? 0 : hiddenCount,
                onTap: () => setState(() {
                  _isExpanded = !_isExpanded;
                }),
              ),
            ),
          if (_isExpanded && trueOverflow > 0)
            Padding(
              padding: const EdgeInsets.only(top: VaultSpacing.xs),
              child: Text(
                "+$trueOverflow more — search this cluster's "
                'files to see them all.',
                style: VaultText.caption.copyWith(
                  fontStyle: FontStyle.italic,
                ),
              ),
            ),
          if (warnings.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.sm),
            for (final w in warnings)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(top: 2, right: 4),
                      child: Icon(
                        Icons.info_outline,
                        size: 12,
                        color: VaultColors.severityWarn,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        w,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: VaultText.caption.copyWith(
                          fontStyle: FontStyle.italic,
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

class _ClusterFileRow extends StatelessWidget {
  final Map<String, dynamic> file;
  final ChatMessage parentMsg;
  final void Function(ChatMessage fileMsg)? onOpen;
  final void Function(String fileId)? onShowRelated;

  const _ClusterFileRow({
    required this.file,
    required this.parentMsg,
    this.onOpen,
    this.onShowRelated,
  });

  @override
  Widget build(BuildContext context) {
    final fileName = (file['file_name'] as String?) ?? 'file';
    final savedName = (file['saved_name'] as String?)?.trim();
    final relativePath = (file['relative_path'] as String?)?.trim();
    final mime = (file['mime_type'] as String?) ?? '';
    final fid = (file['file_id'] as String?) ?? '';
    final title =
        (savedName != null && savedName.isNotEmpty) ? savedName : fileName;

    void tapOpen() {
      if (fid.isEmpty || onOpen == null) return;
      onOpen!.call(
        VaultFileListCard._toFileMessage(file, parentMsg),
      );
    }

    return InkWell(
      onTap: tapOpen,
      borderRadius: BorderRadius.circular(VaultRadius.sm),
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.sm + 2,
          vertical: VaultSpacing.xs + 2,
        ),
        decoration: BoxDecoration(
          color: VaultColors.surface,
          borderRadius: BorderRadius.circular(VaultRadius.sm),
          border: Border.all(color: VaultColors.borderSubtle),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            IconBadge(
              icon: _iconForMime(mime),
              color: VaultColors.severityInfo,
              size: 28,
              radius: VaultRadius.sm,
            ),
            const SizedBox(width: VaultSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: VaultText.subtitle.copyWith(fontSize: 13),
                  ),
                  if (relativePath != null && relativePath.isNotEmpty) ...[
                    const SizedBox(height: 1),
                    Row(
                      children: [
                        const Icon(
                          Icons.folder_outlined,
                          size: 10,
                          color: VaultColors.textTertiary,
                        ),
                        const SizedBox(width: 3),
                        Expanded(
                          child: Text(
                            relativePath,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: VaultText.caption.copyWith(fontSize: 11),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: VaultSpacing.xs + 2),
            IconButton(
              tooltip: AppLocalizations.of(context).commonOpen,
              onPressed: tapOpen,
              visualDensity: VisualDensity.compact,
              icon: const Icon(
                Icons.open_in_new,
                size: 16,
                color: VaultColors.accentBright,
              ),
            ),
            if (onShowRelated != null && fid.isNotEmpty)
              IconButton(
                tooltip: AppLocalizations.of(context).chatCardShowRelated,
                onPressed: () => onShowRelated!(fid),
                visualDensity: VisualDensity.compact,
                icon: const Icon(
                  Icons.account_tree_outlined,
                  size: 16,
                  color: VaultColors.accentBright,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _ClusterTypeChip extends StatelessWidget {
  final String clusterType;
  const _ClusterTypeChip({required this.clusterType});

  @override
  Widget build(BuildContext context) {
    final type = clusterType.toLowerCase();
    String level;
    switch (type) {
      case 'identity':
      case 'travel':
      case 'finance':
      case 'tax':
      case 'duplicates':
        level = 'ok';
        break;
      case 'company':
      case 'application':
      case 'archive_content':
      case 'same_person':
        level = 'info';
        break;
      case 'same_folder':
      default:
        level = 'warning';
        break;
    }
    return SeverityChip(
      level: level,
      label: type.toUpperCase().replaceAll('_', ' '),
    );
  }
}

class _ViewClusterToggle extends StatelessWidget {
  final bool expanded;
  final int hiddenCount;
  final VoidCallback? onTap;

  const _ViewClusterToggle({
    required this.expanded,
    required this.hiddenCount,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final label = expanded
        ? 'Hide cluster'
        : (hiddenCount > 0
            ? 'View cluster — +$hiddenCount more'
            : 'View cluster');
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(VaultRadius.sm),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.xs + 2,
          vertical: 2,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              expanded ? Icons.expand_less : Icons.expand_more,
              size: 14,
              color: VaultColors.accentBright,
            ),
            const SizedBox(width: 4),
            Text(
              label,
              style: VaultText.caption.copyWith(
                color: VaultColors.accentBright,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

IconData _iconForClusterType(String t) {
  switch (t) {
    case 'identity':
      return Icons.badge_outlined;
    case 'travel':
      return Icons.flight_takeoff_outlined;
    case 'finance':
      return Icons.account_balance_outlined;
    case 'tax':
      return Icons.receipt_long_outlined;
    case 'application':
      return Icons.description_outlined;
    case 'company':
      return Icons.business_outlined;
    case 'duplicates':
      return Icons.copy_all_outlined;
    case 'archive_content':
      return Icons.folder_zip_outlined;
    case 'same_person':
      return Icons.person_outline;
    case 'same_folder':
      return Icons.folder_outlined;
    default:
      return Icons.hub_outlined;
  }
}

class VaultBrainAnswerCard extends StatelessWidget {
  final ChatMessage msg;
  final void Function(ChatMessage fileMsg)? onOpen;

  final VoidCallback? onSearchDeeper;

  static const int maxRows = 12;

  static const double maxListHeight = 320;

  const VaultBrainAnswerCard({
    super.key,
    required this.msg,
    this.onOpen,
    this.onSearchDeeper,
  });

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final evidence = (p['evidence'] is List)
        ? (p['evidence'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final coverage = (p['coverage'] is Map)
        ? (p['coverage'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final noEvidence = (p['no_evidence'] == true);
    final retrievalMode = (p['retrieval_mode'] as String?)?.trim() ?? '';
    final continuationAvailable = (p['continuation_available'] == true);
    final body = msg.text;

    final shown =
        evidence.length > maxRows ? evidence.take(maxRows).toList() : evidence;

    final subtitle = noEvidence
        ? 'No matching vault content'
        : (retrievalMode == 'lexical_fallback' ||
                retrievalMode == 'chunk_text_lexical')
            ? '${shown.length} match${shown.length == 1 ? '' : 'es'} '
                '(${retrievalMode == 'chunk_text_lexical' ? 'text scan' : 'filename'} fallback)'
            : '${shown.length} match${shown.length == 1 ? '' : 'es'} '
                'from vault content';

    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          CardHeader(
            icon: noEvidence
                ? Icons.search_off_outlined
                : Icons.psychology_outlined,
            iconColor:
                noEvidence ? VaultColors.textSecondary : VaultColors.accent,
            title: 'Vault intelligence',
            subtitle: subtitle,
          ),
          if (body.trim().isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            Text(body, style: VaultText.body),
          ],
          if (coverage.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            _BrainCoverageStrip(coverage: coverage),
          ],
          if (shown.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.md),
            const Text(
              'Evidence',
              style: VaultText.caption,
            ),
            const SizedBox(height: VaultSpacing.xs),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: maxListHeight),
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: shown.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: VaultSpacing.xs),
                itemBuilder: (context, i) {
                  final row = shown[i];
                  return _BrainEvidenceRow(
                    row: row,
                    onTap: () {
                      final fid = (row['file_id'] as String?)?.trim() ?? '';
                      final fname =
                          (row['file_name'] as String?)?.trim() ?? 'file';
                      if (fid.isEmpty || onOpen == null) return;
                      onOpen!(ChatMessage(
                        'assistant',
                        fname,
                        kind: ChatMessage.kVaultFile,
                        fileId: fid,
                        fileName: fname,
                      ));
                    },
                  );
                },
              ),
            ),
          ],
          if (continuationAvailable && onSearchDeeper != null) ...[
            const SizedBox(height: VaultSpacing.md),
            OutlinedButton.icon(
              onPressed: onSearchDeeper,
              icon: const Icon(
                Icons.travel_explore_outlined,
                size: 18,
              ),
              label: Text(
                AppLocalizations.of(context).chatCardSearchDeeper,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _BrainCoverageStrip extends StatelessWidget {
  final Map<String, dynamic> coverage;

  const _BrainCoverageStrip({required this.coverage});

  @override
  Widget build(BuildContext context) {
    final isComplete = coverage['is_complete'] == true;
    final hasFailures = coverage['has_failures'] == true;
    final totalFiles =
        (coverage['total_files'] is int) ? coverage['total_files'] as int : 0;
    final indexedFiles = (coverage['files_with_embedded_chunks'] is int)
        ? coverage['files_with_embedded_chunks'] as int
        : 0;
    final pct = (coverage['coverage_percentage'] is num)
        ? (coverage['coverage_percentage'] as num).toDouble()
        : 0.0;
    final pctLabel = '${(pct * 100).clamp(0, 100).toStringAsFixed(0)}%';

    final label = totalFiles == 0
        ? 'Vault is empty'
        : isComplete
            ? 'Vault intelligence fully indexed ($indexedFiles/$totalFiles, $pctLabel)'
            : 'Vault intelligence indexed $indexedFiles/$totalFiles files ($pctLabel)';

    return Row(
      children: [
        Icon(
          isComplete ? Icons.check_circle_outline : Icons.sync_outlined,
          size: 14,
          color: hasFailures
              ? VaultColors.textTertiary
              : (isComplete ? VaultColors.accent : VaultColors.textSecondary),
        ),
        const SizedBox(width: 4),
        Expanded(
          child: Text(
            hasFailures ? '$label — some files failed' : label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: VaultText.caption,
          ),
        ),
      ],
    );
  }
}

class _BrainEvidenceRow extends StatelessWidget {
  final Map<String, dynamic> row;
  final VoidCallback onTap;

  const _BrainEvidenceRow({
    required this.row,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final fileName = (row['file_name'] as String?)?.trim() ?? '';
    final snippet = (row['snippet'] as String?)?.trim() ?? '';
    final source = (row['extraction_source'] as String?)?.trim() ?? '';
    final score =
        (row['score'] is num) ? (row['score'] as num).toDouble() : 0.0;

    final sourceLabel = _prettySource(source);
    final scoreLabel =
        score > 0 ? '${(score * 100).toStringAsFixed(0)}%' : null;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(VaultRadius.md),
      child: Padding(
        padding: const EdgeInsets.all(VaultSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Icon(
                  Icons.description_outlined,
                  size: 14,
                  color: VaultColors.textSecondary,
                ),
                const SizedBox(width: 4),
                Expanded(
                  child: Text(
                    fileName.isNotEmpty ? fileName : 'file',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: VaultText.subtitle,
                  ),
                ),
                if (sourceLabel != null) ...[
                  const SizedBox(width: 4),
                  MetaPill(label: sourceLabel),
                ],
                if (scoreLabel != null) ...[
                  const SizedBox(width: 4),
                  MetaPill(label: scoreLabel),
                ],
              ],
            ),
            if (snippet.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                snippet,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: VaultText.caption,
              ),
            ],
          ],
        ),
      ),
    );
  }

  String? _prettySource(String s) {
    switch (s) {
      case 'pdf_text':
        return 'PDF';
      case 'ocr':
        return 'OCR';
      case 'image_ocr':
        return 'OCR';
      case 'docx':
        return 'DOCX';
      case 'txt':
        return 'Text';
      case 'html':
        return 'HTML';
      case 'json':
        return 'JSON';
      case 'csv':
        return 'CSV';
      case 'xlsx':
        return 'XLSX';
      case 'archive':
        return 'Archive';
      case 'audio_transcript':
        return 'Audio';
      case 'video_transcript':
        return 'Video';
      case 'video_frame':
        return 'Frame';
      case 'plain_text':
        return 'Text';
      default:
        return null;
    }
  }
}

const Map<String, IconData> kSecureItemChatIcons = <String, IconData>{
  'login': Icons.lock_outline,
  'credential': Icons.vpn_key_outlined,
  'device': Icons.devices_other_outlined,
  'device_info': Icons.devices_other_outlined,
  'imei': Icons.smartphone_outlined,
  'serial_number': Icons.numbers_outlined,
  'document_note': Icons.sticky_note_2_outlined,
  'recovery_code': Icons.shield_outlined,
  'recovery_phrase': Icons.shield_outlined,
  'backup_code': Icons.backup_outlined,
  'private_note': Icons.notes_outlined,
  'account_note': Icons.note_outlined,
  'bank': Icons.account_balance_outlined,
  'card': Icons.credit_card_outlined,
  'license_key': Icons.key_outlined,
  'product_key': Icons.key_outlined,
  'activation_key': Icons.key_outlined,
  'private_key': Icons.key_outlined,
  'other': Icons.inventory_2_outlined,
  'other_secret': Icons.policy_outlined,
  'crypto_wallet_address': Icons.account_balance_wallet_outlined,
  'crypto_seed_phrase': Icons.password_outlined,
  'crypto_private_key': Icons.key_outlined,
  'crypto_recovery_phrase': Icons.shield_outlined,
  'crypto_note': Icons.notes_outlined,
  'crypto_transaction_note': Icons.receipt_long_outlined,
  'crypto_exchange_note': Icons.swap_horiz_outlined,
  'crypto_hardware_wallet_note': Icons.usb_outlined,
};

bool _chatIsLoginLike(String itemType) {
  return itemType == 'login' || itemType == 'credential';
}

String? _pullRevealedValue(String itemType, Map<String, dynamic> preview) {
  final List<String> keys;
  if (itemType == 'imei') {
    keys = const ['imei_1', 'imei_2'];
  } else if (itemType == 'serial_number') {
    keys = const ['serial_number', 'serial'];
  } else if (itemType == 'crypto_wallet_address') {
    keys = const ['wallet_address'];
  } else if (itemType == 'crypto_seed_phrase') {
    keys = const ['seed_phrase'];
  } else if (itemType == 'crypto_private_key') {
    keys = const ['private_key'];
  } else if (itemType == 'crypto_recovery_phrase') {
    keys = const ['recovery_phrase'];
  } else if (itemType == 'private_note') {
    keys = const ['private_value', 'private_word', 'secret_value'];
  } else if (itemType == 'account_note') {
    keys = const ['account_notes'];
  } else if (itemType == 'backup_code' || itemType == 'recovery_code') {
    keys = const ['backup_codes', 'recovery_code'];
  } else if (itemType == 'license_key') {
    keys = const ['license_key'];
  } else if (itemType == 'product_key') {
    keys = const ['product_key'];
  } else if (itemType == 'activation_key') {
    keys = const ['activation_key'];
  } else if (itemType == 'private_key') {
    keys = const ['private_key'];
  } else if (itemType == 'recovery_phrase') {
    keys = const ['recovery_phrase'];
  } else {
    keys = const ['secret_value', 'private_value'];
  }
  for (final k in keys) {
    final v = preview[k];
    if (v is String && v.isNotEmpty) return v;
  }
  return null;
}

String _chatPreviewLineFor(
  String itemType,
  Map<String, dynamic> preview, {
  required bool reveal,
}) {
  if (reveal) {
    if (_chatIsLoginLike(itemType)) {
      final username = (preview['username'] as String?)?.trim() ?? '';
      final password = (preview['password'] as String?)?.trim() ?? '';
      if (username.isNotEmpty && password.isNotEmpty) {
        return 'Username: $username   •   Password: $password';
      }
      if (password.isNotEmpty) return 'Password: $password';
      if (username.isNotEmpty) return 'Username: $username';
      return 'Login saved';
    }
    for (final key in const [
      'wallet_address',
      'imei_1',
      'imei_2',
      'serial_number',
      'serial',
      'mac_address',
      'mac',
      'phone_number',
      'phone',
      'recovery_code',
      'backup_codes',
      'private_value',
      'private_word',
      'secret_value',
      'account_notes',
      'seed_phrase',
      'private_key',
      'recovery_phrase',
      'crypto_note',
      'transaction_note',
      'exchange_note',
      'hardware_wallet_note',
      'license_key',
      'product_key',
      'activation_key',
    ]) {
      final value = preview[key];
      if (value is String && value.isNotEmpty) return value;
    }
    return 'Login saved';
  }
  if (_chatIsLoginLike(itemType)) {
    final username = (preview['username'] as String?)?.trim() ?? '';
    if (username.isNotEmpty) {
      return 'Username: $username   •   Password saved';
    }
    if (preview['has_password'] == true) return 'Password saved';
    return 'Login saved';
  }
  if (itemType == 'imei') {
    final mask = (preview['imei_1_mask'] as String?)?.trim() ?? '';
    if (mask.isNotEmpty) return 'IMEI $mask';
    return 'IMEI saved (hidden)';
  }
  if (itemType == 'serial_number') {
    final mask = (preview['serial_number_mask'] as String?)?.trim() ?? '';
    if (mask.isNotEmpty) return 'Serial $mask';
    return 'Serial saved (hidden)';
  }
  if (itemType == 'crypto_wallet_address') {
    final mask = (preview['wallet_address_mask'] as String?)?.trim() ?? '';
    final network = (preview['network'] as String?)?.trim() ?? '';
    if (mask.isNotEmpty && network.isNotEmpty) {
      return '$network  $mask';
    }
    if (mask.isNotEmpty) return mask;
    return 'Wallet address saved';
  }
  if (itemType == 'crypto_seed_phrase' ||
      itemType == 'crypto_private_key' ||
      itemType == 'crypto_recovery_phrase') {
    return '•••••• hidden — open only when you mean to read it';
  }
  if (itemType == 'private_note' ||
      itemType == 'account_note' ||
      itemType == 'private_key' ||
      itemType == 'recovery_phrase' ||
      itemType == 'license_key' ||
      itemType == 'product_key' ||
      itemType == 'activation_key' ||
      itemType == 'backup_code' ||
      itemType == 'recovery_code') {
    return '•••••• hidden';
  }
  return 'Stored securely';
}

class SecureItemCardActions {
  final void Function(String itemId, String title, String itemType)? onView;

  final void Function(String itemId, String title, String itemType)? onReveal;

  final void Function(String username)? onCopyUsername;

  final void Function(String value)? onCopyValue;

  final void Function(String title, String itemType)? onEdit;

  final void Function(String title, String itemType)? onDelete;

  const SecureItemCardActions({
    this.onView,
    this.onReveal,
    this.onCopyUsername,
    this.onCopyValue,
    this.onEdit,
    this.onDelete,
  });
}

class SecureItemResultsCard extends StatelessWidget {
  final ChatMessage msg;
  final SecureItemCardActions actions;

  static const int maxRows = 50;

  const SecureItemResultsCard({
    super.key,
    required this.msg,
    this.actions = const SecureItemCardActions(),
  });

  @override
  Widget build(BuildContext context) {
    final p = msg.payload ?? const <String, dynamic>{};
    final items = (p['items'] is List)
        ? (p['items'] as List)
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList()
        : const <Map<String, dynamic>>[];
    final reveal = p['reveal'] == true;

    final rawMode = (p['display_mode'] as String?)?.trim() ?? '';
    final isDetail =
        rawMode == 'detail' || (rawMode.isEmpty && reveal && items.length == 1);
    final count = (p['count'] is int) ? p['count'] as int : items.length;
    final message = (p['message'] as String?)?.trim() ?? '';
    final shown = items.length > maxRows ? items.take(maxRows).toList() : items;

    final headerLine = message.isNotEmpty
        ? message
        : (count == 1
            ? "Here's the saved item I found 🔐"
            : 'I found $count saved items 🔐');

    if (shown.isEmpty) {
      return Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFF2A2A2A),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Colors.white10),
        ),
        child: Text(
          headerLine,
          style: const TextStyle(color: Colors.white, fontSize: 14),
        ),
      );
    }

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF2A2A2A),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(6, 4, 6, 10),
            child: Text(
              headerLine,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          ...shown.map((row) => _SecureItemRow(
                row: row,
                reveal: reveal,
                isDetail: isDetail,
                actions: actions,
              )),
        ],
      ),
    );
  }
}

class _SecureItemRow extends StatelessWidget {
  final Map<String, dynamic> row;
  final bool reveal;

  final bool isDetail;
  final SecureItemCardActions actions;

  const _SecureItemRow({
    required this.row,
    required this.reveal,
    required this.isDetail,
    required this.actions,
  });

  @override
  Widget build(BuildContext context) {
    final itemId = (row['item_id'] as String?)?.trim() ?? '';
    final title = (row['title'] as String?)?.trim() ?? '';
    final itemType = (row['type'] as String?)?.trim() ?? 'other';
    final chip = (row['category_label'] as String?)?.trim() ?? itemType;
    final preview = (row['preview'] is Map)
        ? Map<String, dynamic>.from(row['preview'] as Map)
        : const <String, dynamic>{};
    final icon = kSecureItemChatIcons[itemType] ?? Icons.inventory_2_outlined;
    final previewLine = _chatPreviewLineFor(
      itemType,
      preview,
      reveal: reveal,
    );

    final isLogin = _chatIsLoginLike(itemType);
    final username =
        isLogin ? ((preview['username'] as String?)?.trim() ?? '') : '';
    final password =
        isLogin ? ((preview['password'] as String?)?.trim() ?? '') : '';
    final nonLoginValue =
        !isLogin && reveal ? (_pullRevealedValue(itemType, preview) ?? '') : '';
    final detailFields = isLogin && reveal
        ? _secureItemDetailFields(
            preview,
            username: username,
            password: password,
          )
        : const <_SecureItemDetailField>[];

    return Container(
      key: Key('secure_item_chat_card_$itemType-$title-$itemId'),
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF1F1F1F),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: const Color(0xFF10A37F).withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  icon,
                  color: const Color(0xFF10A37F),
                  size: 18,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title.isEmpty ? 'Saved item' : title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 7,
                        vertical: 1,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xFF10A37F).withValues(alpha: 0.16),
                        borderRadius: BorderRadius.circular(7),
                      ),
                      child: Text(
                        chip,
                        style: const TextStyle(
                          color: Color(0xFF10A37F),
                          fontSize: 10,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (isDetail)
            _DetailBody(
              isLogin: isLogin,
              username: username,
              password: password,
              nonLoginValue: nonLoginValue,
              fallbackLine: previewLine,
              fields: detailFields,
            )
          else
            Text(
              previewLine,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: Color(0xFFD0D0D0),
                fontSize: 12,
              ),
            ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              if (!isDetail)
                TextButton.icon(
                  key: const Key('secure_item_chat_card_view'),
                  onPressed: actions.onView == null
                      ? null
                      : () => actions.onView!(itemId, title, itemType),
                  icon: const Icon(Icons.visibility_outlined, size: 14),
                  label: const Text(
                    'View',
                    style: TextStyle(fontSize: 12),
                  ),
                ),
              if (isLogin && username.isNotEmpty)
                TextButton.icon(
                  key: const Key('secure_item_chat_card_copy_username'),
                  onPressed: actions.onCopyUsername == null
                      ? null
                      : () => actions.onCopyUsername!(username),
                  icon: const Icon(Icons.copy_outlined, size: 14),
                  label: const Text(
                    'Copy username',
                    style: TextStyle(fontSize: 12),
                  ),
                ),
              if (isLogin && reveal && password.isNotEmpty)
                TextButton.icon(
                  key: const Key('secure_item_chat_card_copy_password'),
                  onPressed: actions.onCopyValue == null
                      ? null
                      : () => actions.onCopyValue!(password),
                  icon: const Icon(Icons.copy_outlined, size: 14),
                  label: const Text(
                    'Copy password',
                    style: TextStyle(fontSize: 12),
                  ),
                ),
              if (!isLogin && reveal && nonLoginValue.isNotEmpty)
                TextButton.icon(
                  key: const Key('secure_item_chat_card_copy_value'),
                  onPressed: actions.onCopyValue == null
                      ? null
                      : () => actions.onCopyValue!(nonLoginValue),
                  icon: const Icon(Icons.copy_outlined, size: 14),
                  label: const Text(
                    'Copy value',
                    style: TextStyle(fontSize: 12),
                  ),
                ),
              TextButton.icon(
                key: const Key('secure_item_chat_card_edit'),
                onPressed: actions.onEdit == null
                    ? null
                    : () => actions.onEdit!(title, itemType),
                icon: const Icon(Icons.edit_outlined, size: 14),
                label: const Text('Edit', style: TextStyle(fontSize: 12)),
              ),
              TextButton.icon(
                key: const Key('secure_item_chat_card_delete'),
                onPressed: actions.onDelete == null
                    ? null
                    : () => actions.onDelete!(title, itemType),
                icon: const Icon(Icons.delete_outline, size: 14),
                label: const Text(
                  'Delete',
                  style: TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SecureItemDetailField {
  final String label;
  final String value;
  final Key? valueKey;

  const _SecureItemDetailField({
    required this.label,
    required this.value,
    this.valueKey,
  });
}

List<_SecureItemDetailField> _secureItemDetailFields(
  Map<String, dynamic> preview, {
  required String username,
  required String password,
}) {
  final out = <_SecureItemDetailField>[];
  final raw = preview['fields'];
  if (raw is List) {
    for (final item in raw) {
      if (item is! Map) continue;
      final label = (item['label'] ?? '').toString().trim();
      final value = (item['value'] ?? '').toString();
      if (label.isEmpty) continue;
      out.add(_SecureItemDetailField(label: label, value: value));
    }
  } else if (raw is Map) {
    for (final entry in raw.entries) {
      final label = entry.key.toString().trim();
      final value = (entry.value ?? '').toString();
      if (label.isEmpty) continue;
      out.add(_SecureItemDetailField(label: label, value: value));
    }
  }
  if (out.isNotEmpty) return out;
  if (username.isNotEmpty) {
    out.add(_SecureItemDetailField(
      label: 'Username',
      value: username,
      valueKey: const Key('secure_item_chat_card_detail_username'),
    ));
  }
  if (password.isNotEmpty) {
    out.add(_SecureItemDetailField(
      label: 'Password',
      value: password,
      valueKey: const Key('secure_item_chat_card_detail_password'),
    ));
  }
  return out;
}

class _DetailBody extends StatelessWidget {
  final bool isLogin;
  final String username;
  final String password;
  final String nonLoginValue;
  final String fallbackLine;
  final List<_SecureItemDetailField> fields;

  const _DetailBody({
    required this.isLogin,
    required this.username,
    required this.password,
    required this.nonLoginValue,
    required this.fallbackLine,
    this.fields = const <_SecureItemDetailField>[],
  });

  @override
  Widget build(BuildContext context) {
    const String _kMissingValueCopy =
        "No saved value attached. Ask your vault to look it up "
        "again.";
    if (isLogin) {
      if (fields.isEmpty) {
        return const _DetailFallback(text: _kMissingValueCopy);
      }
      return Container(
        key: const Key('secure_item_chat_card_detail_body'),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: const Color(0xFF161616),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: Colors.white12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < fields.length; i++) ...[
              if (i > 0) const SizedBox(height: 6),
              _DetailRow(
                label: fields[i].label,
                value: fields[i].value,
                valueKey: fields[i].valueKey ??
                    Key('secure_item_chat_card_detail_field_$i'),
              ),
            ],
          ],
        ),
      );
    }
    if (nonLoginValue.isEmpty) {
      return const _DetailFallback(text: _kMissingValueCopy);
    }
    return Container(
      key: const Key('secure_item_chat_card_detail_body'),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFF161616),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white12),
      ),
      child: SelectableText(
        nonLoginValue,
        key: const Key('secure_item_chat_card_detail_value'),
        style: const TextStyle(
          color: Colors.white,
          fontSize: 13,
          fontFamily: 'monospace',
          height: 1.45,
        ),
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;
  final Key? valueKey;

  const _DetailRow({
    required this.label,
    required this.value,
    this.valueKey,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: Color(0xFF8E8E8E),
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.4,
          ),
        ),
        const SizedBox(height: 3),
        SelectableText(
          value,
          key: valueKey,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 13,
            fontFamily: 'monospace',
            height: 1.4,
          ),
        ),
      ],
    );
  }
}

class _DetailFallback extends StatelessWidget {
  final String text;
  const _DetailFallback({required this.text});

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        color: Color(0xFFD0D0D0),
        fontSize: 12,
      ),
    );
  }
}
