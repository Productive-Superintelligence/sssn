"""SSSN service adapters."""

from .endpoints import StoreEndpointSpec, endpoint
from .fastapi import create_app

__all__ = ["StoreEndpointSpec", "create_app", "endpoint"]
