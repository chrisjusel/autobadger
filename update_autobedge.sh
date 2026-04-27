#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/chrisjusel/autobadger.git}"
APP_DIR="${APP_DIR:-/opt/autobedge}"
BRANCH="${BRANCH:-master}"
SERVICE_NAME="${SERVICE_NAME:-autobedge}"
BACKUP_ROOT="${BACKUP_ROOT:-/opt/autobedge-backups}"

log() {
  printf '[autobedge-update] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Comando mancante: %s\n' "$1" >&2
    exit 1
  fi
}

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Esegui lo script con sudo.\n' >&2
  exit 1
fi

require_cmd git
require_cmd python3

# Avoid running pip from a deleted cwd if APP_DIR is replaced while this script is running.
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

mkdir -p "${BACKUP_ROOT}"

if systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1; then
  log "Stop servizio ${SERVICE_NAME}"
  systemctl stop "${SERVICE_NAME}" || true
fi

if [[ -d "${APP_DIR}" ]]; then
  log "Backup configurazione runtime in ${backup_dir}"
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

log "Ricreazione virtualenv"
rm -rf "${APP_DIR}/.venv"
python3 -m venv "${APP_DIR}/.venv"

log "Installazione dipendenze"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"

log "Verifica sintassi Python"
"${APP_DIR}/.venv/bin/python" -m compileall "${APP_DIR}/autobedge"

if systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1; then
  log "Reload systemd e restart servizio ${SERVICE_NAME}"
  systemctl daemon-reload
  systemctl restart "${SERVICE_NAME}"
  systemctl --no-pager --full status "${SERVICE_NAME}" || true
else
  log "Servizio ${SERVICE_NAME}.service non trovato: salto restart systemd"
fi

log "Aggiornamento completato"
