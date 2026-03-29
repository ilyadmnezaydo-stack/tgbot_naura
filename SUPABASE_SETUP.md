# Supabase Setup

This bot expects its own tables in the `public` schema:

- `bot_users`
- `bot_contacts`

Your current Supabase project is reachable, but those tables are missing there right now.

## What to use

- `SUPABASE_URL`: your project URL like `https://<project-ref>.supabase.co`
- `SUPABASE_KEY`: a `service_role` key
- `SUPABASE_ACCESS_TOKEN`: optional, only if you want to apply schema from the local script instead of SQL Editor

Do not use a `publishable` or `anon` key for this bot backend.

## How to create the schema

1. Open Supabase Dashboard.
2. Go to `SQL Editor`.
3. Open [`supabase/bot_schema.sql`](c:\Users\tyryt\Desktop\bots\coffe_ bot\supabase\bot_schema.sql).
4. Run the whole script.

The script is idempotent, so you can rerun it later when the schema gets new fields like birthdays or indexes.

## Optional local apply

If you prefer not to paste SQL manually, add `SUPABASE_ACCESS_TOKEN` to `.env` and run:

```powershell
.venv\Scripts\python.exe .\scripts\apply_supabase_schema.py
```

This uses the Supabase Management API, which requires a personal access token.

## After that

Restart the bot with:

```powershell
.\run_bot.cmd
```

## Security

If a `service_role` key was pasted into chat or shared anywhere, rotate it later in Supabase.
