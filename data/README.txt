CMD Compound Screening Exercise
================================

Three collaborating laboratories have conducted a single-point compound
screening campaign against a shared protein target (USP30 / Ubiquitin
Specific Protease 30) and have submitted their results in their preferred
formats.

Your task is to build a data pipeline that:
  1. Ingests the supplied datasets.
  2. Identifies and handles data quality issues.
  3. Harmonises and transforms the data as appropriate.
  4. Produces one or more processed datasets suitable for loading into
     a central research database.

File inventory
--------------
lab_alpha/
    compounds.csv        compound registry (Alpha internal IDs: ALF-nnn)
    assay_results.csv    single-point inhibition measurements
    assay_metadata.csv   assay and instrument metadata

lab_beta/
    compounds.csv        compound registry (Beta internal IDs)
    screening.tsv        screening results (tab-separated)
    experiment.json      experiment metadata

lab_gamma/
    plate_export.csv     plate reader export (inhibition % per well)
    compound_mapping.csv mapping from Gamma local IDs to preferred compound names
    metadata.csv         experiment metadata

Domain glossary
---------------
- USP30         Protein target screened against in this campaign.
- Compound      A small molecule being tested. Each compound has a SMILES
                string — a text encoding of its chemical structure that can
                be used to check whether two compounds with different IDs
                are actually the same molecule.
- Inhibition %  How much a compound suppresses the target at a given
                concentration. 0% = no effect, 100% = full suppression.
- Single-point  Each compound is tested at one concentration (nominally
  screen        100 nM). Results are inhibition % at that concentration,
                not a full dose-response curve.

Notes
-----
- All three labs screened compounds against the same target. There is
  overlap in the compound sets; some compounds appear in more than one lab
  under different identifiers.
- Concentration units, date formats, and QC conventions differ across labs.
- Inhibition_Pct in plate_export.csv is already calculated by the instrument software.
