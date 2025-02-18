import mysql.connector
import psycopg2
import logging
import hashlib

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

# ✅ Clear logs before running
open("comparison_logs.txt", "w").close()

# ✅ Get user input for database credentials
mysql_db = 'wm_login_mysql_stage'
mysql_user = 'karthikragula'
mysql_pass = 'R.Karthik@04'

postgres_db = 'wm_login_stage_postgres'
postgres_user = 'postgres'
postgres_pass = 'R.Karthik@04'

# ✅ Configure logging
logging.basicConfig(filename="comparison_logs.txt", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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
                mismatches.append(msg)
            if missing_in_postgres:
                msg = f"❌ Columns present in MySQL but missing in PostgreSQL: {missing_in_postgres}"
                logging.warning(msg)
                mismatches.append(msg)
            continue
    except Exception as e:
        msg = f"❌ Error fetching column names for table {table}: {e}\n{traceback.format_exc()}"
        logging.error(msg)
        continue
    
    # ✅ Compare row-by-row in batches
    try:
        mysql_cursor.execute(f"SELECT COUNT(*) FROM {table.upper()};")
        mysql_row_count = mysql_cursor.fetchone()[0]

        # ✅ Check row count in PostgreSQL
        postgres_cursor.execute(f"SELECT COUNT(*) FROM {table};")
        postgres_row_count = postgres_cursor.fetchone()[0]

        # ✅ Log the row counts
        logging.info(f"🔍 Table: {table} | MySQL Rows: {mysql_row_count} | PostgreSQL Rows: {postgres_row_count}")

        # ✅ If row counts don't match, log a warning and continue
        if mysql_row_count != postgres_row_count:
            logging.warning(f"⚠️ Row count mismatch in table {table}: MySQL ({mysql_row_count}) vs PostgreSQL ({postgres_row_count})")
            continue  # Skip row-by-row comparison if counts don't match

        mysql_cursor.execute(f"SELECT {', '.join(mysql_columns)} FROM {table.upper()} ORDER BY {', '.join(mysql_columns)};")
        postgres_cursor.execute(f"SELECT {', '.join(postgres_columns)} FROM {table} ORDER BY {', '.join(postgres_columns)};")
        
        mysql_data = mysql_cursor.fetchall()
        postgres_data = postgres_cursor.fetchall()
        
        # ✅ Create dictionaries to store row hashes mapped to actual row data
        mysql_hash_map = {generate_row_hash(row): row for row in mysql_data}
        postgres_hash_map = {generate_row_hash(row): row for row in postgres_data}

        # ✅ Identify missing or mismatched rows
        missing_in_postgres = mysql_hash_map.keys() - postgres_hash_map.keys()
        missing_in_mysql = postgres_hash_map.keys() - mysql_hash_map.keys()

        if missing_in_postgres:
            logging.warning(f"❌ {len(missing_in_postgres)} rows in MySQL are missing in PostgreSQL for table {table}")
            for hash_value in missing_in_postgres:
                logging.warning(f"MySQL Missing Row: {mysql_hash_map[hash_value]}")

        if missing_in_mysql:
            logging.warning(f"❌ {len(missing_in_mysql)} rows in PostgreSQL are missing in MySQL for table {table}")
            for hash_value in missing_in_mysql:
                logging.warning(f"PostgreSQL Missing Row: {postgres_hash_map[hash_value]}")

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
