from supabase import create_async_client, AsyncClient

from src.config import settings

_supabase: AsyncClient | None = None


async def get_supabase() -> AsyncClient:
    """Get or create the Supabase async client singleton."""
    global _supabase
    if _supabase is None:
        _supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _supabase


async def init_db():
    """Initialize Supabase client."""
    await get_supabase()


async def close_db():
    """Cleanup Supabase client."""
    global _supabase
    if _supabase is not None:
        await _supabase.postgrest.aclose()
        _supabase = None
