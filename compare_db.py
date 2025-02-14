import mysql.connector
import psycopg2
import pandas as pd

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
mysql_cursor = mysql_conn.cursor()

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

# ✅ Compare tables
mismatches = []

for table in mysql_tables:
    if table not in postgres_tables:
        print(f"❌ Table {table} is missing in PostgreSQL!")
        continue

    print(f"✅ Comparing table: {table}")

    # Fetch data from MySQL
    mysql_cursor.execute(f"SELECT * FROM {table};")
    mysql_data = mysql_cursor.fetchall()
    mysql_columns = [desc[0] for desc in mysql_cursor.description]

    # Fetch data from PostgreSQL
    postgres_cursor.execute(f"SELECT * FROM {table};")
    postgres_data = postgres_cursor.fetchall()
    postgres_columns = [desc[0] for desc in postgres_cursor.description]

    # ✅ Check if column structure is the same
    if mysql_columns != postgres_columns:
        print(f"❌ Column mismatch in {table}:")
        print(f"MySQL: {mysql_columns}")
        print(f"PostgreSQL: {postgres_columns}")
        continue

    # ✅ Convert rows to dictionaries for easy comparison
    mysql_dict = {i: dict(zip(mysql_columns, row)) for i, row in enumerate(mysql_data)}
    postgres_dict = {i: dict(zip(postgres_columns, row)) for i, row in enumerate(postgres_data)}

    # ✅ Compare row by row
    for row_idx in range(min(len(mysql_data), len(postgres_data))):
        mysql_row = mysql_dict[row_idx]
        postgres_row = postgres_dict[row_idx]

        for col_idx, col_name in enumerate(mysql_columns):
            mysql_value = mysql_row[col_name]
            postgres_value = postgres_row[col_name]

            if mysql_value != postgres_value:
                mismatch = f"Mismatch in Table: {table}, Row: {row_idx+1}, Column: {col_name} | MySQL: {mysql_value}, PostgreSQL: {postgres_value}"
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
