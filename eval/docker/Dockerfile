FROM ros:jazzy-ros-base

# System packages: tc (iproute2), ping, tcpdump
RUN apt-get update && apt-get install -y \
    iproute2 \
    tcpdump \
    iputils-ping \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Python deps for post-processing (also used inside containers for on-the-fly CSV)
RUN pip3 install pyyaml matplotlib numpy --break-system-packages

# Copy entrypoint
COPY docker/entrypoint.sh /
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
