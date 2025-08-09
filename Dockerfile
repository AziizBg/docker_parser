FROM node:18 AS builder
ARG NODE_ENV
ARG BUILD_DATE
WORKDIR /app
COPY package.json package-lock.json /app/
# Mixed separators and grouping
RUN npm ci && npm run build || (echo "build failed" && exit 1)
COPY scripts/init.sh /usr/local/bin/init.sh
COPY scripts/run.py /usr/local/bin/run.py
RUN chmod +x /usr/local/bin/init.sh && /usr/local/bin/init.sh arg1 & echo background
ENV PATH=${PATH}:/app/node_modules/.bin     DEBUG=${DEBUG:-false}     PREFIX=${PREFIX:+/opt}     NESTED=${OUTER:-${INNER:-fallback}}
EXPOSE 3000/tcp 9229
RUN ["bash", "-lc", "echo json form"]

FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
USER 1001:1001
RUN echo "starting"; for i in 1 2 3; do echo $i; done; if [ -f /etc/alpine-release ]; then echo alpine; fi
EXPOSE 80
ARG CHANNEL=stable
ENV VERSION=${VERSION:-1.0.0}
WORKDIR /srv
COPY configs/nginx.conf /etc/nginx/nginx.conf
COPY src/{a,b}.txt /data/
ADD assets/data.bin /opt/data.bin
RUN python /usr/local/bin/run.py | tee /tmp/out.txt
CMD ["nginx", "-g", "daemon off;"]
