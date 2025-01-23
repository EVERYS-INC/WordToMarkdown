FROM mcr.microsoft.com/azure-functions/python:4-python3.9

ENV AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    AzureWebJobsScriptRoot=/home/site/wwwroot

COPY requirements.txt /

# Install pandoc latest version
RUN apt-get update && \
    apt-get install -y wget && \
    wget https://github.com/jgm/pandoc/releases/download/3.1.11.1/pandoc-3.1.11.1-1-amd64.deb && \
    dpkg -i pandoc-3.1.11.1-1-amd64.deb && \
    rm pandoc-3.1.11.1-1-amd64.deb && \
    apt-get clean && \
    pip install --no-cache-dir -r /requirements.txt

COPY . /home/site/wwwroot