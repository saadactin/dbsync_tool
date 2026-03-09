MySQL → Oracle ADW: Data Type Mapping & Migration

This document describes how the DB Sync Tool maps MySQL data types to Oracle Autonomous Data Warehouse (ADW) and how the migration pipeline works, including the functions involved.

1. Overview

When syncing MySQL (source) → Oracle ADW (target):

1. Schema Creation

Source column types are mapped to Oracle types using:

map_source_to_oracle_type()

This ensures no data truncation or loss.

Examples:

Large decimals → CLOB

Doubles → BINARY_DOUBLE

2. Table Creation
TableHandler._create_table_oracle_aware()

This function:

Builds the Oracle DDL

Uses mapped types

Creates the table in Oracle

Reuses it if compatible

3. Data Migration

Rows are read from MySQL in batches, then normalized for Oracle:

Examples:

Boolean → 0/1

TIME → datetime

Data insertion happens through:

OracleADWConnector.bulk_insert()
Important Note

The generic mapping matrix:

TYPE_MAPPING

in

core/type_mapping.py

is NOT used for Oracle.

Instead, Oracle uses the dedicated function:

map_source_to_oracle_type()

This avoids issues like:

Oracle precision limits

Float conversion problems

Text truncation

2. MySQL → Oracle ADW Data Type Mapping

Mapping is implemented in:

core/type_mapping.py

Function:

map_source_to_oracle_type(
    source_type,
    source_db,
    max_length=None,
    precision=None,
    scale=None
)
2.1 Numeric Types
MySQL Type	Oracle ADW Type	Notes
INT, INTEGER, INT4, MEDIUMINT	NUMBER(10)	Integer-like
INT UNSIGNED, MEDIUMINT UNSIGNED	NUMBER(10)	
BIGINT, INT8	NUMBER(19)	
BIGINT UNSIGNED	NUMBER(20)	Needs 20 digits
SMALLINT, INT2, TINYINT	NUMBER(5) or NUMBER(19)	Small integers
SMALLINT UNSIGNED, TINYINT UNSIGNED	NUMBER(5)	
DECIMAL, NUMERIC	NUMBER(p,s)	Precision > 38 → CLOB
FLOAT	BINARY_FLOAT	Avoids NUMBER range issues
DOUBLE, DOUBLE PRECISION, REAL	BINARY_DOUBLE	
YEAR	NUMBER(4)	1901–2155
2.2 Character & Text Types
MySQL Type	Oracle ADW Type	Notes
CHAR, VARCHAR, NVARCHAR	VARCHAR2(n)	n > 4000 → CLOB
TEXT, LONGTEXT, MEDIUMTEXT, TINYTEXT	CLOB	
JSON, JSONB	CLOB	
ENUM, SET	CLOB	
2.3 Temporal Types
MySQL Type	Oracle ADW Type	Notes
DATE, DATETIME, TIMESTAMP	TIMESTAMP(6)	
TIMESTAMPTZ	TIMESTAMP(6)	
TIME	TIMESTAMP(6)	Normalized to datetime
2.4 Binary & Other Types
MySQL Type	Oracle ADW Type	Notes
BLOB, LONGBLOB, MEDIUMBLOB, TINYBLOB	BLOB	
BINARY, VARBINARY	BLOB	
BIT	BLOB	Converted to bytes
BOOLEAN, BOOL, TINYINT(1)	NUMBER(1)	Stored as 0/1
GEOMETRY, POINT, LINESTRING	BLOB	Stored as WKB
2.5 Fallback Mapping

If no explicit mapping exists:

Fallback → CLOB

A warning is logged to avoid silent truncation.

3. Functions Used in Mapping & Migration
3.1 normalize_data_type()

File:

core/type_mapping.py

Purpose:

Parses a database type string and extracts:

Base type

Length

Precision

Scale

Return format:

(base_type, max_length, precision, scale)

Handles examples like:

int(11) unsigned
varchar(255)
decimal(10,2)
enum('a','b')

Example:

normalize_data_type('int(11) unsigned', 'mysql')
→ ('INT UNSIGNED', None, None, None)
normalize_data_type('decimal(10,2)', 'mysql')
→ ('DECIMAL', None, 10, 2)
3.2 map_source_to_oracle_type()

File:

core/type_mapping.py

Purpose:

Maps a source database type to its Oracle equivalent.

Example:

map_source_to_oracle_type('BIGINT', 'mysql')
→ NUMBER(19)
map_source_to_oracle_type('DOUBLE', 'mysql')
→ BINARY_DOUBLE
map_source_to_oracle_type('TEXT', 'mysql')
→ CLOB
3.3 _normalize_with_overrides()

File:

core/type_mapping.py

Purpose:

Helper function that:

Calls normalize_data_type()

Applies overrides if provided

Overrides may include:

max_length

precision

scale

Used by:

map_source_to_oracle_type

map_oracle_to_target_type

3.4 TableHandler._create_table_oracle_aware()

File:

sync_engine/table_handler.py

Purpose:

Creates Oracle tables when the source or target database is Oracle.

Workflow

Fetch source columns

source_connector.get_columns()

Normalize source types

normalize_data_type()

Map to Oracle types

map_source_to_oracle_type()

Build column metadata

ColumnInfo

Compare with existing Oracle table

If compatible → reuse
If incompatible → drop & recreate

Create table using:

target_connector.create_table()
3.5 OracleADWConnector._normalize_row()

File:

connections/connectors/oracle_adw.py

Purpose:

Convert Python row values into Oracle-compatible values.

Conversion Rules
Python Value	Oracle Conversion
None	None
bool	1 / 0
timedelta	Converted to datetime
time	datetime with epoch date
bytearray	bytes
set / frozenset	comma-separated string
Decimal (CLOB column)	string
Decimal (NUMBER column)	Decimal
float (BINARY_DOUBLE)	Python float

This prevents errors like:

ORA-00932 (type mismatch)

DPY-4003 (NUMBER overflow)

3.6 OracleADWConnector.bulk_insert()

File:

connections/connectors/oracle_adw.py

Purpose:

Bulk insert rows using:

cursor.executemany()
Parameters
Parameter	Description
schema	Oracle schema
table	Target table
columns	Column list
rows	Data rows
target_column_types	Oracle column types
Insert Flow

Skip if rows empty

Build SQL

INSERT INTO "schema"."table"
(col1,col2,...)
VALUES (:1,:2,...)

Normalize rows

_normalize_row()

Execute

cursor.executemany()

Commit transaction

4. End-to-End Migration Flow
4.1 Full Sync

Flow:

Executor starts sync

executor.py

Table creation

TableHandler.create_table_if_not_exists()

Oracle-aware DDL

_create_table_oracle_aware()

Target table truncated

Source data fetched in batches

source_connector.fetch_batch()

Build target column types

normalize_data_type()
map_source_to_oracle_type()

Insert rows

bulk_insert()
4.2 Incremental Sync

File:

incremental_sync.py

Steps:

Create table if needed

Fetch checkpoint

Run incremental query

Example:

WHERE id > checkpoint

Insert rows using:

bulk_insert()

Note:

Incremental sync currently does not pass target_column_types.

5. File Reference
Component	File	Role
Type Mapping	core/type_mapping.py	normalize_data_type(), map_source_to_oracle_type()
Table Creation	sync_engine/table_handler.py	Oracle-aware DDL
Full Sync	sync_engine/full_sync.py	Builds target_column_types
Row Normalization	connections/connectors/oracle_adw.py	_normalize_row()
Bulk Insert	connections/connectors/oracle_adw.py	executemany()
Incremental Sync	sync_engine/incremental_sync.py	Incremental pipeline
6. Summary

Type Mapping

MySQL → Oracle mapping is handled by:

map_source_to_oracle_type()

with type parsing done by:

normalize_data_type()

Table Creation

Handled by:

TableHandler._create_table_oracle_aware()

which builds Oracle DDL using mapped types.

Data Migration

MySQL rows fetched in batches

Oracle column types generated

Rows normalized with _normalize_row()

Inserted using executemany().

Result

The pipeline ensures:

No silent truncation

No precision loss

No Oracle type errors

Common errors avoided:

ORA-00932

DPY-4003