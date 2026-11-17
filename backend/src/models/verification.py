from sqlalchemy import String, JSON, Double, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Verification(Base):
    """试验验真凭据与复算状态（每个分析任务至多一条）。

    封存区（任务完成时写入，之后业务流程不再改动）：
      evidence      封存清单：原输入、参数、规则版本、独立计算依据、指纹
      evidence_hash 封存清单自身的 SHA256，用于检测封存内容是否被改动
    复算区（每次发起/恢复核验时更新）：
      status        pending/running/passed/failed/unverifiable
      progress      0~100 的进度，便于页面展示与中断恢复同次核验
      run_key       同次核验的幂等令牌；并发重试复用它，不重复出凭据
      worker_token  占用执行权的 worker；旧执行的迟到写入据此被拒绝
      differences   逐段分诊与指标差异明细；缺件/失败原因也落在此处
    """
    __tablename__ = 'verifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), unique=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_hash: Mapped[str] = mapped_column(String(64), default='')
    status: Mapped[str] = mapped_column(String(20), default='pending')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    run_key: Mapped[str] = mapped_column(String(64), default='')
    worker_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    differences: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sealed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    checked_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
