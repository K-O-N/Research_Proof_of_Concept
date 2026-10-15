# CMD Compound Screening Pipeline - Research_Proof_of_Concept

## Overview
A containerized data pipeline built to ingest, clean, and harmonize experimental data from multiple collaborating laboratories into a centralized PostgreSQL research database. This proof of concept ingests compound-screening data from three laboratories (Alpha, Beta and Gamma), cleans and harmonises the data, and loads it into PostgreSQL for centralised research and analysis.

**Technology:** Python, pandas, SQLAlchemy, PostgreSQL and Docker Compose.
## Prerequisites

- Git
- Docker Desktop or Docker Engine with Docker Compose
- The supplied laboratory datasets

## Getting Started

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd <repository-folder>
```

### 2. Configure the environment

Review the database connection settings in the application and Docker Compose configuration.

The current database connection uses:

- Database: `oxresearch`
- Host: `pgdatabase`
- Port: `5432`

Configure credentials through environment variables or your existing local configuration. Do not commit real credentials to Git.

### 3. Build and start PostgreSQL

```bash
docker compose build
docker compose up 
```

Wait until PostgreSQL is ready before running the pipeline.

### 4. Run ingestion and cleaning

Run the existing ingestion and cleaning scripts in the order defined by the repository to load the laboratory data into the staging schema.

### 5. Load the Gold model

Run the Gold loader using the appropriate Compose service:

```bash
docker compose run --rm <pipeline-service> \
  python <path-to-gold-loader>
```

Replace the placeholders with the actual service name and loader path in your repository.

### 6. Verify the results

Connect to PostgreSQL and inspect the tables.

**Staging schema:** Contains the ingested laboratory data.

**Gold schema:** Contains the harmonised analytical model:

- `gold.dim_compound`
- `gold.dim_lab`
- `gold.dim_assay`
- `gold.dim_target`
- `gold.dim_date`
- `gold.fact_screening_result`

Records that cannot be safely resolved are retained in `gold.quarantined_records`.

## Data Quality and Harmonisation

The pipeline includes cleaning and standardisation for whitespace, missing values, exact duplicate rows, dates and concentration units. It also applies controlled target and compound identity mappings.

Out-of-range inhibition values are preserved and flagged rather than silently modified. Separate experimental observations are retained.

## Stopping the Environment

```bash
docker compose down
```

To remove the database volume and its persisted data, use `docker compose down -v` **only when you intentionally want to reset the database**.

## Notes

This is a proof of concept. Review the project documentation for the architecture, source mappings, assumptions, data-quality rules, limitations and validation requirements.
