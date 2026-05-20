FROM postgres:16-alpine

# Образ уже содержит pg_dump, pg_restore, sh и стандартные утилиты Linux
COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

CMD ["/usr/local/bin/backup.sh"]