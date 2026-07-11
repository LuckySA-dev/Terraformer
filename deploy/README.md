# Deployment files

`compose.yml` is the production-like local stack. Only `web` is published, on
`127.0.0.1:8080` by default. `api`, `postgres`, and `redis` are reachable only
inside their Compose networks.

`compose.dev.yml` is an explicit development override that also publishes API,
PostgreSQL, and Redis on loopback. It does not weaken PostgreSQL authentication
or put credentials in environment variables.

Before either stack can start, run `python deploy/init-secrets.py` from the
repository root. The generated files are ignored by Git and mounted read-only
through Compose secrets. The script never replaces an existing key.

There is deliberately no AI provider, model runtime, or Ollama service in this
phase.
