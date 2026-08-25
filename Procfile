# Railway / Gunicorn.
#
# --workers 1 jest CELOWE: APScheduler chodzi w procesie aplikacji, więc przy
# większej liczbie workerów to samo zadanie wykonałoby się kilka razy.
# Przy skali tej aplikacji (jeden użytkownik, ~2000 kontaktów) jeden worker
# z wątkami wystarcza z zapasem.
#
# MIGRACJE ODPALAMY W KOMENDZIE STARTOWEJ, nie w osobnym kroku `release`.
# Powód jest praktyczny, nie estetyczny: Railway czyta z tego pliku wyłącznie
# linię `web:` i kroku `release` NIE wykonuje. Sprawdzone na żywym wdrożeniu —
# aplikacja wstała, ale baza była pusta, bo `flask db upgrade` nigdy nie ruszył.
# Odpowiednik po stronie Railwaya (Pre-Deploy Command) siedziałby w panelu,
# niewidoczny dla kogoś, kto czyta repozytorium, i nie pojechałby z projektem
# na inną platformę. `flask db upgrade` jest idempotentne, a worker jest jeden,
# więc powtórzenie przy każdym starcie kontenera nic nie kosztuje.
web: flask db upgrade && gunicorn wsgi:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT
