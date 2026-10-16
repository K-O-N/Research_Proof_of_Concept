import json
import os
import pandas as pd
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text, URL


TARGET_SCHEMA = "gold"
STAGING_SCHEMA = "staging"
# DATABASE_URL = os.getenv(
#     "DATABASE_URL",
#     'postgresql+psycopg2://researchlab:researchlab@pgdatabase:5432/oxresearch',)

DATABASE_URL = URL.create(
    "postgresql+psycopg2",
    username=os.getenv("PG_USER"),
    password=os.getenv("PG_PASSWORD"),
    host="pgdatabase",
    port=5432,
    database=os.getenv("PG_DB", "oxresearch"),
)



DDL = """
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.dim_compound (
    compound_key BIGSERIAL PRIMARY KEY,
    preferred_name TEXT,
    smiles TEXT,
    identity_method TEXT NOT NULL DEFAULT 'UNRESOLVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_dim_compound_smiles UNIQUE (smiles)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dim_compound_preferred_name
    ON gold.dim_compound (preferred_name) WHERE smiles IS NULL AND preferred_name IS NOT NULL;

CREATE TABLE IF NOT EXISTS gold.dim_lab (
    lab_key BIGSERIAL PRIMARY KEY,
    lab_name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gold.dim_target (
    target_key BIGSERIAL PRIMARY KEY,
    target_name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gold.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.dim_assay (
    assay_key BIGSERIAL PRIMARY KEY,
    lab_key BIGINT NOT NULL REFERENCES gold.dim_lab(lab_key),
    source_assay_id TEXT NOT NULL,
    assay_type TEXT,
    assay_format TEXT NOT NULL DEFAULT 'single_point',
    instrument_name TEXT,
    operator_name TEXT,
    nominal_concentration_nm NUMERIC,
    qc_rule TEXT,
    source_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_dim_assay_source UNIQUE (lab_key, source_assay_id)
);

CREATE TABLE IF NOT EXISTS gold.fact_screening_result (
    screening_result_key BIGSERIAL PRIMARY KEY,
    source_record_id TEXT NOT NULL UNIQUE,
    compound_key BIGINT NOT NULL REFERENCES gold.dim_compound(compound_key),
    lab_key BIGINT NOT NULL REFERENCES gold.dim_lab(lab_key),
    assay_key BIGINT NOT NULL REFERENCES gold.dim_assay(assay_key),
    target_key BIGINT NOT NULL REFERENCES gold.dim_target(target_key),
    date_key INTEGER REFERENCES gold.dim_date(date_key),
    concentration_nm NUMERIC,
    inhibition_pct NUMERIC,
    is_out_of_range BOOLEAN NOT NULL DEFAULT FALSE,
    qc_status TEXT NOT NULL DEFAULT 'NOT_ASSESSED'
        CHECK (qc_status IN ('PASS', 'FAIL', 'NOT_ASSESSED')),
    source_compound_id TEXT,
    source_sample_id TEXT,
    source_plate TEXT,
    source_well TEXT,
    is_replicate BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fact_screening_compound ON gold.fact_screening_result(compound_key);
CREATE INDEX IF NOT EXISTS ix_fact_screening_date ON gold.fact_screening_result(date_key);
CREATE INDEX IF NOT EXISTS ix_fact_screening_lab ON gold.fact_screening_result(lab_key);

CREATE TABLE IF NOT EXISTS gold.quarantined_records (
    quarantine_key BIGSERIAL PRIMARY KEY,
    source_record_id TEXT NOT NULL UNIQUE,
    source_table TEXT NOT NULL,
    reason TEXT NOT NULL,
    record_payload JSONB NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""




def is_missing(value):
    """Safely check if a value is null, None, or missing across different data types."""
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def val(row, *names, default=None):
    """Look through multiple alternative column names in a row and return the first valid, non-missing value."""
    for name in names:
        if name in row and not is_missing(row[name]):
            return row[name]
    return default


def as_text(value):
    """Safely convert a value to a clean string, or return None if it is missing."""
    return None if is_missing(value) else str(value).strip()


def as_decimal(value):
    """Safely convert a value to a high-precision Decimal type (vital for science data), returning None if invalid."""
    if is_missing(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def as_date(value):
    """Safely parse a date value into a standard Python date object, returning None if parsing fails."""
    if is_missing(value):
        return None
    try:
        return pd.to_datetime(value, errors="raise").date()
    except (ValueError, TypeError):
        return None


def read_table(conn, table):
    """Helper function to load an entire staging table from the database into a Pandas DataFrame."""
    return pd.read_sql_query(text(f'SELECT * FROM "{STAGING_SCHEMA}"."{table}"'), conn)



def gamma_metadata(df):
    """Convert Lab Gamma's vertical key-value metadata table into a clean, searchable Python dictionary."""
    if df.empty or not {"field", "value"}.issubset(df.columns):
        return {}
    return {
        str(r["field"]).strip().lower(): None if is_missing(r["value"]) else str(r["value"]).strip()
        for _, r in df.iterrows()
    }


def payload(row):
    """Convert a DataFrame row into a dictionary for JSONB storage, handling dates and missing values cleanly."""
    return {str(k): (None if is_missing(v) else (v.isoformat() if hasattr(v, "isoformat") else str(v))) for k, v in row.items()}


def upsert_lab(conn, name):
    return conn.execute(text("""
        INSERT INTO gold.dim_lab(lab_name) VALUES (:name)
        ON CONFLICT (lab_name) DO UPDATE SET updated_at = now()
        RETURNING lab_key
    """), {"name": name}).scalar_one()


# Define a function to upsert a target into the dimension table
def upsert_target(conn, name):
    return conn.execute(text("""
        INSERT INTO gold.dim_target(target_name) VALUES (:name)
        ON CONFLICT (target_name) DO UPDATE SET updated_at = now()
        RETURNING target_key
    """), {"name": name}).scalar_one()


def upsert_date(conn, d):
    if d is None:
        return None
    key = d.year * 10000 + d.month * 100 + d.day
    conn.execute(text("""
        INSERT INTO gold.dim_date(date_key, full_date, year, month, day)
        VALUES (:key, :full_date, :year, :month, :day)
        ON CONFLICT (date_key) DO UPDATE SET full_date=EXCLUDED.full_date
    """), {"key": key, "full_date": d, "year": d.year, "month": d.month, "day": d.day})
    return key


def upsert_assay(conn, lab_key, source_assay_id, assay_type, instrument, operator, nominal, qc_rule, notes):
    return conn.execute(text("""
        INSERT INTO gold.dim_assay
          (lab_key, source_assay_id, assay_type, assay_format, instrument_name,
           operator_name, nominal_concentration_nm, qc_rule, source_notes)
        VALUES (:lab_key, :source_assay_id, :assay_type, 'single_point', :instrument,
                :operator, :nominal, :qc_rule, :notes)
        ON CONFLICT (lab_key, source_assay_id) DO UPDATE SET
          assay_type=EXCLUDED.assay_type,
          assay_format=EXCLUDED.assay_format,
          instrument_name=EXCLUDED.instrument_name,
          operator_name=EXCLUDED.operator_name,
          nominal_concentration_nm=EXCLUDED.nominal_concentration_nm,
          qc_rule=EXCLUDED.qc_rule,
          source_notes=EXCLUDED.source_notes,
          updated_at=now()
        RETURNING assay_key
    """), {"lab_key": lab_key, "source_assay_id": source_assay_id,
          "assay_type": assay_type, "instrument": instrument, "operator": operator,
          "nominal": nominal, "qc_rule": qc_rule, "notes": notes}).scalar_one()


def resolve_compound(conn, preferred_name, smiles):
    """Match exact supplied SMILES first. No chemical canonicalisation is performed."""
    name, smiles = as_text(preferred_name), as_text(smiles)

    # Path A: Process records that have a structural SMILES string
    if smiles:
        found = conn.execute(text("SELECT compound_key FROM gold.dim_compound WHERE smiles=:smiles"), {"smiles": smiles}).scalar()
        if found:
            # Update existing record with a missing name or upgrade its identity resolution method
            conn.execute(text("""
                UPDATE gold.dim_compound SET
                  preferred_name=COALESCE(preferred_name, :name),
                  identity_method=CASE WHEN identity_method='UNRESOLVED' THEN 'SMILES_EXACT' ELSE identity_method END,
                  updated_at=now()
                WHERE compound_key=:key
            """), {"name": name, "key": found})
            return found
        
        # Look for an older record that previously only had a name and no SMILES
        if name:
            found = conn.execute(text("""
                SELECT compound_key FROM gold.dim_compound
                WHERE preferred_name=:name AND smiles IS NULL ORDER BY compound_key LIMIT 1
            """), {"name": name}).scalar()
            if found:
                # Enrich the old name-only record by adding the newly provided SMILES string
                conn.execute(text("""UPDATE gold.dim_compound SET smiles=:smiles,
                    identity_method='SMILES_EXACT', updated_at=now() WHERE compound_key=:key"""),
                    {"smiles": smiles, "key": found})
                return found
        
        # Insert a brand new compound record or handle duplicate SMILES conflicts safely
        return conn.execute(text("""
            INSERT INTO gold.dim_compound(preferred_name, smiles, identity_method)
            VALUES (:name, :smiles, 'SMILES_EXACT')
            ON CONFLICT (smiles) DO UPDATE SET
              preferred_name=COALESCE(gold.dim_compound.preferred_name, EXCLUDED.preferred_name),
              updated_at=now()
            RETURNING compound_key
        """), {"name": name, "smiles": smiles}).scalar_one()

    # Path B: Fallback when no SMILES is available, matching strictly by name Check if an identical name-only record already exists without a structure
    if name:
        found = conn.execute(text("""
            SELECT compound_key FROM gold.dim_compound
            WHERE preferred_name=:name AND smiles IS NULL ORDER BY compound_key LIMIT 1
        """), {"name": name}).scalar()
        if found:
            return found
        
        # Insert a new name-only record using the partial index constraint to prevent duplicates
        return conn.execute(text("""
            INSERT INTO gold.dim_compound(preferred_name, smiles, identity_method)
            VALUES (:name, NULL, 'PREFERRED_NAME_NO_SMILES')
            ON CONFLICT (preferred_name) WHERE smiles IS NULL AND preferred_name IS NOT NULL
            DO UPDATE SET updated_at=now()
            RETURNING compound_key
        """), {"name": name}).scalar_one()
    return None


def quarantine(conn, source_record_id, source_table, reason, row_payload):
    conn.execute(text("""
        INSERT INTO gold.quarantined_records(source_record_id, source_table, reason, record_payload)
        VALUES (:id, :table, :reason, CAST(:payload AS jsonb))
        ON CONFLICT (source_record_id) DO UPDATE SET
          source_table=EXCLUDED.source_table, reason=EXCLUDED.reason,
          record_payload=EXCLUDED.record_payload, last_seen_at=now()
    """), {"id": source_record_id, "table": source_table, "reason": reason,
          "payload": json.dumps(row_payload, default=str)})




def validate_gold_data(conn):
    """Validate Gold primary keys, foreign keys and referential integrity."""

    checks = {
        # Primary keys: NULL values or duplicate key values
        "dim_compound PK": """
            SELECT COUNT(*) FROM (
                SELECT compound_key
                FROM gold.dim_compound
                GROUP BY compound_key
                HAVING compound_key IS NULL OR COUNT(*) > 1
            ) x
        """,
        "dim_lab PK": """
            SELECT COUNT(*) FROM (
                SELECT lab_key FROM gold.dim_lab
                GROUP BY lab_key
                HAVING lab_key IS NULL OR COUNT(*) > 1
            ) x
        """,
        "dim_assay PK": """
            SELECT COUNT(*) FROM (
                SELECT assay_key FROM gold.dim_assay
                GROUP BY assay_key
                HAVING assay_key IS NULL OR COUNT(*) > 1
            ) x
        """,
        "dim_target PK": """
            SELECT COUNT(*) FROM (
                SELECT target_key FROM gold.dim_target
                GROUP BY target_key
                HAVING target_key IS NULL OR COUNT(*) > 1
            ) x
        """,
        "dim_date PK": """
            SELECT COUNT(*) FROM (
                SELECT date_key FROM gold.dim_date
                GROUP BY date_key
                HAVING date_key IS NULL OR COUNT(*) > 1
            ) x
        """,
        "fact_screening_result PK": """
            SELECT COUNT(*) FROM (
                SELECT screening_result_key
                FROM gold.fact_screening_result
                GROUP BY screening_result_key
                HAVING screening_result_key IS NULL
                    OR COUNT(*) > 1
            ) x
        """,

        # Foreign keys: fact records must reference existing dimensions
        "Fact -> compound": """
            SELECT COUNT(*)
            FROM gold.fact_screening_result f
            LEFT JOIN gold.dim_compound d
                ON f.compound_key = d.compound_key
            WHERE d.compound_key IS NULL
        """,
        "Fact -> lab": """
            SELECT COUNT(*)
            FROM gold.fact_screening_result f
            LEFT JOIN gold.dim_lab d ON f.lab_key = d.lab_key
            WHERE d.lab_key IS NULL
        """,
        "Fact -> assay": """
            SELECT COUNT(*)
            FROM gold.fact_screening_result f
            LEFT JOIN gold.dim_assay d ON f.assay_key = d.assay_key
            WHERE d.assay_key IS NULL
        """,
        "Fact -> target": """
            SELECT COUNT(*)
            FROM gold.fact_screening_result f
            LEFT JOIN gold.dim_target d ON f.target_key = d.target_key
            WHERE d.target_key IS NULL
        """,
        "Fact -> date": """
            SELECT COUNT(*)
            FROM gold.fact_screening_result f
            LEFT JOIN gold.dim_date d ON f.date_key = d.date_key
            WHERE f.date_key IS NOT NULL AND d.date_key IS NULL
        """,
        "Assay -> lab": """
            SELECT COUNT(*)
            FROM gold.dim_assay a
            LEFT JOIN gold.dim_lab l ON a.lab_key = l.lab_key
            WHERE l.lab_key IS NULL
        """,

        # A fact's lab must agree with the lab assigned to its assay
        "Fact lab matches assay lab": """
            SELECT COUNT(*)
            FROM gold.fact_screening_result f
            JOIN gold.dim_assay a ON f.assay_key = a.assay_key
            WHERE f.lab_key <> a.lab_key
        """,

        # Business-key uniqueness
        "Duplicate source records": """
            SELECT COUNT(*) FROM (
                SELECT source_record_id
                FROM gold.fact_screening_result
                GROUP BY source_record_id
                HAVING source_record_id IS NULL OR COUNT(*) > 1
            ) x
        """,
        "Duplicate lab and source assay": """
            SELECT COUNT(*) FROM (
                SELECT lab_key, source_assay_id
                FROM gold.dim_assay
                GROUP BY lab_key, source_assay_id
                HAVING COUNT(*) > 1
            ) x
        """,
    }

    failures = []

    for test_name, sql in checks.items():
        failed_rows = conn.execute(text(sql)).scalar_one()

        if failed_rows:
            failures.append(f"{test_name}: {failed_rows} violation(s)")
            print(f"FAIL: {test_name} — {failed_rows} violation(s)")
        else:
            print(f"PASS: {test_name}")

    if failures:
        raise RuntimeError(
            "Gold data quality validation failed:\n"
            + "\n".join(failures)
        )

    print(f"All {len(checks)} Gold data quality checks passed.")




def upsert_fact(conn, record):
    conn.execute(text("""
      INSERT INTO gold.fact_screening_result
       (source_record_id, compound_key, lab_key, assay_key, target_key, date_key,
        concentration_nm, inhibition_pct, is_out_of_range, qc_status, source_compound_id,
        source_sample_id, source_plate, source_well, is_replicate)
      VALUES (:source_record_id, :compound_key, :lab_key, :assay_key, :target_key, :date_key,
        :concentration_nm, :inhibition_pct, :is_out_of_range, :qc_status, :source_compound_id, 
        :source_sample_id, :source_plate, :source_well, :is_replicate)
      ON CONFLICT (source_record_id) DO UPDATE SET
        compound_key=EXCLUDED.compound_key,
        lab_key=EXCLUDED.lab_key, assay_key=EXCLUDED.assay_key, target_key=EXCLUDED.target_key,
        date_key=EXCLUDED.date_key, concentration_nm=EXCLUDED.concentration_nm,
        inhibition_pct=EXCLUDED.inhibition_pct, is_out_of_range=EXCLUDED.is_out_of_range,
        qc_status=EXCLUDED.qc_status, source_compound_id=EXCLUDED.source_compound_id,
        source_sample_id=EXCLUDED.source_sample_id, source_plate=EXCLUDED.source_plate,
        source_well=EXCLUDED.source_well, is_replicate=EXCLUDED.is_replicate,
        updated_at=now()
    """), record)


def main():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    counts = {"facts_upserted": 0, "quarantined": 0}
    with engine.begin() as conn:
        # CREATE IF NOT EXISTS only: existing Gold tables are never dropped or recreated.
        for statement in DDL.split(";"):
            if statement.strip():
                conn.execute(text(statement))

        # Read cleaned staging data. A missing expected table is an explicit error.
        a_comp = read_table(conn, "stg_lab_alpha_compounds")
        a_res = read_table(conn, "stg_lab_alpha_assay_results")
        a_meta = read_table(conn, "stg_lab_alpha_assay_metadata")
        b_comp = read_table(conn, "stg_lab_beta_compounds")
        b_res = read_table(conn, "stg_lab_beta_screening")
        b_meta_df = read_table(conn, "stg_lab_beta_experiment")
        g_map = read_table(conn, "stg_lab_gamma_compound_mapping")
        g_meta_df = read_table(conn, "stg_lab_gamma_metadata")
        g_res = read_table(conn, "stg_lab_gamma_plate_export")

        # Build metadata lookups from the already-cleaned staging values.
        alpha_meta = a_meta.iloc[0].to_dict() if not a_meta.empty else {}
        beta_meta = b_meta_df.iloc[0].to_dict() if not b_meta_df.empty else {}
        gamma_meta = gamma_metadata(g_meta_df)

        # Map and standardize disparate lab metadata into a single unified configuration dictionary
        lab_info = {
          "alpha": {"name": "Alpha", "target": val(alpha_meta, "target", default="USP30"),
                    "assay_type": val(alpha_meta, "assay_type"), "instrument": val(alpha_meta, "instrument"),
                    "operator": val(alpha_meta, "operator"), "date": as_date(val(alpha_meta, "run_date")),
                    "assay_id": val(alpha_meta, "assay_id", default="ALPHA-ASSAY-01"),
                    "nominal": Decimal("100"), "qc_rule": None, "notes": None},
          "beta": {"name": val(beta_meta, "lab", default="Beta"), "target": val(beta_meta, "target", default="USP30"),
                   "assay_type": val(beta_meta, "assay_type"), "instrument": val(beta_meta, "instrument"),
                   "operator": val(beta_meta, "operator"), "date": as_date(val(beta_meta, "screening_date")),
                   "assay_id": "BETA-EXPERIMENT-01", "nominal": Decimal("100"),
                   "qc_rule": "QC supplied by source; original threshold retained in notes",
                   "notes": val(beta_meta, "notes")},
          "gamma": {"name": gamma_meta.get("lab_name", "Gamma"),
                    "target": gamma_meta.get("target", "USP30"), "assay_type": gamma_meta.get("assay_type"),
                    "instrument": gamma_meta.get("instrument"), "operator": gamma_meta.get("operator"),
                    "date": as_date(gamma_meta.get("screening_date")), "assay_id": "GAMMA-EXPERIMENT-01",
                    "nominal": as_decimal(gamma_meta.get("concentration_nm")) or Decimal("100"),
                    "qc_rule": None, "notes": None},
        }

        # Registry records from all labs are used to resolve shared compounds.
        # Build a unified in-memory lookup registry mapping lab-specific compound IDs to their names and SMILES structures
        registry = {}
        for _, r in a_comp.iterrows():
            registry[("alpha", as_text(val(r, "compound_id")))] = {
                "name": as_text(val(r, "compound_name")), "smiles": as_text(val(r, "smiles"))}
        for _, r in b_comp.iterrows():
            registry[("beta", as_text(val(r, "compound_id")))] = {
                "name": as_text(val(r, "compound_name")), "smiles": as_text(val(r, "smiles"))}
        gamma_names = {}
        for _, r in g_map.iterrows():
            gamma_names[as_text(val(r, "local_id"))] = as_text(val(r, "preferred_name"))

        # Fill missing SMILES only from an unambiguous exact preferred-name registry match.
        # Cross-enrich missing SMILES strings using shared compound names across labs while safely flagging naming conflicts
        name_smiles = {}
        ambiguous_names = set()
        for entry in registry.values():
            n, s = entry["name"], entry["smiles"]
            if n and s:
                if n in name_smiles and name_smiles[n] != s:
                    ambiguous_names.add(n)
                else:
                    name_smiles[n] = s
        for entry in registry.values():
            if not entry["smiles"] and entry["name"] and entry["name"] not in ambiguous_names:
                entry["smiles"] = name_smiles.get(entry["name"])

        # Validate metadata values before conformance; preserve unexpected values and warn.
        known_target_values = {"usp-30", "usp30", "ubiquitin specific protease 30"}
        known_assay_types = {"biochemical ic50", "fluorescence biochemical"}
        for lab, info in lab_info.items():
            target_value = str(info["target"] or "").strip()
            assay_value = str(info["assay_type"] or "").strip()

            # Validate lab metadata against known whitelists, print warnings for unrecognized values without halting the pipeline
            if target_value.lower() not in known_target_values:
                print(f"WARNING: {lab} target metadata is missing or unrecognised: {target_value!r}")
            if assay_value.lower() not in known_assay_types:
                print(f"WARNING: {lab} assay_type metadata is missing or unrecognised: {assay_value!r}")

        # Upsert dimension records for labs, targets, assays, and dates, capturing their primary keys for fact insertion
        lab_keys, target_keys, assay_keys, date_keys = {}, {}, {}, {}
        for lab, info in lab_info.items():
            lab_keys[lab] = upsert_lab(conn, info["name"])
            target_name = str(info["target"] or "USP30").strip()

            # Conform known variants without attempting chemical/biological inference.
            if target_name.lower() in {"usp-30", "usp30", "ubiquitin specific protease 30"}:
                target_name = "USP30"
            target_keys[lab] = upsert_target(conn, target_name)
            assay_keys[lab] = upsert_assay(conn, lab_keys[lab], info["assay_id"], info["assay_type"],
                info["instrument"], info["operator"], info["nominal"], info["qc_rule"], info["notes"])
            date_keys[lab] = upsert_date(conn, info["date"])

        
        # Resolve all registered compounds against the database and cache their primary keys using a composite lookup map
        compound_keys = {}
        for (lab, local_id), entry in registry.items():
            key = resolve_compound(conn, entry["name"], entry["smiles"])
            if key is not None:
                compound_keys[(lab, local_id)] = key

        # Gamma IDs are mapped to preferred names; identity is matched to the shared registry.
        for local_id, name in gamma_names.items():
            smiles = name_smiles.get(name) if name and name not in ambiguous_names else None
            key = resolve_compound(conn, name, smiles)
            # If resolution succeeds, it caches the primary key in the global lookup map under Lab Gamma's local ID for later fact insertion. 
            if key is not None:
                compound_keys[("gamma", local_id)] = key

        # Dynamically detect Lab Beta's compound ID column and compute occurrence counts to track test replicates
        beta_id_col = "compound" if "compound" in b_res.columns else "compound_id"
        beta_counts = b_res[beta_id_col].value_counts(dropna=True).to_dict() if beta_id_col in b_res.columns else {}

        # Alpha facts
        for _, r in a_res.iterrows():
            # Convert the current DataFrame row to a dictionary and extract standard identifiers safely
            row = r.to_dict(); sid = as_text(val(row, "sample_id")); local = as_text(val(row, "compound_id"))
            rid = f"lab_alpha.assay_results:{sid or json.dumps(payload(row), sort_keys=True)}"
            ck = compound_keys.get(("alpha", local))
            reason = "Missing source compound ID" if not local else ("Compound not found in Alpha registry" if ck is None else None)

            # Validate compound resolution and route records with missing or unrecognized IDs to quarantine
            if reason:
                quarantine(conn, rid, "stg_lab_alpha_assay_results", reason, payload(row)); counts["quarantined"] += 1; continue
            inhibition = as_decimal(val(row, "inhibition_percent", "inhibition_pct"))
            conc = as_decimal(val(row, "concentration_nm"))
            upsert_fact(conn, {"source_record_id": rid, 
                "compound_key": ck, "lab_key": lab_keys["alpha"], "assay_key": assay_keys["alpha"],
                "target_key": target_keys["alpha"], "date_key": date_keys["alpha"],
                "concentration_nm": conc, "inhibition_pct": inhibition,
                "is_out_of_range": inhibition is not None and (inhibition < 0 or inhibition > 100),
                "qc_status": "NOT_ASSESSED", "source_compound_id": local, "source_sample_id": sid,
                "source_plate": None, "source_well": None, "is_replicate": False
                })
            counts["facts_upserted"] += 1

        # Beta facts
        for _, r in b_res.iterrows():
            row = r.to_dict(); sid = as_text(val(row, "specimen")); local = as_text(val(row, "compound", "compound_id"))

            # Generate a deterministic unique record ID using specimen ID or a fallback sorted JSON payload
            rid = f"lab_beta.screening:{sid or json.dumps(payload(row), sort_keys=True)}"
            # Retrieve the permanent database compound primary key from Lab Beta's cache
            ck = compound_keys.get(("beta", local))
            reason = "Missing source compound ID" if not local else ("Compound ID not found in Beta registry" if ck is None else None)

            # Route invalid records to quarantine, increment the error counter, and skip the current iteration
            if reason:
                quarantine(conn, rid, "stg_lab_beta_screening", reason, payload(row)); counts["quarantined"] += 1; continue
            conc = as_decimal(val(row, "concentration_nm"))
            if conc is None:
                conc = (as_decimal(val(row, "dose_um")) * Decimal("1000")) if as_decimal(val(row, "dose_um")) is not None else None
            raw_qc = str(val(row, "qc", default="")).strip().upper()
            qc = "PASS" if raw_qc == "PASS" else ("FAIL" if raw_qc == "FAIL" else "NOT_ASSESSED")
            inhibition = as_decimal(val(row, "response", "inhibition_percent", "inhibition_pct"))

            upsert_fact(conn, {"source_record_id": rid, 
                "compound_key": ck, "lab_key": lab_keys["beta"], "assay_key": assay_keys["beta"],
                "target_key": target_keys["beta"], "date_key": date_keys["beta"],
                "concentration_nm": conc, "inhibition_pct": inhibition,
                "is_out_of_range": inhibition is not None and (inhibition < 0 or inhibition > 100),
                "qc_status": qc, "source_compound_id": local, "source_sample_id": sid,
                "source_plate": None, "source_well": None,
                "is_replicate": beta_counts.get(local, 0) > 1})
            counts["facts_upserted"] += 1

        # Gamma facts. Instrument-calculated Inhibition_Pct is loaded as supplied.
        for _, r in g_res.iterrows():
            row = r.to_dict(); local = as_text(val(row, "compound_id")); plate = as_text(val(row, "plate")); well = as_text(val(row, "well"))
            rid = f"lab_gamma.plate_export:{plate or 'NO_PLATE'}:{well or 'NO_WELL'}:{local or 'NO_COMPOUND'}"
            ck = compound_keys.get(("gamma", local))
            reason = "Missing Gamma compound mapping" if not local or ("gamma", local) not in compound_keys else ("Unable to resolve compound identity" if ck is None else None)
            if reason:
                quarantine(conn, rid, "stg_lab_gamma_plate_export", reason, payload(row)); counts["quarantined"] += 1; continue
            conc = as_decimal(val(row, "concentration_nm"))
            if conc is None:
                amount = as_decimal(val(row, "concentration")); units = str(val(row, "units", default="")).strip().lower()
                factors = {"nm": Decimal("1"), "um": Decimal("1000"), "µm": Decimal("1000"), "μm": Decimal("1000"), "pm": Decimal("0.001")}
                conc = amount * factors[units] if amount is not None and units in factors else None
            inhibition = as_decimal(val(row, "inhibition_pct", "inhibition_percent"))

            upsert_fact(conn, {"source_record_id": rid, 
                "compound_key": ck, "lab_key": lab_keys["gamma"], "assay_key": assay_keys["gamma"],
                "target_key": target_keys["gamma"], "date_key": date_keys["gamma"],
                "concentration_nm": conc, "inhibition_pct": inhibition,
                "is_out_of_range": inhibition is not None and (inhibition < 0 or inhibition > 100),
                "qc_status": "NOT_ASSESSED", "source_compound_id": local,
                "source_sample_id": None, "source_plate": plate, "source_well": well,
                "is_replicate": False})
            counts["facts_upserted"] += 1

        # Ensure the quarantine table only contains current exceptions. Successful rows are removed
        # from quarantine if a later registry correction makes them loadable.
        conn.execute(text("""
          DELETE FROM gold.quarantined_records q
          WHERE (q.source_table='stg_lab_alpha_assay_results' AND EXISTS (
              SELECT 1 FROM gold.fact_screening_result f WHERE f.source_record_id=q.source_record_id))
             OR (q.source_table='stg_lab_beta_screening' AND EXISTS (
              SELECT 1 FROM gold.fact_screening_result f WHERE f.source_record_id=q.source_record_id))
             OR (q.source_table='stg_lab_gamma_plate_export' AND EXISTS (
              SELECT 1 FROM gold.fact_screening_result f WHERE f.source_record_id=q.source_record_id))
        """))

        validate_gold_data(conn)

    engine.dispose()
    print("Gold load complete:", counts)




if __name__ == "__main__":
    main()