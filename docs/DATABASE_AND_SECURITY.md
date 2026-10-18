# Database setup and security

This CRM stores national IDs, family incomes, health situations and donation amounts. A leak would hurt the poorest people the association serves, so treat it as sensitive data, not as an ordinary contact list.

**The location of the database matters less than these four things:**
1. Strong, unshared passwords for each staff member.
2. Backups that are tested and stored somewhere else.
3. An encrypted disk wherever the data lives.
4. Nobody reaching the database except through the app.

---

## 1. Choose a setup

| | **A. Local (office)** | **B. Cloud (recommended for cloud)** | **C. Cloud database + desktop app** |
|---|---|---|---|
| What it is | One office PC runs `HAZ-CRM-Server.exe`. Other PCs open it in a browser. | A small rented server runs the app and PostgreSQL. Staff use a browser over HTTPS. | Each PC runs `HAZ-CRM.exe`, connected directly to a hosted PostgreSQL database. |
| Works from home / branches | ❌ Office network only | ✅ Anywhere | ✅ Anywhere |
| Data leaves Egypt | No | Depends on where the server is (see §6) | Depends on the provider |
| Biggest risk | Theft or failure of that one PC; unencrypted network traffic | Server misconfiguration; a stolen password works from anywhere | The database password sits on every PC and the database is open to the internet |
| Monthly cost | EGP 0 | About USD 5–15 | About USD 0–25 |
| Needs | One PC that stays on | Someone comfortable with a Linux command line once a month | Same as B, plus IT discipline on every PC |
| **Verdict** | ✅ Fine for one office with fewer than about 10 users | ✅ Best choice when people work from more than one place | ⚠️ Supported, but not recommended |

**Recommendation:** start with **A** if everyone works in one office. Move to **B** when people need access from elsewhere. Moving takes one command (§5).

---

## 2. Built-in protections (all setups)

| Protection | Details |
|---|---|
| Passwords | Hashed (never stored in readable form). Minimum 8 characters. |
| Brute-force lockout | 5 wrong passwords lock that account for 15 minutes. |
| Session timeout | Users are logged out after 30 minutes idle (`HAZ_CRM_SESSION_MINUTES` to change). |
| Roles | **Staff** add and edit. Only **Admin** can delete, manage users, download backups and see the audit log. |
| Audit log (سجل العمليات) | Every login, failed login, add, edit (with old and new values), delete and backup is recorded with user, time and IP. |
| Web protections | CSRF tokens on every form; anti-framing and content-security headers; no caching of pages with personal data. |
| Encrypted connections to cloud databases | Any PostgreSQL address that isn't on this machine automatically gets `sslmode=require`. |
| Automatic daily backups | Keeps the last 30, as portable `.db` files that also open in the desktop app. |

**What the app does not protect against** (you must cover these):
- **The local database file is not encrypted by the app.** Anyone who can log in to that Windows PC can copy `crm.db`. Use disk encryption (A1).
- **Server mode in the office uses plain `http`.** Anyone on the same network who captures traffic could read it. Use it only on a trusted office network, never on public Wi-Fi, and never forward the port on the router.
- **Someone with direct database access can bypass the audit log.** This includes anyone with Windows admin rights on the server PC, or anyone holding the PostgreSQL password.
- **There is no two-factor login.**

---

## 3. Setup A — local office server

### A1. Prepare the server PC (once)
1. **Encrypt the disk.**
   - Windows Pro: Settings → Privacy & security → Device encryption, or *Manage BitLocker* → Turn on.
   - Windows Home: only *Device encryption*, if the hardware supports it.
   - Save the recovery key somewhere other than the PC itself.
2. **Give the Windows account a password**, and set the screen to lock after 5 minutes.
3. **Keep Windows Update and Microsoft Defender on.**
4. **Use a dedicated Windows account** for the CRM, not a shared "Office" account.

### A2. Run it
1. Copy `HAZ-CRM-Server.exe` to the server PC, for example `C:\HAZ-CRM\`.
2. Double-click it. A window shows the address, such as `http://192.168.1.20:8080`.
3. When Windows Firewall asks, allow access on **Private networks only**. Leave *Public* unticked.
4. On the other PCs, open that address in Edge or Chrome and bookmark it. The first person creates the admin account.
5. To start it automatically, open Task Scheduler → *Create Basic Task* → *When I log on* → *Start a program* → `C:\HAZ-CRM\HAZ-CRM-Server.exe`.

Data location: `%APPDATA%\HAZ-CRM\` on the server PC (`crm.db`, `secret.key`, `backups\`).

### A3. Backups (do not skip)
Automatic backups go to `%APPDATA%\HAZ-CRM\backups`. **That copy is lost along with the PC if it's stolen or dies.** Keep a second copy elsewhere.

```
HAZ-CRM-Server.exe --backup-dir "E:\HAZ-CRM-Backups"
```

Point `--backup-dir` at one of:
- an encrypted USB drive (BitLocker To Go), or
- a folder synced to the association's OneDrive or Google Drive.

Once a month, take a USB copy off-site.

**Test a restore every 3 months.** On another PC, copy a backup file to `%APPDATA%\HAZ-CRM\crm.db` and open `HAZ-CRM.exe`. If you have never restored a backup, you don't know whether you have one.

---

## 4. Setup B — cloud server (HTTPS + PostgreSQL)

The repository includes `Dockerfile`, `docker-compose.yml`, `Caddyfile` and `.env.example`. Together they run:

```
Internet ──HTTPS──▶ Caddy (free auto-renewing certificate) ──▶ CRM app ──▶ PostgreSQL
                   ports 80/443 only                        private network, never exposed
```

### B1. Get a server and a domain
1. Rent a small Linux VPS: Ubuntu 24.04, 2 GB RAM, from any provider (Azure, AWS Lightsail, DigitalOcean, Hetzner, or an Egyptian host). Choose the region with §6 in mind.
2. Point a domain name at it, for example an `A` record `crm.your-association.org` → the server's IP.
3. Log in with an **SSH key**, not a password.

### B2. Install and start
```bash
# on the server
sudo apt update && sudo apt -y upgrade && sudo apt -y install docker.io docker-compose-v2 git ufw unattended-upgrades
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable

git clone https://github.com/amhayawan/Test-Project.git haz-crm && cd haz-crm
cp .env.example .env
nano .env   # set DOMAIN, and paste two different values from: openssl rand -hex 32
chmod 600 .env

sudo docker compose up -d --build
```
Open `https://crm.your-association.org` and create the admin account straight away. Until you do, anyone who finds the address could create it.

### B3. Backups
- The app writes a daily backup inside the server (`backups` volume, last 30 kept).
- **Copy them off the server**, at least weekly:
  ```bash
  sudo docker compose cp app:/backups ./backups-copy
  ```
  Then download that folder to an encrypted drive. Many VPS providers also sell automatic snapshots (about 20% extra), which are worth turning on.

### B4. Updates
```bash
cd haz-crm && git pull && sudo docker compose up -d --build
```
Ubuntu security updates install themselves (`unattended-upgrades`).

---

## 5. Moving data: local → cloud, or restoring a backup

Any backup file or `crm.db` can be loaded into an **empty** database:

**Into the cloud server (Setup B):**
```bash
# in the haz-crm folder on the server; upload the file first (e.g. with scp) as ./restore/crm.db
mkdir -p restore && sudo chown -R 1000 restore      # the app runs as user 1000 inside the container
sudo docker compose stop app
sudo docker compose run --rm -v "$PWD/restore:/restore" app \
  python haz_crm.py --data /data --database-url sqlite:////restore/crm.db \
  --migrate-to "postgresql://crm:$(grep POSTGRES_PASSWORD .env | cut -d= -f2)@db:5432/crm?sslmode=disable"
sudo docker compose start app
sudo rm -rf restore                                  # don't leave a copy of the data lying around
```
Log in with the user accounts from the restored file.
This only works if nobody has logged in yet. If the database already has data, the copy stops and asks for an empty one.

**Back to local (leaving the cloud):** download a backup from the CRM (Admin → نسخة احتياطية), save it as `%APPDATA%\HAZ-CRM\crm.db` on a PC, and run the exe. You are never locked in.

---

## 6. Setup C — desktop app talking to a hosted PostgreSQL (not recommended)

I recommend against this. Use it only if you cannot run Setup B, because:
- **Every PC holds the database password.** One stolen laptop means the database password has leaked.
- **The database must accept connections from the internet.** Bots scan for exposed PostgreSQL databases all the time.

If you still choose it:
1. Create a PostgreSQL database with any provider (Azure Database for PostgreSQL, AWS RDS, Supabase, Neon…).
2. In the provider's firewall, **allow only your office's fixed IP address**.
3. Create a database user just for the CRM, with a long random password. Don't use the master account.
4. On each PC, create `%APPDATA%\HAZ-CRM\settings.ini`:
   ```ini
   [database]
   url = postgresql://crm_user:LONG-RANDOM-PASSWORD@your-db-host:5432/crm?sslmode=verify-full
   ```
   Use `sslmode=verify-full` if the provider gives you a certificate; otherwise the app enforces `sslmode=require` automatically.
5. Copy your existing data in once with `HAZ-CRM.exe --migrate-to "<that url>"` (§5).

---

## 7. Egyptian data-protection law: check before choosing a cloud region

**Get advice from a lawyer on this.** It is not settled by this guide.

- [Likely] Egypt's **Personal Data Protection Law No. 151 of 2020** treats health, financial and children's data as *sensitive*. A beneficiary file contains all three.
- [Likely] Transferring personal data outside Egypt is restricted. It generally needs a license from the Personal Data Protection Center, and a destination with comparable protection.
- [Guessing] How strictly this is enforced for small NGOs today.

Setup A, or Setup B with a server **located in Egypt**, avoids the cross-border question entirely.

---

## 8. Monthly checklist (5 minutes)

- [ ] Check that a backup from the last 2 days exists outside the server/PC.
- [ ] Skim the audit log for night-time logins, unexpected deletes, or repeated failed logins.
- [ ] Deactivate accounts of staff or volunteers who have left (Admin → المستخدمون).
- [ ] Every 3 months: test-restore a backup on another PC.
