from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # AI reasoning. The OpenRouter key comes from the InsForge dashboard (Model Gateway).
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-5.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: int = 90
    openrouter_max_retries: int = 2
    ai_max_evidence_chars: int = 60000
    cors_origins: str = "http://localhost:3000"

    # InsForge: verifies the signed-in user and stores investigation history.
    # The backend uses the user's own access token, so no admin key is needed.
    insforge_base_url: str = ""
    insforge_timeout_seconds: int = 10
    # Set to false only for local testing with curl (no sign-in, no history).
    auth_required: bool = True

    # Kubernetes access. Leave KUBECONFIG_PATH empty to use kubectl's default
    # (the KUBECONFIG env var, then ~/.kube/config).
    kubeconfig_path: str = ""
    kubectl_binary: str = "kubectl"
    kubectl_timeout_seconds: int = 20
    # true when the backend runs in Docker next to kind (docker-compose.kind.yml):
    # reach kind clusters by their node name on the `kind` Docker network instead of 127.0.0.1.
    kind_internal_network: bool = False

    # Limits that keep the investigation payload small.
    log_tail_lines: int = 200
    max_log_lines_per_container: int = 30
    max_pods_for_logs: int = 10
    stuck_container_creating_minutes: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Treat `OPENROUTER_MODEL=` (empty) as "not set" so the default applies.
        env_ignore_empty=True,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
