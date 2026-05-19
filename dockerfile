# база - питон 3.10 лёгкий
FROM python:3.10-slim

# метаданные
LABEL maintainer="Игорь Толкачёв <igortolkachov92@gmail.com>"
LABEL description="Поставщики Национального геопортала"

# переменные окружения для питона
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# рабочая директория внутри контейнера
WORKDIR /app

# установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# копирование и установка питон-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# копирование исходного кода
COPY . .

# открытие порта стримлит
EXPOSE 8501

# запуск стримлит
CMD ["streamlit", "run", "src/app.py", "--server.address=0.0.0.0", "--server.port=8501"]