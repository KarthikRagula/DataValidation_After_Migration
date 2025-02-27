import mysql.connector
import psycopg2
import logging
import traceback
from tabulate import tabulate
from datetime import datetime
import sys
from colorama import init, Fore, Style
import psutil
import base64
import time

class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.ERROR: "\033[91m",#RED
        logging.WARNING: "\033[93m",#YELLOW
        "GREEN": "\033[92m",
        "RESET": "\033[0m"
    }
    def format(self, record):
        log_msg = super().format(record)
        color = self.COLORS.get(record.levelno, "")
        if record.levelno == logging.INFO and "data matches perfectly!" in record.msg:
            return f"{self.COLORS['GREEN']}{log_msg}{self.COLORS['RESET']}"
        return f"{color}{log_msg}{self.COLORS['RESET']}"

def get_memory_usage():
    process = psutil.Process()
    return process.memory_info().rss / (1024 * 1024)

def connect_mysql(host, user, password, database):
    return mysql.connector.connect(host=host, user=user, password=password, database=database)

def connect_postgres(host, user, password, database):
    return psycopg2.connect(host=host, user=user, password=password, dbname=database)

def setup_logging(mysql_db):
    log_file = f"{mysql_db}_comparison_logs.txt"
    open(log_file, "w").close()

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColorFormatter("%(asctime)s - %(levelname)s - %(message)s"))
    
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])

def fetch_and_compare_tables(mysql_cursor, postgres_cursor, mysql_db):
    try:
        mysql_cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';"
        )
        mysql_tables_original = {table[0] for table in mysql_cursor.fetchall()}
        mysql_tables_lower = {table.lower() for table in mysql_tables_original}

        postgres_cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
        )
        postgres_tables_original = {table[0] for table in postgres_cursor.fetchall()}
        postgres_tables_lower = {table.lower() for table in postgres_tables_original}

        logging.info(f"Number of tables in MySQL: {len(mysql_tables_original)}")
        logging.info(f"Number of tables in PostgreSQL: {len(postgres_tables_original)}")

        missing_in_mysql = postgres_tables_lower - mysql_tables_lower
        if missing_in_mysql:
            for table in missing_in_mysql:
                original_name = next(tbl for tbl in postgres_tables_original if tbl.lower() == table)
                logging.error(f"Table present in PostgreSQL but missing in MySQL: {original_name}")
        else:
            logging.info("No tables are missing in MySQL.")

        missing_in_postgres = mysql_tables_lower - postgres_tables_lower
        if missing_in_postgres:
            for table in missing_in_postgres:
                original_name = next(tbl for tbl in mysql_tables_original if tbl.lower() == table)
                logging.error(f"Table present in MySQL but missing in PostgreSQL: {original_name}")
        else:
            logging.info("No tables are missing in PostgreSQL.")
        fetch_and_compare_columns(mysql_cursor, postgres_cursor, mysql_db, mysql_tables_original, postgres_tables_original)
    except Exception as e:
        logging.error(f"Error fetching table names: {e}")
        exit(1)

def fetch_and_compare_columns(mysql_cursor, postgres_cursor, mysql_db, mysql_tables_original, postgres_tables_original):
    try:
        for table in mysql_tables_original:
            matching_table = next((t for t in postgres_tables_original if t.lower() == table.lower()), None)
            if not matching_table:
                continue
            logging.info(f"Table: {table} ")
            try:
                mysql_cursor.execute(
                    "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = %s AND TABLE_SCHEMA = %s;",
                    (table, mysql_db)
                )
                mysql_columns_data = mysql_cursor.fetchall()
                mysql_columns_original = [col[0] for col in mysql_columns_data]
                mysql_columns_lower = sorted([col.lower() for col in mysql_columns_original])
                text_columns_mysql = [col[0] for col in mysql_columns_data if col[1] in ("char", "varchar", "text", "longtext") and col[2]!=1]

                postgres_cursor.execute(
                    "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public' ORDER BY ordinal_position;",
                    (matching_table,)
                )
                postgres_columns_data = postgres_cursor.fetchall()
                postgres_columns_original = [col[0] for col in postgres_columns_data]
                postgres_columns_lower = sorted([col.lower() for col in postgres_columns_original])
                text_columns_postgres = [col[0] for col in postgres_columns_data if col[1] in ("character varying", "character", "text")]

                text_columns = list(set(text_columns_mysql) - set(text_columns_postgres))

                missing_in_mysql = [col for col in postgres_columns_lower if col not in mysql_columns_lower]
                missing_in_postgres = [col for col in mysql_columns_lower if col not in postgres_columns_lower]

                if missing_in_mysql or missing_in_postgres:
                    if missing_in_mysql:
                        original_missing = [col for col in postgres_columns_original if col.lower() in missing_in_mysql]
                        logging.error(f"Columns present in PostgreSQL but missing in MySQL: {original_missing}")
                    if missing_in_postgres:
                        original_missing = [col for col in mysql_columns_original if col.lower() in missing_in_postgres]
                        logging.error(f"Columns present in MySQL but missing in PostgreSQL: {original_missing}")
                    continue
            except Exception as e:
                logging.error(f"Error fetching column names for table {table}: {e}\n{traceback.format_exc()}")
                continue
            
            before_memory = get_memory_usage()
            start_time = time.time()

            mysql_constraints = get_mysql_constraints(mysql_cursor, table, mysql_db)
            postgres_constraints = get_postgres_constraints(postgres_cursor, matching_table)
            compare_constraints(mysql_constraints, postgres_constraints, table)

            mysql_indexes = get_mysql_indexes(mysql_cursor, table, mysql_db)
            postgres_indexes = get_postgres_indexes(postgres_cursor, matching_table)
            compare_indexes(mysql_indexes, postgres_indexes, table)

            compare_rows(mysql_cursor, postgres_cursor, table, matching_table, mysql_columns_original,text_columns)

            end_time = time.time()
            after_memory = get_memory_usage()

            memory_used = after_memory - before_memory
            time_taken = end_time - start_time

            print(f"Memory used: {memory_used:.2f} MB | Time taken: {time_taken:.2f} seconds")          
    except Exception as e:
        logging.error(f"Error comparing columns: {e}")
        exit(1)

def normalize_binary_data(value):
    if isinstance(value, memoryview):  
        value = value.tobytes() 
    return base64.b64encode(value).decode("utf-8")

def normalize_value(value):
    if value is None:
        return "NULL"
    elif isinstance(value, bool):
        return "1" if value else "0"  
    elif isinstance(value, (int, float)):
        return str(value)  
    elif isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')  
    elif isinstance(value, (bytes, memoryview)):
        return normalize_binary_data(value) 
    elif isinstance(value, str):
        value = value.strip()
        if value.upper() in ("TRUE", "FALSE"):  
            return "1" if value.upper() == "TRUE" else "0"  
        return value  
    return str(value)  

def print_missing_rows(missing_rows, source_db, table, column_names):
    if not missing_rows:
        return
    formatted_rows = [
        [normalize_value(value) for value in row] for row in missing_rows
    ]
    table_str = tabulate(formatted_rows, headers=column_names, tablefmt="grid")
    log_message = f"\n {len(missing_rows)} rows in {source_db} are missing for table {table}:\n{table_str}\n" + "=" * 200
    logging.warning(log_message)
    
def compare_rows(mysql_cursor, postgres_cursor, table, matching_table, columns, text_columns):
    try:
        mysql_cursor.execute(f"SELECT COUNT(*) FROM {table};")
        mysql_row_count = mysql_cursor.fetchone()[0]

        postgres_table = f'"{matching_table}"' if not matching_table.islower() else matching_table
        postgres_cursor.execute(f"SELECT COUNT(*) FROM {postgres_table};")
        postgres_row_count = postgres_cursor.fetchone()[0]

        logging.info(f"MySQL Rows: {mysql_row_count} | PostgreSQL Rows: {postgres_row_count}")
        order_by_clause_mysql = ", ".join(
            [f"BINARY {col}" if col in text_columns else col for col in columns]
        )
        order_by_clause_postgres = ", ".join(
            [f"{col} COLLATE \"C\"" if col in text_columns else col for col in columns]
        )
        mysql_cursor.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order_by_clause_mysql};")
        postgres_cursor.execute(f"SELECT {', '.join(columns)} FROM {postgres_table} ORDER BY {order_by_clause_postgres};")
        missing_in_mysql=[]
        missing_in_postgres=[]
        while True:
            mysql_row = mysql_cursor.fetchone()
            postgres_row = postgres_cursor.fetchone()
            if mysql_row is None and postgres_row is None:
                break
            mysql_normalized = tuple(normalize_value(val) for val in mysql_row) if mysql_row else None
            postgres_normalized = tuple(normalize_value(val) for val in postgres_row) if postgres_row else None
            if mysql_normalized is None:
                missing_in_mysql.append(postgres_normalized)
            elif postgres_normalized is None:
                missing_in_postgres.append(mysql_normalized)
            elif mysql_normalized != postgres_normalized:
                missing_in_mysql.append(postgres_normalized)
                missing_in_postgres.append(mysql_normalized)

        print_missing_rows(missing_in_mysql, "MySQL", table, columns)
        print_missing_rows(missing_in_postgres,"POSTGRES",table,columns)

        if not missing_in_mysql and not missing_in_postgres:
            logging.info(f"Table {table} data matches perfectly!")

    except Exception as e:
        logging.error(f"Error comparing rows for table {table}: {e}")

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
            
def main():
        
    mysql_db = 'wm_deployment_cloud'
    mysql_user = 'karthikragula'
    mysql_pass = 'R.Karthik@04'

    postgres_db = 'wm_deployment_cloud_postgres'
    postgres_user = 'postgres'
    postgres_pass = 'R.Karthik@04'

    setup_logging(mysql_db)
    
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

    fetch_and_compare_tables(mysql_cursor, postgres_cursor, mysql_db)
    
    mysql_cursor.close()
    mysql_conn.close()
    postgres_cursor.close()
    postgres_conn.close()

    logging.info("========== Comparison Completed ==========")
if __name__ == "__main__":
    main()