# SPDX-License-Identifier: Apache-2.0

"""Worker entrypoint.

Selects a role and runs its loop alongside the health server:
  - ingestion: consume raggie.document.uploaded and run the ingestion pipeline.
  - eval: consume raggie.chat.completed and score answers (faithfulness, citations).
  - scheduler: run due scheduled_tasks via the edge's internal run-task endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import socket

import redis.asyncio as aioredis
from qdrant_client import AsyncQdrantClient

from raggie_workers.bus import RedisStreamsBus
from raggie_workers.config import Settings, settings, validate_secrets
from raggie_workers.db import create_pool
from raggie_workers.evaluation.consumer import EvalConsumer
from raggie_workers.evaluation.dedup import RedisDeduper
from raggie_workers.evaluation.judge import FaithfulnessJudge
from raggie_workers.evaluation.sampler import ThroughputSampler
from raggie_workers.evaluation.store import EvalStore
from raggie_workers.health import start_health_server
from raggie_workers.ingestion.consumer import IngestionConsumer
from raggie_workers.ingestion.deletion import DeletionConsumer
from raggie_workers.ingestion.objectstore import MinioObjectStore
from raggie_workers.ingestion.openai_embedder import (
    OpenAICompatibleEmbedder,
    OpenAICompatibleSparseEmbedder,
)
from raggie_workers.ingestion.status import DocumentStatusStore
from raggie_workers.ingestion.vectorstore import QdrantVectorStore
from raggie_workers.logging import configure_logging
from raggie_workers.redisconn import create_redis
from raggie_workers.scheduler import run_scheduler

log = logging.getLogger("worker")


def redis_client(cfg: Settings) -> aioredis.Redis:
    # Sentinel (HA) or REDIS_URL (+ REDIS_PASSWORD); see raggie_workers.redisconn.
    return create_redis(cfg).client


def eval_judge(cfg: Settings) -> FaithfulnessJudge:
    return FaithfulnessJudge(
        base_url=cfg.llmaas_base_url,
        api_key=cfg.llmaas_api_key,
        model=cfg.llmaas_chat_model,
        max_concurrency=cfg.eval_max_concurrency,
        timeout=cfg.eval_llm_timeout_seconds,
    )


def qdrant_client(cfg: Settings) -> AsyncQdrantClient:
    return AsyncQdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key or None)


async def run_ingestion() -> None:
    redis = redis_client(settings)
    # The gateway picks the model; the bearer is INTERNAL_API_SECRET (enforced
    # by the gateway in cloud mode, ignored in local mode when unset).
    embedder = OpenAICompatibleEmbedder(
        base_url=settings.embeddings_base_url,
        api_key=settings.internal_api_secret,
        timeout=settings.embed_timeout_seconds,
        max_retries=settings.embed_max_retries,
    )
    sparse_embedder = (
        OpenAICompatibleSparseEmbedder(
            base_url=settings.embeddings_base_url,
            api_key=settings.internal_api_secret,
            timeout=settings.embed_timeout_seconds,
            max_retries=settings.embed_max_retries,
        )
        if settings.sparse_enabled
        else None
    )
    bus = RedisStreamsBus(redis)
    object_store = MinioObjectStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        bucket=settings.minio_bucket,
        secure=settings.minio_use_ssl,
    )
    vector_store = QdrantVectorStore(
        qdrant_client(settings),
        replication_factor=settings.qdrant_replication_factor,
        shard_number=settings.qdrant_shard_number,
        write_consistency_factor=settings.qdrant_write_consistency_factor,
    )
    consumer = IngestionConsumer(
        bus=bus,
        object_store=object_store,
        embedder=embedder,
        vector_store=vector_store,
        status=DocumentStatusStore(await create_pool()),
        sparse_embedder=sparse_embedder,
        parser_limits=settings.parser_limits(),
        parse_timeout_seconds=settings.parser_timeout_seconds,
        heartbeat_seconds=settings.ingest_heartbeat_seconds,
        embed_batch_size=settings.embed_batch_size,
    )
    # The deletion cascade (document.deleted) shares this worker's Qdrant client,
    # object store and bus — it drops a document's chunks (archive) and, when
    # purge_object is set, hard-deletes the MinIO object (delete).
    deletion_consumer = DeletionConsumer(
        bus=bus,
        object_store=object_store,
        vector_store=vector_store,
    )
    # Distinct consumer name per replica so the Redis Streams consumer group
    # load-balances messages across all `--scale`d ingestion workers (and XINFO
    # shows per-replica lag). The container hostname is unique per replica.
    consumer_name = f"ingestion-{socket.gethostname()}"
    log.info("ingestion worker ready", extra={"consumer": consumer_name})

    async def _ingest_loop() -> None:
        while True:
            if await consumer.run_once(consumer_name) == 0:
                await asyncio.sleep(0.5)  # idle backoff when the stream is empty

    async def _deletion_loop() -> None:
        while True:
            if await deletion_consumer.run_once(consumer_name) == 0:
                await asyncio.sleep(0.5)  # idle backoff when the stream is empty

    # Run both consumers concurrently in one process; if either loop crashes the
    # gather propagates and the supervisor restarts the worker.
    await asyncio.gather(_ingest_loop(), _deletion_loop())


async def run_eval() -> None:
    redis = redis_client(settings)
    consumer = EvalConsumer(
        bus=RedisStreamsBus(redis),
        store=EvalStore(await create_pool()),
        judge=eval_judge(settings),
        deduper=RedisDeduper(redis, settings.eval_dedup_ttl_seconds),
        sampler=ThroughputSampler(settings.eval_qps_threshold, settings.eval_sample_rate),
        score_threshold=settings.eval_faithfulness_threshold,
        citation_validity_threshold=settings.eval_citation_validity_threshold,
        citation_coverage_threshold=settings.eval_citation_coverage_threshold,
        max_deliveries=settings.eval_max_deliveries,
    )
    log.info("eval worker ready")
    while True:
        if await consumer.run_once() == 0:
            await asyncio.sleep(0.5)  # idle backoff when the stream is empty


async def run_scheduler_role() -> None:
    # The scheduler owns scheduled_tasks/notifications via the asyncpg pool; the
    # poll loop itself lives in raggie_workers.scheduler.
    await run_scheduler(await create_pool())


_ROLES = {
    "eval": run_eval,
    "scheduler": run_scheduler_role,
    "ingestion": run_ingestion,
}


def main() -> None:
    configure_logging(settings.worker_log_level)
    # Fail fast (before serving health) on default/placeholder secrets.
    validate_secrets(settings)
    start_health_server(settings.worker_health_port)
    log.info("worker booting", extra={"role": settings.worker_role})
    loop = _ROLES.get(settings.worker_role, run_ingestion)
    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    main()
