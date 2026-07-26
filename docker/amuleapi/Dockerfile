FROM debian:bookworm-slim AS builder

ARG AMULE_REF=7958b6926910b1f59b477b146bcf8882139f9558
ARG WX_REF=5ff25322553c1870cf20a2e1ba6f20ed50d9fe9a

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates cmake git libboost-dev libcrypto++-dev \
        libcurl4-openssl-dev libglib2.0-dev libgtk-3-dev libwxgtk3.2-dev \
        pkg-config zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/wxwidgets
RUN git clone https://github.com/wxWidgets/wxWidgets.git source \
    && git -C source checkout --force "$WX_REF" \
    && git -C source submodule update --init --recursive \
    && cd source \
    && ./configure --prefix=/usr/local --with-gtk=3 --with-libcurl --enable-unicode \
        --enable-shared --disable-debug --disable-mediactrl --disable-webview \
        --disable-richtext --disable-aui \
    && make -j"$(nproc)" \
    && make install

WORKDIR /build
RUN git clone https://github.com/amule-org/amule.git source \
    && git -C source checkout "$AMULE_REF" \
    && cmake -S source -B build \
        -DBUILD_MONOLITHIC=NO \
        -DBUILD_DAEMON=YES \
        -DBUILD_AMULEAPI=YES \
        -DBUILD_ED2K=NO \
        -DCRYPTOPP_INCLUDE_PREFIX=crypto++ \
        -DENABLE_NLS=NO \
        -DENABLE_UPNP=NO \
        -DENABLE_IP2COUNTRY=NO \
    && cmake --build build -j"$(nproc)" \
    && cmake --install build

FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash ca-certificates coreutils gosu libcrypto++8 libcurl4 libglib2.0-0 \
        libpcre2-32-0 python3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home --home-dir /var/lib/amule amule

COPY --from=builder /usr/local /usr/local
# Debian's wxWidgets lacks the libcurl backend required by amuleapi; the
# pinned wxWidgets build copied above must win at runtime.
RUN rm -f /lib/*-linux-gnu/libwx*.so* && ldconfig \
    && mkdir -p /data/config /data/incoming /data/temp \
    && chown -R amule:amule /data /var/lib/amule

COPY docker/amuleapi/entrypoint.sh /usr/local/bin/amuleapi-entrypoint
RUN chmod 755 /usr/local/bin/amuleapi-entrypoint

EXPOSE 4713
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=6 \
    CMD bash -c '</dev/tcp/127.0.0.1/4713' || exit 1
ENTRYPOINT ["/usr/local/bin/amuleapi-entrypoint"]
