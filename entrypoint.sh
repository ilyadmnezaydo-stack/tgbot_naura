#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
while ! python -c "
import asyncio
import asyncpg
async def check():
    try:
        conn = await asyncpg.connect('${DATABASE_URL}'.replace('+asyncpg', ''))
        await conn.close()
        return True
    except:
        return False
exit(0 if asyncio.run(check()) else 1)
" 2>/dev/null; do
    echo "PostgreSQL is unavailable - sleeping"
    sleep 2
done

echo "PostgreSQL is up - running migrations"
alembic upgrade head

echo "Starting bot..."
exec python src/main.py
