import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/private_v2_folder_tree.dart';

void main() {
  final completeFiles = <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 'old-root',
      'file_name': 'notes.txt',
      'relative_path': null,
    },
    <String, dynamic>{
      'id': 'old-nested',
      'file_name': 'old.jpg',
      'relative_path': 'Holiday/old.jpg',
    },
    <String, dynamic>{
      'id': 'private-nested',
      'file_name': 'beach.jpg',
      'relative_path': 'holiday/Beach/beach.jpg',
      'v2_ready': true,
    },
  ];

  test('complete signed inventory builds old and private folders locally', () {
    final root = buildPrivateLocalFolderTree(path: '', files: completeFiles);
    expect((root['files'] as List).map((file) => file['id']), <String>[
      'old-root',
    ]);
    expect(root['folders'], <Map<String, dynamic>>[
      <String, dynamic>{'name': 'Holiday', 'file_count': 2},
    ]);
    final holiday = buildPrivateLocalFolderTree(
      path: 'Holiday',
      files: completeFiles,
    );
    expect((holiday['files'] as List).map((file) => file['id']), <String>[
      'old-nested',
    ]);
    expect(holiday['folders'], <Map<String, dynamic>>[
      <String, dynamic>{'name': 'Beach', 'file_count': 1},
    ]);
    final beach = buildPrivateLocalFolderTree(
      path: 'Holiday/Beach',
      files: completeFiles,
    );
    expect((beach['files'] as List).single['id'], 'private-nested');
    expect(beach['breadcrumbs'], <String>['Holiday', 'Beach']);
  });

  test('invalid or incomplete local inventory fails closed', () {
    expect(
      () =>
          buildPrivateLocalFolderTree(path: '../Holiday', files: completeFiles),
      throwsFormatException,
    );
    expect(
      () => buildPrivateLocalFolderTree(
        path: '',
        files: <Map<String, dynamic>>[completeFiles.first, completeFiles.first],
      ),
      throwsFormatException,
    );
    expect(
      () => buildPrivateLocalFolderTree(
        path: '',
        files: <Map<String, dynamic>>[
          <String, dynamic>{
            'id': 'invalid',
            'file_name': 'bad.txt',
            'relative_path': 'Holiday/../bad.txt',
          },
        ],
      ),
      throwsFormatException,
    );
  });

  final old = <String, dynamic>{
    'path': '',
    'breadcrumbs': <String>[],
    'folders': <Map<String, dynamic>>[
      <String, dynamic>{'name': 'Holiday', 'file_count': 1},
    ],
    'files': <Map<String, dynamic>>[
      <String, dynamic>{'id': 'old-root', 'file_name': 'notes.txt'},
      <String, dynamic>{'id': 'new-v2', 'file_name': null},
    ],
  };
  final ready = <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 'new-v2',
      'file_name': 'beach.jpg',
      'relative_path': 'Holiday/Beach/beach.jpg',
      'v2_ready': true,
    },
    <String, dynamic>{
      'id': 'root-v2',
      'file_name': 'root.pdf',
      'v2_ready': true,
    },
  ];

  test('V2 folder file leaves server root and joins older folder counts', () {
    final root = mergePrivateV2FolderTree(
      path: '',
      serverTree: old,
      privateFiles: ready,
    );
    expect((root['files'] as List).map((f) => f['id']), <String>[
      'old-root',
      'root-v2',
    ]);
    expect(root['folders'], <Map<String, dynamic>>[
      <String, dynamic>{'name': 'Holiday', 'file_count': 2},
    ]);
    final holiday = mergePrivateV2FolderTree(
      path: 'Holiday',
      serverTree: <String, dynamic>{
        'folders': <Object>[],
        'files': <Map<String, dynamic>>[
          <String, dynamic>{'id': 'old-nested', 'file_name': 'old.txt'},
        ],
      },
      privateFiles: ready,
    );
    expect((holiday['files'] as List).map((f) => f['id']), <String>[
      'old-nested',
    ]);
    expect(holiday['folders'], <Map<String, dynamic>>[
      <String, dynamic>{'name': 'Beach', 'file_count': 1},
    ]);
    final beach = mergePrivateV2FolderTree(
      path: 'Holiday/Beach',
      serverTree: null,
      privateFiles: ready,
    );
    expect((beach['files'] as List).single['id'], 'new-v2');
    expect(beach['breadcrumbs'], <String>['Holiday', 'Beach']);
  });
}
