# Headless test bed for a1b: no display, like the real backend container.
# docker build -t amazon-spike spikes/amazon
# docker run --rm -it -v "$PWD/spikes/amazon/out:/app/out" amazon-spike --domain amazon.de
FROM mcr.microsoft.com/playwright/python:v1.64.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY a1_browser_login.py a1b_headless_login.py ./
ENTRYPOINT ["python", "a1b_headless_login.py"]
