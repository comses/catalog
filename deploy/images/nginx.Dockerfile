FROM nginx:latest

COPY ./deploy/nginx/catalog-haproxy.conf /etc/nginx/nginx.conf
COPY ./deploy/nginx/uwsgi_params /catalog/uwsgi_params