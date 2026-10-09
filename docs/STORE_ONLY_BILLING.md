# Apple and Google Play only

Paid storage comes only from verified Apple App Store or Google Play
subscriptions. Web accounts keep included storage and can use a valid store
subscription belonging to the same account. Card checkout and portal routes,
Stripe SDK and cancellation calls, keys in example configuration, and legacy
paid-storage fallback have been removed.

Historical billing tables/migrations/events are preserved. Migration 0046
rebuilds storage-provider ownership from verified unexpired store records; it
does not delete vault data. Security redaction patterns and chat support for
credentials named "Stripe" are unrelated and intentionally remain.

## Safe production retirement

1. Before changing production, review existing recurring card subscriptions
   in the merchant dashboard. Close renewal there and verify that no future
   charge remains scheduled. Do not finalize or charge old draft invoices.
   Code removal alone cannot cancel a recurring provider subscription.
2. Retain required accounting/payment history. Export a protected database
   backup and verify that Apple/Google configuration is present without
   printing credentials.
3. Deploy the backend with migration 0046 and the matching web bundle.
   Remove retired card credentials/URLs from the real environment and recreate
   the container; editing an environment file alone does not remove existing
   container credentials. Disable the obsolete merchant webhook, then revoke
   its old API keys. Never log key values.
4. Confirm health, release identity, no registered card routes, free legacy
   accounts, and verified store entitlement. Quota reduction must not delete
   existing files, memories, logins or wallet records.
5. Test Apple purchase/restore, Google verification/restore, expiry/revocation,
   duplicate notifications and ownership conflicts using authorized store
   test environments. Release a new iOS/Android binary for client changes;
   deploying web does not update an installed app.

Do not mark this cutover live until the recurring-provider retirement,
credential removal and deployment checks are complete.
