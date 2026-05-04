FROM ros:jazzy-ros-base

# Only iproute2 is needed (provides tc for network impairment)
RUN apt-get update && apt-get install -y \
    iproute2 \
    ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

# Copy entrypoint
COPY docker/entrypoint.sh /
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
