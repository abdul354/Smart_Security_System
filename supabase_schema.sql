-- Run this in Supabase SQL editor

-- Persons metadata
create table if not exists public.persons (
  person_id text primary key,
  display_name text not null,
  role text,
  department text,
  access_status text,
  enrolled_at timestamptz not null default now()
);

-- Attendance logs
create table if not exists public.attendance (
  id bigserial primary key,
  person_id text not null references public.persons(person_id) on delete cascade,
  timestamp timestamptz not null default now(),
  attendance_day date generated always as ((timestamp at time zone 'utc')::date) stored,
  status text not null default 'present',
  source text not null default 'webcam',
  unique (person_id, attendance_day)
);

create index if not exists attendance_person_id_idx on public.attendance(person_id);
create index if not exists attendance_timestamp_idx on public.attendance(timestamp);
