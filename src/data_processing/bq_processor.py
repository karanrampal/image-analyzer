"""Bigquery processor for data processing."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, Self, cast, overload

import pandas as pd
from google.api_core.exceptions import BadRequest, GoogleAPICallError
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SchemaContext:
    """Bundles the shared context for bq table schema."""

    schema: list[bigquery.SchemaField] | None = None
    clustering_fields: list[str] | None = None
    partition_field: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkedQueryResult:
    """Result of a chunked BigQuery query."""

    total_rows: int | None
    chunks: Iterable[pd.DataFrame]


class BigQueryProcessor:
    """Processor for BigQuery data."""

    def __init__(self, project_id: str, location: str, timeout: int = 90) -> None:
        """Initialize the BigQuery client.

        Args:
            project_id: GCP project ID.
            location: GCP location.
            timeout: Timeout for BigQuery operations in seconds.
        """
        self.project = project_id
        self.client = bigquery.Client(project=project_id, location=location)
        self.timeout = timeout

    def close(self) -> None:
        """Close the underlying BigQuery client and release its resources."""
        self.client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def dataset_exists(self, dataset_id: str) -> bool:
        """Check if a BigQuery dataset exists.

        Args:
            dataset_id: The ID of the dataset to check.

        Returns:
            True if the dataset exists, False otherwise.
        """
        dataset_ref = f"{self.project}.{dataset_id}"
        try:
            self.client.get_dataset(dataset_ref, timeout=self.timeout)
            return True
        except NotFound:
            return False

    def table_exists(self, dataset_id: str, table_id: str) -> bool:
        """Check if a BigQuery table exists.

        Args:
            dataset_id: The ID of the dataset containing the table.
            table_id: The ID of the table to check.

        Returns:
            True if the table exists, False otherwise.
        """
        table_ref = f"{self.project}.{dataset_id}.{table_id}"
        try:
            self.client.get_table(table_ref, timeout=self.timeout)
            return True
        except NotFound:
            return False

    def create_dataset(self, dataset_id: str) -> None:
        """Create a BigQuery dataset if it does not exist.

        Args:
            dataset_id: The ID of the dataset to create.
        """
        dataset_ref = f"{self.project}.{dataset_id}"
        self.client.create_dataset(dataset_ref, exists_ok=True, timeout=self.timeout)
        logger.debug("Dataset created (or already exists): %s", dataset_ref)

    def delete_dataset(self, dataset_id: str) -> None:
        """Delete a BigQuery dataset if it exists.

        Args:
            dataset_id: The ID of the dataset to delete.
        """
        dataset_ref = f"{self.project}.{dataset_id}"
        self.client.delete_dataset(
            dataset_ref, timeout=self.timeout, delete_contents=True, not_found_ok=True
        )
        logger.info("Dataset deleted (or did not exist): %s", dataset_ref)

    def create_table(
        self,
        dataset_id: str,
        table_id: str,
        schema_context: SchemaContext | None = None,
    ) -> None:
        """Create a BigQuery table if it does not exist. If dataset does not exist, it will be
        created.

        Args:
            dataset_id: The ID of the dataset to create the table in.
            table_id: The ID of the table to create.
            schema_context: The schema context containing the schema, clustering fields, and
            partition field.
        """
        dataset_ref = f"{self.project}.{dataset_id}"
        self.create_dataset(dataset_id)
        table_ref = f"{dataset_ref}.{table_id}"
        if not schema_context:
            schema_context = SchemaContext()

        table = bigquery.Table(table_ref, schema=schema_context.schema)
        if schema_context.clustering_fields:
            table.clustering_fields = schema_context.clustering_fields
        if schema_context.partition_field:
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field=schema_context.partition_field,
            )
        self.client.create_table(table, exists_ok=True, timeout=self.timeout)
        logger.debug("Table created (or already exists): %s", table_ref)

    def delete_table(self, dataset_id: str, table_id: str) -> None:
        """Delete a BigQuery table if it exists.

        Args:
            dataset_id: The ID of the dataset containing the table.
            table_id: The ID of the table to delete.
        """
        table_ref = f"{self.project}.{dataset_id}.{table_id}"
        self.client.delete_table(table_ref, timeout=self.timeout, not_found_ok=True)
        logger.info("Table deleted (or did not exist): %s", table_ref)

    def get_table_schema(self, dataset_id: str, table_id: str) -> list[bigquery.SchemaField]:
        """Retrieve the schema of a BigQuery table.

        Args:
            dataset_id: The ID of the dataset containing the table.
            table_id: The ID of the table to retrieve the schema for.

        Returns:
            A list of SchemaField objects representing the table schema.

        Raises:
            NotFound: If the table does not exist.
            GoogleAPICallError: If the API call fails.
        """
        table_ref = f"{self.project}.{dataset_id}.{table_id}"
        try:
            table = self.client.get_table(table_ref, timeout=self.timeout)
            return table.schema
        except NotFound:
            logger.exception("Table not found: %s", table_ref)
            raise
        except GoogleAPICallError:
            logger.exception("Failed to retrieve schema for table: %s", table_ref)
            raise

    def _dry_run(self, query: str) -> bigquery.QueryJob:
        """Validate a SQL query via a dry-run and return the job.

        Args:
            query: The SQL query to validate.

        Returns:
            The completed dry-run QueryJob.

        Raises:
            BadRequest: If the query is syntactically invalid.
        """
        try:
            job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
            return self.client.query(query, job_config=job_config)
        except BadRequest:
            logger.exception("Invalid query: %s", query)
            raise

    @overload
    def query(
        self, query: str, chunk_size: None = None, cost_multiplier: float = 6.25e-12
    ) -> pd.DataFrame: ...

    @overload
    def query(
        self, query: str, chunk_size: int, cost_multiplier: float = 6.25e-12
    ) -> ChunkedQueryResult: ...

    def query(
        self, query: str, chunk_size: int | None = None, cost_multiplier: float = 6.25e-12
    ) -> pd.DataFrame | ChunkedQueryResult:
        """Execute a SQL query and return the results.

        Args:
            query: The SQL query to execute.
            chunk_size: If provided, the number of rows to pull per page/chunk. The method
                will yield DataFrames of up to chunk_size rows. If None, returns a single
                DataFrame with all results.
            cost_multiplier: Multiplier to apply to the cost calculation for logging purposes,
            default is 6.25e-12 assuming $6.25 per TB.

        Returns:
            A pandas DataFrame containing the query results if chunk_size is None.
            A ChunkedQueryResult with total_rows and an iterable of DataFrames if chunk_size
            is provided.

        Raises:
            GoogleAPICallError: If the query fails due to an API error (e.g. invalid SQL,
            quota exceeded, insufficient permissions).
            ValueError: If the query contains DML/DDL statements (INSERT, UPDATE, DELETE,
            MERGE, DROP, CREATE, TRUNCATE, ALTER). Use load_data() or
            insert_rows() for writes.
        """
        dry_run_job = self._dry_run(query)
        if dry_run_job.statement_type != "SELECT":
            raise ValueError(
                "query() only supports SELECT statements. "
                "Use load_data() or insert_rows() for writes."
            )
        estimated_bytes = dry_run_job.total_bytes_processed or 0
        logger.debug(
            "Estimated bytes to process: %.2fMB, estimated cost: $%.2f",
            estimated_bytes / (1024 * 1024),
            estimated_bytes * cost_multiplier,
        )

        try:
            job = self.client.query(query, timeout=self.timeout)

            if chunk_size is not None:
                iterator = job.result(page_size=chunk_size, timeout=self.timeout)

                def _generator() -> Iterable[pd.DataFrame]:
                    for raw in iterator.to_dataframe_iterable():
                        df = cast(pd.DataFrame, raw)
                        if not df.empty:
                            yield df

                return ChunkedQueryResult(total_rows=iterator.total_rows, chunks=_generator())

            return job.result(timeout=self.timeout).to_dataframe()

        except GoogleAPICallError:
            logger.exception("BigQuery query failed: %.100s", query)
            raise

    def insert_rows(
        self, data: Iterable[dict[str, Any]] | pd.DataFrame, dataset_id: str, table_id: str
    ) -> None:
        """Append rows into a BigQuery table using a load job.

        Uses the batch load API (WRITE_APPEND) rather than the streaming insert API,
        which is cheaper, atomic, and avoids duplicate rows. Data will be available
        for querying once the load job completes.

        Args:
            data: The data to insert, either as an iterable of dictionaries or a pandas DataFrame.
            dataset_id: The ID of the dataset containing the table.
            table_id: The ID of the table to insert the rows into.

        Raises:
            GoogleAPICallError: If the load job fails.
        """
        self.load_data(
            data,
            dataset_id,
            table_id,
            write_disposition="WRITE_APPEND",
        )

    def load_data(
        self,
        data: Iterable[dict[str, Any]] | pd.DataFrame,
        dataset_id: str,
        table_id: str,
        write_disposition: Literal["WRITE_TRUNCATE", "WRITE_APPEND"] = "WRITE_TRUNCATE",
    ) -> None:
        """Load data into a BigQuery table using a batch load job.

        Blocks until the job completes. Suitable for both full replacements and appends.

        Args:
            data: The data to load, either as an iterable of dictionaries or a pandas DataFrame.
            dataset_id: The ID of the dataset to load the table into.
            table_id: The ID of the table to load the data into.
            write_disposition: Controls how existing data is handled. Defaults to
                WRITE_TRUNCATE (replace all data). Use WRITE_APPEND to add rows.

        Raises:
            GoogleAPICallError: If the load job fails.
        """
        table_ref = f"{self.project}.{dataset_id}.{table_id}"
        job_config = bigquery.LoadJobConfig(write_disposition=write_disposition)
        try:
            if isinstance(data, pd.DataFrame):
                self.client.load_table_from_dataframe(
                    data, table_ref, job_config=job_config, timeout=self.timeout
                ).result(timeout=self.timeout)
            else:
                self.client.load_table_from_json(
                    data, table_ref, job_config=job_config, timeout=self.timeout
                ).result(timeout=self.timeout)
        except GoogleAPICallError:
            logger.exception("BigQuery load job failed for %s", table_ref)
            raise
