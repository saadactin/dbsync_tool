"""
MongoDB database connector implementation.

Day 1 scope: connection test + database listing. SQL-shaped operations are
explicitly not supported and will raise NotImplementedError.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Set
from urllib.parse import quote_plus

from .base import DBConnector, ColumnInfo
from core.exceptions import DatabaseConnectionError
from core.mongo_document_codec import normalize_mongo_value, sanitize_mongo_key

logger = logging.getLogger(__name__)


SYSTEM_DATABASES = {"admin", "local", "config"}
DEFAULT_SAMPLE_SIZE = 200


class MongoDBConnector(DBConnector):
    """MongoDB connector (pymongo-based)."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        database_name: Optional[str] = None,
    ):
        super().__init__(host, port, username, password, database_name)
        self._client = None

    def connect(self):
        """Create MongoClient and validate connectivity via ping."""
        try:
            from pymongo import MongoClient  # type: ignore
            from pymongo.errors import PyMongoError  # type: ignore
        except Exception as e:  # pragma: no cover - environment-specific
            raise DatabaseConnectionError(
                "MongoDB connector not available. Install pymongo."
            ) from e

        try:
            auth_user = (self.username or "").strip()
            auth_pass = self.password if self.password is not None else ""
            host_value = (self.host or "").strip()
            host_lower = host_value.lower()

            # MongoDB Atlas typically provides SRV hosts (*.mongodb.net) that should be
            # resolved via mongodb+srv:// URI mode instead of host+port socket mode.
            use_uri_mode = host_lower.startswith("mongodb+srv://") or host_lower.startswith("mongodb://")
            use_atlas_srv = (
                not use_uri_mode
                and host_lower.endswith(".mongodb.net")
                and host_lower not in {"localhost", "127.0.0.1", "::1"}
            )

            if use_uri_mode or use_atlas_srv:
                if use_uri_mode:
                    mongo_uri = host_value
                    self._client = MongoClient(
                        mongo_uri,
                        serverSelectionTimeoutMS=10_000,
                        connectTimeoutMS=10_000,
                        socketTimeoutMS=10_000,
                    )
                else:
                    # Build URI from host + credentials captured in the form.
                    if not auth_user or not auth_pass:
                        raise DatabaseConnectionError(
                            "MongoDB Atlas requires username and password."
                        )
                    encoded_user = quote_plus(auth_user)
                    encoded_pass = quote_plus(auth_pass)
                    requested_auth_db = (self.database_name or "").strip()
                    candidate_auth_dbs: List[str] = []
                    if requested_auth_db:
                        candidate_auth_dbs.append(requested_auth_db)
                    if "admin" not in {db.lower() for db in candidate_auth_dbs}:
                        candidate_auth_dbs.append("admin")

                    last_auth_error: Optional[Exception] = None
                    for auth_db in candidate_auth_dbs:
                        mongo_uri = (
                            f"mongodb+srv://{encoded_user}:{encoded_pass}@{host_value}/"
                            f"?retryWrites=true&w=majority&authSource={quote_plus(auth_db)}"
                        )
                        try:
                            self._client = MongoClient(
                                mongo_uri,
                                serverSelectionTimeoutMS=10_000,
                                connectTimeoutMS=10_000,
                                socketTimeoutMS=10_000,
                            )
                            self._client.admin.command("ping")
                            self._connection = self._client
                            return self._client
                        except PyMongoError as e:
                            # Keep trying on auth failures; report final error if all fail.
                            last_auth_error = e
                            try:
                                if self._client:
                                    self._client.close()
                            except Exception:
                                pass
                            self._client = None
                            continue

                    if last_auth_error:
                        raise last_auth_error
                    raise DatabaseConnectionError("Connection failed: unable to authenticate.")
            else:
                # Host/port mode for local/self-hosted MongoDB deployments.
                client_kwargs: Dict[str, Any] = {
                    "host": host_value,
                    "port": int(self.port) if self.port is not None else 27017,
                    "serverSelectionTimeoutMS": 10_000,
                    "connectTimeoutMS": 10_000,
                    "socketTimeoutMS": 10_000,
                }
                if auth_user or auth_pass:
                    # MongoDB authenticates against an "authentication database" (authSource).
                    # `root` and most admin users are defined in `admin`.
                    # The UI "Database Name" is the *target database* to browse/sync, not necessarily the auth DB.
                    # For `root`/`admin`, always use `admin` to avoid auth failures when a non-admin database is selected.
                    u_lower = auth_user.lower()
                    if u_lower in {"root", "admin"}:
                        auth_db = "admin"
                    else:
                        auth_db = (self.database_name or "").strip() or "admin"
                    client_kwargs["username"] = auth_user or None
                    client_kwargs["password"] = auth_pass
                    client_kwargs["authSource"] = auth_db
                self._client = MongoClient(**client_kwargs)

            # Validate connectivity.
            self._client.admin.command("ping")
            self._connection = self._client
            return self._client
        except PyMongoError as e:
            msg = str(e).strip() or "Unknown MongoDB error"
            raise DatabaseConnectionError(f"Connection failed: {msg}") from e
        except Exception as e:
            raise DatabaseConnectionError(f"Connection failed: {str(e)}") from e

    def test_connection(self) -> bool:
        """Test MongoDB connection by pinging server."""
        try:
            client = self.connect()
            # If connect succeeds, ping already passed.
            try:
                client.close()
            except Exception:
                pass
            return True
        except DatabaseConnectionError:
            raise
        except Exception as e:
            raise DatabaseConnectionError(f"Connection test failed: {str(e)}") from e

    def list_databases(self) -> List[str]:
        """List non-system databases on the server."""
        if not self._client:
            self.connect()
        try:
            names = list(self._client.list_database_names())
            return sorted([n for n in names if n not in SYSTEM_DATABASES])
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to list databases: {str(e)}") from e

    def get_schemas(self) -> List[str]:
        """MongoDB has databases; we expose them as schemas for UI consistency."""
        return self.list_databases()

    def get_database_size_bytes(self) -> Optional[int]:
        """Return dataSize from dbStats for the configured database."""
        try:
            if not self._client:
                self.connect()
            db_name = self.database_name
            if not db_name:
                return None
            stats = self._client[db_name].command("dbStats")
            value = stats.get("dataSize")
            return int(value) if value is not None else None
        except Exception as e:
            logger.warning(f"Failed to get MongoDB database size: {str(e)}")
            return None

    def get_table_size_bytes(self, schema: str, table: str) -> Optional[int]:
        """Return size (logical BSON bytes) from collStats for a MongoDB collection."""
        try:
            if not self._client:
                self.connect()
            db_name = schema or self.database_name
            if not db_name:
                return None
            stats = self._client[db_name].command("collStats", table)
            value = stats.get("size")
            return int(value) if value is not None else None
        except Exception as e:
            logger.warning(
                f"Failed to get MongoDB collection size for {schema}.{table}: {str(e)}"
            )
            return None

    def get_tables(self, schema: str) -> List[str]:
        """List collections in the given database (schema). Day 1: minimal."""
        if not self._client:
            self.connect()
        try:
            db = self._client[schema]
            return sorted(list(db.list_collection_names()))
        except Exception as e:
            raise DatabaseConnectionError(
                f"Failed to get collections from database '{schema}': {str(e)}"
            ) from e

    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """
        Infer a flat set of fields for a collection by sampling documents.

        Returns logical types suitable for UI mapping and metadata browsing.
        """
        if not self._client:
            self.connect()

        try:
            from bson import ObjectId  # type: ignore
        except Exception:
            ObjectId = None  # type: ignore

        def _sanitize_field_name(path: str) -> str:
            # Convert dot-paths to SQL-safe-ish names used by the mapping UI.
            name = (path or "").strip()
            if not name:
                return name
            return name.replace(".", "_")

        def _flatten(doc: Any, prefix: str = "") -> Dict[str, Any]:
            out: Dict[str, Any] = {}
            if not isinstance(doc, dict):
                return out
            for k, v in doc.items():
                if k is None:
                    continue
                key = str(k)
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(v, dict):
                    out.update(_flatten(v, path))
                else:
                    out[path] = v
            return out

        def _logical_type(v: Any) -> str:
            if v is None:
                return "string"
            if ObjectId is not None and isinstance(v, ObjectId):
                return "string"
            if isinstance(v, bool):
                return "bool"
            if isinstance(v, int) and not isinstance(v, bool):
                return "int"
            if isinstance(v, float):
                return "float"
            # datetime-like
            try:
                from datetime import datetime

                if isinstance(v, datetime):
                    return "datetime"
            except Exception:
                pass
            if isinstance(v, (list, tuple)):
                return "json"
            if isinstance(v, dict):
                return "json"
            if isinstance(v, (bytes, bytearray)):
                return "string"
            return "string"

        # Gather stats by flattened field name.
        observed_count: Dict[str, int] = {}
        type_votes: Dict[str, Dict[str, int]] = {}
        total_docs = 0

        db = self._client[schema]
        coll = db[table]

        cursor = coll.find({}, limit=DEFAULT_SAMPLE_SIZE)
        for doc in cursor:
            total_docs += 1
            flat = _flatten(doc)
            # Ensure _id always included
            if "_id" in doc and "_id" not in flat:
                flat["_id"] = doc.get("_id")

            for path, value in flat.items():
                fname = _sanitize_field_name(path)
                if not fname:
                    continue
                observed_count[fname] = observed_count.get(fname, 0) + 1
                lt = _logical_type(value)
                if fname not in type_votes:
                    type_votes[fname] = {}
                type_votes[fname][lt] = type_votes[fname].get(lt, 0) + 1

        # If collection empty, still return _id as best-effort.
        if total_docs == 0:
            return [
                ColumnInfo(
                    name="_id",
                    data_type="string",
                    is_nullable=False,
                    is_primary_key=True,
                    max_length=None,
                    default_value=None,
                )
            ]

        # Materialize ColumnInfo list.
        fields = sorted(set(observed_count.keys()) | {"_id"})
        cols: List[ColumnInfo] = []
        for f in fields:
            votes = type_votes.get(f) or {}
            # Pick most common logical type.
            chosen = "string"
            if votes:
                chosen = max(votes.items(), key=lambda kv: kv[1])[0]
            is_pk = f == "_id"
            # MongoDB is schemaless; even if sampled docs all contain a field,
            # later docs may omit/null it. Keep non-PK fields nullable for SQL targets.
            is_nullable = not is_pk
            cols.append(
                ColumnInfo(
                    name=f,
                    data_type=chosen,
                    is_nullable=is_nullable,
                    is_primary_key=is_pk,
                    max_length=None,
                    default_value=None,
                )
            )

        return cols

    def fetch_documents_batch(
        self,
        schema: str,
        table: str,
        batch_size: int,
        last_id: Any = None,
    ) -> Tuple[List[Dict[str, Any]], Any]:
        """
        Fetch a batch of documents from a collection using _id keyset pagination.

        Args:
            schema: Mongo database name
            table: Mongo collection name
            batch_size: max number of docs
            last_id: last _id seen (for pagination); pass back the returned last_id
        """
        if not self._client:
            self.connect()

        db = self._client[schema]
        coll = db[table]

        query: Dict[str, Any] = {}
        if last_id is not None:
            query = {"_id": {"$gt": last_id}}

        cursor = coll.find(query).sort("_id", 1).limit(int(batch_size))
        docs = list(cursor)
        new_last = docs[-1].get("_id") if docs else last_id
        return docs, new_last

    def flatten_document_for_sql(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Flatten a Mongo document into a single-level dict using underscore names.

        - Nested objects use underscore join: address.city -> address_city
        - Arrays/objects are JSON-serialized strings for SQL load visibility
        - ObjectId is stringified
        """
        try:
            from bson import ObjectId  # type: ignore
        except Exception:
            ObjectId = None  # type: ignore

        def _sanitize(path: str) -> str:
            return (path or "").replace(".", "_")

        def _to_scalar(v: Any) -> Any:
            if v is None:
                return None
            if ObjectId is not None and isinstance(v, ObjectId):
                return str(v)
            if isinstance(v, (bytes, bytearray)):
                try:
                    return v.decode("utf-8", errors="replace")
                except Exception:
                    return str(v)
            if isinstance(v, (list, tuple, dict)):
                try:
                    return json.dumps(v, default=str, ensure_ascii=False)
                except Exception:
                    return str(v)
            return v

        def _flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
            out: Dict[str, Any] = {}
            if not isinstance(obj, dict):
                return out
            for k, v in obj.items():
                key = str(k)
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(v, dict):
                    out.update(_flatten(v, path))
                else:
                    out[_sanitize(path)] = _to_scalar(v)
            return out

        flat = _flatten(doc)
        if "_id" in doc:
            flat["_id"] = _to_scalar(doc.get("_id"))
        return flat

    def watch_collection(
        self,
        schema: str,
        table: str,
        resume_token: Any = None,
        full_document: str = "updateLookup",
    ):
        """
        Open a Change Stream cursor for a collection.

        Args:
            schema: Mongo database name
            table: Mongo collection name
            resume_token: resume token object previously returned by Change Streams
            full_document: typically 'updateLookup' for correctness on updates
        """
        if not self._client:
            self.connect()

        coll = self._client[schema][table]
        watch_kwargs: Dict[str, Any] = {"full_document": full_document}
        if resume_token is not None:
            # Prefer resumeAfter for simple resume semantics.
            watch_kwargs["resume_after"] = resume_token
        return coll.watch(**watch_kwargs)

    def get_row_count(self, schema: str, table: str) -> int:
        raise NotImplementedError("MongoDBConnector.get_row_count is not supported.")

    def fetch_batch(
        self, query: str, batch_size: int, offset: int = 0, order_by: Optional[str] = None
    ) -> List[Tuple]:
        raise NotImplementedError(
            "MongoDBConnector.fetch_batch does not support SQL queries."
        )

    def get_query_row_count(self, query: str) -> int:
        raise NotImplementedError(
            "MongoDBConnector.get_query_row_count does not support SQL queries."
        )

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        raise NotImplementedError(
            "MongoDBConnector.execute_query does not support SQL queries."
        )

    def create_table(self, schema: str, table: str, columns: List[ColumnInfo]):
        # Mongo creates collections on first write; keep as no-op.
        return None

    def table_exists(self, schema: str, table: str) -> bool:
        if not self._client:
            self.connect()
        try:
            return table in self._client[schema].list_collection_names()
        except Exception:
            return False

    def truncate_table(self, schema: str, table: str):
        if not self._client:
            self.connect()
        self._client[schema][table].delete_many({})
        return None

    def bulk_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]):
        # Interpret bulk_insert as idempotent upsert for MongoDB target.
        docs: List[Dict[str, Any]] = []
        for row in rows:
            doc = {columns[i]: row[i] for i in range(len(columns))}
            docs.append(doc)
        self.bulk_upsert_documents(schema, table, docs)
        return None

    def ensure_schema_exists(self, schema: str):
        # Mongo databases are created lazily on first write; no-op.
        return None

    def get_primary_key(self, schema: str, table: str) -> List[str]:
        raise NotImplementedError("MongoDBConnector.get_primary_key is not supported.")

    def create_table_from_dataframe(self, schema: str, table: str, df):
        raise NotImplementedError(
            "MongoDBConnector.create_table_from_dataframe is not supported."
        )

    def add_missing_columns(self, schema: str, table: str, df):
        # MongoDB is schemaless; nothing to do.
        return None

    def upsert_dataframe(self, schema: str, table: str, df, key_column: str):
        if df is None:
            return None
        if not key_column:
            raise ValueError("key_column is required for MongoDBConnector.upsert_dataframe")

        # Convert rows to documents and use key_column as Mongo _id for idempotency.
        records = df.to_dict(orient="records")
        docs: List[Dict[str, Any]] = []
        for rec in records:
            if key_column not in rec:
                raise ValueError(f"key_column '{key_column}' not present in dataframe row")
            _id = rec.get(key_column)
            if _id is None:
                raise ValueError(f"key_column '{key_column}' contains NULL values")
            doc = dict(rec)
            doc["_id"] = str(_id)
            docs.append(doc)

        self.bulk_upsert_documents(schema, table, docs)
        return None

    def bulk_upsert_documents(self, schema: str, table: str, docs: List[Dict[str, Any]]):
        """Upsert documents into collection by _id."""
        if not self._client:
            self.connect()
        try:
            from pymongo import UpdateOne  # type: ignore
        except Exception as e:
            raise DatabaseConnectionError("MongoDB connector not available. Install pymongo.") from e

        coll = self._client[schema][table]
        ops = []
        for d in docs:
            clean_doc: Dict[str, Any] = {}
            for k, v in (d or {}).items():
                if k == "_id":
                    continue
                clean_doc[sanitize_mongo_key(k)] = normalize_mongo_value(v)
            _id = normalize_mongo_value((d or {}).get("_id"))
            if _id is None:
                # Fall back to a deterministic string id if caller didn't set it.
                _id = json.dumps(clean_doc, default=str, sort_keys=True)
            clean_doc["_id"] = _id
            ops.append(UpdateOne({"_id": _id}, {"$set": clean_doc}, upsert=True))
        if ops:
            coll.bulk_write(ops, ordered=False)
        return None

    def close(self):
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass
        finally:
            self._client = None
            self._connection = None

