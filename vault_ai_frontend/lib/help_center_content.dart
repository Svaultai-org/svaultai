class FaqCategory {
  final String id;
  final String label;
  const FaqCategory({required this.id, required this.label});
}

const FaqCategory kFaqCategoryGettingStarted =
    FaqCategory(id: 'getting_started', label: 'Getting started');
const FaqCategory kFaqCategorySecurity =
    FaqCategory(id: 'security', label: 'Security');
const FaqCategory kFaqCategoryFiles = FaqCategory(id: 'files', label: 'Files');
const FaqCategory kFaqCategorySecureItems =
    FaqCategory(id: 'secure_items', label: 'Secure items');
const FaqCategory kFaqCategoryIds = FaqCategory(id: 'ids', label: 'IDs');
const FaqCategory kFaqCategoryCrypto =
    FaqCategory(id: 'crypto', label: 'Assets');
const FaqCategory kFaqCategoryBilling =
    FaqCategory(id: 'billing', label: 'Billing');
const FaqCategory kFaqCategoryTroubleshooting =
    FaqCategory(id: 'troubleshooting', label: 'Troubleshooting');

const List<FaqCategory> kFaqCategories = <FaqCategory>[
  kFaqCategoryGettingStarted,
  kFaqCategorySecurity,
  kFaqCategoryFiles,
  kFaqCategorySecureItems,
  kFaqCategoryIds,
  kFaqCategoryCrypto,
  kFaqCategoryBilling,
  kFaqCategoryTroubleshooting,
];

class FaqEntry {
  final String id;
  final String category;
  final String question;
  final String answer;
  const FaqEntry({
    required this.id,
    required this.category,
    required this.question,
    required this.answer,
  });
}

// Current native help topics without a legacy backend FAQ identifier. Keep the
// existing IDs stable; these entries are rendered and searched locally.
const kFrontendCapabilityFaqIds = <String>{
  'what-is-memory', 'how-inheritance-works', 'what-is-concierge',
  'concierge-password-checks', 'gold-and-silver-tokens', 'assets-coming-soon',
};

// Reviewed release coverage takes precedence over older generated translations.
// Until these answers are translated, use accurate English rather than stale
// claims about asset support or privacy-check availability.
const kCurrentReleaseCapabilityFaqIds = <String>{
  ...kFrontendCapabilityFaqIds,
  'what-is-vaultai', 'what-can-i-save', 'what-is-crypto-vault',
  'supported-assets', 'is-crypto-custodial', 'usdc-uses-eth-address',
  'erc20-needs-eth-gas', 'buy-sell-swap', 'receive-when-balance-zero',
  'what-happens-when-i-delete-my-vault', 'why-chat-searches-files',
};

const List<FaqEntry> kFaqEntries = <FaqEntry>[
  FaqEntry(
    id: 'what-is-vaultai',
    category: 'getting_started',
    question: 'What is Svaultai?',
    answer: 'Svaultai is your private digital vault. Imagine a physical '
        'vault in digital form — a bank vault or '
        'safe at home for the digital versions of things that matter to you. '
        'Svaultai is more than a password manager: keep files, documents, '
        'private photos, videos, audio, passwords, secure notes, ID documents '
        'and memories together. Assets adds non-custodial wallets for supported '
        'cryptocurrencies and verified Gold and Silver tokens. Inheritance '
        'helps you arrange future vault access for a chosen beneficiary. '
        'Concierge brings together available reminders and optional password '
        'checks. Instead of scattering records across emails, notes, '
        'screenshots or random folders, keep their supported digital versions '
        'in your vault. Ask Svaultai Chat to find, understand or manage what '
        'you have saved. This does not turn a physical object or cash into '
        'a digital asset.',
  ),
  FaqEntry(
    id: 'what-can-i-save',
    category: 'getting_started',
    question: 'What can I save in Svaultai?',
    answer: 'You can save files, documents, photos, videos, '
        'audio, passwords, generated logins, secure notes, '
        'codes, device details, ID documents and memories. If something you '
        'would keep in a physical vault has a supported digital version, '
        'you can keep that version here, within your storage limit. Assets '
        'also supports selected on-chain cryptocurrencies, PAXG and KAG; '
        'the tokens stay on their blockchains. Internal wallet records are '
        'managed by Assets and are not shown as normal secure items.',
  ),
  FaqEntry(
    id: 'what-is-memory',
    category: 'getting_started',
    question: 'What is Memory for?',
    answer: 'Memory keeps personal facts and notes you want to remember, '
        'such as a name, an important detail or an instruction. Ask Svaultai '
        'Chat to save a memory, retrieve it later or delete it. You can also '
        'browse and manage saved memories in Memory. A memory is a personal '
        'record, not a login or a cryptocurrency transaction.',
  ),
  FaqEntry(
    id: 'what-is-concierge',
    category: 'getting_started',
    question: 'What does Concierge do?',
    answer: 'Concierge brings together available vault reminders, document '
        'expiry information and items that may need attention. Its optional '
        'free password checks flag exposed, weak or reused passwords in '
        'eligible encrypted saved logins while your vault is unlocked. '
        'Email breach monitoring, background email checks and stealer-log '
        'checks are not enabled in this release. Concierge is not a '
        'continuous or comprehensive dark-web monitoring service.',
  ),
  FaqEntry(
    id: 'how-do-i-create-my-vault',
    category: 'getting_started',
    question: 'How do I create my vault?',
    answer: 'Open the Svaultai sign-in flow, pick or confirm your '
        'vault name, and set your PIN when prompted. Your '
        'PIN helps protect your vault unlock process — keep '
        'it safe. If recovery is not available for your '
        'account, losing your PIN may mean you cannot '
        'recover access.',
  ),
  FaqEntry(
    id: 'how-do-i-unlock-my-vault',
    category: 'getting_started',
    question: 'How do I unlock my vault?',
    answer: 'Open Svaultai on a trusted device and enter your '
        'PIN. Your PIN unlocks the vault locally — the '
        'server never sees your PIN in plaintext. Some '
        'sensitive actions may ask for confirmation again.',
  ),
  FaqEntry(
    id: 'trusted-device',
    category: 'getting_started',
    question: 'What is a trusted device?',
    answer: 'A trusted device is a device you have already approved '
        'for this account. Sensitive actions — revealing a '
        'password, showing a full ID number, preparing a crypto '
        'send — require the request to come from a trusted '
        'device.',
  ),
  FaqEntry(
    id: 'files-vs-secure-items',
    category: 'getting_started',
    question: 'What is the difference between files and secure items?',
    answer: 'Files are uploaded blobs: PDFs, images, spreadsheets, '
        'and other documents. Secure items are short encrypted '
        'text records: logins, notes, codes, device details, '
        'and crypto wallet addresses.',
  ),
  FaqEntry(
    id: 'is-my-vault-encrypted',
    category: 'security',
    question: 'Is my vault encrypted?',
    answer: 'Yes. Svaultai stores sensitive vault data encrypted with '
        'a key derived from your PIN. Sensitive values are '
        'masked by default and protected by trusted-device, '
        'unlock/PIN, and confirmation gates where required.',
  ),
  FaqEntry(
    id: 'can-vaultai-read-secrets',
    category: 'security',
    question: 'Can Svaultai read my saved secrets?',
    answer: 'Svaultai does not display or ask for your seed phrase, '
        'private key, mnemonic, spend key, view key, encrypted '
        'wallet secret, auth token, or API key in chat. The AI '
        'only works with masked, safe projections of your vault.',
  ),
  FaqEntry(
    id: 'if-i-forget-my-pin',
    category: 'security',
    question: 'What happens if I forget my PIN?',
    answer: 'The PIN is required to derive your encryption key. If '
        'you forget it, recovery may not be possible — keep your '
        'PIN safe and consider recording it in a physical '
        'location only you can access.',
  ),
  FaqEntry(
    id: 'can-someone-else-access',
    category: 'security',
    question: 'Can someone else access my vault?',
    answer: 'Only from a trusted device, with your PIN. Sensitive '
        'reveals require additional confirmation. Never share '
        'your PIN, and remove trusted-device access for devices '
        'you no longer control.',
  ),
  FaqEntry(
    id: 'lost-my-device',
    category: 'security',
    question: 'What should I do if I lose my device?',
    answer: 'Open the Security page from another trusted device and '
        'revoke access for the lost device. Your PIN still '
        'protects your vault, but revoking removes the trusted-'
        'device status.',
  ),
  FaqEntry(
    id: 'how-local-signing-works',
    category: 'security',
    question: 'How does local signing work for crypto?',
    answer: 'Crypto sends are signed on your device with keys that '
        'only your device can access. The server never receives '
        'your private key. Every send requires trusted device, '
        'PIN unlock, local signing, and explicit confirmation.',
  ),
  FaqEntry(
    id: 'never-share-seed',
    category: 'security',
    question: 'Why should I not share my seed phrase or private key?',
    answer: 'Anyone with your seed phrase, private key, mnemonic, '
        'spend key, or view key can access or spend your crypto. '
        'Svaultai will never ask for these values, and no '
        'support person should either.',
  ),
  FaqEntry(
    id: 'delete-my-vault',
    category: 'security',
    question: 'How do I delete my vault?',
    answer: 'Open Settings and choose Delete vault. Svaultai shows a '
        'warning, then asks you to type the exact phrase '
        'DELETE MY VAULT, enter your PIN, and confirm from a '
        'trusted device. This is intentionally not a one-click '
        'action. Deletion is permanent. Svaultai cannot delete '
        'your vault from chat, and the flow cannot bypass PIN, '
        'trusted-device, or phrase confirmation.',
  ),
  FaqEntry(
    id: 'what-happens-when-i-delete-my-vault',
    category: 'security',
    question: 'What happens when I delete my vault?',
    answer: 'Deleting your vault permanently deletes your Svaultai '
        'vault data, including files, secure items, logins, ID '
        'documents, Assets encrypted wallet records, and '
        'related vault metadata. Manage or cancel any storage subscription '
        'in the Apple App Store or Google Play account that purchased it. '
        'Deletion does not move or '
        'delete crypto assets on the blockchain — those remain '
        'wherever the corresponding wallets exist. If you have '
        'not backed up your wallet outside Svaultai, deleting '
        'your encrypted wallet records may cause loss of '
        'access to those funds.',
  ),
  FaqEntry(
    id: 'can-i-recover-deleted-vault',
    category: 'security',
    question: 'Can I recover a deleted vault?',
    answer: 'No. Once you confirm deletion, Svaultai removes vault '
        'data permanently and cannot restore it. There is no '
        'hidden shadow copy and no recovery flow. If you also '
        'lose the wallet backup you kept outside Svaultai, '
        'on-chain crypto in that wallet may become '
        'unrecoverable too.',
  ),
  FaqEntry(
    id: 'how-do-i-upload-files',
    category: 'files',
    question: 'How do I upload files?',
    answer: 'Open the Vault or Files view and choose Upload. You '
        'can also drop files onto the app. Uploads are '
        'encrypted before storage.',
  ),
  FaqEntry(
    id: 'what-file-types',
    category: 'files',
    question: 'What file types can I store?',
    answer: 'Svaultai accepts common document, image, audio, and '
        'video file types. Any file that fits within your '
        'storage quota can be uploaded.',
  ),
  FaqEntry(
    id: 'search-inside-documents',
    category: 'files',
    question: 'Can I search inside documents?',
    answer: 'Yes. Svaultai extracts text from supported documents '
        'and lets you search across their contents from chat '
        'or the file list.',
  ),
  FaqEntry(
    id: 'summarize-pdf',
    category: 'files',
    question: 'Can Svaultai summarize my PDF?',
    answer: 'Yes. Ask the assistant to summarize a specific PDF or '
        'document. The summary uses the extracted text; it '
        'does not modify the original file.',
  ),
  FaqEntry(
    id: 'why-cant-find-file',
    category: 'files',
    question: "Why can't Svaultai find my file?",
    answer: 'Check the file name spelling, the vault you are '
        'in, and whether the upload completed. Files that are '
        'still analyzing may not appear in searches yet.',
  ),
  FaqEntry(
    id: 'how-do-i-delete-a-file',
    category: 'files',
    question: 'How do I delete a file?',
    answer: "Open the file's row in the Files list and choose "
        'Delete. Deletion is permanent — Svaultai does not keep '
        'a shadow copy.',
  ),
  FaqEntry(
    id: 'how-do-i-save-a-password',
    category: 'secure_items',
    question: 'How do I save a password?',
    answer: 'Open the Logins & Secure Items page and choose Save, '
        'or ask the assistant to save a login. Svaultai encrypts '
        'the entry before storing it.',
  ),
  FaqEntry(
    id: 'how-do-i-view-a-password',
    category: 'secure_items',
    question: 'How do I view a saved password?',
    answer: "Open the login's row and choose View. Revealing the "
        'password requires trusted device, PIN unlock, and '
        'explicit confirmation — the chat itself never displays '
        'the password value.',
  ),
  FaqEntry(
    id: 'why-are-passwords-masked',
    category: 'secure_items',
    question: 'Why are passwords masked?',
    answer: 'Passwords are masked by default so nobody looking over '
        'your shoulder — including the AI transcript — sees the '
        'value. Reveal requires unlock and confirmation.',
  ),
  FaqEntry(
    id: 'generated-login',
    category: 'secure_items',
    question: 'How do I create a generated login?',
    answer: 'Ask the assistant to generate a new login for a '
        'service, or open the Logins page and pick Generate. '
        'You confirm the draft before it is saved.',
  ),
  FaqEntry(
    id: 'edit-delete-secure-item',
    category: 'secure_items',
    question: 'How do I edit or delete a secure item?',
    answer: "Open the item's row and choose Edit or Delete. Both "
        'actions require unlock; deletion is permanent.',
  ),
  FaqEntry(
    id: 'duplicate-logins',
    category: 'secure_items',
    question: 'Can Svaultai find duplicate logins?',
    answer: 'Yes. Ask the assistant to show duplicate or reused '
        'passwords. Svaultai compares saved logins locally after '
        'unlock and flags matches.',
  ),
  FaqEntry(
    id: 'save-passport-license',
    category: 'ids',
    question: 'Can I save my passport or driver license?',
    answer: 'Yes. Upload the document and mark it as an ID '
        'document. Extracted fields are stored encrypted; the '
        'ID number is masked by default.',
  ),
  FaqEntry(
    id: 'ids-masked-by-default',
    category: 'ids',
    question: 'Are ID numbers hidden by default?',
    answer: 'Yes. Only the last few characters are shown. Revealing '
        'the full number requires trusted device, PIN unlock, '
        'and explicit confirmation.',
  ),
  FaqEntry(
    id: 'id-expiry-reminders',
    category: 'ids',
    question: 'Can Svaultai remind me about expiration dates?',
    answer: 'Ask the assistant when your passport or license '
        'expires. Svaultai reads the extracted expiry date '
        'from your ID documents.',
  ),
  FaqEntry(
    id: 'how-do-i-search-ids',
    category: 'ids',
    question: 'How do I search my ID documents?',
    answer: 'Ask the assistant, or open the ID Documents page and '
        'use the search bar. Searches match on type, issuing '
        'country, and issuing state — not on the raw ID number.',
  ),
  FaqEntry(
    id: 'how-inheritance-works',
    category: 'security',
    question: 'How does Inheritance work?',
    answer: 'Inheritance lets you pair a chosen beneficiary with your vault '
        'and save the encrypted access credentials needed for that arrangement. '
        'The beneficiary can request access; you can approve or reject the '
        'request. The app shows the applicable countdown before access can '
        'be claimed without your response. Review pairing and credentials '
        'in Inheritance before relying on it. It does not make a legal will '
        'or automatically send cryptocurrency to a beneficiary.',
  ),
  FaqEntry(
    id: 'concierge-password-checks',
    category: 'security',
    question: 'How do the free Concierge password checks protect my privacy?',
    answer: 'Choose your privacy checks in Concierge before enabling them. '
        'Weakness and reuse checks run on your device. For exposure checks, '
        'only the first 5 characters of a password hash go to Have I Been '
        'Pwned; your password and full hash stay on the device. Eligible '
        'saved logins are checked only while the vault is unlocked. The '
        'optional automatic check runs when Concierge opens, at most once '
        'every 24 hours — it is not continuous background scanning. '
        'A clean result is not a guarantee of safety, and an unavailable '
        'check is not treated as clear. You can turn the checks off.',
  ),
  FaqEntry(
    id: 'what-is-crypto-vault',
    category: 'crypto',
    question: 'What is Assets?',
    answer: 'Assets is the wallet area of your digital vault. Cryptocurrency '
        'is one category; Digital Gold and Digital Silver hold supported '
        'Ethereum tokens. For enabled assets, view your balance, network, '
        'receive address and transaction history, or prepare a send you '
        'confirm and sign on your device. Assets is non-custodial and is '
        'not a marketplace, bank or exchange. Categories marked Coming soon '
        'do not yet have a working wallet integration.',
  ),
  FaqEntry(
    id: 'supported-assets',
    category: 'crypto',
    question: 'Which assets are supported?',
    answer: 'Cryptocurrency includes ETH, USDT ERC20 and USDC ERC20 on '
        'Ethereum, SOL on Solana, USDT TRC20 on TRON and XMR on Monero '
        '(receive only; local scanning and sending remain gated). Digital '
        'Gold supports PAXG, and Digital Silver supports the KMS Labs KAG '
        'ERC20 token, both on Ethereum mainnet. Only the actions enabled '
        'for that asset and network are available. Network, provider and '
        'issuer restrictions can make transfers unavailable. Other '
        'categories remain Coming soon, not live holdings integrations.',
  ),
  FaqEntry(
    id: 'is-crypto-custodial',
    category: 'crypto',
    question: 'Is Assets custodial?',
    answer: 'No. Assets is non-custodial. Your keys are on '
        'your device; Svaultai cannot move your crypto without '
        'your local signature.',
  ),
  FaqEntry(
    id: 'can-vaultai-move-crypto',
    category: 'crypto',
    question: 'Can Svaultai move my crypto?',
    answer: 'No. Svaultai cannot broadcast a transaction without '
        'your PIN unlock, trusted device, local signing, and '
        'explicit confirmation. It never auto-sends.',
  ),
  FaqEntry(
    id: 'pin-before-sending',
    category: 'crypto',
    question: 'Why do I need a PIN before sending?',
    answer: 'The PIN unlocks the local signing key. Without it '
        'your device cannot sign a transaction, and Svaultai '
        'will not accept an unsigned send request.',
  ),
  FaqEntry(
    id: 'usdt-erc20-vs-trc20',
    category: 'crypto',
    question: 'Why does USDT have ERC20 and TRC20?',
    answer: 'USDT exists on multiple networks. Svaultai supports '
        'USDT ERC20 on Ethereum and USDT TRC20 on TRON. You '
        'must pick the correct network — addresses, fees, and '
        'transfers are network-specific and not interchangeable.',
  ),
  FaqEntry(
    id: 'usdc-uses-eth-address',
    category: 'crypto',
    question: 'Why does USDC use my Ethereum address?',
    answer: 'USDC, USDT ERC20, PAXG and KAG are ERC20 tokens on Ethereum. '
        'Your Ethereum wallet address can receive ETH, USDT '
        'ERC20, USDC ERC20, PAXG and KAG. Sending an ERC20 token spends '
        'ETH as gas.',
  ),
  FaqEntry(
    id: 'erc20-needs-eth-gas',
    category: 'crypto',
    question: 'Why do token transfers need ETH for gas?',
    answer: 'Ethereum charges gas in ETH for every transaction, '
        'including ERC20 token transfers. Without a small ETH '
        'balance, token sends such as USDT ERC20, USDC ERC20, PAXG or KAG '
        'cannot cover their network fees.',
  ),
  FaqEntry(
    id: 'gold-and-silver-tokens',
    category: 'crypto',
    question: 'What are Digital Gold and Digital Silver?',
    answer: 'Digital Gold supports Paxos PAX Gold (PAXG). Digital Silver '
        'supports the KMS Labs KAG token on Ethereum, which provides indirect '
        'silver exposure backed by native Kinesis-token reserves, not direct '
        'ownership of a silver bar. These are specific supported tokens, '
        'not a way to upload physical bullion or mint it into a token. '
        'Use Ethereum mainnet and the supported token only; native '
        'Kinesis-network KAG is not interchangeable. ETH pays network fees. '
        'Issuer eligibility, sanctions and transfer restrictions apply and '
        'can pause or freeze transfers. Read the issuer notices before '
        'receiving or sending. Svaultai does not buy, redeem or guarantee '
        'the value of these tokens.',
  ),
  FaqEntry(
    id: 'assets-coming-soon',
    category: 'crypto',
    question: 'What does Coming soon mean in Assets?',
    answer: 'Tokenized Real Estate, Diamonds and Gemstones, Artwork, Watches '
        'and Collectibles, Vehicles and Equipment, Inventory and Supply '
        'Chain Goods, and Securities and Equities do not yet have verified '
        'wallet integrations in this release. Their Coming soon pages do '
        'not show a balance, receive address, send action or transaction '
        'history. Saving a photo, document or certificate in Files does not '
        'create ownership of a tokenized asset.',
  ),
  FaqEntry(
    id: 'why-monero-different',
    category: 'crypto',
    question: 'Why is Monero different?',
    answer: 'Monero is private. A public Monero address does not '
        'reveal its balance. To show balance or activity, the '
        'wallet must scan the Monero blockchain using wallet '
        'scanning capability.',
  ),
  FaqEntry(
    id: 'monero-balance-in-browser',
    category: 'crypto',
    question: "Why can't I see my Monero balance in the browser?",
    answer: 'Real Monero scanning cannot run safely inside the web '
        'app. In web, Svaultai can show your Monero receive '
        'address, but balance and activity require the desktop '
        'or native local scanner.',
  ),
  FaqEntry(
    id: 'monero-send-disabled',
    category: 'crypto',
    question: 'Why is Monero send disabled?',
    answer: 'XMR send is disabled until real local Monero scanning '
        'and signing are implemented. This prevents fake '
        'balances, unsafe spending, or invalid transactions.',
  ),
  FaqEntry(
    id: 'buy-sell-swap',
    category: 'crypto',
    question: 'Can I buy, sell, swap, or trade crypto in Svaultai?',
    answer: 'No. Assets is for holding, receiving, and '
        'sending supported assets where enabled. It is not an '
        'exchange and does not support buy, sell, swap, trade, '
        'stake, bridge, banking, fiat deposit or cash-out features.',
  ),
  FaqEntry(
    id: 'provider-unavailable',
    category: 'crypto',
    question: 'What happens if a provider is unavailable?',
    answer: 'Svaultai shows a clear unavailable reason instead of '
        'inventing a balance. A 0 balance is shown only when '
        'the provider actually returns zero.',
  ),
  FaqEntry(
    id: 'why-balance-zero',
    category: 'crypto',
    question: 'Why does my balance say 0?',
    answer: 'A displayed 0 balance means the provider returned a '
        'real zero. If the provider was unavailable, Svaultai '
        'shows an unavailable reason instead of a fake zero.',
  ),
  FaqEntry(
    id: 'receive-when-balance-zero',
    category: 'crypto',
    question: 'Can I receive crypto even if balance is 0?',
    answer: 'Yes, when Receive is enabled for the asset and network. Share your '
        'public receive address to accept funds; incoming '
        'transfers show up when your provider reports them.',
  ),
  FaqEntry(
    id: 'crypto-when-vault-deleted',
    category: 'crypto',
    question: 'What happens to my crypto if I delete my vault?',
    answer: 'Deleting your vault does not move or delete your '
        'crypto on the blockchain. Svaultai stores encrypted '
        'wallet records locally and on the server — but the '
        'coins themselves live on-chain. Deleting your Svaultai '
        'vault removes the encrypted wallet records. If you '
        'have not backed up your wallet outside Svaultai, '
        'losing the encrypted wallet records may mean losing '
        'access to those funds. Svaultai never broadcasts '
        'crypto transactions during deletion.',
  ),
  FaqEntry(
    id: 'what-plan-am-i-on',
    category: 'billing',
    question: 'What plan am I on?',
    answer: 'Ask the assistant "what plan am I on" or open the '
        'Billing page. Svaultai shows your active plan and the '
        'storage quota it grants.',
  ),
  FaqEntry(
    id: 'storage-limits',
    category: 'billing',
    question: 'How much storage do I have?',
    answer: 'Ask the assistant "how much storage am I using" or '
        'open the Storage page. Svaultai shows used bytes, '
        'quota bytes, and percent used.',
  ),
  FaqEntry(
    id: 'storage-exceeded',
    category: 'billing',
    question: 'What happens if I exceed storage?',
    answer: 'Uploads are blocked until you free space or upgrade. '
        'Existing files remain accessible.',
  ),
  FaqEntry(
    id: 'how-do-i-upgrade',
    category: 'billing',
    question: 'How do I upgrade storage?',
    answer: 'Storage subscriptions use Apple App Store or Google Play billing. '
        'Open Storage in the supported mobile app to see available plans. '
        'Your verified storage works with the same vault on the web; '
        'web card checkout is not available.',
  ),
  FaqEntry(
    id: 'how-do-i-cancel',
    category: 'billing',
    question: 'How do I cancel or manage subscription?',
    answer: 'Open Storage and choose Manage subscription. '
        'Change or cancel your plan in the Apple App Store or Google Play '
        'account that purchased it.',
  ),
  FaqEntry(
    id: 'why-checkout-opens',
    category: 'billing',
    question: 'Why does checkout open?',
    answer: 'Apple App Store or Google Play confirms subscription payments '
        'in its own interface. Svaultai does not handle your card details '
        'or provide web card checkout.',
  ),
  FaqEntry(
    id: 'how-storage-calculated',
    category: 'billing',
    question: 'How is storage calculated?',
    answer: 'Storage counts the encrypted byte size of your '
        'uploaded files and documents. Secure items are small '
        'and typically negligible for quota.',
  ),
  FaqEntry(
    id: 'why-inactive-unpaid-deleted',
    category: 'billing',
    question: 'Can Svaultai delete my inactive vault?',
    answer: 'No. Svaultai does not delete a vault because it is inactive '
        'or unsubscribed. Permanent account deletion can only be started '
        'by the vault owner after signing in and completing the protected '
        'Delete vault confirmation flow.',
  ),
  FaqEntry(
    id: 'how-to-prevent-auto-deletion',
    category: 'billing',
    question: 'Who can delete my vault?',
    answer: 'Only the signed-in vault owner can request permanent deletion. '
        'Svaultai support and administrators do not have an account-delete '
        'control. The owner must pass the in-app security checks and enter '
        'the exact confirmation phrase before deletion can proceed.',
  ),
  FaqEntry(
    id: 'why-balance-unavailable',
    category: 'troubleshooting',
    question: 'Why is my balance unavailable?',
    answer: 'The provider for that asset did not return a value in '
        'time. Svaultai shows an honest "unavailable" state '
        'instead of a fake zero. Retry usually recovers it.',
  ),
  FaqEntry(
    id: 'why-file-not-showing',
    category: 'troubleshooting',
    question: 'Why is my file not showing?',
    answer: 'Check that the upload finished, you are in the right '
        'vault, and any active filters or search terms match. '
        'Files still analyzing may not appear in searches yet.',
  ),
  FaqEntry(
    id: 'why-chat-searches-files',
    category: 'troubleshooting',
    question: 'Why is chat searching files when I asked about '
        'something else?',
    answer: 'That is a bug. Chat should route to the correct vault '
        'category — Assets, logins, IDs, billing, '
        'storage, or activity — before falling back to file '
        'search. If a specific phrase misroutes, please tell '
        'the assistant so it can be fixed.',
  ),
  FaqEntry(
    id: 'monero-desktop-required',
    category: 'troubleshooting',
    question: 'Why does Monero say desktop app required?',
    answer: 'Monero scanning cannot run inside a browser. When the '
        'app is running in web, Monero balance and activity '
        'require the desktop or native scanner.',
  ),
  FaqEntry(
    id: 'tron-provider-unavailable',
    category: 'troubleshooting',
    question: 'Why does TRON say provider unavailable?',
    answer: 'The TRON balance provider did not respond in time. '
        'Svaultai shows unavailable instead of a fake zero. '
        'Retry usually recovers, and receive addresses remain '
        'valid regardless.',
  ),
  FaqEntry(
    id: 'why-subscription-checking',
    category: 'troubleshooting',
    question: 'Why is subscription status checking?',
    answer: 'Svaultai is fetching your latest plan state from the '
        'billing provider. It usually clears within a few '
        'seconds; if it persists, try Refresh from the Billing '
        'page.',
  ),
  FaqEntry(
    id: 'how-do-i-refresh',
    category: 'troubleshooting',
    question: 'How do I refresh my vault?',
    answer: 'Every list page has a Refresh action, and chat cards '
        'have a Retry button when data is unavailable. Pulling '
        'to refresh works on touch devices.',
  ),
  FaqEntry(
    id: 'how-do-i-report-bug',
    category: 'troubleshooting',
    question: 'How do I report a bug?',
    answer: 'There is no live customer-support team yet. Use the '
        'in-app FAQ and the AI assistant to search for a '
        'solution first. If a report-issue path is available '
        'in your build, use it; otherwise describe the problem '
        'here so the team can find and fix it.',
  ),
  FaqEntry(
    id: 'how-do-i-get-support',
    category: 'troubleshooting',
    question: 'How do I get support?',
    answer: 'Since there is no live customer-support team yet, use '
        'the in-app FAQ and the AI assistant. If a report-'
        'issue or contact-support route is available in your '
        'build, use it. Otherwise, live support contact is not '
        'available yet.',
  ),
];

List<FaqEntry> faqEntriesInCategory(String categoryId) {
  return kFaqEntries
      .where((e) => e.category == categoryId)
      .toList(growable: false);
}

List<FaqEntry> faqEntriesMatchingQuery(String rawQuery) {
  final q = rawQuery.trim().toLowerCase();
  if (q.isEmpty) return kFaqEntries;
  return kFaqEntries.where((e) {
    return e.question.toLowerCase().contains(q) ||
        e.answer.toLowerCase().contains(q);
  }).toList(growable: false);
}

FaqEntry? faqEntryById(String id) {
  for (final e in kFaqEntries) {
    if (e.id == id) return e;
  }
  return null;
}
