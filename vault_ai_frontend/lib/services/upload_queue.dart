import 'dart:async';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';

enum UploadJobStatus {
  pending,

  reading,

  uploading,

  uploaded,

  failed,

  retrying,

  cancelled,

  skippedDuplicate,

  stoppedForStorage,
}

class UploadJob {
  final String id;

  final String name;

  final String? displayName;

  final String kind;

  final String? mimeType;

  final int size;

  final String? relativePath;

  final String? importId;

  final Future<Uint8List> Function() readBytes;

  UploadJobStatus status;
  double progress;
  String? errorMessage;
  String? uploadedFileId;
  int attempts;

  String? duplicateAction;

  Map<String, dynamic>? duplicateDetail;

  UploadResult? lastResult;

  Uint8List? cachedBytes;

  /// Stable identity for one logical File V2 write. It survives automatic
  /// and operator-triggered retries of this queue job so an uncertain network
  /// response cannot create a second authoritative manifest.
  String? fileV2Id;

  UploadJob({
    required this.id,
    required this.name,
    required this.kind,
    required this.size,
    required this.readBytes,
    this.displayName,
    this.mimeType,
    this.relativePath,
    this.importId,
  })  : status = UploadJobStatus.pending,
        progress = 0,
        attempts = 0;

  bool get isTerminal =>
      status == UploadJobStatus.uploaded ||
      status == UploadJobStatus.failed ||
      status == UploadJobStatus.cancelled ||
      status == UploadJobStatus.skippedDuplicate ||
      status == UploadJobStatus.stoppedForStorage;
}

class UploadResult {
  final String fileId;

  final bool autoNamed;

  final String? message;

  final bool skippedDuplicate;

  final String? existingRelativePath;

  final bool renamed;

  final String? originalSavedName;

  const UploadResult({
    required this.fileId,
    this.autoNamed = false,
    this.message,
    this.skippedDuplicate = false,
    this.existingRelativePath,
    this.renamed = false,
    this.originalSavedName,
  });
}

class TransientUploadException implements Exception {
  final String reason;
  final Duration? pauseFor;
  const TransientUploadException(this.reason, {this.pauseFor});

  @override
  String toString() => 'TransientUploadException($reason, pauseFor=$pauseFor)';
}

class DuplicateUploadDecisionRequired implements Exception {
  final Map<String, dynamic> detail;
  const DuplicateUploadDecisionRequired(this.detail);

  @override
  String toString() => 'DuplicateUploadDecisionRequired()';
}

enum DuplicateUploadDecision { skip, keepBoth }

typedef DuplicateResolver = Future<DuplicateUploadDecision?> Function(
  UploadJob job,
  Map<String, dynamic> detail,
);

class NameConflictDecisionRequired implements Exception {
  final Map<String, dynamic> detail;
  const NameConflictDecisionRequired(this.detail);

  @override
  String toString() => 'NameConflictDecisionRequired()';
}

enum NameConflictDecision { keepBoth, cancel, replace }

typedef NameConflictResolver = Future<NameConflictDecision?> Function(
  UploadJob job,
  Map<String, dynamic> detail,
);

class StorageLimitDuringUploadException implements Exception {
  final String message;
  final int? usedBytes;
  final int? limitBytes;

  const StorageLimitDuringUploadException({
    required this.message,
    this.usedBytes,
    this.limitBytes,
  });

  @override
  String toString() => 'StorageLimitDuringUploadException(message: $message)';
}

typedef StorageLimitHandler = void Function(
  StorageLimitDuringUploadException error,
);

typedef UploadAction = Future<UploadResult> Function(
  UploadJob job,
  Uint8List bytes,
  void Function(double progress) reportProgress,
);

Future<Uint8List> readPlatformFileBytes(PlatformFile pf) async {
  final stream = pf.readStream;
  if (stream != null) {
    final builder = BytesBuilder(copy: false);
    await for (final chunk in stream) {
      builder.add(chunk);
    }
    return builder.takeBytes();
  }
  final eager = pf.bytes;
  if (eager != null) return eager;
  throw StateError(
    'PlatformFile "${pf.name}" has no readStream and no bytes — '
    'pick with withReadStream:true or withData:true',
  );
}

class UploadQueueController extends ChangeNotifier {
  final int maxConcurrency;

  final int maxAttempts;

  final Duration maxBackoff;

  final UploadAction action;

  final DuplicateResolver? onDuplicate;

  final NameConflictResolver? onNameConflict;

  final StorageLimitHandler? onStorageLimitHit;

  final List<UploadJob> _jobs = [];
  int _inFlight = 0;
  DateTime? _pauseUntil;
  Timer? _resumeTimer;
  bool _disposed = false;

  UploadQueueController({
    required this.action,
    this.maxConcurrency = 3,
    this.maxAttempts = 3,
    this.maxBackoff = const Duration(seconds: 30),
    this.onDuplicate,
    this.onNameConflict,
    this.onStorageLimitHit,
  })  : assert(maxConcurrency > 0),
        assert(maxAttempts > 0);

  bool _stoppedForStorage = false;
  bool get stoppedForStorage => _stoppedForStorage;

  int get stoppedForStorageCount =>
      _jobs.where((j) => j.status == UploadJobStatus.stoppedForStorage).length;

  List<UploadJob> get jobs => List.unmodifiable(_jobs);

  int get totalCount => _jobs.length;
  int get uploadedCount =>
      _jobs.where((j) => j.status == UploadJobStatus.uploaded).length;
  int get failedCount =>
      _jobs.where((j) => j.status == UploadJobStatus.failed).length;
  int get pendingCount =>
      _jobs.where((j) => j.status == UploadJobStatus.pending).length;
  int get inFlightCount => _inFlight;
  int get cancelledCount =>
      _jobs.where((j) => j.status == UploadJobStatus.cancelled).length;

  int get skippedDuplicateCount =>
      _jobs.where((j) => j.status == UploadJobStatus.skippedDuplicate).length;

  int get renamedCount =>
      _jobs.where((j) => j.lastResult?.renamed == true).length;

  bool get isBusy => _jobs.any((j) => !j.isTerminal);

  bool get hasFailures => failedCount > 0;

  Duration? get pauseRemaining {
    final until = _pauseUntil;
    if (until == null) return null;
    final remaining = until.difference(DateTime.now());
    return remaining.isNegative ? null : remaining;
  }

  void enqueue(UploadJob job) {
    if (_disposed) return;
    _jobs.add(job);
    notifyListeners();
    _pump();
  }

  void enqueueAll(Iterable<UploadJob> jobs) {
    if (_disposed) return;
    final list = jobs.toList(growable: false);
    if (list.isEmpty) return;
    _jobs.addAll(list);
    notifyListeners();
    _pump();
  }

  void retry(String jobId) {
    final job = _findJob(jobId);
    if (job == null) return;
    if (job.status != UploadJobStatus.failed) return;
    job.status = UploadJobStatus.pending;
    job.attempts = 0;
    job.errorMessage = null;
    job.progress = 0;
    notifyListeners();
    _pump();
  }

  void retryAllFailed() {
    var changed = false;
    for (final j in _jobs) {
      if (j.status == UploadJobStatus.failed) {
        j.status = UploadJobStatus.pending;
        j.attempts = 0;
        j.errorMessage = null;
        j.progress = 0;
        changed = true;
      }
    }
    if (changed) {
      notifyListeners();
      _pump();
    }
  }

  void cancel(String jobId) {
    final job = _findJob(jobId);
    if (job == null || job.isTerminal) return;
    job.status = UploadJobStatus.cancelled;
    job.cachedBytes = null;
    notifyListeners();
  }

  void cancelAll() {
    var changed = false;
    for (final j in _jobs) {
      if (!j.isTerminal) {
        j.status = UploadJobStatus.cancelled;
        j.cachedBytes = null;
        changed = true;
      }
    }
    if (changed) notifyListeners();
  }

  void clearTerminal() {
    final before = _jobs.length;
    _jobs.removeWhere((j) => j.isTerminal);
    if (_jobs.length != before) notifyListeners();
  }

  void reset() {
    cancelAll();
    _jobs.clear();
    notifyListeners();
  }

  Future<List<String>> waitForIdle() {
    if (!isBusy) return Future.value(_collectUploadedIds());
    final completer = Completer<List<String>>();
    late void Function() listener;
    listener = () {
      if (!isBusy) {
        removeListener(listener);
        if (!completer.isCompleted) {
          completer.complete(_collectUploadedIds());
        }
      }
    };
    addListener(listener);
    return completer.future;
  }

  UploadJob? _nextPending() {
    for (final j in _jobs) {
      if (j.status == UploadJobStatus.pending) return j;
    }
    return null;
  }

  void _pump() {
    if (_disposed) return;
    if (_pauseUntil != null && _pauseUntil!.isAfter(DateTime.now())) {
      _schedulePauseResume();
      return;
    }
    while (_inFlight < maxConcurrency) {
      final next = _nextPending();
      if (next == null) return;
      _inFlight += 1;

      _runJob(next);
    }
  }

  void _schedulePauseResume() {
    final until = _pauseUntil;
    if (until == null) return;
    final delay = until.difference(DateTime.now());
    _resumeTimer?.cancel();
    _resumeTimer = Timer(
      delay.isNegative ? Duration.zero : delay,
      () {
        _pauseUntil = null;
        _resumeTimer = null;
        notifyListeners();
        _pump();
      },
    );
  }

  Future<void> _runJob(UploadJob job) async {
    try {
      while (true) {
        if (_disposed) return;
        if (job.status == UploadJobStatus.cancelled) return;

        job.attempts += 1;
        job.status = UploadJobStatus.reading;
        job.progress = 0;
        notifyListeners();

        Uint8List bytes;
        try {
          bytes = job.cachedBytes ?? await job.readBytes();
          job.cachedBytes = bytes;
        } catch (e) {
          job.status = UploadJobStatus.failed;
          job.errorMessage = 'Could not read file: $e';
          notifyListeners();
          return;
        }

        if (job.status == UploadJobStatus.cancelled) return;
        job.status = UploadJobStatus.uploading;
        notifyListeners();

        try {
          final result = await action(job, bytes, (p) {
            if (job.isTerminal) return;
            job.progress = p.clamp(0, 1).toDouble();
            notifyListeners();
          });

          if (job.status == UploadJobStatus.cancelled) {
            job.cachedBytes = null;
            notifyListeners();
            return;
          }

          if (result.skippedDuplicate) {
            job.status = UploadJobStatus.skippedDuplicate;

            job.uploadedFileId = result.fileId;
            job.lastResult = result;
            job.progress = 1;
            job.cachedBytes = null;
            notifyListeners();
            return;
          }
          job.status = UploadJobStatus.uploaded;
          job.uploadedFileId = result.fileId;
          job.lastResult = result;
          job.progress = 1;
          job.cachedBytes = null;
          notifyListeners();
          return;
        } on StorageLimitDuringUploadException catch (e) {
          job.status = UploadJobStatus.stoppedForStorage;
          job.cachedBytes = null;
          job.errorMessage = e.message;
          for (final other in _jobs) {
            if (other.isTerminal) continue;
            other.status = UploadJobStatus.stoppedForStorage;
            other.cachedBytes = null;
            other.errorMessage = e.message;
          }
          final shouldFire = !_stoppedForStorage;
          _stoppedForStorage = true;
          notifyListeners();
          if (shouldFire) {
            try {
              onStorageLimitHit?.call(e);
            } catch (_) {}
          }
          return;
        } on NameConflictDecisionRequired catch (e) {
          job.duplicateDetail = e.detail;
          NameConflictDecision decision = NameConflictDecision.cancel;
          final resolver = onNameConflict;
          if (resolver != null) {
            try {
              final choice = await resolver(job, e.detail);
              if (choice != null) decision = choice;
            } catch (_) {
              decision = NameConflictDecision.cancel;
            }
          }
          if (_disposed || job.status == UploadJobStatus.cancelled) {
            return;
          }
          if (decision == NameConflictDecision.keepBoth) {
            job.duplicateAction = 'keep_both';
            job.status = UploadJobStatus.pending;
            job.attempts -= 1;
            notifyListeners();
            continue;
          }

          job.status = UploadJobStatus.cancelled;
          job.cachedBytes = null;
          notifyListeners();
          return;
        } on DuplicateUploadDecisionRequired catch (e) {
          job.duplicateDetail = e.detail;
          DuplicateUploadDecision decision = DuplicateUploadDecision.skip;
          final resolver = onDuplicate;
          if (resolver != null) {
            try {
              final choice = await resolver(job, e.detail);
              if (choice != null) decision = choice;
            } catch (_) {
              decision = DuplicateUploadDecision.skip;
            }
          }
          if (_disposed || job.status == UploadJobStatus.cancelled) {
            return;
          }
          if (decision == DuplicateUploadDecision.keepBoth) {
            job.duplicateAction = 'keep_both';
            job.status = UploadJobStatus.pending;
            job.attempts -= 1;
            notifyListeners();
            continue;
          }

          job.status = UploadJobStatus.skippedDuplicate;
          job.uploadedFileId = (e.detail['existing_file_id'] as String?) ?? '';
          job.progress = 1;
          job.cachedBytes = null;
          notifyListeners();
          return;
        } on TransientUploadException catch (e) {
          if (e.pauseFor != null && e.pauseFor!.inMilliseconds > 0) {
            final newPauseUntil = DateTime.now().add(e.pauseFor!);

            if (_pauseUntil == null || newPauseUntil.isAfter(_pauseUntil!)) {
              _pauseUntil = newPauseUntil;
            }
          }
          if (job.attempts >= maxAttempts) {
            job.status = UploadJobStatus.failed;
            job.errorMessage = e.reason;
            notifyListeners();
            return;
          }
          job.status = UploadJobStatus.retrying;
          notifyListeners();
          final backoff = e.pauseFor ?? _backoffFor(job.attempts);
          await Future.delayed(backoff);
          if (_disposed || job.status == UploadJobStatus.cancelled) return;

          while (_pauseUntil != null && _pauseUntil!.isAfter(DateTime.now())) {
            await Future.delayed(
              _pauseUntil!.difference(DateTime.now()),
            );
          }
          if (_disposed || job.status == UploadJobStatus.cancelled) return;
          continue;
        } catch (e) {
          job.status = UploadJobStatus.failed;
          job.errorMessage = '$e';
          notifyListeners();
          return;
        }
      }
    } finally {
      _inFlight -= 1;
      if (!_disposed) _pump();
    }
  }

  Duration _backoffFor(int attempt) {
    final ms = 250 * (1 << (attempt - 1));
    final clamped =
        ms > maxBackoff.inMilliseconds ? maxBackoff.inMilliseconds : ms;
    return Duration(milliseconds: clamped);
  }

  UploadJob? _findJob(String id) {
    for (final j in _jobs) {
      if (j.id == id) return j;
    }
    return null;
  }

  List<String> _collectUploadedIds() {
    return [
      for (final j in _jobs)
        if (j.status == UploadJobStatus.uploaded && j.uploadedFileId != null)
          j.uploadedFileId!,
    ];
  }

  @override
  void dispose() {
    _disposed = true;
    _resumeTimer?.cancel();
    super.dispose();
  }
}
