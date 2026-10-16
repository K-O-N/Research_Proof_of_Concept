import json 
import pandas as pd
import sqlalchemy
import psycopg2
import os
import re

from sqlalchemy import URL, create_engine, inspect, text


SOURCE_SCHEMAS = ["lab_alpha", "lab_beta", "lab_gamma"]
TARGET_SCHEMA = "staging"


# Create a SQLAlchemy engine for PostgreSQL using psycopg2
def get_engine():
    return create_engine( 'postgresql+psycopg2://researchlab:researchlab@pgdatabase:5432/oxresearch')


# Clean column names to lowercase snake_case and remove special characters
def clean_column_name(name):
    """Convert column names to lowercase snake_case."""
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


# Clean and standardise the dataframe for each lab's dataset
def clean_dataframe(df, schema_name, table_name):
    original_count = len(df)

    # Standardise column names.
    df.columns = [clean_column_name(c) for c in df.columns]

    # Add to a list any duplicated columns names after cleaning and raise an error 
    if df.columns.duplicated().any():
        duplicates = df.columns[df.columns.duplicated()].tolist()
        raise ValueError(
            f"{schema_name}.{table_name}: duplicate columns "
            f"after normalisation: {duplicates}"
        )

    # Trim text fields and convert blank strings to nulls.
    for column in df.select_dtypes(
        include=["object", "string"]
    ).columns:
        df[column] = df[column].map(
            lambda value: value.strip()
            if isinstance(value, str)
            else value
        )
        df[column] = df[column].replace("", pd.NA)


    # Remove only exact duplicate rows.
    duplicate_count = int(df.duplicated().sum())
    df = df.drop_duplicates().copy()


    # Preserve raw QC values in their cleaned form.
    # Do not assume "1", "True", and "PASS" mean the same thing
    # until the laboratory's QC rules have been confirmed.

    # Beta dose is measured in micromolar convert to nanomolar for consistency
    if schema_name == "lab_beta" and table_name == "screening":
        if "dose_um" in df.columns:
            df["concentration_nm"] = (
                pd.to_numeric(df["dose_um"], errors="coerce") * 1000
            )

    # Gamma concentrations have a separate Units column.
    if schema_name == "lab_gamma" and table_name == "plate_export":
        if {"concentration", "units"}.issubset(df.columns):
            amount = pd.to_numeric(
                df["concentration"], errors="coerce"
            )
            units = df["units"].astype("string").str.strip().str.lower()

            multipliers = {  "nm": 1, "um": 1000, "µm": 1000,  "μm": 1000,  "pm": 0.001,  }

            multiplier = units.map(multipliers)
            df["concentration_nm"] = amount * multiplier

            unknown_units = sorted( units[units.notna() & multiplier.isna()].unique().tolist() )
            if unknown_units:
                print(
                    f"WARNING: {schema_name}.{table_name}: "
                    f"unrecognised units: {unknown_units}"
                )

    print(
        f"{schema_name}.{table_name}: "
        f"input_rows={original_count}, "
        f"duplicates_removed={duplicate_count}, "
        f"output_rows={len(df)}" )

    return df



# Standardise date columns to YYYY-MM-DD format, preserving missing values
def standardise_date_columns(df, schema_name, table_name):
  """Standardise lab dates to YYYY-MM-DD, preserving missing values."""

  # Gamma stores screening_date as a row in its metadata table.
  if schema_name == "lab_gamma" and table_name == "metadata":
    mask = ( df["field"].astype("string").str.strip().str.lower() == "screening_date" )

    if mask.any() and "value" in df.columns:
      values = df.loc[mask, "value"].astype("string").str.strip()

      # Safely parse dates, allowing mixed formats and prioritizing day-first styling
      parsed = pd.to_datetime(
          values,
          format="mixed",
          dayfirst=True,
          errors="coerce",)

      # Check if any original values (invalid) failed to parse and print a warning if so
      invalid = values.notna() & parsed.isna()
      if invalid.any():
        print(
            f"WARNING: {schema_name}.{table_name}: "
            f"{invalid.sum()} invalid screening_date value(s)"
        )

      df.loc[mask, "value"] = parsed.dt.strftime("%Y-%m-%d").astype("string")

  else:
    # Alpha and Beta store dates in standard columns.
    date_columns = {
        ("lab_alpha", "assay_metadata"): ["run_date"],
        ("lab_beta", "experiment"): ["screening_date"],
    }

    for column_date in date_columns.get((schema_name, table_name), []):
      if column_date not in df.columns:
        continue

      values = df[column_date].astype("string").str.strip()
      parsed = pd.to_datetime( values, format="mixed",  dayfirst=True, errors="coerce", )

      # Check if any original values (invalid) failed to parse and print a warning if so
      invalid = values.notna() & parsed.isna()
      if invalid.any():
        print(
            f"WARNING: {schema_name}.{table_name}.{column_date}: "
            f"{invalid.sum()} invalid date value(s)"
        )

      # Overwrite the column with clean YYYY-MM-DD strings
      df[column_date] = parsed.dt.strftime("%Y-%m-%d").astype("string")

  return df



def main():
    # Create the connection engine to the database
    engine = get_engine()

    # Create the target schema if it doesn't exist
    with engine.begin() as connection:
        connection.execute( text(f'CREATE SCHEMA IF NOT EXISTS "{TARGET_SCHEMA}"')  )

    # Initialize the database inspector to look up schemas and tables
    inspector = inspect(engine)
    total_tables = 0

    # Loop through each source lab schema annd confirm it exists before processing its tables
    for schema_name in SOURCE_SCHEMAS:
        if not inspector.has_schema(schema_name):
            print(f"WARNING: Schema {schema_name} does not exist.")
            continue

        table_names = inspector.get_table_names(schema=schema_name)

        for table_name in table_names:
            print(f"\nReading {schema_name}.{table_name}")

            # Identifiers come from PostgreSQL's schema inspection.
            query = text( f'SELECT * FROM "{schema_name}"."{table_name}"' )
            df = pd.read_sql_query(query, engine)


            date_df = standardise_date_columns( df, schema_name, table_name )
            cleaned_df = clean_dataframe(  date_df, schema_name, table_name )

            # Define the standardized target table name for the staging layer
            target_table = clean_column_name( f"stg_{schema_name}_{table_name}" )

            # Write the cleaned dataframe into the target staging schema in chunks
            cleaned_df.to_sql( name=target_table, con=engine, schema=TARGET_SCHEMA, if_exists="replace", index=False, chunksize=1000, )
    
            print( f"Written to {TARGET_SCHEMA}.{target_table}")
            total_tables += 1

    # Clean up and close the database connection engine
    engine.dispose()
    print(f"\nCompleted: {total_tables} source tables processed.")


if __name__ == "__main__":
    main()




