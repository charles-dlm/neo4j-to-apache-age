import json
import psycopg  # Utilisation stricte de psycopg v3
import logging

# Configuration du fichier de log (Correction du formatage)
logging.basicConfig(
    filename='apache_age_import_commands.txt',
    filemode='w',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)

# 1. Connexion à la base de données Apache AGE
conn = psycopg.connect(
    host="localhost",
    port="5432",
    dbname="graph_db",
    user="postgres",
    password="password"
)
conn.autocommit = True
cursor = conn.cursor()

# Initialisation d'Apache AGE
cursor.execute("LOAD 'age';")
cursor.execute("SET search_path = ag_catalog, '$user', public;")

graph_name = 'social_media'

# Liste des types de nœuds récupérés en amont de Neo4j
labels_list = ["Entity", "Address", "Intermediary", "Officer", "Other"]

print("--- PHASE 0 : CRÉATION DES TABLES PAR TYPE DE NOEUD ---")
for label in labels_list:
    try:
        # create_vlabel crée explicitement la table physique dans PostgreSQL
        cursor.execute(f"SELECT create_vlabel('{graph_name}', '{label}');")
        logging.info(f"Table physique pour le label '{label}' créée ou déjà existante.")
    except Exception as e:
        # Si le label existe déjà, Apache AGE lève une erreur, on passe outre proprement
        logging.info(f"Note pour le label '{label}' : {e}")

print("Chargement du fichier JSON en mémoire...")
with open('icij.json', 'r', encoding='utf-8') as f:
    all_data = json.load(f)

print(f"Fichier chargé. {len(all_data)} éléments à traiter.")


def format_property_value(value):
    """Nettoie et type les valeurs pour Apache AGE."""
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


# Dictionnaire temporaire pour la deuxième phase (savoir quel nœud appartient à quelle table)
node_type_lookup = {}

print("\n--- PHASE 1 : INSERTION DES NOEUDS DANS LEURS TABLES RESPECTIVES ---")
node_count = 0

# Utilisation d'une transaction pour accélérer l'écriture de masse
with conn.transaction():
    for data in all_data:
        if data['type'] == 'node':
            node_id = data['id']
            # On récupère le type (label), par défaut 'Other' si absent
            label = data['labels'][0] if data['labels'] else 'Other'
            properties = data['properties']
            
            # Sauvegarde du type pour la phase relation
            node_type_lookup[node_id] = label
            
            # Injection de l'ID Neo4j d'origine dans les propriétés
            properties['neo4j_id'] = node_id

            props_list = []
            for key, value in properties.items():
                props_list.append(f"`{key}`: {format_property_value(value)}")
            props_clean = "{" + ", ".join(props_list) + "}"

            # L'insertion cible directement la table du Label
            cypher_query = f"CREATE (v:{label} {props_clean})"
            full_query = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_query} $$) AS (v agtype);"
            
            cursor.execute(full_query)
            node_count += 1
            
            if node_count % 50000 == 0:
                print(f"   -> {node_count} nœuds insérés...")

print(f"Insertion des nœuds terminée : {node_count} nœuds répartis dans leurs tables.")


print("\n--- CRÉATION DES INDEX RECHERCHE SUR CHAQUE TABLE ---")
# Sans ces index, PostgreSQL se fige lors du MATCH des relations
for lbl in labels_list:
    index_query = f"""
    CREATE INDEX IF NOT EXISTS idx_{lbl.lower()}_neo4j_id 
    ON "{graph_name}"."{lbl}" (ag_catalog.agtype_access_operator(properties, '"neo4j_id"'));
    """
    cursor.execute(index_query)
    print(f" -> Index de recherche activé sur la table '{lbl}'")


print("\n--- PHASE 2 : CRÉATION DES RELATIONS AVEC RECHERCHE CIBLÉE ---")
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

            # Récupération du type de la table cible pour le nœud de départ et d'arrivée
            start_label = node_type_lookup.get(start_id)
            end_label = node_type_lookup.get(end_id)

            # Si on ne trouve pas le type dans notre historique, on ne peut pas cibler la bonne table
            if not start_label or not end_label:
                logging.warning(f"Relation sautée : Nœud de départ {start_id} ou d'arrivée {end_id} introuvable.")
                continue

            props_list = []
            for key, value in properties.items():
                props_list.append(f"`{key}`: {format_property_value(value)}")
            props_clean = "{" + ", ".join(props_list) + "}"

            # REQUÊTE CIBLÉE : On force MATCH à chercher uniquement dans :start_label et :end_label
            # On traite une relation par une pour isoler les erreurs et garantir l'écriture
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
                logging.error(f"Échec création relation entre {start_id} et {end_id} : {e}")
            
            if rel_count % 25000 == 0:
                print(f"   -> {rel_count} relations analysées... ({success_rel} créées en base)")

print(f"\nImportation définitive terminée !")
print(f"Total nœuds : {node_count}")
print(f"Total relations créées avec succès : {success_rel} (sur {rel_count} analysées).")

cursor.close()
conn.close()
