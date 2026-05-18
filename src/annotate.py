#!/usr/bin/env python
"""Annotate images in a dataset and track progress in a BQ table."""

import argparse
import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import pandas as pd
import requests
from google.cloud import bigquery

from agents.agent_runner import AgentRunner
from agents.analyzer import create_img_analysis_agent
from core.config import load_config
from core.logger import setup_logger
from core.pipeline import AsyncPipeline
from core.rate_limiter import RateLimiter
from data_processing.bq_processor import BigQueryProcessor, ChunkedQueryResult, SchemaContext
from data_processing.utils import load_sql_template

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 32


def args_parser() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Annotate product images.")
    parser.add_argument(
        "-p",
        "--project-id",
        type=str,
        default="hm-studios-metadata-c54a",
        help="GCP project ID for BigQuery operations.",
    )
    parser.add_argument(
        "-l",
        "--location",
        type=str,
        default="europe-west1",
        help="GCP location for BigQuery dataset.",
    )
    parser.add_argument(
        "-d",
        "--tracking-dataset",
        type=str,
        default="img_annotations_trf",
        help="BigQuery dataset for tracking annotations.",
    )
    parser.add_argument(
        "-t",
        "--tracking-table",
        type=str,
        default="generated_attributes_tmp",
        help="BigQuery table for tracking annotations.",
    )
    parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=500,
        help="Number of rows to process in each chunk.",
    )
    parser.add_argument(
        "-f",
        "--flush-size",
        type=int,
        default=100,
        help="Number of annotated rows to buffer before flushing to BigQuery.",
    )
    parser.add_argument(
        "-m",
        "--max-concurrency",
        type=int,
        default=8,
        help=f"Maximum number of concurrent requests (capped at {_MAX_CONCURRENT}).",
    )
    parser.add_argument(
        "-r",
        "--rate-limit",
        type=float,
        default=3.0,
        help="Maximum number of requests per second (0 for no limit).",
    )

    args = parser.parse_args()

    if args.chunk_size <= 0:
        parser.error("chunk-size must be a positive integer.")
    if args.flush_size <= 0:
        parser.error("flush-size must be a positive integer.")
    if args.max_concurrency <= 0:
        parser.error("max-concurrency must be a positive integer.")
    if args.max_concurrency > _MAX_CONCURRENT:
        logger.warning(
            "max-concurrency capped at %d to avoid excessive resource usage.", _MAX_CONCURRENT
        )
        args.max_concurrency = _MAX_CONCURRENT
    if args.rate_limit < 0:
        parser.error("rate-limit must be a non-negative number.")
    if args.rate_limit > 0 and args.rate_limit > args.max_concurrency:
        logger.warning("Capping rate-limit to max-concurrency.")
        args.rate_limit = float(args.max_concurrency)
    return args


def _tracking_table_schema() -> SchemaContext:
    """Return the schema and partition field for the tracking table."""
    schema = [
        bigquery.SchemaField("asset_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("path", "STRING", mode="REQUIRED"),
        # predictions
        bigquery.SchemaField("model", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("smile", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("eyes", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("face", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("skin_reveal", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("hand_placement", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("pose", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("accessories", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("movement", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("background", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("environment", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("color", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("framing", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("lighting", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("animal", "STRING", mode="REQUIRED"),
        # metadata
        bigquery.SchemaField("meta_insert_timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("meta_change_timestamp", "TIMESTAMP", mode="REQUIRED"),
    ]
    return SchemaContext(schema=schema, partition_field="meta_insert_timestamp")


def ensure_tracking_table(
    project_id: str, location: str, tracking_dataset: str, tracking_table: str
) -> None:
    """Create the tracking table if it does not already exist.

    Args:
        project_id: GCP project ID.
        location: GCP location for the BigQuery dataset.
        tracking_dataset: BigQuery dataset for tracking annotations.
        tracking_table: BigQuery table for tracking annotations.
    """
    with BigQueryProcessor(project_id, location) as bq:
        bq.create_table(tracking_dataset, tracking_table, _tracking_table_schema())


async def _annotate_row(
    row: dict[str, Any],
    agent_runner: AgentRunner,
) -> dict[str, Any] | None:
    """Annotate a single image row.

    Args:
        row: A dict of the row data from BigQuery.
        agent_runner: The AgentRunner instance to use for annotation.

    Returns:
        A dict ready for BQ insertion, or None if annotation failed.
    """
    asset_id = row["asset_id"]
    try:
        response = await agent_runner.run(
            user_id="image_annotator",
            session_id=asset_id,
            text="Can you annotate the following image?",
            img=row["path"],
        )
        logger.debug("Annotated asset %s.", asset_id)
        return {
            "asset_id": asset_id,
            "name": row["name"],
            "path": row["path"],
            **response.model_dump(),
            "meta_insert_timestamp": row["meta_insert_timestamp"].isoformat(),
            "meta_change_timestamp": pd.Timestamp.now("UTC").isoformat(),
        }
    except (httpx.HTTPStatusError, requests.exceptions.HTTPError) as exc:
        status = (
            exc.response.status_code
            if isinstance(exc, httpx.HTTPStatusError)
            else (exc.response.status_code if exc.response is not None else None)
        )
        if status == 404:
            logger.warning("Asset %s not found (404), skipping: %s", asset_id, row["path"])
        else:
            logger.error("HTTP error annotating asset %s: %s", asset_id, exc, exc_info=False)
        return None
    except TimeoutError:
        logger.error(
            "Asset %s timed out after all retries (model deadline exceeded), skipping.",
            asset_id,
        )
        return None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        detail = str(exc) or repr(exc)
        logger.error(
            "Failed to annotate asset %s [%s]: %s",
            asset_id,
            type(exc).__name__,
            detail,
            exc_info=False,
        )
        return None


async def main() -> None:
    """Main function to annotate images."""
    setup_logger(exclude_loggers=["google_genai.models"])
    args = args_parser()
    config = load_config("./configs/config.yaml")

    logger.info(
        "Starting image annotations (concurrency=%d, rate=%.1f rps).",
        args.max_concurrency,
        args.rate_limit,
    )

    ensure_tracking_table(
        args.project_id, args.location, args.tracking_dataset, args.tracking_table
    )
    logger.info("Tracking table ready.")

    agent_runner = AgentRunner(
        create_img_analysis_agent(args.project_id, config.agents["analyzer"])
    )

    query = load_sql_template(
        "./sql_queries/dam_article_pic.sql",
        {
            "tracking_table": (f"{args.project_id}.{args.tracking_dataset}.{args.tracking_table}"),
        },
    )

    with BigQueryProcessor(args.project_id, args.location) as bq:
        result: ChunkedQueryResult = await asyncio.to_thread(bq.query, query, args.chunk_size)
        logger.info("Query returned %s rows to annotate.", result.total_rows or "unknown")

        async def source() -> AsyncIterator[dict[str, Any]]:
            chunks_iter = iter(result.chunks)
            while True:
                chunk = await asyncio.to_thread(next, chunks_iter, None)
                if chunk is None:
                    break
                for row in cast(list[dict[str, Any]], chunk.to_dict("records")):
                    yield row

        async def worker(row: dict[str, Any]) -> dict[str, Any] | None:
            return await _annotate_row(row, agent_runner)

        async def sink(batch: list[dict[str, Any]]) -> None:
            await asyncio.to_thread(
                bq.insert_rows, batch, args.tracking_dataset, args.tracking_table
            )

        pipeline = AsyncPipeline(
            worker=worker,
            num_workers=args.max_concurrency,
            flush_size=args.flush_size,
            rate_limiter=RateLimiter(args.rate_limit),
        )
        stats = await pipeline.run(source=source(), sink=sink, total=result.total_rows)

    logger.info("Annotation run complete. %s", stats)


if __name__ == "__main__":
    asyncio.run(main())
