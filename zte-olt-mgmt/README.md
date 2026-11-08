# ZTE OLT Management (MVP)

Aplikasi web untuk manajemen & monitoring OLT ZTE C300 (dan OLT lain yang support SNMP).
Stack: FastAPI + SQLAlchemy + APScheduler + Jinja2, deploy via Docker.

## Deploy di Ubuntu / CasaOS

### 1. Salin folder ke server
```
scp -r zte-olt-mgmt user@server:/opt/
```
atau clone jika di git.

### 2. Jalankan dengan Docker Compose
```
cd /opt/zte-olt-mgmt
docker compose up -d --build
```

### 3. Akses
- Web UI: `http://<ip-server>:8099`
- Default: belum ada user login (MVP). Tambahkan OLT di menu "OLTs".

### 4. Tambah OLT
Di halaman OLTs, isi IP OLT, SNMP community, dan (opsional) kredensial SSH.
Pastikan server bisa reach OLT via SNMP (UDP/161) dan SSH (TCP/22).

### Konfigurasi
Env vars di `docker-compose.yml`:
- `DATABASE_URL` (default SQLite di `/data/olt.db`)
- `SECRET_KEY`
- `POLL_INTERVAL` (detik, default 60)

### Catatan penting
- OID SNMP di `app/olt_snmp.py` bersifat generik. Untuk ZTE C300, sesuaikan OID CPU/suhu/memori sesuai firmware Anda (gunakan `snmpwalk` untuk menemukan OID yang tepat).
- Fitur SSH/config belum diimplementasi di MVP ini (hanya SNMP monitoring). Bisa ditambahkan (registrasi ONU via Netmiko) pada tahap berikutnya.
- Untuk CasaOS: gunakan "Custom App" -> import docker-compose, atau jalankan `docker compose` via terminal CasaOS.

### Notifikasi Telegram
1. Buat bot via @BotFather, dapatkan token.
2. Dapatkan chat_id (kirim pesan ke bot, lalu cek `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. Isi di `docker-compose.yml`:
   ```
   - TELEGRAM_BOT_TOKEN=123456:ABC...
   - TELEGRAM_CHAT_ID=987654321
   ```
4. Restart: `docker compose up -d`.
5. Notifikasi dikirim saat: OLT offline, suhu tinggi, dan setelah registrasi ONU (hasil redaman Rx/Tx).

### Keamanan kredensial SSH
- Password SSH dienkripsi (Fernet) dengan `SECRET_KEY` sebelum disimpan di DB.
- Ganti `SECRET_KEY` di `docker-compose.yml` dengan nilai acak (minimal 32 karakter).

### Troubleshooting
- Jika metrik kosong: cek SNMP community & firewall OLT.
- `docker logs zte-olt-mgmt` untuk melihat error polling.
- Test SNMP manual: `snmpwalk -v2c -c public <ip-olt> 1.3.6.1.2.1.1.3.0`
- Test SSH: `curl http://<server>:8099/api/ssh/test/1`