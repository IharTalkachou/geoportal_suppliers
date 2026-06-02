-- создание типов для таблиц
-- для surveys.it_regulations (виды ограничительных грифов)
--CREATE TYPE restrictions AS ENUM ('Открытые данные', 'Для служебного использования', 'Коммерческая информация', 'Иное');
-- для surveys.it_coordinate_determining (виды способов определения координат)
--CREATE TYPE definitions AS ENUM ('Автоматический', 'Полуавтоматический', 'Ручной');

-- таблица-справочник вариантов информационного взаимодействия 
CREATE TABLE ref_interactions (
    interaction_id SERIAL PRIMARY KEY,
    interaction_option_id INTEGER NOT NULL,
    interaction_text TEXT NOT NULL
);

-- основная таблица опросников
CREATE TABLE surveys (
    survey_id SERIAL PRIMARY KEY,
    received_date DATE NOT NULL,
    supplier_id INTEGER NOT NULL, 
    info_type_id INTEGER NOT NULL, 
    it_description TEXT NOT NULL,
    it_purpose TEXT NOT NULL,
    it_legal_status TEXT NOT NULL, 
    it_statute TEXT NOT NULL,
    it_regulations restrictions NOT NULL,
    it_other_regulations TEXT NOT NULL,
    it_format TEXT NOT NULL,
    it_type TEXT NOT NULL,
    it_digital_format TEXT NOT NULL,
    it_digital_transform BOOLEAN DEFAULT FALSE,
    it_metadata_base TEXT NOT NULL,
    it_coordinate_system TEXT NOT NULL,
    it_spatial_extent TEXT NOT NULL,
    it_actual_date DATE NOT NULL,
    it_update TEXT NOT NULL,
    it_spatial_scale TEXT NOT NULL,
    it_classification TEXT NOT NULL,
    it_conventional_signs TEXT NOT NULL,
    it_coordinate_determining definitions NOT NULL,
    it_coordinate_determining_text TEXT,
    it_use TEXT NOT NULL,
    it_distribution_format TEXT NOT NULL,
    it_distribution_method TEXT NOT NULL,
    it_distribution_protocol TEXT,
    it_base_services TEXT NOT NULL,
    interaction_id INTEGER NOT NULL,
    it_cis_publication BOOLEAN NOT NULL,

    -- определение связей
    -- внешний ключ поставщика
    CONSTRAINT fk_survey_supplier
        FOREIGN KEY (supplier_id)
        REFERENCES suppliers(supplier_id)
        ON DELETE CASCADE,
    -- внешний ключ вида сведений
    CONSTRAINT fk_survey_info_type
        FOREIGN KEY (info_type_id)
        REFERENCES info_types(info_id)
        ON DELETE CASCADE,
    -- внешний ключ вариантов информационного взаимодействия
    CONSTRAINT fk_survey_interaction
        FOREIGN KEY (interaction_id)
        REFERENCES ref_interactions(interaction_id)
        ON DELETE CASCADE
);
-- комментарий к таблице опросников
COMMENT ON TABLE surveys IS 'Результаты первичной технической проработки поставщиков ОНПД';
-- комментарий к полям таблицы опросников
COMMENT on COLUMN surveys.survey_id IS 'Идентификатор опросника';
COMMENT on COLUMN surveys.received_date IS 'Дата получения заполненного опросника';
COMMENT on COLUMN surveys.supplier_id IS 'Идентификатор поставщика';
COMMENT on COLUMN surveys.info_type_id IS 'Идентификатор вида сведений';
COMMENT on COLUMN surveys.it_description IS 'Описание набора ПД';
COMMENT on COLUMN surveys.it_purpose IS 'Назначение набора ПД (предполагаемая целевая аудитория при размещении на НГ)';
COMMENT on COLUMN surveys.it_legal_status IS 'Правовой статус набора ПД (основание для формирования и ведения набора ПД)';
COMMENT on COLUMN surveys.it_statute IS 'Нормативные правовые акты и технические нормативные правовые акты, регламентирующие формирование и обновление набора ПД (при их наличии)';
COMMENT on COLUMN surveys.it_regulations IS 'Ограничительный гриф набора ПД (при его наличии)';
COMMENT on COLUMN surveys.it_other_regulations IS 'Наличие иных ограничений, препятствующих предоставлению в пользование и использование набора ПД';
COMMENT on COLUMN surveys.it_format IS 'Форма ведения (хранения) набора ПД (цифровая, иная)';
COMMENT on COLUMN surveys.it_type IS 'Вид цифрового набора ПД (растровые данные, векторные данные, табличные данные, текст и т.д.)';
COMMENT on COLUMN surveys.it_digital_format IS 'Формат хранения цифрового набора ПД. Справочно: в векторном представлении - shp, dwg и другие; в растровой форме - tiff, jpeg, png и другие; в текстовой форме - docs, txt, xls и другие; база данных - mdb и другие';
COMMENT on COLUMN surveys.it_digital_transform IS 'Потребность перевода набора ПД в цифровую форму, текстовых или табличных данных в базу данных';
COMMENT on COLUMN surveys.it_metadata_base IS 'Наличие и виды информационных каталогов, баз данных, журналов учёта из которых возможно формировать метаданные';
COMMENT on COLUMN surveys.it_coordinate_system IS 'Системы отсчёта координат и высот набора ПД. Справочно: система отсчёта координат 1995 года; система отсчёта координат 1942 года, World Geodetic System (WGS-84); местные системы отсчёта координат; Балтийская система высот 1977 года; другие системы отсчёта';
COMMENT on COLUMN surveys.it_spatial_extent IS 'Территория, в отношении которой создан набор ПД (административно-территориальная единица; территориальная единица)';
COMMENT on COLUMN surveys.it_actual_date IS 'Год состояния местности (актуальность) набора ПД';
COMMENT on COLUMN surveys.it_update IS 'Периодичность (частота) обновления набора ПД, регламентирующие документы';
COMMENT on COLUMN surveys.it_spatial_scale IS 'Пространственное разрешение или масштаб данных. Справочно: для данных дистанционного зондирования Земли указывается пространственное разрешение; для картографических материалов - масштаб';
COMMENT on COLUMN surveys.it_classification IS 'Наличие специализированного классификатора объектов набора ПД (утвержденного в Республике Беларусь или международного классификатора)';
COMMENT on COLUMN surveys.it_conventional_signs IS 'Наличие каталога специальных графических отображений объектов набора ПД (специальные условные знаки)';
COMMENT on COLUMN surveys.it_coordinate_determining IS 'Точность и способ определения координат объектов набора ПД. Справочно: способы определения координат - автоматический, полуавтоматический, ручной';
COMMENT on COLUMN surveys.it_coordinate_determining_text IS 'Точность и способ определения координат объектов набора ПД. Описать методику получения координат, в том числе с указанием источника данных и инструмента (при наличии)';
COMMENT on COLUMN surveys.it_use IS 'Вариант использования набора ПД у поставщика (в виде настольных карт и схем, настольных ГИС (указать каких), WEB-сервисов (указать каких))';
COMMENT on COLUMN surveys.it_distribution_format IS 'Возможные формы и форматы предоставления набора ПД (в цифровом или ином виде). Справочно: для иных материалов - на бумаге, на пластике, на пленке и другие; для цифровых материалов в соответствии с п. 12 настоящего опросного листа';
COMMENT on COLUMN surveys.it_distribution_method IS 'Способы предоставления и протоколы обмена набора ПД в цифровой форме. Справочно: способы предоставления - на магнитном носителе, по электронной почте, в виде сервиса и другие';
COMMENT on COLUMN surveys.it_distribution_protocol IS 'Способы предоставления и протоколы обмена набора ПД в цифровой форме. Справочно: протоколы обмена - HTTPS, WMS, WMTS, REST API и другие';
COMMENT on COLUMN surveys.it_base_services IS 'Предполагаемые базовые сервисы на основе набора ПД для Национального геопортала. Справочно: визуализация, поиск, фильтрация, загрузка и другие';
COMMENT on COLUMN surveys.interaction_id IS 'Наиболее предпочтительный вариант информационного взаимодействия с оператором Национального геопортала';
COMMENT on COLUMN surveys.it_cis_publication IS 'Допускается размещение и публикация открытых наборов ПД на Геопортале инфраструктуры пространственных данных государств-участников СНГ';

-- таблица-связка "опросник-контакты"
CREATE TABLE survey_contacts (
    survey_contacts_id SERIAL PRIMARY KEY,
    survey_id INTEGER NOT NULL,
    contact_id INTEGER NOT NULL,
    -- определение связей
    -- внешний ключ опросника
    CONSTRAINT fk_survey_contacts_survey
        FOREIGN KEY (survey_id)
        REFERENCES surveys(survey_id)
        ON DELETE CASCADE,
    -- внешний ключ контактного лица
    CONSTRAINT fk_survey_contacts_contact
        FOREIGN KEY (contact_id)
        REFERENCES contacts(contact_id)
        ON DELETE CASCADE,
    -- защита уникальности контакта в опроснике
    CONSTRAINT unique_survey_contact UNIQUE (survey_id, contact_id)
);
-- комментарий к таблице-связке "опросник-контакты"
COMMENT ON TABLE survey_contacts IS 'Таблица-связка между опросниками и контактами поставщиков';
-- комментарии к полям таблицы-связки "опросник-контакты"
COMMENT on COLUMN survey_contacts.survey_contacts_id IS 'Идентификатор связи опросник-контакт';
COMMENT on COLUMN survey_contacts.survey_id IS 'Идентификатор опросника';
COMMENT on COLUMN survey_contacts.contact_id IS 'Идентификатор контактного лица';

-- таблица-связка "опросник-ссылки"
CREATE TABLE survey_links (
    survey_link_id SERIAL PRIMARY KEY,
    survey_id INTEGER NOT NULL,
    survey_link TEXT NOT NULL,
    -- определение связей
    -- внешний ключ опросника
    CONSTRAINT fk_survey_links_survey
        FOREIGN KEY (survey_id)
        REFERENCES surveys(survey_id)
        ON DELETE CASCADE,
    -- защита уникальности ссылки в опроснике
    CONSTRAINT unique_survey_link UNIQUE (survey_id, survey_link)
);
-- комментарий к таблице-связке "опросник-ссылки"
COMMENT ON TABLE survey_links IS 'Таблица-связка между опросниками и ссылками поставщиков на НПД, сервисы, варианты доступа';
-- комментарии к полям таблицы-связки "опросник-ссылки"
COMMENT on COLUMN survey_links.survey_link_id IS 'Идентификатор связи опросник-ссылка';
COMMENT on COLUMN survey_links.survey_id IS 'Идентификатор опросника';
COMMENT on COLUMN survey_links.survey_link IS 'Ссылка поставщика на НПД, сервис или вариант доступа';