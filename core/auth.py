# ============================================
# CORE MODULE - AUTH
# Shared api key verification dependency
# ============================================

from fastapi import Header, HTTPException

from config import API_KEY


def verify_api_key(x_api_key: str = Header(..., alias="x-api-key")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing api key")
    return x_api_key
