# Database Validation Script

## Description
This script compares the structure and data between MySQL and PostgreSQL databases. It checks for missing tables, column mismatches, row count differences, and data inconsistencies.

## Prerequisites
- Linux OS
- Python 3.8+
- MySQL and PostgreSQL databases
- Required Python libraries: `mysql-connector-python`, `psycopg2`, `tabulate`, `colorama`, `psutil`, `zstandard`, `python-dotenv`

## Installation
1. Install `venv` if not already installed:
   ```sh
   sudo apt install python3.8-venv
   ```
2. Create and activate a virtual environment:
   ```sh
   python3 -m venv myenv
   source myenv/bin/activate
   ```
3. Install dependencies:
   ```sh
   pip install mysql-connector-python psycopg2 tabulate colorama psutil zstandard dotenv
   ```

## Configuration
Create a `.env` file in the same directory as the script with the following content:
```ini
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=username
MYSQL_PASSWORD=password

POSTGRESQL_HOST=localhost
POSTGRESQL_PORT=5432
POSTGRESQL_USER=username
POSTGRESQL_PASSWORD=password
```

## Running the Script
Run the script using:
```sh
python3 validation_script.py --mysql_db wm_login_mysql_stage --postgres_db wm_login_stage_postgres
```

## Packaging as Executable
1. Install PyInstaller:
   ```sh
   pip install pyinstaller
   ```
2. Create a standalone executable:
   ```sh
   pyinstaller --onefile --add-data ".env:." validation_script.py
   ```
3. Navigate to the `dist` folder and run the packaged script:
   ```sh
   cd dist
   ./validation_script --mysql_db wm_login_mysql_stage --postgres_db wm_login_stage_postgres
   ```

### If Any Errors Occur
If the script fails to execute due to permission issues, grant execute permission:
```sh
chmod +x validation_script
```

## Logging
The script logs the validation process to `comparison_logs.txt`. If any issues arise, check the log file for details.

## License
This project is licensed under the MIT License.

## Author
Karthik Ragula

