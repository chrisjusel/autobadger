# AutoBedge Python/Linux

Questa cartella contiene la migrazione Python dell'applicazione ESP32 per esecuzione su VM Linux.

## Avvio locale

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo python -m autobedge.app --host 0.0.0.0 --port 80 --data-dir data
```

Apri `http://IP_VM/login`.

Credenziali iniziali, se `data/users.json` non esiste:

```text
admin / admin123
```

## Dati

I file JSON sono salvati in `data/` e mantengono i nomi del firmware:

- `users.json`
- `wifi.json`
- `holidays.json`
- `ntfy.json`
- `scheduler.json`

Puoi copiare questi file dal filesystem LittleFS/backup del firmware nella directory `data/`.

## Variabili ambiente

- `AUTOBEDGE_HOST`: default `0.0.0.0`
- `AUTOBEDGE_PORT`: default `80`
- `AUTOBEDGE_DATA_DIR`: default `data`
- `AUTOBEDGE_TIMEZONE`: default `Europe/Rome`
- `AUTOBEDGE_DRY_RUN`: `1` per simulare i badge senza chiamare Corem
- `AUTOBEDGE_SECRET_KEY`: chiave Flask stabile per mantenere valide le sessioni dopo restart

## Note di migrazione

Su Linux le funzioni ESP32 WiFi, captive portal e LED sono sostituite da un layer compatibile no-op. La rete della VM va configurata con gli strumenti del sistema operativo; la pagina WiFi salva solo metadati compatibili con il vecchio formato.

La porta `80` e' privilegiata su Linux: in avvio manuale serve `sudo`, oppure usa la unit systemd inclusa che concede `CAP_NET_BIND_SERVICE`.
