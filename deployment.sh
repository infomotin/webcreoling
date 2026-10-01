#!/usr/bin/bash
# Deployment Script - System-level deployment operations

# Usage: ./deployment.sh [OPTIONS]
# This script handles system-level operations for Flask application deployment.
# It is distribution-agnostic and works across different Linux distributions.

# Exit immediately if a command exits with a non-zero status.
set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Detect Linux distribution
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION=$VERSION_ID
    else
        OS="unknown"
        VERSION="unknown"
    fi

    case $OS in
        ubuntu|debian)
            DISTRO="debian"
            PKG_MGR="apt-get"
            PKG_INSTALL="apt-get install -y"
            ;;
        centos|rhel|rocky|almalinux)
            DISTRO="rhel"
            PKG_MGR="yum"
            PKG_INSTALL="yum install -y"
            ;;
        fedora)
            DISTRO="fedora"
            PKG_MGR="dnf"
            PKG_INSTALL="dnf install -y"
            ;;
        arch)
            DISTRO="arch"
            PKG_MGR="pacman"
            PKG_INSTALL="pacman -S --noconfirm"
            ;;
        opensuse*|sles*)
            DISTRO="suse"
            PKG_MGR="zypper"
            PKG_INSTALL="zypper install -y"
            ;;
        *)
            DISTRO="unknown"
            PKG_MGR=""
            PKG_INSTALL=""
            ;;
    esac

    echo "$DISTRO"
}

# Check if running as root
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
       log_error "This script must be run as root"
       echo "Please run with: sudo $0"
       exit 1
    fi
}

# Update package list
update_packages() {
    log_info "Updating package list..."
    case $DISTRO in
        debian)
            $PKG_MGR update -qq
            ;;
        rhel|fedora)
            $PKG_MGR makecache -q
            ;;
        arch)
            $PKG_MGR -Sy --noconfirm
            ;;
        suse)
            $PKG_MGR refresh -q
            ;;
        *)
            log_error "Unsupported distribution: $DISTRO"
            exit 1
            ;;
    esac
    log_success "Package list updated"
}

# Install system dependencies
install_system_deps() {
    log_info "Installing system dependencies..."

    case $DISTRO in
        debian)
            $PKG_INSTALL \
                python3 python3-pip python3-venv python3-dev \
                build-essential libpq-dev libssl-dev libffi-dev \
                python3-dev mysql-server mysql-client nginx \
                fail2ban redis-server git curl wget net-tools \
                htop iotop tree
            ;;
        rhel)
            $PKG_INSTALL \
                python3 python3-pip python3-venv python3-devel \
                gcc gcc-c++ make libpq-devel openssl-devel libffi-devel \
                mysql-server mysql-devel nginx fail2ban redis \
                git curl wget net-tools htop iotop tree
            ;;
        fedora)
            $PKG_INSTALL \
                python3 python3-pip python3-venv python3-devel \
                gcc gcc-c++ make libpq-devel openssl-devel libffi-devel \
                mysql-server mysql-devel nginx fail2ban redis \
                git curl wget net-tools htop iotop tree
            ;;
        arch)
            $PKG_INSTALL \
                python python-pip python-virtualenv base-devel \
                postgresql-libs openssl libffi mysql nginx \
                fail2ban redis git curl wget htop iotop tree
            ;;
        suse)
            $PKG_INSTALL \
                python3 python3-pip python3-venv python3-devel \
                gcc gcc-c++ make postgresql-devel openssl-devel libffi-devel \
                mysql-server mysql-devel nginx fail2ban redis \
                git curl wget net-tools htop iotop tree
            ;;
        *)
            log_error "Unsupported distribution: $DISTRO"
            exit 1
            ;;
    esac

    log_success "System dependencies installed"
}

# Install Python dependencies
install_python_deps() {
    log_info "Installing Python dependencies..."

    DEPLOYMENT_ROOT=${1:-/opt/webapp}
    PYTHON_VENV=$DEPLOYMENT_ROOT/venv

    if [ ! -d "$PYTHON_VENV" ]; then
        log_info "Creating Python virtual environment..."
        python3 -m venv "$PYTHON_VENV"
    fi

    # Get the correct pip path based on OS
    if [ "$DISTRO" = "arch" ]; then
        PIP_PATH="$PYTHON_VENV/bin/pip"
    else
        PIP_PATH="$PYTHON_VENV/Scripts/pip.exe"
    fi

    # Upgrade pip
    log_info "Upgrading pip..."
    $PIP_PATH install --upgrade pip

    # Install requirements
    REQUIREMENTS_FILE="$DEPLOYMENT_ROOT/requirements.txt"
    if [ -f "$REQUIREMENTS_FILE" ]; then
        log_info "Installing Python dependencies from requirements.txt..."
        $PIP_PATH install -r "$REQUIREMENTS_FILE"
    else
        log_error "requirements.txt not found at $REQUIREMENTS_FILE"
        exit 1
    fi

    log_success "Python dependencies installed"
}

# Configure MySQL
configure_mysql() {
    log_info "Configuring MySQL..."

    # Start and enable MySQL service
    if command -v systemctl >/dev/null 2>&1; then
        systemctl enable mysql
        systemctl start mysql
    else
        service mysql start
    fi

    # Create database and user if they don't exist
    DB_NAME=${1:-webcreoling}
    DB_USER=${2:-webcreoling}
    DB_PASS=${3:-${DB_USER}pass123}

    mysql -e "CREATE DATABASE IF NOT EXISTS $DB_NAME;"
    mysql -e "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';"
    mysql -e "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
    mysql -e "FLUSH PRIVILEGES;"

    # Configure MySQL security
    MYSQL_CONF=/etc/mysql/mysql.conf.d/mysqld.cnf
    if [ -f "$MYSQL_CONF" ]; then
        # Backup original config
        cp "$MYSQL_CONF" "$MYSQL_CONF.backup"

        # Add security settings
        cat >> "$MYSQL_CONF" <<EOF

# Security settings for webcreoling
mysqld:
    user = mysql
    bind-address = 127.0.0.1
    skip-external-logging
    log-error = /var/log/mysql/error.log
EOF

        # Restart MySQL to apply changes
        if command -v systemctl >/dev/null 2>&1; then
            systemctl restart mysql
        else
            service mysql restart
        fi
    fi

    log_success "MySQL configured"
}

# Configure firewall
configure_firewall() {
    log_info "Configuring firewall..."

    if ! command -v firewall-cmd >/dev/null 2>&1 && ! command -v iptables >/dev/null 2>&1; then
        log_warn "Firewall not available, skipping firewall configuration"
        return 0
    fi

    # Get port from argument or use default
    PORT=${1:-5000}

    # Open required ports
    if command -v firewall-cmd >/dev/null 2>&1; then
        # Using firewalld
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --permanent --add-port=$PORT/tcp
        firewall-cmd --permanent --zone=public --add-service=ssh
        firewall-cmd --reload
    elif command -v iptables >/dev/null 2>&1; then
        # Using iptables
        iptables -I INPUT -p tcp --dport 22 -j ACCEPT
        iptables -I INPUT -p tcp --dport $PORT -j ACCEPT
        iptables -I INPUT -p tcp --dport 80 -j ACCEPT
        iptables -I INPUT -p tcp --dport 443 -j ACCEPT
    fi

    log_success "Firewall configured"
}

# Configure nginx
configure_nginx() {
    log_info "Configuring nginx..."

    DOMAIN=${1:-localhost}
    PORT=${2:-5000}

    # Install nginx if not present
    if ! command -v nginx >/dev/null 2>&1; then
        log_info "Installing nginx..."
        $PKG_INSTALL nginx
    fi

    # Create nginx configuration
    NGINX_CONF=/etc/nginx/sites-available/webcreoling
    cat > $NGINX_CONF <<EOF
server {
    listen $PORT;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 300s;
    }

    location /static/ {
        alias /opt/webapp/static/;
        expires 1y;
        access_log off;
    }

    error_page 500 502 503 504 /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}
EOF

    # Enable the site
    ln -sf $NGINX_CONF /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default

    # Test and reload nginx
    nginx -t
    if command -v systemctl >/dev/null 2>&1; then
        systemctl restart nginx
    else
        service nginx restart
    fi

    log_success "nginx configured"
}

# Setup systemd service
setup_service() {
    log_info "Setting up systemd service..."

    DEPLOYMENT_ROOT=${1:-/opt/webapp}
    PYTHON_VENV=$DEPLOYMENT_ROOT/venv

    # Get the correct python and gunicorn paths
    if [ "$DISTRO" = "arch" ]; then
        PYTHON_PATH="$PYTHON_VENV/bin/python3"
        GUNICORN_PATH="$PYTHON_VENV/bin/gunicorn"
    else
        PYTHON_PATH="$PYTHON_VENV/Scripts/python.exe"
        GUNICORN_PATH="$PYTHON_VENV/Scripts/gunicorn.exe"
    fi

    cat > /etc/systemd/system/webcreoling.service <<EOF
[Unit]
Description=Webcreoling Flask Application
After=network.target mysql.service

[Service]
Type=simple
User=root
WorkingDirectory=$DEPLOYMENT_ROOT/webroot
Environment=PATH=$PYTHON_VENV/bin
ExecStart=$GUNICORN_PATH --workers 3 --bind 0.0.0.0:5000 --chdir=$DEPLOYMENT_ROOT/webroot webcreoling.app:app
Restart=always
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=webcreoling

[Install]
WantedBy=multi-user.target
EOF

    # Enable and start the service
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
        systemctl enable webcreoling.service
        systemctl start webcreoling.service
    else
        # Fallback for systems without systemd
        log_warn "Systemd not available, please manually install the service"
    fi

    log_success "Systemd service configured"
}

# Setup fail2ban
configure_fail2ban() {
    log_info "Configuring fail2ban..."

    # Install fail2ban if not present
    if ! command -v fail2ban-server >/dev/null 2>&1; then
        log_info "Installing fail2ban..."
        $PKG_INSTALL fail2ban
    fi

    # Create fail2ban configuration
    cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
enabled = true
bantime = 600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
logpath = /var/log/auth.log
maxretry = 3
bantime = 1800

[webcreoling]
enabled = true
port = http,https
logpath = /opt/webapp/webroot/logs/access.log
maxretry = 10
bantime = 3600
EOF

    # Restart fail2ban
    if command -v systemctl >/dev/null 2>&1; then
        systemctl restart fail2ban
    else
        service fail2ban restart
    fi

    log_success "fail2ban configured"
}

# Generate installation key
generate_installation_key() {
    log_info "Generating installation key..."

    DEPLOYMENT_ROOT=${1:-/opt/webapp}
    SECURITY_DIR=$DEPLOYMENT_ROOT/security
    mkdir -p "$SECURITY_DIR"

    HOSTNAME=$(hostname)
    TIMESTAMP=$(date +%s)
    RANDOM_DATA=$(head -c 16 /dev/urandom | xxd -p | tr -d '\n')

    KEY_DATA="$HOSTNAME:$TIMESTAMP:$RANDOM_DATA"
    INSTALLATION_KEY=$(echo -n "$KEY_DATA" | sha256sum | cut -d ' ' -f 1)

    cat > "$SECURITY_DIR/installation_key.txt" <<EOF
# Installation Key for Webcreoling
# Generated on: $(date)
# Hostname: $HOSTNAME
# Deployment ID: $TIMESTAMP

INSTALLATION_KEY=$INSTALLATION_KEY
EOF

    chmod 600 "$SECURITY_DIR/installation_key.txt"

    log_success "Installation key generated: $INSTALLATION_KEY"
    log_info "Key stored at: $SECURITY_DIR/installation_key.txt"

    # Output the installation key
    echo ""
    echo "=== INSTALLATION KEY ==="
    echo "$INSTALLATION_KEY"
    echo "======================="
}

# Verify deployment
verify_deployment() {
    log_info "Verifying deployment..."

    DEPLOYMENT_ROOT=${1:-/opt/webapp}

    # Check if virtual environment exists
    if [ ! -d "$DEPLOYMENT_ROOT/venv" ]; then
        log_error "Virtual environment not found at $DEPLOYMENT_ROOT/venv"
        return 1
    fi

    # Check if application files exist
    APP_FILE="$DEPLOYMENT_ROOT/webroot/webcreoling"
    if [ ! -f "$APP_FILE" ]; then
        log_error "Application file not found at $APP_FILE"
        return 1
    fi

    # Check if requirements.txt exists
    if [ ! -f "$DEPLOYMENT_ROOT/requirements.txt" ]; then
        log_error "requirements.txt not found"
        return 1
    fi

    # Try to run a simple Python command
    if [ "$DISTRO" = "arch" ]; then
        PYTHON_PATH="$DEPLOYMENT_ROOT/venv/bin/python3"
    else
        PYTHON_PATH="$DEPLOYMENT_ROOT/venv/Scripts/python.exe"
    fi

    $PYTHON_PATH -c "import flask; import sqlalchemy; import pymysql; print('Python dependencies OK')"
    if [ $? -ne 0 ]; then
        log_error "Python dependencies not installed correctly"
        return 1
    fi

    log_success "Deployment verification completed"
    return 0
}

# Show usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --domain DOMAIN          Custom domain name (e.g., example.com)"
    echo "  --port PORT              Port to use (default: 5000)"
    echo "  --db-name NAME           Database name (default: webcreoling)"
    echo "  --db-user USER           Database username (default: webcreoling)"
    echo "  --db-pass PASS           Database password (default: generated)"
    echo "  --deployment-root DIR    Deployment root directory (default: /opt/webapp)"
    echo "  --skip-validation        Skip server validation"
    echo "  --skip-mysql            Skip MySQL configuration"
    echo "  --skip-nginx            Skip nginx configuration"
    echo "  --skip-service          Skip systemd service setup"
    echo "  --help                   Show this help message"
    echo ""
    echo "Example:"
    echo "  sudo $0 --domain example.com --port 8080 --deployment-root /var/www/webapp"
    echo ""
}

# Main function
main() {
    # Parse command line arguments
    while [ $# -gt 0 ]; do
        case $1 in
            --domain)
                DOMAIN=$2
                shift 2
                ;;
            --port)
                PORT=$2
                shift 2
                ;;
            --db-name)
                DB_NAME=$2
                shift 2
                ;;
            --db-user)
                DB_USER=$2
                shift 2
                ;;
            --db-pass)
                DB_PASS=$2
                shift 2
                ;;
            --deployment-root)
                DEPLOYMENT_ROOT=$2
                shift 2
                ;;
            --skip-validation)
                SKIP_VALIDATION=true
                shift
                ;;
            --skip-mysql)
                SKIP_MYSQL=true
                shift
                ;;
            --skip-nginx)
                SKIP_NGINX=true
                shift
                ;;
            --skip-service)
                SKIP_SERVICE=true
                shift
                ;;
            --help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done

    # Set defaults
    DISTRO=$(detect_distro)
    DOMAIN=${DOMAIN:-localhost}
    PORT=${PORT:-5000}
    DB_NAME=${DB_NAME:-webcreoling}
    DB_USER=${DB_USER:-webcreoling}
    DB_PASS=${DB_PASS:-${DB_USER}pass123}
    DEPLOYMENT_ROOT=${DEPLOYMENT_ROOT:-/opt/webapp}
    SKIP_VALIDATION=false
    SKIP_MYSQL=false
    SKIP_NGINX=false
    SKIP_SERVICE=false

    # Check if running as root
    check_root

    # Update package list
    update_packages

    # Install system dependencies
    install_system_deps

    # Install Python dependencies
    install_python_deps "$DEPLOYMENT_ROOT"

    # Configure MySQL
    if [ "$SKIP_MYSQL" = false ]; then
        configure_mysql "$DB_NAME" "$DB_USER" "$DB_PASS"
    fi

    # Configure firewall
    configure_firewall "$PORT"

    # Configure nginx
    if [ "$SKIP_NGINX" = false ]; then
        configure_nginx "$DOMAIN" "$PORT"
    fi

    # Setup systemd service
    if [ "$SKIP_SERVICE" = false ]; then
        setup_service "$DEPLOYMENT_ROOT"
    fi

    # Configure fail2ban
    configure_fail2ban

    # Generate installation key
    generate_installation_key "$DEPLOYMENT_ROOT"

    # Verify deployment
    verify_deployment "$DEPLOYMENT_ROOT"

    log_success "Deployment completed successfully"
}

# Run main function
main "$@"
