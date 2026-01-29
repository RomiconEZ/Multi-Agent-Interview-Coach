# --------- requirements ---------
FROM python:3.11-slim-bookworm as requirements-stage

WORKDIR /tmp
RUN pip install poetry poetry-plugin-export

COPY ./pyproject.toml ./poetry.lock* /tmp/
# Группа web ставит gunicorn/uvicorn/httptools; без неё воркеры живут «полегче»
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes

# --------- final image build ---------
FROM python:3.11-slim-bookworm

WORKDIR /code
RUN mkdir -p /code/logs /code/.pycache

ENV PYTHONPYCACHEPREFIX=/code/.pycache \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=requirements-stage /tmp/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY ./src/app /code/app

# N — сколько ядер не трогаем
ENV RESERVED_CPUS=6

ENTRYPOINT ["sh","-c", "\
  total=$(nproc); \
  reserve=${RESERVED_CPUS}; \
  workers=$(( total > reserve ? total - reserve : 1 )); \
  echo \"[startup] PID $$ — CPUs=$total, reserved=$reserve, gunicorn workers=$workers\"; \
  exec gunicorn -k uvicorn.workers.UvicornWorker \
       --workers ${workers} \
       --threads 2 \
       --worker-connections 1000 \
       -b 0.0.0.0:${BACKEND_PORT} \
       --timeout 1200 \
       --graceful-timeout 600 \
       app.main:app"]