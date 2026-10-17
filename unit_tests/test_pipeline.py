
import pandas as pd

from src.b_silver_layer import (
    clean_column_name,
    clean_dataframe,
    standardise_date_columns,
)


def test_clean_column_name():
    assert clean_column_name(" Inhibition (%) ") == "inhibition"


def test_beta_cleaning_and_concentration_conversion():
    df = pd.DataFrame({
        "Compound ID": [" BETA_001 ", "BETA_001", "BETA_002"],
        "dose_um": [0.1, 0.1, 0.25],
        "qc": [" PASS ", "PASS", "   "],
    })

    result = clean_dataframe(df, "lab_beta", "screening")

    # Exact duplicates are removed after trimming.
    assert len(result) == 2

    # Micromolar values are converted to nanomolar.
    assert result.loc[
        result["compound_id"] == "BETA_001",
        "concentration_nm"
    ].iloc[0] == 100

    assert result.loc[
        result["compound_id"] == "BETA_002",
        "concentration_nm"
    ].iloc[0] == 250

    # Blank strings become missing values.
    assert pd.isna(
        result.loc[result["compound_id"] == "BETA_002", "qc"].iloc[0]
    )


def test_gamma_concentration_conversion():
    df = pd.DataFrame({
        "compound_id": ["G1", "G2", "G3"],
        "concentration": [100, 0.2, 500],
        "units": ["nM", "uM", "pM"],
    })

    result = clean_dataframe(df, "lab_gamma", "plate_export")

    assert result["concentration_nm"].tolist() == [100, 200, 0.5]


def test_beta_date_standardisation():
    df = pd.DataFrame({
        "screening_date": ["16/10/2026"]
    })

    result = standardise_date_columns(
        df, "lab_beta", "experiment"
    )

    assert result.loc[0, "screening_date"] == "2026-10-16"
