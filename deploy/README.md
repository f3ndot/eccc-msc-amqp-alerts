# Deploying

How to run the webserver on an Ubuntu server behind nginx, with HTTPS from Let's
Encrypt. The app runs as a systemd service listening on `127.0.0.1:5000`, and nginx
serves it, WebSockets included, at your domain.

Run exactly one instance. It holds the only AMQP connection and fans bulletins out to
visitors from memory, so don't add workers or a second copy.

## 1. Install

Python 3.15 isn't packaged for Ubuntu, so uv downloads one. git is needed for the
GTStoWIS2 dependency.

```
sudo apt install git
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh

sudo useradd --system --create-home --home-dir /srv/weather-alerts --shell /usr/sbin/nologin weather-alerts
sudo -u weather-alerts git clone https://github.com/f3ndot/eccc-msc-amqp-alerts.git /srv/weather-alerts/app
cd /srv/weather-alerts/app && sudo -u weather-alerts uv sync --locked --no-dev
```

## 2. Configure

The app reads `config.ini` from the directory it runs in. Keep the server's copy outside
the checkout, so `git pull` doesn't conflict with it:

```
sudo -u weather-alerts cp /srv/weather-alerts/app/config.ini /srv/weather-alerts/config.ini
sudo -u weather-alerts nano /srv/weather-alerts/config.ini
```

- Set `name` to something used nowhere else, eg. `yourname-weather-alerts`. Instances
  with the same name share one queue on ECCC's server and split the messages between
  them, so a copy running on your own machine would take bulletins from the server's.
- Pick `topics` for visitors. Avoid `all`, which floods every visitor.
- Leave `[webserver]` at `127.0.0.1` and `5000`, which `nginx.conf` expects.

## 3. Run the service

```
sudo cp /srv/weather-alerts/app/deploy/weather-alerts.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-alerts
journalctl -u weather-alerts -f
```

If ECCC's server has no room for new queues, the log shows "no room for our queue"
warnings and the app keeps retrying by itself.

## 4. Serve it with nginx

Point your domain's DNS at the server first, and change `server_name` in `nginx.conf`
to it.

```
sudo cp /srv/weather-alerts/app/deploy/nginx.conf /etc/nginx/sites-available/weather-alerts
sudo ln -s /etc/nginx/sites-available/weather-alerts /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d weather-alerts.justinbull.ca
sudo ufw allow 'Nginx Full'
```

The app also needs to reach out on TCP 5671 (AMQPS) to `dd.weather.gc.ca`, and HTTPS to
`hpfx.collab.science.gc.ca` and `dd.weather.gc.ca`. If the log shows connection
timeouts, check your provider doesn't block port 5671.

## Updating

```
cd /srv/weather-alerts/app
sudo -u weather-alerts git pull
sudo -u weather-alerts uv sync --locked --no-dev
sudo systemctl restart weather-alerts
```

Check `deploy/` for changes after pulling, and copy them into place if so. After
changing the service file, run `sudo systemctl daemon-reload` before restarting:
systemd keeps its own copy of the file and otherwise carries on using the old one.
