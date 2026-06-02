import json
import psycopg2
import logging

# [AJOUT MINIMAL] Configuration du fichier texte de journalisation
logging.basicConfig(
    filename='apache_age_import_commands.txt',
    filemode='w',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)

# 1. Connexion à la base de données Apache AGE (Docker)
conn = psycopg2.connect(
    host="localhost",
    port="5432",
    database="graph_db",
    user="postgres",
    password="password"
)
cursor = conn.cursor()
logging.info("Connexion établie avec PostgreSQL.")

# 2. Initialisation de la session Apache AGE
cursor.execute("LOAD 'age';")
cursor.execute("SET search_path = ag_catalog, '$user', public;")
conn.commit()

graph_name = 'reseau_social' # Le nom de ton graphe

print("🚀 Chargement du fichier JSON en mémoire...")

# On ouvre le fichier et on charge TOUT le tableau JSON d'un coup
with open('graph.json', 'r', encoding='utf-8') as f:
    all_data = json.load(f)

print(f"📋 Fichier chargé. {len(all_data)} éléments trouvés à traiter.")
logging.info(f"Fichier JSON chargé contenant {len(all_data)} éléments.")

relationships = []
node_count = 0

# --- PREMIÈRE PASSE : IMPORTATION DES NŒUDS ---
print("🔹 Importation des nœuds en cours...")
for data in all_data:
    if data['type'] == 'node':
        node_id = data['id']
        label = data['labels'][0] if data['labels'] else 'Unlabeled'
        properties = data['properties']
        
        # On injecte l'ID Neo4j d'origine dans les propriétés
        properties['neo4j_id'] = node_id
        
        # Formatage des propriétés avec des backticks pour les clés
        props_list = []
        for key, value in properties.items():
            safe_key = f"`{key}`" # Gère les espaces dans les clés des nœuds
            
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
            
            # [AJOUT MINIMAL] Validation par batch de 1000 pour sécuriser les données insérées
            if node_count % 100 == 0:
                conn.commit()
                logging.info(f"[BATCH] 100 nœuds validés et committés (Total actuel: {node_count})")
                
            if node_count % 500 == 0:
                print(f"   -> {node_count} nœuds importés...")
        except Exception as e:
            # [AJOUT MINIMAL] Écriture de l'erreur exacte rencontrée dans le fichier texte
            logging.error(f"❌ Erreur lors de l'insertion du nœud {node_id}: {e}")
            print(f"❌ Erreur lors de l'insertion du nœud {node_id}: {e}")
            conn.rollback()
            
    elif data['type'] == 'relationship':
        relationships.append(data)

conn.commit()
print(f"✅ Importation des nœuds terminée ({node_count} nœuds).")
logging.info(f"Fin d'importation des nœuds. Total : {node_count}")


# --- INDEXATION CRUCIALE ---
print("⚡ Création de l'index pour accélérer la liaison des relations...")
cursor.execute(f"""
    CREATE INDEX IF NOT EXISTS idx_neo4j_id 
    ON "{graph_name}"."_ag_label_vertex" (ag_catalog.agtype_access_operator(properties, '"neo4j_id"'));
""")
conn.commit()


# --- SECONDE PASSE : IMPORTATION DES RELATIONS ---
print(f"🚀 Liaison de {len(relationships)} relations en cours...")
rel_count = 0

for rel in relationships:
    start_id = rel['start']['id']
    end_id = rel['end']['id']
    rel_type = rel['label']
    properties = rel.get('properties', {})
    
    # Formatage des propriétés avec des backticks pour les clés (Ex: `player misc_crdy`)
    props_list = []
    for key, value in properties.items():
        safe_key = f"`{key}`" # Solution pour le bug de l'espace
        
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
        
        # [AJOUT MINIMAL] Validation par batch de 1000 pour libérer la mémoire de Postgres
        if rel_count % 5 == 0:
            conn.commit()
            logging.info(f"[BATCH] 5 relations validées et committées (Total actuel: {rel_count})")
            
        if rel_count % 100 == 0:
            print(f"   -> {rel_count} relations liées...")
    except Exception as e:
        # [AJOUT MINIMAL] Journalisation de l'erreur de liaison
        logging.error(f"❌ Erreur relation entre {start_id} et {end_id} (Type: {rel_type}): {e}")
        print(f"❌ Erreur relation entre {start_id} et {end_id}: {e}")
        conn.rollback()

conn.commit()
print(f"🎉 Importation terminée avec succès ! Total : {node_count} nœuds et {rel_count} relations.")
logging.info(f"🎉 Importation terminée avec succès ! Total : {node_count} nœuds et {rel_count} relations.")

# Fermeture des connexions
cursor.close()
conn.close()