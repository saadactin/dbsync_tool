## MongoDB integration runbook (MongoDB ↔ SQL)

This document describes how to configure and operate MongoDB replication in this project.

### Supported directions and modes

- **MongoDB → SQL**
  - **Full sync**: batch read Mongo documents, flatten, create/extend SQL table, bulk insert
  - **Incremental sync**: Mongo Change Streams (CDC) using **resume tokens**, applied to SQL via upsert/delete
- **SQL → MongoDB**
  - **Full sync**: batch read SQL rows, build documents, upsert into Mongo by `_id`
  - **Incremental sync**: existing watermark-based incremental executor, upserts into Mongo by `_id`

### Connection setup (UI)

Create two `DatabaseConnection` entries from **Connections → Add Connection**:

- **MongoDB connection**
  - **db_type**: `mongodb`
  - **host/port**: default port is `27017`
  - **username/password**: leave both empty if your MongoDB has **no authentication** (common local installs). If you use `root` / `MONGO_INITDB_ROOT_*` (Docker) or similar, the user is almost always stored in the **`admin`** database.
  - **Authentication database (Database Name field)**: this value is sent to PyMongo as **`authSource`**. Leave it empty to default to **`admin`** (correct for `root`). If your user was created in another database, set that name here.

- **SQL connection** (Postgres/MySQL/SQL Server/ClickHouse/Oracle ADW)

### Job setup (UI)

From **Sync Jobs → Create Job**:

- **Step 2 (metadata)**:
  - Mongo **database** is treated as `schema_name`
  - Mongo **collection** is treated as `table_name`
- **Step 3 (mapping)**:
  - Mongo inferred `_id` is **protected** (cannot be excluded)
  - Exclude/rename behaves like SQL
  - Mongo “type override” UI is hidden; target types are mapped automatically

### Runtime behavior

#### MongoDB → SQL (full)

- Documents are flattened using the Mongo connector’s flattening logic.
- SQL DDL is created using inferred Mongo fields.
- If the SQL table already exists and new Mongo fields appear, the engine will **add missing SQL columns** before inserting.

#### MongoDB → SQL (incremental / CDC)

- Uses **Change Streams** with `full_document='updateLookup'`.
- A per-job+db+collection checkpoint (`MongoCdcCheckpoint.resume_token`) is advanced **only after** the SQL apply succeeds.
- Deletes:
  - Respects `SyncJob.no_delete_propagation` (when true, delete events are ignored).
- Schema drift:
  - If a CDC event contains a new field, missing SQL columns are added before upsert.
- Restart safety:
  - A resume-token dedupe guard skips re-applying an event if the incoming token matches the stored token.

#### SQL → MongoDB (full)

- Rows are mapped into documents and upserted to Mongo using `_id`:
  - Prefer SQL single-column primary key for `_id`
  - Otherwise a deterministic hash is used

#### SQL → MongoDB (incremental)

- Uses the existing watermark incremental sync engine.
- When the target is MongoDB, incremental requires **exactly one** upsert key column (stored in `SyncJobTable.incremental_key_columns`).

### Loop prevention (bi-directional “ping-pong”)

If you run Mongo→SQL and SQL→Mongo jobs against the same data, changes can “ping-pong” indefinitely.

Two supported strategies:

- **Recommended (operational)**: choose one direction as authoritative.
- **Optional runtime guard (origin stamping)**:
  - Enable origin stamping by setting environment variable `DBSYNC_STAMP_ORIGIN=1`
  - SQL→Mongo writes stamp documents with `__dbsync_origin_job_id=<job_id>`
  - Mongo→SQL CDC apply skips events whose `fullDocument.__dbsync_origin_job_id` matches the current job’s id (and still advances the resume token)

### Smoke-test scripts (optional, manual)

Scripts live under `dbsync_tool/scripts/` and assume you already created `DatabaseConnection` rows in Django DB.

Environment variables used:

- `MONGO_CONN_NAME`: `DatabaseConnection.name` for MongoDB
- `PG_CONN_NAME`: `DatabaseConnection.name` for Postgres
- `MONGO_DB`: Mongo database name (schema)
- `MONGO_COLL`: Mongo collection name (table)
- `PG_SCHEMA` (optional, default `public`)

Examples:

```bash
set MONGO_CONN_NAME=Mongo
set PG_CONN_NAME=PG
set MONGO_DB=appdb
set MONGO_COLL=users
python dbsync_tool/scripts/run_mongo_postgres_full_e2e.py
```

CDC requires Mongo Change Streams support (replica set/sharded cluster):

```bash
set MONGO_CONN_NAME=Mongo
set PG_CONN_NAME=PG
set MONGO_DB=appdb
set MONGO_COLL=users
python dbsync_tool/scripts/run_mongo_postgres_cdc_e2e.py
```

### Known limitations

- SQL-log CDC (WAL/binlog/CT) is not implemented (SQL incremental is watermark-based).
- Conflict resolution for concurrent bidirectional updates is not implemented.
- Mongo connection config does not currently expose advanced URI features (SRV, authSource, replica set options) via the UI.

