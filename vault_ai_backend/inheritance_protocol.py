"""Version markers shared by legacy and private inheritance routes."""

import os

# `beneficiary_links.wrapped_vault_key` is NOT NULL. Private V2 links do not
# have a server-side vault key; this value is a protocol discriminator only.
ZK_BENEFICIARY_V2_MARKER = "zk-beneficiary-v2:no-server-key"
ZK_BENEFICIARY_V2_CRYPTO_VERSION = 2


def zk_beneficiary_v2_enabled() -> bool:
    return os.getenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
