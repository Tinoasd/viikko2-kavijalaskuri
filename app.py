"""A persistent page-view counter behind Nginx at /viikko2/."""

import os
from pathlib import Path

import pymysql
from flask import Flask, make_response, render_template, request

app = Flask(__name__, static_url_path="/viikko2/static")


@app.get("/viikko2/")
def index():
    # A new connection for each request keeps transactions separate between
    # Gunicorn workers. UPDATE locks this row until commit(), so simultaneous
    # requests cannot overwrite each other's increments.
    with pymysql.connect(
        host="127.0.0.1",
        user=os.environ.get("DB_USER", "pythonapp"),
        password=os.environ["DB_PASSWORD"],
        database="pythonapp",
        charset="utf8mb4",
        connect_timeout=5,
        autocommit=False,
    ) as connection:
        with connection.cursor() as cursor:
            # Flask also accepts HEAD requests on GET routes. HEAD checks,
            # static images and CSS do not increase the page-view counter.
            if request.method == "GET":
                cursor.execute(
                    "UPDATE page_counter SET visits = visits + 1 WHERE id = 1"
                )

            cursor.execute(
                "SELECT visits, app_restart_result, server_restart_result "
                "FROM page_counter WHERE id = 1"
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Counter row missing. Run schema.sql first.")
            visits, app_restart_result, server_restart_result = row

        connection.commit()

    static_dir = Path(app.static_folder)
    background = "tausta.jpg" if (static_dir / "tausta.jpg").is_file() else "tausta.svg"
    response = make_response(
        render_template(
            "index.html",
            visits=visits,
            app_restart_result=app_restart_result,
            server_restart_result=server_restart_result,
            background=background,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    return response
