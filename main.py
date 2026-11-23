import time
import asyncio

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from tools.logging_util import setup_logger
from tools.google_translate import GoogleTranslateClient
from config import DEBUG, APP_MAIN_PORT, BASE_DATA_PATH

operation_logger = setup_logger('operation', path=f"{BASE_DATA_PATH}/logs")
classification_logger = setup_logger('classification', path=f"{BASE_DATA_PATH}/logs")

# Cap concurrent Google requests per worker.
RATE_SEMAPHORE = asyncio.Semaphore(10)

# One shared async HTTP client. Raises on failure instead of echoing the input.
translator = GoogleTranslateClient(logger=operation_logger)


async def translate_one(text, dest):
    async with RATE_SEMAPHORE:
        return (await translator.translate(str(text), dest=dest)).text


async def detect_one(text):
    async with RATE_SEMAPHORE:
        return await translator.detect(str(text))


# CREATING A INSTANCE FOR MAIN APP
app = FastAPI()
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _close_translator():
    await translator.aclose()


print(""" -----------------------------------------------------
 ------------- Application ready to USE --------------
 ----------------------------------------------------- """)


# TEST GET METHOD
@app.get("/", tags=["Test"])
def test():
    results = ["App is ready to use"]
    return {"status": "successful", "result": results}


# TEST POST METHOD
@app.post("/test", tags=["Test"])
def test_post():
    results = ["App is ready to use"]
    return {"status": "successful", "result": results}


def _error_response(e):
    operation_logger.exception(f"{__name__}: request failed: {e}")
    return JSONResponse(content={"status": "error", "error": [str(e)]})


def _success_response(texts, results, start_time):
    final_result = {
        "status": "successful",
        "results": [
            {"index": i, "text": str(text), "result": result}
            for i, (text, result) in enumerate(zip(texts, results))
        ],
        "time_ms": int((time.time() - start_time) * 1000),
    }
    if not DEBUG:
        classification_logger.warning(final_result)
    return JSONResponse(content=final_result)


@app.post("/translator")
async def api_endpoint(req: Request):
    try:
        data = await req.json()
        start_time = time.time()
        lang = data.get("lang", "en") or "en"
        texts = data['text']

        results = await asyncio.gather(*(translate_one(text, lang) for text in texts))
    except Exception as e:
        return _error_response(e)

    return _success_response(texts, results, start_time)


@app.post("/detect")
async def api_endpoint_detect(req: Request):
    try:
        data = await req.json()
        start_time = time.time()
        texts = data['text']

        results = await asyncio.gather(*(detect_one(text) for text in texts))
    except Exception as e:
        return _error_response(e)

    return _success_response(texts, results, start_time)


if __name__ == '__main__':
    uvicorn.run("main:app", host="0.0.0.0", port=APP_MAIN_PORT, log_level="info", reload=True)