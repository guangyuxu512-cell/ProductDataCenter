FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
RUN pip install --no-cache-dir .
USER 1026:100
EXPOSE 8180
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8180"]
