#!/bin/sh
# Extract DB to volume if missing, or if the shipped gz is newer than the volume copy
if [ ! -f /data/dict.db ] || [ /app/dict.db.gz -nt /data/dict.db ]; then
    echo "Extracting dict.db to /data (gz newer or missing)..."
    gunzip -c /app/dict.db.gz > /data/dict.db
    echo "Done: $(ls -lh /data/dict.db)"
fi

python -c "import server; server.init_examples_table()"
# 워커 1개 + 스레드. 숙어 탐지기(spaCy)가 워커마다 약 220MB라서 512MB VM에 워커 2개는 빠듯하다
exec gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 --timeout 30 server:app
