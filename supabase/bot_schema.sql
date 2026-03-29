create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create or replace function public.is_valid_partial_birthday(
  birthday_day integer,
  birthday_month integer,
  birthday_year integer
)
returns boolean
language plpgsql
immutable
as $$
begin
  if birthday_day is null and birthday_month is null and birthday_year is null then
    return true;
  end if;

  if birthday_day is null or birthday_month is null then
    return false;
  end if;

  if birthday_year is not null and (birthday_year < 1900 or birthday_year > 2100) then
    return false;
  end if;

  perform make_date(coalesce(birthday_year, 2000), birthday_month, birthday_day);
  return true;
exception
  when others then
    return false;
end;
$$;

create table if not exists public.bot_users (
  id bigint primary key,
  username text,
  first_name text,
  language_code text not null default 'ru',
  voice_trial_started_at timestamptz,
  voice_trial_expires_at timestamptz,
  voice_subscription_expires_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.bot_users
  add column if not exists username text,
  add column if not exists first_name text,
  add column if not exists language_code text not null default 'ru',
  add column if not exists voice_trial_started_at timestamptz,
  add column if not exists voice_trial_expires_at timestamptz,
  add column if not exists voice_subscription_expires_at timestamptz,
  add column if not exists created_at timestamptz not null default timezone('utc', now()),
  add column if not exists updated_at timestamptz not null default timezone('utc', now());

create table if not exists public.bot_contacts (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null references public.bot_users(id) on delete cascade,
  username text not null,
  display_name text,
  description text,
  tags text[] not null default '{}'::text[],
  birthday_day integer,
  birthday_month integer,
  birthday_year integer,
  reminder_frequency text not null default 'biweekly',
  custom_interval_days integer,
  next_reminder_date date,
  one_time_date date,
  status text not null default 'active',
  last_contacted_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.bot_contacts
  add column if not exists display_name text,
  add column if not exists description text,
  add column if not exists tags text[] not null default '{}'::text[],
  add column if not exists birthday_day integer,
  add column if not exists birthday_month integer,
  add column if not exists birthday_year integer,
  add column if not exists reminder_frequency text not null default 'biweekly',
  add column if not exists custom_interval_days integer,
  add column if not exists next_reminder_date date,
  add column if not exists one_time_date date,
  add column if not exists status text not null default 'active',
  add column if not exists last_contacted_at timestamptz,
  add column if not exists created_at timestamptz not null default timezone('utc', now()),
  add column if not exists updated_at timestamptz not null default timezone('utc', now());

alter table public.bot_contacts
  drop constraint if exists bot_contacts_status_check;

alter table public.bot_contacts
  add constraint bot_contacts_status_check
  check (status in ('active', 'paused', 'one_time'));

alter table public.bot_contacts
  drop constraint if exists bot_contacts_birthday_check;

alter table public.bot_contacts
  add constraint bot_contacts_birthday_check
  check (public.is_valid_partial_birthday(birthday_day, birthday_month, birthday_year));

create index if not exists bot_contacts_user_id_idx
  on public.bot_contacts(user_id);

create unique index if not exists bot_contacts_user_username_unique_idx
  on public.bot_contacts(user_id, lower(username));

create index if not exists bot_contacts_next_reminder_date_idx
  on public.bot_contacts(next_reminder_date);

create index if not exists bot_contacts_birthdays_idx
  on public.bot_contacts(birthday_month, birthday_day);

create table if not exists public.bot_payments (
  id uuid primary key default gen_random_uuid(),
  invoice_id text not null unique,
  user_id bigint not null references public.bot_users(id) on delete cascade,
  provider text not null,
  payment_method text not null,
  status text not null default 'pending',
  amount numeric(12,2) not null,
  currency text not null default 'RUB',
  description text,
  account_id text,
  provider_transaction_id bigint,
  provider_qr_id text,
  payment_url text,
  provider_status text,
  failure_reason text,
  failure_reason_code integer,
  raw_create_response jsonb,
  raw_last_webhook jsonb,
  last_webhook_type text,
  paid_at timestamptz,
  failed_at timestamptz,
  canceled_at timestamptz,
  expired_at timestamptz,
  notified_paid_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.bot_payments
  add column if not exists invoice_id text,
  add column if not exists user_id bigint references public.bot_users(id) on delete cascade,
  add column if not exists provider text,
  add column if not exists payment_method text,
  add column if not exists status text not null default 'pending',
  add column if not exists amount numeric(12,2),
  add column if not exists currency text not null default 'RUB',
  add column if not exists description text,
  add column if not exists account_id text,
  add column if not exists provider_transaction_id bigint,
  add column if not exists provider_qr_id text,
  add column if not exists payment_url text,
  add column if not exists provider_status text,
  add column if not exists failure_reason text,
  add column if not exists failure_reason_code integer,
  add column if not exists raw_create_response jsonb,
  add column if not exists raw_last_webhook jsonb,
  add column if not exists last_webhook_type text,
  add column if not exists paid_at timestamptz,
  add column if not exists failed_at timestamptz,
  add column if not exists canceled_at timestamptz,
  add column if not exists expired_at timestamptz,
  add column if not exists notified_paid_at timestamptz,
  add column if not exists created_at timestamptz not null default timezone('utc', now()),
  add column if not exists updated_at timestamptz not null default timezone('utc', now());

alter table public.bot_payments
  alter column invoice_id set not null,
  alter column user_id set not null,
  alter column provider set not null,
  alter column payment_method set not null,
  alter column amount set not null;

alter table public.bot_payments
  drop constraint if exists bot_payments_status_check;

alter table public.bot_payments
  add constraint bot_payments_status_check
  check (status in ('pending', 'paid', 'failed', 'canceled', 'expired'));

create unique index if not exists bot_payments_invoice_id_unique_idx
  on public.bot_payments(invoice_id);

create index if not exists bot_payments_user_id_idx
  on public.bot_payments(user_id);

create index if not exists bot_payments_status_idx
  on public.bot_payments(status);

create index if not exists bot_payments_provider_transaction_id_idx
  on public.bot_payments(provider_transaction_id);

drop trigger if exists set_bot_users_updated_at on public.bot_users;
create trigger set_bot_users_updated_at
before update on public.bot_users
for each row
execute function public.set_updated_at();

drop trigger if exists set_bot_contacts_updated_at on public.bot_contacts;
create trigger set_bot_contacts_updated_at
before update on public.bot_contacts
for each row
execute function public.set_updated_at();

drop trigger if exists set_bot_payments_updated_at on public.bot_payments;
create trigger set_bot_payments_updated_at
before update on public.bot_payments
for each row
execute function public.set_updated_at();
