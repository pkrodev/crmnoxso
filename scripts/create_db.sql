-- Zakłada bazy dla NOXSO CRM.
--
-- Uruchom po instalacji PostgreSQL 16, z katalogu projektu:
--     psql -U postgres -f scripts/create_db.sql
--
-- Jeśli psql nie jest w PATH (typowe na Windows), użyj pełnej ścieżki:
--     "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -f scripts/create_db.sql

CREATE DATABASE noxso_crm
    ENCODING 'UTF8'
    TEMPLATE template0;

-- Osobna baza dla testów — pytest ją czyści między uruchomieniami,
-- więc nie może to być baza robocza.
CREATE DATABASE noxso_crm_test
    ENCODING 'UTF8'
    TEMPLATE template0;
