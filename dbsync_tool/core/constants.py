"""
Constants used throughout the application
"""

# Database type choices
# NOTE: When adding new database backends, update DB_TYPES, DEFAULT_PORTS,
# and CONNECTION_STRING_TEMPLATES so they can be surfaced consistently in
# forms, views, and tests.
DB_TYPES = [
    ('postgres', 'PostgreSQL'),
    ('mysql', 'MySQL'),
    ('sqlserver', 'SQL Server'),
    ('clickhouse', 'ClickHouse'),
    ('oracle_adw', 'Oracle ADW'),
]

DB_TYPE_CHOICES = DB_TYPES

# Default ports for each database type
DEFAULT_PORTS = {
    'postgres': 5432,
    'mysql': 3306,
    'sqlserver': 1433,
    'clickhouse': 9000,  # Native protocol port (HTTP is 8123)
    # Oracle Autonomous Data Warehouse typically uses TCPS on 1522
    'oracle_adw': 1522,
}

# Connection string templates (for reference, not used directly)
CONNECTION_STRING_TEMPLATES = {
    'postgres': 'postgresql://{username}:{password}@{host}:{port}/{database}',
    'mysql': 'mysql+connector://{username}:{password}@{host}:{port}/{database}',
    'sqlserver': 'mssql+pyodbc://{username}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server',
    'clickhouse': 'clickhouse://{username}:{password}@{host}:{port}/{database}',
    # Reference JDBC-style template for Oracle ADW. The actual Python connector
    # will use an oracledb DSN built from host/port/service name, but we keep
    # this here to clarify the expected pieces of the JDBC string.
    'oracle_adw': 'jdbc:oracle:thin:@//{host}:{port}/{database}',
}

# Sync job status choices
SYNC_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('running', 'Running'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
    ('paused', 'Paused'),
]

# Sync type choices
SYNC_TYPE_CHOICES = [
    ('full', 'Full Sync'),
    ('incremental', 'Incremental Sync'),
]

# Execution status choices
EXECUTION_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('running', 'Running'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
    ('cancelled', 'Cancelled'),
]

# Schedule type choices
SCHEDULE_TYPE_CHOICES = [
    ('once', 'Once'),
    ('hourly', 'Hourly'),
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('custom', 'Custom Cron'),
]

# Batch processing constants
DEFAULT_BATCH_SIZE = 5000  # Rows per batch
MAX_BATCH_SIZE = 10000
MIN_BATCH_SIZE = 100

# Type mapping reference (actual implementation in type_mapping.py)
TYPE_MAPPING_MODULE = 'core.type_mapping'

# API type choices
API_TYPE_CHOICES = [
    ('zoho_crm', 'Zoho CRM'),
    ('sap_b1', 'SAP Business One'),
]

# SAP API region mappings (for future multi-region/custom server support)
SAP_API_REGIONS = {
    'default': 'Custom SAP Server',
}

# SAP Business One document types / endpoints for sync (full list – all 25)
# Endpoints match SAP B1 Service Layer OData entity names; id_field used for incremental sync.
SAP_DOCUMENT_TYPES = [
    {"name": "Journal Entries", "endpoint": "JournalEntries", "id_field": "JdtNum"},
    {"name": "Chart Of Accounts", "endpoint": "ChartOfAccounts", "id_field": "Code"},
    {"name": "Item Master", "endpoint": "Items", "id_field": "ItemCode"},
    {"name": "Capitalization", "endpoint": "AssetCapitalization", "id_field": "DocEntry"},
    {"name": "Manual Depreciation", "endpoint": "AssetDepreciation", "id_field": "DocEntry"},
    {"name": "Sales Orders", "endpoint": "Orders", "id_field": "DocEntry"},
    {"name": "Delivery Notes", "endpoint": "DeliveryNotes", "id_field": "DocEntry"},
    {"name": "A/R Invoices", "endpoint": "Invoices", "id_field": "DocEntry"},
    {"name": "Returns", "endpoint": "Returns", "id_field": "DocEntry"},
    {"name": "A/R Credit Memos", "endpoint": "CreditNotes", "id_field": "DocEntry"},
    {"name": "Purchase Orders", "endpoint": "PurchaseOrders", "id_field": "DocEntry"},
    {"name": "GRPO", "endpoint": "PurchaseDeliveryNotes", "id_field": "DocEntry"},
    {"name": "Goods Return", "endpoint": "PurchaseReturns", "id_field": "DocEntry"},
    {"name": "A/P Invoices", "endpoint": "PurchaseInvoices", "id_field": "DocEntry"},
    {"name": "A/P Credit Memos", "endpoint": "PurchaseCreditNotes", "id_field": "DocEntry"},
    {"name": "BP Master", "endpoint": "BusinessPartners", "id_field": "CardCode"},
    {"name": "Incoming Payments", "endpoint": "IncomingPayments", "id_field": "DocEntry"},
    {"name": "Outgoing Payments", "endpoint": "VendorPayments", "id_field": "DocEntry"},
    {"name": "Items - Warehouse", "endpoint": "ItemsWarehouse", "id_field": "ItemCode"},
    {"name": "Goods Receipt", "endpoint": "InventoryGenEntry", "id_field": "DocEntry"},
    {"name": "Goods Issue", "endpoint": "InventoryGenExit", "id_field": "DocEntry"},
    {"name": "Inventory Transfer", "endpoint": "StockTransfers", "id_field": "DocEntry"},
    {"name": "Bill Of Materials", "endpoint": "BillOfMaterials", "id_field": "ItemCode"},
    {"name": "Production Orders", "endpoint": "ProductionOrders", "id_field": "DocEntry"},
    {"name": "Price Lists", "endpoint": "PriceLists", "id_field": "PriceListNo"},
]

# Connection category choices (for future use)
CONNECTION_CATEGORY_CHOICES = [
    ('database', 'Database'),
    ('api', 'API'),
]

# Zoho API domain mappings
ZOHO_API_DOMAINS = {
    'india': 'https://www.zohoapis.in',
    'us': 'https://www.zohoapis.com',
    'europe': 'https://www.zohoapis.eu',
    'australia': 'https://www.zohoapis.com.au',
}

# Zoho token URL mappings
ZOHO_DEFAULT_TOKEN_URLS = {
    'https://www.zohoapis.in': 'https://accounts.zoho.in/oauth/v2/token',
    'https://www.zohoapis.com': 'https://accounts.zoho.com/oauth/v2/token',
    'https://www.zohoapis.eu': 'https://accounts.zoho.eu/oauth/v2/token',
    'https://www.zohoapis.com.au': 'https://accounts.zoho.com.au/oauth/v2/token',
}
