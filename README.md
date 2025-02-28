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
