# Example Dockerfile demonstrating enhanced RUN instruction parsing capabilities
# This Dockerfile showcases all the shell syntax that the enhanced parser can handle

FROM ubuntu:latest

# Set build arguments
ARG PACKAGE=curl
ARG VERSION=latest

# Simple command (both versions work)
RUN echo "Starting build process"

# AND operator (both versions work)
RUN apt-get update && apt-get install -y curl

# Semicolon separator (enhanced only)
RUN apt-get update; apt-get install -y wget

# OR operator (enhanced only)
RUN apt-get update || echo "Update failed, continuing anyway"

# Complex logic with multiple separators (enhanced only)
RUN apt-get update && apt-get install -y $PACKAGE || exit 1

# Parentheses grouping (enhanced only)
RUN (apt-get update && apt-get install -y curl)

# Pipe operations (enhanced only)
RUN apt-get update | grep "packages" | wc -l

# Background execution (enhanced only)
RUN long_running_command &

# Mixed separators with variables (enhanced only)
RUN apt-get update && apt-get install -y $PACKAGE || echo "Failed to install $PACKAGE"

# JSON array format (both versions work)
RUN ["apt-get", "update"]

# Complex nested commands (enhanced only)
RUN apt-get update && (apt-get install -y curl || apt-get install -y wget) && echo "Installation complete"

# Multiple semicolons (enhanced only)
RUN apt-get update; apt-get install -y curl; apt-get clean

# Mixed operators with quotes (enhanced only)
RUN apt-get update && echo "Update completed" || echo "Update failed"

# Complex conditional logic (enhanced only)
RUN apt-get update && apt-get install -y curl || (echo "Failed to install curl" && exit 1)

# Pipeline with multiple commands (enhanced only)
RUN apt-get update | grep "packages" | wc -l

# Multiple stages with complex commands
FROM alpine:latest AS builder

# Complex build process with multiple separators
RUN apk add --no-cache build-base && \
    (make build || make build-debug) && \
    echo "Build completed"

# Final stage
FROM ubuntu:latest

# Copy from builder stage
COPY --from=builder /app /app

# Complex setup with error handling
RUN apt-get update && \
    apt-get install -y curl wget && \
    (curl --version || wget --version) && \
    echo "Setup completed successfully" || \
    (echo "Setup failed" && exit 1)

# Health check with complex command
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost/ || exit 1

# Expose ports
EXPOSE 80 443

# Set working directory
WORKDIR /app

# Complex entrypoint with fallback
ENTRYPOINT ["sh", "-c", "echo 'Starting application' && exec /app/main"] 