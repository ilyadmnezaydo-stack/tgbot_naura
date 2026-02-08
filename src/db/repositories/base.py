from supabase import AsyncClient


class BaseRepository:
    def __init__(self, client: AsyncClient):
        self.client = client
