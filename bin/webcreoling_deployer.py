#!/usr/bin/env python3
"""
Webcreoling Deployment Script - Main entry point for deployment operations.

This script orchestrates the complete deployment process using the deployment wrapper,
which in turn uses the Bash script for system-level operations.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Import the deployment wrapper
from bin.deployer import DeploymentOrchestrator
class WebcreolingDeployer:
    """Main deployment class for Webcreoling application."""

    def __init__(self):
        self.deployment_script_path = Path(__file__).parent / 'deployment.sh'
        self.setup_config()

    def setup_config(self):
        """Setup default configuration."""
        self.config = {
            'deployment_type': 'initial',
            'skip_validation': False,
            'skip_mysql': False,
            'skip_nginx': False,
            'skip_service': False,
            'log_level': 'INFO',
            'min_disk_space_gb': 10,
            'package_cleanup': True,
            'security_hardening': True,
            'version_scheme': 'semver',
            'environment': 'production',
            'deployment_id': f"deploy_{int(datetime.now().timestamp())}",
            'generated_at': datetime.now().isoformat(),
        }

    def run(self, args):
        """Run the deployment process."""
        print("=" * 60)
        print("Webcreoling Deployment Script")
        print("=" * 60)

        # Update config with command line arguments
        if args.domain:
            self.config['domain'] = args.domain
        if args.port:
            self.config['port'] = args.port
        if args.db_name:
            self.config['database'] = {'name': args.db_name}
        if args.db_user:
            if 'database' not in self.config:
                self.config['database'] = {}
            self.config['database']['user'] = args.db_user
        if args.db_pass:
            if 'database' not in self.config:
                self.config['database'] = {}
            self.config['database']['password'] = args.db_pass
        if args.deployment_root:
            self.config['deployment_root'] = args.deployment_root
        if args.deployment_type:
            self.config['deployment_type'] = args.deployment_type
        if args.skip_validation:
            self.config['skip_validation'] = True
        if args.skip_mysql:
            self.config['skip_mysql'] = True
        if args.skip_nginx:
            self.config['skip_nginx'] = True
        if args.skip_service:
            self.config['skip_service'] = True
        if args.version_file:
            self.config['version_file'] = args.version_file
        if args.packages_dir:
            self.config['packages_dir'] = args.packages_dir
        if args.log_level:
            self.config['log_level'] = args.log_level
        if args.force:
            self.config['force'] = True

        # Validate configuration
        if not self._validate_config():
            return False

        # Create deployment directory
        deployment_path = Path(self.config.get('deployment_root', '/opt/webapp'))
        deployment_path.mkdir(parents=True, exist_ok=True)

        # Write configuration
        self._write_config(deployment_path)

        # Run deployment using the orchestrator
        return self._run_deployment()

    def _validate_config(self):
        """Validate configuration."""
        required_fields = ['domain']

        for field in required_fields:
            if field not in self.config:
                print(f"Error: Required field '{field}' is missing")
                return False

        # Validate deployment root permissions
        deployment_path = Path(self.config.get('deployment_root', '/opt/webapp'))
        if not deployment_path.exists():
            try:
                deployment_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"Error: Cannot create deployment directory {deployment_path}: {e}")
                return False

        return True

    def _write_config(self, deployment_path: Path):
        """Write configuration to deployment directory."""
        config_file = deployment_path / 'deployment_config.json'

        config_data = {
            'config': self.config,
            'deployment_info': {
                'deployment_id': self.config.get('deployment_id'),
                'generated_at': self.config.get('generated_at'),
                'version': '1.0.0',
                'environment': self.config.get('environment'),
            }
        }

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        print(f"Configuration written to: {config_file}")

    def _run_deployment(self):
        """Run the deployment process."""
        print("Starting deployment process...")

        # Create temporary deployment configuration
        deployment_config = self._create_deployment_config()

        # Run deployment
        orchestrator = DeploymentOrchestrator(deployment_config)
        success = orchestrator.run()

        if success:
            print("✓ Deployment completed successfully")
            return True
        else:
            print("✗ Deployment failed")
            return False

    def _create_deployment_config(self):
        """Create deployment configuration for the orchestrator."""
        return {
            'domain': self.config.get('domain'),
            'port': self.config.get('port', 5000),
            'deployment_type': self.config.get('deployment_type', 'initial'),
            'version_file': self.config.get('version_file', 'version.json'),
            'deployment_root': self.config.get('deployment_root', '/opt/webapp'),
            'packages_dir': self.config.get('packages_dir', 'packages'),
            'log_level': self.config.get('log_level', 'INFO'),
            'skip_validation': self.config.get('skip_validation', False),
            'force': self.config.get('force', False),
        }

    def show_help(self):
        """Show help information."""
        help_text = """
Webcreoling Deployment Script

This script deploys the Webcreoling Flask application with MySQL database
on a target Linux server.

USAGE:
    python3 deployer.py [OPTIONS]

OPTIONS:
    --domain DOMAIN              Custom domain name (e.g., example.com)
    --port PORT                  Port to use (default: 5000)
    --db-name NAME               Database name (default: webcreoling)
    --db-user USER               Database username (default: webcreoling)
    --db-pass PASS               Database password (default: generated)
    --deployment-root DIR         Deployment root directory (default: /opt/webapp)
    --deployment-type TYPE        Deployment type (initial, update, bugfix)
    --version-file FILE           Version tracking file (default: version.json)
    --packages-dir DIR            Package storage directory (default: packages)
    --log-level LEVEL            Logging level (DEBUG, INFO, WARNING, ERROR)
    --skip-validation            Skip server validation
    --skip-mysql                 Skip MySQL configuration
    --skip-nginx                 Skip nginx configuration
    --skip-service               Skip systemd service setup
    --force                      Force deployment even if validation fails
    --help                       Show this help message

EXAMPLES:
    # Initial deployment
    python3 deployer.py --domain example.com --port 8080

    # Deployment with custom database
    python3 deployer.py --domain example.com --db-name mydb --db-user myuser --db-pass mypass

    # Skip validation for development
    python3 deployer.py --domain example.com --skip-validation --skip-mysql

    # Update deployment
    python3 deployer.py --domain example.com --deployment-type update

    # Bugfix deployment
    python3 deployer.py --domain example.com --deployment-type bugfix

REQUIREMENTS:
    - Root access to the target server
    - SSH access to the target server
    - Internet connectivity (for installing packages)
    - At least 10GB of free disk space

DEPLOYMENT FLOW:
    1. Validate server configuration and prerequisites
    2. Install system dependencies (if needed)
    3. Configure domain/IP binding and port assignment
    4. Initialize database with schema and reference data
    5. Generate and securely store installation key
    6. Deploy application and configure web server
    7. Package deployment for distribution
    8. Manage version tracking
    9. Verify deployment is functional

For more information, visit: https://github.com/infomotin/webcreoling
        """
        print(help_text)
class ArgumentParser:
    """Custom argument parser for the deployment script."""

    def __init__(self):
        self.parser = argparse.ArgumentParser(
            description="Deploy Flask web application with MySQL database",
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        self._add_arguments()

    def _add_arguments(self):
        """Add all command line arguments."""
        self.parser.add_argument(
            '--domain', required=True,
            help='Custom domain name (e.g., example.com)'
        )
        self.parser.add_argument(
            '--port', type=int, default=5000,
            help='Port to use (default: 5000)'
        )
        self.parser.add_argument(
            '--db-name', default='webcreoling',
            help='Database name (default: webcreoling)'
        )
        self.parser.add_argument(
            '--db-user', default='webcreoling',
            help='Database username (default: webcreoling)'
        )
        self.parser.add_argument(
            '--db-pass', default='',
            help='Database password (default: generated)'
        )
        self.parser.add_argument(
            '--deployment-root', default='/opt/webapp',
            help='Deployment root directory (default: /opt/webapp)'
        )
        self.parser.add_argument(
            '--deployment-type', default='initial',
            choices=['initial', 'update', 'bugfix'],
            help='Type of deployment (default: initial)'
        )
        self.parser.add_argument(
            '--version-file', default='version.json',
            help='Path to version tracking file (default: version.json)'
        )
        self.parser.add_argument(
            '--packages-dir', default='packages',
            help='Directory to store deployment packages (default: packages)'
        )
        self.parser.add_argument(
            '--log-level', default='INFO',
            choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
            help='Logging level (default: INFO)'
        )
        self.parser.add_argument(
            '--skip-validation',
            action='store_true',
            help='Skip server validation (not recommended)'
        )
        self.parser.add_argument(
            '--skip-mysql',
            action='store_true',
            help='Skip MySQL configuration'
        )
        self.parser.add_argument(
            '--skip-nginx',
            action='store_true',
            help='Skip nginx configuration'
        )
        self.parser.add_argument(
            '--skip-service',
            action='store_true',
            help='Skip systemd service setup'
        )
        self.parser.add_argument(
            '--force',
            action='store_true',
            help='Force deployment even if validation fails'
        )
        self.parser.add_argument(
            '--help',
            action='store_true',
            help='Show this help message'
        )

    def parse_args(self, args=None):
        """Parse command line arguments."""
        if not args:
            args = sys.argv[1:]

        # Handle help argument
        if '--help' in args or '-h' in args:
            self.parser.print_help()
            sys.exit(0)

        return self.parser.parse_args(args)
def main():
    """Main entry point for the deployment script."""
    # Initialize argument parser
    arg_parser = ArgumentParser()
    args = arg_parser.parse_args()

    # Initialize and run deployer
    deployer = WebcreolingDeployer()

    # Show help if no arguments provided
    if not args.domain and not any(arg in sys.argv for arg in ['--help', '-h']):
        print("Error: --domain argument is required")
        arg_parser.parser.print_help()
        sys.exit(1)

    # Run deployment
    success = deployer.run(args)

    if success:
        sys.exit(0)
    else:
        sys.exit(1)
if __name__ == '__main__':
    main()
