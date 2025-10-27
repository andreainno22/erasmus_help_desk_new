# app/core/auth.py
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import settings

# Configurazione JWT (caricata da .env o usa default)
SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES

security = HTTPBearer()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Crea un token JWT."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """Decodifica e verifica un token JWT."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=401,
            detail="Token non valido o scaduto",
            headers={"WWW-Authenticate": "Bearer"}
        )


def get_current_university(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """
    Dependency per proteggere gli endpoint.
    Verifica il token JWT e restituisce i dati dell'università autenticata.
    """
    token = credentials.credentials
    payload = decode_access_token(token)
    
    university_id = payload.get("university_id")
    email = payload.get("email")
    
    if not university_id or not email:
        raise HTTPException(
            status_code=401,
            detail="Token non valido",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return {
        "university_id": university_id,
        "email": email,
        "university_name": payload.get("university_name")
    }
