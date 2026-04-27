# AutoBadger

Migrazione Python/Linux dell'applicazione AutoBedge, impacchettata per Docker.

## Avvio Rapido Con Docker

Prima installazione sulla VPS:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker

cd /home/ubuntu
git clone --branch master https://github.com/chrisjusel/autobadger.git autobadger
cd /home/ubuntu/autobadger

sudo docker compose up -d --build
```

Apri:

```text
http://IP_VM/login
```

Credenziali iniziali, se `data/users.json` non esiste:

```text
admin / admin123
```

## Aggiornamento

La pipeline Docker aggiorna il codice da GitHub, preserva `data/` e `.env`, ricostruisce l'immagine e riavvia il container:

```bash
cd /
sudo /home/ubuntu/autobadger/update_autobedge.sh
```

Default della pipeline:

- repo: `https://github.com/chrisjusel/autobadger.git`
- branch: `master`
- directory app: `/home/ubuntu/autobadger`
- backup dati: `/home/ubuntu/autobadger-backups`

## Configurazione

Il container legge `.env` dalla directory del progetto. Se manca, `update_autobedge.sh` lo crea automaticamente.

Esempio `.env` per uso con Nginx/HTTPS:

```env
AUTOBEDGE_SECRET_KEY=metti-una-stringa-lunga-casuale
AUTOBADGER_HTTP_PORT=127.0.0.1:10100
AUTOBEDGE_TIMEZONE=Europe/Rome
AUTOBEDGE_DRY_RUN=0
```

Variabili principali:

- `AUTOBADGER_HTTP_PORT`: bind host del container, consigliato `127.0.0.1:10100` dietro Nginx
- `AUTOBEDGE_SECRET_KEY`: chiave Flask stabile per sessioni e cookie
- `AUTOBEDGE_TIMEZONE`: default `Europe/Rome`
- `AUTOBEDGE_DRY_RUN`: `1` per simulare i badge senza chiamare Corem

## Dati Persistenti

I JSON applicativi sono montati in volume bind:

```text
/home/ubuntu/autobadger/data -> /app/data
```

File usati:

- `users.json`
- `wifi.json`
- `holidays.json`
- `ntfy.json`
- `scheduler.json`

Puoi copiare i file esistenti nella directory:

```bash
mkdir -p /home/ubuntu/autobadger/data
cp users.json holidays.json ntfy.json scheduler.json /home/ubuntu/autobadger/data/
```

## Comandi Utili

```bash
cd /home/ubuntu/autobadger
sudo docker compose ps
sudo docker compose logs -f
sudo docker compose restart
sudo docker compose down
sudo docker compose up -d --build
```

## HTTPS

Per HTTPS puoi mettere Caddy, Nginx o Traefik davanti al container. Con Nginx, il container deve ascoltare solo in locale:

```env
AUTOBADGER_HTTP_PORT=127.0.0.1:10100
```

Poi configura il reverse proxy verso:

```text
http://127.0.0.1:10100
```

La pipeline puo' anche creare/aggiornare il vhost Nginx:

```bash
cd /
sudo NGINX_DOMAIN=badge.scientify.it /home/ubuntu/autobadger/update_autobedge.sh
```

Poi emetti o rinnova il certificato:

```bash
sudo certbot --nginx -d badge.scientify.it
```

## Note

Le funzioni ESP32 WiFi, captive portal e LED sono sostituite da un layer compatibile no-op. Su VPS la rete e' gestita dal sistema operativo o dal provider.
