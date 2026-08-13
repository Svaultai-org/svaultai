import 'file_v2_repository.dart';

/// QA-only capability probe. It exposes no token, MVK, or key material.
class QaRuntimeAccess {
  static Future<Map<String, dynamic>> Function()? _list;
  static Future<Map<String, dynamic>> Function(String)? _download;
  static Future<bool> Function(String)? _delete;

  static void install({required Future<Map<String, dynamic>> Function() list,
      required Future<Map<String, dynamic>> Function(String) download,
      required Future<bool> Function(String) delete}) {
    _list = list; _download = download; _delete = delete;
  }

  static void clear() { _list = null; _download = null; _delete = null; }

  static bool get fileV2RepositoryAvailable =>
      FileV2Repository.current() != null && _list != null;

  static Future<Map<String, dynamic>> list() =>
      _list?.call() ?? Future.error(StateError('file_v2_qa_unavailable'));
  static Future<Map<String, dynamic>> download(String fileId) =>
      _download?.call(fileId) ?? Future.error(StateError('file_v2_qa_unavailable'));
  static Future<bool> delete(String fileId) =>
      _delete?.call(fileId) ?? Future.error(StateError('file_v2_qa_unavailable'));
}
