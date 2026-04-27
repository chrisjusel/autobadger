#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/chrisjusel/autobadger.git}"
APP_DIR="${APP_DIR:-/home/ubuntu/autobadger}"
BRANCH="${BRANCH:-master}"
SERVICE_NAME="${SERVICE_NAME:-autobedge}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/ubuntu/autobadger-backups}"
NGINX_DOMAIN="${NGINX_DOMAIN:-}"
CONTAINER_BIND="${CONTAINER_BIND:-127.0.0.1:10100}"

log() {
  printf '[autobadger-deploy] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Comando mancante: %s\n' "$1" >&2
    exit 1
  fi
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    printf 'Docker Compose mancante. Installa docker compose plugin oppure docker-compose.\n' >&2
    exit 1
  fi
}

set_env_value() {
  local key="$1"
  local value="$2"
  local file="${3:-.env}"

  if [[ -f "${file}" ]] && grep -q "^${key}=" "${file}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${file}"
  fi
}

configure_nginx() {
  if [[ -z "${NGINX_DOMAIN}" ]]; then
    return
  fi

  require_cmd nginx

  local site_available="/etc/nginx/sites-available/autobadger"
  local site_enabled="/etc/nginx/sites-enabled/autobadger"

  log "Configuro Nginx per ${NGINX_DOMAIN} -> http://127.0.0.1:10100"

  cat > "${site_available}" <<EOF
server {
    listen 80;
    server_name ${NGINX_DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:10100;
        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

  ln -sfn "${site_available}" "${site_enabled}"

  # Disable the previous pre-Docker vhost if it exists with the same server_name.
  if [[ -L "/etc/nginx/sites-enabled/autobedge" ]] && grep -q "server_name ${NGINX_DOMAIN}" "/etc/nginx/sites-enabled/autobedge"; then
    rm -f "/etc/nginx/sites-enabled/autobedge"
  fi

  nginx -t
  systemctl enable nginx >/dev/null 2>&1 || true
  if systemctl is-active --quiet nginx; then
    systemctl reload nginx
  else
    systemctl start nginx
  fi
}

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Esegui lo script con sudo.\n' >&2
  exit 1
fi

require_cmd git
require_cmd docker

# Avoid running from a directory that may be replaced during deploy.
cd /

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="${BACKUP_ROOT}/${timestamp}"
tmp_clone="$(mktemp -d)"

cleanup() {
  rm -rf "${tmp_clone}"
}
trap cleanup EXIT

log "Repo: ${REPO_URL}"
log "Directory applicazione: ${APP_DIR}"
log "Branch: ${BRANCH}"
if [[ -n "${NGINX_DOMAIN}" ]]; then
  log "Dominio Nginx: ${NGINX_DOMAIN}"
fi

mkdir -p "${BACKUP_ROOT}"

if systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1; then
  log "Disabilito vecchio servizio systemd ${SERVICE_NAME} per evitare conflitti"
  systemctl disable --now "${SERVICE_NAME}" || true
fi

if [[ -d "${APP_DIR}" ]]; then
  log "Backup dati runtime in ${backup_dir}"
  mkdir -p "${backup_dir}"
  [[ -d "${APP_DIR}/data" ]] && cp -a "${APP_DIR}/data" "${backup_dir}/data"
  [[ -f "${APP_DIR}/.env" ]] && cp -a "${APP_DIR}/.env" "${backup_dir}/.env"
fi

if [[ -d "${APP_DIR}/.git" ]]; then
  log "Aggiornamento repository esistente"
  git -C "${APP_DIR}" fetch origin "${BRANCH}"
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
else
  log "Directory non git: clone pulito e sostituzione codice"
  git clone --branch "${BRANCH}" --single-branch "${REPO_URL}" "${tmp_clone}/repo"
  if [[ -d "${APP_DIR}" ]]; then
    mkdir -p "${backup_dir}"
    cp -a "${APP_DIR}" "${backup_dir}/previous-tree"
    rm -rf "${APP_DIR}"
  fi
  mv "${tmp_clone}/repo" "${APP_DIR}"
fi

log "Ripristino dati runtime preservati"
if [[ -d "${backup_dir}/data" ]]; then
  rm -rf "${APP_DIR}/data"
  cp -a "${backup_dir}/data" "${APP_DIR}/data"
else
  mkdir -p "${APP_DIR}/data"
fi

if [[ -f "${backup_dir}/.env" ]]; then
  cp -a "${backup_dir}/.env" "${APP_DIR}/.env"
fi

cd "${APP_DIR}"

if [[ ! -f ".env" ]]; then
  log "Creo .env con secret key e bind container locale"
  secret_key="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  {
    printf 'AUTOBEDGE_SECRET_KEY=%s\n' "${secret_key}"
    printf 'AUTOBADGER_HTTP_PORT=%s\n' "${CONTAINER_BIND}"
    printf 'AUTOBEDGE_TIMEZONE=Europe/Rome\n'
    printf 'AUTOBEDGE_DRY_RUN=0\n'
  } > .env
else
  log "Aggiorno .env per esporre Docker solo in locale"
  set_env_value "AUTOBADGER_HTTP_PORT" "${CONTAINER_BIND}" ".env"
fi

log "Build e avvio container Docker"
compose down --remove-orphans || true
docker rm -f autobadger >/dev/null 2>&1 || true
compose up -d --build --force-recreate

log "Stato container"
compose ps

configure_nginx

log "Deploy completato"
