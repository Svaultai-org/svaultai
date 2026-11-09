import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/private_v2_folder_tree.dart';

void main() {
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
    expect((root['files'] as List).map((f) => f['id']),
        <String>['old-root', 'root-v2']);
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
    expect(
        (holiday['files'] as List).map((f) => f['id']), <String>['old-nested']);
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
