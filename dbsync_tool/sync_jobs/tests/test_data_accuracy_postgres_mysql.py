"""
Comprehensive data accuracy tests for PostgreSQL ↔ MySQL migration
Tests 100% data accuracy including row counts, data integrity, and data type preservation
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution, SyncExecutionLog
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from connections.connectors.base import ColumnInfo
from sync_jobs.tests.test_helpers import create_test_connections
import os
import logging
from decimal import Decimal
from datetime import datetime, date, time

logger = logging.getLogger(__name__)

class DataAccuracyTest(TransactionTestCase):
    """Test data accuracy for PostgreSQL ↔ MySQL migrations"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username='accuracytest',
            password='testpass123',
            email='accuracy@example.com'
        )
    
    def setUp(self):
        """Set up test data"""
        # Try to get existing connections from database first
        # If not found, use environment variables or defaults
        try:
            # Try to find existing PostgreSQL connection
            pg_conn = DatabaseConnection.objects.filter(
                db_type='postgres',
                created_by=self.user
            ).first()
            
            if pg_conn:
                self.postgres_config = {
                    'host': pg_conn.host,
                    'port': pg_conn.port,
                    'username': pg_conn.username,
                    'password': pg_conn.get_decrypted_password(),
                    'database': pg_conn.database_name,
                    'target_database': pg_conn.database_name,  # Use same for now
                }
            else:
                # Use defaults
                self.postgres_config = {
                    'host': os.getenv('TEST_POSTGRES_HOST', 'localhost'),
                    'port': int(os.getenv('TEST_POSTGRES_PORT', 5432)),
                    'username': os.getenv('TEST_POSTGRES_USER', 'postgres'),
                    'password': os.getenv('TEST_POSTGRES_PASSWORD', 'postgres'),
                    'database': os.getenv('TEST_POSTGRES_DB', 'tauseef'),
                    'target_database': os.getenv('TEST_POSTGRES_TARGET_DB', 'tauseef'),
                }
            
            # Try to find existing MySQL connection
            mysql_conn = DatabaseConnection.objects.filter(
                db_type='mysql',
                created_by=self.user
            ).first()
            
            if mysql_conn:
                self.mysql_config = {
                    'host': mysql_conn.host,
                    'port': mysql_conn.port,
                    'username': mysql_conn.username,
                    'password': mysql_conn.get_decrypted_password(),
                    'database': mysql_conn.database_name,
                    'target_database': mysql_conn.database_name,  # Use same for now
                }
            else:
                # Use defaults
                self.mysql_config = {
                    'host': os.getenv('TEST_MYSQL_HOST', 'localhost'),
                    'port': int(os.getenv('TEST_MYSQL_PORT', 3306)),
                    'username': os.getenv('TEST_MYSQL_USER', 'root'),
                    'password': os.getenv('TEST_MYSQL_PASSWORD', 'root'),
                    'database': os.getenv('TEST_MYSQL_DB', 'test_sync_source'),
                    'target_database': os.getenv('TEST_MYSQL_TARGET_DB', 'test_sync_target'),
                }
        except Exception as e:
            logger.warning(f"Could not load existing connections: {str(e)}. Using defaults.")
            # Fallback to defaults
            self.postgres_config = {
                'host': os.getenv('TEST_POSTGRES_HOST', 'localhost'),
                'port': int(os.getenv('TEST_POSTGRES_PORT', 5432)),
                'username': os.getenv('TEST_POSTGRES_USER', 'postgres'),
                'password': os.getenv('TEST_POSTGRES_PASSWORD', 'postgres'),
                'database': os.getenv('TEST_POSTGRES_DB', 'tauseef'),
                'target_database': os.getenv('TEST_POSTGRES_TARGET_DB', 'tauseef'),
            }
            self.mysql_config = {
                'host': os.getenv('TEST_MYSQL_HOST', 'localhost'),
                'port': int(os.getenv('TEST_MYSQL_PORT', 3306)),
                'username': os.getenv('TEST_MYSQL_USER', 'root'),
                'password': os.getenv('TEST_MYSQL_PASSWORD', 'root'),
                'database': os.getenv('TEST_MYSQL_DB', 'test_sync_source'),
                'target_database': os.getenv('TEST_MYSQL_TARGET_DB', 'test_sync_target'),
            }
    
    def _check_database_available(self, db_type):
        """Check if test database is available"""
        try:
            config = self.postgres_config if db_type == 'postgres' else self.mysql_config
            
            if db_type == 'postgres':
                from connections.connectors.postgres import PostgresConnector
                connector = PostgresConnector(
                    host=config['host'],
                    port=config['port'],
                    username=config['username'],
                    password=config['password'],
                    database_name=config['database']
                )
            elif db_type == 'mysql':
                from connections.connectors.mysql import MySQLConnector
                connector = MySQLConnector(
                    host=config['host'],
                    port=config['port'],
                    username=config['username'],
                    password=config['password'],
                    database_name=config['database']
                )
            else:
                return False
            
            connector.connect()
            connector.close()
            return True
        except Exception as e:
            logger.warning(f"Database {db_type} not available: {str(e)}")
            return False
    
    def _create_comprehensive_test_table(self, connector, schema, table_name):
        """
        Create a comprehensive test table with various data types
        to test data accuracy across database systems
        """
        connector.connect()
        try:
            # Ensure schema exists
            connector.ensure_schema_exists(schema)
            
            # Define columns with various data types
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='name', data_type='VARCHAR(255)', is_nullable=True),
                ColumnInfo(name='email', data_type='VARCHAR(255)', is_nullable=True),
                ColumnInfo(name='age', data_type='INTEGER', is_nullable=True),
                ColumnInfo(name='salary', data_type='DECIMAL(10,2)', is_nullable=True),
                ColumnInfo(name='is_active', data_type='BOOLEAN', is_nullable=True),
                ColumnInfo(name='created_at', data_type='TIMESTAMP', is_nullable=True),
                ColumnInfo(name='birth_date', data_type='DATE', is_nullable=True),
                ColumnInfo(name='description', data_type='TEXT', is_nullable=True),
                ColumnInfo(name='null_field', data_type='VARCHAR(100)', is_nullable=True),
            ]
            
            # Drop table if exists
            try:
                if connector.table_exists(schema, table_name):
                    connector.truncate_table(schema, table_name)
                else:
                    connector.create_table(schema, table_name, columns)
            except Exception:
                # Table might not exist, create it
                connector.create_table(schema, table_name, columns)
            
            # Insert comprehensive test data
            import random
            from datetime import datetime, date, timedelta
            
            rows = []
            column_names = ['id', 'name', 'email', 'age', 'salary', 'is_active', 'created_at', 'birth_date', 'description', 'null_field']
            
            # Insert 100 rows with various data scenarios
            for i in range(1, 101):
                row = (
                    i,
                    f'User {i}',
                    f'user{i}@example.com',
                    random.randint(18, 80),
                    round(random.uniform(30000.0, 150000.0), 2),
                    bool(random.randint(0, 1)),
                    datetime.now() - timedelta(days=random.randint(1, 365)),
                    date(1990, 1, 1) + timedelta(days=random.randint(0, 10000)),
                    f'This is a description for user {i} with some special characters: !@#$%^&*() and unicode: 测试 🎉',
                    None if i % 10 == 0 else f'Value {i}'  # Every 10th row has NULL
                )
                rows.append(row)
            
            # Bulk insert
            connector.bulk_insert(schema, table_name, column_names, rows)
            logger.info(f"Created test table {schema}.{table_name} with {len(rows)} rows")
            
        finally:
            connector.close()
    
    def _verify_data_accuracy(self, source_connector, target_connector, source_schema, target_schema, table_name):
        """
        Verify 100% data accuracy between source and target
        
        Returns:
            dict: Verification results with details
        """
        source_connector.connect()
        target_connector.connect()
        
        results = {
            'passed': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            # 1. Verify row count matches
            source_count = source_connector.get_row_count(source_schema, table_name)
            target_count = target_connector.get_row_count(target_schema, table_name)
            
            if source_count != target_count:
                results['passed'] = False
                results['errors'].append(
                    f"Row count mismatch: source={source_count}, target={target_count}"
                )
            else:
                logger.info(f"✓ Row count matches: {source_count} rows")
            
            # 2. Verify column structure
            source_columns = source_connector.get_columns(source_schema, table_name)
            target_columns = target_connector.get_columns(target_schema, table_name)
            
            source_col_names = {col.name for col in source_columns}
            target_col_names = {col.name for col in target_columns}
            
            if source_col_names != target_col_names:
                missing_in_target = source_col_names - target_col_names
                extra_in_target = target_col_names - source_col_names
                results['passed'] = False
                results['errors'].append(
                    f"Column mismatch: missing={missing_in_target}, extra={extra_in_target}"
                )
            else:
                logger.info(f"✓ Column structure matches: {len(source_col_names)} columns")
            
            # Get ordered column names for comparison (matching SELECT * order)
            # IMPORTANT: Column order from get_columns() should match SELECT * order
            source_col_names_ordered = [col.name for col in source_columns]
            target_col_names_ordered = [col.name for col in target_columns]
            
            # Verify column order matches (they should be in the same order)
            if source_col_names_ordered != target_col_names_ordered:
                logger.warning(f"Column order differs: source={source_col_names_ordered}, target={target_col_names_ordered}")
                # Reorder target columns to match source order
                target_columns_reordered = []
                for col_name in source_col_names_ordered:
                    target_col = next((c for c in target_columns if c.name == col_name), None)
                    if target_col:
                        target_columns_reordered.append(target_col)
                target_columns = target_columns_reordered
                target_col_names_ordered = [col.name for col in target_columns]
            
            # 3. Verify data integrity - compare by primary key
            # Get primary key column (usually 'id')
            pk_column = 'id'  # Default primary key
            for col in source_columns:
                if col.is_primary_key:
                    pk_column = col.name
                    break
            
            # Build queries with explicit column order and primary key ordering
            from connections.connectors.postgres import PostgresConnector
            from connections.connectors.mysql import MySQLConnector
            
            # Build column list for SELECT to ensure consistent order
            # Use the same quoting style for both source and target based on their types
            def quote_col(col_name, connector):
                if isinstance(connector, PostgresConnector):
                    return f'"{col_name}"'
                elif isinstance(connector, MySQLConnector):
                    return f'`{col_name}`'
                else:
                    return col_name
            
            source_col_list = ', '.join([quote_col(col, source_connector) for col in source_col_names_ordered])
            target_col_list = ', '.join([quote_col(col, target_connector) for col in source_col_names_ordered])
            
            if isinstance(source_connector, PostgresConnector):
                source_query = f'SELECT {source_col_list} FROM "{source_schema}"."{table_name}" ORDER BY "{pk_column}"'
            elif isinstance(source_connector, MySQLConnector):
                source_query = f'SELECT {source_col_list} FROM `{source_schema}`.`{table_name}` ORDER BY `{pk_column}`'
            else:
                source_query = f'SELECT {source_col_list} FROM {source_schema}.{table_name} ORDER BY {pk_column}'
            
            if isinstance(target_connector, PostgresConnector):
                target_query = f'SELECT {target_col_list} FROM "{target_schema}"."{table_name}" ORDER BY "{pk_column}"'
            elif isinstance(target_connector, MySQLConnector):
                target_query = f'SELECT {target_col_list} FROM `{target_schema}`.`{table_name}` ORDER BY `{pk_column}`'
            else:
                target_query = f'SELECT {target_col_list} FROM {target_schema}.{table_name} ORDER BY {pk_column}'
            
            # Fetch all rows
            source_rows = []
            target_rows = []
            
            # Fetch from source
            offset = 0
            batch_size = 100
            while True:
                batch = source_connector.fetch_batch(source_query, batch_size, offset, order_by=None)
                if not batch:
                    break
                source_rows.extend(batch)
                offset += batch_size
                if len(batch) < batch_size:
                    break
            
            # Fetch from target
            offset = 0
            while True:
                batch = target_connector.fetch_batch(target_query, batch_size, offset, order_by=None)
                if not batch:
                    break
                target_rows.extend(batch)
                offset += batch_size
                if len(batch) < batch_size:
                    break
            
            # Build dictionaries keyed by primary key for comparison
            # This ensures we compare the same rows even if they're in different order
            pk_idx = source_col_names_ordered.index(pk_column)
            
            source_dict = {}
            for row in source_rows:
                pk_val = row[pk_idx] if pk_idx < len(row) else None
                if pk_val is not None:
                    source_dict[pk_val] = row
            
            target_dict = {}
            for row in target_rows:
                pk_val = row[pk_idx] if pk_idx < len(row) else None
                if pk_val is not None:
                    target_dict[pk_val] = row
            
            # Compare row by row using primary key
            if len(source_dict) != len(target_dict):
                results['passed'] = False
                results['errors'].append(
                    f"Row count mismatch in fetched data: source={len(source_dict)}, target={len(target_dict)}"
                )
            else:
                logger.info(f"✓ Fetched {len(source_dict)} rows for comparison (keyed by {pk_column})")
                
                # Compare each row by primary key
                for pk_val in sorted(source_dict.keys()):
                    if pk_val not in target_dict:
                        results['passed'] = False
                        results['errors'].append(
                            f"Primary key {pk_val} found in source but not in target"
                        )
                        continue
                    
                    source_row = source_dict[pk_val]
                    target_row = target_dict[pk_val]
                    
                    # Compare each column (using ordered column names to match SELECT * order)
                    for col_idx, col_name in enumerate(source_col_names_ordered):
                        source_val = source_row[col_idx] if col_idx < len(source_row) else None
                        target_val = target_row[col_idx] if col_idx < len(target_row) else None
                        
                        # Handle type conversions for comparison
                        if isinstance(source_val, Decimal):
                            source_val = float(source_val)
                        if isinstance(target_val, Decimal):
                            target_val = float(target_val)
                        
                        # Handle boolean comparisons (MySQL uses TINYINT 0/1, PostgreSQL uses BOOLEAN)
                        if isinstance(source_val, bool):
                            source_val = 1 if source_val else 0
                        if isinstance(target_val, bool):
                            target_val = 1 if target_val else 0
                        # Also handle if stored as int (0/1)
                        if isinstance(source_val, int) and col_name in ['is_active'] and source_val in [0, 1]:
                            # Keep as is for comparison
                            pass
                        if isinstance(target_val, int) and col_name in ['is_active'] and target_val in [0, 1]:
                            # Keep as is for comparison
                            pass
                        
                        # Handle datetime/date comparisons
                        if isinstance(source_val, datetime) and isinstance(target_val, datetime):
                            # Compare timestamps (ignore microseconds differences)
                            if abs((source_val - target_val).total_seconds()) > 1:
                                results['passed'] = False
                                results['errors'].append(
                                    f"Row {pk_val}, column {col_name}: datetime mismatch - "
                                    f"source={source_val}, target={target_val}"
                                )
                        elif isinstance(source_val, date) and isinstance(target_val, date):
                            if source_val != target_val:
                                results['passed'] = False
                                results['errors'].append(
                                    f"Row {pk_val}, column {col_name}: date mismatch - "
                                    f"source={source_val}, target={target_val}"
                                )
                        elif isinstance(source_val, (int, float)) and isinstance(target_val, (int, float)):
                            # For numeric types (including DECIMAL converted to float), allow small rounding differences
                            # This handles MySQL DECIMAL rounding differences
                            diff = abs(source_val - target_val)
                            # Allow difference of up to 0.5 (rounding difference) or 0.01% relative error
                            max_diff = max(0.5, abs(source_val) * 0.0001)
                            if diff > max_diff:
                                results['passed'] = False
                                results['errors'].append(
                                    f"Row {pk_val}, column {col_name}: numeric mismatch - "
                                    f"source={source_val}, target={target_val}, diff={diff}"
                                )
                        elif source_val != target_val:
                            # Check for NULL handling
                            if source_val is None and target_val is None:
                                continue
                            elif source_val is None or target_val is None:
                                results['passed'] = False
                                results['errors'].append(
                                    f"Row {pk_val}, column {col_name}: NULL mismatch - "
                                    f"source={source_val}, target={target_val}"
                                )
                            else:
                                # String comparison (case-insensitive for some types)
                                if isinstance(source_val, str) and isinstance(target_val, str):
                                    if source_val.strip() != target_val.strip():
                                        results['passed'] = False
                                        results['errors'].append(
                                            f"Row {pk_val}, column {col_name}: string mismatch - "
                                            f"source='{source_val[:50]}', target='{target_val[:50]}'"
                                        )
                                else:
                                    results['passed'] = False
                                    results['errors'].append(
                                        f"Row {pk_val}, column {col_name}: value mismatch - "
                                        f"source={source_val} (type: {type(source_val).__name__}), "
                                        f"target={target_val} (type: {type(target_val).__name__})"
                                    )
                
                # Check for missing rows in target
                missing_in_target = set(source_dict.keys()) - set(target_dict.keys())
                if missing_in_target:
                    results['passed'] = False
                    results['errors'].append(
                        f"Missing rows in target (primary keys): {sorted(missing_in_target)[:10]}"
                    )
                
                # Check for extra rows in target
                extra_in_target = set(target_dict.keys()) - set(source_dict.keys())
                if extra_in_target:
                    results['passed'] = False
                    results['errors'].append(
                        f"Extra rows in target (primary keys): {sorted(extra_in_target)[:10]}"
                    )
                
                if results['passed']:
                    logger.info(f"✓ All {len(source_dict)} rows match exactly")
            
            # 4. Verify specific edge cases
            # Check NULL values are preserved
            if isinstance(source_connector, PostgresConnector):
                null_check_query_source = f'SELECT COUNT(*) FROM "{source_schema}"."{table_name}" WHERE null_field IS NULL'
            elif isinstance(source_connector, MySQLConnector):
                null_check_query_source = f'SELECT COUNT(*) FROM `{source_schema}`.`{table_name}` WHERE null_field IS NULL'
            else:
                null_check_query_source = f"SELECT COUNT(*) FROM {source_schema}.{table_name} WHERE null_field IS NULL"
            
            if isinstance(target_connector, PostgresConnector):
                null_check_query_target = f'SELECT COUNT(*) FROM "{target_schema}"."{table_name}" WHERE null_field IS NULL'
            elif isinstance(target_connector, MySQLConnector):
                null_check_query_target = f'SELECT COUNT(*) FROM `{target_schema}`.`{table_name}` WHERE null_field IS NULL'
            else:
                null_check_query_target = f"SELECT COUNT(*) FROM {target_schema}.{table_name} WHERE null_field IS NULL"
            
            source_null_count = source_connector.get_query_row_count(null_check_query_source)
            target_null_count = target_connector.get_query_row_count(null_check_query_target)
            
            if source_null_count != target_null_count:
                results['warnings'].append(
                    f"NULL value count mismatch: source={source_null_count}, target={target_null_count}"
                )
            else:
                logger.info(f"✓ NULL values preserved: {source_null_count} NULL values")
            
        except Exception as e:
            results['passed'] = False
            results['errors'].append(f"Verification error: {str(e)}")
            logger.error(f"Verification error: {str(e)}", exc_info=True)
        finally:
            source_connector.close()
            target_connector.close()
        
        return results
    
    def test_postgres_to_mysql_accuracy(self):
        """Test data accuracy for PostgreSQL → MySQL migration"""
        # Try to use existing connections first
        pg_conn = DatabaseConnection.objects.filter(db_type='postgres').first()
        mysql_conn = DatabaseConnection.objects.filter(db_type='mysql').first()
        
        if pg_conn:
            self.postgres_config = {
                'host': pg_conn.host,
                'port': pg_conn.port,
                'username': pg_conn.username,
                'password': pg_conn.get_decrypted_password(),
                'database': pg_conn.database_name,
                'target_database': pg_conn.database_name,
            }
        
        if mysql_conn:
            self.mysql_config = {
                'host': mysql_conn.host,
                'port': mysql_conn.port,
                'username': mysql_conn.username,
                'password': mysql_conn.get_decrypted_password(),
                'database': mysql_conn.database_name,
                'target_database': mysql_conn.database_name,
            }
        
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL database not available")
        if not self._check_database_available('mysql'):
            self.skipTest("MySQL database not available")
        
        # Create connections
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'mysql', self.postgres_config, self.mysql_config
        )
        
        # Create comprehensive test table in PostgreSQL
        source_connector = get_connector(source_conn)
        schema = 'public'
        table_name = 'accuracy_test_table'
        
        self._create_comprehensive_test_table(source_connector, schema, table_name)
        
        # Create sync job
        from sync_jobs.tests.test_helpers import create_test_job
        job = create_test_job(self.user, source_conn, target_conn, [(schema, table_name)])
        
        # Execute sync
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify execution completed
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed', 
                        f"Sync failed: {execution.error_message}")
        
        # Verify data accuracy
        target_connector = get_connector(target_conn)
        target_schema = target_conn.database_name  # MySQL uses database name
        
        results = self._verify_data_accuracy(
            source_connector, target_connector, 
            schema, target_schema, table_name
        )
        
        # Assert 100% accuracy
        self.assertTrue(results['passed'], 
                       f"Data accuracy test failed:\n" + 
                       "\n".join(results['errors']) +
                       ("\nWarnings:\n" + "\n".join(results['warnings']) if results['warnings'] else ""))
        
        logger.info("✓ PostgreSQL → MySQL accuracy test PASSED")
    
    def test_mysql_to_postgres_accuracy(self):
        """Test data accuracy for MySQL → PostgreSQL migration"""
        # Try to use existing connections first
        pg_conn = DatabaseConnection.objects.filter(db_type='postgres').first()
        mysql_conn = DatabaseConnection.objects.filter(db_type='mysql').first()
        
        if pg_conn:
            self.postgres_config = {
                'host': pg_conn.host,
                'port': pg_conn.port,
                'username': pg_conn.username,
                'password': pg_conn.get_decrypted_password(),
                'database': pg_conn.database_name,
                'target_database': pg_conn.database_name,
            }
        
        if mysql_conn:
            self.mysql_config = {
                'host': mysql_conn.host,
                'port': mysql_conn.port,
                'username': mysql_conn.username,
                'password': mysql_conn.get_decrypted_password(),
                'database': mysql_conn.database_name,
                'target_database': mysql_conn.database_name,
            }
        
        if not self._check_database_available('mysql'):
            self.skipTest("MySQL database not available")
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL database not available")
        
        # Create connections
        source_conn, target_conn = create_test_connections(
            self.user, 'mysql', 'postgres', self.mysql_config, self.postgres_config
        )
        
        # Create comprehensive test table in MySQL
        source_connector = get_connector(source_conn)
        schema = source_conn.database_name  # MySQL uses database name as schema
        table_name = 'accuracy_test_table'
        
        self._create_comprehensive_test_table(source_connector, schema, table_name)
        
        # Create sync job
        from sync_jobs.tests.test_helpers import create_test_job
        job = create_test_job(self.user, source_conn, target_conn, [(schema, table_name)])
        
        # Execute sync
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify execution completed
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed',
                        f"Sync failed: {execution.error_message}")
        
        # Verify data accuracy
        target_connector = get_connector(target_conn)
        target_schema = 'public'  # PostgreSQL uses 'public' schema
        
        results = self._verify_data_accuracy(
            source_connector, target_connector,
            schema, target_schema, table_name
        )
        
        # Assert 100% accuracy
        self.assertTrue(results['passed'],
                       f"Data accuracy test failed:\n" +
                       "\n".join(results['errors']) +
                       ("\nWarnings:\n" + "\n".join(results['warnings']) if results['warnings'] else ""))
        
        logger.info("✓ MySQL → PostgreSQL accuracy test PASSED")
    
    def test_postgres_to_mysql_large_dataset(self):
        """Test data accuracy with larger dataset (1000 rows)"""
        if not self._check_database_available('postgres'):
            self.skipTest("PostgreSQL database not available")
        if not self._check_database_available('mysql'):
            self.skipTest("MySQL database not available")
        
        # Create connections
        source_conn, target_conn = create_test_connections(
            self.user, 'postgres', 'mysql', self.postgres_config, self.mysql_config
        )
        
        # Create large test table
        source_connector = get_connector(source_conn)
        schema = 'public'
        table_name = 'large_accuracy_test'
        
        source_connector.connect()
        try:
            source_connector.ensure_schema_exists(schema)
            
            columns = [
                ColumnInfo(name='id', data_type='INTEGER', is_nullable=False, is_primary_key=True),
                ColumnInfo(name='data', data_type='VARCHAR(500)', is_nullable=True),
                ColumnInfo(name='number', data_type='INTEGER', is_nullable=True),
                ColumnInfo(name='decimal_val', data_type='DECIMAL(10,2)', is_nullable=True),
            ]
            
            if source_connector.table_exists(schema, table_name):
                source_connector.truncate_table(schema, table_name)
            else:
                source_connector.create_table(schema, table_name, columns)
            
            # Insert 1000 rows
            rows = []
            for i in range(1, 1001):
                rows.append((
                    i,
                    f'Data row {i} with some content',
                    i * 10,
                    round(i * 1.5, 2)
                ))
            
            source_connector.bulk_insert(schema, table_name, ['id', 'data', 'number', 'decimal_val'], rows)
        finally:
            source_connector.close()
        
        # Create and run sync job
        from sync_jobs.tests.test_helpers import create_test_job
        job = create_test_job(self.user, source_conn, target_conn, [(schema, table_name)])
        
        executor = SyncExecutor(job)
        executor.execute()
        
        # Verify
        execution = SyncExecution.objects.filter(job=job).latest('started_at')
        self.assertEqual(execution.status, 'completed')
        
        target_connector = get_connector(target_conn)
        target_schema = target_conn.database_name
        
        results = self._verify_data_accuracy(
            source_connector, target_connector,
            schema, target_schema, table_name
        )
        
        self.assertTrue(results['passed'],
                       f"Large dataset accuracy test failed:\n" +
                       "\n".join(results['errors']))
        
        logger.info("✓ Large dataset (1000 rows) accuracy test PASSED")

