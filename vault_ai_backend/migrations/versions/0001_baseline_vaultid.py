

from typing import Sequence, Union

from alembic import op


revision: str = "0001_baseline_vaultid"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INCLUDED_BYTES          = 1_073_741_824                               
BLOCK_BYTES             = 53_687_091_200                           
BLOCK_PRICE_CENTS_USD   = 2500                                         
SELF_SERVICE_MAX_BLOCKS = 100                                                

                                         
KDF_TARGET_ITERATIONS_DEFAULT = 600000

                                                                       
ACCOUNT_TYPES_SQL    = "'individual','organization'"
SALES_CHANNELS_SQL   = "'self_service','enterprise'"
MEMBER_ROLES_SQL     = "'owner','admin','member'"
MEMBER_STATUSES_SQL  = "'active','invited','suspended'"
SUB_STATUSES_SQL = (
    "'none','active','in_grace','past_due','canceled_pending','expired',"
    "'paused','refunded','over_quota_grace','over_quota_locked'"
)
SUB_SOURCES_SQL = (
    "'none','apple','google','stripe','paypal','enterprise','admin_grant'"
)
BILLING_PERIODS_SQL = "'monthly','annual'"

                                      
ALLOWED_TAGS_SQL = (
    "'travel','finance','legal','medical','business','education',"
    "'identity','government','security','personal','media','receipt','tax'"
)

                                                     
DOC_TYPES_SQL = (
    "'passport','visa','boarding_pass','ticket','hotel_itinerary',"
    "'receipt','invoice','contract','agreement','degree','certificate',"
    "'insurance','driver_license','id_card','tax_document','medical_record'"
)

                                                           
MEMORY_TYPES_SQL = (
    "'identity','travel','preference','project','company',"
    "'goal','location','relationship','note',"
    "'family','date','life_event'"
)

                                                   
LOCALES_SQL = "'en','ar','fr','es','ja','ko','zh'"

                             
SCRIPTS_SQL = "'latin','arabic','cjk','hangul','other'"

                                                          
CATEGORY_SQL = (
    "'bank','wallet','exchange','social','travel','commerce',"
    "'media','government','business','unknown'"
)

                                    
SERVICE_CATEGORY_SOURCES_SQL = "'llm','manual'"

                          
RELATION_TYPES_SQL = (
    "'travel_related','identity_related','business_related',"
    "'finance_related','tax_related','medical_related',"
    "'family_related','security_related','media_related',"
    "'inheritance_related'"
)

                                         
ENTITY_TYPES_SQL = (
    "'identity','travel','government','finance','tax','business',"
    "'medical','education','insurance','legal','personal','other'"
)

                      
EXPIRY_SOURCE_KINDS_SQL = "'uploaded_file','vault_item','inheritance','memory'"
EXPIRY_TYPES_SQL = (
    "'passport','visa','id_card','driver_license','insurance',"
    "'tax','contract','subscription','inheritance','custom'"
)
EXPIRY_SEVERITIES_SQL = "'info','warning','critical'"
EXPIRY_STATUSES_SQL   = "'active','dismissed','expired','resolved'"

                        
USERNAME_ALLOWED_CHARS_SQL = (
    "'letters_numbers',"
    "'letters_numbers_underscore',"
    "'letters_numbers_dot_underscore',"
    "'email'"
)
USERNAME_CONFIDENCES_SQL = "'official','inferred','unknown'"


def upgrade() -> None:
    import os

    _debug = os.getenv("VAULTAI_ALEMBIC_DEBUG", "").strip() not in ("", "0", "false", "False")
    if _debug:
        print("[ALEMBIC] upgrade.enter revision=0001_baseline_vaultid", flush=True)

                                                                        
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")                     
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")              
    if _debug:
        print("[ALEMBIC] upgrade.extensions.created", flush=True)

                                                                        
    op.execute(
        f"""
        CREATE TABLE accounts (
            account_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            account_type          TEXT        NOT NULL
                CHECK (account_type IN ({ACCOUNT_TYPES_SQL})),
            display_name          TEXT
                CHECK (display_name IS NULL OR length(display_name) BETWEEN 1 AND 200),
            sales_channel         TEXT        NOT NULL
                CHECK (sales_channel IN ({SALES_CHANNELS_SQL})),
            billing_owner_vault_id UUID,
            slug                  TEXT        UNIQUE
                CHECK (slug IS NULL OR length(slug) BETWEEN 1 AND 100),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT individuals_are_self_service
              CHECK (account_type = 'organization'
                     OR sales_channel = 'self_service'),

            CONSTRAINT orgs_have_a_name
              CHECK (account_type = 'individual' OR display_name IS NOT NULL)
        );
        """
    )
    op.execute(
        "CREATE INDEX accounts_billing_owner_idx "
        "ON accounts(billing_owner_vault_id);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vaults (
            vault_id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_name               TEXT        NOT NULL UNIQUE
                CHECK (length(vault_name) BETWEEN 1 AND 200),
            display_username         TEXT
                CHECK (display_username IS NULL OR length(display_username) BETWEEN 1 AND 200),
            pin_salt                 TEXT        NOT NULL,
            pin_verifier             TEXT        NOT NULL,
            kdf_iterations           INTEGER     NOT NULL DEFAULT {KDF_TARGET_ITERATIONS_DEFAULT}
                CHECK (kdf_iterations >= 100000),
            kdf_algorithm            TEXT        NOT NULL DEFAULT 'pbkdf2_sha256',
            failed_pin_attempts      INTEGER     NOT NULL DEFAULT 0
                CHECK (failed_pin_attempts >= 0),
            locked_until             TIMESTAMPTZ,
            must_reset               BOOLEAN     NOT NULL DEFAULT FALSE,
            frozen_until             TIMESTAMPTZ,
            inherited_from_label     TEXT,
            total_bytes              BIGINT      NOT NULL DEFAULT 0
                CHECK (total_bytes >= 0),
            account_id               UUID
                REFERENCES accounts(account_id) ON DELETE SET NULL,
            acknowledged_irrecoverable BOOLEAN   NOT NULL DEFAULT FALSE,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX vaults_account_idx ON vaults(account_id);")
    if _debug:
        print("[ALEMBIC] upgrade.vaults.created", flush=True)

                                                                         
    op.execute(
        """
        ALTER TABLE accounts
        ADD CONSTRAINT accounts_billing_owner_vault_fk
        FOREIGN KEY (billing_owner_vault_id)
        REFERENCES vaults(vault_id) ON DELETE SET NULL;
        """
    )

                                                                        
    op.execute(
        """
        CREATE TABLE auth_sessions (
            token_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id      UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            device_id     TEXT,
            issued_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at    TIMESTAMPTZ NOT NULL,
            revoked_at    TIMESTAMPTZ,
            last_used_at  TIMESTAMPTZ,
            CHECK (expires_at > issued_at)
        );
        """
    )
    op.execute(
        "CREATE INDEX auth_sessions_vault_idx "
        "ON auth_sessions(vault_id, revoked_at);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE account_members (
            account_id  UUID        NOT NULL
                REFERENCES accounts(account_id) ON DELETE CASCADE,
            vault_id    UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            role        TEXT        NOT NULL DEFAULT 'owner'
                CHECK (role IN ({MEMBER_ROLES_SQL})),
            status      TEXT        NOT NULL DEFAULT 'active'
                CHECK (status IN ({MEMBER_STATUSES_SQL})),
            added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (account_id, vault_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX account_members_vault_idx "
        "ON account_members(vault_id);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE account_subscriptions (
            account_id                     UUID        PRIMARY KEY
                REFERENCES accounts(account_id) ON DELETE CASCADE,
            status                         TEXT        NOT NULL DEFAULT 'none'
                CHECK (status IN ({SUB_STATUSES_SQL})),
            source                         TEXT        NOT NULL DEFAULT 'none'
                CHECK (source IN ({SUB_SOURCES_SQL})),
            source_subscription_id         TEXT,
            stripe_subscription_item_id    TEXT,
            billing_period                 TEXT
                CHECK (billing_period IS NULL
                       OR billing_period IN ({BILLING_PERIODS_SQL})),
            block_count                    INTEGER     NOT NULL DEFAULT 0
                CHECK (block_count >= 0),
            purchased_bytes                BIGINT      NOT NULL DEFAULT 0
                CHECK (purchased_bytes >= 0),
            storage_bytes_grant            BIGINT      NOT NULL DEFAULT 0
                CHECK (storage_bytes_grant >= 0),
            storage_bytes_grant_expires_at TIMESTAMPTZ,
            current_period_start           TIMESTAMPTZ,
            current_period_end             TIMESTAMPTZ,
            cancel_at_period_end           BOOLEAN     NOT NULL DEFAULT FALSE,
            canceled_at                    TIMESTAMPTZ,
            grace_period_ends_at           TIMESTAMPTZ,
            over_quota_grace_ends_at       TIMESTAMPTZ,
            metadata_jsonb                 JSONB       NOT NULL DEFAULT '{{}}'::JSONB,
            created_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT purchased_bytes_matches_blocks
              CHECK (purchased_bytes = block_count * {BLOCK_BYTES})
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX account_subscriptions_source_subid_uniq "
        "ON account_subscriptions(source, source_subscription_id) "
        "WHERE source_subscription_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX account_subscriptions_unique_stripe_item_idx "
        "ON account_subscriptions(stripe_subscription_item_id) "
        "WHERE stripe_subscription_item_id IS NOT NULL;"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE subscription_events (
            id                    BIGSERIAL   PRIMARY KEY,
            account_id            UUID        NOT NULL,
            event_type            TEXT        NOT NULL
                CHECK (length(event_type) BETWEEN 1 AND 64),
            source                TEXT        NOT NULL,
            source_event_id       TEXT,
            sales_channel         TEXT        NOT NULL,
            from_block_count      INTEGER,
            to_block_count        INTEGER,
            from_purchased_bytes  BIGINT,
            to_purchased_bytes    BIGINT,
            occurred_at           TIMESTAMPTZ NOT NULL,
            recorded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            payload_jsonb         JSONB       NOT NULL DEFAULT '{}'::JSONB
        );
        """
    )
    op.execute(
        "CREATE INDEX subscription_events_account_idx "
        "ON subscription_events(account_id, occurred_at DESC);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE provider_event_log (
            source             TEXT        NOT NULL
                CHECK (source IN ('apple','google','stripe','paypal')),
            source_event_id    TEXT        NOT NULL,
            signature_verified BOOLEAN     NOT NULL,
            environment        TEXT        NOT NULL
                CHECK (environment IN ('sandbox','production')),
            received_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at       TIMESTAMPTZ,
            outcome            TEXT,
            error_text         TEXT,
            raw_payload_jsonb  JSONB       NOT NULL,
            PRIMARY KEY (source, source_event_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX provider_event_log_received_idx "
        "ON provider_event_log(received_at DESC);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE storage_skus (
            sku_key            TEXT        PRIMARY KEY
                CHECK (length(sku_key) BETWEEN 1 AND 64),
            block_count        INTEGER     NOT NULL
                CHECK (block_count >= 1),
            billing_period     TEXT        NOT NULL DEFAULT 'monthly'
                CHECK (billing_period IN ('monthly','annual')),
            apple_product_id   TEXT        UNIQUE,
            google_product_id  TEXT        UNIQUE,
            stripe_price_id    TEXT        UNIQUE,
            paypal_plan_id     TEXT        UNIQUE,
            is_archived        BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

                                                                        
    op.execute(
        """
        CREATE TABLE storage_pricing (
            key           TEXT        PRIMARY KEY
                CHECK (length(key) BETWEEN 1 AND 64),
            value         BIGINT      NOT NULL CHECK (value >= 0),
            effective_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes         TEXT
        );
        """
    )

                                                                        
    op.execute(
        """
        CREATE TABLE account_storage_totals (
            account_id      UUID        PRIMARY KEY
                REFERENCES accounts(account_id) ON DELETE CASCADE,
            encrypted_bytes BIGINT      NOT NULL DEFAULT 0
                CHECK (encrypted_bytes >= 0),
            last_recomputed TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

                                                                        
    op.execute(
        """
        CREATE TABLE contact_sales_requests (
            id                BIGSERIAL   PRIMARY KEY,
            account_id        UUID
                REFERENCES accounts(account_id) ON DELETE SET NULL,
            vault_id          UUID
                REFERENCES vaults(vault_id) ON DELETE SET NULL,
            email             TEXT        NOT NULL
                CHECK (length(email) BETWEEN 3 AND 320 AND email LIKE '%_@_%'),
            company_name      TEXT
                CHECK (company_name IS NULL OR length(company_name) BETWEEN 1 AND 200),
            requested_blocks  INTEGER
                CHECK (requested_blocks IS NULL OR requested_blocks >= 1),
            message           TEXT
                CHECK (message IS NULL OR length(message) BETWEEN 1 AND 4000),
            status            TEXT        NOT NULL DEFAULT 'new'
                CHECK (status IN ('new','contacted','closed','spam')),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX contact_sales_requests_status_idx "
        "ON contact_sales_requests(status, created_at DESC);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE stripe_customers (
            account_id          UUID        PRIMARY KEY
                REFERENCES accounts(account_id) ON DELETE CASCADE,
            stripe_customer_id  TEXT        NOT NULL UNIQUE
                CHECK (stripe_customer_id LIKE 'cus_%'
                       AND length(stripe_customer_id) BETWEEN 5 AND 100),
            livemode            BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX stripe_customers_livemode_idx "
        "ON stripe_customers(livemode);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE vault_items (
            id             SERIAL      PRIMARY KEY,
            vault_id       UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            item_type      TEXT        NOT NULL,
            service        TEXT        NOT NULL,
            encrypted_data TEXT        NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX vault_items_lookup_idx "
        "ON vault_items(vault_id, service, created_at DESC);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE uploaded_files (
            id                        TEXT        PRIMARY KEY,
            vault_id                  UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            file_name                 TEXT        NOT NULL,
            content_type              TEXT,
            file_size                 BIGINT      NOT NULL CHECK (file_size >= 0),
            encrypted_file_data       TEXT,
            extracted_text            TEXT,
            extracted_text_encrypted  BOOLEAN     NOT NULL DEFAULT FALSE,
            detected_type             TEXT,
            detected_service          TEXT,
            autosaved_secret          BOOLEAN     NOT NULL DEFAULT FALSE,
            saved_name                TEXT,
            asset_type                TEXT        DEFAULT 'file',
            needs_naming              BOOLEAN     NOT NULL DEFAULT FALSE,
            storage_mode              TEXT        NOT NULL DEFAULT 'inline'
                CHECK (storage_mode IN ('inline','chunked')),
            chunk_size                INTEGER,
            chunk_count               INTEGER,
            upload_status             TEXT        NOT NULL DEFAULT 'complete'
                CHECK (upload_status IN ('pending','complete','failed')),
            created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX uploaded_files_lookup_idx "
        "ON uploaded_files(vault_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX uploaded_files_saved_name_idx "
        "ON uploaded_files(vault_id, saved_name, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX uploaded_files_status_idx "
        "ON uploaded_files(vault_id, upload_status, created_at DESC);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE uploaded_file_chunks (
            file_id     TEXT        NOT NULL
                REFERENCES uploaded_files(id) ON DELETE CASCADE,
            chunk_index INTEGER     NOT NULL,
            chunk_bytes BYTEA       NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (file_id, chunk_index)
        );
        """
    )

                                                                        
    op.execute(
        """
        CREATE TABLE beneficiary_links (
            id                     SERIAL      PRIMARY KEY,
            passer_vault_id        UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            passer_label           TEXT        NOT NULL,
            beneficiary_vault_id   UUID
                REFERENCES vaults(vault_id) ON DELETE SET NULL,
            pairing_code_hash      TEXT,
            pairing_expires_at     TIMESTAMPTZ,
            wrapped_vault_key      TEXT        NOT NULL,
            status                 TEXT        NOT NULL DEFAULT 'pairing_pending',
            transfer_requested_at  TIMESTAMPTZ,
            transfer_executes_at   TIMESTAMPTZ,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX beneficiary_links_passer_idx "
        "ON beneficiary_links(passer_vault_id);"
    )
    op.execute(
        "CREATE INDEX beneficiary_links_beneficiary_idx "
        "ON beneficiary_links(beneficiary_vault_id) "
        "WHERE beneficiary_vault_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX beneficiary_links_pairing_code_idx "
        "ON beneficiary_links(pairing_code_hash) "
        "WHERE pairing_code_hash IS NOT NULL;"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE notifications (
            id         BIGSERIAL   PRIMARY KEY,
            vault_id   UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            kind       TEXT        NOT NULL,
            title      TEXT        NOT NULL,
            body       TEXT        NOT NULL,
            metadata   TEXT,
            read_at    TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX notifications_vault_unread_idx "
        "ON notifications(vault_id, read_at, created_at DESC);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE trusted_devices (
            vault_id          UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            device_id         TEXT        NOT NULL,
            label             TEXT,
            user_agent_brand  TEXT,
            last_ip_prefix    TEXT,
            approx_city       TEXT,
            status            TEXT        NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','trusted','revoked')),
            cooldown_until    TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            approved_at       TIMESTAMPTZ,
            revoked_at        TIMESTAMPTZ,
            last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (vault_id, device_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX trusted_devices_status_idx "
        "ON trusted_devices(vault_id, status, last_seen_at DESC);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE semantic_index (
            id                BIGSERIAL    PRIMARY KEY,
            vault_id          UUID         NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            source_kind       TEXT         NOT NULL
                CHECK (source_kind IN (
                    'file_name',
                    'saved_name',
                    'asset_type',
                    'detected_service',
                    'item_service',
                    'item_type',
                    'semantic_profile'
                )),
            uploaded_file_id  TEXT         REFERENCES uploaded_files(id) ON DELETE CASCADE,
            vault_item_id     INTEGER      REFERENCES vault_items(id)    ON DELETE CASCADE,
            embedding         vector(1536) NOT NULL,
            content_hash      BYTEA        NOT NULL,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CHECK ((uploaded_file_id IS NOT NULL)::int +
                   (vault_item_id    IS NOT NULL)::int = 1)
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX semantic_index_uniq_file "
        "ON semantic_index(vault_id, source_kind, uploaded_file_id) "
        "WHERE uploaded_file_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX semantic_index_uniq_item "
        "ON semantic_index(vault_id, source_kind, vault_item_id) "
        "WHERE vault_item_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX semantic_index_vault_kind_idx "
        "ON semantic_index(vault_id, source_kind);"
    )
    op.execute(
        "CREATE INDEX semantic_index_embedding_idx "
        "ON semantic_index USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vault_asset_tags (
            id                BIGSERIAL   PRIMARY KEY,
            vault_id          UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            source_kind       TEXT        NOT NULL
                CHECK (source_kind IN ('uploaded_file','vault_item')),
            uploaded_file_id  TEXT        REFERENCES uploaded_files(id) ON DELETE CASCADE,
            vault_item_id     INTEGER     REFERENCES vault_items(id)    ON DELETE CASCADE,
            tag               TEXT        NOT NULL
                CHECK (tag IN ({ALLOWED_TAGS_SQL})),
            confidence        REAL        NOT NULL DEFAULT 1.0
                CHECK (confidence >= 0.0 AND confidence <= 1.0),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK ((uploaded_file_id IS NOT NULL)::int +
                   (vault_item_id    IS NOT NULL)::int = 1)
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_asset_tags_uniq_file "
        "ON vault_asset_tags(vault_id, uploaded_file_id, tag) "
        "WHERE uploaded_file_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_asset_tags_uniq_item "
        "ON vault_asset_tags(vault_id, vault_item_id, tag) "
        "WHERE vault_item_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX vault_asset_tags_vault_tag_idx "
        "ON vault_asset_tags(vault_id, tag);"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE vault_password_audit (
            id                       BIGSERIAL   PRIMARY KEY,
            vault_id                 UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            vault_item_id            INTEGER     NOT NULL
                REFERENCES vault_items(id) ON DELETE CASCADE,
            password_hash_sha256     BYTEA       NOT NULL,
            password_strength_score  INTEGER     NOT NULL
                CHECK (password_strength_score BETWEEN 0 AND 100),
            generated_by_vaultai     BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (vault_id, vault_item_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX vault_password_audit_vault_idx "
        "ON vault_password_audit(vault_id);"
    )
    op.execute(
        "CREATE INDEX vault_password_audit_vault_hash_idx "
        "ON vault_password_audit(vault_id, password_hash_sha256);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vault_document_metadata (
            id                BIGSERIAL   PRIMARY KEY,
            vault_id          UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            uploaded_file_id  TEXT        NOT NULL
                REFERENCES uploaded_files(id) ON DELETE CASCADE,
            doc_type          TEXT        NOT NULL
                CHECK (doc_type IN ({DOC_TYPES_SQL})),
            metadata_json     JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            confidence        REAL        NOT NULL DEFAULT 1.0
                CHECK (confidence >= 0.0 AND confidence <= 1.0),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (vault_id, uploaded_file_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX vault_document_metadata_vault_type_idx "
        "ON vault_document_metadata(vault_id, doc_type);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vault_ai_memory (
            id                    BIGSERIAL   PRIMARY KEY,
            vault_id              UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            memory_type           TEXT        NOT NULL
                CHECK (memory_type IN ({MEMORY_TYPES_SQL})),
            memory_key            TEXT        NOT NULL
                CHECK (length(memory_key)   BETWEEN 1 AND 100),
            memory_value          TEXT        NOT NULL
                CHECK (length(memory_value) BETWEEN 1 AND 500),
            confidence            REAL        NOT NULL DEFAULT 1.0
                CHECK (confidence >= 0.0 AND confidence <= 1.0),
            source                TEXT        NOT NULL DEFAULT 'chat'
                CHECK (source IN ('chat')),
            event_date            DATE,
            superseded_at         TIMESTAMPTZ,
            superseded_by_id      BIGINT,
            memory_language       TEXT
                CHECK (memory_language IS NULL OR memory_language IN ({LOCALES_SQL})),
            memory_script         TEXT
                CHECK (memory_script   IS NULL OR memory_script   IN ({SCRIPTS_SQL})),
            memory_normalized_key TEXT
                CHECK (memory_normalized_key IS NULL OR length(memory_normalized_key) BETWEEN 1 AND 200),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
                                                       
    op.execute(
        """
        ALTER TABLE vault_ai_memory
        ADD CONSTRAINT vault_ai_memory_superseded_by_fk
        FOREIGN KEY (superseded_by_id)
        REFERENCES vault_ai_memory(id) ON DELETE SET NULL;
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_ai_memory_active_uniq "
        "ON vault_ai_memory(vault_id, memory_type, memory_key) "
        "WHERE superseded_at IS NULL;"
    )
    op.execute(
        "CREATE INDEX vault_ai_memory_vault_type_idx "
        "ON vault_ai_memory(vault_id, memory_type);"
    )
    op.execute(
        "CREATE INDEX vault_ai_memory_vault_idx "
        "ON vault_ai_memory(vault_id);"
    )
    op.execute(
        "CREATE INDEX vault_ai_memory_event_date_idx "
        "ON vault_ai_memory(vault_id, event_date) "
        "WHERE event_date IS NOT NULL AND superseded_at IS NULL;"
    )
    op.execute(
        "CREATE INDEX vault_ai_memory_superseded_chain_idx "
        "ON vault_ai_memory(vault_id, memory_type, memory_key) "
        "WHERE superseded_at IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX vault_ai_memory_normkey_idx "
        "ON vault_ai_memory(vault_id, memory_normalized_key) "
        "WHERE memory_normalized_key IS NOT NULL AND superseded_at IS NULL;"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vault_preferences (
            vault_id         UUID        PRIMARY KEY
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            preferred_locale TEXT        NOT NULL DEFAULT 'en'
                CHECK (preferred_locale IN ({LOCALES_SQL})),
            chat_language    TEXT
                CHECK (chat_language   IS NULL OR chat_language   IN ({LOCALES_SQL})),
            ui_language      TEXT
                CHECK (ui_language     IS NULL OR ui_language     IN ({LOCALES_SQL})),
            memory_language  TEXT
                CHECK (memory_language IS NULL OR memory_language IN ({LOCALES_SQL})),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vault_service_categories (
            id           BIGSERIAL   PRIMARY KEY,
            service_name TEXT        NOT NULL
                CHECK (length(service_name) BETWEEN 1 AND 200),
            locale       TEXT        NOT NULL DEFAULT 'en'
                CHECK (locale IN ({LOCALES_SQL})),
            category     TEXT        NOT NULL
                CHECK (category IN ({CATEGORY_SQL})),
            confidence   REAL        NOT NULL DEFAULT 1.0
                CHECK (confidence >= 0.0 AND confidence <= 1.0),
            source       TEXT        NOT NULL DEFAULT 'llm'
                CHECK (source IN ({SERVICE_CATEGORY_SOURCES_SQL})),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (service_name, locale)
        );
        """
    )
    op.execute(
        "CREATE INDEX vault_service_categories_lookup_idx "
        "ON vault_service_categories(service_name, locale);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vault_relationships (
            id              BIGSERIAL   PRIMARY KEY,
            vault_id        UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            source_kind     TEXT        NOT NULL
                CHECK (source_kind IN ('uploaded_file','vault_item')),
            source_file_id  TEXT        REFERENCES uploaded_files(id) ON DELETE CASCADE,
            source_item_id  INTEGER     REFERENCES vault_items(id)    ON DELETE CASCADE,
            target_kind     TEXT        NOT NULL
                CHECK (target_kind IN ('uploaded_file','vault_item')),
            target_file_id  TEXT        REFERENCES uploaded_files(id) ON DELETE CASCADE,
            target_item_id  INTEGER     REFERENCES vault_items(id)    ON DELETE CASCADE,
            relation_type   TEXT        NOT NULL
                CHECK (relation_type IN ({RELATION_TYPES_SQL})),
            confidence      REAL        NOT NULL DEFAULT 1.0
                CHECK (confidence >= 0.0 AND confidence <= 1.0),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CHECK ((source_file_id IS NOT NULL)::int + (source_item_id IS NOT NULL)::int = 1),
            CHECK ((target_file_id IS NOT NULL)::int + (target_item_id IS NOT NULL)::int = 1),
            CHECK ((source_kind = 'uploaded_file' AND source_file_id IS NOT NULL)
                OR (source_kind = 'vault_item'    AND source_item_id IS NOT NULL)),
            CHECK ((target_kind = 'uploaded_file' AND target_file_id IS NOT NULL)
                OR (target_kind = 'vault_item'    AND target_item_id IS NOT NULL)),
            CHECK (NOT (
                source_kind = target_kind
                AND source_file_id IS NOT DISTINCT FROM target_file_id
                AND source_item_id IS NOT DISTINCT FROM target_item_id
            ))
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_relationships_uniq_ff "
        "ON vault_relationships(vault_id, source_file_id, target_file_id, relation_type) "
        "WHERE source_file_id IS NOT NULL AND target_file_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_relationships_uniq_fi "
        "ON vault_relationships(vault_id, source_file_id, target_item_id, relation_type) "
        "WHERE source_file_id IS NOT NULL AND target_item_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_relationships_uniq_if "
        "ON vault_relationships(vault_id, source_item_id, target_file_id, relation_type) "
        "WHERE source_item_id IS NOT NULL AND target_file_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_relationships_uniq_ii "
        "ON vault_relationships(vault_id, source_item_id, target_item_id, relation_type) "
        "WHERE source_item_id IS NOT NULL AND target_item_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX vault_relationships_src_file_idx "
        "ON vault_relationships(vault_id, source_file_id) WHERE source_file_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX vault_relationships_tgt_file_idx "
        "ON vault_relationships(vault_id, target_file_id) WHERE target_file_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX vault_relationships_src_item_idx "
        "ON vault_relationships(vault_id, source_item_id) WHERE source_item_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX vault_relationships_tgt_item_idx "
        "ON vault_relationships(vault_id, target_item_id) WHERE target_item_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX vault_relationships_relation_idx "
        "ON vault_relationships(vault_id, relation_type);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vault_expiry_alerts (
            id                BIGSERIAL   PRIMARY KEY,
            vault_id          UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            source_kind       TEXT        NOT NULL
                CHECK (source_kind IN ({EXPIRY_SOURCE_KINDS_SQL})),
            source_file_id    TEXT        REFERENCES uploaded_files(id) ON DELETE CASCADE,
            source_item_id    INTEGER     REFERENCES vault_items(id)    ON DELETE CASCADE,
            expiry_type       TEXT        NOT NULL
                CHECK (expiry_type IN ({EXPIRY_TYPES_SQL})),
            expiry_date       DATE        NOT NULL,
            alert_window_days INTEGER     NOT NULL
                CHECK (alert_window_days > 0 AND alert_window_days <= 3650),
            severity          TEXT        NOT NULL
                CHECK (severity IN ({EXPIRY_SEVERITIES_SQL})),
            status            TEXT        NOT NULL DEFAULT 'active'
                CHECK (status IN ({EXPIRY_STATUSES_SQL})),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CHECK (
                (source_kind = 'uploaded_file' AND source_file_id IS NOT NULL AND source_item_id IS NULL)
             OR (source_kind = 'vault_item'   AND source_file_id IS NULL     AND source_item_id IS NOT NULL)
             OR (source_kind = 'inheritance'  AND source_file_id IS NULL     AND source_item_id IS NULL)
             OR (source_kind = 'memory'       AND source_file_id IS NULL     AND source_item_id IS NULL)
            )
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_expiry_alerts_uniq_file "
        "ON vault_expiry_alerts(vault_id, source_file_id, expiry_type, alert_window_days) "
        "WHERE source_file_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_expiry_alerts_uniq_item "
        "ON vault_expiry_alerts(vault_id, source_item_id, expiry_type, alert_window_days) "
        "WHERE source_item_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_expiry_alerts_uniq_inh "
        "ON vault_expiry_alerts(vault_id, expiry_type, expiry_date, alert_window_days) "
        "WHERE source_kind = 'inheritance';"
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_expiry_alerts_uniq_mem "
        "ON vault_expiry_alerts(vault_id, expiry_type, expiry_date, alert_window_days) "
        "WHERE source_kind = 'memory';"
    )
    op.execute(
        "CREATE INDEX vault_expiry_alerts_active_idx "
        "ON vault_expiry_alerts(vault_id, status, severity, expiry_date) "
        "WHERE status = 'active';"
    )
    op.execute(
        "CREATE INDEX vault_expiry_alerts_source_file_idx "
        "ON vault_expiry_alerts(vault_id, source_file_id) WHERE source_file_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX vault_expiry_alerts_source_item_idx "
        "ON vault_expiry_alerts(vault_id, source_item_id) WHERE source_item_id IS NOT NULL;"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE vault_document_entities (
            id              BIGSERIAL   PRIMARY KEY,
            vault_id        UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            source_file_id  TEXT        NOT NULL
                REFERENCES uploaded_files(id) ON DELETE CASCADE,
            entity_type     TEXT        NOT NULL
                CHECK (entity_type IN ({ENTITY_TYPES_SQL})),
            entity_key      TEXT        NOT NULL
                CHECK (length(entity_key)   BETWEEN 1 AND 100),
            entity_value    TEXT        NOT NULL
                CHECK (length(entity_value) BETWEEN 1 AND 500),
            confidence      REAL        NOT NULL DEFAULT 1.0
                CHECK (confidence >= 0.0 AND confidence <= 1.0),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (vault_id, source_file_id, entity_type, entity_key)
        );
        """
    )
    op.execute(
        "CREATE INDEX vault_document_entities_lookup_idx "
        "ON vault_document_entities(vault_id, entity_type, entity_key);"
    )
    op.execute(
        "CREATE INDEX vault_document_entities_file_idx "
        "ON vault_document_entities(vault_id, source_file_id);"
    )

                                                                        
    op.execute(
        f"""
        CREATE TABLE username_policies (
            service_key         TEXT        PRIMARY KEY
                CHECK (length(service_key) BETWEEN 1 AND 200),
            service_display     TEXT        NOT NULL
                CHECK (length(service_display) BETWEEN 1 AND 200),
            allowed_chars       TEXT        NOT NULL
                CHECK (allowed_chars IN ({USERNAME_ALLOWED_CHARS_SQL})),
            min_length          INTEGER     NOT NULL
                CHECK (min_length BETWEEN 1 AND 64),
            max_length          INTEGER     NOT NULL
                CHECK (max_length BETWEEN 1 AND 64
                       AND max_length >= min_length),
            disallow_symbols    BOOLEAN     NOT NULL DEFAULT TRUE,
            disallow_underscore BOOLEAN     NOT NULL DEFAULT TRUE,
            email_required      BOOLEAN     NOT NULL DEFAULT FALSE,
            source_url          TEXT
                CHECK (source_url IS NULL OR length(source_url) <= 2048),
            confidence          TEXT        NOT NULL DEFAULT 'unknown'
                CHECK (confidence IN ({USERNAME_CONFIDENCES_SQL})),
            checked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

                                                                        
    op.execute(
        f"""
        INSERT INTO storage_pricing (key, value, notes) VALUES
          ('included_bytes',          {INCLUDED_BYTES},
           '1 GB free tier — included on every account'),
          ('block_bytes',             {BLOCK_BYTES},
           '50 GB per purchased block'),
          ('block_price_cents_usd',   {BLOCK_PRICE_CENTS_USD},
           '$25/month per block — Stripe quantity-driven, Apple/Google per-SKU'),
          ('self_service_max_blocks', {SELF_SERVICE_MAX_BLOCKS},
           '5 TB self-service ceiling — checkout-layer enforcement only');
        """
    )

    op.execute(
        """
        INSERT INTO storage_skus (sku_key, block_count, billing_period) VALUES
          ('storage_50gb_monthly',   1,  'monthly'),
          ('storage_100gb_monthly',  2,  'monthly'),
          ('storage_150gb_monthly',  3,  'monthly'),
          ('storage_200gb_monthly',  4,  'monthly'),
          ('storage_250gb_monthly',  5,  'monthly'),
          ('storage_500gb_monthly',  10, 'monthly'),
          ('storage_1tb_monthly',    20, 'monthly'),
          ('storage_2tb_monthly',    40, 'monthly'),
          ('storage_5tb_monthly',    100,'monthly');
        """
    )


def downgrade() -> None:
                                                                      
                                                         
    for tbl in (
        "username_policies",
        "vault_document_entities",
        "vault_expiry_alerts",
        "vault_relationships",
        "vault_service_categories",
        "vault_preferences",
        "vault_ai_memory",
        "vault_document_metadata",
        "vault_password_audit",
        "vault_asset_tags",
        "semantic_index",
        "trusted_devices",
        "notifications",
        "beneficiary_links",
        "uploaded_file_chunks",
        "uploaded_files",
        "vault_items",
        "stripe_customers",
        "contact_sales_requests",
        "account_storage_totals",
        "storage_pricing",
        "storage_skus",
        "provider_event_log",
        "subscription_events",
        "account_subscriptions",
        "account_members",
        "auth_sessions",
    ):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")

                                                                  
    op.execute(
        "ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_billing_owner_vault_fk;"
    )
    op.execute("DROP TABLE IF EXISTS vaults CASCADE;")
    op.execute("DROP TABLE IF EXISTS accounts CASCADE;")
