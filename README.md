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

The script will output differences between the two databases and log the results in a file.


## Building Executable
To package the script as a standalone executable using PyInstaller:
```sh
pip install pyinstaller
pyinstaller --onefile validation_script.py
```

This will generate an executable in the `dist` folder.

## Usage
1. Build manually from the code or Download the `validation_script` file from the `dist` folder.
2. Place a `.env` file in the same directory as the script.
3. Run the script using the following format:
   ```sh
   ./validation_script --mysql_db MYSQL_DB --postgres_db POSTGRES_DB
   ```

### Configuration
Ensure `.env` contains the necessary database credentials:

```
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=username
MYSQL_PASSWORD=password

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=username
POSTGRES_PASSWORD=password
```

## Troubleshooting
If you encounter a permission error, run the following command to grant execution permission:
   ```sh
   chmod +x validation_script
   ```

## Logging
The script logs the validation process to `comparison_logs.txt`. If any issues arise, check the log file for details.

## Author
Karthik Ragula
