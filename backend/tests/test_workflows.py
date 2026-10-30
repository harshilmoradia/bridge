async def test_inngest_endpoint_lists_functions(client):
    response = await client.get("/api/inngest")
    assert response.status_code == 200
    body = response.json()
    assert body["function_count"] == 3  # reconcile-run, item-decided, and the bounded RAG indexer
    assert body["mode"] == "dev"
