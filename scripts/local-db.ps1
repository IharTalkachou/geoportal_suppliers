<#
.SYNOPSIS
    Локальная копия БД для тестов: переносимый PostgreSQL 17, без Docker и без прав администратора.

.DESCRIPTION
    Команды:
      init     - один раз: создать пустой сервер БД (роль и пароль берутся из .env)
      start    - запустить сервер (после каждой перезагрузки компьютера)
      stop     - остановить сервер
      status   - проверить, запущен ли сервер
      restore  - залить дамп в локальную БД; прежнее содержимое стирается

    Работает ТОЛЬКО с сервером на localhost - в прод-БД этот скрипт не ходит,
    какой бы DB_HOST ни стоял в .env.

    Пути по умолчанию: D:\tools\pgsql (программа), D:\tools\pgdata (данные).
    Переопределяются переменными окружения PG_HOME и PG_DATA.

    Нужна версия PostgreSQL 17 или новее: дампы с ВМ делает pg_dump 17
    (формат архива 1.16), более старый pg_restore их не читает.

.EXAMPLE
    .\scripts\local-db.ps1 init
    .\scripts\local-db.ps1 start
    .\scripts\local-db.ps1 restore
    .\scripts\local-db.ps1 restore D:\temp\other.dump
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('init', 'start', 'stop', 'status', 'restore')]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$DumpFile = 'backups\local\prod.dump'
)

# Не 'Stop': в PowerShell 5.1 вывод утилит в stderr (например, NOTICE от psql)
# иначе превращается в ошибку и обрывает скрипт. Коды возврата проверяем сами.
$ErrorActionPreference = 'Continue'

$root   = Split-Path -Parent $PSScriptRoot
$pgHome = if ($env:PG_HOME) { $env:PG_HOME } else { 'D:\tools\pgsql' }
$pgData = if ($env:PG_DATA) { $env:PG_DATA } else { 'D:\tools\pgdata' }
$bin    = Join-Path $pgHome 'bin'

function Fail($message) {
    Write-Host "ОШИБКА: $message" -ForegroundColor Red
    exit 1
}

function Check($what) {
    if ($LASTEXITCODE -ne 0) { Fail "$what (код $LASTEXITCODE)" }
}

if (-not (Test-Path (Join-Path $bin 'pg_ctl.exe'))) {
    Fail "не найден PostgreSQL в $pgHome. Укажите путь переменной окружения PG_HOME."
}

# --- Реквизиты из .env: те же, что использует приложение ---
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) { Fail "не найден $envFile" }
$cfg = @{}
foreach ($line in Get-Content $envFile -Encoding UTF8) {
    # Строки-комментарии (#DB_HOST=...) сюда не попадают: имя должно начинаться с буквы
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        $cfg[$Matches[1]] = $Matches[2].Trim('"', "'")
    }
}
foreach ($key in 'DB_USER', 'DB_PASS', 'DB_NAME') {
    if (-not $cfg[$key]) { Fail "в .env не задан $key" }
}
$port = if ($cfg['DB_PORT']) { $cfg['DB_PORT'] } else { '5432' }
$conn = @('-h', 'localhost', '-p', $port, '-U', $cfg['DB_USER'])
$env:PGPASSWORD = $cfg['DB_PASS']
$env:PGOPTIONS  = '-c client_min_messages=warning'   # без NOTICE-шума от DROP ... CASCADE

switch ($Command) {

    'init' {
        if (Test-Path (Join-Path $pgData 'PG_VERSION')) {
            Fail "сервер уже создан в $pgData. Чтобы начать с нуля: остановите его и удалите эту папку."
        }
        # Пароль передаётся файлом, а не в командной строке
        $pwFile = [IO.Path]::GetTempFileName()
        [IO.File]::WriteAllText($pwFile, $cfg['DB_PASS'])
        # ICU ru-RU: русские строки сортируются по алфавиту (ORDER BY по названиям)
        & (Join-Path $bin 'initdb.exe') -D $pgData -U $cfg['DB_USER'] "--pwfile=$pwFile" `
            -A scram-sha-256 -E UTF8 --locale=C --locale-provider=icu --icu-locale=ru-RU
        $rc = $LASTEXITCODE
        Remove-Item $pwFile -Force
        if ($rc -ne 0) { Fail "initdb (код $rc)" }
        # Сервер слушает только этот компьютер - снаружи к нему не подключиться
        Add-Content (Join-Path $pgData 'postgresql.conf') "`r`nlisten_addresses = 'localhost'`r`nport = $port`r`n"
        Write-Host "Готово: сервер создан в $pgData. Дальше: start, затем restore." -ForegroundColor Green
    }

    'start' {
        & (Join-Path $bin 'pg_ctl.exe') -D $pgData -l (Join-Path $pgData 'server.log') -w start
        Check 'не удалось запустить сервер, подробности в server.log'
    }

    'stop' {
        & (Join-Path $bin 'pg_ctl.exe') -D $pgData -m fast stop
        Check 'не удалось остановить сервер'
    }

    'status' {
        & (Join-Path $bin 'pg_ctl.exe') -D $pgData status
    }

    'restore' {
        $dump = if ([IO.Path]::IsPathRooted($DumpFile)) { $DumpFile } else { Join-Path $root $DumpFile }
        if (-not (Test-Path $dump)) { Fail "не найден дамп $dump" }
        $db = $cfg['DB_NAME']
        $psql = Join-Path $bin 'psql.exe'

        $exists = & $psql @conn -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'"
        Check 'нет подключения к локальному серверу - он запущен? (.\scripts\local-db.ps1 start)'
        if ($exists -ne '1') {
            & (Join-Path $bin 'createdb.exe') @conn $db
            Check "не удалось создать базу $db"
        }

        Write-Host "Очистка локальной базы $db..."
        & $psql @conn -d $db -v ON_ERROR_STOP=1 -q -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'
        Check 'очистка схемы'

        Write-Host "Восстановление из $dump..."
        # --no-owner/--no-privileges: владельцем всех объектов станет локальная роль,
        # права и роли прода (которых здесь нет) не переносятся
        & (Join-Path $bin 'pg_restore.exe') @conn -d $db --no-owner --no-privileges $dump
        if ($LASTEXITCODE -ne 0) {
            Write-Host "pg_restore завершился с ошибками (см. выше) - проверьте, критичны ли они." -ForegroundColor Yellow
        }

        & $psql @conn -d $db -q -c 'VACUUM ANALYZE;'
        $tables = & $psql @conn -d $db -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        $alembic = & $psql @conn -d $db -tAc 'SELECT version_num FROM alembic_version'
        Write-Host "Готово: таблиц $tables, версия схемы (alembic) $alembic." -ForegroundColor Green
    }
}
