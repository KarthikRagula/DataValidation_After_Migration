# Database Comparison Script

## Overview
This script compares table structures and data between MySQL and PostgreSQL databases. It helps identify missing tables, differences in column structures, row count mismatches, and data inconsistencies.

## Features
- Connects to both MySQL and PostgreSQL databases.
- Fetches table names and identifies missing tables.
- Compares column structures for common tables.
- Checks row count mismatches.
- Uses hashing to detect missing or mismatched rows.
- Logs results and prints missing row details in a formatted table.
- Compares indexes for each table in both databases.

## Requirements
- Python 3.x
- MySQL Connector (`mysql-connector-python`)
- PostgreSQL Adapter (`psycopg2`)

Install dependencies using:
```sh
pip install mysql-connector-python psycopg2
```

## Configuration
Update the file validation_script.py :
```python
mysql_db = MYSQL_DATABASE_NAME
mysql_user = MYSQL_USERNAME
mysql_pass = MYSQL_PASSWORD

postgres_db = POSTGRES_DATABASE_NAME
postgres_user = POSTGRES_USERNAME
postgres_pass = POSTGRES_USER_PASSWORD
```

## Usage
Run the script using:
```sh
python3 validation_script.py
```

The script will output differences between the two databases and log the results in a file.

## Logging
Comparison results are logged in a file named `{MYSQL_DB}_comparison_logs.txt`, including details on missing tables, column mismatches, row count differences, and missing rows.
