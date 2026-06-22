-- 1. Удаляем документы, связанные с историей удаляемых заявок
DELETE FROM stage_documents 
WHERE provision_history_id IN (
    SELECT history_id FROM provision_request_history WHERE req_id > 1
);

-- 2. Удаляем историю переходов для заявок с ID > 1
DELETE FROM provision_request_history WHERE req_id > 1;

-- 3. Удаляем сами заявки с ID > 1
DELETE FROM provision_requests WHERE req_id > 1;

-- 4. Сбрасываем счетчик ID (sequence), чтобы следующая запись получила ID = 2
-- 'provision_requests_req_id_seq' — это стандартное имя последовательности в Postgres
SELECT setval('provision_requests_req_id_seq', 1);