import mysql.connector
import psycopg2
import logging
import hashlib
import traceback
from tabulate import tabulate
from datetime import datetime
import sys
from colorama import init, Fore, Style

class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.ERROR: "\033[91m",#RED
        logging.WARNING: "\033[93m",
        "GREEN": "\033[92m",
        "RESET": "\033[0m"
    }
    def format(self, record):
        log_msg = super().format(record)
        color = self.COLORS.get(record.levelno, "")
        if record.levelno == logging.INFO and "data matches perfectly!" in record.msg:
            return f"{self.COLORS['GREEN']}{log_msg}{self.COLORS['RESET']}"
        return f"{color}{log_msg}{self.COLORS['RESET']}"
    
def get_mysql_constraints(mysql_cursor, table, mysql_db):
    constraints = {
        "primary_key": set(),
        "foreign_keys": set(),
        "unique_keys": set(),
        "check_constraints": set(),
        "default_values": {},
        "not_null": set()
    }
    mysql_cursor.execute(
        """
        SELECT COLUMN_NAME FROM information_schema.key_column_usage
        WHERE table_name = %s AND table_schema = %s AND constraint_name = 'PRIMARY'
        """, (table, mysql_db)
    )
    constraints["primary_key"] = sorted({row[0].lower() for row in mysql_cursor.fetchall()})
    mysql_cursor.execute(
        """
        SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
        FROM information_schema.key_column_usage
        WHERE table_name = %s AND table_schema = %s AND REFERENCED_TABLE_NAME IS NOT NULL
        """, (table, mysql_db)
    )
    constraints["foreign_keys"] = sorted({(row[0].lower(), row[1].lower(), row[2].lower()) for row in mysql_cursor.fetchall()})    
    mysql_cursor.execute(
        """
        SELECT DISTINCT INDEX_NAME, COLUMN_NAME FROM information_schema.statistics
        WHERE table_name = %s AND table_schema = %s AND non_unique = 0
        """, (table, mysql_db)
    )
    constraints["unique_keys"] = sorted({row[1].lower() for row in mysql_cursor.fetchall()})
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
    """Fetch constraints from PostgreSQL while handling case sensitivity properly"""
    constraints = {
        "primary_key": set(),
        "foreign_keys": set(),
        "unique_keys": set(),
        "check_constraints": set(),
        "default_values": {},
        "not_null": set()
    }
    table_query = f'"{table}"' if not table.islower() else table
    postgres_cursor.execute(
        f"""
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
        """, (table_query,)
    )
    constraints["primary_key"] = sorted({row[0] for row in postgres_cursor.fetchall()})
    postgres_cursor.execute(
        f"""
        SELECT a.attname, c.confrelid::regclass, d.attname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        JOIN pg_attribute d ON d.attrelid = c.confrelid AND d.attnum = ANY(c.confkey)
        WHERE c.contype = 'f' AND c.conrelid = %s::regclass
        """, (table_query,)
    )
    constraints["foreign_keys"] = sorted({(row[0], row[1], row[2]) for row in postgres_cursor.fetchall()})
    postgres_cursor.execute(
        f"""
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisunique
        """, (table_query,)
    )
    constraints["unique_keys"] = sorted({row[0] for row in postgres_cursor.fetchall()})
    postgres_cursor.execute(
        f"""
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = %s::regclass AND contype = 'c'
        """, (table_query,)
    )
    constraints["check_constraints"] = sorted({row[1].strip() for row in postgres_cursor.fetchall()})
    postgres_cursor.execute(
        """
        SELECT column_name, column_default, is_nullable
        FROM information_schema.columns
        WHERE table_name = %s
        """, (table.lower(),)
    )
    for row in postgres_cursor.fetchall():
        column, default_value, is_nullable = row
        if default_value:
            constraints["default_values"][column] = default_value
        if is_nullable == 'NO':
            constraints["not_null"].add(column)
    return constraints

def compare_constraints(mysql_constraints, postgres_constraints, table_name):
    for key in mysql_constraints.keys():
        if isinstance(mysql_constraints[key], set) and isinstance(postgres_constraints[key], set):
            missing_in_postgres = mysql_constraints[key] - postgres_constraints[key]
            missing_in_mysql = postgres_constraints[key] - mysql_constraints[key]
        elif isinstance(mysql_constraints[key], dict) and isinstance(postgres_constraints[key], dict):
            missing_in_postgres = {k: v for k, v in mysql_constraints[key].items() if k not in postgres_constraints[key]}
            missing_in_mysql = {k: v for k, v in postgres_constraints[key].items() if k not in mysql_constraints[key]}
    if missing_in_postgres:
        logging.error(f"Missing {key} in PostgreSQL for table {table_name}: {missing_in_postgres}")  
    if missing_in_mysql:
        logging.error(f"Missing {key} in MySQL for table {table_name}: {missing_in_mysql}")

def print_missing_rows(missing_hashes, hash_map, source_db, table, mysql_columns):
    if not missing_hashes:
        return
    missing_rows = [hash_map[hash_value] for hash_value in missing_hashes]
    formatted_rows = [
        [value.strftime('%Y-%m-%d %H:%M:%S') if isinstance(value, datetime) else value for value in row]
        for row in missing_rows
    ]
    column_widths = [max(len(col), 10) for col in mysql_columns]  
    formatted_headers = [col.ljust(width) for col, width in zip(mysql_columns, column_widths)]
    formatted_rows = [
        [str(value).ljust(width)[:width] for value, width in zip(row, column_widths)] for row in formatted_rows
    ]
    table_str = tabulate(formatted_rows, headers=formatted_headers, tablefmt="grid")
    log_message = f"\n {len(missing_hashes)} rows in {source_db} are missing for table {table}:\n{table_str}\n" + "=" * 200
    logging.warning(log_message)

def normalize_value(value):
    if isinstance(value, bool):
        return int(value)
    elif isinstance(value, int):
        return value
    elif value == 'TRUE' or value == 'FALSE':
        return True if value == 'TRUE' else False
    return value

def normalize_binary_data(data):
    if isinstance(data, bytes):
        return data
    elif isinstance(data, memoryview):
        return data.tobytes()
    else:
        raise ValueError("Unsupported data type for binary conversion")

def generate_row_hash(row):
    normalized_row = []
    for value in row:
        if isinstance(value, (bytes, memoryview)):
            normalized_value = normalize_binary_data(value)
        else:
            normalized_value = str(normalize_value(value))
        normalized_row.append(normalized_value)
    row_string = ''.join([str(v) for v in normalized_row])
    return hashlib.sha256(row_string.encode('utf-8')).hexdigest()

def get_mysql_indexes(mysql_cursor, table, mysql_db):
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
        if index_name == column_name:
            continue  
        if index_name not in indexes:
            indexes[index_name] = {"columns": [], "unique": not bool(non_unique)}
        indexes[index_name]["columns"].append(column_name)
    return indexes

def get_postgres_indexes(postgres_cursor, table):
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
            expected_index_name = f"{table}_{column_name}_key"
            if index_name == column_name:
                continue  
            if index_name == expected_index_name:
                continue
        indexes[index_name] = {"columns": [col.lower() for col in columns], "unique": unique}
    return indexes


def compare_indexes(mysql_indexes, postgres_indexes, table_name):
    missing_in_postgres = set(mysql_indexes.keys()) - set(postgres_indexes.keys())
    missing_in_mysql = set(postgres_indexes.keys()) - set(mysql_indexes.keys())
    if missing_in_postgres:
        logging.error(f"Missing indexes in PostgreSQL for table {table_name}: {missing_in_postgres}")
    if missing_in_mysql:
        logging.error(f"Missing indexes in MySQL for table {table_name}: {missing_in_mysql}")
    for index_name in mysql_indexes.keys() & postgres_indexes.keys():
        mysql_index = mysql_indexes[index_name]
        postgres_index = postgres_indexes[index_name]
        if mysql_index["columns"] != postgres_index["columns"]:
            logging.error(f" Column mismatch in index {index_name} for table {table_name}.")
        if mysql_index["unique"] != postgres_index["unique"]:
            logging.error(f" Uniqueness mismatch in index {index_name} for table {table_name}.")
            
def connect_mysql(host, user, password, database):
    return mysql.connector.connect(host=host, user=user, password=password, database=database)

def connect_postgres(host, user, password, database):
    return psycopg2.connect(host=host, user=user, password=password, dbname=database)
"""
mysql_db = input("Enter MySQL database name: ")
mysql_user = input("Enter MySQL username: ")
mysql_pass = input("Enter MySQL password: ")

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

log_file = f"{mysql_db}_comparison_logs.txt"
file_handler = logging.FileHandler(log_file)
open(log_file, "w").close()
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(ColorFormatter("%(asctime)s - %(levelname)s - %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
logging.info("========== Comparison started ==========")
try:
    mysql_conn = mysql_conn = connect_mysql('localhost', mysql_user, mysql_pass, mysql_db)
    mysql_cursor = mysql_conn.cursor(buffered=True)
    logging.info(" Connected to MySQL successfully")
except mysql.connector.Error as err:
    logging.error(f" MySQL connection error: {err}")
    exit(1)

try:
    postgres_conn = connect_postgres('localhost', postgres_user, postgres_pass, postgres_db)
    postgres_cursor = postgres_conn.cursor()
    logging.info(" Connected to PostgreSQL successfully")
except psycopg2.Error as err:
    logging.error(f" PostgreSQL connection error: {err}")
    exit(1)

# Fetch all table names
try:
    # Fetch MySQL tables with original case
    mysql_cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';"
    )
    mysql_tables_original = {table[0] for table in mysql_cursor.fetchall()}  # Store original table names
    mysql_tables_lower = {table.lower() for table in mysql_tables_original}  # Lowercase for comparison

    # Fetch PostgreSQL tables with original case
    postgres_cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
    )
    postgres_tables_original = {table[0] for table in postgres_cursor.fetchall()}  # Store original table names
    postgres_tables_lower = {table.lower() for table in postgres_tables_original}  # Lowercase for comparison

    logging.info(f"Number of tables in MySQL: {len(mysql_tables_original)}")
    logging.info(f"Number of tables in PostgreSQL: {len(postgres_tables_original)}")

    # ✅ Find tables that are missing in MySQL but present in PostgreSQL
    missing_in_mysql = postgres_tables_lower - mysql_tables_lower
    if missing_in_mysql:
        for table in missing_in_mysql:
            original_name = next(
                tbl for tbl in postgres_tables_original if tbl.lower() == table
            )
            msg = f" Table present in PostgreSQL but missing in MySQL: {original_name}"
            logging.error(msg)
    else:
        logging.info(" No tables are missing in MySQL.")

    #  Find tables that are missing in PostgreSQL but present in MySQL
    missing_in_postgres = mysql_tables_lower - postgres_tables_lower
    if missing_in_postgres:
        for table in missing_in_postgres:
            original_name = next(
                tbl for tbl in mysql_tables_original if tbl.lower() == table
            )
            msg = f" Table present in MySQL but missing in PostgreSQL: {original_name}"
            logging.error(msg)
    else:
        logging.info(" No tables are missing in PostgreSQL.")

except Exception as e:
    logging.error(f" Error fetching table names: {e}")
    exit(1)
try:
    # Compare tables (preserve original case, compare in lowercase)
    for table in mysql_tables_original:
        matching_table = next((t for t in postgres_tables_original if t.lower() == table.lower()), None)
        if not matching_table:
            continue  # Skip if table is not present in PostgreSQL

        logging.info(f"Table: {table} ")

        try:
            # MySQL Query using INFORMATION_SCHEMA for column details
            mysql_cursor.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = %s ORDER BY ORDINAL_POSITION;",
                (table, mysql_db)
            )
            mysql_columns_original = [desc[0] for desc in mysql_cursor.fetchall()]
            mysql_columns_lower = sorted([col.lower() for col in mysql_columns_original])

            # PostgreSQL Query using INFORMATION_SCHEMA for column details
            postgres_cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public' ORDER BY ordinal_position;",
                (matching_table,)
            )
            postgres_columns_original = [desc[0] for desc in postgres_cursor.fetchall()]
            postgres_columns_lower = sorted([col.lower() for col in postgres_columns_original])

            #  Check if column structure matches
            missing_in_mysql = [col for col in postgres_columns_lower if col not in mysql_columns_lower]
            missing_in_postgres = [col for col in mysql_columns_lower if col not in postgres_columns_lower]

            if missing_in_mysql or missing_in_postgres:
                if missing_in_mysql:
                    original_missing = [col for col in postgres_columns_original if col.lower() in missing_in_mysql]
                    logging.error(f" Columns present in PostgreSQL but missing in MySQL: {original_missing}")
                if missing_in_postgres:
                    original_missing = [col for col in mysql_columns_original if col.lower() in missing_in_postgres]
                    logging.error(f" Columns present in MySQL but missing in PostgreSQL: {original_missing}")
                continue  # Skip further checks if columns don't match

        except Exception as e:
            logging.error(f" Error fetching column names for table {table}: {e}\n{traceback.format_exc()}")
            continue

        #  Compare constraints
        mysql_constraints = get_mysql_constraints(mysql_cursor, table, mysql_db)
        postgres_constraints = get_postgres_constraints(postgres_cursor, matching_table)
        compare_constraints(mysql_constraints, postgres_constraints, table)

        #  Compare indexes
        mysql_indexes = get_mysql_indexes(mysql_cursor, table, mysql_db)
        postgres_indexes = get_postgres_indexes(postgres_cursor, matching_table)
        compare_indexes(mysql_indexes, postgres_indexes, table)
        
        #  Compare row-by-row in batches
        try:
            mysql_cursor.execute(f"SELECT COUNT(*) FROM {table};")
            mysql_row_count = mysql_cursor.fetchone()[0]

            postgres_table = f'"{matching_table}"' if not matching_table.islower() else matching_table
            postgres_cursor.execute(f"SELECT COUNT(*) FROM {postgres_table};")

            postgres_row_count = postgres_cursor.fetchone()[0]

            logging.info(f" MySQL Rows: {mysql_row_count} | PostgreSQL Rows: {postgres_row_count}")

            #  If row counts don't match, log a error and continue
            if mysql_row_count != postgres_row_count:
                logging.error(f" Row count mismatch in table {table}: MySQL ({mysql_row_count}) vs PostgreSQL ({postgres_row_count})")
                continue  # Skip row-by-row comparison if counts don't match

            mysql_cursor.execute(f"SELECT {', '.join(mysql_columns_original)} FROM {table} ORDER BY {', '.join(mysql_columns_original)};")
            postgres_cursor.execute(f"SELECT {', '.join(mysql_columns_original)} FROM {postgres_table} ORDER BY {', '.join(mysql_columns_original)};")
            
            mysql_data = mysql_cursor.fetchall()
            postgres_data = postgres_cursor.fetchall()
            
            mysql_hash_map = {generate_row_hash(row): row for row in mysql_data}
            postgres_hash_map = {generate_row_hash(row): row for row in postgres_data}

            # Identify missing or mismatched rows
            missing_in_postgres = mysql_hash_map.keys() - postgres_hash_map.keys()
            missing_in_mysql = postgres_hash_map.keys() - mysql_hash_map.keys()

            if missing_in_postgres:
                print_missing_rows(missing_in_postgres, mysql_hash_map, "PostgreSQL", table, mysql_columns_original)

            if missing_in_mysql:
                print_missing_rows(missing_in_mysql, postgres_hash_map, "MySQL", table, mysql_columns_original)

            if not missing_in_postgres and not missing_in_mysql :
                logging.info(f"Table {table} data matches perfectly!")

        except Exception as e:
            logging.error(f"Error comparing rows for table {table}: {e}")

except Exception as e:
    logging.error(f" Error in table comparison: {e}")
    exit(1)

# ✅ Close connections
mysql_cursor.close()
mysql_conn.close()
postgres_cursor.close()
postgres_conn.close()

logging.info("========== Comparison Completed ==========")
