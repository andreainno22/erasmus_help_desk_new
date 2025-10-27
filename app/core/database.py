# app/core/database.py
import sqlite3
from pathlib import Path
from typing import Optional
import bcrypt
from datetime import datetime

class DatabaseManager:
    """Gestisce il database SQLite per le università."""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Crea il database nella cartella del progetto
            db_path = Path(__file__).parent.parent.parent / "data" / "universities.db"
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    def get_connection(self):
        """Crea una connessione al database."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Per accedere ai risultati come dizionari
        return conn
    
    def init_database(self):
        """Inizializza il database con le tabelle necessarie."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Tabella università
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS universities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                university_name TEXT UNIQUE NOT NULL,
                institutional_email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                contact_person TEXT,
                phone TEXT,
                is_verified BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')
        
        # Tabella documenti caricati
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS uploaded_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                university_id INTEGER NOT NULL,
                document_type TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                academic_year TEXT,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (university_id) REFERENCES universities(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def hash_password(self, password: str) -> str:
        """Genera l'hash della password usando bcrypt."""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verifica se la password corrisponde all'hash."""
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    def create_university(self, university_name: str, institutional_email: str, 
                         password: str, contact_person: str = None, phone: str = None) -> Optional[int]:
        """
        Crea una nuova università nel database.
        Restituisce l'ID dell'università creata o None in caso di errore.
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            password_hash = self.hash_password(password)
            
            cursor.execute('''
                INSERT INTO universities 
                (university_name, institutional_email, password_hash, contact_person, phone)
                VALUES (?, ?, ?, ?, ?)
            ''', (university_name, institutional_email, password_hash, contact_person, phone))
            
            university_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            return university_id
        except sqlite3.IntegrityError as e:
            print(f"Errore creazione università: {e}")
            return None
    
    def get_university_by_email(self, email: str) -> Optional[dict]:
        """Recupera un'università tramite email."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM universities WHERE institutional_email = ?
        ''', (email,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_university_by_id(self, university_id: int) -> Optional[dict]:
        """Recupera un'università tramite ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM universities WHERE id = ?
        ''', (university_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def update_last_login(self, university_id: int):
        """Aggiorna il timestamp dell'ultimo login."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE universities 
            SET last_login = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (university_id,))
        
        conn.commit()
        conn.close()
    
    def add_document(self, university_id: int, document_type: str, 
                    original_filename: str, stored_filename: str, 
                    file_path: str, academic_year: str = None) -> Optional[int]:
        """
        Aggiunge un documento caricato dall'università.
        document_type può essere: 'erasmus_call', 'destinations', 'courses', etc.
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO uploaded_documents 
                (university_id, document_type, original_filename, stored_filename, 
                 file_path, academic_year)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (university_id, document_type, original_filename, stored_filename, 
                  file_path, academic_year))
            
            doc_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            return doc_id
        except Exception as e:
            print(f"Errore aggiunta documento: {e}")
            return None
    
    def get_university_documents(self, university_id: int, document_type: str = None, 
                                 is_active: bool = True) -> list:
        """Recupera i documenti di un'università."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT * FROM uploaded_documents 
            WHERE university_id = ? AND is_active = ?
        '''
        params = [university_id, 1 if is_active else 0]
        
        if document_type:
            query += ' AND document_type = ?'
            params.append(document_type)
        
        query += ' ORDER BY upload_date DESC'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def deactivate_document(self, document_id: int, university_id: int) -> bool:
        """Disattiva un documento (soft delete)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE uploaded_documents 
            SET is_active = 0 
            WHERE id = ? AND university_id = ?
        ''', (document_id, university_id))
        
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected > 0
    
    def get_all_active_calls(self) -> list:
        """Recupera tutti i bandi attivi (per gli studenti)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                d.*,
                u.university_name,
                u.institutional_email
            FROM uploaded_documents d
            JOIN universities u ON d.university_id = u.id
            WHERE d.document_type = 'erasmus_call' 
            AND d.is_active = 1
            ORDER BY d.upload_date DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]

    # ----------------------
    # Utility di amministrazione
    # ----------------------
    def list_universities(self) -> list:
        """Ritorna l'elenco delle università (id, university_name, institutional_email)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, university_name, institutional_email FROM universities ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def update_university_name(self, current_name: str, new_name: str) -> bool:
        """Rinomina un'università cercando per nome corrente. Restituisce True se aggiornata."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE universities SET university_name = ? WHERE LOWER(university_name) = LOWER(?)",
                (new_name, current_name)
            )
            affected = cursor.rowcount
            conn.commit()
            return affected > 0
        except sqlite3.IntegrityError as e:
            # Probabilmente violazione UNIQUE sul nuovo nome
            print(f"Errore rinomina università: {e}")
            return False
        finally:
            conn.close()

    def update_university_name_by_id(self, university_id: int, new_name: str) -> bool:
        """Rinomina un'università per ID. Restituisce True se aggiornata."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE universities SET university_name = ? WHERE id = ?",
                (new_name, university_id)
            )
            affected = cursor.rowcount
            conn.commit()
            return affected > 0
        except sqlite3.IntegrityError as e:
            print(f"Errore rinomina università (by id): {e}")
            return False
        finally:
            conn.close()


# Istanza singleton del database
db_manager = DatabaseManager()
