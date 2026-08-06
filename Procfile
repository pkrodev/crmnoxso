# Railway / Gunicorn.
#
# --workers 1 jest CELOWE: APScheduler chodzi w procesie aplikacji, więc przy
# większej liczbie workerów to samo zadanie wykonałoby się kilka razy.
# Przy skali tej aplikacji (jeden użytkownik, ~2000 kontaktów) jeden worker
# z wątkami wystarcza z zapasem.
web: gunicorn wsgi:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT
release: flask db upgrade
