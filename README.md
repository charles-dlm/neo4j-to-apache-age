# Migration Guide: Moving a Property Graph from Neo4j to Apache AGE

## OBJECTIVE

This guide details the complete procedure to migrate a property graph from a Neo4j Desktop environment.

# 1. DATA EXTRACTION AND PREPARATION FROM NEO4J

## Enabling the APOC Extension

- Open Neo4j Desktop and navigate to your project settings (DBMS).
- Locate the plugins section and ensure that the APOC extension is installed and activated for the target database.

## Authorizing File Exports

To allow Neo4j to write files directly to your local disk, you must modify or create the `apoc.conf` configuration file.

- Open the `apoc.conf` file (if it does not exist, create it at the root of your DBMS configuration folder).
- Add the following lines to authorize file import and export operations:

```ini
apoc.export.file.enabled=true
apoc.import.file.enabled=true
```

- Stop your running database instance.
- Close and fully restart the Neo4j Desktop application (or your Browser interface) to permanently apply the modifications.

## Exporting the Graph to JSON Format

Open your query interface (Neo4j Browser) and execute the following Cypher instruction to generate a JSON export:

```cypher
CALL apoc.export.json.all(
  "graph.json",
  {useTypes:true, jsonFormat:"ARRAY_JSON"}
)
```

Retrieve the newly generated `graph.json` file located inside the `import/` subdirectory of your Neo4j Desktop DBMS folder.

# 2. TARGET INFRASTRUCTURE SETUP AND ALIGNMENT

## Prerequisites: Apache AGE Deployment

Before proceeding with the import steps, your target environment must be fully functional.

Please ensure you have completed all setup requirements and successfully launched the container infrastructure.

## Project Initialization in VS Code

Locate the compressed archive named `source_files.zip` and extract its entire content.

Open your existing Docker environment working directory (`apache_age`) in VS Code, and copy all the extracted files from the ZIP archive into this folder.

# 3. PYTHON IMPORT ENVIRONMENT SETUP

## Creating and Activating the Virtual Environment (venv)

Create a virtual environment inside your working directory and place the `requirements.txt` file inside it.

To select the correct Python interpreter within VS Code, open the Command Palette:

### macOS

```text
Cmd + Shift + P
```

### Windows / Linux

```text
Ctrl + Shift + P
```

Type and select:

```text
Python: Create Environment
```

Choose to skip the automatic packages installation step (**Skip packages installation**).

## Installing Dependencies

Open the integrated terminal in VS Code (ensuring your virtual environment is active) and execute:

```bash
pip install -r requirements.txt
```

> Note: The `json` and `logging` modules are already part of the Python standard library by default; therefore, they do not need to be specified inside the `requirements.txt` file.

# 4. MIGRATION EXECUTION AND VERIFICATION

## Launching the Transition Script

Move both the exported `graph.json` file and the `import_graph.py` script into your virtual environment workspace.

Position your terminal inside the active virtual environment directory, then run:

```bash
python import_graph.py
```

Wait for the process to complete.

Once the execution is finished, you can connect to your PostgreSQL database command-line interface to directly verify, manage, and query your migrated property graphs using Apache AGE.
