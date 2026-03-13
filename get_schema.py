import sqlite3

db = sqlite3.connect('C:/Users/chang/OneDrive/Desktop/Personal Finance Project/data/sentry.db')
for row in db.execute('SELECT sql FROM sqlite_master WHERE type="table"'):
    print(row[0])
