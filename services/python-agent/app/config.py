"""全局配置。所有配置项只从这里读，禁止在业务代码里直接 os.getenv。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 本地开发时 .env 在仓库根目录；容器里由 compose 注入环境变量，不读文件
_ENV_CANDIDATES = (
    Path(__file__).resolve().parents[3] / ".env",  # 仓库根 .env
    Path.cwd() / ".env",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_CANDIDATES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 服务 ----------
    service_name: str = "codeatlas-agent"
    internal_token: str = "dev_internal_token"
    agent_host: str = "0.0.0.0"
    agent_port: int = 8000

    # ---------- 数据库 ----------
    database_url: str = (
        "postgresql+psycopg://codeatlas:codeatlas_dev@localhost:5433/codeatlas"
    )

    # ---------- 模型 ----------
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    llm_model: str = "deepseek-ai/DeepSeek-V4.1-Flash"
    llm_model_fallback: str = "deepseek-ai/DeepSeek-V3"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 128
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_enabled: bool = True

    # ---------- Agent 预算（防死循环的硬约束）----------
    agent_max_steps: int = 8
    agent_max_rewrite: int = 2
    agent_timeout_seconds: int = 60
    agent_token_budget: int = 30_000
    agent_coverage_threshold: float = 0.6
    retrieval_top_k: int = 20
    retrieval_rrf_top_n: int = 12

    # ---------- 开发开关 ----------
    # mock_agent=true 时用假事件流，不调真实模型（P0 阶段默认）
    mock_agent: bool = True

    @property
    def has_llm_key(self) -> bool:
        return bool(self.siliconflow_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
