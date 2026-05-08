#!/usr/bin/env python3
"""
SQLite to CSV Export Script
===========================

This script exports all tables from a SQLite database to CSV files.
Perfect for data backup, migration, or analysis workflows.

Requirements:
    pip install pandas

Usage:
    python export_sqlite_to_csv.py

Author: Data Engineering Team
Date: 2026
"""

import sqlite3
import pandas as pd
import os
import sys
from pathlib import Path


def create_directory_if_missing(directory_path):
    """
    Create the output directory if it doesn't exist.
    
    Args:
        directory_path (str): Path to the directory to create
    """
    # Path() makes this work on Windows, Mac, and Linux
    path = Path(directory_path)
    
    # exist_ok=True means no error if directory already exists
    path.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Output directory ready: {path.absolute()}")


def get_all_table_names(connection):
    """
    Get a list of all table names from the SQLite database.
    
    Args:
        connection (sqlite3.Connection): Active database connection
        
    Returns:
        list: List of table names
    """
    # SQLite stores table names in a special table called 'sqlite_master'
    query = """
        SELECT name 
        FROM sqlite_master 
        WHERE type='table' 
        AND name NOT LIKE 'sqlite_%'  -- Exclude SQLite internal tables
    """
    
    # Execute query and fetch all results
    cursor = connection.execute(query)
    tables = cursor.fetchall()
    
    # Extract table names from tuples (each result is a tuple like ('users',))
    table_names = [table[0] for table in tables]
    
    return table_names


def export_table_to_csv(connection, table_name, output_directory):
    """
    Export a single table to a CSV file.
    
    Args:
        connection (sqlite3.Connection): Active database connection
        table_name (str): Name of the table to export
        output_directory (str): Where to save the CSV file
        
    Returns:
        bool: True if successful, False if failed
    """
    try:
        # Read the entire table into a pandas DataFrame
        # This is the magic line that converts SQL table to Python dataframe
        query = f"SELECT * FROM {table_name}"
        df = pd.read_sql_query(query, connection)
        
        # Create the output file path
        # Example: data/raw/users.csv
        output_file = os.path.join(output_directory, f"{table_name}.csv")
        
        # Export to CSV
        # index=False means don't write row numbers (0, 1, 2...) as a column
        df.to_csv(output_file, index=False)
        
        # Print success message with row count
        print(f"   ✅ {table_name}: {len(df)} rows exported")
        
        return True
        
    except Exception as error:
        # If something goes wrong, print the error but don't stop the script
        print(f"   ❌ {table_name}: ERROR - {error}")
        return False


def main():
    """
    Main function - orchestrates the export process.
    """
    # ============ CONFIGURATION ============
    # Change these values if your setup is different
    
    DATABASE_FILE = "store.db"           # Your SQLite database file
    OUTPUT_DIRECTORY = "data/raw"       # Where CSV files will be saved
    
    # =======================================
    
    print("=" * 50)
    print("SQLite to CSV Exporter")
    print("=" * 50)
    
    # Step 1: Check if database file exists
    if not os.path.exists(DATABASE_FILE):
        print(f"\n❌ Error: Database file not found: {DATABASE_FILE}")
        print("Please make sure the database file is in the same folder as this script.")
        sys.exit(1)  # Exit with error code
    
    print(f"\n📂 Database: {DATABASE_FILE}")
    
    # Step 2: Create output directory (if it doesn't exist)
    create_directory_if_missing(OUTPUT_DIRECTORY)
    
    # Step 3: Connect to the database
    try:
        # sqlite3.connect() creates a connection to the database
        connection = sqlite3.connect(DATABASE_FILE)
        print("\n🔌 Connected to database successfully!")
        
    except sqlite3.Error as error:
        print(f"\n❌ Failed to connect to database: {error}")
        sys.exit(1)
    
    # Step 4: Get list of all tables
    print("\n📋 Discovering tables...")
    tables = get_all_table_names(connection)
    
    if not tables:
        print("No tables found in the database!")
        connection.close()
        sys.exit(0)
    
    print(f"   Found {len(tables)} table(s): {', '.join(tables)}")
    
    # Step 5: Export each table
    print("\n📤 Exporting tables to CSV...")
    print("-" * 50)
    
    success_count = 0
    fail_count = 0
    
    for table_name in tables:
        if export_table_to_csv(connection, table_name, OUTPUT_DIRECTORY):
            success_count += 1
        else:
            fail_count += 1
    
    # Step 6: Close the database connection
    connection.close()
    
    # Step 7: Print summary
    print("-" * 50)
    print("\n📊 Export Summary:")
    print(f"   ✅ Successful: {success_count}")
    print(f"   ❌ Failed: {fail_count}")
    print(f"\n💾 CSV files saved in: {Path(OUTPUT_DIRECTORY).absolute()}")
    print("\n✨ Export complete!")
    print("=" * 50)


# This block runs only when the script is executed directly
# (not when imported as a module)
if __name__ == "__main__":
    main()
