#!/usr/bin/env python3
"""
SQLite to CSV Export Script
===========================
Exports all tables from the Smart Retail AI SQLite database to CSV files.

Usage:
    python export_sqlite_to_csv.py
"""

import sqlite3
import pandas as pd
import os
import sys
from pathlib import Path


def find_database_file():
    """Find the SQLite database file in common locations."""
    # Common paths where the database might be located
    possible_paths = [
        "store.db",                    # Current directory
        "app/store.db",                # App subdirectory
        "instance/store.db",           # Flask instance folder
        "data/store.db",               # Data folder
        "database.db",                 # Alternative name
        "app/database.db",             # App with different name
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # If not found, ask user or search recursively
    print("🔍 Searching for database files in current directory...")
    
    # Look for any .db files
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(".db") or file.endswith(".sqlite") or file.endswith(".sqlite3"):
                path = os.path.join(root, file)
                print(f"   Found: {path}")
                return path
    
    return None


def create_directory_if_missing(directory_path):
    """Create the output directory if it doesn't exist."""
    path = Path(directory_path)
    path.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output directory ready: {path.absolute()}")


def get_all_table_names(connection):
    """Get a list of all table names from the SQLite database."""
    query = """
        SELECT name 
        FROM sqlite_master 
        WHERE type='table' 
        AND name NOT LIKE 'sqlite_%'
    """
    
    cursor = connection.execute(query)
    tables = cursor.fetchall()
    table_names = [table[0] for table in tables]
    
    return table_names


def export_table_to_csv(connection, table_name, output_directory):
    """Export a single table to a CSV file."""
    try:
        query = f"SELECT * FROM {table_name}"
        df = pd.read_sql_query(query, connection)
        
        output_file = os.path.join(output_directory, f"{table_name}.csv")
        df.to_csv(output_file, index=False)
        
        print(f"   ✅ {table_name}: {len(df)} rows → {table_name}.csv")
        return True
        
    except Exception as error:
        print(f"   ❌ {table_name}: ERROR - {error}")
        return False


def main():
    """Main function - orchestrates the export process."""
    
    OUTPUT_DIRECTORY = "data/raw"
    
    print("=" * 60)
    print("SQLite to CSV Exporter")
    print("=" * 60)
    
    # Step 1: Find the database file
    print("\n🔍 Locating database file...")
    DATABASE_FILE = find_database_file()
    
    if not DATABASE_FILE:
        print("\n❌ Error: Could not find any .db or .sqlite files!")
        print("\nPlease ensure your SQLite database is in one of these locations:")
        print("   - store.db (in the project root)")
        print("   - app/store.db")
        print("   - instance/store.db")
        sys.exit(1)
    
    print(f"📂 Found database: {DATABASE_FILE}")
    
    # Step 2: Create output directory
    create_directory_if_missing(OUTPUT_DIRECTORY)
    
    # Step 3: Connect to the database
    try:
        connection = sqlite3.connect(DATABASE_FILE)
        print("🔌 Connected to database successfully!")
        
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
    print("-" * 60)
    
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
    print("-" * 60)
    print("\n📊 Export Summary:")
    print(f"   ✅ Successful: {success_count}")
    print(f"   ❌ Failed: {fail_count}")
    print(f"\n💾 CSV files saved in: {Path(OUTPUT_DIRECTORY).absolute()}")
    print("\n✨ Export complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
