

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


_PROD_TOKENS = frozenset({"prod", "production", "live"})
_DEV_TOKENS  = frozenset({"dev", "development", "local", "test", "ci"})


def _read_env_token() -> str:
    for var in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
        v = os.getenv(var, "").strip().lower()
        if v:
            return v
    return ""


def is_production() -> bool:

    return _read_env_token() in _PROD_TOKENS


def is_dev_or_local() -> bool:


    token = _read_env_token()
    if not token:
        return True
    return token in _DEV_TOKENS


def _env_str(name: str, *, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return str(raw).strip()


def _env_int(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(
            "[vault_config] %s is not a valid int (%r); using default %d",
            name, raw, default,
        )
        return int(default)


def _env_float(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(
            "[vault_config] %s is not a valid float (%r); using default %f",
            name, raw, default,
        )
        return float(default)


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass(frozen=True)
class AIConfig:


    provider:                    str = "openai"
    fallback_provider:           str = "openai"

                          
    openai_chat_model:           str = "gpt-4o-mini"
    openai_intent_model:         str = "gpt-4o-mini"

                         
    embedding_model:             str = "text-embedding-3-small"
    embedding_dim:               int = 1536
    brain_query_embed_cap_chars: int = 8000
    metadata_embed_cap_chars:    int = 256

                                                   
    experimental_vault_brain_chat_enabled: bool = False

                                                             
    crypto_wallet_engine_enabled: bool = True

    @property
    def chat_model(self) -> str:

        return self.openai_chat_model

    @property
    def intent_model(self) -> str:

        return self.openai_intent_model


@dataclass(frozen=True)
class BrainConfig:

    chunk_target_chars:    int   = 1500
    chunk_overlap_chars:   int   = 200
    max_chunk_chars:       int   = 8000
    retrieval_top_k:       int   = 8
    lexical_fallback_limit:int   = 20
    min_similarity:        float = 0.20
    max_context_chunks:    int   = 5
    evidence_snippet_chars:int   = 240
    read_file_excerpt_chars:int  = 4000
    indexer_batch:         int   = 8
    max_chunks_per_file:   int   = 256

                                                        
    narrow_retrieval_top_k:         int   = 8
    broad_retrieval_top_k:          int   = 32
                                                                 
                                                                   
    max_files_per_query:            int   = 12
    max_chunks_per_file_per_query:  int   = 4
    summary_max_chunks:             int   = 40
    diversify_by_file:              bool  = True
                                                     
                                                                 
    coverage_complete_threshold:    float = 0.95
                                                                   
                                                    
    deep_continuation_page_size:    int   = 16


@dataclass(frozen=True)
class WorkerConfig:

    drain_budget_per_iter:        int   = 6
    daemon_iteration_sleep_secs:  float = 1.0
    daemon_shutdown_grace_secs:   float = 5.0
    deep_answer_max_wallclock_secs:float= 90.0
    max_jobs_per_stage:           int   = 4
    stuck_job_lease_timeout_secs: int   = 600


@dataclass(frozen=True)
class UploadConfig:

    max_upload_bytes:    int = 100 * 1024 * 1024                    
    max_json_body_bytes: int = 1 * 1024 * 1024                    
    chunk_upload_min_bytes: int = 256 * 1024                        
    chunk_upload_max_bytes: int = 8 * 1024 * 1024                 
    max_chunk_count:     int = 4096                                     


@dataclass(frozen=True)
class MediaConfig:

    max_audio_bytes:      int = 25 * 1024 * 1024                   
    max_video_bytes:      int = 200 * 1024 * 1024                   
    max_transcript_chars: int = 500_000                                  


@dataclass(frozen=True)
class CacheSecurityConfig:

    vault_key_idle_ttl_secs: float = 30 * 60                        
    vault_key_hard_ttl_secs: float = 8 * 60 * 60                 
    debug_endpoints_enabled: bool = False
    is_dev_environment:      bool = True


@dataclass(frozen=True)
class BillingConfig:


    free_included_bytes:           int = 1_073_741_824
    storage_block_bytes:           int = 53_687_091_200
    monthly_block_price_cents_usd: int = 2500
    self_service_max_blocks:       int = 100


@dataclass(frozen=True)
class VaultConfig:


    ai:        AIConfig
    brain:     BrainConfig
    worker:    WorkerConfig
    upload:    UploadConfig
    media:     MediaConfig
    cache:     CacheSecurityConfig
    billing:   BillingConfig
    env_token: str
    is_production: bool

    def describe(self) -> dict:
        return {
            "env": {
                "token":         self.env_token,
                "is_production": bool(self.is_production),
            },
            "ai":      _asdict(self.ai),
            "brain":   _asdict(self.brain),
            "worker":  _asdict(self.worker),
            "upload":  _asdict(self.upload),
            "media":   _asdict(self.media),
            "cache":   _asdict(self.cache),
            "billing": _asdict(self.billing),
        }


def _asdict(obj) -> dict:
    return {f: getattr(obj, f) for f in obj.__dataclass_fields__}


_CONFIG: Optional[VaultConfig] = None


def _load() -> VaultConfig:
    env_token = _read_env_token() or ("development" if not is_production() else "production")
    prod = is_production()

    ai = AIConfig(
        openai_chat_model=_env_str(
            "VAULTAI_CHAT_MODEL", default="gpt-4o-mini",
        ),
        openai_intent_model=_env_str(
            "VAULTAI_INTENT_MODEL", default="gpt-4o-mini",
        ),
        embedding_model=_env_str(
            "VAULTAI_EMBEDDING_MODEL", default="text-embedding-3-small",
        ),
        embedding_dim=_env_int(
            "VAULTAI_EMBEDDING_DIM", default=1536,
        ),
        brain_query_embed_cap_chars=_env_int(
            "VAULTAI_BRAIN_QUERY_EMBED_CAP_CHARS", default=8000,
        ),
        metadata_embed_cap_chars=_env_int(
            "VAULTAI_METADATA_EMBED_CAP_CHARS", default=256,
        ),
        experimental_vault_brain_chat_enabled=_env_bool(
            "VAULTAI_EXPERIMENTAL_VAULT_BRAIN_CHAT_ENABLED",
            default=False,
        ),
        crypto_wallet_engine_enabled=_env_bool(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            default=True,
        ),
    )

    brain = BrainConfig(
        chunk_target_chars=_env_int(
            "VAULTAI_CHUNK_TARGET_CHARS", default=1500,
        ),
        chunk_overlap_chars=_env_int(
            "VAULTAI_CHUNK_OVERLAP_CHARS", default=200,
        ),
        max_chunk_chars=_env_int(
            "VAULTAI_MAX_CHUNK_CHARS", default=8000,
        ),
        retrieval_top_k=_env_int(
            "VAULTAI_RETRIEVAL_TOP_K", default=8,
        ),
        lexical_fallback_limit=_env_int(
            "VAULTAI_LEXICAL_FALLBACK_LIMIT", default=20,
        ),
        min_similarity=_env_float(
            "VAULTAI_MIN_SIMILARITY", default=0.20,
        ),
        max_context_chunks=_env_int(
            "VAULTAI_MAX_CONTEXT_CHUNKS", default=5,
        ),
        evidence_snippet_chars=_env_int(
            "VAULTAI_EVIDENCE_SNIPPET_CHARS", default=240,
        ),
        read_file_excerpt_chars=_env_int(
            "VAULTAI_READ_FILE_EXCERPT_CHARS", default=4000,
        ),
        indexer_batch=_env_int(
            "VAULTAI_INDEXER_BATCH", default=8,
        ),
        max_chunks_per_file=_env_int(
            "VAULTAI_MAX_CHUNKS_PER_FILE", default=256,
        ),
        narrow_retrieval_top_k=_env_int(
            "VAULTAI_NARROW_RETRIEVAL_TOP_K", default=8,
        ),
        broad_retrieval_top_k=_env_int(
            "VAULTAI_BROAD_RETRIEVAL_TOP_K", default=32,
        ),
        max_files_per_query=_env_int(
            "VAULTAI_MAX_FILES_PER_QUERY", default=12,
        ),
        max_chunks_per_file_per_query=_env_int(
            "VAULTAI_MAX_CHUNKS_PER_FILE_PER_QUERY", default=4,
        ),
        summary_max_chunks=_env_int(
            "VAULTAI_SUMMARY_MAX_CHUNKS", default=40,
        ),
        diversify_by_file=_env_bool(
            "VAULTAI_DIVERSIFY_BY_FILE", default=True,
        ),
        coverage_complete_threshold=_env_float(
            "VAULTAI_COVERAGE_COMPLETE_THRESHOLD", default=0.95,
        ),
        deep_continuation_page_size=_env_int(
            "VAULTAI_DEEP_CONTINUATION_PAGE_SIZE", default=16,
        ),
    )

    worker = WorkerConfig(
        drain_budget_per_iter=_env_int(
            "VAULTAI_DRAIN_BUDGET_PER_ITER", default=6,
        ),
        daemon_iteration_sleep_secs=_env_float(
            "VAULTAI_DAEMON_ITERATION_SLEEP_SECS", default=1.0,
        ),
        daemon_shutdown_grace_secs=_env_float(
            "VAULTAI_DAEMON_SHUTDOWN_GRACE_SECS", default=5.0,
        ),
        deep_answer_max_wallclock_secs=_env_float(
            "VAULTAI_DEEP_ANSWER_MAX_WALLCLOCK_SECS", default=90.0,
        ),
        max_jobs_per_stage=_env_int(
            "VAULTAI_MAX_JOBS_PER_STAGE", default=4,
        ),
        stuck_job_lease_timeout_secs=_env_int(
            "VAULTAI_STUCK_JOB_LEASE_TIMEOUT_SECS", default=600,
        ),
    )

    upload = UploadConfig(
        max_upload_bytes=_env_int(
            "MAX_UPLOAD_BYTES", default=100 * 1024 * 1024,
        ),
        max_json_body_bytes=_env_int(
            "MAX_JSON_BODY_BYTES", default=1 * 1024 * 1024,
        ),
        chunk_upload_min_bytes=_env_int(
            "VAULTAI_CHUNK_UPLOAD_MIN_BYTES", default=256 * 1024,
        ),
        chunk_upload_max_bytes=_env_int(
            "VAULTAI_CHUNK_UPLOAD_MAX_BYTES", default=8 * 1024 * 1024,
        ),
        max_chunk_count=_env_int(
            "VAULTAI_MAX_CHUNK_COUNT", default=4096,
        ),
    )

    media = MediaConfig(
        max_audio_bytes=_env_int(
            "VAULTAI_MAX_AUDIO_BYTES", default=25 * 1024 * 1024,
        ),
        max_video_bytes=_env_int(
            "VAULTAI_MAX_VIDEO_BYTES", default=200 * 1024 * 1024,
        ),
        max_transcript_chars=_env_int(
            "VAULTAI_MAX_TRANSCRIPT_CHARS", default=500_000,
        ),
    )

    cache = CacheSecurityConfig(
        vault_key_idle_ttl_secs=_env_float(
            "VAULTAI_VAULT_KEY_IDLE_TTL_SECS", default=30 * 60,
        ),
        vault_key_hard_ttl_secs=_env_float(
            "VAULTAI_VAULT_KEY_HARD_TTL_SECS", default=8 * 60 * 60,
        ),
        debug_endpoints_enabled=_env_bool(
            "VAULTAI_DEBUG_ENDPOINTS_ENABLED", default=not prod,
        ),
        is_dev_environment=not prod,
    )

    billing = BillingConfig(
        free_included_bytes=_env_int(
            "VAULTAI_FREE_INCLUDED_BYTES", default=1_073_741_824,
        ),
        storage_block_bytes=_env_int(
            "VAULTAI_STORAGE_BLOCK_BYTES", default=53_687_091_200,
        ),
        monthly_block_price_cents_usd=_env_int(
            "VAULTAI_MONTHLY_BLOCK_PRICE_CENTS_USD", default=2500,
        ),
        self_service_max_blocks=_env_int(
            "VAULTAI_SELF_SERVICE_MAX_BLOCKS", default=100,
        ),
    )

    cfg = VaultConfig(
        ai=ai, brain=brain, worker=worker,
        upload=upload, media=media, cache=cache, billing=billing,
        env_token=env_token, is_production=prod,
    )

    _validate_production_requirements(cfg)
    return cfg


def _validate_production_requirements(cfg: VaultConfig) -> None:


    if not cfg.is_production:
        return

    missing: list[str] = []
    if not os.getenv("VAULT_SESSION_SECRET", "").strip():
        missing.append("VAULT_SESSION_SECRET")
    if not (
        os.getenv("CORS_ALLOWED_ORIGIN_REGEX", "").strip()
        or os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    ):
        missing.append("CORS_ALLOWED_ORIGIN_REGEX or CORS_ALLOWED_ORIGINS")
    if cfg.cache.debug_endpoints_enabled:

        missing.append(
            "VAULTAI_DEBUG_ENDPOINTS_ENABLED must be unset/false in production",
        )
    if not os.getenv("STRIPE_WEBHOOK_SECRET", "").strip():
        missing.append(
            "STRIPE_WEBHOOK_SECRET (required for signed Stripe webhooks)",
        )
    if os.getenv(
        "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST", "",
    ).strip().lower() == "true":
        missing.append(
            "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST must be unset/false in "
            "production (dev cleanup routes stay closed)",
        )
    if missing:
        raise RuntimeError(
            "[vault_config] production refuses to boot — missing required "
            f"config: {', '.join(missing)}. Dev defaults are NOT used in "
            "production. Set these in the environment before starting "
            "the server.",
        )


def get_config() -> VaultConfig:

    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _load()
    return _CONFIG


def ai() -> AIConfig:
    return get_config().ai


def brain() -> BrainConfig:
    return get_config().brain


def worker() -> WorkerConfig:
    return get_config().worker


def upload() -> UploadConfig:
    return get_config().upload


def media() -> MediaConfig:
    return get_config().media


def cache() -> CacheSecurityConfig:
    return get_config().cache


def billing() -> BillingConfig:
    return get_config().billing


def vault_brain_chat_enabled() -> bool:


    return bool(get_config().ai.experimental_vault_brain_chat_enabled)


_ETH_SEPOLIA_TOKEN_CONTRACT_ENV: dict[str, str] = {
    "USDT_ERC20": "ETH_SEPOLIA_USDT_CONTRACT_ADDRESS",
    "USDC_ERC20": "ETH_SEPOLIA_USDC_CONTRACT_ADDRESS",
}

                                                                 
_ETH_SEPOLIA_TOKEN_DECIMALS_ENV: dict[str, tuple[str, int]] = {
    "USDT_ERC20": ("ETH_SEPOLIA_USDT_DECIMALS", 6),
    "USDC_ERC20": ("ETH_SEPOLIA_USDC_DECIMALS", 6),
}

                                                       
_TOKEN_UNIT_LABEL: dict[str, str] = {
    "USDT_ERC20": "USDT",
    "USDC_ERC20": "USDC",
}


def ethereum_sepolia_token_contract(asset: str) -> str:


    env_var = _ETH_SEPOLIA_TOKEN_CONTRACT_ENV.get(asset)
    if env_var is None:
        return ""
    return os.getenv(env_var, "").strip()


def ethereum_sepolia_token_decimals(asset: str) -> int:


    entry = _ETH_SEPOLIA_TOKEN_DECIMALS_ENV.get(asset)
    if entry is None:
        return 18
    env_var, default = entry
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < 0 or v > 36:
        return default
    return v


def ethereum_sepolia_token_unit(asset: str) -> str:

    return _TOKEN_UNIT_LABEL.get(asset, asset)


def ethereum_sepolia_rpc_url() -> str:


    raw = os.getenv("ETHEREUM_SEPOLIA_RPC_URL", "").strip()
    return raw


_TX_INDEXER_ALLOWED_PROVIDERS: frozenset[str] = frozenset({
    "etherscan",
    "blockscout",
})


def ethereum_sepolia_tx_indexer_provider() -> str:


    raw = os.getenv("ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER", "").strip().lower()
    if raw not in _TX_INDEXER_ALLOWED_PROVIDERS:
        return ""
    return raw


def ethereum_sepolia_tx_indexer_api_key() -> str:


    return os.getenv("ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY", "").strip()


def ethereum_sepolia_tx_indexer_base_url() -> str:


    raw = os.getenv("ETHEREUM_SEPOLIA_TX_INDEXER_BASE_URL", "").strip()
    if raw:
        return raw
    provider = ethereum_sepolia_tx_indexer_provider()
    if provider == "etherscan":
                                                               
                                                                  
        return "https://api.etherscan.io/v2/api"
    if provider == "blockscout":
        return "https://eth-sepolia.blockscout.com/api"
    return ""


def ethereum_mainnet_rpc_url() -> str:


    return os.getenv("ETHEREUM_MAINNET_RPC_URL", "").strip()


def ethereum_mainnet_tx_indexer_provider() -> str:


    raw = os.getenv("ETHEREUM_MAINNET_TX_INDEXER_PROVIDER", "").strip().lower()
    if raw not in _TX_INDEXER_ALLOWED_PROVIDERS:
        return ""
    return raw


def ethereum_mainnet_tx_indexer_api_key() -> str:


    return os.getenv("ETHEREUM_MAINNET_TX_INDEXER_API_KEY", "").strip()


def ethereum_mainnet_tx_indexer_base_url() -> str:


    raw = os.getenv("ETHEREUM_MAINNET_TX_INDEXER_BASE_URL", "").strip()
    if raw:
        return raw
    provider = ethereum_mainnet_tx_indexer_provider()
    if provider == "etherscan":
        return "https://api.etherscan.io/v2/api"
    if provider == "blockscout":
        return "https://eth.blockscout.com/api"
    return ""


def ethereum_mainnet_tx_indexer_configured() -> bool:


    provider = ethereum_mainnet_tx_indexer_provider()
    if not provider:
        return False
    base = ethereum_mainnet_tx_indexer_base_url()
    if not base:
        return False
    if provider == "etherscan":
        return bool(ethereum_mainnet_tx_indexer_api_key())
    return True


def ethereum_mainnet_erc20_receive_enabled() -> bool:


    return _env_bool(
        "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
        default=False,
    )


_ETH_MAINNET_TOKEN_DECIMALS_ENV: dict[str, tuple[str, int]] = {
    "USDT_ERC20": ("ETHEREUM_MAINNET_USDT_DECIMALS", 6),
    "USDC_ERC20": ("ETHEREUM_MAINNET_USDC_DECIMALS", 6),
}


def ethereum_mainnet_token_decimals(asset: str) -> int:


    entry = _ETH_MAINNET_TOKEN_DECIMALS_ENV.get(asset)
    if entry is None:
        return 18
    env_var, default = entry
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < 0 or v > 36:
        return default
    return v


def ethereum_mainnet_token_unit(asset: str) -> str:


    return _TOKEN_UNIT_LABEL.get(asset, asset)


def ethereum_mainnet_send_paused() -> bool:


    return _env_bool(
        "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED", default=False,
    )


def ethereum_mainnet_broadcast_rate_limit() -> int:


    raw = os.getenv(
        "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT", "",
    ).strip()
    if not raw:
        return 3
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 3
    if v < 0:
        return 3
    return v


def ethereum_mainnet_broadcast_rate_window_secs() -> int:


    raw = os.getenv(
        "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS", "",
    ).strip()
    if not raw:
        return 60
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 60
    if v < 1:
        return 60
    return v


CRYPTO_DEFAULT_NETWORK_ENV_VAR: str = "VAULTAI_CRYPTO_DEFAULT_NETWORK"
_CRYPTO_VALID_DEFAULT_NETWORKS: frozenset = frozenset({
    "ethereum_mainnet",
    "ethereum_sepolia",
})
_CRYPTO_ROUTING_FALLBACK_NETWORK: str = "ethereum_sepolia"


def _crypto_default_network_raw() -> str:
    return os.getenv(CRYPTO_DEFAULT_NETWORK_ENV_VAR, "").strip().lower()


def crypto_default_network() -> str:
    raw = _crypto_default_network_raw()
    if raw in _CRYPTO_VALID_DEFAULT_NETWORKS:
        return raw
    return _CRYPTO_ROUTING_FALLBACK_NETWORK


def crypto_default_network_configured_value() -> str:
    return _crypto_default_network_raw()


def crypto_default_network_config_valid() -> bool:
    raw = _crypto_default_network_raw()
    if raw in _CRYPTO_VALID_DEFAULT_NETWORKS:
        return True
    if not raw:
        return not is_production()
    return False


def crypto_wallet_health_admin_token() -> str:


    return os.getenv("VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN", "").strip()


def billing_admin_health_token() -> str:
    return os.getenv("VAULTAI_BILLING_HEALTH_ADMIN_TOKEN", "").strip()


def solana_enabled() -> bool:
    return _env_bool("VAULTAI_CRYPTO_SOLANA_ENABLED", default=False)


def solana_rpc_url() -> str:
    return os.getenv("SOLANA_RPC_URL", "").strip()


def solana_tx_indexer_provider() -> str:
    raw = os.getenv("SOLANA_TX_INDEXER_PROVIDER", "").strip().lower()
    if raw in ("helius", "solscan", "quicknode", "custom"):
        return raw
    return ""


def solana_tx_indexer_api_key() -> str:
    return os.getenv("SOLANA_TX_INDEXER_API_KEY", "").strip()


def solana_tx_indexer_base_url() -> str:
    raw = os.getenv("SOLANA_TX_INDEXER_BASE_URL", "").strip()
    if raw:
        return raw
    provider = solana_tx_indexer_provider()
    if provider == "helius":
        return "https://api.helius.xyz"
    if provider == "solscan":
        return "https://pro-api.solscan.io"
    return ""


def solana_tx_indexer_configured() -> bool:
    if not solana_tx_indexer_provider():
        return False
    if not solana_tx_indexer_base_url():
        return False
    return True


def solana_send_enabled() -> bool:
    return _env_bool("VAULTAI_CRYPTO_SOLANA_SEND_ENABLED", default=False)


def solana_send_paused() -> bool:
    return _env_bool("VAULTAI_CRYPTO_SOLANA_SEND_PAUSED", default=False)


def solana_broadcast_rate_limit() -> int:
    raw = os.getenv(
        "VAULTAI_CRYPTO_SOLANA_BROADCAST_RATE_LIMIT", "",
    ).strip()
    if not raw:
        return 3
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 3
    if v < 0:
        return 3
    return v


def solana_broadcast_rate_window_secs() -> int:
    raw = os.getenv(
        "VAULTAI_CRYPTO_SOLANA_BROADCAST_RATE_WINDOW_SECS", "",
    ).strip()
    if not raw:
        return 60
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 60
    if v < 1:
        return 60
    return v


def tron_enabled() -> bool:
    return _env_bool("VAULTAI_CRYPTO_TRON_ENABLED", default=False)


def tron_api_base_url() -> str:
    raw = os.getenv("TRON_API_BASE_URL", "").strip()
    if raw:
        return raw
    return os.getenv("TRON_RPC_URL", "").strip()


def tron_api_key() -> str:
    return os.getenv("TRON_API_KEY", "").strip()


def tron_usdt_contract_address() -> str:
    return os.getenv("TRON_USDT_CONTRACT_ADDRESS", "").strip()


def tron_usdt_decimals() -> int:
    raw = os.getenv("TRON_USDT_DECIMALS", "").strip()
    if not raw:
        return 6
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 6
    if v < 0 or v > 36:
        return 6
    return v


def tron_send_enabled() -> bool:
    return _env_bool("VAULTAI_CRYPTO_TRON_SEND_ENABLED", default=False)


def tron_send_paused() -> bool:
    return _env_bool("VAULTAI_CRYPTO_TRON_SEND_PAUSED", default=False)


def tron_broadcast_rate_limit() -> int:
    raw = os.getenv(
        "VAULTAI_CRYPTO_TRON_BROADCAST_RATE_LIMIT", "",
    ).strip()
    if not raw:
        return 3
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 3
    if v < 0:
        return 3
    return v


def tron_broadcast_rate_window_secs() -> int:
    raw = os.getenv(
        "VAULTAI_CRYPTO_TRON_BROADCAST_RATE_WINDOW_SECS", "",
    ).strip()
    if not raw:
        return 60
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 60
    if v < 1:
        return 60
    return v


def tron_send_fee_limit_sun() -> int:
    raw = os.getenv("VAULTAI_CRYPTO_TRON_SEND_FEE_LIMIT_SUN", "").strip()
    default = 100_000_000
    if not raw:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v <= 0:
        return default
    return v


def tron_low_trx_threshold_sun() -> int:
    raw = os.getenv("VAULTAI_CRYPTO_TRON_LOW_TRX_THRESHOLD_SUN", "").strip()
    default = 5_000_000
    if not raw:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < 0:
        return default
    return v


_MONERO_ALLOWED_SCANNER_MODES: frozenset[str] = frozenset({
    "none",
    "client_local",
    "server_view_only",
})


def monero_enabled() -> bool:
    return _env_bool("VAULTAI_CRYPTO_XMR_ENABLED", default=False)


def monero_send_enabled() -> bool:
    return _env_bool("VAULTAI_CRYPTO_XMR_SEND_ENABLED", default=False)


def monero_scanner_mode() -> str:
    raw = os.getenv("VAULTAI_CRYPTO_XMR_SCANNER_MODE", "").strip().lower()
    if raw in _MONERO_ALLOWED_SCANNER_MODES:
        return raw
    return "none"


def monero_scanner_url() -> str:
    return os.getenv("VAULTAI_CRYPTO_XMR_SCANNER_URL", "").strip()


def ethereum_sepolia_tx_indexer_configured() -> bool:


    provider = ethereum_sepolia_tx_indexer_provider()
    if not provider:
        return False
    base = ethereum_sepolia_tx_indexer_base_url()
    if not base:
        return False
    if provider == "etherscan":
                                        
        return bool(ethereum_sepolia_tx_indexer_api_key())
                                        
    return True


def crypto_wallet_engine_enabled() -> bool:


    return bool(get_config().ai.crypto_wallet_engine_enabled)


def describe() -> dict:


    return get_config().describe()


def reset_for_tests() -> None:


    global _CONFIG
    _CONFIG = None


__all__ = [
    "AIConfig",
    "BrainConfig",
    "WorkerConfig",
    "UploadConfig",
    "MediaConfig",
    "CacheSecurityConfig",
    "BillingConfig",
    "VaultConfig",
    "get_config",
    "ai", "brain", "worker", "upload", "media", "cache", "billing",
    "vault_brain_chat_enabled",
    "crypto_wallet_engine_enabled",
    "ethereum_sepolia_rpc_url",
    "ethereum_sepolia_token_contract",
    "ethereum_sepolia_token_decimals",
    "ethereum_sepolia_token_unit",
    "ethereum_sepolia_tx_indexer_provider",
    "ethereum_sepolia_tx_indexer_api_key",
    "ethereum_sepolia_tx_indexer_base_url",
    "ethereum_sepolia_tx_indexer_configured",
    "ethereum_mainnet_rpc_url",
    "ethereum_mainnet_tx_indexer_provider",
    "ethereum_mainnet_tx_indexer_api_key",
    "ethereum_mainnet_tx_indexer_base_url",
    "ethereum_mainnet_tx_indexer_configured",
    "ethereum_mainnet_erc20_receive_enabled",
    "ethereum_mainnet_token_decimals",
    "ethereum_mainnet_token_unit",
    "ethereum_mainnet_send_paused",
    "ethereum_mainnet_broadcast_rate_limit",
    "ethereum_mainnet_broadcast_rate_window_secs",
    "CRYPTO_DEFAULT_NETWORK_ENV_VAR",
    "crypto_default_network",
    "crypto_default_network_configured_value",
    "crypto_default_network_config_valid",
    "crypto_wallet_health_admin_token",
    "billing_admin_health_token",
    "solana_enabled",
    "solana_rpc_url",
    "solana_tx_indexer_provider",
    "solana_tx_indexer_api_key",
    "solana_tx_indexer_base_url",
    "solana_tx_indexer_configured",
    "solana_send_enabled",
    "solana_send_paused",
    "solana_broadcast_rate_limit",
    "solana_broadcast_rate_window_secs",
    "tron_enabled",
    "tron_api_base_url",
    "tron_api_key",
    "tron_usdt_contract_address",
    "tron_usdt_decimals",
    "tron_send_enabled",
    "tron_send_paused",
    "tron_broadcast_rate_limit",
    "tron_broadcast_rate_window_secs",
    "tron_send_fee_limit_sun",
    "tron_low_trx_threshold_sun",
    "monero_enabled",
    "monero_send_enabled",
    "monero_scanner_mode",
    "describe", "reset_for_tests",
    "is_production", "is_dev_or_local",
]
