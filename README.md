# Migration Guide: Moving a Property Graph from Neo4j to Apache AGE

## Objective

This guide details the complete procedure to migrate a property graph from a Neo4j Desktop environment to a PostgreSQL database equipped with Apache AGE.

## 1. Data Extraction and Preparation from Neo4j

### Enabling the APOC Extension

- Open Neo4j Desktop and navigate to your project settings (DBMS).
- Locate the plugins section and ensure that the APOC extension is installed and activated.

### Authorizing File Exports

To allow Neo4j to write files directly to your local disk:

- Open the `apoc.conf` file.
- Add the following configuration:

```ini
apoc.export.file.enabled=true
apoc.import.file.enabled=true
```

- Stop your database instance.
- Restart Neo4j Desktop.

### Exporting the Graph to JSON Format

Execute the following Cypher query:

```cypher
CALL apoc.export.json.all(
  "graph.json",
  {useTypes:true, jsonFormat:"ARRAY_JSON"}
)
```

Retrieve the generated `graph.json` file from the `import/` directory.

## 2. Target Infrastructure Setup

### Apache AGE Prerequisites

Ensure that:

- Apache AGE is installed.
- PostgreSQL is running.
- The Docker environment is operational.

### Project Initialization

- Extract `source_files.zip`.
- Open the `apache_age` directory in VS Code.
- Copy the extracted files into this directory.

## 3. Python Environment Setup

### Creating the Virtual Environment

Create a virtual environment and place the `requirements.txt` file inside it.

Open the Command Palette:

**macOS**

```text
Cmd + Shift + P
```

**Windows / Linux**

```text
Ctrl + Shift + P
```

Select:

```text
Python: Create Environment
```

Then choose **Skip packages installation**.

### Installing Dependencies

Run:

```bash
pip install -r requirements.txt
```

> The `json` and `logging` modules are included in Python's standard library and do not need to be added to `requirements.txt`.

## 4. Migration Execution

### Running the Import Script

Place the following files in your workspace:

- `graph.json`
- `import_graph.py`

Execute:

```bash
python import_graph.py
```

### Verification

Once the import is complete, connect to PostgreSQL and verify that your graph has been successfully migrated and is accessible through Apache AGE.
