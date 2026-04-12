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
    ('mongodb', 'MongoDB'),
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
    'mongodb': 27017,
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
    'mongodb': 'mongodb://{username}:{password}@{host}:{port}/{database}',
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
    ('azure_devops', 'Azure DevOps'),
]

# SAP API region mappings (for future multi-region/custom server support)
SAP_API_REGIONS = {
    'default': 'Custom SAP Server',
}

# SAP Business One document types / endpoints for sync (full list – all 23)
# Endpoints match SAP B1 Service Layer OData entity names; id_field used for incremental sync.
# Last updated: 2026-03-17 13:30 (Added 23 tables and target_table mapping)
SAP_DOCUMENT_TYPES = [
    {"name": "Journal Entries", "endpoint": "JournalEntries", "id_field": "JdtNum", "incremental_field": "TaxDate", "target_table": "journal_entries"},
    {"name": "Chart Of Accounts", "endpoint": "ChartOfAccounts", "id_field": "Code", "target_table": "chart_of_accounts"},
    {"name": "Item Master", "endpoint": "Items", "id_field": "ItemCode", "target_table": "items"},
    {"name": "Capitalization", "endpoint": "AssetCapitalization", "id_field": "DocEntry", "incremental_field": "PostingDate", "target_table": "asset_capitalization"},
    {"name": "Sales Orders", "endpoint": "Orders", "id_field": "DocEntry", "target_table": "sales_orders"},
    {"name": "Delivery Notes", "endpoint": "DeliveryNotes", "id_field": "DocEntry", "target_table": "delivery_notes"},
    {"name": "A/R Invoices", "endpoint": "Invoices", "id_field": "DocEntry", "target_table": "ar_invoices"},
    {"name": "Returns", "endpoint": "Returns", "id_field": "DocEntry", "target_table": "returns"},
    {"name": "A/R Credit Memos", "endpoint": "CreditNotes", "id_field": "DocEntry", "target_table": "ar_credit_memos"},
    {"name": "Purchase Orders", "endpoint": "PurchaseOrders", "id_field": "DocEntry", "target_table": "purchase_orders"},
    {"name": "GRPO", "endpoint": "PurchaseDeliveryNotes", "id_field": "DocEntry", "target_table": "purchase_delivery_notes"},
    {"name": "Goods Return", "endpoint": "PurchaseReturns", "id_field": "DocEntry", "target_table": "purchase_returns"},
    {"name": "A/P Invoices", "endpoint": "PurchaseInvoices", "id_field": "DocEntry", "target_table": "ap_invoices"},
    {"name": "A/P Credit Memos", "endpoint": "PurchaseCreditNotes", "id_field": "DocEntry", "target_table": "ap_credit_memos"},
    {"name": "BP Master", "endpoint": "BusinessPartners", "id_field": "CardCode", "target_table": "business_partners"},
    {"name": "Incoming Payments", "endpoint": "IncomingPayments", "id_field": "DocEntry", "incremental_field": "DocDate", "target_table": "incoming_payments"},
    {"name": "Outgoing Payments", "endpoint": "VendorPayments", "id_field": "DocEntry", "target_table": "vendor_payments"},
    {"name": "Items - Warehouse", "endpoint": "ItemsWarehouseInfo", "id_field": "ItemCode", "target_table": "items_warehouse"},
    {"name": "Goods Receipt", "endpoint": "InventoryGenEntries", "id_field": "DocEntry", "target_table": "inventory_gen_entries"},
    {"name": "Goods Issue", "endpoint": "InventoryGenExits", "id_field": "DocEntry", "target_table": "inventory_gen_exits"},
    {"name": "Inventory Transfer", "endpoint": "StockTransfers", "id_field": "DocEntry", "target_table": "stock_transfers"},
    {"name": "Production Orders", "endpoint": "ProductionOrders", "id_field": "AbsoluteEntry", "target_table": "production_orders"},
    {"name": "Price Lists", "endpoint": "PriceLists", "id_field": "PriceListNo", "target_table": "price_lists"},
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

# Step 3 protected column defaults.
# Lower-case values matched exactly against source column names.
DEFAULT_PROTECTED_COLUMN_NAMES = [
    "created_at",
    "createdon",
    "created_date",
    "created_time",
    "createdby",
    "tenant_id",
    "company_id",
    "org_id",
]
