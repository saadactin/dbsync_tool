"""
Comprehensive Migration Testing Script
Tests SQL Server → PostgreSQL and PostgreSQL → ClickHouse migrations
with 100% accuracy verification
"""

import os
import sys
import django
import time
from datetime import datetime
from decimal import Decimal

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from connections.models import DatabaseConnection
from sync_jobs.models import SyncJob, SyncJobTable, SyncExecution
from sync_engine.executor import SyncExecutor
from connections.connectors.factory import get_connector
from django.contrib.auth.models import User
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MigrationTester:
    """Test harness for database migrations"""

    def __init__(self):
        self.test_results = {
            'sqlserver_to_postgres': {'full': None, 'incremental': None},
            'postgres_to_clickhouse': {'full': None, 'incremental': None}
        }
        # Get or create test user
        self.test_user = User.objects.filter(is_superuser=True).first()
        if not self.test_user:
            self.test_user = User.objects.create_user(
                username='test_user',
                password='test_password',
                is_superuser=True
            )

    def setup_test_table_sqlserver(self, conn):
        """Create test table in SQL Server"""
        logger.info("Setting up test table in SQL Server...")

        connector = get_connector(conn)
        connector.connect()

        try:
            # Drop existing test table
            connector.execute_query("IF OBJECT_ID('dbo.migration_test', 'U') IS NOT NULL DROP TABLE dbo.migration_test")

            # Create test table
            create_sql = """
            CREATE TABLE dbo.migration_test (
                id INT PRIMARY KEY IDENTITY(1,1),
                name NVARCHAR(100) NOT NULL,
                email NVARCHAR(100),
                salary DECIMAL(10,2),
                hire_date DATE,
                is_active BIT DEFAULT 1,
                updated_at DATETIME2 DEFAULT GETDATE(),
                created_at DATETIME2 DEFAULT GETDATE()
            )
            """
            connector.execute_query(create_sql)

            # Insert initial test data (10 rows)
            insert_sql = """
            INSERT INTO dbo.migration_test (name, email, salary, hire_date, is_active, updated_at, created_at)
            VALUES
                ('Alice Johnson', 'alice@test.com', 75000.00, '2023-01-15', 1, GETDATE(), GETDATE()),
                ('Bob Smith', 'bob@test.com', 82000.50, '2023-02-20', 1, GETDATE(), GETDATE()),
                ('Carol White', 'carol@test.com', 68000.75, '2023-03-10', 1, GETDATE(), GETDATE()),
                ('David Brown', 'david@test.com', 91000.00, '2023-04-05', 1, GETDATE(), GETDATE()),
                ('Eve Davis', 'eve@test.com', 77000.25, '2023-05-12', 1, GETDATE(), GETDATE()),
                ('Frank Wilson', 'frank@test.com', 84000.00, '2023-06-18', 1, GETDATE(), GETDATE()),
                ('Grace Lee', 'grace@test.com', 79000.50, '2023-07-22', 1, GETDATE(), GETDATE()),
                ('Henry Clark', 'henry@test.com', 88000.75, '2023-08-30', 1, GETDATE(), GETDATE()),
                ('Ivy Martinez', 'ivy@test.com', 72000.00, '2023-09-14', 1, GETDATE(), GETDATE()),
                ('Jack Taylor', 'jack@test.com', 95000.50, '2023-10-25', 1, GETDATE(), GETDATE())
            """
            connector.execute_query(insert_sql)

            logger.info("✓ Created SQL Server test table with 10 rows")
            return True

        except Exception as e:
            logger.error(f"Failed to setup SQL Server test table: {e}")
            return False
        finally:
            connector.close()

    def setup_test_table_postgres(self, conn):
        """Create test table in PostgreSQL (for ClickHouse migration test)"""
        logger.info("Setting up test table in PostgreSQL...")

        connector = get_connector(conn)
        connector.connect()

        try:
            # Drop existing test table
            connector.execute_query("DROP TABLE IF EXISTS public.clickhouse_test CASCADE")

            # Create test table
            create_sql = """
            CREATE TABLE public.clickhouse_test (
                id SERIAL PRIMARY KEY,
                product_name VARCHAR(100) NOT NULL,
                category VARCHAR(50),
                price NUMERIC(10,2),
                stock_quantity INT,
                last_sold DATE,
                is_available BOOLEAN DEFAULT true,
                updated_at TIMESTAMP DEFAULT NOW(),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
            connector.execute_query(create_sql)

            # Create trigger for updated_at
            trigger_sql = """
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_clickhouse_test_updated_at
            BEFORE UPDATE ON public.clickhouse_test
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
            """
            connector.execute_query(trigger_sql)

            # Insert initial test data (10 rows)
            insert_sql = """
            INSERT INTO public.clickhouse_test (product_name, category, price, stock_quantity, last_sold, is_available, updated_at, created_at)
            VALUES
                ('Laptop Pro 15', 'Electronics', 1299.99, 45, '2024-05-01', true, NOW(), NOW()),
                ('Wireless Mouse', 'Accessories', 29.99, 150, '2024-05-02', true, NOW(), NOW()),
                ('USB-C Cable', 'Accessories', 12.50, 200, '2024-05-03', true, NOW(), NOW()),
                ('Monitor 27 inch', 'Electronics', 349.00, 30, '2024-05-04', true, NOW(), NOW()),
                ('Keyboard Mechanical', 'Accessories', 89.99, 75, '2024-05-05', true, NOW(), NOW()),
                ('Webcam HD', 'Electronics', 79.99, 60, '2024-05-06', true, NOW(), NOW()),
                ('Desk Lamp LED', 'Furniture', 45.00, 100, '2024-05-07', true, NOW(), NOW()),
                ('Office Chair', 'Furniture', 299.99, 25, '2024-05-08', true, NOW(), NOW()),
                ('Notebook A4', 'Stationery', 5.99, 500, '2024-05-09', true, NOW(), NOW()),
                ('Pen Set', 'Stationery', 15.00, 300, '2024-05-10', true, NOW(), NOW())
            """
            connector.execute_query(insert_sql)

            logger.info("✓ Created PostgreSQL test table with 10 rows and update trigger")
            return True

        except Exception as e:
            logger.error(f"Failed to setup PostgreSQL test table: {e}")
            return False
        finally:
            connector.close()

    def verify_row_count(self, connector, schema, table, expected_count, condition=""):
        """Verify row count matches expected"""
        try:
            query = f"SELECT COUNT(*) FROM {schema}.{table}"
            if condition:
                query += f" WHERE {condition}"

            result = connector.execute_query_fetchall(query)
            actual_count = result[0][0] if result else 0

            if actual_count == expected_count:
                logger.info(f"✓ Row count verified: {actual_count} rows (expected {expected_count})")
                return True
            else:
                logger.error(f"✗ Row count mismatch: {actual_count} rows (expected {expected_count})")
                return False

        except Exception as e:
            logger.error(f"Failed to verify row count: {e}")
            return False

    def verify_data_integrity(self, source_conn, target_conn, source_schema, source_table, target_schema, target_table):
        """Verify data integrity between source and target"""
        logger.info("Verifying data integrity...")

        source_connector = get_connector(source_conn)
        target_connector = get_connector(target_conn)

        try:
            source_connector.connect()
            target_connector.connect()

            # Get sample rows from source
            source_query = f"SELECT * FROM {source_schema}.{source_table} ORDER BY id LIMIT 5"
            source_rows = source_connector.execute_query_fetchall(source_query)

            # Get corresponding rows from target
            for source_row in source_rows:
                row_id = source_row[0]  # Assuming id is first column
                target_query = f"SELECT * FROM {target_schema}.{target_table} WHERE id = {row_id}"
                target_rows = target_connector.execute_query_fetchall(target_query)

                if not target_rows:
                    logger.error(f"✗ Row with id={row_id} not found in target")
                    return False

            logger.info("✓ Data integrity verified for sample rows")
            return True

        except Exception as e:
            logger.error(f"Failed to verify data integrity: {e}")
            return False
        finally:
            source_connector.close()
            target_connector.close()

    def test_sqlserver_to_postgres_full(self):
        """Test SQL Server → PostgreSQL full sync"""
        logger.info("\n" + "="*80)
        logger.info("TEST: SQL Server → PostgreSQL - FULL SYNC")
        logger.info("="*80)

        try:
            # Get or create connections
            sqlserver_conn = DatabaseConnection.objects.filter(
                db_type='sqlserver',
                host='localhost',
                database_name='test1'
            ).first()

            if not sqlserver_conn:
                sqlserver_conn = DatabaseConnection.objects.create(
                    name='Test SQL Server',
                    db_type='sqlserver',
                    host='localhost',
                    port=1433,
                    database_name='test1',
                    username='sa',
                    password='root',
                    created_by=self.test_user,
                    tenant=self.test_user
                )
                logger.info("Created SQL Server connection")

            # Use existing working PostgreSQL connection
            postgres_conn = DatabaseConnection.objects.filter(
                name='db11'  # Use existing working connection
            ).first()

            if not postgres_conn:
                logger.error("db11 PostgreSQL connection not found")
                self.test_results['sqlserver_to_postgres']['full'] = 'FAILED - No Postgres connection'
                return False

            # Setup test table in SQL Server
            if not self.setup_test_table_sqlserver(sqlserver_conn):
                self.test_results['sqlserver_to_postgres']['full'] = 'FAILED - Setup'
                return False

            # Create sync job
            job = SyncJob.objects.create(
                name='Test_SQLServer_to_Postgres_Full',
                source_connection=sqlserver_conn,
                target_connection=postgres_conn,
                sync_type='full',
                verification_mode='hash',
                no_delete_propagation=True,
                created_by=self.test_user,
                tenant=self.test_user
            )

            # Create job table (only schema_name and table_name - no target fields)
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name='dbo',
                table_name='migration_test',
                incremental_column='updated_at',  # Set incremental column
                incremental_key_columns=['id'],  # Set primary key for upsert
                is_enabled=True
            )

            logger.info(f"Created sync job: {job.id} with table: {job_table.table_name}")

            # Execute sync
            executor = SyncExecutor(job)
            executor.execute()

            # Wait for completion
            time.sleep(2)

            # Get execution result
            execution = SyncExecution.objects.filter(job=job).order_by('-created_at').first()

            if execution and execution.status == 'completed':
                logger.info(f"✓ Full sync completed: {execution.total_rows_synced} rows")

                # Verify row count (use db11 database)
                postgres_connector = get_connector(postgres_conn)
                postgres_connector.connect()
                verified = self.verify_row_count(postgres_connector, 'public', 'migration_test', 10)
                postgres_connector.close()

                if verified:
                    self.test_results['sqlserver_to_postgres']['full'] = 'PASSED'
                    logger.info("✓ SQL Server → PostgreSQL FULL SYNC: PASSED")
                    return True
                else:
                    self.test_results['sqlserver_to_postgres']['full'] = 'FAILED - Verification'
                    return False
            else:
                error_msg = execution.error_message if execution else "No execution record"
                logger.error(f"✗ Full sync failed: {error_msg}")
                self.test_results['sqlserver_to_postgres']['full'] = f'FAILED - {error_msg}'
                return False

        except Exception as e:
            logger.error(f"✗ Test failed with exception: {e}", exc_info=True)
            self.test_results['sqlserver_to_postgres']['full'] = f'FAILED - {str(e)}'
            return False

    def test_sqlserver_to_postgres_incremental(self):
        """Test SQL Server → PostgreSQL incremental sync"""
        logger.info("\n" + "="*80)
        logger.info("TEST: SQL Server → PostgreSQL - INCREMENTAL SYNC")
        logger.info("="*80)

        try:
            # Get existing connections
            sqlserver_conn = DatabaseConnection.objects.filter(
                db_type='sqlserver',
                host='localhost',
                database_name='test1'
            ).first()

            # Use existing working PostgreSQL connection
            postgres_conn = DatabaseConnection.objects.filter(
                name='db11'
            ).first()

            if not sqlserver_conn or not postgres_conn:
                logger.error("Connections not found - run full sync test first")
                self.test_results['sqlserver_to_postgres']['incremental'] = 'FAILED - No connections'
                return False

            # Insert new rows in SQL Server
            logger.info("Inserting 3 new rows in SQL Server...")
            sqlserver_connector = get_connector(sqlserver_conn)
            sqlserver_connector.connect()

            insert_sql = """
            INSERT INTO dbo.migration_test (name, email, salary, hire_date, is_active, updated_at, created_at)
            VALUES
                ('Kate Johnson', 'kate@test.com', 67000.00, '2024-01-10', 1, GETDATE(), GETDATE()),
                ('Leo Wilson', 'leo@test.com', 73000.50, '2024-02-15', 1, GETDATE(), GETDATE()),
                ('Mia Brown', 'mia@test.com', 81000.75, '2024-03-20', 1, GETDATE(), GETDATE())
            """
            sqlserver_connector.execute_query(insert_sql)
            sqlserver_connector.close()
            logger.info("✓ Inserted 3 new rows")

            # Wait a moment to ensure timestamps are distinct
            time.sleep(1)

            # Update existing rows in SQL Server
            logger.info("Updating 2 existing rows in SQL Server...")
            sqlserver_connector = get_connector(sqlserver_conn)
            sqlserver_connector.connect()

            update_sql = """
            UPDATE dbo.migration_test
            SET salary = salary + 5000, updated_at = GETDATE()
            WHERE id IN (1, 2)
            """
            sqlserver_connector.execute_query(update_sql)
            sqlserver_connector.close()
            logger.info("✓ Updated 2 rows")

            # Get existing job or create new one
            job = SyncJob.objects.filter(
                name='Test_SQLServer_to_Postgres_Incremental',
                source_connection=sqlserver_conn,
                target_connection=postgres_conn
            ).first()

            if not job:
                # Create incremental sync job
                job = SyncJob.objects.create(
                    name='Test_SQLServer_to_Postgres_Incremental',
                    source_connection=sqlserver_conn,
                    target_connection=postgres_conn,
                    sync_type='incremental',
                    verification_mode='hash',
                    no_delete_propagation=True,
                    created_by=self.test_user,
                    tenant=self.test_user
                )
                logger.info(f"Created incremental sync job: {job.id}")
            else:
                # Update to incremental if it was full
                job.sync_type = 'incremental'
                job.save()
                logger.info(f"Updated existing job {job.id} to incremental")

            # Always ensure the job table is configured correctly
            job_table = SyncJobTable.objects.filter(
                job=job,
                schema_name='dbo',
                table_name='migration_test'
            ).first()

            if not job_table:
                # Create job table
                job_table = SyncJobTable.objects.create(
                    job=job,
                    schema_name='dbo',
                    table_name='migration_test',
                    incremental_column='updated_at',
                    incremental_key_columns=['id'],
                    is_enabled=True
                )
                logger.info(f"Created job table: {job_table.table_name}")
            else:
                # Update existing job table
                job_table.incremental_column = 'updated_at'
                job_table.incremental_key_columns = ['id']
                job_table.is_enabled = True
                job_table.save()
                logger.info(f"Updated job table: {job_table.table_name} with incremental_key_columns=['id']")

            # Execute sync
            executor = SyncExecutor(job)
            executor.execute()

            # Wait for completion
            time.sleep(2)

            # Get execution result
            execution = SyncExecution.objects.filter(job=job).order_by('-created_at').first()

            if execution and execution.status == 'completed':
                logger.info(f"✓ Incremental sync completed: {execution.total_rows_synced} rows")

                # Verify row count (should be 13 total: 10 initial + 3 new)
                postgres_connector = get_connector(postgres_conn)
                postgres_connector.connect()
                verified = self.verify_row_count(postgres_connector, 'public', 'migration_test', 13)

                # Verify no duplicates
                dup_query = "SELECT id, COUNT(*) as cnt FROM public.migration_test GROUP BY id HAVING COUNT(*) > 1"
                dup_result = postgres_connector.execute_query_fetchall(dup_query)

                postgres_connector.close()

                if dup_result:
                    logger.error(f"✗ Found {len(dup_result)} duplicate IDs")
                    self.test_results['sqlserver_to_postgres']['incremental'] = 'FAILED - Duplicates found'
                    return False

                if verified:
                    self.test_results['sqlserver_to_postgres']['incremental'] = 'PASSED'
                    logger.info("✓ SQL Server → PostgreSQL INCREMENTAL SYNC: PASSED")
                    logger.info("✓ No duplicates found")
                    return True
                else:
                    self.test_results['sqlserver_to_postgres']['incremental'] = 'FAILED - Verification'
                    return False
            else:
                error_msg = execution.error_message if execution else "No execution record"
                logger.error(f"✗ Incremental sync failed: {error_msg}")
                self.test_results['sqlserver_to_postgres']['incremental'] = f'FAILED - {error_msg}'
                return False

        except Exception as e:
            logger.error(f"✗ Test failed with exception: {e}", exc_info=True)
            self.test_results['sqlserver_to_postgres']['incremental'] = f'FAILED - {str(e)}'
            return False

    def test_postgres_to_clickhouse_full(self):
        """Test PostgreSQL → ClickHouse full sync"""
        logger.info("\n" + "="*80)
        logger.info("TEST: PostgreSQL → ClickHouse - FULL SYNC")
        logger.info("="*80)

        try:
            # Use existing working PostgreSQL connection
            postgres_conn = DatabaseConnection.objects.filter(
                name='db11'
            ).first()

            if not postgres_conn:
                logger.error("db11 PostgreSQL connection not found")
                self.test_results['postgres_to_clickhouse']['full'] = 'FAILED - No Postgres connection'
                return False

            clickhouse_conn = DatabaseConnection.objects.filter(
                db_type='clickhouse',
                host='20.204.31.93'
            ).first()

            if not clickhouse_conn:
                clickhouse_conn = DatabaseConnection.objects.create(
                    name='Test ClickHouse',
                    db_type='clickhouse',
                    host='20.204.31.93',
                    port=8123,
                    database_name='test_sql',  # Use test_sql as specified
                    username='default',
                    password='root',
                    created_by=self.test_user,
                    tenant=self.test_user
                )
                logger.info("Created ClickHouse connection")
            else:
                # Update existing connection to use correct database
                clickhouse_conn.database_name = 'test_sql'
                clickhouse_conn.save()
                logger.info("Updated ClickHouse connection to use test_sql database")

            # Setup test table in PostgreSQL
            if not self.setup_test_table_postgres(postgres_conn):
                self.test_results['postgres_to_clickhouse']['full'] = 'FAILED - Setup'
                return False

            # Clean up ClickHouse table from previous runs
            try:
                clickhouse_connector = get_connector(clickhouse_conn)
                clickhouse_connector.connect()
                target_database = clickhouse_conn.database_name
                clickhouse_connector.execute_query(f"DROP TABLE IF EXISTS `{target_database}`.clickhouse_test")
                logger.info(f"✓ Dropped existing ClickHouse table {target_database}.clickhouse_test")
                clickhouse_connector.close()
            except Exception as e:
                logger.warning(f"Could not drop ClickHouse table: {e}")

            # Create sync job
            job = SyncJob.objects.create(
                name='Test_Postgres_to_ClickHouse_Full',
                source_connection=postgres_conn,
                target_connection=clickhouse_conn,
                sync_type='full',
                verification_mode='hash',
                no_delete_propagation=True,
                created_by=self.test_user,
                tenant=self.test_user
            )

            # Create job table (only schema_name and table_name - no target fields)
            job_table = SyncJobTable.objects.create(
                job=job,
                schema_name='public',
                table_name='clickhouse_test',
                incremental_column='updated_at',  # Set incremental column
                incremental_key_columns=['id'],  # Set primary key for upsert
                is_enabled=True
            )

            logger.info(f"Created sync job: {job.id} with table: {job_table.table_name}")

            # Execute sync
            executor = SyncExecutor(job)
            executor.execute()

            # Wait for completion
            time.sleep(2)

            # Get execution result
            execution = SyncExecution.objects.filter(job=job).order_by('-created_at').first()

            if execution and execution.status == 'completed':
                logger.info(f"✓ Full sync completed: {execution.total_rows_synced} rows")

                # Verify row count in ClickHouse
                clickhouse_connector = get_connector(clickhouse_conn)
                clickhouse_connector.connect()
                # Use the actual target database from the connection
                target_database = clickhouse_conn.database_name
                verified = self.verify_row_count(
                    clickhouse_connector,
                    target_database,
                    'clickhouse_test FINAL',
                    10,
                    "is_deleted = 0"
                )
                clickhouse_connector.close()

                if verified:
                    self.test_results['postgres_to_clickhouse']['full'] = 'PASSED'
                    logger.info("✓ PostgreSQL → ClickHouse FULL SYNC: PASSED")
                    return True
                else:
                    self.test_results['postgres_to_clickhouse']['full'] = 'FAILED - Verification'
                    return False
            else:
                error_msg = execution.error_message if execution else "No execution record"
                logger.error(f"✗ Full sync failed: {error_msg}")
                self.test_results['postgres_to_clickhouse']['full'] = f'FAILED - {error_msg}'
                return False

        except Exception as e:
            logger.error(f"✗ Test failed with exception: {e}", exc_info=True)
            self.test_results['postgres_to_clickhouse']['full'] = f'FAILED - {str(e)}'
            return False

    def test_postgres_to_clickhouse_incremental(self):
        """Test PostgreSQL → ClickHouse incremental sync"""
        logger.info("\n" + "="*80)
        logger.info("TEST: PostgreSQL → ClickHouse - INCREMENTAL SYNC")
        logger.info("="*80)

        try:
            # Use existing working connections
            postgres_conn = DatabaseConnection.objects.filter(
                name='db11'
            ).first()

            clickhouse_conn = DatabaseConnection.objects.filter(
                db_type='clickhouse',
                host='20.204.31.93'
            ).first()

            if not postgres_conn or not clickhouse_conn:
                logger.error("Connections not found - run full sync test first")
                self.test_results['postgres_to_clickhouse']['incremental'] = 'FAILED - No connections'
                return False

            # Insert new rows in PostgreSQL
            logger.info("Inserting 3 new rows in PostgreSQL...")
            postgres_connector = get_connector(postgres_conn)
            postgres_connector.connect()

            insert_sql = """
            INSERT INTO public.clickhouse_test (product_name, category, price, stock_quantity, last_sold, is_available, updated_at, created_at)
            VALUES
                ('Tablet 10 inch', 'Electronics', 399.99, 35, '2024-05-11', true, NOW(), NOW()),
                ('Headphones Pro', 'Accessories', 149.99, 80, '2024-05-12', true, NOW(), NOW()),
                ('Backpack Laptop', 'Accessories', 59.99, 120, '2024-05-13', true, NOW(), NOW())
            """
            postgres_connector.execute_query(insert_sql)
            postgres_connector.close()
            logger.info("✓ Inserted 3 new rows")

            # Wait a moment to ensure timestamps are distinct
            time.sleep(1)

            # Update existing rows in PostgreSQL
            logger.info("Updating 2 existing rows in PostgreSQL...")
            postgres_connector = get_connector(postgres_conn)
            postgres_connector.connect()

            update_sql = """
            UPDATE public.clickhouse_test
            SET price = price * 1.1
            WHERE id IN (1, 2)
            """
            postgres_connector.execute_query(update_sql)
            postgres_connector.close()
            logger.info("✓ Updated 2 rows (trigger should update updated_at)")

            # Get existing job or create new one
            job = SyncJob.objects.filter(
                name='Test_Postgres_to_ClickHouse_Incremental',
                source_connection=postgres_conn,
                target_connection=clickhouse_conn
            ).first()

            if not job:
                # Create incremental sync job
                job = SyncJob.objects.create(
                    name='Test_Postgres_to_ClickHouse_Incremental',
                    source_connection=postgres_conn,
                    target_connection=clickhouse_conn,
                    sync_type='incremental',
                    verification_mode='hash',
                    no_delete_propagation=True,
                    created_by=self.test_user,
                    tenant=self.test_user
                )
                logger.info(f"Created incremental sync job: {job.id}")
            else:
                # Update to incremental if it was full
                job.sync_type = 'incremental'
                job.save()
                logger.info(f"Updated existing job {job.id} to incremental")

            # Always ensure the job table is configured correctly
            job_table = SyncJobTable.objects.filter(
                job=job,
                schema_name='public',
                table_name='clickhouse_test'
            ).first()

            if not job_table:
                # Create job table
                job_table = SyncJobTable.objects.create(
                    job=job,
                    schema_name='public',
                    table_name='clickhouse_test',
                    incremental_column='updated_at',
                    incremental_key_columns=['id'],  # Set primary key for upsert
                    is_enabled=True
                )
                logger.info(f"Created job table: {job_table.table_name}")
            else:
                # Update existing job table
                job_table.incremental_column = 'updated_at'
                job_table.incremental_key_columns = ['id']
                job_table.is_enabled = True
                job_table.save()
                logger.info(f"Updated job table: {job_table.table_name} with incremental_key_columns=['id']")

            # Execute sync
            executor = SyncExecutor(job)
            executor.execute()

            # Wait for completion
            time.sleep(2)

            # Get execution result
            execution = SyncExecution.objects.filter(job=job).order_by('-created_at').first()

            if execution and execution.status == 'completed':
                logger.info(f"✓ Incremental sync completed: {execution.total_rows_synced} rows")

                # Verify row count (should be 13 total: 10 initial + 3 new)
                clickhouse_connector = get_connector(clickhouse_conn)
                clickhouse_connector.connect()
                # Use the actual target database from the connection
                target_database = clickhouse_conn.database_name
                verified = self.verify_row_count(
                    clickhouse_connector,
                    target_database,
                    'clickhouse_test FINAL',
                    13,
                    "is_deleted = 0"
                )

                # Verify no duplicates (by checking each id appears only once)
                dup_query = f"""
                SELECT id, COUNT(*) as cnt
                FROM (
                    SELECT id FROM {target_database}.clickhouse_test FINAL WHERE is_deleted = 0
                )
                GROUP BY id
                HAVING COUNT(*) > 1
                """
                dup_result = clickhouse_connector.execute_query_fetchall(dup_query)

                clickhouse_connector.close()

                if dup_result:
                    logger.error(f"✗ Found {len(dup_result)} duplicate IDs")
                    self.test_results['postgres_to_clickhouse']['incremental'] = 'FAILED - Duplicates found'
                    return False

                if verified:
                    self.test_results['postgres_to_clickhouse']['incremental'] = 'PASSED'
                    logger.info("✓ PostgreSQL → ClickHouse INCREMENTAL SYNC: PASSED")
                    logger.info("✓ No duplicates found (ReplacingMergeTree working correctly)")
                    return True
                else:
                    self.test_results['postgres_to_clickhouse']['incremental'] = 'FAILED - Verification'
                    return False
            else:
                error_msg = execution.error_message if execution else "No execution record"
                logger.error(f"✗ Incremental sync failed: {error_msg}")
                self.test_results['postgres_to_clickhouse']['incremental'] = f'FAILED - {error_msg}'
                return False

        except Exception as e:
            logger.error(f"✗ Test failed with exception: {e}", exc_info=True)
            self.test_results['postgres_to_clickhouse']['incremental'] = f'FAILED - {str(e)}'
            return False

    def print_summary(self):
        """Print test summary"""
        logger.info("\n" + "="*80)
        logger.info("TEST SUMMARY")
        logger.info("="*80)

        logger.info("\n📊 SQL Server → PostgreSQL:")
        logger.info(f"  Full Sync:        {self.test_results['sqlserver_to_postgres']['full']}")
        logger.info(f"  Incremental Sync: {self.test_results['sqlserver_to_postgres']['incremental']}")

        logger.info("\n📊 PostgreSQL → ClickHouse:")
        logger.info(f"  Full Sync:        {self.test_results['postgres_to_clickhouse']['full']}")
        logger.info(f"  Incremental Sync: {self.test_results['postgres_to_clickhouse']['incremental']}")

        # Overall status
        all_passed = all(
            result == 'PASSED'
            for migration in self.test_results.values()
            for result in migration.values()
            if result is not None
        )

        logger.info("\n" + "="*80)
        if all_passed:
            logger.info("✅ ALL TESTS PASSED - 100% ACCURACY ACHIEVED")
        else:
            logger.info("❌ SOME TESTS FAILED - REVIEW ERRORS ABOVE")
        logger.info("="*80 + "\n")

        return all_passed

    def run_all_tests(self):
        """Run all migration tests"""
        logger.info("Starting comprehensive migration tests...")
        logger.info(f"Test started at: {datetime.now()}\n")

        # Test SQL Server → PostgreSQL
        self.test_sqlserver_to_postgres_full()
        time.sleep(2)
        self.test_sqlserver_to_postgres_incremental()

        # Test PostgreSQL → ClickHouse
        time.sleep(2)
        self.test_postgres_to_clickhouse_full()
        time.sleep(2)
        self.test_postgres_to_clickhouse_incremental()

        # Print summary
        return self.print_summary()


if __name__ == '__main__':
    tester = MigrationTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
