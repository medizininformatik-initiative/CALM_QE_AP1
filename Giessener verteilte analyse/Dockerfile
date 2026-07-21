# Use official Python image
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Default command: First download, then analyze
CMD ["sh", "-c", "python download_fhir_distributed.py && python analyze_fhir_distributed.py"]
