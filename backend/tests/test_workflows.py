async def test_inngest_endpoint_lists_functions(client):
    response = await client.get("/api/inngest")
    assert response.status_code == 200
    body = response.json()
    assert body["function_count"] == 2  # reconcile-run and item-decided; the day-1 smoke spike is gone
    assert body["mode"] == "dev"
