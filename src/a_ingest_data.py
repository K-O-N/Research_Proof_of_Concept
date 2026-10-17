import os
import json 
import pandas as pd
import sqlalchemy
import psycopg2
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, URL

load_dotenv()





user = os.getenv("PG_USER")
password = os.getenv("PG_PASSWORD")
host = os.getenv("PG_HOST", "pgdatabase")
port = os.getenv("PG_PORT", 5432)
db = os.getenv("PG_DB", "oxresearch")

database_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
engine = create_engine(database_url)



#  Create schemas for each lab
labs = ["lab_alpha", "lab_beta", "lab_gamma"]
with engine.connect() as conn:
    for lab in labs:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {lab};"))
        conn.commit()
    print("Schemas created successfully.")



# Define the data file paths  
base_path = "./data"  


# Define the datasets and their corresponding file paths for each lab
datasets = {
    "lab_alpha": {
        "compounds": f"{base_path}/lab_alpha/compounds.csv",
        "assay_results": f"{base_path}/lab_alpha/assay_results.csv",
        "assay_metadata": f"{base_path}/lab_alpha/assay_metadata.csv",
    },
    "lab_beta": {
        "compounds": f"{base_path}/lab_beta/compounds.csv",
        "screening": f"{base_path}/lab_beta/screening.tsv",  # TSV format
        "experiment": f"{base_path}/lab_beta/experiment.json",  # JSON format
    },
    "lab_gamma": {
        "plate_export": f"{base_path}/lab_gamma/plate_export.csv",
        "compound_mapping": f"{base_path}/lab_gamma/compound_mapping.csv",
        "metadata": f"{base_path}/lab_gamma/metadata.csv",
    },
}


# Ingest raw data into PostgreSQL tables
for lab, files in datasets.items():
    print(f"\n--- Ingesting {lab} ---")
    for table_name, file_path in files.items():
        try:
            # Handle different file formats 
            if file_path.endswith(".csv"):
                df = pd.read_csv(file_path)
            elif file_path.endswith(".tsv"):
                df = pd.read_csv(file_path, sep="\t")
            elif file_path.endswith(".json"):
                # Try reading the JSON file normally using pandas
                try:
                    df = pd.read_json(file_path)
                except ValueError:

                    # Fallback: if standard pandas read fails (common with flat key-value metadata dictionaries), 
                    # read the file manually using Python's standard json library
                    with open(file_path, "r") as f:
                        data = json.load(f)

                    # If it's a single dictionary, wrap it in a list so Pandas can successfully form a clean 1-row DataFrame
                    if isinstance(data, dict):
                        df = pd.DataFrame([data])
                    else:
                        # Otherwise, assume it's already a list of records and load it directly
                        df = pd.DataFrame(data)

            # Load into database Raw layer; Overwrite table on re-runs during development
            df.to_sql(
                name=table_name,
                con=engine,
                schema=lab,
                if_exists="replace",  
                index=False
            )
            print(f"Loaded {file_path} -> {lab}.{table_name} ({len(df)} rows)")

        except Exception as e:
            print(f"Error loading {file_path}: {e}")

print("\nRaw data ingestion complete!")

