# Webcreoling Deployment Documentation

This document provides comprehensive guidance for deploying the Webcreoling Flask web application with MySQL database support.

## Introduction

Webcreoling is a sophisticated web application that aggregates and presents news articles from multiple sources. This deployment solution provides a complete, production-ready deployment process that works across various Linux distributions.

## Overview

The deployment solution is organized into three main components:

1. **Main Deployment Wrapper** (`bin/deployer.py`): Orchestrates the complete deployment process
2. **Bash Deployment Script** (`deployment.sh`): Handles system-level operations
3. **Entry Point** (`bin/webcreoling_deployer.py`): User-friendly command-line interface

The deployment process is divided into three phases:
- **Preparation**: Server validation and dependency installation
- **Configuration**: Database setup, network configuration, and security hardening
- **Application Deployment**: Application deployment, service setup, and verification

## Installation

### Prerequisites

- Linux system (Ubuntu/Debian, CentOS/RHEL, Fedora, Arch, openSUSE)
- Root access to the target server
- At least 10GB of free disk space
- Internet connectivity (for package installation)

### Installation Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/infomotin/webcreoling-deployment.git
   cd webcreoling-deployment
   ```

2. **Make scripts executable**:
   ```bash
   chmod +x deployment.sh bin/deployer.py bin/webcreoling_deployer.py
   ```

3. **Run deployment**:
   ```bash
   # Quick start using the Python wrapper
   python3 bin/webcreoling_deployer.py --domain example.com
   ```

## Configuration Options

### Required Parameters

| Parameter | Description | Example | Default |
|-----------|-------------|---------|---------|
| `--domain` | Custom domain name | `example.com` | Required |
| `--port` | Application port | `8080` | `5000` |

### Database Parameters

| Parameter | Description | Example | Default |
|-----------|-------------|---------|---------|
| `--db-name` | Database name | `mydatabase` | `webcreoling` |
| `--db-user` | Database username | `dbuser` | `webcreoling` |
| `--db-pass` | Database password | `dbpass123` | Generated |

### Deployment Control Parameters

| Parameter | Description | Values | Default |
|-----------|-------------|--------|---------|
| `--deployment-type` | Deployment type | `initial`, `update`, `bugfix` | `initial` |
| `--skip-validation` | Skip server validation | `true`, `false` | `false` |
| `--skip-mysql` | Skip MySQL configuration | `true`, `false` | `false` |
| `--skip-nginx` | Skip nginx configuration | `true`, `false` | `false` |
| `--skip-service` | Skip systemd service setup | `true`, `false` | `false` |

### Advanced Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--deployment-root` | Deployment directory path | `/var/www/webapp` |
| `--version-file` | Version tracking file | `version.json` |
| `--packages-dir` | Package storage directory | `packages` |
| `--log-level` | Logging level | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Deployment Process

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

8. **Verification and Packaging**
   - Verify application functionality
   - Test Python dependencies
   - Create deployment package
   - Validate installation

## Usage Examples

### Example 1: Initial Deployment

```bash
# Deploy with custom domain and port
python3 bin/webcreoling_deployer.py --domain example.com --port 8080
```

### Example 2: Deployment with Custom Database

```bash
python3 bin/webcreoling_deployer.py \
  --domain example.com \
  --db-name mydatabase \
  --db-user myuser \
  --db-pass mypass123 \
  --deployment-root /var/www/webapp
```

### Example 3: Update Deployment

```bash
python3 bin/webcreoling_deployer.py \
  --domain example.com \
  --deployment-type update \
  --skip-validation
```

### Example 4: Bugfix Deployment

```bash
python3 bin/webcreoling_deployer.py \
  --domain example.com \
  --deployment-type bugfix \
  --skip-service
```

### Example 5: Development Deployment

```bash
python3 bin/webcreoling_deployer.py \
  --domain localhost \
  --deployment-type initial \
  --skip-validation \
  --skip-mysql \
  --skip-nginx \
  --skip-service
```

## System-Specific Instructions

### Ubuntu/Debian

```bash
# Update package list
sudo apt-get update

# Install dependencies
sudo apt-get install -y python3 python3-pip python3-venv \
  mysql-server mysql-client nginx fail2ban git curl

# Run deployment
python3 bin/webcreoling_deployer.py --domain example.com
```

### CentOS/RHEL/Fedora

```bash
# Install dependencies
sudo yum install -y python3 python3-pip python3-venv \
  mysql-server mysql-devel nginx fail2ban git curl

# Or for Fedora:
sudo dnf install -y python3 python3-pip python3-venv \
  mysql-server mysql-devel nginx fail2ban git curl

# Run deployment
python3 bin/webcreoling_deployer.py --domain example.com
```

### Arch Linux

```bash
# Install dependencies
sudo pacman -S --noconfirm python python-pip python-virtualenv \
  base-devel postgresql-libs openssl libffi mysql nginx \
  fail2ban redis git curl

# Run deployment
python3 bin/webcreoling_deployer.py --domain example.com
```

### openSUSE

```bash
# Install dependencies
sudo zypper install -y python3 python3-pip python3-venv \
  python3-devel gcc gcc-c++ make postgresql-devel openssl-devel \
  libffi-devel mysql-server mysql-devel nginx fail2ban redis \
  git curl

# Run deployment
python3 bin/webcreoling_deployer.py --domain example.com
```

## Configuration File Format

### Deployment Configuration

The deployment configuration is stored in `deployment_config.json`:

```json
{
  "config": {
    "domain": "example.com",
    "port": 5000,
    "deployment_type": "initial",
    "skip_validation": false,
    "skip_mysql": false,
    "skip_nginx": false,
    "skip_service": false,
    "deployment_root": "/opt/webapp",
    "log_level": "INFO"
  },
  "deployment_info": {
    "deployment_id": "deploy_1672534400_abc123",
    "generated_at": "2026-01-01T12:00:00",
    "version": "1.0.0",
    "environment": "production"
  }
}
```

### Version Tracking

Version information is stored in `version.json`:

```json
{
  "current_version": "1.0.0",
  "version_code": 10000,
  "created_at": "2026-01-01T12:00:00",
  "last_updated": "2026-01-01T12:00:00",
  "changelog": []
}
```

### Installation Key

The installation key is stored in `security/installation_key.txt`:

```txt
# Installation Key for Webcreoling
# Generated on: 2026-01-01 12:00:00
# Hostname: server-name
# Deployment ID: 1672534400

INSTALLATION_KEY=5e884898da28047151d0e56f8dc6292773603d0d6aabb8a70b10f7d6d4f3b5f8
```

## Troubleshooting

### Common Issues

#### 1. Port Already in Use

**Problem**: The specified port is already in use by another application.

**Solution**: The deployment script automatically tries to find an alternative port. Check the logs for the alternative port, or specify a different port manually.

#### 2. MySQL Service Not Starting

**Problem**: MySQL fails to start during deployment.

**Solution**:

```bash
# Check MySQL status
sudo systemctl status mysql

# Start MySQL manually
sudo systemctl start mysql

# Check MySQL logs
tail -f /var/log/mysql/error.log
```

#### 3. Nginx Configuration Error

**Problem**: Nginx configuration is invalid.

**Solution**:

```bash
# Test nginx configuration
sudo nginx -t

# Check nginx logs
tail -f /var/log/nginx/error.log
```

#### 4. Python Dependencies Not Installed

**Problem**: Required Python packages are not installed.

**Solution**:

```bash
# Check if virtual environment exists
ls -la /opt/webapp/venv

# Install dependencies manually
source /opt/webapp/venv/bin/activate
pip install -r requirements.txt
```

### Debugging Tips

1. **Check deployment logs**:
   ```bash
   tail -f /opt/webapp/logs/deployment.log
   ```

2. **Manual service management**:
   ```bash
   # Start service
   sudo systemctl start webcreoling.service

   # Check service status
   sudo systemctl status webcreoling.service

   # Stop service
   sudo systemctl stop webcreoling.service

   # Restart service
   sudo systemctl restart webcreoling.service
   ```

3. **Check application logs**:
   ```bash
   # Check webcreoling application logs
   tail -f /opt/webapp/webroot/logs/app.log
   ```

4. **Test application connectivity**:
   ```bash
   # Test if application is running
   curl http://localhost:5000
   ```

5. **Check firewall settings**:
   ```bash
   # List open ports
   sudo firewall-cmd --list-all-zones
   sudo firewall-cmd --list-ports
   ```

### Getting More Help

- **Documentation**: `docs/DEPLOYMENT.md`
- **Examples**: `examples/` directory
- **Issues**: Report at GitHub repository
- **Support**: Check community forums or support channels

## File Structure

### Application Structure

```
webcreoling-deployment/
├── bin/                          # Entry point scripts
│   ├── deployer.py               # Main orchestrator
│   └── webcreoling_deployer.py    # User-friendly interface
│
├── deployment.sh                  # Bash deployment script
│
├── lib/                          # Supporting modules
│   ├── deployment_logger.py       # Logging utilities
│   ├── version_manager.py         # Version tracking
│   ├── system_validator.py        # System validation
│   ├── database_initializer.py    # Database setup
│   ├── application_deployer.py     # Application deployment
│   └── security_manager.py         # Security configuration
│
├── docs/                          # Documentation
│   ├── DEPLOYMENT.md              # Main documentation
│   └── DEPLOYMENT_DEMO.py         # Demonstration script
│
├── examples/                      # Sample configurations
│   ├── nginx.conf.example
│   └── systemd.service.example
│
├── test/                          # Test suite
│   ├── test_deployment.py
│   └── test_components.py
│
└── README.md                      # Quick start guide
```

## Best Practices

### Security Best Practices

1. **Use strong passwords** for database and service accounts
2. **Restrict SSH access** to specific IPs
3. **Keep software updated** with latest security patches
4. **Use firewalls** to restrict network access
5. **Monitor logs** for suspicious activities
6. **Backup regularly** to prevent data loss

### Deployment Best Practices

1. **Test in staging** before production deployment
2. **Document all changes** and configurations
3. **Use version control** for configuration files
4. **Automate testing** to ensure deployment quality
5. **Monitor performance** after deployment
6. **Plan for scaling** future growth needs

### Maintenance Best Practices

1. **Regularly update dependencies**
2. **Monitor system resources**
3. **Backup data regularly**
4. **Review logs for errors**
5. **Test disaster recovery procedures**
6. **Keep documentation up to date**

## Compatibility

### Supported Operating Systems

- **Ubuntu**: 20.04, 22.04, 23.10, 24.04
- **Debian**: 10, 11, 12
- **CentOS**: 7, 8, 9
- **RHEL**: 8, 9
- **Fedora**: 36, 37, 38, 39
- **Arch Linux**: Any recent release
- **openSUSE**: Leap 15, Tumbleweed

### Python Version Compatibility

- **Python 3.11+**: Fully supported
- **Python 3.12+**: Fully supported
- **Python 3.10**: Partially supported (some features may not work)

### Database Compatibility

- **MySQL**: 8.0, 5.7
- **MariaDB**: 10.5, 10.6, 11.0

## License

This deployment solution is provided under the MIT License. See `LICENSE` file for details.

## Copyright

© 2026 Webcreoling Deployment Team
All rights reserved.

---

**Last Updated**: 2026-10-01
**Version**: 1.0.0
**Author**: Deployment Solution Team

For support and questions, please refer to the documentation or contact the development team.