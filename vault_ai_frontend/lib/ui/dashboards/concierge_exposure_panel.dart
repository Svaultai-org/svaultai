import 'dart:async';

import 'package:flutter/material.dart';

import '../../services/concierge_exposure.dart';
import '../tokens.dart';
import 'concierge_private_dialog.dart';

class ConciergeExposurePanel extends StatefulWidget {
  final ConciergeExposureBindings bindings;
  const ConciergeExposurePanel({super.key, required this.bindings});
  @override
  State<ConciergeExposurePanel> createState() => _ConciergeExposurePanelState();
}

class _ConciergeExposurePanelState extends State<ConciergeExposurePanel> {
  late ConciergeExposureController controller;
  Route<dynamic>? _privateDialog;

  Future<T?> _showPrivateDialog<T>(ConciergeAccessLease access,
      Widget Function(BuildContext) builder) async {
    access.assertCurrent();
    Route<T>? owned;
    try {
      return await showConciergeLeaseDialog<T>(
          context: context,
          sessionChanges: widget.bindings.accessChanges ?? controller,
          access: access,
          builder: builder,
          onRouteCreated: (route) {
            owned = route;
            _privateDialog = route;
          });
    } finally {
      if (identical(_privateDialog, owned)) _privateDialog = null;
    }
  }

  void _closePrivateDialog() {
    final route = _privateDialog;
    _privateDialog = null;
    if (route == null) return;
    // An owned route, not an arbitrary top route. Defer Navigator mutation
    // out of page rebuild/unmount, then remove even if another route is above it.
    scheduleMicrotask(() {
      final navigator = route.navigator;
      if (navigator != null && route.isActive) navigator.removeRoute(route);
    });
  }

  @override
  void initState() {
    super.initState();
    _createController();
  }

  void _createController() {
    controller = ConciergeExposureController(widget.bindings)
      ..addListener(_changed);
    controller.hydrate();
  }

  void _changed() {
    if (!mounted) return;
    if (!widget.bindings.captureAccess().isCurrent) {
      _closePrivateDialog();
      if (controller.passwordStatus != 'locked') controller.lock();
      return;
    }
    setState(() {});
  }

  @override
  void didUpdateWidget(covariant ConciergeExposurePanel old) {
    super.didUpdateWidget(old);
    if (!identical(old.bindings, widget.bindings)) {
      _closePrivateDialog();
      controller.removeListener(_changed);
      controller.dispose();
      _createController();
    }
  }

  @override
  void dispose() {
    _closePrivateDialog();
    controller.removeListener(_changed);
    controller.dispose();
    super.dispose();
  }

  String _status(String value) => switch (value) {
        'checked' => 'Checked against known data',
        'partial' => 'Incomplete — some checks unavailable',
        'unavailable' => 'Unavailable — not confirmed clear',
        'provider_not_configured' ||
        'not_configured' =>
          'Provider not configured',
        'provider_disabled' || 'disabled' => 'Provider disabled',
        'provider_plan_unavailable' ||
        'unsupported_plan' =>
          'Provider plan unavailable',
        'rate_limited' => 'Rate limited — try again later',
        'unsupported_domain' => 'No provider-verified email domain available',
        'no_eligible_passwords' => 'No eligible encrypted passwords',
        'not_selected' => 'No email addresses selected',
        'off' => 'Off',
        'locked' => 'Paused — unlock your vault',
        _ => 'Not checked',
      };
  String _time(DateTime? value) => value == null
      ? 'Never'
      : '${value.toLocal().toString().split('.').first} (local time)';

  Future<void> _manage() async {
    final access = widget.bindings.captureAccess();
    try {
      access.assertCurrent();
      final choices = await controller.emailChoices();
      access.assertCurrent();
      if (!mounted) return;
      var enabled = controller.consent.enabled;
      var automatic = controller.consent.checkOnUnlock;
      var background = controller.consent.backgroundEmails;
      var stealer = controller.consent.stealerLogs;
      final selected = Set<String>.from(controller.consent.approvedEmails);
      final emails = choices.map((e) => e.email!).toSet().toList()..sort();
      final result = await _showPrivateDialog<ConciergeConsent>(
          access,
          (ctx) => StatefulBuilder(
              builder: (ctx, update) => AlertDialog(
                    title: const Text('Choose your privacy checks'),
                    content: SizedBox(
                        width: 520,
                        child: SingleChildScrollView(
                            child: Column(
                                mainAxisSize: MainAxisSize.min,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                              const Text(
                                  'These checks are optional. We inspect only eligible, client-encrypted saved logins after you unlock your vault.'),
                              CheckboxListTile(
                                  contentPadding: EdgeInsets.zero,
                                  value: enabled,
                                  title: const Text(
                                      'Allow password exposure checks'),
                                  subtitle: const Text(
                                      'Only the first 5 characters of a password hash go to Have I Been Pwned. Your password and full hash stay on this device.'),
                                  onChanged: (v) =>
                                      update(() => enabled = v == true)),
                              CheckboxListTile(
                                  contentPadding: EdgeInsets.zero,
                                  value: automatic,
                                  title:
                                      const Text('Check when Concierge opens'),
                                  subtitle: const Text(
                                      'At most once every 24 hours, only while the vault is unlocked. This is not continuous background password scanning.'),
                                  onChanged: enabled
                                      ? (v) =>
                                          update(() => automatic = v == true)
                                      : null),
                              const Divider(),
                              const Text('Email exposure checks',
                                  style:
                                      TextStyle(fontWeight: FontWeight.w700)),
                              const SizedBox(height: 8),
                              const Text(
                                  'Select only addresses you own or are authorized to check. One-time checks send a 6-character hash prefix, not your full email, to our breach provider.'),
                              if (!controller.capabilities.emailRange)
                                Padding(
                                    padding:
                                        const EdgeInsets.symmetric(vertical: 8),
                                    child: Text(
                                        'Email checks cannot run: ${_status(controller.emailStatus)}.')),
                              if (emails.isEmpty)
                                const Padding(
                                    padding: EdgeInsets.symmetric(vertical: 8),
                                    child: Text(
                                        'No email addresses found in eligible encrypted saved logins.')),
                              for (final email in emails)
                                CheckboxListTile(
                                    contentPadding: EdgeInsets.zero,
                                    value: selected.contains(email),
                                    title: Text(email),
                                    onChanged: enabled &&
                                            controller.capabilities.emailRange
                                        ? (v) => update(() {
                                              if (v == true) {
                                                selected.add(email);
                                              } else {
                                                selected.remove(email);
                                              }
                                            })
                                        : null),
                              const Divider(),
                              CheckboxListTile(
                                  contentPadding: EdgeInsets.zero,
                                  value: background,
                                  title: const Text(
                                      'Authorize background email monitoring'),
                                  subtitle: const Text(
                                      'Separate permission: selected full email addresses will be sent to SVaultAI and Have I Been Pwned. SVaultAI’s monitoring service can read these approved addresses; they are encrypted with its operational key, not your vault-only key, so checks can run while your vault is locked. You can withdraw this permission here.'),
                                  onChanged: enabled &&
                                          selected.isNotEmpty &&
                                          controller
                                              .capabilities.emailMonitoring
                                      ? (v) => update(() {
                                            background = v == true;
                                            if (!background) stealer = false;
                                          })
                                      : null),
                              CheckboxListTile(
                                  contentPadding: EdgeInsets.zero,
                                  value: stealer,
                                  title: const Text(
                                      'Include supported stealer-log checks'),
                                  subtitle: Text(controller
                                          .capabilities.stealerLogs
                                      ? 'Requires separate full-email disclosure permission and a provider-verified email domain. Unsupported addresses will not be queried.'
                                      : '${_status(controller.capabilities.stealerStatus == 'not_configured' ? 'provider_not_configured' : controller.capabilities.stealerStatus)}. This is not a comprehensive dark-web search.'),
                                  onChanged: background &&
                                          controller.capabilities.stealerLogs
                                      ? (v) => update(() => stealer = v == true)
                                      : null),
                            ]))),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(ctx),
                          child: const Text('Cancel')),
                      FilledButton(
                          onPressed: () => Navigator.pop(
                              ctx,
                              ConciergeConsent(
                                  enabled: enabled,
                                  checkOnUnlock: enabled && automatic,
                                  approvedEmails: enabled ? selected : {},
                                  backgroundEmails: enabled && background,
                                  stealerLogs:
                                      enabled && background && stealer)),
                          child: const Text('Save choices'))
                    ],
                  )));
      access.assertCurrent();
      if (result != null) await controller.configure(result);
    } catch (_) {
      if (!mounted || !access.isCurrent) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
              'Could not load or save check settings. Please try again.')));
    }
  }

  Future<void> _review(ConciergeFinding finding) async {
    final access = widget.bindings.captureAccess();
    if (!access.isCurrent || widget.bindings.onUpdateLogin == null) return;
    final proceed = await _showPrivateDialog<bool>(
        access,
        (ctx) => AlertDialog(
                title: Text('Review ${finding.title}'),
                content: const Text(
                    'Change a compromised or reused password on the original service first. Saving a different password here updates only your encrypted vault copy; it does not change the password on that service. Then return and recheck.'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(ctx, false),
                      child: const Text('Cancel')),
                  FilledButton(
                      onPressed: () => Navigator.pop(ctx, true),
                      child: const Text('Update vault copy'))
                ]));
    if (!mounted || !access.isCurrent || proceed != true) return;
    widget.bindings.onUpdateLogin!(
        finding.loginId, finding.title, finding.itemType);
  }

  String _finding(ConciergeFinding finding) => switch (finding.kind) {
        'weak' =>
          'Short or common password — choose a longer, unique password.',
        'reused' =>
          'This password is reused across ${finding.count} saved logins.',
        'pwned' =>
          'This password appears ${finding.count} times in known exposed-password data.',
        'email_breach' =>
          'Saved email appears in a known breach: ${finding.detail ?? 'Unknown service'}. This does not prove your current saved password was exposed.',
        'email_monitor_breach' =>
          'Authorized background email check found a known breach: ${finding.detail ?? 'Unknown service'}. This does not prove your current saved password was exposed.',
        'stealer_domain' =>
          'Saved email appeared beside ${finding.detail ?? 'a website'} in stealer logs. It does not prove this saved password was exposed.',
        _ => 'Review this saved login.',
      };

  @override
  Widget build(BuildContext context) {
    if (!widget.bindings.captureAccess().isCurrent) {
      _closePrivateDialog();
      return const SizedBox.shrink();
    }
    final busy = controller.loading || controller.checking;
    return Container(
        key: const Key('concierge_exposure_panel'),
        padding: const EdgeInsets.all(VaultSpacing.lg),
        margin: const EdgeInsets.only(bottom: VaultSpacing.lg),
        decoration: BoxDecoration(
            color: VaultColors.surface,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: VaultColors.borderSubtle)),
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('Login exposure checks',
              style: TextStyle(fontWeight: FontWeight.w700, fontSize: 20)),
          const SizedBox(height: 8),
          const Text(
              'Optional, privacy-conscious checks for eligible encrypted saved logins. Results cover known breach data, not the entire internet or dark web.'),
          const SizedBox(height: 16),
          Wrap(spacing: 12, runSpacing: 8, children: [
            FilledButton.icon(
                onPressed: busy ||
                        !controller.consent.enabled ||
                        !controller.stateReady
                    ? null
                    : controller.checkNow,
                icon: const Icon(Icons.shield_outlined),
                label: Text(controller.checking ? 'Checking…' : 'Check now')),
            OutlinedButton.icon(
                onPressed: busy || !controller.stateReady ? null : _manage,
                icon: const Icon(Icons.tune),
                label: const Text('Manage checks')),
            if (controller.revocationPending)
              OutlinedButton(
                  onPressed: busy ? null : controller.retryRevocation,
                  child: const Text('Retry consent withdrawal')),
          ]),
          if (busy)
            const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: LinearProgressIndicator()),
          const SizedBox(height: 12),
          Text(controller.consent.enabled
              ? 'Checks: enabled with your permission'
              : 'Checks: off — opt in to begin'),
          Text('Password status: ${_status(controller.passwordStatus)}'),
          Text('Email status: ${_status(controller.emailStatus)}'),
          Text(
              'Last successful password check: ${_time(controller.lastPasswordCheckAt)}'),
          Text(
              'Last successful email check: ${_time(controller.lastEmailCheckAt)}'),
          if (controller.lastAttemptAt != null)
            Text('Last attempt: ${_time(controller.lastAttemptAt)}'),
          Text(
              '${controller.checkedPasswords} passwords checked; ${controller.unavailablePasswords} unavailable; ${controller.unreadableRecords} encrypted records could not be read.'),
          if (controller.consent.checkOnUnlock)
            const Text(
                'Automatic checks: when Concierge opens, while unlocked.'),
          if (controller.consent.backgroundEmails)
            Text(controller.revocationPending
                ? 'Background monitoring: consent withdrawal pending.'
                : 'Background monitoring: ${controller.monitorRows.isEmpty ? 'awaiting provider status' : 'see latest provider status below'}.'),
          if (controller.issue != null)
            Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(controller.issue!,
                    key: const Key('concierge_exposure_issue'),
                    style: const TextStyle(color: VaultColors.severityWarn))),
          for (final finding in controller.findings)
            Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(finding.title,
                          style: const TextStyle(fontWeight: FontWeight.w700)),
                      Text(_finding(finding)),
                      Text(
                          'Finding checked: ${_time(finding.checkedAt)}${finding.stale ? ' • Earlier result — latest check unavailable' : ''}'),
                      if (widget.bindings.onUpdateLogin != null)
                        TextButton(
                            onPressed: busy ? null : () => _review(finding),
                            child: const Text('Review and update saved login')),
                    ])),
          if (controller.passwordStatus == 'checked' &&
              controller.findings.isEmpty)
            const Padding(
                padding: EdgeInsets.only(top: 12),
                child: Text(
                    'No password findings in the completed password check. Email coverage is shown separately. This is not a guarantee that an account or password is safe.')),
          for (final row in controller.monitorRows)
            Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                    'Background email check: ${row['status'] ?? 'not_checked'} • Last successful check: ${row['successful_at'] ?? 'Never'}${row['status'] == 'unavailable' ? ' • Earlier findings may be out of date' : ''}${row['error_code'] == 'source_item_no_longer_available' ? ' • The linked saved login was removed. Withdraw and re-enable background checks to choose a current login.' : ''}')),
          const Divider(height: 32),
          const Text(
              'Files and full dark-web scanning: not supported. We do not upload your files, images, documents, seed phrases or private keys to a breach service.'),
          const SizedBox(height: 8),
          const SelectableText(
              'Known breach data: Have I Been Pwned • https://haveibeenpwned.com'),
        ]));
  }
}
