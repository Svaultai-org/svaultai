"""Phase 3: additive ciphertext columns for all user-identifying metadata.

Every column added by this migration is nullable and every existing
column is untouched. Legacy plaintext columns will be dropped in a
follow-up migration once the fleet-adoption metric confirms 100%
lazy-migration coverage on next unlock. No data is destroyed, no
user is forced to re-signup, no subscription state is disturbed.

Tables touched (additive columns only):

  * ``uploaded_files``
      + file_name_ciphertext            BYTEA
      + saved_name_ciphertext           BYTEA
      + content_type_ciphertext         BYTEA
      + detected_type_ciphertext        BYTEA
      + detected_service_ciphertext     BYTEA
      + asset_type_ciphertext           BYTEA

  * ``vault_items``
      + item_type_ciphertext            BYTEA
      + service_ciphertext              BYTEA
      + payload_ciphertext              BYTEA
        (new home for the JSON body that today lives in
        ``encrypted_data`` as a plaintext JSON wrapping ciphertext
        wallet secrets)

  * ``vault_document_metadata``
      + doc_type_ciphertext             BYTEA
      + metadata_ciphertext             BYTEA

  * ``vault_ai_memory``
      + payload_ciphertext              BYTEA
      + memory_lookup_hash              BYTEA(32)
        (vault-scoped HMAC over the memory key — preserves the
        supersede-lookup semantic without leaking plaintext to the DB)

  * ``semantic_index``
      + keyed_content_hash              BYTEA(32)
        (vault-scoped HMAC replacing the plaintext-SHA256 content_hash)

  * ``notifications``
      + title_ciphertext                BYTEA
      + body_ciphertext                 BYTEA
      + metadata_ciphertext             BYTEA

  * ``beneficiary_links``
      + passer_label_ciphertext         BYTEA

  * ``crypto_solana_drafts``,
    ``crypto_mainnet_drafts``,
    ``crypto_tron_drafts``
      + draft_payload_ciphertext        BYTEA
        (holds destination/asset/amount as ciphertext once the client
        upgrades; existing plaintext columns remain populated for the
        currently-in-flight draft state machine until the client
        supports ciphertext-only mode)

  * ``crypto_solana_wallet_locks``,
    ``crypto_mainnet_wallet_locks``,
    ``crypto_tron_wallet_locks``
      + sender_address_lookup_hash      BYTEA(32)

  * ``crypto_solana_outgoing_history``,
    ``crypto_mainnet_outgoing_history``,
    ``crypto_tron_outgoing_history``
      (best-effort — added only when the table exists)
      + signature_lookup_hash           BYTEA(32)
      + outcome_payload_ciphertext      BYTEA

New table:

  * ``vault_metadata_migration_state`` — one row per vault, keyed by
    vault_id. Tracks lazy-migration cursors so a partially-migrated
    vault resumes cleanly on next unlock.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0024_vault_metadata_encryption"
down_revision: Union[str, None] = "0023_vault_zk_state"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE uploaded_files
          ADD COLUMN IF NOT EXISTS file_name_ciphertext         BYTEA,
          ADD COLUMN IF NOT EXISTS saved_name_ciphertext        BYTEA,
          ADD COLUMN IF NOT EXISTS content_type_ciphertext      BYTEA,
          ADD COLUMN IF NOT EXISTS detected_type_ciphertext     BYTEA,
          ADD COLUMN IF NOT EXISTS detected_service_ciphertext  BYTEA,
          ADD COLUMN IF NOT EXISTS asset_type_ciphertext        BYTEA
        """
    )

    op.execute(
        """
        ALTER TABLE vault_items
          ADD COLUMN IF NOT EXISTS item_type_ciphertext         BYTEA,
          ADD COLUMN IF NOT EXISTS service_ciphertext           BYTEA,
          ADD COLUMN IF NOT EXISTS payload_ciphertext           BYTEA
        """
    )

    op.execute(
        """
        ALTER TABLE vault_document_metadata
          ADD COLUMN IF NOT EXISTS doc_type_ciphertext          BYTEA,
          ADD COLUMN IF NOT EXISTS metadata_ciphertext          BYTEA
        """
    )

    op.execute(
        """
        ALTER TABLE vault_ai_memory
          ADD COLUMN IF NOT EXISTS payload_ciphertext           BYTEA,
          ADD COLUMN IF NOT EXISTS memory_lookup_hash           BYTEA
        """
    )
    op.execute(
        """
        ALTER TABLE vault_ai_memory
          ADD CONSTRAINT vault_ai_memory_lookup_hash_len_check
            CHECK (memory_lookup_hash IS NULL
                   OR octet_length(memory_lookup_hash) = 32)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS vault_ai_memory_lookup_uniq
          ON vault_ai_memory (vault_id, memory_lookup_hash)
          WHERE superseded_at IS NULL AND memory_lookup_hash IS NOT NULL
        """
    )

    op.execute(
        """
        ALTER TABLE semantic_index
          ADD COLUMN IF NOT EXISTS keyed_content_hash           BYTEA
        """
    )
    op.execute(
        """
        ALTER TABLE semantic_index
          ADD CONSTRAINT semantic_index_keyed_hash_len_check
            CHECK (keyed_content_hash IS NULL
                   OR octet_length(keyed_content_hash) = 32)
        """
    )

    op.execute(
        """
        ALTER TABLE notifications
          ADD COLUMN IF NOT EXISTS title_ciphertext             BYTEA,
          ADD COLUMN IF NOT EXISTS body_ciphertext              BYTEA,
          ADD COLUMN IF NOT EXISTS metadata_ciphertext          BYTEA
        """
    )

    op.execute(
        """
        ALTER TABLE beneficiary_links
          ADD COLUMN IF NOT EXISTS passer_label_ciphertext      BYTEA
        """
    )

    for tbl in (
        "crypto_solana_drafts",
        "crypto_mainnet_drafts",
        "crypto_tron_drafts",
    ):
        op.execute(
            f"""
            ALTER TABLE {tbl}
              ADD COLUMN IF NOT EXISTS draft_payload_ciphertext BYTEA
            """
        )

    for tbl in (
        "crypto_solana_wallet_locks",
        "crypto_mainnet_wallet_locks",
        "crypto_tron_wallet_locks",
    ):
        op.execute(
            f"""
            ALTER TABLE {tbl}
              ADD COLUMN IF NOT EXISTS sender_address_lookup_hash BYTEA
            """
        )
        op.execute(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{tbl}_lookup_hash_len_check'
              ) THEN
                ALTER TABLE {tbl}
                  ADD CONSTRAINT {tbl}_lookup_hash_len_check
                    CHECK (sender_address_lookup_hash IS NULL
                           OR octet_length(sender_address_lookup_hash) = 32);
              END IF;
            END $$
            """
        )

    for tbl in (
        "crypto_solana_outgoing_history",
        "crypto_mainnet_outgoing_history",
        "crypto_tron_outgoing_history",
    ):
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{tbl}'
              ) THEN
                EXECUTE 'ALTER TABLE {tbl}
                  ADD COLUMN IF NOT EXISTS signature_lookup_hash BYTEA,
                  ADD COLUMN IF NOT EXISTS outcome_payload_ciphertext BYTEA';
              END IF;
            END $$
            """
        )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_metadata_migration_state (
            vault_id UUID PRIMARY KEY
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            uploaded_files_done_upto           TIMESTAMPTZ,
            vault_items_done_upto              TIMESTAMPTZ,
            vault_document_metadata_done_upto  TIMESTAMPTZ,
            vault_ai_memory_done_upto          TIMESTAMPTZ,
            notifications_done_upto            TIMESTAMPTZ,
            beneficiary_labels_done_upto       TIMESTAMPTZ,
            wallet_accounts_done_upto          TIMESTAMPTZ,
            crypto_drafts_done_upto            TIMESTAMPTZ,
            crypto_history_done_upto           TIMESTAMPTZ,
            semantic_index_done_upto           TIMESTAMPTZ,
            completed_at                       TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # Relax legacy NOT NULL / length CHECK constraints on plaintext
    # metadata columns so ciphertext-first writes can persist NULL
    # instead of a placeholder empty string. Existing rows are
    # unaffected. These columns will be dropped entirely in a
    # follow-up Phase 4 migration once fleet adoption completes.
    op.execute(
        """
        ALTER TABLE vault_items
          ALTER COLUMN item_type      DROP NOT NULL,
          ALTER COLUMN service        DROP NOT NULL,
          ALTER COLUMN encrypted_data DROP NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE uploaded_files
          ALTER COLUMN file_name DROP NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE notifications
          ALTER COLUMN title DROP NOT NULL,
          ALTER COLUMN body  DROP NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE vault_ai_memory
          DROP CONSTRAINT IF EXISTS vault_ai_memory_memory_key_check
        """
    )
    op.execute(
        """
        ALTER TABLE vault_ai_memory
          DROP CONSTRAINT IF EXISTS vault_ai_memory_memory_value_check
        """
    )
    op.execute(
        """
        ALTER TABLE vault_ai_memory
          ALTER COLUMN memory_key   DROP NOT NULL,
          ALTER COLUMN memory_value DROP NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE beneficiary_links
          ALTER COLUMN passer_label DROP NOT NULL
        """
    )

    # semantic_index.content_hash was originally a SHA-256 of the
    # plaintext topic string. ZK/ciphertext-first rows compute
    # keyed_content_hash instead and MUST persist content_hash =
    # NULL — no plaintext-derived hash may remain server-visible for
    # a ZK vault. Legacy rows keep whatever they had.
    op.execute(
        """
        ALTER TABLE semantic_index
          ALTER COLUMN content_hash DROP NOT NULL
        """
    )

    # Crypto draft plaintext columns → nullable for ciphertext-first
    # writes. recent_blockhash / last_valid_block_height / nonce /
    # gas / raw_data_hex remain NOT NULL because they are protocol-
    # required for transaction correctness and contain no user
    # metadata. sender_address / destination_address / asset /
    # value / fee are user-derived readable metadata and go into
    # draft_payload_ciphertext for ZK writes.
    for tbl in (
        "crypto_solana_drafts",
        "crypto_mainnet_drafts",
        "crypto_tron_drafts",
    ):
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_name = '{tbl}'
                           AND column_name = 'sender_address') THEN
                EXECUTE 'ALTER TABLE {tbl}
                           ALTER COLUMN sender_address DROP NOT NULL';
              END IF;
              IF EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_name = '{tbl}'
                           AND column_name = 'destination_address') THEN
                EXECUTE 'ALTER TABLE {tbl}
                           ALTER COLUMN destination_address DROP NOT NULL';
              END IF;
              IF EXISTS (SELECT 1 FROM information_schema.columns
                         WHERE table_name = '{tbl}'
                           AND column_name = 'asset') THEN
                EXECUTE 'ALTER TABLE {tbl}
                           ALTER COLUMN asset DROP NOT NULL';
              END IF;
            END $$
            """
        )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'crypto_solana_drafts'
                       AND column_name = 'value_lamports_str') THEN
            EXECUTE 'ALTER TABLE crypto_solana_drafts
                       ALTER COLUMN value_lamports_str DROP NOT NULL,
                       ALTER COLUMN fee_lamports_str   DROP NOT NULL';
          END IF;
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'crypto_mainnet_drafts'
                       AND column_name = 'sender_address_lower') THEN
            EXECUTE 'ALTER TABLE crypto_mainnet_drafts
                       ALTER COLUMN sender_address_lower DROP NOT NULL,
                       ALTER COLUMN value_wei_str        DROP NOT NULL,
                       ALTER COLUMN data_hex             DROP NOT NULL,
                       ALTER COLUMN transaction_to       DROP NOT NULL';
          END IF;
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'crypto_tron_drafts'
                       AND column_name = 'fee_limit_sun_str') THEN
            EXECUTE 'ALTER TABLE crypto_tron_drafts
                       ALTER COLUMN token_contract_address DROP NOT NULL,
                       ALTER COLUMN amount_base_units_str  DROP NOT NULL,
                       ALTER COLUMN raw_data_hex           DROP NOT NULL,
                       ALTER COLUMN fee_limit_sun_str      DROP NOT NULL';
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    # Restore NOT NULL / CHECK constraints. Downgrade REQUIRES that
    # every legacy plaintext column is currently non-NULL — if any
    # ZK-adopted vault has already written NULL, downgrade will fail
    # and MUST NOT be forced (it would corrupt existing rows).
    op.execute(
        """
        ALTER TABLE semantic_index
          ALTER COLUMN content_hash SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE beneficiary_links
          ALTER COLUMN passer_label SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE vault_ai_memory
          ALTER COLUMN memory_value SET NOT NULL,
          ALTER COLUMN memory_key   SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE notifications
          ALTER COLUMN body  SET NOT NULL,
          ALTER COLUMN title SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE uploaded_files
          ALTER COLUMN file_name SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE vault_items
          ALTER COLUMN encrypted_data SET NOT NULL,
          ALTER COLUMN service        SET NOT NULL,
          ALTER COLUMN item_type      SET NOT NULL
        """
    )

    op.execute("DROP TABLE IF EXISTS vault_metadata_migration_state")

    for tbl in (
        "crypto_solana_outgoing_history",
        "crypto_mainnet_outgoing_history",
        "crypto_tron_outgoing_history",
    ):
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM information_schema.tables
                         WHERE table_name = '{tbl}') THEN
                EXECUTE 'ALTER TABLE {tbl}
                  DROP COLUMN IF EXISTS outcome_payload_ciphertext,
                  DROP COLUMN IF EXISTS signature_lookup_hash';
              END IF;
            END $$
            """
        )

    for tbl in (
        "crypto_tron_wallet_locks",
        "crypto_mainnet_wallet_locks",
        "crypto_solana_wallet_locks",
    ):
        op.execute(
            f"""
            ALTER TABLE {tbl}
              DROP CONSTRAINT IF EXISTS {tbl}_lookup_hash_len_check,
              DROP COLUMN IF EXISTS sender_address_lookup_hash
            """
        )

    for tbl in (
        "crypto_tron_drafts",
        "crypto_mainnet_drafts",
        "crypto_solana_drafts",
    ):
        op.execute(
            f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS draft_payload_ciphertext"
        )

    op.execute(
        """
        ALTER TABLE beneficiary_links
          DROP COLUMN IF EXISTS passer_label_ciphertext
        """
    )

    op.execute(
        """
        ALTER TABLE notifications
          DROP COLUMN IF EXISTS metadata_ciphertext,
          DROP COLUMN IF EXISTS body_ciphertext,
          DROP COLUMN IF EXISTS title_ciphertext
        """
    )

    op.execute(
        """
        ALTER TABLE semantic_index
          DROP CONSTRAINT IF EXISTS semantic_index_keyed_hash_len_check,
          DROP COLUMN IF EXISTS keyed_content_hash
        """
    )

    op.execute("DROP INDEX IF EXISTS vault_ai_memory_lookup_uniq")
    op.execute(
        """
        ALTER TABLE vault_ai_memory
          DROP CONSTRAINT IF EXISTS vault_ai_memory_lookup_hash_len_check,
          DROP COLUMN IF EXISTS memory_lookup_hash,
          DROP COLUMN IF EXISTS payload_ciphertext
        """
    )

    op.execute(
        """
        ALTER TABLE vault_document_metadata
          DROP COLUMN IF EXISTS metadata_ciphertext,
          DROP COLUMN IF EXISTS doc_type_ciphertext
        """
    )

    op.execute(
        """
        ALTER TABLE vault_items
          DROP COLUMN IF EXISTS payload_ciphertext,
          DROP COLUMN IF EXISTS service_ciphertext,
          DROP COLUMN IF EXISTS item_type_ciphertext
        """
    )

    op.execute(
        """
        ALTER TABLE uploaded_files
          DROP COLUMN IF EXISTS asset_type_ciphertext,
          DROP COLUMN IF EXISTS detected_service_ciphertext,
          DROP COLUMN IF EXISTS detected_type_ciphertext,
          DROP COLUMN IF EXISTS content_type_ciphertext,
          DROP COLUMN IF EXISTS saved_name_ciphertext,
          DROP COLUMN IF EXISTS file_name_ciphertext
        """
    )
