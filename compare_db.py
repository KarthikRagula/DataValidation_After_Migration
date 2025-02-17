import mysql.connector
import psycopg2
import math
import logging

# ✅ Get user input for database credentials
mysql_db = input("Enter MySQL database name: ")
mysql_user = input("Enter MySQL username: ")
mysql_pass = input("Enter MySQL password: ")

postgres_db = input("Enter PostgreSQL database name: ")
postgres_user = input("Enter PostgreSQL username: ")
postgres_pass = input("Enter PostgreSQL password: ")

# ✅ Configure logging
logging.basicConfig(filename="comparison_logs.txt", level=logging.INFO)
logging.info("Comparison started")

# ✅ Connect to MySQL
try:
    mysql_conn = mysql.connector.connect(
        host="localhost", database=mysql_db, user=mysql_user, password=mysql_pass
    )
    mysql_cursor = mysql_conn.cursor(buffered=True)
except mysql.connector.Error as err:
    logging.error(f"MySQL connection error: {err}")
    exit(1)

# ✅ Connect to PostgreSQL
try:
    postgres_conn = psycopg2.connect(
        host="localhost", database=postgres_db, user=postgres_user, password=postgres_pass
    )
    postgres_cursor = postgres_conn.cursor()
except psycopg2.Error as err:
    logging.error(f"PostgreSQL connection error: {err}")
    exit(1)

# ✅ Fetch all table names
try:
    mysql_cursor.execute("SHOW TABLES;")
    mysql_tables = [table[0] for table in mysql_cursor.fetchall()]

    postgres_cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
    )
    postgres_tables = [table[0] for table in postgres_cursor.fetchall()]
except Exception as e:
    logging.error(f"Error fetching table names: {e}")
    exit(1)

# ✅ Clear logs.txt before running
open("comparison_logs.txt", "w").close()  # Clears previous logs

# ✅ Define batch size for fetching rows
BATCH_SIZE = 1000  # Adjust based on memory availability

# ✅ Helper function for comparing floats with precision tolerance
def compare_floats(mysql_val, postgres_val):
    """ Compare FLOAT/DATA values considering precision tolerance """
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
        logging.warning(f"Table {table} is missing in PostgreSQL!")
        mismatches.append(f"Table {table} is missing in PostgreSQL")
        continue

    logging.info(f"Comparing table: {table}")

    # Fetch column names
    try:
        mysql_cursor.execute(f"SELECT * FROM {table} LIMIT 1;")
        mysql_columns = [desc[0].lower() for desc in mysql_cursor.description]  # Normalize column names

        postgres_cursor.execute(f"SELECT * FROM {table} LIMIT 1;")
        postgres_columns = [desc[0].lower() for desc in postgres_cursor.description]  # Normalize column names
    except Exception as e:
        logging.error(f"Error fetching column names for table {table}: {e}")
        continue

    # ✅ Check if column structure matches
    if mysql_columns != postgres_columns:
        logging.warning(f"Column mismatch in {table}: MySQL={mysql_columns}, PostgreSQL={postgres_columns}")
        mismatches.append(f"Column mismatch in {table}: MySQL={mysql_columns}, PostgreSQL={postgres_columns}")
        continue

    # ✅ Compare row-by-row in batches
    # ✅ Compare row-by-row in batches
    try:
        mysql_cursor.execute(f"SELECT * FROM {table};")
        postgres_cursor.execute(f"SELECT * FROM {table};")

        row_idx = 0

        while True:
            mysql_data = mysql_cursor.fetchmany(BATCH_SIZE)
            postgres_data = postgres_cursor.fetchmany(BATCH_SIZE)

            if not mysql_data and not postgres_data:
                break  # Stop when both databases have no more data

            mysql_dict = [dict(zip(mysql_columns, row)) for row in mysql_data]
            postgres_dict = [dict(zip(postgres_columns, row)) for row in postgres_data]

            for row_idx, (mysql_row, postgres_row) in enumerate(zip(mysql_dict, postgres_dict), start=row_idx + 1):
                for col_name in mysql_columns:
                    # Handle boolean data type mismatch (1/0 vs TRUE/FALSE)
                    if isinstance(mysql_row[col_name], bool) and isinstance(postgres_row[col_name], bool):
                        if mysql_row[col_name] != postgres_row[col_name]:
                            mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_row[col_name]}, PostgreSQL: {postgres_row[col_name]}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                            mismatches.append(mismatch)
                            logging.warning(mismatch)

                    # Handle NULL comparison
                    elif mysql_row[col_name] is None and postgres_row[col_name] is None:
                        continue  # Both NULLs, no issue
                    elif mysql_row[col_name] != postgres_row[col_name]:
                        mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_row[col_name]}, PostgreSQL: {postgres_row[col_name]}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                        mismatches.append(mismatch)
                        logging.warning(mismatch)

                    # Handle FLOAT/DATA precision mismatch
                    elif isinstance(mysql_row[col_name], float) and isinstance(postgres_row[col_name], float):
                        if not compare_floats(mysql_row[col_name], postgres_row[col_name]):
                            mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_row[col_name]}, PostgreSQL: {postgres_row[col_name]}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                            mismatches.append(mismatch)
                            logging.warning(mismatch)

                    # Handle timestamp precision issues
                    elif isinstance(mysql_row[col_name], str) and isinstance(postgres_row[col_name], str):
                        mysql_row[col_name] = normalize_timestamp(mysql_row[col_name])
                        postgres_row[col_name] = normalize_timestamp(postgres_row[col_name])

                        if mysql_row[col_name] != postgres_row[col_name]:
                            mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_row[col_name]}, PostgreSQL: {postgres_row[col_name]}\nMySQL Row: {mysql_row}\nPostgreSQL Row: {postgres_row}"
                            mismatches.append(mismatch)
                            logging.warning(mismatch)

    except Exception as e:
        logging.error(f"Error comparing rows for table {table}: {e}")
        continue


# ✅ Save mismatches to logs.txt
if mismatches:
    logging.info("Mismatches found!")
else:
    logging.info("No mismatches found! Databases are identical.")

# ✅ Close connections
mysql_cursor.close()
mysql_conn.close()
postgres_cursor.close()
postgres_conn.close()
