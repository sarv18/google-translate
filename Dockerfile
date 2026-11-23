FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Install basic requirements
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /home/code

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make the entrypoint script executable
RUN chmod 755 /home/code/auto_run.sh

# Set the entrypoint
ENTRYPOINT ["/home/code/auto_run.sh"]