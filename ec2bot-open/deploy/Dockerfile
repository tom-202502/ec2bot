FROM python:3.11-slim

LABEL maintainer="ec2bot"
LABEL description="EC2Bot - Telegram AWS Server Management Bot"

WORKDIR /opt/ec2bot

# Install dependencies
COPY app/requirements.txt app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt

# Copy application code
COPY app/ app/

# Create runtime directories
RUN mkdir -p logs run

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV EC2BOT_CONFIG=/opt/ec2bot/config/config.yaml
ENV EC2BOT_ENV=/opt/ec2bot/config/.env

# Run
WORKDIR /opt/ec2bot/app
CMD ["python3", "ec2_bot.py"]
