import json
import psycopg  # Strict use of psycopg v3
import logging

# Log file configuration
logging.basicConfig(
    filename='apache_age_import_commands.txt',
    filemode='w',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)

# 1. Connection to Apache AGE database (Docker) via psycopg3
conn = psycopg.connect(
    host="localhost",
    port="5432",
    dbname="graph_db",
    user="postgres",
    password="password"
)

# Explicit autocommit configuration (required for psycopg3 in your architecture)
conn.autocommit = True

cursor = conn.cursor()
logging.info("Connection established with PostgreSQL (psycopg3).")

# 2. Apache AGE session initialization (executes immediately due to autocommit)
cursor.execute("LOAD 'age';")
cursor.execute("SET search_path = ag_catalog, '$user', public;")

graph_name = 'social_media'  # Target graph name

print("Loading JSON file into memory...")

# Open file and load the complete JSON array into memory
with open('graph.json', 'r', encoding='utf-8') as f:
    all_data = json.load(f)

print(f"File loaded. {len(all_data)} elements found to process.")
logging.info(f"JSON file loaded containing {len(all_data)} elements.")

relationships = []
node_count = 0

# --- FIRST PASS: NODE IMPORT (BATCHES OF 25 IN A SINGLE CREATE) ---
print("Importing nodes...")
batch_creates = []  # Buffer to store internal "CREATE (...)" lines

# Open an explicit psycopg3 transactional block (temporarily disables autocommit)
with conn.transaction():
    for data in all_data:
        if data['type'] == 'node':
            node_id = data['id']
            label = data['labels'][0] if data['labels'] else 'Unlabeled'
            properties = data['properties']

            # Inject the original Neo4j ID into the AGE node properties
            properties['neo4j_id'] = node_id

            # Property formatting (using backticks for keys)
            props_list = []
            for key, value in properties.items():
                safe_key = f"`{key}`"  # Handles spaces in property keys

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

            # Store only the internal creation instruction with a unique alias (v_id)
            single_create = f"CREATE (v_{node_id}:{label} {props_clean})"
            batch_creates.append(single_create)
            node_count += 1

            # Once the buffer contains 25 nodes, forge and execute the single global query
            if len(batch_creates) == 25:
                try:
                    # Multi-line string replaced by clear string concatenation with \n
                    cypher_query = "\n".join(batch_creates)
                    full_query = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_query} $$) AS (v agtype);"
                    
                    cursor.execute(full_query)
                    batch_creates = []  # Clear the buffer
                    
                    logging.info(f"[BATCH] 25 nodes injected in 1 Cypher call (Total parsed: {node_count})")
                    if node_count % 500 == 0:
                        print(f"   -> {node_count} nodes imported...")
                except Exception as e:
                    logging.error(f"Error during batch node execution around total count {node_count}: {e}")
                    print(f"Error during batch node execution: {e}")
                    # Propagate exception to force the automatic ROLLBACK of the transactional block
                    raise e

        elif data['type'] == 'relationship':
            relationships.append(data)

    # Handle the remainder (if the total number of nodes is not an exact multiple of 25)
    if batch_creates:
        try:
            cypher_query = "\n".join(batch_creates)
            full_query = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_query} $$) AS (v agtype);"
            cursor.execute(full_query)
            logging.info(f"[BATCH-FINAL] Last {len(batch_creates)} nodes injected in 1 Cypher call.")
        except Exception as e:
            logging.error(f"Error during final batch node execution: {e}")
            print(f"Error during final batch node execution: {e}")
            raise e

print(f"Node import completed ({node_count} nodes).")
logging.info(f"Node import completed. Total: {node_count}")

# --- CRITICAL INDEX CREATION ---
print("Creating index to speed up relationship linking...")
# SQL multi-line replaced to avoid GitHub code highlighting issues
index_query = f"CREATE INDEX IF NOT EXISTS idx_neo4j_id ON \"{graph_name}\".\"_ag_label_vertex\" (ag_catalog.agtype_access_operator(properties, '\"neo4j_id\"'));"
cursor.execute(index_query)

# --- SECOND PASS: RELATIONSHIP IMPORT (BATCHES OF 25 SIMULTANEOUS MATCH/CREATE) ---
print(f"Linking {len(relationships)} relationships...")
rel_count = 0
batch_matches = []
batch_creates_rel = []

# Open the second transactional block for secure edge creation
with conn.transaction():
    for rel in relationships:
        start_id = rel['start']['id']
        end_id = rel['end']['id']
        rel_type = rel['label']
        properties = rel.get('properties', {})

        # Property formatting for the relationship
        props_list = []
        for key, value in properties.items():
            safe_key = f"`{key}`"

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

        # Define unique aliases per relationship to prevent clashing within the same query
        alias_a = f"a_{rel_count}"
        alias_b = f"b_{rel_count}"
        alias_r = f"r_{rel_count}"

        # Fill the two separate buffers (MATCHs on one side, CREATEs on the other)
        batch_matches.append(f"MATCH ({alias_a}), ({alias_b}) WHERE {alias_a}.neo4j_id = '{start_id}' AND {alias_b}.neo4j_id = '{end_id}'")
        batch_creates_rel.append(f"CREATE ({alias_a})-[{alias_r}:{rel_type} {props_clean}]->({alias_b})")
        rel_count += 1

        # Once a batch of 25 relationships is reached, merge the buffers
        if len(batch_matches) == 25:
            try:
                # Concatenate all MATCHs first, then all CREATEs as required by Cypher
                cypher_internal = "\n".join(batch_matches) + "\n" + "\n".join(batch_creates_rel)
                full_query = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_internal} $$) AS (r agtype);"
                
                cursor.execute(full_query)
                
                # Reset batch buffers
                batch_matches = []
                batch_creates_rel = []
                
                logging.info(f"[BATCH] 25 relationships linked in 1 Cypher call (Total parsed: {rel_count})")
                if rel_count % 500 == 0:
                    print(f"   -> {rel_count} relationships linked...")
            except Exception as e:
                logging.error(f"Error during batch relationship execution around total count {rel_count}: {e}")
                print(f"Error during batch relationship execution: {e}")
                raise e

    # Handle the remainder for the last remaining relationships
    if batch_matches:
        try:
            cypher_internal = "\n".join(batch_matches) + "\n" + "\n".join(batch_creates_rel)
            full_query = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_internal} $$) AS (r agtype);"
            
            cursor.execute(full_query)
            logging.info(f"[BATCH-FINAL] Last {len(batch_matches)} relationships linked in 1 Cypher call.")
        except Exception as e:
            logging.error(f"Error during final batch relationship execution: {e}")
            print(f"Error during final batch relationship execution: {e}")
            raise e

print(
    f"Import completed successfully! Total: {node_count} nodes and {rel_count} relationships."
)
logging.info(
    f"Import completed successfully! Total: {node_count} nodes and {rel_count} relationships."
)

# Clean closure of cursors and connections
cursor.close()
conn.close()
