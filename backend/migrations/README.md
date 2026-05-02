# Database Migrations

In **development** the app calls `Base.metadata.create_all()` at startup,
which is fine for tearing things down and rebuilding. In **production**
that's dangerous — schema drift between code and DB silently happens.

So in production we use Alembic. Workflow:

## Initial setup (already done — for reference)

```bash
cd backend
alembic init migrations            # only run once, ever — creates this folder
# Then edit env.py + alembic.ini per project conventions.
```

## Creating a new migration

When you change a SQLAlchemy table in `app/db/tables/`, generate a migration:

```bash
cd backend
alembic revision --autogenerate -m "add some_column to users"
```

Alembic will diff the metadata against the current DB and write a Python
file under `migrations/versions/`. **Always read the generated file** —
autogenerate is not perfect (it misses constraint name changes, server
defaults, etc.).

## Applying migrations

```bash
# Apply everything
alembic upgrade head

# Apply one step
alembic upgrade +1

# Roll back one step
alembic downgrade -1

# Show current version
alembic current

# Show full history
alembic history
```

## Production deployment

Run migrations as part of deploy, BEFORE starting new app containers:

```bash
# On the EC2 box, against the RDS instance:
docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml \
    run --rm backend alembic upgrade head

# Then restart the app:
docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml \
    up -d backend
```

Or use the Makefile target: `make migrate-prod`.

## First-time bootstrap

On a fresh database (RDS just created, no tables yet):

```bash
alembic upgrade head    # creates everything from scratch via migrations
```

If you want to "stamp" an existing DB that already has the tables (e.g.
because dev mode created them), tell Alembic the current state:

```bash
alembic stamp head      # marks the DB as fully migrated; no SQL run
```

Then future `alembic revision --autogenerate` calls will diff against
the live state correctly.