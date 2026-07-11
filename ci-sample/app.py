from fastapi import FastAPI

app = FastAPI(title="food-budget ci-sample")


@app.get("/health")
def health():
    return {"status": "ok"}
