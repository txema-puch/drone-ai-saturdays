# Dockerfile para el Backend (FastAPI)

# 1. Usar una imagen base de Python ligera
FROM python:3.11-slim

# 2. Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# 3. Instalar 'uv' para manejar las dependencias de Python
RUN pip install uv

# 4. Copiar solo el archivo de dependencias e instalarlas
#    Esto aprovecha el cache de Docker: solo se reinstala si pyproject.toml cambia
COPY pyproject.toml .
RUN uv pip install --system -r pyproject.toml

# 5. Copiar todo el código de la aplicación
COPY . .

# 6. Exponer el puerto que usará FastAPI
EXPOSE 8000

# 7. Comando para iniciar la aplicación con Uvicorn
#    --host 0.0.0.0 es crucial para que sea accesible desde fuera del contenedor
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
