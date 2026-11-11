# Arena — Telegram Mini App (VPS ga o'rnatish)

## 1. Bot tokenini yangilang
@BotFather → `/mybots` → botingiz → API Token → **Revoke**. Yangi tokenni `.env` ga yozing. `.env` GitHub'ga **chiqmaydi** (`.gitignore` da).

## 2. VPS (Ubuntu 22/24) — oddiy usul
```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx git
sudo useradd -m -s /bin/bash arena
sudo git clone https://github.com/SIZNING/REPO.git /opt/arena && sudo chown -R arena: /opt/arena
cd /opt/arena && sudo -u arena python3 -m venv venv && sudo -u arena venv/bin/pip install -r requirements.txt
sudo -u arena cp .env.example .env && sudo -u arena nano .env     # BOT_TOKEN, WEBAPP_URL, ADMIN_PASSWORD
sudo cp deploy/arena.service /etc/systemd/system/ && sudo systemctl enable --now arena
sudo cp deploy/nginx.conf /etc/nginx/sites-available/arena && sudo ln -s /etc/nginx/sites-available/arena /etc/nginx/sites-enabled/
# nginx.conf ichida domenni almashtiring, keyin:
sudo nginx -t && sudo systemctl reload nginx && sudo certbot --nginx -d sizning-domen.uz
```
Domenning A-yozuvi VPS IP'siga qaragan bo'lishi kerak. Telegram faqat **https** ochadi.
Yangilash: `cd /opt/arena && sudo -u arena git pull && sudo systemctl restart arena`
Loglar: `journalctl -u arena -f`

### Docker bilan
```bash
cp .env.example .env && nano .env && docker compose up -d --build
```
(nginx + certbot yuqoridagidek; baza `./data/arena.db` da saqlanadi.)

## 3. Botni Mini App ga ulash
Server ishga tushganda menyu tugmasi o'zi o'rnatiladi (`WEBAPP_URL` to'g'ri bo'lsa). Qo'shimcha: @BotFather → `/newapp` — to'g'ridan-to'g'ri havola uchun.

## 4. Admin panel
`https://sizning-domen.uz/admin` — parol: `.env` dagi `ADMIN_PASSWORD`.
- **Boshqaruv**: onlayn, faol stollar, yangi/faol foydalanuvchilar, komissiya daromadi, depozitlar, 7 kunlik grafik
- **Foydalanuvchilar**: qidiruv, balansni qo'shish/ayirish, ban/unban, ismni o'zgartirish, chiqarib yuborish
- **O'yinlar**: jonli stollar va tarix · **Tranzaksiyalar**: depozit, komissiya, admin o'zgarishlari
- **Sozlamalar**: komissiya %, test rejimi, texnik ishlar, banner e'lon · **Xabar**: ilovadagilarga yoki Telegram orqali hammaga
Admin paneldagi sozlamalar bazada saqlanadi, qayta ishga tushirganda yo'qolmaydi. Parol 5 marta xato kiritilsa IP 5 daqiqaga bloklanadi.

## 5. To'lovlar
- Stars: `TEST_MODE=0` (yoki admin paneldan test rejimini o'chiring).
- TON: `.env` ga `TON_ADDRESS` (+ ixtiyoriy `TONCENTER_KEY`). Depozit izohi `dep:<uid>` — dastur o'zi ko'rsatadi.
- Haqiqiy pulga chiqishdan oldin test rejimi **o'chiq** ekaniga ishonch hosil qiling.

## 6. Zaxira
`arena.db` — butun baza. Kunlik nusxa: `crontab -e` → `0 4 * * * cp /opt/arena/arena.db /opt/arena/arena.$(date +\%a).db`
