# Gebruik een efficiënte Python base image
FROM python:3.12-slim

# Stel de werkdirectory in de container in
WORKDIR /app

# Kopieer de applicatiecode
COPY app.py .

# Installeer de dependencies met uv
RUN pip install uv
RUN uv pip install --system waitress flask

# Expose de poort die de listener gebruikt
EXPOSE 8081

# Het commando om de applicatie te starten
CMD ["python3", "app.py"]