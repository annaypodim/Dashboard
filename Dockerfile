FROM python:3.11-slim
RUN pip install -r requirements.txt 
RUN streamlit run dashboard.py
WORKDIR /app