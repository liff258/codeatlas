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
    # ⚠️ 这一组是 embedding API 的 key，和下面的 llm_api_key 必须分开。
    # embedding.py 用它判断「要不要走 API embedding」——如果把智谱的 key 塞进来，
    # embedding 会被路由到智谱，模型名和维度全错，而且不会报错，只是检索质量莫名其妙地差。
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    llm_model: str = "deepseek-ai/DeepSeek-V4.1-Flash"
    llm_model_fallback: str = "deepseek-ai/DeepSeek-V3"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 128
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_enabled: bool = True
    # 本地模型缓存目录（gitignore，约 2.2GB）
    model_cache_dir: str = str(Path(__file__).resolve().parents[3] / "data" / "models")

    # ---------- Agent 用的对话模型（P2）----------
    # 默认智谱 GLM-4.5-Flash：免费、OpenAI SDK 兼容。
    # 注意模型 ID 是 glm-4.5-flash，不是上一代的 glm-4-flash。
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    # 注意：不能复用上面的 llm_model。那个字段是给硅基流动的 DeepSeek 用的，
    # .env 里已经写了 LLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash，
    # 拿它去调智谱会直接 404（模型不存在）。
    agent_model: str = "glm-4.5-flash"
    llm_timeout_seconds: int = 20

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
        """Agent 能不能调真实模型。

        只认 llm_api_key，不看 siliconflow_api_key——后者是 embedding API 用的，
        两者指向完全不同的服务。
        """
        return bool(self.llm_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
