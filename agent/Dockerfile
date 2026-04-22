FROM python:3.11-slim

WORKDIR /opt/aibot-agent

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python3", "agent.py"]
