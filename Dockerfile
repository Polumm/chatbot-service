# Use a lightweight Python image
FROM python:3.9

# Set working directory
WORKDIR /app

# Copy files
COPY . /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port for Client API
EXPOSE 6002

# Run the client application
CMD ["python", "app.py"]