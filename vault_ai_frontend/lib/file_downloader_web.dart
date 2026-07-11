

import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';


/// Browser-file download for the `download` button on chat file cards.
///
/// Semantics enforced by this class (see the accompanying test file
/// `file_downloader_web_2026_07_12_test.dart`):
///
///   * Creates a `Blob` with the caller-supplied MIME (falling back
///     to `application/octet-stream` for unknown types — matches the
///     browser's own default for a missing Content-Type).
///   * Uses `URL.createObjectURL` to produce a blob URL. **Never**
///     uses `window.open`, `window.location`, or in-page navigation.
///   * Creates a hidden anchor with `download = fileName` so the
///     browser saves the file with the original filename + extension
///     instead of viewing it in-tab.
///   * Fires exactly one `click()` on the anchor, then removes it.
///   * Defers `revokeObjectUrl` to a later frame (via
///     `Future.delayed(seconds: 60)`) — Safari + some Chromium builds
///     will abort the download if the object URL is revoked
///     synchronously in the same microtask as the click. 60 s is
///     long enough for any real-world download to have started.
///   * Never opens the media viewer; never mutates route state.
///
/// This class MUST stay isolated from the media viewer path — the
/// bug we shipped in the previous iteration was that the "Download"
/// button on the file card wired straight into `_openVaultFileCard`,
/// which opened `_openMediaDialog` instead of hitting this class.
class FileDownloader {
  bool downloadBytes({
    required Uint8List bytes,
    required String fileName,
    required String? mimeType,
  }) {
    String? blobUrl;
    try {
      final mime = (mimeType == null || mimeType.isEmpty)
          ? 'application/octet-stream'
          : mimeType;
      final blob = html.Blob([bytes], mime);
      blobUrl = html.Url.createObjectUrlFromBlob(blob);
      final anchor = html.AnchorElement(href: blobUrl)
        ..download = fileName
        // rel=noopener prevents the anchor's fake window from ever
        // gaining a reference to the current window. It also side-
        // steps a Safari edge case where the click can leak an
        // opener even for download anchors.
        ..rel = 'noopener'
        ..style.display = 'none';
      html.document.body?.append(anchor);
      anchor.click();
      anchor.remove();
      // Deferred revoke: revoking synchronously here has been
      // observed to abort the download in Safari + some Chromium
      // release channels. 60s is long enough for any browser to
      // have consumed the URL. The url is captured in a local so
      // the finally block below does not double-revoke.
      final urlToRevoke = blobUrl;
      blobUrl = null;
      Future<void>.delayed(const Duration(seconds: 60), () {
        try {
          html.Url.revokeObjectUrl(urlToRevoke);
        } catch (_) {}
      });
      return true;
    } catch (_) {
      return false;
    } finally {
      if (blobUrl != null) {
        // Only reached on the catch path — we set blobUrl=null right
        // after a successful click(), so the "success" revoke goes
        // through the deferred future above and NOT this finally.
        try {
          html.Url.revokeObjectUrl(blobUrl);
        } catch (_) {}
      }
    }
  }

  /// Kept for legacy call sites that want to preview a file in a new
  /// tab (e.g. PDF preview fallback). NOT wired to the chat card's
  /// Download button — that path calls `downloadBytes` above.
  bool openBytesInBrowser({
    required Uint8List bytes,
    required String fileName,
    required String? mimeType,
  }) {
    String? blobUrl;
    try {
      final mime = (mimeType == null || mimeType.isEmpty)
          ? 'application/octet-stream'
          : mimeType;
      final blob = html.Blob([bytes], mime);
      blobUrl = html.Url.createObjectUrlFromBlob(blob);

      html.window.open(blobUrl, '_blank');


      final urlToRevoke = blobUrl;
      Future<void>.delayed(const Duration(seconds: 60), () {
        try {
          html.Url.revokeObjectUrl(urlToRevoke);
        } catch (_) {}
      });
      blobUrl = null;
      return true;
    } catch (_) {
      return false;
    } finally {
      if (blobUrl != null) {
        try {
          html.Url.revokeObjectUrl(blobUrl);
        } catch (_) {}
      }
    }
  }
}
