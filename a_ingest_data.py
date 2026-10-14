
import json 
import pandas as pd
import sqlalchemy
import psycopg2
from sqlalchemy import create_engine, text



# engine = create_engine('postgresql://researchlab:researchlab@localhost:5432/oxresearch')

# Switch to using the service name defined in docker-compose.yaml for the database host 
engine = create_engine( 'postgresql+psycopg2://researchlab:researchlab@pgdatabase:5432/oxresearch')



#  Create schemas for each lab
labs = ["lab_alpha", "lab_beta", "lab_gamma"]
with engine.connect() as conn:
    for lab in labs:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {lab};"))
        conn.commit()
    print("Schemas created successfully.")



# Define file paths and load configurations
# Adjust the base path to point to where your lab folders are stored locally
base_path = "./data"  # Change this to your actual data directory 

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
                # Read JSON safely whether it's a dict/metadata or a list of records
                try:
                    df = pd.read_json(file_path)
                except ValueError:
                    # Fallback for scalar/flat dictionary metadata files
                    with open(file_path, "r") as f:
                        data = json.load(f)
                    # If it's a single dictionary, wrap it in a list so it forms a 1-row DataFrame
                    if isinstance(data, dict):
                        df = pd.DataFrame([data])
                    else:
                        df = pd.DataFrame(data)

            # Load into database Raw layer
            df.to_sql(
                name=table_name,
                con=engine,
                schema=lab,
                if_exists="replace",  # Overwrite table on re-runs during development
                index=False
            )
            print(f"Loaded {file_path} -> {lab}.{table_name} ({len(df)} rows)")

        except Exception as e:
            print(f"Error loading {file_path}: {e}")

print("\nRaw data ingestion complete!")






