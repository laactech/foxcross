import os
from pathlib import Path
from typing import Any

import pytest
import requests
from slugify import slugify
from starlette.testclient import TestClient

from foxcross.enums import MediaTypes
from foxcross.exceptions import BadDataFormatError
from foxcross.serving import ModelServing, ModelServingRunner, compose

try:
    import ujson as json
except ImportError:
    import json

__location__ = Path(
    os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))
)

add_one_data_path = __location__ / "data/add_one.json"
add_five_data_path = __location__ / "data/add_five.json"

with Path(add_one_data_path).open() as f:
    add_one_data = json.load(f)

with Path(__location__ / "data/add_one_result.json").open() as f:
    add_one_result_data = json.load(f)

with Path(add_five_data_path).open() as f:
    add_five_data = json.load(f)

with Path(__location__ / "data/add_five_result.json").open() as f:
    add_five_result_data = json.load(f)


class AddOneModel(ModelServing):
    test_data_path = add_one_data_path

    def predict(self, data: Any) -> Any:
        try:
            return [x + 1 for x in data]
        except TypeError:
            raise BadDataFormatError("Must be a list")


class AddAnyModel:
    def __init__(self, add_amount):
        self._add_amount = add_amount

    def add(self, data):
        return [x + self._add_amount for x in data]


class AddFiveModel(ModelServing):
    test_data_path = add_five_data_path

    def load_model(self):
        self.model = AddAnyModel(5)

    def predict(self, data: Any) -> Any:
        return self.model.add(data)


@pytest.mark.parametrize(
    "model_serving,input_data,expected,endpoint",
    [
        (AddOneModel, add_one_data, add_one_result_data, "/predict/"),
        (AddFiveModel, add_five_data, add_five_result_data, "/predict/"),
        (AddOneModel, None, add_one_data, "/input-format/"),
        (AddFiveModel, None, add_five_data, "/input-format/"),
        (AddOneModel, add_one_data, add_one_result_data, "/predict-test/"),
        (AddFiveModel, add_five_data, add_five_result_data, "/predict-test/"),
    ],
)
def test_endpoints_single_model_serving(model_serving, input_data, expected, endpoint):
    app = model_serving(debug=True)
    client = TestClient(app)
    if endpoint == "/predict/":
        response = client.post(
            endpoint, headers={"Accept": MediaTypes.JSON.value}, json=input_data
        )
    else:
        response = client.get(endpoint, headers={"Accept": MediaTypes.JSON.value})
    assert response.status_code == 200
    assert response.json() == expected


def test_index_single_model_serving():
    app = AddOneModel(debug=True)
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


def test_predict_multi_model_serving():
    app = compose(__name__, debug=True)
    client = TestClient(app)
    add_one_response = client.post(
        f"{slugify(AddOneModel.__name__)}/predict/",
        headers={"Accept": MediaTypes.JSON.value},
        json=add_one_data,
    )
    assert add_one_response.status_code == 200
    assert add_one_response.json() == add_one_result_data

    add_five_response = client.post(
        f"{slugify(AddFiveModel.__name__)}/predict/",
        headers={"Accept": MediaTypes.JSON.value},
        json=add_five_data,
    )
    assert add_five_response.status_code == 200
    assert add_five_response.json() == add_five_result_data


def test_index_multi_model_serving():
    app = compose(__name__, debug=True)
    client = TestClient(app)
    add_one_response = client.get(f"{slugify(AddOneModel.__name__)}/")
    assert add_one_response.status_code == 200

    add_five_response = client.get(f"{slugify(AddFiveModel.__name__)}/")
    assert add_five_response.status_code == 200

    root_response = client.get("/")
    assert root_response.status_code == 200


@pytest.mark.parametrize(
    "endpoint,first_expected,second_expected",
    [
        ("/input-format/", add_one_data, add_five_data),
        ("/predict-test/", add_one_result_data, add_five_result_data),
    ],
)
def test_endpoints_multi_model_serving(endpoint, first_expected, second_expected):
    app = compose(__name__, debug=True)
    client = TestClient(app)
    add_one_response = client.get(
        f"{slugify(AddOneModel.__name__)}{endpoint}",
        headers={"Accept": MediaTypes.JSON.value},
    )
    assert add_one_response.status_code == 200
    assert add_one_response.json() == first_expected

    add_five_response = client.get(
        f"{slugify(AddFiveModel.__name__)}{endpoint}",
        headers={"Accept": MediaTypes.JSON.value},
    )
    assert add_five_response.status_code == 200
    assert add_five_response.json() == second_expected


def test_bad_data_format_error():
    app = AddOneModel(debug=True)
    client = TestClient(app)
    response = client.post("/predict/", headers={"Accept": MediaTypes.JSON.value}, json=1)
    assert response.status_code == 400
    assert response.content == b"Must be a list"


def test_single_model_compose():
    runner = ModelServingRunner(ModelServing, [ModelServing, AddFiveModel])
    app = runner.compose(__name__)
    client = TestClient(app)
    add_one_response = client.post(
        "/predict/", headers={"Accept": MediaTypes.JSON.value}, json=add_one_data
    )
    assert add_one_response.status_code == 200
    assert add_one_response.json() == add_one_result_data


def test_https_redirect():
    app = AddOneModel(redirect_https=True)
    client = TestClient(app)
    add_one_response = client.get("/", allow_redirects=False)
    assert add_one_response.status_code == 301


def test_predict_head_request():
    app = AddOneModel(debug=True)
    client = TestClient(app)
    response = client.head("/predict/")
    assert response.status_code == 200


@pytest.mark.parametrize("endpoint", ["/predict/", "/predict-test/", "/input-format/"])
def test_missing_accept_header(endpoint):
    app = AddOneModel(debug=True)
    client = TestClient(app)
    if endpoint == "/predict/":
        http_method = "POST"
    else:
        http_method = "GET"
    req = requests.Request(http_method, f"{client.base_url}{endpoint}", json=1)
    prepped_req = req.prepare()
    try:
        prepped_req.headers.pop("Accept")
    except KeyError:
        pass
    response = client.send(prepped_req)
    assert response.status_code == 400


def test_missing_content_type_header():
    app = AddOneModel(debug=True)
    client = TestClient(app)
    req = requests.Request("POST", f"{client.base_url}/predict/", json=1)
    prepped_req = req.prepare()
    try:
        prepped_req.headers.pop("Content-Type")
    except KeyError:
        pass
    response = client.send(prepped_req)
    assert response.status_code == 400


def test_wrong_content_type_header():
    app = AddOneModel(debug=True)
    client = TestClient(app)
    response = client.post(
        "/predict/",
        headers={"Accept": MediaTypes.JSON.value, "Content-Type": "text/html"},
    )
    assert response.status_code == 415


@pytest.mark.parametrize("endpoint", ["/predict/", "/predict-test/", "/input-format/"])
def test_wrong_accept_header(endpoint):
    app = AddOneModel(debug=True)
    client = TestClient(app)
    if endpoint == "/predict/":
        response = client.post(
            endpoint,
            headers={"Accept": "text/html", "Content-Type": MediaTypes.JSON.value},
        )
    else:
        response = client.get(endpoint, headers={"Accept": "text/html"})
    assert response.status_code == 406
