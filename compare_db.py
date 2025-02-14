import mysql.connector
import psycopg2

# ✅ Get user input for database credentials
mysql_db = input("Enter MySQL database name: ")
mysql_user = input("Enter MySQL username: ")
mysql_pass = input("Enter MySQL password: ")

postgres_db = input("Enter PostgreSQL database name: ")
postgres_user = input("Enter PostgreSQL username: ")
postgres_pass = input("Enter PostgreSQL password: ")

# ✅ Connect to MySQL
mysql_conn = mysql.connector.connect(
    host="localhost", database=mysql_db, user=mysql_user, password=mysql_pass
)
mysql_cursor = mysql_conn.cursor(buffered=True)

# ✅ Connect to PostgreSQL
postgres_conn = psycopg2.connect(
    host="localhost", database=postgres_db, user=postgres_user, password=postgres_pass
)
postgres_cursor = postgres_conn.cursor()

# ✅ Fetch all table names
mysql_cursor.execute("SHOW TABLES;")
mysql_tables = {table[0] for table in mysql_cursor.fetchall()}

postgres_cursor.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
)
postgres_tables = {table[0] for table in postgres_cursor.fetchall()}

# ✅ Clear logs.txt before running
with open("logs.txt", "w") as log_file:
    log_file.write("")  # Clears previous logs

# ✅ Define batch size for fetching rows
BATCH_SIZE = 5000  # Adjust based on memory availability

# ✅ Compare tables
with open("logs.txt", "a") as log_file:
    for table in mysql_tables:
        if table not in postgres_tables:
            print(f"❌ Table {table} is missing in PostgreSQL!")
            log_file.write(f"Table {table} is missing in PostgreSQL\n")
            continue

        print(f"✅ Comparing table: {table}")

        # ✅ Fetch column names
        mysql_cursor.execute(f"SELECT * FROM {table} LIMIT 1;")
        mysql_columns = [desc[0] for desc in mysql_cursor.description]

        postgres_cursor.execute(f"SELECT * FROM {table} LIMIT 1;")
        postgres_columns = [desc[0] for desc in postgres_cursor.description]

        # ✅ Check if column structure matches
        if mysql_columns != postgres_columns:
            print(f"❌ Column mismatch in {table}")
            log_file.write(f"Column mismatch in {table}: MySQL={mysql_columns}, PostgreSQL={postgres_columns}\n")
            continue

        # ✅ Compare row-by-row in batches (Using Python Sets for Fast Comparison)
        mysql_cursor.execute(f"SELECT * FROM {table};")
        postgres_cursor.execute(f"SELECT * FROM {table};")

        while True:
            mysql_data = mysql_cursor.fetchmany(BATCH_SIZE)
            postgres_data = postgres_cursor.fetchmany(BATCH_SIZE)

            if not mysql_data and not postgres_data:
                break  # Stop when both databases have no more data

            # ✅ Convert rows to tuples for comparison (More Efficient than Dict)
            mysql_set = {tuple(row) for row in mysql_data}
            postgres_set = {tuple(row) for row in postgres_data}

            # ✅ Find Differences (Mismatches)
            mysql_only = mysql_set - postgres_set
            postgres_only = postgres_set - mysql_set

            # ✅ Log Mismatches (Directly to File for Efficiency)
            for row in mysql_only:
                log_file.write(f"Table: {table}, Extra in MySQL: {row}\n")
            for row in postgres_only:
                log_file.write(f"Table: {table}, Extra in PostgreSQL: {row}\n")

# ✅ Close connections
mysql_cursor.close()
mysql_conn.close()
postgres_cursor.close()
postgres_conn.close()

print("✅ Data comparison completed! Check logs.txt for mismatches.")
