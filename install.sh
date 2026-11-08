#!/usr/bin/env bash
set -euo pipefail

if [[ $(id -u) -ne 0 ]]; then
    echo "Run: sudo bash install.sh [mysql-user] [mysql-host]" >&2
    exit 1
fi

counter_mysql_user="${1:-pythonapp}"
counter_mysql_host="${2:-127.0.0.1}"
if [[ ! "$counter_mysql_user" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "This installer accepts a MySQL user name containing letters, digits and underscores." >&2
    exit 1
fi
if [[ "$counter_mysql_host" != "127.0.0.1" && "$counter_mysql_host" != "localhost" ]]; then
    echo "MySQL host must be 127.0.0.1 or localhost." >&2
    exit 1
fi

counter_source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for counter_tool in mysql python3 systemctl nginx; do
    command -v "$counter_tool" >/dev/null
done
id pythonapp >/dev/null
test -x /opt/pythonapp/.venv/bin/python
test -f /etc/pythonapp.env
test -f /etc/systemd/system/pythonapp.service
/opt/pythonapp/.venv/bin/python -c 'import flask, pymysql'

counter_account_count="$(mysql --batch --skip-column-names --execute \
    "SELECT COUNT(*) FROM mysql.user WHERE User='$counter_mysql_user' AND Host='$counter_mysql_host'")"
if [[ "$counter_account_count" != "1" ]]; then
    echo "MySQL account '$counter_mysql_user'@'$counter_mysql_host' was not found." >&2
    echo "Check accounts: sudo mysql -e \"SELECT User,Host FROM mysql.user WHERE User IN ('python','pythonapp');\"" >&2
    echo "Run this installer again with the correct user and Host values." >&2
    exit 1
fi
mysql --database=pythonapp --execute 'SELECT 1' >/dev/null
nginx -t

install -d -m 700 /var/backups/pythonapp
counter_backup_dir="$(mktemp -d /var/backups/pythonapp/backup.XXXXXX)"
for counter_relative_file in app.py templates/index.html static/style.css persistence_test.py; do
    if [[ -f "/opt/pythonapp/$counter_relative_file" ]]; then
        install -d -m 700 "$counter_backup_dir/$(dirname -- "$counter_relative_file")"
        cp -p -- "/opt/pythonapp/$counter_relative_file" "$counter_backup_dir/$counter_relative_file"
    fi
done
cp -p -- /etc/pythonapp.env "$counter_backup_dir/pythonapp.env"

mysql --database=pythonapp < "$counter_source_dir/schema.sql"
mysql --database=pythonapp --execute \
    "GRANT SELECT, UPDATE ON pythonapp.page_counter TO '$counter_mysql_user'@'$counter_mysql_host'"

install -d -m 755 /opt/pythonapp/templates /opt/pythonapp/static
install -m 644 "$counter_source_dir/app.py" /opt/pythonapp/app.py
install -m 644 "$counter_source_dir/templates/index.html" /opt/pythonapp/templates/index.html
install -m 644 "$counter_source_dir/static/style.css" /opt/pythonapp/static/style.css
install -m 644 "$counter_source_dir/static/tausta.svg" /opt/pythonapp/static/tausta.svg
install -m 644 "$counter_source_dir/persistence_test.py" /opt/pythonapp/persistence_test.py
install -d -o pythonapp -g pythonapp -m 700 /opt/pythonapp/.gunicorn

# Preserve the existing password and other settings; select the actual MySQL
# account explicitly so renaming python -> pythonapp is not required.
python3 - "$counter_mysql_user" <<'PY'
import os
from pathlib import Path
import re
import sys

path = Path("/etc/pythonapp.env")
lines = [line for line in path.read_text().splitlines()
         if not re.match(r"\s*DB_USER\s*=", line)]
lines.append("DB_USER=" + sys.argv[1])
path.write_text("\n".join(lines) + "\n")
os.chown(path, 0, 0)
os.chmod(path, 0o600)
PY

systemctl enable --now mysql nginx
systemctl enable pythonapp
systemctl restart pythonapp
systemctl is-active --quiet pythonapp
echo "Installed. Open http://YOUR_SERVER_IP/viikko2/ and reload the page."
echo "Previous application files are backed up in: $counter_backup_dir"
echo "The first page request will verify the application's MySQL password."
echo "If it fails: sudo journalctl -u pythonapp -n 40 --no-pager"
