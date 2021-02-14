#FROM molior-docker:1.4.0-alpha242-local
FROM debian:buster-slim
RUN apt-get update && apt-get install -y supervisor wget gnupg1
RUN wget http://molior.info/archive-keyring.asc -q -O- | apt-key add -
COPY apt.sources /etc/apt/sources.list.d/molior.list
RUN apt-get update && apt-get install -y molior-server molior-web aptly
RUN sed -i '/::/d' /etc/nginx/sites-enabled/molior-web
RUN sed -i 's/listen 80\([^0-9]\)/listen 8080\1/' /etc/nginx/sites-enabled/aptlyapi
RUN sed -i 's/listen 80/listen 3142/' /etc/nginx/sites-enabled/aptly
RUN sed -i 's/handlers=\[logging.handlers.SysLogHandler.*/)/' /usr/lib/python3/dist-packages/molior/app.py
RUN echo "daemon off;" >/etc/nginx/modules-enabled/no-daemon.conf
COPY supervisord.conf /etc/supervisor/conf.d/molior.conf
COPY start.sh /usr/local/bin/molior-start.sh
CMD /usr/bin/supervisord
