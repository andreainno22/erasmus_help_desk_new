# app/services/rag_service.py
import os
import json
import google.generativeai as genai
import fitz  # PyMuPDF
import pdfplumber
import re
import markdown
from pathlib import Path

from .vector_db_service import get_retriever
from ..core.config import settings

def clean_and_parse_json_response(response_text: str, expected_type: str = "array") -> any:
    """
    Utility per pulire e parsare le risposte JSON dai modelli AI.
    
    Args:
        response_text: Il testo della risposta dal modello
        expected_type: "array" o "object" per validare il tipo di ritorno
        
    Returns:
        Il JSON parsato o None se il parsing fallisce
        
    Raises:
        ValueError: Se il JSON non è valido o non corrisponde al tipo atteso
    """
    if not response_text or not response_text.strip():
        raise ValueError("Risposta vuota dal modello AI")
    
    # Pulisci il testo della risposta
    cleaned_text = response_text.strip()
    
    # Rimuovi eventuali backticks e marcatori di codice
    if cleaned_text.startswith('```json'):
        cleaned_text = cleaned_text[7:]
    elif cleaned_text.startswith('```'):
        cleaned_text = cleaned_text[3:]
    
    if cleaned_text.endswith('```'):
        cleaned_text = cleaned_text[:-3]
    
    cleaned_text = cleaned_text.strip()
    
    # Prova prima a parsare il testo completo se inizia già con [ o {
    if expected_type == "array" and cleaned_text.startswith('['):
        try:
            parsed_data = json.loads(cleaned_text)
            if isinstance(parsed_data, list):
                print(f"✅ JSON array parsato direttamente: {len(parsed_data)} elementi")
                return parsed_data
        except json.JSONDecodeError:
            pass  # Continua con il metodo regex
    elif expected_type == "object" and cleaned_text.startswith('{'):
        try:
            parsed_data = json.loads(cleaned_text)
            if isinstance(parsed_data, dict):
                print(f"✅ JSON object parsato direttamente")
                return parsed_data
        except json.JSONDecodeError:
            pass  # Continua con il metodo regex
    
    # Cerca il pattern JSON appropriato
    if expected_type == "array":
        json_match = re.search(r'\[.*\]', cleaned_text, re.DOTALL)
    else:
        json_match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
    
    if not json_match:
        raise ValueError(f"Nessun JSON {expected_type} trovato nella risposta: {cleaned_text[:200]}...")
    
    try:
        parsed_data = json.loads(json_match.group(0))
        
        # Valida il tipo
        if expected_type == "array" and not isinstance(parsed_data, list):
            raise ValueError(f"JSON parsato non è un array: {type(parsed_data)}")
        elif expected_type == "object" and not isinstance(parsed_data, dict):
            raise ValueError(f"JSON parsato non è un oggetto: {type(parsed_data)}")
        
        print(f"✅ JSON {expected_type} parsato con regex: {len(parsed_data) if isinstance(parsed_data, list) else 'N/A'} elementi")
        return parsed_data
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Errore nel parsing JSON: {e}. Testo: {json_match.group(0)[:200]}...")

def markdown_to_html(text: str) -> str:
    """
    Converte testo in formato Markdown in HTML.
    Utile per rendere correttamente le risposte formattate di Gemini nel frontend.
    
    Args:
        text: Testo in formato Markdown
        
    Returns:
        HTML formattato
    """
    if not text:
        return ""
    
    # Converti Markdown in HTML
    html = markdown.markdown(
        text,
        extensions=[
            'nl2br',      # Converte \n in <br>
            'fenced_code', # Supporto per code blocks con ```
            'tables',     # Supporto per tabelle
        ]
    )
    
    return html

def extract_department_section(full_text: str, department: str) -> str:
    """
    Estrae la sezione del/i dipartimento/i dal testo completo delle destinazioni.

    - Supporta input che può contenere più "Dipartimento di ..." concatenati
    - Non richiede più la presenza di "n° borse" vicino all'header
    - È più tollerante a spazi, maiuscole/minuscole e punteggiatura

    Args:
        full_text: Testo completo delle destinazioni (con newline preservati)
        department: Testo selezionato dall'utente (anche con più dipartimenti)

    Returns:
        La sezione di testo relativa al primo dipartimento trovato (header → header successivo)

    Raises:
        ValueError: Se nessun dipartimento dell'input viene trovato
    """
    # Prepara le righe e una versione normalizzata per i confronti
    lines = full_text.split('\n')
    def normalize(s: str) -> str:
        s = s.lower().replace('\u2019', "'")
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    lines_norm = [normalize(l) for l in lines]

    # Individua tutti gli header di dipartimento nel documento
    header_regex = re.compile(r'\bdipartiment[oi]\b', re.IGNORECASE)
    header_indexes = [i for i, l in enumerate(lines) if header_regex.search(l or '')]

    if not header_indexes:
        raise ValueError("Nel file non sono presenti header di dipartimento riconoscibili")

    # L'input può contenere più dipartimenti concatenati: splitta per tentare ogni candidato
    raw = normalize(department)
    # Spezza ogni volta che ricompare "dipartimento ..."
    parts = re.split(r'(?=\bdipartiment[oi]\s+)', raw, flags=re.IGNORECASE)
    # Pulisci i prefissi "dipartimento (di)"
    def strip_prefix(p: str) -> str:
        p = re.sub(r'^dipartiment[oi]\s+di\s+', '', p.strip(), flags=re.IGNORECASE)
        p = re.sub(r'^dipartiment[oi]\s+', '', p, flags=re.IGNORECASE)
        return p.strip()

    candidates = [strip_prefix(p) for p in parts if p.strip()]
    # Rimuovi duplicati mantenendo l'ordine
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    # Funzione di match: substring oppure match di parole principali
    def find_start_index(search_core: str) -> int | None:
        if not search_core:
            return None
        # Approccio 1: substring diretto
        for idx in header_indexes:
            if search_core in lines_norm[idx]:
                return idx
        # Approccio 2: tutte le parole significative presenti
        tokens = [t for t in re.split(r'\W+', search_core) if len(t) >= 3]
        for idx in header_indexes:
            line = lines_norm[idx]
            if all(tok in line for tok in tokens[: min(3, len(tokens))]):
                return idx
        return None

    # Tenta i candidati in ordine; alla prima sezione valida, restituisci
    for cand in candidates:
        search_core = normalize(cand)
        start_idx = find_start_index(search_core)
        if start_idx is None:
            continue

        # Trova il prossimo header successivo come fine sezione
        next_headers = [i for i in header_indexes if i > start_idx]
        end_idx = next_headers[0] if next_headers else len(lines)

        section = '\n'.join(lines[start_idx:end_idx]).strip()
        if section:
            print(f"✅ Header dipartimento trovato: '{lines[start_idx].strip()[:120]}' (linea {start_idx})")
            print(f"✅ Estratta sezione per '{cand}': {len(section)} caratteri")
            return section

    # Se arrivi qui, nessun candidato è stato trovato
    raise ValueError(f"Dipartimento '{department}' non trovato nel file delle destinazioni")

# --- CONFIGURAZIONE DI GOOGLE AI ---
# Questa parte viene eseguita una sola volta quando il servizio viene importato.
# Configura la libreria con la chiave API caricata da .env
try:
    if not settings.GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY non è impostato nel file .env o non è stato caricato.")
    genai.configure(api_key=settings.GOOGLE_API_KEY)
except Exception as e:
    print(f"ATTENZIONE: Errore durante la configurazione di Google AI: {e}")
    pass

async def get_call_summary(university_name: str) -> dict:
    """
    Identifica il bando dal database, recupera i dati e genera un riassunto
    utilizzando il Google AI Python SDK (genai).
    """
    try:
        from ..core.database import db_manager
        
        # --- 1. RECUPERA IL BANDO DAL DATABASE ---
        active_calls = db_manager.get_all_active_calls()
        
        # Cerca il bando per l'università specificata
        target_call = None
        for call in active_calls:
            if call.get('university_name', '').lower() == university_name.lower():
                target_call = call
                break
        
        if not target_call:
            return {"has_program": False, "summary": f"Nessun bando trovato per '{university_name}'."}
        
        target_filename = target_call.get('stored_filename')
        file_path = target_call.get('file_path')

        # --- 2. ESTRAI IL TESTO DAL PDF ---
        if not os.path.exists(file_path):
            return {"has_program": False, "summary": f"File del bando non trovato: {file_path}"}
        
        # Estrai tutto il testo dal PDF
        call_text = extract_text_from_pdf(file_path)
        
        # --- 3. RECUPERA I CHUNK SOLO DA QUEL FILE (se il vector DB è configurato) ---
        # Prova a usare il vector DB, altrimenti usa il testo completo
        try:
            K_VALUE = 5
            retriever = get_retriever(settings.DB_PATH, category='calls', top_k=K_VALUE)
            retriever.search_kwargs = {'filter': {'source': target_filename}}
            query = "riassunto completo del bando erasmus: requisiti, scadenze e procedura"
            docs = retriever.get_relevant_documents(query)
        except Exception as e:
            print(f"⚠️ Vector DB non disponibile, uso testo completo: {e}")
            docs = None
        
        # --- 4. PREPARA IL CONTESTO PER GEMINI ---
        if docs and len(docs) > 0:
            # Usa i chunk dal vector DB se disponibili
            full_context = "\n\n---\n\n".join([doc.page_content for doc in docs])
        else:
            # Altrimenti usa il testo completo (troncato se troppo lungo)
            max_chars = 30000  # Limite per evitare token overflow
            full_context = call_text[:max_chars]
            if len(call_text) > max_chars:
                full_context += "\n\n[... testo troncato ...]"
        
        template = f"""
        Sei un assistente specializzato in programmi Erasmus. 
        Analizza il seguente testo estratto da un bando Erasmus e creane un riassunto conciso 
        evidenziando:
        - Periodo di apertura del bando
        - Requisiti principali (inclusi i requisiti linguistici)
        - Scadenze importanti
        - Processo di candidatura
        - Se presente, il numero di CFU (crediti formativi universitari) minimi che lo studente deve guadagnare durante l'erasmus
        
        Contesto estratto dal bando:
        {full_context}
        """

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = await model.generate_content_async(template)
        summary_text = response.text

        # Costruisci un link pubblico al PDF del bando per gli studenti
        call_pdf_url = f"/api/students/files/calls/{target_filename}"

        # Converti il Markdown in HTML per una corretta renderizzazione nel frontend
        summary_html = markdown_to_html(summary_text)

        # Aggiungi SEMPRE il link al sito/bando (PDF)
        link_html = f'<p><strong>Link al bando:</strong> <a href="{call_pdf_url}" target="_blank" rel="noopener">apri il PDF ufficiale</a></p>'
        summary_with_link = summary_html + link_html

        return {"has_program": True, "summary": summary_with_link}
        
    except Exception as e:
        print(f"Errore in get_call_summary: {e}")
        raise e

async def get_available_departments(home_university: str) -> list[str]:
    """
    Estrae tutti i dipartimenti disponibili dal file delle destinazioni dell'università nel database.
    Il PDF viene processato in memoria senza salvare file temporanei.
    
    Args:
        home_university: Nome dell'università di origine
        
    Returns:
        Lista dei nomi dei dipartimenti disponibili
        
    Raises:
        FileNotFoundError: Se il file delle destinazioni non esiste
        ValueError: Se non è possibile estrarre i dipartimenti
    """
    try:
        from ..core.database import db_manager
        
        # --- 1. RECUPERA IL FILE DELLE DESTINAZIONI DAL DATABASE ---
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM universities WHERE university_name = ?', (home_university,))
        uni_row = cursor.fetchone()
        conn.close()
        
        if not uni_row:
            raise FileNotFoundError(f"Università '{home_university}' non trovata nel database")
        
        university_id = uni_row['id']
        
        # Recupera il documento delle destinazioni
        destinations_docs = db_manager.get_university_documents(university_id, document_type='destinazioni')
        
        if not destinations_docs:
            raise FileNotFoundError(f"Nessun file di destinazioni trovato per '{home_university}'")
        
        # Prendi il più recente
        dest_doc = destinations_docs[0]
        pdf_path = dest_doc.get('file_path')

        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Il file delle destinazioni non è stato trovato: {pdf_path}")

        # --- 2. ESTRAI IL TESTO DAL PDF (IN MEMORIA) ---
        full_text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # Estrai tabelle strutturate
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        cleaned_row = [
                            cell.replace('\n', ' ').strip() if cell is not None else "" 
                            for cell in row
                        ]
                        line = " | ".join(cleaned_row)
                        full_text += line + "\n"
                
                # Estrai anche testo normale (non in tabelle)
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
        
        if not full_text.strip():
            raise ValueError("Il PDF è vuoto o non è stato possibile estrarre il testo.")

        # Non comprimere tutto: mantieni le linee separate
        print(f"✅ Testo estratto dal database ({len(full_text)} caratteri)")

        # --- 3. ESTRAI I DIPARTIMENTI CON REGEX ---
        # Prima rimuovi tutta la colonna "note per gli studenti" dal testo
        # Cerca tutte le occorrenze dopo "note per gli studenti" fino alla fine della riga o tabella
        text_without_notes = re.sub(
            r'(note per gli studenti|note per lo studente).*?(?=\n|$)', 
            '', 
            full_text, 
            flags=re.IGNORECASE
        )
        
        # Dividi il testo in linee
        lines = text_without_notes.split('\n')
        
        # Usa un set per eliminare automaticamente i duplicati
        departments_set = set()
        
        for line in lines:
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            # Cerca solo le linee che INIZIANO con "dipartimento" o "dipartimenti"
            if line_lower.startswith('dipartiment'):
                # Estrai solo la parte prima di "n° borse" o "n°borse" o "|"
                if 'n°' in line_lower or 'n °' in line_lower:
                    # Prendi tutto prima di "n°"
                    dept_line = re.split(r'n\s*°', line_stripped, flags=re.IGNORECASE)[0]
                elif '|' in line_stripped:
                    # Se c'è un pipe, prendi solo la prima parte
                    dept_line = line_stripped.split('|')[0]
                else:
                    dept_line = line_stripped
                
                # Pulisci la linea: rimuovi caratteri non alfanumerici (tranne spazi e apostrofi)
                dept_line = re.sub(r"[^a-zA-Z0-9\s'àèéìòùÀÈÉÌÒÙ]", '', dept_line)
                # Rimuovi spazi multipli
                dept_line = re.sub(r'\s+', ' ', dept_line).strip()
                
                # Aggiungi solo se ha senso (almeno 10 caratteri per evitare frammenti)
                if dept_line and len(dept_line) >= 10:
                    departments_set.add(dept_line)
        
        if not departments_set:
            raise ValueError("Nessun dipartimento trovato nel file delle destinazioni")
        
        # Converti il set in lista ordinata
        departments = sorted(list(departments_set))
        print(f"✅ Trovati {len(departments)} dipartimenti: {departments}")
        return departments
        
    except FileNotFoundError as e:
        print(f"Errore file in get_available_departments: {e}")
        raise e
    except Exception as e:
        print(f"Errore generico in get_available_departments: {e}")
        raise e

def get_erasmus_suggestions(course: str, preferences: str) -> list:
    """
    Orchestra il processo RAG per generare i suggerimenti.
    """
    # 1. Recupero (Retrieval)
    retriever = get_retriever(settings.DB_PATH, category='calls')
    
    # 2. Prompt
    context_docs = retriever.get_relevant_documents(f"Corso: {course}, Preferenze: {preferences}")
    context = "\n\n---\n\n".join([doc.page_content for doc in context_docs])

    template = f"""
    Sei un assistente esperto per studenti che devono scegliere una meta Erasmus.
    Il tuo compito è analizzare le preferenze dello studente e le informazioni estratte dai documenti per creare una classifica personalizzata delle 3 migliori destinazioni.
    Per ogni destinazione, fornisci: nome università, città, corsi consigliati, una motivazione chiara e un punteggio di affinità da 1 a 100.
    Basati ESCLUSIVAMENTE sul contesto fornito. Non inventare informazioni. Restituisci il risultato in formato JSON.

    --- CONTESTO RECUPERATO DAI DOCUMENTI ---
    {context}
    
    --- RICHIESTA DELLO STUDENTE ---
    Corso di studio: {course}
    Preferenze: {preferences}
    
    --- OUTPUT RICHIESTO (FORMATO JSON) ---
    """
    
    # 3. Generazione (Generation)
    model = genai.GenerativeModel("gemini-2.0-flash")
    #response = model.generate_content(template)
    response = "test"
    
    try:
        # Se la risposta è ancora "test", restituisci un array vuoto
        if response == "test":
            print("⚠️ Risposta di test rilevata, restituisco array vuoto")
            return []
            
        # Prova a parsare come JSON
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"❌ Errore nel parsing JSON in get_erasmus_suggestions: {e}")
        print(f"❌ Risposta ricevuta: {response if isinstance(response, str) else getattr(response, 'text', 'N/A')[:200]}...")
        return []

def get_available_universities() -> list[str]:
    """
    Recupera la lista delle università che hanno caricato bandi attivi dal database.
    """
    from ..core.database import db_manager
    
    try:
        # Recupera tutti i bandi attivi
        active_calls = db_manager.get_all_active_calls()
        
        # Estrae i nomi delle università dai bandi
        universities = []
        for call in active_calls:
            uni_name = call.get('university_name')
            if uni_name and uni_name not in universities:
                universities.append(uni_name)
        
        return sorted(universities)
    except Exception as e:
        print(f"Errore nel recupero delle università dal database: {e}")
        return []

async def analyze_destinations_for_department(home_university: str, department: str, period: str) -> list:
    """
    Analizza il PDF delle destinazioni per un'università specifica dal database:
    1. Recupera il file dal database
    2. Estrae il testo con pdfplumber (IN MEMORIA)
    3. Estrae solo la sezione del dipartimento specificato
    4. Usa Gemini per analizzare solo quella sezione e trovare le destinazioni
    """
    try:
        from ..core.database import db_manager
        
        # --- 1. RECUPERA IL FILE DELLE DESTINAZIONI DAL DATABASE ---
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM universities WHERE university_name = ?', (home_university,))
        uni_row = cursor.fetchone()
        conn.close()
        
        if not uni_row:
            raise FileNotFoundError(f"Università '{home_university}' non trovata nel database")
        
        university_id = uni_row['id']
        
        # Recupera il documento delle destinazioni
        destinations_docs = db_manager.get_university_documents(university_id, document_type='destinazioni')
        
        if not destinations_docs:
            raise FileNotFoundError(f"Nessun file di destinazioni trovato per '{home_university}'")
        
        # Prendi il più recente
        dest_doc = destinations_docs[0]
        pdf_path = dest_doc.get('file_path')

        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Il file delle destinazioni non è stato trovato: {pdf_path}")

        # --- 2. ESTRAI IL TESTO DAL PDF (IN MEMORIA) ---
        full_text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # Estrai tabelle strutturate
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        cleaned_row = [
                            cell.replace('\n', ' ').strip() if cell is not None else "" 
                            for cell in row
                        ]
                        line = " | ".join(cleaned_row)
                        full_text += line + "\n"

                # Estrai anche testo normale (non in tabelle)
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"

        if not full_text.strip():
            raise ValueError("Il PDF è vuoto o non è stato possibile estrarre il testo.")

        # Pulisci il testo mantenendo la struttura a righe per l'estrazione del dipartimento
        llm_ready_text = "\n".join(line.strip() for line in full_text.splitlines()).strip()
        print(f"✅ Testo estratto dal database ({len(llm_ready_text)} caratteri)")

        # --- 3. ESTRAI SOLO LA SEZIONE DEL DIPARTIMENTO SPECIFICO ---
        try:
            department_section = extract_department_section(llm_ready_text, department)
            print(f"📋 Sezione del dipartimento estratta: {len(department_section)} caratteri")
        except ValueError as e:
            print(f"❌ Errore nell'estrazione della sezione del dipartimento: {e}")
            raise e

        # --- 4. GENERA L'ANALISI CON GEMINI USANDO SOLO LA SEZIONE SPECIFICA ---
        template = f"""
        Sei un assistente universitario esperto nell'analisi di bandi Erasmus.
        Il tuo compito è analizzare la sezione specifica del dipartimento "{department}" fornita di seguito.
        Considera il periodo "{period}" per filtrare le destinazioni. Se non ci sono info sul periodo ignoralo.
        
        Estrai TUTTE le università partner elencate nella sezione, mantenendo ESATTAMENTE i campi come sono scritti nel file originale.

        Per ogni università partner trovata, crea un oggetto JSON con i seguenti campi:
        - "name": il nome dell'università estratto dal campo "NOME ISTITUZIONE"
        - "codice_europeo": valore del campo "CODICE EUROPEO"
        - "nome_istituzione": valore del campo "NOME ISTITUZIONE"
        - "codice_area": valore del campo "CODICE AREA"
        - "posti": valore del campo "POSTI"
        - "durata_per_posto": valore del campo "DURATA PER POSTO"
        - "livello": valore del campo "LIVELLO"
        - "dettagli_livello": valore del campo "DETTAGLI LIVELLO"
        - "requisiti_linguistici": valore del campo "REQUISITI LINGUISTICI"
        - "description": una breve descrizione accattivante di 1-2 frasi sull'università

        IMPORTANTE: 
        - Restituisci ESCLUSIVAMENTE un array JSON valido
        - Non aggiungere testo, spiegazioni o commenti prima o dopo l'array
        - Se un campo è vuoto nel file, inserisci una stringa vuota "" o null
        - Se non trovi destinazioni per il dipartimento, restituisci un array vuoto: []
        - Assicurati che il JSON sia sintatticamente corretto
        - Mantieni i valori dei campi esattamente come appaiono nel file
        - I campi devono corrispondere esattamente a quelli del file: CODICE EUROPEO | NOME ISTITUZIONE | CODICE AREA | DESCRIZIONE AREA ISCED | POSTI | DURATA PER POSTO | LIVELLO | DETTAGLI LIVELLO | REQUISITI LINGUISTICI | BLENDED | SHORT MOBILITY | BIP | CIRCLE U | SOTTO CONDIZIONE | NOTE PER GLI STUDENTI

        Esempio di formato richiesto:
        [
          {{
            "name": "UNIVERSIDAD DE BARCELONA",
            "codice_europeo": "E BARCELO01",
            "nome_istituzione": "UNIVERSIDAD DE BARCELONA",
            "codice_area": "0732",
            "posti": "2",
            "durata_per_posto": "5",
            "livello": "U",
            "dettagli_livello": "",
            "requisiti_linguistici": "Spanish B2",
            "description": "Prestigiosa università catalana con forti programmi in ingegneria civile."
          }}
        ]

        --- SEZIONE DEL DIPARTIMENTO "{department}" ---
        {department_section}
        """

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = await model.generate_content_async(template)
        
        print(f"🔍 Risposta di Gemini (primi 500 caratteri): {response.text[:500]}")
        
        try:
            destinations_data = clean_and_parse_json_response(response.text, "array")
            print(f"✅ Trovate {len(destinations_data)} destinazioni per {department}")
            return destinations_data
        except ValueError as e:
            print(f"❌ Errore nel parsing della risposta di Gemini: {e}")
            raise e

    except FileNotFoundError as e:
        print(f"Errore file in analyze_destinations: {e}")
        raise e
    except Exception as e:
        print(f"Errore generico in analyze_destinations: {e}")
        raise e

async def analyze_exams_compatibility(destination_university_name: str, student_study_plan_text: str, period: str = None) -> dict:
    """
    Analizza la compatibilità degli esami tra il piano di studi dello studente 
    e gli esami disponibili presso l'università di destinazione (dal database).
    
    Args:
        destination_university_name: Nome dell'università di destinazione
        student_study_plan_text: Testo del piano di studi dello studente (estratto dal PDF)
        period: Periodo Erasmus selezionato (fall/spring) - opzionale
        
    Returns:
        Dizionario con:
        - matched_exams: Lista degli esami con corrispondenze
        - suggested_exams: Lista degli esami suggeriti
        - compatibility_score: Punteggio di compatibilità 0-100
        - analysis_summary: Riassunto dell'analisi
        - exams_pdf_url: URL per scaricare il PDF completo
        - exams_pdf_filename: Nome del file PDF
        
    Raises:
        FileNotFoundError: Se il file degli esami dell'università non esiste
        ValueError: Se non è possibile analizzare la compatibilità
    """
    try:
        from ..core.database import db_manager
        
        # --- 1. CERCA IL FILE PDF DEGLI ESAMI NEL DATABASE ---
        # Cerca l'università nel database
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        # Cerca per nome esatto o parziale
        cursor.execute('''
            SELECT d.* 
            FROM uploaded_documents d
            JOIN universities u ON d.university_id = u.id
            WHERE d.document_type = 'erasmus_courses' 
            AND d.is_active = 1
            AND (
                LOWER(u.university_name) = LOWER(?)
                OR LOWER(u.university_name) LIKE LOWER(?)
                OR LOWER(?) LIKE '%' || LOWER(u.university_name) || '%'
            )
            ORDER BY d.upload_date DESC
            LIMIT 1
        ''', (destination_university_name, f'%{destination_university_name}%', destination_university_name))
        
        course_doc = cursor.fetchone()
        conn.close()
        
        if not course_doc:
            raise FileNotFoundError(f"Nessun file di esami trovato per '{destination_university_name}' nel database")
        
        course_doc = dict(course_doc)
        target_filename = course_doc.get('stored_filename')
        exam_pdf_path = course_doc.get('file_path')
        
        if not os.path.exists(exam_pdf_path):
            raise FileNotFoundError(f"File degli esami non trovato: {exam_pdf_path}")
        
        # --- 2. ESTRAI IL TESTO DAL PDF DEGLI ESAMI ---
        exam_text = extract_text_from_pdf(exam_pdf_path)

        print(f"✅ Estratto testo da {target_filename} ({len(exam_text)} caratteri)")
        print(f"🎓 Piano di studi studente ({len(student_study_plan_text)} caratteri)")
        
        # Prepara l'informazione sul periodo per il prompt
        period_info = ""
        if period:
            period_name = "autunnale (Fall)" if period.lower() == "fall" else "primaverile (Spring)"
            period_info = f"\n\n**PERIODO ERASMUS SELEZIONATO:** {period_name}\n"

        # --- 3. ANALIZZA LA COMPATIBILITÀ CON GEMINI ---
        template = f"""
        Sei un esperto consulente universitario specializzato in programmi Erasmus.
        Il tuo compito è analizzare la compatibilità tra il piano di studi di uno studente 
        e gli esami disponibili presso un'università di destinazione Erasmus.

        **PIANO DI STUDI DELLO STUDENTE:**
        {student_study_plan_text}

        **ESAMI DISPONIBILI PRESSO L'UNIVERSITÀ DI DESTINAZIONE ({destination_university_name}):**
        {exam_text}
        {period_info}
        **ISTRUZIONI:**
        1. Analizza il piano di studi dello studente per identificare gli esami
        2. Trova corrispondenze tra esami dello studente e corsi dell'università di destinazione
        3. Suggerisci esami aggiuntivi interessanti per il profilo dello studente
        4. Calcola un punteggio di compatibilità complessivo (0-100)
        5. Fornisci un riassunto dell'analisi
        {"6. IMPORTANTE: Indica nel campo 'notes' degli esami se il corso è disponibile nel periodo selezionato dallo studente. Se il PDF degli esami specifica i periodi (Fall/Spring, Semester 1/2, ecc.), usa queste informazioni per segnalare la compatibilità temporale." if period else ""}

        **FORMATO DI RISPOSTA RICHIESTO (JSON):**
        {{
            "matched_exams": [
                {{
                    "student_exam": "Nome esame dello studente",
                    "destination_course": "Nome corso di destinazione corrispondente",
                    "compatibility": "alta",
                    "credits_student": "6 CFU",
                    "credits_destination": "6 ECTS",
                    "notes": "Descrizione della corrispondenza{' + indicazione del periodo se disponibile nel PDF (es: Disponibile in Fall Semester)' if period else ''}"
                }}
            ],
            "suggested_exams": [
                {{
                    "course_name": "Nome corso suggerito",
                    "credits": "6 ECTS",
                    "reason": "Motivo del suggerimento{' + periodo se disponibile' if period else ''}",
                    "category": "Computer Science"
                }}
            ],
            "compatibility_score": 85.0,
            "analysis_summary": "Riassunto dettagliato dell'analisi di compatibilità...{' Menziona quanti degli esami trovati sono disponibili nel periodo selezionato.' if period else ''}"
        }}

        IMPORTANTE: 
        - Restituisci SOLO il JSON, senza testo aggiuntivo prima o dopo
        - Se non trovi corrispondenze, lascia gli array vuoti ma mantieni la struttura
        - Il punteggio deve essere un numero tra 0 e 100
        {f"- Dai priorità agli esami disponibili nel periodo {period_name} selezionato dallo studente" if period else ""}
        {f"- Nel riassunto finale, specifica esplicitamente quanti esami sono compatibili con il periodo {period_name}" if period else ""}
        """

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = await model.generate_content_async(template)
        
        print(f"🔍 Risposta di Gemini per analisi esami (primi 500 caratteri): {response.text[:500]}")
        
        try:
            analysis_result = clean_and_parse_json_response(response.text, "object")
            print(f"✅ Analisi completata: {len(analysis_result.get('matched_exams', []))} corrispondenze, score: {analysis_result.get('compatibility_score', 0)}")
            
            # Aggiungi le informazioni del PDF al risultato
            analysis_result["exams_pdf_url"] = f"/api/students/files/exams/{target_filename}"
            analysis_result["exams_pdf_filename"] = target_filename
            
            return analysis_result
            
        except ValueError as e:
            print(f"❌ Errore nel parsing della risposta di Gemini: {e}")
            # Restituisce una risposta di fallback
            return {
                "matched_exams": [],
                "suggested_exams": [],
                "compatibility_score": 0.0,
                "analysis_summary": f"Errore nell'analisi automatica. Si prega di consultare manualmente il PDF dei corsi disponibili.",
                "exams_pdf_url": f"/api/students/files/exams/{target_filename}",
                "exams_pdf_filename": target_filename
            }
            
    except FileNotFoundError as e:
        print(f"Errore file in analyze_exams_compatibility: {e}")
        raise e
    except Exception as e:
        print(f"Errore generico in analyze_exams_compatibility: {e}")
        raise e
        raise e

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Utility per estrarre testo da un file PDF.
    
    Args:
        pdf_path: Percorso al file PDF
        
    Returns:
        Testo estratto dal PDF
        
    Raises:
        ValueError: Se il PDF è vuoto o non leggibile
    """
    try:
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        if not text.strip():
            raise ValueError(f"Il PDF '{pdf_path}' è vuoto o non è stato possibile estrarre il testo.")
            
        return text.strip()
        
    except Exception as e:
        raise ValueError(f"Errore nell'estrazione del testo dal PDF '{pdf_path}': {e}")