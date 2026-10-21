FROM python:3.12-slim
WORKDIR /app
COPY report.py example.json ./
ENTRYPOINT ["python", "report.py"]
CMD ["--input", "example.json", "--output", "/tmp/report.md"]
