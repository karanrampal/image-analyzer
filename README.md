# Image Analysis

A pipeline that fetches fashion product images from Google Cloud, annotates them using a Gemini LLM agent, and writes structured results back to BigQuery.

## Overview

The pipeline runs in three stages:

1. **Source** — Queries BigQuery to retrieve unannotated image URLs in chunks.
2. **Worker** — Downloads each image and sends it to a LangGraph agent backed by Google Gemini, which returns a structured set of visual attributes.
3. **Sink** — Flushes annotation batches back to a BigQuery tracking table.

Back-pressure is built in: a slow sink naturally throttles workers, and a configurable rate limiter caps requests to the LLM API.

### Annotation attributes

The agent classifies each image across 15 visual dimensions:

| Attribute | Description |
|---|---|
| `model` | Is a human model present? (`yes` / `no` / `multiple`) |
| `smile` | Model's smile (`no` / `closed mouth` / `open mouth`) |
| `eyes` | Eye visibility (`full` / `partial` / `not visible` / `eye contact`) |
| `face` | Is the face visible? |
| `skin_reveal` | Prominent display of bare skin? |
| `hand_placement` | Position of the model's hands |
| `pose` | Primary pose / orientation |
| `accessories` | Fashion accessories present? |
| `movement` | Static pose or sense of movement? |
| `background` | Distinct background vs. plain studio void? |
| `environment` | `indoor` / `outdoor` |
| `color` | `colored` / `b/w` |
| `framing` | Shot crop / framing type |
| `lighting` | Color temperature / mood |
| `animal` | Is an animal present? |

Model-dependent fields (`smile`, `eyes`, `face`, etc.) are set to `null` when no model is detected.

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Agent orchestration | LangGraph + LangChain |
| LLM | Google Gemini (`gemini-3.1-pro-preview`) via `langchain-google-genai` |
| Data source / sink | Google Cloud BigQuery |
| Image storage | Google Cloud Storage (via `gcsfs`) |
| Data validation | Pydantic v2 |
| Infrastructure | Terraform |
| Deployment | Docker + Google Cloud Run Jobs |
| Dependency management | [uv](https://github.com/astral-sh/uv) |

## Project Structure

```
src/
├── annotate.py              # Entry point — CLI arg parsing and pipeline wiring
├── agents/
│   ├── agent_runner.py      # AgentRunner: wraps a compiled LangGraph graph
│   ├── analyzer.py          # Creates the Gemini-backed analysis agent
│   └── instructions/
│       ├── data_models.py   # Pydantic output schema (FashionImageAnnotation)
│       └── system_prompts.py
├── core/
│   ├── config.py            # Config loading from configs/config.yaml
│   ├── logger.py            # Structured logging setup
│   ├── pipeline.py          # Async producer-consumer pipeline
│   └── rate_limiter.py      # Token-bucket rate limiter
└── data_processing/
    ├── bq_processor.py      # BigQuery read / write helpers
    ├── image_processor.py   # Image download and base64 encoding
    └── utils.py
configs/
└── config.yaml              # Project ID, model name, agent parameters
terraform/                   # GCP infrastructure (BigQuery, Artifact Registry, monitoring)
tests/
├── unit_tests/
├── integration_tests/
└── performance_tests/
```

## Getting Started

### Prerequisites

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) package manager
- GCP credentials with access to BigQuery and GCS (e.g. `gcloud auth application-default login`)

### Installation

```bash
# Install runtime dependencies only
make install

# Install all dependencies including dev tools
make install-all
```

### Configuration

Edit `configs/config.yaml` to set your GCP project, location, and model parameters:

```yaml
project:
  id: "your-gcp-project-id"
  location: "europe-west1"

agents:
  analyzer:
    model_name: "gemini-3.1-pro-preview"
    temperature: 1.0
    thinking_level: "low"
    max_output_tokens: 2048
```

### Running locally

```bash
python src/annotate.py \
  --project-id your-gcp-project-id \
  --location europe-west1 \
  --tracking-dataset img_annotations_trf \
  --tracking-table generated_attributes_tmp \
  --chunk-size 500 \
  --flush-size 100 \
  --max-concurrency 8 \
  --rate-limit 5
```

Key arguments:

| Flag | Default | Description |
|---|---|---|
| `--project-id` | `hm-studios-metadata-c54a` | GCP project for BigQuery |
| `--tracking-dataset` | `img_annotations_trf` | BigQuery dataset for results |
| `--tracking-table` | `generated_attributes_tmp` | BigQuery table for results |
| `--chunk-size` | `500` | Rows fetched per BigQuery query |
| `--flush-size` | `100` | Annotation rows buffered before each BQ write |
| `--max-concurrency` | `8` | Parallel LLM requests (capped at 32) |
| `--rate-limit` | `5` | Max LLM requests per second |

## Deployment

### Build and push Docker image

```bash
make docker-bp DOCKERFILE=Dockerfile
```

### Deploy to Cloud Run Jobs

```bash
bash scripts/run_cr_job.sh
```

The Cloud Run job is configured with 2 vCPUs, 6 Gi memory, and a 24-hour timeout.

### Infrastructure (Terraform)

```bash
cd terraform
terraform init
terraform apply -var-file=dev.tfvars   # or prod.tfvars
```

## Development

```bash
make format      # Format code with ruff
make typecheck   # Run mypy type checking
make lint        # Lint with pylint
make test        # Unit tests with coverage
make test-int    # Integration tests (requires network access)
make test-perf   # Performance benchmarks
make precommit   # format + lint + typecheck + test
```
