FROM python:3.12-slim

# The dashboard proxy uses psql for parameterized, read-only Operations DB
# queries. It does not expose the database port or credentials to the browser.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY local_proxy.py ./

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin svc
USER 10001:10001

EXPOSE 8080
CMD ["python", "local_proxy.py"]
