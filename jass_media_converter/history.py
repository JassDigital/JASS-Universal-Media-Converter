import sqlite3, os
from pathlib import Path
from datetime import datetime

class HistoryStore:
    def __init__(self):
        base=Path(os.getenv("APPDATA",str(Path.home())))/"JASS"/"UniversalMediaConverter"
        base.mkdir(parents=True,exist_ok=True)
        self.db=base/"history.sqlite3"
        with sqlite3.connect(self.db) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, source TEXT NOT NULL,
                output TEXT NOT NULL, result TEXT NOT NULL, details TEXT NOT NULL)""")
    def add(self,source,output,success,details):
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO jobs(created_at,source,output,result,details) VALUES(?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),str(source),str(output),"Success" if success else "Failed",str(details)))
    def list(self):
        with sqlite3.connect(self.db) as con:
            rows=con.execute("SELECT created_at,source,output,result FROM jobs ORDER BY id DESC LIMIT 500").fetchall()
        return [dict(zip(("created_at","source","output","result"),r)) for r in rows]
