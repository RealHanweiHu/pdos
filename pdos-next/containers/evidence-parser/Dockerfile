# Build script supplies the verified immutable digest of the official Python base.
ARG PYTHON_BASE
FROM ${PYTHON_BASE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY wheels /app/wheels
RUN python -m pip install --no-index --find-links=/app/wheels --no-cache-dir --disable-pip-version-check -r /app/requirements.txt && rm -rf /app/wheels
COPY pdos_next /app/pdos_next
COPY parser_worker.py /app/parser_worker.py
RUN chmod -R a-w /app && chmod -R a+rX /app
USER 65532:65532
ENTRYPOINT ["python", "-I", "-B", "/app/parser_worker.py"]
