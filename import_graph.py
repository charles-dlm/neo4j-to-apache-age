import json
import psycopg  # Strict usage of psycopg v3
import logging

# Log file configuration (Fixed formatting)
logging.basicConfig(
    filename='apache_age_import_commands.txt',
    filemode='w',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)

# 1. Connection to the Apache AGE database
conn = psycopg.connect(
    host="localhost",
    port="5432",
    dbname="graph_db",
    user="postgres",
    password="password"
)
conn.autocommit = True
cursor = conn.cursor()

# Initialization of Apache AGE
cursor.execute("LOAD 'age';")
cursor.execute("SET search_path = ag_catalog, '$user', public;")

graph_name = 'graph1'

# List of node types and relationship types retrieved from Neo4j
labels_list = ["Entity", "Address", "Intermediary", "Officer", "Other"]
relations_list = [
    "similar", "same_name_as", "intermediary_of", "same_intermediary_as", 
    "registered_address", "same_as", "same_id_as", "underlying", 
    "similar_company_as", "same_address_as", "connected_to", "officer_of", 
    "probably_same_officer_as", "same_company_as"
]

print("--- PHASE 0-A: CREATING TABLES BY NODE TYPE ---")
for label in labels_list:
    try:
        # create_vlabel explicitly creates the physical node table in PostgreSQL
        cursor.execute(f"SELECT create_vlabel('{graph_name}', '{label}');")
        logging.info(f"Physical table for node label '{label}' created or already exists.")
    except Exception as e:
        logging.info(f"Note for node label '{label}': {e}")

print("\n--- PHASE 0-B: CREATING PARTITION TABLES BY RELATIONSHIP TYPE ---")
for rel_type in relations_list:
    try:
        # create_elabel isolates each relationship type into its own physical PostgreSQL table
        # This enables native Postgres Partition Pruning during queries
        cursor.execute(f"SELECT create_elabel('{graph_name}', '{rel_type}');")
        logging.info(f"Physical table (partitioning) for relationship '{rel_type}' created or already exists.")
    except Exception as e:
        logging.info(f"Note for relationship '{rel_type}': {e}")

print("\nLoading JSON file into memory...")
with open('icij.json', 'r', encoding='utf-8') as f:
    all_data = json.load(f)

print(f"File loaded. {len(all_data)} elements to process.")


def format_property_value(value):
    """Cleans and types values specifically for Apache AGE."""
    if value is None:
        return '""'
    if isinstance(value, str):
        val_clean = value.strip().replace('\\', '')
        if val_clean.lower() == "null" or val_clean == "":
            return '""'
        try:
            return f"toInteger({int(val_clean)})"
        except ValueError:
            pass
        try:
            return f"toFloat({float(val_clean)})"
        except ValueError:
            pass
        if val_clean.lower() in ["true", "false"]:
            return val_clean.lower()
        safe_str = val_clean.replace('"', '\\"')
        return f'"{safe_str}"'
    elif isinstance(value, bool):
        return str(value).lower()
    elif isinstance(value, (int, float)):
        return str(value)
    return f'"{str(value)}"'


# Temporary dictionary for the second phase (to map which node belongs to which table)
node_type_lookup = {}

print("\n--- PHASE 1: INSERTING NODES INTO THEIR RESPECTIVE TABLES ---")
node_count = 0

# Using a transaction to speed up batch bulk writes
with conn.transaction():
    for data in all_data:
        if data['type'] == 'node':
            node_id = data['id']
            # Retrieve the type (label), defaults to 'Other' if missing
            label = data['labels'][0] if data['labels'] else 'Other'
            properties = data['properties']
            
            # Save the type for the relationship phase
            node_type_lookup[node_id] = label
            
            # Inject the original Neo4j ID into properties
            properties['neo4j_id'] = node_id

            props_list = []
            for key, value in properties.items():
                props_list.append(f"`{key}`: {format_property_value(value)}")
            props_clean = "{" + ", ".join(props_list) + "}"

            # The insertion directly targets the Label table
            cypher_query = f"CREATE (v:{label} {props_clean})"
            full_query = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_query} $$) AS (v agtype);"
            
            cursor.execute(full_query)
            node_count += 1
            
            if node_count % 50000 == 0:
                print(f"   -> {node_count} nodes inserted...")

print(f"Node insertion completed: {node_count} nodes distributed across tables.")


print("\n--- CREATING LOOKUP INDEXES ON EACH TABLE ---")
# Without these indexes, PostgreSQL freezes during relationship MATCH operations
for lbl in labels_list:
    index_query = f"""
    CREATE INDEX IF NOT EXISTS idx_{lbl.lower()}_neo4j_id 
    ON "{graph_name}"."{lbl}" (ag_catalog.agtype_access_operator(properties, '"neo4j_id"'));
    """
    cursor.execute(index_query)
    print(f" -> Lookup index enabled on table '{lbl}'")


print("\n--- PHASE 2: CREATING RELATIONSHIPS WITH TARGETED LOOKUPS ---")
rel_count = 0
success_rel = 0

with conn.transaction():
    for data in all_data:
        if data['type'] == 'relationship':
            rel_count += 1
            start_id = data['start']['id']
            end_id = data['end']['id']
            rel_type = data['label']
            properties = data.get('properties', {})

            # Retrieve the target table label for both start and end nodes
            start_label = node_type_lookup.get(start_id)
            end_label = node_type_lookup.get(end_id)

            # If the label is missing from our lookup history, we cannot target the correct table
            if not start_label or not end_label:
                logging.warning(f"Relationship skipped: Start node {start_id} or End node {end_id} not found.")
                continue

            props_list = []
            for key, value in properties.items():
                props_list.append(f"`{key}`: {format_property_value(value)}")
            props_clean = "{" + ", ".join(props_list) + "}"

            # TARGETED QUERY: Forces MATCH to look directly inside :start_label and :end_label
            # Explicitly specifies [r:{rel_type}] to enforce Partition Pruning in Postgres
            cypher_rel = f"""
                MATCH (a:{start_label}), (b:{end_label})
                WHERE a.neo4j_id = {start_id} AND b.neo4j_id = {end_id}
                CREATE (a)-[r:{rel_type} {props_clean}]->(b)
            """
            
            full_query = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_rel} $$) AS (r agtype);"
            
            try:
                cursor.execute(full_query)
                success_rel += 1
            except Exception as e:
                logging.error(f"Failed to create relationship between {start_id} and {end_id}: {e}")
            
            if rel_count % 25000 == 0:
                print(f"   -> {rel_count} relationships analyzed... ({success_rel} created in database)")

print(f"\nFinal import completed!")
print(f"Total nodes: {node_count}")
print(f"Total relationships successfully created: {success_rel} (out of {rel_count} analyzed).")

cursor.close()
conn.close()
