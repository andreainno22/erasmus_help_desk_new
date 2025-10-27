# app/schemas/university.py
from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime
import re


class UniversityRegisterRequest(BaseModel):
    """Schema per la registrazione di una nuova università."""
    model_config = ConfigDict(extra='forbid')
    
    university_name: str = Field(
        ..., 
        min_length=3, 
        max_length=200,
        example="Università di Pisa",
        description="Nome ufficiale dell'università"
    )
    institutional_email: EmailStr = Field(
        ...,
        example="erasmus@unipi.it",
        description="Email istituzionale dell'università (deve contenere il dominio dell'università)"
    )
    password: str = Field(
        ...,
        min_length=8,
        example="SecurePassword123!",
        description="Password (minimo 8 caratteri, almeno una maiuscola, una minuscola e un numero)"
    )
    contact_person: Optional[str] = Field(
        None,
        max_length=100,
        example="Mario Rossi",
        description="Nome della persona di riferimento"
    )
    phone: Optional[str] = Field(
        None,
        max_length=20,
        example="+39 050 2211000",
        description="Numero di telefono"
    )
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Valida che la password sia sufficientemente sicura."""
        if len(v) < 8:
            raise ValueError('La password deve essere di almeno 8 caratteri')
        if not re.search(r'[A-Z]', v):
            raise ValueError('La password deve contenere almeno una lettera maiuscola')
        if not re.search(r'[a-z]', v):
            raise ValueError('La password deve contenere almeno una lettera minuscola')
        if not re.search(r'[0-9]', v):
            raise ValueError('La password deve contenere almeno un numero')
        return v


class UniversityLoginRequest(BaseModel):
    """Schema per il login di un'università."""
    model_config = ConfigDict(extra='forbid')
    
    institutional_email: EmailStr = Field(..., example="erasmus@unipi.it")
    password: str = Field(..., example="SecurePassword123!")


class UniversityLoginResponse(BaseModel):
    """Schema per la risposta di login."""
    access_token: str = Field(..., description="Token JWT per l'autenticazione")
    token_type: str = Field(default="bearer", description="Tipo di token")
    university_id: int = Field(..., description="ID dell'università")
    university_name: str = Field(..., description="Nome dell'università")
    email: str = Field(..., description="Email istituzionale")


class UniversityProfileResponse(BaseModel):
    """Schema per il profilo dell'università."""
    id: int
    university_name: str
    institutional_email: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    is_verified: bool
    created_at: str
    last_login: Optional[str] = None


class DocumentUploadResponse(BaseModel):
    """Schema per la risposta dopo l'upload di un documento."""
    document_id: int = Field(..., description="ID del documento caricato")
    message: str = Field(..., description="Messaggio di conferma")
    filename: str = Field(..., description="Nome del file salvato")
    upload_date: str = Field(..., description="Data di upload")


class DocumentInfo(BaseModel):
    """Schema per le informazioni di un documento."""
    id: int
    document_type: str
    original_filename: str
    stored_filename: str
    upload_date: str
    academic_year: Optional[str] = None
    is_active: bool


class UniversityDocumentsResponse(BaseModel):
    """Schema per la lista di documenti di un'università."""
    documents: List[DocumentInfo]
    total: int


class ActiveCallInfo(BaseModel):
    """Schema per le informazioni di un bando attivo (per studenti)."""
    id: int
    university_name: str
    original_filename: str
    stored_filename: str
    academic_year: Optional[str] = None
    upload_date: str


class ActiveCallsListResponse(BaseModel):
    """Schema per la lista di bandi attivi."""
    calls: List[ActiveCallInfo]
    total: int
