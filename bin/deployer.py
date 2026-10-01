#!/usr/bin/env python3
"""
Deployment Wrapper - Orchestrates the complete Flask application deployment process.

This module manages the deployment flow, handles zip packaging/extraction,
and tracks version incrementing for distributable releases.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Import local modules
sys.path.insert(0, str(Path(__file__).parent))

from lib.deployment_logger import DeploymentLogger
from lib.version_manager import VersionManager
from lib.system_validator import SystemValidator
from lib/database_initializer import DatabaseInitializer
from lib.application_deployer import ApplicationDeployer
from lib.security_manager import SecurityManager

class DeploymentOrchestrator:
    """Main deployment orchestrator class."""

    def __init__(self, config: Dict):
        self.config = config
        self.logger = DeploymentLogger(config.get('log_level', 'INFO'))
        self.version_manager = VersionManager(
            config.get('version_file', 'version.json'),
            config.get('version_scheme', 'semver')
        )
        self.validator = SystemValidator(self.logger)
        self.db_initializer = DatabaseInitializer(self.logger, config)
        self.app_deployer = ApplicationDeployer(self.logger, config)
        self.security_manager = SecurityManager(self.logger, config)

    def run(self) -> bool:
        """Execute the complete deployment process."""
        deployment_id = f"deploy_{int(time.time())}_{hashlib.md5(str(self.config).encode()).hexdigest()[:8]}"
        self.logger.info(f"Starting deployment: {deployment_id}")

        try:
            # Step 1: Validate server configuration
            self.logger.info("Step 1: Validating server configuration...")
            if not self.validator.validate_server():
                self.logger.error("Server validation failed")
                return False

            # Step 2: Install dependencies if needed
            self.logger.info("Step 2: Installing dependencies...")
            if not self.validator.install_dependencies():
                self.logger.error("Dependency installation failed")
                return False

            # Step 3: Configure domain/IP and port
            self.logger.info("Step 3: Configuring network...")
            if not self.security_manager.configure_network():
                self.logger.error("Network configuration failed")
                return False

            # Step 4: Initialize database
            self.logger.info("Step 4: Initializing database...")
            if not self.db_initializer.initialize_database():
                self.logger.error("Database initialization failed")
                return False

            # Step 5: Generate and store installation key
            self.logger.info("Step 5: Generating installation key...")
            installation_key = self.security_manager.generate_installation_key()
            if not self.security_manager.store_installation_key(installation_key):
                self.logger.error("Installation key storage failed")
                return False

            # Step 6: Deploy application
            self.logger.info("Step 6: Deploying application...")
            if not self.app_deployer.deploy():
                self.logger.error("Application deployment failed")
                return False

            # Step 7: Package deployment
            self.logger.info("Step 7: Packaging deployment...")
            if not self._package_deployment():
                self.logger.error("Deployment packaging failed")
                return False

            # Step 8: Version management
            self.logger.info("Step 8: Managing version...")
            if not self._manage_version():
                self.logger.error("Version management failed")
                return False

            # Step 9: Verify deployment
            self.logger.info("Step 9: Verifying deployment...")
            if not self._verify_deployment():
                self.logger.error("Deployment verification failed")
                return False

            self.logger.info(f"Deployment {deployment_id} completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Deployment failed with exception: {e}")
            return False

    def _package_deployment(self) -> bool:
        """Package the complete deployment into a zip file."""
        try:
            deployment_root = Path(self.config.get('deployment_root', '.'))
            package_name = f"webcreoling_deployment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            package_path = Path(self.config.get('packages_dir', 'packages')) / package_name
            package_path.parent.mkdir(exist_ok=True)

            self.logger.info(f"Creating deployment package: {package_path}")

            with zipfile.ZipFile(package_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add application code
                for item in deployment_root.rglob('*'):
                    if item.is_file() and not item.name.startswith('.') and 'packages' not in str(item):
                        rel_path = item.relative_to(deployment_root.parent)
                        zipf.write(item, rel_path)

                # Add deployment scripts and configs
                config_dir = deployment_root / 'config'
                if config_dir.exists():
                    for item in config_dir.rglob('*'):
                        if item.is_file():
                            rel_path = item.relative_to(deployment_root.parent)
                            zipf.write(item, rel_path)

            self.logger.info(f"Deployment package created at: {package_path}")
            return True

        except Exception as e:
            self.logger.error(f"Packaging failed: {e}")
            return False

    def _manage_version(self) -> bool:
        """Manage version based on deployment type."""
        try:
            deployment_type = self.config.get('deployment_type', 'initial')

            if deployment_type == 'initial':
                self.version_manager.set_version('1.0.0')
                self.logger.info("Set initial version to 1.0.0")
            elif deployment_type == 'update':
                current_version = self.version_manager.get_version()
                new_version = self.version_manager.increment_minor_version()
                self.logger.info(f"Incremented version from {current_version} to {new_version}")
            elif deployment_type == 'bugfix':
                current_version = self.version_manager.get_version()
                new_version = self.version_manager.increment_patch_version()
                self.logger.info(f"Incremented version from {current_version} to {new_version}")

            return True

        except Exception as e:
            self.logger.error(f"Version management failed: {e}")
            return False

    def _verify_deployment(self) -> bool:
        """Verify the deployment is functional."""
        try:
            # Check if critical files exist
            deployment_root = Path(self.config.get('deployment_root', '.'))

            # Check for Python files
            python_files = list(deployment_root.rglob('*.py'))
            if len(python_files) < 10:
                self.logger.error(f"Expected at least 10 Python files, found {len(python_files)}")
                return False

            # Check for configuration files
            config_files = list(deployment_root.glob('config.json'))
            if not config_files and not Path('.env').exists():
                self.logger.error("No configuration files found")
                return False

            # Check for database files
            db_files = list(deployment_root.glob('*.db')) + list(deployment_root.rglob('data/*.db'))
            if not db_files:
                self.logger.warning("No database files found (may be created later)")

            self.logger.info("Deployment verification completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Deployment verification failed: {e}")
            return False


def main():
    """Main entry point for the deployment wrapper."""
    parser = argparse.ArgumentParser(
        description="Deploy Flask web application with MySQL database"
    )

    parser.add_argument('--domain', required=True,
                        help='Custom domain name (e.g., example.com)')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port to use (default: 5000)')
    parser.add_argument('--deployment-type', default='initial',
                       choices=['initial', 'update', 'bugfix'],
                       help='Type of deployment (default: initial)')
    parser.add_argument('--version-file', default='version.json',
                       help='Path to version tracking file')
    parser.add_argument('--deployment-root', default='.',
                       help='Root directory of the deployment')
    parser.add_argument('--packages-dir', default='packages',
                       help='Directory to store deployment packages')
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level')
    parser.add_argument('--skip-validation', action='store_true',
                       help='Skip server validation (not recommended)')
    parser.add_argument('--force', action='store_true',
                       help='Force deployment even if validation fails')

    args = parser.parse_args()

    # Configuration
    config = {
        'domain': args.domain,
        'port': args.port,
        'deployment_type': args.deployment_type,
        'version_file': args.version_file,
        'deployment_root': args.deployment_root,
        'packages_dir': args.packages_dir,
        'log_level': args.log_level,
        'skip_validation': args.skip_validation,
        'force': args.force,
        'generated_at': datetime.now().isoformat(),
        'server_hostname': os.uname()[1],
    }

    # Create deployment directory
    Path(args.packages_dir).mkdir(exist_ok=True)

    # Run deployment
    orchestrator = DeploymentOrchestrator(config)
    success = orchestrator.run()

    if success:
        print("✓ Deployment completed successfully")
        sys.exit(0)
    else:
        print("✗ Deployment failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
