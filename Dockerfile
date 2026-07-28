# Note: For production CI/CD pipelines, it is highly recommended to run dependency 
# vulnerability scanning before building this image.
# Example: `pip install safety && safety check -r requirements.txt`
# Or using pip-audit: `pip install pip-audit && pip-audit -r requirements.txt`

FROM python:3.11-slim

RUN useradd -m appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir pip-audit && \
    pip-audit -r requirements.txt --strict \
        --ignore-vuln PYSEC-2026-95 \
        --ignore-vuln CVE-2026-25516 \
        --ignore-vuln CVE-2026-27156 \
        --ignore-vuln CVE-2026-33332 \
        --ignore-vuln CVE-2026-45553 \
        --ignore-vuln CVE-2026-45554 \
        --ignore-vuln PYSEC-2026-2234 > /tmp/pip-audit.log 2>&1; \
    if [ $? -ne 0 ]; then \
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"; \
        cat /tmp/pip-audit.log; \
        echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"; \
        echo "UNEXPECTED CVE found — investigate before deploying."; \
        echo "If it is a known false-positive, add --ignore-vuln to Dockerfile."; \
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"; \
        exit 1; \
    fi
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
CMD ["python", "main.py"]
