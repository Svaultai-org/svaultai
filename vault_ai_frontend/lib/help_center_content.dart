class FaqCategory {
  final String id;
  final String label;
  const FaqCategory({required this.id, required this.label});
}

class FaqEntry {
  final String id;
  final String category;
  final String question;
  final String answer;
  const FaqEntry(
      {required this.id,
      required this.category,
      required this.question,
      required this.answer});
}

const List<FaqCategory> kFaqCategories = <FaqCategory>[
  FaqCategory(id: 'getting_started', label: 'About SVaultAI'),
  FaqCategory(id: 'privacy', label: 'Privacy and Encryption'),
  FaqCategory(id: 'security', label: 'Vault Access and PIN Security'),
  FaqCategory(id: 'files', label: 'Files, Photos, Videos, and Voice Notes'),
  FaqCategory(id: 'credentials', label: 'Saved Logins and Credentials'),
  FaqCategory(id: 'ai', label: 'Personal Memories and Private AI'),
  FaqCategory(id: 'devices', label: 'Devices and Account Security'),
  FaqCategory(id: 'crypto', label: 'Crypto Wallet Privacy'),
  FaqCategory(id: 'inheritance', label: 'Inheritance and Beneficiaries'),
  FaqCategory(id: 'storage', label: 'Subscription and Inactivity'),
  FaqCategory(id: 'deletion', label: 'Deleting Files and Vaults'),
  FaqCategory(id: 'safety', label: 'Safety and Best Practices'),
];

const List<FaqEntry> kFaqEntries = <FaqEntry>[
  FaqEntry(
      id: 'what-is-vaultai',
      category: 'getting_started',
      question: 'What is SVaultAI?',
      answer:
          'SVaultAI is a privacy-focused digital vault for documents, media, credentials, personal memories, and supported digital assets. It combines encrypted storage with tools for organizing and finding your own information.'),
  FaqEntry(
      id: 'what-can-i-save',
      category: 'getting_started',
      question: 'What can I protect in SVaultAI?',
      answer:
          'You can protect supported files, photos, videos, audio, saved logins, secure notes, personal memories, identity documents, and locally protected wallet secrets. Features and file limits may depend on your platform and plan.'),
  FaqEntry(
      id: 'create-vault',
      category: 'getting_started',
      question: 'How do I create and unlock a vault?',
      answer:
          'Create an account, choose a vault name, and set a PIN. On a trusted device, enter the PIN when asked to unlock protected features. Keep the PIN and every recovery method you configure somewhere safe.'),
  FaqEntry(
      id: 'local-vs-backend',
      category: 'getting_started',
      question: 'How does SVaultAI protect my information?',
      answer:
          'Your authorized device protects access to readable vault content. SVaultAI stores encrypted vault information and only the limited service records needed for subscriptions, storage, trusted devices, security, account status, and deletion eligibility.'),
  FaqEntry(
      id: 'employees-see-vault',
      category: 'privacy',
      question: 'Can SVaultAI employees see what is inside my vault?',
      answer:
          'SVaultAI staff cannot open and read protected vault contents such as encrypted files, credential values, personal memories, and locally protected wallet secrets. Limited operational metadata remains available to operate and secure the service.'),
  FaqEntry(
      id: 'developers-open-vault',
      category: 'privacy',
      question: 'Can the developers open my vault?',
      answer:
          'No. Developers do not have a universal key that opens a user’s protected content. They may access operational systems under controlled conditions, but the protected content is not available to them in readable form.'),
  FaqEntry(
      id: 'master-key',
      category: 'privacy',
      question: 'Is there a master key or backdoor?',
      answer:
          'SVaultAI does not maintain a master key or customer-support backdoor that can simply unlock every vault.'),
  FaqEntry(
      id: 'see-files',
      category: 'privacy',
      question: 'Can SVaultAI see my files?',
      answer:
          'Stored file bytes and protected file metadata are encrypted. When you request supported analysis, selected content may be processed for that request and may be sent to an AI or media-processing provider; the whole vault is not sent automatically.'),
  FaqEntry(
      id: 'see-credentials',
      category: 'privacy',
      question: 'Can SVaultAI see my saved usernames and passwords?',
      answer:
          'Saved credential values are encrypted. They are not available to staff or support, and secret values are excluded from ordinary AI chat context and masked until you explicitly reveal them.'),
  FaqEntry(
      id: 'read-memories',
      category: 'privacy',
      question: 'Can SVaultAI read my personal memories?',
      answer:
          'Personal memories are stored as protected vault content. The app can decrypt relevant memories for features you request, but staff cannot browse them as readable account data.'),
  FaqEntry(
      id: 'see-vault-name',
      category: 'privacy',
      question: 'Can SVaultAI see my vault name?',
      answer:
          'Private display names and labels are protected as part of the encrypted vault design. SVaultAI still uses an account identifier to find the correct encrypted vault when you sign in.'),
  FaqEntry(
      id: 'operational-metadata',
      category: 'privacy',
      question: 'What information can SVaultAI see?',
      answer:
          'SVaultAI keeps limited operational records such as account status, subscription state, storage amount, trusted devices, security status, system errors, and deletion eligibility. These records do not allow staff to open and read protected vault contents.'),
  FaqEntry(
      id: 'know-vault-exists',
      category: 'privacy',
      question: 'Does SVaultAI know that I have a vault?',
      answer:
          'Yes. The service must know that an account and vault record exist so it can authenticate you, store encrypted data, enforce storage limits, bill the correct plan, and apply retention rules.'),
  FaqEntry(
      id: 'discover-vault',
      category: 'privacy',
      question: 'Can another user discover my vault?',
      answer:
          'SVaultAI does not provide a public vault directory. Another person may still know or guess a sign-in name, but that does not give them the PIN, trusted-device status, keys, or access to protected content.'),
  FaqEntry(
      id: 'support-reset-content',
      category: 'privacy',
      question: 'Can customer support reset or reveal my vault contents?',
      answer:
          'No. Support cannot reveal protected content or bypass its encryption. Support may help with billing, service access, or device records, but cannot provide a decrypted copy of your vault.'),
  FaqEntry(
      id: 'legal-decrypt-request',
      category: 'privacy',
      question:
          'Can the government or another company ask SVaultAI to decrypt my vault?',
      answer:
          'They may make a lawful request for information SVaultAI holds. SVaultAI can only provide data available to it; it does not have a master key that decrypts protected vault content. Operational, billing, or public blockchain records may still be available.'),
  FaqEntry(
      id: 'server-breach',
      category: 'privacy',
      question: 'What happens if SVaultAI’s servers are breached?',
      answer:
          'An attacker could obtain encrypted content and some operational metadata. Encryption reduces the exposure of protected content, but no service can promise that a breach is impossible. SVaultAI should investigate, contain, and notify as required.'),
  FaqEntry(
      id: 'upload-encryption',
      category: 'privacy',
      question: 'Is my data encrypted while being uploaded?',
      answer:
          'Yes. Connections use transport encryption, and supported vault data is encrypted before or as part of protected storage. This protects data in transit as well as the stored ciphertext.'),
  FaqEntry(
      id: 'file-separate-encryption',
      category: 'privacy',
      question: 'Is every file encrypted separately?',
      answer:
          'Yes. File data is stored in independently authenticated encrypted chunks, so one file is not protected by simply hiding an entire storage folder behind a single server password.'),
  FaqEntry(
      id: 'file-names-encrypted',
      category: 'privacy',
      question: 'Are file names encrypted?',
      answer:
          'Yes. Private file names and saved titles are protected according to SVaultAI’s encrypted metadata design.'),
  FaqEntry(
      id: 'folder-labels-encrypted',
      category: 'privacy',
      question: 'Are folder names and vault labels encrypted?',
      answer:
          'Yes. Private folder names, display labels, and supported metadata are protected according to SVaultAI’s encrypted metadata design.'),
  FaqEntry(
      id: 'ai-training',
      category: 'privacy',
      question: 'Can SVaultAI use my private data to train AI models?',
      answer:
          'SVaultAI does not use private vault content to train public AI models. Selected content may be sent to a configured AI provider to fulfill a request; provider handling is governed by the service’s processor terms and configuration.'),
  FaqEntry(
      id: 'advertisers',
      category: 'privacy',
      question: 'Is my vault content sold or shared with advertisers?',
      answer:
          'No. SVaultAI does not sell private vault content or use it for advertising. It may share the minimum necessary data with service processors or when legally required.'),
  FaqEntry(
      id: 'ai-provider-access',
      category: 'privacy',
      question: 'Can AI providers see everything inside my vault?',
      answer:
          'No. The app does not send the entire vault automatically. Depending on the feature, prompts, selected excerpts, extracted document text, images, audio, or safe search context may be sent to OpenAI to answer or analyze your request. Credentials and wallet signing secrets are excluded.'),
  FaqEntry(
      id: 'file-types',
      category: 'files',
      question: 'What kinds of files can I store?',
      answer:
          'SVaultAI supports common documents, images, audio, and video that fit your plan and platform limits. Unsupported formats can still be stored when allowed, but preview, search, or analysis may not work.'),
  FaqEntry(
      id: 'media-encrypted',
      category: 'files',
      question: 'Are photos, videos, and voice notes encrypted?',
      answer:
          'Yes. Their stored file data is encrypted. If you ask for transcription, visual analysis, or another AI feature, the selected media may be processed by the configured provider for that request.'),
  FaqEntry(
      id: 'document-answer',
      category: 'files',
      question: 'Can SVaultAI read a document to answer my questions?',
      answer:
          'Yes, when you request it and the format is supported. The service may extract or decrypt relevant text and send selected content to the AI provider to produce the answer.'),
  FaqEntry(
      id: 'encrypted-name-search',
      category: 'files',
      question: 'How does the AI find a file if the file name is encrypted?',
      answer:
          'After you unlock the vault, protected search information can identify relevant items without making file names publicly searchable. The assistant only receives the information needed for your request.'),
  FaqEntry(
      id: 'rename-move',
      category: 'files',
      question: 'Can I rename or move a file?',
      answer:
          'Use the file actions available in your build. Renaming or moving updates protected metadata; it does not change the original file bytes.'),
  FaqEntry(
      id: 'download-original',
      category: 'files',
      question: 'Can I download my original file?',
      answer:
          'Yes. Download retrieves the encrypted data and decrypts it for you on an authorized, unlocked device. Check the downloaded copy before deleting the vault version.'),
  FaqEntry(
      id: 'upload-interrupted',
      category: 'files',
      question: 'What happens if an upload is interrupted?',
      answer:
          'An incomplete upload should not appear as a complete file. Retry after reconnecting; resumable behavior depends on the file size and platform. Do not delete your original until the uploaded file opens correctly.'),
  FaqEntry(
      id: 'deleted-file-recovery',
      category: 'files',
      question: 'Are deleted files recoverable?',
      answer:
          'No user-facing recycle bin is currently provided. Treat file deletion as permanent and keep an independent backup of anything you cannot replace.'),
  FaqEntry(
      id: 'delete-all-copies',
      category: 'files',
      question: 'Does deleting a file remove all copies?',
      answer:
          'The active vault record and stored file data are deleted. Temporary processing data should expire, while encrypted backups and operational logs may age out on separate schedules. Copies you exported and content sent to processors are governed separately.'),
  FaqEntry(
      id: 'export-all',
      category: 'files',
      question: 'Can I export everything from my vault?',
      answer:
          'You can download original files and export supported records where the app provides an export action. A single complete-vault export is not guaranteed in every current build, so verify your important items before deletion.'),
  FaqEntry(
      id: 'logins-encrypted',
      category: 'credentials',
      question: 'Are saved logins encrypted?',
      answer:
          'Yes. Usernames, passwords, and related protected fields are stored as encrypted vault content and are masked by default.'),
  FaqEntry(
      id: 'generated-passwords',
      category: 'credentials',
      question: 'Can SVaultAI see generated passwords?',
      answer:
          'Generated passwords are intended to be created and protected in the client flow. They are not ordinary server metadata and are not included in AI prompts.'),
  FaqEntry(
      id: 'support-credentials',
      category: 'credentials',
      question: 'Can support reveal my credentials?',
      answer:
          'No. Support cannot decrypt or reveal a saved password or other protected credential value.'),
  FaqEntry(
      id: 'personal-memories',
      category: 'credentials',
      question: 'What are personal memories?',
      answer:
          'Personal memories are facts or notes you intentionally save so the assistant can give more useful answers later, such as preferences, dates, or context about people and projects.'),
  FaqEntry(
      id: 'memory-without-save',
      category: 'credentials',
      question: 'Can the AI remember something without saving it?',
      answer:
          'It can use the current conversation context temporarily. It should not create a durable personal memory unless the feature identifies and saves one under the product’s memory rules.'),
  FaqEntry(
      id: 'change-forget-memory',
      category: 'credentials',
      question: 'How do I change or forget a saved memory?',
      answer:
          'Open the memories area or ask the assistant to show the relevant memory, then edit or delete it. Confirm the result if the information is sensitive or important.'),
  FaqEntry(
      id: 'save-everything',
      category: 'credentials',
      question: 'Does the AI permanently save everything I say?',
      answer:
          'No. Conversation processing and durable memories are different. Only selected information is stored as a memory; security and operational logs may retain limited event data without storing the full protected conversation.'),
  FaqEntry(
      id: 'cross-user-memory',
      category: 'credentials',
      question: 'Can one user’s memories appear in another user’s vault?',
      answer:
          'They should not. Vault records are scoped to their owner. If you see information that appears to belong to someone else, stop using the feature and contact support immediately.'),
  FaqEntry(
      id: 'assistant-capabilities',
      category: 'ai',
      question: 'What can the SVaultAI assistant do?',
      answer:
          'It can help find and summarize supported vault content, organize items, recall saved memories, explain account features, and prepare supported actions. Availability depends on platform, plan, and file type.'),
  FaqEntry(
      id: 'ai-unrestricted',
      category: 'ai',
      question: 'Does the AI have unrestricted access to my vault?',
      answer:
          'No. It receives context selected for the request and is subject to vault scope, unlock state, secret masking, and action-confirmation rules.'),
  FaqEntry(
      id: 'ai-entire-vault',
      category: 'ai',
      question: 'Does the AI send my entire vault to an external provider?',
      answer:
          'No. Requests can include the prompt and selected excerpts or media needed for the task, but should not upload the entire vault as background context.'),
  FaqEntry(
      id: 'ai-encrypted-search',
      category: 'ai',
      question: 'How does the AI search encrypted information?',
      answer:
          'Protected indexes and client-authorized context identify relevant items. Only the information needed for the requested answer is decrypted or selected for AI processing; opaque record identifiers can be used for the rest.'),
  FaqEntry(
      id: 'ai-actions-approval',
      category: 'ai',
      question: 'Can the AI take actions without my approval?',
      answer:
          'It may perform low-risk read or search steps needed to answer you. Sensitive, destructive, or financial actions require the product’s confirmation and authorization checks.'),
  FaqEntry(
      id: 'ai-destructive',
      category: 'ai',
      question:
          'Can the AI delete, move, or send something without confirmation?',
      answer:
          'It should not delete vault data or send crypto without explicit confirmation and the required security checks. Review every action summary before approving it.'),
  FaqEntry(
      id: 'public-model-training',
      category: 'ai',
      question: 'Does SVaultAI use my vault to train public AI models?',
      answer:
          'No. Private vault content is used to provide requested features, not to train public models.'),
  FaqEntry(
      id: 'ai-not-found',
      category: 'ai',
      question: 'What happens when the AI cannot find something?',
      answer:
          'It should say that it could not find a reliable match. Try the exact file, service, person, or date, and check that the item finished uploading or indexing.'),
  FaqEntry(
      id: 'ai-mistakes',
      category: 'ai',
      question: 'Can the AI make mistakes?',
      answer:
          'Yes. AI can misunderstand a request, miss an item, or produce an incorrect summary. Open the source item and verify important details.'),
  FaqEntry(
      id: 'verify-advice',
      category: 'ai',
      question: 'How should I verify important financial or legal information?',
      answer:
          'Treat AI output as a starting point, not professional advice. Check the original document and transaction details and consult a qualified professional where the consequences matter.'),
  FaqEntry(
      id: 'forgot-pin',
      category: 'security',
      question: 'What happens if I forget my PIN?',
      answer:
          'SVaultAI cannot recover a forgotten PIN or unlock the existing vault. Losing the PIN makes its protected data permanently inaccessible. Account, email, device, billing, or support changes cannot recreate the vault decryption key.'),
  FaqEntry(
      id: 'reset-pin',
      category: 'security',
      question: 'Can SVaultAI reset my PIN?',
      answer:
          'No. Support and administrators cannot reset a forgotten PIN and restore the existing encrypted vault. A user who knows the current PIN may use an authorized PIN-change flow, but account recovery is not vault-key recovery.'),
  FaqEntry(
      id: 'why-no-support-recovery',
      category: 'security',
      question: 'Why can’t support recover my vault for me?',
      answer:
          'Giving support a universal recovery ability would create a backdoor into every vault. The encryption design intentionally gives no creator, operator, administrator, or support agent a secret that can replace your PIN.'),
  FaqEntry(
      id: 'key-storage',
      category: 'security',
      question: 'Where are my encryption keys stored?',
      answer:
          'Unlock and private key material is kept in protected client storage or derived locally. The backend stores encrypted key envelopes and public or opaque values needed for synchronization, not a plaintext master key that staff can use.'),
  FaqEntry(
      id: 'pin-server',
      category: 'security',
      question: 'Is my PIN sent to the server?',
      answer:
          'No. Authentication is designed so that the plaintext PIN is not exposed as a normal readable password. Signing in proves you are authorized without giving staff a vault-opening secret.'),
  FaqEntry(
      id: 'new-phone',
      category: 'security',
      question: 'What happens when I use a new phone?',
      answer:
          'You must authenticate and complete the device-approval or recovery flow. A new phone does not automatically inherit an old device’s unlocked key state.'),
  FaqEntry(
      id: 'lost-phone',
      category: 'security',
      question: 'What happens if I lose my phone?',
      answer:
          'From another authorized device, revoke the lost device and review security activity. Protect your email and mobile account too. If the lost phone was your only source of required local key material, recovery may not be possible.'),
  FaqEntry(
      id: 'logout-device',
      category: 'security',
      question: 'Does logging out remove access from that device?',
      answer:
          'Logging out ends the current app session and clears active unlock state. Revoke the device as well if you no longer control it; logging out alone is not a substitute for remote revocation.'),
  FaqEntry(
      id: 'trusted-devices',
      category: 'security',
      question: 'Can I see and remove trusted devices?',
      answer:
          'Yes. Use the Security area to review trusted devices and revoke any you do not recognize or no longer use.'),
  FaqEntry(
      id: 'reinstall-session',
      category: 'security',
      question: 'Does reinstalling the app restore an old session?',
      answer:
          'It should not restore an authenticated session merely because the app was reinstalled. You will need to sign in again, and local secure storage behavior can vary by platform.'),
  FaqEntry(
      id: 'biometrics-pin',
      category: 'security',
      question: 'Can Face ID or biometrics replace my vault PIN?',
      answer:
          'Biometrics may unlock locally cached access where supported, but they do not replace the vault PIN or recovery material. You may still need the PIN after logout, reinstall, device change, or a sensitive action.'),
  FaqEntry(
      id: 'wrong-pin-attempts',
      category: 'security',
      question: 'How many wrong PIN attempts are allowed?',
      answer:
          'Attempt limits and delays can vary by authentication path and security policy. Repeated failures are rate-limited and may temporarily block attempts; SVaultAI does not promise a fixed universal number in this Help Center.'),
  FaqEntry(
      id: 'wallet-custody',
      category: 'crypto',
      question: 'Is the SVaultAI wallet custodial or non-custodial?',
      answer:
          'It is non-custodial. Transactions are signed with key material protected on your device; SVaultAI does not hold funds on your behalf like an exchange.'),
  FaqEntry(
      id: 'wallet-key-control',
      category: 'crypto',
      question: 'Who controls the wallet keys?',
      answer:
          'You control the wallet through the locally protected signing keys and your authorized device. Anyone who obtains your recovery or signing secret may control the funds.'),
  FaqEntry(
      id: 'freeze-move-crypto',
      category: 'crypto',
      question: 'Can SVaultAI freeze or move my crypto?',
      answer:
          'SVaultAI cannot sign a transaction without your locally protected key. A network, token issuer, smart contract, or legal restriction may still affect a particular asset independently of SVaultAI.'),
  FaqEntry(
      id: 'wallet-recovery',
      category: 'crypto',
      question: 'Can SVaultAI recover my wallet if I lose access?',
      answer:
          'Recovery is not guaranteed. If you lose the device, PIN, and any required backup or recovery material, SVaultAI cannot recreate the private signing key.'),
  FaqEntry(
      id: 'wallet-keys-server',
      category: 'crypto',
      question: 'Are wallet private keys stored on the server?',
      answer:
          'Wallet secret material may be synchronized only as vault ciphertext. The server should not receive a plaintext private signing key or a form staff can use to sign transactions.'),
  FaqEntry(
      id: 'wallet-public-data',
      category: 'crypto',
      question: 'Does SVaultAI know my wallet balance and transaction history?',
      answer:
          'Public addresses and transactions are visible on their networks. SVaultAI also processes wallet and transaction metadata needed to show balances, estimate fees, prevent duplicate sends, and track status. Privacy-oriented networks may work differently.'),
  FaqEntry(
      id: 'network-fees',
      category: 'crypto',
      question: 'Why are network fees required?',
      answer:
          'Blockchain networks charge fees to process transactions. Fees go to network validators or miners, not to SVaultAI unless a separate fee is clearly disclosed.'),
  FaqEntry(
      id: 'maximum-send',
      category: 'crypto',
      question: 'How is the maximum send amount calculated?',
      answer:
          'The app subtracts an estimated network fee and any required reserve from the spendable balance. Token transfers may also require the network’s native asset for fees.'),
  FaqEntry(
      id: 'fee-change',
      category: 'crypto',
      question: 'What happens if the fee changes before signing?',
      answer:
          'The transaction may be rebuilt with a new estimate or fail validation. Review the final amount and fee shown immediately before approval.'),
  FaqEntry(
      id: 'transaction-reversal',
      category: 'crypto',
      question: 'Can a transaction be reversed?',
      answer:
          'Usually not after a valid transaction is confirmed on-chain. Check the network, asset, address, amount, and fee before signing.'),
  FaqEntry(
      id: 'after-wallet-pin',
      category: 'crypto',
      question: 'What happens after I enter my PIN?',
      answer:
          'The PIN unlocks local signing capability for the authorized flow. You still review and confirm the transaction; entering the PIN alone should not send funds.'),
  FaqEntry(
      id: 'broadcast-approval',
      category: 'crypto',
      question: 'Can SVaultAI broadcast a transaction without my approval?',
      answer:
          'SVaultAI should only receive a locally signed transaction after the required review and confirmation. It cannot create your signature without the local key.'),
  FaqEntry(
      id: 'uncertain-status',
      category: 'crypto',
      question: 'What should I do if a transaction status is uncertain?',
      answer:
          'Do not immediately send again. Copy the transaction hash and check a reputable explorer for the correct network, then refresh the wallet or contact support.'),
  FaqEntry(
      id: 'supported-assets',
      category: 'crypto',
      question: 'Which networks and assets are supported?',
      answer:
          'The current build supports ETH, Ethereum USDT and USDC, SOL, TRON USDT, and receive-only XMR. Availability can change by platform and release; always use the network label shown in the app.'),
  FaqEntry(
      id: 'not-exchange',
      category: 'crypto',
      question: 'Is SVaultAI an exchange or investment service?',
      answer:
          'No. SVaultAI does not provide investment advice and is not an exchange. It does not promise returns or reverse blockchain transactions.'),
  FaqEntry(
      id: 'inheritance-feature',
      category: 'inheritance',
      question: 'What is the inheritance feature?',
      answer:
          'It lets a vault owner designate a beneficiary and prepare protected information for a controlled future release. It is a technical access feature, not a will or substitute for legal estate planning.'),
  FaqEntry(
      id: 'beneficiary-alive-access',
      category: 'inheritance',
      question: 'Can my beneficiary access my vault while I am alive?',
      answer:
          'Not through the normal inheritance flow. Linking a beneficiary does not grant immediate access; the configured request, waiting, authorization, and release steps must complete.'),
  FaqEntry(
      id: 'beneficiary-visible-info',
      category: 'inheritance',
      question: 'What information can a beneficiary see?',
      answer:
          'Before release, a beneficiary sees limited pairing and status information, not the owner’s readable vault content. After an authorized transfer, only the prepared and re-encrypted inheritance material should become available.'),
  FaqEntry(
      id: 'choose-beneficiary',
      category: 'inheritance',
      question: 'Can SVaultAI choose or change my beneficiary?',
      answer:
          'No. The vault owner chooses and removes beneficiaries. Support cannot silently substitute another person.'),
  FaqEntry(
      id: 'inheritance-authorization',
      category: 'inheritance',
      question: 'How is beneficiary access authorized?',
      answer:
          'The current flow uses beneficiary pairing, a release request, a 30-day waiting period, owner notification or approval controls, and client-side re-encryption/key material. Exact availability depends on completing setup on both sides.'),
  FaqEntry(
      id: 'remove-beneficiary',
      category: 'inheritance',
      question: 'What happens if I remove a beneficiary?',
      answer:
          'The link and pending access path are removed. Previously exported information cannot be recalled, so review what you shared outside SVaultAI.'),
  FaqEntry(
      id: 'support-inheritance-bypass',
      category: 'inheritance',
      question: 'Can support bypass the inheritance process?',
      answer:
          'No. Support cannot bypass the release gates or decrypt the owner’s vault for a beneficiary.'),
  FaqEntry(
      id: 'inheritance-after-delete',
      category: 'inheritance',
      question:
          'What happens to inheritance instructions if I delete my vault?',
      answer:
          'Vault deletion removes beneficiary links and vault-held inheritance material. It does not retrieve copies already exported or alter public blockchain records.'),
  FaqEntry(
      id: 'inheritance-evidence',
      category: 'inheritance',
      question: 'What evidence or verification may be required?',
      answer:
          'The product may require account authentication, beneficiary pairing, waiting periods, and confirmations. Legal proof requirements vary by jurisdiction and are not currently a promise that support can adjudicate an estate claim.'),
  FaqEntry(
      id: 'stop-using',
      category: 'storage',
      question: 'What happens if I stop using SVaultAI?',
      answer:
          'A paid vault remains subject to its subscription terms. An unpaid vault that remains inactive for the configured threshold can be deleted automatically, so export important data and do not rely on free inactive storage as an archive.'),
  FaqEntry(
      id: 'inactive-definition',
      category: 'storage',
      question: 'What counts as an inactive account?',
      answer:
          'The backend compares the vault’s last recorded account or vault activity with the cleanup cutoff. Successful zero-knowledge registration, login, session refresh, unlock completion, and authenticated vault use can update activity; viewing content inside the vault is not logged as readable content.'),
  FaqEntry(
      id: 'inactive-delete-when',
      category: 'storage',
      question: 'When can an unpaid inactive vault be deleted?',
      answer:
          'An unsubscribed vault that has not been logged into for six months may be automatically deleted. Logging in resets the inactivity period. Subscribed vaults are not treated as inactive unpaid vaults.'),
  FaqEntry(
      id: 'inactive-warning',
      category: 'storage',
      question: 'Will I be warned before automatic deletion?',
      answer:
          'Do not rely on a final warning. Keep your contact details current, log in regularly, maintain a subscription, and keep independent copies of anything you cannot replace.'),
  FaqEntry(
      id: 'last-activity-purpose',
      category: 'storage',
      question: 'Why does SVaultAI process a last-activity date?',
      answer:
          'It is needed to apply the inactive-unpaid retention rule and protect active accounts from cleanup. The date is operational metadata and does not reveal which file or secret you viewed.'),
  FaqEntry(
      id: 'activity-content',
      category: 'storage',
      question:
          'Does the inactivity system reveal what I did inside the vault?',
      answer:
          'No. It needs a timestamp indicating recent account or vault activity, not the readable content of the action. Separate security events may record event type and limited technical context.'),
  FaqEntry(
      id: 'subscription-expires',
      category: 'storage',
      question: 'What happens if my subscription expires?',
      answer:
          'Your plan moves through the configured billing state and may enter billing or over-quota grace before becoming unpaid or locked. Once no protected paid status remains, the inactive cleanup rule can apply based on the existing last-activity timestamp.'),
  FaqEntry(
      id: 'download-before-delete',
      category: 'storage',
      question: 'Can I download my data before deletion?',
      answer:
          'Yes, while you can still authenticate and the vault exists. Download and verify important files and records early; the automatic cleanup job does not provide a final recovery window.'),
  FaqEntry(
      id: 'storage-calculation',
      category: 'storage',
      question: 'How is storage usage calculated?',
      answer:
          'Storage usage includes encrypted uploaded data and service overhead as implemented by the quota system. The displayed value may differ slightly from the original file sizes.'),
  FaqEntry(
      id: 'manage-billing',
      category: 'storage',
      question: 'How do I manage or cancel my subscription?',
      answer:
          'Open Billing and use the subscription-management link. Cancellation changes future billing according to the payment provider and does not itself export your data.'),
  FaqEntry(
      id: 'delete-vault',
      category: 'deletion',
      question: 'How do I permanently delete my vault?',
      answer:
          'In Settings, choose Delete vault and complete the trusted-device, exact confirmation phrase, PIN, and final confirmation steps. If subscription cancellation cannot be confirmed, deletion is deferred so billing is not left active accidentally.'),
  FaqEntry(
      id: 'restore-deleted',
      category: 'deletion',
      question: 'Can a deleted vault be restored?',
      answer:
          'No user-facing restore is provided after confirmed deletion. The active database vault and its dependent records are deleted, so export and verify anything important first.'),
  FaqEntry(
      id: 'remaining-records',
      category: 'deletion',
      question:
          'What records may legally or operationally remain after deletion?',
      answer:
          'A deletion tombstone containing a timestamp, reason, and one-way hash of the vault identifier remains. Billing-provider records, security or legal records, processor records, and encrypted backups may remain for their applicable retention periods.'),
  FaqEntry(
      id: 'delete-file-vs-vault',
      category: 'deletion',
      question: 'What happens when a vault is deleted?',
      answer:
          'SVaultAI removes the vault and its protected files, saved items, memories, sessions, trusted devices, wallet records, and beneficiary links. Deleted content is not available through ordinary support recovery.'),
  FaqEntry(
      id: 'blockchain-after-delete',
      category: 'deletion',
      question:
          'What happens to wallet records and public blockchain transactions after account deletion?',
      answer:
          'SVaultAI’s encrypted wallet records are deleted with the vault. Assets and transactions remain on their public networks and cannot be erased by deleting an SVaultAI account. Without an independent wallet backup, you may lose access to funds.'),
  FaqEntry(
      id: 'file-missing',
      category: 'safety',
      question: 'Why can’t I find a file or memory?',
      answer:
          'Clear filters, check the selected vault, try a distinctive word, and wait for upload or indexing to finish. If the original item appears in its list but AI search misses it, open it directly and report the search problem.'),
  FaqEntry(
      id: 'upload-failed',
      category: 'safety',
      question: 'Why did my upload fail?',
      answer:
          'Check your connection, available storage, file size, and supported format, then retry. Keep the original file until the uploaded copy opens and downloads correctly.'),
  FaqEntry(
      id: 'balance-unavailable',
      category: 'safety',
      question: 'Why is my wallet balance or transaction status unavailable?',
      answer:
          'The network or RPC provider may be delayed or unavailable. Do not assume unavailable means zero; verify the public address or transaction hash on the correct network explorer.'),
  FaqEntry(
      id: 'contact-support',
      category: 'safety',
      question: 'How do I contact support?',
      answer:
          'Use the “Still need help?” section below. Never include your PIN, password, recovery phrase, private key, full credential value, or decrypted vault content in a support message.'),
  FaqEntry(
      id: 'protect-yourself',
      category: 'safety',
      question: 'How can I protect my vault?',
      answer:
          'Use a unique PIN, secure your email and devices, enable device biometrics and screen lock, review trusted devices, install updates, and keep verified offline backups of irreplaceable data and wallet recovery material.'),
  FaqEntry(
      id: 'never-share',
      category: 'safety',
      question: 'What should I never share with support?',
      answer:
          'Never share your PIN, passwords, one-time codes, seed phrase, private key, recovery material, or decrypted copies of sensitive vault content. Legitimate support does not need these secrets.'),
  FaqEntry(
      id: 'phishing',
      category: 'safety',
      question: 'How do I recognize a phishing attempt?',
      answer:
          'Be suspicious of urgent messages, unexpected links, requests to move crypto, and anyone asking for a secret. Open SVaultAI from your usual app or saved address and contact support through the official Help Center.'),
  FaqEntry(
      id: 'backup-plan',
      category: 'safety',
      question: 'Should I keep another backup?',
      answer:
          'Yes for anything irreplaceable. Encryption and cloud storage do not prevent every form of loss. Keep an offline, protected, tested backup and make sure your heirs can use any recovery instructions you intend for them.'),
  FaqEntry(
      id: 'different-cloud',
      category: 'getting_started',
      question: 'Why is SVaultAI different from normal cloud storage?',
      answer:
          'SVaultAI is designed around a private encrypted vault, local authorization, protected credentials, private memories, and a non-custodial wallet—not public sharing or staff access to readable content.'),
  FaqEntry(
      id: 'password-manager',
      category: 'getting_started',
      question: 'Is SVaultAI a password manager?',
      answer:
          'It includes protected login and password features, but it is broader than a password manager because it also protects files, media, memories, inheritance information, and supported digital assets.'),
  FaqEntry(
      id: 'public-profile',
      category: 'getting_started',
      question: 'Is SVaultAI a public profile?',
      answer:
          'No. Your vault is private and is not presented as a public profile.'),
  FaqEntry(
      id: 'search-my-vault',
      category: 'getting_started',
      question: 'Can anyone search for my vault?',
      answer:
          'No public vault directory is provided. Other users cannot search for or browse your vault.'),
  FaqEntry(
      id: 'who-owns-info',
      category: 'getting_started',
      question: 'Who owns the information stored in my vault?',
      answer:
          'You remain in control of the information you place in your vault, subject to the service terms and applicable law.'),
  FaqEntry(
      id: 'decide-storage',
      category: 'getting_started',
      question: 'Can SVaultAI decide what I store?',
      answer:
          'You choose what to store, provided it is lawful and supported by the service.'),
  FaqEntry(
      id: 'important-records',
      category: 'getting_started',
      question: 'Is SVaultAI suitable for important private records?',
      answer:
          'It is designed for private records, but you should keep a separate protected backup of anything irreplaceable.'),
  FaqEntry(
      id: 'support-see-docs',
      category: 'privacy',
      question: 'Can customer support see my uploaded documents?',
      answer:
          'No. Support cannot open your vault and browse protected uploaded documents.'),
  FaqEntry(
      id: 'hidden-backdoor',
      category: 'privacy',
      question: 'Is there a hidden backdoor?',
      answer:
          'No. SVaultAI is not designed with a hidden developer or support route into protected vault contents.'),
  FaqEntry(
      id: 'listen-recordings',
      category: 'privacy',
      question: 'Can SVaultAI listen to my voice recordings?',
      answer:
          'Staff cannot browse or listen to protected voice recordings stored in your vault.'),
  FaqEntry(
      id: 'admin-unlock',
      category: 'privacy',
      question: 'Can an administrator secretly unlock my vault?',
      answer:
          'No. Administrative service access does not provide a key that opens protected vault contents.'),
  FaqEntry(
      id: 'content-public',
      category: 'privacy',
      question: 'Is my vault content public?',
      answer:
          'No. Protected vault content is private and is not published by SVaultAI.'),
  FaqEntry(
      id: 'search-index',
      category: 'privacy',
      question: 'Can search engines index my vault?',
      answer:
          'No. Private vault contents are not placed in a public search index.'),
  FaqEntry(
      id: 'employees-browse',
      category: 'privacy',
      question: 'Can employees browse user files?',
      answer:
          'No. There is no ordinary employee browsing access to protected user files.'),
  FaqEntry(
      id: 'developers-credentials',
      category: 'privacy',
      question: 'Can developers inspect saved credentials?',
      answer:
          'No. Saved credential values are protected and are not available for developers to browse.'),
  FaqEntry(
      id: 'support-download',
      category: 'privacy',
      question: 'Can support download my files?',
      answer:
          'No. Support cannot download a readable copy of protected vault files for you.'),
  FaqEntry(
      id: 'view-control-panel',
      category: 'privacy',
      question: 'Does SVaultAI have a “view user vault” control panel?',
      answer:
          'No. There is no staff-facing control that reveals protected vault contents.'),
  FaqEntry(
      id: 'support-pin',
      category: 'security',
      question: 'Can customer support tell me my PIN?',
      answer:
          'No. Customer support cannot look up, reveal, or send you your PIN.'),
  FaqEntry(
      id: 'wrong-pin',
      category: 'security',
      question: 'What happens after a wrong PIN?',
      answer:
          'The vault stays locked. Repeated attempts may be delayed or temporarily blocked, and wrong guesses do not reveal vault contents.'),
  FaqEntry(
      id: 'share-pin',
      category: 'security',
      question: 'Should I share my PIN with support?',
      answer:
          'No. SVaultAI support does not need your PIN and will not ask you to send it.'),
  FaqEntry(
      id: 'employee-pin-bypass',
      category: 'security',
      question: 'Can an employee bypass the PIN?',
      answer:
          'No. Employees do not have a universal bypass for the vault PIN.'),
  FaqEntry(
      id: 'session-expiry',
      category: 'security',
      question: 'What happens if my session expires?',
      answer:
          'Protected access is locked and you must authenticate again. Session expiry does not expose vault content.'),
  FaqEntry(
      id: 'pin-sensitive-actions',
      category: 'security',
      question: 'Why must I enter my PIN again for sensitive actions?',
      answer:
          'Reauthorization helps prevent someone with a briefly unattended device from revealing secrets, deleting data, or approving a wallet transaction.'),
  FaqEntry(
      id: 'pin-staff-access',
      category: 'security',
      question: 'Does entering my PIN allow SVaultAI staff to see my vault?',
      answer:
          'No. Entering your PIN authorizes your vault session; it does not give staff access.'),
  FaqEntry(
      id: 'photos-private',
      category: 'files',
      question: 'Are photos encrypted?',
      answer:
          'Yes. Photos stored in the vault are protected encrypted content.'),
  FaqEntry(
      id: 'videos-private',
      category: 'files',
      question: 'Are videos encrypted?',
      answer:
          'Yes. Videos stored in the vault are protected encrypted content.'),
  FaqEntry(
      id: 'voice-private',
      category: 'files',
      question: 'Are voice notes encrypted?',
      answer:
          'Yes. Voice notes and audio recordings stored in the vault are protected encrypted content.'),
  FaqEntry(
      id: 'staff-watch-video',
      category: 'files',
      question: 'Can SVaultAI staff watch my videos?',
      answer: 'No. Staff cannot open the vault and browse protected videos.'),
  FaqEntry(
      id: 'staff-listen-audio',
      category: 'files',
      question: 'Can employees listen to my recordings?',
      answer: 'No. Employees cannot browse protected vault recordings.'),
  FaqEntry(
      id: 'legal-documents',
      category: 'files',
      question: 'Can I upload legal documents?',
      answer:
          'Yes, if they are lawful and supported. Verify important documents after upload and keep an independent protected copy.'),
  FaqEntry(
      id: 'identity-documents',
      category: 'files',
      question: 'Can I store identity documents?',
      answer:
          'Yes. Identity documents are protected vault content, with sensitive values masked where supported.'),
  FaqEntry(
      id: 'family-records',
      category: 'files',
      question: 'Can I store family records?',
      answer:
          'Yes. You can store supported family records that you are authorized to keep.'),
  FaqEntry(
      id: 'business-documents',
      category: 'files',
      question: 'Can I store business documents?',
      answer:
          'Yes, if you are authorized to store them and their use complies with your legal and workplace obligations.'),
  FaqEntry(
      id: 'private-rename',
      category: 'files',
      question: 'Can I rename a file privately?',
      answer:
          'Yes. Private file titles are protected according to the encrypted metadata design.'),
  FaqEntry(
      id: 'other-user-file-name',
      category: 'files',
      question: 'Can another user find my file by name?',
      answer:
          'No. Private file names are not exposed through a public or cross-user search.'),
  FaqEntry(
      id: 'ad-file-scan',
      category: 'files',
      question: 'Does SVaultAI scan my files for advertising?',
      answer: 'No. Vault files are not scanned to build advertising profiles.'),
  FaqEntry(
      id: 'cross-user-file-search',
      category: 'files',
      question: 'Can my files appear in another user’s search?',
      answer: 'No. Searches are scoped to the authorized vault.'),
  FaqEntry(
      id: 'custom-credential-fields',
      category: 'credentials',
      question: 'Are custom credential fields protected?',
      answer:
          'Yes. Supported custom credential fields are protected inside the encrypted vault.'),
  FaqEntry(
      id: 'credential-advertisers',
      category: 'credentials',
      question: 'Can credentials be sent to advertisers?',
      answer: 'No. Saved credentials are not provided to advertisers.'),
  FaqEntry(
      id: 'ai-reveal-credentials',
      category: 'credentials',
      question: 'Does the AI automatically reveal credentials?',
      answer:
          'No. Credentials stay masked and require the protected reveal flow.'),
  FaqEntry(
      id: 'employee-login-visibility',
      category: 'credentials',
      question: 'Does saving a login make it visible to SVaultAI employees?',
      answer:
          'No. Saving a login places it inside the protected vault; it does not make it staff-readable.'),
  FaqEntry(
      id: 'svaultai-login-for-me',
      category: 'credentials',
      question: 'Can SVaultAI log in to another service for me?',
      answer:
          'SVaultAI stores and reveals credentials through protected flows; it does not give staff control of your other accounts.'),
  FaqEntry(
      id: 'staff-change-credential',
      category: 'credentials',
      question: 'Can staff change one of my saved credentials?',
      answer: 'No. Staff cannot browse or edit protected credential values.'),
  FaqEntry(
      id: 'memories-public',
      category: 'ai',
      question: 'Are personal memories public?',
      answer:
          'No. Personal memories are private vault information for your assistant.'),
  FaqEntry(
      id: 'choose-memory',
      category: 'ai',
      question: 'How do I choose what the AI remembers?',
      answer:
          'Save only information you want available later. Review the memories area and remove anything you no longer want remembered.'),
  FaqEntry(
      id: 'ai-other-vault',
      category: 'ai',
      question: 'Does the AI search another user’s vault?',
      answer: 'No. The assistant is scoped to the authorized user’s vault.'),
  FaqEntry(
      id: 'ai-advertisers',
      category: 'ai',
      question: 'Can advertisers use what I tell the assistant?',
      answer:
          'No. Private assistant content is not used to build advertising profiles.'),
  FaqEntry(
      id: 'trusted-device-definition',
      category: 'devices',
      question: 'What is a trusted device?',
      answer:
          'A trusted device is a device you approved for account access. It adds protection around sensitive vault actions.'),
  FaqEntry(
      id: 'device-new-phone',
      category: 'devices',
      question: 'What happens when I use a new phone?',
      answer:
          'You must sign in and complete any additional device verification before protected access is available.'),
  FaqEntry(
      id: 'device-lost-phone',
      category: 'devices',
      question: 'What happens if I lose my phone?',
      answer:
          'Use another authorized device to revoke it, secure your email and mobile account, and review security events.'),
  FaqEntry(
      id: 'remove-old-device',
      category: 'devices',
      question: 'Can I remove an old device?',
      answer:
          'Yes. Review trusted devices in Security and remove devices you no longer use or control.'),
  FaqEntry(
      id: 'logout-protection',
      category: 'devices',
      question: 'Does logging out protect my vault?',
      answer:
          'Logging out removes the active session and locks protected access on that device.'),
  FaqEntry(
      id: 'reinstall-login',
      category: 'devices',
      question: 'Does reinstalling the app keep me logged in?',
      answer:
          'A reinstall should not be treated as proof of authorization. Sign in again and review the device afterward.'),
  FaqEntry(
      id: 'stolen-phone',
      category: 'devices',
      question: 'Can a stolen phone reveal my vault?',
      answer:
          'A locked phone does not automatically reveal the vault. Device security, logout state, trusted-device controls, and your PIN remain important.'),
  FaqEntry(
      id: 'session-other-device',
      category: 'devices',
      question: 'Can another device use my session?',
      answer:
          'Sessions are protected and associated with authorized access. Revoke unfamiliar devices and sessions immediately.'),
  FaqEntry(
      id: 'security-events',
      category: 'devices',
      question: 'Why does SVaultAI monitor security events?',
      answer:
          'Limited security records help detect abuse, protect sessions, and show suspicious access without revealing readable vault contents.'),
  FaqEntry(
      id: 'support-phone-access',
      category: 'devices',
      question: 'Can support remotely access my phone?',
      answer:
          'No. Support does not need remote control of your phone or your vault secrets.'),
  FaqEntry(
      id: 'phone-backups',
      category: 'devices',
      question: 'Does SVaultAI copy my vault into phone backups?',
      answer:
          'SVaultAI does not intentionally place readable vault contents into ordinary phone backups. Platform secure-storage behavior may differ, so protect device backups and accounts.'),
  FaqEntry(
      id: 'switch-vaults',
      category: 'devices',
      question: 'What happens when I switch vaults?',
      answer:
          'The previous vault context is cleared and the newly authorized vault becomes active. Data must remain isolated between vaults.'),
  FaqEntry(
      id: 'employee-send-funds',
      category: 'crypto',
      question: 'Can an employee send funds from my wallet?',
      answer:
          'No. Employees do not have your local signing authorization and cannot press Send on your behalf.'),
  FaqEntry(
      id: 'private-key-recovery',
      category: 'crypto',
      question: 'Can support recover my wallet private key?',
      answer:
          'No. Support cannot reveal or recreate your protected wallet private key.'),
  FaqEntry(
      id: 'review-transaction',
      category: 'crypto',
      question: 'Why must I review a transaction?',
      answer:
          'Blockchain transactions are usually irreversible. Confirm the asset, network, address, amount, and fee before approval.'),
  FaqEntry(
      id: 'eth-gas-reserve',
      category: 'crypto',
      question: 'Why must some ETH remain for gas?',
      answer:
          'Ethereum token transfers require ETH to pay the network fee, so the full ETH balance may not be spendable.'),
  FaqEntry(
      id: 'wallet-addresses-private',
      category: 'crypto',
      question: 'Are wallet addresses private?',
      answer:
          'Public wallet addresses can be visible on their blockchain and should not be treated as secret.'),
  FaqEntry(
      id: 'blockchain-private',
      category: 'crypto',
      question: 'Are blockchain transactions private?',
      answer:
          'Transactions on public networks are publicly visible. Privacy varies by network and does not make public records disappear.'),
  FaqEntry(
      id: 'hide-transaction',
      category: 'crypto',
      question: 'Can SVaultAI hide a blockchain transaction?',
      answer:
          'No. SVaultAI cannot erase or hide records maintained by a public blockchain.'),
  FaqEntry(
      id: 'investment-advice',
      category: 'crypto',
      question: 'Does SVaultAI provide investment advice?',
      answer:
          'No. Information shown in the wallet is not a recommendation to buy, sell, or hold an asset.'),
  FaqEntry(
      id: 'token-prices',
      category: 'crypto',
      question: 'Does SVaultAI control token prices?',
      answer:
          'No. Market prices come from external markets and can change rapidly.'),
  FaqEntry(
      id: 'ai-trade',
      category: 'crypto',
      question: 'Can the AI trade for me?',
      answer:
          'No. The assistant cannot independently trade or approve wallet transactions.'),
  FaqEntry(
      id: 'ai-invest',
      category: 'crypto',
      question: 'Can the AI invest my money?',
      answer:
          'No. The assistant does not control your funds or make investments for you.'),
  FaqEntry(
      id: 'wrong-address-recovery',
      category: 'crypto',
      question: 'Can SVaultAI recover funds sent to the wrong address?',
      answer:
          'Usually not. Confirmed blockchain transfers generally cannot be reversed by SVaultAI.'),
  FaqEntry(
      id: 'support-add-beneficiary',
      category: 'inheritance',
      question: 'Can support add a beneficiary?',
      answer:
          'No. Only the vault owner can choose and authorize a beneficiary.'),
  FaqEntry(
      id: 'developer-inheritance-bypass',
      category: 'inheritance',
      question: 'Can developers bypass inheritance rules?',
      answer:
          'No. Developers do not have a tool that bypasses protected inheritance authorization.'),
  FaqEntry(
      id: 'change-beneficiary',
      category: 'inheritance',
      question: 'Can I change my beneficiary?',
      answer:
          'Yes. Remove the existing beneficiary and configure the intended beneficiary through the protected inheritance flow.'),
  FaqEntry(
      id: 'beneficiary-immediate',
      category: 'inheritance',
      question: 'Does a beneficiary receive access immediately?',
      answer:
          'No. Pairing alone does not grant immediate vault access; the required authorization and waiting steps must complete.'),
  FaqEntry(
      id: 'claim-assets',
      category: 'inheritance',
      question: 'Can SVaultAI claim my assets?',
      answer:
          'No. SVaultAI does not become the owner of your vault contents or wallet assets.'),
  FaqEntry(
      id: 'redirect-inheritance',
      category: 'inheritance',
      question: 'Can SVaultAI redirect an inheritance transfer?',
      answer:
          'No. SVaultAI cannot choose a different beneficiary or independently redirect protected assets.'),
  FaqEntry(
      id: 'update-instructions',
      category: 'inheritance',
      question: 'Why should I keep inheritance instructions updated?',
      answer:
          'Outdated beneficiary details or recovery instructions may prevent the person you intend from completing the process.'),
  FaqEntry(
      id: 'without-subscription',
      category: 'storage',
      question: 'What happens if I do not subscribe?',
      answer:
          'You may use the available unsubscribed plan, but an unsubscribed vault that is not logged into for six months may be deleted.'),
  FaqEntry(
      id: 'use-unsubscribed',
      category: 'storage',
      question: 'Can I still use an unsubscribed vault?',
      answer:
          'Yes, within the available free-plan limits. Log in regularly and keep independent backups.'),
  FaqEntry(
      id: 'six-months',
      category: 'storage',
      question: 'What happens after six months without logging in?',
      answer:
          'An unsubscribed vault that has not been logged into for six months may be automatically deleted. Logging in resets inactivity. Subscribed vaults are not treated as inactive unpaid vaults.'),
  FaqEntry(
      id: 'eligible-inactivity',
      category: 'storage',
      question: 'Which vaults are eligible for inactivity deletion?',
      answer:
          'Vaults that are unsubscribed and have not been logged into for six months may be eligible.'),
  FaqEntry(
      id: 'login-resets',
      category: 'storage',
      question: 'Does logging in reset inactivity?',
      answer: 'Yes. A successful login resets the inactivity period.'),
  FaqEntry(
      id: 'subscribed-inactivity',
      category: 'storage',
      question: 'Are subscribed vaults deleted for inactivity?',
      answer:
          'No. Active subscribers are not treated as unpaid inactive vaults.'),
  FaqEntry(
      id: 'why-inactivity-delete',
      category: 'storage',
      question: 'Why does SVaultAI delete inactive unsubscribed vaults?',
      answer:
          'Deleting abandoned unsubscribed vaults limits indefinite storage of unused encrypted data and reduces the risk of forgotten vaults remaining online forever.'),
  FaqEntry(
      id: 'read-before-delete',
      category: 'storage',
      question: 'Does SVaultAI read my vault before deleting it?',
      answer:
          'No. The service only needs account status and the last successful login date; it does not need to read protected contents.'),
  FaqEntry(
      id: 'recover-inactive',
      category: 'storage',
      question: 'Can customer support recover a deleted inactive vault?',
      answer:
          'No. Deleted vault content is not available through ordinary support recovery.'),
  FaqEntry(
      id: 'prevent-inactivity',
      category: 'storage',
      question: 'How do I prevent inactivity deletion?',
      answer:
          'Log in before six months pass, maintain an active subscription, keep your contact details current, and keep independent backups.'),
  FaqEntry(
      id: 'inactivity-tracking',
      category: 'storage',
      question: 'Does inactivity mean SVaultAI is tracking what I store?',
      answer:
          'No. The service uses account status and login timing, not a readable history of the private content you store or view.'),
  FaqEntry(
      id: 'abandoned-forever',
      category: 'storage',
      question: 'Does SVaultAI keep abandoned vaults forever?',
      answer:
          'No. An unsubscribed vault that remains inactive for six months may be deleted.'),
  FaqEntry(
      id: 'delete-login',
      category: 'deletion',
      question: 'How do I delete a saved login?',
      answer:
          'Open the saved login, choose Delete, and confirm. Treat deletion as permanent.'),
  FaqEntry(
      id: 'delete-memory',
      category: 'deletion',
      question: 'How do I delete a memory?',
      answer:
          'Open personal memories, select the memory, and choose Forget or Delete.'),
  FaqEntry(
      id: 'undo-deletion',
      category: 'deletion',
      question: 'Can support undo vault deletion?',
      answer:
          'No. Support cannot reopen or restore a permanently deleted vault.'),
  FaqEntry(
      id: 'wallet-address-delete',
      category: 'deletion',
      question: 'What happens to wallet addresses after deletion?',
      answer:
          'SVaultAI removes its protected wallet records, but public addresses and transactions remain on their blockchain.'),
  FaqEntry(
      id: 'move-before-delete',
      category: 'deletion',
      question: 'Should I move my crypto before deleting my vault?',
      answer:
          'Make sure you have a verified independent way to access the wallet. If you do not, move funds safely before deletion.'),
  FaqEntry(
      id: 'sessions-after-delete',
      category: 'deletion',
      question: 'What happens to active sessions after deletion?',
      answer:
          'Vault sessions are removed and can no longer open the deleted vault.'),
  FaqEntry(
      id: 'devices-after-delete',
      category: 'deletion',
      question: 'What happens to trusted devices after deletion?',
      answer:
          'Trusted-device records linked to the deleted vault are removed.'),
  FaqEntry(
      id: 'pin-email',
      category: 'safety',
      question: 'Will SVaultAI ever ask for my PIN by email?',
      answer: 'No. Never send your PIN by email, chat, or support message.'),
  FaqEntry(
      id: 'support-private-key',
      category: 'safety',
      question: 'Will support ask for my private key?',
      answer:
          'No. Support should never ask for your private key, seed phrase, or wallet recovery secret.'),
  FaqEntry(
      id: 'before-send',
      category: 'safety',
      question: 'What should I do before sending crypto?',
      answer:
          'Verify the network, asset, full destination address, amount, and fee. Start with a small test transfer when appropriate.'),
  FaqEntry(
      id: 'verify-addresses',
      category: 'safety',
      question: 'Why should I verify wallet addresses?',
      answer:
          'Malware, clipboard replacement, and human error can change an address. Compare the full address using a trusted source.'),
  FaqEntry(
      id: 'recovery-copies',
      category: 'safety',
      question: 'Should I keep copies of important recovery information?',
      answer:
          'Yes. Keep protected offline copies in a location only you or your intended beneficiary can access.'),
  FaqEntry(
      id: 'report-suspicious',
      category: 'safety',
      question: 'How do I report suspicious activity?',
      answer:
          'Revoke unfamiliar devices, secure your accounts, and contact SVaultAI through the official Help Center without sharing secrets.'),
  FaqEntry(
      id: 'no-access-guarantee',
      category: 'safety',
      question: 'Can SVaultAI guarantee that I will never lose access?',
      answer:
          'No. Losing your PIN, device, and recovery material may permanently prevent access. Keep tested backups and recovery information.'),
  FaqEntry(
      id: 'never-share-info',
      category: 'safety',
      question: 'What information should I never share?',
      answer:
          'Never share your PIN, passwords, one-time codes, private keys, seed phrases, wallet recovery material, or decrypted sensitive files.'),
];

List<FaqEntry> faqEntriesInCategory(String categoryId) =>
    kFaqEntries.where((e) => e.category == categoryId).toList(growable: false);

List<FaqEntry> faqEntriesMatchingQuery(String rawQuery) {
  final q = rawQuery.trim().toLowerCase();
  if (q.isEmpty) return kFaqEntries;
  return kFaqEntries
      .where((e) =>
          e.question.toLowerCase().contains(q) ||
          e.answer.toLowerCase().contains(q))
      .toList(growable: false);
}

FaqEntry? faqEntryById(String id) {
  for (final entry in kFaqEntries) {
    if (entry.id == id) return entry;
  }
  return null;
}
