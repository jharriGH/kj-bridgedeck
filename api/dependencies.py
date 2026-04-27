"""Shared FastAPI dependencies."""
from services.brain_client import BrainClient
from services.supabase_client import get_supabase
from services.watcher_client import WatcherClient


def supabase_dep():
    return get_supabase()


def brain_client_dep():
    return BrainClient()


def watcher_client_dep():
    return WatcherClient()
