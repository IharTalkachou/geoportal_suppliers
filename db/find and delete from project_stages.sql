-- поиск вхождений со словом
SELECT project_id, project_name FROM public.projects WHERE project_name ILIKE '%гослес%';

-- выбор этапов по id проекта
SELECT stage_progress_id, actual_start, actual_end, comments FROM project_stages WHERE project_id = 15;

-- удалить несколько записей этапов
DELETE FROM project_stages WHERE stage_progress_id IN (225, 226, 227, 228, 229);

-- удалить диапазон записей этапов
DELETE FROM project_stages WHERE stage_progress_id BETWEEN 164 AND 169;