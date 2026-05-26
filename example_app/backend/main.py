from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(
    title="Anti Gravity Demo Backend API",
    description="A micro-backend for continuous deployment verification.",
    version="1.0.0"
)

# Allow CORS requests so the React frontend can fetch from here
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "service": "Anti Gravity Demo Backend",
        "version": "1.0.0",
        "endpoints": ["/api/message"]
    }

@app.get("/api/message")
def get_message():
    return {
        "success": True,
        "message": "Hello from the Anti Gravity micro-backend! CORS is active and working. 🚀"
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
