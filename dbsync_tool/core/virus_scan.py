"""
Virus scanning service for file uploads using ClamAV integration.
"""
import logging
import subprocess
import os
from typing import Optional, Tuple
from django.conf import settings

logger = logging.getLogger(__name__)


class VirusScanError(Exception):
    """Raised when virus scanning fails or virus is detected."""
    pass


class VirusScanner:
    """
    Virus scanner service using ClamAV.

    Configuration in settings.py:
        VIRUS_SCAN_ENABLED = True/False
        CLAMAV_SOCKET = '/var/run/clamav/clamd.ctl'  # Unix socket path
        CLAMAV_HOST = 'localhost'  # TCP host (if no socket)
        CLAMAV_PORT = 3310  # TCP port
    """

    def __init__(self):
        self.enabled = getattr(settings, 'VIRUS_SCAN_ENABLED', False)
        self.socket_path = getattr(settings, 'CLAMAV_SOCKET', None)
        self.host = getattr(settings, 'CLAMAV_HOST', 'localhost')
        self.port = getattr(settings, 'CLAMAV_PORT', 3310)

    def is_available(self) -> bool:
        """Check if ClamAV scanner is available."""
        if not self.enabled:
            return False

        try:
            # Try clamdscan first (faster, uses daemon)
            result = subprocess.run(
                ['clamdscan', '--version'],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        try:
            # Fallback to clamscan (slower, standalone)
            result = subprocess.run(
                ['clamscan', '--version'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def scan_file(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Scan a file for viruses.

        Args:
            file_path: Absolute path to file to scan

        Returns:
            Tuple of (is_clean, threat_name)
            - (True, None) if file is clean
            - (False, "virus_name") if virus detected

        Raises:
            VirusScanError: If scanning fails
        """
        if not self.enabled:
            logger.debug("Virus scanning disabled, skipping scan")
            return True, None

        if not os.path.exists(file_path):
            raise VirusScanError(f"File not found: {file_path}")

        # Try clamdscan first (faster)
        try:
            result = subprocess.run(
                ['clamdscan', '--no-summary', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                # Clean file
                return True, None
            elif result.returncode == 1:
                # Virus found
                threat = self._extract_threat_name(result.stdout)
                logger.warning(f"Virus detected in {file_path}: {threat}")
                return False, threat
            else:
                # Error occurred
                raise VirusScanError(f"ClamAV scan failed: {result.stderr}")

        except FileNotFoundError:
            # clamdscan not found, try clamscan
            logger.debug("clamdscan not found, falling back to clamscan")

        except subprocess.TimeoutExpired:
            raise VirusScanError("Virus scan timed out after 30 seconds")

        # Fallback to clamscan (slower)
        try:
            result = subprocess.run(
                ['clamscan', '--no-summary', file_path],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                return True, None
            elif result.returncode == 1:
                threat = self._extract_threat_name(result.stdout)
                logger.warning(f"Virus detected in {file_path}: {threat}")
                return False, threat
            else:
                raise VirusScanError(f"ClamAV scan failed: {result.stderr}")

        except FileNotFoundError:
            if self.enabled:
                logger.error("ClamAV not installed but VIRUS_SCAN_ENABLED=True")
                raise VirusScanError("ClamAV is not installed or not in PATH")
            return True, None

        except subprocess.TimeoutExpired:
            raise VirusScanError("Virus scan timed out after 60 seconds")

    def _extract_threat_name(self, output: str) -> str:
        """Extract virus/threat name from ClamAV output."""
        # ClamAV output format: "/path/to/file: Threat.Name FOUND"
        for line in output.splitlines():
            if ' FOUND' in line:
                parts = line.split(': ')
                if len(parts) >= 2:
                    threat_part = parts[-1].replace(' FOUND', '').strip()
                    return threat_part
        return "Unknown threat"

    def scan_uploaded_file(self, uploaded_file) -> Tuple[bool, Optional[str]]:
        """
        Scan an uploaded Django file.

        Args:
            uploaded_file: Django UploadedFile object

        Returns:
            Tuple of (is_clean, threat_name)

        Raises:
            VirusScanError: If scanning fails
        """
        if not self.enabled:
            return True, None

        # For TemporaryUploadedFile, scan the temp file directly
        if hasattr(uploaded_file, 'temporary_file_path'):
            temp_path = uploaded_file.temporary_file_path()
            return self.scan_file(temp_path)

        # For InMemoryUploadedFile, write to temp file first
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            try:
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
                tmp.flush()
                temp_path = tmp.name

                # Scan the temp file
                result = self.scan_file(temp_path)

                return result
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except OSError as e:
                    logger.warning(f"Failed to delete temp file {temp_path}: {e}")


# Singleton instance
_scanner = None


def get_virus_scanner() -> VirusScanner:
    """Get the global virus scanner instance."""
    global _scanner
    if _scanner is None:
        _scanner = VirusScanner()
    return _scanner


def scan_file(file_path: str) -> Tuple[bool, Optional[str]]:
    """Convenience function to scan a file."""
    scanner = get_virus_scanner()
    return scanner.scan_file(file_path)


def scan_uploaded_file(uploaded_file) -> Tuple[bool, Optional[str]]:
    """Convenience function to scan an uploaded file."""
    scanner = get_virus_scanner()
    return scanner.scan_uploaded_file(uploaded_file)
