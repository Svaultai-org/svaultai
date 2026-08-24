import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/attachment_title_binding.dart';
import 'package:vault_ai_frontend/services/file_inventory_view_state.dart';

void main() {
  test('unrequested and delayed inventories render loading, never false empty',
      () async {
    var loading = false;
    var completed = false;
    var count = 0;

    FileInventoryViewState state() => resolveFileInventoryViewState(
          loading: loading,
          authoritativeLoadCompleted: completed,
          fileCount: count,
          hasError: false,
        );

    expect(state(), FileInventoryViewState.loading);

    final response = Completer<int>();
    loading = true;
    final load = response.future.then((value) {
      count = value;
      completed = true;
      loading = false;
    });
    expect(state(), FileInventoryViewState.loading);

    response.complete(1);
    await load;
    expect(state(), FileInventoryViewState.readyWithFiles);
  });

  test('empty is rendered only after an authoritative completed load', () {
    expect(
      resolveFileInventoryViewState(
        loading: false,
        authoritativeLoadCompleted: true,
        fileCount: 0,
        hasError: false,
      ),
      FileInventoryViewState.readyEmpty,
    );
    expect(
      resolveFileInventoryViewState(
        loading: false,
        authoritativeLoadCompleted: false,
        fileCount: 0,
        hasError: true,
      ),
      FileInventoryViewState.error,
    );
  });

  test('chosen vault name is authoritative for normal confirmation copy', () {
    expect(
      uploadConfirmationName(
        originalFilename: 'image_random_device_name.png',
        chosenTitle: 'john',
      ),
      'john',
    );
    expect(
      filenameWithChosenTitle(
        originalFilename: 'image_random_device_name.png',
        chosenTitle: 'john',
      ),
      'john.png',
    );
  });

  test('production Files route triggers authoritative hydration directly', () {
    final source = File('lib/main.dart').readAsStringSync();
    final filesCase = source.indexOf('case _DashboardSection.files:');
    final loginsCase = source.indexOf(
      'case _DashboardSection.logins:',
      filesCase,
    );
    final route = source.substring(filesCase, loginsCase);

    expect(route, contains('addPostFrameCallback'));
    expect(route, contains('_loadVaultFiles()'));
    expect(route, contains('!hasLoadedFiles'));
    expect(route, contains('!loadingFiles'));
  });

  test('File V2 confirmation uses chosen-name precedence helper', () {
    final source = File('lib/main.dart').readAsStringSync();
    final uploadStart = source.indexOf('final fileId = job.fileV2Id');
    final legacyStart =
        source.indexOf('Map<String, dynamic> result;', uploadStart);
    final fileV2Upload = source.substring(uploadStart, legacyStart);

    expect(fileV2Upload, contains('uploadConfirmationName('));
    expect(fileV2Upload, isNot(contains("message: 'Uploaded \${job.name}.")));
  });
}
