FROM molior-docker:1.4.0-alpha118-local
RUN apt-get update && apt-get install -y supervisor
RUN sed -i '/::/d' /etc/nginx/sites-enabled/molior-web
RUN sed -i 's/listen 80\([^0-9]\)/listen 8080\1/' /etc/nginx/sites-enabled/aptlyapi
RUN sed -i 's/handlers=\[logging.handlers.SysLogHandler.*/)/' /usr/lib/python3/dist-packages/molior/app.py
COPY supervisord.conf /etc/supervisor/conf.d/molior.conf
COPY start.sh /usr/local/bin/molior-start.sh
CMD /usr/bin/supervisord
