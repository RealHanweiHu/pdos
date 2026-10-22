from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from pdos_next.api import create_app
from pdos_next.error_catalog import CATEGORIES


def test_actual_host_routing_validation_and_unexpected_failures_share_public_contract():
    engine = create_engine("postgresql+psycopg://offline@127.0.0.1:1/pdos_schema_export")

    @event.listens_for(engine, "do_connect")
    def forbid_connection(*_args):
        raise AssertionError("Routing and schema checks must not connect to a database")

    app = create_app(engine, engine)

    @app.get("/synthetic-failure")
    def failure():
        raise RuntimeError("Synthetic confidential diagnostic must stay outside the response")

    client = TestClient(app, raise_server_exceptions=False)
    try:
        for response, status, code in (
            (client.get("/unknown-route"), 404, "NOT_FOUND"),
            (client.post("/synthetic-failure"), 405, "VALIDATION_FAILED"),
            (client.get("/synthetic-failure"), 500, "INTERNAL_ERROR"),
        ):
            assert response.status_code == status
            assert response.json()["code"] == code
            assert response.json()["detail"]["reason"]
            assert "confidential" not in response.text
        schema = client.get("/openapi.json").json()
        assert (
            set(schema["components"]["schemas"]["PDOSFailure"]["properties"]["code"]["enum"])
            == CATEGORIES
        )
        assert schema["paths"]["/v1/categories/{category_id}/commands"]["post"]["responses"]["422"][
            "content"
        ]["application/json"]["schema"] == {"$ref": "#/components/schemas/PDOSFailure"}
    finally:
        client.close()
        engine.dispose()
