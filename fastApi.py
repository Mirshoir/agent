from fastapi import FastAPI, Request

app = FastAPI()

VERIFY_TOKEN = "my_verify_token"

@app.get("/webhook")
async def verify(request: Request):
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(params.get("hub.challenge"))
    return {"error": "Verification failed"}

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("Received:", data)
    return {"status": "ok"}