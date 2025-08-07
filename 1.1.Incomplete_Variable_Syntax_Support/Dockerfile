
FROM ubuntu:latest
ENV PATH=${PATH:-/usr/local/bin}
ENV VERSION=${BUILD_VERSION:-1.0.0}
ENV DEBUG=${DEBUG:+debug}
RUN echo "Building version ${VERSION}"
COPY ${SRC:-.} ${DST:-/app}
USER ${USER:-root}
