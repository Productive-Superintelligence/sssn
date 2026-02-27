# WIP: its still a draft, security is complicated, I will come back to this later.


import jwt
import time
from typing import Dict, Any

# The single secret the server needs to remember. 
# (Load this from an environment variable or keyring in production)
MASTER_SECRET = "super-secret-channel-key-do-not-share"

def generate_jwt(requester_id: str, role: str, expires_in_seconds: float = 3600) -> str:
    """Generates a token. Notice we don't save anything to a DB!"""
    payload = {
        "sub": requester_id,         # Subject (who this token is for)
        "role": role,                # Their permission level
        "exp": time.time() + expires_in_seconds  # Expiration timestamp
    }
    
    # Creates the cryptographic string
    token = jwt.encode(payload, MASTER_SECRET, algorithm="HS256")
    return token

def verify_jwt(token: str) -> Dict[str, Any]:
    """Verifies the token. Notice we don't look up anything in a DB!"""
    try:
        # This mathematically verifies the signature AND checks the 'exp' time automatically!
        decoded_payload = jwt.decode(token, MASTER_SECRET, algorithms=["HS256"])
        return decoded_payload
        
    except jwt.ExpiredSignatureError:
        raise Exception("Token has expired. Please request a new one.")
    except jwt.InvalidTokenError:
        raise Exception("Invalid or tampered token.")

# import abc
# from calendar import day_abbr
# import os
# import json
# import time
# from typing import Dict, Any, Optional, List
# from pathlib import Path
# from dataclasses import dataclass

# from enum import Enum
# import secrets
# from pydantic import BaseModel, Field

# import logging

# logger = logging.getLogger(__name__)



# # Key Management, basic key-based access control. 
# # The network creator may generate keys using an admin key. Generated when creating a KM.
# # We have keyrings in KM, each keyring has a list of keys. 

# class KeyRole(str, Enum):
#     READ = "read"
#     WRITE = "write"
#     ADMIN = "admin"

# # A simple Pydantic model for the incoming JSON request to generate a key
# class GenerateKeyRequest(BaseModel):
#     requester_id: str
#     role: KeyRole
#     expires_at: Optional[float] = None # by default 30 days

# class Key(BaseModel):
#     holder_id: str
#     holder_role: KeyRole
#     expires_at: Optional[float] = None # by default 30 days

# class Keyring(BaseModel):
#     id: str
#     keys: List[Key] = Field(default_factory=list)
#     description: Optional[str] = None
#     created_at: float
#     updated_at: float
#     created_by: str
#     updated_by: str

#     def __init__(self, id: str, description: Optional[str] = None, created_by: str = "system", updated_by: str = "system"):
#         self.id = id
#         self.description = description
#         self.created_at = time.time()
#         self.updated_at = time.time()
#         self.created_by = created_by
#         self.updated_by = updated_by

#     def add_key(self, key: Key, updated_by: str = "system"):
#         self.keys.append(key)
#         self.updated_at = time.time()
#         self.updated_by = updated_by

#     def remove_key(self, key: Key, updated_by: str = "system"):
#         self.keys = [k for k in self.keys if k.id != key.id]
#         self.updated_at = time.time()
#         self.updated_by = updated_by


# class BaseKeyManager(abc.ABC):
#     """Abstract base class for persisting API keys."""

#     def __init__(self):
#         self.keyrings: Dict[str, Keyring] = {}

#     def new_keyring(self, ring_id: str, keys: List[Key], description: Optional[str] = None, created_by: str = "system", updated_by: str = "system") -> Keyring:
#         if ring_id in self.keyrings:
#             logger.warning(f"Keyring {ring_id} already exists. Returning existing keyring.")
#             return self.keyrings[ring_id]
#         keyring = Keyring(ring_id, keys, description, created_by, updated_by)
#         self.keyrings[ring_id] = keyring
#         return keyring

#     @abc.abstractmethod
#     async def generate_key(self, request: GenerateKeyRequest) -> Key:
#         pass

#     @abc.abstractmethod
#     async def _save_key(self, ring_id: str, key: str, requester_id: str, role: KeyRole, expires_at: Optional[float]) -> bool:
#         pass

#     @abc.abstractmethod
#     async def _load_keys(self, ring_id: str) -> Dict[str, Dict[str, Any]]:
#         pass

#     async def check_access(self, ring_id: str, key: str, required_role: KeyRole) -> bool:
#         keys = await self._load_keys(ring_id)
#         if key not in keys:
#             return False
#         return keys[key]["role"] == required_role.value
    

# class LocalKeyManager(BaseKeyManager):
#     """
#     Default secure local key storage. 
#     Saves keys to ~/.sssn/keys/ and restricts file permissions.
#     """
#     def __init__(self, base_dir: Optional[str] = None):
#         super().__init__()
#         self.dir = Path(base_dir) if base_dir else Path.home() / ".sssn" / "keys"
#         self.dir.mkdir(parents=True, exist_ok=True)
#         # Attempt to restrict directory permissions to owner-only (rwx------)
#         try:
#             os.chmod(self.dir, 0o700)
#         except Exception:
#             raise Exception("Failed to set directory permissions") # OS might not support it (e.g., some Windows setups)

#     def _get_path(self, ring_id: str) -> Path:
#         return self.dir / f"{ring_id}_keys.json"

#     async def generate_key(self, request: GenerateKeyRequest) -> Key:
#         key = secrets.token_urlsafe(32)
#         if request.ring_id not in self.keyrings:
#             self.new_keyring(request.ring_id, [], request.description, request.requester_id, request.requester_id)
#         await self.save_key(request.ring_id, key, request.requester_id, request.role, request.expires_at)
#         return key

#     async def _save_key(self, ring_id: str, key: str, requester_id: str, role: KeyRole, expires_at: Optional[float]) -> bool:
#         with open(file_path, "w") as f:
#             json.dump(keys, f)
            
#         # Lock down file permissions (rw-------)
#         try:
#             os.chmod(file_path, 0o600)
#         except Exception:
#             pass
            
#         return True

#     async def load_keys(self, ring_id: str) -> Dict[str, Dict[str, Any]]:
#         file_path = self._get_path(ring_id)
#         if not file_path.exists():
#             return {}
#         with open(file_path, "r") as f:
#             return json.load(f)

#     async def check_access(self, ring_id: str, key: str, required_role: KeyRole) -> bool:
#         keys = await self.load_keys(ring_id)
#         if key not in keys:
#             return False
#         return keys[key]["role"] == required_role.value
