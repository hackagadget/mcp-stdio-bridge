# SPDX-License-Identifier: Unlicense
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies if needed (e.g., ssh for remote bridging)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install the package
RUN pip install --no-cache-dir .

# Create a non-root user and switch to it
RUN useradd -m bridgeuser && chown -R bridgeuser:bridgeuser /app
USER bridgeuser

# Expose the default port
EXPOSE 8000

# Set the entrypoint to the bridge command
ENTRYPOINT ["mcp-stdio-bridge"]

# Default command (can be overridden)
CMD ["--help"]
