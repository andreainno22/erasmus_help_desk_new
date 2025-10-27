# app/api/endpoints/endpoints_university.py
import os
import shutil
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse
from typing import Optional

from ...schemas.university import (
    UniversityRegisterRequest,
    UniversityLoginRequest,
    UniversityLoginResponse,
    UniversityProfileResponse,
    DocumentUploadResponse,
    UniversityDocumentsResponse,
    ActiveCallsListResponse,
    ActiveCallInfo,
    DocumentInfo
)
from ...core.database import db_manager
from ...core.auth import create_access_token, get_current_university

router = APIRouter()


@router.post("/register", status_code=201)
async def register_university(request: UniversityRegisterRequest):
    """
    Registra una nuova università al portale.
    Richiede email istituzionale e password sicura.
    """
    try:
        # Verifica che l'email sia istituzionale (semplice check)
        email_domain = request.institutional_email.split('@')[1]
        if not any(edu_suffix in email_domain.lower() for edu_suffix in ['.edu', '.ac.', 'uni', '.it']):
            # Controllo più permissivo - accetta qualsiasi dominio ma avvisa
            print(f"⚠️ Email potenzialmente non istituzionale: {request.institutional_email}")
        
        # Crea l'università nel database
        university_id = db_manager.create_university(
            university_name=request.university_name,
            institutional_email=request.institutional_email,
            password=request.password,
            contact_person=request.contact_person,
            phone=request.phone
        )
        
        if not university_id:
            raise HTTPException(
                status_code=400,
                detail="Università o email già registrata nel sistema"
            )
        
        return {
            "message": "Università registrata con successo",
            "university_id": university_id,
            "university_name": request.university_name,
            "note": "Controlla la tua email per verificare l'account (funzionalità da implementare)"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nella registrazione: {e}")
        raise HTTPException(status_code=500, detail=f"Errore durante la registrazione: {str(e)}")


@router.post("/login", response_model=UniversityLoginResponse)
async def login_university(request: UniversityLoginRequest):
    """
    Effettua il login di un'università.
    Restituisce un token JWT per l'autenticazione delle richieste successive.
    """
    try:
        # Recupera l'università dal database
        university = db_manager.get_university_by_email(request.institutional_email)
        
        if not university:
            raise HTTPException(
                status_code=401,
                detail="Email o password non corretti"
            )
        
        # Verifica la password
        if not db_manager.verify_password(request.password, university['password_hash']):
            raise HTTPException(
                status_code=401,
                detail="Email o password non corretti"
            )
        
        # Aggiorna timestamp ultimo login
        db_manager.update_last_login(university['id'])
        
        # Crea il token JWT
        token_data = {
            "university_id": university['id'],
            "email": university['institutional_email'],
            "university_name": university['university_name']
        }
        access_token = create_access_token(data=token_data)
        
        return UniversityLoginResponse(
            access_token=access_token,
            token_type="bearer",
            university_id=university['id'],
            university_name=university['university_name'],
            email=university['institutional_email']
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nel login: {e}")
        raise HTTPException(status_code=500, detail=f"Errore durante il login: {str(e)}")


@router.get("/profile", response_model=UniversityProfileResponse)
async def get_profile(current_university: dict = Depends(get_current_university)):
    """
    Recupera il profilo dell'università autenticata.
    Richiede autenticazione tramite token JWT.
    """
    try:
        university = db_manager.get_university_by_id(current_university['university_id'])
        
        if not university:
            raise HTTPException(status_code=404, detail="Università non trovata")
        
        return UniversityProfileResponse(
            id=university['id'],
            university_name=university['university_name'],
            institutional_email=university['institutional_email'],
            contact_person=university['contact_person'],
            phone=university['phone'],
            is_verified=bool(university['is_verified']),
            created_at=university['created_at'],
            last_login=university['last_login']
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nel recupero profilo: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/erasmus-call", response_model=DocumentUploadResponse)
async def upload_erasmus_call(
    file: UploadFile = File(..., description="PDF del bando Erasmus"),
    academic_year: Optional[str] = Form(None, description="Anno accademico (es. 2024-2025)"),
    current_university: dict = Depends(get_current_university)
):
    """
    Carica il PDF del bando Erasmus per l'università autenticata.
    Il file viene salvato nella cartella data/calls/.
    """
    try:
        # Verifica che il file sia un PDF
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail="Solo file PDF sono accettati"
            )
        
        # Crea la cartella di destinazione se non esiste
        upload_dir = Path(__file__).parent.parent.parent.parent / "data" / "calls"
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Genera un nome file univoco
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        university_slug = current_university['university_name'].lower().replace(' ', '_').replace('-', '_')
        stored_filename = f"{university_slug}_erasmus_call_{timestamp}.pdf"
        file_path = upload_dir / stored_filename
        
        # Salva il file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Registra il documento nel database
        doc_id = db_manager.add_document(
            university_id=current_university['university_id'],
            document_type='erasmus_call',
            original_filename=file.filename,
            stored_filename=stored_filename,
            file_path=str(file_path),
            academic_year=academic_year
        )
        
        if not doc_id:
            # Rimuovi il file se il salvataggio nel DB fallisce
            os.unlink(file_path)
            raise HTTPException(
                status_code=500,
                detail="Errore nel salvataggio delle informazioni del documento"
            )
        
        # INDEXING NEL VECTOR STORE - Solo per i bandi!
        try:
            from ...services.document_service import process_calls
            from ...services.vector_db_service import create_vector_store
            
            print(f"📚 Inizio indicizzazione del bando nel vector store...")
            
            # Processa solo il file appena caricato
            from langchain.document_loaders import PyPDFLoader
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            
            loader = PyPDFLoader(str(file_path))
            pages = loader.load()
            
            # Aggiungi metadata
            for page in pages:
                page.metadata["source"] = stored_filename
                page.metadata["university"] = current_university['university_name']
            
            # Dividi in chunks
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200,
            )
            chunks = text_splitter.split_documents(pages)
            
            # Crea/aggiorna vector store
            create_vector_store(chunks, category='calls')
            
            print(f"✅ Indicizzati {len(chunks)} chunks nel vector store")
        except Exception as e:
            print(f"⚠️ Errore nell'indicizzazione (il documento è comunque salvato): {e}")
            # Non blocchiamo l'upload se l'indicizzazione fallisce
        
        return DocumentUploadResponse(
            document_id=doc_id,
            message="Bando Erasmus caricato con successo",
            filename=stored_filename,
            upload_date=datetime.now().isoformat()
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nell'upload del bando: {e}")
        raise HTTPException(status_code=500, detail=f"Errore durante l'upload: {str(e)}")


@router.post("/upload/destinazioni", response_model=DocumentUploadResponse)
async def upload_destinations(
    file: UploadFile = File(..., description="PDF con le destinazioni Erasmus"),
    academic_year: Optional[str] = Form(None, description="Anno accademico (opzionale)"),
    current_university: dict = Depends(get_current_university)
):
    """Carica un PDF contenente le destinazioni. Il file viene salvato in data/destinazioni
    e, su richiesta, può essere processato.
    """
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Solo file PDF sono accettati")

        upload_dir = Path(__file__).parent.parent.parent.parent / "data" / "destinazioni"
        upload_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        university_slug = current_university['university_name'].lower().replace(' ', '_').replace('-', '_')
        stored_filename = f"{university_slug}_destinations_{timestamp}.pdf"
        file_path = upload_dir / stored_filename

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        doc_id = db_manager.add_document(
            university_id=current_university['university_id'],
            document_type='destinazioni',
            original_filename=file.filename,
            stored_filename=stored_filename,
            file_path=str(file_path),
            academic_year=academic_year
        )

        if not doc_id:
            os.unlink(file_path)
            raise HTTPException(status_code=500, detail="Errore nel salvataggio delle informazioni del documento")

        # Le destinazioni NON vengono indicizzate nel vector store
        # Vengono processate on-demand quando richieste dal servizio RAG

        return DocumentUploadResponse(
            document_id=doc_id,
            message="File destinazioni caricato con successo",
            filename=stored_filename,
            upload_date=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nell'upload delle destinazioni: {e}")
        raise HTTPException(status_code=500, detail=f"Errore durante l'upload: {str(e)}")


@router.post("/upload/erasmus-courses", response_model=DocumentUploadResponse)
async def upload_erasmus_courses(
    file: UploadFile = File(..., description="PDF dei corsi Erasmus"),
    academic_year: Optional[str] = Form(None, description="Anno accademico (opzionale)"),
    current_university: dict = Depends(get_current_university)
):
    """Carica un PDF contenente i corsi Erasmus. Il file viene salvato in data/corsi_erasmus."""
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Solo file PDF sono accettati")

        upload_dir = Path(__file__).parent.parent.parent.parent / "data" / "corsi_erasmus"
        upload_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        university_slug = current_university['university_name'].lower().replace(' ', '_').replace('-', '_')
        stored_filename = f"{university_slug}_courses_{timestamp}.pdf"
        file_path = upload_dir / stored_filename

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        doc_id = db_manager.add_document(
            university_id=current_university['university_id'],
            document_type='corsi_erasmus',
            original_filename=file.filename,
            stored_filename=stored_filename,
            file_path=str(file_path),
            academic_year=academic_year
        )

        if not doc_id:
            os.unlink(file_path)
            raise HTTPException(status_code=500, detail="Errore nel salvataggio delle informazioni del documento")

        return DocumentUploadResponse(
            document_id=doc_id,
            message="File corsi Erasmus caricato con successo",
            filename=stored_filename,
            upload_date=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nell'upload dei corsi: {e}")
        raise HTTPException(status_code=500, detail=f"Errore durante l'upload: {str(e)}")


@router.post("/upload/destinazioni", response_model=DocumentUploadResponse)
async def upload_destinations(
    file: UploadFile = File(..., description="PDF delle destinazioni Erasmus"),
    academic_year: Optional[str] = Form(None),
    current_university: dict = Depends(get_current_university)
):
    """
    Carica il PDF delle destinazioni per l'università autenticata.
    Salva il file in data/destinazioni/.
    """
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Solo file PDF sono accettati")

        upload_dir = Path(__file__).parent.parent.parent.parent / "data" / "destinazioni"
        upload_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        university_slug = current_university['university_name'].lower().replace(' ', '_').replace('-', '_')
        stored_filename = f"{university_slug}_destinazioni_{timestamp}.pdf"
        file_path = upload_dir / stored_filename

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        doc_id = db_manager.add_document(
            university_id=current_university['university_id'],
            document_type='destinazioni',
            original_filename=file.filename,
            stored_filename=stored_filename,
            file_path=str(file_path),
            academic_year=academic_year
        )

        if not doc_id:
            os.unlink(file_path)
            raise HTTPException(status_code=500, detail="Errore nel salvataggio delle informazioni del documento")

        return DocumentUploadResponse(
            document_id=doc_id,
            message="File destinazioni caricato con successo",
            filename=stored_filename,
            upload_date=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nell'upload delle destinazioni: {e}")
        raise HTTPException(status_code=500, detail=f"Errore durante l'upload: {str(e)}")


@router.post("/upload/erasmus-courses", response_model=DocumentUploadResponse)
async def upload_erasmus_courses(
    file: UploadFile = File(..., description="PDF dei corsi Erasmus della destinazione"),
    academic_year: Optional[str] = Form(None),
    current_university: dict = Depends(get_current_university)
):
    """
    Carica il PDF dei corsi Erasmus (esami) per l'università autenticata.
    Salva il file in data/corsi_erasmus/.
    """
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Solo file PDF sono accettati")

        upload_dir = Path(__file__).parent.parent.parent.parent / "data" / "corsi_erasmus"
        upload_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        university_slug = current_university['university_name'].lower().replace(' ', '_').replace('-', '_')
        stored_filename = f"{university_slug}_courses_{timestamp}.pdf"
        file_path = upload_dir / stored_filename

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        doc_id = db_manager.add_document(
            university_id=current_university['university_id'],
            document_type='corsi_erasmus',
            original_filename=file.filename,
            stored_filename=stored_filename,
            file_path=str(file_path),
            academic_year=academic_year
        )

        if not doc_id:
            os.unlink(file_path)
            raise HTTPException(status_code=500, detail="Errore nel salvataggio delle informazioni del documento")

        return DocumentUploadResponse(
            document_id=doc_id,
            message="File corsi Erasmus caricato con successo",
            filename=stored_filename,
            upload_date=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nell'upload dei corsi: {e}")
        raise HTTPException(status_code=500, detail=f"Errore durante l'upload: {str(e)}")


@router.post("/process/destinazioni/{document_id}")
async def process_destinations_endpoint(document_id: int, current_university: dict = Depends(get_current_university)):
    """
    Endpoint che forza il processamento delle destinazioni per il documento dato.
    Chiama le funzioni di servizio per estrarre e preprocessare il testo.
    """
    try:
        # Recupera il documento
        documents = db_manager.get_university_documents(university_id=current_university['university_id'])
        document = next((d for d in documents if d['id'] == document_id), None)
        if not document:
            raise HTTPException(status_code=404, detail="Documento non trovato")

        # Importa il servizio e forza il processamento (ricrea il file processed)
        from ...services.rag_service import analyze_destinations_for_department
        # Qui non conosciamo il dipartimento: limitiamo all'estrazione generale => ricreiamo il file processed
        # Chiamiamo la funzione con valori placeholder per forzare l'estrazione
        # Nota: la funzione salva il file processed nel path standard
        home_university = current_university['university_name'].lower().replace(' ', '_')
        # Invoke extraction by calling analyze_destinations_for_department with a dummy dept and period,
        # wrapped in try/except because la funzione usa Gemini e può fallire
        try:
            await analyze_destinations_for_department(home_university, department='ALL', period='')
        except Exception as e:
            # Non blocchiamo l'endpoint in caso di errori di AI; restituiamo comunque successo parziale
            print(f"Errore durante il processamento delle destinazioni: {e}")

        return {"message": "Processamento destinazioni avviato"}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore in process_destinations_endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents", response_model=UniversityDocumentsResponse)
async def get_my_documents(
    document_type: Optional[str] = None,
    current_university: dict = Depends(get_current_university)
):
    """
    Recupera tutti i documenti caricati dall'università autenticata.
    Opzionalmente filtra per tipo di documento.
    """
    try:
        documents = db_manager.get_university_documents(
            university_id=current_university['university_id'],
            document_type=document_type
        )
        
        doc_list = [
            DocumentInfo(
                id=doc['id'],
                document_type=doc['document_type'],
                original_filename=doc['original_filename'],
                stored_filename=doc['stored_filename'],
                upload_date=doc['upload_date'],
                academic_year=doc['academic_year'],
                is_active=bool(doc['is_active'])
            )
            for doc in documents
        ]
        
        return UniversityDocumentsResponse(
            documents=doc_list,
            total=len(doc_list)
        )
    
    except Exception as e:
        print(f"Errore nel recupero documenti: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    current_university: dict = Depends(get_current_university)
):
    """
    Disattiva (soft delete) un documento caricato dall'università.
    """
    try:
        success = db_manager.deactivate_document(
            document_id=document_id,
            university_id=current_university['university_id']
        )
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail="Documento non trovato o non autorizzato"
            )
        
        return {
            "message": "Documento disattivato con successo",
            "document_id": document_id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nella disattivazione documento: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{document_id}")
async def download_document(
    document_id: int,
    current_university: dict = Depends(get_current_university)
):
    """
    Scarica un documento caricato dall'università autenticata.
    """
    try:
        documents = db_manager.get_university_documents(
            university_id=current_university['university_id']
        )
        
        document = next((doc for doc in documents if doc['id'] == document_id), None)
        
        if not document:
            raise HTTPException(
                status_code=404,
                detail="Documento non trovato"
            )
        
        file_path = Path(document['file_path'])
        
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail="File non trovato sul server"
            )
        
        return FileResponse(
            path=str(file_path),
            filename=document['original_filename'],
            media_type='application/pdf'
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Errore nel download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/db-status")
async def debug_db_status():
    """Endpoint di debug per verificare il contenuto del database"""
    try:
        # Università registrate
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, university_name, institutional_email FROM universities")
        universities = [dict(row) for row in cursor.fetchall()]
        
        # Documenti totali
        cursor.execute("SELECT COUNT(*) as count FROM uploaded_documents")
        total_docs = cursor.fetchone()['count']
        
        # Bandi attivi
        cursor.execute("""
            SELECT d.document_type, COUNT(*) as count
            FROM uploaded_documents d
            WHERE d.is_active = 1
            GROUP BY d.document_type
        """)
        docs_by_type = [dict(row) for row in cursor.fetchall()]
        
        # Bandi erasmus_call attivi
        active_calls = db_manager.get_all_active_calls()
        
        conn.close()
        
        return {
            "universities_count": len(universities),
            "universities": universities,
            "total_documents": total_docs,
            "documents_by_type": docs_by_type,
            "active_erasmus_calls": len(active_calls),
            "active_calls_details": [
                {
                    "university": call.get('university_name'),
                    "filename": call.get('original_filename'),
                    "type": call.get('document_type')
                }
                for call in active_calls
            ]
        }
    except Exception as e:
        print(f"Errore debug: {e}")
        raise HTTPException(status_code=500, detail=str(e))

