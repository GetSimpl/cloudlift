FROM python:3.7.7-slim
RUN apt-get update && apt-get install make git docker.io -y
WORKDIR /cloudlift-bin
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY .  .
RUN pip install -e .
WORKDIR /workspace
ENTRYPOINT ["cloudlift"]