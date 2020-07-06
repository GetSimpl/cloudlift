FROM buildpack-deps


# update distribution
RUN apt-get update      \
 && apt-get upgrade -y  \
 && rm -rf /var/lib/apt/lists/*

# Debugging utilities
RUN apt-get update            \
 && apt-get install -y socat  \
 && rm -rf /var/lib/apt/lists/*

# Debugging utilities
RUN apt-get update          \
 && apt-get install -y vim  \
 && rm -rf /var/lib/apt/lists/*

EXPOSE 1025/udp
EXPOSE 1026/tcp

COPY entrypoint.sh /usr/local/bin/

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
