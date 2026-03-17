import sqlite3

db = sqlite3.connect('data/sentry.db')
for row in db.execute('SELECT sql FROM sqlite_master WHERE type="table"'):
    print(row[0])
