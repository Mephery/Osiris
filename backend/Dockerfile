FROM python:3.11-slim

WORKDIR /app

# Outils systeme requis par le worker (extraction ISO, manipulation WIM)
# innoextract : packs de pilotes Lenovo, livres en installeurs Inno Setup que
# 7z ne sait pas ouvrir (il n'en sort que les ressources PE, aucun pilote).
RUN apt-get update && apt-get install -y --no-install-recommends \
    p7zip-full \
    innoextract \
    xorriso \
    wimtools \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
