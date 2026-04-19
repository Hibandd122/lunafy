from fastapi import FastAPI
from api.check import check_and_renew

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Lunafy Renew API is running. Use /check to trigger."}

@app.get("/check")
def run_check():
    result = check_and_renew()
    return result
