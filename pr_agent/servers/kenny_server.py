# KENNY
"""Single FastAPI app serving both the stock GitHub webhook routes and the Kenny JSON API.

Run:  gunicorn -k uvicorn.workers.UvicornWorker --timeout 300 -w 2 pr_agent.servers.kenny_server:app
Dev:  python -m pr_agent.servers.kenny_server
"""

import os

import uvicorn
from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette_context.middleware import RawContextMiddleware

from pr_agent.servers.github_app import router as github_router
from pr_agent.servers.kenny_api import router as kenny_router

middleware = [Middleware(RawContextMiddleware)]
app = FastAPI(middleware=middleware)
app.include_router(github_router)
app.include_router(kenny_router)


def start():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "3000")))


if __name__ == "__main__":
    start()
