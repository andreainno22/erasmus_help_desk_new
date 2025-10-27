#!/usr/bin/env python3
"""Script per verificare il contenuto del database"""
import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "data" / "universities.db"

if not db_path.exists():
    print(f"❌ Database non trovato: {db_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("\n=== UNIVERSITÀ REGISTRATE ===")
cursor.execute("SELECT * FROM universities")
universities = cursor.fetchall()
if universities:
    for uni in universities:
        print(f"  ID: {uni['id']}, Nome: {uni['university_name']}, Email: {uni['institutional_email']}")
else:
    print("  Nessuna università trovata")

print("\n=== DOCUMENTI CARICATI ===")
cursor.execute("""
    SELECT d.*, u.university_name 
    FROM uploaded_documents d 
    JOIN universities u ON d.university_id = u.id 
    ORDER BY d.upload_date DESC
""")
documents = cursor.fetchall()
if documents:
    for doc in documents:
        print(f"  ID: {doc['id']}, Tipo: {doc['document_type']}, Università: {doc['university_name']}")
        print(f"    File: {doc['original_filename']}, Attivo: {doc['is_active']}")
        print(f"    Path: {doc['file_path']}")
else:
    print("  Nessun documento trovato")

print("\n=== BANDI ATTIVI (erasmus_call) ===")
cursor.execute("""
    SELECT d.*, u.university_name 
    FROM uploaded_documents d 
    JOIN universities u ON d.university_id = u.id 
    WHERE d.document_type = 'erasmus_call' AND d.is_active = 1
""")
active_calls = cursor.fetchall()
if active_calls:
    for call in active_calls:
        print(f"  ✅ {call['university_name']} - {call['original_filename']}")
else:
    print("  ❌ Nessun bando attivo trovato!")

conn.close()
print("\n✅ Verifica completata\n")
