
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';

import '_helpers/responsive_harness.dart';




VaultLoginItem _item(String type, String service) =>
    VaultLoginItem(service: service, itemType: type);


final _bigLoginList = <VaultLoginItem>[
  _item('login', 'Netflix'),
  _item('login', 'American First Credit Union Online Banking Portal'),
  _item('login', 'Bank of America Business Rewards Card Portal — long name'),
  _item('card', 'A Very Long Bank Card Nickname That Wraps'),
  _item('id_document', 'Passport (United States, 2028 Expiry)'),
  _item('secure_note', 'A secure note with a name that is quite long indeed'),
  _item('crypto', 'Ledger backup seed phrase — 24 words'),
  _item('subscription', 'AWS Enterprise'),
  _item('subscription', 'Google Cloud Enterprise Plan (5 Users, US-East)'),
  _item('login', 'Discord'),
];


void _forEachPhone(
  String description,
  Future<void> Function(WidgetTester tester, DeviceProfile device) body, {
  List<DeviceProfile>? devices,
}) {
  final targets = devices ?? DeviceProfiles.allPhones;
  for (final d in targets) {
    testWidgets('$description @ ${d.name}', (tester) async {
      await body(tester, d);
      expectNoOverflow(tester, context: d.name);
    });
  }
}


Widget _wrap(Widget page) => Localizations(
      locale: const Locale('en'),
      delegates: AppLocalizations.localizationsDelegates,
      child: page,
    );

void main() {


  group('LoginsPage — empty state', () {
    _forEachPhone(
      'renders without overflow',
      (tester, device) async {
        await pumpAtDevice(
          tester,
          _wrap(LoginsPage(
            isLoading: false,
            hasLoaded: true,
            logins: const <VaultLoginItem>[],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          )),
          device: device,
        );
      },
      devices: const [
        DeviceProfiles.iphoneSE,
        DeviceProfiles.iphone12,
        DeviceProfiles.iphone14ProMax,
      ],
    );
  });


  group('LoginsPage — mixed items (long names)', () {
    _forEachPhone(
      'renders without overflow',
      (tester, device) async {
        await pumpAtDevice(
          tester,
          _wrap(LoginsPage(
            isLoading: false,
            hasLoaded: true,
            logins: _bigLoginList,
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          )),
          device: device,
        );
      },
      devices: const [
        DeviceProfiles.iphoneSE,
        DeviceProfiles.iphone12,
        DeviceProfiles.iphone14ProMax,
      ],
    );
  });


  group('LoginsPage — loading state', () {
    _forEachPhone(
      'renders without overflow',
      (tester, device) async {
        await pumpAtDevice(
          tester,
          _wrap(LoginsPage(
            isLoading: true,
            hasLoaded: false,
            logins: const <VaultLoginItem>[],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          )),
          device: device,
          settle: false,
        );
      },
      devices: const [
        DeviceProfiles.iphoneSE,
        DeviceProfiles.iphone12,
        DeviceProfiles.iphone14ProMax,
      ],
    );
  });


  group('LoginsPage — error state', () {
    _forEachPhone(
      'renders without overflow',
      (tester, device) async {
        await pumpAtDevice(
          tester,
          _wrap(LoginsPage(
            isLoading: false,
            hasLoaded: true,
            error:
                'Could not load your logins. Check your connection and try again with a very long error message.',
            logins: const <VaultLoginItem>[],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          )),
          device: device,
        );
      },
      devices: const [
        DeviceProfiles.iphoneSE,
        DeviceProfiles.iphone12,
        DeviceProfiles.iphone14ProMax,
      ],
    );
  });


  group('HelpCenterPage — public mode', () {
    _forEachPhone(
      'renders without overflow',
      (tester, device) async {
        await pumpAtDevice(
          tester,
          _wrap(const HelpCenterPage(mode: HelpCenterMode.public)),
          device: device,
        );
      },
      devices: const [
        DeviceProfiles.iphoneSE,
        DeviceProfiles.iphone12,
        DeviceProfiles.iphone14ProMax,
      ],
    );
  });


  group('HelpCenterPage — signed-in mode', () {
    _forEachPhone(
      'renders without overflow',
      (tester, device) async {
        await pumpAtDevice(
          tester,
          _wrap(const HelpCenterPage(mode: HelpCenterMode.signedIn)),
          device: device,
        );
      },
      devices: const [
        DeviceProfiles.iphoneSE,
        DeviceProfiles.iphone12,
        DeviceProfiles.iphone14ProMax,
      ],
    );
  });
}
