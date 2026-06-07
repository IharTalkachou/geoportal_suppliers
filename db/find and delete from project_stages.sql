-- поиск вхождений со словом
SELECT project_id, project_name FROM public.projects WHERE project_name ILIKE '%ниип%';

-- поиск проектов
SELECT project_id, project_name FROM public.projects;

-- выбор этапов по id проекта
SELECT stage_progress_id, iteration_count, actual_end, comments FROM project_stages WHERE project_id = 12;
SELECT * FROM project_stages WHERE project_id = 12;

-- удалить несколько записей этапов
DELETE FROM project_stages WHERE stage_progress_id IN (225, 226, 227, 228, 229);

-- удалить диапазон записей этапов
DELETE FROM project_stages WHERE stage_progress_id BETWEEN 289 AND 293;

-- удалить одну запись этапов
DELETE FROM project_stages WHERE stage_progress_id = 144;


UPDATE project_stages SET iteration_count = 1 WHERE stage_progress_id = 356;
UPDATE project_stages SET iteration_count = 2 WHERE stage_progress_id = 144;