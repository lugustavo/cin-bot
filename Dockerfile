FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py notify.py pin.py bot.py watch.py ./

ENV DATA_DIR=/app/data CONFIG_DIR=/app/config
RUN mkdir -p /app/data

CMD ["python", "watch.py"]
