import mysql.connector
import psycopg2
import logging
import hashlib
import traceback
from tabulate import tabulate
from datetime import datetime

def get_mysql_constraints(mysql_cursor, table, mysql_db):
    """Fetch constraints from MySQL"""
    constraints = {
        "primary_key": set(),
        "foreign_keys": set(),
        "unique_keys": set(),
        "check_constraints": set(),
        "default_values": {},
        "not_null": set()
    }
    # Fetch Primary Key
    mysql_cursor.execute(
        """
        SELECT COLUMN_NAME FROM information_schema.key_column_usage
        WHERE table_name = %s AND table_schema = %s AND constraint_name = 'PRIMARY'
        """, (table, mysql_db)
    )
    constraints["primary_key"] = sorted({row[0].lower() for row in mysql_cursor.fetchall()})
    # Fetch Foreign Keys
    mysql_cursor.execute(
        """
        SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
        FROM information_schema.key_column_usage
        WHERE table_name = %s AND table_schema = %s AND REFERENCED_TABLE_NAME IS NOT NULL
        """, (table, mysql_db)
    )
    constraints["foreign_keys"] = sorted({(row[0].lower(), row[1].lower(), row[2].lower()) for row in mysql_cursor.fetchall()})    
    # Fetch Unique Constraints
    mysql_cursor.execute(
        """
        SELECT DISTINCT INDEX_NAME, COLUMN_NAME FROM information_schema.statistics
        WHERE table_name = %s AND table_schema = %s AND non_unique = 0
        """, (table, mysql_db)
    )
    constraints["unique_keys"] = sorted({row[1].lower() for row in mysql_cursor.fetchall()})
    # Fetch CHECK Constraints 
    mysql_cursor.execute(
        """
        SELECT tc.constraint_name, cc.check_clause 
        FROM information_schema.table_constraints tc
        JOIN information_schema.check_constraints cc 
        ON tc.constraint_name = cc.constraint_name
        WHERE tc.table_schema = %s AND tc.table_name = %s
        """, (mysql_db, table)
    )
    constraints["check_constraints"] = sorted({row[1].strip().lower() for row in mysql_cursor.fetchall()})
    # Fetch Default Values & Not Null
    mysql_cursor.execute(
        """
        SELECT COLUMN_NAME, COLUMN_DEFAULT, IS_NULLABLE FROM information_schema.columns
        WHERE table_name = %s AND table_schema = %s
        """, (table, mysql_db)
    )
    for row in mysql_cursor.fetchall():
        column, default_value, is_nullable = row
        if default_value:
            constraints["default_values"][column.lower()] = default_value
        if is_nullable == 'NO':
            constraints["not_null"].add(column.lower())
    return constraints

def get_postgres_constraints(postgres_cursor, table):
    """Fetch constraints from PostgreSQL"""
    constraints = {
        "primary_key": set(),
        "foreign_keys": set(),
        "unique_keys": set(),
        "check_constraints": set(),
        "default_values": {},
        "not_null": set()
    }
    # Fetch Primary Key
    postgres_cursor.execute(
        """
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
        """, (table,)
    )
    constraints["primary_key"] = sorted({row[0] for row in postgres_cursor.fetchall()})
    # Fetch Foreign Keys
    postgres_cursor.execute(
        """
        SELECT a.attname, c.confrelid::regclass, d.attname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        JOIN pg_attribute d ON d.attrelid = c.confrelid AND d.attnum = ANY(c.confkey)
        WHERE c.contype = 'f' AND c.conrelid = %s::regclass
        """, (table,)
    )
    constraints["foreign_keys"] = sorted({(row[0], row[1], row[2]) for row in postgres_cursor.fetchall()})
    # Fetch Unique Constraints
    postgres_cursor.execute(
        """
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisunique
        """, (table,)
    )
    constraints["unique_keys"] = sorted({row[0] for row in postgres_cursor.fetchall()})
    # Fetch CHECK Constraints
    postgres_cursor.execute(
        """
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = %s::regclass AND contype = 'c'
        """, (table,)
    )
    constraints["check_constraints"] = sorted({row[1].strip() for row in postgres_cursor.fetchall()})
    # Fetch Default Values & Not Null
    postgres_cursor.execute(
        """
        SELECT column_name, column_default, is_nullable
        FROM information_schema.columns
        WHERE table_name = %s
        """, (table,)
    )
    for row in postgres_cursor.fetchall():
        column, default_value, is_nullable = row
        if default_value:
            constraints["default_values"][column] = default_value
        if is_nullable == 'NO':
            constraints["not_null"].add(column)
    return constraints

def compare_constraints(mysql_constraints, postgres_constraints, table_name):
    """Compare constraints between MySQL and PostgreSQL
    logging.info(f"MySQL Constraints")
    logging.warning(mysql_constraints)
    logging.info(f"Postgres Constraints")
    logging.warning(postgres_constraints)"""
    for key in mysql_constraints.keys():
        if isinstance(mysql_constraints[key], set) and isinstance(postgres_constraints[key], set):
            # Set-based comparison for primary key, foreign keys, unique keys, check constraints, not null
            missing_in_postgres = mysql_constraints[key] - postgres_constraints[key]
            missing_in_mysql = postgres_constraints[key] - mysql_constraints[key]
        elif isinstance(mysql_constraints[key], dict) and isinstance(postgres_constraints[key], dict):
            # Dictionary-based comparison for default values
            missing_in_postgres = {k: v for k, v in mysql_constraints[key].items() if k not in postgres_constraints[key]}
            missing_in_mysql = {k: v for k, v in postgres_constraints[key].items() if k not in mysql_constraints[key]}
    if missing_in_postgres:
        logging.warning(f"🔴 Missing {key} in PostgreSQL for table {table_name}: {missing_in_postgres}")  
    if missing_in_mysql:
        logging.warning(f"🔴 Missing {key} in MySQL for table {table_name}: {missing_in_mysql}")

def print_missing_rows(missing_hashes, hash_map, source_db, table, mysql_columns):
    if not missing_hashes:
        return
    missing_rows = [hash_map[hash_value] for hash_value in missing_hashes]
    # ✅ Convert datetime values to string for better readability
    formatted_rows = [
        [value.strftime('%Y-%m-%d %H:%M:%S') if isinstance(value, datetime) else value for value in row]
        for row in missing_rows
    ]
    # ✅ Dynamically set column width based on MySQL column name lengths
    column_widths = [max(len(col), 10) for col in mysql_columns]  # Ensure a minimum width of 10
    # ✅ Apply column widths to headers
    formatted_headers = [col.ljust(width) for col, width in zip(mysql_columns, column_widths)]
    # ✅ Apply column widths to each row
    formatted_rows = [
        [str(value).ljust(width)[:width] for value, width in zip(row, column_widths)] for row in formatted_rows
    ]
    # ✅ Format table with proper alignment
    table_str = tabulate(formatted_rows, headers=formatted_headers, tablefmt="grid")
    # ✅ Log & Print Neatly
    log_message = f"\n❌ {len(missing_hashes)} rows in {source_db} are missing for table {table}:\n{table_str}\n" + "=" * 200
    logging.warning(log_message)  # Log as warning

def normalize_value(value):
    """Normalize MySQL and PostgreSQL values for consistent hashing."""
    if isinstance(value, bool):
        return int(value)  # Normalize boolean values as integers (True -> 1, False -> 0)
    elif isinstance(value, int):
        return value  # Keep integers as they are
    elif value == 'TRUE' or value == 'FALSE':
        return True if value == 'TRUE' else False  # Handle string boolean values from PostgreSQL
    return value  # Return other types of values as they are

def normalize_binary_data(data):
    """Normalize binary data (BLOB in MySQL and BYTEA in PostgreSQL) for consistent hashing."""
    if isinstance(data, bytes):
        return data  # Already in bytes, so return as-is
    elif isinstance(data, memoryview):
        return data.tobytes()  # Convert memoryview to bytes
    else:
        raise ValueError("Unsupported data type for binary conversion")

def generate_row_hash(row):
    """Generate a hash for a given row by concatenating all columns as a string."""
    normalized_row = []
    for value in row:
        if isinstance(value, (bytes, memoryview)):  # Check if value is binary data
            normalized_value = normalize_binary_data(value)
        else:
            normalized_value = str(normalize_value(value))
        normalized_row.append(normalized_value)
    
    row_string = ''.join([str(v) for v in normalized_row])  # Concatenate the normalized values
    return hashlib.sha256(row_string.encode('utf-8')).hexdigest()  # Generate the hash
def get_mysql_indexes(mysql_cursor, table, mysql_db):
    """Fetch non-constraint indexes from MySQL."""
    mysql_cursor.execute(
        """
        SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE
        FROM information_schema.statistics
        WHERE TABLE_SCHEMA = %s 
        AND TABLE_NAME = %s
        AND INDEX_NAME NOT IN (
            SELECT CONSTRAINT_NAME 
            FROM information_schema.table_constraints
            WHERE TABLE_SCHEMA = %s 
            AND TABLE_NAME = %s
            AND CONSTRAINT_TYPE IN ('PRIMARY KEY', 'FOREIGN KEY')
        )
        """, (mysql_db, table, mysql_db, table)
    )
    
    indexes = {}
    for index_name, column_name, non_unique in mysql_cursor.fetchall():
        index_name = index_name.lower()
        column_name = column_name.lower()
        
        # Skip indexes where index name is exactly the same as column name
        if index_name == column_name:
            continue  
        
        if index_name not in indexes:
            indexes[index_name] = {"columns": [], "unique": not bool(non_unique)}
        
        indexes[index_name]["columns"].append(column_name)
    
    return indexes


def get_postgres_indexes(postgres_cursor, table):
    """Fetch non-constraint indexes from PostgreSQL."""
    postgres_cursor.execute(
        """
        SELECT i.relname AS index_name, 
               array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) AS column_names,
               ix.indisunique AS is_unique
        FROM pg_index ix
        JOIN pg_class i ON ix.indexrelid = i.oid
        JOIN pg_class t ON ix.indrelid = t.oid
        JOIN pg_namespace n ON t.relnamespace = n.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
        LEFT JOIN pg_constraint c ON c.conindid = i.oid -- Exclude constraints
        WHERE t.relname = %s AND n.nspname = 'public' AND (c.contype IS NULL OR c.contype NOT IN ('p', 'f'))
        GROUP BY i.relname, ix.indisunique
        """, (table,)
    )
    indexes = {}
    for index_name, columns, unique in postgres_cursor.fetchall():
        if len(columns) == 1:
            column_name = columns[0]
            expected_index_name = f"{table}_{column_name}_key"  # Construct expected index name
            # Skip indexes where index name is exactly the same as column name
            if index_name == column_name:
                continue  
            if index_name == expected_index_name:
                continue  # Skip storing this index
        indexes[index_name] = {"columns": [col.lower() for col in columns], "unique": unique}
    return indexes


def compare_indexes(mysql_indexes, postgres_indexes, table_name):
    logging.info("MySQL Indexes: %s", mysql_indexes)
    logging.info("PostgreSQL Indexes: %s", postgres_indexes)
    """Compare indexes between MySQL and PostgreSQL."""
    missing_in_postgres = set(mysql_indexes.keys()) - set(postgres_indexes.keys())
    missing_in_mysql = set(postgres_indexes.keys()) - set(mysql_indexes.keys())

    if missing_in_postgres:
        logging.warning(f"🔴 Missing indexes in PostgreSQL for table {table_name}: {missing_in_postgres}")
    if missing_in_mysql:
        logging.warning(f"🔴 Missing indexes in MySQL for table {table_name}: {missing_in_mysql}")

    for index_name in mysql_indexes.keys() & postgres_indexes.keys():
        mysql_index = mysql_indexes[index_name]
        postgres_index = postgres_indexes[index_name]
        if mysql_index["columns"] != postgres_index["columns"]:
            logging.warning(f"⚠️ Column mismatch in index {index_name} for table {table_name}.")
        if mysql_index["unique"] != postgres_index["unique"]:
            logging.warning(f"⚠️ Uniqueness mismatch in index {index_name} for table {table_name}.")

# ✅ Get user input for database credentials
# Get MySQL credentials
mysql_db = input("Enter MySQL database name: ")
mysql_user = input("Enter MySQL username: ")
mysql_pass = input("Enter MySQL password: ")

# Get PostgreSQL credentials
postgres_db = input("Enter PostgreSQL database name: ")
postgres_user = input("Enter PostgreSQL username: ")
postgres_pass = input("Enter PostgreSQL password: ")

"""
mysql_db = 'wm_login_mysql_stage'
mysql_user = 'karthikragula'
mysql_pass = 'R.Karthik@04'

postgres_db = 'wm_login_stage_postgres'
postgres_user = 'postgres'
postgres_pass = 'R.Karthik@04'

mysql_db = 'wmstudio_mysql'
mysql_user = 'karthikragula'
mysql_pass = 'R.Karthik@04'

postgres_db = 'wm_studio_postgres'
postgres_user = 'postgres'
postgres_pass = 'R.Karthik@04'

mysql_db = 'wm_edn'
mysql_user = 'karthikragula'
mysql_pass = 'R.Karthik@04'

postgres_db = 'wm_edn_postgres'
postgres_user = 'postgres'
postgres_pass = 'R.Karthik@04'

mysql_db = 'wm_container_services'
mysql_user = 'karthikragula'
mysql_pass = 'R.Karthik@04'

postgres_db = 'wm_container_services_postgres'
postgres_user = 'postgres'
postgres_pass = 'R.Karthik@04'

mysql_db = 'wm_deployment_cloud'
mysql_user = 'karthikragula'
mysql_pass = 'R.Karthik@04'

postgres_db = 'wm_deployment_cloud_postgres'
postgres_user = 'postgres'
postgres_pass = 'R.Karthik@04'

mysql_db = 'wm_developer_cloud'
mysql_user = 'karthikragula'
mysql_pass = 'R.Karthik@04'

postgres_db = 'wm_developer_cloud_postgres'
postgres_user = 'postgres'
postgres_pass = 'R.Karthik@04'
"""
# ✅ Clear logs before running
log_file = f"{mysql_db}_comparison_logs.txt"
open(log_file, "w").close()


# ✅ Configure logging
logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.info("========== Comparison started ==========")

# ✅ Connect to MySQL
try:
    mysql_conn = mysql.connector.connect(
        host="localhost", database=mysql_db, user=mysql_user, password=mysql_pass
    )
    mysql_cursor = mysql_conn.cursor(buffered=True)
    logging.info("✅ Connected to MySQL successfully")
except mysql.connector.Error as err:
    logging.error(f"❌ MySQL connection error: {err}")
    exit(1)

# ✅ Connect to PostgreSQL
try:
    postgres_conn = psycopg2.connect(
        host="localhost", database=postgres_db, user=postgres_user, password=postgres_pass
    )
    postgres_cursor = postgres_conn.cursor()
    logging.info("✅ Connected to PostgreSQL successfully")
except psycopg2.Error as err:
    logging.error(f"❌ PostgreSQL connection error: {err}")
    exit(1)

# ✅ Fetch all table names
try:
    mysql_cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';"
    )
    mysql_tables = {table[0].lower() for table in mysql_cursor.fetchall()}  # Normalize table names to lowercase

    # Fetch only tables (excluding views) from PostgreSQL
    postgres_cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
    )
    postgres_tables = {table[0].lower() for table in postgres_cursor.fetchall()}  # Normalize table names to lowercase

    logging.info(f"Number of tables in MySQL: {len(mysql_tables)}")
    logging.info(f"Number of tables in PostgreSQL: {len(postgres_tables)}")

    # ✅ Find tables that are missing in MySQL but present in PostgreSQL
    missing_in_mysql = postgres_tables - mysql_tables
    if missing_in_mysql:
        for table in missing_in_mysql:
            msg = f"❌ Table present in PostgreSQL but missing in MySQL: {table}"
            logging.warning(msg)
    else:
        msg = "✅ No tables are missing in MySQL."
        logging.info(msg)

    # ✅ Find tables that are missing in PostgreSQL but present in MySQL
    missing_in_postgres = mysql_tables - postgres_tables
    if missing_in_postgres:
        for table in missing_in_postgres:
            msg = f"❌ Table present in MySQL but missing in PostgreSQL: {table}"
            logging.warning(msg)
    else:
        msg = "✅ No tables are missing in PostgreSQL."
        logging.info(msg)

except Exception as e:
    logging.error(f"❌ Error fetching table names: {e}")
    exit(1)
# ✅ Compare tables
for table in mysql_tables:
    if table not in postgres_tables:
        continue
    logging.info(f"🔍 Table: {table} ")
    try:
        # ✅ MySQL Query using INFORMATION_SCHEMA for column details
        mysql_cursor.execute(f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = %s ORDER BY ORDINAL_POSITION;", (table.upper(), mysql_db))
        mysql_columns = sorted([desc[0].lower() for desc in mysql_cursor.fetchall()])
        # ✅ PostgreSQL Query using INFORMATION_SCHEMA for column details
        postgres_cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public' ORDER BY ordinal_position;", (table,))
        postgres_columns = sorted([desc[0].lower() for desc in postgres_cursor.fetchall()])
        # ✅ Check if column structure matches using 'not in'
        missing_in_mysql = [col for col in postgres_columns if col not in mysql_columns]
        missing_in_postgres = [col for col in mysql_columns if col not in postgres_columns]
        if missing_in_mysql or missing_in_postgres:
            if missing_in_mysql:
                msg = f"❌ Columns present in PostgreSQL but missing in MySQL: {missing_in_mysql}"
                logging.warning(msg)
            if missing_in_postgres:
                msg = f"❌ Columns present in MySQL but missing in PostgreSQL: {missing_in_postgres}"
                logging.warning(msg)
            continue
    except Exception as e:
        msg = f"❌ Error fetching column names for table {table}: {e}\n{traceback.format_exc()}"
        logging.error(msg)
        continue
    mysql_constraints = get_mysql_constraints(mysql_cursor, table.upper(), mysql_db)
    postgres_constraints = get_postgres_constraints(postgres_cursor, table)
    compare_constraints(mysql_constraints, postgres_constraints, table)
    """
    mysql_indexes = get_mysql_indexes(mysql_cursor, table.upper(), mysql_db)
    postgres_indexes = get_postgres_indexes(postgres_cursor, table)
    compare_indexes(mysql_indexes, postgres_indexes, table)"""

    # ✅ Compare row-by-row in batches
    try:
        mysql_cursor.execute(f"SELECT COUNT(*) FROM {table.upper()};")
        mysql_row_count = mysql_cursor.fetchone()[0]

        # ✅ Check row count in PostgreSQL
        postgres_cursor.execute(f"SELECT COUNT(*) FROM {table};")
        postgres_row_count = postgres_cursor.fetchone()[0]

        # ✅ Log the row counts
        logging.info(f" MySQL Rows: {mysql_row_count} | PostgreSQL Rows: {postgres_row_count}")

        # ✅ If row counts don't match, log a warning and continue
        if mysql_row_count != postgres_row_count:
            logging.warning(f"⚠️ Row count mismatch in table {table}: MySQL ({mysql_row_count}) vs PostgreSQL ({postgres_row_count})")
            continue  # Skip row-by-row comparison if counts don't match

        mysql_cursor.execute(f"SELECT {', '.join(mysql_columns)} FROM {table.upper()} ORDER BY {', '.join(mysql_columns)};")
        postgres_cursor.execute(f"SELECT {', '.join(postgres_columns)} FROM {table} ORDER BY {', '.join(postgres_columns)};")
        
        mysql_data = mysql_cursor.fetchall()
        postgres_data = postgres_cursor.fetchall()
        
        mysql_hash_map = {generate_row_hash(row): row for row in mysql_data}
        postgres_hash_map = {generate_row_hash(row): row for row in postgres_data}

        # ✅ Identify missing or mismatched rows
        missing_in_postgres = mysql_hash_map.keys() - postgres_hash_map.keys()
        missing_in_mysql = postgres_hash_map.keys() - mysql_hash_map.keys()

        if missing_in_postgres:
            print_missing_rows(missing_in_postgres, mysql_hash_map, "PostgreSQL", table, mysql_columns)

        if missing_in_mysql:
            print_missing_rows(missing_in_mysql, postgres_hash_map, "MySQL", table, mysql_columns)

        if not missing_in_postgres and not missing_in_mysql:
            logging.info(f"✅ Table {table} data matches perfectly!")

    except Exception as e:
        logging.error(f"Error comparing rows for table {table}: {e}")

# ✅ Close connections
mysql_cursor.close()
mysql_conn.close()
postgres_cursor.close()
postgres_conn.close()

logging.info("========== Comparison Completed ==========")
