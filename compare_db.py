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
mysql_tables = [table[0] for table in mysql_cursor.fetchall()]

postgres_cursor.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public';"
)
postgres_tables = [table[0] for table in postgres_cursor.fetchall()]

# ✅ Clear logs.txt before running
open("logs.txt", "w").close()  # Clears previous logs

# ✅ Define batch size for fetching rows
BATCH_SIZE = 1000  # Adjust based on memory availability

# ✅ Compare tables
mismatches = []

for table in mysql_tables:
    if table not in postgres_tables:
        print(f"❌ Table {table} is missing in PostgreSQL!")
        mismatches.append(f"Table {table} is missing in PostgreSQL")
        continue

    print(f"✅ Comparing table: {table}")

    # Fetch column names
    mysql_cursor.execute(f"SELECT * FROM {table} LIMIT 1;")
    mysql_columns = [desc[0] for desc in mysql_cursor.description]

    postgres_cursor.execute(f"SELECT * FROM {table} LIMIT 1;")
    postgres_columns = [desc[0] for desc in postgres_cursor.description]

    # ✅ Check if column structure matches
    if mysql_columns != postgres_columns:
        print(f"❌ Column mismatch in {table}:")
        print(f"MySQL: {mysql_columns}")
        print(f"PostgreSQL: {postgres_columns}")
        mismatches.append(f"Column mismatch in {table}: MySQL={mysql_columns}, PostgreSQL={postgres_columns}")
        continue

    # ✅ Compare using SQL-based method (Faster for Huge Data)
    postgres_cursor.execute(f"""
        (SELECT * FROM {table})
        EXCEPT
        (SELECT * FROM {table});
    """)
    
    diff_rows = postgres_cursor.fetchall()

    if diff_rows:
        print(f"❌ Mismatches found in {table}")
        for row in diff_rows:
            mismatches.append(f"Table: {table}, Mismatched Row: {row}")

    # ✅ Compare row-by-row in batches (Backup method)
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
                if mysql_row[col_name] != postgres_row[col_name]:
                    mismatch = f"Mismatch in Table: {table}, Row: {row_idx}, Column: {col_name} | MySQL: {mysql_row[col_name]}, PostgreSQL: {postgres_row[col_name]}"
                    mismatches.append(mismatch)

# ✅ Save mismatches to logs.txt
if mismatches:
    with open("logs.txt", "w") as log_file:
        log_file.write("\n".join(mismatches))
    print("❌ Mismatches found! Check logs.txt for details.")
else:
    print("✅ No mismatches found! Databases are identical.")

# ✅ Close connections
mysql_cursor.close()
mysql_conn.close()
postgres_cursor.close()
postgres_conn.close()
