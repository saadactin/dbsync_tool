"""
Base API connector abstract class
All API-specific connectors inherit from this class
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime


class APIConnector(ABC):
    """
    Abstract base class for API connectors
    All API-specific connectors must implement these methods
    """
    
    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with API and return success status
        
        Returns:
            bool: True if authentication successful, False otherwise
            
        Raises:
            Exception: If authentication fails with error details
        """
        pass
    
    @abstractmethod
    def get_available_modules(self) -> List[str]:
        """
        Get list of available modules/entities from the API
        
        Returns:
            List[str]: List of module/entity names available for syncing
            
        Raises:
            Exception: If module discovery fails
        """
        pass
    
    @abstractmethod
    def fetch_records(
        self, 
        module: str, 
        params: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Fetch all records from a module (full sync)
        
        Args:
            module: Module/entity name to fetch records from
            params: Optional parameters for filtering, pagination, etc.
            
        Returns:
            List[Dict]: List of record dictionaries
            
        Raises:
            Exception: If record fetching fails
        """
        pass
    
    @abstractmethod
    def fetch_incremental_records(
        self, 
        module: str, 
        since: datetime
    ) -> List[Dict]:
        """
        Fetch records modified since a specific timestamp (incremental sync)
        
        Args:
            module: Module/entity name to fetch records from
            since: Datetime object representing the earliest modification time
            
        Returns:
            List[Dict]: List of record dictionaries modified since 'since' timestamp
            
        Raises:
            Exception: If incremental record fetching fails
        """
        pass
