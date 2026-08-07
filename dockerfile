FROM python:3.13.5-slim

WORKDIR /app

# 1. СНАЧАЛА копируем ТОЛЬКО requirements.txt
COPY requirements.txt .

# 2. Устанавливаем зависимости
# --trusted-host: локальная сборка идёт за TLS-инспекцией Kaspersky (подменяет сертификат pypi.org),
# из-за чего pip не может проверить цепочку доверия
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# 3. И ТОЛЬКО ПОТОМ копируем весь остальной код
COPY . .

ENTRYPOINT ["streamlit", "run", "src/app.py", "--server.port=8501", "--server.address=0.0.0.0"]