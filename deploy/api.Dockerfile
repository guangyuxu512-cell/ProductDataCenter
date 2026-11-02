FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
RUN pip install --no-cache-dir .
RUN mkdir -p /var/lib/product-category-cache && chown 1026:100 /var/lib/product-category-cache && chmod 700 /var/lib/product-category-cache
USER 1026:100
EXPOSE 8180
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8180"]
