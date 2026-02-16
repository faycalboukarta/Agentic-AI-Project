import sqlite3
import pandas as pd
import os

def init_database():
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, "ecommerce.db")
    
    # Remove existing database if it exists
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing database: {db_path}")

    # Create a new database connection
    conn = sqlite3.connect(db_path)
    
    data_folder = os.path.join(script_dir, "data")
    
    # Map CSV filenames to table names
    csv_files = {
        "olist_customers_dataset.csv": "customers",
        "olist_geolocation_dataset.csv": "geolocation",
        "olist_order_items_dataset.csv": "order_items",
        "olist_order_payments_dataset.csv": "order_payments",
        "olist_order_reviews_dataset.csv": "order_reviews",
        "olist_orders_dataset.csv": "orders",
        "olist_products_dataset.csv": "products",
        "olist_sellers_dataset.csv": "sellers",
        "product_category_name_translation.csv": "product_category_name_translation"
    }

    try:
        for csv_file, table_name in csv_files.items():
            file_path = os.path.join(data_folder, csv_file)
            if os.path.exists(file_path):
                print(f"Loading {csv_file} into table {table_name}...")
                df = pd.read_csv(file_path)
                df.to_sql(table_name, conn, if_exists="replace", index=False)
                print(f"Table {table_name} created with {len(df)} rows.")
            else:
                print(f"File not found: {csv_file}")
        
        print("\nDatabase initialization complete.")
        
        # Verify tables
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print("Tables in database:", [table[0] for table in tables])
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_database()
