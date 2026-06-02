import json
import psycopg2
import logging

# [MINIMAL ADDITION] Logging configuration file
logging.basicConfig(
    filename='apache_age_import_commands.txt',
    filemode='w',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)

# 1. Connect to the Apache AGE database (Docker)
conn = psycopg2.connect(
    host="localhost",
    port="5432",
    database="graph_db",
    user="postgres",
    password="password"
)
cursor = conn.cursor()
logging.info("Connection established with PostgreSQL.")

# 2. Initialize Apache AGE session
cursor.execute("LOAD 'age';")
cursor.execute("SET search_path = ag_catalog, '$user', public;")
conn.commit()

graph_name = 'social_media'  # Graph name

print("Loading JSON file into memory...")

# Open the file and load the entire JSON array at once
with open('graph.json', 'r', encoding='utf-8') as f:
    all_data = json.load(f)

print(f"File loaded. {len(all_data)} elements found to process.")
logging.info(f"JSON file loaded containing {len(all_data)} elements.")

relationships = []
node_count = 0

# --- FIRST PASS: NODE IMPORT ---
print("Importing nodes...")
for data in all_data:
    if data['type'] == 'node':
        node_id = data['id']
        label = data['labels'][0] if data['labels'] else 'Unlabeled'
        properties = data['properties']

        # Inject the original Neo4j ID into the node properties
        properties['neo4j_id'] = node_id

        # Format properties using backticks for keys
        props_list = []
        for key, value in properties.items():
            safe_key = f"`{key}`"  # Handles spaces in node property keys

            if isinstance(value, str):
                safe_value = value.replace('"', '\\"')
                props_list.append(f'{safe_key}: "{safe_value}"')
            elif isinstance(value, bool):
                props_list.append(f'{safe_key}: {str(value).lower()}')
            elif value is None:
                props_list.append(f'{safe_key}: ""')
            else:
                props_list.append(f'{safe_key}: {value}')

        props_clean = "{" + ", ".join(props_list) + "}"

        query = f"""
            SELECT * FROM cypher('{graph_name}', $$
                CREATE (v:{label} {props_clean})
            $$) AS (v agtype);
        """

        try:
            cursor.execute(query)
            node_count += 1

            # [MINIMAL ADDITION] Commit every 100 nodes to secure inserted data
            if node_count % 100 == 0:
                conn.commit()
                logging.info(
                    f"[BATCH] 100 nodes validated and committed (Current total: {node_count})"
                )

            if node_count % 500 == 0:
                print(f"   -> {node_count} nodes imported...")

        except Exception as e:
            # [MINIMAL ADDITION] Log the exact insertion error
            logging.error(f"Error while inserting node {node_id}: {e}")
            print(f"Error while inserting node {node_id}: {e}")
            conn.rollback()

    elif data['type'] == 'relationship':
        relationships.append(data)

conn.commit()
print(f"Node import completed ({node_count} nodes).")
logging.info(f"Node import completed. Total: {node_count}")

# --- CRITICAL INDEX CREATION ---
print("Creating index to speed up relationship linking...")
cursor.execute(f"""
    CREATE INDEX IF NOT EXISTS idx_neo4j_id
    ON "{graph_name}"."_ag_label_vertex"
    (ag_catalog.agtype_access_operator(properties, '"neo4j_id"'));
""")
conn.commit()

# --- SECOND PASS: RELATIONSHIP IMPORT ---
print(f"Linking {len(relationships)} relationships...")
rel_count = 0

for rel in relationships:
    start_id = rel['start']['id']
    end_id = rel['end']['id']
    rel_type = rel['label']
    properties = rel.get('properties', {})

    # Format properties using backticks for keys (e.g. `player misc_crdy`)
    props_list = []
    for key, value in properties.items():
        safe_key = f"`{key}`"  # Fix for keys containing spaces

        if isinstance(value, str):
            safe_value = value.replace('"', '\\"')
            props_list.append(f'{safe_key}: "{safe_value}"')
        elif isinstance(value, bool):
            props_list.append(f'{safe_key}: {str(value).lower()}')
        elif value is None:
            props_list.append(f'{safe_key}: ""')
        else:
            props_list.append(f'{safe_key}: {value}')

    props_clean = "{" + ", ".join(props_list) + "}"

    query = f"""
        SELECT * FROM cypher('{graph_name}', $$
            MATCH (a), (b)
            WHERE a.neo4j_id = '{start_id}' AND b.neo4j_id = '{end_id}'
            CREATE (a)-[r:{rel_type} {props_clean}]->(b)
        $$) AS (r agtype);
    """

    try:
        cursor.execute(query)
        rel_count += 1

        # [MINIMAL ADDITION] Commit every 5 relationships to release PostgreSQL memory
        if rel_count % 5 == 0:
            conn.commit()
            logging.info(
                f"[BATCH] 5 relationships validated and committed (Current total: {rel_count})"
            )

        if rel_count % 100 == 0:
            print(f"   -> {rel_count} relationships linked...")

    except Exception as e:
        # [MINIMAL ADDITION] Log relationship creation errors
        logging.error(
            f"Relationship error between {start_id} and {end_id} (Type: {rel_type}): {e}"
        )
        print(f"Relationship error between {start_id} and {end_id}: {e}")
        conn.rollback()

conn.commit()
print(
    f"Import completed successfully! Total: {node_count} nodes and {rel_count} relationships."
)
logging.info(
    f"Import completed successfully! Total: {node_count} nodes and {rel_count} relationships."
)

# Close database connections
cursor.close()
conn.close()
