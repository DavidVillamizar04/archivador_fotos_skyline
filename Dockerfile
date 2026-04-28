FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run Jobs ejecuta el contenedor como un proceso que corre y termina.
# No hay servidor HTTP: python main.py es suficiente.
CMD ["python", "main.py"]
