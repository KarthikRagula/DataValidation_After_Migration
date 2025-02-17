import mysql.connector
import psycopg2
import math
import logging
import traceback
from datetime import datetime

# ✅ Clear logs before running
open("comparison_logs.txt", "w").close()  # Clears previous logs

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
    mysql_cursor.execute("SHOW TABLES;")
    mysql_tables = {table[0].lower() for table in mysql_cursor.fetchall()}  # Normalize table names to lowercase
    mysql_tables1 = {table[0] for table in mysql_cursor.fetchall()}  # Normalize table names to lowercase
    
    postgres_cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
    )
    postgres_tables = {table[0].lower() for table in postgres_cursor.fetchall()}  # Normalize table names to lowercase
    
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

# ✅ Define batch size for fetching rows
BATCH_SIZE = 1000  # Adjust based on memory availability

# ✅ Helper function for comparing floats with precision tolerance
def compare_floats(mysql_val, postgres_val):
    """ Compare FLOAT/DOUBLE values considering precision tolerance """
    return math.isclose(mysql_val, postgres_val, rel_tol=1e-5)

# ✅ Helper function to normalize timestamps for comparison
def normalize_timestamp(timestamp):
    """ Normalize timestamp by truncating fractional seconds """
    if timestamp and len(timestamp) > 19:
        return timestamp[:19]  # Remove fractional seconds
    return timestamp

# ✅ Compare tables
mismatches = []

for table in mysql_tables:
    if table not in postgres_tables:
        continue
    try:
        # ✅ MySQL Query using INFORMATION_SCHEMA for column details
        mysql_cursor.execute(
        f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s AND TABLE_SCHEMA = %s;", 
        (table.upper(), mysql_db))
        mysql_columns = [desc[0].lower() for desc in mysql_cursor.fetchall()]
        # ✅ PostgreSQL Query using INFORMATION_SCHEMA for column details
        postgres_cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public';", (table,)
        )
        postgres_columns = [desc[0].lower() for desc in postgres_cursor.fetchall()]
    except mysql.connector.errors.ProgrammingError as e:
        if "1146" in str(e):
            msg = f"❌ Table {table} doesn't exist in MySQL!"
            logging.warning(msg)
        else:
            msg = f"❌ Error fetching column names for table {table} in MySQL: {e}\n{traceback.format_exc()}"
            logging.error(msg)
        continue

    except Exception as e:
        msg = f"❌ Error fetching column names for table {table}: {e}\n{traceback.format_exc()}"
        logging.error(msg)
        continue
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


    # ✅ Compare row-by-row in batches
    try:
        mysql_cursor.execute(f"SELECT * FROM {table.upper()};")
        postgres_cursor.execute(f"SELECT * FROM {table.upper()};")

        row_idx = 0

        while True:
            mysql_data = mysql_cursor.fetchmany(BATCH_SIZE)
            postgres_data = postgres_cursor.fetchmany(BATCH_SIZE)

            if not mysql_data and not postgres_data:
                break  # Stop when both databases have no more data

            # Create dictionaries mapping column names to values for each row
            mysql_dict = [dict(zip(mysql_columns, row)) for row in mysql_data]
            postgres_dict = [dict(zip(postgres_columns, row)) for row in postgres_data]

            # Compare the rows by checking column names explicitly
            for row_idx, (mysql_row, postgres_row) in enumerate(zip(mysql_dict, postgres_dict), start=row_idx + 1):
                for col_name in mysql_columns:
                    if col_name in mysql_row and col_name in postgres_row:
                        mysql_value = mysql_row[col_name]
                        postgres_value = postgres_row[col_name]

                        # Handle boolean data type mismatch (1/0 vs TRUE/FALSE)
                        if isinstance(mysql_value, bool) and isinstance(postgres_value, bool):
                            if mysql_value != postgres_value:
                                mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_value}, PostgreSQL: {postgres_value}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                                mismatches.append(mismatch)
                                logging.warning(mismatch)
                        # Handle BLOB (MySQL) and BYTEA (PostgreSQL) comparison
                        elif isinstance(mysql_value, bytes) and isinstance(postgres_value, memoryview):
                            # Convert memoryview (PostgreSQL) to bytes for comparison
                            postgres_value = bytes(postgres_value)
                            if mysql_value != postgres_value:
                                mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: BLOB (binary data), PostgreSQL: BYTEA (binary data)\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                                mismatches.append(mismatch)
                                logging.warning(mismatch)

                        # Alternatively, if both are of type 'bytes', just compare them as normal:
                        elif isinstance(mysql_value, bytes) and isinstance(postgres_value, bytes):
                            if mysql_value != postgres_value:
                                mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: BLOB (binary data), PostgreSQL: BYTEA (binary data)\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                                mismatches.append(mismatch)
                                logging.warning(mismatch)

                        # Handle NULL comparison
                        elif mysql_value is None and postgres_value is None:
                            continue  # Both NULLs, no issue
                        elif mysql_value != postgres_value:
                            mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_value}, PostgreSQL: {postgres_value}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                            mismatches.append(mismatch)
                            logging.warning(mismatch)

                        # Handle FLOAT/DATA precision mismatch
                        elif isinstance(mysql_value, float) and isinstance(postgres_value, float):
                            if not compare_floats(mysql_value, postgres_value):
                                mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_value}, PostgreSQL: {postgres_value}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                                mismatches.append(mismatch)
                                logging.warning(mismatch)

                        # Handle datetime and string mismatch
                        elif isinstance(mysql_value, datetime) and isinstance(postgres_value, datetime):
                            if mysql_value != postgres_value:
                                mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_value}, PostgreSQL: {postgres_value}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                                mismatches.append(mismatch)
                                logging.warning(mismatch)

                        elif isinstance(mysql_value, str) and isinstance(postgres_value, str):
                            # If they are datetime strings, try parsing them into datetime objects
                            try:
                                mysql_value = datetime.strptime(mysql_value, '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                pass  # Not a datetime string

                            try:
                                postgres_value = datetime.strptime(postgres_value, '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                pass  # Not a datetime string

                            if mysql_value != postgres_value:
                                mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_value}, PostgreSQL: {postgres_value}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                                mismatches.append(mismatch)
                                logging.warning(mismatch)

                        # Handle timestamp precision issues
                        elif isinstance(mysql_value, str) and isinstance(postgres_value, str):
                            mysql_value = normalize_timestamp(mysql_value)
                            postgres_value = normalize_timestamp(postgres_value)

                            if mysql_value != postgres_value:
                                mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_value}, PostgreSQL: {postgres_value}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                                mismatches.append(mismatch)
                                logging.warning(mismatch)

    except Exception as e:
        logging.error(f"Error comparing rows for table {table}: {e}")


# ✅ Save mismatches to logs.txt
if mismatches:
    logging.info("❌ Mismatches found! Check the logs.")
else:
    logging.info("✅ No mismatches found! Databases are identical.")

# ✅ Close connections
mysql_cursor.close()
mysql_conn.close()
postgres_cursor.close()
postgres_conn.close()

logging.info("========== Comparison Completed ==========")
