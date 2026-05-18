"""Unit tests for the BigQueryProcessor module."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from google.api_core.exceptions import BadRequest, GoogleAPICallError
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

from data_processing.bq_processor import (
    BigQueryProcessor,
    ChunkedQueryResult,
    SchemaContext,
)

PROJECT = "test-project"
LOCATION = "us-central1"
DATASET = "test_dataset"
TABLE = "test_table"


@pytest.fixture(name="mock_client")
def _mock_client() -> Iterator[MagicMock]:
    """Yield a MagicMock BigQuery client, patching construction."""
    with patch("data_processing.bq_processor.bigquery.Client", autospec=True) as mock_cls:
        yield mock_cls.return_value


@pytest.fixture(name="processor")
def _processor(mock_client: MagicMock) -> BigQueryProcessor:  # pylint: disable=unused-argument
    """Return a BigQueryProcessor backed by a mock BQ client.

    Depends on mock_client to ensure bigquery.Client is patched before construction.
    """
    return BigQueryProcessor(PROJECT, LOCATION, timeout=30)


class TestSchemaContext:
    """Tests for the SchemaContext dataclass."""

    def test_defaults(self) -> None:
        """Test that all fields default to None."""
        ctx = SchemaContext()
        assert ctx.schema is None
        assert ctx.clustering_fields is None
        assert ctx.partition_field is None

    def test_stores_values(self) -> None:
        """Test that provided values are stored correctly."""
        field = bigquery.SchemaField("col", "STRING")
        ctx = SchemaContext(schema=[field], clustering_fields=["col"], partition_field="col")
        assert ctx.schema == [field]
        assert ctx.clustering_fields == ["col"]
        assert ctx.partition_field == "col"

    def test_is_immutable(self) -> None:
        """Test that SchemaContext is frozen and rejects mutation."""
        ctx = SchemaContext()
        with pytest.raises(Exception):
            ctx.partition_field = "date"  # type: ignore[misc]


class TestChunkedQueryResult:
    """Tests for the ChunkedQueryResult dataclass."""

    def test_stores_values(self) -> None:
        """Test total_rows and chunks are accessible after construction."""
        chunks = iter([pd.DataFrame({"a": [1]})])
        result = ChunkedQueryResult(total_rows=1, chunks=chunks)
        assert result.total_rows == 1

    def test_none_total_rows(self) -> None:
        """Test that total_rows may be None when the count is unavailable."""
        result = ChunkedQueryResult(total_rows=None, chunks=iter([]))
        assert result.total_rows is None


class TestBigQueryProcessorInit:
    """Tests for BigQueryProcessor construction and resource management."""

    def test_client_created_with_correct_args(self) -> None:
        """Test the BQ client is initialised with the given project and location."""
        with patch("data_processing.bq_processor.bigquery.Client") as mock_cls:
            BigQueryProcessor(PROJECT, LOCATION)
            mock_cls.assert_called_once_with(project=PROJECT, location=LOCATION)

    def test_project_and_timeout_stored(self, processor: BigQueryProcessor) -> None:
        """Test that project and timeout are stored as instance attributes."""
        assert processor.project == PROJECT
        assert processor.timeout == 30

    def test_close_delegates_to_client(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that close() calls the underlying client's close method."""
        processor.close()
        mock_client.close.assert_called_once()

    def test_context_manager_returns_self(self, processor: BigQueryProcessor) -> None:
        """Test that the context manager yields the processor itself."""
        with processor as p:
            assert p is processor

    def test_context_manager_closes_on_exit(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that exiting the context manager calls close()."""
        with processor:
            pass
        mock_client.close.assert_called_once()


class TestDatasetOperations:
    """Tests for dataset existence checks, creation, and deletion."""

    def test_dataset_exists_returns_true(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test dataset_exists returns True when the BQ client finds the dataset."""
        mock_client.get_dataset.return_value = MagicMock()
        assert processor.dataset_exists(DATASET) is True
        mock_client.get_dataset.assert_called_once_with(
            f"{PROJECT}.{DATASET}", timeout=processor.timeout
        )

    def test_dataset_exists_returns_false_on_not_found(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test dataset_exists returns False when the dataset is not found."""
        mock_client.get_dataset.side_effect = NotFound("dataset")
        assert processor.dataset_exists(DATASET) is False

    def test_create_dataset_calls_client(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test create_dataset passes the correct ref and exists_ok=True."""
        processor.create_dataset(DATASET)
        mock_client.create_dataset.assert_called_once_with(
            f"{PROJECT}.{DATASET}", exists_ok=True, timeout=processor.timeout
        )

    def test_delete_dataset_calls_client(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test delete_dataset passes correct args including delete_contents and not_found_ok."""
        processor.delete_dataset(DATASET)
        mock_client.delete_dataset.assert_called_once_with(
            f"{PROJECT}.{DATASET}",
            timeout=processor.timeout,
            delete_contents=True,
            not_found_ok=True,
        )


class TestTableOperations:
    """Tests for table existence checks, creation, and deletion."""

    def test_table_exists_returns_true(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test table_exists returns True when the BQ client finds the table."""
        mock_client.get_table.return_value = MagicMock()
        assert processor.table_exists(DATASET, TABLE) is True
        mock_client.get_table.assert_called_once_with(
            f"{PROJECT}.{DATASET}.{TABLE}", timeout=processor.timeout
        )

    def test_table_exists_returns_false_on_not_found(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test table_exists returns False when the table is not found."""
        mock_client.get_table.side_effect = NotFound("table")
        assert processor.table_exists(DATASET, TABLE) is False

    def test_create_table_no_schema(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test create_table works without a SchemaContext (plain table)."""
        processor.create_table(DATASET, TABLE)
        mock_client.create_dataset.assert_called_once()
        mock_client.create_table.assert_called_once()
        created_table: bigquery.Table = mock_client.create_table.call_args.args[0]
        assert created_table.clustering_fields is None
        assert created_table.time_partitioning is None

    def test_create_table_with_clustering(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test create_table sets clustering_fields when provided in SchemaContext."""
        ctx = SchemaContext(clustering_fields=["col_a"])
        processor.create_table(DATASET, TABLE, schema_context=ctx)
        created_table: bigquery.Table = mock_client.create_table.call_args.args[0]
        assert created_table.clustering_fields == ["col_a"]

    def test_create_table_with_partition(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test create_table configures time partitioning when partition_field is set."""
        ctx = SchemaContext(partition_field="event_date")
        processor.create_table(DATASET, TABLE, schema_context=ctx)
        created_table: bigquery.Table = mock_client.create_table.call_args.args[0]
        assert created_table.time_partitioning is not None
        assert created_table.time_partitioning.field == "event_date"

    def test_delete_table_calls_client(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test delete_table passes the correct table ref and not_found_ok=True."""
        processor.delete_table(DATASET, TABLE)
        mock_client.delete_table.assert_called_once_with(
            f"{PROJECT}.{DATASET}.{TABLE}",
            timeout=processor.timeout,
            not_found_ok=True,
        )

    def test_get_table_schema_returns_schema(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test get_table_schema returns the schema from the fetched table object."""
        expected = [bigquery.SchemaField("id", "INTEGER")]
        mock_table = MagicMock()
        mock_table.schema = expected
        mock_client.get_table.return_value = mock_table
        assert processor.get_table_schema(DATASET, TABLE) == expected

    def test_get_table_schema_raises_not_found(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test get_table_schema re-raises NotFound when the table does not exist."""
        mock_client.get_table.side_effect = NotFound("table")
        with pytest.raises(NotFound):
            processor.get_table_schema(DATASET, TABLE)

    def test_get_table_schema_raises_api_error(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test get_table_schema re-raises GoogleAPICallError on API failure."""
        mock_client.get_table.side_effect = GoogleAPICallError("err")
        with pytest.raises(GoogleAPICallError):
            processor.get_table_schema(DATASET, TABLE)


class TestDryRun:
    """Tests for the _dry_run internal method."""

    def test_dry_run_sends_dry_run_config(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test _dry_run calls client.query with dry_run=True and use_query_cache=False."""
        processor._dry_run("SELECT 1")  # pylint: disable=protected-access
        job_config: bigquery.QueryJobConfig = mock_client.query.call_args.kwargs["job_config"]
        assert job_config.dry_run is True
        assert job_config.use_query_cache is False

    def test_dry_run_raises_bad_request(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test _dry_run re-raises BadRequest for invalid SQL."""
        mock_client.query.side_effect = BadRequest("syntax error")
        with pytest.raises(BadRequest):
            processor._dry_run("NOT SQL")  # pylint: disable=protected-access


class TestQuery:
    """Tests for the query() method."""

    def _mock_dry_run(self, mock_client: MagicMock, statement_type: str = "SELECT") -> None:
        """Configure the first client.query call to look like a dry-run job."""
        dry_run_job = MagicMock()
        dry_run_job.statement_type = statement_type
        dry_run_job.total_bytes_processed = 1024
        mock_client.query.return_value = dry_run_job

    def test_non_select_raises_value_error(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that passing a non-SELECT statement raises ValueError."""
        self._mock_dry_run(mock_client, statement_type="INSERT")
        with pytest.raises(ValueError, match="SELECT"):
            processor.query("INSERT INTO t VALUES (1)")

    def test_select_returns_dataframe(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that a SELECT query without chunk_size returns a DataFrame."""
        expected_df = pd.DataFrame({"col": [1, 2]})
        dry_run_job = MagicMock()
        dry_run_job.statement_type = "SELECT"
        dry_run_job.total_bytes_processed = 0
        exec_job = MagicMock()
        exec_job.result.return_value.to_dataframe.return_value = expected_df
        mock_client.query.side_effect = [dry_run_job, exec_job]

        result = processor.query("SELECT 1")

        assert isinstance(result, pd.DataFrame)
        pd.testing.assert_frame_equal(result, expected_df)

    def test_chunked_query_returns_chunked_result(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that chunk_size causes query() to return a ChunkedQueryResult."""
        df_chunk = pd.DataFrame({"col": [1]})
        dry_run_job = MagicMock()
        dry_run_job.statement_type = "SELECT"
        dry_run_job.total_bytes_processed = 0
        iterator = MagicMock()
        iterator.total_rows = 1
        iterator.to_dataframe_iterable.return_value = [df_chunk]
        exec_job = MagicMock()
        exec_job.result.return_value = iterator
        mock_client.query.side_effect = [dry_run_job, exec_job]

        result = processor.query("SELECT 1", chunk_size=100)

        assert isinstance(result, ChunkedQueryResult)
        assert result.total_rows == 1
        chunks = list(result.chunks)
        assert len(chunks) == 1
        pd.testing.assert_frame_equal(chunks[0], df_chunk)

    def test_chunked_query_skips_empty_frames(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that empty DataFrames are filtered out from the chunked iterator."""
        dry_run_job = MagicMock()
        dry_run_job.statement_type = "SELECT"
        dry_run_job.total_bytes_processed = 0
        iterator = MagicMock()
        iterator.total_rows = 0
        iterator.to_dataframe_iterable.return_value = [pd.DataFrame()]
        exec_job = MagicMock()
        exec_job.result.return_value = iterator
        mock_client.query.side_effect = [dry_run_job, exec_job]

        result = processor.query("SELECT 1", chunk_size=100)
        assert isinstance(result, ChunkedQueryResult)
        assert not list(result.chunks)

    def test_query_raises_api_error(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that GoogleAPICallError from execution is re-raised."""
        dry_run_job = MagicMock()
        dry_run_job.statement_type = "SELECT"
        dry_run_job.total_bytes_processed = 0
        mock_client.query.side_effect = [dry_run_job, GoogleAPICallError("quota")]

        with pytest.raises(GoogleAPICallError):
            processor.query("SELECT 1")


class TestLoadData:
    """Tests for load_data() and insert_rows()."""

    def test_load_dataframe_calls_load_table_from_dataframe(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that a DataFrame is loaded via load_table_from_dataframe."""
        df = pd.DataFrame({"a": [1]})
        processor.load_data(df, DATASET, TABLE)
        mock_client.load_table_from_dataframe.assert_called_once()
        call_args = mock_client.load_table_from_dataframe.call_args
        assert call_args.args[0] is df
        assert call_args.args[1] == f"{PROJECT}.{DATASET}.{TABLE}"

    def test_load_dict_calls_load_table_from_json(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that an iterable of dicts is loaded via load_table_from_json."""
        rows: list[dict[str, Any]] = [{"a": 1}]
        processor.load_data(rows, DATASET, TABLE)
        mock_client.load_table_from_json.assert_called_once()
        call_args = mock_client.load_table_from_json.call_args
        assert call_args.args[0] is rows
        assert call_args.args[1] == f"{PROJECT}.{DATASET}.{TABLE}"

    def test_default_write_disposition_is_truncate(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that the default write_disposition is WRITE_TRUNCATE."""
        processor.load_data(pd.DataFrame({"a": [1]}), DATASET, TABLE)
        job_config: bigquery.LoadJobConfig = mock_client.load_table_from_dataframe.call_args.kwargs[
            "job_config"
        ]
        assert job_config.write_disposition == "WRITE_TRUNCATE"

    def test_write_append_disposition(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that write_disposition=WRITE_APPEND is forwarded to the job config."""
        processor.load_data(
            pd.DataFrame({"a": [1]}), DATASET, TABLE, write_disposition="WRITE_APPEND"
        )
        job_config: bigquery.LoadJobConfig = mock_client.load_table_from_dataframe.call_args.kwargs[
            "job_config"
        ]
        assert job_config.write_disposition == "WRITE_APPEND"

    def test_load_raises_api_error(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test that GoogleAPICallError from the load job is re-raised."""
        mock_client.load_table_from_dataframe.return_value.result.side_effect = GoogleAPICallError(
            "err"
        )
        with pytest.raises(GoogleAPICallError):
            processor.load_data(pd.DataFrame({"a": [1]}), DATASET, TABLE)

    def test_insert_rows_delegates_to_load_data_with_append(
        self, processor: BigQueryProcessor, mock_client: MagicMock
    ) -> None:
        """Test insert_rows calls load_data with WRITE_APPEND disposition."""
        rows: list[dict[str, Any]] = [{"x": 1}]
        processor.insert_rows(rows, DATASET, TABLE)
        mock_client.load_table_from_json.assert_called_once()
        job_config: bigquery.LoadJobConfig = mock_client.load_table_from_json.call_args.kwargs[
            "job_config"
        ]
        assert job_config.write_disposition == "WRITE_APPEND"
