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
            'int4': 'Int32',
            'integer': 'Int32',
            'bigint': 'Int64',
            'int8': 'Int64',
            'smallint': 'Int16',
            'int2': 'Int16',
            'serial': 'Int32',
            'bigserial': 'Int64',
            'varchar': 'String',
            'character varying': 'String',
            'text': 'String',
            'char': 'FixedString',
            'timestamp without time zone': 'DateTime',
            'timestamp with time zone': 'DateTime',
            'timestamp': 'DateTime',
            'date': 'Date',
            'time': 'String',
            'boolean': 'UInt8',
            'bool': 'UInt8',
            'numeric': 'Decimal',
            'decimal': 'Decimal',
            'double precision': 'Float64',
            'real': 'Float32',
            'json': 'String',
            'jsonb': 'String',
            'uuid': 'UUID',
            'bytea': 'String',
        },
    },
    'mysql': {
        'postgres': {
            'INT': 'INTEGER',
            'BIGINT': 'BIGINT',
            'SMALLINT': 'SMALLINT',
            'TINYINT': 'SMALLINT',
            'MEDIUMINT': 'INTEGER',
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
            'TINYINT(1)': 'BOOLEAN',
            'DECIMAL': 'NUMERIC',
            'NUMERIC': 'NUMERIC',
            'DOUBLE': 'DOUBLE PRECISION',
            'FLOAT': 'REAL',
            'JSON': 'JSONB',
            'BLOB': 'BYTEA',
            'LONGBLOB': 'BYTEA',
            'MEDIUMBLOB': 'BYTEA',
            'TINYBLOB': 'BYTEA',
        },
        'sqlserver': {
            'INT': 'INT',
            'BIGINT': 'BIGINT',
            'SMALLINT': 'SMALLINT',
            'TINYINT': 'TINYINT',
            'MEDIUMINT': 'INT',
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
            'TINYINT(1)': 'BIT',
            'DECIMAL': 'DECIMAL',
            'NUMERIC': 'NUMERIC',
            'DOUBLE': 'FLOAT',
            'FLOAT': 'REAL',
            'JSON': 'NVARCHAR(MAX)',
            'BLOB': 'VARBINARY(MAX)',
            'LONGBLOB': 'VARBINARY(MAX)',
            'MEDIUMBLOB': 'VARBINARY(MAX)',
            'TINYBLOB': 'VARBINARY(MAX)',
        },
        'clickhouse': {
            'INT': 'Int32',
            'BIGINT': 'Int64',
            'SMALLINT': 'Int16',
            'TINYINT': 'Int8',
            'MEDIUMINT': 'Int32',
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
            'TINYINT(1)': 'UInt8',
            'DECIMAL': 'Decimal',
            'NUMERIC': 'Decimal',
            'DOUBLE': 'Float64',
            'FLOAT': 'Float32',
            'JSON': 'String',
            'BLOB': 'String',
            'LONGBLOB': 'String',
            'MEDIUMBLOB': 'String',
            'TINYBLOB': 'String',
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
    if source_db not in ['postgres', 'mysql', 'sqlserver', 'clickhouse']:
        raise ValueError(f"Invalid source database type: {source_db}")
    if target_db not in ['postgres', 'mysql', 'sqlserver', 'clickhouse']:
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
    
    # Apply length constraints
    if max_length:
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
    
    # Extract base type
    if '(' in data_type_upper:
        base_type = data_type_upper.split('(')[0].strip()
        params = data_type_upper.split('(')[1].split(')')[0].strip()
    else:
        base_type = data_type_upper
        params = None
    
    max_length = None
    precision = None
    scale = None
    
    if params:
        # Check if it's numeric (precision,scale) or string (length)
        if ',' in params:
            # Numeric type with precision and scale
            parts = params.split(',')
            try:
                precision = int(parts[0].strip())
                scale = int(parts[1].strip())
            except ValueError:
                pass
        else:
            # String type with length
            try:
                max_length = int(params.strip())
            except ValueError:
                pass
    
    return (base_type, max_length, precision, scale)

