# Webcreoling Deployment Solution

This is a comprehensive deployment solution for the Webcreoling Flask web application with MySQL database support.

## Overview

The deployment solution consists of:

1. **Deployment Wrapper** (`bin/deployer.py`) - Main orchestrator that manages the complete deployment flow
2. **Bash Deployment Script** (`deployment.sh`) - System-level operations script for Linux distributions
3. **Main Entry Point** (`bin/webcreoling_deployer.py`) - User-friendly command-line interface
4. **Supporting Modules** (`lib/`) - Components for validation, version management, and security
5. **Documentation** (`docs/`) - Comprehensive deployment guides and examples

## Architecture

### Python Wrapper (Orchestrator)

The `deployer.py` script serves as the main orchestrator, responsible for:

- Managing the complete deployment flow
- Handling zip file creation and extraction
- Tracking version incrementing (semver: 1.0.0 → 2.0.0 for updates, 1.0.0 → 1.0.1 for bug fixes)
- Coordinating with the Bash script for system operations
- Comprehensive error handling and logging

### Bash Deployment Script

The `deployment.sh` script handles system-level operations:

- Server validation and prerequisite checking
- Distribution-agnostic package installation
- MySQL database setup and schema initialization
- Firewall and port configuration management
- Application deployment and service configuration
- Installation key generation and secure storage

### Supporting Modules

1. **`deployment_logger.py`** - Structured logging with console and file output
2. **`version_manager.py`** - Semantic version tracking and incrementing
3. **`system_validator.py`** - Server configuration validation
4. **`database_initializer.py`** - Database setup with schema and reference data
5. **`application_deployer.py`** - Application deployment and service management
6. **`security_manager.py`** - Security configurations and hardening

## Deployment Flow

### Phase 1: Preparation

1. **Server Validation**
   - Check Python version and environment
   - Verify disk space and system requirements
   - Validate network configuration
   - Ensure user permissions

2. **Dependency Installation**
   - Install system packages (Python, MySQL, nginx, etc.)
   - Setup Python virtual environment
   - Install Python dependencies from requirements.txt

### Phase 2: Configuration

3. **Database Setup**
   - Create MySQL database and user
   - Initialize database schema
   - Populate reference data
   - Configure MySQL security settings

4. **Network Configuration**
   - Configure domain/IP binding
   - Assign and validate port availability
   - Setup firewall rules
   - Configure host entries

5. **Security Hardening**
   - Generate installation key
   - Configure fail2ban
   - Setup SSH security
   - Configure AppArmor profiles

### Phase 3: Application Deployment

6. **Application Setup**
   - Copy application code to deployment directory
   - Configure application settings
   - Setup web server (nginx)
   - Configure systemd service

7. **Version Management**
   - Track deployment version
   - Increment version based on deployment type
   - Manage changelog entries

### Phase 4: Verification and Packaging

8. **Verification**
   - Verify application functionality
   - Test Python dependencies
   - Check system configuration

9. **Packaging**
   - Create deployment package
   - Include all application files
   - Package for distribution

## Usage Examples

### Initial Deployment

```bash
# Deploy with custom domain and port
sudo ./deployment.sh --domain example.com --port 8080

# Using the Python wrapper
python3 bin/webcreoling_deployer.py --domain example.com --port 8080
```

### Deployment with Custom Database

```bash
python3 bin/webcreoling_deployer.py \
  --domain example.com \
  --db-name mydatabase \
  --db-user dbuser \
  --db-pass dbpassword \
  --deployment-root /var/www/webapp
```

### Update Deployment

```bash
python3 bin/webcreoling_deployer.py \
  --domain example.com \
  --deployment-type update
```

### Bugfix Deployment

```bash
python3 bin/webcreoling_deployer.py \
  --domain example.com \
  --deployment-type bugfix
```

### Skip Validation for Development

```bash
python3 bin/webcreoling_deployer.py \
  --domain example.com \
  --skip-validation \
  --skip-mysql \
  --skip-nginx \
  --skip-service
```

## Directory Structure

```
webcreoling-deployment/
├── bin/                           # Entry point scripts
│   ├── deployer.py               # Main orchestrator
│   └── webcreoling_deployer.py    # User-friendly interface
│
├── deployment.sh                  # Bash deployment script
│
├── lib/                          # Supporting modules
│   ├── deployment_logger.py
│   ├── version_manager.py
│   ├── system_validator.py
│   ├── database_initializer.py
│   ├── application_deployer.py
│   └── security_manager.py
│
├── docs/                          # Documentation
│   ├── DEPLOYMENT.md              # Detailed deployment guide
│   ├── CONFIGURATION.md            # Configuration options
│   └── TROUBLESHOOTING.md         # Troubleshooting guide
│
├── examples/                      # Sample configurations
│   ├── nginx.conf.example
│   └── systemd.service.example
│
├── test/                          # Test suite
│   ├── test_deployment.py
│   └── test_components.py
│
└── README.md                      # This file
```

## Requirements

### System Requirements

- **Operating System**: Any Linux distribution (Ubuntu/Debian, CentOS/RHEL, Fedora, Arch, openSUSE)
- **Architecture**: x86_64 (64-bit)
- **Root Access**: Required for installation and configuration
- **Disk Space**: At least 10GB of free space
- **Network**: Internet connectivity (for package installation)

### Software Dependencies

- **Python 3.11+** or **Python 3.12+**
- **MySQL 8.0+** or **MariaDB 10.5+**
- **nginx** (optional but recommended)
- **firewalld** or **iptables** (optional but recommended)

## Installation

### Quick Start

1. **Make scripts executable**:
   ```bash
   chmod +x deployment.sh bin/deployer.py bin/webcreoling_deployer.py
   ```

2. **Run initial deployment**:
   ```bash
   sudo ./deployment.sh --domain example.com
   ```

3. **Or using the Python wrapper**:
   ```bash
   python3 bin/webcreoling_deployer.py --domain example.com
   ```

### Manual Installation

1. **Clone the deployment solution**:
   ```bash
   git clone https://github.com/infomotin/webcreoling-deployment.git
   cd webcreoling-deployment
   ```

2. **Install required packages**:
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3 python3-pip python3-venv nginx mysql-server
   ```

3. **Run deployment**:
   ```bash
   sudo ./deployment.sh --domain example.com
   ```

## Configuration Options

### Deployment Parameters

| Option | Description | Default | Example |
|--------|-------------|---------|---------|
| `--domain` | Custom domain name | localhost | example.com |
| `--port` | Application port | 5000 | 8080 |
| `--db-name` | Database name | webcreoling | mydatabase |
| `--db-user` | Database username | webcreoling | dbuser |
| `--db-pass` | Database password | generated | dbpass123 |
| `--deployment-root` | Deployment directory | /opt/webapp | /var/www/webapp |

### Deployment Types

- **Initial**: First deployment (version 1.0.0)
- **Update**: Feature deployment (version 2.0.0)
- **Bugfix**: Fix deployment (version 1.0.1)

## Version Management

The deployment solution uses semantic versioning (semver):

- **Initial Release**: `1.0.0`
- **Update (new features)**: `1.0.0` → `2.0.0`
- **Bugfix (bug fixes only)**: `1.0.0` → `1.0.1`

Version information is stored in `version.json` file:

```json
{
  "current_version": "1.0.0",
  "version_code": 10000,
  "created_at": "2026-01-01T12:00:00",
  "last_updated": "2026-01-01T12:00:00",
  "changelog": []
}
```

## Security Features

### Installation Key

Each deployment generates a unique installation key:

- Derived from hostname, timestamp, and random data
- SHA-256 hashed for security
- Stored securely in the deployment directory
- Used for deployment tracking and validation

### Firewall Configuration

The deployment script automatically:

- Opens required ports (HTTP, HTTPS, application port)
- Configures firewall rules
- Sets up SSH security
- Configures fail2ban

### Service Security

- **User**: Runs as root (for system services)
- **File Permissions**: Sensitive files have restricted permissions
- **Configuration**: Minimal security configuration
- **Monitoring**: Logs are collected and monitored

## Troubleshooting

### Common Issues

#### 1. Port Already in Use

If the specified port is in use, the deployment script will automatically:

- Try to find an available alternative port
- Log a warning message
- Continue with the alternative port

#### 2. Missing Dependencies

If required dependencies are missing:

- The deployment script will attempt to install them
- If installation fails, the deployment will be aborted
- Check system logs for detailed error information

#### 3. Permission Issues

If running without root access:

- The deployment will fail
- Use `sudo` to run the deployment script

### Debugging Tips

1. **Check logs**:
   ```bash
   tail -f /var/log/deployment.log
   ```

2. **Manual service start**:
   ```bash
   sudo systemctl start webcreoling.service
   sudo systemctl status webcreoling.service
   ```

3. **Check application**:
   ```bash
   curl http://localhost:5000
   ```

4. **Check firewall**:
   ```bash
   sudo firewall-cmd --list-all-zones
   sudo firewall-cmd --list-ports
   ```

## Support and Updates

### Documentation

- **Main Documentation**: `docs/DEPLOYMENT.md`
- **Configuration Guide**: `docs/CONFIGURATION.md`
- **Troubleshooting Guide**: `docs/TROUBLESHOOTING.md`

### Examples

- **nginx Configuration**: `examples/nginx.conf.example`
- **Systemd Service**: `examples/systemd.service.example`

### Test Suite

The deployment solution includes a comprehensive test suite:

```bash
python3 -m pytest test/ -v
```

## License

This deployment solution is provided under the MIT License. See `LICENSE` file for details.

## Contributing

Contributions to the deployment solution are welcome:

1. Fork the repository
2. Create a feature branch
3. Implement your changes
4. Submit a pull request

## Contact

For questions or support:

- **Documentation**: `docs/DEPLOYMENT.md`
- **Examples**: `examples/` directory
- **Issues**: Report at GitHub repository

---

**Last Updated**: 2026-10-01
**Version**: 1.0.0
**Author**: Deployment Solution Team
