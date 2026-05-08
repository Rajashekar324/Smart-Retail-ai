import pandas as pd
import sqlite3

conn = sqlite3.connect("data/store.db")

df = pd.read_sql_query("SELECT * FROM sales", conn)

df.to_csv("data/sales.csv", index=False)