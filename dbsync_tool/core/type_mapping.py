"""
Centralized data type mapping system for cross-database synchronization
"""
from typing import Dict, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class SourceDBType(Enum):
    POSTGRES = 'postgres'
    MYSQL = 'mysql'
    SQLSERVER = 'sqlserver'
    CLICKHOUSE = 'clickhouse'  # NEW

class TargetDBType(Enum):
    POSTGRES = 'postgres'
    MYSQL = 'mysql'
    SQLSERVER = 'sqlserver'
    CLICKHOUSE = 'clickhouse'  # NEW

# Comprehensive type mapping dictionary
TYPE_MAPPING: Dict[str, Dict[str, Dict[str, str]]] = {
    'mongodb': {
        'postgres': {
            'string': 'TEXT',
            'int': 'BIGINT',
            'float': 'DOUBLE PRECISION',
            'bool': 'BOOLEAN',
            'datetime': 'TIMESTAMP',
            'json': 'JSONB',
        },
        'mysql': {
            'string': 'TEXT',
            'int': 'BIGINT',
            'float': 'DOUBLE',
            'bool': 'TINYINT(1)',
            'datetime': 'DATETIME',
            'json': 'JSON',
        },
        'sqlserver': {
            'string': 'NVARCHAR(MAX)',
            'int': 'BIGINT',
            'float': 'FLOAT',
            'bool': 'BIT',
            'datetime': 'DATETIME2',
            'json': 'NVARCHAR(MAX)',
        },
        'clickhouse': {
            'string': 'String',
            'int': 'Int64',
            'float': 'Float64',
            'bool': 'UInt8',
            'datetime': 'DateTime',
            'json': 'String',
        },
    },
    'postgres': {
        'mysql': {
            'int4': 'INT',
            'integer': 'INT',
            'bigint': 'BIGINT',
            'smallint': 'SMALLINT',
            'serial': 'INT AUTO_INCREMENT',
            'bigserial': 'BIGINT AUTO_INCREMENT',
            'varchar': 'VARCHAR',
            'character varying': 'VARCHAR',
            'text': 'TEXT',
            'char': 'CHAR',
            'timestamp without time zone': 'DATETIME',
            'timestamp with time zone': 'DATETIME',
            'timestamp': 'DATETIME',
            'date': 'DATE',
            'time': 'TIME',
            'boolean': 'BOOLEAN',
            'bool': 'TINYINT(1)',
            'numeric': 'DECIMAL',
            'decimal': 'DECIMAL',
            'double precision': 'DOUBLE',
            'real': 'FLOAT',
            'json': 'JSON',
            'jsonb': 'JSON',
            'uuid': 'CHAR(36)',
            'bytea': 'BLOB',
        },
        'sqlserver': {
            'int4': 'INT',
            'integer': 'INT',
            'bigint': 'BIGINT',
            'smallint': 'SMALLINT',
            'serial': 'INT IDENTITY(1,1)',
            'bigserial': 'BIGINT IDENTITY(1,1)',
            'varchar': 'NVARCHAR',
            'character varying': 'NVARCHAR',
            'text': 'NVARCHAR(MAX)',
            'char': 'NCHAR',
            'timestamp without time zone': 'DATETIME2',
            'timestamp with time zone': 'DATETIME2',
            'timestamp': 'DATETIME2',
            'date': 'DATE',
            'time': 'TIME',
            'boolean': 'BIT',
            'bool': 'BIT',
            'numeric': 'DECIMAL',
            'decimal': 'DECIMAL',
            'double precision': 'FLOAT',
            'real': 'REAL',
            'json': 'NVARCHAR(MAX)',
            'jsonb': 'NVARCHAR(MAX)',
            'uuid': 'UNIQUEIDENTIFIER',
            'bytea': 'VARBINARY(MAX)',
        },
        'clickhouse': {
            # Integers
            'int4': 'Int32',
            'integer': 'Int32',
            'bigint': 'Int64',
            'int8': 'Int64',
            'smallint': 'Int16',
            'int2': 'Int16',
            'serial': 'Int32',
            'bigserial': 'Int64',

            # Strings
            'varchar': 'String',
            'character varying': 'String',
            'text': 'String',
            'char': 'FixedString',
            'bpchar': 'String',  # CHAR without length

            # Timestamps with microsecond precision
            'timestamp without time zone': "DateTime64(6, 'UTC')",
            'timestamp with time zone': "DateTime64(6, 'UTC')",
            'timestamp': "DateTime64(6, 'UTC')",
            'timestamptz': "DateTime64(6, 'UTC')",

            # Dates and times
            'date': 'Date32',
            'time': 'String',
            'time without time zone': 'String',
            'time with time zone': 'String',
            'timetz': 'String',
            'interval': 'String',

            # Decimals and money
            'numeric': 'Decimal',
            'decimal': 'Decimal',
            'money': 'Decimal(19,4)',

            # Floating point
            'double precision': 'Float64',
            'real': 'Float32',
            'float4': 'Float32',
            'float8': 'Float64',

            # Boolean
            'boolean': 'UInt8',
            'bool': 'UInt8',

            # JSON
            'json': 'String',
            'jsonb': 'String',

            # UUID
            'uuid': 'UUID',

            # Binary
            'bytea': 'String',

            # Network types
            'inet': 'IPv6',  # Can store both IPv4 and IPv6
            'cidr': 'String',
            'macaddr': 'UInt64',  # Store as integer
            'macaddr8': 'String',

            # Geometric types (stored as WKT - Well-Known Text)
            'point': 'Tuple(Float64, Float64)',
            'line': 'String',
            'lseg': 'String',
            'box': 'String',
            'path': 'String',
            'polygon': 'String',
            'circle': 'String',

            # Range types
            'int4range': 'String',
            'int8range': 'String',
            'numrange': 'String',
            'tsrange': 'String',
            'tstzrange': 'String',
            'daterange': 'String',

            # Array types (handled dynamically in code)
            'array': 'Array',  # Placeholder, actual type determined at runtime

            # HSTORE (key-value)
            'hstore': 'Map(String, String)',

            # Bit strings
            'bit': 'String',
            'bit varying': 'String',
            'varbit': 'String',

            # Text search
            'tsvector': 'String',
            'tsquery': 'String',

            # XML
            'xml': 'String',
        },
    },
    'mysql': {
        'postgres': {
            'INT': 'INTEGER',
            'INTEGER': 'INTEGER',
            'BIGINT': 'BIGINT',
            'SMALLINT': 'SMALLINT',
            'TINYINT': 'SMALLINT',
            'MEDIUMINT': 'INTEGER',
            'INT UNSIGNED': 'BIGINT',
            'BIGINT UNSIGNED': 'NUMERIC(20)',
            'SMALLINT UNSIGNED': 'INTEGER',
            'TINYINT UNSIGNED': 'INTEGER',
            'MEDIUMINT UNSIGNED': 'INTEGER',
            'INT AUTO_INCREMENT': 'SERIAL',
            'BIGINT AUTO_INCREMENT': 'BIGSERIAL',
            'VARCHAR': 'VARCHAR',
            'CHAR': 'CHAR',
            'TEXT': 'TEXT',
            'LONGTEXT': 'TEXT',
            'MEDIUMTEXT': 'TEXT',
            'TINYTEXT': 'TEXT',
            'DATETIME': 'TIMESTAMP',
            'DATE': 'DATE',
            'TIME': 'TIME',
            'TIMESTAMP': 'TIMESTAMP',
            'YEAR': 'INTEGER',
            'BOOLEAN': 'BOOLEAN',
            'BOOL': 'BOOLEAN',
            'TINYINT(1)': 'BOOLEAN',
            'DECIMAL': 'NUMERIC',
            'NUMERIC': 'NUMERIC',
            'DOUBLE': 'DOUBLE PRECISION',
            'DOUBLE PRECISION': 'DOUBLE PRECISION',
            'REAL': 'REAL',
            'FLOAT': 'REAL',
            'BIT': 'BYTEA',
            'JSON': 'JSONB',
            'BLOB': 'BYTEA',
            'LONGBLOB': 'BYTEA',
            'MEDIUMBLOB': 'BYTEA',
            'TINYBLOB': 'BYTEA',
            'BINARY': 'BYTEA',
            'VARBINARY': 'BYTEA',
            'ENUM': 'TEXT',
            'SET': 'TEXT',
            'GEOMETRY': 'BYTEA',
            'POINT': 'BYTEA',
            'LINESTRING': 'BYTEA',
            'POLYGON': 'BYTEA',
            'MULTIPOINT': 'BYTEA',
            'MULTILINESTRING': 'BYTEA',
            'MULTIPOLYGON': 'BYTEA',
            'GEOMETRYCOLLECTION': 'BYTEA',
        },
        'sqlserver': {
            'INT': 'INT',
            'INTEGER': 'INT',
            'BIGINT': 'BIGINT',
            'SMALLINT': 'SMALLINT',
            'TINYINT': 'TINYINT',
            'MEDIUMINT': 'INT',
            'INT UNSIGNED': 'BIGINT',
            'BIGINT UNSIGNED': 'BIGINT',
            'SMALLINT UNSIGNED': 'INT',
            'TINYINT UNSIGNED': 'TINYINT',
            'MEDIUMINT UNSIGNED': 'INT',
            'INT AUTO_INCREMENT': 'INT IDENTITY(1,1)',
            'BIGINT AUTO_INCREMENT': 'BIGINT IDENTITY(1,1)',
            'VARCHAR': 'NVARCHAR',
            'CHAR': 'NCHAR',
            'TEXT': 'NVARCHAR(MAX)',
            'LONGTEXT': 'NVARCHAR(MAX)',
            'MEDIUMTEXT': 'NVARCHAR(MAX)',
            'TINYTEXT': 'NVARCHAR(MAX)',
            'DATETIME': 'DATETIME2',
            'DATE': 'DATE',
            'TIME': 'TIME',
            'TIMESTAMP': 'DATETIME2',
            'YEAR': 'INT',
            'BOOLEAN': 'BIT',
            'BOOL': 'BIT',
            'TINYINT(1)': 'BIT',
            'DECIMAL': 'DECIMAL',
            'NUMERIC': 'NUMERIC',
            'DOUBLE': 'FLOAT',
            'DOUBLE PRECISION': 'FLOAT',
            'REAL': 'REAL',
            'FLOAT': 'REAL',
            'BIT': 'VARBINARY(MAX)',
            'JSON': 'NVARCHAR(MAX)',
            'BLOB': 'VARBINARY(MAX)',
            'LONGBLOB': 'VARBINARY(MAX)',
            'MEDIUMBLOB': 'VARBINARY(MAX)',
            'TINYBLOB': 'VARBINARY(MAX)',
            'BINARY': 'BINARY',
            'VARBINARY': 'VARBINARY(MAX)',
            'ENUM': 'NVARCHAR(MAX)',
            'SET': 'NVARCHAR(MAX)',
            'GEOMETRY': 'VARBINARY(MAX)',
            'POINT': 'VARBINARY(MAX)',
            'LINESTRING': 'VARBINARY(MAX)',
            'POLYGON': 'VARBINARY(MAX)',
            'MULTIPOINT': 'VARBINARY(MAX)',
            'MULTILINESTRING': 'VARBINARY(MAX)',
            'MULTIPOLYGON': 'VARBINARY(MAX)',
            'GEOMETRYCOLLECTION': 'VARBINARY(MAX)',
        },
        'clickhouse': {
            'INT': 'Int32',
            'INTEGER': 'Int32',
            'BIGINT': 'Int64',
            'SMALLINT': 'Int16',
            'TINYINT': 'Int8',
            'MEDIUMINT': 'Int32',
            'INT UNSIGNED': 'UInt32',
            'BIGINT UNSIGNED': 'UInt64',
            'SMALLINT UNSIGNED': 'UInt16',
            'TINYINT UNSIGNED': 'UInt8',
            'MEDIUMINT UNSIGNED': 'UInt32',
            'INT AUTO_INCREMENT': 'Int32',
            'BIGINT AUTO_INCREMENT': 'Int64',
            'VARCHAR': 'String',
            'CHAR': 'FixedString',
            'TEXT': 'String',
            'LONGTEXT': 'String',
            'MEDIUMTEXT': 'String',
            'TINYTEXT': 'String',
            'DATETIME': 'DateTime',
            'DATE': 'Date',
            'TIME': 'String',
            'TIMESTAMP': 'DateTime',
            'YEAR': 'Int16',
            'BOOLEAN': 'UInt8',
            'BOOL': 'UInt8',
            'TINYINT(1)': 'UInt8',
            'DECIMAL': 'Decimal',
            'NUMERIC': 'Decimal',
            'DOUBLE': 'Float64',
            'DOUBLE PRECISION': 'Float64',
            'REAL': 'Float32',
            'FLOAT': 'Float32',
            'BIT': 'String',
            'JSON': 'String',
            'BLOB': 'String',
            'LONGBLOB': 'String',
            'MEDIUMBLOB': 'String',
            'TINYBLOB': 'String',
            'BINARY': 'String',
            'VARBINARY': 'String',
            'ENUM': 'String',
            'SET': 'String',
            'GEOMETRY': 'String',
            'POINT': 'String',
            'LINESTRING': 'String',
            'POLYGON': 'String',
            'MULTIPOINT': 'String',
            'MULTILINESTRING': 'String',
            'MULTIPOLYGON': 'String',
            'GEOMETRYCOLLECTION': 'String',
        },
    },
    'sqlserver': {
        'postgres': {
            'INT': 'INTEGER',
            'BIGINT': 'BIGINT',
            'SMALLINT': 'SMALLINT',
            'TINYINT': 'SMALLINT',
            'INT IDENTITY(1,1)': 'SERIAL',
            'BIGINT IDENTITY(1,1)': 'BIGSERIAL',
            'NVARCHAR': 'VARCHAR',
            'VARCHAR': 'VARCHAR',
            'NCHAR': 'CHAR',
            'CHAR': 'CHAR',
            'NVARCHAR(MAX)': 'TEXT',
            'TEXT': 'TEXT',
            'NTEXT': 'TEXT',
            'DATETIME2': 'TIMESTAMP',
            'DATETIME': 'TIMESTAMP',
            'DATETIMEOFFSET': 'TIMESTAMP WITH TIME ZONE',
            'DATE': 'DATE',
            'TIME': 'TIME',
            'SMALLDATETIME': 'TIMESTAMP',
            'BIT': 'BOOLEAN',
            'DECIMAL': 'NUMERIC',
            'NUMERIC': 'NUMERIC',
            'FLOAT': 'DOUBLE PRECISION',
            'REAL': 'REAL',
            'MONEY': 'NUMERIC(19,4)',
            'SMALLMONEY': 'NUMERIC(10,4)',
            'UNIQUEIDENTIFIER': 'UUID',
            'VARBINARY(MAX)': 'BYTEA',
            'VARBINARY': 'BYTEA',
            'BINARY': 'BYTEA',
            'IMAGE': 'BYTEA',
            'GEOGRAPHY': 'TEXT',
            'GEOMETRY': 'TEXT',
            'HIERARCHYID': 'TEXT',
            'XML': 'TEXT',
            'SQL_VARIANT': 'TEXT',
            'TIMESTAMP': 'BYTEA',
            'ROWVERSION': 'BYTEA',
        },
        'mysql': {
            'INT': 'INT',
            'BIGINT': 'BIGINT',
            'SMALLINT': 'SMALLINT',
            'TINYINT': 'TINYINT',
            'INT IDENTITY(1,1)': 'INT AUTO_INCREMENT',
            'BIGINT IDENTITY(1,1)': 'BIGINT AUTO_INCREMENT',
            'NVARCHAR': 'VARCHAR',
            'VARCHAR': 'VARCHAR',
            'NCHAR': 'CHAR',
            'CHAR': 'CHAR',
            'NVARCHAR(MAX)': 'LONGTEXT',
            'TEXT': 'TEXT',
            'NTEXT': 'LONGTEXT',
            'DATETIME2': 'DATETIME',
            'DATETIME': 'DATETIME',
            'DATE': 'DATE',
            'TIME': 'TIME',
            'SMALLDATETIME': 'DATETIME',
            'BIT': 'TINYINT(1)',
            'DECIMAL': 'DECIMAL',
            'NUMERIC': 'NUMERIC',
            'FLOAT': 'DOUBLE',
            'REAL': 'FLOAT',
            'MONEY': 'DECIMAL(19,4)',
            'SMALLMONEY': 'DECIMAL(10,4)',
            'UNIQUEIDENTIFIER': 'CHAR(36)',
            'VARBINARY(MAX)': 'LONGBLOB',
            'VARBINARY': 'BLOB',
            'BINARY': 'BINARY',
            'IMAGE': 'LONGBLOB',
        },
        'clickhouse': {
            'INT': 'Int32',
            'BIGINT': 'Int64',
            'SMALLINT': 'Int16',
            'TINYINT': 'Int8',
            'INT IDENTITY(1,1)': 'Int32',
            'BIGINT IDENTITY(1,1)': 'Int64',
            'NVARCHAR': 'String',
            'VARCHAR': 'String',
            'NCHAR': 'FixedString',
            'CHAR': 'FixedString',
            'NVARCHAR(MAX)': 'String',
            'TEXT': 'String',
            'NTEXT': 'String',
            'DATETIME2': 'DateTime64',
            'DATETIME': 'DateTime',
            'DATE': 'Date',
            'TIME': 'String',
            'SMALLDATETIME': 'DateTime',
            'BIT': 'UInt8',
            'DECIMAL': 'Decimal',
            'NUMERIC': 'Decimal',
            'FLOAT': 'Float64',
            'REAL': 'Float32',
            'MONEY': 'Decimal(19,4)',
            'SMALLMONEY': 'Decimal(10,4)',
            'UNIQUEIDENTIFIER': 'UUID',
            'VARBINARY(MAX)': 'String',
            'VARBINARY': 'String',
            'BINARY': 'FixedString',
            'IMAGE': 'String',
            'DATETIMEOFFSET': 'DateTime64',
            'HIERARCHYID': 'String',
            'GEOMETRY': 'String',
            'GEOGRAPHY': 'String',
            'TIMESTAMP': 'String',
            'ROWVERSION': 'String',
            'SQL_VARIANT': 'String',
            'XML': 'String',
        },
    },
    'clickhouse': {
        'postgres': {
            'Int8': 'SMALLINT',
            'Int16': 'SMALLINT',
            'Int32': 'INTEGER',
            'Int64': 'BIGINT',
            'UInt8': 'SMALLINT',
            'UInt16': 'INTEGER',
            'UInt32': 'BIGINT',
            'UInt64': 'BIGINT',
            'Float32': 'REAL',
            'Float64': 'DOUBLE PRECISION',
            'String': 'TEXT',
            'FixedString': 'CHAR',
            'Date': 'DATE',
            'Date32': 'DATE',
            'DateTime': 'TIMESTAMP',
            'DateTime64': 'TIMESTAMP',
            'Decimal': 'NUMERIC',
            'UUID': 'UUID',
        },
        'mysql': {
            'Int8': 'TINYINT',
            'Int16': 'SMALLINT',
            'Int32': 'INT',
            'Int64': 'BIGINT',
            'UInt8': 'TINYINT',
            'UInt16': 'SMALLINT',
            'UInt32': 'INT',
            'UInt64': 'BIGINT',
            'Float32': 'FLOAT',
            'Float64': 'DOUBLE',
            'String': 'TEXT',
            'FixedString': 'CHAR',
            'Date': 'DATE',
            'Date32': 'DATE',
            'DateTime': 'DATETIME',
            'DateTime64': 'DATETIME',
            'Decimal': 'DECIMAL',
            'UUID': 'CHAR(36)',
        },
        'sqlserver': {
            'Int8': 'TINYINT',
            'Int16': 'SMALLINT',
            'Int32': 'INT',
            'Int64': 'BIGINT',
            'UInt8': 'TINYINT',
            'UInt16': 'SMALLINT',
            'UInt32': 'INT',
            'UInt64': 'BIGINT',
            'Float32': 'REAL',
            'Float64': 'FLOAT',
            'String': 'NVARCHAR(MAX)',
            'FixedString': 'NCHAR',
            'Date': 'DATE',
            'Date32': 'DATE',
            'DateTime': 'DATETIME2',
            'DateTime64': 'DATETIME2',
            'Decimal': 'DECIMAL',
            'UUID': 'UNIQUEIDENTIFIER',
        },
    },
}

def map_data_type(
    source_type: str,
    source_db: str,
    target_db: str,
    max_length: Optional[int] = None,
    precision: Optional[int] = None,
    scale: Optional[int] = None
) -> str:
    """
    Map data type from source database to target database
    
    Args:
        source_type: Source data type name (e.g., 'varchar', 'INT', 'NVARCHAR(255)')
        source_db: Source database type ('postgres', 'mysql', 'sqlserver', 'clickhouse')
        target_db: Target database type ('postgres', 'mysql', 'sqlserver', 'clickhouse')
        max_length: Optional maximum length for VARCHAR/CHAR types
        precision: Optional precision for NUMERIC/DECIMAL types
        scale: Optional scale for NUMERIC/DECIMAL types
    
    Returns:
        Mapped data type string for target database
    
    Raises:
        ValueError: If source_db or target_db is invalid
    """
    if source_db not in ['postgres', 'mysql', 'sqlserver', 'clickhouse', 'mongodb']:
        raise ValueError(f"Invalid source database type: {source_db}")
    if target_db not in ['postgres', 'mysql', 'sqlserver', 'clickhouse', 'mongodb']:
        raise ValueError(f"Invalid target database type: {target_db}")
    
    if source_db == target_db:
        # Same database type, return as-is with length if applicable
        if max_length and ('varchar' in source_type.lower() or 'char' in source_type.lower()):
            # Extract base type if it already has length
            base_type = source_type.split('(')[0]
            return f"{base_type}({max_length})"
        return source_type
    
    # Normalize source type - extract base type and remove length/precision
    # Handle ClickHouse Nullable types: strip Nullable() wrapper
    source_type_normalized = source_type.upper().strip()
    if source_type_normalized.startswith('NULLABLE(') and source_type_normalized.endswith(')'):
        # Extract inner type from Nullable(Type)
        inner_type = source_type_normalized[9:-1].strip()
        source_type_normalized = inner_type
    
    # Remove length/precision from type string (e.g., "VARCHAR(255)" -> "VARCHAR")
    if '(' in source_type_normalized:
        base_type = source_type_normalized.split('(')[0].strip()
    else:
        base_type = source_type_normalized
    
    # Get mapping dictionary
    source_mappings = TYPE_MAPPING.get(source_db, {})
    target_mapping = source_mappings.get(target_db, {})
    
    # Try exact match first (with full type string including parentheses) - case insensitive
    mapped_type = None
    for key, value in target_mapping.items():
        if key.upper() == source_type_normalized:
            mapped_type = value
            break
    
    if not mapped_type:
        # Try exact match with base type - case insensitive
        for key, value in target_mapping.items():
            if key.upper() == base_type:
                mapped_type = value
                break
    
    if not mapped_type:
        # Try case-insensitive exact match first
        base_type_upper = base_type.upper()
        for key, value in target_mapping.items():
            if key.upper() == base_type_upper:
                mapped_type = value
                break
        
        # If still not found, try case-insensitive partial match, but prefer longer/more specific matches
        if not mapped_type:
            # Sort keys by length (longest first) to prefer more specific matches
            sorted_keys = sorted(target_mapping.keys(), key=len, reverse=True)
            for key in sorted_keys:
                key_upper = key.upper()
                # Check if key matches base_type exactly
                if key_upper == base_type_upper:
                    mapped_type = target_mapping[key]
                    break
                # Check if base_type starts with key (e.g., "DATETIME2" starts with "DATETIME")
                elif base_type_upper.startswith(key_upper):
                    mapped_type = target_mapping[key]
                    break
                # Check if key starts with base_type (e.g., "TINYINT(1)" starts with "TINYINT")
                elif key_upper.startswith(base_type_upper):
                    mapped_type = target_mapping[key]
                    break
    
    # Default fallback
    if not mapped_type:
        logger.warning(
            f"No mapping found for {source_type} from {source_db} to {target_db}, "
            f"using fallback type"
        )
        if target_db == 'postgres':
            mapped_type = 'TEXT'
        elif target_db == 'mysql':
            mapped_type = 'TEXT'
        elif target_db == 'sqlserver':
            mapped_type = 'NVARCHAR(MAX)'
        elif target_db == 'clickhouse':
            mapped_type = 'String'
        else:
            mapped_type = 'TEXT'
    
    # SQL Server reports varchar(max)/nvarchar(max) with max_length=-1.
    # That must never be rendered as VARCHAR(-1) on target databases.
    source_type_upper = source_type_normalized.upper()
    has_unbounded_length = (
        isinstance(max_length, int) and max_length < 0
    ) or ("(MAX)" in source_type_upper)

    if has_unbounded_length and (
        "VARCHAR" in mapped_type.upper()
        or "NVARCHAR" in mapped_type.upper()
        or "CHAR" in mapped_type.upper()
        or "NCHAR" in mapped_type.upper()
    ):
        logger.info(
            "Unbounded character type detected during mapping: source_type=%s source_db=%s "
            "target_db=%s max_length=%s -> coercing to unbounded-safe target type.",
            source_type,
            source_db,
            target_db,
            max_length,
        )
        if target_db == "postgres":
            mapped_type = "TEXT"
        elif target_db == "mysql":
            mapped_type = "TEXT"
        elif target_db == "sqlserver":
            mapped_type = "NVARCHAR(MAX)"
        elif target_db == "clickhouse":
            mapped_type = "String"

    # Apply length constraints only for valid positive lengths.
    if isinstance(max_length, int) and max_length > 0:
        if 'VARCHAR' in mapped_type.upper() or 'NVARCHAR' in mapped_type.upper():
            # Replace (MAX) with actual length or add length
            if '(MAX)' in mapped_type.upper():
                mapped_type = mapped_type.replace('(MAX)', f'({max_length})')
            elif '(' not in mapped_type:
                mapped_type = f"{mapped_type}({max_length})"
        elif 'CHAR' in mapped_type.upper() or 'NCHAR' in mapped_type.upper():
            if '(' not in mapped_type:
                mapped_type = f"{mapped_type}({max_length})"
    
    # Apply precision and scale for numeric types
    if precision is not None and ('NUMERIC' in mapped_type.upper() or 'DECIMAL' in mapped_type.upper()):
        if scale is not None:
            mapped_type = f"{mapped_type.split('(')[0]}({precision},{scale})"
        else:
            mapped_type = f"{mapped_type.split('(')[0]}({precision})"
    
    # Handle ClickHouse-specific type formatting
    if target_db == 'clickhouse':
        # Handle ClickHouse Decimal types with precision/scale
        if 'Decimal' in mapped_type and precision is not None:
            if scale is not None:
                mapped_type = f'Decimal({precision},{scale})'
            else:
                mapped_type = f'Decimal({precision})'
        
        # Handle ClickHouse FixedString with length
        if 'FixedString' in mapped_type and max_length is not None:
            mapped_type = f'FixedString({max_length})'
    
    # Handle FixedString mapping FROM ClickHouse - should map to CHAR with length
    if source_db == 'clickhouse' and 'FixedString' in source_type_normalized and max_length is not None:
        if target_db == 'postgres' or target_db == 'mysql' or target_db == 'sqlserver':
            # FixedString maps to CHAR/NCHAR, apply length
            if mapped_type == 'CHAR' or mapped_type == 'NCHAR':
                mapped_type = f"{mapped_type}({max_length})"
    
    return mapped_type


def _normalize_with_overrides(
    data_type: str,
    max_length: Optional[int],
    precision: Optional[int],
    scale: Optional[int],
) -> Tuple[str, Optional[int], Optional[int], Optional[int]]:
    """
    Helper to normalize a type string but prefer explicit precision/scale/length
    passed by callers when available.
    """
    base_type, parsed_length, parsed_precision, parsed_scale = normalize_data_type(
        data_type, db_type=""
    )

    final_length = max_length if max_length is not None else parsed_length
    final_precision = precision if precision is not None else parsed_precision
    final_scale = scale if scale is not None else parsed_scale

    return base_type, final_length, final_precision, final_scale


def map_oracle_to_target_type(
    oracle_type: str,
    target_db: str,
    max_length: Optional[int] = None,
    precision: Optional[int] = None,
    scale: Optional[int] = None,
) -> str:
    """
    Map an Oracle column type to a target database type (postgres/mysql/clickhouse)
    with a strong bias towards non-lossy mappings.

    This helper is intentionally Oracle-specific and is used by the sync engine
    and table handler for Oracle-as-source flows. It does NOT rely on the generic
    TYPE_MAPPING matrix to keep the Oracle rules explicit and auditable.
    """
    target_db = target_db.lower()
    if target_db not in ("postgres", "mysql", "clickhouse"):
        raise ValueError(f"Unsupported target_db for Oracle mapping: {target_db}")

    base_type, eff_length, eff_precision, eff_scale = _normalize_with_overrides(
        oracle_type, max_length, precision, scale
    )
    base_upper = base_type.upper()

    # ---------- Unsupported Oracle types (fail early, no silent fallback) ----------
    UNSUPPORTED_ORACLE_TYPES = ("LONG RAW", "RAW", "BFILE", "SDO_GEOMETRY")
    if base_upper in UNSUPPORTED_ORACLE_TYPES:
        raise ValueError(
            f"Unsupported Oracle type for migration: {oracle_type}. "
            "Use a supported type or exclude this column."
        )

    # ---------- Numeric ----------
    if base_upper in ("NUMBER", "DECIMAL", "NUMERIC", "FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE"):
        # FLOAT / BINARY_* map to floating types; NUMBER/DECIMAL/NUMERIC map to exact numerics
        if base_upper in ("FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE"):
            if target_db == "postgres":
                return "DOUBLE PRECISION"
            if target_db == "mysql":
                return "DOUBLE"
            return "Float64"  # clickhouse

        # NUMBER family – preserve precision/scale where possible
        p = eff_precision
        s = eff_scale or 0

        # Integer-like NUMBER
        if s == 0 and (p is None or p <= 18):
            if target_db == "postgres":
                return "BIGINT"
            if target_db == "mysql":
                return "BIGINT"
            return "Int64"

        # High-precision or scaled NUMBER -> DECIMAL/NUMERIC
        if target_db == "postgres":
            if p is not None:
                return f"NUMERIC({p},{s})" if s is not None else f"NUMERIC({p})"
            return "NUMERIC"
        if target_db == "mysql":
            if p is not None:
                return f"DECIMAL({p},{s})" if s is not None else f"DECIMAL({p})"
            return "DECIMAL"
        # clickhouse
        if p is not None:
            if s is not None:
                return f"Decimal({p},{s})"
            return f"Decimal({p})"
        return "Decimal(38,10)"

    # ---------- Character / LOB ----------
    if base_upper in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR"):
        length = eff_length or get_default_length(base_type, "oracle") or 255
        # Avoid truncation by using TEXT-style types when lengths are large
        if target_db == "postgres":
            if length > 10_000:
                return "TEXT"
            return f"VARCHAR({length})"
        if target_db == "mysql":
            # MySQL VARCHAR upper bound depends on charset; use TEXT above a conservative threshold
            if length > 16_000:
                return "LONGTEXT"
            return f"VARCHAR({length})"
        # clickhouse
        if length > 65535:
            return "String"
        return "String"

    if base_upper in ("CLOB", "NCLOB", "LONG"):
        if target_db == "postgres":
            return "TEXT"
        if target_db == "mysql":
            return "LONGTEXT"
        return "String"

    # ---------- Temporal ----------
    if base_upper in ("DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE", "TIMESTAMP WITH LOCAL TIME ZONE"):
        if target_db == "postgres":
            # Prefer timestamptz semantics; actual TZ normalization is handled at value level
            return "TIMESTAMP"
        if target_db == "mysql":
            return "DATETIME"
        return "DateTime"

    # ---------- Binary ----------
    if base_upper == "BLOB":
        if target_db == "postgres":
            return "BYTEA"
        if target_db == "mysql":
            return "LONGBLOB"
        return "String"

    # ---------- Fallback ----------
    logger.warning(
        "No explicit Oracle→%s mapping for type '%s', "
        "falling back to large text representation to avoid data loss.",
        target_db,
        oracle_type,
    )
    if target_db == "postgres":
        return "TEXT"
    if target_db == "mysql":
        return "LONGTEXT"
    return "String"


def map_source_to_oracle_type(
    source_type: str,
    source_db: str,
    max_length: Optional[int] = None,
    precision: Optional[int] = None,
    scale: Optional[int] = None,
) -> str:
    """
    Map a Postgres/MySQL/ClickHouse type to an Oracle column type.

    This is used for Oracle-as-target flows. The goal is to always choose an
    Oracle type that can represent the full range/precision of the source
    column, even if that means using a wider NUMBER or CLOB.
    """
    source_db = source_db.lower()
    if source_db not in ("postgres", "mysql", "clickhouse"):
        raise ValueError(f"Unsupported source_db for Oracle mapping: {source_db}")

    base_type, eff_length, eff_precision, eff_scale = _normalize_with_overrides(
        source_type, max_length, precision, scale
    )
    base_upper = base_type.upper()

    # ---------- Floating point (approximate) ----------
    #
    # Oracle NUMBER is an exact decimal type with max precision 38 and max
    # magnitude about 1e126. MySQL DOUBLE can represent values up to ~1.7e308.
    # Mapping DOUBLE/FLOAT to NUMBER will fail at insert-time for large values
    # (DPY-4003: value cannot be represented as an Oracle number).
    #
    # Use Oracle binary floating types instead to preserve IEEE-754 ranges.
    if base_upper in ("DOUBLE", "DOUBLE PRECISION"):
        return "BINARY_DOUBLE"
    if base_upper in ("FLOAT", "REAL"):
        # In MySQL, FLOAT is 32-bit and DOUBLE is 64-bit. REAL is usually a
        # synonym for DOUBLE unless REAL_AS_FLOAT is enabled; we still prefer a
        # safe, wide representation in Oracle.
        return "BINARY_FLOAT" if base_upper == "FLOAT" else "BINARY_DOUBLE"

    # ---------- Numeric ----------
    numeric_like = {
        "INT",
        "INT2",
        "INT4",
        "INT8",
        "INTEGER",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "MEDIUMINT",
        "INT UNSIGNED",
        "BIGINT UNSIGNED",
        "SMALLINT UNSIGNED",
        "TINYINT UNSIGNED",
        "MEDIUMINT UNSIGNED",
        "REAL",
        "DOUBLE",
        "DOUBLE PRECISION",
        "FLOAT",
        "DECIMAL",
        "NUMERIC",
    }
    if base_upper in numeric_like:
        # use precision/scale when provided, otherwise choose safe defaults
        p = eff_precision
        s = eff_scale or 0

        if p is None:
            # Pick a generous precision if original type had no explicit precision
            # BIGINT UNSIGNED max 2^64-1 = 20 digits; Oracle NUMBER(20) required
            if base_upper == "BIGINT UNSIGNED":
                p, s = 20, 0
            elif base_upper in ("BIGINT", "INT8"):
                p, s = 19, 0
            elif base_upper in ("INT", "INTEGER", "INT4", "MEDIUMINT", "INT UNSIGNED", "MEDIUMINT UNSIGNED"):
                p, s = 10, 0
            elif base_upper in ("SMALLINT", "INT2", "TINYINT", "SMALLINT UNSIGNED", "TINYINT UNSIGNED"):
                p, s = 5, 0
            elif base_upper in ("DECIMAL", "NUMERIC"):
                p, s = 38, 10
            else:
                p, s = 38, 10

        # Oracle NUMBER max precision is 38; use CLOB for higher precision (DPY-4003)
        if p is not None and p > 38:
            return "CLOB"

        # Scale of 0 -> integer-like
        if s == 0:
            return f"NUMBER({p})"
        return f"NUMBER({p},{s})"

    # ---------- MySQL YEAR (1901-2155) ----------
    if base_upper == "YEAR":
        return "NUMBER(4)"

    # ---------- MySQL BIT(n): store as BLOB for any n (MySQL returns bytes) ----------
    if base_upper == "BIT":
        return "BLOB"

    # ---------- MySQL ENUM / SET: store as CLOB to preserve any length ----------
    if base_upper in ("ENUM", "SET"):
        return "CLOB"

    # ---------- MySQL spatial types: store WKB as BLOB ----------
    spatial_types = (
        "GEOMETRY", "POINT", "LINESTRING", "POLYGON",
        "MULTIPOINT", "MULTILINESTRING", "MULTIPOLYGON", "GEOMETRYCOLLECTION",
    )
    if base_upper in spatial_types:
        return "BLOB"

    # ---------- Character / Text ----------
    char_like = {"CHAR", "NCHAR", "VARCHAR", "VARCHAR2", "NVARCHAR", "NVARCHAR2"}
    text_like = {"TEXT", "LONGTEXT", "MEDIUMTEXT", "TINYTEXT", "JSON", "JSONB", "STRING"}

    if base_upper in char_like:
        length = eff_length or get_default_length(base_type, source_db) or 255
        # Oracle VARCHAR2 max is 4000 (in bytes) for many setups; above that we should use CLOB
        if length > 4000:
            return "CLOB"
        return f"VARCHAR2({length})"

    if base_upper in text_like:
        return "CLOB"

    # ---------- Temporal ----------
    # TIME: MySQL returns timedelta; we map to TIMESTAMP(6) and normalize timedelta->datetime in Oracle connector.
    temporal = {
        "TIMESTAMP",
        "TIMESTAMPTZ",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMP WITHOUT TIME ZONE",
        "DATETIME",
        "DATE",
        "TIME",
        "DATEONLY",
    }
    if base_upper in temporal or "TIMESTAMP" in base_upper:
        return "TIMESTAMP(6)"

    # ---------- Binary ----------
    binary_like = {"BYTEA", "BLOB", "LONGBLOB", "MEDIUMBLOB", "TINYBLOB", "VARBINARY", "BINARY"}
    if base_upper in binary_like:
        return "BLOB"

    # ---------- Boolean ----------
    if base_upper in ("BOOLEAN", "BOOL", "BIT", "TINYINT(1)"):
        # Standardise on NUMBER(1) 0/1 representation
        return "NUMBER(1)"

    # ---------- Fallback ----------
    logger.warning(
        "No explicit %s→Oracle mapping for type '%s', "
        "falling back to CLOB to avoid truncation.",
        source_db,
        source_type,
    )
    return "CLOB"

def get_default_length(data_type: str, source_db: str) -> Optional[int]:
    """
    Get default length for data types that require it
    
    Args:
        data_type: Data type name
        source_db: Source database type
    
    Returns:
        Default length or None
    """
    type_lower = data_type.lower()
    
    if 'varchar' in type_lower or 'char' in type_lower:
        return 255
    
    return None

def normalize_data_type(data_type: str, db_type: str) -> Tuple[str, Optional[int], Optional[int], Optional[int]]:
    """
    Normalize data type string and extract components
    
    Args:
        data_type: Data type string (e.g., "VARCHAR(255)", "DECIMAL(10,2)")
        db_type: Database type ('postgres', 'mysql', 'sqlserver', 'clickhouse')
    
    Returns:
        Tuple of (base_type, max_length, precision, scale)
    """
    data_type_upper = data_type.upper().strip()
    
    # MySQL: int(11) unsigned -> base_type INT UNSIGNED for mapping
    if db_type == 'mysql' and ' UNSIGNED' in data_type_upper:
        data_type_upper = data_type_upper.replace(' UNSIGNED', '')  # strip for param parsing
        unsigned_suffix = ' UNSIGNED'
    else:
        unsigned_suffix = ''
    
    # Extract base type
    if '(' in data_type_upper:
        base_type = data_type_upper.split('(')[0].strip() + unsigned_suffix
        params = data_type_upper.split('(')[1].split(')')[0].strip()
    else:
        base_type = data_type_upper.strip() + unsigned_suffix
        params = None
    
    max_length = None
    precision = None
    scale = None
    
    if params:
        # ENUM('a','b') and SET('x','y') have quoted params — do not parse as numbers
        if base_type in ('ENUM', 'SET') or ("'" in params or '"' in params):
            # Use params length as rough max_length for VARCHAR mapping if needed
            max_length = min(len(params), 4000) if params else None
        elif ',' in params:
            # Numeric type with precision and scale (e.g. decimal(10,2), float(7,4))
            parts = params.split(',')
            if parts and parts[0].strip().isdigit():
                try:
                    precision = int(parts[0].strip())
                    scale = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else None
                except (ValueError, IndexError):
                    pass
        else:
            # Single numeric param: length or bit size (e.g. varchar(255), bit(64))
            if params.strip().isdigit():
                try:
                    max_length = int(params.strip())
                except ValueError:
                    pass
    return (base_type, max_length, precision, scale)

